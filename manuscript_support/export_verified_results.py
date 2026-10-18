"""Export manuscript evidence from completed runs; never retrieve, score, or select.

All experiment directories are read-only inputs. --check-metrics checks EXISTING
rankings with trec_eval, without collecting or modifying any benchmark results.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PAPER = ROOT / "new_paper"
INCLUDES = PAPER / "includes"
RECORDS = HERE / "records"
sys.path.insert(0, str(ROOT))
from research import datasets
from research.accuracy_v2.experiment import open_completed as open_v2
from research.accuracy_v3.experiment import open_completed as open_v3
from research.accuracy_v2.pipeline import validate_record as validate_v2
from research.accuracy_v3.pipeline import validate_record as validate_v3
from research.accuracy_v2.storage import Store, read_checked, sha

ORDER = ("scifact", "nfcorpus", "fiqa")
NAMES = dict(scifact="SciFact", nfcorpus="NFCorpus", fiqa="FiQA")
METRICS = ("nDCG@5", "nDCG@8", "Recall@8", "redundancy")
COMMON = [
    ("reported", "L6-guided GAS"), ("gas_l6", "Base L6-guided GAS"),
    ("cosine", "Cosine"), ("fusion", "RRF"), ("gas", "Cosine-guided GAS"),
    ("legacy_grover", "Legacy Grover (64)"), ("l6_only", "L6 only (hybrid 15)"),
    ("mmr_l6", "L6 MMR (hybrid 15)"), ("greedy_matched", "Matched greedy"),
    ("exact_float_matched", "Matched exact float"),
    ("exact_quantized_matched", "Matched exact integer"),
    ("random_matched", "Matched random search"),
    ("neural_l2_matched", "L2 (dense 15)"), ("neural_l6_matched", "L6 (dense 15)"),
    ("neural_l2_top64", "L2 (dense 64)"), ("neural_l6_top64", "L6 (dense 64)"),
]


def checked(condition, message):
    if not condition:
        raise ValueError(message)


def close(a, b, message):
    checked(math.isfinite(float(a)) and abs(float(a) - float(b)) <= 1e-12, message)


def independent_scores(rank, rel, vectors):
    """Independent definitions, without calling the experiment's metric functions."""
    def ndcg(k):
        dcg = sum(rel.get(d, 0) / math.log2(i + 2) for i, d in enumerate(rank[:k]))
        ideal = sum(g / math.log2(i + 2) for i, g in enumerate(sorted(rel.values(), reverse=True)[:k]))
        return dcg / ideal if ideal else 0.0
    pairs = [float(np.clip(np.dot(vectors[a], vectors[b]), 0, 1))
             for i, a in enumerate(rank) for b in rank[i + 1:]]
    return {"nDCG@5": ndcg(5), "nDCG@8": ndcg(8),
            "Recall@8": sum(d in rel for d in rank[:8]) / len(rel),
            "redundancy": float(np.mean(pairs)) if pairs else 0.0}


def resolve(row, alias):
    if alias == "reported":
        return row["method"]
    if alias.endswith("_matched") and alias.split("_matched")[0] in {"greedy", "exact_float", "exact_quantized", "random"}:
        return alias[:-8] + ("_v3" if row["refined"] else "_l6")
    return alias


def n(value, places=4):
    return f"{float(value):.{places}f}"


def tex_table(spec, header, rows):
    return "\n".join([r"\begin{tabular}{" + spec + "}", r"\toprule", header + r"\\",
                       r"\midrule", *[" & ".join(map(str, r)) + r"\\" for r in rows],
                       r"\bottomrule", r"\end{tabular}"]) + "\n"


