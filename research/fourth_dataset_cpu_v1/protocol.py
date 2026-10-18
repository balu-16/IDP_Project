"""Versioned preparation profile and immutable import of completed encoding work."""
from pathlib import Path
import shutil

import numpy as np

from research.accuracy_v2.encoding import validate_matrix
from research.accuracy_v2.storage import (ROOT, atomic_bytes, digest, exclusive, read_checked,
                                        sha, utc, write_checked)
from research.fourth_dataset_v1 import protocol as parent

STUDY = ROOT / "research/runs/fourth_dataset_cpu_v1_trec_covid"
CACHE = ROOT / "research/cache/fourth_dataset_cpu_v1/trec-covid"
PARENT = parent.STUDY


def sources():
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted(Path(__file__).parent.glob("*.py"))}


def verify_shards(directory, expected_rows=None):
    directory = Path(directory)
    identity = read_checked(directory / "identity.json")
    rows, records = 0, []
    for path in sorted(directory.glob("[0-9]*.json")):
        record = read_checked(path)
        if (record["identity"] != digest(identity) or record["begin"] != rows or
                record["end"] != min(rows + identity["shard_rows"], identity["rows"]) or
                path.name != f"{rows:09}.json" or sha(path.with_suffix(".npy")) != record["sha256"]):
            raise ValueError(f"Corrupt or noncontiguous encoding shard: {path}")
        matrix = np.load(path.with_suffix(".npy"), mmap_mode="r", allow_pickle=False)
        validate_matrix(matrix, record["end"] - rows, 384)
        if list(matrix.shape) != record["shape"]:
            raise ValueError("Shard metadata shape mismatch")
        records.append({"begin": rows, "end": record["end"], "array_sha256": record["sha256"],
                        "commit_sha256": sha(path), "encode_ms": record["encode_ms"]})
        rows = record["end"]
    if expected_rows is not None and rows != expected_rows:
        raise ValueError("Imported shard row coverage mismatch")
    return identity, records


def prepare(study=STUDY):
    study = Path(study)
    parent.require_frozen(PARENT)
    stop = read_checked(PARENT / "stop_for_cpu_profile.json")
    state = read_checked(PARENT / "execution.json")
    if not stop["both_stopped"] or state["status"] != "interrupted" or state.get("committed_queries", 0):
        raise ValueError("Original encoder must be stopped before importing its cache")
    with exclusive(PARENT / ".supervisor.lock"):
        key = stop["cache_key"]
        original = parent.CACHE / f"{key}.shards"
        shard_identity, records = verify_shards(original, stop["committed_rows"])
        if [{k: r[k] for k in ("begin", "end", "commit_sha256", "array_sha256")} for r in records] != stop["shards"]:
            raise ValueError("Original cache changed after the verified stop")
        study.mkdir(parents=True, exist_ok=True)
        destination = CACHE / f"{key}.shards"
        destination.mkdir(parents=True, exist_ok=True)
        names = ["identity.json"] + [name for r in records for name in
                 (f"{r['begin']:09}.npy", f"{r['begin']:09}.json")]
        for name in names:
            target, source = destination / name, original / name
            if target.exists():
                if sha(target) != sha(source):
                    raise ValueError(f"Existing imported file changed: {target}")
            else:
                # Separate copies prevent later cache damage from modifying the parent.
                atomic_bytes(target, source.read_bytes())
        imported = {"parent_study": str(PARENT.relative_to(ROOT)), "parent_frozen_sha256": sha(PARENT / "frozen.json"),
            "stop_record_sha256": sha(PARENT / "stop_for_cpu_profile.json"), "cache_key": key,
            "shard_identity": shard_identity, "rows": stop["committed_rows"],
            "records": [{**r, "encoding_threads": 2} for r in records]}
        path = study / "imported_shards.json"
        if path.exists() and read_checked(path) != imported:
            raise ValueError("Imported encoding prefix is immutable")
        write_checked(path, imported)
        for name in ("preflight.json", "smoke.json", "smoke_tests.log", "dataset_inventory.json"):
            target = study / name
            if target.exists() and sha(target) != sha(PARENT / name):
                raise ValueError(f"Inherited preparation artifact changed: {name}")
            if not target.exists():
                atomic_bytes(target, (PARENT / name).read_bytes())
    return path


