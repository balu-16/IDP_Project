"""Explicit tune/run/evaluate lifecycle. No benchmark command runs on import."""
from __future__ import annotations

from dataclasses import asdict, replace
import json
from pathlib import Path

import numpy as np

from research import baselines, datasets, metrics
from research.config_frozen import FROZEN
from research.selection import CandidateFeatures, GASConfig, SelectionResult, selection_metrics
from research.selection_experiment import hardware_record, tune_mmr_weight, tune_weight
from .core import BETAS, PENALTIES, MMR_WEIGHTS, SEEDS, Config, ScoredFeatures, select, take
from .pipeline import (STOCHASTIC, Runtime, execute_features, expected_methods, load_development,
                       model_identity, validate_record)
from .storage import ROOT, Store, atomic_bytes, digest, environment_identity, exclusive, read_checked, sha, write_checked


def data_identity(name):
    return {"dataset": "synthetic", "synthetic": True} if name == "synthetic" else datasets.freeze_record(name)


def require_preflight(name, full_controls, path=None):
    if name == "synthetic":
        return
    path = Path(path or ROOT / "build/accuracy_v2/preflight.json")
    if not path.is_file():
        raise ValueError("Run preflight before development tuning or dataset collection")
    saved = json.loads(path.read_text())
    expected_models = model_identity(full_controls)
    if (saved.get("schema") != "accuracy-v2-preflight" or not saved.get("passed")
            or name not in saved.get("datasets", {})
            or saved["datasets"][name]["freeze"] != data_identity(name)
            or saved.get("environment") != environment_identity()
            or any(saved.get("models", {}).get(label) != value for label, value in expected_models.items())):
        raise ValueError("Preflight is stale or incompatible; rerun preflight for the current files/code/models")


def identity(name, kind, ids, full_controls, legacy, configuration):
    return {"dataset": name, "kind": kind, "data": data_identity(name), "query_ids": sorted(ids),
            "environment": environment_identity(), "models": {} if name == "synthetic" else model_identity(full_controls),
            "full_controls": full_controls, "legacy_grover": legacy, "configuration": configuration,
            "representation": "compact simulated GAS; synthetic scorer only for synthetic dataset"}


def _setup(store, runtime):
    path = store.path / "setup.json"
    previous = read_checked(path) if path.exists() else []
    previous.append({"offline_setup_ms": runtime.offline_ms, "warmup_ms": runtime.warmup_ms,
                     "hardware": hardware_record(),
                     "corpus_cache": getattr(runtime.vecs, "embedding_cache", None),
                     "provenance": getattr(runtime.vecs, "meta", {"embedding_space": "synthetic TF-IDF"})})
    write_checked(path, previous)


def _mean_result(result, rel):
    return selection_metrics(result, rel)


def _tune_query(bundle_by_beta, rel, legacy):
    output = {}
    for beta in BETAS:
        features = ScoredFeatures.from_dict(bundle_by_beta[str(beta)]["guided"])
        cfg = Config(lexical_weight=beta)
        baseline = _mean_result(select(features, "l6_only", cfg), rel)
        penalties = {}
        for penalty in PENALTIES:
            rows = []
            for seed in SEEDS:
                result = select(features, config=replace(cfg, diversity_weight=penalty), seed=seed)
                rows.append({"seed": seed, "ranked_ids": result.ranked_ids, "metrics": _mean_result(result, rel),
                             "counts": result.counts, "status": result.status})
            penalties[str(penalty)] = {"seeds": rows, "means": {key: float(np.mean([r["metrics"][key] for r in rows])) for key in baseline}}
        mmr = {str(weight): _mean_result(select(features, "mmr_l6", cfg, mmr_weight=weight), rel) for weight in MMR_WEIGHTS}
        output[str(beta)] = {"baseline": baseline, "penalties": penalties, "mmr": mmr}
    legacy_scores = {}
    if legacy:
        full = CandidateFeatures.from_dict(bundle_by_beta[str(0.0)]["full"])
        scores = dict(zip(full.ids, map(float, full.cosine_scores)))
        for threshold in (0.5, 0.3, 0.7):
            _, trace = baselines.rerank_frozen(list(full.ids), scores, "sampling", threshold,
                FROZEN["shots"], FROZEN["boost"], list(SEEDS))
            legacy_scores[str(threshold)] = float(np.mean([metrics.ndcg_at(rank[:8], rel, 5) for rank in trace["per_seed_rankings"].values()]))
    return {"grid": output, "legacy_scores": legacy_scores}


