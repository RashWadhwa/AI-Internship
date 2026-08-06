"""
ADK Multi-Agent Systems -- Interactive Classroom Demo

Run:
    uvicorn shipping_agent:app --port 8001   # Terminal 1
    streamlit run streamlit_app.py            # Terminal 2
"""

import streamlit as st
import asyncio
import concurrent.futures
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from langfuse import get_client, observe, propagate_attributes
from openinference.instrumentation.google_adk import GoogleADKInstrumentor

langfuse = get_client()
GoogleADKInstrumentor().instrument()

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

# "gemini-2.5-flash" 404s ("no longer available to new users") for a fresh
# GOOGLE_API_KEY. "gemini-2.0-flash"/"gemini-2.5-flash-lite" both hit hard
# free-tier walls (limit 0 / 404) on this key too. "gemini-3.1-flash-lite"
# is a stable (non-"-latest") pinned model confirmed to have working quota.
MODEL = "gemini-3.1-flash-lite"

# Secure by default: read-only unless explicitly disabled. This page takes
# free-text input from whoever loads it -- on a deployed/public instance
# that's anyone, so the MCP server must not be able to run
# apply_migration/execute_sql/delete_branch/etc. against the real project.
SUPABASE_READ_ONLY = os.getenv("SUPABASE_READ_ONLY", "true").strip().lower() != "false"

# Defaults to localhost for local dev; set SHIPPING_AGENT_URL to the deployed
# shipping_agent's real URL when running this off of localhost (e.g. Render).
SHIPPING_AGENT_URL = os.getenv("SHIPPING_AGENT_URL", "http://localhost:8001")

# Belt-and-suspenders on top of --read-only: verified --read-only blocks
# execute_sql/apply_migration writes at the DB/app level, but tools like
# deploy_edge_function/delete_branch/create_branch weren't individually
# confirmed to respect it. Restricting the exposed tool set makes that moot
# -- these agents only ever need to read data and inspect schema.
SUPABASE_MCP_TOOL_FILTER = ["list_tables", "execute_sql", "get_advisors", "search_docs"]

# --- Tools ---
# Demo 1's tools/agents below are the healthcare-capstone theme (same as
# healthcare_router.py) -- stub data, matching the class-demo style. The real,
# Pinecone-backed version of this job lives in ../week-1/adk_agent.py.

def lookup_coverage(plan_name: str) -> dict:
    """Look up benefits coverage details for a health plan by name."""
    plans = {
        "northwind health plus": {"plan": "Northwind Health Plus", "deductible": "$500", "out_of_pocket_max": "$3,000", "coverage": "Full medical, dental, vision"},
        "northwind standard": {"plan": "Northwind Standard", "deductible": "$1,500", "out_of_pocket_max": "$6,000", "coverage": "Medical only"},
    }
    return plans.get(plan_name.lower(), {"error": f"No plan found matching {plan_name}"})

def check_prior_authorization(procedure_code: str) -> dict:
    """Check whether a procedure requires prior authorization under the member's plan."""
    procedures = {
        "MRI-001": {"requires_auth": True, "typical_turnaround": "3-5 business days"},
        "PT-002": {"requires_auth": False, "typical_turnaround": "n/a"},
    }
    return procedures.get(procedure_code.upper(), {"error": f"No procedure found for code {procedure_code}"})

def search_symptom_guidance(query: str) -> dict:
    """Search self-care guidance for common, non-urgent symptoms."""
    articles = {
        "fever": {"title": "Managing a Fever", "guidance": "1. Rest and fluids. 2. OTC fever reducer per label. 3. See a doctor if fever exceeds 103F or lasts 3+ days."},
        "headache": {"title": "Headache Relief", "guidance": "1. Hydrate. 2. Rest in a dark room. 3. OTC pain reliever. 4. Seek care if sudden/severe."},
        "rash": {"title": "Skin Rash", "guidance": "1. Avoid scratching. 2. Use fragrance-free moisturizer. 3. See a doctor if spreading or with fever."},
    }
    for keyword, article in articles.items():
        if keyword in query.lower():
            return article
    return {"title": "General Guidance", "guidance": "No specific article found. Consider scheduling a visit."}

