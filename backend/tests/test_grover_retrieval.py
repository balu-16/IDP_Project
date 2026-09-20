"""Mathematical regression cases; these are not benchmark relevance judgments."""
import unittest
import numpy as np
from qiskit.quantum_info import Operator, Statevector
from services.circuits import (parameters, phase_oracle, grover_circuit,
    ideal_probabilities, score_oracle, ResourceLimitError)
from services.quantum_search import QuantumSearch, normalized_matrix


class GroverCorrectnessTests(unittest.TestCase):
    def test_every_small_basis_state_marks_the_intended_little_endian_index(self):
        for qubits in range(1, 5):
            for target in range(2**qubits):
                diagonal = np.diag(Operator(phase_oracle([target], qubits)).data)
                expected = np.ones(2**qubits)
                expected[target] = -1
                np.testing.assert_allclose(diagonal, expected, atol=1e-10)

    def test_non_power_of_two_and_dense_cases_match_theory(self):
        for size in (1, 2, 3, 4, 5, 8, 9, 16):
            for marked in ([], [0], list(range(size)), list(range(0, size, 2))):
                with self.subTest(size=size, marked=marked):
                    actual = Statevector.from_instruction(grover_circuit(size, marked)).probabilities()
                    np.testing.assert_allclose(actual, ideal_probabilities(size, marked), atol=1e-10)

    def test_dense_marking_allows_zero_iterations(self):
        self.assertEqual(parameters(4, [0, 1, 2])[-1], 0)
        self.assertAlmostEqual(ideal_probabilities(4, [0, 1, 2])[:3].sum(), .75)

    def test_iteration_count_is_not_silently_capped_at_ten(self):
        self.assertEqual(parameters(1024, [1])[-1], 25)

    def test_padding_mass_is_retained(self):
        probs = ideal_probabilities(5, [3])
        self.assertEqual(len(probs), 8)
        self.assertAlmostEqual(sum(probs), 1)
        self.assertGreater(probs[5:].sum(), 0)

    def test_invalid_marked_indices_are_rejected(self):
        for indices in ([-1], [4], [1.5]):
            with self.assertRaises(ValueError):
                parameters(4, indices)

    def test_duplicate_marking_does_not_cancel_a_phase(self):
        np.testing.assert_allclose(Operator(phase_oracle([1, 1], 2)).data,
                                   Operator(phase_oracle([1], 2)).data)

    def test_resource_exhaustion_is_explicit(self):
        search = QuantumSearch()
        search.max_qubits = 2
        with self.assertRaises(ResourceLimitError):
            search.distribution(5, [1])

    def test_aer_sampling_is_seeded_and_preserves_index(self):
        search = QuantumSearch()
        first, report = search.distribution(4, [1], seed=42)
        second, _ = search.distribution(4, [1], seed=42)
        np.testing.assert_array_equal(first, second)
        np.testing.assert_allclose(first, [0, 1, 0, 0])
        self.assertEqual(report['padded_probability'], 0)

    def test_classical_sampling_has_same_distribution_in_aggregate(self):
        search = QuantumSearch()
        probabilities, _ = search.distribution(8, [1], method='classical_sampling', shots=100_000, seed=42)
        np.testing.assert_allclose(probabilities, ideal_probabilities(8, [1]), atol=.005)

    def test_rank_boost_keeps_raw_cosine_and_separate_score(self):
        documents = [{'id': str(i), 'document': 'basis case'} for i in range(4)]
        result = QuantumSearch().rank_scores(documents, [.1, 1, .6, .2], 'closed_form', threshold=.9)
        self.assertEqual(result['results'][0]['id'], '1')
        self.assertEqual(result['results'][0]['cosine_score'], 1)
        self.assertEqual(result['results'][0]['rank_score'], 3)

    def test_ideal_boost_preserves_positive_cosine_ranking(self):
        documents = [{'id': str(i)} for i in range(16)]
        scores = np.random.default_rng(7).uniform(.01, 1, 16)
        search = QuantumSearch()
        expected = search.rank_scores(documents, scores, top_k=16)
        for threshold in (.3, .5, .7):
            actual = search.rank_scores(documents, scores, 'closed_form', top_k=16, threshold=threshold)
            self.assertEqual([x['id'] for x in actual['results']], [x['id'] for x in expected['results']])

    def test_zero_nonfinite_and_mismatched_vectors_fail(self):
        for matrix in ([[0, 0]], [[float('nan'), 1]], [[float('inf'), 1]]):
            with self.assertRaises(ValueError):
                normalized_matrix(matrix)
        with self.assertRaises(ValueError):
            QuantumSearch()._calculate_similarity_scores([1, 0], [[1, 0, 0]])

    def test_signed_cosine_is_preserved(self):
        np.testing.assert_allclose(
            QuantumSearch()._calculate_similarity_scores([1, 0], [[-1, 0], [1, 0]]), [-1, 1])

    def test_negative_scores_keep_signed_rank_and_order(self):
        documents = [{'id': str(i)} for i in range(4)]
        scores = [-0.8, -0.2, 0.3, 0.9]
        result = QuantumSearch().rank_scores(documents, scores, 'closed_form', top_k=4, threshold=0.5)
        by_id = {r['id']: r for r in result['results']}
        # Negatives stay negative: rank == cosine when cosine < 0.
        self.assertAlmostEqual(by_id['0']['rank_score'], -0.8)
        self.assertAlmostEqual(by_id['1']['rank_score'], -0.2)
        # Negatives never outranked due to quantum path; order among negatives unchanged.
        ids = [r['id'] for r in result['results']]
        self.assertLess(ids.index('1'), ids.index('0'))
        # Threshold 0 must not mark negatives.
        marked_result = QuantumSearch().rank_scores(
            [{'id': 'a'}, {'id': 'b'}], [-0.5, 0.1], 'closed_form', top_k=2, threshold=0.0)
        self.assertEqual(marked_result['quantum']['marked_count'], 1)

    def test_singleton_needs_no_circuit(self):
        result = QuantumSearch().rank_scores([{'id': 'only'}], [0.9], 'grover', threshold=0.5)
        self.assertEqual(result['search_method'], 'cosine')
        self.assertEqual(result['fallback_reason'], 'singleton_no_circuit')
        self.assertIsNone(result['quantum'])
        self.assertAlmostEqual(result['results'][0]['rank_score'], 0.9)

    def test_classical_controls_ignore_quantum_qubit_limits(self):
        search = QuantumSearch()
        search.max_qubits = 2
        # Grover still limited.
        with self.assertRaises(ResourceLimitError):
            search.distribution(5, [1], method='grover')
        # Classical controls bypass artificial limits (plan A.1).
        probs, report = search.distribution(5, [1], method='closed_form')
        self.assertEqual(len(probs), 8)
        self.assertEqual(report['marked_count'], 1)
        probs, _ = search.distribution(5, [1], method='classical_sampling', shots=100, seed=0)
        self.assertAlmostEqual(float(probs.sum()), 1.0)

    def test_zero_iteration_builds_no_oracle(self):
        circuit = grover_circuit(4, [0, 1, 2])
        # H-only: depth 1, no mcx/u phase structure.
        self.assertEqual(circuit.depth(), 1)
        probs, report = QuantumSearch().distribution(4, [0, 1, 2], method='grover', shots=1024, seed=0)
        self.assertEqual(report['iterations'], 0)
        self.assertEqual(report['oracle_calls'], 0)
        self.assertEqual(report['timings_ms']['oracle_build_ms'], report['timings_ms']['oracle_build_ms'])

    def test_resource_report_exports_depth_gates_and_calls(self):
        _, report = QuantumSearch().distribution(4, [1], method='grover', shots=64, seed=0)
        self.assertIn('logical_depth', report)
        self.assertIn('gate_counts', report)
        self.assertIn('oracle_calls', report)
        self.assertIn('transpilation_config', report)
        self.assertEqual(report['oracle_calls'], report['iterations'])
        self.assertGreater(report['logical_depth'], 0)


