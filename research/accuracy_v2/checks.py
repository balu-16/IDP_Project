"""No-evaluation preflight and bounded development-feature smoke checks."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import zipfile

import numpy as np

from research import datasets
from research.selection import CandidateFeatures, selection_metrics
from .core import Config, SEEDS, ScoredFeatures, hybrid_scores, select, shortlist
from .pipeline import Scorer, model_identity, model_path
from .storage import ROOT, atomic_bytes, environment_identity, sha

ARCHIVE_MD5 = {"scifact": "5f7d1de60b170fc8027bb7898e2efca1", "nfcorpus": "a89dba18a62ef92f7d323ec890a0d38d", "fiqa": "17918ed23cd04fb15047f73e6c3bd9d9"}
SAVED_DEVELOPMENT = ROOT / "build/accuracy_smalltest_20261017T091602Z"


def inspect_chunks(corpus, tokenizer):
    """Mirror the preserved dense input construction without loading/encoding a model."""
    backend = getattr(tokenizer, "backend_tokenizer", None)
    if backend is None:
        raise ValueError("Pinned fast tokenizer required for preflight")
    backend.no_padding()
    backend.no_truncation()
    count, empty, largest, total, first_full = 0, 0, 0, 0, None
    for text in corpus.values():
        offsets = backend.encode(text, add_special_tokens=False).offsets
        if first_full is None:
            actual = tokenizer.encode(text, add_special_tokens=False, truncation=False, padding=False)
            first_full = len(offsets) == len(actual)
            if not first_full:
                raise ValueError("First-document tokenizer offsets are truncated or padded")
        if not offsets:
            count += 1
            empty += 1
            continue
        for start in range(0, len(offsets), 158):
            end = min(start + 190, len(offsets))
            while end > start:
                candidate = text[offsets[start][0]:offsets[end - 1][1]]
                length = len(tokenizer.encode(candidate, add_special_tokens=False, truncation=False, padding=False))
                if length <= 190:
                    break
                end -= 1
            if end <= start:
                raise ValueError("Cannot construct a valid document chunk")
            count += 1
            largest = max(largest, length)
            total += length
    return {"chunks": count, "empty_documents": empty, "max_chunk_content_tokens": largest,
            "mean_chunk_content_tokens": total / count, "first_document_full_offsets": first_full}


def preflight(names, output=None):
    import hashlib
    from transformers import AutoTokenizer
    start = time.perf_counter()
    models = model_identity(True)
    tokenizer = AutoTokenizer.from_pretrained(model_path("dense"), local_files_only=True, trust_remote_code=False)
    ce_tokenizer = AutoTokenizer.from_pretrained(model_path("l6"), local_files_only=True, trust_remote_code=False)
    records = {}
    available = shutil.disk_usage(ROOT).free
    required = 0
    for name in names:
        print(f"Preflight {name}: files, splits and tokenization only; no model inference", flush=True)
        corpus, dev, dev_rel, test, test_rel = datasets.load_splits(name)
        freeze = datasets.freeze_record(name)
        archive = ROOT / "research/downloads" / f"{name}.zip"
        md5 = hashlib.md5()
        with archive.open("rb") as handle:
            for part in iter(lambda: handle.read(1 << 20), b""):
                md5.update(part)
        if md5.hexdigest() != ARCHIVE_MD5[name]:
            raise ValueError(f"Official archive checksum mismatch: {name}")
        with zipfile.ZipFile(archive) as zipped:
            for relative, expected in freeze["files"].items():
                if hashlib.sha256(zipped.read(f"{name}/{relative}")).hexdigest() != expected:
                    raise ValueError(f"Local file differs from official archive: {name}/{relative}")
        chunks = inspect_chunks(corpus, tokenizer)
        queries = list(dev.values()) + list(test.values())
        lengths = [len(row) for row in tokenizer(queries, add_special_tokens=False, truncation=False, padding=False)["input_ids"]]
        ce_lengths = [len(row) for row in ce_tokenizer(queries, add_special_tokens=False, truncation=False, padding=False)["input_ids"]]
        if max(lengths) > 190:
            raise ValueError(f"{name}: query exceeds dense input limit")
        # Both pinned MiniLM tokenizers must use the same document WordPiece vocabulary.
        if tokenizer.get_vocab() != ce_tokenizer.get_vocab():
            raise ValueError("Cross-encoder tokenizer differs: explicit passage-length preflight is required")
        pair_bound = max(ce_lengths) + chunks["max_chunk_content_tokens"] + ce_tokenizer.num_special_tokens_to_add(pair=True)
        if pair_bound > 512:
            raise ValueError(f"{name}: cross-encoder input bound exceeds 512")
        caches = []
        for path in sorted((ROOT / "research/cache/dense").glob("*.json")):
            data = json.loads(path.read_text())
            matrix_path = path.with_suffix(".npy")
            if not matrix_path.exists() or sha(matrix_path) != data["sha256"]:
                raise ValueError(f"Corrupt corpus cache: {path}")
            matrix = np.load(matrix_path, mmap_mode="r", allow_pickle=False)
            from .encoding import validate_matrix
            validate_matrix(matrix, data["shape"][0], 384)
            if list(matrix.shape) != data["shape"]:
                raise ValueError(f"Cache shape mismatch: {path}")
            caches.append({"key": path.stem, "rows": len(matrix), "sha256": data["sha256"],
                           "rows_match_dataset": len(matrix) == chunks["chunks"]})
        # Two float64 copies (durable shards + assembled matrix), feature/result
        # checkpoints and conservative headroom; this is a capacity check, not a runtime forecast.
        storage = chunks["chunks"] * 384 * 8 * 2 + (len(dev) + len(test)) * 2_000_000 + 256_000_000
        required += storage
        records[name] = {"parents": len(corpus), "development_queries": len(dev), "test_queries": len(test),
                         "maximum_query_content_tokens": max(lengths), "cross_encoder_pair_token_bound": pair_bound,
                         "freeze": freeze, "tokenization": chunks, "validated_caches": caches,
                         "estimated_additional_storage_bytes": storage}
    if available < required:
        raise ValueError(f"Insufficient disk space: need {required} bytes, available {available}")
    result = {"schema": "accuracy-v2-preflight", "passed": True, "datasets": records, "models": models,
              "environment": environment_identity(),
              "free_disk_bytes": available, "estimated_additional_storage_bytes": required,
              "elapsed_seconds": time.perf_counter() - start, "model_inference_performed": False,
              "benchmark_rankings_generated": False}
    if output:
        atomic_bytes(output, json.dumps(result, indent=2, allow_nan=False).encode() + b"\n")
    return result


def independent_metrics(requests, executable=None):
    """Check every request's nDCG@5 and Recall@8 against official trec_eval."""
    executable = Path(executable or ROOT / "build/tools/trec_eval")
    if not executable.is_file():
        raise ValueError(f"Official trec_eval is unavailable: {executable}")
    checks, maximum_error = 0, 0.0
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        qrel_lines, run_lines, expected = [], [], {}
        for i, (ranked, rel) in enumerate(requests):
            qid = f"R{i}"
            qrel_lines += [f"{qid} 0 {did} {grade}\n" for did, grade in rel.items() if grade > 0]
            run_lines += [f"{qid} Q0 {did} {j} {len(ranked) - j + 1} accuracy_v2\n" for j, did in enumerate(ranked, 1)]
            from research.metrics import ndcg_at, recall_at
            positive = {d: g for d, g in rel.items() if g > 0}
            expected[qid] = {"ndcg_cut_5": ndcg_at(ranked, positive, 5), "recall_8": recall_at(ranked, positive, 8)}
        (base / "qrels").write_text("".join(qrel_lines))
        (base / "run").write_text("".join(run_lines))
        result = subprocess.run([str(executable), "-q", "-m", "ndcg_cut.5", "-m", "recall.8", str(base / "qrels"), str(base / "run")],
                                text=True, capture_output=True, check=True)
        seen = set()
        for line in result.stdout.splitlines():
            metric, qid, value = line.split()
            if qid == "all":
                continue
            error = abs(float(value) - expected[qid][metric])
            if error > 0.000051:
                raise ArithmeticError(f"trec_eval disagreement for {qid}/{metric}: {error}")
            maximum_error = max(maximum_error, error)
            seen.add((qid, metric))
            checks += 1
        if len(seen) != len(expected) * 2:
            raise ValueError("Incomplete official metric cross-check coverage")
    return {"checks": checks, "maximum_rounding_error": maximum_error, "tolerance": 0.000051,
            "executable_sha256": sha(executable)}


