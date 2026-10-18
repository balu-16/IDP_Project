"""Versioned collection, independent evaluation, and frozen accuracy gates."""
from __future__ import annotations

from dataclasses import asdict
from functools import lru_cache
import json
from pathlib import Path

import numpy as np

from research import datasets, metrics
from research.selection import SelectionResult, selection_metrics
from research.accuracy_v2.core import Config as BaseConfig, SEEDS
from research.accuracy_v2.experiment import data_identity, _setup
from research.accuracy_v2.pipeline import model_identity
from research.accuracy_v2.storage import Store as OldStore
from . import VERSION
from .core import Config, METHODS
from .pipeline import Runtime, ensure_features, execute_features, expected_methods, validate_record
from .storage import (ROOT, Store, atomic_bytes, digest, environment_identity, exclusive,
                      extension_identity, read_checked, sha, write_checked)

NAMESPACE = "accuracy-v3-confirmation-v1"
CONFIRMATION_COUNT = 100
RECALL_RATIO = 0.98


@lru_cache(maxsize=3)
def base_frozen(name):
    directory = ROOT / f"research/runs/accuracy_v2_{name}_dev"
    frozen = read_checked(directory / "frozen.json")
    ident = frozen["tuning_identity"]
    if (ident["dataset"] != name or ident["kind"] != "tune" or
            ident["environment"] != environment_identity() or ident["data"] != data_identity(name) or
            not frozen["development_only"] or frozen["test_judgments_used"] or
            not ident["full_controls"] or not ident["legacy_grover"] or ident["models"] != model_identity(True)):
        raise ValueError("Archived v2 configuration is incompatible with the current environment")
    OldStore(directory, ident, resume=True).verify()
    return frozen, sha(directory / "frozen.json"), sha(directory / "manifest.json")


def exclusions(name):
    excluded, sources = set(), {}
    for directory in sorted((ROOT / "research/runs").iterdir()):
        if not directory.is_dir() or directory.name.startswith("accuracy_v3"):
            continue
        if directory.name.startswith("accuracy_v2"):
            path = directory / "run.json"
            if path.exists():
                ident = read_checked(path)["identity"]
                if ident.get("dataset") == name:
                    excluded.update(map(str, ident["query_ids"]))
                    sources[str(path.relative_to(ROOT))] = sha(path)
        else:
            path = directory / "manifest.json"
            if path.exists():
                data = json.loads(path.read_text())
                if data.get("canonical_dataset", data.get("dataset")) == name:
                    for key in ("dev_ids", "test_ids", "pilot_ids", "secondary_sample_ids"):
                        excluded.update(map(str, data.get(key, [])))
                    sources[str(path.relative_to(ROOT))] = sha(path)
    path = ROOT / "build/accuracy_smalltest_20261017T091602Z/features.json"
    if name == "scifact" and path.exists():
        data = json.loads(path.read_text())
        excluded.update(str(row["qid"]) for row in data["records"])
        sources[str(path.relative_to(ROOT))] = sha(path)
    return excluded, sources


def confirmation_queries(name):
    base = datasets.DATA_ROOT / name
    queries, rel = datasets._filter_to_qrels(datasets._load_queries(base, "train"), datasets._load_qrels(base, "train"))
    excluded, sources = exclusions(name)
    ids = datasets.deterministic_query_subset(set(queries) - excluded, name, CONFIRMATION_COUNT, NAMESPACE)
    return {q: queries[q] for q in ids}, {q: rel[q] for q in ids}, sources


def query_data(name, kind):
    if name == "synthetic":
        corpus, dev, dev_rel, test, test_rel = datasets.synthetic_splits()
        return (corpus, dev, dev_rel, {}) if kind == "confirm" else (corpus, test, test_rel, {})
    corpus = datasets._load_corpus(datasets.DATA_ROOT / name)
    if kind == "confirm":
        queries, rel, sources = confirmation_queries(name)
    else:
        recorded = read_checked(ROOT / f"research/runs/accuracy_v2_{name}_test/run.json")["identity"]["query_ids"]
        all_queries = datasets._load_queries(datasets.DATA_ROOT / name, "test")
        queries, rel, sources = {q: all_queries[q] for q in recorded}, None, {}
    return corpus, queries, rel, sources


