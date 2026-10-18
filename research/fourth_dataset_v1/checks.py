"""No-ranking preflight and artificial-data smoke verification."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from research.accuracy_v2.checks import inspect_chunks
from research.accuracy_v2.pipeline import model_identity, model_path
from research.accuracy_v2.storage import ROOT, read_checked, write_checked, sha
from research.selection_experiment import hardware_record
from . import data
from .protocol import STUDY, CACHE, code_identity


def memory_available():
    values = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    return int(values["MemAvailable"].split()[0]) * 1024


def preflight(study=STUDY):
    from transformers import AutoTokenizer
    study = Path(study)
    if (study / "frozen.json").exists():
        raise ValueError("Protocol already frozen; use its recorded preflight instead of replacing evidence")
    start = time.perf_counter()
    inventory = data.inventory()
    corpus, queries, judgments = data.load()
    models = model_identity(True)
    tokenizers = {label: AutoTokenizer.from_pretrained(model_path(label), local_files_only=True, trust_remote_code=False)
                  for label in ("dense", "l6", "l2")}
    print("Checking all corpus chunks and all query token lengths; no model inference or rankings", flush=True)
    chunks = inspect_chunks(corpus, tokenizers["dense"])
    query_lengths = {}
    for label, tokenizer in tokenizers.items():
        query_lengths[label] = max(len(ids) for ids in tokenizer(list(queries.values()), add_special_tokens=False,
                                    truncation=False, padding=False)["input_ids"])
    if query_lengths["dense"] > 190:
        raise ValueError("Dense query token budget exceeded")
    if any(tokenizers["dense"].get_vocab() != tokenizers[label].get_vocab() for label in ("l6", "l2")):
        raise ValueError("Document token vocabulary differs across models")
    bound = max(query_lengths.values()) + chunks["max_chunk_content_tokens"] + 3
    if bound > 512:
        raise ValueError("Cross-encoder query/passage token budget exceeded")
    # Durable float64 shards plus assembled matrix, checkpoints, and headroom.
    storage = chunks["chunks"] * 384 * 8 * 2 + 750_000_000
    free = shutil.disk_usage(ROOT).free
    available = memory_available()
    # Model weights, tokenizer/chunk strings, lexical dictionaries, matrix working set.
    memory_estimate = 1_000_000_000 + (data.DATA / "corpus.jsonl").stat().st_size * 6 + chunks["chunks"] * 384 * 8
    if free < storage:
        raise ValueError(f"Insufficient storage: estimated {storage}, available {free}")
    if available < memory_estimate:
        raise ValueError(f"Insufficient available RAM: estimated {memory_estimate}, available {available}")
    if CACHE.exists() and any(CACHE.iterdir()):
        raise ValueError("Fresh preflight requires an empty fourth-dataset cache; use frozen recovery if already started")
    executable = ROOT / "build/tools/trec_eval"
    if not executable.is_file():
        raise ValueError("Independent trec_eval is missing")
    record = {"passed": True, "code": code_identity(), "data": inventory, "models": models,
        "hardware": hardware_record(), "tokenization": chunks, "maximum_query_tokens": query_lengths,
        "maximum_pair_tokens": bound, "available_storage_bytes": free, "estimated_storage_bytes": storage,
        "available_memory_bytes": available, "estimated_memory_bytes": memory_estimate,
        "trec_eval_sha256": sha(executable), "elapsed_seconds": time.perf_counter() - start,
        "rankings_generated": False, "model_inference_performed": False,
        "judgment_policy": "Preserve grades -1,0,1,2; -1 is unjudged; judged means grade>=0; relevance means grade>0; linear graded nDCG",
        "judgment_format_reference": "https://github.com/usnistgov/trec_eval/blob/main/formats.c"}
    write_checked(study / "preflight.json", record)
    return study / "preflight.json"


def smoke(study=STUDY):
    study = Path(study)
    if (study / "frozen.json").exists():
        raise ValueError("Protocol already frozen; do not replace its smoke evidence")
    study.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "unittest", "research.fourth_dataset_v1.test_fourth",
               "research.accuracy_v2.test_accuracy", "research.accuracy_v3.test_accuracy", "-v"]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, env=os.environ.copy())
    from research.accuracy_v2.storage import atomic_bytes
    atomic_bytes(study / "smoke_tests.log", (result.stdout + result.stderr).encode())
    if result.returncode:
        raise ValueError(f"Smoke tests failed; see {study / 'smoke_tests.log'}")
    # No benchmark query or corpus passage is scored by this artificial inference check.
    import numpy as np
    from research.accuracy_v2.pipeline import Scorer
    from research.selection import CandidateFeatures
    passage = CandidateFeatures(("artificial",), [.5], np.ones((1, 384)), ("A short scientific passage.",))
    scores = {}
    for label in ("l6", "l2"):
        values, elapsed = Scorer(label).scores("a short query", passage)
        scores[label] = {"finite_logit": float(values[0]), "milliseconds": elapsed}
    record = {"passed": True, "code": code_identity(), "command": command,
              "test_log_sha256": sha(study / "smoke_tests.log"), "artificial_inference": scores,
              "benchmark_queries_run": 0}
    write_checked(study / "smoke.json", record)
    return study / "smoke.json"