def smoke(output=None, saved=SAVED_DEVELOPMENT, local_inference=True):
    saved = Path(saved)
    original = json.loads((saved / "features.json").read_text())
    prefilter = json.loads((saved / "candidate_prefilter_results.json").read_text())
    if original["test_qrels_read"] or prefilter["test_qrels_read"]:
        raise ValueError("Smoke features must be development-only")
    by_id = {row["qid"]: row for row in original["records"]}
    zero, shortlist_checks, score_checks, requests = 0, 0, 0, []
    ndcg, recall = [], []
    for row in prefilter["per_query"]:
        source = by_id[row["qid"]]
        ids = source["shortlist_ids"]
        def aligned(name):
            values = source[name]
            return np.array([values[d] for d in ids] if isinstance(values, dict) else values)
        cosine, lexical = aligned("shortlist_dense_scores"), aligned("shortlist_lexical_scores")
        indices = shortlist(ids, cosine, lexical)
        if [ids[i] for i in indices] != row["candidate_ids"]:
            raise AssertionError("Hybrid shortlist differs from saved experiment")
        np.testing.assert_array_equal(hybrid_scores(cosine, lexical)[indices], row["hybrid_scores"])
        shortlist_checks += 1
        features = ScoredFeatures(CandidateFeatures.from_dict(row["features"]), row["raw_l6_logits"])
        baseline = select(features, "l6_only")
        baseline_metrics = selection_metrics(baseline, source["qrels"])
        ndcg.append(baseline_metrics["nDCG@5"])
        recall.append(baseline_metrics["Recall@8"])
        for penalty in (0.0, 0.025, 0.05):
            cfg = Config(diversity_weight=penalty)
            for seed in SEEDS:
                result = select(features, config=cfg, seed=seed)
                if penalty == 0:
                    assert result.ranked_ids == baseline.ranked_ids
                    zero += 1
                old_key = f"l6_rep_gas_b8_lam{penalty:g}"
                expected = row["metrics"][old_key]
                actual = selection_metrics(result, source["qrels"])
                for metric in ("nDCG@5", "Recall@8"):
                    if abs(actual[metric] - expected[metric]) > 1e-10:
                        raise AssertionError(f"Saved metric mismatch: {row['qid']}/{old_key}/{metric}")
                    score_checks += 1
                requests.append((result.ranked_ids, source["qrels"]))
    result = {"passed": True, "role": "saved development replay; not a full evaluation",
              "environment": environment_identity(),
              "input_sha256": {name: sha(saved / name) for name in ("features.json", "candidate_prefilter_results.json")},
              "shortlist_checks": shortlist_checks, "saved_metric_checks": score_checks,
              "zero_penalty_checks": zero, "mean_nDCG@5": float(np.mean(ndcg)), "mean_Recall@8": float(np.mean(recall)),
              "official_metrics": independent_metrics(requests), "full_dataset_evaluations_started": False}
    if local_inference:
        first = prefilter["per_query"][0]
        features = CandidateFeatures.from_dict(first["features"])
        from .core import take
        logits, elapsed = Scorer("l6").scores(by_id[first["qid"]]["query"], take(features, [0, 1]))
        np.testing.assert_allclose(logits, first["raw_l6_logits"][:2], rtol=0, atol=2e-5)
        result["local_l6_inference"] = {"pairs": 2, "passed": True, "inference_ms": elapsed}
    if output:
        atomic_bytes(output, json.dumps(result, indent=2, allow_nan=False).encode() + b"\n")
    return result
