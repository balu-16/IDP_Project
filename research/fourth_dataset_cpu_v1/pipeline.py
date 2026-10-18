"""Thread-checked offline encoding and two-thread online runtime."""
import json
from pathlib import Path
import time

import numpy as np

from research import baselines
from research.accuracy_v2 import pipeline as v2
from research.accuracy_v2.encoding import encode_sharded, legacy_key, validate_matrix
from research.accuracy_v2.storage import digest, read_checked, write_checked, sha, utc
from research.accuracy_v3.pipeline import CachedDenseSpace
from research.baselines import DenseVectorSpace
from research.config_frozen import FROZEN
from research.fourth_dataset_v1 import data
from research.fourth_dataset_v1.pipeline import Runtime as OriginalRuntime
from research.selection import CandidateFeatures
from research.selection_features import FeatureBuilder
from .protocol import CACHE, STUDY, require_frozen


def apply_threads(threads):
    import torch
    torch.set_num_threads(threads)
    if torch.get_num_threads() != threads or torch.get_num_interop_threads() != 1:
        raise ValueError("Effective Torch thread settings differ from the frozen CPU profile")


class ThreadCheckedModel:
    def __init__(self, model, threads):
        self.model, self.threads = model, threads

    def __getattr__(self, name):
        return getattr(self.model, name)

    def encode(self, *args, **kwargs):
        # DenseVectorSpace resets threads during construction. Restore and assert
        # the offline profile immediately before any actual encoding inference.
        apply_threads(self.threads)
        return self.model.encode(*args, **kwargs)


def progress_record(shards, imported_rows, threads, total_rows, protocol_sha256):
    identity = read_checked(Path(shards) / "identity.json")
    records, expected = [], 0
    for path in sorted(Path(shards).glob("[0-9]*.json")):
        meta = read_checked(path)
        if (meta["begin"] != expected or meta["identity"] != digest(identity) or
                meta["end"] != min(expected + identity["shard_rows"], total_rows) or path.name != f"{expected:09}.json"):
            raise ValueError("Encoding progress has invalid shard coverage/identity")
        records.append({"begin": meta["begin"], "end": meta["end"], "encode_ms": meta["encode_ms"],
                        "threads": 2 if meta["end"] <= imported_rows else threads,
                        "imported": meta["end"] <= imported_rows, "commit_sha256": sha(path),
                        "array_sha256": meta["sha256"]})
        expected = meta["end"]
    new = [r for r in records if not r["imported"]]
    rows = sum(r["end"] - r["begin"] for r in new)
    seconds = sum(r["encode_ms"] for r in new) / 1000
    rate = rows / seconds if seconds else None
    return {"updated_utc": utc(), "protocol_sha256": protocol_sha256,
            "completed_chunk_rows": expected, "total_chunk_rows": total_rows,
            "imported_rows": imported_rows, "imported_threads": 2, "encoding_threads": threads,
            "new_profile_rows": rows, "new_profile_encoding_seconds": seconds,
            "encoding_rows_per_second": rate,
            "remaining_encoding_hours": (total_rows - expected) / rate / 3600 if rate else None,
            "encoding_seconds": sum(r["encode_ms"] for r in records) / 1000,
            "profiles": records}


class EncodingSpace(DenseVectorSpace):
    def __init__(self, corpus, study=STUDY):
        self.study = Path(study)
        self.frozen = read_checked(self.study / "frozen.json")["identity"]
        self.imported = read_checked(self.study / "imported_shards.json")
        super().__init__(corpus, *v2.MODEL_PINS["dense"], cache_dir=CACHE)

    def _encode_chunks(self, texts, cache_dir):
        target = self.frozen["cpu_preparation"]["encoding_threads"]
        self.model = ThreadCheckedModel(self.model, target)
        apply_threads(target)
        key = legacy_key(self, texts)
        if key != self.imported["cache_key"] or len(texts) != self.imported["shard_identity"]["rows"]:
            raise ValueError("Reconstructed corpus chunks differ from the imported embedding identity")
        shards = Path(cache_dir) / f"{key}.shards"
        protocol_hash = sha(self.study / "frozen.json")
        def progress(event, begin):
            if event != "after_embedding_commit":
                return
            path = self.study / "encoding_progress.json"
            if path.exists():
                previous = read_checked(path)
                if previous["protocol_sha256"] != protocol_hash:
                    raise ValueError("Encoding progress belongs to a different frozen profile")
            record = progress_record(shards, self.imported["rows"], target, len(texts), protocol_hash)
            write_checked(path, record)
        return encode_sharded(self, texts, cache_dir, shard_rows=512, hook=progress)


