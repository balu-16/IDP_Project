import asyncio
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DEBUG", "false")

from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.chat_routes as chat_routes_module
from routes.chat_routes import router as chat_router
from routes.query_routes import router as query_router
from services.quantum_search import QuantumSearch
from services.retrieval import retrieve_ranked_documents
from services.shared import get_pdf_processor, get_quantum_search, get_vector_store


BACKEND_DIR = Path(__file__).resolve().parents[1]


def build_test_documents(count: int, session_id: str = "session-1", user_id: str = "1"):
    documents = []
    for index in range(count):
        embedding = [0.0] * count
        embedding[index] = 1.0
        documents.append(
            {
                "id": str(index),
                "embedding": embedding,
                "document": f"doc-{index}",
                "metadata": {
                    "filename": f"doc-{index}.pdf",
                    "session_id": session_id,
                    "user_id": user_id,
                },
            }
        )
    return documents


class FakeVectorStore:
    def __init__(self, documents):
        self.documents = list(documents)

    async def get_collection_stats(self):
        return {
            "has_data": bool(self.documents),
            "total_documents": len(self.documents),
        }

    async def get_all_embeddings(self, session_id=None, user_id=None):
        if session_id is None and user_id is None:
            return list(self.documents)

        return [
            document
            for document in self.documents
            if (
                (session_id is None or document.get("metadata", {}).get("session_id") == session_id)
                and (
                    user_id is None
                    or str(document.get("metadata", {}).get("user_id")) == str(user_id)
                )
            )
        ]


class FakePDFProcessor:
    def __init__(self, embedding, delay=0.0):
        self.embedding = list(embedding)
        self.delay = delay
        self.embedding_config = {"model": "test-model"}

    async def embed_query(self, query):
        if self.delay:
            await asyncio.sleep(self.delay)
        return list(self.embedding)


class RetrievalTimingTests(unittest.IsolatedAsyncioTestCase):
    async def test_quantum_search_returns_expected_top_result(self):
        quantum_search = QuantumSearch()
        documents = build_test_documents(4)

        result = await quantum_search.quantum_enhanced_search(
            query_embedding=[1.0, 0.0, 0.0, 0.0],
            document_embeddings=documents,
            similarity_threshold=0.1,
            top_k=1,
        )

        self.assertEqual(result["search_method"], "quantum_enhanced")
        self.assertEqual(result["results"][0]["id"], "0")
        self.assertEqual(result["results"][0]["search_method"], "quantum_enhanced")

    async def test_retrieval_helper_times_quantum_search(self):
        quantum_search = QuantumSearch()
        vector_store = FakeVectorStore(build_test_documents(4))

        result = await retrieve_ranked_documents(
            query_embedding=[1.0, 0.0, 0.0, 0.0],
            vector_store=vector_store,
            quantum_search=quantum_search,
            top_k=1,
            similarity_threshold=0.1,
            use_quantum=True,
        )

        self.assertGreater(result["retrieval_time_ms"], 0.0)
        self.assertEqual(result["search_method"], "quantum_enhanced")
        self.assertEqual(result["results"][0]["id"], "0")

    async def test_retrieval_helper_falls_back_when_dataset_exceeds_qubits(self):
        quantum_search = QuantumSearch()
        quantum_search.max_qubits = 1
        vector_store = FakeVectorStore(build_test_documents(3))

        result = await retrieve_ranked_documents(
            query_embedding=[1.0, 0.0, 0.0],
            vector_store=vector_store,
            quantum_search=quantum_search,
            top_k=1,
            similarity_threshold=0.1,
            use_quantum=True,
        )

        self.assertEqual(result["search_method"], "classical_fallback")
        self.assertEqual(result["fallback_reason"], "too_many_documents")
        self.assertEqual(result["results"][0]["id"], "0")

    async def test_retrieval_helper_falls_back_when_no_marked_items_exist(self):
        quantum_search = QuantumSearch()
        vector_store = FakeVectorStore(build_test_documents(4))

        result = await retrieve_ranked_documents(
            query_embedding=[0.0, 0.0, 0.0, 0.0],
            vector_store=vector_store,
            quantum_search=quantum_search,
            top_k=1,
            similarity_threshold=0.1,
            use_quantum=True,
        )

        self.assertEqual(result["search_method"], "classical_fallback")
        self.assertEqual(result["fallback_reason"], "no_marked_items")


