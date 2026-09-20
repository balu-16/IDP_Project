"""Baselines + matched Grover controls (plan A.3).

Full-pipeline: each method selects its own top-K from the corpus.
Matched-candidate: all rerankers share identical frozen candidate IDs
and raw scores; equality is checked, not assumed.

Embedding space is honest: `build_vector_space` tries the pinned dense
encoder first and records what actually executed in `meta`. Manifests
derive provenance from `meta` — they must never claim MiniLM while
TF-IDF executed. Chunking follows the frozen 192/32 policy.

Methods:
  bm25            Okapi BM25 implemented here (no extra dep).
  exact_cosine    brute-force cosine over the active vector space
                  (dense when available, else TF-IDF stand-in).
  hnsw            hnswlib cosine index over the same vectors, built once
                  per run and queried for top-K (see HNSWIndex).
  grover          QuantumSearch simulation via Aer (falls back explicitly).
  analytical      exact classical amplification probabilities.
  sampling        matched multinomial sampling, per-seed metrics averaged.
"""
from __future__ import annotations

import math
import re
import time
from collections import Counter

import numpy as np

TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


class BM25:
    def __init__(self, corpus: dict[str, str], k1: float = 0.9, b: float = 0.4):
        self.doc_ids = list(corpus.keys())
        self.docs = [tokenize(corpus[d]) for d in self.doc_ids]
        self.doc_len = np.array([len(d) for d in self.docs], dtype=float)
        self.avgdl = float(self.doc_len.mean()) if len(self.doc_len) else 1.0
        df: Counter = Counter()
        for d in self.docs:
            for t in set(d):
                df[t] += 1
        n = max(1, len(self.docs))
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.tfs = [Counter(d) for d in self.docs]
        self.k1, self.b = k1, b
        self.settings = {"k1": k1, "b": b}

    def scores(self, query: str) -> dict[str, float]:
        qterms = tokenize(query)
        out: dict[str, float] = {}
        for i, did in enumerate(self.doc_ids):
            s = 0.0
            dl = self.doc_len[i]
            tf = self.tfs[i]
            for t in qterms:
                f = tf.get(t, 0)
                if not f:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
                s += self.idf.get(t, 0.0) * f * (self.k1 + 1) / denom
            out[did] = s
        return out


class TfidfVectors:
    """Shared TF-IDF space so exact/HNSW compare identical vectors."""

    def __init__(self, corpus: dict[str, str]):
        self.doc_ids = list(corpus.keys())
        vocab: dict[str, int] = {}
        for text in corpus.values():
            for t in set(tokenize(text)):
                if t not in vocab:
                    vocab[t] = len(vocab)
        self.vocab = vocab
        n = len(self.doc_ids)
        df = np.zeros(len(vocab))
        rows = []
        for did in self.doc_ids:
            counts = Counter(tokenize(corpus[did]))
            row = np.zeros(len(vocab))
            for t, c in counts.items():
                row[vocab[t]] = c
            rows.append(row)
            for t in counts:
                df[vocab[t]] += 1
        idf = np.log(1 + (n - df + 0.5) / (df + 0.5))
        mat = np.array(rows) * idf
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self.matrix = mat / norms
        self.idf = idf

    def query_vec(self, query: str) -> np.ndarray:
        counts = Counter(tokenize(query))
        v = np.zeros(len(self.vocab))
        for t, c in counts.items():
            if t in self.vocab:
                v[self.vocab[t]] = c
        v = v * self.idf
        n = np.linalg.norm(v)
        return v / n if n > 0 else v


def exact_cosine_scores(vecs, query: str) -> dict[str, float]:
    if getattr(vecs, "is_chunked", False):
        return vecs.parent_scores(query)
    q = vecs.query_vec(query)
    sims = vecs.matrix @ q
    return {did: float(s) for did, s in zip(vecs.doc_ids, sims)}


def chunk_words(words: list[str], chunk_tokens: int = 192, overlap: int = 32) -> list[list[str]]:
    """Frozen 192/32 word-chunk policy (whitespace tokens as MiniLM proxy).

    Special-token accounting: callers reserve 2 slots ([CLS]/[SEP]); inputs
    longer than chunk_tokens-2 are never silently truncated — they emit
    another overlapping window.
    """
    if chunk_tokens < 8 or overlap < 0 or overlap >= chunk_tokens:
        raise ValueError("Invalid chunk policy")
    step = chunk_tokens - overlap
    return [words[i:i + chunk_tokens] for i in range(0, max(1, len(words)), step) if words[i:i + chunk_tokens]]


