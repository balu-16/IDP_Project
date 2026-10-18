"""Application contract, scope, and kernel parity; no dataset collection."""
from dataclasses import replace
import hashlib
import itertools
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import httpx
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from config import settings
from services.gas_profile import APPLICATION_GAS
from services.gas_retrieval import rank_passages
from services.gas_selector import baseline, refinement
from services.gas_selector.primitives import CandidateFeatures, grover_step
from services.l6_scorer import L6Scorer, L6Unavailable
from services.retrieval import RetrievalConfig, retrieve_ranked_documents
from services.vector_store import VectorStore
from services.quantum_search import QuantumSearch


def features(n=15):
    rng = np.random.default_rng(318)
    vectors = rng.normal(size=(n, 384))
    return baseline.ScoredFeatures(CandidateFeatures(tuple(f'p{i:02}' for i in range(n)),
        np.linspace(0.1, 0.9, n), vectors, tuple(f'Passage {i}' for i in range(n))),
        np.linspace(-8, -0.2, n))


class KernelParityTests(unittest.TestCase):
    def test_snapshot_checksums_and_frozen_kernel_parity(self):
        from research.accuracy_v2 import core as original_base
        from research.accuracy_v3 import core as original_refine
        from research.selection import CandidateFeatures as OriginalFeatures
        folder = ROOT / 'backend/services/gas_selector'
        for name, value in json.loads((folder / 'ORIGINS.json').read_text())['sources'].items():
            self.assertEqual(hashlib.sha256((ROOT / value['origin']).read_bytes()).hexdigest(), value['origin_sha256'])
            self.assertEqual(hashlib.sha256((folder / name).read_bytes()).hexdigest(), value['sha256'])
        for n in (3, 8, 12, 15):
            scored = features(n)
            original = original_base.ScoredFeatures(OriginalFeatures.from_dict(scored.candidates.to_dict()), scored.l6_logits)
            for seed in (0, 2, 4):
                app = baseline.select(scored, config=APPLICATION_GAS.baseline(), seed=seed)
                old = original_base.select(original, config=original_base.Config(**app.config), seed=seed)
                self.assertEqual(app.ranked_ids, old.ranked_ids)
                self.assertEqual(app.counts, old.counts)
                actual = refinement.select(scored, app.ranked_ids, seed=seed)
                wanted = original_refine.select(original, old.ranked_ids, seed=seed)
                self.assertEqual(actual.ranked_ids, wanted.ranked_ids)
                self.assertEqual(actual.energy, wanted.energy)
                self.assertEqual(actual.counts, wanted.counts)

    def test_prefix_feasibility_reproducibility_and_budgets(self):
        scored = features()
        for seed in range(5):
            base = baseline.select(scored, config=APPLICATION_GAS.baseline(), seed=seed)
            result = refinement.select(scored, base.ranked_ids, seed=seed)
            repeat = refinement.select(scored, base.ranked_ids, seed=seed)
            self.assertEqual(result.ranked_ids, repeat.ranked_ids)
            self.assertEqual(result.ranked_ids[:5], base.ranked_ids[:5])
            self.assertEqual(len(set(result.ranked_ids)), 8)
            z = dict(zip(scored.candidates.ids, scored.l6_logits))
            self.assertTrue(np.all(np.sort([z[d] for d in result.ranked_ids[5:]]) >=
                                   np.sort([z[d] for d in base.ranked_ids[5:]]) - 1e-12))
            self.assertLessEqual(result.redundancy, base.redundancy + 1e-12)
            self.assertLessEqual(result.counts['phase_oracle_calls'], 64)
            self.assertLessEqual(result.counts['measured_trials'], 32)
            for item in result.trace:
                self.assertAlmostEqual(item['state_norm'], 1)
                if item['accepted']:
                    self.assertLess(item['energy_after'], item['energy_before'])
                    self.assertLess(item['redundancy_after'], item['redundancy_before'])
            stopped = refinement.select(scored, base.ranked_ids,
                config=replace(APPLICATION_GAS.refinement(), max_oracle_calls=0), seed=seed)
            self.assertEqual(stopped.ranked_ids, base.ranked_ids)
            self.assertEqual(stopped.counts['phase_oracle_calls'], 0)
        # A strict-score fixture can leave only the baseline feasible, which
        # correctly reports trivial_basis before consulting the phase budget.
        tied = baseline.ScoredFeatures(scored.candidates, np.full(15, -4.0))
        stopped = refinement.select(tied, list(tied.candidates.ids[:8]),
            config=replace(APPLICATION_GAS.refinement(), max_oracle_calls=0))
        self.assertEqual(stopped.status, 'oracle_budget')
        self.assertEqual(stopped.ranked_ids, list(tied.candidates.ids[:8]))

    def test_phase_reflection_and_independent_small_objective(self):
        state = np.full(4, 0.5, dtype=np.complex128)
        grover_step(state, np.array([True, False, False, False]))
        np.testing.assert_allclose(state, [1, 0, 0, 0])
        scored = features(10)
        base = [f'p{i:02}' for i in (9, 8, 7, 6, 5, 0, 1, 2)]
        result = refinement.select(scored, base, method='exact_float_v3')
        ids, logits = scored.candidates.ids, dict(zip(scored.candidates.ids, scored.l6_logits))
        vectors = dict(zip(ids, scored.candidates.embeddings))
        def redundancy(chosen):
            return np.mean([np.clip(vectors[a] @ vectors[b], 0, 1)
                            for a, b in itertools.combinations(chosen, 2)])
        tail_scores = sorted(logits[d] for d in base[5:])
        values = [redundancy(base[:5] + list(tail))
                  for tail in itertools.combinations([d for d in ids if d not in base[:5]], 3)
                  if all(a >= b - 1e-12 for a, b in zip(sorted(logits[d] for d in tail), tail_scores))]
        self.assertAlmostEqual(result.redundancy, min(values))

    def test_nontrivial_search_performs_phase_calls_and_strict_updates(self):
        vectors = np.zeros((12, 384))
        vectors[:8, 0] = 1
        for i in range(8, 12):
            vectors[i, i-7] = 1
        scored = baseline.ScoredFeatures(CandidateFeatures(tuple(f'p{i:02}' for i in range(12)),
            np.zeros(12), vectors), np.full(12, -4.0))
        base = list(scored.candidates.ids[:8])
        result = refinement.select(scored, base)
        self.assertGreater(result.counts['phase_oracle_calls'], 0)
        self.assertGreater(result.counts['accepted_updates'], 0)
        self.assertLess(result.redundancy, 1)
        self.assertEqual(result.ranked_ids[:5], base[:5])

    def test_constant_negative_ties_invalid_scores_and_zero_penalty(self):
        scored = features()
        for logits in (np.full(15, -4.0), -np.arange(15, dtype=float)):
            values = baseline.ScoredFeatures(scored.candidates, logits)
            a = baseline.select(values, config=replace(APPLICATION_GAS.baseline(), diversity_weight=0))
            b = baseline.select(values, method='l6_only', config=APPLICATION_GAS.baseline())
            self.assertEqual(a.ranked_ids, b.ranked_ids)
        self.assertTrue(np.all(baseline.normalize_relevance(np.full(15, -4.0)) == 0.5))
        for invalid in (np.full(15, np.nan), np.full(15, np.inf), np.zeros(14)):
            with self.assertRaises(ValueError):
                baseline.ScoredFeatures(scored.candidates, invalid)
        for n in range(1, 9):
            values = features(n)
            base = baseline.select(values, config=APPLICATION_GAS.baseline())
            result = refinement.select(values, base.ranked_ids)
            self.assertEqual(len(result.ranked_ids), n)
            self.assertEqual(result.ranked_ids, base.ranked_ids)


