"""Ingest the Northwind sample PDFs into the vector store via POST /ingest.

Requires the API to be running locally first:
  uvicorn main:app --host 127.0.0.1 --port 8000 --reload

Then:
  python ingest_northwind.py
"""

import re
import sys
from pathlib import Path

import httpx
from pypdf import PdfReader

THIS_DIR = Path(__file__).resolve().parent
DATA_DIR = THIS_DIR / "data" / "northwind"
BASE_URL = "http://127.0.0.1:8000"


def stable_document_id(pdf_path: Path) -> str:
    return re.sub(r"[^a-z0-9]+", "-", pdf_path.stem.lower()).strip("-")


def extract_text(pdf_path: Path) -> str:
    reader = PdfReader(pdf_path)
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)


def main() -> None:
    pdf_paths = sorted(DATA_DIR.glob("*.pdf"))
    if not pdf_paths:
        sys.exit(f"No PDFs found in {DATA_DIR}")

    with httpx.Client(timeout=120.0) as client:
        for pdf_path in pdf_paths:
            document_id = stable_document_id(pdf_path)
            text = extract_text(pdf_path)

            response = client.post(
                f"{BASE_URL}/ingest",
                json={"document_id": document_id, "text": text, "source": pdf_path.name},
            )
            response.raise_for_status()
            result = response.json()

            print(
                f"{pdf_path.name} -> document_id={document_id}, "
                f"chunks_indexed={result['chunks_indexed']}"
            )

        health = client.get(f"{BASE_URL}/debug/pinecone").json()
        print(f"\nTotal chunks in vector store: {health.get('vector_count')}")


if __name__ == "__main__":
    main()
