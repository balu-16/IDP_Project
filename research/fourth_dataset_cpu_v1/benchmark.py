"""Label-free CPU comparison with numerical agreement and fixed selection policy."""
import hashlib
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

import numpy as np

from research.accuracy_v2.encoding import atomic_array
from research.accuracy_v2.pipeline import MODEL_PINS, model_path
from research.accuracy_v2.storage import ROOT, digest, read_checked, sha, utc, write_checked
from research.baselines import DenseVectorSpace
from research.fourth_dataset_v1 import data
from .protocol import STUDY, PARENT, sources


def choose(records):
    baseline = records[2]["median_rows_per_second"]
    eligible = {t: r["median_rows_per_second"] for t, r in records.items()
                if t != 2 and r["median_rows_per_second"] / baseline >= 1.10}
    if not eligible:
        selected = 2
    else:
        fastest = max(eligible.values())
        selected = min(t for t, rate in eligible.items() if rate / fastest >= .95)
    return {"threads": selected, "measured_speedup": records[selected]["median_rows_per_second"] / baseline,
            "rule": "At least 10% faster than two threads; within 5% of fastest prefer fewer threads; otherwise two threads"}


def sample(study=STUDY):
    study = Path(study)
    path = study / "benchmark_sample.json"
    if path.exists():
        record = read_checked(path)
        if record["parent_protocol_sha256"] != sha(PARENT / "frozen.json"):
            raise ValueError("Benchmark sample belongs to a different parent protocol")
        return path
    corpus, _, _ = data.load()
    order = sorted(corpus, key=lambda d: (hashlib.sha256(("cpu-encoding-v1:" + d).encode()).hexdigest(), d))[:256]
    subset = {d: corpus[d] for d in order}
    class TextOnlySpace(DenseVectorSpace):
        def _encode_chunks(self, texts, cache_dir):
            # Temporary placeholders support inherited chunk construction only;
            # never persisted or used as embeddings/benchmark evidence.
            return np.zeros((len(texts), 384)), {"text_extraction_only": True}
    space = TextOnlySpace(subset, *MODEL_PINS["dense"])
    order = sorted(range(len(space.chunk_texts)), key=lambda i:
        (hashlib.sha256((space.chunk_parents[i] + ":" + str(i)).encode()).hexdigest(), i))[:256]
    if len(order) != 256:
        raise ValueError("Insufficient deterministic benchmark chunks")
    record = {"namespace": "cpu-encoding-v1", "parent_protocol_sha256": sha(PARENT / "frozen.json"),
              "texts": [space.chunk_texts[i] for i in order],
              "chunk_ids": [f"{space.chunk_parents[i]}::{i}" for i in order],
              "judgments_used": False, "chunk_policy": space.meta["chunk_policy"]}
    write_checked(path, record)
    return path


def worker(study, threads):
    import torch
    from sentence_transformers import SentenceTransformer
    if threads not in (2, 4, 6) or torch.get_num_threads() != threads or torch.get_num_interop_threads() != 1:
        raise ValueError("Benchmark effective CPU thread count differs from requested profile")
    study = Path(study)
    text_record = read_checked(study / "benchmark_sample.json")
    texts = text_record["texts"]
    model = SentenceTransformer(model_path("dense"), device="cpu", trust_remote_code=False)
    # Two warm-up batches; model/tokenizer/dtype/batch/normalization unchanged.
    model.encode(texts[:16], batch_size=8, normalize_embeddings=True, show_progress_bar=False)
    elapsed, values = [], None
    for _ in range(3):
        if torch.get_num_threads() != threads:
            raise ValueError("Benchmark CPU threads unexpectedly changed")
        start = time.perf_counter()
        current = np.asarray(model.encode(texts, batch_size=8, normalize_embeddings=True, show_progress_bar=False))
        elapsed.append(time.perf_counter() - start)
        if current.dtype != np.float32 or current.shape != (256, 384) or not np.isfinite(current).all():
            raise ValueError("Benchmark produced invalid embeddings or changed model precision")
        np.testing.assert_allclose(np.linalg.norm(current, axis=1), 1., rtol=1e-5, atol=1e-6)
        if values is not None:
            np.testing.assert_allclose(current, values, rtol=1e-5, atol=1e-6)
        values = current
    output = study / "benchmark" / f"threads_{threads}.npy"
    atomic_array(output, values)
    record = {"threads": threads, "actual_torch_threads": torch.get_num_threads(),
        "interop_threads": torch.get_num_interop_threads(), "model_max_seq_length": model.max_seq_length,
        "elapsed_seconds": elapsed, "median_rows_per_second": 256 / float(np.median(elapsed)),
        "batch_size": 8, "warmup_batches": 2, "repetitions": 3, "rows": 256,
        "dtype": str(values.dtype), "sample_sha256": sha(study / "benchmark_sample.json"),
        "matrix_sha256": sha(output), "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "thread_environment": {k: os.environ[k] for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")}}
    write_checked(output.with_suffix(".json"), record)
    return record


