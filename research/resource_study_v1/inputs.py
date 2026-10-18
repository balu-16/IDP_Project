"""Freeze training-confirmation samples and matched candidate/precision cells."""
from pathlib import Path

from research.accuracy_v2.core import ScoredFeatures
from research.accuracy_v3.experiment import open_completed
from . import VERSION
from .problem import POOLS, BITS, SEEDS, stable, eligible, synthetic
from .storage import (ROOT, atomic_bytes, environment_identity, once, prerequisites,
                      protocol, read_checked, sha, sources, utc)


def freeze(directory):
    directory = Path(directory)
    previous = None
    if (directory / "protocol.json").exists():
        previous = read_checked(directory / "protocol.json")
        if previous["sources"] != sources() or previous["environment"] != environment_identity():
            raise ValueError("Cannot resume input freeze with changed sources/dependencies")
        if (directory / "frozen_inputs.json").exists():
            protocol(directory)
            index = read_checked(directory / "frozen_inputs.json")
            if index["tasks_sha256"] != sha(directory / "tasks.json"):
                raise ValueError("Frozen task index changed")
            return read_checked(directory / "tasks.json")
    if previous is None and directory.exists() and any(directory.iterdir()):
        raise ValueError("Refusing a nonempty resource directory without its protocol")
    conditions = prerequisites()
    check_path = ROOT / "build/resource_study/checks.json"
    checks = read_checked(check_path)
    if not checks["passed"] or checks["sources"] != sources():
        raise ValueError("Pass current resource oracle/recovery checks before freezing")
    parents, samples, stores = {}, {}, {}
    for dataset in ("scifact", "nfcorpus", "fiqa"):
        parent = ROOT / f"research/runs/accuracy_v3_redundancy_{dataset}_confirmation"
        store, manifest = open_completed(parent)
        if store.identity["kind"] != "confirm" or len(manifest["query_ids"]) != 100:
            raise ValueError("Resource sampling requires sealed 100-query confirmation runs")
        parents[dataset] = {"directory": str(parent.relative_to(ROOT)),
            "hashes": {name: sha(parent / name) for name in ("manifest.json", "run.json", "evaluation.json")}}
        samples[dataset] = sorted(manifest["query_ids"], key=lambda q: (stable(f"resource-study-v1:{dataset}:{q}"), q))[:32]
        stores[dataset] = store
    directory.mkdir(parents=True, exist_ok=True)
    frozen = previous or {"version": VERSION, "created_utc": utc(), "sources": sources(),
        "environment": environment_identity(), "parents": parents, "samples": samples,
        "sampling_namespace": "resource-study-v1", "pools": list(POOLS), "bits": list(BITS),
        "seeds": list(SEEDS), "prefix": 5, "tail_selected": 3, "phase_budget": 64,
        "trial_budget": 32, "native_seed": 0, "native_queries_per_cell": 2,
        "circuit_timeout_seconds": 120, "circuit_address_space_limit_bytes": 2 << 30,
        "native_maximum_bond_dimension": 128, "native_validation_tolerance": 1e-8,
        "engineering_pilot_directory": "research/runs/resource_study_v1",
        "verification_sha256": sha(check_path),
        "coefficient_choices_are_tuning": False, "prerequisites": conditions}
    # Identity and sampled IDs exist before feature processing or circuit work.
    once(directory / "protocol.json", frozen)
    verification = directory / "verification.json"
    if verification.exists():
        if sha(verification) != frozen["verification_sha256"]:
            raise ValueError("Resource verification snapshot changed")
    else:
        if sha(check_path) != frozen["verification_sha256"]:
            raise ValueError("Cannot recover verification snapshot from a different check")
        atomic_bytes(verification, check_path.read_bytes())
    if frozen["parents"] != parents or frozen["samples"] != samples:
        raise ValueError("Frozen parents/sample IDs changed during input recovery")
    for relative, expected in frozen["sources"].items():
        path = directory / "source_snapshot" / relative
        if path.exists():
            if sha(path) != expected:
                raise ValueError("Corrupt resource source snapshot")
        else:
            atomic_bytes(path, (ROOT / relative).read_bytes())
    tasks, inventory, availability = [], {}, {}
    native_candidates = {m: [] for m in POOLS}
    for dataset, ids in samples.items():
        availability[dataset] = {str(m): {str(seed): 0 for seed in SEEDS} for m in POOLS}
        for qid in ids:
            store = stores[dataset]
            bundle = store.get("features", qid)
            record = store.get("queries", qid)
            scored = ScoredFeatures.from_dict(bundle["union"])
            bases = {str(seed): record["methods"]["gas_l6"]["per_seed_results"][str(seed)]["ranked_ids"]
                     for seed in SEEDS}
            payload = {"dataset": dataset, "qid": qid, "role": "saved training-confirmation feature",
                       "features": scored.to_dict(), "baselines": bases}
            path = directory / "inputs" / f"{dataset}_{stable(qid)}.json"
            once(path, payload)
            item = {"dataset": dataset, "qid": qid, "input": str(path.relative_to(directory)),
                    "input_sha256": sha(path)}
            inventory[f"{dataset}:{qid}"] = item
            tasks.append({**item, "kind": "compact"})
            for m in POOLS:
                for seed in SEEDS:
                    if len(eligible(scored, bases[str(seed)])) >= m:
                        availability[dataset][str(m)][str(seed)] += 1
                if len(eligible(scored, bases["0"])) >= m:
                    native_candidates[m].append(item)
    # Freeze the first two eligible sampled queries PER DATASET and candidate
    # count. Identical IDs are used for all four coefficient precisions.
    for m, candidates in native_candidates.items():
        for dataset in samples:
            chosen = [item for item in candidates if item["dataset"] == dataset][:2]
            for item in chosen:
                for bits in BITS:
                    tasks.append({**item, "kind": "native", "pool": m, "bits": bits})
    for m in POOLS:
        if any(availability[d][str(m)]["0"] for d in samples):
            continue
        scored, base = synthetic(m)
        path = directory / "inputs" / f"synthetic_{m}.json"
        once(path, {"dataset": "synthetic", "qid": f"stress-{m}",
            "role": "artificial stress case; not dataset or effectiveness evidence",
            "features": scored.to_dict(), "baselines": {str(seed): base for seed in SEEDS}})
        item = {"dataset": "synthetic", "qid": f"stress-{m}", "input": str(path.relative_to(directory)),
                "input_sha256": sha(path)}
        inventory[f"synthetic:{m}"] = item
        tasks.append({**item, "kind": "compact"})
        for bits in BITS:
            tasks.append({**item, "kind": "native", "pool": m, "bits": bits})
    # Every native cell can be identified before any measured outcomes exist.
    task_file = {"tasks": tasks, "inventory": inventory, "availability": availability}
    once(directory / "tasks.json", task_file)
    once(directory / "frozen_inputs.json", {"protocol_sha256": sha(directory / "protocol.json"),
        "tasks_sha256": sha(directory / "tasks.json"),
        "inputs": {item["input"]: item["input_sha256"] for item in inventory.values()}})
    return task_file
