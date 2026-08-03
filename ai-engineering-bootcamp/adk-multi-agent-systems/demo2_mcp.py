"""
Demo 2: MCP -- Agent with Real Database Access (Supabase)
Run: python demo2_mcp.py

Healthcare capstone theme: the Supabase project backing this has
patients/claims/support_tickets tables (created + seeded via the MCP
server's apply_migration/execute_sql tools -- see
../week-1/README.md or CLAUDE.md for the schema).
"""

import asyncio
import os
import sys
from dotenv import load_dotenv

load_dotenv()

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
# Top-level google.adk.tools.mcp_tool doesn't re-export these in installed
# google-adk 2.6.1 -- import from the actual submodules instead.
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from google.genai import types
from mcp.client.stdio import StdioServerParameters

# "gemini-2.5-flash" 404s ("no longer available to new users") for a fresh
# GOOGLE_API_KEY. "gemini-2.0-flash"/"gemini-2.5-flash-lite" both hit hard
# free-tier walls (limit 0 / 404) on this key too. "gemini-3.1-flash-lite"
# is a stable (non-"-latest") pinned model confirmed to have working quota.
MODEL = "gemini-3.1-flash-lite"
TOKEN = os.getenv("SUPABASE_ACCESS_TOKEN", "")
PROJECT_REF = os.getenv("SUPABASE_PROJECT_REF", "")
# Secure by default: read-only unless explicitly disabled. This agent takes
# free-text input from whoever is talking to it -- on a deployed/public
# instance that could be anyone, so the MCP server must not be able to run
# apply_migration/execute_sql/delete_branch/etc. against the real project.
SUPABASE_READ_ONLY = os.getenv("SUPABASE_READ_ONLY", "true").strip().lower() != "false"

if not TOKEN:
    sys.exit("Set SUPABASE_ACCESS_TOKEN in .env (https://supabase.com/dashboard/account/tokens)")

# --- MCP Toolset (launches Supabase MCP server as subprocess) ---

mcp_args = ["-y", "@supabase/mcp-server-supabase@latest", "--access-token", TOKEN]
if PROJECT_REF:
    mcp_args += ["--project-ref", PROJECT_REF]
if SUPABASE_READ_ONLY:
    mcp_args += ["--read-only"]

supabase_mcp = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(command="npx", args=mcp_args),
        timeout=30.0,
    ),
    # Belt-and-suspenders on top of --read-only: verified --read-only blocks
    # execute_sql/apply_migration writes at the DB/app level, but tools like
    # deploy_edge_function/delete_branch/create_branch weren't individually
    # confirmed to respect it. Restricting the exposed tool set makes that
    # moot -- this agent only ever needs to read data and inspect schema.
    tool_filter=["list_tables", "execute_sql", "get_advisors", "search_docs"],
)

# --- Agent ---

billing_agent = Agent(
    name="claims_agent_mcp", model=MODEL,
    instruction="You are a healthcare claims and billing specialist with real database access. "
                "Use MCP tools to query the patients, claims, and support_tickets tables. "
                "Always look up the patient first.",
    tools=[supabase_mcp],
)

# --- Runner ---

async def ask(agent, message):
    service = InMemorySessionService()
    runner = Runner(agent=agent, app_name="demo", session_service=service)
    session = await service.create_session(app_name="demo", user_id="user1")
    content = types.Content(role="user", parts=[types.Part(text=message)])
    # Let the generator run to completion instead of `return`-ing the moment we
    # see a final response -- breaking out of an `async for` early forces ADK's
    # tracing span to close from a different context, which raises a harmless
    # but noisy OpenTelemetry error.
    final_answer = "(no response)"
    async for event in runner.run_async(user_id="user1", session_id=session.id, new_message=content):
        if event.is_final_response() and event.content and event.content.parts:
            final_answer = event.content.parts[0].text
    return final_answer

async def main():
    tests = [
        ("PATIENT LOOKUP", "What claims does Bob Smith have? What's the total amount?"),
        ("CROSS-TABLE QUERY", "Show me all high-priority open support tickets with patient name and email."),
    ]
    for label, query in tests:
        print(f"\n--- {label} ---")
        print(f"User: {query}\n")
        try:
            print(f"Agent: {await ask(billing_agent, query)}\n")
        except Exception as exc:
            print(f"Agent: [FAILED] {type(exc).__name__}: {exc}\n")

if __name__ == "__main__":
    asyncio.run(main())
