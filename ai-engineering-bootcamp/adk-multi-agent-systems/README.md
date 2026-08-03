# ADK Multi-Agent Systems

Three progressive demos showing multi-agent system design using [Google's Agent Development Kit (ADK)](https://google.github.io/adk-docs/).

| Demo | What it shows | Protocol |
|------|--------------|----------|
| **Demo 1** — Routing | Router agent delegates to benefits, clinical, and escalation specialists (healthcare capstone theme, stub data) | Local tools |
| **Demo 2** — MCP | `claims_agent_mcp` queries a live Supabase database (real `patients`/`claims`/`support_tickets` tables, healthcare-themed, RLS enabled) | MCP |
| **Demo 3** — Full System | Combines routing + MCP (same claims data as Demo 2) + A2A with a remote shipping agent (shipping stays generic — package tracking isn't part of the capstone) | MCP + A2A |
| **Streamlit App** | Interactive UI that runs all three demos in the browser, same healthcare theme throughout | All |

All demos use `MODEL = "gemini-3.1-flash-lite"`. The previously hardcoded
`"gemini-2.5-flash"` 404s ("no longer available to new users") on a fresh
`GOOGLE_API_KEY` — see "Model choice" below for the full story on why this
specific model was picked.

## Prerequisites

- **Python 3.12+** (required — earlier versions have asyncio incompatibilities with MCP)
- **Node.js / npm** (needed by the Supabase MCP server, launched via `npx`)
- A **Google API key** for Gemini models → [Get one here](https://aistudio.google.com/apikey)
- A **Supabase project** with a Personal Access Token → [Generate here](https://supabase.com/dashboard/account/tokens) *(Demos 2 & 3 only)*

## Setup

### 1. Create and activate a virtual environment

**With [uv](https://docs.astral.sh/uv/) (recommended):**

```bash
uv venv
source .venv/bin/activate   # macOS / Linux
# .venv\Scripts\activate    # Windows
uv pip install -e .
```

**With plain pip:**

```bash
python3 -m venv .venv
source .venv/bin/activate   # macOS / Linux
# .venv\Scripts\activate    # Windows
pip install -e .
```

A `requirements.txt` is also provided (`pip install -r requirements.txt`) for
environments that prefer it over `pip install -e .`. It includes `mcp`,
`langfuse`, and `openinference-instrumentation-google-adk` — used by
`demo2_mcp.py`/`demo3_full_system.py`/`streamlit_app.py` but not yet declared
in `pyproject.toml`; keep both files in sync if dependencies change. It also
pins `opentelemetry-api`/`opentelemetry-sdk` to `1.42.1` — installing
`langfuse`/`openinference-instrumentation-google-adk` normally pulls in
`1.44.x`, which conflicts with what `google-adk` declares (harmless in
practice, but pinned to silence the resolver warning).

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in your keys:

```
GOOGLE_API_KEY=your_google_api_key_here
SUPABASE_ACCESS_TOKEN=your_personal_access_token_here
SUPABASE_PROJECT_REF=your_project_ref_here
```

## Running the demos

### Demo 1 — Multi-Agent Routing (local tools only)

```bash
python demo1_routing.py
```

### Demo 2 — MCP + Supabase

Requires `SUPABASE_ACCESS_TOKEN` and `SUPABASE_PROJECT_REF` in `.env`.

```bash
python demo2_mcp.py
```

### Demo 3 — Full System (Routing + MCP + A2A)

Start the shipping agent in one terminal, then run the demo in another:

```bash
# Terminal 1 — start the A2A shipping agent
uvicorn shipping_agent:app --port 8001

# Terminal 2 — run the demo
python demo3_full_system.py
```

### Streamlit App (interactive UI for all demos)

```bash
# Terminal 1 — start the A2A shipping agent (only needed for the Demo 3 page)
uvicorn shipping_agent:app --port 8001

# Terminal 2 — launch the Streamlit app
streamlit run streamlit_app.py
```

Just want to see the capstone (Demo 1)? Skip Terminal 1 — the shipping
agent is only needed if you click into the Demo 3 page; the sidebar shows
its status (and Supabase's) as warnings rather than blocking the app.
Needs only `GOOGLE_API_KEY` in `.env` to run Demo 1; `LANGFUSE_PUBLIC_KEY`/
`LANGFUSE_SECRET_KEY`/`LANGFUSE_HOST` are optional (enables the "Langfuse
Tracing" sidebar status — get keys from your Langfuse project's Settings →
API Keys page).

## Status / capstone notes

My capstone theme is Healthcare. `demo1_routing.py` has been adapted from the
generic customer-support starter to a `healthcare_router` root agent routing
to:
- `benefits_agent` — plan coverage / deductible / prior-authorization lookups
- `clinical_agent` — non-urgent self-care guidance and clinic status
- `escalation_agent` — urgent-symptom triage, escalates to a human reviewer

It uses stub in-memory data, same as the original demo. `streamlit_app.py`'s
Demo 1 page uses the identical tools/agents.

`demo2_mcp.py` (and the MCP portion of `demo3_full_system.py`) query a
**real** Supabase project via MCP — `claims_agent_mcp`, backed by real
`patients`/`claims`/`support_tickets` tables (healthcare-themed: the same
Bob Smith/Jane Doe/Alice Johnson-style seed data as Demo 1, but real rows in
a real Postgres database). Schema + seed data were created via the MCP
server's own `apply_migration`/`execute_sql` tools (not by hand in the
Supabase dashboard):

```sql
create table patients (id bigint generated always as identity primary key,
  name text not null, email text not null unique, plan_name text not null);
create table claims (id bigint generated always as identity primary key,
  patient_id bigint references patients(id), service_description text not null,
  amount numeric(10,2) not null,
  status text not null check (status in ('pending','approved','denied','paid')),
  submitted_date date not null);
create table support_tickets (id bigint generated always as identity primary key,
  patient_id bigint references patients(id), subject text not null,
  priority text not null check (priority in ('low','medium','high')),
  status text not null check (status in ('open','closed')), created_date date not null);
```

3 patients, 4 claims, 4 support tickets seeded. **RLS is enabled** (deny-all,
no policies) on all three tables — Supabase's own advisor flagged them as
exposed to `anon`/`authenticated` API roles right after creation, so this
was fixed immediately. The MCP server itself uses elevated management-API
access, not the `anon`/`authenticated` roles, so RLS doesn't affect these
demos at all — confirmed by re-running `demo2_mcp.py` after enabling it.

`shipping_agent.py`/the A2A piece stays generic (package tracking isn't
part of the healthcare capstone).

**Verified working (2026-08-02)**: ran `demo1_routing.py`, `demo2_mcp.py`,
`demo3_full_system.py` (with `shipping_agent.py` running), and
`../week-1/adk_agent.py` end-to-end against real Gemini/Pinecone/Supabase —
every route answered correctly with real data, including the A2A shipping
handoff in Demo 3. Also launched `streamlit_app.py` and confirmed it serves
(HTTP 200) with all imports resolving.

**Bugs fixed to get MCP working at all**:
- `google.adk.tools.mcp_tool` doesn't re-export `McpToolset`/
  `StdioConnectionParams` at the top level in installed `google-adk` 2.6.1 —
  both `demo2_mcp.py` and `demo3_full_system.py` now import from the actual
  submodules (`google.adk.tools.mcp_tool.mcp_toolset` /
  `...mcp_tool.mcp_session_manager`).
- The installed `mcp` package was 2.0.0, but `google-adk` 2.6.1 requires
  `mcp>=1.24,<2` — `mcp` 2.x removed `mcp.shared.session`, which `google-adk`
  imports directly, breaking the import outright. Downgraded to `mcp`
  1.29.0; `requirements.txt` now pins `mcp>=1.24,<2` instead of the
  too-loose `mcp>=1.0.0` so this doesn't regress on a fresh install.
- `streamlit_app.py`'s Demo 2/3 pages have their own duplicated
  `create_mcp_claims_agent()`/`create_full_system_agent()` factories, not
  shared code with `demo2_mcp.py`/`demo3_full_system.py` — same broken
  import, same stale generic schema. Fixed and rethemed the same way, UI
  copy updated to match. App re-verified to still serve (HTTP 200) after the
  edit; the button click paths themselves weren't separately exercised (no
  browser automation here), but the underlying logic is structurally
  identical to the now-verified standalone scripts.

### Model choice: `gemini-3.1-flash-lite`

This API key hit a wall on nearly every model name tried, in order:
- `"gemini-2.5-flash"` and `"gemini-2.5-flash-lite"` — 404, "no longer
  available to new users"
- `"gemini-2.0-flash"` and `"gemini-2.0-flash-lite"` — 429 with `limit: 0`
  (a hard free-tier entitlement wall, not exhausted quota)
- `"gemini-flash-latest"` (an alias) — worked, resolved server-side to
  `"gemini-3.6-flash"`, but capped at **20 requests/day**; this session's
  own testing exhausted it mid-verification-run
- `"gemini-3.1-flash-lite"` and `"gemini-flash-lite-latest"` — both
  confirmed working with real API calls

Settled on **`"gemini-3.1-flash-lite"`**: a pinned, stable model (not a
`"-latest"` alias that could silently start resolving to a different,
differently-quota'd model later), with confirmed working quota. Applied to
every file in this folder plus `../week-1/adk_agent.py`.

Note: a Google AI **Pro** subscription (the consumer Gemini app plan) does
**not** fix any of this — API quota comes from whether the Cloud project
behind `GOOGLE_API_KEY` has billing enabled, a separate, unrelated system.
If you hit a quota wall while testing, either wait for the daily reset,
enable billing on that Cloud project, or ask to try a different model name.

Two other bugs fixed to get a clean run:
- `demo1_routing.py`'s and `demo3_full_system.py`'s (and `capstone_agent.py`'s)
  `ask()` helper used to `return` from inside the
  `async for event in runner.run_async(...)` loop the moment it saw a final
  response — that early exit forces ADK's OpenTelemetry span to close from a
  different async context, raising a harmless-but-noisy
  `GeneratorExit`/`ValueError` traceback on every run. All now drain the
  event stream to completion instead of returning early. Note:
  `demo3_full_system.py` (and `streamlit_app.py`) also use
  `GoogleADKInstrumentor()` (Langfuse/OpenInference), which introduces a
  *second*, separate source of the same class of noise from OpenInference's
  own event wrapper — confirmed harmless (all 3 Demo 3 scenarios still
  answered correctly with real data) but not fully silenced by this fix;
  not chased further since it doesn't affect output. `demo2_mcp.py` doesn't
  use this instrumentor, so it runs fully clean.
- `demo1_routing.py`'s and `demo3_full_system.py`'s `main()` now wrap each
  test query in try/except so one failed call (rate limit or otherwise)
  doesn't crash the whole test run — prints `[FAILED] ...` and moves to the
  next query instead.

**Also done**: real RAG wiring lives in `../week-1/adk_agent.py` — a sibling
entry point to `main.py` (not an edit to it), a single-agent
`benefits_coverage_agent` whose retrieval tool calls
`../week-1/vectorstore.py`'s `query_similar` directly against the real
Northwind Pinecone index. See `../week-1/README.md`'s "ADK Capstone Agent"
section to run it.

### `capstone_agent.py` — single-agent capstone starting point

A minimal, single-agent (no router) version of the capstone job, built by
copying patterns straight from `demo1_routing.py`: same `load_dotenv()` +
`MODEL` setup, same tool-function shape, same `Agent(...)` fields, same
`ask()`/`main()` Runner harness. What's different from `demo1_routing.py`:

- **One job, not three** — `benefits_coverage_agent` only answers benefits
  coverage questions (deductible, prior-auth) by searching plan documents; no
  `sub_agents`/routing, since this one job doesn't need dispatching to
  different specialists.
- **One placeholder tool** — `search_benefits_documents` returns a canned
  stub snippet today; it's designed to be swapped for a real call to
  `../week-1/vectorstore.py`'s `query_similar()` next.
- **Step limit** — `MAX_STEPS = 6` caps the number of stream events (tool
  calls + responses + model text) per question, so the agent can't loop
  forever if it keeps re-searching.
- **Think/Act/Observe logging** — `log_event()` prints each ADK stream event
  as `THINK` (model reasoning text), `ACT` (a tool call and its args), or
  `OBSERVE` (the tool's return value), so you can watch the loop step by step.

Run: `python capstone_agent.py` (same style as the other demos — needs only
`GOOGLE_API_KEY`).

## Deploying (Render)

`Dockerfile` + `.dockerignore` here let this run on Render as
`adk-healthcare-capstone` (see repo-root `render.yaml`) — Docker, not
`env: python`, because Demo 2/3's Supabase MCP server launches via `npx`
and Render's native Python runtime has no Node.js. Verified locally with a
real `docker build` + running container (HTTP 200, `$PORT` binding works).

**Since this repo is public**, Supabase MCP access is hardened two ways
before deploying, not just documented:
- `SUPABASE_READ_ONLY` defaults to `true` even if the env var is unset —
  appends `--read-only` to the MCP server launch. Verified against the live
  project with a real write attempt: `execute_sql`/`apply_migration` are
  genuinely blocked at the DB/app level, not just discouraged by an LLM
  instruction.
- `McpToolset(tool_filter=[...])` additionally restricts the exposed tools
  to `list_tables`/`execute_sql`/`get_advisors`/`search_docs` — belt-and-
  suspenders, since tools like `deploy_edge_function`/`delete_branch`/
  `create_branch` weren't individually confirmed to respect `--read-only`.
- Three `st.error(str(e))` sites in `streamlit_app.py` could have leaked the
  Supabase token to a public visitor (a subprocess launch failure can embed
  the full command line in its exception text) — replaced with
  `log_and_show_error()`: logs the real exception server-side, shows only a
  generic message on the page.

Set `SHIPPING_AGENT_URL`/`A2A_HOST`/`A2A_PORT`/`A2A_PROTOCOL` (see
`.env.example`) if you later deploy `shipping_agent.py` as its own service
for Demo 3's A2A piece — not included in `render.yaml` yet, so that piece
will show "not running" on the deployed site until it is.

## Architecture

```
User Query
    │
    ▼
┌───────────────────────┐
│     Router Agent       │
├───────┬───────┬───────┤
│       │       │       │
▼       ▼       ▼       │
Billing  Tech  Shipping │
│       │       │       │
▼       ▼       ▼       │
MCP    Local    A2A     │
Server  Tools  Protocol │
│               │       │
▼               ▼       │
Supabase     Remote     │
  DB         Agent      │
└───────────────────────┘
```