def check_clinic_status() -> dict:
    """Check current operating status and wait times of partner clinics."""
    return {"overall": "operational", "clinics": {"downtown": "operational", "westside": "operational", "urgent_care": "high_volume"}, "last_incident": "2026-02-08"}

def create_escalation_ticket(patient_id: str, symptom_summary: str, urgency: str) -> dict:
    """Create an escalation ticket routing a patient to a nurse or provider for review."""
    times = {"low": "48 hours", "medium": "24 hours", "high": "4 hours", "critical": "immediate -- call 911 or go to ER"}
    return {"ticket_id": "ESC-2026-0042", "urgency": urgency, "estimated_response": times.get(urgency, "24 hours")}

# --- Demo 1 Agents (healthcare capstone) ---

benefits_agent = Agent(
    name="benefits_agent", model=MODEL,
    description="Handles benefits: plan coverage, deductibles, prior authorization.",
    instruction="You are a benefits specialist. Use lookup_coverage and check_prior_authorization.",
    tools=[lookup_coverage, check_prior_authorization],
)
clinical_agent = Agent(
    name="clinical_agent", model=MODEL,
    description="Handles non-urgent clinical questions: symptoms, self-care, clinic status.",
    instruction="You are a clinical information specialist. Use search_symptom_guidance and check_clinic_status. Never diagnose -- offer general guidance only.",
    tools=[search_symptom_guidance, check_clinic_status],
)
escalation_agent = Agent(
    name="escalation_agent", model=MODEL,
    description="Handles urgent symptoms or requests needing nurse/provider review.",
    instruction="You are a triage escalation specialist. Use create_escalation_ticket.",
    tools=[create_escalation_ticket],
)
router_agent = Agent(
    name="healthcare_router", model=MODEL,
    instruction="Route to benefits_agent, clinical_agent, or escalation_agent. Never answer directly.",
    sub_agents=[benefits_agent, clinical_agent, escalation_agent],
)

# --- Demo 2 & 3 Agent Factories ---

def create_mcp_claims_agent():
    # Top-level google.adk.tools.mcp_tool doesn't re-export these in installed
    # google-adk 2.6.1 -- import from the actual submodules instead.
    from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
    from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
    from mcp.client.stdio import StdioServerParameters
    token = os.getenv("SUPABASE_ACCESS_TOKEN", "")
    ref = os.getenv("SUPABASE_PROJECT_REF", "")
    if not token:
        return None, "SUPABASE_ACCESS_TOKEN not set in .env"
    mcp_args = ["-y", "@supabase/mcp-server-supabase@latest", "--access-token", token]
    if ref:
        mcp_args += ["--project-ref", ref]
    if SUPABASE_READ_ONLY:
        mcp_args += ["--read-only"]
    mcp = McpToolset(connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(command="npx", args=mcp_args), timeout=30.0),
        tool_filter=SUPABASE_MCP_TOOL_FILTER)
    agent = Agent(
        name="claims_agent_mcp", model=MODEL,
        description="Healthcare claims/billing agent with real Supabase database access via MCP.",
        instruction="You are a healthcare claims specialist with database access. Use MCP tools to query patients, claims, support_tickets.",
        tools=[mcp])
    return agent, None

