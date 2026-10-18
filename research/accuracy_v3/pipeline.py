"""Fresh timed pipelines, durable feature stages, and unchanged v2 controls."""
from __future__ import annotations

import json
from pathlib import Path
import time

import numpy as np

from research import baselines
from research.config_frozen import FROZEN
from research.selection import CandidateFeatures, GASConfig, SelectionResult
from research.selection_features import FeatureBuilder
from research.accuracy_v2 import pipeline as v2
from research.accuracy_v2.core import Config as BaseConfig, SEEDS, ScoredFeatures, shortlist, take
from research.accuracy_v2.encoding import ResumableDenseSpace, legacy_key, validate_matrix
from .core import CONSTRAINED, METHODS, Config, select
from .storage import ROOT, sha


class CachedDenseSpace(ResumableDenseSpace):
    def _encode_chunks(self, texts, cache_dir):
        if cache_dir is None:
            raise ValueError("V3 requires an existing verified embedding cache")
        key = legacy_key(self, texts)
        path = Path(cache_dir) / f"{key}.npy"
        metadata = path.with_suffix(".json")
        start = time.perf_counter()
        if not path.is_file() or not metadata.is_file():
            raise ValueError(f"Required corpus embedding cache missing: {key}; refusing corpus encoding")
        meta = json.loads(metadata.read_text())
        if sha(path) != meta["sha256"]:
            raise ValueError(f"Required corpus embedding cache corrupt: {key}")
        matrix = np.load(path, mmap_mode="r", allow_pickle=False)
        validate_matrix(matrix, len(texts), 384)
        if list(matrix.shape) != meta["shape"]:
            raise ValueError("Corpus cache shape disagrees with metadata")
        return matrix, {"enabled": True, "hit": True, "key": key,
                        "cold_model_encode_ms": meta["cold_model_encode_ms"],
                        "restore_ms": (time.perf_counter() - start) * 1000}


class Runtime(v2.Runtime):
    def __init__(self, corpus, full_controls=True, synthetic=False):
        if synthetic:
            super().__init__(corpus, full_controls, synthetic=True)
            return
        start = time.perf_counter()
        self.synthetic, self.full_controls = False, full_controls
        self.vecs = CachedDenseSpace(corpus, *v2.MODEL_PINS["dense"], cache_dir=ROOT / "research/cache/dense")
        self.l6, self.l2 = v2.Scorer("l6"), v2.Scorer("l2") if full_controls else None
        self.builder, self.bm25 = FeatureBuilder(self.vecs, corpus), baselines.BM25(corpus)
        self.offline_ms = (time.perf_counter() - start) * 1000
        start = time.perf_counter()
        dummy = CandidateFeatures(("warmup",), [0.0], np.ones((1, FROZEN["embedding_dimension"])),
                                  ("A short scientific passage.",))
        self.vecs.query_vec("a short query")
        self.l6.scores("a short query", dummy)
        if self.l2:
            self.l2.scores("a short query", dummy)
        self.warmup_ms = (time.perf_counter() - start) * 1000

    def expand(self, query, bundle):
        full = CandidateFeatures.from_dict(bundle["full"])
        original = ScoredFeatures.from_dict(bundle["guided"])
        start = time.perf_counter()
        union = set()
        for beta in (0.0, 0.25, 0.5):
            union.update(shortlist(full.ids, full.cosine_scores, bundle["lexical"], beta, 15))
        indices = sorted(union, key=lambda i: full.ids[i])
        features = take(full, indices)
        known = dict(zip(original.candidates.ids, map(float, original.l6_logits)))
        missing = [i for i in indices if full.ids[i] not in known]
        union_prefilter_ms = (time.perf_counter() - start) * 1000
        extra_scores, extra_ms = self.score("l6", query, take(full, missing))
        known.update(zip((full.ids[i] for i in missing), map(float, extra_scores)))
        scored = ScoredFeatures(features, [known[did] for did in features.ids])
        return {**bundle, "union": scored.to_dict(),
                "union_betas": [0.0, 0.25, 0.5], "additional_l6_pairs": len(missing),
                "timings_ms": {**bundle["timings_ms"], "union_prefilter_ms": union_prefilter_ms,
                               "additional_l6_inference_ms": extra_ms}}


def ensure_features(store, qid, query, config, runtime, hook=None):
    features = store.get("features", qid)
    if features is not None:
        return features
    base = store.get("original_features", qid)
    if base is None:
        retrieved = store.get("retrieved", qid)
        if retrieved is None:
            retrieved = runtime().retrieve(query)
            store.put("retrieved", qid, retrieved, hook)
        base = runtime().enrich(query, retrieved, config)
        store.put("original_features", qid, base, hook)
    features = runtime().expand(query, base)
    store.put("features", qid, features, hook)
    return features


def expected_methods(full_controls=True, legacy=True):
    return sorted(v2.expected_methods(full_controls, legacy) + list(METHODS))


