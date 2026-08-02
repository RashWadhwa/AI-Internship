"""Evaluate POST /ask against 5 known-answer Northwind questions.

Tracks per question:
  retrieval_hit - did a chunk from the expected source document get retrieved?
  correctness   - do the expected key facts appear in the generated answer?
  faithfulness  - is every claim in the answer supported by the retrieved context? (LLM-judged)

Requires the API running locally first:
  uvicorn main:app --host 127.0.0.1 --port 8000 --reload

Then:
  python eval_northwind.py
"""

import json
from dataclasses import dataclass

import httpx
from openai import OpenAI
from pydantic import BaseModel, Field

BASE_URL = "http://127.0.0.1:8000"


@dataclass
class KnownAnswerQuestion:
    question: str
    expected_document_id: str
    # answer counts as "correct" if it contains every fact from at least one of these sets.
    # more than one set means the source document itself states conflicting figures.
    accepted_fact_sets: list[list[str]]


QUESTIONS = [
    KnownAnswerQuestion(
        question="What is the calendar year deductible for the Northwind Standard plan?",
        expected_document_id="northwind-standard-benefits-details",
        accepted_fact_sets=[["$2,000", "$4,000"]],
    ),
    KnownAnswerQuestion(
        question="What is the out-of-pocket maximum for the Northwind Standard plan?",
        expected_document_id="northwind-standard-benefits-details",
        # the source PDF states this figure twice, inconsistently: $6,000 early on,
        # then $6,350 / $12,700 later in an "IMPORTANT PLAN INFORMATION" section.
        accepted_fact_sets=[["$6,000"], ["$6,350", "$12,700"]],
    ),
    KnownAnswerQuestion(
        question="What is the prescription drug deductible under the Northwind Standard plan?",
        expected_document_id="northwind-standard-benefits-details",
        accepted_fact_sets=[["$250", "$500"]],
    ),
    KnownAnswerQuestion(
        question="What is the in-network copayment for a primary care visit under Northwind Health Plus?",
        expected_document_id="northwind-health-plus-benefits-details",
        accepted_fact_sets=[["$20"]],
    ),
    KnownAnswerQuestion(
        question="What is the in-network calendar year deductible for the Northwind Health Plus plan?",
        expected_document_id="northwind-health-plus-benefits-details",
        accepted_fact_sets=[["$1,500", "$3,000"]],
    ),
]


class FaithfulnessJudgment(BaseModel):
    faithful: bool
    reasoning: str = Field(max_length=300)


FAITHFULNESS_PROMPT = """You are checking a RAG answer for hallucination.

CONTEXT (the only source the answer is allowed to use):
{context}

ANSWER:
{answer}

Is every factual claim in the ANSWER supported by the CONTEXT? Respond faithful=true only if \
nothing in the ANSWER goes beyond what the CONTEXT states. Respond faithful=false if the ANSWER \
includes any claim not backed by the CONTEXT."""


def judge_faithfulness(client: OpenAI, context: str, answer: str) -> FaithfulnessJudgment:
    completion = client.chat.completions.parse(
        model="gpt-4o-mini",
        messages=[
            {"role": "user", "content": FAITHFULNESS_PROMPT.format(context=context, answer=answer)}
        ],
        response_format=FaithfulnessJudgment,
    )
    return completion.choices[0].message.parsed


def main() -> None:
    client = OpenAI()
    results = []

    with httpx.Client(timeout=60.0) as http_client:
        for qa in QUESTIONS:
            ask_resp = http_client.post(f"{BASE_URL}/ask", json={"question": qa.question})
            ask_resp.raise_for_status()
            ask_data = ask_resp.json()
            answer_text = ask_data["answer"]["answer"]
            retrieved_chunk_ids = ask_data["retrieved_chunk_ids"]

            retrieval_hit = any(
                chunk_id.startswith(f"{qa.expected_document_id}-")
                for chunk_id in retrieved_chunk_ids
            )
            correctness = any(
                all(fact in answer_text for fact in fact_set)
                for fact_set in qa.accepted_fact_sets
            )

            retrieve_resp = http_client.get(
                f"{BASE_URL}/debug/retrieve", params={"q": qa.question, "top_k": 5}
            )
            retrieve_resp.raise_for_status()
            context = "\n\n".join(
                f"[{r['document_id']}]: {r['text']}" for r in retrieve_resp.json()["results"]
            )
            judgment = judge_faithfulness(client, context, answer_text)

            results.append(
                {
                    "question": qa.question,
                    "answer": answer_text,
                    "expected_document_id": qa.expected_document_id,
                    "retrieved_chunk_ids": retrieved_chunk_ids,
                    "retrieval_hit": retrieval_hit,
                    "correctness": correctness,
                    "faithful": judgment.faithful,
                    "faithfulness_reasoning": judgment.reasoning,
                }
            )

            print(f"Q: {qa.question}")
            print(f"A: {answer_text}")
            print(
                f"retrieval_hit={retrieval_hit}  correctness={correctness}  "
                f"faithful={judgment.faithful}"
            )
            print()

    n = len(results)
    hits = sum(r["retrieval_hit"] for r in results)
    correct = sum(r["correctness"] for r in results)
    faithful = sum(r["faithful"] for r in results)

    print("=== Summary ===")
    print(f"Retrieval hit rate: {hits}/{n}")
    print(f"Correctness rate:   {correct}/{n}")
    print(f"Faithfulness rate:  {faithful}/{n}")

    with open("eval_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nFull results written to eval_results.json")


if __name__ == "__main__":
    main()
