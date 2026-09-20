"""Grounded chat with persisted source provenance and honest error responses."""
import asyncio
import time
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from services.database import DatabaseService, Identity, get_database_service, get_identity, require_matching_user
from services.documents import owner_lock
from services.generation import generate_answer
from services.retrieval import RetrievalConfig, retrieve_ranked_documents
from services.shared import get_pdf_processor, get_quantum_search, get_vector_store
from config import settings

router = APIRouter(tags=['chat'])


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    message: str = Field(min_length=1, max_length=2000)
    session_id: str
    user_id: int | None = None  # Compatibility only; cannot establish ownership.
    run_id: UUID = Field(default_factory=uuid4)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    temperature: float = Field(default=0, ge=0, le=1)


class ChatResponse(BaseModel):
    success: bool
    response: str
    session_id: str
    run_id: str
    context_used: bool
    context_sources: list[dict]
    retrieval_time_ms: float
    processing_time_ms: float
    metadata: dict


@router.post('/chat', response_model=ChatResponse)
async def chat_message(body: ChatRequest, identity: Identity = Depends(get_identity),
                       database: DatabaseService = Depends(get_database_service),
                       pdf_processor=Depends(get_pdf_processor),
                       vector_store=Depends(get_vector_store), quantum_search=Depends(get_quantum_search)):
    require_matching_user(identity, body.user_id)
    start = time.perf_counter()
    async with owner_lock(identity.user_id):
        session = await database.require_session(body.session_id, identity)
        session_id = str(session['id'])
        existing = await database.request('GET', '/rest/v1/chat_history', params={
            'select': 'input_data,provenance', 'run_id': f'eq.{body.run_id}',
            'chat_id': f'eq.{session_id}', 'user_id': f'eq.{identity.user_id}', 'limit': '1'})
        if existing:
            if existing[0]['input_data'] != body.message:
                raise HTTPException(409, 'This run ID was already used for another message')
            return ChatResponse.model_validate(existing[0]['provenance'])
        records = await database.uploaded_files(identity, session_id)
        try:
            clock = time.perf_counter()
            embedding = await pdf_processor.embed_query(body.message)
            embedding_ms = (time.perf_counter()-clock)*1000
            result = await retrieve_ranked_documents(embedding, vector_store, quantum_search,
                config=body.retrieval, user_id=identity.user_id, session_id=session_id,
                allowed_document_ids={r['document_id'] for r in records if r.get('status') == 'ready'})
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        history = await database.history(session_id, identity)
        clock = time.perf_counter()
        try:
            async with asyncio.timeout(settings.GENERATION_TIMEOUT_SECONDS):
                answer = await generate_answer(body.message, result['results'], history, body.temperature)
        except (TimeoutError, RuntimeError):
            raise HTTPException(503, 'Answer generation unavailable; no answer was saved') from None
        except Exception:
            raise HTTPException(502, 'The generation provider failed; no answer was saved') from None
        payload = ChatResponse(success=True, response=answer, session_id=session_id,
            run_id=str(body.run_id), context_used=bool(result['results']), context_sources=result['results'],
            retrieval_time_ms=result['retrieval_time_ms'], processing_time_ms=(time.perf_counter()-start)*1000,
            metadata={'model': settings.GEMINI_MODEL if result['results'] else None,
                'temperature': body.temperature, 'retrieval_method': result['search_method'],
                'requested_method': body.retrieval.strategy, 'fallback_reason': result['fallback_reason'],
                'candidate_count': result['candidate_count'], 'quantum': result['quantum'],
                'timings_ms': {**result['timings_ms'], 'query_embedding': embedding_ms,
                               'generation': (time.perf_counter()-clock)*1000}})
        await database.request('POST', '/rest/v1/chat_history', json={
            'chat_id': int(session_id), 'user_id': identity.user_id, 'input_data': body.message,
            'output_data': answer, 'run_id': str(body.run_id), 'provenance': payload.model_dump()})
        if session.get('chat_name') in (None, 'New Chat'):
            await database.request('PATCH', '/rest/v1/chats',
                params={'id': f'eq.{session_id}', 'user_id': f'eq.{identity.user_id}'},
                json={'chat_name': body.message[:50]})
        return payload