def create_full_system_agent():
    # Top-level google.adk.tools.mcp_tool doesn't re-export these in installed
    # google-adk 2.6.1 -- import from the actual submodules instead.
    from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
    from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
    from google.adk.agents.remote_a2a_agent import RemoteA2aAgent
    from mcp.client.stdio import StdioServerParameters
    token = os.getenv("SUPABASE_ACCESS_TOKEN", "")
    ref = os.getenv("SUPABASE_PROJECT_REF", "")
    if not token:
        return None, "SUPABASE_ACCESS_TOKEN not set in .env"
    mcp_args = ["-y", "@supabase/mcp-server-supabase@latest", "--access-token", token]
    if ref:
        mcp_args += ["--project-ref", ref]
    if SUPABASE_READ_ONLY:
        mcp_args += ["--read-only"]
    mcp = McpToolset(connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(command="npx", args=mcp_args), timeout=30.0),
        tool_filter=SUPABASE_MCP_TOOL_FILTER)
    claims = Agent(name="claims_agent_mcp", model=MODEL,
        description="Healthcare claims with real Supabase DB via MCP.",
        instruction="You are a healthcare claims specialist. Use MCP tools to query patients, claims, support_tickets.", tools=[mcp])
    tech = Agent(name="technical_agent", model=MODEL,
        description="Technical issues: bugs, crashes, performance.", instruction="Use search_knowledge_base and check_system_status.",
        tools=[search_knowledge_base, check_system_status])
    shipping = RemoteA2aAgent(name="shipping_agent", agent_card=SHIPPING_AGENT_URL,
        description="Remote agent for shipping and delivery tracking.")
    root = Agent(name="full_support_system", model=MODEL,
        instruction="Route to claims_agent_mcp, technical_agent, or shipping_agent. Never answer directly.",
        sub_agents=[claims, tech, shipping])
    return root, None

# --- Runner ---

# Verb-first, low-cardinality trace names per Langfuse best practices --
# matches the same job's name in the standalone script it mirrors, so the
# Streamlit and CLI versions of "the same job" show up under one name.
_TRACE_NAME_BY_DEMO = {
    "demo1-routing": "route-healthcare-query",
    "demo2-mcp": "query-patient-claims",
    "demo3-full-system": "route-support-request",
}

def run_agent_sync(agent, message, timeout=120, demo_label="demo", user_id="user1"):
    """Run an ADK agent synchronously with trace capture.

    demo_label tags the Langfuse trace and looks up its name (e.g.
    "demo1-routing") -- this runner is shared across all three demo pages,
    so the caller identifies which one. @observe is applied to _run(), not
    to run_agent_sync() itself: _run() executes inside a fresh worker
    thread's own event loop (via ThreadPoolExecutor + asyncio.run below),
    and OpenTelemetry context doesn't cross thread boundaries -- decorating
    the outer sync function here would create a span in the Streamlit main
    thread that never actually wraps the agent execution.
    """
    trace_name = _TRACE_NAME_BY_DEMO.get(demo_label, demo_label)

    @observe(name=trace_name, capture_input=False, capture_output=False)
    async def _run():
        service = InMemorySessionService()
        runner = Runner(agent=agent, app_name="demo", session_service=service)
        session = await service.create_session(app_name="demo", user_id=user_id)
        # capture_input=False above + explicit set here: the decorator would
        # otherwise capture zero args (message is a closure var, not a param),
        # so set it explicitly to make the trace input meaningful.
        langfuse.update_current_span(input=message)
        content = types.Content(role="user", parts=[types.Part(text=message)])
        trace, final = [], "(no response)"
        with propagate_attributes(
            user_id=user_id,
            session_id=session.id,
            tags=[demo_label, "healthcare-capstone"],
            environment=os.getenv("LANGFUSE_ENVIRONMENT", "development"),
        ):
            async for event in runner.run_async(user_id=user_id, session_id=session.id, new_message=content):
                author = getattr(event, "author", "unknown")
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        fc = getattr(part, "function_call", None)
                        fr = getattr(part, "function_response", None)
                        text = getattr(part, "text", None)
                        if fc:
                            trace.append({"author": author, "type": "tool_call", "tool": fc.name, "args": dict(fc.args) if fc.args else {}})
                        elif fr:
                            trace.append({"author": author, "type": "tool_response", "tool": fr.name, "result": str(fr.response)[:800] if fr.response else ""})
                        elif text:
                            trace.append({"author": author, "type": "text", "text": text})
                            if event.is_final_response():
                                final = text
        langfuse.update_current_span(output=final)
        langfuse.flush()
        return final, trace
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, _run()).result(timeout=timeout)

# --- Helpers ---