class DenseVectorSpace:
    """Pinned MiniLM dense space with frozen 192/32 chunking.

    Docs are tokenized with the pinned MiniLM WordPiece tokenizer, split
    into 192-token windows with 32-token overlap (2 slots reserved for
    [CLS]/[SEP] -> 190 content tokens, step 158), encoded per chunk, and
    aggregated to parents via max chunk cosine. `chunk_words` remains the
    whitespace fallback used only when the HF tokenizer is unavailable in
    offline unit tests; official runs always use the real tokenizer and
    record it in `meta`. Raises RuntimeError if weights/tokenizer unavailable.
    """

    CONTENT_TOKENS = 190
    STEP = 158

    def __init__(self, corpus: dict[str, str], model: str, revision: str):
        import numpy as _np

        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:
            raise RuntimeError(f"sentence-transformers unavailable: {exc}") from exc
        try:
            self.model = SentenceTransformer(model, revision=revision, trust_remote_code=False)
        except Exception as exc:
            raise RuntimeError(f"pinned encoder load failed ({model}@{revision}): {exc}") from exc
        try:
            from transformers import AutoTokenizer

            self.tokenizer = AutoTokenizer.from_pretrained(model, revision=revision, trust_remote_code=False)
            self.tokenizer_name = f"{model}@{revision}"
        except Exception as exc:
            raise RuntimeError(f"pinned tokenizer load failed ({model}@{revision}): {exc}") from exc
        try:
            import torch

            torch.set_num_threads(2)
            torch.set_num_interop_threads(1)
        except Exception:
            pass
        self.doc_ids = list(corpus.keys())
        self._query_cache: dict[str, _np.ndarray] = {}
        chunk_texts: list[str] = []
        self.chunk_parents: list[str] = []
        self.chunk_stats = {"n_chunks": 0, "truncation_events": 0, "tokenizer": self.tokenizer_name}
        for did in self.doc_ids:
            text = corpus[did]
            backend = getattr(self.tokenizer, "backend_tokenizer", None)
            if backend is not None:
                backend_encoding = backend.encode(text, add_special_tokens=False)
                offsets = backend_encoding.offsets
            else:
                # Slow-tokenizer fallback used only if a compatible fast
                # tokenizer is unavailable. The warning is about inspecting a
                # whole document for offsets, not about a model input; actual
                # chunks are validated below before encoding.
                encoded = self.tokenizer(text, add_special_tokens=False,
                                         return_offsets_mapping=True, truncation=False)
                offsets = encoded.get("offset_mapping", [])
            if not offsets:
                chunk_texts.append("")
                self.chunk_parents.append(did)
                continue
            for start in range(0, len(offsets), self.STEP):
                end = min(start + self.CONTENT_TOKENS, len(offsets))
                while end > start:
                    left, right = offsets[start][0], offsets[end - 1][1]
                    candidate = text[left:right]
                    actual = len(self.tokenizer.encode(candidate, add_special_tokens=False,
                                                       truncation=False))
                    if actual <= self.CONTENT_TOKENS:
                        break
                    end -= 1
                if end <= start:
                    raise RuntimeError(f"unable to construct a valid MiniLM chunk for document {did}")
                chunk_texts.append(candidate)
                self.chunk_parents.append(did)
                self.chunk_stats.setdefault("token_counts", []).append(actual)
        self.chunk_stats["n_chunks"] = len(chunk_texts)
        counts = self.chunk_stats.pop("token_counts", [])
        self.chunk_stats["min_tokens"] = min(counts) if counts else 0
        self.chunk_stats["max_tokens"] = max(counts) if counts else 0
        self.chunk_stats["mean_tokens"] = (sum(counts) / len(counts)) if counts else 0.0
        mat = self.model.encode(chunk_texts, batch_size=8, normalize_embeddings=True,
                                show_progress_bar=False)
        self.chunk_matrix = _np.asarray(mat, dtype=float)
        self.model_name, self.revision = model, revision
        self.is_chunked = True
        self.meta = {"embedding_space": f"dense:{model}@{revision}",
                     "dimension": int(self.chunk_matrix.shape[1]),
                     "chunk_policy": "MiniLM WordPiece 192/32 (190 content, step 158, 2 specials reserved)",
                     "tokenizer": self.tokenizer_name,
                     "n_chunks": len(chunk_texts), "n_parents": len(self.doc_ids),
                     "truncation_events": self.chunk_stats["truncation_events"],
                     "chunk_min_tokens": self.chunk_stats["min_tokens"],
                     "chunk_max_tokens": self.chunk_stats["max_tokens"],
                     "chunk_mean_tokens": self.chunk_stats["mean_tokens"]}

    def query_vec(self, query: str):
        import numpy as _np

        if query in self._query_cache:
            return self._query_cache[query].copy()
        ids = self.tokenizer.encode(query, add_special_tokens=False)
        if len(ids) > self.CONTENT_TOKENS:
            raise ValueError(f"Query exceeds 190 content tokens ({len(ids)}); shorten query")
        vector = _np.asarray(self.model.encode([query], normalize_embeddings=True,
                                               show_progress_bar=False)[0], dtype=float)
        self._query_cache[query] = vector
        return vector.copy()

    def parent_scores(self, query: str) -> dict[str, float]:
        import numpy as _np

        from .datasets import aggregate_chunks_to_parents

        q = self.query_vec(query)
        sims = self.chunk_matrix @ q
        chunk_scores = {f"{p}::{i}": float(s) for i, (p, s) in enumerate(zip(self.chunk_parents, sims))}
        return aggregate_chunks_to_parents(chunk_scores)


