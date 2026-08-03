# Render's native Python runtime has no Node.js, but the Supabase MCP
# server (Demo 2/3) launches via `npx` -- so this service needs Docker
# instead of env: python.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render sets $PORT at runtime; shell form (not exec/JSON array) so it expands.
CMD streamlit run streamlit_app.py --server.port $PORT --server.address 0.0.0.0