class ApiTimingTests(unittest.TestCase):
    def _build_query_client(self, vector_store, quantum_search, pdf_processor):
        app = FastAPI()
        app.include_router(query_router, prefix="/api/v1")
        app.dependency_overrides[get_vector_store] = lambda: vector_store
        app.dependency_overrides[get_quantum_search] = lambda: quantum_search
        app.dependency_overrides[get_pdf_processor] = lambda: pdf_processor
        return TestClient(app)

    def _build_chat_client(self, vector_store, quantum_search, pdf_processor):
        app = FastAPI()
        app.include_router(chat_router, prefix="/api")
        app.dependency_overrides[get_vector_store] = lambda: vector_store
        app.dependency_overrides[get_quantum_search] = lambda: quantum_search
        app.dependency_overrides[get_pdf_processor] = lambda: pdf_processor
        return TestClient(app)

    def test_query_api_reports_retrieval_time_separately_from_embedding_time(self):
        vector_store = FakeVectorStore(build_test_documents(4))
        quantum_search = QuantumSearch()
        pdf_processor = FakePDFProcessor([1.0, 0.0, 0.0, 0.0], delay=0.2)

        with self._build_query_client(vector_store, quantum_search, pdf_processor) as client:
            response = client.post(
                "/api/v1/query",
                json={
                    "query": "find the first document",
                    "top_k": 1,
                    "similarity_threshold": 0.1,
                    "use_quantum": True,
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            payload = response.json()
            response.close()

        self.assertEqual(payload["search_method"], "quantum_enhanced")
        self.assertGreater(payload["retrieval_time_ms"], 0.0)
        self.assertGreater(payload["processing_time_ms"], payload["retrieval_time_ms"])
        self.assertEqual(payload["metadata"]["retrieval_method"], "quantum_enhanced")

    def test_query_api_honestly_reports_classical_fallback(self):
        vector_store = FakeVectorStore(build_test_documents(3))
        quantum_search = QuantumSearch()
        quantum_search.max_qubits = 1
        pdf_processor = FakePDFProcessor([1.0, 0.0, 0.0])

        with self._build_query_client(vector_store, quantum_search, pdf_processor) as client:
            response = client.post(
                "/api/v1/query",
                json={
                    "query": "force fallback",
                    "top_k": 1,
                    "similarity_threshold": 0.1,
                    "use_quantum": True,
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            payload = response.json()
            response.close()

        self.assertEqual(payload["search_method"], "classical_fallback")
        self.assertEqual(payload["metadata"]["fallback_reason"], "too_many_documents")

    def test_chat_api_reports_retrieval_method_and_excludes_generation_time(self):
        vector_store = FakeVectorStore(build_test_documents(4))
        quantum_search = QuantumSearch()
        pdf_processor = FakePDFProcessor([1.0, 0.0, 0.0, 0.0], delay=0.2)

        async def fake_gemini_response(*args, **kwargs):
            await asyncio.sleep(0.2)
            return "stubbed response"

        with patch.object(chat_routes_module.settings, "GEMINI_API_KEY", "test-key"):
            with patch.object(chat_routes_module, "_generate_gemini_response", side_effect=fake_gemini_response):
                with self._build_chat_client(vector_store, quantum_search, pdf_processor) as client:
                    response = client.post(
                        "/api/chat",
                        json={
                            "message": "summarize doc 0",
                            "user_id": 1,
                            "session_id": "session-1",
                            "use_context": True,
                            "force_general": False,
                            "max_context_results": 1,
                            "temperature": 0.7,
                        },
                    )
                    self.assertEqual(response.status_code, 200, response.text)
                    payload = response.json()
                    response.close()

        self.assertGreater(payload["retrieval_time_ms"], 0.0)
        self.assertGreater(payload["processing_time_ms"], payload["retrieval_time_ms"])
        self.assertEqual(payload["metadata"]["retrieval_method"], "quantum_enhanced")

    def test_debug_release_environment_imports_main_successfully(self):
        result = subprocess.run(
            [sys.executable, "-c", "from main import app; print(app.title)"],
            cwd=BACKEND_DIR,
            env={**os.environ, "DEBUG": "release"},
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Quantum PDF Chatbot Backend", result.stdout)


if __name__ == "__main__":
    unittest.main()
