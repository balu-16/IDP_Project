"""Fixed, disjoint test stages; sealed checkpoints and query-weighted evaluation."""
from pathlib import Path
import subprocess
import tempfile
import time
import numpy as np

from research import metrics
from research.selection import SelectionResult, selection_metrics
from research.accuracy_v2.core import Config as BaseConfig
from research.accuracy_v2.experiment import _setup
from research.accuracy_v2.storage import exclusive, read_checked, write_checked, sha, utc, atomic_bytes, ROOT, digest
from research.accuracy_v3.core import Config, METHODS
from research.accuracy_v3.experiment import gate
from research.accuracy_v3.pipeline import execute_features, expected_methods
from . import VERSION, data
from .protocol import STUDY, Store, require_frozen
from .pipeline import Runtime, verify_encoding, ensure_features, validate_record

STAGES = ("checkpoint", "continuation")


def collect_into(store, corpus, queries, runtime_factory=Runtime, hook=None, progress=None):
    """No judgments are passed to collection; retain frozen hash order across resumes."""
    names = store.identity["methods"]
    ordered = store.identity["stage_query_ids"]
    if set(ordered) != set(queries) or len(ordered) != len(queries):
        raise ValueError("Collection query IDs differ from frozen stage")
    with store.session():
        active = None
        def runtime():
            nonlocal active
            if active is None:
                active = runtime_factory(corpus)
                _setup(store, active)
            return active
        for index, qid in enumerate(ordered, 1):
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
            print(f"SCIDOCS {store.identity.get('stage', 'fixture')}: {index}/{len(queries)} committed; 27 methods; seeds 0-4", flush=True)
            if progress:
                progress(index, time.perf_counter() - start)
    store.seal(ordered, lambda row, bundle: validate_record(row, bundle, names))


def stage_identity(study, stage):
    if stage not in STAGES:
        raise ValueError("Collection stage must be checkpoint or continuation")
    study = Path(study)
    ident = require_frozen(study)
    encoding = verify_encoding(study, ident)
    value = {**ident, "stage": stage, "stage_query_ids": ident["sampling"][stage],
        "frozen_protocol_sha256": sha(study / "frozen.json"),
        "encoding_artifact_sha256": sha(study / "encoding.json"),
        "embedding_matrix_sha256": encoding["matrix_sha256"]}
    if stage == "continuation":
        require_checkpoint(study)
        value["checkpoint_outcome_sha256"] = sha(study / "checkpoint_outcome.json")
    return value


def run(study=STUDY, stage="checkpoint", resume=False):
    study = Path(study)
    ident = stage_identity(study, stage)  # manual continuation cannot bypass the gate
    corpus, all_queries, _ = data.load()
    queries = {q: all_queries[q] for q in ident["stage_query_ids"]}
    directory = study / stage
    with exclusive(directory / ".lock"):
        store = Store(directory, ident, resume)
        if (directory / "manifest.json").exists():
            store.verify()
            return directory / "manifest.json"
        durations = []
        def progress(index, elapsed):
            durations.append(elapsed)
            write_checked(study / f"{stage}_progress.json", {"updated_utc": utc(), "stage": stage,
                "committed_queries": index, "total_queries": len(queries),
                "mean_query_seconds_this_session": float(np.mean(durations)),
                "estimated_remaining_minutes": float(np.mean(durations)) * (len(queries) - index) / 60})
        collect_into(store, corpus, queries, progress=progress)
    return directory / "manifest.json"


def open_completed(study=STUDY, stage="checkpoint"):
    study = Path(study)
    ident = stage_identity(study, stage)
    store = Store(study / stage, ident, resume=True)
    manifest = store.verify()
    if manifest["query_ids"] != sorted(ident["stage_query_ids"]):
        raise ValueError("Scientific evaluation requires complete frozen stage coverage")
    return store, manifest


