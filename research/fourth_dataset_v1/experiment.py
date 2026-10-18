"""Atomic 50-query collection and independent, seed-averaged evaluation."""
from pathlib import Path
import subprocess
import tempfile
import time

import numpy as np

from research import metrics
from research.selection import SelectionResult, selection_metrics
from research.accuracy_v2.core import Config as BaseConfig
from research.accuracy_v2.experiment import _setup
from research.accuracy_v2.storage import exclusive, read_checked, write_checked, sha, utc, atomic_bytes, ROOT
from research.accuracy_v3.core import Config, METHODS
from research.accuracy_v3.experiment import gate
from research.accuracy_v3.pipeline import ensure_features, execute_features, validate_record, expected_methods
from . import VERSION, data
from .protocol import STUDY, Store, require_frozen
from .pipeline import Runtime, verify_encoding


def collect_into(store, corpus, queries, runtime_factory=Runtime, hook=None, progress=None):
    """Shared real/synthetic recovery path; labels are never used by collection."""
    names = store.identity["methods"]
    with store.session():
        active = None
        def runtime():
            nonlocal active
            if active is None:
                active = runtime_factory(corpus)
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
            start = time.perf_counter()
            base = store.identity["base_frozen"]
            features = ensure_features(store, qid, queries[qid], BaseConfig(**base["config"]), runtime, hook)
            result = execute_features(features, base, Config(**store.identity["config"]))
            validate_record(result, features, names)
            store.put("queries", qid, result, hook)
            print(f"TREC-COVID: {index}/{len(queries)} committed; 27 methods; seeds 0-4", flush=True)
            if progress:
                progress(index, time.perf_counter() - start)
    store.seal(queries, lambda row, bundle: validate_record(row, bundle, names))


def run(study=STUDY, resume=False):
    study = Path(study)
    ident = require_frozen(study)
    encoding = verify_encoding(study, ident)
    ident = {**ident, "frozen_protocol_sha256": sha(study / "frozen.json"),
             "encoding_artifact_sha256": sha(study / "encoding.json"),
             "embedding_matrix_sha256": encoding["matrix_sha256"]}
    corpus, queries, _ = data.load()
    if sorted(queries) != ident["query_ids"]:
        raise ValueError("Collection query coverage differs from frozen protocol")
    directory = study / "test"
    with exclusive(directory / ".lock"):
        store = Store(directory, ident, resume)
        if (directory / "manifest.json").exists():
            store.verify()
            return directory / "manifest.json"
        durations = []
        def progress(index, elapsed):
            durations.append(elapsed)
            write_checked(study / "collection_progress.json", {"updated_utc": utc(),
                "committed_queries": index, "total_queries": len(queries),
                "mean_query_seconds_this_session": float(np.mean(durations)),
                "estimated_remaining_minutes": float(np.mean(durations)) * (len(queries) - index) / 60})
        collect_into(store, corpus, queries, progress=progress)
    return directory / "manifest.json"


def open_completed(study=STUDY):
    study = Path(study)
    frozen = require_frozen(study)
    saved = read_checked(study / "test/run.json")["identity"]
    for key, value in frozen.items():
        if saved[key] != value:
            raise ValueError(f"Collected identity differs from frozen protocol: {key}")
    if saved["frozen_protocol_sha256"] != sha(study / "frozen.json") or saved["encoding_artifact_sha256"] != sha(study / "encoding.json"):
        raise ValueError("Collection protocol/encoding provenance mismatch")
    store = Store(study / "test", saved, resume=True)
    manifest = store.verify()
    if manifest["query_ids"] != frozen["query_ids"] or len(manifest["query_ids"]) != 50:
        raise ValueError("Scientific evaluation requires all 50 queries")
    return store, manifest


def diagnostics(ranking, judgments):
    positive = {did: g for did, g in judgments.items() if g > 0}
    top = ranking[:8]
    return {"Precision@8": metrics.precision_at(top, positive, 8),
            "judged@8": sum(judgments.get(d, -1) >= 0 for d in top) / 8,
            "unjudged@8": sum(judgments.get(d, -1) < 0 for d in top) / 8,
            "nonrelevant_judged@8": sum(judgments.get(d, -1) == 0 for d in top) / 8}


