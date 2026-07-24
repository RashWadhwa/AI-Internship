"""Week 1 v2 demo API: one compact `/ask` endpoint for the intro class.

Run:
  uvicorn main:app --host 127.0.0.1 --port 8000 --reload
"""

import time
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse
from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

THIS_DIR = Path(__file__).resolve().parent
load_dotenv(THIS_DIR / ".env")
load_dotenv(THIS_DIR.parent / ".env")
load_dotenv(THIS_DIR.parent.parent / ".env")

from vectorstore import (  # noqa: E402
    EMBEDDING_MODEL,
    chunk_text,
    pinecone_health,
    query_similar,
    upsert_documents,
)

app = FastAPI(title="Week 1 v2 /ask Demo")
_client: OpenAI | None = None

ModelName = Literal["gpt-4o-mini", "gpt-4o", "o3-mini"]
DEFAULT_MODEL: ModelName = "gpt-4o-mini"
MODEL_PRICES_PER_1K: dict[str, tuple[float, float]] = {
    "gpt-4o": (0.0025, 0.01),
    "gpt-4o-mini": (0.00015, 0.0006),
    "o3-mini": (0.0011, 0.0044),
}

RAG_TOP_K = 5

GROUNDING_PROMPT_TEMPLATE = """Answer using ONLY the context below.
If the context does not contain the answer, say:
"I don't have enough information to answer that."
Cite the document_id of each chunk you used.

Context:
{context}

Question: {question}"""


class Answer(BaseModel):
    """The model output shape we want every caller to receive."""

    answer: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    sources_needed: bool


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    model: ModelName | None = None
    force_bad: bool = False


class AttemptResult(BaseModel):
    attempt: int
    step: str
    ok: bool
    message: str
    raw_output: str | None = None
    validation_error: str | None = None


class AskResponse(BaseModel):
    answer: Answer
    tokens_used: int
    model: str
    latency_ms: int
    cost_usd: float
    attempts: list[AttemptResult]
    retrieved_chunk_ids: list[str]


class IngestRequest(BaseModel):
    document_id: str = Field(min_length=1)
    text: str
    source: str | None = None


class IngestResponse(BaseModel):
    document_id: str
    chunks_indexed: int
    status: str


class RetrievedChunk(BaseModel):
    chunk_id: str
    score: float
    document_id: str | None = None
    chunk_index: int | None = None
    source: str | None = None
    text: str | None = None


class DebugRetrieveResponse(BaseModel):
    query: str
    embedding_model: str
    results: list[RetrievedChunk]


def to_retrieved_chunks(matches: list[dict]) -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            chunk_id=match["id"],
            score=match["score"],
            document_id=(match["metadata"] or {}).get("document_id"),
            chunk_index=(match["metadata"] or {}).get("chunk_index"),
            source=(match["metadata"] or {}).get("source"),
            text=(match["metadata"] or {}).get("text"),
        )
        for match in matches
    ]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/debug/pinecone")
def debug_pinecone() -> dict:
    try:
        return pinecone_health()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Pinecone unreachable: {exc}")


# curl -s "http://127.0.0.1:8000/debug/retrieve?q=What+does+the+handbook+say+about+PTO"
@app.get("/debug/retrieve")
def debug_retrieve(
    q: str = Query(min_length=1), top_k: int = Query(5, ge=1, le=20)
) -> DebugRetrieveResponse:
    """Embeddings + vector search only — no LLM call. Use to sanity-check retrieval."""
    try:
        matches = query_similar(q, top_k=top_k)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Vector store query failed: {exc}")

    results = to_retrieved_chunks(matches)
    return DebugRetrieveResponse(query=q, embedding_model=EMBEDDING_MODEL, results=results)


@app.get("/", include_in_schema=False)
def root_redirect():
    """Redirect the site root to the interactive docs for convenience."""
    return RedirectResponse(url="/docs")


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


def compute_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    input_per_1k, output_per_1k = MODEL_PRICES_PER_1K.get(
        model, MODEL_PRICES_PER_1K[DEFAULT_MODEL]
    )
    return (prompt_tokens / 1000 * input_per_1k) + (
        completion_tokens / 1000 * output_per_1k
    )


def usage_counts(completion) -> tuple[int, int, int]:
    usage = completion.usage
    if usage is None:
        return 0, 0, 0
    return usage.total_tokens, usage.prompt_tokens, usage.completion_tokens


