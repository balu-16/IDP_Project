"""Sequential supervisor: stop on integrity, process, or accuracy-gate failure."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

from .checks import require_preflight, require_smoke
from .storage import ROOT, atomic_bytes, environment_identity, exclusive, extension_identity, read_checked, sha, utc

STATE = ROOT / "research/runs/accuracy_v3_execution.json"
LOGS = ROOT / "research/runs/accuracy_v3_logs"
DATASETS = ("scifact", "nfcorpus", "fiqa")
PYTHON = ROOT / "backend/.venv/bin/python"


class AccuracyGateFailure(ValueError):
    """A completed evaluation failed its predeclared scientific criteria."""


def save(state, path=None):
    state["updated_utc"] = utc()
    atomic_bytes(path or STATE, json.dumps(state, indent=2, allow_nan=False).encode() + b"\n")


def require_confirmation_gate(name, directory):
    """Stop before freezing or collecting any test queries after a failed pilot."""
    from .experiment import CONFIRMATION_COUNT
    evaluation = read_checked(Path(directory) / "evaluation.json")
    if sha(Path(directory) / "manifest.json") != evaluation["manifest_sha256"]:
        raise ValueError("Confirmation evaluation does not match its sealed results")
    if evaluation["query_count"] != CONFIRMATION_COUNT:
        raise ValueError(f"Expected exactly {CONFIRMATION_COUNT} confirmation queries for {name}")
    if not evaluation["gate"]["passed"]:
        outcome = evaluation["gate"]
        raise AccuracyGateFailure(
            f"{name}: stopped after {CONFIRMATION_COUNT} confirmation queries; "
            f"nDCG@5 unchanged={outcome.get('ndcg_unchanged')}, "
            f"Recall@8 within 2% relative loss={outcome.get('recall_within_limit')}, "
            f"redundancy decreased={outcome.get('redundancy_decreased')}. "
            "No test collection or next dataset will start.")


def summarize(state):
    prefix = state.get("batch_name", "accuracy_v3")
    results, lines = {}, ["# V3 follow-up dataset evaluations", "", f"Batch status: {state['status']}", ""]
    for name in DATASETS:
        directory = ROOT / f"research/runs/{prefix}_{name}_test"
        path = directory / "evaluation.json"
        if not path.exists():
            continue
        data = read_checked(path)
        if sha(directory / "manifest.json") != data["manifest_sha256"]:
            raise ValueError("Aggregate report evaluation/manifest mismatch")
        results[name] = {"query_count": data["query_count"], "gate": data["gate"], "means": data["means"],
                         "execution": data["execution"], "official_metrics": data["official_metrics"]}
        report = directory / "REPORT.md"
        if report.exists():
            lines += [report.read_text(), ""]
    atomic_bytes(ROOT / f"research/runs/{prefix}_summary.json", json.dumps(
        {"status": state["status"], "datasets": results, "updated_utc": utc()}, indent=2, allow_nan=False).encode() + b"\n")
    atomic_bytes(ROOT / f"research/runs/{prefix}_summary.md", ("\n".join(lines) + "\n").encode())


def main(resume=False, batch_name=None):
    prefix = batch_name or "accuracy_v3"
    if not re.fullmatch(r"accuracy_v3(?:_[a-z0-9]+)*", prefix):
        raise ValueError("Batch name must be accuracy_v3 followed by optional lowercase/digit suffixes")
    state_path = ROOT / f"research/runs/{prefix}_execution.json" if batch_name else STATE
    logs = ROOT / f"research/runs/{prefix}_logs" if batch_name else LOGS
    logs.mkdir(parents=True, exist_ok=True)
    child, interrupted = None, False
    def stop(signum, frame):
        nonlocal interrupted
        interrupted = True
        if child is not None and child.poll() is None:
            child.send_signal(signal.SIGTERM)
    with exclusive(logs / ".batch.lock"):
        require_smoke()
        for name in DATASETS:
            require_preflight(name)
        environment, extension = environment_identity(), extension_identity()
        if state_path.exists():
            if not resume:
                raise ValueError("V3 batch exists; use --resume")
            state = json.loads(state_path.read_text())
            if state["environment"] != environment or state["extension"] != extension:
                raise ValueError("Batch source/dependency identity changed")
        else:
            if resume:
                raise ValueError("No v3 batch exists to resume")
            for name in DATASETS:
                for stage in ("confirmation", "test"):
                    if (ROOT / f"research/runs/{prefix}_{name}_{stage}").exists():
                        raise ValueError("Fresh v3 collection directory already exists")
            state = {"schema": "accuracy-v3-batch", "batch_name": prefix, "created_utc": utc(), "environment": environment,
                     "extension": extension, "datasets": list(DATASETS), "stages": {},
                     "initial_estimate_hours": [2, 3], "accuracy_rule": "nDCG@5 unchanged; Recall@8 >=98% of gas_l6; redundancy decreases"}
        state.update(status="running", supervisor_pid=os.getpid())
        save(state, state_path)
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        try:
            for name in DATASETS:
                confirmation = ROOT / f"research/runs/{prefix}_{name}_confirmation"
                test = ROOT / f"research/runs/{prefix}_{name}_test"
                frozen = ROOT / f"research/runs/{prefix}_{name}_frozen.json"
                stages = (("confirm", ["--dataset", name, "--directory", str(confirmation)], confirmation / "manifest.json"),
                          ("confirm_evaluate", ["--directory", str(confirmation)], confirmation / "evaluation.json"),
                          ("confirm_report", ["--directory", str(confirmation)], confirmation / "REPORT.md"),
                          ("freeze", ["--directory", str(confirmation), "--output", str(frozen)], frozen),
                          ("run", ["--dataset", name, "--directory", str(test), "--frozen", str(frozen)], test / "manifest.json"),
                          ("evaluate", ["--directory", str(test)], test / "evaluation.json"),
                          ("report", ["--directory", str(test)], test / "REPORT.md"))
                for stage, arguments, artifact in stages:
                    if interrupted:
                        raise InterruptedError("Batch interrupted")
                    if environment_identity() != environment or extension_identity() != extension:
                        raise ValueError("Source/dependency changes detected during background execution")
                    if stage == "freeze":
                        state.update(active_dataset=name, active_stage="confirmation_gate")
                        save(state, state_path)
                        require_confirmation_gate(name, confirmation)
                    key = f"{name}:{stage}"
                    previous = state["stages"].get(key)
                    if previous and previous["status"] == "completed":
                        if not artifact.is_file() or sha(artifact) != previous["artifact_sha256"]:
                            raise ValueError(f"Completed stage artifact changed: {key}")
                        continue
                    command_name = stage.removeprefix("confirm_")
                    command = [str(PYTHON), "-u", "-m", "research.accuracy_v3", command_name, *arguments]
                    directory = confirmation if stage == "confirm" else test
                    if stage in {"confirm", "run"} and (directory / "run.json").exists():
                        command.append("--resume")
                    logfile = logs / f"{name}_{stage}.log"
                    item = {"status": "running", "started_utc": utc(), "attempt": (previous or {}).get("attempt", 0) + 1,
                            "command": command, "log": str(logfile.relative_to(ROOT))}
                    state["stages"][key] = item
                    state.update(active_dataset=name, active_stage=stage)
                    save(state, state_path)
                    print(f"{utc()} START {key}; log={logfile}", flush=True)
                    with logfile.open("a", buffering=1) as log:
                        log.write(f"\n{utc()} attempt {item['attempt']}: {command!r}\n")
                        child = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log,
                                                 stderr=subprocess.STDOUT, env=os.environ.copy())
                        item["pid"] = child.pid
                        save(state, state_path)
                        initial_count = len(list((directory / "queries").glob("*.json"))) if stage in {"confirm", "run"} else 0
                        session_start = time.monotonic()
                        while True:
                            try:
                                code = child.wait(timeout=15)
                                break
                            except subprocess.TimeoutExpired:
                                if stage in {"confirm", "run"}:
                                    run_path = directory / "run.json"
                                    if run_path.exists():
                                        total = len(read_checked(run_path)["identity"]["query_ids"])
                                        committed = len(list((directory / "queries").glob("*.json")))
                                        elapsed = time.monotonic() - session_start
                                        done = committed - initial_count
                                        item["progress"] = {"committed_queries": committed, "total_queries": total,
                                                            "session_elapsed_seconds": elapsed,
                                                            "remaining_stage_seconds_estimate": (total - committed) * elapsed / done if done > 0 else None}
                                        save(state, state_path)
                        child = None
                    item.update(returncode=code, ended_utc=utc())
                    if interrupted or code == 130:
                        item["status"] = "interrupted"
                        raise InterruptedError(f"Stopped at {key}")
                    if code != 0 or not artifact.is_file():
                        item["status"] = "failed"
                        raise RuntimeError(f"{key} failed; inspect {logfile}")
                    item.update(status="completed", artifact=str(artifact.relative_to(ROOT)), artifact_sha256=sha(artifact))
                    save(state, state_path)
                    print(f"{utc()} COMPLETE {key}", flush=True)
                summarize(state)
                evaluation = read_checked(test / "evaluation.json")
                if not evaluation["gate"]["passed"]:
                    raise AccuracyGateFailure(f"{name} test accuracy/redundancy gate failed; results retained, no retuning or next dataset")
            state.update(status="completed", completed_utc=utc(), active_dataset=None, active_stage=None)
            save(state, state_path)
            summarize(state)
            print(f"{utc()} ALL THREE DATASETS COMPLETE", flush=True)
            return 0
        except BaseException as exc:
            status = "interrupted" if isinstance(exc, (KeyboardInterrupt, InterruptedError)) else "gate_failed" if isinstance(exc, AccuracyGateFailure) else "failed"
            state.update(status=status,
                         error=f"{type(exc).__name__}: {exc}")
            save(state, state_path)
            summarize(state)
            print(f"{utc()} {state['status'].upper()}: {exc}", flush=True)
            return 130 if state["status"] == "interrupted" else 1
