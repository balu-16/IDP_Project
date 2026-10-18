"""Numerical correctness and fault injection; no real dataset evaluation."""
from __future__ import annotations

from dataclasses import replace
import contextlib
import io
import itertools
import json
import math
import signal
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from research.selection import CandidateFeatures, grover_step
from research.accuracy_v2 import core, experiment
from research.accuracy_v2.core import Config, ScoredFeatures, prepare, select
from research.accuracy_v2.encoding import encode_sharded
from research.accuracy_v2.pipeline import Runtime, execute_features, expected_methods, validate_record
from research.accuracy_v2.storage import Store, digest, exclusive, read_checked, write_checked


def fixture(n=15):
    rng = np.random.default_rng(31)
    base = CandidateFeatures(tuple(f"D{i:02}" for i in range(n)), np.linspace(.95, -.2, n),
                             rng.normal(size=(n, 7)), tuple(f"passage {i}" for i in range(n)))
    return ScoredFeatures(base, np.linspace(-8, 4, n))


class NumericalTests(unittest.TestCase):
    def test_installed_cross_encoder_score_interface_and_input_limit(self):
        from research.accuracy_v2.pipeline import Scorer
        class FakeModel:
            def tokenizer(self, queries, passages, **kwargs):
                return {"input_ids": [[1, 2, 3] for _ in queries]}
            def predict(self, pairs, batch_size, show_progress_bar, activation_fct):
                return [-4.0] * len(pairs)
        scorer = Scorer.__new__(Scorer)
        scorer.model, scorer.activation = FakeModel(), lambda x: x
        values, _ = scorer.scores("query", fixture(3).candidates)
        np.testing.assert_array_equal(values, [-4, -4, -4])
        with patch.object(scorer.model, "tokenizer", return_value={"input_ids": [[1] * 513] * 3}):
            with self.assertRaisesRegex(ValueError, "512 tokens"):
                scorer.scores("query", fixture(3).candidates)

    def test_separate_score_semantics_and_zero_penalty_for_all_seeds(self):
        for n in (0, 1, 5, 15):
            features = fixture(n)
            old_cosine = features.candidates.cosine_scores.copy()
            baseline = select(features, "l6_only")
            for seed in core.SEEDS:
                result = select(features, config=Config(diversity_weight=0), seed=seed)
                self.assertEqual(result.ranked_ids, baseline.ranked_ids)
                self.assertEqual(len(result.ranked_ids), min(8, n))
                self.assertEqual(len(set(result.ranked_ids)), min(8, n))
            np.testing.assert_array_equal(features.candidates.cosine_scores, old_cosine)
            self.assertFalse(features.l6_logits.flags.writeable)

    def test_constant_tied_and_negative_logits(self):
        np.testing.assert_array_equal(core.normalize_relevance([-5, -5, -5]), [.5, .5, .5])
        np.testing.assert_array_equal(core.normalize_relevance([1, 1 + 1e-13]), [.5, .5])
        np.testing.assert_allclose(core.normalize_relevance([-9, -5, -1]), [0, .5, 1])
        features = ScoredFeatures(fixture().candidates, np.full(15, -3.))
        result = select(features, config=Config(diversity_weight=0))
        self.assertEqual(result.ranked_ids, [f"D{i:02}" for i in range(8)])

    def test_invalid_scores_and_configuration(self):
        for scores in ([float("nan")], [float("inf")], [[1]], [1e308, -1e308]):
            with self.assertRaises(ValueError), np.errstate(over="ignore"):
                core.normalize_relevance(scores)
        for value in (-.1, 1.1, float("nan"), True):
            with self.assertRaises(ValueError):
                Config(lexical_weight=value)
        with self.assertRaises(ValueError):
            ScoredFeatures(fixture(3).candidates, [1, 2])
        with self.assertRaises(ValueError):
            core.hybrid_scores([.2], [-1])
        with self.assertRaises(ValueError):
            select(fixture(), seed=True)

    def test_hybrid_formula_fallback_and_document_ties(self):
        cosine, lexical = np.array([.8, .5, -.2]), np.array([0, 2, 1])
        expected = .75 * (1 + cosine) / 1.8 + .25 * lexical / 2
        np.testing.assert_array_equal(core.hybrid_scores(cosine, lexical), expected)
        np.testing.assert_array_equal(core.hybrid_scores(cosine, [0, 0, 0]), (1 + cosine) / 1.8)
        np.testing.assert_array_equal(core.hybrid_scores([-1, -1], [0, 0]), [0, 0])
        self.assertEqual(core.shortlist(["b", "a"], [.5, .5], [0, 0]), [1, 0])

    def test_integer_and_continuous_optima_against_independent_formula(self):
        features = fixture(7)
        cfg = Config(candidate_limit=7, selected_count=3, diversity_weight=.4)
        problem = prepare(features, cfg)
        energies, utilities = [], []
        for row in itertools.combinations(range(7), 3):
            relevance = (features.l6_logits - features.l6_logits.min()) / np.ptp(features.l6_logits)
            similarities = [max(0, min(1, float(features.candidates.embeddings[i] @ features.candidates.embeddings[j])))
                            for i, j in itertools.combinations(row, 2)]
            energy = -sum(round(255 * relevance[i]) for i in row) + sum(round(255 * .4 * d) for d in similarities)
            utility = np.mean(relevance[list(row)]) - .4 * np.mean(similarities)
            self.assertEqual(problem.energy(row), energy)
            self.assertAlmostEqual(problem.utility(row), utility)
            energies.append(energy)
            utilities.append(utility)
        self.assertEqual(select(features, "exact_quantized_l6", cfg).energy, min(energies))
        self.assertAlmostEqual(select(features, "exact_float_l6", cfg).utility, max(utilities))

    def test_continuous_exact_control_does_not_build_an_integer_energy_table(self):
        with patch("research.accuracy_v2.core.enumerate_energies", side_effect=AssertionError("unnecessary integer oracle work")):
            result = select(fixture(7), "exact_float_l6", Config(candidate_limit=7, selected_count=3))
        self.assertEqual(result.counts["classical_objective_evaluations"], 35)

    def test_grover_amplification_and_no_or_all_marked(self):
        for count in (0, 2, 8):
            amplitudes = np.full(8, 1 / math.sqrt(8), dtype=complex)
            mask = np.arange(8) < count
            grover_step(amplitudes, mask)
            self.assertAlmostEqual(float(np.sum(np.abs(amplitudes) ** 2)), 1)
            if count == 2:
                self.assertAlmostEqual(float(np.sum(np.abs(amplitudes[mask]) ** 2)), 1)

    def test_budget_status_trace_and_reproducibility(self):
        features = fixture()
        for options, status in (({"max_oracle_calls": 0}, "oracle_budget"), ({"max_trials": 0}, "trial_budget"),
                                ({"time_limit_seconds": 0}, "time_limit")):
            self.assertEqual(select(features, config=Config(**options)).status, status)
        for seed in core.SEEDS:
            a = select(features, config=Config(diversity_weight=.7), seed=seed)
            b = select(features, config=Config(diversity_weight=.7), seed=seed)
            self.assertEqual(a.ranked_ids, b.ranked_ids)
            self.assertEqual(a.trace, b.trace)
            self.assertLessEqual(a.counts["phase_oracle_calls"], 64)
            self.assertLessEqual(a.counts["measured_trials"], 32)
            self.assertEqual(a.counts["classical_simulator_objective_evaluations"], 6435)
            for row in a.trace:
                if row.get("accepted"):
                    self.assertLess(row["incumbent_after"], row["incumbent_before"])

    def test_grover_actually_changes_a_redundant_starting_set(self):
        angles = np.array([0, .1, 1.5])
        base = CandidateFeatures(("a", "b", "c"), [.9, .8, .7], np.column_stack([np.cos(angles), np.sin(angles)]))
        features = ScoredFeatures(base, [.9, .89, .75])
        cfg = Config(candidate_limit=3, selected_count=2, diversity_weight=.7)
        baseline = select(features, "l6_only", cfg)
        results = [select(features, config=cfg, seed=s) for s in core.SEEDS]
        self.assertTrue(any(r.selected_ids != baseline.selected_ids for r in results))
        self.assertTrue(any(row.get("accepted") for r in results for row in r.trace))
        self.assertTrue(all(r.energy <= baseline.energy for r in results))

    def test_matching_controls_and_full_l6_cost(self):
        from research.datasets import synthetic_splits
        corpus, queries, _, _, _ = synthetic_splits()
        runtime = Runtime(corpus, full_controls=True, synthetic=True)
        query = next(iter(queries.values()))
        bundle = runtime.enrich(query, runtime.retrieve(query), Config())
        record = execute_features(bundle, Config())
        validate_record(record, bundle, expected_methods())
        for name in core.GUIDED:
            row = next(iter(record["methods"][name]["per_seed_results"].values())) if name in {"gas_l6", "random_l6"} else record["methods"][name]["result"]
            expected = row["timings_ms"]["total_ms"] + sum(bundle["timings_ms"].values())
            self.assertAlmostEqual(row["timings_ms"]["online_total_ms"], expected)
        del record["methods"]["gas_l6"]["per_seed_results"]["4"]
        with self.assertRaises(ValueError):
            validate_record(record, bundle, expected_methods())


