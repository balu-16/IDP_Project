"""Explicit, opt-in GAS experiment runner and feature-file selection CLI.

Importing this module never loads a dataset/model or starts an experiment.
Dataset commands are intended for the separately scheduled evaluation work.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys
import time

import numpy as np

from .selection import (CandidateFeatures, GASConfig, SelectionResult,
                        select_classical, select_evidence, selection_metrics, subset_layout)

ROOT = Path(__file__).resolve().parent.parent
SEEDS = (0, 1, 2, 3, 4)
WEIGHTS = (0.1, 0.25, 0.5)
MMR_WEIGHTS = (0.0, 0.1, 0.25, 0.5, 0.75, 1.0)
SCHEMA = "gas-selection-v1"
STOCHASTIC = {"gas", "random", "legacy_grover"}


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def add_gas_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--gas-pool-size", type=int, default=15)
    parser.add_argument("--gas-output-size", type=int, default=8)
    parser.add_argument("--gas-coefficient-bits", type=int, default=6)
    parser.add_argument("--gas-weight", type=float, default=None,
                        help="Fixed weight; omission tunes on development judgments only")
    parser.add_argument("--gas-max-oracle-calls", type=int, default=64)
    parser.add_argument("--gas-max-trials", type=int, default=32)
    parser.add_argument("--gas-time-limit", type=float, default=15.0)
    parser.add_argument("--neural-baselines", action="store_true",
                        help="Explicitly load/download pinned L2/L6 baselines for matched and top-64 runs")
    parser.add_argument("--legacy-grover", action="store_true",
                        help="Also execute the old probability-based top-64 circuit reranker")
    parser.add_argument("--neural-l2-revision", default="main")
    parser.add_argument("--neural-l6-revision", default="main")
    parser.add_argument("--pilot-queries", type=int, default=16,
                        help="Deterministic development-only checks before test collection")


def config_from_args(args) -> GASConfig:
    return GASConfig(candidate_limit=args.gas_pool_size, selected_count=args.gas_output_size,
                     coefficient_bits=args.gas_coefficient_bits,
                     diversity_weight=0.25 if args.gas_weight is None else args.gas_weight,
                     max_oracle_calls=args.gas_max_oracle_calls, max_trials=args.gas_max_trials,
                     time_limit_seconds=args.gas_time_limit)


def tune_weight(development: dict[str, CandidateFeatures], qrels: dict,
                config: GASConfig) -> tuple[GASConfig, dict]:
    """Exact quantized solver tunes the objective, never supplies GAS answers."""
    if not development or set(development) != set(qrels):
        raise ValueError("Development features and judgments must have identical nonempty query IDs")
    if any(not any(g > 0 for g in qrels[q].values()) for q in development):
        raise ValueError("Every development query requires positive judgments")
    baseline = np.mean([selection_metrics(select_classical(f, "cosine", config), qrels[q])["nDCG@5"]
                        for q, f in development.items()])
    rows = []
    for weight in WEIGHTS:
        cfg = replace(config, diversity_weight=weight)
        results = [selection_metrics(select_classical(f, "exact_quantized", cfg), qrels[q])
                   for q, f in development.items()]
        quality = float(np.mean([r["nDCG@5"] for r in results]))
        rows.append({"weight": weight, "nDCG@5": quality,
                     "redundancy": float(np.mean([r["redundancy"] for r in results])),
                     "eligible": bool(quality >= baseline - 0.01)})
    eligible = [r for r in rows if r["eligible"]]
    chosen = min(eligible, key=lambda r: (r["redundancy"], -r["nDCG@5"], r["weight"])) if eligible else rows[0]
    return replace(config, diversity_weight=chosen["weight"]), {
        "method": "exact quantized development optimizer; no test judgments",
        "development_cosine_nDCG@5": float(baseline), "quality_margin": 0.01,
        "development_target_met": bool(eligible), "grid": rows,
        "selected_weight": chosen["weight"], "query_ids": sorted(development)}


def tune_mmr_weight(development: dict[str, CandidateFeatures], qrels: dict,
                    config: GASConfig) -> tuple[float, dict]:
    """Independently tune the comparator using development judgments only."""
    if not development or set(development) != set(qrels):
        raise ValueError("Development features and judgments must have identical nonempty query IDs")
    if any(not any(g > 0 for g in qrels[q].values()) for q in development):
        raise ValueError("Every development query requires positive judgments")
    rows = []
    for weight in MMR_WEIGHTS:
        results = [selection_metrics(select_classical(f, "mmr", config, mmr_weight=weight), qrels[q])
                   for q, f in development.items()]
        rows.append({"weight": weight, "nDCG@5": float(np.mean([r["nDCG@5"] for r in results])),
                     "redundancy": float(np.mean([r["redundancy"] for r in results]))})
    chosen = min(rows, key=lambda r: (-r["nDCG@5"], r["redundancy"], r["weight"]))
    return chosen["weight"], {"method": "Independent MMR development nDCG@5 tuning; no test judgments",
                              "selected_weight": chosen["weight"], "grid": rows,
                              "query_ids": sorted(development)}


def hardware_record() -> dict:
    import os

    model, memory = platform.processor() or "unknown", None
    cpuinfo, meminfo = Path("/proc/cpuinfo"), Path("/proc/meminfo")
    if cpuinfo.exists():
        model = next((line.split(":", 1)[1].strip() for line in cpuinfo.read_text().splitlines()
                      if line.startswith("model name")), model)
    if meminfo.exists():
        memory = next((int(line.split()[1]) * 1024 for line in meminfo.read_text().splitlines()
                       if line.startswith("MemTotal:")), None)
    packages = {}
    for package in ("numpy", "scipy", "hnswlib", "qiskit", "qiskit-aer", "torch",
                    "sentence-transformers", "transformers", "huggingface-hub"):
        try:
            packages[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            packages[package] = None
    return {"platform": platform.platform(), "python": sys.version, "cpu_model": model,
            "logical_cpus": os.cpu_count(), "ram_bytes": memory, "cpu_threads": 2,
            "load_average": list(os.getloadavg()) if hasattr(os, "getloadavg") else None,
            "thread_environment": {key: os.environ.get(key) for key in
                                   ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")},
            "packages": packages}


def snapshot_sources(run_dir: Path) -> dict:
    """Snapshot source only, never .env, model credentials, or runtime settings."""
    sources = sorted((ROOT / "research").glob("*.py"))
    sources += [ROOT / "backend" / "config.py"]
    sources += [ROOT / "backend" / "services" / name for name in
                ("circuits.py", "quantum_search.py", "workers.py")]
    record = {}
    for source in sources:
        relative = source.relative_to(ROOT)
        target = run_dir / "source_snapshot" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        record[str(relative)] = _sha(target)
    return record


def seal_run(run_dir: Path, manifest: dict) -> None:
    # Preserve the original source hashes; evaluating must not rewrite history.
    manifest = dict(manifest)
    manifest["result_hashes"] = {str(p.relative_to(run_dir)): _sha(p)
                                 for p in sorted(run_dir.rglob("*")) if p.is_file() and
                                 p.name not in {"manifest.json", "manifest.sha256"}}
    _write_json(run_dir / "manifest.json", manifest)
    (run_dir / "manifest.sha256").write_text(_sha(run_dir / "manifest.json") + "\n")


def verify_run(run_dir: Path) -> dict:
    if _sha(run_dir / "manifest.json") != (run_dir / "manifest.sha256").read_text().strip():
        raise ValueError("GAS manifest checksum mismatch")
    manifest = json.loads((run_dir / "manifest.json").read_text())
    if manifest.get("schema") != SCHEMA:
        raise ValueError("Unsupported GAS artifact schema")
    for relative, digest in manifest["result_hashes"].items():
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or _sha(run_dir / path) != digest:
            raise ValueError(f"GAS artifact checksum mismatch: {relative}")
    for relative, digest in manifest["source_hashes"].items():
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or _sha(ROOT / path) != digest:
            raise ValueError(f"Source changed since GAS run: {relative}; restore the recorded source snapshot")
    return manifest


def _record_result(result: SelectionResult, selection_ms: float, feature_ms: float) -> dict:
    record = result.to_dict()
    record["timings_ms"]["candidate_selection_ms"] = selection_ms
    record["timings_ms"]["representative_features_ms"] = feature_ms
    record["timings_ms"]["retrieval_total_ms"] = selection_ms + feature_ms + result.timings_ms["total_ms"]
    return record


def run_query(features: CandidateFeatures, config: GASConfig, qrels_unused=None,
              lexical_scores=None, mmr_weight: float | None = None) -> dict:
    """Pure feature-level comparison. No qrels are inspected by selection."""
    if qrels_unused is not None:
        raise ValueError("Selectors must not receive relevance judgments")
    methods = {}
    gas = {str(seed): select_evidence(features, config, seed) for seed in SEEDS}
    methods["gas"] = {"per_seed_results": {s: r.to_dict() for s, r in gas.items()}}
    methods["random"] = {"per_seed_results": {s: select_classical(
        features, "random", config, int(s), objective_budget=(
            2 * r.counts["phase_oracle_calls"] + r.counts["classical_search_objective_evaluations"])).to_dict()
        for s, r in gas.items()}}
    for name in ("cosine", "mmr", "greedy", "exact_quantized", "exact_float"):
        options = {"mmr_weight": mmr_weight} if name == "mmr" else {}
        methods[name] = {"result": select_classical(features, name, config, **options).to_dict()}
    if lexical_scores is not None:
        methods["fusion"] = {"result": select_classical(features, "fusion", config,
                                                       lexical_scores=lexical_scores).to_dict()}
    return methods


def cmd_run(args) -> Path:
    """Explicit dataset entrypoint; never invoked by import or unit-test CLI."""
    from . import artifacts, baselines
    from .config_frozen import FROZEN
    from .run import load_dataset, retrieve_full
    from .selection_features import FeatureBuilder, NeuralReranker

    config = config_from_args(args)
    if args.pilot_queries < 1:
        raise ValueError("At least one development pilot query is required")
    print(f"Preparing {args.dataset}: loading data and encoding corpus", flush=True)
    load_start = time.perf_counter()
    corpus, dev_q, dev_rel, test_q, test_rel, freeze = load_dataset(args.dataset)
    if args.dataset != "synthetic" and args.encoder != "dense":
        raise ValueError("Official GAS experiments require the pinned dense encoder")
    if args.encoder == "dense":
        vecs = baselines.DenseVectorSpace(corpus, FROZEN["encoder"], FROZEN["encoder_revision"],
                                          cache_dir=ROOT / "research" / "cache" / "dense")
        metadata = {**vecs.meta, "fallback": None}
    else:
        vecs, metadata = baselines.build_vector_space(corpus, prefer=args.encoder, dataset=args.dataset)
    corpus_encoding_ms = (time.perf_counter() - load_start) * 1000
    print(f"{args.dataset}: {len(corpus)} parents, {len(dev_q)} development queries, "
          f"{len(test_q)} test queries; corpus encoding {corpus_encoding_ms / 1000:.1f}s", flush=True)
    builder = FeatureBuilder(vecs, corpus)
    bm_start = time.perf_counter()
    bm25 = baselines.BM25(corpus)
    bm25_build_ms = (time.perf_counter() - bm_start) * 1000

    def candidates(query):
        # Exact retrieval does not use an HNSW index.
        return retrieve_full(query, "exact_cosine", vecs, bm25, None, 64)

    development = {}
    dev_shortlists = {}
    for qid in sorted(dev_q):
        query = dev_q[qid]
        ids, scores, _ = candidates(query)
        development[qid] = builder.build(query, ids[:config.candidate_limit], scores)
        dev_shortlists[qid] = (ids, {d: scores[d] for d in ids})
    if args.gas_weight is None:
        config, tuning = tune_weight(development, dev_rel, config)
    else:
        tuning = {"method": "explicit fixed weight", "selected_weight": config.diversity_weight,
                  "query_ids": sorted(development)}
    mmr_weight, mmr_tuning = tune_mmr_weight(development, dev_rel, config)

    legacy_threshold = None
    if args.legacy_grover:
        from .metrics import ndcg_at
        preference = (0.5, 0.3, 0.7)
        dev_scores = {}
        for threshold in preference:
            values = []
            for qid, (ids, scores) in dev_shortlists.items():
                _, trace = baselines.rerank_frozen(ids, scores, "sampling", threshold,
                                                  FROZEN["shots"], FROZEN["boost"], list(SEEDS))
                values.append(np.mean([ndcg_at(rank[:config.selected_count], dev_rel[qid], 5)
                                       for rank in trace["per_seed_rankings"].values()]))
            dev_scores[threshold] = float(np.mean(values))
        legacy_threshold = max(preference, key=lambda t: (dev_scores[t], -preference.index(t)))
        tuning["legacy_threshold_grid"] = dev_scores
        tuning["legacy_threshold_metric"] = "Mean-seed development nDCG@5"

    neural, neural_info = {}, {}
    if args.neural_baselines:
        for label, model_id in (("l2", "cross-encoder/ms-marco-MiniLM-L2-v2"),
                                ("l6", "cross-encoder/ms-marco-MiniLM-L6-v2")):
            start = time.perf_counter()
            neural[label] = NeuralReranker.load(model_id, revision=getattr(args, f"neural_{label}_revision"))
            neural_info[label] = {"id": model_id, "revision": neural[label].revision,
                                  "load_ms": (time.perf_counter() - start) * 1000}
    test_ids = sorted(test_q)
    if not test_ids:
        raise ValueError("Test query set is empty")

    from .datasets import deterministic_query_subset

    pilot_ids = deterministic_query_subset(dev_q, args.dataset, min(args.pilot_queries, len(dev_q)),
                                           "gas-development-pilot-v1")
    pilot_records = []
    for qid in pilot_ids:
        ids, scores, _ = candidates(dev_q[qid])
        features = development[qid]
        lexical = bm25.scores(dev_q[qid])
        methods = run_query(features, config, lexical_scores=[lexical[d] for d in features.ids],
                            mmr_weight=mmr_weight)
        _add_neural(methods, neural, "matched", dev_q[qid], features, config, 0.0, 0.0)
        if neural or args.legacy_grover:
            full_features = builder.build(dev_q[qid], ids, scores)
            _add_neural(methods, neural, "top64", dev_q[qid], full_features, config, 0.0, 0.0)
            if args.legacy_grover:
                # Verify the real legacy circuit path on development data.
                baseline, old_trace = baselines.rerank_frozen(
                    ids, scores, "grover", legacy_threshold, FROZEN["shots"], FROZEN["boost"], [0])
                if len(set(baseline)) != len(ids) or set(baseline) != set(ids):
                    raise ValueError("Legacy development pilot returned an invalid ranking")
        pilot_records.append({"qid": qid, "candidate_ids": list(features.ids),
                              "shortlist_ids": ids, "methods": methods})
    pilot_manifest = {"test_ids": pilot_ids, "methods": sorted(pilot_records[0]["methods"]),
                      "seeds": list(SEEDS), "config": asdict(config)}
    pilot_scores = evaluate_records(pilot_manifest, pilot_records, {q: dev_rel[q] for q in pilot_ids})
    if any(pilot_scores["means"][method]["quantized_energy_gap"] < 0 for method in
           ("gas", "random", "cosine", "mmr", "greedy")):
        raise ArithmeticError("A development selection beats the exact quantized optimum")
    print(f"{args.dataset}: development pilot passed ({len(pilot_ids)} queries); "
          f"GAS weight={config.diversity_weight}, MMR weight={mmr_weight}. Starting test collection.", flush=True)
    basis_start = time.perf_counter()
    pool_count = min(config.candidate_limit, len(corpus))
    subset_layout(pool_count, min(config.selected_count, pool_count))
    basis_setup_ms = (time.perf_counter() - basis_start) * 1000
    query_start = time.perf_counter()
    query_vectors, query_encoding_times = [], {}
    for qid in test_ids:
        begin = time.perf_counter()
        getattr(vecs, "_query_cache", {}).pop(test_q[qid], None)
        query_vectors.append(vecs.query_vec(test_q[qid]))
        query_encoding_times[qid] = (time.perf_counter() - begin) * 1000
    query_vectors = np.asarray(query_vectors, dtype=np.float32)
    query_encoding_ms = (time.perf_counter() - query_start) * 1000
    run_dir = artifacts.new_run_dir(args.tag)
    source_hashes = snapshot_sources(run_dir)
    _write_json(run_dir / "pilot.json", {"role": "development-only integration checks", "query_ids": pilot_ids,
                                        "config": asdict(config), "scores": pilot_scores,
                                        "legacy_circuit_checked": bool(args.legacy_grover)})
    print(f"{args.dataset}: writing test artifacts to {run_dir}", flush=True)
    np.savez_compressed(run_dir / "query_embeddings.npz", query_ids=np.asarray(test_ids), embeddings=query_vectors)
    records = []
    feature_path = run_dir / "features.jsonl"
    test_start = time.perf_counter()
    with feature_path.open("w") as feature_output, (run_dir / "full_features.jsonl").open("w") as full_output, \
            (run_dir / "traces.jsonl").open("w") as trace_output:
        for query_index, qid in enumerate(test_ids, 1):
            query = test_q[qid]
            ids, scores, timings = candidates(query)
            start = time.perf_counter()
            features = builder.build(query, ids[:config.candidate_limit], scores)
            feature_ms = (time.perf_counter() - start) * 1000
            lexical_start = time.perf_counter()
            lexical = bm25.scores(query)
            lexical_ms = (time.perf_counter() - lexical_start) * 1000
            methods = run_query(features, config, lexical_scores=[lexical[d] for d in features.ids],
                                mmr_weight=mmr_weight)
            for name, record in methods.items():
                results = record.get("per_seed_results", {}).values() if name in STOCHASTIC else [record["result"]]
                for result in results:
                    result["timings_ms"]["candidate_selection_ms"] = timings["candidate_selection"]
                    result["timings_ms"]["representative_features_ms"] = feature_ms
                    result["timings_ms"]["retrieval_total_ms"] = (
                        timings["candidate_selection"] + feature_ms + result["timings_ms"]["total_ms"])
                    if name == "fusion":
                        result["timings_ms"]["lexical_scoring_ms"] = lexical_ms
                        result["timings_ms"]["retrieval_total_ms"] += lexical_ms
            _add_neural(methods, neural, "matched", query, features, config,
                        timings["candidate_selection"], feature_ms)
            if neural or args.legacy_grover:
                start = time.perf_counter()
                full_features = builder.build(query, ids, scores)
                full_feature_ms = (time.perf_counter() - start) * 1000
                full_output.write(json.dumps({"qid": qid, "features": full_features.to_dict()}, allow_nan=False) + "\n")
                _add_neural(methods, neural, "top64", query, full_features, config,
                            timings["candidate_selection"], full_feature_ms)
                if args.legacy_grover:
                    reference_results = {}
                    for seed in SEEDS:
                        start, cpu_start = time.perf_counter(), time.process_time()
                        ranked, old_trace = baselines.rerank_frozen(
                            ids, scores, "grover", legacy_threshold, FROZEN["shots"], FROZEN["boost"], [seed])
                        result = summarize_ranking("legacy_grover", ranked[:config.selected_count],
                                                   full_features, config)
                        result.seed = seed
                        result.status = "fallback" if old_trace["fallback"] else "completed"
                        result.trace = [old_trace]
                        result.timings_ms = {"total_ms": (time.perf_counter() - start) * 1000,
                                             "cpu_ms": (time.process_time() - cpu_start) * 1000}
                        result.resources = {"legacy_circuit": old_trace.get("quantum"),
                                            "ordering_policy": "legacy probability-transformed relevance scores",
                                            "note": "Single-seed legacy request; includes fresh search-object construction."}
                        reference_results[str(seed)] = _record_result(
                            result, timings["candidate_selection"], full_feature_ms)
                    methods["legacy_grover"] = {"per_seed_results": reference_results}
            for name, record in methods.items():
                rows = record["per_seed_results"].values() if name in STOCHASTIC else [record["result"]]
                for result in rows:
                    result["timings_ms"]["query_encoding_ms"] = query_encoding_times[qid]
                    result["timings_ms"]["online_total_ms"] = (
                        result["timings_ms"]["retrieval_total_ms"] + query_encoding_times[qid])
            feature_output.write(json.dumps({"qid": qid, "features": features.to_dict()}, allow_nan=False) + "\n")
            records.append({"qid": qid, "candidate_ids": list(features.ids), "shortlist_ids": ids,
                            "shortlist_scores": {d: scores[d] for d in ids}, "methods": methods})
            trace_output.write(json.dumps(records[-1], allow_nan=False) + "\n")
            if query_index % 10 == 0 or query_index == len(test_ids):
                for handle in (feature_output, full_output, trace_output):
                    handle.flush()
                print(f"{args.dataset}: {query_index}/{len(test_ids)} test queries, "
                      f"{time.perf_counter() - test_start:.1f}s", flush=True)
    from datetime import datetime, timezone
    manifest = {"schema": SCHEMA, "profile": "gas", "dataset": args.dataset,
                "canonical_dataset": freeze["dataset"], "freeze": freeze,
                "created_utc": datetime.now(timezone.utc).isoformat(), "config": asdict(config),
                "seeds": list(SEEDS), "methods": sorted(records[0]["methods"]),
                "test_ids": test_ids, "dev_ids": sorted(dev_q), "n_corpus": len(corpus),
                "pilot_ids": pilot_ids, "pilot_role": "development-only",
                "secondary_sample_ids": deterministic_query_subset(
                    test_ids, args.dataset, min(64, len(test_ids)), "gas-secondary-studies-v1"),
                "provenance": metadata, "hardware": hardware_record(), "source_hashes": source_hashes,
                "tuning": tuning, "mmr_tuning": mmr_tuning,
                "neural_models": neural_info, "legacy_threshold": legacy_threshold,
                "offline_timings_ms": {"dataset_and_corpus_encoding": corpus_encoding_ms,
                                       "bm25_build": bm25_build_ms, "test_query_encoding": query_encoding_ms,
                                       "data_independent_subset_basis_setup": basis_setup_ms},
                "representation": "exact compact feasible-subset amplitude simulation",
                "note": "Classical energy enumeration is included. Not full-circuit or physical-QPU timing."}
    seal_run(run_dir, manifest)
    print(f"GAS artifacts saved to {run_dir}; evaluation is a separate explicit command.")
    return run_dir


def summarize_ranking(method: str, ranked: list[str], features: CandidateFeatures,
                      config: GASConfig) -> SelectionResult:
    """Score a selected set without replacing a neural/legacy output ordering."""
    if len(set(ranked)) != len(ranked) or not set(ranked) <= set(features.ids):
        raise ValueError("Ranking must contain unique candidate IDs")
    indices = [features.ids.index(d) for d in ranked]
    chosen = CandidateFeatures(tuple(ranked), features.cosine_scores[indices], features.embeddings[indices])
    result = select_classical(chosen, "cosine", config)
    result.method, result.ranked_ids = method, list(ranked)
    result.resources["ordering_policy"] = "supplied neural or legacy relevance ordering"
    return result


def _add_neural(methods, models, pool_label, query, features, config, selection_ms, feature_ms):
    for label, model in models.items():
        start, cpu_start = time.perf_counter(), time.process_time()
        ranked = model.rank(query, features, config.selected_count)
        result = summarize_ranking(f"neural_{label}_{pool_label}", ranked, features, config)
        result.timings_ms["total_ms"] = (time.perf_counter() - start) * 1000
        result.timings_ms["cpu_ms"] = (time.process_time() - cpu_start) * 1000
        methods[result.method] = {"result": _record_result(result, selection_ms, feature_ms)}


def evaluate_records(manifest: dict, records: list[dict], qrels: dict) -> dict:
    """Pure scoring/coverage function, suitable for in-memory unit fixtures."""
    expected = set(manifest["test_ids"])
    by_id = {r["qid"]: r for r in records}
    if len(by_id) != len(records) or set(by_id) != expected or set(qrels) != expected:
        raise ValueError("Query coverage mismatch or duplicate query records")
    if not expected:
        raise ValueError("Cannot evaluate an empty run")
    seeds = {str(s) for s in manifest["seeds"]}
    if not seeds:
        raise ValueError("Seed list cannot be empty")
    per_query = {method: {} for method in manifest["methods"]}
    requests = {method: [] for method in manifest["methods"]}
    for qid, record in by_id.items():
        if set(record["methods"]) != set(per_query):
            raise ValueError(f"Method coverage mismatch for {qid}")
        for method, payload in record["methods"].items():
            if method in STOCHASTIC:
                if set(payload["per_seed_results"]) != seeds:
                    raise ValueError(f"Seed coverage mismatch for {qid}/{method}")
                if any(r["seed"] != int(s) for s, r in payload["per_seed_results"].items()):
                    raise ValueError(f"Seed labels disagree with results for {qid}/{method}")
                results = [SelectionResult(**r) for r in payload["per_seed_results"].values()]
            else:
                results = [SelectionResult(**payload["result"])]
            scored = []
            for result in results:
                if result.method != method:
                    raise ValueError(f"Result method disagrees with record for {qid}/{method}")
                allowed = set(record["shortlist_ids"] if method.endswith("top64") or method == "legacy_grover"
                              else record["candidate_ids"])
                rank = result.ranked_ids
                if (len(set(rank)) != len(rank) or not set(rank) <= allowed or
                        len(rank) != min(manifest["config"]["selected_count"], len(allowed))):
                    raise ValueError(f"Invalid selected documents for {qid}/{method}")
                if set(result.selected_ids) != set(rank) or len(result.selected_ids) != len(rank):
                    raise ValueError(f"Selected IDs disagree with ranking for {qid}/{method}")
                scores = selection_metrics(result, qrels[qid])
                if method != "legacy_grover" and not method.endswith("top64"):
                    exact = record["methods"].get("exact_quantized", {}).get("result")
                    continuous = record["methods"].get("exact_float", {}).get("result")
                    if exact:
                        scores["quantized_energy_gap"] = float(result.energy - exact["energy"])
                        scores["quantized_optimum_hit"] = float(result.energy == exact["energy"])
                    if continuous:
                        scores["float_utility_gap"] = float(continuous["utility"] - result.utility)
                scored.append(scores)
                requests[method].append(result)
            per_query[method][qid] = {key: float(np.mean([r[key] for r in scored])) for key in scored[0]}
    means = {method: {key: float(np.mean([row[key] for row in values.values()]))
                      for key in next(iter(values.values()))} for method, values in per_query.items()}
    execution = {}
    for method, rows in requests.items():
        status_counts = {}
        for row in rows:
            status_counts[row.status] = status_counts.get(row.status, 0) + 1
        summary = {"requests": len(rows), "status_counts": status_counts,
                   "phase_oracle_calls": sum(r.counts.get("phase_oracle_calls", 0) for r in rows),
                   "classical_simulator_objective_evaluations": sum(
                       r.counts.get("classical_simulator_objective_evaluations", 0) for r in rows)}
        for key in ("total_ms", "retrieval_total_ms", "query_encoding_ms", "online_total_ms", "cpu_ms"):
            values = [r.timings_ms[key] for r in rows if key in r.timings_ms]
            if values:
                summary[key] = {"median": float(np.median(values)), "p95": float(np.percentile(values, 95))}
        execution[method] = summary
    return {"means": means, "per_query": per_query, "n_queries": len(expected), "execution": execution,
            "timing_boundary": "Seeded requests measured individually. Retrieval totals add candidate and "
                               "representative features; online_total_ms also adds freshly measured query encoding. "
                               "Model/corpus loading is offline and reported separately.",
            "scoring": "Metrics averaged across seeds within query; no best-seed or ensemble selection"}


def _load_records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def cmd_evaluate(args) -> Path:
    from . import datasets, metrics

    run_dir = Path(args.run)
    manifest = verify_run(run_dir)
    freeze = manifest["freeze"]
    if not freeze.get("synthetic"):
        for relative, digest in freeze["files"].items():
            if datasets.sha256_file(datasets.DATA_ROOT / freeze["dataset"] / relative) != digest:
                raise ValueError(f"Dataset checksum mismatch: {relative}")
        _, _, qrels = datasets.load_beir(freeze["dataset"], "test")
    else:
        _, _, _, _, qrels = datasets.synthetic_splits()
    result = evaluate_records(manifest, _load_records(run_dir / "traces.jsonl"), qrels)
    primary = result["per_query"]["gas"]
    comparisons, p_values = {}, {}
    for method, rows in result["per_query"].items():
        if method == "gas":
            continue
        base = {q: row["nDCG@5"] for q, row in rows.items()}
        gas = {q: row["nDCG@5"] for q, row in primary.items()}
        comparisons[method] = {**metrics.paired_bootstrap(base, gas), **metrics.paired_randomization(base, gas)}
        p_values[method] = comparisons[method]["p_value"]
    result["comparisons_nDCG@5_gas_minus_baseline"] = comparisons
    result["holm"] = metrics.holm(p_values)
    if "mmr" in result["per_query"]:
        mmr = result["per_query"]["mmr"]
        redundancy = metrics.paired_bootstrap({q: row["redundancy"] for q, row in mmr.items()},
                                              {q: row["redundancy"] for q, row in primary.items()})
        quality = comparisons["mmr"]
        result["primary_target"] = {"quality_margin": -0.01, "quality_ci": quality,
                                    "redundancy_ci": redundancy,
                                    "met": bool(quality["ci_low"] > -0.01 and redundancy["ci_high"] < 0)}
    _write_json(run_dir / "scores.json", result)
    seal_run(run_dir, manifest)
    print(json.dumps(result["means"], indent=2))
    return run_dir


def cmd_report(args) -> Path:
    run_dir = Path(args.run)
    manifest = verify_run(run_dir)
    if "scores.json" not in manifest["result_hashes"]:
        raise ValueError("Evaluate and seal GAS scores before reporting")
    scores = json.loads((run_dir / "scores.json").read_text())
    lines = ["# GAS selection report", "", "Exact compact simulation; all classical preparation costs must be included.",
             "", "| Method | nDCG@5 | nDCG@8 | Recall@8 | Redundancy |", "|---|---:|---:|---:|---:|"]
    for method, row in scores["means"].items():
        redundancy = f"{row['redundancy']:.4f}"
        lines.append(f"| {method} | {row['nDCG@5']:.4f} | {row['nDCG@8']:.4f} | {row['Recall@8']:.4f} | {redundancy} |")
    lines += ["", "| Method | Median selection ms | P95 selection ms | Median retrieval ms | P95 retrieval ms |",
              "|---|---:|---:|---:|---:|"]
    for method, summary in scores["execution"].items():
        selection = summary.get("total_ms", {})
        retrieval = summary.get("retrieval_total_ms", {})
        lines.append(f"| {method} | {selection.get('median', float('nan')):.3f} | "
                     f"{selection.get('p95', float('nan')):.3f} | "
                     f"{retrieval.get('median', float('nan')):.3f} | "
                     f"{retrieval.get('p95', float('nan')):.3f} |")
    lines += ["", "Timing and resource traces are in traces.jsonl; these are not physical-QPU measurements.",
              "", "Primary target:", "```json", json.dumps(scores.get("primary_target"), indent=2), "```", ""]
    (run_dir / "REPORT.md").write_text("\n".join(lines))
    seal_run(run_dir, manifest)
    print("\n".join(lines))
    return run_dir


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    select = sub.add_parser("select", help="Select from an explicit feature JSON file; no dataset/model access")
    select.add_argument("--input", type=Path, required=True)
    select.add_argument("--output", type=Path)
    select.add_argument("--seed", type=int, default=0)
    select.add_argument("--config", type=Path, help="Optional GASConfig JSON object")
    args = parser.parse_args(argv)
    if args.output and args.output.resolve() == args.input.resolve():
        parser.error("Output must not overwrite the input features")
    config = GASConfig(**json.loads(args.config.read_text())) if args.config else GASConfig()
    features = CandidateFeatures.from_dict(json.loads(args.input.read_text()))
    payload = {"schema": SCHEMA, "input_sha256": _sha(args.input),
               "representation": "exact compact feasible-subset amplitude simulation",
               "result": select_evidence(features, config, args.seed).to_dict()}
    if args.output:
        _write_json(args.output, payload)
    else:
        print(json.dumps(payload, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
