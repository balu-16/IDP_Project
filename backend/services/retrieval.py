"""Shared, scoped retrieval with explicit strategies and stage timings."""
import time
from uuid import uuid4
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from config import settings
from services.workers import run_blocking


class RetrievalConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    strategy: Literal['cosine', 'grover', 'closed_form', 'classical_sampling', 'l6_gas'] = 'cosine'
    candidate_limit: int = Field(default=64, ge=1, le=1024)
    top_k: int = Field(default=5, ge=1, le=64)
    threshold: float = Field(default=0.5, ge=0, le=1)
    shots: int = Field(default=1024, ge=1, le=100_000)
    seed: int = Field(default=0, ge=0)

    @model_validator(mode='after')
    def validate_strategy(self):
        if self.strategy == 'l6_gas':
            if 'top_k' not in self.model_fields_set:
                self.top_k = 8
            if self.top_k != 8 or self.candidate_limit != 64:
                raise ValueError('l6_gas uses candidate_limit=64 and top_k=8; smaller pools return fewer passages')
        if self.top_k > self.candidate_limit:
            raise ValueError('top_k cannot exceed candidate_limit')
        return self


async def retrieve_ranked_documents(query_embedding, vector_store, quantum_search,
                                    top_k=5, similarity_threshold=0.5, use_quantum=False,
                                    metadata_filter=None, session_id=None, user_id=None,
                                    config=None, allowed_document_ids=None, query_text=None):
    if user_id is None or not session_id:
        raise ValueError('Authenticated user and session scopes are required')
    config = config or RetrievalConfig(
        strategy='grover' if use_quantum else 'cosine', top_k=top_k,
        threshold=similarity_threshold, candidate_limit=settings.CANDIDATE_LIMIT,
        shots=settings.QUANTUM_SHOTS, seed=settings.QUANTUM_SEED)
    if config.top_k > config.candidate_limit:
        raise ValueError('top_k cannot exceed candidate_limit')
    start = time.perf_counter()
    if config.strategy == 'l6_gas':
        from services.gas_retrieval import rank_passages
        if allowed_document_ids is None:
            raise ValueError('L6-guided GAS requires the ready-document scope')
        rows = await vector_store.get_all_embeddings(user_id=user_id, session_id=session_id,
            metadata=metadata_filter, allowed_document_ids=allowed_document_ids)
        # Defense in depth for alternate stores: lifecycle filtering precedes
        # all lexical statistics, shortlist construction, and L6 inference.
        rows = [row for row in rows if row['metadata'].get('document_id') in allowed_document_ids]
        read_ms = (time.perf_counter() - start) * 1000
        result = await run_blocking(rank_passages, query_text, query_embedding, rows, seed=config.seed)
        total_ms = (time.perf_counter() - start) * 1000
        timings = {**result['timings_ms'], 'eligible_passage_loading': read_ms,
                   'ranking': result['ranking_time_ms']}
        timings['online_retrieval'] = max(0.0, total_ms - timings.get('model_loading_ms', 0)
                                         - timings.get('model_warmup_ms', 0))
        return {**result, 'run_id': str(uuid4()), 'retrieval_time_ms': total_ms, 'timings_ms': timings}
    candidates = await vector_store.candidates(
        query_embedding, user_id=user_id, session_id=session_id,
        limit=config.candidate_limit, metadata=metadata_filter, allowed_document_ids=allowed_document_ids)
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
