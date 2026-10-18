"""Input integrity, cache-only preflight, and bounded regression verification."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import unittest

import numpy as np

from research import datasets
from research.selection import CandidateFeatures
from research.accuracy_v2.checks import independent_metrics
from research.accuracy_v2.core import ScoredFeatures, take
from research.accuracy_v2.encoding import validate_matrix
from research.accuracy_v2.experiment import require_preflight as require_base_preflight
from research.accuracy_v2.pipeline import Scorer, model_path
from .core import select
from .experiment import confirmation_queries
from .storage import ROOT, environment_identity, extension_identity, read_checked, sha, write_checked

PREFLIGHT = ROOT / "build/accuracy_v3/preflight.json"
SMOKE = ROOT / "build/accuracy_v3/smoke.json"


def preflight(output=PREFLIGHT):
    from transformers import AutoTokenizer
    records = {}
    dense = AutoTokenizer.from_pretrained(model_path("dense"), local_files_only=True)
    l6 = AutoTokenizer.from_pretrained(model_path("l6"), local_files_only=True)
    if dense.get_vocab() != l6.get_vocab():
        raise ValueError("Dense/L6 tokenizer vocabularies differ")
    old = json.loads((ROOT / "build/accuracy_v2/preflight.json").read_text())
    required = 2_000_000_000
    for name in ("scifact", "nfcorpus", "fiqa"):
        require_base_preflight(name, True)
        queries, rel, sources = confirmation_queries(name)
        corpus = datasets._load_corpus(datasets.DATA_ROOT / name)
        if any(doc not in corpus for rows in rel.values() for doc in rows):
            raise ValueError("Fresh training judgments reference missing documents")
        if any(not any(grade > 0 for grade in rows.values()) for rows in rel.values()):
            raise ValueError("Confirmation query has no positive judgment")
        dense_lengths = [len(v) for v in dense(list(queries.values()), add_special_tokens=False, truncation=False, padding=False)["input_ids"]]
        l6_lengths = [len(v) for v in l6(list(queries.values()), add_special_tokens=False, truncation=False, padding=False)["input_ids"]]
        if max(dense_lengths) > 190 or max(l6_lengths) + 190 + l6.num_special_tokens_to_add(pair=True) > 512:
            raise ValueError(f"Fresh {name} query exceeds the pinned model token budget")
        setup = read_checked(ROOT / f"research/runs/accuracy_v2_{name}_test/setup.json")[-1]
        key = setup["corpus_cache"]["key"]
        path = ROOT / f"research/cache/dense/{key}.npy"
        meta_path = path.with_suffix(".json")
        if not path.is_file() or not meta_path.is_file():
            raise ValueError(f"Required {name} corpus cache is missing; no encoding authorized in this batch")
        meta = json.loads(meta_path.read_text())
        if sha(path) != meta["sha256"]:
            raise ValueError(f"Required {name} cache is corrupt")
        matrix = np.load(path, mmap_mode="r", allow_pickle=False)
        validate_matrix(matrix, old["datasets"][name]["tokenization"]["chunks"], 384)
        required += (100 + old["datasets"][name]["test_queries"]) * 4_000_000
        records[name] = {"confirmation_ids": sorted(queries), "confirmation_count": len(queries),
                         "exclusion_sources": sources, "max_confirmation_query_tokens": max(dense_lengths),
                         "cache_key": key, "cache_sha256": meta["sha256"],
                         "input_freeze": old["datasets"][name]["freeze"],
                         "original_tokenization_audit": old["datasets"][name]["tokenization"]}
        print(f"Preflight {name}: 100 fresh training queries, token limits, pinned inputs, and existing cache verified", flush=True)
    available = shutil.disk_usage(ROOT).free
    if available < required:
        raise ValueError(f"Insufficient storage: need {required}, available {available}")
    write_checked(output, {"passed": True, "environment": environment_identity(), "extension": extension_identity(),
                          "datasets": records, "free_bytes": available, "required_bytes": required,
                          "model_inference_performed": False, "corpus_encoding_performed": False})
    return Path(output)


def require_preflight(name):
    saved = read_checked(PREFLIGHT)
    if (not saved["passed"] or saved["environment"] != environment_identity() or saved["extension"] != extension_identity()):
        raise ValueError("V3 preflight is missing, stale, or incompatible")
    require_base_preflight(name, True)
    queries, _, sources = confirmation_queries(name)
    record = saved["datasets"][name]
    if record["confirmation_ids"] != sorted(queries) or record["exclusion_sources"] != sources:
        raise ValueError("Confirmation exclusions or deterministic query selection changed")


def smoke(output=SMOKE):
    suite = unittest.defaultTestLoader.loadTestsFromName("research.accuracy_v3.test_accuracy")
    tested = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(suite)
    if not tested.wasSuccessful():
        raise ValueError("V3 regression/recovery tests failed")
    saved = ROOT / "build/accuracy_v3_feasibility"
    audit = json.loads((saved / "dominance_canonical_audit.json").read_text())
    requests, checked = [], 0
    for name, ds in audit["datasets"].items():
        for sample, result in ds["samples"].items():
            rows = json.loads((saved / f"dominance_canonical_{name}_{sample}_features.json").read_text())
            expected = {(r["qid"], r["seed"]): r for r in result["details"]}
            for row in rows:
                import hashlib
                file = hashlib.sha256(row["qid"].encode()).hexdigest() + ".json"
                original = read_checked(ROOT / f"research/runs/accuracy_v2_{name}_dev/features" / file)["data"]["0.0"]["full"]
                full = CandidateFeatures.from_dict(original)
                indices = [full.ids.index(did) for did in row["ids"]]
                features = ScoredFeatures(take(full, indices), row["logits"])
                for seed, baseline in enumerate(row["baseline"]):
                    actual = select(features, baseline, seed=seed)
                    want = expected[(row["qid"], seed)]["methods"]["gas|delta=0|gap=0"]
                    if actual.ranked_ids != want["ranked_ids"] or abs(actual.redundancy - want["metrics"][2]) > 1e-12:
                        raise ArithmeticError(f"Prototype replay mismatch: {name}/{row['qid']}/{seed}")
                    requests.append((actual.ranked_ids, row["qrels"]))
                    checked += 1
        print(f"Smoke {name}: complete 128-query/five-seed prototype replay passed", flush=True)
    scorer = Scorer("l6")
    features = CandidateFeatures(("smoke1", "smoke2"), [0., 0.], np.ones((2, 384)),
                                ("Scientific evidence concerns a treatment.", "A financial account contains savings."))
    scores, _ = scorer.scores("What does the evidence support?", features)
    if len(scores) != 2 or not np.isfinite(scores).all():
        raise ValueError("Local L6 smoke inference failed")
    write_checked(output, {"passed": True, "environment": environment_identity(), "extension": extension_identity(),
                          "unit_tests": tested.testsRun, "prototype_seed_requests": checked,
                          "independent_metrics": independent_metrics(requests), "local_l6_pairs": len(scores),
                          "prototype_artifact_sha256": sha(saved / "dominance_canonical_audit.json")})
    return Path(output)


def require_smoke():
    saved = read_checked(SMOKE)
    if not saved["passed"] or saved["environment"] != environment_identity() or saved["extension"] != extension_identity():
        raise ValueError("V3 verification is missing, stale, or failed")
