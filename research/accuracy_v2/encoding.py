"""Existing cache compatibility plus durable shards for new corpus encodings."""
from __future__ import annotations

import hashlib
import importlib.metadata
import inspect
import json
import os
from pathlib import Path
import tempfile
import time

import numpy as np

from research.baselines import DenseVectorSpace
from .storage import digest, exclusive, read_checked, sha, sync_directory, write_checked


def legacy_key(space, texts):
    versions = {p: importlib.metadata.version(p) for p in ("numpy", "torch", "transformers", "sentence-transformers")}
    result = hashlib.sha256(json.dumps([space.model_name, space.revision, versions,
        getattr(space.model, "max_seq_length", None), space.CONTENT_TOKENS, space.STEP,
        hashlib.sha256(inspect.getsource(DenseVectorSpace).encode()).hexdigest()], sort_keys=True).encode())
    for text in texts:
        result.update(json.dumps(text, ensure_ascii=False).encode())
        result.update(b"\n")
    return result.hexdigest()


def validate_matrix(matrix, rows, dimension=None):
    if (matrix.ndim != 2 or matrix.shape[0] != rows or matrix.shape[1] < 1
            or (dimension is not None and matrix.shape[1] != dimension)
            or not np.isfinite(matrix).all() or np.any(np.linalg.norm(matrix, axis=1) <= 1e-12)):
        raise ValueError("Invalid corpus embedding cache shape or values")


def atomic_array(path, matrix):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".pending-", delete=False) as handle:
            temporary = Path(handle.name)
            np.save(handle, matrix, allow_pickle=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def encode_sharded(space, texts, cache_dir, shard_rows=512, hook=None):
    if not texts or shard_rows < 1:
        raise ValueError("Encoding requires nonempty inputs and a positive shard size")
    start = time.perf_counter()
    directory = Path(cache_dir)
    directory.mkdir(parents=True, exist_ok=True)
    key = legacy_key(space, texts)
    matrix_path, metadata_path = directory / f"{key}.npy", directory / f"{key}.json"
    with exclusive(directory / f"{key}.lock"):
        if metadata_path.exists():
            meta = json.loads(metadata_path.read_text())
            if not matrix_path.exists() or sha(matrix_path) != meta["sha256"]:
                raise ValueError("Corpus embedding cache checksum mismatch")
            matrix = np.load(matrix_path, mmap_mode="r", allow_pickle=False)
            validate_matrix(matrix, len(texts))
            if list(matrix.shape) != meta["shape"]:
                raise ValueError("Corpus embedding cache metadata shape mismatch")
            return matrix, {"enabled": True, "hit": True, "key": key,
                            "cold_model_encode_ms": meta["cold_model_encode_ms"],
                            "restore_ms": (time.perf_counter() - start) * 1000}
        shards = directory / f"{key}.shards"
        shards.mkdir(exist_ok=True)
        identity = {"legacy_key": key, "shard_rows": shard_rows, "rows": len(texts),
                    "implementation_sha256": sha(Path(__file__)), "dtype": "float64"}
        identity_path = shards / "identity.json"
        if identity_path.exists():
            if read_checked(identity_path) != identity:
                raise ValueError("Embedding shard identity mismatch; restore recorded encoding code/options")
        else:
            write_checked(identity_path, identity)
        shape, encoding_ms, reused = None, 0.0, 0
        for begin in range(0, len(texts), shard_rows):
            end = min(begin + shard_rows, len(texts))
            data_path, commit_path = shards / f"{begin:09}.npy", shards / f"{begin:09}.json"
            if commit_path.exists():
                meta = read_checked(commit_path)
                if (meta["identity"] != digest(identity) or meta["begin"] != begin or meta["end"] != end
                        or not data_path.exists() or sha(data_path) != meta["sha256"]):
                    raise ValueError(f"Corrupt embedding shard {begin}")
                matrix = np.load(data_path, mmap_mode="r", allow_pickle=False)
                reused += end - begin
            else:
                before = time.perf_counter()
                matrix = np.asarray(space.model.encode(texts[begin:end], batch_size=8,
                    normalize_embeddings=True, show_progress_bar=False), dtype=float)
                elapsed = (time.perf_counter() - before) * 1000
                validate_matrix(matrix, end - begin, shape[1] if shape else None)
                if hook:
                    hook("before_embedding_commit", begin)
                atomic_array(data_path, matrix)
                meta = {"identity": digest(identity), "begin": begin, "end": end, "shape": list(matrix.shape),
                        "sha256": sha(data_path), "encode_ms": elapsed}
                write_checked(commit_path, meta)
                if hook:
                    hook("after_embedding_commit", begin)
                print(f"Encoding checkpoint: {end}/{len(texts)} chunks", flush=True)
            validate_matrix(matrix, end - begin, shape[1] if shape else None)
            if list(matrix.shape) != meta["shape"]:
                raise ValueError("Embedding shard shape mismatch")
            shape = (len(texts), matrix.shape[1])
            encoding_ms += meta["encode_ms"]
        # A stopped assembly is retried from shards, never by re-encoding.
        temporary = shards / ".pending-assembly.npy"
        assembled = np.lib.format.open_memmap(temporary, mode="w+", dtype=float, shape=shape)
        for begin in range(0, len(texts), shard_rows):
            part = np.load(shards / f"{begin:09}.npy", mmap_mode="r", allow_pickle=False)
            assembled[begin:begin + len(part)] = part
        assembled.flush()
        del assembled
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, matrix_path)
        sync_directory(directory)
        # Match the old whole-cache metadata format exactly for compatibility.
        from .storage import atomic_bytes
        atomic_bytes(metadata_path, json.dumps({"sha256": sha(matrix_path), "shape": list(shape),
                     "cold_model_encode_ms": encoding_ms}).encode())
        matrix = np.load(matrix_path, mmap_mode="r", allow_pickle=False)
        return matrix, {"enabled": True, "hit": False, "key": key, "reused_shard_rows": reused,
                        "cold_model_encode_ms": encoding_ms, "restore_ms": (time.perf_counter() - start) * 1000}


class ResumableDenseSpace(DenseVectorSpace):
    def _encode_chunks(self, texts, cache_dir):
        if cache_dir is None:
            raise ValueError("Accuracy v2 requires a durable corpus cache")
        return encode_sharded(self, texts, cache_dir)
