# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

AI Engineering bootcamp coursework, organized by week under
`ai-engineering-bootcamp/`. The only actively deployed/runnable code is in
`ai-engineering-bootcamp/week-1/` — a FastAPI service (Session 1: typed
`/ask`, extended in Session 2 with Pinecone-backed RAG) plus two Streamlit
UIs. `ai-engineering-bootcamp/week-2/rag-vector-databases/` is a separate,
standalone Jupyter notebook (LangChain + Chroma reference material) — not
wired into the deployed app. `ai-engineering-bootcamp/adk-multi-agent-systems/`
(Session 3) is a separate, standalone set of Google ADK demos — see its own
section below. It has its own venv/`pyproject.toml`, but as of the capstone
agent (`week-1/adk_agent.py`, see below) `week-1/` now also depends on
`google-adk`/`google-genai` and needs a `GOOGLE_API_KEY`, so the two folders
are no longer fully independent.

> Note: this folder was previously `ai-engineering-bootcamp-v2/week-1v2/`
> (and week-2 under `ai-engineering-bootcamp-v2/`). The repo was
> restructured to drop the `-v2`/`v2` suffixes; if you find stale references
> to the old paths elsewhere (docs, `render.yaml`), they need updating too —
> see the Deployment note below.

## Commands

All commands run from `ai-engineering-bootcamp/week-1/`, using the venv
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
services, both deploying from `main` only — `ai-engineering-api` (the
FastAPI backend) and `ai-engineering-streamlit` (runs `demo_page.py` via
`start_streamlit.sh`; `rag_demo_page.py` isn't wired into any start command
yet, so it currently only runs locally). These produce two different live
URLs that are easy to confuse — see the table in the repo-root `README.md`
before assuming which one a request hit. Non-secret env vars
(`PINECONE_INDEX_NAME`, `PINECONE_CLOUD`, `PINECONE_REGION`,
`EMBEDDING_MODEL`) are set directly in `render.yaml`; secrets
(`OPENAI_API_KEY`, `PINECONE_API_KEY`) are declared with `sync: false` and
must be pasted into the Render dashboard manually — pushing a blueprint
change that touches `envVars` for the first time can require re-entering
them even if they were set before.

**Fixed (2026-08-03)**: `render.yaml`'s `root:` for both services was still
`ai-engineering-bootcamp-v2/week-1v2` (deleted in the original restructure) —
updated to `ai-engineering-bootcamp/week-1` for both. If these services are
connected to Render as a synced Blueprint, this was a real fix (the next
deploy would have failed to find the app); if they were configured manually
in the dashboard instead, `render.yaml` wasn't authoritative anyway and this
just brings the file back in sync with reality.

**`data/northwind/`** (under `week-1/`) holds two real PDFs (Northwind
Health Plus/Standard benefits docs) pulled from Microsoft's
`azure-search-openai-demo` reference repo, used as the sample RAG corpus.
Note: the source PDFs themselves contain internally inconsistent figures in
places (e.g. the Standard plan's out-of-pocket max is stated as both $6,000
and $6,350/$12,700 in different sections) — this is a property of the
sample data, not a retrieval bug, and `eval_northwind.py`'s known-answer set
accounts for it.

## `adk-multi-agent-systems/` (Session 3 — not deployed)

Standalone Google ADK (Agent Development Kit) coursework, separate from
`week-1/`'s FastAPI/Pinecone stack — different dependency set (own
`pyproject.toml` + `requirements.txt`, not the repo-root `.venv`), different
LLM provider (Gemini via `GOOGLE_API_KEY`, not OpenAI), no shared code.

