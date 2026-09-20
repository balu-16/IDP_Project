# QubitChat — Intelligent Document Chat

QubitChat is an intelligent document-analysis application for uploading PDFs and images, asking questions about document contents, and retrieving cited evidence. The React/Vite frontend is backed by a FastAPI service with Supabase, Gemini, ChromaDB, MiniLM embeddings, and optional Grover-inspired retrieval controls.

## Requirements

- Node.js 20 or later and npm
- Python 3.12 and pip
- Optional: Docker Compose, a Gemini API key, and Supabase project credentials

## Local development

Create local environment files from the checked-in examples. Add credentials only to these ignored local copies:

```sh
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

Run the API in one terminal:

```sh
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Run the frontend in another terminal:

```sh
cd frontend
npm ci
npm run dev
```

Set `VITE_API_BASE_URL=http://localhost:8000` in `frontend/.env`. The backend allows the local Vite origin by default. Add Gemini and Supabase values to the relevant local environment files as needed; never commit those files. The API documentation is available at `http://localhost:8000/docs` while the backend is running.

## Docker Compose

The checked-in Compose file builds both services locally:

```sh
cp .env.example .env
docker compose up --build
```

The frontend is served at `http://localhost:8080` and the API at `http://localhost:8000`. Add optional credentials to the local root `.env`. `docker-compose.deploy.example.yml` describes image-based deployment configuration; keep actual registry names and production origins in the ignored `docker-compose.deploy.local.yml`.

## Checks

```sh
(cd frontend && npm run lint && npm run build)
(cd backend && python -m pip install pytest && python -m pytest)
```

The research verification suite is in `research/test_research.py` and requires the research dependencies plus locally downloaded BEIR data. The manuscript source, figures, generated tables, and verified PDF are in `new_paper/`. Raw datasets and sealed run directories are intentionally not stored in this repository; the manuscript README describes the inputs needed to regenerate its tables.
