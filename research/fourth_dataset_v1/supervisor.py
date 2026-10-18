"""Dedicated detached supervisor; technical failures stop, scientific failures persist."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from research.accuracy_v2.storage import (ROOT, exclusive, read_checked, write_checked,
                                        atomic_bytes, sha, utc)
from .protocol import STUDY, require_frozen


def launch(study=STUDY, resume=False):
    study = Path(study).resolve()
    require_frozen(study)
    study.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-u", "-m", "research.fourth_dataset_v1", "supervise", "--study", str(study)]
    if resume:
        command.append("--resume")
    # Precheck the same OS lock before creating a competing detached process.
    with exclusive(study / ".supervisor.lock"):
        if (study / "execution.json").exists() and not resume:
            raise ValueError("Supervisor history exists; use launch --resume")
    with (study / "supervisor.log").open("a", buffering=1) as log:
        child = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log,
                                 stderr=subprocess.STDOUT, env=os.environ.copy(), start_new_session=True)
    atomic_bytes(study / "supervisor.pid", f"{child.pid}\n".encode())
    return {"supervisor_pid": child.pid, "log": str(study / "supervisor.log"),
            "status": "spawned; verify execution state and committed progress before claiming launch success"}


def supervise(study=STUDY, resume=False):
    study = Path(study).resolve()
    state_path = study / "execution.json"
    child, stopped = None, False
    def stop(signum, frame):
        nonlocal stopped
        stopped = True
        if child is not None and child.poll() is None:
            child.send_signal(signal.SIGTERM)
    def save():
        state["updated_utc"] = utc()
        write_checked(state_path, state)
    with exclusive(study / ".supervisor.lock"):
        ident = require_frozen(study)
        protocol_hash = sha(study / "frozen.json")
        if state_path.exists():
            if not resume:
                raise ValueError("Supervisor exists; --resume is required")
            state = read_checked(state_path)
            if state["frozen_protocol_sha256"] != protocol_hash:
                raise ValueError("Supervisor resume protocol mismatch")
            if state["status"] in {"completed", "gate_failed"}:
                from .experiment import open_completed
                open_completed(study)
                return state["status"]
        else:
            if resume:
                raise ValueError("No supervisor state to resume")
            state = {"created_utc": utc(), "frozen_protocol_sha256": protocol_hash,
                     "stages": {}, "sessions": [], "dataset": "trec-covid"}
        session = {"pid": os.getpid(), "started_utc": utc(), "status": "running"}
        for previous in state["sessions"]:
            if previous["status"] == "running":
                previous.update(status="interrupted", recovery_detected_utc=utc())
        state["sessions"].append(session)
        state.update(status="running", supervisor_pid=os.getpid())
        atomic_bytes(study / "supervisor.pid", f"{os.getpid()}\n".encode())
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        save()
        try:
            for stage, artifact in (("encode", study / "encoding.json"), ("run", study / "test/manifest.json"),
                                     ("evaluate", study / "test/evaluation.json"), ("report", study / "test/REPORT.md")):
                if stopped:
                    raise InterruptedError("Supervisor stopped; committed work retained")
                require_frozen(study)
                previous = state["stages"].get(stage)
                if previous and previous["status"] == "completed":
                    if not artifact.is_file() or sha(artifact) != previous["artifact_sha256"]:
                        raise ValueError(f"Completed {stage} artifact changed")
                    continue
                command = [sys.executable, "-u", "-m", "research.fourth_dataset_v1", stage, "--study", str(study)]
                if stage == "run" and (study / "test/run.json").exists():
                    command.append("--resume")
                logfile = study / "logs" / f"{stage}.log"
                logfile.parent.mkdir(exist_ok=True)
                item = {"status": "running", "started_utc": utc(), "command": command,
                        "attempt": (previous or {}).get("attempt", 0) + 1, "log": str(logfile)}
                state["stages"][stage] = item
                state["active_stage"] = stage
                save()
                print(f"{utc()} START {stage}; log={logfile}", flush=True)
                with logfile.open("a", buffering=1) as log:
                    log.write(f"\n{utc()} attempt {item['attempt']}\n")
                    child = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log,
                                             stderr=subprocess.STDOUT, env=os.environ.copy())
                    item["pid"] = child.pid
                    save()
                    while child.poll() is None:
                        try:
                            child.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            state["committed_queries"] = len(list((study / "test/queries").glob("*.json")))
                            progress = study / ("encoding_progress.json" if stage == "encode" else "collection_progress.json")
                            if progress.exists():
                                state["progress"] = read_checked(progress)
                            save()
                    code = child.returncode
                    child = None
                if stopped:
                    raise InterruptedError("Supervisor stopped; use launch --resume")
                if code != 0:
                    raise RuntimeError(f"{stage} exited {code}; see {logfile}")
                if not artifact.is_file():
                    raise ValueError(f"{stage} did not produce its required artifact")
                item.update(status="completed", ended_utc=utc(), artifact_sha256=sha(artifact))
                save()
                print(f"{utc()} COMPLETE {stage}", flush=True)
            evaluation = read_checked(study / "test/evaluation.json")
            state.update(status="completed" if evaluation["gate"]["passed"] else "gate_failed",
                         gate=evaluation["gate"], active_stage=None, committed_queries=50)
        except BaseException as exc:
            # A failed heartbeat/integrity check must never leave collection orphaned.
            if child is not None and child.poll() is None:
                child.send_signal(signal.SIGTERM)
                try:
                    child.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=10)
            state.update(status="interrupted" if isinstance(exc, (KeyboardInterrupt, InterruptedError)) else "failed",
                         error=f"{type(exc).__name__}: {exc}")
            active = state["stages"].get(state.get("active_stage"))
            if active and active["status"] == "running":
                active.update(status=state["status"], ended_utc=utc(), error=state["error"])
            raise
        finally:
            session.update(ended_utc=utc(), status=state["status"])
            save()
    return state["status"]