def independent_metrics(requests, executable=ROOT / "build/tools/trec_eval"):
    """Official checks at both nDCG cutoffs, recall, and precision for every unique request."""
    executable = Path(executable)
    if not executable.is_file():
        raise ValueError("Pinned independent trec_eval executable is missing")
    expected, seen_requests, all_requests = {}, {}, 0
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        with (root / "qrels").open("w") as qf, (root / "run").open("w") as rf:
            for ranked, raw in requests:
                all_requests += 1
                signature = (tuple(ranked), tuple(sorted(raw.items())))
                if signature in seen_requests:
                    continue
                qid = f"Q{len(expected)}"
                seen_requests[signature] = qid
                for did, grade in raw.items():
                    qf.write(f"{qid} 0 {did} {grade}\n")
                for rank, did in enumerate(ranked, 1):
                    rf.write(f"{qid} Q0 {did} {rank} {len(ranked) - rank + 1} fourth_dataset_v1\n")
                pos = {d: g for d, g in raw.items() if g > 0}
                expected[qid] = {"ndcg_cut_5": metrics.ndcg_at(ranked, pos, 5),
                    "ndcg_cut_8": metrics.ndcg_at(ranked, pos, 8),
                    "recall_8": metrics.recall_at(ranked, pos, 8),
                    "P_8": metrics.precision_at(ranked, pos, 8)}
        command = [str(executable), "-q", "-m", "ndcg_cut.5,8", "-m", "recall.8", "-m", "P.8", str(root / "qrels"), str(root / "run")]
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        seen, maximum_error = set(), 0.
        for line in result.stdout.splitlines():
            name, qid, value = line.split()
            if qid == "all":
                continue
            pair = qid, name
            if pair in seen or qid not in expected or name not in expected[qid]:
                raise ValueError("Unexpected or duplicate independent metric output")
            error = abs(float(value) - expected[qid][name])
            if error > .000051:
                raise ArithmeticError(f"trec_eval disagreement: {qid}/{name}: {error}")
            maximum_error = max(maximum_error, error)
            seen.add(pair)
        if len(seen) != 4 * len(expected):
            raise ValueError("Incomplete independent metric verification")
    return {"requests_covered": all_requests, "unique_requests": len(expected), "checks": len(seen),
            "maximum_rounding_error": maximum_error, "tolerance": .000051,
            "executable_sha256": sha(executable), "gain": "linear graded gains; grade > 0 relevant for recall/precision",
            "deduplication": "Identical ranking and full graded judgments checked once; every result is covered"}


def evaluate(study=STUDY):
    store, manifest = open_completed(study)
    _, _, judgments = data.load()
    names = store.identity["methods"]
    per_query, timings, counts, statuses = ({n: {} for n in names}, {n: [] for n in names},
                                         {n: {} for n in names}, {n: {} for n in names})
    official = []
    for qid in manifest["query_ids"]:
        record, bundle = store.get("queries", qid), store.get("features", qid)
        validate_record(record, bundle, names)
        for name, payload in record["methods"].items():
            rows = list(payload["per_seed_results"].values()) if "per_seed_results" in payload else [payload["result"]]
            values = []
            for row in rows:
                result = SelectionResult(**row)
                value = {**selection_metrics(result, judgments[qid]), **diagnostics(result.ranked_ids, judgments[qid])}
                if name in METHODS[:5]:
                    optimum = record["methods"]["exact_float_v3"]["per_seed_results"][str(result.seed)]["redundancy"]
                    value.update(float_redundancy_optimum_hit=float(abs(result.redundancy - optimum) <= 1e-12),
                                 float_redundancy_gap=result.redundancy - optimum)
                values.append(value)
                timings[name].append(result.timings_ms)
                statuses[name][result.status] = statuses[name].get(result.status, 0) + 1
                for key, value in result.counts.items():
                    counts[name][key] = counts[name].get(key, 0) + value
                official.append((result.ranked_ids, judgments[qid]))
            per_query[name][qid] = {k: float(np.mean([v[k] for v in values])) for k in values[0]}
    means = {n: {k: float(np.mean([v[k] for v in rows.values()])) for k in next(iter(rows.values()))} for n, rows in per_query.items()}
    execution = {}
    for name, rows in timings.items():
        execution[name] = {"requests": len(rows), "statuses": statuses[name], "counts": counts[name],
            "fallback_requests": sum(n for status, n in statuses[name].items() if "fallback" in status)}
        for key in sorted(set.intersection(*(set(r) for r in rows))):
            values = [row[key] for row in rows]
            execution[name][key] = {"median": float(np.median(values)), "p95": float(np.percentile(values, 95))}
    family = store.identity["statistical_family"]
    comparisons, pvalues = {}, {}
    for baseline in family["baselines"]:
        comparisons[baseline] = {}
        for metric in family["metrics"]:
            a = {q: v[metric] for q, v in per_query[baseline].items()}
            b = {q: per_query["gas_v3"][q][metric] for q in a}
            b = {q: a[q] if abs(b[q] - a[q]) <= 1e-12 else b[q] for q in a}
            stats = {**metrics.paired_bootstrap(a, b), **metrics.paired_randomization(a, b)}
            stats.update(queries_increased=sum(b[q] > a[q] + 1e-12 for q in a),
                         queries_decreased=sum(b[q] < a[q] - 1e-12 for q in a))
            comparisons[baseline][metric] = stats
            pvalues[f"{baseline}:{metric}"] = stats["p_value"]
    losses = []
    for qid in manifest["query_ids"]:
        a, b = per_query["gas_l6"][qid], per_query["gas_v3"][qid]
        if b["Recall@8"] < a["Recall@8"] - 1e-12:
            losses.append({"qid": qid, "baseline_recall": a["Recall@8"], "refined_recall": b["Recall@8"],
                "absolute_change": b["Recall@8"] - a["Recall@8"],
                "relative_change_percent": 100 * (b["Recall@8"] / a["Recall@8"] - 1)})
    output = {"schema": VERSION, "manifest_sha256": sha(store.path / "manifest.json"), "query_count": len(manifest["query_ids"]),
        "means": means, "per_query": per_query, "execution": execution, "gate": gate(means),
        "comparisons": comparisons, "holm": metrics.holm(pvalues), "recall_loss_queries": losses,
        "official_metrics": independent_metrics(official), "protocol": store.identity,
        "seed_rule": "Five seeds averaged within each query; deterministic controls once per query; no best-seed selection",
        "timing_rule": "Fresh complete-pipeline timings include retrieval, lexical scoring, original/additional L6, baseline and refinement. Loading, encoding and warm-up are separate. Request median/P95 over recorded query/seed requests.",
        "limitations": store.identity["limitations"] + " Judgments are incomplete; unjudged documents count as nonrelevant in official metrics. Recall@8 is inherently small when many documents are relevant. Mean gates are descriptive, not statistical non-inferiority."}
    write_checked(store.path / "evaluation.json", output)
    return store.path / "evaluation.json"


