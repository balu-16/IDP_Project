"""Generate manuscript fragments from verified, sealed experiment runs.

The original experiment-hashed research/paper_tables.py is intentionally left
unchanged. This paper-layer wrapper adds explicit fallback disclosure and IEEE
presentation refinements without changing or resealing experiment artifacts.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from research import artifacts, datasets, paper_tables


def _config_table(manifests: list[dict]) -> str:
    text = paper_tables.config_table(manifests)
    text = text.replace("Quantum qubit cap", "Resource-grid total-qubit cap")
    hnsw = manifests[0].get("hnsw", {})
    text = text.replace(
        "HNSW & ef=",
        f"HNSW & efConstruction={hnsw.get('ef_construction', '--')}, ef=",
    )
    schema = manifests[0].get("provenance", {}).get("schema_version", "--")
    text = text.replace(
        r"\bottomrule",
        f"Manifest schema & {paper_tables._tex(schema)}\\\\\n\\bottomrule",
    )
    return text


def _retrieval_table(runs: list[tuple[dict, dict]]) -> str:
    text = paper_tables.retrieval_table(runs)
    return (
        text.replace("Analytical amplification", "Analytical policy")
        .replace("Classical sampling", "Classical-sampling policy")
        .replace("Grover simulation", "Grover policy")
    )


def _matched_table(runs: list[tuple[dict, dict]]) -> str:
    labels = {
        "bm25_vs_exact_cosine": "BM25 full pipeline vs. exact",
        "hnsw_vs_exact_cosine": "HNSW full pipeline vs. exact",
        "analytical_vs_exact_cosine": "Analytical vs. exact",
        "sampling_vs_exact_cosine": "Sampling vs. exact",
        "grover_vs_exact_cosine": "Grover policy vs. exact",
    }
    lines = [
        r"\begin{tabular}{llrrrrrl}",
        r"\toprule",
        r"Dataset & Comparison & $\Delta$ nDCG ($10^{-3}$) & 95\% CI low & 95\% CI high & raw $p$ & $d_z$ & Holm reject\\",
        r"\midrule",
    ]
    for manifest, scores in runs:
        dataset = manifest.get("canonical_dataset", manifest.get("dataset"))
        for key, label in labels.items():
            row = scores.get("comparisons", {}).get(key)
            if row is None:
                continue
            lines.append(
                f"{paper_tables._tex(dataset)} & {paper_tables._tex(label)} & "
                f"{paper_tables._num(row['mean_diff'] * 1000, 3)} & "
                f"{paper_tables._num(row['ci_low'] * 1000, 3)} & "
                f"{paper_tables._num(row['ci_high'] * 1000, 3)} & "
                f"{paper_tables._num(row['p_value'])} & "
                f"{paper_tables._num(row['effect_dz'], 3)} & "
                f"{'Yes' if scores.get('holm', {}).get(key, {}).get('significant', False) else 'No'}\\\\"
            )
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines)


def _fallback_counts(run_path: Path) -> tuple[int, int, int]:
    total = no_marked = executed = 0
    with (run_path / "traces.jsonl").open() as handle:
        for line in handle:
            record = json.loads(line).get("grover", {})
            total += 1
            no_marked += record.get("fallback") == "no_marked_items"
            executed += record.get("quantum") is not None
    return total, no_marked, executed


def _query_accounting(manifests: list[dict]) -> str:
    expected_splits = {
        "scifact": ("train", "test"),
        "nfcorpus": ("train", "dev", "test"),
    }
    counts = {}
    for manifest in manifests:
        dataset = manifest.get("canonical_dataset", manifest.get("dataset"))
        if dataset not in expected_splits:
            raise ValueError(f"unexpected dataset for query accounting: {dataset}")
        frozen_files = manifest.get("freeze", {}).get("files", {})
        required_files = {"queries.jsonl"} | {
            f"qrels/{split}.tsv" for split in expected_splits[dataset]
        }
        missing_files = required_files - set(frozen_files)
        if missing_files:
            raise ValueError(
                f"{dataset}: manifest does not freeze required query/qrel files: "
                f"{sorted(missing_files)}"
            )

        _, queries, test_qrels = datasets.load_beir(dataset, "test")
        query_ids = set(queries)
        test_ids = set(test_qrels)
        if test_ids - query_ids:
            raise ValueError(f"{dataset}: test qrels contain query IDs without query text")
        if test_ids != set(manifest["test_ids"]):
            raise ValueError(f"{dataset}: local positive test-qrel IDs differ from sealed manifest")

        split_ids = {}
        for split in expected_splits[dataset]:
            _, _, qrels = datasets.load_beir(dataset, split)
            split_ids[split] = set(qrels)
            if split_ids[split] - query_ids:
                raise ValueError(f"{dataset}: {split} qrels contain query IDs without query text")
        all_qrel_ids = set().union(*split_ids.values())
        if query_ids != all_qrel_ids:
            raise ValueError(
                f"{dataset}: shared query rows do not equal the union of positive IDs "
                "in the frozen split qrels"
            )
        for i, split in enumerate(expected_splits[dataset]):
            for other in expected_splits[dataset][i + 1:]:
                if split_ids[split] & split_ids[other]:
                    raise ValueError(f"{dataset}: query IDs overlap between {split} and {other} qrels")

        counts[dataset] = (len(query_ids), len(test_ids), len(query_ids - test_ids))
    scifact = counts["scifact"]
    nfcorpus = counts["nfcorpus"]
    return (
        "The shared query JSONL files contain "
        f"{scifact[0]:,} SciFact and {nfcorpus[0]:,} NFCorpus query rows across splits. "
        "The positive IDs in the official test qrels select "
        f"{scifact[1]:,} and {nfcorpus[1]:,} judged test queries, respectively; "
        "all selected IDs have query text. The remaining "
        f"{scifact[2]:,} and {nfcorpus[2]:,} rows are excluded because they are outside "
        "the positive test-qrel ID sets; they are not characterized as unjudged test examples."
    )


def _findings(runs: list[tuple[dict, dict]], run_paths: list[Path]) -> tuple[str, str]:
    abstract = []
    results = []
    labels = {"scifact": "SciFact", "nfcorpus": "NFCorpus"}
    execution_summary = []
    for (manifest, scores), run_path in zip(runs, run_paths):
        dataset = manifest.get("canonical_dataset", manifest.get("dataset"))
        dataset_label = labels.get(dataset, dataset)
        means = scores["means"]
        exact = means["exact_cosine"]["nDCG@10"]
        grover = means["grover"]["nDCG@10"]
        analytical = means["analytical"]["nDCG@10"]
        sampling = means["sampling"]["nDCG@10"]
        delta = grover - exact
        comp = scores["comparisons"]["grover_vs_exact_cosine"]
        total, no_marked, executed = _fallback_counts(run_path)
        execution_summary.append(
            f"{dataset_label}: circuits ran for {executed}/{total} queries; "
            f"{no_marked}/{total} used exact-cosine fallback because no candidate met the threshold"
        )
        abstract.append(
            f"On {dataset_label}, the Grover policy changed mean normalized discounted "
            f"cumulative gain at rank 10 by {delta:+.4f} relative to exact cosine "
            f"(paired $p$={comp['p_value']:.3f}); the analytical control scored "
            f"{analytical:.3f} and matched classical sampling scored {sampling:.3f}."
        )
        results.append(
            f"For {dataset_label}, exact cosine achieved nDCG@10={exact:.3f}, while the Grover "
            f"policy achieved {grover:.3f} (paired difference {delta:+.4f}, "
            f"95\\% CI [{comp['ci_low']:.4f},{comp['ci_high']:.4f}], "
            f"$p$={comp['p_value']:.3f}). The analytical control was {analytical:.3f}. "
            f"Grover circuits ran for {executed}/{total} queries; {no_marked}/{total} "
            f"used exact-cosine fallback because no candidate met the threshold."
        )
    abstract.append("Across the test sets, " + "; ".join(execution_summary) + ".")
    results.append(
        "The analytical and sampling policies use the same no-marked cosine fallback. "
        "Aggregate scores therefore evaluate the declared hybrid policies, not circuit execution on every query."
    )
    return " ".join(abstract), " ".join(results)


def generate(scifact: Path, nfcorpus: Path, output: Path) -> None:
    run_paths = [scifact, nfcorpus]
    for path in run_paths:
        artifacts.verify_manifest(path)
    runs = [paper_tables._load(path) for path in run_paths]
    paper_tables.generate(scifact, nfcorpus, output)
    manifests = [manifest for manifest, _ in runs]
    paper_tables._write(output / "config_table.tex", _config_table(manifests))
    paper_tables._write(output / "retrieval_table.tex", _retrieval_table(runs))
    paper_tables._write(output / "matched_table.tex", _matched_table(runs))
    resource_path = output / "resource_table.tex"
    paper_tables._write(
        resource_path,
        resource_path.read_text().replace("Build ms", "Build/export ms"),
    )
    abstract, results = _findings(runs, run_paths)
    paper_tables._write(output / "abstract_findings.tex", abstract)
    paper_tables._write(output / "results_findings.tex", results)
    paper_tables._write(output / "query_accounting.tex", _query_accounting(manifests))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scifact-run", type=Path, required=True)
    parser.add_argument("--nfcorpus-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "new_paper/generated")
    args = parser.parse_args()
    generate(args.scifact_run, args.nfcorpus_run, args.output)


if __name__ == "__main__":
    main()
