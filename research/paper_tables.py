"""Generate manuscript LaTeX fragments from sealed research artifacts.

The manuscript must not contain hand-entered benchmark values. This module
reads verified run directories and writes compact .tex fragments for the
dataset, configuration, retrieval, timing, matched-control, and resource
tables.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import median


def _load(run: Path) -> tuple[dict, dict]:
    manifest = json.loads((run / "manifest.json").read_text())
    scores = json.loads((run / "scores.json").read_text())
    return manifest, scores


def _tex(value) -> str:
    if value is None:
        return "--"
    return str(value).replace("&", r"\&").replace("%", r"\%").replace("_", r"\_")


def _num(value, digits: int = 3) -> str:
    if value is None:
        return "--"
    return f"{float(value):.{digits}f}"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n")


def dataset_table(runs: list[tuple[dict, dict]]) -> str:
    lines = [
        r"\begin{tabular}{lrrrrrrrrrr}",
        r"\toprule",
        r"Dataset & Corpus & Dev. queries & Test queries & Chunks & Min tokens & Mean tokens & Max tokens & Trunc. & Relevant pairs & Relevant documents\\",
        r"\midrule",
    ]
    for manifest, _ in runs:
        freeze = manifest.get("freeze", {})
        stats = (manifest.get("provenance", {}).get("chunk_statistics", {}) or {})
        lines.append(
            f"{_tex(manifest.get('canonical_dataset', manifest.get('dataset')))} & "
            f"{_tex(manifest.get('n_corpus', '--'))} & "
            f"{_tex(manifest.get('n_dev', '--'))} & "
            f"{_tex(manifest.get('n_test', '--'))} & "
            f"{_tex(stats.get('n_chunks', '--'))} & "
            f"{_num(stats.get('chunk_min_tokens'), 1)} & "
            f"{_num(stats.get('chunk_mean_tokens'), 1)} & "
            f"{_num(stats.get('chunk_max_tokens'), 1)} & "
            f"{_tex(stats.get('truncation_events', '--'))} & "
            f"{_tex(manifest.get('relevant_test_pairs', '--'))} & "
            f"{_tex(manifest.get('unique_relevant_test_docs', '--'))}\\\\"
        )
        if not freeze.get("available", False):
            lines.append(r"\multicolumn{11}{l}{\emph{Dataset files unavailable in this run}}\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines)


def config_table(manifests: list[dict]) -> str:
    manifest = manifests[0]
    cfg = manifest["config"]
    thresholds = " / ".join(f"{m.get('threshold_tuned_on_dev', float('nan')):.3f}"
                            for m in manifests)
    dev_source = "SciFact: SHA-256 20% train sample / NFCorpus: official dev"
    hnsw = manifest.get("hnsw", {})
    deps = manifest.get("dependencies", {})
    platform = str(deps.get("platform", "unknown")).split("-")[0]
    rows = [
        ("Encoder", f"{cfg['encoder']}@{cfg['encoder_revision']}"),
        ("Embedding dimension", cfg["embedding_dimension"]),
        ("Chunk / overlap", f"{cfg['chunk_tokens']} / {cfg['chunk_overlap_tokens']} tokens"),
        ("Candidate budget", cfg["candidate_budget"]),
        ("Threshold (SciFact / NFCorpus)", thresholds),
        ("Development tuning", dev_source),
        ("Shots", cfg["shots"]),
        ("Boost $\\beta$", cfg["boost"]),
        ("Seeds", ", ".join(str(x) for x in cfg["seeds"])),
        ("CPU threads", cfg["cpu_threads"]),
        ("Quantum qubit cap", cfg["qubit_cap"]),
        ("HNSW", f"ef={hnsw.get('ef', '--')}, M={hnsw.get('M', '--')}, overfetch={hnsw.get('overfetch', '--')}, seed={hnsw.get('random_seed', '--')}, threads={hnsw.get('threads', '--')}"),
        ("Host", f"{platform}; {deps.get('cpu_count', '--')} logical CPUs"),
    ]
    lines = [r"\begin{tabular}{ll}", r"\toprule", r"Setting & Value\\", r"\midrule"]
    lines.extend(f"{_tex(k)} & {_tex(v)}\\\\" for k, v in rows)
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines)


def retrieval_table(runs: list[tuple[dict, dict]]) -> str:
    methods = ["bm25", "exact_cosine", "hnsw", "analytical", "sampling", "grover"]
    labels = {
        "bm25": "BM25",
        "exact_cosine": "Exact cosine",
        "hnsw": "HNSW",
        "analytical": "Analytical amplification",
        "sampling": "Classical sampling",
        "grover": "Grover simulation",
    }
    lines = [
        r"\begin{tabular}{llrrrrrr}",
        r"\toprule",
        r"Dataset & Method & $n$ & nDCG@10 & Recall@10 & Recall@64 & MRR@10 & P@5\\",
        r"\midrule",
    ]
    for manifest, scores in runs:
        dataset = manifest.get("canonical_dataset", manifest.get("dataset"))
        for method in methods:
            means = scores.get("means", {}).get(method)
            if not means:
                continue
            lines.append(
                f"{_tex(dataset)} & {_tex(labels[method])} & {scores.get('n_queries', '--')} & "
                f"{_num(means.get('nDCG@10'))} & {_num(means.get('Recall@10'))} & "
                f"{_num(means.get('Recall@64'))} & {_num(means.get('MRR@10'))} & "
                f"{_num(means.get('P@5'))}\\\\"
            )
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines)


def matched_table(runs: list[tuple[dict, dict]]) -> str:
    labels = {
        "analytical_vs_exact_cosine": "Analytical vs. exact",
        "sampling_vs_exact_cosine": "Sampling vs. exact",
        "grover_vs_exact_cosine": "Grover vs. exact",
    }
    lines = [
        r"\begin{tabular}{llrrrrrl}",
        r"\toprule",
        r"Dataset & Comparison & Mean $\Delta$ nDCG & 95\% CI low & 95\% CI high & $p$ & $d_z$ & Holm\\",
        r"\midrule",
    ]
    for manifest, scores in runs:
        dataset = manifest.get("canonical_dataset", manifest.get("dataset"))
        for key, label in labels.items():
            row = scores.get("comparisons", {}).get(key)
            if not row:
                continue
            lines.append(
                f"{_tex(dataset)} & {_tex(label)} & {_num(row.get('mean_diff'))} & "
                f"{_num(row.get('ci_low'))} & {_num(row.get('ci_high'))} & "
                f"{_num(row.get('p_value'))} & {_num(row.get('effect_dz'), 2)} & "
                f"{_tex(scores.get('holm', {}).get(key, {}).get('significant', False))}\\\\"
            )
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines)


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    values = sorted(values)
    index = (len(values) - 1) * p
    low, high = math.floor(index), math.ceil(index)
    if low == high:
        return values[low]
    return values[low] + (values[high] - values[low]) * (index - low)


def timing_table(runs: list[tuple[dict, dict]], run_paths: list[Path]) -> str:
    rows: list[tuple[str, str, float, float]] = []
    for (manifest, _), run in zip(runs, run_paths):
        traces = {}
        with (run / "traces.jsonl").open() as handle:
            for line in handle:
                row = json.loads(line)
                traces[row["qid"]] = row
        dataset = manifest.get("canonical_dataset", manifest.get("dataset"))
        for method in ("bm25", "exact_cosine", "hnsw", "analytical", "sampling", "grover"):
            values = [
                float(traces[qid][method]["timings_ms"]["total"])
                for qid in traces
                if method in traces[qid]
            ]
            if values:
                rows.append((dataset, method, median(values), _percentile(values, 0.95)))
    labels = {"bm25": "BM25", "exact_cosine": "Exact cosine", "hnsw": "HNSW",
              "analytical": "Analytical", "sampling": "Sampling", "grover": "Grover"}
    lines = [r"\begin{tabular}{llrr}", r"\toprule",
             r"Dataset & Method & Median ms & P95 ms\\", r"\midrule"]
    lines += [f"{_tex(d)} & {_tex(labels[m])} & {_num(med, 1)} & {_num(p95, 1)}\\\\"
              for d, m, med, p95 in rows]
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines)


def resource_table(runs: list[tuple[dict, dict]], run_paths: list[Path]) -> str:
    rows = []
    for (manifest, _), run in zip(runs, run_paths):
        resource_path = run / "resources.json"
        if not resource_path.exists():
            continue
        resources = json.loads(resource_path.read_text())
        dataset = manifest.get("canonical_dataset", manifest.get("dataset"))
        for qid, payload in resources.items():
            for row in payload.get("rows", []):
                if row.get("supported"):
                    rows.append((dataset, qid, row))
    grouped = {}
    for dataset, _, row in rows:
        key = (dataset, row.get("candidates"), row.get("score_bits"))
        grouped.setdefault(key, []).append(row)
    lines = [r"\begin{tabular}{lrrrrrrrrrrrr}", r"\toprule",
             r"Dataset & $K$ & Bits & Qubits & Marked & Q-change & Oracle depth & Oracle 1q & Oracle 2q & Search depth & Search 1q & Search 2q & Build ms\\",
             r"\midrule"]
    for (dataset, candidates, bits), group in sorted(grouped.items()):
        def med(key):
            return median([float(item.get(key, 0.0)) for item in group])

        lines.append(
            f"{_tex(dataset)} & {candidates} & {bits} & {int(med('total_qubits'))} & "
            f"{int(median([len(item.get('marked_indices', [])) for item in group]))} & "
            f"{int(med('quantization_changed_marks'))} & {int(med('oracle_depth'))} & "
            f"{int(med('oracle_one_q'))} & {int(med('oracle_two_q'))} & "
            f"{int(med('circuit_depth'))} & {int(med('circuit_one_q'))} & "
            f"{int(med('circuit_two_q'))} & {med('build_ms'):.1f}\\\\"
        )
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines)


def _findings(runs: list[tuple[dict, dict]]) -> tuple[str, str]:
    abstract = []
    results = []
    labels = {"scifact": "SciFact", "nfcorpus": "NFCorpus"}
    for manifest, scores in runs:
        dataset = manifest.get("canonical_dataset", manifest.get("dataset"))
        dataset_label = labels.get(dataset, dataset)
        means = scores["means"]
        exact = means["exact_cosine"]["nDCG@10"]
        grover = means["grover"]["nDCG@10"]
        analytical = means["analytical"]["nDCG@10"]
        sampling = means["sampling"]["nDCG@10"]
        delta = grover - exact
        comp = scores["comparisons"]["grover_vs_exact_cosine"]
        abstract.append(
            f"On {dataset_label}, Grover simulation changed nDCG@10 by {delta:+.4f} "
            f"relative to exact cosine (paired $p$={comp['p_value']:.3f}); the analytical "
            f"control was {analytical:.3f} and matched classical sampling was {sampling:.3f}."
        )
        results.append(
            f"For {dataset_label}, exact cosine achieved nDCG@10={exact:.3f}, while Grover "
            f"simulation achieved {grover:.3f} (paired difference {delta:+.4f}, "
            f"95\\% CI [{comp['ci_low']:.4f},{comp['ci_high']:.4f}], "
            f"$p$={comp['p_value']:.3f}). The analytical control was {analytical:.3f}, "
            f"showing whether the ideal probability rule itself changed the ranking."
        )
    return " ".join(abstract), " ".join(results)


def generate(scifact: Path, nfcorpus: Path, output: Path) -> None:
    run_paths = [scifact, nfcorpus]
    runs = [_load(path) for path in run_paths]
    _write(output / "dataset_table.tex", dataset_table(runs))
    _write(output / "config_table.tex", config_table([manifest for manifest, _ in runs]))
    _write(output / "retrieval_table.tex", retrieval_table(runs))
    _write(output / "matched_table.tex", matched_table(runs))
    _write(output / "timing_table.tex", timing_table(runs, run_paths))
    _write(output / "resource_table.tex", resource_table(runs, run_paths))
    abstract, results = _findings(runs)
    _write(output / "abstract_findings.tex", abstract)
    _write(output / "results_findings.tex", results)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scifact-run", type=Path, required=True)
    parser.add_argument("--nfcorpus-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("new_paper/generated"))
    args = parser.parse_args()
    generate(args.scifact_run, args.nfcorpus_run, args.output)


if __name__ == "__main__":
    main()