def execute_features(bundle, frozen, config=Config()):
    record = v2.execute_features(bundle, BaseConfig(**frozen["config"]), frozen["mmr_weight"],
        GASConfig(**frozen["old_config"]), frozen["old_mmr_weight"], frozen["legacy_threshold"])
    union = ScoredFeatures.from_dict(bundle["union"])
    shared = bundle["timings_ms"]
    expanded_ms = shared["union_prefilter_ms"] + shared["additional_l6_inference_ms"]
    for method in METHODS:
        record["methods"][method] = {"per_seed_results": {}}
    for seed in SEEDS:
        base = record["methods"]["gas_l6"]["per_seed_results"][str(seed)]
        gas = select(union, base["ranked_ids"], "gas_v3", config, seed)
        for method in METHODS:
            budget = max(1, 2 * gas.counts["phase_oracle_calls"])
            result = gas if method == "gas_v3" else select(union, base["ranked_ids"], method, config, seed, budget)
            timing = result.timings_ms
            timing.update({k: shared[k] for k in ("query_encoding_ms", "dense_retrieval_ms", "representative_features_ms",
                          "lexical_scoring_ms", "hybrid_prefilter_ms", "l6_inference_ms",
                          "union_prefilter_ms", "additional_l6_inference_ms")})
            # Global union-L6 needs no baseline GAS; all protected-prefix methods do.
            baseline_ms = 0.0 if method == "l6_union" else base["timings_ms"]["total_ms"]
            upstream = base["timings_ms"]["online_total_ms"] - base["timings_ms"]["total_ms"]
            timing["baseline_selection_ms"] = baseline_ms
            timing["online_total_ms"] = upstream + expanded_ms + baseline_ms + timing["total_ms"]
            result.counts["baseline_phase_oracle_calls"] = 0 if method == "l6_union" else base["counts"]["phase_oracle_calls"]
            record["methods"][method]["per_seed_results"][str(seed)] = result.to_dict()
    record["union_ids"] = list(union.candidates.ids)
    return record


def validate_record(record, bundle, names):
    original = {k: v for k, v in record.items() if k != "methods"}
    original["methods"] = {k: v for k, v in record["methods"].items() if k not in METHODS}
    old_names = [n for n in names if n not in METHODS]
    v2.validate_record(original, bundle, old_names)
    if set(record["methods"]) != set(names):
        raise ValueError("Incomplete v3 method coverage")
    union = ScoredFeatures.from_dict(bundle["union"])
    if record["union_ids"] != list(union.candidates.ids):
        raise ValueError("Union feature/result IDs disagree")
    z = dict(zip(union.candidates.ids, union.l6_logits))
    old = ScoredFeatures.from_dict(bundle["guided"])
    if any(z[did] != score for did, score in zip(old.candidates.ids, old.l6_logits)):
        raise ValueError("Original L6 logits were replaced during expansion")
    lookup = {did: i for i, did in enumerate(union.candidates.ids)}
    sim = np.clip(union.candidates.embeddings @ union.candidates.embeddings.T, 0, 1)
    for method in METHODS:
        rows = record["methods"][method]["per_seed_results"]
        if set(rows) != {str(s) for s in SEEDS}:
            raise ValueError(f"Missing v3 seeds: {method}")
        for seed, row in rows.items():
            result = SelectionResult(**row)
            base = record["methods"]["gas_l6"]["per_seed_results"][seed]
            rank = result.ranked_ids
            if result.method != method or result.seed != int(seed) or len(rank) != len(base["ranked_ids"]):
                raise ValueError("V3 method/seed/output labels disagree")
            if len(rank) != len(set(rank)) or set(rank) != set(result.selected_ids) or not set(rank) <= set(z):
                raise ValueError("Invalid v3 selected documents")
            if method != "l6_union" and rank[:5] != base["ranked_ids"][:5]:
                raise ValueError("Protected prefix changed")
            if method in CONSTRAINED:
                if any(a < b - 1e-12 for a, b in zip(sorted(z[d] for d in rank[5:]), sorted(z[d] for d in base["ranked_ids"][5:]))):
                    raise ValueError("Tail relevance dominance violated")
                if result.redundancy > base["redundancy"] + 1e-12:
                    raise ValueError("Refinement worsened redundancy")
            pairs = [sim[lookup[a], lookup[b]] for i, a in enumerate(rank) for b in rank[i + 1:]]
            if abs(result.redundancy - (float(np.mean(pairs)) if pairs else 0.0)) > 1e-12:
                raise ValueError("Recorded redundancy disagrees with embeddings")
            if any(not np.isfinite(v) or v < 0 for v in result.timings_ms.values()):
                raise ValueError("Invalid v3 timing")
            if result.counts["phase_oracle_calls"] > result.config["max_oracle_calls"]:
                raise ValueError("Phase budget exceeded")
            for update in result.trace:
                if update["accepted"] and not (update["energy_after"] < update["energy_before"] and
                                                update["redundancy_after"] < update["redundancy_before"] - 1e-12):
                    raise ValueError("Accepted update did not strictly improve")