def format_retrieved_context(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return "(no relevant context was retrieved)"
    return "\n\n".join(
        f"[{chunk.document_id}] (chunk {chunk.chunk_index}): {chunk.text}" for chunk in chunks
    )


def build_grounding_prompt(question: str, chunks: list[RetrievedChunk]) -> str:
    return GROUNDING_PROMPT_TEMPLATE.format(
        context=format_retrieved_context(chunks), question=question
    )


def call_structured_model(question: str, model: ModelName) -> tuple[Answer, int, int, int]:
    completion = get_client().chat.completions.parse(
        model=model,
        messages=[{"role": "user", "content": question}],
        response_format=Answer,
    )

    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise ValueError("Model returned no parseable structured output")

    total_tokens, prompt_tokens, completion_tokens = usage_counts(completion)
    return parsed, total_tokens, prompt_tokens, completion_tokens


def call_malformed_json_once(question: str, model: ModelName) -> tuple[str, int, int, int]:
    """Demo-only path: force one malformed response so students can see retry."""

    completion = get_client().chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": (
                    f"{question}\n\n"
                    "Reply with ONLY JSON using keys answer, confidence, sources_needed. "
                    "Set confidence to the string 'very high' instead of a number."
                ),
            }
        ],
    )

    raw = completion.choices[0].message.content or ""
    total_tokens, prompt_tokens, completion_tokens = usage_counts(completion)
    return raw, total_tokens, prompt_tokens, completion_tokens


# curl -s -X POST http://127.0.0.1:8000/ingest \
#   -H "Content-Type: application/json" \
#   -d '{"document_id": "handbook-1", "text": "Long document text...", "source": "handbook.pdf"}'
@app.post("/ingest")
def ingest(body: IngestRequest) -> IngestResponse:
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text must not be empty")

    chunks = chunk_text(text)
    if not chunks:
        raise HTTPException(status_code=400, detail="text produced no chunks after splitting")

    ids = [f"{body.document_id}-{i}" for i in range(len(chunks))]
    metadatas = [
        {"document_id": body.document_id, "chunk_index": i, "source": body.source or ""}
        for i in range(len(chunks))
    ]

    try:
        chunks_indexed = upsert_documents(ids, chunks, metadatas)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Vector store upsert failed: {exc}")

    return IngestResponse(
        document_id=body.document_id, chunks_indexed=chunks_indexed, status="indexed"
    )


@app.post("/ask")
def ask(body: AskRequest) -> AskResponse:
    model = body.model or DEFAULT_MODEL
    start = time.perf_counter()

    try:
        matches = query_similar(body.question, top_k=RAG_TOP_K)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Retrieval failed: {exc}")

    retrieved_chunks = to_retrieved_chunks(matches)
    prompt = build_grounding_prompt(body.question, retrieved_chunks)

    last_error: str | None = None
    attempts: list[AttemptResult] = []
    total_tokens_used = 0
    total_prompt_tokens = 0
    total_completion_tokens = 0

    for attempt in range(2):
        try:
            if body.force_bad and attempt == 0:
                raw, tokens_used, prompt_tokens, completion_tokens = call_malformed_json_once(
                    prompt, model
                )
                total_tokens_used += tokens_used
                total_prompt_tokens += prompt_tokens
                total_completion_tokens += completion_tokens

                try:
                    answer = Answer.model_validate_json(raw)
                except ValidationError as exc:
                    last_error = str(exc)
                    attempts.append(
                        AttemptResult(
                            attempt=attempt + 1,
                            step="forced_bad_json",
                            ok=False,
                            message="Validation failed, so the endpoint retries with structured output.",
                            raw_output=raw,
                            validation_error=str(exc),
                        )
                    )
                    continue

                attempts.append(
                    AttemptResult(
                        attempt=attempt + 1,
                        step="forced_bad_json",
                        ok=True,
                        message="Unexpectedly passed validation.",
                        raw_output=raw,
                    )
                )
            else:
                answer, tokens_used, prompt_tokens, completion_tokens = call_structured_model(
                    prompt, model
                )
                total_tokens_used += tokens_used
                total_prompt_tokens += prompt_tokens
                total_completion_tokens += completion_tokens
                attempts.append(
                    AttemptResult(
                        attempt=attempt + 1,
                        step="structured_output",
                        ok=True,
                        message="Structured output matched the Answer schema.",
                    )
                )

            latency_ms = int((time.perf_counter() - start) * 1000)
            cost_usd = compute_cost_usd(
                model, total_prompt_tokens, total_completion_tokens
            )
            return AskResponse(
                answer=answer,
                tokens_used=total_tokens_used,
                model=model,
                latency_ms=latency_ms,
                cost_usd=round(cost_usd, 6),
                attempts=attempts,
                retrieved_chunk_ids=[chunk.chunk_id for chunk in retrieved_chunks],
            )
        except (ValidationError, ValueError) as exc:
            last_error = str(exc)
            attempts.append(
                AttemptResult(
                    attempt=attempt + 1,
                    step="structured_output",
                    ok=False,
                    message="Structured output failed validation.",
                    validation_error=str(exc),
                )
            )

    raise HTTPException(
        status_code=502,
        detail=f"Model response failed schema validation after retry: {last_error}",
    )
