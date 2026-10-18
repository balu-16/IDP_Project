"""Atomic task execution, bounded pilot, detached batch, and strict recovery."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from .storage import (ROOT, atomic_bytes, digest, exclusive, load_input, once,
    prerequisites, protocol, read_checked, read_result, result_path, sha, utc, write_checked)


def task_index(directory):
    protocol(directory)
    frozen = read_checked(directory / "frozen_inputs.json")
    if frozen["protocol_sha256"] != sha(directory / "protocol.json") or frozen["tasks_sha256"] != sha(directory / "tasks.json"):
        raise ValueError("Frozen resource task identity mismatch")
    return read_checked(directory / "tasks.json")


class Executor:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.child = None
        self.interrupted = False

    def stop(self, signum, frame):
        self.interrupted = True
        if self.child is not None and self.child.poll() is None:
            self.child.send_signal(signal.SIGTERM)

    def execute(self, task):
        directory = self.directory
        saved = read_result(directory, task)
        if saved is not None:
            return saved, True
        if self.interrupted:
            raise InterruptedError("Resource study interrupted; committed results retained")
        load_input(directory, task)
        name = digest(task)
        request = directory / "requests" / f"{name}.json"
        pending = directory / "pending" / f"{name}.json"
        logfile = directory / "logs" / f"{name}.log"
        payload = {"directory": str(directory.resolve()), "task": task}
        encoded = (json.dumps(payload, sort_keys=True) + "\n").encode()
        if request.exists() and request.read_bytes() != encoded:
            raise ValueError("Resource task request changed")
        atomic_bytes(request, encoded)
        logfile.parent.mkdir(parents=True, exist_ok=True)
        # A pending file is an uncommitted worker result, never a final checkpoint.
        # Preserve it for diagnosis before recomputing unfinished work.
        if pending.exists():
            read_checked(pending)  # explicitly reject corrupt pending results
            pending.rename(pending.with_name(f"{pending.stem}.uncommitted-{time.time_ns()}.json"))
        start = time.perf_counter()
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", OMP_NUM_THREADS="2",
                   OPENBLAS_NUM_THREADS="2", MKL_NUM_THREADS="2", HF_HUB_OFFLINE="1",
                   TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
        timeout = 120 if task["kind"] == "native" else 300
        with logfile.open("a") as log:
            log.write(f"\n{utc()} START {task!r}\n")
            log.flush()
            self.child = subprocess.Popen([sys.executable, "-u", "-m", "research.resource_study_v1.worker",
                "--request", str(request), "--output", str(pending)], cwd=ROOT, env=env,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
            try:
                if self.interrupted:
                    self.child.terminate()
                code = self.child.wait(timeout=timeout)
                if self.interrupted or code in (130, -signal.SIGTERM):
                    raise InterruptedError("Resource worker stopped; use --resume")
                if code != 0:
                    tail = logfile.read_text()[-5000:]
                    if "MemoryError" in tail or "Cannot allocate memory" in tail:
                        output = {"status": "memory_limit", "limit_bytes": 2 << 30}
                    else:
                        raise RuntimeError(f"Resource worker failed ({code}); inspect {logfile}")
                else:
                    output = read_checked(pending)
            except subprocess.TimeoutExpired:
                self.child.kill()
                self.child.wait()
                output = {"status": "timeout", "timeout_seconds": timeout}
            except BaseException:
                if self.child.poll() is None:
                    self.child.terminate()
                    self.child.wait()
                raise
            finally:
                self.child = None
        saved = {"protocol_sha256": sha(directory / "protocol.json"), "task": task,
                 "completed_utc": utc(), "process_wall_ms": (time.perf_counter()-start)*1000, "output": output}
        once(result_path(directory, task), saved)
        return saved, False


def pilot(directory):
    directory = Path(directory)
    prerequisites()
    index = task_index(directory)
    tasks = index["tasks"]
    chosen = []
    for dataset in ("scifact", "nfcorpus", "fiqa"):
        chosen.append(next(t for t in tasks if t["kind"] == "compact" and t["dataset"] == dataset))
    native = [t for t in tasks if t["kind"] == "native"]
    for m, bits in ((3, 4), (5, 4), (5, 16), (8, 8), (20, 16)):
        matches = [t for t in native if t["pool"] == m and t["bits"] == bits]
        if matches:
            chosen.append(matches[0])
    executor = Executor(directory)
    old = {s: signal.signal(s, executor.stop) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        with exclusive(directory / ".lock"):
            rows = []
            for i, task in enumerate(chosen, 1):
                result, reused = executor.execute(task)
                rows.append(result)
                print(f"Pilot {i}/{len(chosen)}: {task['kind']} {task['dataset']} {task.get('pool','grid')} "
                      f"{task.get('bits','')} -> {result['output']['status']} ({result['process_wall_ms']/1000:.2f}s)", flush=True)
            compact_times = [r["process_wall_ms"]/1000 for r in rows if r["task"]["kind"] == "compact"]
            native_times = [r["process_wall_ms"]/1000 for r in rows if r["task"]["kind"] == "native"]
            estimate = (sum(t["kind"] == "compact" for t in tasks) * sum(compact_times)/len(compact_times)
                        + sum(t["kind"] == "native" for t in tasks) * max(native_times))
            payload = {"protocol_sha256": sha(directory / "protocol.json"), "tasks": chosen,
                       "statuses": [r["output"]["status"] for r in rows],
                       "estimated_total_seconds_conservative": estimate,
                       "estimated_range_minutes": [max(1, estimate*.5/60), max(2, estimate*1.5/60)],
                       "estimate_rule": "mean compact worker and maximum pilot native worker; resource-limit cells retained",
                       "total_tasks": len(tasks)}
            write_checked(directory / "pilot.json", payload)
            return payload
    finally:
        for signum, handler in old.items():
            signal.signal(signum, handler)


def run(directory, resume=False):
    directory = Path(directory)
    prerequisites()
    index = task_index(directory)
    if not (directory / "pilot.json").exists():
        raise ValueError("Run the pilot and report its estimate before the complete study")
    if read_checked(directory / "pilot.json")["protocol_sha256"] != sha(directory / "protocol.json"):
        raise ValueError("Pilot identity mismatch")
    state_path = directory / "execution.json"
    executor = Executor(directory)
    old = {s: signal.signal(s, executor.stop) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        with exclusive(directory / ".lock"):
            if state_path.exists():
                if not resume:
                    raise ValueError("Resource execution exists; use --resume")
                state = read_checked(state_path)
                if state["protocol_sha256"] != sha(directory / "protocol.json"):
                    raise ValueError("Resource execution identity mismatch")
            else:
                state = {"protocol_sha256": sha(directory / "protocol.json"), "created_utc": utc(), "sessions": []}
            session = {"started_utc": utc(), "pid": os.getpid(), "status": "running"}
            for prior in state["sessions"]:
                if prior["status"] == "running":
                    prior.update(status="interrupted", recovery_detected_utc=utc())
            state["sessions"].append(session)
            state.update(status="running", supervisor_pid=os.getpid(), completed_tasks=0, total_tasks=len(index["tasks"]))
            write_checked(state_path, state)
            try:
                for i, task in enumerate(index["tasks"], 1):
                    protocol(directory)
                    result, reused = executor.execute(task)
                    state.update(completed_tasks=i, active_task=task, updated_utc=utc())
                    write_checked(state_path, state)
                    print(f"Resource {i}/{len(index['tasks'])}: {task['kind']} {task['dataset']} "
                          f"{task.get('pool','grid')} {task.get('bits','')} {result['output']['status']}"
                          f"{' [verified checkpoint]' if reused else ''}", flush=True)
                files = {str(path.relative_to(directory)): sha(path)
                         for path in sorted((directory / "results").glob("*.json"))}
                if len(files) != len(index["tasks"]):
                    raise ValueError("Resource task/result coverage mismatch")
                completed_at = (read_checked(directory / "manifest.json")["completed_utc"]
                                if (directory / "manifest.json").exists() else utc())
                once(directory / "manifest.json", {"protocol_sha256": sha(directory / "protocol.json"),
                    "task_index_sha256": sha(directory / "tasks.json"), "files": files,
                    "task_count": len(index["tasks"]), "completed_utc": completed_at})
                state.update(status="completed", active_task=None, completed_utc=utc())
                session.update(status="completed", ended_utc=utc())
                write_checked(state_path, state)
            except BaseException as exc:
                status = "interrupted" if isinstance(exc, (KeyboardInterrupt, InterruptedError)) else "failed"
                session.update(status=status, ended_utc=utc())
                state.update(status=status, error=f"{type(exc).__name__}: {exc}")
                write_checked(state_path, state)
                raise
    finally:
        for signum, handler in old.items():
            signal.signal(signum, handler)
    from .report import report
    return report(directory)