def benchmark(study=STUDY):
    study = Path(study)
    if (study / "frozen.json").exists():
        raise ValueError("Do not reselect CPU settings after freezing")
    sample(study)
    (study / "benchmark").mkdir(exist_ok=True)
    declaration = {"created_utc": utc(), "cpu_sources": sources(), "parent_protocol_sha256": sha(PARENT / "frozen.json"),
                   "sample_sha256": sha(study / "benchmark_sample.json"), "threads": [2, 4, 6],
                   "batch_size": 8, "warmup_batches": 2, "measured_repetitions": 3,
                   "selection_rule": choose({2: {"median_rows_per_second": 1}})["rule"]}
    write_checked(study / "benchmark_declaration.json", declaration)
    for relative, expected in sources().items():
        from research.accuracy_v2.storage import atomic_bytes
        target = study / "source_snapshot" / relative
        atomic_bytes(target, (ROOT / relative).read_bytes())
        if sha(target) != expected:
            raise ValueError("CPU source changed during benchmark declaration")
    records = {}
    for threads in (2, 4, 6):
        command = [sys.executable, "-u", "-m", "research.fourth_dataset_cpu_v1", "benchmark-worker",
                   "--study", str(study), "--threads", str(threads)]
        log = study / "benchmark" / f"threads_{threads}.log"
        with log.open("w") as handle:
            subprocess.run(command, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT, check=True, timeout=180)
        path = study / "benchmark" / f"threads_{threads}.json"
        records[threads] = read_checked(path)
        print(f"{threads} threads: {records[threads]['median_rows_per_second']:.2f} chunks/second", flush=True)
    reference = np.load(study / "benchmark/threads_2.npy", allow_pickle=False)
    agreement = {}
    for threads in (2, 4, 6):
        path = study / "benchmark" / f"threads_{threads}.npy"
        values = np.load(path, allow_pickle=False)
        if sha(path) != records[threads]["matrix_sha256"]:
            raise ValueError("Benchmark output checksum mismatch")
        np.testing.assert_allclose(values, reference, rtol=1e-5, atol=1e-6)
        agreement[str(threads)] = {"passed": True, "maximum_absolute_difference": float(np.max(np.abs(values - reference)))}
    record = {"created_utc": utc(), "cpu_sources": sources(), "declaration_sha256": sha(study / "benchmark_declaration.json"),
              "sample_sha256": sha(study / "benchmark_sample.json"), "profiles": {str(k): v for k, v in records.items()},
              "selection": choose(records), "embedding_agreement": agreement, "rtol": 1e-5, "atol": 1e-6,
              "judgments_used": False, "rankings_generated": False}
    if record["cpu_sources"] != declaration["cpu_sources"]:
        raise ValueError("CPU adapter sources changed during benchmarking")
    write_checked(study / "cpu_benchmark.json", record)
    return study / "cpu_benchmark.json"