def encode(study=STUDY):
    study = Path(study)
    ident = require_frozen(study)
    output = study / "encoding.json"
    if output.exists():
        verify_encoding(study, ident)
        return output
    corpus, _, _ = data.load()
    start = time.perf_counter()
    space = EncodingSpace(corpus, study)
    key = space.embedding_cache["key"]
    profile = progress_record(CACHE / f"{key}.shards", space.imported["rows"],
        ident["cpu_preparation"]["encoding_threads"], len(space.chunk_texts), sha(study / "frozen.json"))
    profile_path = study / "encoding_profiles.json"
    if profile_path.exists():
        previous = read_checked(profile_path)
        if {k: v for k, v in previous.items() if k != "updated_utc"} != {k: v for k, v in profile.items() if k != "updated_utc"}:
            raise ValueError("Existing completed encoding profile changed")
    else:
        write_checked(profile_path, profile)
    write_checked(output, {"protocol_sha256": sha(study / "frozen.json"), "completed_utc": utc(),
        "elapsed_this_session_seconds": time.perf_counter() - start, "cache": space.embedding_cache,
        "representation": space.meta, "matrix_sha256": sha(CACHE / f"{key}.npy"),
        "encoding_profiles_sha256": sha(study / "encoding_profiles.json"),
        "encoding_threads": ident["cpu_preparation"]["encoding_threads"], "online_threads": 2})
    return output


def verify_encoding(study=STUDY, ident=None):
    study = Path(study)
    ident = ident or require_frozen(study)
    record = read_checked(study / "encoding.json")
    if (record["protocol_sha256"] != sha(study / "frozen.json") or
            record["encoding_threads"] != ident["cpu_preparation"]["encoding_threads"] or record["online_threads"] != 2 or
            record["encoding_profiles_sha256"] != sha(study / "encoding_profiles.json")):
        raise ValueError("Completed encoding profile/protocol fingerprint mismatch")
    path = CACHE / f"{record['cache']['key']}.npy"
    meta = json.loads(path.with_suffix(".json").read_text())
    if sha(path) != record["matrix_sha256"] or meta["sha256"] != record["matrix_sha256"]:
        raise ValueError("Accelerated corpus embedding cache corrupt")
    matrix = np.load(path, mmap_mode="r", allow_pickle=False)
    validate_matrix(matrix, record["representation"]["n_chunks"], 384)
    if list(matrix.shape) != meta["shape"]:
        raise ValueError("Accelerated cache shape mismatch")
    return record


class Runtime(OriginalRuntime):
    def __init__(self, corpus):
        apply_threads(2)
        start = time.perf_counter()
        self.synthetic, self.full_controls = False, True
        self.vecs = CachedDenseSpace(corpus, *v2.MODEL_PINS["dense"], cache_dir=CACHE)
        self.l6, self.l2 = v2.Scorer("l6"), v2.Scorer("l2")
        self.builder, self.bm25 = FeatureBuilder(self.vecs, corpus), baselines.BM25(corpus)
        self.offline_ms = (time.perf_counter() - start) * 1000
        start = time.perf_counter()
        dummy = CandidateFeatures(("warmup",), [0.], np.ones((1, FROZEN["embedding_dimension"])),
                                  ("A short scientific passage.",))
        self.vecs.query_vec("a short query")
        self.l6.scores("a short query", dummy)
        self.l2.scores("a short query", dummy)
        apply_threads(2)
        self.warmup_ms = (time.perf_counter() - start) * 1000