class FakeScorer:
    def __init__(self):
        self.calls = []

    def score(self, query, passages):
        self.calls.append(list(passages))
        return np.array([-float(text.split('|')[0]) for text in passages]), {
            'model_loading_ms': 0., 'model_warmup_ms': 0., 'l6_queue_ms': 0., 'inference_ms': 0.}


def passage_rows(n=35):
    scored = features(n)
    return [{'id': f'p{i:02}', 'document': f'{i}| ' + ('specific topic ' * 10 if i > 25 else 'general evidence'),
             'embedding': scored.candidates.embeddings[i].tolist(),
             'metadata': {'document_id': 'ready', 'page_start': i + 1, 'file_name': 'example.pdf'}}
            for i in range(n)]


class PipelineTests(unittest.TestCase):
    def test_original_logits_are_not_rescored_and_prefix_and_citations_survive(self):
        rows, scorer = passage_rows(), FakeScorer()
        result = rank_passages('specific topic', rows[0]['embedding'], rows, scorer=scorer)
        original, extra = scorer.calls
        self.assertEqual(len(original), 15)
        self.assertTrue(set(original).isdisjoint(extra))
        self.assertGreater(len(extra), 0)
        self.assertEqual(len(result['results']), 8)
        self.assertEqual([r['id'] for r in result['results'][:5]],
                         result['quantum']['baseline']['ranked_ids'][:5])
        for row in result['results']:
            self.assertEqual(row['l6_logit'], -float(row['document'].split('|')[0]))
            self.assertEqual(row['rank_score'], row['l6_logit'])
            self.assertIsNone(row['sampling_probability'])
            self.assertEqual(row['metadata']['file_name'], 'example.pdf')
        self.assertGreaterEqual(result['ranking_time_ms'], sum(result['timings_ms'].values()))

    def test_empty_pool_does_not_load_model_and_invalid_inputs_are_rejected(self):
        scorer = FakeScorer()
        result = rank_passages('question', [1.] * 384, [], scorer=scorer)
        self.assertEqual(result['fallback_reason'], 'no_candidates')
        self.assertEqual(scorer.calls, [])
        rows = passage_rows(3)
        for bad_rows, query, vector in ((rows + [rows[0]], 'q', rows[0]['embedding']),
                                         (rows, '', rows[0]['embedding']), (rows, 'q', [0.] * 384)):
            with self.assertRaises(ValueError):
                rank_passages(query, vector, bad_rows, scorer=scorer)

    def test_config_keeps_legacy_defaults_and_enforces_fixed_gas_shape(self):
        self.assertEqual(RetrievalConfig().top_k, 5)
        self.assertEqual(RetrievalConfig(strategy='l6_gas').top_k, 8)
        for args in ({'top_k': 5}, {'candidate_limit': 32}, {'seed': -1}):
            with self.assertRaises(ValueError):
                RetrievalConfig(strategy='l6_gas', **args)

    def test_l6_token_budget_and_invalid_output(self):
        class Model:
            length = 513
            def tokenizer(self, queries, passages, **kwargs):
                return {'input_ids': [[0] * self.length for _ in passages]}
            def predict(self, pairs, **kwargs):
                return [float('nan')] * len(pairs)
        scorer = L6Scorer()
        scorer._model = Model()
        with self.assertRaises(ValueError):
            scorer.score('q', ['passage'])
        scorer._model.length = 10
        with self.assertRaises(L6Unavailable):
            scorer.score('q', ['passage'])
        with patch.object(scorer, '_load', side_effect=L6Unavailable('unavailable')):
            with self.assertRaises(L6Unavailable):
                scorer.score('q', ['passage'])


class ScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_lifecycle_owner_and_session_filters_precede_top64(self):
        with tempfile.TemporaryDirectory() as directory:
            store = VectorStore(directory)
            vector = [1.] + [0.] * 383
            def chunk(identifier, doc):
                return {'id': identifier, 'text': '0| general evidence', 'embedding': vector,
                        'metadata': {'document_id': doc, 'embedding_revision': settings.HUGGINGFACE_REVISION}}
            await store.add_documents([chunk(str(i), 'stale') for i in range(70)] + [chunk('ready', 'ready')], user_id=1, session_id='1')
            await store.add_documents([chunk('other-user', 'ready')], user_id=2, session_id='1')
            await store.add_documents([chunk('other-session', 'ready')], user_id=1, session_id='2')
            rows = await store.candidates(vector, user_id=1, session_id='1', limit=1, allowed_document_ids={'ready'})
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['metadata']['document_id'], 'ready')
            with patch('services.gas_retrieval.get_l6_scorer', return_value=FakeScorer()):
                result = await retrieve_ranked_documents(vector, store, QuantumSearch(),
                    user_id=1, session_id='1', query_text='evidence', allowed_document_ids={'ready'},
                    config=RetrievalConfig(strategy='l6_gas'))
            self.assertEqual(len(result['results']), 1)
            self.assertEqual(result['results'][0]['metadata']['user_id'], '1')
            self.assertEqual(result['quantum']['eligible_passages'], 1)
            await store.close()


class APITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from main import app
        from services.database import get_identity, get_database_service, Identity
        from services.shared import get_pdf_processor, get_quantum_search, get_vector_store
        self.app, self.saved = app, {}
        rows = passage_rows(12)
        class DB:
            async def require_session(db, session_id, identity):
                return {'id': 1, 'user_id': 1, 'chat_name': 'Existing chat'}
            async def uploaded_files(db, identity, session_id):
                return [{'document_id': 'ready', 'status': 'ready'}, {'document_id': 'stale', 'status': 'failed'}]
            async def history(db, session_id, identity):
                return []
            async def request(db, method, path, **kwargs):
                if method == 'POST':
                    data = kwargs['json']
                    self.saved[data['run_id']] = data
                    return None
                run_id = kwargs['params']['run_id'][3:]
                return [self.saved[run_id]] if run_id in self.saved else []
        class PDF:
            async def embed_query(pdf, query):
                return rows[0]['embedding']
        class Store:
            async def get_all_embeddings(store, **kwargs):
                assert kwargs['user_id'] == 1 and kwargs['session_id'] == '1'
                assert kwargs['allowed_document_ids'] == {'ready'}
                return rows + [{**rows[0], 'id': 'stale', 'metadata': {'document_id': 'stale'}}]
        self.previous_overrides = app.dependency_overrides.copy()
        app.dependency_overrides.update({get_identity: lambda: Identity(1, 'verified-user', {}),
            get_database_service: lambda: DB(), get_pdf_processor: lambda: PDF(),
            get_vector_store: lambda: Store(), get_quantum_search: lambda: QuantumSearch()})
        self.scorer = patch('services.gas_retrieval.get_l6_scorer', return_value=FakeScorer())
        self.scorer.start()
        self.generator = patch('routes.chat_routes.generate_answer', new=AsyncMock(return_value='Answer [S1]'))
        self.generator.start()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test')

    async def asyncTearDown(self):
        await self.client.aclose()
        self.generator.stop()
        self.scorer.stop()
        self.app.dependency_overrides.clear()
        self.app.dependency_overrides.update(self.previous_overrides)

    async def test_both_endpoints_and_persisted_idempotent_provenance(self):
        response = await self.client.post('/api/v1/query', json={'query': 'evidence', 'session_id': '1',
            'retrieval': {'strategy': 'l6_gas'}})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['results_count'], 8)
        self.assertEqual(response.json()['search_method'], 'l6_gas')
        request = {'message': 'evidence', 'session_id': '1',
            'run_id': '00000000-0000-4000-8000-000000000001', 'retrieval': {'strategy': 'l6_gas'}}
        chat = await self.client.post('/api/chat', json=request)
        self.assertEqual(chat.status_code, 200, chat.text)
        data = chat.json()
        self.assertEqual(data['metadata']['retrieval_method'], 'l6_gas')
        self.assertEqual(len(data['context_sources']), 8)
        self.assertEqual(data['context_sources'][0]['metadata']['file_name'], 'example.pdf')
        self.assertIn('baseline', data['metadata']['quantum'])
        self.assertIn('refinement', data['metadata']['quantum'])
        retry = await self.client.post('/api/chat', json=request)
        self.assertEqual(retry.json(), data)
        self.assertEqual(len(self.saved), 1)

    async def test_unavailable_model_returns_503_without_persisting_an_answer(self):
        with patch('services.gas_retrieval.get_l6_scorer', side_effect=L6Unavailable('not cached')):
            for path, body in (('/api/v1/query', {'query': 'q'}), ('/api/chat', {'message': 'q'})):
                response = await self.client.post(path, json={**body, 'session_id': '1',
                    'retrieval': {'strategy': 'l6_gas'}})
                self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(self.saved, {})


@unittest.skipUnless(os.getenv('QUBIT_TEST_L6') == '1', 'Set QUBIT_TEST_L6=1 after FiQA timing finishes')
class LocalL6Smoke(unittest.TestCase):
    def test_pinned_local_inference(self):
        scorer = L6Scorer()
        scores, timing = scorer.score('What is the evidence?',
            ['The study reports scientific evidence.', 'A bank account contains savings.'])
        self.assertEqual(len(scores), 2)
        self.assertTrue(np.isfinite(scores).all())
        self.assertGreater(timing['inference_ms'], 0)


if __name__ == '__main__':
    unittest.main()