def identity(name, kind, queries, base, base_hash, base_manifest, config, sources, frozen_path=None):
    return {"schema": VERSION, "dataset": name, "kind": kind, "query_ids": sorted(queries),
            "data": data_identity(name), "environment": environment_identity(), "extension": extension_identity(),
            "models": {} if name == "synthetic" else model_identity(True), "base_frozen": base,
            "base_frozen_sha256": base_hash, "base_manifest_sha256": base_manifest,
            "config": asdict(config), "full_controls": True, "legacy_grover": True,
            "confirmation_namespace": NAMESPACE, "exclusion_sources": sources,
            "frozen_configuration": None if frozen_path is None else {"path": str(Path(frozen_path).resolve()), "sha256": sha(frozen_path)},
            "accuracy_rule": {"recall_ratio_minimum": RECALL_RATIO, "ndcg_tolerance": 1e-12, "redundancy_must_decrease": True},
            "test_role": "post-hoc follow-up on previously observed official tests"}


def synthetic_base():
    from research.selection import GASConfig
    return {"config": asdict(BaseConfig()), "old_config": asdict(GASConfig(diversity_weight=.1)),
            "mmr_weight": 0., "old_mmr_weight": 0., "legacy_threshold": .5}


def collect(name, kind, directory, resume=False, frozen_path=None, hook=None, runtime_factory=None):
    if kind not in {"confirm", "run"}:
        raise ValueError("Unknown collection kind")
    from .checks import require_preflight
    if name != "synthetic":
        require_preflight(name)
    base, base_hash, base_manifest = (synthetic_base(), "synthetic", "synthetic") if name == "synthetic" else base_frozen(name)
    config = Config()
    if kind == "run" and name != "synthetic":
        if frozen_path is None:
            raise ValueError("Test collection requires a frozen, successful confirmation")
        frozen = read_checked(frozen_path)
        if (frozen["dataset"] != name or not frozen["gate"]["passed"] or frozen["extension"] != extension_identity()
                or frozen["environment"] != environment_identity() or frozen["base_frozen_sha256"] != base_hash
                or frozen["config"] != asdict(config) or frozen["data"] != data_identity(name)):
            raise ValueError("Frozen confirmation/configuration is incompatible")
        confirmation, _ = open_completed(frozen["confirmation_directory"])
        if (sha(confirmation.path / "manifest.json") != frozen["confirmation_manifest_sha256"] or
                sha(confirmation.path / "evaluation.json") != frozen["confirmation_evaluation_sha256"]):
            raise ValueError("Frozen confirmation artifacts changed")
    corpus, queries, _, sources = query_data(name, kind)
    ident = identity(name, kind, queries, base, base_hash, base_manifest, config, sources, frozen_path)
    names = expected_methods()
    with exclusive(Path(directory) / ".lock"):
        store = Store(directory, ident, resume)
        if (store.path / "manifest.json").exists():
            store.verify()
            return store.path / "manifest.json"
        with store.session():
            active = None
            def runtime():
                nonlocal active
                if active is None:
                    active = (runtime_factory or Runtime)(corpus, full_controls=True, synthetic=name == "synthetic")
                    _setup(store, active)
                return active
            for index, qid in enumerate(sorted(queries), 1):
                saved = store.get("queries", qid)
                if saved is not None:
                    features = store.get("features", qid)
                    if features is None:
                        raise ValueError("Completed query has no committed features")
                    validate_record(saved, features, names)
                    continue
                features = ensure_features(store, qid, queries[qid], BaseConfig(**base["config"]), runtime, hook)
                result = execute_features(features, base, config)
                validate_record(result, features, names)
                store.put("queries", qid, result, hook)
                print(f"{name} {kind}: {index}/{len(queries)} queries committed; methods={len(names)} seeds=5", flush=True)
        store.seal(queries, lambda record, bundle: validate_record(record, bundle, names))
    return store.path / "manifest.json"


def open_completed(directory):
    saved = read_checked(Path(directory) / "run.json")
    ident = saved["identity"]
    if ident["environment"] != environment_identity() or ident["data"] != data_identity(ident["dataset"]):
        raise ValueError("Dataset or dependencies changed since v3 collection")
    store = Store(directory, ident, resume=True)
    return store, store.verify()


