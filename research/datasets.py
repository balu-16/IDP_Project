"""BEIR-format loaders + chunk->parent aggregation (plan A.2).

Real data: official BEIR layout under research/data/<name>/, matching
https://github.com/beir-cellar/beir/blob/main/beir/datasets/data_loader.py :
  corpus.jsonl            {_id, title, text}  (`id` accepted for compat)
  queries.jsonl  OR  queries/<split>.tsv + qrels/<split>.tsv with header
    query-id <tab> corpus-id <tab> score   (BEIR official uses qrels/test.tsv)
  queries.json  (HF beir export) also accepted.
Download once via BEIR, then runs work offline. Hashes frozen in manifest.

Synthetic: deterministic fixture for unit tests and offline smoke runs.
Aggregation: max chunk score per parent doc, deduplicated. Never infer
chunk relevance from parent judgments.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
from pathlib import Path

DATA_ROOT = Path(__file__).resolve().parent / "data"

# Canonical BEIR ids. `nqcorpus` retained as deprecated alias for `nfcorpus`.
DATASET_ALIASES = {"nqcorpus": "nfcorpus", "nfcorpus": "nfcorpus", "scifact": "scifact"}


def normalize_text(text: str) -> str:
    """Apply the deterministic normalization used by official runs."""
    value = unicodedata.normalize("NFKC", str(text or ""))
    return re.sub(r"\s+", " ", value).strip()


def canonical_dataset(name: str) -> str:
    key = name.strip().lower()
    if key not in DATASET_ALIASES:
        raise ValueError(f"Unknown dataset {name!r}; expected one of {sorted(set(DATASET_ALIASES.values()))}")
    return DATASET_ALIASES[key]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_corpus(base: Path) -> dict[str, str]:
    corpus_p = base / "corpus.jsonl"
    if not corpus_p.exists():
        raise FileNotFoundError(f"BEIR corpus missing: {corpus_p}")
    corpus = {}
    with open(corpus_p) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            did = row.get("_id", row.get("id"))
            if did is None:
                raise ValueError(f"Corpus row missing _id/id in {corpus_p}")
            corpus[str(did)] = normalize_text(f"{row.get('title', '')} {row.get('text', '')}")
    return corpus


def _load_queries(base: Path, split: str) -> dict[str, str]:
    # Preferred official: queries/<split>.tsv or queries.jsonl / queries.<split>.jsonl / queries.json
    candidates = [
        base / f"queries.{split}.jsonl",
        base / "queries.jsonl",
        base / "queries.json",
        base / "queries" / f"{split}.tsv",
    ]
    for path in candidates:
        if not path.exists():
            continue
        queries: dict[str, str] = {}
        with open(path) as f:
            if path.suffix == ".json":
                rows = json.load(f)
                items = rows.items() if isinstance(rows, dict) else rows
                for row in (items if isinstance(rows, list) else []):
                    if isinstance(row, dict):
                        qid = row.get("_id", row.get("id"))
                        queries[str(qid)] = normalize_text(row.get("text", ""))
                    else:
                        pass
                if isinstance(rows, dict):
                    queries = {str(k): normalize_text(v) for k, v in rows.items()}
                return queries
            if path.suffix == ".tsv":
                reader = csv.reader(f, delimiter="\t")
                for row in reader:
                    if not row or row[0].startswith("query-id"):
                        continue
                    if len(row) >= 2:
                        queries[row[0].strip()] = normalize_text(row[1])
                return queries
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                qid = row.get("_id", row.get("id"))
                if qid is None:
                    raise ValueError(f"Query row missing _id/id in {path}")
                queries[str(qid)] = normalize_text(row.get("text", ""))
        return queries
    raise FileNotFoundError(f"BEIR queries missing for split {split!r} under {base}")


def _load_qrels(base: Path, split: str) -> dict[str, dict[str, int]]:
    # Official BEIR: qrels/<split>.tsv with header; legacy flat qrels.<split>.tsv accepted.
    candidates = [base / "qrels" / f"{split}.tsv", base / f"qrels.{split}.tsv"]
    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        raise FileNotFoundError(f"BEIR qrels missing for split {split!r} under {base}")
    qrels: dict[str, dict[str, int]] = {}
    with open(path) as f:
        reader = csv.reader(f, delimiter="\t")
        for row in reader:
            if not row:
                continue
            # Skip header variants: query-id / qid / query_id
            if row[0].strip().lower().replace("_", "-") in {"query-id", "qid", "queryid"}:
                continue
            if len(row) < 3:
                continue
            qid, did, score = row[0].strip(), row[1].strip(), int(float(row[2]))
            if score > 0:
                qrels.setdefault(qid, {})[did] = score
    return qrels


def load_beir(name: str, split: str = "test"):
    """Load (corpus, queries, qrels) for a cached BEIR dataset.

    Returns dicts: corpus {doc_id: text}, queries {qid: text},
    qrels {qid: {doc_id: int_score}}. Raises FileNotFoundError if not cached.
    Canonical ids (scifact/nfcorpus, nqcorpus alias) are enforced unless
    DATA_ROOT/<name> exists directly (test fixtures).
    """
    base = DATA_ROOT / name
    if base.exists():
        canonical = name
    else:
        canonical = canonical_dataset(name)
        base = DATA_ROOT / canonical
    corpus = _load_corpus(base)
    queries = _load_queries(base, split)
    qrels = _load_qrels(base, split)
    return corpus, queries, qrels


def _filter_to_qrels(queries: dict[str, str], qrels: dict[str, dict[str, int]]):
    """Keep only queries with judgments (official BEIR behavior).

    Shared query files contain many queries without test judgments; scoring
    them as zero corrupts averages. Returns filtered (queries, qrels) with
    qrels restricted to surviving queries.
    """
    kept = {qid: queries[qid] for qid in queries if qid in qrels and qrels[qid]}
    return kept, {qid: qrels[qid] for qid in kept}


def scifact_train_sample(train_queries: dict[str, str], train_qrels: dict[str, dict[str, int]],
                         frac: float = 0.2):
    """Deterministic 20% SciFact train subset via SHA-256 ordering.

    Key `20260911:scifact:<query_id>`; never touches test judgments.
    """
    scored = sorted(train_queries, key=lambda q: hashlib.sha256(f"20260911:scifact:{q}".encode()).hexdigest())
    n = max(1, int(len(scored) * frac))
    subset = scored[:n]
    return {q: train_queries[q] for q in subset}, {q: train_qrels[q] for q in subset if q in train_qrels}


def deterministic_query_subset(query_ids, dataset: str, count: int,
                                version: str = "beir-test-subset-v1") -> list[str]:
    """Select a stable pseudo-random subset using only query IDs.

    This helper is for predeclared secondary/resource samples. The selected
    IDs must be persisted in the run manifest and reused across methods.
    """
    ids = sorted({str(qid) for qid in query_ids})
    if count < 0 or count > len(ids):
        raise ValueError(f"subset count {count} outside [0, {len(ids)}]")
    prefix = f"{version}|{dataset}|"
    return sorted(ids, key=lambda qid: hashlib.sha256(
        f"{prefix}{qid}".encode("utf-8")).hexdigest())[:count]


def load_splits(name: str):
    """Load (corpus, dev_queries, dev_qrels, test_queries, test_qrels).

    Tuning and test judgments are kept separate: nfcorpus uses its official
    dev split plus test, while scifact uses a deterministic train-derived
    sample plus test. Queries are filtered to split qrels and test counts are
    enforced (300/323).
    """
    from .config_frozen import DATASETS as _D

    canonical = canonical_dataset(name)
    base = DATA_ROOT / canonical
    corpus = _load_corpus(base)
    dev_split = "dev" if canonical == "nfcorpus" else "train"
    try:
        dev_queries_raw = _load_queries(base, dev_split)
        dev_qrels_raw = _load_qrels(base, dev_split)
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"Development data required for {canonical} ({dev_split} split): {exc}. "
            "Download the full BEIR archive; tuning without dev judgments is not allowed.") from exc
    test_queries_raw = _load_queries(base, "test")
    test_qrels_raw = _load_qrels(base, "test")
    # Filter to judged queries (official behavior).
    test_queries, test_qrels = _filter_to_qrels(test_queries_raw, test_qrels_raw)
    if canonical == "scifact":
        dev_queries, dev_qrels = _filter_to_qrels(dev_queries_raw, dev_qrels_raw)
        dev_queries, dev_qrels = scifact_train_sample(dev_queries, dev_qrels)
    else:
        dev_queries, dev_qrels = _filter_to_qrels(dev_queries_raw, dev_qrels_raw)
    if not dev_queries or not dev_qrels:
        raise ValueError(f"{canonical} development data empty after qrels filtering; "
                         "refusing to tune without judgments")
    expected = _D[canonical]["test_queries"]
    if len(test_queries) != expected:
        raise ValueError(f"{canonical} test queries: expected {expected}, got {len(test_queries)} "
                         f"(filter to qrels, check cache completeness)")
    return corpus, dev_queries, dev_qrels, test_queries, test_qrels


def synthetic_fixture(n_docs: int = 40, n_queries: int = 8, seed: int = 0):
    """Deterministic toy corpus for unit tests. Parent-level judgments."""
    rng = __import__("numpy").random.default_rng(seed)
    vocab = [f"term{i}" for i in range(60)]
    corpus = {}
    for d in range(n_docs):
        words = rng.choice(vocab, size=30).tolist()
        # Plant query-relevant terms so retrieval is non-trivial.
        words[:5] = [f"query{q % n_queries}" for q in range(5)]
        corpus[f"D{d}"] = " ".join(words + [f"query{d % n_queries}"])
    queries = {f"Q{q}": f"query{q}" for q in range(n_queries)}
    qrels = {f"Q{q}": {f"D{d}": 1 for d in range(n_docs) if d % n_queries == q} for q in range(n_queries)}
    return corpus, queries, qrels


def synthetic_splits(n_docs: int = 48, n_dev: int = 4, n_test: int = 8, seed: int = 0):
    """Disjoint dev/test synthetic pools so tuning never consumes test queries.

    Dev queries QDEV* and test queries Q* use disjoint relevant doc sets.
    Every test query is preserved for evaluation.
    """
    rng = __import__("numpy").random.default_rng(seed)
    vocab = [f"term{i}" for i in range(60)]
    corpus = {}
    for d in range(n_docs):
        words = rng.choice(vocab, size=30).tolist()
        corpus[f"D{d}"] = " ".join(words)
    dev_queries, dev_qrels = {}, {}
    for q in range(n_dev):
        qid = f"QDEV{q}"
        dev_queries[qid] = f"devquery{q}"
        rel = [f"D{(q * 3 + j) % n_docs}" for j in range(3)]
        for did in rel:
            corpus[did] += f" devquery{q}"
        dev_qrels[qid] = {did: 1 for did in rel}
    test_queries, test_qrels = {}, {}
    for q in range(n_test):
        qid = f"Q{q}"
        test_queries[qid] = f"query{q}"
        rel = [f"D{(n_dev * 3 + q * 3 + j) % n_docs}" for j in range(3)]
        for did in rel:
            corpus[did] += f" query{q}"
        test_qrels[qid] = {did: 1 for did in rel}
    return corpus, dev_queries, dev_qrels, test_queries, test_qrels


def aggregate_chunks_to_parents(chunk_scores: dict[str, float]) -> dict[str, float]:
    """Max chunk score per parent. Chunk id format `parent::chunk` or plain parent."""
    parents: dict[str, float] = {}
    for cid, score in chunk_scores.items():
        parent = cid.split("::")[0]
        if parent not in parents or score > parents[parent]:
            parents[parent] = score
    return parents


def freeze_record(name: str) -> dict:
    """Hash cached files for manifest; missing cache -> explicit unavailable record."""
    canonical = canonical_dataset(name)
    base = DATA_ROOT / canonical
    record: dict = {"dataset": canonical, "files": {}, "available": False}
    candidates = ["corpus.jsonl", "queries.jsonl", "queries.test.jsonl", "queries.json",
                  "queries/test.tsv", "qrels/test.tsv", "qrels/dev.tsv", "qrels/train.tsv",
                  "qrels.test.tsv"]
    for fname in candidates:
        p = base / fname
        if p.exists():
            record["files"][fname] = sha256_file(p)
    record["available"] = bool(record["files"])
    return record
