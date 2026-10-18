"""Declared secondary ablations, small circuit resources, and isolated memory.

Primary effectiveness always uses all test queries in the parent runs. The
secondary sample is fixed from query IDs before their results are examined.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path
import resource
import subprocess
import sys
import time

import numpy as np

from .selection import CandidateFeatures, GASConfig, prepare_problem, select_classical, select_evidence
from .selection_experiment import (SCHEMA, SEEDS, _sha, _write_json, evaluate_records, hardware_record,
                                   run_query, seal_run, snapshot_sources, verify_run)


def take_features(features: CandidateFeatures, count: int) -> CandidateFeatures:
    return CandidateFeatures(features.ids[:count], features.cosine_scores[:count], features.embeddings[:count],
                             features.passages[:count], features.representative_ids[:count])


def load_sample(run: Path, ids: list[str]) -> dict[str, CandidateFeatures]:
    chosen = set(ids)
    result = {}
    with (run / "full_features.jsonl").open() as handle:
        for line in handle:
            row = json.loads(line)
            if row["qid"] in chosen:
                if row["qid"] in result:
                    raise ValueError("Duplicate full-feature query")
                result[row["qid"]] = CandidateFeatures.from_dict(row["features"])
    if set(result) != chosen:
        raise ValueError("Secondary feature coverage mismatch")
    return result


def memory_worker(args) -> None:
    """Fresh process per method; excludes shared corpus and upstream encoder."""
    from .datasets import DATA_ROOT, _load_queries
    from .selection_features import NeuralReranker

    run = Path(args.run)
    manifest = verify_run(run)
    sample = load_sample(run, manifest["secondary_sample_ids"])
    queries = _load_queries(DATA_ROOT / manifest["canonical_dataset"], "test")
    config = GASConfig(**manifest["config"])
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    model = None
    if args.method.startswith("neural_"):
        import torch
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        label = args.method.split("_")[1]
        pin = manifest["neural_models"][label]
        model = NeuralReranker.load(pin["id"], pin["revision"])
    for qid in sorted(sample):
        features = sample[qid]
        if not args.method.endswith("top64"):
            features = take_features(features, config.candidate_limit)
        if model is not None:
            model.rank(queries[qid], features, config.selected_count)
        elif args.method == "gas":
            select_evidence(features, config, seed=0)
        else:
            kwargs = {"mmr_weight": manifest["mmr_tuning"]["selected_weight"]} if args.method == "mmr" else {}
            select_classical(features, args.method, config, **kwargs)
    after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    print(json.dumps({"method": args.method, "queries": len(sample), "initial_peak_rss_bytes": before,
                      "process_peak_rss_bytes": after, "additional_high_water_bytes": max(0, after - before),
                      "boundary": "Fresh feature-level process; includes imported libraries and neural weights. "
                                  "Excludes shared corpus/index/encoder. Seed 0 for stochastic selectors."}))


def small_circuit_resources(features: CandidateFeatures, config: GASConfig) -> list[dict]:
    from qiskit import transpile
    from .selection_circuits import reference_circuit

    rows = []
    for n in (4, 6, 8):
        for bits in (2, 4, 6):
            cfg = replace(config, candidate_limit=n, selected_count=min(4, n), coefficient_bits=bits)
            problem = prepare_problem(take_features(features, n), cfg)
            threshold = problem.energy(problem.cosine_order()[:problem.count])
            start = time.perf_counter()
            circuit = reference_circuit(problem, threshold, 1, max_qubits=24)
            build_ms = (time.perf_counter() - start) * 1000
            start = time.perf_counter()
            compiled = transpile(circuit, basis_gates=["u", "cx"], optimization_level=1, seed_transpiler=0)
            rows.append({"candidates": n, "selected": cfg.selected_count, "coefficient_bits": bits,
                         "iterations": 1, "qubits": circuit.num_qubits, "depth": compiled.depth(),
                         "gates": {str(k): int(v) for k, v in compiled.count_ops().items()},
                         "build_ms": build_ms, "transpile_ms": (time.perf_counter() - start) * 1000,
                         "implementation": "Generic StatePreparation reference; not efficient Dicke preparation. "
                                           "Synthesis only; no QPU or full-state execution timing."})
    return rows


def studies(args) -> Path:
    from . import artifacts, datasets

    output = artifacts.new_run_dir("gas_secondary_studies")
    sources = snapshot_sources(output)
    summary, references = {}, []
    for run_arg in args.runs:
        run = Path(run_arg).resolve()
        manifest = verify_run(run)
        references.append({"run": str(run), "manifest_sha256": _sha(run / "manifest.json")})
        name = manifest["canonical_dataset"]
        ids = manifest["secondary_sample_ids"]
        sample = load_sample(run, ids)
        _, _, qrels_all = datasets.load_beir(name, "test")
        qrels = {q: qrels_all[q] for q in ids}
        config = GASConfig(**manifest["config"])
        configs = {f"pool_{n}": replace(config, candidate_limit=n) for n in (10, 12, 15, 20)}
        configs.update({f"bits_{b}": replace(config, coefficient_bits=b) for b in (2, 4)})
        configs["no_diversity"] = replace(config, diversity_weight=0)
        rows = {}
        for label, cfg in configs.items():
            records = []
            with (output / f"{name}_{label}_traces.jsonl").open("w") as handle:
                for qid in ids:
                    features = take_features(sample[qid], cfg.candidate_limit)
                    methods = run_query(features, cfg, mmr_weight=manifest["mmr_tuning"]["selected_weight"])
                    row = {"qid": qid, "candidate_ids": list(features.ids),
                           "shortlist_ids": list(features.ids), "methods": methods}
                    records.append(row)
                    handle.write(json.dumps(row, allow_nan=False) + "\n")
            meta = {"test_ids": ids, "methods": sorted(records[0]["methods"]),
                    "seeds": list(SEEDS), "config": asdict(cfg)}
            scored = evaluate_records(meta, records, qrels)
            scored["config"] = asdict(cfg)
            scored["logical_resources_first_sample"] = prepare_problem(
                take_features(sample[ids[0]], cfg.candidate_limit), cfg).resources()
            rows[label] = scored
            print(f"Secondary {name}/{label}: {len(ids)} queries completed", flush=True)
        memory = {}
        if not args.skip_memory:
            methods = ["gas", "cosine", "mmr", "greedy", "exact_quantized", "exact_float"]
            methods += [f"neural_{label}_{pool}" for label in ("l2", "l6") for pool in ("matched", "top64")]
            for method in methods:
                completed = subprocess.run([sys.executable, "-m", "research.selection_studies", "memory-worker",
                                             "--run", str(run), "--method", method], check=True,
                                           capture_output=True, text=True, timeout=600)
                memory[method] = json.loads(completed.stdout.strip().splitlines()[-1])
                print(f"Memory {name}/{method}: {memory[method]['process_peak_rss_bytes']} bytes", flush=True)
        summary[name] = {"sample_ids": ids, "role": "Declared secondary 64-query sample, not full effectiveness",
                         "ablations": rows, "memory": memory,
                         "small_circuit_resources": small_circuit_resources(sample[ids[0]], config)}
    _write_json(output / "studies.json", summary)
    seal_run(output, {"schema": SCHEMA, "profile": "gas_studies", "source_hashes": sources,
                      "parent_runs": references, "hardware": hardware_record(),
                      "sampling": "64 IDs per dataset; gas-secondary-studies-v1, frozen in parent manifests"})
    print(f"Sealed secondary studies: {output}", flush=True)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    study = sub.add_parser("run")
    study.add_argument("--runs", nargs="+", required=True)
    study.add_argument("--skip-memory", action="store_true")
    worker = sub.add_parser("memory-worker")
    worker.add_argument("--run", required=True)
    worker.add_argument("--method", required=True)
    args = parser.parse_args()
    memory_worker(args) if args.command == "memory-worker" else studies(args)


if __name__ == "__main__":
    main()
