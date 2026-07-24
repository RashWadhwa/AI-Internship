"""Pinecone vector store integration: config, embeddings, and index helpers.

Ingest and query must share the same embedding model so vectors stay comparable.
"""

import os

from langchain_text_splitters import RecursiveCharacterTextSplitter
from openai import OpenAI
from pinecone import Pinecone, ServerlessSpec

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIMENSION = 1536  # text-embedding-3-small's default output size

PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "ai-internship-rag")
PINECONE_CLOUD = os.getenv("PINECONE_CLOUD", "aws")
PINECONE_REGION = os.getenv("PINECONE_REGION", "us-east-1")

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "800"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "100"))

_pinecone_client: Pinecone | None = None
_openai_client: OpenAI | None = None


def get_pinecone_client() -> Pinecone:
    global _pinecone_client
    if _pinecone_client is None:
        _pinecone_client = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    return _pinecone_client


def get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI()
    return _openai_client


def get_index():
    pc = get_pinecone_client()
    if PINECONE_INDEX_NAME not in pc.list_indexes().names():
        pc.create_index(
            name=PINECONE_INDEX_NAME,
            dimension=EMBEDDING_DIMENSION,
            metric="cosine",
            spec=ServerlessSpec(cloud=PINECONE_CLOUD, region=PINECONE_REGION),
        )
    return pc.Index(PINECONE_INDEX_NAME)


def chunk_text(text: str) -> list[str]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    )
    return splitter.split_text(text)


def embed_texts(texts: list[str]) -> list[list[float]]:
    response = get_openai_client().embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in response.data]


UPSERT_BATCH_SIZE = 100  # keeps each Pinecone upsert request comfortably under its 2MB limit


def upsert_documents(
    ids: list[str], texts: list[str], metadatas: list[dict] | None = None
) -> int:
    metadatas = metadatas or [{} for _ in texts]
    index = get_index()
    indexed = 0

    for start in range(0, len(texts), UPSERT_BATCH_SIZE):
        batch_ids = ids[start : start + UPSERT_BATCH_SIZE]
        batch_texts = texts[start : start + UPSERT_BATCH_SIZE]
        batch_metadatas = metadatas[start : start + UPSERT_BATCH_SIZE]

        batch_vectors = embed_texts(batch_texts)
        records = [
            {"id": id_, "values": vector, "metadata": {**meta, "text": text}}
            for id_, vector, text, meta in zip(
                batch_ids, batch_vectors, batch_texts, batch_metadatas
            )
        ]
        index.upsert(vectors=records)
        indexed += len(records)

    return indexed


def query_similar(query_text: str, top_k: int = 5) -> list[dict]:
    query_vector = embed_texts([query_text])[0]
    result = get_index().query(vector=query_vector, top_k=top_k, include_metadata=True)
    return [
        {"id": match.id, "score": match.score, "metadata": match.metadata}
        for match in result.matches
    ]


def pinecone_health() -> dict:
    """Confirm Pinecone is reachable and report the target index's status."""
    pc = get_pinecone_client()
    index_names = list(pc.list_indexes().names())
    target_exists = PINECONE_INDEX_NAME in index_names

    status = {
        "reachable": True,
        "embedding_model": EMBEDDING_MODEL,
        "indexes": index_names,
        "target_index": PINECONE_INDEX_NAME,
        "target_index_exists": target_exists,
    }

    if target_exists:
        stats = pc.Index(PINECONE_INDEX_NAME).describe_index_stats()
        status["vector_count"] = stats.total_vector_count
        status["dimension"] = stats.dimension

    return status
