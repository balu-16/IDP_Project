"""Synthetic correctness, objective independence, and interruption recovery."""
from dataclasses import replace
import contextlib
import io
import itertools
import subprocess
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from research import datasets
from research.selection import CandidateFeatures, grover_step
from research.accuracy_v2.core import ScoredFeatures
from . import core, experiment, pipeline
from .core import Config, select
from .storage import Store, environment_identity, extension_identity, read_checked, sha, write_checked


def fixture(n=15, constant=False):
    rng = np.random.default_rng(91)
    f = CandidateFeatures(tuple(f"D{i:02}" for i in range(n)), np.linspace(.9, -.1, n),
                          rng.normal(size=(n, 9)), tuple(f"passage {i}" for i in range(n)))
    return ScoredFeatures(f, np.full(n, -4.) if constant else np.linspace(5, -9, n))


def baseline(features):
    ids = features.candidates.ids
    return list(ids[4:12]) if len(ids) >= 12 else list(ids[:8])


class SelectionTests(unittest.TestCase):
    def test_independent_exhaustive_objectives(self):
        f = fixture()
        old = baseline(f)
        ids, z = f.candidates.ids, f.l6_logits
        ix = {d: i for i, d in enumerate(ids)}
        tail0 = sorted(z[ix[d]] for d in old[5:])
        red, energy = [], []
        baseR = sum(max(0., min(1., float(f.candidates.embeddings[ix[a]] @ f.candidates.embeddings[ix[b]])))
                    for a, b in itertools.combinations(old, 2)) / 28
        for tail in itertools.combinations([d for d in ids if d not in old[:5]], 3):
            if any(a < b - 1e-12 for a, b in zip(sorted(z[ix[d]] for d in tail), tail0)):
                continue
            rank = old[:5] + list(tail)
            pairs = [max(0., min(1., float(f.candidates.embeddings[ix[a]] @ f.candidates.embeddings[ix[b]])))
                     for a, b in itertools.combinations(rank, 2)]
            if np.mean(pairs) <= baseR + 1e-12:
                red.append(float(np.mean(pairs)))
                energy.append(sum(round(65535 * v) for v in pairs))
        self.assertAlmostEqual(select(f, old, "exact_float_v3").redundancy, min(red), places=12)
        self.assertEqual(select(f, old, "exact_quantized_v3").energy, min(energy))

    def test_seeds_prefix_dominance_and_improvements(self):
        f = fixture()
        old = baseline(f)
        z = dict(zip(f.candidates.ids, f.l6_logits))
        for seed in range(5):
            a, b = select(f, old, seed=seed), select(f, old, seed=seed)
            self.assertEqual(a.ranked_ids, b.ranked_ids)
            self.assertEqual(a.trace, b.trace)
            self.assertEqual(a.ranked_ids[:5], old[:5])
            self.assertEqual(len(set(a.ranked_ids)), 8)
            self.assertTrue(all(x >= y - 1e-12 for x, y in zip(sorted(z[d] for d in a.ranked_ids[5:]), sorted(z[d] for d in old[5:]))))
            self.assertLessEqual(a.counts["phase_oracle_calls"], 64)
            for update in a.trace:
                self.assertAlmostEqual(update["state_norm"], 1.)
                if update["accepted"]:
                    self.assertLess(update["energy_after"], update["energy_before"])
                    self.assertLess(update["redundancy_after"], update["redundancy_before"] - 1e-12)

    def test_constant_negative_tied_and_undersized(self):
        for n in (0, 1, 4, 5, 6, 8, 15):
            f = fixture(n, constant=True)
            old = baseline(f)
            for method in core.METHODS:
                result = select(f, old, method)
                self.assertEqual(len(result.ranked_ids), min(8, n))
                self.assertEqual(len(set(result.ranked_ids)), min(8, n))
                if method != "l6_union":
                    self.assertEqual(result.ranked_ids[:5], old[:5])

    def test_budget_and_invalid_inputs(self):
        f, cfg = fixture(), Config()
        old = baseline(f)
        for options in ({"max_oracle_calls": 0}, {"max_trials": 0}, {"time_limit_seconds": 0}):
            result = select(f, old, config=replace(cfg, **options))
            self.assertEqual(result.ranked_ids, old)
            self.assertEqual(result.counts["phase_oracle_calls"], 0)
        for value in (-1, True, float("nan")):
            with self.assertRaises(ValueError):
                Config(max_oracle_calls=value)
        with self.assertRaises(ValueError):
            select(f, old + [old[0]])
        with self.assertRaises(ValueError):
            select(f, ["missing"] * 8)
        with self.assertRaises(ValueError):
            select(f, old, seed=True)
        with self.assertRaises(ValueError):
            ScoredFeatures(f.candidates, [float("nan")] * 15)

    def test_phase_reflection_and_normalization(self):
        state = np.full(4, .5, dtype=complex)
        grover_step(state, np.array([True, False, False, False]))
        np.testing.assert_allclose(state, [1, 0, 0, 0], atol=1e-15)
        rng = np.random.default_rng(19)
        state = rng.normal(size=9) + 1j * rng.normal(size=9)
        state /= np.linalg.norm(state)
        marked = np.arange(9) % 2 == 0
        phase = state * np.where(marked, -1, 1)
        expected = 2 * phase.mean() - phase
        grover_step(state, marked)
        np.testing.assert_allclose(state, expected, atol=1e-15)
        self.assertAlmostEqual(float(np.vdot(state, state).real), 1.)

    def test_gate_relative_loss_and_numerical_ties(self):
        b = {"nDCG@5": .7, "Recall@8": .15, "redundancy": .45}
        a = {"nDCG@5": .7 + 1e-16, "Recall@8": .147, "redundancy": .42}
        self.assertTrue(experiment.gate({"gas_l6": b, "gas_v3": a})["passed"])
        a["Recall@8"] = .1469
        self.assertFalse(experiment.gate({"gas_l6": b, "gas_v3": a})["passed"])
        a.update(Recall_ignored=0, **{"Recall@8": .15, "redundancy": .45})
        self.assertFalse(experiment.gate({"gas_l6": b, "gas_v3": a})["passed"])