def _choose(rows):
    grid = []
    for beta in BETAS:
        baseline = {key: float(np.mean([r["grid"][str(beta)]["baseline"][key] for r in rows])) for key in ("nDCG@5", "Recall@8")}
        for penalty in PENALTIES:
            means = {key: float(np.mean([r["grid"][str(beta)]["penalties"][str(penalty)]["means"][key] for r in rows]))
                     for key in ("nDCG@5", "Recall@8", "redundancy")}
            grid.append({"beta": beta, "penalty": penalty, **means,
                         "eligible": means["nDCG@5"] >= baseline["nDCG@5"] - 1e-12 and means["Recall@8"] >= baseline["Recall@8"] - 1e-12,
                         "same_pool_l6_baseline": baseline})
    eligible = [r for r in grid if r["eligible"]]
    if not eligible:
        raise ArithmeticError("No eligible configuration, including zero penalty")
    # Quantize comparison keys only to resolve numerical ties within 1e-12.
    winner = min(eligible, key=lambda r: (-round(r["nDCG@5"], 12), -round(r["Recall@8"], 12),
                                        round(r["redundancy"], 12), r["penalty"], r["beta"]))
    mmr = []
    for weight in MMR_WEIGHTS:
        means = {key: float(np.mean([r["grid"][str(winner["beta"])]["mmr"][str(weight)][key] for r in rows]))
                 for key in ("nDCG@5", "Recall@8", "redundancy")}
        mmr.append({"weight": weight, **means})
    mmr_winner = min(mmr, key=lambda r: (-round(r["nDCG@5"], 12), -round(r["Recall@8"], 12), round(r["redundancy"], 12), r["weight"]))
    return winner, grid, mmr_winner, mmr


def tune(name, directory, resume=False, full_controls=True, legacy=False, hook=None, preflight_path=None):
    require_preflight(name, full_controls, preflight_path)
    corpus, queries, rel = load_development(name)  # This path never opens test qrels.
    specification = {"betas": list(BETAS), "penalties": list(PENALTIES), "seeds": list(SEEDS),
                     "base_config": asdict(Config()), "mmr_weights": list(MMR_WEIGHTS)}
    ident = identity(name, "tune", queries, full_controls, legacy, specification)
    with exclusive(Path(directory) / ".lock"):
        store = Store(directory, ident, resume)
        frozen_path = store.path / "frozen.json"
        if (store.path / "manifest.json").exists():
            store.verify()
            return frozen_path
        with store.session():
            runtime = None
            for index, qid in enumerate(sorted(queries), 1):
                if store.get("queries", qid) is not None:
                    continue
                bundles = store.get("features", qid)
                if bundles is None:
                    if runtime is None:
                        runtime = Runtime(corpus, full_controls=False, synthetic=name == "synthetic")
                        _setup(store, runtime)
                    retrieved = store.get("retrieved", qid)
                    if retrieved is None:
                        retrieved = runtime.retrieve(queries[qid])
                        store.put("retrieved", qid, retrieved, hook)
                    bundles = {}
                    for beta in BETAS:
                        key = f"{qid}:beta:{beta}"
                        bundle = store.get("tuning_features", key)
                        if bundle is None:
                            bundle = runtime.enrich(queries[qid], retrieved, Config(lexical_weight=beta))
                            store.put("tuning_features", key, bundle, hook)
                        bundles[str(beta)] = bundle
                    store.put("features", qid, bundles, hook)
                store.put("queries", qid, _tune_query(bundles, rel[qid], legacy), hook)
                print(f"Development tuning {name}: {index}/{len(queries)} queries committed", flush=True)
            rows = [store.get("queries", q) for q in sorted(queries)]
            chosen, grid, mmr, mmr_grid = _choose(rows)
            dense = {}
            for qid in sorted(queries):
                full = CandidateFeatures.from_dict(store.get("features", qid)[str(0.0)]["full"])
                dense[qid] = take(full, list(range(min(15, len(full.ids)))))
            old_config, old_tuning = tune_weight(dense, rel, GASConfig())
            old_mmr, old_mmr_tuning = tune_mmr_weight(dense, rel, old_config)
            threshold = None
            if legacy:
                preference = (0.5, 0.3, 0.7)
                threshold = max(preference, key=lambda t: (np.mean([r["legacy_scores"][str(t)] for r in rows]), -preference.index(t)))
            frozen = {"schema": "accuracy-v2-frozen", "tuning_identity": ident, "tuning_identity_sha256": digest(ident),
                      "config": asdict(Config(lexical_weight=chosen["beta"], diversity_weight=chosen["penalty"])),
                      "mmr_weight": mmr["weight"], "grid": grid, "mmr_grid": mmr_grid,
                      "old_config": asdict(old_config), "old_tuning": old_tuning,
                      "old_mmr_weight": old_mmr, "old_mmr_tuning": old_mmr_tuning, "legacy_threshold": threshold,
                      "development_only": True, "test_judgments_used": False,
                      "selection_rule": "Both relevance means >= same-pool L6; maximize nDCG, recall, lower redundancy, smaller penalty, smaller beta"}
            write_checked(frozen_path, frozen)
        def validate_tuning(record, bundles):
            if set(record["grid"]) != {str(b) for b in BETAS} or set(bundles) != {str(b) for b in BETAS}:
                raise ValueError("Incomplete tuning grid")
            for beta in BETAS:
                values = record["grid"][str(beta)]
                if set(values["penalties"]) != {str(p) for p in PENALTIES} or set(values["mmr"]) != {str(w) for w in MMR_WEIGHTS}:
                    raise ValueError("Incomplete penalty/MMR grid")
                for row in values["penalties"].values():
                    if [r["seed"] for r in row["seeds"]] != list(SEEDS):
                        raise ValueError("Incomplete tuning seeds")
        store.seal(queries, validate_tuning)
        return frozen_path


