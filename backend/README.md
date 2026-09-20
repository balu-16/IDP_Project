# QubitChat API

FastAPI backend for document ingestion, retrieval, and answer generation. It uses ChromaDB for local vector storage, MiniLM embeddings, optional OCR through Tesseract, Supabase configuration, and Gemini for generated responses.

## Requirements

- Python 3.12 and pip
- Tesseract OCR installed on the host when processing scanned documents
- Gemini and Supabase credentials for the corresponding integrated features

## Local setup

From the repository root:

```sh
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Set credentials in `backend/.env` as needed. The file is ignored by Git. Local Chroma data, model cache, and uploaded documents are runtime data and must not be committed.

Start the API from the `backend/` directory:

```sh
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Interactive API documentation is served at `http://localhost:8000/docs`; the registered routes are the source of truth for the current API surface.

## Tests

Run backend tests from this directory:

```sh
python -m pip install pytest
python -m pytest
```

The repository-root research suite is separate and uses the `research/` modules and locally cached BEIR data.