class PipelineTests(unittest.TestCase):
    def test_union_formula_and_original_scores_preserved(self):
        corpus, queries, _, _, _ = datasets.synthetic_splits()
        runtime = pipeline.Runtime(corpus, full_controls=True, synthetic=True)
        query = next(iter(queries.values()))
        retrieved = runtime.retrieve(query)
        original = runtime.enrich(query, retrieved, experiment.BaseConfig())
        expanded = runtime.expand(query, original)
        full = CandidateFeatures.from_dict(retrieved["full"])
        want = set()
        for beta in (0., .25, .5):
            want.update(full.ids[i] for i in pipeline.shortlist(full.ids, full.cosine_scores, retrieved["lexical"], beta, 15))
        self.assertEqual(set(expanded["union"]["candidates"]["ids"]), want)
        known = dict(zip(expanded["union"]["candidates"]["ids"], expanded["union"]["l6_logits"]))
        for did, score in zip(original["guided"]["candidates"]["ids"], original["guided"]["l6_logits"]):
            self.assertEqual(known[did], score)
        record = pipeline.execute_features(expanded, experiment.synthetic_base())
        pipeline.validate_record(record, expanded, pipeline.expected_methods())
        self.assertEqual(len(record["methods"]), 27)
        for method in core.METHODS:
            for result in record["methods"][method]["per_seed_results"].values():
                t = result["timings_ms"]
                total = sum(t[k] for k in ("query_encoding_ms", "dense_retrieval_ms", "representative_features_ms", "lexical_scoring_ms", "hybrid_prefilter_ms", "l6_inference_ms", "union_prefilter_ms", "additional_l6_inference_ms", "baseline_selection_ms", "total_ms"))
                self.assertAlmostEqual(t["online_total_ms"], total, places=9)

    def test_missing_cache_refuses_encoding(self):
        obj = pipeline.CachedDenseSpace.__new__(pipeline.CachedDenseSpace)
        with tempfile.TemporaryDirectory() as directory, patch.object(pipeline, "legacy_key", return_value="absent"):
            with self.assertRaisesRegex(ValueError, "refusing corpus encoding"):
                obj._encode_chunks(["text"], directory)