def run(name, directory, frozen_path=None, resume=False, full_controls=True, legacy=False, hook=None, preflight_path=None):
    require_preflight(name, full_controls, preflight_path)
    if frozen_path is not None:
        frozen = read_checked(frozen_path)
        tuning = frozen["tuning_identity"]
        if (not frozen.get("development_only") or frozen.get("test_judgments_used")
                or tuning["dataset"] != name or tuning["data"] != data_identity(name)
                or tuning["environment"] != environment_identity() or tuning["models"] != ({} if name == "synthetic" else model_identity(full_controls))
                or tuning["full_controls"] != full_controls or tuning["legacy_grover"] != legacy):
            raise ValueError("Frozen development configuration is incompatible with this dataset/code/models/control roster")
        # Require the tuning run's sealed coverage, not merely an unattached config file.
        Store(Path(frozen_path).parent, tuning, resume=True).verify()
    elif name == "synthetic":
        frozen = {"config": asdict(Config()), "mmr_weight": 0.0,
                  "old_config": asdict(GASConfig(diversity_weight=0.1)), "old_mmr_weight": 0.0, "legacy_threshold": 0.5 if legacy else None}
    else:
        raise ValueError("Real dataset runs require --frozen from completed development tuning")
    if name == "synthetic":
        corpus, _, _, queries, _ = datasets.synthetic_splits()
    else:
        corpus, _, _, queries, _ = datasets.load_splits(name)
    config, old_config = Config(**frozen["config"]), GASConfig(**frozen["old_config"])
    ident = identity(name, "run", queries, full_controls, legacy, frozen)
    names = expected_methods(full_controls, legacy)
    with exclusive(Path(directory) / ".lock"):
        store = Store(directory, ident, resume)
        if (store.path / "manifest.json").exists():
            store.verify()
            return store.path
        with store.session():
            runtime = None
            for index, qid in enumerate(sorted(queries), 1):
                completed = store.get("queries", qid)
                bundle = store.get("features", qid)
                if completed is not None:
                    if bundle is None:
                        raise ValueError("Result checkpoint has no committed features")
                    validate_record(completed, bundle, names, config.selected_count)
                    continue
                if bundle is None:
                    if runtime is None:
                        runtime = Runtime(corpus, full_controls, synthetic=name == "synthetic")
                        _setup(store, runtime)
                    retrieved = store.get("retrieved", qid)
                    if retrieved is None:
                        retrieved = runtime.retrieve(queries[qid])
                        store.put("retrieved", qid, retrieved, hook)
                    bundle = runtime.enrich(queries[qid], retrieved, config)
                    store.put("features", qid, bundle, hook)
                result = execute_features(bundle, config, frozen["mmr_weight"], old_config,
                                          frozen["old_mmr_weight"], frozen["legacy_threshold"])
                validate_record(result, bundle, names, config.selected_count)
                store.put("queries", qid, result, hook)
                print(f"{name}: {index}/{len(queries)} queries committed", flush=True)
        store.seal(queries, lambda record, features: validate_record(record, features, names, config.selected_count))
        return store.path


def open_completed(directory):
    saved = read_checked(Path(directory) / "run.json")
    ident = saved["identity"]
    if ident["kind"] != "run":
        raise ValueError("Evaluation requires a completed run, not a tuning job")
    if ident["environment"] != environment_identity() or ident["data"] != data_identity(ident["dataset"]):
        raise ValueError("Dataset or source/dependencies changed since collection")
    store = Store(directory, ident, resume=True)
    return store, store.verify()


