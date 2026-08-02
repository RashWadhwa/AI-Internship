"""
Capstone Agent: Benefits Coverage Assistant (single agent, multi-step)

Patterns copied from demo1_routing.py: load_dotenv() + MODEL constant, the
tool-function shape (typed args, docstring, dict return), the Agent(...)
constructor fields (name/model/description/instruction/tools), and the
ask()/main() Runner + InMemorySessionService harness. Unlike demo1, this is
ONE agent with no sub_agents/router -- the job (answer a benefits question by
searching plan documents, possibly re-searching once, then citing a source or
refusing) is a single multi-step loop, not a dispatch-to-specialist problem.

Run: python capstone_agent.py
"""

import asyncio
from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

load_dotenv()

# "gemini-2.5-flash" 404s ("no longer available to new users") for a fresh
# GOOGLE_API_KEY. "gemini-2.0-flash"/"gemini-2.5-flash-lite" both hit hard
# free-tier walls (limit 0 / 404) on this key too. "gemini-3.1-flash-lite"
# is a stable (non-"-latest") pinned model confirmed to have working quota.
MODEL = "gemini-3.1-flash-lite"

# Hard cap on stream events (tool calls + responses + text) per question, so a
# model stuck re-searching (or a broken tool) can't loop forever.
MAX_STEPS = 6

# --- Tools ---
# Placeholder only. Next step: replace this with a real call to
# ../week-1/vectorstore.py's query_similar(), so results come from the actual
# Northwind Pinecone index instead of this stub.

def search_benefits_documents(query: str) -> dict:
    """Search Northwind plan documents for text relevant to the query.

    Placeholder implementation -- returns one canned snippet regardless of
    query. Will be replaced by a real Pinecone similarity search.
    """
    return {
        "document_id": "northwind-health-plus",
        "chunk_text": (
            "Northwind Health Plus: annual deductible $500. Most outpatient "
            "procedures do not require prior authorization; imaging (MRI, "
            "CT) and inpatient admissions do."
        ),
    }

# --- Agent ---

root_agent = Agent(
    name="benefits_coverage_agent",
    model=MODEL,
    description="Answers a Northwind health plan member's benefits questions using only retrieved plan documents.",
    instruction="""You are a Northwind Health benefits assistant for plan members.

GOAL: Answer the member's question about their plan's coverage, deductible, or
prior-authorization requirements, using ONLY information returned by the
search_benefits_documents tool.

HOW TO WORK:
1. Call search_benefits_documents with a short, specific query drawn from the
   member's question.
2. If the result doesn't fully answer the question, you may call it again
   with a refined query -- at most 2 searches total.
3. Compose a final answer that cites which document (document_id) the
   information came from.

CONSTRAINTS:
- Never invent coverage details that are not in the tool results.
- Do not answer questions unrelated to Northwind health plan benefits.

DONE means you have produced a final answer that either:
(a) directly answers the question with a document_id citation, or
(b) states plainly "I don't have enough information in the plan documents to
    answer that" if your searches didn't turn up an answer.
Stop as soon as (a) or (b) is true -- do not keep searching after that.""",
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

    return "(no response)"


async def main():
    tests = [
        "I'm on Northwind Health Plus. What's my annual deductible?",
        "Does an MRI need prior authorization on my plan?",
    ]
    for query in tests:
        print(f"\n--- User: {query} ---")
        answer = await ask(root_agent, query)
        print(f"\nAgent: {answer}\n")


if __name__ == "__main__":
    asyncio.run(main())