Three progressive demos, each runnable standalone (`python demo1_routing.py`
etc. — see the folder's own `README.md` for full run instructions):
- **`demo1_routing.py`** — one root `Agent` (`sub_agents=[...]`) routes a
  user message to a specialist agent, each with local Python-function
  tools. Adapted to the Session 3 healthcare capstone theme: `benefits_agent`
  (coverage/deductible/prior-auth lookups), `clinical_agent` (self-care
  guidance, clinic status), `escalation_agent` (urgent-symptom triage
  ticketing) behind a `healthcare_router` root agent. Uses stub in-memory
  data, not `week-1/vectorstore.py` — see the integration note below.
- **`demo2_mcp.py`** — a `claims_agent_mcp` agent gets its tools from a live
  Supabase MCP server (launched as an `npx` subprocess via `McpToolset`)
  instead of hardcoded functions. Requires `SUPABASE_ACCESS_TOKEN` /
  `SUPABASE_PROJECT_REF`, now configured — the Supabase project has real
  `patients`/`claims`/`support_tickets` tables (healthcare-capstone-themed,
  parallel to `demo1_routing.py`'s stub schema), created and seeded via the
  MCP server's own `apply_migration`/`execute_sql` tools, RLS enabled
  (deny-all — nothing needs anon/authenticated API access to these tables;
  the MCP server itself uses elevated management-API access and is
  unaffected by RLS). `shipping_agent.py` is exposed separately via
  `to_a2a(...)` and must be running (`uvicorn shipping_agent:app --port
  8001`) before Demo 3.
- **`demo3_full_system.py`** — combines all three tool sources under one
  router: local tools (technical), MCP/Supabase (`claims_agent_mcp`), and
  A2A (`RemoteA2aAgent` pointed at the standalone `shipping_agent.py`
  process). Also wires up Langfuse tracing (`GoogleADKInstrumentor`) —
  `langfuse` and `openinference-instrumentation-google-adk` are required for
  this and for `streamlit_app.py`, but are declared only in
  `requirements.txt`, not yet in `pyproject.toml`; keep both files in sync
  if you add dependencies.

**Verified working (2026-08-02)**: ran both `demo2_mcp.py` and
`demo3_full_system.py` end-to-end against the real Supabase project and
Gemini — patient/claims lookups, the cross-table support-ticket query, and
the A2A shipping handoff all returned correct real data. Bugs fixed to get
there:
- `google.adk.tools.mcp_tool` doesn't re-export `McpToolset`/
  `StdioConnectionParams` at the top level in installed `google-adk` 2.6.1 —
  both demos now import from the actual submodules
  (`google.adk.tools.mcp_tool.mcp_toolset` /
  `...mcp_tool.mcp_session_manager`).
- The installed `mcp` package was 2.0.0, but `google-adk` 2.6.1 requires
  `mcp>=1.24,<2` — `mcp` 2.x removed/moved modules (`mcp.shared.session`)
  that `google-adk` imports directly, breaking the import outright.
  Downgraded to `mcp` 1.29.0; `requirements.txt` now pins `mcp>=1.24,<2`
  instead of the too-loose `mcp>=1.0.0` to stop this regressing.
- `demo3_full_system.py`'s `ask()` had the same early-return tracing issue
  as `demo1_routing.py` (see above) — fixed the same way. Note:
  `demo3_full_system.py`/`streamlit_app.py` also use
  `GoogleADKInstrumentor()` (Langfuse/OpenInference), which introduces a
  *second*, separate source of the same class of harmless
  `GeneratorExit`/context-detach noise (from OpenInference's own event
  wrapper, not from this file's own `ask()` loop) — confirmed harmless
  (all 3 test scenarios still answered correctly) but not fully silenced;
  not chased further since it doesn't affect output.
- `streamlit_app.py`'s Demo 2/3 pages have their own duplicated
  `create_mcp_claims_agent()`/`create_full_system_agent()` factories (not
  shared code with `demo2_mcp.py`/`demo3_full_system.py`) — these had the
  same broken top-level `mcp_tool` import and the old generic
  customers/orders schema; fixed and rethemed the same way, and the UI copy
  (buttons, captions, placeholders) updated to match. Verified the app still
  serves (HTTP 200) after the edit; the underlying agent-building logic is
  structurally identical to the now-verified `demo2_mcp.py`/
  `demo3_full_system.py`, though the Streamlit button click paths themselves
  weren't separately re-exercised (no browser automation available here).

**`capstone_agent.py`** — a minimal single-agent (no `sub_agents`) starting
point for the capstone job, built with the same patterns as
`demo1_routing.py` (`load_dotenv`/`MODEL`, tool-function shape,
`Agent(...)` fields, `ask()`/`main()` Runner harness). `benefits_coverage_agent`
answers benefits-coverage questions using one placeholder tool
(`search_benefits_documents`, a stub — will become a real
`vectorstore.query_similar` call), capped at `MAX_STEPS = 6` stream events so
it can't loop forever, with `log_event()` printing each event as
THINK/ACT/OBSERVE. No router here — the job doesn't need one.

**Capstone integration — implemented**: `week-1/adk_agent.py` is a sibling
entry point to `main.py` (not an edit to it — `main.py`'s `/ask` stays
OpenAI-only and deployed as-is). It's the real-RAG version of
`adk-multi-agent-systems/capstone_agent.py`: same single-agent
`benefits_coverage_agent`, same `Agent`/Runner/logging/`MAX_STEPS` pattern,
but `search_benefits_documents` now calls `vectorstore.query_similar`
directly (imported like `main.py` does) instead of returning a stub —
so it queries the same Northwind Pinecone index `/ask` already uses. No
Supabase/MCP needed for this; the RAG source is Pinecone, already configured.
Still single-agent, no router — the coverage-lookup job doesn't need one;
`demo1_routing.py`'s router pattern is there if a second job (e.g.
appointment scheduling) needs dispatching later.

Because this file lives in `week-1/` and imports `vectorstore.py` directly,
`week-1/requirements.txt` now also includes `google-adk`/`google-genai` —
unused by the deployed `main.py`, but needed for `adk_agent.py` to run in the
same venv (both are now installed in the repo-root `.venv`).
`GOOGLE_API_KEY` has been added to the repo-root `.env` (copied from
`adk-multi-agent-systems/.env`, which `adk_agent.py`'s dotenv walk doesn't
reach on its own).

**Verified working (2026-08-02)**: ran `python adk_agent.py` end-to-end
against the real Pinecone index and Gemini — `search_benefits_documents`
returns real ranked chunks from `northwind-health-plus-benefits-details`,
and the agent answers with a citation. Also ran `demo1_routing.py`
end-to-end: all three routes (benefits/clinical/escalation) delegated and
answered correctly, clean log, no tracebacks. Fixes that were needed to get
there:
- `search_benefits_documents` now wraps `query_similar` in try/except,
  logging the real exception and returning `{"error": ...}` instead of
  raising — so a Pinecone/OpenAI failure becomes an observation the model
  reacts to (per its instruction's error-handling clause) rather than
  crashing the run.
- `demo1_routing.py`'s and `capstone_agent.py`'s `ask()` helpers used to
  `return` the moment they saw `event.is_final_response()`, which breaks out
  of the `async for` early and forces ADK's OpenTelemetry span to close from
  a different async context — this raised a harmless but noisy
  `GeneratorExit`/`ValueError` traceback on every run. Both now let the event
  stream run to completion and only `break` early on a genuine step-limit
  abort. `adk_agent.py` already had this fix from its own verification pass.
  `demo2_mcp.py`/`demo3_full_system.py` still have the old early-return
  pattern — same latent noisy-but-harmless issue if/when those are run.
- `demo1_routing.py`'s `main()` now wraps each test query in try/except so
  one failed call (rate limit or otherwise) doesn't crash the whole test
  run — it prints `[FAILED] ...` and moves to the next query instead.

**Model name history (2026-08-02) — settled on `"gemini-3.1-flash-lite"`.**
This API key hit a wall on every model tried before that one:
`"gemini-2.5-flash"` and `"gemini-2.5-flash-lite"` both 404 ("no longer
available to new users"); `"gemini-2.0-flash"` and `"gemini-2.0-flash-lite"`
both 429 with `limit: 0` — a hard free-tier entitlement wall, not exhausted
quota; `"gemini-flash-latest"` (an alias) resolved to `"gemini-3.6-flash"`
and worked, but only a **20 requests/day** cap, which this session's testing
exhausted mid-run. `"gemini-3.1-flash-lite"` and `"gemini-flash-lite-latest"`
were the two confirmed-working options found by testing candidates directly
against the API; `"gemini-3.1-flash-lite"` was chosen since it's a pinned,
stable model (not a `"-latest"` alias that can silently start resolving to a
different, differently-quota'd model later). Applied repo-wide:
`demo1_routing.py`, `demo2_mcp.py`, `demo3_full_system.py`,
`shipping_agent.py`, `capstone_agent.py`, `streamlit_app.py`, and
`week-1/adk_agent.py`. Note: a Google AI **Pro** subscription (the consumer
Gemini app plan) does not affect this — API quota comes from whether the
Cloud project behind `GOOGLE_API_KEY` has billing enabled, a separate,
unrelated system.

**Deployment (2026-08-03)**: added `Dockerfile` + `.dockerignore` under
`adk-multi-agent-systems/` (Render's native Python runtime has no Node.js,
but Demo 2/3's Supabase MCP server launches via `npx` — this service needs
Docker) and a third `render.yaml` service, `adk-healthcare-capstone`. Since
this repo is public, hardened Supabase MCP access first:
- `SUPABASE_READ_ONLY` (env var, defaults to `true` even if unset) appends
  `--read-only` to the MCP server launch — verified with a real write
  attempt against the live project that this genuinely blocks
  `execute_sql`/`apply_migration` at the DB/app level, not just an LLM
  instruction.
- On top of that, `McpToolset(tool_filter=[...])` restricts the exposed
  tools to `list_tables`/`execute_sql`/`get_advisors`/`search_docs` only —
  belt-and-suspenders, since `deploy_edge_function`/`delete_branch`/
  `create_branch`/etc. weren't individually confirmed to respect
  `--read-only`.
- Fixed three `st.error(str(e))` call sites in `streamlit_app.py` that
  could have leaked the Supabase token to a public visitor (a subprocess
  launch failure's exception text can embed the full command line,
  `--access-token` included) — replaced with `log_and_show_error()`, which
  logs the real exception server-side and shows only a generic message
  publicly, same pattern as `main.py`'s existing error handling.

`shipping_agent.py`'s A2A URL is now configurable (`A2A_HOST`/`A2A_PORT`/
`A2A_PROTOCOL`) instead of hardcoded to `localhost:8001`, but it isn't
deployed as its own Render service yet — Demo 3's shipping piece will show
"not running" on the deployed site until/unless that's added separately.

Verified for real, not just written: `docker build` succeeds, and a running
container (real secrets passed as env vars, exactly as Render would) serves
HTTP 200 with `$PORT` binding working correctly. `demo2_mcp.py` re-run with
both `--read-only` and `tool_filter` active still answers correctly with
real data — the hardening didn't break functionality.
