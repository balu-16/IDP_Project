import os
import tempfile
import unittest
from pathlib import Path
import numpy as np
from config import settings
from services.vector_store import VectorStore
from services.pdf_processor import PDFProcessor
from services.retrieval import retrieve_ranked_documents, RetrievalConfig
from services.quantum_search import QuantumSearch


class ScopedVectorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = VectorStore(self.directory.name)
        self.vector = [1.0] + [0.0] * (settings.EMBEDDING_DIMENSION-1)
        self.chunk = {'id': 'same-content', 'text': 'Ownership isolation test',
            'embedding': self.vector, 'metadata': {'document_id': 'doc',
                'embedding_revision': settings.HUGGINGFACE_REVISION}}
        await self.store.add_documents([self.chunk], user_id=1, session_id='1')
        await self.store.add_documents([self.chunk], user_id=2, session_id='2')

    async def asyncTearDown(self):
        await self.store.close()
        self.directory.cleanup()

    async def test_identical_contents_do_not_overwrite_other_owners(self):
        first = await self.store.get_all_embeddings(user_id=1)
        second = await self.store.get_all_embeddings(user_id=2)
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertNotEqual(first[0]['id'], second[0]['id'])

    async def test_scope_is_applied_before_candidate_search(self):
        self.assertEqual(await self.store.candidates(self.vector, user_id=1, session_id='2'), [])
        rows = await self.store.candidates(self.vector, user_id=1, session_id='1')
        self.assertEqual(len(rows), 1)

    async def test_unscoped_reads_and_scope_filter_override_are_rejected(self):
        with self.assertRaises(ValueError):
            await self.store.get_all_embeddings()
        with self.assertRaises(ValueError):
            await self.store.candidates(self.vector, user_id=1, session_id='1', metadata={'user_id': '2'})

    async def test_delete_is_idempotent_and_preserves_other_owners(self):
        await self.store.delete_scope(user_id=1, session_id='1')
        await self.store.delete_scope(user_id=1, session_id='1')
        self.assertEqual(len(await self.store.get_all_embeddings(user_id=1)), 0)
        self.assertEqual(len(await self.store.get_all_embeddings(user_id=2)), 1)

    async def test_failed_uploads_are_excluded_from_retrieval(self):
        result = await retrieve_ranked_documents(self.vector, self.store, QuantumSearch(),
            user_id=1, session_id='1', allowed_document_ids=set())
        self.assertEqual(result['results'], [])
        self.assertEqual(result['fallback_reason'], 'no_candidates')

    async def test_cosine_score_is_one_for_identical_vectors(self):
        result = await retrieve_ranked_documents(self.vector, self.store, QuantumSearch(),
            user_id=1, session_id='1', allowed_document_ids={'doc'}, config=RetrievalConfig(strategy='closed_form'))
        self.assertAlmostEqual(result['results'][0]['cosine_score'], 1)
        self.assertGreaterEqual(result['retrieval_time_ms'], result['timings_ms']['candidate_selection'])

    async def test_incompatible_embeddings_fail_before_write(self):
        bad = {**self.chunk, 'embedding': [1, 0]}
        with self.assertRaises(ValueError):
            await self.store.add_documents([bad], user_id=1, session_id='1')


@unittest.skipUnless(os.getenv('QUBIT_TEST_PDF'), 'Set QUBIT_TEST_PDF to run against a real source PDF and model')
class RealDocumentTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_pdf_has_stable_chunks_pages_and_normalized_embeddings(self):
        processor = PDFProcessor()
        path = Path(os.environ['QUBIT_TEST_PDF'])
        first = await processor.process_pdf(path, filename=path.name)
        second = await processor.process_pdf(path, filename=path.name)
        chunks = first['embedded_chunks']
        self.assertGreater(len(chunks), 0)
        self.assertEqual([x['id'] for x in chunks], [x['id'] for x in second['embedded_chunks']])
        for chunk in chunks:
            self.assertGreaterEqual(chunk['metadata']['page_start'], 1)
            self.assertLessEqual(chunk['metadata']['token_count'], settings.CHUNK_TOKENS)
            self.assertAlmostEqual(np.linalg.norm(chunk['embedding']), 1, places=6)
            self.assertTrue(chunk['metadata']['embedding_revision'])