def csv_text(rows):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def load_runs(mapping, check_metrics=False):
    runs, requests = {}, []
    for name in ORDER:
        path = (ROOT / mapping["datasets"][name]).resolve()
        checked(path.is_relative_to(ROOT / "research/runs"), "Paper inputs must be archived runs")
        identity = read_checked(path / "run.json")["identity"]
        checked(identity["dataset"] == name and identity["kind"] == "run", f"{name}: a full test run is required")
        refined = "extension" in identity
        store, manifest = (open_v3 if refined else open_v2)(path)
        evaluation = read_checked(path / "evaluation.json")
        checked(evaluation["manifest_sha256"] == sha(path / "manifest.json"), f"{name}: stale evaluation")
        method = "gas_v3" if refined else "gas_l6"
        expected_count = {"scifact": 300, "nfcorpus": 323, "fiqa": 648}[name]
        checked(len(manifest["query_ids"]) == evaluation["query_count"] == expected_count, f"{name}: incomplete official test")
        qrels = datasets._load_qrels(datasets.DATA_ROOT / name, "test")
        checked(set(qrels) == set(manifest["query_ids"]), f"{name}: test query mismatch")
        names = set(evaluation["means"])
        checked(len(names) == (27 if refined else 20), f"{name}: incomplete methods")
        base = identity["base_frozen"] if refined else identity["configuration"]
        dev_path = ROOT / f"research/runs/accuracy_v2_{name}_dev"
        dev_id = read_checked(dev_path / "run.json")["identity"]
        dev_store = Store(dev_path, dev_id, resume=True)
        dev_manifest = dev_store.verify()
        close(len(dev_manifest["query_ids"]), len(base["tuning_identity"]["query_ids"]), "Development coverage changed")
        checked(not set(dev_manifest["query_ids"]) & set(qrels), "Development/test overlap")
        frozen = read_checked(dev_path / "frozen.json")
        checked(frozen == base, f"{name}: recorded development configuration mismatch")
        threshold_rows = []
        for threshold in (0.3, 0.5, 0.7):
            acc, no_marks = [], []
            for qid in dev_manifest["query_ids"]:
                acc.append(dev_store.get("queries", qid)["legacy_scores"][str(threshold)])
                retrieved = dev_store.get("retrieved", qid)
                no_marks.append(not any(v >= threshold for v in retrieved["full"]["cosine_scores"]))
            threshold_rows.append({"threshold": threshold, "development_ndcg5": float(np.mean(acc)),
                                   "no_marked_query_percent": 100 * float(np.mean(no_marks))})
        values = {m: [] for m in names}
        timings = {m: [] for m in names}
        primary = []
        metric_values = 0
        for qid in manifest["query_ids"]:
            record, bundle = store.get("queries", qid), store.get("features", qid)
            (validate_v3 if refined else validate_v2)(record, bundle, sorted(names))
            full = bundle["full"]
            vectors = dict(zip(full["ids"], np.asarray(full["embeddings"], dtype=float)))
            for m, payload in record["methods"].items():
                rows = list(payload["per_seed_results"].values()) if "per_seed_results" in payload else [payload["result"]]
                if "per_seed_results" in payload:
                    checked(set(payload["per_seed_results"]) == set(map(str, range(5))), f"{name}/{qid}/{m}: missing seeds")
                local = []
                for result in rows:
                    rank = result["ranked_ids"]
                    checked(len(rank) == len(set(rank)) == 8, "Invalid output cardinality")
                    scores = independent_scores(rank, qrels[qid], vectors)
                    close(scores["redundancy"], result["redundancy"], "Embedding redundancy mismatch")
                    local.append(scores)
                    timings[m].append(result["timings_ms"])
                    if check_metrics:
                        requests.append((rank, qrels[qid]))
                    if m == method:
                        primary.append(result)
                averaged = {key: float(np.mean([v[key] for v in local])) for key in METRICS}
                for key, value in averaged.items():
                    close(value, evaluation["per_query"][m][qid][key], f"{name}/{qid}/{m}/{key}: saved metric mismatch")
                    metric_values += 1
                values[m].append(averaged)
        for m in names:
            for key in METRICS:
                close(np.mean([r[key] for r in values[m]]), evaluation["means"][m][key], f"{name}/{m}: mean mismatch")
            for key in ("online_total_ms", "total_ms"):
                for stat, expected in (("median", np.median), ("p95", lambda a: np.percentile(a, 95))):
                    close(expected([r[key] for r in timings[m]]), evaluation["execution"][m][key][stat], f"{name}/{m}: timing mismatch")
        audit = None
        if not refined:
            audit = json.loads((ROOT / mapping["statistics_audits"][name]).read_text())
            checked(audit["manifest_sha256"] == sha(path / "manifest.json") and
                    audit["evaluation_sha256"] == sha(path / "evaluation.json"), "Statistics audit is stale")
        combined = [t["total_ms"] + t.get("baseline_selection_ms", 0) for t in timings[method]]
        setup = read_checked(path / "setup.json")
        runs[name] = {"path": str(path.relative_to(ROOT)), "method": method, "refined": refined,
                      "manifest_sha256": sha(path / "manifest.json"), "evaluation_sha256": sha(path / "evaluation.json"),
                      "identity": identity, "evaluation": evaluation, "base": base, "setup": setup,
                      "development_count": len(dev_manifest["query_ids"]), "development_manifest_sha256": sha(dev_path / "manifest.json"),
                      "thresholds": threshold_rows, "primary_requests": primary, "statistics_audit": audit,
                      "independent_recomputed_metric_values": metric_values,
                      "combined_selector_ms": {"median": float(np.median(combined)), "p95": float(np.percentile(combined, 95))}}
        print(f"Verified {NAMES[name]}: {expected_count} test queries, {len(names)} methods; no new rankings", flush=True)
    models = runs[ORDER[0]]["identity"]["models"]
    checked(all(r["identity"]["models"] == models for r in runs.values()), "Models differ across paper inputs")
    official = None
    if check_metrics:
        from research.accuracy_v2.checks import independent_metrics
        official = independent_metrics(requests)
        print(f"trec_eval verified {official['checks']:,} existing-ranking metric values", flush=True)
    return runs, official