def checked_evaluation(study, stage):
    store, manifest = open_completed(study, stage)
    result = read_checked(store.path / "evaluation.json")
    if (result["manifest_sha256"] != sha(store.path / "manifest.json")
            or result["query_count"] != len(manifest["query_ids"])
            or result["protocol"] != store.identity or result["gate"] != gate(result["means"])):
        raise ValueError("Evaluation identity, coverage, or gate mismatch")
    expected_requests = sum(v["requests"] for v in result["execution"].values())
    if result["official_metrics"]["requests_covered"] != expected_requests:
        raise ValueError("Independent metric verification coverage incomplete")
    if set(result["per_query"]) != set(store.identity["methods"]) or any(
            set(rows) != set(manifest["query_ids"]) for rows in result["per_query"].values()):
        raise ValueError("Evaluation method/query coverage incomplete")
    return result


def freeze_checkpoint(study=STUDY):
    """Record either outcome immutably; only PASS authorizes the last 400 IDs."""
    study = Path(study)
    result = checked_evaluation(study, "checkpoint")
    frozen = require_frozen(study)
    if result["query_count"] != 100:
        raise ValueError("Stopping checkpoint requires exactly 100 frozen queries")
    value = {"passed": result["gate"]["passed"], "gate": result["gate"],
        "protocol_sha256": sha(study / "frozen.json"),
        "manifest_sha256": sha(study / "checkpoint/manifest.json"),
        "evaluation_sha256": sha(study / "checkpoint/evaluation.json"),
        "sampling_sha256": frozen["sampling_sha256"],
        "continuation_ids": frozen["sampling"]["continuation"],
        "rule": "Stop after 100 test queries on ANY failed gate; no retuning/resampling"}
    output = study / "checkpoint_outcome.json"
    if output.exists():
        if read_checked(output) != value:
            raise ValueError("Frozen checkpoint outcome changed")
    else:
        write_checked(output, value)
    return output


def require_checkpoint(study=STUDY):
    study = Path(study)
    path = study / "checkpoint_outcome.json"
    if not path.exists():
        raise ValueError("Continuation blocked: verified frozen 100-query outcome is missing")
    saved = read_checked(path)
    freeze_checkpoint(study)  # validates coverage, independent checks, manifest and evaluation hashes
    if not saved["passed"]:
        raise ValueError("Continuation blocked: 100-query scientific gate FAILED; retain partial report")
    return saved


def evaluation_inputs(study, stage):
    study = Path(study)
    if stage != "aggregate":
        store, manifest = open_completed(study, stage)
        return store.path, store.identity, {q: (store.get("queries", q), store.get("features", q)) for q in manifest["query_ids"]}
    require_checkpoint(study)
    frozen = require_frozen(study)
    records, bindings = {}, {}
    for part in STAGES:
        store, manifest = open_completed(study, part)
        for qid in manifest["query_ids"]:
            if qid in records:
                raise ValueError("Overlapping stages; refusing duplicate-weighted aggregate")
            records[qid] = (store.get("queries", qid), store.get("features", qid))
        bindings[part] = {"manifest_sha256": sha(store.path / "manifest.json"), "identity": store.fingerprint}
    if set(records) != set(frozen["query_ids"]) or len(records) != 500:
        raise ValueError("Final aggregate requires exactly all 500 frozen query records")
    directory = study / "aggregate"
    identity = {**frozen, "stage": "aggregate", "stage_query_ids": frozen["query_ids"],
        "stage_bindings": bindings, "checkpoint_outcome_sha256": sha(study / "checkpoint_outcome.json"),
        "aggregation": "Union of 100+400 query records; each query weight 1/500"}
    manifest = {"identity": digest(identity), "query_ids": sorted(records), "stages": bindings}
    output = directory / "manifest.json"
    if output.exists():
        if read_checked(output) != manifest:
            raise ValueError("Aggregate manifest or stage binding changed")
    else:
        write_checked(output, manifest)
    return directory, identity, records


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
                    rf.write(f"{qid} Q0 {did} {rank} {len(ranked) - rank + 1} scidocs_500_v1\n")
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


def query_means(per_query):
    """Equal weight per query, independent of stage sizes or number of seeds."""
    return {n: {k: float(np.mean([v[k] for v in rows.values()]))
                for k in next(iter(rows.values()))} for n, rows in per_query.items()}