def gate(means):
    before, after = means["gas_l6"], means["gas_v3"]
    ndcg = abs(after["nDCG@5"] - before["nDCG@5"]) <= 1e-12
    recall = after["Recall@8"] + 1e-12 >= RECALL_RATIO * before["Recall@8"]
    redundancy = after["redundancy"] < before["redundancy"] - 1e-12
    ratio = after["Recall@8"] / before["Recall@8"] if before["Recall@8"] else 1.0
    return {"passed": bool(ndcg and recall and redundancy), "ndcg_unchanged": bool(ndcg),
            "recall_within_limit": bool(recall), "redundancy_decreased": bool(redundancy),
            "recall_ratio": ratio, "recall_relative_change_percent": 100 * (ratio - 1),
            "recall_minimum_ratio": RECALL_RATIO,
            "redundancy_relative_reduction_percent": 100 * (before["redundancy"] - after["redundancy"]) / before["redundancy"] if before["redundancy"] else 0.0,
            "baseline": before, "candidate": after}


def evaluate(directory):
    from research.accuracy_v2.checks import independent_metrics
    store, manifest = open_completed(directory)
    ident = store.identity
    if ident["kind"] == "confirm":
        _, _, rel, _ = query_data(ident["dataset"], "confirm")
    elif ident["dataset"] == "synthetic":
        _, _, _, _, rel = datasets.synthetic_splits()
    else:
        rel = datasets._load_qrels(datasets.DATA_ROOT / ident["dataset"], "test")
    if set(rel) != set(manifest["query_ids"]):
        raise ValueError("Evaluation judgments do not match sealed query coverage")
    names = expected_methods()
    per_query, timings, statuses, counts = ({n: {} for n in names}, {n: [] for n in names},
                                          {n: {} for n in names}, {n: {} for n in names})
    official = []
    unchanged = {n: 0 for n in names}
    for qid in manifest["query_ids"]:
        record, features = store.get("queries", qid), store.get("features", qid)
        validate_record(record, features, names)
        for name, payload in record["methods"].items():
            rows = list(payload["per_seed_results"].values()) if "per_seed_results" in payload else [payload["result"]]
            values = []
            for row in rows:
                result = SelectionResult(**row)
                scores = selection_metrics(result, rel[qid])
                if name in METHODS[:5]:
                    exact = record["methods"]["exact_float_v3"]["per_seed_results"][str(result.seed)]
                    scores["float_redundancy_optimum_hit"] = float(abs(result.redundancy - exact["redundancy"]) <= 1e-12)
                    scores["float_redundancy_gap"] = result.redundancy - exact["redundancy"]
                values.append(scores)
                timings[name].append(result.timings_ms)
                statuses[name][result.status] = statuses[name].get(result.status, 0) + 1
                for key, value in result.counts.items():
                    counts[name][key] = counts[name].get(key, 0) + value
                if name in METHODS:
                    base_rank = record["methods"]["gas_l6"]["per_seed_results"][str(result.seed)]["ranked_ids"]
                    unchanged[name] += int(set(result.ranked_ids) == set(base_rank))
                official.append((result.ranked_ids, rel[qid]))
            per_query[name][qid] = {key: float(np.mean([v[key] for v in values])) for key in values[0]}
    means = {n: {key: float(np.mean([v[key] for v in qs.values()])) for key in next(iter(qs.values()))} for n, qs in per_query.items()}
    execution = {}
    for name, rows in timings.items():
        execution[name] = {"requests": len(rows), "statuses": statuses[name], "counts": counts[name],
                           "fallback_requests": sum(value for status, value in statuses[name].items() if "fallback" in status)}
        for key in sorted(set.intersection(*(set(r) for r in rows))):
            data = [r[key] for r in rows]
            execution[name][key] = {"median": float(np.median(data)), "p95": float(np.percentile(data, 95))}
        if name in METHODS:
            execution[name]["unchanged_selection_requests"] = unchanged[name]
    comparisons, pvalues = {}, {}
    for baseline in ("gas_l6", "l6_only", "greedy_v3", "exact_float_v3", "random_v3", "l6_union", "gas", "mmr_l6", "neural_l6_top64"):
        comparisons[baseline] = {}
        for metric in ("nDCG@5", "Recall@8", "nDCG@8", "redundancy"):
            a = {q: v[metric] for q, v in per_query[baseline].items()}
            b = {q: per_query["gas_v3"][q][metric] for q in a}
            b = {q: a[q] if abs(b[q] - a[q]) <= 1e-12 else b[q] for q in a}
            stats = {**metrics.paired_bootstrap(a, b), **metrics.paired_randomization(a, b)}
            stats["queries_increased"] = sum(b[q] > a[q] + 1e-12 for q in a)
            stats["queries_decreased"] = sum(b[q] < a[q] - 1e-12 for q in a)
            comparisons[baseline][metric] = stats
            pvalues[f"{baseline}:{metric}"] = stats["p_value"]
    output = {"schema": VERSION, "manifest_sha256": sha(store.path / "manifest.json"), "query_count": len(rel),
              "means": means, "per_query": per_query, "execution": execution, "comparisons": comparisons,
              "holm": metrics.holm(pvalues), "official_metrics": independent_metrics(official), "gate": gate(means),
              "seed_rule": "Five seeds averaged within query; no best-seed selection",
              "timing_rule": "Fresh shared upstream measurements charged to each pipeline; original and extra L6, baseline selection, and refinement included where required. Loading/warm-up separate.",
              "limitations": "Compact classical simulation; no established Grover speed, cost, or accuracy superiority. Cosine redundancy is a proxy. Recall floor is empirical, not proven non-inferiority. Official tests are a post-hoc follow-up."}
    write_checked(store.path / "evaluation.json", output)
    return store.path / "evaluation.json"


