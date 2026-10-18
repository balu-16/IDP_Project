"""Focused unit tests: synthetic arrays only; no real datasets or model loading."""
from __future__ import annotations

from dataclasses import asdict, replace
import itertools
import contextlib
import io
import json
import math
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from research.selection import (CandidateFeatures, GASConfig, enumerate_energies, grover_step,
                                prepare_problem, search, select_classical, select_evidence,
                                selection_metrics, subset_layout)
from research.selection_experiment import (SEEDS, SCHEMA, MMR_WEIGHTS, config_from_args, evaluate_records,
                                          run_query, seal_run, summarize_ranking, tune_weight,
                                          tune_mmr_weight, verify_run)
from research.selection_features import FeatureBuilder, NeuralReranker


def fixture(n=15, dimension=6):
    rng = np.random.default_rng(19)
    return CandidateFeatures(tuple(f"D{i:02}" for i in range(n)), np.linspace(0.95, -0.2, n),
                             rng.normal(size=(n, dimension)), tuple(f"passage {i}" for i in range(n)))


class FeatureAndConfigTests(unittest.TestCase):
    def test_missing_judged_query_is_not_silently_dropped(self):
        from research.datasets import _filter_to_qrels
        with self.assertRaisesRegex(ValueError, "no query text"):
            _filter_to_qrels({'present': 'text'}, {'missing': {'doc': 1}})

    def test_defaults_and_round_trip(self):
        config = GASConfig()
        self.assertEqual((config.candidate_limit, config.selected_count, config.coefficient_bits), (15, 8, 6))
        self.assertEqual(GASConfig(**asdict(config)), config)
        features = fixture()
        restored = CandidateFeatures.from_dict(json.loads(json.dumps(features.to_dict())))
        self.assertEqual(restored.ids, features.ids)
        np.testing.assert_allclose(restored.embeddings, features.embeddings)
        self.assertFalse(features.embeddings.flags.writeable)

    def test_bad_configuration_is_rejected(self):
        for kwargs in ({"selected_count": 16}, {"candidate_limit": 21}, {"coefficient_bits": 0},
                       {"coefficient_bits": 17}, {"diversity_weight": float("nan")},
                       {"diversity_weight": -0.1}, {"time_limit_seconds": -1},
                       {"window_growth": 1}, {"window_growth": 2}, {"max_oracle_calls": -1},
                       {"selected_count": True}, {"max_subsets": 2}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                GASConfig(**kwargs)

    def test_bad_features_are_rejected(self):
        bad = [(('a', 'a'), [0.2, 0.3], np.eye(2)),
               (('a',), [float('nan')], [[1, 0]]),
               (('a',), [1.2], [[1, 0]]),
               (('a',), [0.2], [[0, 0]]),
               (('a',), [0.2, 0.3], [[1, 0]]),
               (('a',), [0.2], [[float('inf'), 0]])]
        for args in bad:
            with self.subTest(args=args), self.assertRaises(ValueError):
                CandidateFeatures(*args)

    def test_prefilter_is_explicit(self):
        with self.assertRaises(ValueError):
            select_evidence(fixture(16))

    def test_normalization_copies_caller_data(self):
        matrix = np.array([[3., 4.]])
        features = CandidateFeatures(('a',), [0.2], matrix)
        np.testing.assert_array_equal(matrix, [[3., 4.]])
        np.testing.assert_allclose(features.embeddings, [[0.6, 0.8]])

    def test_representative_uses_best_chunk_and_first_exact_tie(self):
        class FakeSpace:
            is_chunked = True
            chunk_parents = ['a', 'a', 'b', 'b']
            chunk_matrix = np.array([[0., 1.], [1., 0.], [0.8, 0.6], [0.8, 0.6]])
            chunk_texts = ['wrong a', 'best a', 'first b', 'second b']

            def query_vec(self, query):
                return np.array([1., 0.])
        features = FeatureBuilder(FakeSpace(), {}).build('query', ['a', 'b'], {'a': 1., 'b': .8})
        self.assertEqual(features.passages, ('best a', 'first b'))
        self.assertEqual(features.representative_ids, ('a::chunk1', 'b::chunk2'))

    def test_document_level_feature_adapter(self):
        class FakeSpace:
            doc_ids = ['a', 'b']
            matrix = np.eye(2)

            def query_vec(self, query):
                return np.array([1., 0.])
        features = FeatureBuilder(FakeSpace(), {'a': 'text a', 'b': 'text b'}).build(
            'query', ['b', 'a'], {'a': 1., 'b': 0.})
        self.assertEqual(features.ids, ('b', 'a'))
        self.assertEqual(features.passages, ('text b', 'text a'))


class DenseTokenizerRegressionTests(unittest.TestCase):
    class Backend:
        def __init__(self):
            self.truncated, self.padded = True, True

        def no_truncation(self):
            self.truncated = False

        def no_padding(self):
            self.padded = False

        def encode(self, text, **kwargs):
            from types import SimpleNamespace
            offsets = [m.span() for m in re.finditer(r"\S+", text)]
            if self.truncated:
                offsets = offsets[:128]
            if self.padded:
                offsets += [(0, 0)] * max(0, 128 - len(offsets))
            return SimpleNamespace(offsets=offsets)

    class Tokenizer:
        def __init__(self):
            self.backend_tokenizer = DenseTokenizerRegressionTests.Backend()

        def encode(self, text, **kwargs):
            self.backend_tokenizer.no_padding()
            self.backend_tokenizer.no_truncation()
            return list(range(len(text.split())))

    class Model:
        max_seq_length = 192

        def __init__(self):
            self.calls = 0

        def encode(self, texts, **kwargs):
            self.calls += 1
            return np.ones((len(texts), 4)) / 2

    def build(self, corpus, model, cache_dir=None):
        from research.baselines import DenseVectorSpace
        with patch('sentence_transformers.SentenceTransformer', return_value=model), \
                patch('transformers.AutoTokenizer.from_pretrained', return_value=self.Tokenizer()), \
                contextlib.redirect_stdout(io.StringIO()):
            return DenseVectorSpace(corpus, 'fake', 'unit-test', cache_dir=cache_dir)

    def test_first_document_offsets_are_neither_truncated_nor_padded(self):
        corpus = {'first': ' '.join(['evidence'] * 400), 'second': 'tiny'}
        space = self.build(corpus, self.Model())
        self.assertEqual(space.chunk_parents, ['first', 'first', 'first', 'second'])
        self.assertEqual([len(t.split()) for t in space.chunk_texts], [190, 190, 84, 1])
        self.assertTrue(space.meta['tokenizer_full_text_offsets'])

    def test_embedding_cache_reuses_only_identical_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            model = self.Model()
            first = self.build({'doc': 'original text'}, model, directory)
            second = self.build({'doc': 'original text'}, model, directory)
            self.assertEqual(model.calls, 1)
            self.assertTrue(second.meta['embedding_cache']['hit'])
            np.testing.assert_array_equal(first.chunk_matrix, second.chunk_matrix)
            changed = self.build({'doc': 'changed text'}, model, directory)
            self.assertEqual(model.calls, 2)
            self.assertFalse(changed.meta['embedding_cache']['hit'])

    def test_empty_parent_is_retained_and_included_in_token_statistics(self):
        space = self.build({'empty': '', 'long': ' '.join(['evidence'] * 400)}, self.Model())
        self.assertEqual(space.chunk_parents, ['empty', 'long', 'long', 'long'])
        self.assertEqual(space.chunk_texts[0], '')
        self.assertEqual(space.meta['chunk_min_tokens'], 0)
        self.assertEqual(space.meta['chunk_mean_tokens'], 116.)

    def test_embedding_cache_checksum_rejects_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            model = self.Model()
            self.build({'doc': 'original text'}, model, directory)
            path = next(Path(directory).glob('*.npy'))
            with path.open('ab') as handle:
                handle.write(b'corruption')
            with self.assertRaisesRegex(ValueError, 'cache checksum mismatch'):
                self.build({'doc': 'original text'}, model, directory)


class OracleAndSearchTests(unittest.TestCase):
    def test_energy_table_matches_independent_subset_formula(self):
        config = GASConfig(candidate_limit=6, selected_count=3)
        problem = prepare_problem(fixture(6), config)
        layout, energies = enumerate_energies(problem)
        self.assertEqual(len(layout), math.comb(6, 3))
        expected = []
        for subset in itertools.combinations(range(6), 3):
            energy = -sum(int(problem.linear[i]) for i in subset)
            energy += sum(int(problem.quadratic[i, j]) for i, j in itertools.combinations(subset, 2))
            expected.append(energy)
        np.testing.assert_array_equal(energies, expected)

    def test_phase_reflection_matches_amplification_formula(self):
        for size, marked_count in [(6, 1), (6, 3), (20, 2), (20, 19)]:
            marked = np.arange(size) < marked_count
            state = np.full(size, 1 / math.sqrt(size), dtype=np.complex128)
            theta = math.asin(math.sqrt(marked_count / size))
            for iteration in range(1, 4):
                grover_step(state, marked)
                self.assertAlmostEqual(float(np.sum(abs(state) ** 2)), 1., places=12)
                self.assertAlmostEqual(float(np.sum(abs(state[marked]) ** 2)),
                                       math.sin((2 * iteration + 1) * theta) ** 2, places=12)

    def test_no_marked_and_all_marked_are_safe(self):
        for marked in [np.zeros(6, dtype=bool), np.ones(6, dtype=bool)]:
            state = np.ones(6, dtype=complex) / math.sqrt(6)
            grover_step(state, marked)
            np.testing.assert_allclose(abs(state) ** 2, np.ones(6) / 6)

    def test_15_to_8_cardinality_order_and_accounting(self):
        features = fixture()
        config = GASConfig()
        result = select_evidence(features, config, seed=7)
        self.assertEqual(len(set(result.selected_ids)), 8)
        self.assertEqual(set(result.ranked_ids), set(result.selected_ids))
        score = dict(zip(features.ids, features.cosine_scores))
        self.assertEqual(result.ranked_ids, sorted(result.selected_ids, key=lambda d: (-score[d], d)))
        self.assertEqual(result.resources['feasible_subsets'], 6435)
        self.assertEqual(result.counts['classical_simulator_objective_evaluations'], 6435)
        self.assertLessEqual(result.counts['phase_oracle_calls'], 64)
        self.assertLessEqual(result.counts['measured_trials'], 32)
        self.assertEqual(result.counts['reversible_objective_calls'], 2 * result.counts['phase_oracle_calls'])
        self.assertGreaterEqual(result.timings_ms['total_ms'], result.timings_ms['enumeration_ms'])
        self.assertGreaterEqual(result.timings_ms['cpu_ms'], 0)
        self.assertIn('rss_note', result.resources)

    def test_seed_reproducibility(self):
        first = select_evidence(fixture(), seed=12)
        second = select_evidence(fixture(), seed=12)
        self.assertEqual(first.selected_ids, second.selected_ids)
        self.assertEqual(first.trace, second.trace)
        self.assertEqual(first.counts, second.counts)

    def test_every_accepted_update_strictly_improves_energy(self):
        problem = prepare_problem(fixture())
        initial = problem.energy(problem.cosine_order()[:problem.count])
        result = search(problem, 4)
        self.assertLessEqual(result.energy, initial)
        for step in result.trace:
            self.assertLessEqual(step['incumbent_after'], step['incumbent_before'])
            if step.get('accepted'):
                self.assertLess(step['incumbent_after'], step['incumbent_before'])

    def test_gas_can_find_non_cosine_evidence_set(self):
        features = CandidateFeatures(('a', 'b', 'c'), [1., .98, .8], [[1, 0], [1, .01], [0, 1]])
        config = GASConfig(candidate_limit=3, selected_count=2, diversity_weight=.5)
        cosine = select_classical(features, 'cosine', config)
        exact = select_classical(features, 'exact_quantized', config)
        runs = [select_evidence(features, config, seed) for seed in SEEDS]
        self.assertGreater(cosine.energy, exact.energy)
        self.assertTrue(any(result.energy == exact.energy for result in runs))
        self.assertTrue(all(result.energy >= exact.energy for result in runs))

    def test_empty_and_undersized_pools(self):
        for features in [CandidateFeatures((), [], []), fixture(1), fixture(5), fixture(8)]:
            result = select_evidence(features)
            self.assertEqual(result.status, 'trivial')
            self.assertEqual(len(result.selected_ids), len(features.ids))
            self.assertEqual(result.counts['phase_oracle_calls'], 0)
            json.dumps(result.to_dict(), allow_nan=False)

    def test_budgets_zero_and_one(self):
        for kwargs, status in [({'max_trials': 0}, 'trial_budget'),
                               ({'max_oracle_calls': 0}, 'oracle_budget'),
                               ({'time_limit_seconds': 0}, 'time_limit')]:
            result = select_evidence(fixture(), GASConfig(**kwargs))
            self.assertEqual(result.status, status)
            self.assertEqual(result.counts['phase_oracle_calls'], 0)
        result = select_evidence(fixture(), GASConfig(max_oracle_calls=1))
        self.assertLessEqual(result.counts['phase_oracle_calls'], 1)

    def test_timeout_is_explicit(self):
        with patch('research.selection.time.perf_counter', side_effect=itertools.count(step=1)):
            result = search(prepare_problem(fixture()), 1)
        self.assertEqual(result.status, 'time_limit')
        self.assertLessEqual(result.counts['phase_oracle_calls'], 64)

    def test_negative_and_tied_cosines(self):
        features = CandidateFeatures(('z', 'a', 'b'), [-.5, -.5, -.9], np.eye(3))
        result = select_evidence(features, GASConfig(candidate_limit=3, selected_count=2, diversity_weight=0))
        self.assertEqual(result.ranked_ids, ['a', 'z'])

    def test_resource_bounds_prevent_feasible_signed_overflow(self):
        for precision in [2, 4, 6]:
            problem = prepare_problem(fixture(6), GASConfig(candidate_limit=6, selected_count=3,
                                                           coefficient_bits=precision))
            _, energies = enumerate_energies(problem)
            resource = problem.resources()
            limit = 1 << (resource['value_qubits'] - 1)
            self.assertGreaterEqual(int(energies.min()), resource['energy_lower_bound'])
            self.assertLessEqual(int(energies.max()), resource['energy_upper_bound'])
            self.assertLess(int(energies.max() - energies.min()), limit)


class ClassicalAndEvaluationTests(unittest.TestCase):
    def test_baselines_return_matched_sets_and_independent_optimum(self):
        features = fixture(6)
        config = GASConfig(candidate_limit=6, selected_count=3)
        problem = prepare_problem(features, config)
        expected = min(problem.energy(s) for s in itertools.combinations(range(6), 3))
        for method in ['cosine', 'fusion', 'mmr', 'greedy', 'exact_quantized', 'exact_float', 'random']:
            result = select_classical(features, method, config, lexical_scores=list(range(6)))
            self.assertEqual(len(set(result.selected_ids)), 3)
            self.assertGreaterEqual(result.energy, expected)
        self.assertEqual(select_classical(features, 'exact_quantized', config).energy, expected)

    def test_exact_float_optimizes_unquantized_objective(self):
        features, config = fixture(6), GASConfig(candidate_limit=6, selected_count=3)
        problem = prepare_problem(features, config)
        expected = max(problem.utility(s) for s in itertools.combinations(range(6), 3))
        result = select_classical(features, 'exact_float', config)
        self.assertAlmostEqual(result.utility, expected)

    def test_random_budget_is_counted_and_gas_remains_independent(self):
        result = select_classical(fixture(), 'random', objective_budget=4)
        self.assertEqual(result.counts['classical_objective_evaluations'], 4)
        with patch('research.selection.enumerate_energies', side_effect=AssertionError('enumeration forbidden')):
            select_classical(fixture(), 'random', objective_budget=4)
            select_classical(fixture(), 'greedy')
            select_classical(fixture(), 'mmr')

    def test_pure_metric_cutoffs_and_zero_qrels(self):
        result = select_classical(fixture(), 'cosine')
        values = selection_metrics(result, {result.ranked_ids[0]: 2, result.ranked_ids[1]: 0})
        self.assertEqual(values['nDCG@5'], 1.)
        self.assertEqual(values['Recall@8'], 1.)
        self.assertEqual(selection_metrics(result, {})['nDCG@5'], 0.)

    def test_weight_tuning_is_development_only(self):
        config = GASConfig(candidate_limit=6, selected_count=3)
        chosen, audit = tune_weight({'dev': fixture(6)}, {'dev': {'D00': 1}}, config)
        self.assertIn(chosen.diversity_weight, (.1, .25, .5))
        self.assertEqual(audit['query_ids'], ['dev'])
        with self.assertRaises(ValueError):
            tune_weight({'dev': fixture(6)}, {'test': {'D00': 1}}, config)

    def test_feature_comparison_cannot_accept_qrels(self):
        with self.assertRaises(ValueError):
            run_query(fixture(), GASConfig(), qrels_unused={'a': 1})

    def test_mmr_tuning_is_independent_and_keeps_common_scoring_objective(self):
        features = CandidateFeatures(('a', 'b', 'c'), [1., .98, .4], [[1, 0], [1, .01], [0, 1]])
        config = GASConfig(candidate_limit=3, selected_count=2, diversity_weight=.1)
        judgments = {'a': 1, 'c': 1}
        weight, audit = tune_mmr_weight({'dev': features}, {'dev': judgments}, config)
        self.assertIn(weight, MMR_WEIGHTS)
        self.assertNotEqual(weight, config.diversity_weight)
        self.assertEqual(audit['query_ids'], ['dev'])
        self.assertEqual(max(row['nDCG@5'] for row in audit['grid']),
                         next(row['nDCG@5'] for row in audit['grid'] if row['weight'] == weight))
        result = type_from_record(run_query(features, config, mmr_weight=weight)['mmr']['result'])
        self.assertEqual(result.ranked_ids, ['a', 'c'])
        self.assertEqual(result.resources['mmr_diversity_weight'], weight)
        self.assertEqual(result.config['diversity_weight'], .1)
        self.assertEqual(result.energy, prepare_problem(features, config).energy([0, 2]))
        with self.assertRaises(ValueError):
            tune_mmr_weight({'dev': features}, {'test': judgments}, config)
        for invalid in (-.1, 1.1, float('nan')):
            with self.assertRaises(ValueError):
                select_classical(features, 'mmr', config, mmr_weight=invalid)

    def test_seed_average_and_coverage_from_in_memory_records(self):
        config = GASConfig(candidate_limit=6, selected_count=3)
        methods = run_query(fixture(6), config)
        manifest = {'test_ids': ['q'], 'methods': sorted(methods), 'seeds': list(SEEDS), 'config': asdict(config)}
        records = [{'qid': 'q', 'candidate_ids': list(fixture(6).ids),
                    'shortlist_ids': list(fixture(6).ids), 'methods': methods}]
        scores = evaluate_records(manifest, records, {'q': {'D00': 1}})
        expected = np.mean([selection_metrics(type_from_record(r), {'D00': 1})['nDCG@5']
                            for r in methods['gas']['per_seed_results'].values()])
        self.assertAlmostEqual(scores['means']['gas']['nDCG@5'], expected)
        del methods['gas']['per_seed_results']['4']
        with self.assertRaises(ValueError):
            evaluate_records(manifest, records, {'q': {'D00': 1}})

    def test_mock_neural_uses_passages_and_model_order(self):
        class FakeModel:
            def predict(self, pairs, **kwargs):
                self.pairs = pairs
                return np.arange(len(pairs), dtype=float)
        model = FakeModel()
        reranker = NeuralReranker(model, 'fake', 'unit-test')
        result = reranker.rank('query', fixture(6), 3)
        self.assertEqual(result, ['D05', 'D04', 'D03'])
        self.assertEqual(model.pairs[0], ('query', 'passage 0'))

    def test_full_pool_summary_keeps_neural_or_legacy_order(self):
        features = fixture(20)
        ranked = ['D19', 'D18', 'D17', 'D16', 'D15', 'D14', 'D13', 'D12']
        result = summarize_ranking('neural_l6_top64', ranked, features, GASConfig())
        self.assertEqual(result.ranked_ids, ranked)
        self.assertEqual(set(result.selected_ids), set(ranked))
        self.assertGreaterEqual(result.redundancy, 0)

    def test_result_accounting_reports_per_seed_latency_and_gap(self):
        config = GASConfig(candidate_limit=6, selected_count=3)
        methods = run_query(fixture(6), config)
        manifest = {'test_ids': ['q'], 'methods': sorted(methods), 'seeds': list(SEEDS), 'config': asdict(config)}
        records = [{'qid': 'q', 'candidate_ids': list(fixture(6).ids),
                    'shortlist_ids': list(fixture(6).ids), 'methods': methods}]
        scores = evaluate_records(manifest, records, {'q': {'D00': 1}})
        self.assertEqual(scores['execution']['gas']['requests'], 5)
        self.assertGreaterEqual(scores['means']['gas']['quantized_energy_gap'], 0)
        self.assertEqual(scores['means']['exact_quantized']['quantized_energy_gap'], 0)
        self.assertIn('p95', scores['execution']['gas']['total_ms'])

    def test_zero_weight_reduces_to_relevance_objective(self):
        config = GASConfig(diversity_weight=0)
        problem = prepare_problem(fixture(), config)
        self.assertFalse(np.any(problem.quadratic))
        cosine = select_classical(fixture(), 'cosine', config)
        exact = select_classical(fixture(), 'exact_quantized', config)
        self.assertEqual(cosine.energy, exact.energy)

    def test_mmr_baseline_keeps_its_native_order(self):
        features = CandidateFeatures(('a', 'b', 'c'), [1., .98, .8], [[1, 0], [1, .01], [0, 1]])
        config = GASConfig(candidate_limit=3, selected_count=3, diversity_weight=.5)
        result = select_classical(features, 'mmr', config)
        self.assertEqual(result.ranked_ids, ['a', 'c', 'b'])
        self.assertEqual(result.resources['ordering_policy'], 'native MMR')


def type_from_record(record):
    from research.selection import SelectionResult
    return SelectionResult(**record)


class CommandAndArtifactTests(unittest.TestCase):
    def test_gas_dispatch_never_enters_legacy_dataset_loader(self):
        from types import SimpleNamespace
        from research import run
        with patch('research.run.load_dataset', side_effect=AssertionError('dataset access forbidden')):
            with patch('research.selection_experiment.cmd_run', return_value=Path('not-executed')) as delegated:
                self.assertEqual(run.cmd_run(SimpleNamespace(profile='gas')), Path('not-executed'))
                delegated.assert_called_once()

    def test_evaluation_and_report_dispatch_are_mocked_only(self):
        from types import SimpleNamespace
        from research import run
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'manifest.json').write_text(json.dumps({'profile': 'gas'}))
            with patch('research.artifacts.verify_manifest', side_effect=AssertionError('legacy verifier forbidden')):
                with patch('research.selection_experiment.cmd_evaluate', return_value=path) as evaluation:
                    self.assertEqual(run.cmd_evaluate(SimpleNamespace(run=directory)), path)
                    evaluation.assert_called_once()
                with patch('research.selection_experiment.cmd_report', return_value=path) as report:
                    self.assertEqual(run.cmd_report(SimpleNamespace(run=directory)), path)
                    report.assert_called_once()

    def test_cli_operates_only_on_feature_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            features = path / 'features.json'
            features.write_text(json.dumps(fixture().to_dict()))
            output = path / 'result.json'
            result = subprocess.run([sys.executable, '-m', 'research.selection_experiment', 'select',
                                     '--input', str(features), '--output', str(output)],
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output.read_text())
            self.assertEqual(len(payload['result']['ranked_ids']), 8)
            self.assertEqual(set(p.name for p in path.iterdir()), {'features.json', 'result.json'})

    def test_cli_refuses_to_overwrite_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'features.json'
            original = json.dumps(fixture().to_dict())
            path.write_text(original)
            result = subprocess.run([sys.executable, '-m', 'research.selection_experiment', 'select',
                                     '--input', str(path), '--output', str(path)],
                                    capture_output=True, text=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(path.read_text(), original)

    def test_profile_help_does_not_load_datasets_or_models(self):
        from research.run import main
        with patch('research.run.load_dataset', side_effect=AssertionError('dataset access forbidden')):
            with patch.object(sys, 'argv', ['research.run', 'run', '--help']):
                with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as result:
                    main()
                self.assertEqual(result.exception.code, 0)

    def test_artifact_tampering_and_source_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'trace.json').write_text('{}')
            manifest = {'schema': SCHEMA, 'source_hashes': {}}
            seal_run(path, manifest)
            self.assertEqual(verify_run(path)['schema'], SCHEMA)
            (path / 'trace.json').write_text('changed')
            with self.assertRaises(ValueError):
                verify_run(path)

    def test_fiqa_registration_without_reading_any_data(self):
        from research.config_frozen import DATASETS, FROZEN
        from research.datasets import canonical_dataset
        self.assertEqual(canonical_dataset('fiqa'), 'fiqa')
        self.assertEqual(DATASETS['fiqa']['test_queries'], 648)
        self.assertEqual(DATASETS['fiqa']['dev_split'], 'dev')
        self.assertEqual((FROZEN['candidate_budget'], FROZEN['qubit_cap']), (64, 18))


