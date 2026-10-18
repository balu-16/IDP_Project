"""Pinned local model loading and query features, with explicit timing scopes."""
from __future__ import annotations

import time

import numpy as np

from research import baselines, datasets
from research.config_frozen import FROZEN, DATASETS
from research.selection import CandidateFeatures, GASConfig, SelectionResult
from research.selection_experiment import run_query, summarize_ranking
from research.selection_features import FeatureBuilder
from .core import Config, SEEDS, ScoredFeatures, guided_methods, shortlist, take
from .encoding import ResumableDenseSpace
from .storage import ROOT, sha

MODEL_PINS = {
    "dense": (FROZEN["encoder"], FROZEN["encoder_revision"]),
    "l6": ("cross-encoder/ms-marco-MiniLM-L6-v2", "233902d25c440f23af6f7d6e94d2946bac0bee0a"),
    "l2": ("cross-encoder/ms-marco-MiniLM-L2-v2", "1b5cd67b15209f24824c50370e0397743aa9b787"),
}
OLD_STOCHASTIC = {"gas", "random", "legacy_grover"}
STOCHASTIC = OLD_STOCHASTIC | {"gas_l6", "random_l6"}


def model_path(label):
    from huggingface_hub import snapshot_download
    model, revision = MODEL_PINS[label]
    return snapshot_download(repo_id=model, revision=revision, local_files_only=True,
        allow_patterns=["*.json", "*.txt", "*.safetensors", "pytorch_model.bin", "*.model"],
        ignore_patterns=["onnx/*", "openvino/*"])


def model_identity(full_controls=True):
    from pathlib import Path
    result = {}
    for label in ("dense", "l6", "l2") if full_controls else ("dense", "l6"):
        path = Path(model_path(label))
        weights = sorted(p for p in path.iterdir() if p.suffix in {".safetensors", ".bin"})
        if not weights:
            raise ValueError(f"Missing local weights: {label}")
        files = sorted(p for p in path.rglob("*") if p.is_file() and not any(v in p.parts for v in ("onnx", "openvino")))
        result[label] = {"model": MODEL_PINS[label][0], "revision": MODEL_PINS[label][1],
                         "files": {str(p.relative_to(path)): sha(p) for p in files}}
    return result


class Scorer:
    def __init__(self, label):
        import torch
        from sentence_transformers import CrossEncoder
        self.model = CrossEncoder(model_path(label), device="cpu", max_length=512, trust_remote_code=False)
        self.model.model.eval()
        self.activation = torch.nn.Identity()

    def scores(self, query, features):
        if not features.ids:
            return np.array([], dtype=float), 0.0
        if len(features.passages) != len(features.ids):
            raise ValueError("Scoring requires the exact representative passage per candidate")
        start = time.perf_counter()
        pairs = [(query, passage) for passage in features.passages]
        # Explicitly inspect untruncated inputs instead of trusting implicit truncation.
        tokens = self.model.tokenizer([p[0] for p in pairs], [p[1] for p in pairs],
            add_special_tokens=True, truncation=False, padding=False)["input_ids"]
        if any(len(ids) > 512 for ids in tokens):
            raise ValueError("Cross-encoder query/passage exceeds 512 tokens; refusing silent truncation")
        logits = np.asarray(self.model.predict(pairs, batch_size=8, show_progress_bar=False,
                            activation_fct=self.activation), dtype=float).reshape(-1)
        if logits.shape != (len(features.ids),) or not np.isfinite(logits).all():
            raise ValueError("Cross-encoder returned invalid raw logits")
        return logits, (time.perf_counter() - start) * 1000


def load_development(name):
    if name == "synthetic":
        corpus, dev, rel, _, _ = datasets.synthetic_splits()
        return corpus, dev, rel
    base = datasets.DATA_ROOT / name
    split = DATASETS[name]["dev_split"]
    corpus = datasets._load_corpus(base)
    queries, rel = datasets._filter_to_qrels(datasets._load_queries(base, split), datasets._load_qrels(base, split))
    if name == "scifact":
        queries, rel = datasets.scifact_train_sample(queries, rel)
    if not queries or any(not any(g > 0 for g in rows.values()) for rows in rel.values()):
        raise ValueError("Development queries require positive judgments")
    if any(d not in corpus for rows in rel.values() for d in rows):
        raise ValueError("Development judgments reference missing documents")
    return corpus, queries, rel


