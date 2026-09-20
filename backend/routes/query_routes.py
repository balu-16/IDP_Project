"""Authenticated session-scoped search; no global similar-document endpoint."""
import time
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from services.database import DatabaseService, Identity, get_database_service, get_identity
from services.retrieval import RetrievalConfig, retrieve_ranked_documents
from services.shared import get_pdf_processor, get_quantum_search, get_vector_store

router = APIRouter(tags=['query'])


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    query: str = Field(min_length=1, max_length=2000)
    session_id: str
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    filter_metadata: dict[str, str] | None = None


@router.post('/query')
async def search_query(body: QueryRequest, identity: Identity = Depends(get_identity),
                       database: DatabaseService = Depends(get_database_service),
                       pdf_processor=Depends(get_pdf_processor),
                       vector_store=Depends(get_vector_store), quantum_search=Depends(get_quantum_search)):
    start = time.perf_counter()
    await database.require_session(body.session_id, identity)
    records = await database.uploaded_files(identity, body.session_id)
    try:
        embedding = await pdf_processor.embed_query(body.query)
        embedding_ms = (time.perf_counter()-start)*1000
        result = await retrieve_ranked_documents(embedding, vector_store, quantum_search,
            config=body.retrieval, user_id=identity.user_id, session_id=str(int(body.session_id)),
            metadata_filter=body.filter_metadata,
            allowed_document_ids={r['document_id'] for r in records if r.get('status') == 'ready'})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return {'success': True, 'query': body.query, **result, 'results_count': len(result['results']),
            'query_preparation_time_ms': embedding_ms, 'processing_time_ms': (time.perf_counter()-start)*1000}
