"""Minimal Streamlit UI for the RAG-backed `/ingest` and `/ask` endpoints.

The API is the source of truth: this page only calls /ingest and /ask and
renders their JSON responses. No chunking, embedding, or retrieval logic here.

Run:
  streamlit run rag_demo_page.py
"""

import json
import os

import httpx
import streamlit as st

WORKDIR_CMD = "ai-engineering-bootcamp-v2/week-1v2"


def call_json(method: str, url: str, payload: dict | None = None) -> tuple[int, dict | str]:
    try:
        if method == "POST":
            response = httpx.post(url, json=payload, timeout=120.0)
        else:
            response = httpx.get(url, params=payload, timeout=30.0)

        try:
            return response.status_code, response.json()
        except json.JSONDecodeError:
            return response.status_code, response.text
    except httpx.ConnectError:
        return 0, {"error": f"Cannot reach {url}. Check the API base URL in the sidebar."}
    except httpx.HTTPError as exc:
        return 0, {"error": str(exc)}


REFUSAL_PHRASE = "I don't have enough information to answer that."


def render_ask_result(data: dict | str) -> None:
    """Render an /ask response, detecting refusal from sources_needed or the exact refusal phrase.

    Pinecone always returns its top-k nearest vectors regardless of relevance (no similarity
    cutoff), so retrieved_chunk_ids is never empty even when nothing relevant was found — and the
    model doesn't reliably set sources_needed=true every time it refuses in the answer text. The
    phrase check is a second, more reliable signal since it's the exact wording the grounding
    prompt instructs the model to use when it refuses.
    """
    if not isinstance(data, dict) or "error" in data:
        st.error(data.get("error", "Request failed") if isinstance(data, dict) else data)
        return

    answer = data.get("answer", {})
    sources_needed = answer.get("sources_needed", False)
    chunk_ids = data.get("retrieved_chunk_ids", [])
    refused = sources_needed or not chunk_ids or REFUSAL_PHRASE in answer.get("answer", "")

    if refused:
        st.warning("⚠️ Refused — insufficient context in the vector store to answer confidently.")
    else:
        st.success("✅ Answered from retrieved context")

    st.markdown("### Answer")
    st.write(answer.get("answer", ""))
    st.caption(
        f"confidence: {answer.get('confidence')} | sources_needed: {sources_needed}"
    )

    st.markdown("### Citations")
    if chunk_ids:
        document_ids = sorted({chunk_id.rsplit("-", 1)[0] for chunk_id in chunk_ids})
        st.write("**Documents cited:** " + ", ".join(document_ids))
        st.write("**Chunk IDs:** " + ", ".join(chunk_ids))
    else:
        st.write("(none retrieved)")

    metric_cols = st.columns(4)
    metric_cols[0].metric("Model", str(data.get("model", "-")))
    metric_cols[1].metric("Tokens", str(data.get("tokens_used", "-")))
    metric_cols[2].metric("Latency", f"{data.get('latency_ms', '-')} ms")
    metric_cols[3].metric("Cost", f"${data.get('cost_usd', '-')}")

    with st.expander("Raw JSON"):
        st.json(data)


st.set_page_config(page_title="RAG Demo: /ingest + /ask", layout="centered")
st.title("RAG Demo: `/ingest` + `/ask`")

default_base_url = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
base_url = st.sidebar.text_input("API base URL", default_base_url).rstrip("/")

if st.sidebar.button("Check API health"):
    status, data = call_json("GET", f"{base_url}/health")
    st.sidebar.markdown(f"**HTTP {status}**" if status else "**Not connected**")
    st.sidebar.json(data)

st.sidebar.markdown("### Start the API")
st.sidebar.code(
    f"cd {WORKDIR_CMD}\n"
    "uvicorn main:app --host 127.0.0.1 --port 8000 --reload",
    language="bash",
)
st.sidebar.markdown("### Start this page")
st.sidebar.code(
    f"cd {WORKDIR_CMD}\nstreamlit run rag_demo_page.py",
    language="bash",
)

tab_ingest, tab_ask = st.tabs(["Ingest", "Ask"])

with tab_ingest:
    with st.form("ingest_form"):
        ingest_text = st.text_area("Text", height=200)
        document_id = st.text_input("document_id")
        source = st.text_input("source (optional)")
        ingest_submitted = st.form_submit_button("Ingest", type="primary")

    if ingest_submitted:
        payload = {"document_id": document_id, "text": ingest_text, "source": source or None}
        with st.spinner("Calling /ingest..."):
            status, data = call_json("POST", f"{base_url}/ingest", payload)
        st.markdown(f"**HTTP {status}**" if status else "**Request failed**")
        st.json(data)

with tab_ask:
    with st.form("ask_form"):
        question = st.text_area("Question", height=100)
        ask_submitted = st.form_submit_button("Ask", type="primary")

    if ask_submitted:
        with st.spinner("Calling /ask..."):
            status, data = call_json("POST", f"{base_url}/ask", {"question": question})
        st.markdown(f"**HTTP {status}**" if status else "**Request failed**")
        render_ask_result(data)
