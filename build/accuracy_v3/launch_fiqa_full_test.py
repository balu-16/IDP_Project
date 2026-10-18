"""Detach/resume the frozen FiQA test; never collect other datasets."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from research.accuracy_v3.storage import (atomic_bytes, environment_identity,
    exclusive, extension_identity, read_checked, sha, utc)

SELF = Path(__file__).resolve()
PYTHON = ROOT / "backend/.venv/bin/python"
RUNS = ROOT / "research/runs"
PREFIX = "accuracy_v3_redundancy_fiqa_full"
STATE = RUNS / f"{PREFIX}_execution.json"
PID = RUNS / f"{PREFIX}.pid"
LOCK = RUNS / f"{PREFIX}.lock"
LOG = RUNS / f"{PREFIX}_supervisor.log"
LOGS = RUNS / "accuracy_v3_redundancy_logs"
CONFIRM = RUNS / "accuracy_v3_redundancy_fiqa_confirmation"
FROZEN = RUNS / "accuracy_v3_redundancy_fiqa_frozen.json"
TEST = RUNS / "accuracy_v3_redundancy_fiqa_test"
SNAPSHOT = RUNS / f"{PREFIX}_source_snapshot.py"


def save(state):
    state["updated_utc"] = utc()
    atomic_bytes(STATE, (json.dumps(state, indent=2, allow_nan=False) + "\n").encode())


def birth(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def live(state):
    pid = state.get("supervisor_pid")
    try:
        command = Path(f"/proc/{pid}/cmdline").read_bytes()
        return (str(SELF).encode() in command and b"--supervise" in command
                and birth(pid) == state.get("process_start_ticks"))
    except OSError:
        return False


def fingerprint():
    return {"environment": environment_identity(), "extension": extension_identity(),
            "controller_sha256": sha(SELF),
            "confirmation_manifest_sha256": sha(CONFIRM / "manifest.json"),
            "confirmation_evaluation_sha256": sha(CONFIRM / "evaluation.json")}


def supervise(resume=False):
    child, interrupted = None, False
    def stop(signum, frame):
        nonlocal interrupted
        interrupted = True
        if child is not None and child.poll() is None:
            child.send_signal(signal.SIGTERM)
    with exclusive(LOCK):
        current = fingerprint()
        if STATE.exists():
            if not resume:
                raise ValueError("FiQA supervisor state exists; use --resume")
            state = json.loads(STATE.read_text())
            if state["fingerprint"] != current:
                raise ValueError("FiQA resume rejected: source, dependencies, or confirmation changed")
            if not SNAPSHOT.is_file() or sha(SNAPSHOT) != current["controller_sha256"]:
                raise ValueError("FiQA controller snapshot missing or corrupt")
        else:
            if resume:
                raise ValueError("No FiQA supervisor state to resume")
            if TEST.exists() or FROZEN.exists():
                raise ValueError("FiQA artifacts exist without supervisor state; refusing replacement")
            atomic_bytes(SNAPSHOT, SELF.read_bytes())
            state = {"schema": "accuracy-v3-fiqa-only-full-v1", "created_utc": utc(),
                     "fingerprint": current, "stages": {}, "sessions": [],
                     "dataset": "fiqa", "expected_queries": 648,
                     "expected_methods": 27, "seeds": list(range(5)),
                     "confirmation_directory": str(CONFIRM), "test_directory": str(TEST)}
        session = {"started_utc": utc(), "pid": os.getpid(), "status": "running"}
        for prior in state["sessions"]:
            if prior["status"] == "running":
                prior.update(status="interrupted", recovery_detected_utc=utc())
        state["sessions"].append(session)
        state.update(status="running", supervisor_pid=os.getpid(),
                     process_start_ticks=birth(os.getpid()), active_stage="verification")
        atomic_bytes(PID, f"{os.getpid()}\n".encode())
        save(state)
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        LOGS.mkdir(parents=True, exist_ok=True)
        base = [str(PYTHON), "-u", "-m", "research.accuracy_v3"]
        stages = (
            ("preflight", base + ["preflight"], ROOT / "build/accuracy_v3/preflight.json"),
            ("freeze", base + ["freeze", "--directory", str(CONFIRM), "--output", str(FROZEN)], FROZEN),
            ("run", base + ["run", "--dataset", "fiqa", "--directory", str(TEST), "--frozen", str(FROZEN)], TEST / "manifest.json"),
            ("evaluate", base + ["evaluate", "--directory", str(TEST)], TEST / "evaluation.json"),
            ("report", base + ["report", "--directory", str(TEST)], TEST / "REPORT.md"))
        try:
            from research.accuracy_v3.checks import require_smoke
            require_smoke()
            data = read_checked(CONFIRM / "evaluation.json")
            manifest = read_checked(CONFIRM / "manifest.json")
            if (data["query_count"] != 100 or len(manifest["query_ids"]) != 100
                    or not data["gate"]["passed"]
                    or data["manifest_sha256"] != sha(CONFIRM / "manifest.json")):
                raise ValueError("FiQA requires the verified successful 100-query confirmation")
            for name, command, artifact in stages:
                if interrupted:
                    raise InterruptedError("Supervisor interrupted")
                if fingerprint() != current:
                    raise ValueError("Provenance changed while FiQA was running")
                prior = state["stages"].get(name)
                if prior and prior["status"] == "completed":
                    if not artifact.is_file() or sha(artifact) != prior["artifact_sha256"]:
                        raise ValueError(f"Completed FiQA stage artifact changed: {name}")
                    continue
                if name == "run" and (TEST / "run.json").exists():
                    command += ["--resume"]
                item = {"status": "running", "started_utc": utc(), "command": command,
                        "attempt": (prior or {}).get("attempt", 0) + 1,
                        "log": str(LOGS / f"fiqa_full_{name}.log")}
                state["stages"][name] = item
                state["active_stage"] = name
                save(state)
                print(f"{utc()} START FiQA {name}; log={item['log']}", flush=True)
                with Path(item["log"]).open("a", buffering=1) as handle:
                    handle.write(f"\n{utc()} attempt {item['attempt']}: {command!r}\n")
                    child = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                        stdout=handle, stderr=subprocess.STDOUT, env=os.environ.copy())
                    item["pid"] = child.pid
                    save(state)
                    if interrupted:
                        child.send_signal(signal.SIGTERM)
                    while True:
                        try:
                            code = child.wait(timeout=15)
                            break
                        except subprocess.TimeoutExpired:
                            if name == "run":
                                item["committed_queries"] = len(list((TEST / "queries").glob("*.json")))
                                item["total_queries"] = 648
                                save(state)
                    child = None
                item.update(returncode=code, ended_utc=utc())
                if interrupted or code == 130:
                    item["status"] = "interrupted"
                    raise InterruptedError(f"FiQA interrupted at {name}")
                if code != 0 or not artifact.is_file():
                    item["status"] = "failed"
                    raise RuntimeError(f"FiQA {name} failed; inspect {item['log']}")
                if name == "run":
                    run = read_checked(TEST / "run.json")["identity"]
                    completed = read_checked(artifact)
                    from research.accuracy_v3.pipeline import expected_methods
                    if (run["dataset"] != "fiqa" or len(completed["query_ids"]) != 648
                            or len(expected_methods()) != 27):
                        raise ValueError("FiQA final coverage/identity is incomplete")
                    item["committed_queries"] = 648
                item.update(status="completed", artifact=str(artifact), artifact_sha256=sha(artifact))
                save(state)
                print(f"{utc()} COMPLETE FiQA {name}", flush=True)
            result = read_checked(TEST / "evaluation.json")
            state.update(status="completed" if result["gate"]["passed"] else "gate_failed",
                         active_stage=None, gate=result["gate"], completed_utc=utc())
            session.update(status=state["status"], ended_utc=utc())
            save(state)
            print(f"{utc()} FiQA {state['status']}; report={TEST / 'REPORT.md'}", flush=True)
            return 0 if result["gate"]["passed"] else 2
        except BaseException as exc:
            if child is not None and child.poll() is None:
                child.send_signal(signal.SIGTERM)
                child.wait()
            status = "interrupted" if isinstance(exc, (KeyboardInterrupt, InterruptedError)) else "failed"
            session.update(status=status, ended_utc=utc())
            state.update(status=status, error=f"{type(exc).__name__}: {exc}")
            save(state)
            print(f"{utc()} {status.upper()}: {exc}", flush=True)
            return 130 if status == "interrupted" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--supervise", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    if args.supervise:
        return supervise(args.resume)
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    if args.status:
        print(json.dumps({**state, "supervisor_alive": live(state)}, indent=2))
        return 0
    if args.stop:
        if not live(state):
            raise ValueError("No verified live FiQA supervisor to stop")
        os.kill(state["supervisor_pid"], signal.SIGTERM)
        print("Graceful stop requested; committed checkpoints will be retained")
        return 0
    if live(state):
        raise ValueError(f"FiQA already running: PID {state['supervisor_pid']}")
    if state and not args.resume:
        raise ValueError("FiQA state exists; use --resume")
    if not state and args.resume:
        raise ValueError("No FiQA execution to resume")
    command = [str(PYTHON), "-u", str(SELF), "--supervise"]
    if args.resume:
        command += ["--resume"]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", HF_HUB_OFFLINE="1",
               TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false",
               OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2", MKL_NUM_THREADS="2")
    RUNS.mkdir(parents=True, exist_ok=True)
    with LOG.open("ab", buffering=0) as handle:
        process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
            stdout=handle, stderr=subprocess.STDOUT, start_new_session=True, env=env)
    print(json.dumps({"supervisor_pid": process.pid, "log": str(LOG), "state": str(STATE)}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
