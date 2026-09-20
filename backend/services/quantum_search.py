"""Controlled ranking experiments, not a claim of quantum retrieval speedup."""
import time
import numpy as np
from config import settings
from services.circuits import (ResourceLimitError, parameters, ideal_probabilities,
                               phase_oracle, diffuser, grover_circuit)
from services.workers import run_blocking


def normalized_matrix(values, dimension=None):
    matrix = np.asarray(values, dtype=np.float64)
    if matrix.ndim != 2 or not matrix.shape[1] or not np.isfinite(matrix).all():
        raise ValueError('Embeddings must be a finite two-dimensional matrix')
    if dimension is not None and matrix.shape[1] != dimension:
        raise ValueError('Embedding dimension mismatch; rebuild the versioned index')
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    if np.any(norms <= 1e-12):
        raise ValueError('Zero embeddings cannot be used for cosine retrieval')
    return matrix / norms


class QuantumSearch:
    def __init__(self):
        self.max_qubits = settings.QUANTUM_MAX_QUBITS
        self.quantum_shots = settings.QUANTUM_SHOTS
        self._compiled_cache = {}

    def _calculate_similarity_scores(self, query_embedding, document_embeddings):
        query = normalized_matrix([query_embedding])[0]
        docs = normalized_matrix(document_embeddings, len(query))
        return np.clip(docs @ query, -1, 1)

    _create_oracle = staticmethod(phase_oracle)
    _create_diffuser = staticmethod(diffuser)

    def distribution(self, num_items, marked_items, method='grover', shots=None, seed=None):
        start = time.perf_counter()
        qubits, space, marked, iterations = parameters(num_items, marked_items)
        shots = self.quantum_shots if shots is None else shots
        seed = settings.QUANTUM_SEED if seed is None else seed
        if shots < 1 or seed < 0:
            raise ValueError('Shots must be positive and seed nonnegative')
        timings = {'oracle_build_ms': 0.0, 'transpile_ms': 0.0, 'sampling_ms': 0.0}
        # Classical controls must not inherit artificial quantum limits (plan A.1).
        if method in {'closed_form', 'classical_sampling'}:
            probabilities = ideal_probabilities(num_items, marked, iterations)
            if method == 'classical_sampling':
                probabilities = np.random.default_rng(seed).multinomial(shots, probabilities) / shots
            timings['sampling_ms'] = (time.perf_counter()-start)*1000
            return probabilities, {'address_qubits': qubits, 'work_qubits': 0,
                                   'total_qubits': qubits, 'state_space': space,
                                   'marked_count': len(marked), 'iterations': iterations,
                                   'oracle_calls': iterations,
                                   'shots': shots if method != 'closed_form' else None, 'seed': seed,
                                   'padded_probability': float(probabilities[num_items:].sum()),
                                   'marked_probability': float(probabilities[marked].sum()) if marked else 0.0,
                                   'logical_depth': 0, 'gate_counts': {},
                                   'basis_gates': [], 'transpilation_config': {'method': method},
                                   'output_distribution_bytes': int(probabilities.nbytes),
                                   'estimated_statevector_bytes': int(space * 16),
                                   'memory_note': ('classical control: no circuit; bytes are output array only'),
                                   'timings_ms': timings}
        if method != 'grover':
            raise ValueError('Unknown distribution method')
        # Simulator limits apply only to quantum execution.
        if qubits > self.max_qubits:
            raise ResourceLimitError('too_many_documents')
        if iterations > settings.QUANTUM_MAX_ITERATIONS:
            raise ResourceLimitError('iteration_limit')
        from qiskit import transpile
        from qiskit_aer import AerSimulator
        circuit = grover_circuit(num_items, marked, iterations)
        circuit.measure_all()
        timings['oracle_build_ms'] = (time.perf_counter()-start)*1000
        simulator = AerSimulator(max_parallel_threads=settings.CPU_THREADS)
        # Fixed universal 1-/2-qubit basis so gate counts are honest (issue 9):
        # Aer-native transpilation retains mcx and reports zero 2q gates.
        basis_gates = ["u", "cx"]
        cache_key = (num_items, tuple(marked), iterations, tuple(basis_gates))
        compiled = self._compiled_cache.get(cache_key)
        if compiled is None:
            clock = time.perf_counter()
            compiled = transpile(circuit, simulator, basis_gates=basis_gates,
                                 seed_transpiler=seed, optimization_level=1)
            timings['transpile_ms'] = (time.perf_counter()-clock)*1000
            self._compiled_cache[cache_key] = compiled
            transpilation_cached = False
        else:
            timings['transpile_ms'] = 0.0
            transpilation_cached = True
        clock = time.perf_counter()
        counts = simulator.run(compiled, shots=shots, seed_simulator=seed).result().get_counts()
        probabilities = np.zeros(space)
        for bits, count in counts.items():
            probabilities[int(bits.replace(' ', ''), 2)] = count/shots
        timings['sampling_ms'] = (time.perf_counter()-clock)*1000
        try:
            ops = dict(compiled.count_ops())
            depth = int(compiled.depth())
            basis = sorted(ops.keys())
            one_q = sum(v for k, v in ops.items() if k in {'u', 'u1', 'u2', 'u3', 'rx', 'ry', 'rz', 'h', 'x', 'y', 'z', 's', 't', 'id', 'p', 'sx'})
            two_q = sum(v for k, v in ops.items() if k in {'cx', 'cz', 'swap', 'ecr', 'cp'})
        except Exception:
            ops, depth, basis, one_q, two_q = {}, 0, [], 0, 0
        return probabilities, {'address_qubits': qubits, 'work_qubits': 0,
                               'total_qubits': qubits, 'state_space': space,
                               'marked_count': len(marked), 'iterations': iterations,
                               'oracle_calls': iterations,
                               'shots': shots, 'seed': seed,
                               'padded_probability': float(probabilities[num_items:].sum()),
                               'marked_probability': float(probabilities[marked].sum()) if marked else 0.0,
                               'logical_depth': depth, 'gate_counts': ops,
                               'one_qubit_gates': int(one_q), 'two_qubit_gates': int(two_q),
                               'basis_gates': basis_gates,
                               'transpilation_config': {'backend': 'AerSimulator', 'optimization_level': 1,
                                                       'basis_gates': basis_gates,
                                                       'seed_transpiler': seed,
                                                       'cached': transpilation_cached,
                                                       'cpu_threads': settings.CPU_THREADS},
                               'output_distribution_bytes': int(probabilities.nbytes),
                               'estimated_statevector_bytes': int(space * 16),
                               'memory_note': ('output_distribution_bytes is the returned array only; '
                                               'estimated_statevector_bytes assumes complex128 statevector; '
                                               'simulator peak RSS not measured'),
                               'timings_ms': timings}

    def _run_grovers_algorithm(self, num_items, marked_items):
        probabilities, _ = self.distribution(num_items, marked_items)
        return dict(enumerate(probabilities[:num_items].tolist()))

    def rank_scores(self, documents, scores, method='cosine', top_k=5, threshold=0.5,
                    shots=None, seed=None, boost=None):
        start = time.perf_counter()
        if method not in {'cosine', 'grover', 'closed_form', 'classical_sampling'}:
            raise ValueError('Unknown ranking method')
        if top_k < 1 or not 0 <= threshold <= 1:
            raise ValueError('Invalid ranking configuration')
        raw = np.asarray(scores, dtype=float)
        if raw.ndim != 1 or len(documents) != len(raw) or not np.isfinite(raw).all():
            raise ValueError('Each candidate requires a finite score')
        if not documents:
            return {'results': [], 'search_method': 'none', 'requested_search_method': method,
                    'fallback_reason': 'no_candidates', 'quantum': None, 'ranking_time_ms': 0.0}
        # Singleton needs no Grover circuit (plan A.1): rank directly, record fallback.
        if len(documents) == 1 and method != 'cosine':
            raw_one = float(raw[0])
            doc = documents[0]
            return {'results': [{'id': str(doc['id']), 'document': doc.get('document', doc.get('text', '')),
                                 'metadata': doc.get('metadata', {}), 'cosine_score': raw_one,
                                 'similarity_score': raw_one, 'rank_score': raw_one,
                                 'sampling_probability': None, 'search_method': 'cosine'}],
                    'search_method': 'cosine', 'requested_search_method': method,
                    'fallback_reason': 'singleton_no_circuit', 'quantum': None,
                    'ranking_time_ms': (time.perf_counter()-start)*1000}
        probabilities = np.zeros(len(documents))
        ranks = raw.copy()
        actual, fallback, report = method, None, None
        if method != 'cosine':
            # Use signed cosine for marking: negatives are never marked at threshold >= 0.
            marked = np.flatnonzero(raw >= threshold).tolist()
            if not marked:
                actual, fallback = 'cosine', 'no_marked_items'
            else:
                try:
                    distribution, report = self.distribution(len(documents), marked, method, shots, seed)
                    probabilities = distribution[:len(documents)]
                    factor = settings.QUANTUM_BOOST_FACTOR if boost is None else boost
                    if factor < 0 or not np.isfinite(factor):
                        raise ValueError('Boost must be finite and nonnegative')
                    # Signed rule: rank = cosine + boost * max(cosine,0) * prob.
                    # Negatives stay negative; ordering among negatives never changes
                    # merely because a quantum method was selected.
                    ranks = raw + factor * np.maximum(raw, 0) * probabilities
                except ResourceLimitError as exc:
                    actual, fallback = 'cosine', str(exc)
        order = sorted(range(len(documents)), key=lambda i: (-ranks[i], str(documents[i]['id'])))[:top_k]
        results = []
        for i in order:
            doc = documents[i]
            results.append({'id': str(doc['id']), 'document': doc.get('document', doc.get('text', '')),
                            'metadata': doc.get('metadata', {}), 'cosine_score': float(raw[i]),
                            'similarity_score': float(raw[i]), 'rank_score': float(ranks[i]),
                            'sampling_probability': float(probabilities[i]) if actual != 'cosine' else None,
                            'search_method': actual})
        return {'results': results, 'search_method': actual, 'requested_search_method': method,
                'fallback_reason': fallback, 'quantum': report,
                'ranking_time_ms': (time.perf_counter()-start)*1000}

    async def quantum_enhanced_search(self, query_embedding, document_embeddings,
                                      similarity_threshold=0.5, top_k=5, **kwargs):
        if not document_embeddings:
            return self.rank_scores([], [], method='grover', top_k=top_k)
        scores = await run_blocking(self._calculate_similarity_scores, query_embedding,
                                    [x['embedding'] for x in document_embeddings])
        return await run_blocking(self.rank_scores, document_embeddings, scores,
                                  method='grover', top_k=top_k, threshold=similarity_threshold, **kwargs)

    async def classical_similarity_search(self, query_embedding, document_embeddings, top_k=5, **kwargs):
        if not document_embeddings:
            return self.rank_scores([], [], top_k=top_k)
        scores = await run_blocking(self._calculate_similarity_scores, query_embedding,
                                    [x['embedding'] for x in document_embeddings])
        return await run_blocking(self.rank_scores, document_embeddings, scores, top_k=top_k)
