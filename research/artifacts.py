"""Immutable artifacts: manifests, TREC, per-query JSONL, tables (plan A.5)."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

RUNS_ROOT = Path(__file__).resolve().parent / "runs"


def git_state() -> dict:
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        dirty = subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
        try:
            diff = subprocess.check_output(["git", "diff", "--", "research", "backend"], text=True)
            content_hash = hashlib.sha256(diff.encode()).hexdigest() if diff.strip() else None
        except Exception:
            content_hash = None
        return {"commit": commit, "dirty": bool(dirty),
                "dirty_files": dirty.splitlines()[:20],
                "dirty_content_sha256": content_hash}
    except Exception as exc:
        return {"commit": None, "dirty": None, "error": str(exc)}


def dependency_record() -> dict:
    """Key dependency versions + hardware for independent reproduction."""
    record: dict = {"python": sys.version, "platform": platform.platform(),
                    "cpu_count": os.cpu_count(), "packages": {}}
    for pkg in ("numpy", "scipy", "sklearn", "hnswlib", "qiskit", "qiskit_aer",
                "sentence_transformers", "torch"):
        try:
            mod = __import__(pkg)
            record["packages"][pkg] = getattr(mod, "__version__", "installed")
        except Exception:
            record["packages"][pkg] = None
    return record


def new_run_dir(tag: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = RUNS_ROOT / f"{stamp}_{tag}"
    (path / "rankings").mkdir(parents=True, exist_ok=False)
    return path


def source_hashes() -> dict[str, str]:
    """Hash actual source files (tracked or not) for the manifest.

    git diff misses untracked files (all of research/ is untracked), so hash
    file bytes directly. Missing files recorded as None (fail at verify only
    if the run claimed them).
    """
    root = Path(__file__).resolve().parent
    backend = root.parent / "backend"
    files = [root / f for f in ("run.py", "datasets.py", "baselines.py", "metrics.py",
                                "artifacts.py", "resources.py", "config_frozen.py",
                                "paper_tables.py")]
    files += [backend / "services" / f for f in ("circuits.py", "quantum_search.py")]
    files += [backend / "config.py"]
    out: dict[str, str] = {}
    for p in files:
        try:
            rel = str(p.relative_to(root.parent))
        except Exception:
            rel = str(p)
        out[rel] = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
    return out


def result_hashes(run_dir: Path) -> dict[str, str]:
    """Hash result files written by run (rankings/traces/resources/trec/circuits)."""
    out: dict[str, str] = {}
    for p in sorted(run_dir.rglob("*")):
        if p.is_file() and p.name not in ("manifest.json", "manifest.sha256"):
            try:
                out[str(p.relative_to(run_dir))] = hashlib.sha256(p.read_bytes()).hexdigest()
            except Exception:
                pass
    return out


def seal_results(run_dir: Path) -> dict:
    """Append result hashes to the manifest and re-sign sha (call after writes)."""
    manifest_p = run_dir / "manifest.json"
    manifest = json.loads(manifest_p.read_text())
    manifest["source_hashes"] = source_hashes()
    manifest["result_hashes"] = result_hashes(run_dir)
    blob = json.dumps(manifest, indent=2, sort_keys=True)
    manifest_p.write_text(blob)
    (run_dir / "manifest.sha256").write_text(hashlib.sha256(blob.encode()).hexdigest())
    return manifest


def seal_scores(run_dir: Path) -> dict:
    """Bind evaluated scores.json to verified inputs (call at end of evaluate).

    Re-hashes result files including scores.json and re-signs the manifest so
    report can prove the scores came from the verified inputs.
    """
    return seal_results(run_dir)


def write_manifest(path: Path, payload: dict) -> Path:
    payload = {**payload, "created_utc": datetime.now(timezone.utc).isoformat(),
               "git": git_state(), "dependencies": dependency_record(),
               "source_hashes": source_hashes(), "python": sys.version}
    blob = json.dumps(payload, indent=2, sort_keys=True)
    (path / "manifest.json").write_text(blob)
    (path / "manifest.sha256").write_text(hashlib.sha256(blob.encode()).hexdigest())
    return path / "manifest.json"


def verify_manifest(path: Path) -> dict:
    """Enforce reproducibility before evaluation (issue 10).

    Checks manifest sha, dataset re-hash, source file hashes, and result
    file hashes. Rejects edited runs, changed inputs, and unrelated files.
    Returns manifest on success.
    """
    manifest = json.loads((path / "manifest.json").read_text())
    recorded = (path / "manifest.sha256").read_text().strip()
    actual = hashlib.sha256((path / "manifest.json").read_bytes()).hexdigest()
    if actual != recorded:
        raise ValueError(f"manifest.sha256 mismatch in {path}: refusing to evaluate edited run")
    # Source files must match run-time hashes (catches untracked edits too).
    for rel, digest in manifest.get("source_hashes", {}).items():
        candidate = Path(__file__).resolve().parent.parent / rel
        if digest is None:
            continue
        if not candidate.exists():
            raise ValueError(f"source file missing for reproduction: {rel}")
        if hashlib.sha256(candidate.read_bytes()).hexdigest() != digest:
            raise ValueError(f"source file changed since run: {rel}")
    # Result files must match sealed hashes when present.
    for rel, digest in manifest.get("result_hashes", {}).items():
        candidate = path / rel
        if not candidate.exists():
            raise ValueError(f"result file missing: {rel}")
        if hashlib.sha256(candidate.read_bytes()).hexdigest() != digest:
            raise ValueError(f"result file changed since run: {rel}")
    # Re-hash dataset cache and compare to freeze record.
    from .datasets import DATA_ROOT, sha256_file

    freeze = manifest.get("freeze", {})
    if freeze.get("synthetic"):
        return manifest
    for fname, digest in freeze.get("files", {}).items():
        base = DATA_ROOT / freeze.get("dataset", manifest.get("canonical_dataset", ""))
        candidate = base / fname
        if not candidate.exists():
            raise ValueError(f"dataset file missing for reproduction: {candidate}")
        if sha256_file(candidate) != digest:
            raise ValueError(f"dataset file changed since run: {candidate}")
    return manifest


def validate_coverage(manifest: dict, rankings: dict, traces: dict) -> None:
    """Require complete qid x method x seed coverage (no silent skips).

    Raises ValueError on any missing query ranking, missing trace, or missing
    per-seed ranking for stochastic methods. Ensemble fallback is banned.
    """
    from .config_frozen import FROZEN as _F

    expected_qids = set(manifest.get("test_ids", []))
    expected_methods = set(manifest.get("methods", []))
    for method in expected_methods:
        got = set(rankings.get(method, {}))
        if got != expected_qids:
            raise ValueError(f"incomplete rankings for {method}: "
                             f"missing {sorted(expected_qids - got)[:5]}, "
                             f"extra {sorted(got - expected_qids)[:5]}")
    for qid in expected_qids:
        if qid not in traces:
            raise ValueError(f"missing trace for query {qid}")
        for method in expected_methods:
            if method not in traces[qid]:
                raise ValueError(f"missing trace for {qid}/{method}")
            if method in {"grover", "sampling"}:
                seeds = traces[qid][method].get("per_seed_rankings") or {}
                try:
                    got_seeds = sorted(int(s) for s in seeds)
                except Exception:
                    got_seeds = sorted(seeds)
                if got_seeds != list(_F["seeds"]):
                    raise ValueError(f"incomplete seeds for {qid}/{method}: "
                                     f"expected {_F['seeds']}, got {sorted(seeds)}")


def write_trec(rankings: dict[str, list[str]], method: str, path: Path):
    """TREC run file: qid Q0 doc rank score tag."""
    lines = []
    for qid in sorted(rankings):
        for rank, did in enumerate(rankings[qid][:100], start=1):
            score = 1.0 / rank
            lines.append(f"{qid} Q0 {did} {rank} {score:.6f} {method}")
    (path / f"{method}.trec").write_text("\n".join(lines) + "\n")


def write_per_seed_trec(traces: dict[str, dict], path: Path):
    """Per-seed TREC files matching primary per-seed evaluation.

    One file per method per seed (grover.seed0.trec, sampling.seed0.trec, ...).
    Methods are never merged: pytrec_eval rejects duplicate qid/doc pairs and
    method tags do not separate runs.
    """
    for method in ("grover", "sampling"):
        seeds: set = set()
        for qid in traces:
            seeds.update((traces[qid].get(method, {}).get("per_seed_rankings") or {}).keys())
        for seed in sorted(seeds, key=str):
            lines = []
            for qid in sorted(traces):
                rank_list = (traces[qid].get(method, {}).get("per_seed_rankings") or {}).get(seed, [])
                for rank, did in enumerate(rank_list[:100], start=1):
                    lines.append(f"{qid} Q0 {did} {rank} {1.0 / rank:.6f} {method}.seed{seed}")
            if lines:
                (path / f"{method}.seed{seed}.trec").write_text("\n".join(lines) + "\n")


def write_traces(traces: dict[str, dict], path: Path):
    with open(path / "traces.jsonl", "w") as f:
        for qid in sorted(traces):
            f.write(json.dumps({"qid": qid, **traces[qid]}) + "\n")


def comparison_table(rows: list[dict]) -> str:
    header = "| method | nDCG@10 | Recall@10 | Recall@64 | MRR@10 | P@5 | n |"
    sep = "|---|---|---|---|---|---|---|"
    lines = [header, sep]
    for r in rows:
        m = r["means"]
        lines.append(f"| {r['method']} | {m['nDCG@10']:.3f} | {m['Recall@10']:.3f} | "
                     f"{m['Recall@64']:.3f} | {m['MRR@10']:.3f} | {m['P@5']:.3f} | {r['n_queries']} |")
    return "\n".join(lines) + "\n"
