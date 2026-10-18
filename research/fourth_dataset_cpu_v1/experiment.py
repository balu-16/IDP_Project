"""Two-thread collection with frozen kernels and explicit offline profile reporting."""
from pathlib import Path
import time

import numpy as np

from research.accuracy_v2.storage import atomic_bytes, exclusive, read_checked, sha, utc, write_checked
from research.fourth_dataset_v1 import data, experiment as original
from .pipeline import Runtime, apply_threads, verify_encoding
from .protocol import STUDY, Store, require_frozen


def run(study=STUDY, resume=False):
    study = Path(study)
    apply_threads(2)
    ident = require_frozen(study)
    encoding = verify_encoding(study, ident)
    ident = {**ident, "frozen_protocol_sha256": sha(study / "frozen.json"),
             "encoding_artifact_sha256": sha(study / "encoding.json"),
             "embedding_matrix_sha256": encoding["matrix_sha256"]}
    corpus, queries, _ = data.load()
    if sorted(queries) != ident["query_ids"]:
        raise ValueError("Query coverage differs from frozen transfer protocol")
    directory = study / "test"
    with exclusive(directory / ".lock"):
        store = Store(directory, ident, resume)
        if (directory / "manifest.json").exists():
            store.verify()
            return directory / "manifest.json"
        durations = []
        def progress(index, elapsed):
            durations.append(elapsed)
            write_checked(study / "collection_progress.json", {"updated_utc": utc(), "online_threads": 2,
                "committed_queries": index, "total_queries": len(queries),
                "mean_query_seconds_this_session": float(np.mean(durations)),
                "estimated_remaining_minutes": float(np.mean(durations)) * (len(queries) - index) / 60})
        original.collect_into(store, corpus, queries, Runtime, progress=progress)
    return directory / "manifest.json"


def open_completed(study=STUDY):
    require_frozen(study)
    store, manifest = original.open_completed(study)
    Store(store.path, store.identity, resume=True).verify()
    return store, manifest


def evaluate(study=STUDY):
    apply_threads(2)
    open_completed(study)
    return original.evaluate(study)


def report(study=STUDY):
    store, _ = open_completed(study)
    path = original.report(study)
    benchmark = read_checked(Path(study) / "cpu_benchmark.json")
    imported = read_checked(Path(study) / "imported_shards.json")
    threads = store.identity["cpu_preparation"]["encoding_threads"]
    extra = ("\n## Offline encoding CPU profile\n\n"
        f"Imported {imported['rows']:,} verified chunks encoded with two threads. "
        f"Remaining corpus encoding used {threads} threads; all online retrieval, L6/L2 scoring, "
        "selection, and 27 comparisons used two threads in a fresh process. "
        f"The label-free pilot measured {benchmark['selection']['measured_speedup']:.3f}x encoding throughput "
        "relative to two threads. This is an offline preparation measurement, not a Grover or online retrieval speedup. "
        "Thread-count changes can introduce small floating-point differences; sample embeddings passed the declared numerical tolerance. "
        "Complete mixed-profile costs and per-shard provenance are in encoding_profiles.json.\n")
    atomic_bytes(path, (path.read_text() + extra).encode())
    return path
