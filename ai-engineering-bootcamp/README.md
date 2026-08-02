# AI Engineering Bootcamp

Hands-on experience for building production-style LLM APIs with **FastAPI**, **OpenAI**, **Pydantic**, and **Streamlit** — plus, from Session 3 on, multi-agent systems with **Google ADK**.

## Weeks

| Week | Topic | Location |
|------|-------|----------|
| 1 | `/ask` endpoint — typed I/O, structured output, guardrails, model selection, cost; extended in Session 2 with Pinecone-backed RAG (`/ingest`, Northwind health-benefits corpus) | [`week-1/`](week-1/) |
| 2 | RAG and vector databases (standalone reference notebook — LangChain + Chroma) | [`week-2/`](week-2/) |
| 3 | ADK multi-agent systems — routing, MCP, A2A demos (standalone, own deps, Gemini instead of OpenAI) | [`adk-multi-agent-systems/`](adk-multi-agent-systems/) |

## Tech stack

- **FastAPI** — HTTP API with automatic OpenAPI docs
- **OpenAI Python SDK** — chat completions and structured output (`response_format`)
- **Pydantic** — request/response schemas and validation guardrails
- **python-dotenv** — load `OPENAI_API_KEY` from `.env`
- **Streamlit** — interactive demo runner (`demo_page.py`)
- **httpx** — HTTP client for tests and the Streamlit UI
- **Pinecone** — vector store for `week-1/`'s RAG extension
- **Google ADK / Gemini** — multi-agent routing, MCP, and A2A demos in `adk-multi-agent-systems/` (separate dependency set from the rest of the repo)

## Quick start

```
cd week-1
cp .env.example .env          # add your OPENAI_API_KEY
python -m venv .venv
.venv/scripts/activate.ps1
pip install -r requirements.txt
```

See [week-1/README.md](week-1/README.md) for usage instructions, or
[adk-multi-agent-systems/README.md](adk-multi-agent-systems/README.md) for the
Session 3 ADK demos (separate setup — needs its own venv and `GOOGLE_API_KEY`).
