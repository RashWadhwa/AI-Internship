---
name: run
description: Launch and drive the week-1v2 FastAPI service and its Streamlit UIs (demo_page.py, rag_demo_page.py) for this repo. Use when asked to run, start, test, or screenshot the /ask or /ingest API, or either Streamlit page.
---

# Running this app

`ai-engineering-bootcamp-v2/week-1v2/` has two kinds of runnable pieces: a
FastAPI server and two Streamlit pages that call it. Nothing else in this
repo is runnable this way (week-2 is a notebook).

## Python environment

Use the project venv, not system Python:
```
C:\Users\rashp\RashWadhwa\AI-Internship\.venv\Scripts\python.exe
```

## FastAPI server

```bash
cd ai-engineering-bootcamp-v2/week-1v2
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```
Smoke-test: `curl -s http://127.0.0.1:8000/health` → `{"status":"ok"}`.
Key routes: `POST /ask`, `POST /ingest`, `GET /debug/pinecone`, `GET /debug/retrieve?q=...`.
Needs `OPENAI_API_KEY` and `PINECONE_API_KEY` set — `main.py` loads `.env`
from three directory levels up (`THIS_DIR`, `.parent`, `.parent.parent`), so
the repo-root `.env` is the one that actually gets picked up locally.

Stop: kill the uvicorn process directly (e.g. the PID from
`Start-Process -PassThru`, or `Stop-Process`) — there's no separate wrapper
process to worry about.

## Streamlit UIs

Two pages in the same folder:
- `demo_page.py` — Session 1 `/ask` demo (model picker, `force_bad` guardrail toggle)
- `rag_demo_page.py` — RAG demo: **Ingest** tab (`POST /ingest`) + **Ask** tab
  (`POST /ask`, shows a green "answered" or yellow "refused" banner plus
  cited chunk/document IDs)

```bash
cd ai-engineering-bootcamp-v2/week-1v2
streamlit run rag_demo_page.py --server.port 8600 --server.headless true
```

Both pages read the API base URL from a sidebar text input, defaulting to
the `API_BASE_URL` env var (falls back to `http://127.0.0.1:8000`). To point
at the live Render deployment instead of local:
```bash
API_BASE_URL="https://ai-engineering-bootcamp-u7ud.onrender.com" \
  streamlit run rag_demo_page.py --server.port 8600 --server.headless true
```
(That URL is the **API** service. The Streamlit service has its own separate
Render URL — see the table in the repo-root `README.md`. Don't confuse the
two: the Streamlit URL serves the same SPA shell on every path, including
`/health`, so curling it never proves anything about the API.)

Health check without a browser (also catches script-level exceptions that a
bare `200` on `/` would hide, since Streamlit serves the same shell either
way): `curl http://127.0.0.1:8600/_stcore/health` → `ok`.

Stop: kill by port. Don't `pkill -f streamlit` — too broad if more than one
session is running.

## Driving the Streamlit UI in a browser (screenshots)

`chromium-cli` is **not installed** in this environment. Use `npx playwright`
directly instead — it self-installs on first use:
```bash
cd <scratchpad dir>
npm init -y
npm install playwright
npx playwright install chromium --with-deps   # one-time, ~115MB; cached after
```
Then drive it with a short Node script: `chromium.launch()` → `newPage()` →
`goto()` → locate widgets by role/label/text → `page.screenshot({ path })`.

Streamlit reruns the whole script server-side on each widget interaction
over a websocket. Wait for the resulting element/text to appear
(`page.waitForSelector`, `locator(...).waitFor()`) — never a fixed `sleep`,
and never `networkidle` (the websocket stays open indefinitely so it never
fires).

Representative interaction for `rag_demo_page.py`:
1. `goto` the page, wait for the "RAG Demo" title to render.
2. **Ingest tab**: fill the `Text` textarea + `document_id` input, click
   `Ingest`, wait for the JSON response block to update, screenshot.
3. **Ask tab**: fill `Question` with something answerable from already-
   ingested docs, click `Ask`, wait for either the green "Answered from
   retrieved context" or yellow "Refused" banner, screenshot.
4. Repeat step 3 with an out-of-scope question to confirm the refusal path.

## Gotchas

- Two separate live Render URLs exist for this repo (API vs Streamlit) and
  are easy to mix up — check the table in the root `README.md` before
  assuming which one you're hitting.
- Pinecone/OpenAI failures return sanitized error messages
  (`main.py`'s `/debug/*`, `/ingest`, `/ask` all log the real exception
  server-side via `logger.exception(...)` and return a generic `detail` to
  the client) — check server logs (or run locally to see the real
  traceback), not the HTTP response, when one of these 503s.