def evaluate(directory):
    from .checks import independent_metrics
    store, manifest = open_completed(directory)
    ident = store.identity
    name = ident["dataset"]
    if name == "synthetic":
        _, _, _, _, qrels = datasets.synthetic_splits()
    else:
        _, _, _, _, qrels = datasets.load_splits(name)
    if set(qrels) != set(manifest["query_ids"]):
        raise ValueError("Judgment coverage differs from sealed query coverage")
    names = expected_methods(ident["full_controls"], ident["legacy_grover"])
    per_query, timings, statuses, official = {n: {} for n in names}, {n: [] for n in names}, {n: {} for n in names}, []
    for qid in manifest["query_ids"]:
        record, features = store.get("queries", qid), store.get("features", qid)
        validate_record(record, features, names)
        exact = record["methods"]["exact_quantized_l6"]["result"]["energy"]
        for name, payload in record["methods"].items():
            rows = payload["per_seed_results"].values() if name in STOCHASTIC else [payload["result"]]
            values = []
            for row in rows:
                result = SelectionResult(**row)
                scores = selection_metrics(result, qrels[qid])
                if name.endswith("_l6") or name == "l6_only":
                    if result.energy < exact:
                        raise ArithmeticError("Selection beats exact quantized optimum")
                    scores["quantized_energy_gap"] = float(result.energy - exact)
                    scores["quantized_optimum_hit"] = float(result.energy == exact)
                values.append(scores)
                timings[name].append(result.timings_ms)
                statuses[name][result.status] = statuses[name].get(result.status, 0) + 1
                official.append((result.ranked_ids, qrels[qid]))
            per_query[name][qid] = {key: float(np.mean([r[key] for r in values])) for key in values[0]}
    means = {name: {key: float(np.mean([r[key] for r in values.values()])) for key in next(iter(values.values()))}
             for name, values in per_query.items()}
    execution = {}
    for name, rows in timings.items():
        execution[name] = {"requests": len(rows), "statuses": statuses[name]}
        for key in sorted(set.intersection(*(set(r) for r in rows))):
            data = [r[key] for r in rows]
            execution[name][key] = {"median": float(np.median(data)), "p95": float(np.percentile(data, 95))}
    comparisons, pvalues = {}, {}
    for baseline in ("l6_only", "greedy_l6", "mmr_l6", "gas", "fusion", "neural_l6_top64"):
        if baseline not in per_query:
            continue
        a = {q: r["nDCG@5"] for q, r in per_query[baseline].items()}
        b = {q: r["nDCG@5"] for q, r in per_query["gas_l6"].items()}
        statistics = {**metrics.paired_bootstrap(a, b), **metrics.paired_randomization(a, b)}
        comparisons[baseline] = statistics
        pvalues[baseline] = statistics["p_value"]
    result = {"schema": "accuracy-v2-evaluation", "manifest_sha256": sha(store.path / "manifest.json"),
              "means": means, "per_query": per_query, "execution": execution, "comparisons": comparisons,
              "holm": metrics.holm(pvalues), "official_metrics": independent_metrics(official),
              "query_count": len(manifest["query_ids"]), "seed_rule": "Average all five seeds within query; never select the best seed",
              "timing_rule": "online_total includes query encoding, dense retrieval, representative features, lexical prefilter and L6 inference where used; warm-up/loading are separate",
              "limitations": "Classical compact simulation, not physical quantum speedup. Better L6/hybrid inputs do not establish a Grover-specific relevance improvement."}
    write_checked(store.path / "evaluation.json", result)
    return store.path / "evaluation.json"


def report(directory):
    store, manifest = open_completed(directory)
    scores = read_checked(store.path / "evaluation.json")
    if scores["manifest_sha256"] != sha(store.path / "manifest.json"):
        raise ValueError("Evaluation is not bound to this sealed run")
    lines = ["# L6-guided GAS evaluation", "", f"Dataset: {store.identity['dataset']}; queries: {scores['query_count']}.", "",
             "| Method | nDCG@5 | Recall@8 | Redundancy | Online median ms | Online P95 ms |",
             "|---|---:|---:|---:|---:|---:|"]
    for name, means in scores["means"].items():
        timing = scores["execution"][name]["online_total_ms"]
        lines.append(f"| {name} | {means['nDCG@5']:.6f} | {means['Recall@8']:.6f} | {means['redundancy']:.6f} | {timing['median']:.3f} | {timing['p95']:.3f} |")
    lines += ["", scores["seed_rule"], "", scores["timing_rule"], "", scores["limitations"], "",
              "Paired confidence intervals, corrected comparisons, termination statuses, and independent metric checks are in evaluation.json."]
    path = store.path / "REPORT.md"
    atomic_bytes(path, ("\n".join(lines) + "\n").encode())
    return path