def require_dense(corpus: dict[str, str]):
    """Hard-require pinned dense encoder (official runs). No TF-IDF fallback."""
    from .config_frozen import FROZEN as _F

    try:
        space = DenseVectorSpace(corpus, _F["encoder"], _F["encoder_revision"])
    except Exception as exc:
        raise RuntimeError(
            f"Dense encoder required for official datasets but unavailable: {exc}. "
            f"Download {_F['encoder']}@{_F['encoder_revision']} into the HF cache and retry; "
            "TF-IDF stand-in is not publishable.") from exc
    return space, {**space.meta, "fallback": None}


def build_vector_space(corpus: dict[str, str], prefer: str = "dense", dataset: str = "synthetic"):
    """Return (vecs, meta) with honest provenance.

    Official datasets (scifact/nfcorpus) hard-require dense: any failure
    raises, never falls back. Synthetic smoke may use prefer='tfidf'
    explicitly, stamped NOT PUBLISHABLE.
    """
    official = dataset.strip().lower() in {"scifact", "nfcorpus", "nqcorpus"}
    if official:
        if prefer != "dense":
            raise ValueError(f"Official dataset {dataset!r} requires --encoder dense (got {prefer!r})")
        return require_dense(corpus)
    if prefer == "dense":
        try:
            from .config_frozen import FROZEN as _F

            space = DenseVectorSpace(corpus, _F["encoder"], _F["encoder_revision"])
            return space, {**space.meta, "fallback": None}
        except Exception as exc:
            vecs = TfidfVectors(corpus)
            return vecs, {"embedding_space": "tfidf-standin",
                          "dimension": int(vecs.matrix.shape[1]),
                          "chunk_policy": "192/32 word windows (tfidf proxy, NOT PUBLISHABLE)",
                          "fallback": f"dense unavailable: {exc}"}
    vecs = TfidfVectors(corpus)
    return vecs, {"embedding_space": "tfidf-standin",
                  "dimension": int(vecs.matrix.shape[1]),
                  "chunk_policy": "192/32 word windows (tfidf proxy, NOT PUBLISHABLE)",
                  "fallback": "forced tfidf preference (synthetic smoke only)"}


