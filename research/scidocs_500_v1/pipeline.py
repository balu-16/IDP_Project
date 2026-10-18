"""Unchanged selection kernels, isolated cache, and resumable encoding pilot."""
import json
from pathlib import Path
import time

from research import baselines
from research.accuracy_v2 import pipeline as v2
from research.accuracy_v2.encoding import ResumableDenseSpace, encode_sharded, legacy_key, validate_matrix
from research.accuracy_v2.storage import read_checked, write_checked, sha, utc
from research.accuracy_v3.pipeline import Runtime as V3Runtime, CachedDenseSpace
from research.config_frozen import FROZEN
from research.selection import CandidateFeatures
from research.selection_features import FeatureBuilder
from .protocol import CACHE, STUDY, require_frozen, assert_threads
from . import data


class PilotComplete(Exception):
    pass


class EncodingSpace(ResumableDenseSpace):
    def __init__(self, corpus, study=STUDY, pilot_shards=0):
        assert_threads()
        self.study, self.pilot_shards = Path(study), pilot_shards
        super().__init__(corpus, *v2.MODEL_PINS["dense"], cache_dir=CACHE)

    def _encode_chunks(self, texts, cache_dir):
        assert_threads()
        key = legacy_key(self, texts)
        def progress(event, begin):
            if event != "after_embedding_commit":
                return
            shards = Path(cache_dir) / f"{key}.shards"
            committed = [read_checked(p) for p in sorted(shards.glob("[0-9]*.json"))]
            rows = sum(p["end"] - p["begin"] for p in committed)
            seconds = sum(p["encode_ms"] for p in committed) / 1000
            record = {"updated_utc": utc(), "key": key, "completed_chunk_rows": rows,
                      "protocol_sha256": sha(self.study / "frozen.json"),
                      "total_chunk_rows": len(texts), "encoding_seconds": seconds,
                      "encoding_rows_per_second": rows / seconds if seconds else None,
                      "remaining_encoding_hours": seconds / rows * (len(texts) - rows) / 3600 if rows else None,
                      "chunk_stats": self.chunk_stats, "shard_rows": 512}
            write_checked(self.study / "encoding_progress.json", record)
            if self.pilot_shards and len(committed) >= self.pilot_shards:
                write_checked(self.study / "encoding_pilot.json", record)
                raise PilotComplete()
        return encode_sharded(self, texts, cache_dir, shard_rows=512, hook=progress)


def encode(study=STUDY, pilot_shards=0):
    assert_threads()
    ident = require_frozen(study)
    study = Path(study)
    output = study / "encoding.json"
    if output.exists():
        verify_encoding(study, ident)
        return output
    pilot = study / "encoding_pilot.json"
    if pilot_shards and pilot.exists():
        record = read_checked(pilot)
        if record["protocol_sha256"] != sha(study / "frozen.json"):
            raise ValueError("Encoding pilot protocol mismatch")
        # Verify every completed pilot shard before reusing its throughput estimate.
        shards = CACHE / f"{record['key']}.shards"
        for path in sorted(shards.glob("[0-9]*.json")):
            meta = read_checked(path)
            if sha(path.with_suffix(".npy")) != meta["sha256"]:
                raise ValueError("Encoding pilot shard is corrupt")
        return pilot
    corpus, _, _ = data.load()
    started = time.perf_counter()
    try:
        space = EncodingSpace(corpus, study, pilot_shards)
    except PilotComplete:
        return study / "encoding_pilot.json"
    write_checked(output, {"protocol_sha256": sha(study / "frozen.json"), "completed_utc": utc(),
        "elapsed_this_session_seconds": time.perf_counter() - started,
        "cache": space.embedding_cache, "representation": space.meta,
        "matrix_sha256": sha(CACHE / f"{space.embedding_cache['key']}.npy")})
    return output