class RecoveryTests(unittest.TestCase):
    def test_atomic_checkpoint_rejects_corruption_and_identity_change(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory, {"config": 1})
            store.put("features", "Q", {"scores": [1, 2]})
            with self.assertRaisesRegex(ValueError, "identity mismatch"):
                Store(directory, {"config": 2}, resume=True)
            path = store.file("features", "Q")
            value = json.loads(path.read_text())
            value["payload"]["data"]["scores"][0] = 5
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "Corrupt checkpoint"):
                store.get("features", "Q")

    def test_atomic_file_failure_keeps_previous_value(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint"
            write_checked(path, {"value": 1})
            with patch("research.accuracy_v2.storage.os.replace", side_effect=OSError("simulated interrupted rename")):
                with self.assertRaises(OSError):
                    write_checked(path, {"value": 2})
            self.assertEqual(read_checked(path), {"value": 1})
            self.assertEqual(list(Path(directory).glob(".pending-*")), [])

    def test_embedding_resume_and_corrupt_shard(self):
        class FakeEncoder:
            max_seq_length = 192
            def __init__(self):
                self.calls = []
            def encode(self, texts, **kwargs):
                self.calls.append(list(texts))
                return np.array([[int(t) + 1, 1.] for t in texts])
        with tempfile.TemporaryDirectory() as directory:
            encoder = FakeEncoder()
            space = SimpleNamespace(model=encoder, model_name="fixture", revision="fixture", CONTENT_TOKENS=190, STEP=158)
            def stop(event, index):
                if event == "after_embedding_commit" and index == 0:
                    raise InterruptedError("stop after one shard")
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(InterruptedError):
                    encode_sharded(space, list(map(str, range(7))), directory, shard_rows=3, hook=stop)
                matrix, info = encode_sharded(space, list(map(str, range(7))), directory, shard_rows=3)
                cached, restored = encode_sharded(space, list(map(str, range(7))), directory, shard_rows=3)
            np.testing.assert_array_equal(matrix, [[i + 1, 1.] for i in range(7)])
            np.testing.assert_array_equal(matrix, cached)
            self.assertEqual(info["reused_shard_rows"], 3)
            self.assertTrue(restored["hit"])
            self.assertEqual(encoder.calls, [["0", "1", "2"], ["3", "4", "5"], ["6"]])
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(InterruptedError), contextlib.redirect_stdout(io.StringIO()):
                encode_sharded(space, list(map(str, range(7))), directory, shard_rows=3, hook=stop)
            path = next(Path(directory).glob("*.shards/*.npy"))
            path.write_bytes(b"corrupt")
            with self.assertRaisesRegex(ValueError, "Corrupt embedding shard"):
                encode_sharded(space, list(map(str, range(7))), directory, shard_rows=3)

    def test_resume_before_and_after_feature_and_query_commits(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory)
            complete = experiment.run("synthetic", root / "reference", full_controls=False)
            reference = read_checked(complete / "run.json")["identity"]
            ref_store = Store(complete, reference, resume=True)
            expected = {q: ref_store.get("queries", q) for q in reference["query_ids"]}
            for target_stage in ("features", "queries"):
                for target_event in ("before_commit", "after_commit"):
                    case = root / f"{target_stage}-{target_event}"
                    calls = []
                    def stop(event, stage, qid):
                        if event == target_event and stage == target_stage and not calls:
                            calls.append(qid)
                            raise InterruptedError("injected stop")
                    with self.assertRaises(InterruptedError):
                        experiment.run("synthetic", case, full_controls=False, hook=stop)
                    ident = read_checked(case / "run.json")["identity"]
                    interrupted = Store(case, ident, resume=True)
                    completed_feature = interrupted.get("features", calls[0])
                    completed_query = interrupted.get("queries", calls[0])
                    before_digest = digest(completed_query) if completed_query else None
                    original = Runtime.enrich
                    first_query = __import__("research.datasets", fromlist=["synthetic_splits"]).synthetic_splits()[3][calls[0]]
                    def guard(runtime, query, retrieved, config):
                        if completed_feature is not None and query == first_query:
                            raise AssertionError("Repeated completed neural scoring")
                        return original(runtime, query, retrieved, config)
                    with patch.object(Runtime, "enrich", guard):
                        experiment.run("synthetic", case, resume=True, full_controls=False)
                    resumed = Store(case, ident, resume=True)
                    resumed.verify()
                    if before_digest:
                        self.assertEqual(digest(resumed.get("queries", calls[0])), before_digest)
                    for qid in ident["query_ids"]:
                        record = resumed.get("queries", qid)
                        for method, payload in record["methods"].items():
                            key = "per_seed_results" if method in {"gas", "random", "gas_l6", "random_l6"} else "result"
                            a, b = payload[key], expected[qid]["methods"][method][key]
                            if key == "result":
                                self.assertEqual(a["ranked_ids"], b["ranked_ids"])
                            else:
                                self.assertEqual({s: r["ranked_ids"] for s, r in a.items()}, {s: r["ranked_ids"] for s, r in b.items()})
                    sessions = read_checked(case / "sessions.json")
                    self.assertEqual([s["status"] for s in sessions], ["interrupted", "completed"])

    def test_incomplete_runs_cannot_be_evaluated_or_sealed(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory, {"fixture": 1})
            store.put("features", "q", {})
            with self.assertRaisesRegex(ValueError, "coverage"):
                store.seal(["q"], lambda *_: None)
            with self.assertRaises(FileNotFoundError):
                store.verify()

    def test_completed_manifest_rejects_extra_work_and_exclusive_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory, {"fixture": 1})
            store.put("features", "q", {})
            store.put("queries", "q", {})
            store.seal(["q"], lambda *_: None)
            store.verify()
            store.put("queries", "unsealed", {})
            with self.assertRaisesRegex(ValueError, "Unsealed"):
                store.verify()
            with exclusive(Path(directory) / ".lock"):
                with self.assertRaisesRegex(ValueError, "Another process"):
                    with exclusive(Path(directory) / ".lock"):
                        pass

    def test_sigterm_records_interrupted_session_and_restores_handler(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory, {"fixture": 1})
            original = signal.getsignal(signal.SIGTERM)
            with self.assertRaises(InterruptedError):
                with store.session():
                    signal.raise_signal(signal.SIGTERM)
            self.assertEqual(signal.getsignal(signal.SIGTERM), original)
            self.assertEqual(read_checked(Path(directory) / "sessions.json")[0]["status"], "interrupted")

    def test_real_development_loader_never_opens_test_judgments(self):
        from research.accuracy_v2.pipeline import load_development
        calls = []
        def qrels(base, split):
            calls.append(split)
            if split != "train":
                raise AssertionError("Test judgments reached development tuning")
            return {"Q": {"D": 1}}
        with patch("research.accuracy_v2.pipeline.datasets._load_corpus", return_value={"D": "text"}), \
             patch("research.accuracy_v2.pipeline.datasets._load_queries", return_value={"Q": "query"}), \
             patch("research.accuracy_v2.pipeline.datasets._load_qrels", side_effect=qrels):
            self.assertEqual(set(load_development("scifact")[1]), {"Q"})
        self.assertEqual(calls, ["train"])

    def test_zero_penalty_eligible_and_tuning_uses_development_loader(self):
        from research.datasets import synthetic_splits
        corpus, dev, rel, _, _ = synthetic_splits()
        runtime = Runtime(corpus, False, synthetic=True)
        bundles = {str(beta): runtime.enrich(next(iter(dev.values())), runtime.retrieve(next(iter(dev.values()))), Config(lexical_weight=beta)) for beta in core.BETAS}
        row = experiment._tune_query(bundles, rel[next(iter(dev))], False)
        winner, grid, _, _ = experiment._choose([row])
        self.assertTrue(all(r["eligible"] for r in grid if r["penalty"] == 0))
        self.assertTrue(winner["eligible"])
        with patch("research.accuracy_v2.pipeline.datasets._load_qrels", side_effect=AssertionError("test qrels")):
            # Synthetic development loader must not reach any real dataset loader.
            self.assertEqual(len(experiment.load_development("synthetic")[1]), len(dev))


if __name__ == "__main__":
    unittest.main()
