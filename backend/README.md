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

## L6-guided GAS retrieval

Both `POST /api/v1/query` and `POST /api/chat` accept
`"retrieval": {"strategy": "l6_gas", "candidate_limit": 64, "top_k": 8, "seed": 0}`.
Omitting `top_k` for this strategy also selects eight; explicit incompatible
pool/output counts return 422. Smaller eligible pools return fewer sources.
The legacy strategies and their defaults remain available. `threshold` and
`shots` apply to legacy methods; the GAS profile uses its own bounded search.

The new strategy computes dense and BM25 scores across ready passages in the
authenticated session, scores a union of hybrid shortlists with pinned L6,
then uses baseline GAS and protected-prefix refinement. Multiple passages can
come from the same PDF. The first five baseline passages remain fixed; the
tail is ordered by L6 score. The application defaults are lexical weight
0.25 and diversity penalty 0.05. Benchmark settings and accuracy guarantees
are not transferred to uploaded PDFs.

The pinned reranker is `cross-encoder/ms-marco-MiniLM-L6-v2`, revision
`233902d25c440f23af6f7d6e94d2946bac0bee0a`. Provision that snapshot in the
default Hugging Face cache or `MODEL_CACHE_DIR` before using GAS. Request-time
loading is local-only; the service returns 503 if it is unavailable rather
than silently changing methods. Inputs exceeding 512 pair tokens return 422.
The model is loaded lazily, warmed once, and scored in the bounded executor.

Sources retain citation metadata and compatibility fields. `rank_score` is
the raw L6 logit for GAS; `l6_logit` and `normalized_relevance` expose its
separate representations, and `sampling_probability` is null. The final
ordering preserves the prefix, so it is not a global sort of these logits.
Chat provenance includes the actual method, separate baseline/refinement
results and termination reasons, classical simulator work, and stage timings.
`retrieval_time_ms` includes loading and warm-up when they occur;
`online_retrieval` excludes those two components. `pipeline_total` includes
query embedding plus the entire retrieval wall time, excluding answer generation.

The kernels implement phase marking and amplitude amplification in a compact
classical simulation, without physical-QPU or quantum-speedup claims. Their
origin records and parity tests are in `services/gas_selector/` and
`tests/test_l6_gas.py`.

After benchmark timing has finished, run the local-only inference smoke check:

```sh
QUBIT_TEST_L6=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  .venv/bin/python -m unittest discover -s tests -p test_l6_gas.py -k LocalL6Smoke -v
```