def report(directory):
    store, _ = open_completed(directory)
    data = read_checked(store.path / "evaluation.json")
    if data["manifest_sha256"] != sha(store.path / "manifest.json"):
        raise ValueError("Evaluation is not bound to this manifest")
    lines = ["# Protected-prefix GAS v3 evaluation", "", f"Dataset: {store.identity['dataset']}; stage: {store.identity['kind']}; queries: {data['query_count']}.",
             "", f"Accuracy/redundancy gate: {'PASS' if data['gate']['passed'] else 'FAIL'}.",
             f"Recall relative change: {data['gate']['recall_relative_change_percent']:+.4f}%; permitted minimum ratio: 0.98.", "",
             "| Method | nDCG@5 | Recall@8 | nDCG@8 | Redundancy | Online median ms | Online P95 ms |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for name, means in data["means"].items():
        timing = data["execution"][name]["online_total_ms"]
        lines.append(f"| {name} | {means['nDCG@5']:.6f} | {means['Recall@8']:.6f} | {means['nDCG@8']:.6f} | {means['redundancy']:.6f} | {timing['median']:.3f} | {timing['p95']:.3f} |")
    lines += ["", data["seed_rule"], "", data["timing_rule"], "", data["limitations"], "",
              "Statuses, fallback/unchanged counts, objective gaps, paired query statistics, and independent metric checks are in evaluation.json."]
    atomic_bytes(store.path / "REPORT.md", ("\n".join(lines) + "\n").encode())
    return store.path / "REPORT.md"


def freeze(directory, output):
    store, _ = open_completed(directory)
    if Path(output).resolve().is_relative_to(store.path.resolve()):
        raise ValueError("Write the frozen configuration outside the sealed confirmation directory")
    if store.identity["kind"] != "confirm":
        raise ValueError("Only confirmation results can freeze a configuration")
    data = read_checked(store.path / "evaluation.json")
    if store.identity["dataset"] != "synthetic" and data["query_count"] != CONFIRMATION_COUNT:
        raise ValueError(f"Freezing requires exactly {CONFIRMATION_COUNT} complete confirmation queries")
    if data["manifest_sha256"] != sha(store.path / "manifest.json") or not data["gate"]["passed"]:
        raise ValueError("Confirmation failed an accuracy or redundancy gate; batch must stop")
    payload = {"schema": VERSION, "dataset": store.identity["dataset"], "config": store.identity["config"],
               "base_frozen_sha256": store.identity["base_frozen_sha256"], "data": store.identity["data"],
               "environment": store.identity["environment"], "extension": store.identity["extension"],
               "confirmation_directory": str(store.path.resolve()), "confirmation_manifest_sha256": sha(store.path / "manifest.json"),
               "confirmation_evaluation_sha256": sha(store.path / "evaluation.json"), "gate": data["gate"],
               "test_judgments_used_for_selection": False}
    if Path(output).exists():
        if read_checked(output) != payload:
            raise ValueError("Refusing to replace a frozen configuration")
    else:
        write_checked(output, payload)
    return Path(output)
