"""Verified resource summaries; synthetic, compact, and native scopes stay distinct."""
import csv
import io
import json
from pathlib import Path

import numpy as np

from .problem import POOLS, BITS
from .runner import task_index
from .storage import atomic_bytes, once, read_checked, read_result, sha, write_checked


def report(directory):
    directory = Path(directory)
    index = task_index(directory)
    manifest = read_checked(directory / "manifest.json")
    if (manifest["protocol_sha256"] != sha(directory / "protocol.json")
            or manifest["task_index_sha256"] != sha(directory / "tasks.json")
            or manifest["task_count"] != len(index["tasks"])):
        raise ValueError("Resource manifest coverage/identity mismatch")
    actual = {str(p.relative_to(directory)) for p in (directory / "results").glob("*.json")}
    if actual != set(manifest["files"]):
        raise ValueError("Missing or unsealed resource result files")
    for relative, expected in manifest["files"].items():
        if sha(directory / relative) != expected:
            raise ValueError(f"Resource result changed: {relative}")
    native, compact, statuses = [], [], {}
    for task in index["tasks"]:
        value = read_result(directory, task)
        if value is None:
            raise ValueError("Missing resource task result")
        output = value["output"]
        statuses[output["status"]] = statuses.get(output["status"], 0) + 1
        if task["kind"] == "native":
            native.append({"dataset": task["dataset"], "qid": task["qid"],
                           "pool": task["pool"], "bits": task["bits"], **output})
        elif output["status"] == "completed":
            compact.extend({"dataset": task["dataset"], "qid": task["qid"], **row}
                           for row in output["rows"])
    groups = {}
    for m in POOLS:
        groups[str(m)] = {}
        for bits in BITS:
            rows = [r for r in native if r["pool"] == m and r["bits"] == bits]
            measured = [r for r in rows if r["status"] == "completed"]
            item = {"attempted": len(rows), "completed": len(measured),
                    "limited": len(rows)-len(measured), "datasets": sorted({r["dataset"] for r in rows}),
                    "native_simulations_completed": sum("iteration_validation" in r for r in measured),
                    "native_simulations_resource_limited": sum(r.get("native_simulation", {}).get("status") == "memory_limit" for r in measured)}
            if measured:
                item.update(qubits_max=max(r["registers"]["total"] for r in measured),
                    oracle_depth_max=max(r["oracle"]["depth"] for r in measured),
                    oracle_cx_max=max(r["oracle"]["cx_gates"] for r in measured),
                    synthesis_ms_median=float(np.median([r["build_ms"]+r["oracle"]["transpile_ms"] for r in measured])),
                    peak_rss_bytes_max=max(r["process_peak_rss_bytes"] for r in measured))
                simulated = [r["iteration_validation"]["simulation_ms"] for r in measured if "iteration_validation" in r]
                if simulated:
                    item["native_iteration_simulation_ms_median"] = float(np.median(simulated))
            groups[str(m)][str(bits)] = item
    compact_groups = {}
    for dataset in ("scifact", "nfcorpus", "fiqa", "synthetic"):
        compact_groups[dataset] = {}
        for m in POOLS:
            for bits in BITS:
                rows = [r for r in compact if r["dataset"] == dataset and r["pool"] == m
                        and r.get("bits") == bits and r["status"] == "completed"]
                if not rows:
                    continue
                methods = {}
                for method in ("gas_v3", "exact_float_v3", "exact_quantized_v3"):
                    values = [r["methods"][method] for r in rows]
                    timings = [v["timings_ms"]["total_ms"] for v in values]
                    methods[method] = {"requests": len(values), "median_ms": float(np.median(timings)),
                        "p95_ms": float(np.percentile(timings, 95)),
                        "redundancy_mean": float(np.mean([v["redundancy"] for v in values])),
                        "traced_peak_bytes_max": max(v["additional_traced_peak_bytes"] for v in values)}
                compact_groups[dataset][f"{m}:{bits}"] = {"methods": methods,
                    "float_gap_mean": float(np.mean([r["float_gap"] for r in rows])),
                    "quantized_gap_mean": float(np.mean([r["quantized_gap"] for r in rows])),
                    "phase_calls_mean": float(np.mean([r["methods"]["gas_v3"]["counts"]["phase_oracle_calls"] for r in rows])),
                    "termination_counts": {status: sum(r["methods"]["gas_v3"]["status"] == status for r in rows)
                        for status in sorted({r["methods"]["gas_v3"]["status"] for r in rows})}}
    summary = {"protocol_sha256": sha(directory / "protocol.json"), "manifest_sha256": sha(directory / "manifest.json"),
        "task_statuses": statuses, "availability": index["availability"],
        "native": groups, "compact": compact_groups, "real_query_count": 96,
        "limitations": [
            "Thirty-two training-confirmation queries per dataset; not a fresh retrieval-effectiveness evaluation.",
            "Native circuit metrics use at most two fixed seed-0 queries per dataset and pool; synthetic cells are labelled.",
            "Native complete iteration synthesis is limited to eight decisions; validation simulation to five.",
            "MPS inverse-expected-state/local-Z validation uses zero truncation threshold, bond cap 128, and a 1e-8 infidelity bound.",
            "Qiskit 0.46/Aer 0.13.3 are preserved; no package upgrade or physical QPU execution.",
            "Circuit constants come from classical saved coefficients; construction costs are recorded.",
            "Per-method allocation replay is excluded from selector timing; whole-worker RSS includes its entire query grid.",
            "u/cx counts assume unrestricted connectivity; no hardware-routing or quantum-speedup claim."
        ]}
    write_checked(directory / "summary.json", summary)
    header = ["dataset", "qid", "pool", "bits", "status", "qubits", "oracle_depth", "oracle_cx",
              "build_ms", "transpile_ms", "iteration_simulation_ms", "simulation_status", "peak_rss_bytes"]
    csv_text = io.StringIO()
    writer = csv.DictWriter(csv_text, fieldnames=header)
    writer.writeheader()
    for r in native:
        writer.writerow({"dataset": r["dataset"], "qid": r["qid"], "pool": r["pool"], "bits": r["bits"],
            "status": r["status"], "qubits": r.get("registers", {}).get("total"),
            "oracle_depth": r.get("oracle", {}).get("depth"), "oracle_cx": r.get("oracle", {}).get("cx_gates"),
            "build_ms": r.get("build_ms"), "transpile_ms": r.get("oracle", {}).get("transpile_ms"),
            "iteration_simulation_ms": r.get("iteration_validation", {}).get("simulation_ms"),
            "simulation_status": "validated" if "iteration_validation" in r else r.get("native_simulation", {}).get("status", "not_performed"),
            "peak_rss_bytes": r.get("process_peak_rss_bytes")})
    atomic_bytes(directory / "native_resources.csv", csv_text.getvalue().encode())
    lines = ["# Constrained-oracle resource study", "",
        "Saved confirmation features; this study does not retune retrieval parameters.", "",
        "| Tail pool | Source | Native cells completed/attempted | Qubits (4/16 bit) | Oracle depth (4/16 bit) |",
        "|---:|---|---:|---:|---:|"]
    tex = [r"\begin{tabular}{rlrrr}", r"\toprule",
        r"Tail & Source & Qubits & Depth & CX gates\\", r"\midrule"]
    def pair(a, b, key):
        return f"{a.get(key, '--')}/{b.get(key, '--')}"
    for m in POOLS:
        a, b = groups[str(m)]["4"], groups[str(m)]["16"]
        source = "stress" if a["datasets"] == ["synthetic"] else "real"
        completed = sum(groups[str(m)][str(bit)]["completed"] for bit in BITS)
        attempted = sum(groups[str(m)][str(bit)]["attempted"] for bit in BITS)
        lines.append(f"| {m} | {source} | {completed}/{attempted} | {pair(a,b,'qubits_max')} | {pair(a,b,'oracle_depth_max')} |")
        tex.append(f"{m} & {source} & {pair(a,b,'qubits_max')} & {pair(a,b,'oracle_depth_max')} & {pair(a,b,'oracle_cx_max')}" + r"\\")
    tex += [r"\bottomrule", r"\end{tabular}"]
    atomic_bytes(directory / "resource_table.tex", ("\n".join(tex)+"\n").encode())
    lines += ["", "Values separated by / compare 4 and 16 bits. Resource entries are observed maxima.",
              "Full 4/8/12/16-bit results, simulator times, memory, gaps, and exclusions are in summary.json and native_resources.csv.",
              f"Native iterations validated: {sum('iteration_validation' in r for r in native)}; "
              f"native simulation memory-limit outcomes: {sum(r.get('native_simulation',{}).get('status') == 'memory_limit' for r in native)}.",
              "", "## Coverage and limits", "", *["- "+s for s in summary["limitations"]]]
    atomic_bytes(directory / "REPORT.md", ("\n".join(lines)+"\n").encode())
    write_checked(directory / "report_manifest.json", {"study_manifest_sha256": sha(directory / "manifest.json"),
        "files": {name: sha(directory / name) for name in
                  ("summary.json", "REPORT.md", "native_resources.csv", "resource_table.tex")}})
    return summary
