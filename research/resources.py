"""Resource study: real query-derived scores, 4/8/16 candidates x 3/4/6 bits (plan A.1).

Scores and threshold share the identical global (c+1)/2 mapping, so the
marking predicate never shifts merely because scores were mapped (cosine
0.5 == unit 0.75). Per-subset min-max rescaling is banned. Circuits are
saved as .qasm (+ .qpy when available) with decomposed u/cx counts and
wired into run/evaluate/report.
"""
from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path


def get_backend():
    backend = Path(__file__).resolve().parent.parent / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    from services.circuits import grover_circuit, score_oracle

    return score_oracle, grover_circuit


def cosine_to_unit(scores: list[float]) -> list[float]:
    """Global cosine [-1,1] -> [0,1] mapping. Fixed for all subsets."""
    return [(float(s) + 1.0) / 2.0 for s in scores]


def cosine_threshold_to_unit(threshold_cosine: float) -> float:
    """Map cosine threshold with the identical transform as scores."""
    if not -1.0 <= threshold_cosine <= 1.0:
        raise ValueError("Cosine threshold must be in [-1, 1]")
    return (float(threshold_cosine) + 1.0) / 2.0


def _decomposed_counts(circuit):
    """Count gates in the declared u/cx basis (never raw mcx)."""
    try:
        from qiskit import transpile

        basis = ["u", "cx"]
        decomposed = transpile(circuit, basis_gates=basis, optimization_level=1)
        ops = dict(decomposed.count_ops())
        return {"ops": ops, "depth": int(decomposed.depth()), "basis": basis,
                "one_q": sum(v for k, v in ops.items() if k == "u"),
                "two_q": sum(v for k, v in ops.items() if k == "cx")}
    except Exception:
        ops = dict(circuit.count_ops())
        return {"ops": ops, "depth": int(circuit.depth()), "basis": ["undecomposed"],
                "one_q": 0, "two_q": 0}


def _export_circuit(circuit, out_dir: Path | None, stem: str) -> dict:
    """Save .qasm (+ .qpy when qiskit supports it); always return hash + counts."""
    counts = _decomposed_counts(circuit)
    try:
        from qiskit import qasm2 as _q2

        qasm = _q2.dumps(circuit)
    except Exception:
        try:
            qasm = circuit.qasm()
        except Exception:
            qasm = ""
    record = {"qasm_sha256": hashlib.sha256(qasm.encode()).hexdigest() if qasm else None,
              **counts}
    if out_dir is not None and qasm:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{stem}.qasm").write_text(qasm)
        try:
            from qiskit import qpy as _qpy

            with open(out_dir / f"{stem}.qpy", "wb") as f:
                _qpy.dump(circuit, f)
            record["qpy"] = f"{stem}.qpy"
        except Exception:
            pass
        record["qasm"] = f"{stem}.qasm"
    return record