class RecoveryTests(unittest.TestCase):
    def test_interruptions_retain_retrieval_features_and_completed_queries(self):
        corpus, queries, rel, _, _ = datasets.synthetic_splits()
        ids = sorted(queries)[:2]
        data = (corpus, {q: queries[q] for q in ids}, {q: rel[q] for q in ids}, {})
        calls = {"retrieve": 0}
        class CountingRuntime(pipeline.Runtime):
            def retrieve(self, query):
                calls["retrieve"] += 1
                return super().retrieve(query)
        with tempfile.TemporaryDirectory() as directory, patch.object(experiment, "query_data", return_value=data), contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory)
            experiment.collect("synthetic", "confirm", root / "clean", runtime_factory=CountingRuntime)
            clean_id = read_checked(root / "clean/run.json")["identity"]
            clean = Store(root / "clean", clean_id, resume=True)
            expected = {q: {m: [r["ranked_ids"] for r in p["per_seed_results"].values()] if "per_seed_results" in p else p["result"]["ranked_ids"] for m, p in clean.get("queries", q)["methods"].items()} for q in ids}
            for target in (("after_commit", "retrieved"), ("after_commit", "original_features"),
                           ("before_commit", "features"), ("after_commit", "features"),
                           ("before_commit", "queries"), ("after_commit", "queries")):
                calls["retrieve"] = 0
                dest = root / (target[0] + target[1])
                fired = False
                def hook(event, stage, qid):
                    nonlocal fired
                    if (event, stage) == target and not fired:
                        fired = True
                        raise InterruptedError("synthetic interruption")
                with self.assertRaises(InterruptedError):
                    experiment.collect("synthetic", "confirm", dest, hook=hook, runtime_factory=CountingRuntime)
                ident = read_checked(dest / "run.json")["identity"]
                before = Store(dest, ident, resume=True)
                committed = {q: sha(before.file("queries", q)) for q in ids if before.file("queries", q).exists()}
                experiment.collect("synthetic", "confirm", dest, resume=True, runtime_factory=CountingRuntime)
                restored = Store(dest, ident, resume=True)
                restored.verify()
                self.assertEqual(calls["retrieve"], 2)
                for q in ids:
                    found = {m: [r["ranked_ids"] for r in p["per_seed_results"].values()] if "per_seed_results" in p else p["result"]["ranked_ids"] for m, p in restored.get("queries", q)["methods"].items()}
                    self.assertEqual(found, expected[q])
                for q, checksum in committed.items():
                    self.assertEqual(sha(restored.file("queries", q)), checksum)

    def test_corrupt_checkpoint_and_incompatible_resume_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            ident = {"environment": environment_identity(), "extension": extension_identity(), "test": True}
            store = Store(directory, ident)
            store.put("features", "q", {"value": 1})
            store.file("features", "q").write_text('{"bad":true}')
            with self.assertRaisesRegex(ValueError, "Corrupt checkpoint"):
                store.get("features", "q")
            with self.assertRaisesRegex(ValueError, "Resume identity mismatch"):
                Store(directory, {**ident, "test": False}, resume=True)
            snapshot = next((Path(directory) / "source_snapshot/research/accuracy_v3").glob("*.py"))
            snapshot.write_text("corrupt")
            with self.assertRaisesRegex(ValueError, "snapshot corrupted"):
                Store(directory, ident, resume=True)

    def test_completed_collection_evaluation_report_and_freeze(self):
        corpus, queries, rel, _, _ = datasets.synthetic_splits()
        ids = sorted(queries)[:2]
        data = (corpus, {q: queries[q] for q in ids}, {q: rel[q] for q in ids}, {})
        with tempfile.TemporaryDirectory() as directory, patch.object(experiment, "query_data", return_value=data), contextlib.redirect_stdout(io.StringIO()):
            run = Path(directory) / "confirmation"
            experiment.collect("synthetic", "confirm", run)
            experiment.evaluate(run)
            experiment.report(run)
            result = read_checked(run / "evaluation.json")
            self.assertEqual(result["query_count"], 2)
            self.assertEqual(len(result["means"]), 27)
            self.assertEqual(result["comparisons"]["gas_l6"]["nDCG@5"]["p_value"], 1.)
            self.assertGreater(result["official_metrics"]["checks"], 0)
            self.assertTrue((run / "REPORT.md").is_file())
            if result["gate"]["passed"]:
                experiment.freeze(run, Path(directory) / "frozen.json")
                experiment.open_completed(run)
            else:
                with self.assertRaisesRegex(ValueError, "Confirmation failed"):
                    experiment.freeze(run, Path(directory) / "frozen.json")
            with self.assertRaisesRegex(ValueError, "outside the sealed"):
                experiment.freeze(run, run / "frozen.json")


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.handlers = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}

    def tearDown(self):
        for sig, handler in self.handlers.items():
            signal.signal(sig, handler)

    def test_stage_sequence_resume_and_gate_stop(self):
        from . import batch
        import json
        for failure in (False, True, "gate"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
                root = Path(directory)
                launched = []
                class Child:
                    pid = 123456
                    def __init__(self, command, **kwargs):
                        self.command = command
                        launched.append(command)
                    def wait(self, timeout=None):
                        command = self.command
                        stage = command[4]
                        if failure is True and stage == "freeze":
                            return 1
                        dest = Path(command[command.index("--directory") + 1])
                        dest.mkdir(parents=True, exist_ok=True)
                        if stage in {"confirm", "run"}:
                            (dest / "manifest.json").write_text("manifest")
                        elif stage == "evaluate":
                            write_checked(dest / "evaluation.json", {"manifest_sha256": sha(dest / "manifest.json"), "gate": {"passed": failure != "gate"}, "query_count": 100, "means": {}, "execution": {}, "official_metrics": {}})
                        elif stage == "report":
                            (dest / "REPORT.md").write_text("report")
                        elif stage == "freeze":
                            write_checked(Path(command[command.index("--output") + 1]), {"frozen": True})
                        return 0
                with patch.multiple(batch, ROOT=root, STATE=root / "state.json", LOGS=root / "logs", DATASETS=("scifact", "nfcorpus")), \
                     patch.object(batch, "require_smoke"), patch.object(batch, "require_preflight"), patch.object(batch.subprocess, "Popen", Child):
                    code = batch.main()
                    if failure:
                        self.assertEqual(code, 1)
                        self.assertFalse(any(c[4] == "run" for c in launched))
                        self.assertFalse(any("nfcorpus" in c for c in launched))
                        if failure == "gate":
                            state = json.loads((root / "state.json").read_text())
                            self.assertEqual(state["status"], "gate_failed")
                            self.assertEqual(state["active_stage"], "confirmation_gate")
                    else:
                        self.assertEqual(code, 0)
                        self.assertEqual(len(launched), 14)
                        self.assertEqual(batch.main(resume=True), 0)
                        self.assertEqual(len(launched), 14)
                        state = json.loads((root / "state.json").read_text())
                        self.assertEqual(state["status"], "completed")


if __name__ == "__main__":
    unittest.main()