def log_and_show_error(exc: Exception, context: str) -> None:
    """Log the real exception server-side; show only a generic message publicly.

    A raw MCP subprocess exception can embed the full launch command line --
    including "--access-token <TOKEN>" -- in its message. On a public page,
    st.error(str(exc)) would leak that token to any visitor. Same pattern as
    main.py's error handling (see CLAUDE.md); never surface raw exception
    text on a page anyone can load.
    """
    print(f"[{context}] {type(exc).__name__}: {exc}")
    st.error(f"{context} failed -- check server logs for details.")

def check_shipping_agent(url=SHIPPING_AGENT_URL):
    try:
        import urllib.request
        with urllib.request.urlopen(f"{url}/.well-known/agent-card.json", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False

def render_trace(trace):
    if not trace:
        return
    seen = []
    for i, step in enumerate(trace):
        author = step.get("author", "unknown")
        if author not in seen:
            seen.append(author)
            if len(seen) > 1:
                st.info(f"Routed to **{author}**")
        if step["type"] == "tool_call":
            args = ", ".join(f"{k}={v!r}" for k, v in step.get("args", {}).items())
            st.warning(f"**{i+1}.** `{author}` called **{step['tool']}**({args[:200]})")
        elif step["type"] == "tool_response":
            st.success(f"**{i+1}.** `{author}` got result from **{step['tool']}**")
            if step.get("result"):
                st.code(step["result"][:500], language="json")
        elif step["type"] == "text" and step.get("text", "").strip():
            st.markdown(f"**{i+1}.** `{author}`: {step['text'][:300]}")

# --- Page Config ---

st.set_page_config(page_title="ADK Multi-Agent Systems", layout="wide")
st.markdown("<style>.block-container{padding-top:1.5rem;}</style>", unsafe_allow_html=True)

api_key = os.getenv("GOOGLE_API_KEY")
supa_token = os.getenv("SUPABASE_ACCESS_TOKEN")
supa_ref = os.getenv("SUPABASE_PROJECT_REF")
shipping_ok = check_shipping_agent()

# --- Sidebar ---

with st.sidebar:
    st.title("ADK Multi-Agent Systems")
    st.caption("Interactive Classroom Demo")
    page = st.radio("Navigate", ["Overview", "Demo 1: Routing", "Demo 2: MCP + Database", "Demo 3: Full System"], label_visibility="collapsed")
    st.markdown("---")
    st.markdown("### Status")
    if api_key:
        st.success("Google API Key")
    else:
        st.error("Google API Key -- not set")
    if supa_token and supa_ref:
        st.success("Supabase")
    else:
        st.warning("Supabase -- not configured")
    if shipping_ok:
        st.success("Shipping Agent (:8001)")
    else:
        st.info("Shipping Agent off -- optional (Demo 3 A2A)")
    if langfuse.auth_check():
        st.success("Langfuse Tracing")
    else:
        st.warning("Langfuse -- not connected")

# --- Overview ---

if page == "Overview":
    st.header("Building Multi-Agent AI Systems with ADK")
    st.markdown("Three progressive demos showing multi-agent system design using Google's Agent Development Kit.")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.subheader("Demo 1: Routing (Capstone)")
        st.markdown("Router agent delegates to benefits, clinical, and escalation specialists -- my healthcare capstone theme (stub data).\n\n**Pattern:** Router / Delegation")
    with col2:
        st.subheader("Demo 2: MCP (Capstone)")
        st.markdown("Agent connects to a live Supabase database via MCP -- real patients/claims/support_tickets tables, healthcare-themed, RLS enabled.\n\n**Pattern:** External tool discovery.")
    with col3:
        st.subheader("Demo 3: Full System")
        st.markdown("Combines routing + MCP (same real claims data as Demo 2) + A2A. Shipping stays generic -- package tracking isn't part of the capstone.\n\n**Pattern:** Cross-process communication.")

    st.markdown("---")
    st.subheader("Architecture")
    st.code("""
    User Query
        |
        v
    +-----------------------+
    |     Router Agent      |
    +---+-------+-------+--+
        |       |       |
        v       v       v
    +------+ +------+ +--------+
    |Billing| | Tech | |Shipping|
    +---+--+ +--+---+ +---+----+
        |       |          |
        v       v          v
    +------+ +------+ +--------+
    | MCP  | |Local | |  A2A   |
    |Server| |Tools | |Protocol|
    +---+--+ +------+ +---+----+
        |                  |
        v                  v
    +------+          +--------+
    |Supa- |          | Remote |
    | base |          | Agent  |
    +------+          +--------+
    """, language=None)

    st.markdown("---")
    st.subheader("Multi-Agent Patterns")
    for name, desc in {
        "Router / Delegation": "Router inspects the query and delegates to the right specialist via `sub_agents`.",
        "Sequential Pipeline": "Agents run in order: Draft -> Review -> Polish. Use `SequentialAgent`.",
        "Parallel Fan-Out": "Multiple agents process input simultaneously. Use `ParallelAgent`.",
        "Loop / Iterative Refinement": "Agent refines output until quality criteria are met. Use `LoopAgent`.",
    }.items():
        with st.expander(name):
            st.markdown(desc)

    st.subheader("Why Multi-Agent?")
    st.markdown(
        "| Single Agent | Multi-Agent |\n|---|---|\n"
        "| One massive prompt | Focused, modular agents |\n"
        "| Hard to test | Each agent testable independently |\n"
        "| Fragile | Swap or update agents independently |\n"
        "| Can't scale | Add specialists without rewriting |"
    )

# --- Demo 1 ---

elif page == "Demo 1: Routing":
    st.header("Demo 1: Multi-Agent Routing -- Healthcare Capstone")
    st.markdown("A **router agent** delegates to the right specialist based on the query. This is my capstone theme; the real Pinecone-backed version of the benefits job lives in `../week-1/adk_agent.py`.")

    with st.expander("Architecture"):
        st.code("""
    healthcare_router
      |--- benefits_agent   -> lookup_coverage, check_prior_authorization
      |--- clinical_agent   -> search_symptom_guidance, check_clinic_status
      |--- escalation_agent -> create_escalation_ticket
        """, language=None)

    if not api_key:
        st.error("Set GOOGLE_API_KEY in .env"); st.stop()

    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    query = None
    with col1:
        if st.button("Benefits Query", use_container_width=True):
            query = "I'm on Northwind Health Plus. What's my deductible, and does an MRI (code MRI-001) need prior authorization?"
    with col2:
        if st.button("Clinical Query", use_container_width=True):
            query = "I've had a headache since this morning, what should I do? Also is the downtown clinic open?"
    with col3:
        if st.button("Escalation Query", use_container_width=True):
            query = "I'm having chest pain and shortness of breath, I need help now."
    custom = st.text_input("Or type your own:", placeholder="e.g. What's my out-of-pocket max on Northwind Standard?")
    if st.button("Send", type="primary") and custom.strip():
        query = custom.strip()

    if query:
        st.markdown(f"**Query:** {query}")
        with st.spinner("Running..."):
            try:
                response, trace = run_agent_sync(router_agent, query, demo_label="demo1-routing")
                st.session_state["d1_resp"], st.session_state["d1_trace"], st.session_state["d1_q"] = response, trace, query
            except Exception as e:
                log_and_show_error(e, "Demo 1")

    if st.session_state.get("d1_resp"):
        st.markdown("---")
        st.markdown(f"**Query:** {st.session_state.get('d1_q', '')}")
        st.subheader("Response")
        st.markdown(st.session_state["d1_resp"])
        with st.expander("Agent Trace", expanded=True):
            render_trace(st.session_state.get("d1_trace", []))

# --- Demo 2 ---

elif page == "Demo 2: MCP + Database":
    st.header("Demo 2: MCP -- Real Database Access")
    st.caption("Healthcare capstone theme: real patients/claims/support_tickets tables in Supabase, RLS enabled.")
    st.markdown("The agent connects to a **live Supabase database** via MCP. Tools are auto-discovered at runtime.")

    with st.expander("Architecture"):
        st.code("claims_agent_mcp -> MCP Protocol -> Supabase MCP Server (npx) -> Supabase DB (patients/claims/support_tickets)", language=None)

    if not api_key:
        st.error("Set GOOGLE_API_KEY in .env"); st.stop()
    if not supa_token:
        st.error("Set SUPABASE_ACCESS_TOKEN and SUPABASE_PROJECT_REF in .env"); st.stop()

    st.markdown("---")
    col1, col2 = st.columns(2)
    query = None
    with col1:
        if st.button("Patient Lookup", use_container_width=True):
            query = "What claims does Bob Smith have? What's the total amount?"
    with col2:
        if st.button("Cross-Table Query", use_container_width=True):
            query = "Show all high-priority open support tickets with patient name and email."
    custom = st.text_input("Or type your own:", key="d2c", placeholder="e.g. What plan is Jane Doe on?")
    if st.button("Send", key="d2s", type="primary") and custom.strip():
        query = custom.strip()

    if query:
        st.markdown(f"**Query:** {query}")
        with st.spinner("Connecting to MCP + Supabase (may take 10-15s)..."):
            try:
                agent, err = create_mcp_claims_agent()
                if err:
                    st.error(err)
                else:
                    response, trace = run_agent_sync(agent, query, timeout=180, demo_label="demo2-mcp")
                    st.session_state["d2_resp"], st.session_state["d2_trace"], st.session_state["d2_q"] = response, trace, query
            except Exception as e:
                log_and_show_error(e, "Demo 2")

    if st.session_state.get("d2_resp"):
        st.markdown("---")
        st.markdown(f"**Query:** {st.session_state.get('d2_q', '')}")
        st.subheader("Response")
        st.markdown(st.session_state["d2_resp"])
        with st.expander("Agent Trace", expanded=True):
            render_trace(st.session_state.get("d2_trace", []))

# --- Demo 3 ---

elif page == "Demo 3: Full System":
    st.header("Demo 3: Full System -- Routing + MCP + A2A")
    st.caption("Healthcare capstone theme for claims (same Supabase data as Demo 2); shipping stays generic -- package tracking isn't part of the capstone.")
    st.markdown("Combines **routing** + **MCP** (Supabase) + **A2A** (remote shipping agent).")

    with st.expander("Architecture"):
        st.code("""
    Router -> claims_agent_mcp (MCP -> Supabase: patients/claims/support_tickets)
           -> technical_agent   (local tools)
           -> shipping_agent    (A2A -> localhost:8001)
        """, language=None)

    if not api_key:
        st.error("Set GOOGLE_API_KEY in .env"); st.stop()
    if not supa_token:
        st.warning("Supabase not configured -- claims lookup won't work.")
    if not shipping_ok:
        st.warning("Shipping agent not running. Start: `uvicorn shipping_agent:app --port 8001`")

    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    query = None
    with col1:
        if st.button("Claims (MCP)", use_container_width=True):
            query = "I'm Jane Doe (jane@example.com). What plan am I on? Show my recent claims."
    with col2:
        if st.button("Technical (Local)", use_container_width=True):
            query = "My app is slow. Is something wrong with your servers?"
    with col3:
        if st.button("Shipping (A2A)", use_container_width=True):
            query = "Where is my package for order ORD-1004?"
    custom = st.text_input("Or type your own:", key="d3c", placeholder="e.g. What claims does Bob Smith have?")
    if st.button("Send", key="d3s", type="primary") and custom.strip():
        query = custom.strip()

    if query:
        st.markdown(f"**Query:** {query}")
        with st.spinner("Running full system (15-20s)..."):
            try:
                agent, err = create_full_system_agent()
                if err:
                    st.error(err)
                else:
                    response, trace = run_agent_sync(agent, query, timeout=180, demo_label="demo3-full-system")
                    st.session_state["d3_resp"], st.session_state["d3_trace"], st.session_state["d3_q"] = response, trace, query
            except Exception as e:
                log_and_show_error(e, "Demo 3")

    if st.session_state.get("d3_resp"):
        st.markdown("---")
        st.markdown(f"**Query:** {st.session_state.get('d3_q', '')}")
        st.subheader("Response")
        st.markdown(st.session_state["d3_resp"])
        with st.expander("Agent Trace", expanded=True):
            render_trace(st.session_state.get("d3_trace", []))