def verify_encoding(study=STUDY, ident=None):
    import numpy as np
    study = Path(study)
    ident = ident or require_frozen(study)
    record = read_checked(study / "encoding.json")
    if record["protocol_sha256"] != sha(study / "frozen.json"):
        raise ValueError("Encoding protocol fingerprint mismatch")
    path = CACHE / f"{record['cache']['key']}.npy"
    meta = json.loads(path.with_suffix(".json").read_text())
    if sha(path) != record["matrix_sha256"] or meta["sha256"] != record["matrix_sha256"]:
        raise ValueError("SCIDOCS embedding cache corrupt")
    matrix = np.load(path, mmap_mode="r", allow_pickle=False)
    validate_matrix(matrix, record["representation"]["n_chunks"], 384)
    if not np.allclose(np.linalg.norm(matrix, axis=1), 1.0, rtol=1e-5, atol=1e-6):
        raise ValueError("Embedding normalization check failed")
    if list(matrix.shape) != meta["shape"]:
        raise ValueError("Embedding metadata shape mismatch")
    return record


class Runtime(V3Runtime):
    def __init__(self, corpus):
        import numpy as np
        assert_threads()
        start = time.perf_counter()
        self.synthetic, self.full_controls = False, True
        self.vecs = CachedDenseSpace(corpus, *v2.MODEL_PINS["dense"], cache_dir=CACHE)
        self.l6, self.l2 = v2.Scorer("l6"), v2.Scorer("l2")
        self.builder, self.bm25 = FeatureBuilder(self.vecs, corpus), baselines.BM25(corpus)
        self.offline_ms = (time.perf_counter() - start) * 1000
        start = time.perf_counter()
        dummy = CandidateFeatures(("warmup",), [0.], np.ones((1, FROZEN["embedding_dimension"])),
                                  ("A short scientific passage.",))
        self.vecs.query_vec("a short query")
        self.l6.scores("a short query", dummy)
        self.l2.scores("a short query", dummy)
        self.warmup_ms = (time.perf_counter() - start) * 1000

    def retrieve(self, query, qid):
        start = time.perf_counter()
        self.vecs._query_cache.pop(query, None) if hasattr(self.vecs, "_query_cache") else None
        vector = self.vecs.query_vec(query)
        encoding_ms = (time.perf_counter() - start) * 1000
        start = time.perf_counter()
        if self.synthetic:
            scores = dict(zip(self.vecs.doc_ids, map(float, self.vecs.matrix @ vector)))
        else:
            scores = self.vecs.parent_scores(query)
        excluded = int(str(qid) in scores)
        scores.pop(str(qid), None)
        ids = baselines.top_candidates(scores, 64)
        retrieval_ms = (time.perf_counter() - start) * 1000
        start = time.perf_counter()
        lexical = self.bm25.scores(query)
        lexical_ms = (time.perf_counter() - start) * 1000
        start = time.perf_counter()
        full = self.builder.build(query, ids, scores)
        feature_ms = (time.perf_counter() - start) * 1000
        return {"full": full.to_dict(), "lexical": [lexical[d] for d in ids],
                "self_excluded": excluded, "query_id": str(qid),
                "timings_ms": {"query_encoding_ms": encoding_ms, "dense_retrieval_ms": retrieval_ms,
                               "lexical_scoring_ms": lexical_ms, "representative_features_ms": feature_ms}}


def ensure_features(store, qid, query, config, runtime, hook=None):
    features = store.get("features", qid)
    if features is not None:
        return features
    base = store.get("original_features", qid)
    if base is None:
        retrieved = store.get("retrieved", qid)
        if retrieved is None:
            retrieved = runtime().retrieve(query, qid)
            store.put("retrieved", qid, retrieved, hook)
        base = runtime().enrich(query, retrieved, config)
        store.put("original_features", qid, base, hook)
    features = runtime().expand(query, base)
    store.put("features", qid, features, hook)
    return features


def validate_record(record, bundle, names):
    from research.accuracy_v3.pipeline import validate_record as frozen_validate
    qid = bundle["query_id"]
    if qid in bundle["full"]["ids"] or qid in bundle["union"]["candidates"]["ids"]:
        raise ValueError("Identical query/document ID present in candidate pools")
    frozen_validate(record, bundle, names)
    for payload in record["methods"].values():
        rows = payload.get("per_seed_results", {}).values() if "per_seed_results" in payload else [payload["result"]]
        if any(qid in row["ranked_ids"] for row in rows):
            raise ValueError("Self document present in a method ranking")
