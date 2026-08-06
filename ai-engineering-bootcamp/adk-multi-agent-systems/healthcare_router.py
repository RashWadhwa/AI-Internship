"""
Healthcare Router: Multi-Agent Routing with ADK (Demo 1 -- healthcare capstone theme)
Run: python healthcare_router.py
"""

import asyncio
import os
from dotenv import load_dotenv

load_dotenv()  # must run before importing langfuse, so credentials are present

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

# --- Tools ---

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
    return {
        "overall": "operational",
        "clinics": {"downtown": "operational", "westside": "operational", "urgent_care": "high_volume"},
        "last_incident": "2026-02-08 -- Downtown clinic brief system outage (resolved)",
    }

def create_escalation_ticket(patient_id: str, symptom_summary: str, urgency: str) -> dict:
    """Create an escalation ticket routing a patient to a nurse or provider for review."""
    times = {"low": "48 hours", "medium": "24 hours", "high": "4 hours", "critical": "immediate -- call 911 or go to ER"}
    return {"ticket_id": "ESC-2026-0042", "urgency": urgency, "estimated_response": times.get(urgency, "24 hours")}

# --- Agents ---

benefits_agent = Agent(
    name="benefits_agent", model=MODEL,
    description="Handles benefits: plan coverage, deductibles, prior authorization.",
    instruction="You are a benefits specialist. Use lookup_coverage to explain plan details. Use check_prior_authorization for procedure questions.",
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
    instruction="You are a triage escalation specialist. Use create_escalation_ticket to route the patient to a human reviewer.",
    tools=[create_escalation_ticket],
)

root_agent = Agent(
    name="healthcare_router", model=MODEL,
    instruction="Route to benefits_agent, clinical_agent, or escalation_agent. Never answer directly.",
    sub_agents=[benefits_agent, clinical_agent, escalation_agent],
)

# --- Runner ---

@observe(name="route-healthcare-query", capture_input=False, capture_output=False)
async def ask(agent, message, user_id="user1"):
    service = InMemorySessionService()
    runner = Runner(agent=agent, app_name="demo", session_service=service)
    session = await service.create_session(app_name="demo", user_id=user_id)
    # capture_input=False above + explicit set here: the decorator would
    # otherwise capture *args (including the Agent object) as trace input.
    langfuse.update_current_span(input=message)
    content = types.Content(role="user", parts=[types.Part(text=message)])
    with propagate_attributes(
        user_id=user_id,
        session_id=session.id,
        tags=["demo1-routing", "healthcare-capstone"],
        environment=os.getenv("LANGFUSE_ENVIRONMENT", "development"),
    ):
        # Let the generator run to completion instead of `return`-ing the moment
        # we see a final response -- breaking out of an `async for` early forces
        # ADK's OpenTelemetry span to close from a different context, which
        # raises a harmless but noisy OpenTelemetry error.
        final_answer = "(no response)"
        async for event in runner.run_async(user_id=user_id, session_id=session.id, new_message=content):
            if event.is_final_response() and event.content and event.content.parts:
                final_answer = event.content.parts[0].text
    langfuse.update_current_span(output=final_answer)
    return final_answer

async def main():
    tests = [
        ("BENEFITS", "I'm on Northwind Health Plus. What's my deductible, and does an MRI (code MRI-001) need prior authorization?"),
        ("CLINICAL", "I've had a headache since this morning, what should I do? Also is the downtown clinic open?"),
        ("ESCALATION", "I'm having chest pain and shortness of breath, I need help now."),
    ]
    for label, query in tests:
        print(f"\n--- {label} ---")
        print(f"User: {query}\n")
        try:
            print(f"Agent: {await ask(root_agent, query)}\n")
        except Exception as exc:
            # A failed query (e.g. Gemini free-tier rate limit) shouldn't kill
            # the rest of the test run -- report it and move to the next one.
            print(f"Agent: [FAILED] {type(exc).__name__}: {exc}\n")
    langfuse.flush()  # short-lived script -- traces are lost if not flushed before exit

if __name__ == "__main__":
    asyncio.run(main())