def run_grid(scores: list[float], threshold_cosine: float = 0.5, out_dir: Path | None = None,
             qid: str = "q", **kwargs):
    """Grid over 4/8/16 candidates x 3/4/6 bits.

    Args:
        scores: raw cosine scores in [-1,1].
        threshold_cosine: cosine-space threshold, mapped with scores.
        out_dir: when given, circuits saved as <qid>_k<k>_b<bits>.qasm.
    """
    if "threshold" in kwargs:
        import warnings

        warnings.warn("threshold= is deprecated; interpreted as cosine threshold", DeprecationWarning)
        threshold_cosine = kwargs.pop("threshold")
    if "unit_mapped" in kwargs:
        raise TypeError("unit_mapped removed: pass raw cosine scores + cosine threshold")
    if kwargs:
        raise TypeError(f"Unexpected kwargs: {sorted(kwargs)}")
    score_oracle, grover_circuit = get_backend()
    threshold_unit = cosine_threshold_to_unit(threshold_cosine)
    unit = cosine_to_unit(scores)
    rows = []
    for k in (4, 8, 16):
        if len(unit) < k:
            rows.append({"candidates": k, "supported": False, "reason": "not enough scores"})
            continue
        subset = unit[:k]
        for bits in (3, 4, 6):
            t0 = time.perf_counter()
            try:
                oracle, meta = score_oracle(subset, bits, threshold_unit, max_qubits=18)
                stem = f"{qid}_k{k}_b{bits}" if out_dir else "n"
                # Keep the score-oracle resource separate from the executed
                # search circuit.  For M=0, M=B, or another zero-iteration
                # case, grover_circuit intentionally omits an unused oracle;
                # exporting the oracle separately prevents that case from
                # being misreported as an oracle with zero gates.
                oracle_export = _export_circuit(oracle, out_dir, f"{stem}_oracle")
                circuit = grover_circuit(k, meta["marked_indices"], oracle=oracle)
                export = _export_circuit(circuit, out_dir, stem)
                if out_dir is None:
                    for record in (oracle_export, export):
                        record.pop("qasm", None)
                        record.pop("qpy", None)
                rows.append({"candidates": k, "score_bits": bits, "supported": True,
                             "total_qubits": meta["total_qubits"],
                             "address_qubits": meta["address_qubits"],
                             "work_qubits": meta["work_qubits"],
                             "marked_indices": meta["marked_indices"],
                             "quantization_changed_marks": meta["quantization_changed_marks"],
                             "oracle_depth": oracle_export["depth"],
                             "oracle_ops": oracle_export["ops"],
                             "oracle_basis": oracle_export["basis"],
                             "oracle_one_q": oracle_export["one_q"],
                             "oracle_two_q": oracle_export["two_q"],
                             "oracle_qasm_sha256": oracle_export["qasm_sha256"],
                             "circuit_depth": export["depth"],
                             "circuit_ops": export["ops"],
                             "circuit_basis": export["basis"],
                             "circuit_one_q": export["one_q"],
                             "circuit_two_q": export["two_q"],
                             "qasm_sha256": export["qasm_sha256"],
                             **({"oracle_qasm": oracle_export["qasm"]}
                                if "qasm" in oracle_export else {}),
                             **({"oracle_qpy": oracle_export["qpy"]}
                                if "qpy" in oracle_export else {}),
                             **({"qasm": export["qasm"]} if "qasm" in export else {}),
                             **({"qpy": export["qpy"]} if "qpy" in export else {}),
                             "unit_mapping": "cosine (c+1)/2 global",
                             "threshold_cosine": threshold_cosine,
                             "threshold_unit": threshold_unit,
                             "build_ms": (time.perf_counter() - t0) * 1000})
            except Exception as exc:
                rows.append({"candidates": k, "score_bits": bits, "supported": False,
                             "reason": f"{type(exc).__name__}: {exc}"})
    return rows


def run_grid_for_query(raw_scores: dict[str, float], threshold_cosine: float = 0.5,
                       out_dir: Path | None = None, qid: str = "q", **kwargs):
    """Query-derived resource rows: top-16 by raw cosine, then grid."""
    if "threshold" in kwargs:
        import warnings

        warnings.warn("threshold= is deprecated; interpreted as cosine threshold", DeprecationWarning)
        threshold_cosine = kwargs.pop("threshold")
    if kwargs:
        raise TypeError(f"Unexpected kwargs: {sorted(kwargs)}")
    ordered = sorted(raw_scores, key=lambda d: (-raw_scores[d], d))[:16]
    scores = [float(raw_scores[d]) for d in ordered]
    rows = run_grid(scores, threshold_cosine=threshold_cosine, out_dir=out_dir, qid=qid)
    return rows, {"doc_order": ordered, "threshold_cosine": threshold_cosine,
                  "threshold_unit": cosine_threshold_to_unit(threshold_cosine),
                  "mapping": "global (c+1)/2", "n_source": len(raw_scores)}


def resource_table(rows_by_qid: dict) -> str:
    """Generate resource table from resources.json (used by report)."""
    lines = ["## Resource grid (generated from resources.json)",
             "| qid | K | bits | qubits (a/w/tot) | marked | qchange | depth | 1q | 2q | build_ms |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for qid in sorted(rows_by_qid):
        for r in rows_by_qid[qid].get("rows", []):
            if not r.get("supported"):
                lines.append(f"| {qid} | {r.get('candidates')} | {r.get('score_bits')} | — | — | — | — | — | — | — |")
                continue
            lines.append(f"| {qid} | {r['candidates']} | {r['score_bits']} | "
                         f"{r['address_qubits']}/{r['work_qubits']}/{r['total_qubits']} | "
                         f"{len(r['marked_indices'])} | {r['quantization_changed_marks']} | "
                         f"{r['circuit_depth']} | {r['circuit_one_q']} | {r['circuit_two_q']} | "
                         f"{r['build_ms']:.1f} |")
    return "\n".join(lines) + "\n"