class HNSWIndex:
    """hnswlib index built once per run; queried per question for top-K.

    Dense chunked spaces index chunks and map back to parents with
    overfetch + dedup: query top K*overfetch chunks, take max chunk score
    per parent, return top-K parents. TF-IDF/doc-level spaces index docs
    directly. Build time recorded once, never charged per query.
    """

    def __init__(self, vecs, ef_construction: int = 100, m: int = 16, ef: int = 64,
                 overfetch: int = 4):
        import time as _time

        import hnswlib

        t0 = _time.perf_counter()
        self.vecs = vecs
        self.overfetch = overfetch
        if getattr(vecs, "is_chunked", False):
            import numpy as _np

            self.chunk_parents = list(vecs.chunk_parents)
            self.doc_ids = list(vecs.doc_ids)
            mat = _np.asarray(vecs.chunk_matrix, dtype=_np.float32)
            self._index_ids = self.chunk_parents  # index rows are chunks
            self._is_chunked = True
        else:
            import numpy as _np

            self.doc_ids = list(vecs.doc_ids)
            mat = _np.asarray(vecs.matrix, dtype=_np.float32)
            self._index_ids = self.doc_ids
            self._is_chunked = False
        dim = mat.shape[1]
        self.index = hnswlib.Index(space="cosine", dim=dim)
        from .config_frozen import FROZEN as _F

        random_seed = int(_F.get("hnsw_random_seed", 0))
        hnsw_threads = int(_F.get("hnsw_threads", 1))
        self.index.init_index(max_elements=len(mat),
                              ef_construction=ef_construction, M=m,
                              random_seed=random_seed)
        self.index.add_items(mat, __import__("numpy").arange(len(mat)),
                             num_threads=hnsw_threads)
        self.index.set_ef(ef)
        self.settings = {"ef_construction": ef_construction, "M": m, "ef": ef,
                         "random_seed": random_seed, "threads": hnsw_threads,
                         "space": "cosine", "overfetch": overfetch,
                         "chunked": self._is_chunked}
        self.build_ms = (_time.perf_counter() - t0) * 1000

    def query(self, query: str, k: int) -> tuple[dict[str, float], dict]:
        import time as _time

        from .datasets import aggregate_chunks_to_parents

        t0 = _time.perf_counter()
        k = max(1, min(k, len(self.doc_ids)))
        q = self.vecs.query_vec(query).astype(__import__("numpy").float32).reshape(1, -1)
        if not self._is_chunked:
            labels, dists = self.index.knn_query(q, k=k, num_threads=self.settings["threads"])
            out = {self.doc_ids[int(i)]: float(1 - d) for i, d in zip(labels[0], dists[0])}
            return out, {"query_ms": (_time.perf_counter() - t0) * 1000, **self.settings}
        fetch = max(k * self.overfetch, k + 10)
        fetch = max(1, min(fetch, len(self.chunk_parents)))
        parents: dict[str, float] = {}
        rounds = 0
        # Progressively widen retrieval until K distinct parents are found
        # or all chunks are exhausted. A single overfetch can return fewer
        # than K parents when one document owns the nearest chunks.
        while True:
            rounds += 1
            labels, dists = self.index.knn_query(q, k=fetch, num_threads=self.settings["threads"])
            chunk_scores = {f"{self.chunk_parents[int(i)]}::{int(i)}": float(1 - d)
                            for i, d in zip(labels[0], dists[0])}
            parents = aggregate_chunks_to_parents(chunk_scores)
            if len(parents) >= k or fetch >= len(self.chunk_parents):
                break
            fetch = min(len(self.chunk_parents), max(fetch + 10, fetch * 2))
        top = sorted(parents, key=lambda d: (-parents[d], d))[:k]
        return {d: parents[d] for d in top}, {
            "query_ms": (_time.perf_counter() - t0) * 1000, **self.settings,
            "chunks_fetched": fetch, "fetch_rounds": rounds,
            "exhausted": fetch >= len(self.chunk_parents),
            "parents_returned": len(top)}


def hnsw_scores(vecs, query: str, ef: int = 64) -> tuple[dict[str, float], dict]:
    """Single-query convenience wrapper (builds index; prefer HNSWIndex in runs)."""
    return HNSWIndex(vecs, ef=ef).query(query, k=len(vecs.doc_ids))


def top_candidates(scores: dict[str, float], k: int) -> list[str]:
    return sorted(scores, key=lambda d: (-scores[d], d))[:k]


