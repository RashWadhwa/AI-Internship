"""
ADK Capstone Agent: Benefits Coverage Assistant (real RAG, wired to Pinecone)

Sibling entry point to main.py -- does NOT touch main.py's existing /ask
endpoint (OpenAI-based, already deployed). Pattern copied from
../adk-multi-agent-systems/capstone_agent.py (itself copied from
demo1_routing.py): same Agent(...) fields, same ask()/main() Runner harness,
same THINK/ACT/OBSERVE event logging, same MAX_STEPS cap. The only real
change from capstone_agent.py: search_benefits_documents is no longer a
stub -- it calls vectorstore.query_similar() and hits the same Northwind
Pinecone index main.py's /ask endpoint already queries.

Single agent, no router: this is still one job (answer a benefits coverage
question from retrieved plan text), so there's no sub_agents split here --
see ../adk-multi-agent-systems/demo1_routing.py if a second job (e.g.
appointment scheduling) later needs one.

Run: python adk_agent.py
Needs GOOGLE_API_KEY (Gemini) in addition to the OPENAI_API_KEY/
PINECONE_API_KEY that vectorstore.py already requires for embeddings and
retrieval -- add GOOGLE_API_KEY to the repo-root .env alongside those two;
it currently only exists in adk-multi-agent-systems/.env, which this
script's dotenv walk (THIS_DIR -> parent -> parent.parent) does not reach.
"""

import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

THIS_DIR = Path(__file__).resolve().parent
load_dotenv(THIS_DIR / ".env")
load_dotenv(THIS_DIR.parent / ".env")
load_dotenv(THIS_DIR.parent.parent / ".env")

from vectorstore import query_similar  # noqa: E402

logger = logging.getLogger(__name__)

# "gemini-2.5-flash" (used in the adk-multi-agent-systems demos) 404s for
# this API key -- Google restricts it from new keys as of 2026.
# "gemini-2.0-flash"/"gemini-2.5-flash-lite" both hit hard free-tier walls
# (limit 0 / 404) on this key too. "gemini-3.1-flash-lite" is a stable
# (non-"-latest") pinned model confirmed to have working quota. A Google AI
# Pro subscription doesn't change this -- API quota comes from whether the
# Cloud project behind GOOGLE_API_KEY has billing enabled, a separate system.
MODEL = "gemini-3.1-flash-lite"
RAG_TOP_K = 5

# Hard cap on stream events (tool calls + responses + text) per question, so a
# model stuck re-searching (or a broken tool) can't loop forever.
MAX_STEPS = 6

# --- Tools ---

def search_benefits_documents(query: str) -> dict:
    """Search the real Northwind benefits Pinecone index for text relevant to the query.

    Call this whenever the member's question involves plan coverage, deductibles,
    or prior-authorization rules -- it is the only source of truth this agent is
    allowed to answer from. Returns the top matching chunks with their
    document_id and score, so the agent can cite sources the same way main.py's
    /ask endpoint does. On failure, returns {"error": ...} instead of raising,
    so the model sees the failure as an observation and can react to it (per
    main.py's existing error-handling pattern: log the real exception
    server-side, never surface raw exception text -- see CLAUDE.md).
    """
    try:
        matches = query_similar(query, top_k=RAG_TOP_K)
    except Exception:
        logger.exception("Benefits document search failed for query=%r", query)
        return {"error": "Benefits document search is temporarily unavailable. Try again shortly."}

    return {
        "results": [
            {
                "document_id": (match["metadata"] or {}).get("document_id"),
                "chunk_text": (match["metadata"] or {}).get("text"),
                "score": match["score"],
            }
            for match in matches
        ]
    }

# --- Agent ---

root_agent = Agent(
    name="benefits_coverage_agent",
    model=MODEL,
    description="Answers a Northwind health plan member's benefits questions using the real plan-document index.",
    instruction="""You are a Northwind Health benefits assistant for plan members.

GOAL: Answer the member's question about their plan's coverage, deductible, or
prior-authorization requirements, using ONLY information returned by the
search_benefits_documents tool.

HOW TO WORK:
1. Call search_benefits_documents with a short, specific query drawn from the
   member's question.
2. Look through the returned results (ranked by score) for text that answers
   the question. If nothing returned is relevant, you may call the tool again
   with a refined query -- at most 2 searches total.
3. Compose a final answer that cites which document (document_id) the
   information came from.

CONSTRAINTS:
- Never invent coverage details that are not in the tool results.
- Do not answer questions unrelated to Northwind health plan benefits.
- If a tool call returns an "error" field, that means the search itself
  failed (not "no matching coverage"). Retry at most once; if it errors
  again, tell the member you're temporarily unable to search plan documents
  and to try again shortly -- do not guess an answer.

DONE means you have produced a final answer that either:
(a) directly answers the question with a document_id citation, or
(b) states plainly "I don't have enough information in the plan documents to
    answer that" if your searches didn't turn up an answer, or
(c) reports a temporary search failure per the CONSTRAINTS above.
Stop as soon as (a), (b), or (c) is true -- do not keep searching after that.""",
    tools=[search_benefits_documents],
)

# --- Runner with Think / Act / Observe logging ---


def log_event(step: int, event) -> None:
    """Print each event as THINK (model text), ACT (tool call), or OBSERVE (tool result)."""
    if not event.content or not event.content.parts:
        return
    for part in event.content.parts:
        if getattr(part, "function_call", None):
            fc = part.function_call
            print(f"[{step}] ACT     -> {fc.name}(args={dict(fc.args or {})})")
        elif getattr(part, "function_response", None):
            fr = part.function_response
            print(f"[{step}] OBSERVE <- {fr.name} returned: {fr.response}")
        elif getattr(part, "text", None):
            label = "FINAL" if event.is_final_response() else "THINK"
            print(f"[{step}] {label:<7} {part.text}")


async def ask(agent, message, max_steps: int = MAX_STEPS) -> str:
    service = InMemorySessionService()
    runner = Runner(agent=agent, app_name="capstone_demo", session_service=service)
    session = await service.create_session(app_name="capstone_demo", user_id="member1")
    content = types.Content(role="user", parts=[types.Part(text=message)])

    step = 0
    final_answer = None
    # Let the generator run to completion instead of `return`-ing the moment we
    # see a final response -- breaking out of an `async for` early forces ADK's
    # tracing span to close from a different context, which raises a harmless
    # but noisy OpenTelemetry error. Only the (rare) step-limit path breaks
    # early, since that's a genuine abort, not a clean finish.
    async for event in runner.run_async(
        user_id="member1", session_id=session.id, new_message=content
    ):
        step += 1
        log_event(step, event)

        if final_answer is None and event.is_final_response() and event.content and event.content.parts:
            final_answer = event.content.parts[0].text

        if step >= max_steps:
            print(f"[STEP LIMIT] Stopping after {max_steps} steps to avoid an infinite loop.")
            break

    if final_answer is not None:
        return final_answer
    return "(no final answer within step limit)" if step >= max_steps else "(no response)"


async def main():
    tests = [
        "What's my annual deductible on the Health Plus plan?",
        "Does an MRI need prior authorization?",
    ]
    for query in tests:
        print(f"\n--- User: {query} ---")
        answer = await ask(root_agent, query)
        print(f"\nAgent: {answer}\n")


if __name__ == "__main__":
    asyncio.run(main())
