"""Shared retrieval helpers for vector search timing and method selection."""

import logging
import time
from typing import Any, Dict, List, Optional

from .quantum_search import QuantumSearch
from .vector_store import VectorStore

logger = logging.getLogger(__name__)


def _matches_metadata_filter(
    metadata: Dict[str, Any],
    metadata_filter: Optional[Dict[str, str]],
) -> bool:
    """Return True when metadata satisfies the requested filter set."""
    if not metadata_filter:
        return True

    for key, value in metadata_filter.items():
        if str(metadata.get(key, "")).lower() != str(value).lower():
            return False

    return True


async def retrieve_ranked_documents(
    query_embedding: List[float],
    vector_store: VectorStore,
    quantum_search: QuantumSearch,
    top_k: int,
    similarity_threshold: float,
    use_quantum: bool = True,
    metadata_filter: Optional[Dict[str, str]] = None,
    session_id: Optional[str] = None,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Retrieve and rank candidate vectors with honest retrieval timing."""
    retrieval_start = time.perf_counter()
    requested_method = "quantum_enhanced" if use_quantum else "classical"

    try:
        candidates = await vector_store.get_all_embeddings(
            session_id=session_id,
            user_id=user_id,
        )

        if metadata_filter:
            candidates = [
                candidate
                for candidate in candidates
                if _matches_metadata_filter(candidate.get("metadata", {}), metadata_filter)
            ]

        retrieval_time_ms = (time.perf_counter() - retrieval_start) * 1000

        if not candidates:
            logger.info("No candidates found for retrieval")
            return {
                "results": [],
                "retrieval_time_ms": round(retrieval_time_ms, 2),
                "search_method": "none",
                "requested_search_method": requested_method,
                "fallback_reason": "no_candidates",
                "candidate_count": 0,
            }

        if use_quantum:
            ranking_result = await quantum_search.quantum_enhanced_search(
                query_embedding=query_embedding,
                document_embeddings=candidates,
                similarity_threshold=similarity_threshold,
                top_k=top_k,
            )
        else:
            ranking_result = await quantum_search.classical_similarity_search(
                query_embedding=query_embedding,
                document_embeddings=candidates,
                top_k=top_k,
                search_method="classical",
            )

        retrieval_time_ms = (time.perf_counter() - retrieval_start) * 1000

        return {
            "results": ranking_result["results"],
            "retrieval_time_ms": round(retrieval_time_ms, 2),
            "search_method": ranking_result["search_method"],
            "requested_search_method": requested_method,
            "fallback_reason": ranking_result.get("fallback_reason"),
            "candidate_count": len(candidates),
        }
    except Exception as exc:
        logger.error(f"Shared retrieval failed: {exc}")
        retrieval_time_ms = (time.perf_counter() - retrieval_start) * 1000
        return {
            "results": [],
            "retrieval_time_ms": round(retrieval_time_ms, 2),
            "search_method": "none",
            "requested_search_method": requested_method,
            "fallback_reason": "retrieval_error",
            "candidate_count": 0,
        }
