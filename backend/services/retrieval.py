"""Shared, scoped retrieval with explicit strategies and stage timings."""
import time
from uuid import uuid4
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from config import settings
from services.workers import run_blocking


class RetrievalConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    strategy: Literal['cosine', 'grover', 'closed_form', 'classical_sampling'] = 'cosine'
    candidate_limit: int = Field(default=64, ge=1, le=1024)
    top_k: int = Field(default=5, ge=1, le=64)
    threshold: float = Field(default=0.5, ge=0, le=1)
    shots: int = Field(default=1024, ge=1, le=100_000)
    seed: int = Field(default=0, ge=0)


async def retrieve_ranked_documents(query_embedding, vector_store, quantum_search,
                                    top_k=5, similarity_threshold=0.5, use_quantum=False,
                                    metadata_filter=None, session_id=None, user_id=None,
                                    config=None, allowed_document_ids=None):
    if user_id is None or not session_id:
        raise ValueError('Authenticated user and session scopes are required')
    config = config or RetrievalConfig(
        strategy='grover' if use_quantum else 'cosine', top_k=top_k,
        threshold=similarity_threshold, candidate_limit=settings.CANDIDATE_LIMIT,
        shots=settings.QUANTUM_SHOTS, seed=settings.QUANTUM_SEED)
    if config.top_k > config.candidate_limit:
        raise ValueError('top_k cannot exceed candidate_limit')
    start = time.perf_counter()
    candidates = await vector_store.candidates(
        query_embedding, user_id=user_id, session_id=session_id,
        limit=config.candidate_limit, metadata=metadata_filter)
    # Lifecycle gate prevents stale or incompletely committed vectors becoming sources.
    if allowed_document_ids is not None:
        candidates = [x for x in candidates if x['metadata'].get('document_id') in allowed_document_ids]
    candidate_ms = (time.perf_counter()-start)*1000
    clock = time.perf_counter()
    scores = (await run_blocking(quantum_search._calculate_similarity_scores, query_embedding,
                                [x['embedding'] for x in candidates])) if candidates else []
    scoring_ms = (time.perf_counter()-clock)*1000
    result = await run_blocking(quantum_search.rank_scores, candidates, scores,
        method=config.strategy, top_k=config.top_k, threshold=config.threshold,
        shots=config.shots, seed=config.seed)
    return {**result, 'run_id': str(uuid4()), 'candidate_count': len(candidates),
            'retrieval_time_ms': (time.perf_counter()-start)*1000,
            'timings_ms': {'candidate_selection': candidate_ms, 'cosine_scoring': scoring_ms,
                           'ranking': result['ranking_time_ms']}}
