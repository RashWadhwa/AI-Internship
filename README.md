# AI-Enginnering-Bootcamp

This repository contains my AI Engineering bootcamp work, organised week by week.
Below is a concise status update for each week and the next steps I plan to take.

## Week 1 — Typed `/ask` demo (complete)

I built a typed FastAPI `/ask` endpoint plus a small Streamlit UI that demonstrates
structured-model output, validation/retry guardrails, and basic observability.

Artifacts:

- API health check screenshot
	![healthCheck](ai-engineering-bootcamp-v2/week-1v2/images/healthCheck.png)
- Streamlit demo screenshots
	![output1](ai-engineering-bootcamp-v2/week-1v2/images/output1.png)
	![output2](ai-engineering-bootcamp-v2/week-1v2/images/output2.png)

See `ai-engineering-bootcamp-v2/week-1v2/README.md` for usage instructions and
PowerShell-based venv activation steps.

## Week 2 — Retrieval & Vector DBs (in progress)

Work this week focuses on Retrieval-Augmented Generation (RAG) and experimenting
with vector databases. Reference materials and the working notebook live in:

`ai-engineering-bootcamp-v2/week-2/rag-vector-databases/`


### Weekly README guidance

Each week's folder should include a `README.md` that briefly documents what was built,
how to run it, and any important artifacts or next steps. Use this checklist as a template:

- **One-line summary:** What I built this week and why it matters.
- **Quick start:** Minimal commands to create/activate the venv and run the project (PowerShell and Bash variants when relevant).
- **Artifacts:** Screenshots, notebooks, or links to important files produced that week.
- **Tests/smoke checks:** How to run any included smoke tests or sanity checks.
- **Notes / troubleshooting:** Common issues and quick fixes.
- **Next steps/deployment notes:** Short items for follow-up (e.g., deploy to Render.com).

Keeping a consistent weekly `README.md` makes the repository easier to review and
simplifies the final deployment and documentation pass.

## Deployment on Render.com

**Live URLs** (two separate Render services — easy to mix up, so labeled explicitly):

| Service | URL | What it is |
|---|---|---|
| **API** (FastAPI) | https://ai-engineering-bootcamp-u7ud.onrender.com | The actual backend. Swagger docs at [`/docs`](https://ai-engineering-bootcamp-u7ud.onrender.com/docs). Endpoints: `/health`, `/ask`, `/ingest`, `/debug/pinecone`, `/debug/retrieve`. |
| **Streamlit UI** | https://ai-eng-bootcamp-5khs.onrender.com | A browser frontend that calls the API above. Has no endpoints of its own — hitting any path (`/health`, `/debug/...`) just returns the Streamlit app shell, not JSON. |

Both are defined in [render.yaml](render.yaml) as `ai-engineering-api` and `ai-engineering-streamlit`, both deploying from the `main` branch, both rooted at `ai-engineering-bootcamp-v2/week-1v2`. Feature work happens on a branch (e.g. `add/render-manifest`) and only reaches these live URLs once merged into `main` and pushed — Render doesn't deploy unmerged branches.

- API service (FastAPI)
	- **Root Directory:** `ai-engineering-bootcamp-v2/week-1v2`
	- **Build Command:** `python -m pip install --upgrade pip setuptools wheel && pip install -r requirements.txt`
	- **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
	- **Notes:** I added a nested `Procfile` in the week folder so Render can detect the app when the Root Directory is set.

- Streamlit demo (UI)
	- **Root Directory:** `ai-engineering-bootcamp-v2/week-1v2` (create a separate Render service pointing to the same folder)
	- **Build Command:** same as API (install requirements)
	- **Start Command:** `streamlit run demo_page.py --server.port $PORT --server.address 0.0.0.0`
	- **Notes:** I added `start_streamlit.sh` to the folder; you can use it as the Start Command (`sh start_streamlit.sh`) or paste the command above. There's also `rag_demo_page.py`, a second Streamlit page for the `/ingest` + `/ask` RAG flow specifically — not wired into `start_streamlit.sh` yet, so it currently only runs locally (`streamlit run rag_demo_page.py`), pointed at the API URL above via the sidebar or `API_BASE_URL` env var.

Common tips:

- Use `0.0.0.0` and `$PORT` (bash-style) in Render start commands. Do not use PowerShell `$env:PORT` in Render settings.
- If a dependency fails to build, upgrade pip/setuptools/wheel in the Build Command (see above).
- The repo includes `runtime.txt` to pin Python to a compatible version on Render.


![alt text](retrieval.png)