class Runtime:
    def __init__(self, corpus, full_controls=True, synthetic=False):
        self.synthetic = synthetic
        begin = time.perf_counter()
        if synthetic:
            self.vecs = baselines.TfidfVectors(corpus)
            self.l6 = self.l2 = None
        else:
            self.vecs = ResumableDenseSpace(corpus, *MODEL_PINS["dense"], cache_dir=ROOT / "research/cache/dense")
            self.l6 = Scorer("l6")
            self.l2 = Scorer("l2") if full_controls else None
        self.builder = FeatureBuilder(self.vecs, corpus)
        self.bm25 = baselines.BM25(corpus)
        self.full_controls = full_controls
        self.offline_ms = (time.perf_counter() - begin) * 1000
        self.warmup_ms = 0.0
        if not synthetic:
            # Warm-up uses an artificial query and passage, never test labels.
            dummy = CandidateFeatures(("warmup",), [0.0], np.ones((1, FROZEN["embedding_dimension"])), ("A short scientific passage.",))
            start = time.perf_counter()
            self.vecs.query_vec("a short query")
            self.l6.scores("a short query", dummy)
            if self.l2:
                self.l2.scores("a short query", dummy)
            self.warmup_ms = (time.perf_counter() - start) * 1000

    def score(self, label, query, features):
        if self.synthetic:
            # Deliberately marked synthetic stand-in, never benchmark evidence.
            start = time.perf_counter()
            logits = 4 * features.cosine_scores + np.array([0.001 * sum(map(ord, d)) for d in features.ids])
            return logits, (time.perf_counter() - start) * 1000
        return getattr(self, label).scores(query, features)

    def retrieve(self, query):
        start = time.perf_counter()
        self.vecs._query_cache.pop(query, None) if hasattr(self.vecs, "_query_cache") else None
        vector = self.vecs.query_vec(query)
        encoding_ms = (time.perf_counter() - start) * 1000
        start = time.perf_counter()
        if self.synthetic:
            dense = self.vecs.matrix @ vector
            scores = dict(zip(self.vecs.doc_ids, map(float, dense)))
        else:
            scores = self.vecs.parent_scores(query)
        ids = baselines.top_candidates(scores, 64)
        retrieval_ms = (time.perf_counter() - start) * 1000
        start = time.perf_counter()
        lexical = self.bm25.scores(query)
        lexical_ms = (time.perf_counter() - start) * 1000
        start = time.perf_counter()
        full = self.builder.build(query, ids, scores)
        feature_ms = (time.perf_counter() - start) * 1000
        return {"full": full.to_dict(), "lexical": [lexical[d] for d in ids],
                "timings_ms": {"query_encoding_ms": encoding_ms, "dense_retrieval_ms": retrieval_ms,
                               "lexical_scoring_ms": lexical_ms, "representative_features_ms": feature_ms}}

    def enrich(self, query, retrieved, config):
        full = CandidateFeatures.from_dict(retrieved["full"])
        start = time.perf_counter()
        indices = shortlist(full.ids, full.cosine_scores, retrieved["lexical"], config.lexical_weight, config.candidate_limit)
        features = take(full, indices)
        prefilter_ms = (time.perf_counter() - start) * 1000
        logits, neural_ms = self.score("l6", query, features)
        neural = {}
        if self.full_controls:
            dense15 = take(full, list(range(min(config.candidate_limit, len(full.ids)))))
            for label in ("l2", "l6"):
                for pool, candidates in (("matched", dense15), ("top64", full)):
                    values, elapsed = self.score(label, query, candidates)
                    neural[f"neural_{label}_{pool}"] = {"scores": values.tolist(), "inference_ms": elapsed}
        return {**retrieved, "guided": ScoredFeatures(features, logits).to_dict(), "neural_controls": neural,
                "timings_ms": {**retrieved["timings_ms"], "hybrid_prefilter_ms": prefilter_ms, "l6_inference_ms": neural_ms}}


def expected_methods(full_controls=True, legacy=False):
    from .core import GUIDED
    names = set(GUIDED) | {"cosine", "mmr", "greedy", "exact_quantized", "exact_float", "random", "fusion", "gas"}
    if full_controls:
        names |= {f"neural_{label}_{pool}" for label in ("l2", "l6") for pool in ("matched", "top64")}
    if legacy:
        names.add("legacy_grover")
    return sorted(names)