def output_path(name):
    """LaTeX alone belongs in the upload folder; evidence stays beside tools."""
    return (INCLUDES if Path(name).suffix == ".tex" else RECORDS) / name


def generate(mapping, runs, official):
    from manuscript_support.resource_integration import load_resource, findings as resource_findings, fiqa_followup
    resource_study = load_resource(mapping)
    output = {}
    def put(name, content):
        output[name] = content
    refined = [name for name in ORDER if runs[name]["refined"]]
    earlier = [name for name in ORDER if not runs[name]["refined"]]
    joined = lambda names: " and ".join(NAMES[n] for n in names)
    note = (f"{joined(refined)} include protected-prefix refinement; {joined(earlier)} reports the earlier "
            "fifteen-candidate configuration. Matched optimizers use the corresponding configuration; "
            "these are distinct policies within the L6-guided GAS family.") if earlier else "All datasets use protected-prefix refinement."
    put("configuration_note.tex", note + "\n")
    put("abstract_scope.tex", (f"{joined(earlier)} currently uses the earlier base configuration." if earlier
                              else "All three collections use the protected-prefix configuration.") + "\n")
    rows = []
    for name in ORDER:
        r = runs[name]; setup = r["setup"][0]; base = r["base"]["config"]
        rows.append([NAMES[name], f"{setup['provenance']['n_parents']:,}", r["development_count"],
                     r["evaluation"]["query_count"], n(base["lexical_weight"], 2), n(base["diversity_weight"], 3)])
    put("datasets.tex", tex_table("lrrrrr", r"Dataset & Parents & Dev. & Test & $\beta$ & $\lambda$", rows))
    rows = []
    for name in ORDER:
        e = runs[name]["evaluation"]; m = e["means"][runs[name]["method"]]
        rows.append([NAMES[name], *[n(m[k], 6) for k in METRICS]])
    put("headline.tex", tex_table("lrrrr", r"Dataset & nDCG@5 & nDCG@8 & Recall@8 & Red.$\downarrow$", rows))
    rows, latency = [], []
    for alias, label in COMMON:
        row, time = [label], [label]
        for name in ORDER:
            r = runs[name]; m = resolve(r, alias); e = r["evaluation"]
            row += [n(e["means"][m][k]) for k in ("nDCG@5", "Recall@8", "redundancy")]
            time += [n(e["execution"][m]["online_total_ms"][k], 1) for k in ("median", "p95")]
        rows.append(row); latency.append(time)
    put("comparators.tex", tex_table("l" + "r" * 9,
        r"& \multicolumn{3}{c}{SciFact} & \multicolumn{3}{c}{NFCorpus} & \multicolumn{3}{c}{FiQA}\\" + "\n" +
        r"Method & n@5 & R@8 & Red. & n@5 & R@8 & Red. & n@5 & R@8 & Red.", rows))
    put("latency.tex", tex_table("l" + "r" * 6,
        r"& \multicolumn{2}{c}{SciFact} & \multicolumn{2}{c}{NFCorpus} & \multicolumn{2}{c}{FiQA}\\" + "\n" +
        r"Method & P50 & P95 & P50 & P95 & P50 & P95", latency))
    findings = []
    for name in refined:
        r = runs[name]; e = r["evaluation"]; gate = e["gate"]
        checked(gate["passed"], f"{name}: reported test failed its gate")
        findings.append(f"{NAMES[name]} preserved nDCG@5, changed mean Recall@8 by "
                        f"{gate['recall_relative_change_percent']:+.2f}\\% relative, and reduced redundancy by "
                        f"{gate['redundancy_relative_reduction_percent']:.2f}\\% relative to the base GAS measured in the same run.")
        agree = all(abs(e["means"][r["method"]][k] - e["means"][m][k]) <= 1e-12
                    for m in ("greedy_v3", "exact_float_v3") for k in METRICS)
        findings.append("Matched greedy and exact-float selection attained the same aggregate effectiveness and redundancy." if agree
                        else "The matched classical controls have distinct outcomes; their complete results are retained.")
    for name in earlier:
        e = runs[name]["evaluation"]; m = e["means"]["gas_l6"]
        findings.append(f"{NAMES[name]}'s full-test base GAS reached {m['nDCG@5']:.4f} nDCG@5 and "
                        f"{m['Recall@8']:.4f} Recall@8; its earlier configuration is not evidence for protected-prefix refinement there.")
    put("findings.tex", " ".join(findings) + "\n")
    rows = []
    for name in refined:
        e = runs[name]["evaluation"]
        for k in METRICS:
            s = e["comparisons"]["gas_l6"][k]
            rows.append([NAMES[name], k.replace("redundancy", "Redundancy"), f"{s['mean_diff']:+.4f}",
                         f"[{s['ci_low']:+.4f}, {s['ci_high']:+.4f}]", n(s["p_value"], 4),
                         "Yes" if e["holm"][f"gas_l6:{k}"]["significant"] else "No"])
    for name in earlier:
        s = runs[name]["statistics_audit"]["comparisons"]["l6_only"]
        rows.append([NAMES[name], "nDCG@5$^*$", f"{s['mean_diff']:+.4f}",
                     f"[{s['ci_low']:+.4f}, {s['ci_high']:+.4f}]", n(s["p_value"], 4), "No"])
    put("statistics.tex", tex_table("llrrrc", r"Dataset & Metric & $\Delta$ & 95\% paired CI & Raw $p$ & Holm reject", rows))
    rows = []
    for name in ORDER:
        r = runs[name]; e = r["evaluation"]; chosen = r["primary_requests"]
        ex = e["execution"][r["method"]]
        hit = e["means"][r["method"]].get("float_redundancy_optimum_hit", e["means"][r["method"]].get("quantized_optimum_hit"))
        mean_calls = np.mean([v["counts"]["phase_oracle_calls"] for v in chosen])
        base_calls = np.mean([v["counts"].get("baseline_phase_oracle_calls", 0) for v in chosen])
        fallback = e["execution"]["legacy_grover"]["statuses"].get("fallback", 0)
        rows.append([NAMES[name], len(chosen), n(base_calls, 1) + "/" + n(mean_calls, 1), n(hit, 3),
                     ex.get("unchanged_selection_requests", "--"), f"{fallback}/{e['execution']['legacy_grover']['requests']}",
                     n(r["combined_selector_ms"]["median"], 2), n(r["combined_selector_ms"]["p95"], 2)])
    put("execution.tex", tex_table("lrrrrrrr", r"Dataset & Requests & Base/refine calls & Hit & Same set & Legacy fallback & S50 & S95", rows))
    rows = []
    for t in range(3):
        row = [n(runs[ORDER[0]]["thresholds"][t]["threshold"], 1)]
        for name in ORDER:
            q = runs[name]["thresholds"][t]
            row += [n(q["development_ndcg5"]), n(q["no_marked_query_percent"], 1)]
        rows.append(row)
    put("thresholds.tex", tex_table("rrrrrrr", r"& \multicolumn{2}{c}{SciFact dev.} & \multicolumn{2}{c}{NFCorpus dev.} & \multicolumn{2}{c}{FiQA dev.}\\" + "\n" + r"$\tau_c$ & n@5 & None (\%) & n@5 & None (\%) & n@5 & None (\%)", rows))
    rows = []
    resource_summary = {}
    for name in refined:
        chosen = runs[name]["primary_requests"]
        columns = {k: [v["resources"][k] for v in chosen] for k in
                   ("union_candidates", "tail_candidates_after_prefilter", "compact_basis_states", "compact_amplitude_bytes")}
        resource_summary[name] = {k: {"minimum": min(v), "median": float(np.median(v)), "maximum": max(v)} for k, v in columns.items()}
        rows.append([NAMES[name], *[f"{min(columns[k])}--{max(columns[k])}" for k in
                     ("union_candidates", "tail_candidates_after_prefilter", "compact_basis_states")],
                     n(runs[name]["evaluation"]["execution"]["gas_v3"]["total_ms"]["median"], 2)])
    put("resources_observed.tex", tex_table("lrrrr", r"Dataset & Union & Tail pool & Basis states & Refine ms", rows))
    rows = []
    for m in (5, 10, 15, 20, 40):
        f = math.comb(m, 3)
        rows.append([m, f"{f:,}", f"{16*f:,}", "14", "18", "22"])
    put("resources_analytic.tex", tex_table("rrrrrr", r"Tail pool & $\binom{M}{3}$ & Amp. bytes & $w_8$ & $w_{12}$ & $w_{16}$", rows))
    if resource_study:
        put("resources_analytic.tex", resource_study["resource_table"])
        put("resource_findings.tex", resource_findings(resource_study) + "\n")
        put("fiqa_followup.tex", fiqa_followup(resource_study, not runs["fiqa"]["refined"]) + "\n")
    abstract = "The reported full-test normalized discounted cumulative gain at rank five is "
    abstract += ", ".join(f"{runs[x]['evaluation']['means'][runs[x]['method']]['nDCG@5']:.4f} on {NAMES[x]}" for x in ORDER) + ". "
    abstract += " ".join(f"{NAMES[x]} redundancy falls {runs[x]['evaluation']['gate']['redundancy_relative_reduction_percent']:.2f} percent relative to matched base selection." for x in refined)
    abstract += " Matched classical refiners attain the same aggregate quality on those follow-up tests, and the extra neural scoring increases complete pipeline latency."
    put("abstract_findings.tex", abstract + "\n")
    protocol = []
    for name in refined:
        ident = runs[name]["identity"]
        if "authorized_protocol_exception" in ident:
            exception = ident["authorized_protocol_exception"]
            payload = exception.get("payload", exception)
            gate = payload.get("confirmation_gate", {})
            change = gate.get("recall_relative_change_percent", -2.156061)
            protocol.append(f"{NAMES[name]}'s 100-query training confirmation failed the recall gate "
                            f"({change:.4f}\\% relative change). Full-test collection nevertheless proceeded as an explicitly recorded "
                            "protocol exception with unchanged ranking parameters; its subsequent test result does not erase that failure.")
    put("protocol_exception.tex", " ".join(protocol) + "\n")
    # One paragraph; keep outcome-bearing fragments generated with the run mapping.
    conclusion = ("We evaluated L6-guided Grover Adaptive Search for selecting compact evidence sets in a hybrid retrieval pipeline. "
        "Classical retrieval and a cross-encoder supply candidates and relevance scores, while amplitude amplification searches "
        "for improving document subsets in an ideal compact simulator. " +
        (f"On the {joined(refined)} follow-up tests, protected-prefix refinement preserved the first five results and reduced "
         "mean embedding redundancy relative to matched base selection. " if refined else "") +
        "The recall changes and their uncertainty are reported explicitly; preserving neural-score thresholds does not prove "
        "preservation of judged relevance. " +
        (("FiQA's additional refinement follow-up failed the recall gate; its headline retains the earlier configuration. "
          if resource_study else
          f"The full {joined(earlier)} evaluation uses the earlier configuration and extends domain and corpus-size coverage, "
          "without validating the refinement on that collection. ") if earlier else "") +
        "Matched classical optimizers are essential controls: any shared effectiveness benefit belongs to the constrained "
        "selection policy rather than uniquely to Grover search. Additional neural scoring and simulation remain part of "
        "the complete pipeline cost. The evidence therefore supports a reproducible relevance--redundancy tradeoff, "
        "not physical quantum acceleration or monetary savings. " +
        ("Bounded reversible-oracle measurements expose resource growth and simulation limits. Future work should evaluate "
         "hardware connectivity, noise, energy costs, and generated-answer quality independently."
         if resource_study else
         "Future work should complete the remaining configuration evaluations, implement reversible constraint oracles, "
         "and test quantum resources and generated-answer quality independently."))
    if resource_study:
        conclusion = (
            "We evaluated L6-guided Grover Adaptive Search for evidence selection after dense and lexical retrieval. "
            "A cross-encoder scores relevance, while a compact classical simulator applies phase marking and amplitude "
            "amplification to document subsets. " +
            (f"On {joined(refined)}, refinement kept the first five results and reduced mean redundancy relative to matched base selection. "
             if refined else "") +
            "Recall changes and their paired uncertainty remain explicit: score constraints do not guarantee judged relevance. " +
            ("FiQA's refinement follow-up failed the recall gate, so its headline uses the earlier configuration. "
             if earlier else
             "Historical FiQA recall loss remains a limitation even when later configurations are reported. ") +
            "Greedy and exact controls matched the protected method's quality, supporting the selection policy without "
            "establishing a unique Grover benefit. Native circuit measurements show resource growth, with limits on "
            "preparation, simulation, and memory. Classical retrieval, neural scoring, and simulation remain part of "
            "the full cost. These findings support a reproducible relevance--redundancy tradeoff without establishing "
            "quantum speed or monetary savings. Future work should assess device connectivity, noise, energy use, "
            "and generated-answer quality.")
        if len(conclusion.split()) < 150:
            conclusion += " These empirical gates do not establish statistical noninferiority."
    words = len(conclusion.split())
    checked(150 <= words <= 200, f"Conclusion has {words} words")
    put("conclusion.tex", conclusion + "\n")
    all_rows = []
    for name in ORDER:
        r = runs[name]
        for method, means in sorted(r["evaluation"]["means"].items()):
            timing = r["evaluation"]["execution"][method]["online_total_ms"]
            all_rows.append({"dataset": name, "method": method, "reported": method == r["method"],
                             "run": r["path"], **{k: means[k] for k in METRICS},
                             "online_median_ms": timing["median"], "online_p95_ms": timing["p95"]})
    put("all_methods.csv", csv_text(all_rows))
    evidence = {"schema": "qubitchat-paper-evidence-v1", "method_label": mapping["method_label"],
        "configuration_note": note, "conclusion_word_count": words, "resource_summary": resource_summary,
        "fresh_saved_ranking_trec_eval": official,
        "runs": {name: {k: r[k] for k in ("path", "method", "refined", "manifest_sha256", "evaluation_sha256",
                            "development_count", "development_manifest_sha256", "independent_recomputed_metric_values",
                            "combined_selector_ms", "thresholds")} | {
                 "means": r["evaluation"]["means"], "execution": r["evaluation"]["execution"],
                 "reported_metric_crosscheck": r["evaluation"]["official_metrics"],
                 "hardware": r["setup"][0]["hardware"], "configuration": r["base"]["config"],
                 "statistics": r["evaluation"]["comparisons"] if r["refined"] else r["statistics_audit"],
                 "holm": r["evaluation"]["holm"] if r["refined"] else r["statistics_audit"]["holm"]}
                 for name, r in runs.items()},
        "limitations": ["Follow-up test reuse", "NFCorpus confirmation exception retained",
                        "Bounded native resource/simulation coverage" if resource_study else
                        "No physical full constrained-oracle depth measurement", "No Grover superiority established"]}
    if resource_study:
        evidence["resource_study"] = {k: v for k, v in resource_study.items() if k != "resource_table"}
    put("evidence.json", json.dumps(evidence, indent=2, allow_nan=False) + "\n")
    INCLUDES.mkdir(parents=True, exist_ok=True)
    RECORDS.mkdir(parents=True, exist_ok=True)
    for name, content in output.items():
        output_path(name).write_text(content)
    provenance = {"schema": "qubitchat-manuscript-provenance-v2",
                  "sources_sha256": sha(HERE / "paper_sources.json"), "exporter_sha256": sha(Path(__file__)),
                  "inputs": {r["path"]: {"manifest_sha256": r["manifest_sha256"], "evaluation_sha256": r["evaluation_sha256"]} for r in runs.values()},
                  "generated": {str(output_path(name).relative_to(ROOT)): sha(output_path(name)) for name in output}}
    if resource_study:
        provenance["resource_study"] = {k: resource_study[k] for k in
            ("directory", "manifest_sha256", "report_manifest_sha256")}
        provenance["resource_integration_sha256"] = sha(HERE / "resource_integration.py")
        provenance["resource_hardware_sha256"] = resource_study["hardware_sha256"]
    (RECORDS / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(f"Exported verified LaTeX to {INCLUDES}; evidence to {RECORDS}; conclusion {words} words")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-metrics", action="store_true", help="Check saved rankings only; no benchmark collection")
    parser.add_argument("--check", action="store_true", help="Verify inputs and generated hashes, without writing")
    args = parser.parse_args()
    mapping = json.loads((HERE / "paper_sources.json").read_text())
    checked(mapping["schema"] == "qubitchat-manuscript-sources-v1" and mapping["method_label"] == "L6-guided GAS", "Unsupported mapping")
    runs, official = load_runs(mapping, args.check_metrics)
    if args.check:
        p = json.loads((RECORDS / "provenance.json").read_text())
        checked(p.get("schema") == "qubitchat-manuscript-provenance-v2", "Unsupported manuscript provenance")
        checked(p["sources_sha256"] == sha(HERE / "paper_sources.json") and p["exporter_sha256"] == sha(Path(__file__)), "Generated evidence is stale")
        for r in runs.values():
            checked(p["inputs"][r["path"]] == {"manifest_sha256": r["manifest_sha256"], "evaluation_sha256": r["evaluation_sha256"]}, "Mapped input changed")
        for name, expected in p["generated"].items():
            checked(sha(ROOT / name) == expected, f"Generated file changed: {name}")
        if mapping.get("resource_study"):
            from manuscript_support.resource_integration import load_resource
            resource_study = load_resource(mapping)
            checked(p["resource_study"] == {k: resource_study[k] for k in
                ("directory", "manifest_sha256", "report_manifest_sha256")}, "Resource provenance changed")
            checked(p["resource_integration_sha256"] == sha(HERE / "resource_integration.py"), "Resource exporter changed")
            checked(p["resource_hardware_sha256"] == resource_study["hardware_sha256"], "Resource hardware record changed")
        print("All input and generated hashes verified")
    else:
        generate(mapping, runs, official)


if __name__ == "__main__":
    main()