class SmallCircuitUnitTests(unittest.TestCase):
    def test_reference_phase_and_reflection_match_compact_state(self):
        from qiskit.quantum_info import Statevector
        from research.selection_circuits import reference_circuit

        problem = prepare_problem(fixture(4), GASConfig(candidate_limit=4, selected_count=2, coefficient_bits=3))
        layout, energies = enumerate_energies(problem)
        threshold = problem.energy(problem.cosine_order()[:2])
        addresses = [sum(1 << int(i) for i in subset) for subset in layout]
        compact = np.ones(len(layout), dtype=complex) / math.sqrt(len(layout))
        for iteration in [1, 2, 3]:
            grover_step(compact, energies < threshold)
            full = Statevector.from_instruction(reference_circuit(problem, threshold, iteration)).data
            amplitudes = full[addresses]  # work-register-zero addresses
            self.assertAlmostEqual(abs(np.vdot(compact, amplitudes)) ** 2, 1., places=10)
            self.assertAlmostEqual(float(np.sum(abs(amplitudes) ** 2)), 1., places=10)

    def test_reference_circuit_limits_are_explicit(self):
        from research.selection_circuits import reference_circuit

        with self.assertRaises(ValueError):
            reference_circuit(prepare_problem(fixture()), 0, 1)
        problem = prepare_problem(fixture(4), GASConfig(candidate_limit=4, selected_count=2))
        with self.assertRaises(ValueError):
            reference_circuit(problem, 100000, 1)


if __name__ == '__main__':
    unittest.main()