def execute_features(bundle, config, mmr_weight=0.0, old_config=None, old_mmr_weight=0.0, legacy_threshold=None):
    guided = ScoredFeatures.from_dict(bundle["guided"])
    full = CandidateFeatures.from_dict(bundle["full"])
    dense15 = take(full, list(range(min(config.candidate_limit, len(full.ids)))))
    old_config = old_config or GASConfig(diversity_weight=0.1)
    methods = guided_methods(guided, config, mmr_weight)
    methods.update(run_query(dense15, old_config, lexical_scores=bundle["lexical"][:len(dense15.ids)], mmr_weight=old_mmr_weight))
    for method, neural in bundle.get("neural_controls", {}).items():
        candidates = full if method.endswith("top64") else dense15
        order = sorted(range(len(candidates.ids)), key=lambda i: (-neural["scores"][i], candidates.ids[i]))[:config.selected_count]
        result = summarize_ranking(method, [candidates.ids[i] for i in order], candidates, old_config)
        result.timings_ms = {"total_ms": neural["inference_ms"]}
        methods[method] = {"result": result.to_dict()}
    if legacy_threshold is not None:
        rows = {}
        scores = dict(zip(full.ids, map(float, full.cosine_scores)))
        for seed in SEEDS:
            start, cpu = time.perf_counter(), time.process_time()
            ranked, trace = baselines.rerank_frozen(list(full.ids), scores, "grover", legacy_threshold,
                                                 FROZEN["shots"], FROZEN["boost"], [seed])
            result = summarize_ranking("legacy_grover", ranked[:config.selected_count], full, old_config)
            result.seed, result.status = seed, "fallback" if trace["fallback"] else "completed"
            result.timings_ms = {"total_ms": (time.perf_counter() - start) * 1000, "cpu_ms": (time.process_time() - cpu) * 1000}
            result.trace = [trace]
            rows[str(seed)] = result.to_dict()
        methods["legacy_grover"] = {"per_seed_results": rows}
    shared = bundle["timings_ms"]
    for name, payload in methods.items():
        results = payload["per_seed_results"].values() if name in STOCHASTIC else [payload["result"]]
        for result in results:
            timing = result["timings_ms"]
            # Shared computation may be reused, but its full cost is charged to each pipeline.
            timing.update({k: shared[k] for k in ("query_encoding_ms", "dense_retrieval_ms", "representative_features_ms")})
            extra = 0.0
            if name.endswith("_l6") or name == "l6_only":
                timing.update({k: shared[k] for k in ("lexical_scoring_ms", "hybrid_prefilter_ms", "l6_inference_ms")})
                extra = sum(shared[k] for k in ("lexical_scoring_ms", "hybrid_prefilter_ms", "l6_inference_ms"))
            elif name == "fusion":
                timing["lexical_scoring_ms"] = shared["lexical_scoring_ms"]
                extra = shared["lexical_scoring_ms"]
            timing["online_total_ms"] = sum(shared[k] for k in ("query_encoding_ms", "dense_retrieval_ms", "representative_features_ms")) + extra + timing["total_ms"]
    return {"candidate_ids": list(guided.candidates.ids), "dense_candidate_ids": list(dense15.ids),
            "shortlist_ids": list(full.ids), "methods": methods}


def validate_record(record, bundle, names, selected_count=8):
    if set(record["methods"]) != set(names):
        raise ValueError("Method coverage mismatch")
    guided = ScoredFeatures.from_dict(bundle["guided"])
    full = CandidateFeatures.from_dict(bundle["full"])
    if record["candidate_ids"] != list(guided.candidates.ids) or record["shortlist_ids"] != list(full.ids):
        raise ValueError("Feature/result candidate IDs disagree")
    if record["dense_candidate_ids"] != list(full.ids[:len(record["dense_candidate_ids"])]):
        raise ValueError("Dense-pool IDs disagree")
    for name, payload in record["methods"].items():
        rows = payload.get("per_seed_results") if name in STOCHASTIC else {None: payload.get("result")}
        if not rows or (name in STOCHASTIC and set(rows) != {str(s) for s in SEEDS}):
            raise ValueError(f"Seed coverage mismatch for {name}")
        allowed = set(record["candidate_ids"] if name.endswith("_l6") or name == "l6_only" else
                      record["shortlist_ids"] if name.endswith("top64") or name == "legacy_grover" else record["dense_candidate_ids"])
        for seed, row in rows.items():
            result = SelectionResult(**row)
            if result.method != name or (seed is not None and result.seed != int(seed)):
                raise ValueError(f"Method/seed labels disagree for {name}")
            if (len(result.ranked_ids) != min(selected_count, len(allowed)) or len(set(result.ranked_ids)) != len(result.ranked_ids)
                    or not set(result.ranked_ids) <= allowed or set(result.ranked_ids) != set(result.selected_ids)
                    or len(result.selected_ids) != len(result.ranked_ids)):
                raise ValueError(f"Invalid selected IDs for {name}")
            for value in result.timings_ms.values():
                if not np.isfinite(value) or value < 0:
                    raise ValueError("Invalid recorded timing")
