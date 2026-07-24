# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

AI Engineering bootcamp coursework, organized by week. The only actively
deployed/runnable code is in `ai-engineering-bootcamp-v2/week-1v2/` — a
FastAPI service (Session 1: typed `/ask`, extended in Session 2 with
Pinecone-backed RAG) plus two Streamlit UIs.
`ai-engineering-bootcamp-v2/week-2/rag-vector-databases/` is a separate,
standalone Jupyter notebook (LangChain + Chroma reference material) — not
wired into the deployed app.

## Commands

All commands run from `ai-engineering-bootcamp-v2/week-1v2/`, using the venv
at the repo root (`.venv`).

Setup:
```powershell
pip install -r requirements.txt
```

Run the API:
```bash
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Run either Streamlit UI (each reads the API URL from a sidebar "API base
URL" field / `API_BASE_URL` env var, defaulting to `http://127.0.0.1:8000`):
```bash
streamlit run demo_page.py       # Session 1 /ask demo (model picker, force_bad guardrail toggle)
streamlit run rag_demo_page.py   # Session 2 RAG demo (/ingest + /ask tabs, citations/refusal display)
```

No-token startup smoke test (starts the API on a free port, checks
`/health` + `/docs`, does not call OpenAI):
```bash
python smoke_test.py
```

Ingest the Northwind sample PDFs (requires the API running locally first):
```bash
python ingest_northwind.py
```

Run the RAG eval — 5 known-answer questions against `/ask`, tracking
retrieval hit / correctness / faithfulness (LLM-judged); writes
`eval_results.json`:
```bash
python eval_northwind.py
```

There is no lint config, formatter config, or test framework (pytest etc.)
in this repo. `smoke_test.py` and `eval_northwind.py` are the closest things
to a test suite, and both make real, metered API calls.

## Architecture

**`main.py`** is the single FastAPI app actually deployed (`render.yaml`
points `uvicorn` at it). Routes:
- `POST /ask` — RAG-augmented: embeds the question, retrieves the top
  `RAG_TOP_K` (5) chunks via `vectorstore.query_similar`, builds a grounding
  prompt (`GROUNDING_PROMPT_TEMPLATE`) instructing the model to answer only
  from context and cite `document_id`s, then calls the *same*
  structured-output generation path from Session 1
  (`call_structured_model`, using `client.chat.completions.parse` against
  the `Answer` Pydantic schema). Returns `retrieved_chunk_ids` alongside the
  usual `tokens_used`/`cost_usd`/`latency_ms`. When retrieval turns up
  nothing relevant, the prompt drives the model to refuse explicitly —
  `sources_needed` on the response is the structured signal for "refused";
  don't rely on string-matching the answer text for that.
- `POST /ingest` — chunks text (`vectorstore.chunk_text`,
  `RecursiveCharacterTextSplitter`), embeds and upserts to Pinecone
  (`vectorstore.upsert_documents`). Chunk IDs are
  `f"{document_id}-{chunk_index}"`; metadata carries
  `document_id`/`chunk_index`/`source` plus the raw chunk text, so retrieval
  can return snippets without a second lookup.
- `GET /debug/pinecone`, `GET /debug/retrieve?q=...` — introspection
  endpoints that do embedding + vector search only, no LLM call. Use these
  to isolate retrieval quality from generation quality when debugging.
- `force_bad` on `/ask` triggers a demo-only path
  (`call_malformed_json_once`) that intentionally requests malformed JSON to
  demonstrate the validate-then-retry guardrail from Session 1; it still
  runs through the same grounding prompt as the normal path.

**`vectorstore.py`** is the only module that talks to Pinecone/OpenAI
embeddings — all RAG config (index name, cloud/region, embedding model,
chunk size/overlap) comes from env vars with defaults, so this is the place
to change RAG behavior. `upsert_documents` batches in groups of
`UPSERT_BATCH_SIZE` (100) specifically because Pinecone rejects upsert
requests over 2MB — a single real document's chunk set can exceed that in
one unbatched call. Both `get_pinecone_client`/`get_openai_client` here and
`main.py`'s `get_client()` `.strip()` their API keys before use — a
trailing newline from a pasted Render env var previously broke the Pinecone
HTTP client outright.

**Error handling pattern**: every endpoint that can hit Pinecone/OpenAI
(`/ingest`, `/ask`, `/debug/*`) catches broad exceptions, logs the real
exception server-side via `logger.exception(...)`, and returns a *generic*
`HTTPException` detail to the caller — never the raw exception text. This is
deliberate: a raw exception once leaked a live API key through a public
error response. Keep this pattern when adding endpoints that touch external
services.

**`.env` loading**: `main.py` calls `load_dotenv` three times, walking up
from `THIS_DIR` (`week-1v2/`) through `.parent` and `.parent.parent` — the
repo-root `.env` is what actually supplies `OPENAI_API_KEY`/
`PINECONE_API_KEY` locally. `stages/*.py` only walk up two levels, so they
don't see the repo-root `.env`.

**Deployment**: `render.yaml` (repo root) defines two separate Render
services from the same `week-1v2` root directory, both deploying from
`main` only — `ai-engineering-api` (the FastAPI backend) and
`ai-engineering-streamlit` (runs `demo_page.py` via `start_streamlit.sh`;
`rag_demo_page.py` isn't wired into any start command yet, so it currently
only runs locally). These produce two different live URLs that are easy to
confuse — see the table in the repo-root `README.md` before assuming which
one a request hit. Non-secret env vars (`PINECONE_INDEX_NAME`,
`PINECONE_CLOUD`, `PINECONE_REGION`, `EMBEDDING_MODEL`) are set directly in
`render.yaml`; secrets (`OPENAI_API_KEY`, `PINECONE_API_KEY`) are declared
with `sync: false` and must be pasted into the Render dashboard manually —
pushing a blueprint change that touches `envVars` for the first time can
require re-entering them even if they were set before.

**`data/northwind/`** holds two real PDFs (Northwind Health Plus/Standard
benefits docs) pulled from Microsoft's `azure-search-openai-demo` reference
repo, used as the sample RAG corpus. Note: the source PDFs themselves
contain internally inconsistent figures in places (e.g. the Standard plan's
out-of-pocket max is stated as both $6,000 and $6,350/$12,700 in different
sections) — this is a property of the sample data, not a retrieval bug, and
`eval_northwind.py`'s known-answer set accounts for it.