def report(study=STUDY):
    store, _ = open_completed(study)
    result = read_checked(store.path / "evaluation.json")
    if result["manifest_sha256"] != sha(store.path / "manifest.json"):
        raise ValueError("Evaluation/manifest provenance mismatch")
    lines = ["# TREC-COVID predeclared transfer evaluation", "", "50 queries; 171,332 documents; 27 methods; seeds 0–4.",
        "No development tuning or test-judgment confirmation was performed.", "",
        f"Scientific gate: **{'PASS' if result['gate']['passed'] else 'FAIL'}**. All 50 queries were retained.", "",
        "| Check | Outcome |", "|---|---|",
        f"| nDCG@5 unchanged | {result['gate']['ndcg_unchanged']} |",
        f"| Recall@8 retention ≥98% | {result['gate']['recall_within_limit']}; {100 * result['gate']['recall_ratio']:.4f}% retained |",
        f"| Mean redundancy decreases | {result['gate']['redundancy_decreased']}; reduction {result['gate']['redundancy_relative_reduction_percent']:.4f}% |", "",
        "| Method | nDCG@5 | nDCG@8 | Recall@8 | Precision@8 | Judged@8 | Redundancy ↓ | Pipeline median/P95 ms |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name, means in result["means"].items():
        timing = result["execution"][name]["online_total_ms"]
        lines.append(f"| {name} | {means['nDCG@5']:.6f} | {means['nDCG@8']:.6f} | {means['Recall@8']:.6f} | {means['Precision@8']:.6f} | {means['judged@8']:.6f} | {means['redundancy']:.6f} | {timing['median']:.2f} / {timing['p95']:.2f} |")
    lines += ["", "## Optimization and termination", "", "| Method | Requests | Fallback statuses | Float optimum hit rate | Termination statuses |", "|---|---:|---:|---:|---|"]
    for name, value in result["execution"].items():
        optimum = result["means"][name].get("float_redundancy_optimum_hit")
        lines.append(f"| {name} | {value['requests']} | {value['fallback_requests']} | {optimum if optimum is not None else 'n/a'} | {value['statuses']} |")
    lines += ["", "Fallback counts refer to explicit fallback status labels; feasible-incumbent/budget terminations remain separately visible above.",
        "", "## Paired query comparisons against matched baseline GAS", "", "| Metric | Mean change | Paired bootstrap 95% CI | Increased / decreased queries |", "|---|---:|---|---|"]
    for metric, stats in result["comparisons"]["gas_l6"].items():
        lines.append(f"| {metric} | {stats['mean_diff']:+.8f} | [{stats['ci_low']:+.8f}, {stats['ci_high']:+.8f}] | {stats['queries_increased']} / {stats['queries_decreased']} |")
    lines += ["", f"Queries with Recall@8 loss: {len(result['recall_loss_queries'])}; individual losses are recorded in evaluation.json.",
        "", result["seed_rule"], "", result["timing_rule"], "", result["limitations"], "",
        "Complete per-query diagnostics, all paired comparisons, Holm correction, stage accounting and oracle counts are in evaluation.json. Independent trec_eval verification covers nDCG@5/@8, Recall@8 and Precision@8 for every ranking.",
        "", "Loading and artificial warm-up measurements: test/setup.json. Corpus encoding: ../encoding.json; pilot: ../encoding_pilot.json. No manuscript was changed."]
    atomic_bytes(store.path / "REPORT.md", ("\n".join(lines) + "\n").encode())
    return store.path / "REPORT.md"