def evaluate(study=STUDY, stage="checkpoint"):
    directory, identity, records = evaluation_inputs(study, stage)
    _, _, judgments = data.load()
    names = identity["methods"]
    per_query, timings, counts, statuses = ({n: {} for n in names}, {n: [] for n in names},
                                         {n: {} for n in names}, {n: {} for n in names})
    target = directory / "evaluation.json"
    if target.exists():
        saved = read_checked(target)
        if saved["manifest_sha256"] != sha(directory / "manifest.json") or saved["protocol"] != identity:
            raise ValueError("Existing evaluation provenance mismatch")
        return target
    official = []
    for qid in sorted(records):
        record, bundle = records[qid]
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
    means = query_means(per_query)
    execution = {}
    for name, rows in timings.items():
        execution[name] = {"requests": len(rows), "statuses": statuses[name], "counts": counts[name],
            "fallback_requests": sum(n for status, n in statuses[name].items() if "fallback" in status)}
        for key in sorted(set.intersection(*(set(r) for r in rows))):
            values = [row[key] for row in rows]
            execution[name][key] = {"median": float(np.median(values)), "p95": float(np.percentile(values, 95))}
    family = identity["statistical_family"]
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
    for qid in sorted(records):
        a, b = per_query["gas_l6"][qid], per_query["gas_v3"][qid]
        if b["Recall@8"] < a["Recall@8"] - 1e-12:
            losses.append({"qid": qid, "baseline_recall": a["Recall@8"], "refined_recall": b["Recall@8"],
                "absolute_change": b["Recall@8"] - a["Recall@8"],
                "relative_change_percent": 100 * (b["Recall@8"] / a["Recall@8"] - 1)})
    output = {"schema": VERSION, "manifest_sha256": sha(directory / "manifest.json"), "query_count": len(records),
        "means": means, "per_query": per_query, "execution": execution, "gate": gate(means),
        "comparisons": comparisons, "holm": metrics.holm(pvalues), "recall_loss_queries": losses,
        "official_metrics": independent_metrics(official), "protocol": identity,
        "seed_rule": "Five seeds averaged within each query; deterministic controls once per query; no best-seed selection",
        "timing_rule": "Fresh complete-pipeline timings include retrieval, lexical scoring, original/additional L6, baseline and refinement. Loading, encoding and warm-up are separate. Request median/P95 over recorded query/seed requests.",
        "limitations": identity["limitations"] + " Judgments are incomplete; unjudged documents count as nonrelevant in official metrics. Recall@8 is inherently small when many documents are relevant. Mean gates are descriptive, not statistical non-inferiority."}
    output["self_document_exclusions"] = sum(bundle["self_excluded"] for _, bundle in records.values())
    target = directory / "evaluation.json"
    if target.exists():
        if read_checked(target) != output:
            raise ValueError("Existing evaluation differs; refusing to overwrite scientific outcomes")
    else:
        write_checked(target, output)
    return target



