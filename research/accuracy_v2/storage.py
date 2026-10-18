"""Checksummed, atomic work units and strict resumable run identities."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import signal
import tempfile

from . import VERSION

ROOT = Path(__file__).resolve().parents[2]


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            result.update(chunk)
    return result.hexdigest()


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_bytes(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".pending-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_checked(path, payload):
    atomic_bytes(path, canonical({"sha256": digest(payload), "payload": payload}) + b"\n")


def read_checked(path):
    path = Path(path)
    try:
        value = json.loads(path.read_text())
        if set(value) != {"sha256", "payload"} or digest(value["payload"]) != value["sha256"]:
            raise ValueError("checksum mismatch")
        return value["payload"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"Corrupt checkpoint {path}: {exc}") from exc


def source_paths():
    files = sorted((ROOT / "research").glob("*.py"))
    files += sorted((ROOT / "research" / "accuracy_v2").glob("*.py"))
    files += [ROOT / "research" / "neural_model_pins.json", ROOT / "backend" / "config.py"]
    files += [ROOT / "backend" / "services" / name for name in ("circuits.py", "quantum_search.py", "workers.py")]
    return files


def environment_identity():
    packages = {}
    for name in ("numpy", "scipy", "torch", "transformers", "sentence-transformers", "huggingface-hub", "qiskit", "qiskit-aer"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {"schema": VERSION, "python": platform.python_version(), "packages": packages,
            "sources": {str(path.relative_to(ROOT)): sha(path) for path in source_paths()},
            "cpu_threads": 2}


def utc():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def exclusive(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError(f"Another process owns {path.parent}") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


class Store:
    def __init__(self, directory, identity, resume=False):
        self.path = Path(directory)
        self.identity = identity
        run = self.path / "run.json"
        if run.exists():
            if not resume:
                raise ValueError(f"Run already exists; use --resume: {self.path}")
            saved = read_checked(run)
            if saved["identity"] != identity:
                keys = sorted(k for k in set(saved["identity"]) | set(identity) if saved["identity"].get(k) != identity.get(k))
                raise ValueError(f"Resume identity mismatch: {', '.join(keys)}; use the recorded code/configuration or a new run directory")
            for relative, expected in identity.get("environment", {}).get("sources", {}).items():
                if sha(self.path / "source_snapshot" / relative) != expected:
                    raise ValueError(f"Source snapshot corrupted: {relative}")
        else:
            if resume:
                raise ValueError(f"Cannot resume: missing {run}")
            if self.path.exists() and any(p.name != ".lock" for p in self.path.iterdir()):
                raise ValueError(f"Refusing to overwrite nonempty directory: {self.path}")
            self.path.mkdir(parents=True, exist_ok=True)
            for relative in identity.get("environment", {}).get("sources", {}):
                atomic_bytes(self.path / "source_snapshot" / relative, (ROOT / relative).read_bytes())
                if sha(self.path / "source_snapshot" / relative) != identity["environment"]["sources"][relative]:
                    raise ValueError(f"Source changed during initialization: {relative}")
            write_checked(run, {"created_utc": utc(), "identity": identity})
        self.fingerprint = digest(identity)

    def file(self, stage, qid):
        return self.path / stage / (hashlib.sha256(str(qid).encode()).hexdigest() + ".json")

    def get(self, stage, qid):
        path = self.file(stage, qid)
        if not path.exists():
            return None
        value = read_checked(path)
        if value["identity"] != self.fingerprint or value["qid"] != str(qid):
            raise ValueError(f"Checkpoint identity mismatch: {path}")
        return value["data"]

    def put(self, stage, qid, data, hook=None):
        path = self.file(stage, qid)
        if path.exists():
            if self.get(stage, qid) != data:
                raise ValueError(f"Refusing to replace committed work: {path}")
            return
        if hook:
            hook("before_commit", stage, qid)
        write_checked(path, {"identity": self.fingerprint, "qid": str(qid), "data": data})
        if hook:
            hook("after_commit", stage, qid)

    @contextmanager
    def session(self):
        path = self.path / "sessions.json"
        sessions = read_checked(path) if path.exists() else []
        for previous in sessions:
            if previous["status"] == "running":
                previous.update(status="interrupted", recovery_detected_utc=utc())
        record = {"started_utc": utc(), "status": "running", "pid": os.getpid(),
                  "platform": platform.platform(), "cpu": platform.processor(),
                  "thread_environment": {k: os.environ.get(k) for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")}}
        sessions.append(record)
        write_checked(path, sessions)
        previous_handler = signal.getsignal(signal.SIGTERM)
        def stop(signum, frame):
            raise InterruptedError("SIGTERM: committed work retained; resume this run")
        signal.signal(signal.SIGTERM, stop)
        try:
            yield
        except BaseException as exc:
            record.update(status="interrupted" if isinstance(exc, (KeyboardInterrupt, InterruptedError)) else "failed",
                          ended_utc=utc(), error=f"{type(exc).__name__}: {exc}")
            raise
        else:
            record.update(status="completed", ended_utc=utc())
        finally:
            signal.signal(signal.SIGTERM, previous_handler)
            write_checked(path, sessions)

    def seal(self, query_ids, validate):
        if "environment" in self.identity and self.identity["environment"] != environment_identity():
            raise ValueError("Source or dependencies changed during execution; refusing to seal mixed provenance")
        expected = set(map(str, query_ids))
        for stage in ("features", "queries"):
            found = set()
            for path in (self.path / stage).glob("*.json"):
                value = read_checked(path)
                qid = value["qid"]
                if path != self.file(stage, qid) or qid in found:
                    raise ValueError("Duplicate or misnamed query checkpoint")
                found.add(qid)
                self.get(stage, qid)
            if found != expected:
                raise ValueError(f"Incomplete {stage} coverage: expected {len(expected)}, found {len(found)}")
        for qid in sorted(expected):
            validate(self.get("queries", qid), self.get("features", qid))
        files = {str(p.relative_to(self.path)): sha(p) for p in sorted(self.path.rglob("*"))
                 if p.is_file() and p.name != ".lock" and not p.name.startswith(".pending-")
                 and p.name not in {"manifest.json", "evaluation.json", "REPORT.md"}}
        write_checked(self.path / "manifest.json", {"schema": VERSION, "identity": self.fingerprint,
                      "completed_utc": utc(), "query_ids": sorted(expected), "files": files})

    def verify(self):
        manifest = read_checked(self.path / "manifest.json")
        if manifest["identity"] != self.fingerprint:
            raise ValueError("Final manifest identity mismatch")
        for relative, expected in manifest["files"].items():
            path = Path(relative)
            if path.is_absolute() or ".." in path.parts or sha(self.path / path) != expected:
                raise ValueError(f"Final artifact corrupted: {relative}")
        actual = {str(p.relative_to(self.path)) for p in self.path.rglob("*")
                  if p.is_file() and p.name != ".lock" and not p.name.startswith(".pending-")
                  and p.name not in {"manifest.json", "evaluation.json", "REPORT.md"}}
        if actual != set(manifest["files"]):
            raise ValueError("Unsealed or missing files in completed run")
        return manifest