class ReversibleOracleTests(unittest.TestCase):
    def test_lookup_comparison_and_uncomputation_on_every_address(self):
        scores = [.1, .8, .4, 1.0, .0]
        for threshold in (0, .5, 1):
            oracle, meta = score_oracle(scores, 3, threshold)
            for address in range(meta['space']):
                state = Statevector.from_int(address, 2**meta['total_qubits']).evolve(oracle)
                expected = np.zeros(2**meta['total_qubits'], dtype=complex)
                expected[address] = -1 if address in meta['marked_indices'] else 1
                np.testing.assert_allclose(state.data, expected, atol=1e-9)

    def test_address_only_diffusion_leaves_work_registers_zero(self):
        oracle, meta = score_oracle([.1, .8, .4, 1], 3, .5)
        circuit = grover_circuit(4, meta['marked_indices'], oracle=oracle)
        probabilities = Statevector.from_instruction(circuit).probabilities()
        self.assertLess(probabilities[4:].sum(), 1e-12)
        np.testing.assert_allclose(probabilities[:4], ideal_probabilities(4, meta['marked_indices']), atol=1e-9)

    def test_work_qubit_oracle_amplifies_single_marked(self):
        # Issue 4: 4 candidates, 1 marked, 1 iteration must reach ~100%.
        oracle, meta = score_oracle([0.0, 0.0, 0.0, 1.0], 3, 0.5)
        self.assertEqual(meta['marked_indices'], [3])
        circuit = grover_circuit(4, [3], oracle=oracle)
        probabilities = Statevector.from_instruction(circuit).probabilities()
        self.assertLess(probabilities[4:].sum(), 1e-12)
        self.assertAlmostEqual(float(probabilities[:4][3]), 1.0, places=6)

    def test_resource_basis_is_one_and_two_qubit(self):
        _, report = QuantumSearch().distribution(4, [1], method='grover', shots=64, seed=0)
        self.assertEqual(sorted(report['transpilation_config']['basis_gates']), ['cx', 'u'])
        self.assertNotIn('mcx', report['gate_counts'])
        self.assertIn('output_distribution_bytes', report)
        self.assertNotIn('memory_bytes', report)

    def test_total_qubit_guard_includes_work_registers(self):
        with self.assertRaises(ResourceLimitError):
            score_oracle([.1, .8, .4, 1], 6, .5, max_qubits=8)

    def test_quantization_decisions_are_exposed(self):
        _, meta = score_oracle([.49, .5], 3, .5)
        self.assertEqual(meta['quantized_scores'], [3, 4])
        self.assertEqual(meta['marked_indices'], [1])