def report(study=STUDY, stage="checkpoint"):
    directory, identity, records = evaluation_inputs(study, stage)
    result = read_checked(directory / "evaluation.json")
    if result["manifest_sha256"] != sha(directory / "manifest.json") or result["protocol"] != identity:
        raise ValueError("Evaluation/manifest provenance mismatch")
    if stage == "checkpoint":
        checked_evaluation(study, stage)
    title = {"checkpoint": "SCIDOCS-100 checkpoint", "continuation": "SCIDOCS-400 continuation (stage diagnostic)",
             "aggregate": "SCIDOCS-500: fixed test subset"}[stage]
    lines = [f"# {title}", "", f"{len(records)} frozen test queries against the complete 25,657-document corpus; 27 methods; seeds 0–4.",
        "No development split or tuning. Query IDs were selected without reading judgments/results.",
        "Identical query/document IDs are excluded before dense top64 for every method; official qrels remain unchanged.", "",
        "The first 100 test queries are a predeclared stopping checkpoint. Continue only if all three checks pass; never retune or resample.",
        "Statistical findings are exploratory and conditional on the early-stop rule; mean gates do not establish statistical non-inferiority.", "",
        f"Scientific gate: **{'PASS' if result['gate']['passed'] else 'FAIL'}**.", ""]
    if stage == "checkpoint":
        lines += ["This is a **100-query partial result**, not a 500-query evaluation. " +
                  ("The frozen continuation may proceed." if result["gate"]["passed"] else "**STOP: do not collect the remaining 400.**"), ""]
    if stage == "aggregate":
        lines += ["The disjoint 100+400 query records were merged, with each query receiving weight 1/500. Stage means were not averaged equally.", ""]
    lines += ["| Check | Outcome |", "|---|---|",
        f"| nDCG@5 unchanged within 1e-12 | {result['gate']['ndcg_unchanged']} |",
        f"| Recall@8 retention ≥98% | {result['gate']['recall_within_limit']}; {100 * result['gate']['recall_ratio']:.4f}% retained |",
        f"| Mean redundancy decreases | {result['gate']['redundancy_decreased']}; reduction {result['gate']['redundancy_relative_reduction_percent']:.4f}% |", "",
        "| Method | nDCG@5 | nDCG@8 | Recall@8 | Precision@8 | Judged@8 | Redundancy ↓ | Pipeline median/P95 ms |",
        "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name, means in result["means"].items():
        timing = result["execution"][name]["online_total_ms"]
        lines.append(f"| {name} | {means['nDCG@5']:.6f} | {means['nDCG@8']:.6f} | {means['Recall@8']:.6f} | {means['Precision@8']:.6f} | {means['judged@8']:.6f} | {means['redundancy']:.6f} | {timing['median']:.2f} / {timing['p95']:.2f} |")
    lines += ["", "## Optimization and termination", "", "| Method | Requests | Fallback statuses | Float optimum hit rate | Phase calls (method / baseline) | Termination statuses |", "|---|---:|---:|---:|---|---|"]
    for name, value in result["execution"].items():
        optimum = result["means"][name].get("float_redundancy_optimum_hit")
        lines.append(f"| {name} | {value['requests']} | {value['fallback_requests']} | {optimum if optimum is not None else 'n/a'} | {value['counts'].get('phase_oracle_calls', 0)} / {value['counts'].get('baseline_phase_oracle_calls', 0)} | {value['statuses']} |")
    lines += ["", "Fallback counts refer to explicit fallback statuses. Budget/feasible-incumbent terminations are shown separately.",
        "", "## Paired comparisons and corrected significance", "",
        "| Baseline | Metric | Mean change | Paired bootstrap 95% CI | Holm p / threshold / reject | Increased / decreased queries |",
        "|---|---|---:|---|---:|---|"]
    for baseline, comparisons in result["comparisons"].items():
        for metric, stats in comparisons.items():
            h = result["holm"][f"{baseline}:{metric}"]
            correction = f"{h['p']:.5g} / {h['holm_alpha']:.5g} / {h['significant']}"
            lines.append(f"| {baseline} | {metric} | {stats['mean_diff']:+.8f} | [{stats['ci_low']:+.8f}, {stats['ci_high']:+.8f}] | {correction} | {stats['queries_increased']} / {stats['queries_decreased']} |")
    lines += ["", f"Queries with Recall@8 loss: {len(result['recall_loss_queries'])}. Individual losses:", "",
        "| Query ID | Baseline recall | Refined recall | Absolute change |", "|---|---:|---:|---:|"]
    for row in result["recall_loss_queries"]:
        lines.append(f"| {row['qid']} | {row['baseline_recall']:.6f} | {row['refined_recall']:.6f} | {row['absolute_change']:+.6f} |")
    lines += ["", result["seed_rule"], "", result["timing_rule"], "", result["limitations"], "",
        "Complete oracle counts and baseline/refinement accounting, all query metrics and optimization gaps are retained in evaluation.json.",
        "Independent trec_eval checks cover nDCG@5/@8, Recall@8 and Precision@8 for every ranking.",
        "Loading/warm-up are recorded separately in each stage's setup.json; encoding/pilot timings are outside online benchmark latency.",
        "Dense model training-data disclosure: https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2 . No manuscript was changed."]
    atomic_bytes(directory / "REPORT.md", ("\n".join(lines) + "\n").encode())
    return directory / "REPORT.md"