def freeze(study=STUDY):
    study = Path(study)
    if (study / "frozen.json").exists():
        require_frozen(study)
        return study / "frozen.json"
    original = parent.require_frozen(PARENT)
    benchmark = read_checked(study / "cpu_benchmark.json")
    checks = read_checked(study / "cpu_checks.json")
    if benchmark["cpu_sources"] != sources() or checks["cpu_sources"] != sources() or not checks["passed"]:
        raise ValueError("CPU benchmark or regression evidence does not match current adapter sources")
    imported = read_checked(study / "imported_shards.json")
    verify_shards(CACHE / f"{imported['cache_key']}.shards", imported["rows"])
    required = imported["shard_identity"]["rows"] * 384 * 8 * 2 + 750_000_000
    available = shutil.disk_usage(ROOT).free
    from research.fourth_dataset_v1.checks import memory_available
    memory = memory_available()
    if available < required or memory < read_checked(study / "preflight.json")["estimated_memory_bytes"]:
        raise ValueError("Insufficient storage/RAM for resumed encoding and evaluation")
    ident = {**original, "cache_namespace": str(CACHE.relative_to(ROOT)), "cpu_sources": sources(),
        "cpu_preparation": {"parent_protocol_sha256": sha(PARENT / "frozen.json"),
            "imported_shards_sha256": sha(study / "imported_shards.json"),
            "benchmark_sha256": sha(study / "cpu_benchmark.json"), "checks_sha256": sha(study / "cpu_checks.json"),
            "declaration_sha256": sha(study / "benchmark_declaration.json"),
            "sample_sha256": sha(study / "benchmark_sample.json"),
            "encoding_threads": benchmark["selection"]["threads"], "online_threads": 2,
            "interop_threads": 1, "batch_size": 8, "imported_threads": 2,
            "available_storage_bytes": available, "available_memory_bytes": memory,
            "note": "Offline preparation profile changed before any test rankings. Parent token preflight reused for identical data/model/chunk code; actual encoding profiles recorded by shard. Online timings retain two threads."}}
    all_sources = {**ident["environment"]["sources"], **ident["extension"]["sources"],
                   **ident["fourth_sources"], **ident["cpu_sources"]}
    for relative, expected in all_sources.items():
        target = study / "source_snapshot" / relative
        atomic_bytes(target, (ROOT / relative).read_bytes())
        if sha(target) != expected:
            raise ValueError("Source changed while freezing CPU profile")
    write_checked(study / "frozen.json", {"created_utc": utc(), "identity": ident})
    return study / "frozen.json"


def require_frozen(study=STUDY):
    study = Path(study)
    ident = parent.require_frozen(study)
    if ident["cpu_sources"] != sources():
        raise ValueError("CPU adapter source fingerprint mismatch; restore recorded sources")
    profile = ident["cpu_preparation"]
    for name, filename in (("imported_shards", "imported_shards.json"), ("benchmark", "cpu_benchmark.json"),
                           ("checks", "cpu_checks.json"), ("sample", "benchmark_sample.json"),
                           ("declaration", "benchmark_declaration.json")):
        if sha(study / filename) != profile[f"{name}_sha256"]:
            raise ValueError(f"CPU profile artifact changed: {filename}")
    checks = read_checked(study / "cpu_checks.json")
    if sha(study / "cpu_tests.log") != checks["test_log_sha256"]:
        raise ValueError("CPU regression-test log changed")
    benchmark = read_checked(study / "cpu_benchmark.json")
    for threads, record in benchmark["profiles"].items():
        path = study / "benchmark" / f"threads_{threads}.npy"
        if sha(path) != record["matrix_sha256"] or read_checked(path.with_suffix(".json")) != record:
            raise ValueError("CPU benchmark output changed after freezing")
    for relative, expected in ident["cpu_sources"].items():
        if sha(study / "source_snapshot" / relative) != expected:
            raise ValueError(f"CPU source snapshot corrupt: {relative}")
    imported = read_checked(study / "imported_shards.json")
    for row in imported["records"]:
        path = CACHE / f"{imported['cache_key']}.shards" / f"{row['begin']:09}"
        if sha(path.with_suffix(".json")) != row["commit_sha256"] or sha(path.with_suffix(".npy")) != row["array_sha256"]:
            raise ValueError("Imported encoding prefix changed")
    return ident


class Store(parent.Store):
    def __init__(self, directory, identity, resume=False):
        if identity["cpu_sources"] != sources():
            raise ValueError("CPU source identity mismatch")
        super().__init__(directory, identity, resume)
        for relative, expected in identity["cpu_sources"].items():
            target = self.path / "source_snapshot" / relative
            if not resume:
                atomic_bytes(target, (ROOT / relative).read_bytes())
            if sha(target) != expected:
                raise ValueError("CPU collection snapshot corrupt")

    def seal(self, query_ids, validate):
        if self.identity["cpu_sources"] != sources():
            raise ValueError("CPU source changed during collection")
        super().seal(query_ids, validate)

    def verify(self):
        if self.identity["cpu_sources"] != sources():
            raise ValueError("CPU source changed since collection")
        return super().verify()