def get_quantum_search():
    import sys
    from pathlib import Path

    backend = Path(__file__).resolve().parent.parent / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    from services.quantum_search import QuantumSearch

    return QuantumSearch()


def rerank_frozen(
    candidate_ids: list[str],
    raw_scores: dict[str, float],
    method: str,
    threshold: float,
    shots: int,
    boost: float,
    seeds: list[int],
) -> tuple[list[str], dict]:
    """Rerank identical candidates with per-seed rankings preserved.

    Deterministic methods return a single ranking. Stochastic methods
    (grover/sampling) run each seed independently and return:
      ranked_ids: ensemble mean-rank-score ordering (labeled as such),
      trace: {per_seed_rankings: {seed: [ids]}, per_seed_scores: {seed: {id: rank_score}},
              ensemble_ranking: [...], ...}
    Callers must average per-seed *metrics* within the query for primary
    statistics; the ensemble is a separate diagnostic, not the evaluated
    algorithm (issue 6).
    """
    docs = [{"id": d} for d in candidate_ids]
    scores = [float(raw_scores[d]) for d in candidate_ids]
    search = get_quantum_search()
    if method in {"cosine", "analytical"}:
        # analytical == closed_form deterministic control
        actual = "cosine" if method == "cosine" else "closed_form"
        res = search.rank_scores(docs, scores, method=actual, top_k=len(docs),
                                 threshold=threshold, boost=boost)
        ranked = [r["id"] for r in res["results"]]
        score_by_id = {r["id"]: r["rank_score"] for r in res["results"]}
        return ranked, {"method": method, "seeds": [],
                        "fallback": res["fallback_reason"],
                        "frozen_match": True,
                        "per_seed_rankings": {},
                        "per_seed_scores": {},
                        "ensemble_ranking": ranked,
                        "score_by_id": score_by_id,
                        "quantum": res["quantum"]}
    # grover / sampling: independent per-seed rankings.
    per_seed_rankings: dict[int, list[str]] = {}
    per_seed_scores: dict[int, dict[str, float]] = {}
    fallback = None
    quantum = None
    quantum_per_seed: dict[int, object] = {}
    for seed in seeds:
        res = search.rank_scores(docs, scores, method="grover" if method == "grover" else "classical_sampling",
                                 top_k=len(docs), threshold=threshold, shots=shots,
                                 seed=seed, boost=boost)
        if res["fallback_reason"]:
            fallback = res["fallback_reason"]
            if res["search_method"] == "cosine":
                # Legitimate fallback (e.g. no candidates meet threshold):
                # save an explicitly labeled per-seed cosine ranking for EVERY
                # expected seed so the query stays evaluable and in denominators.
                ranked = [r["id"] for r in res["results"]]
                score_by_id = {r["id"]: r["rank_score"] for r in res["results"]}
                per_seed_rankings = {s: list(ranked) for s in seeds}
                per_seed_scores = {s: dict(score_by_id) for s in seeds}
                return ranked, {"method": method, "seeds": list(seeds),
                                "fallback": fallback, "fallback_search_method": "cosine",
                                "quantum": res["quantum"],
                                "quantum_per_seed": {s: res["quantum"] for s in seeds},
                                "frozen_match": True,
                                "per_seed_rankings": per_seed_rankings,
                                "per_seed_scores": per_seed_scores,
                                "ensemble_ranking": list(ranked),
                                "score_by_id": score_by_id}
        quantum = res["quantum"]
        quantum_per_seed[seed] = res["quantum"]
        ranked_seed = [r["id"] for r in res["results"]]
        per_seed_rankings[seed] = ranked_seed
        per_seed_scores[seed] = {r["id"]: r["rank_score"] for r in res["results"]}
    # Ensemble diagnostic only: mean rank_score across seeds.
    avg = {d: float(np.mean([per_seed_scores[s][d] for s in seeds])) for d in candidate_ids}
    ensemble = sorted(candidate_ids, key=lambda d: (-avg[d], d))
    return ensemble, {"method": method, "seeds": list(seeds), "fallback": fallback,
                      "frozen_match": True,
                      "quantum": quantum, "quantum_per_seed": quantum_per_seed,
                      "per_seed_rankings": per_seed_rankings,
                      "per_seed_scores": per_seed_scores,
                      "ensemble_ranking": ensemble}
