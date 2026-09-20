"""Validated PDF/image uploads and owner-scoped source access and deletion."""
import hashlib
import os
import tempfile
import time
from pathlib import Path
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from services.database import DatabaseService, Identity, get_database_service, get_identity, require_matching_user
from services.documents import owner_lock, document_path, delete_record, delete_session_documents
from services.shared import get_pdf_processor, get_vector_store
from services.workers import run_blocking
from config import settings

router = APIRouter(tags=['documents'])


@router.post('/upload_pdf')
async def upload_pdf(file: UploadFile = File(...), session_id: str = Form(...),
                     user_id: str | None = Form(None),
                     identity: Identity = Depends(get_identity),
                     database: DatabaseService = Depends(get_database_service),
                     processor=Depends(get_pdf_processor), store=Depends(get_vector_store)):
    require_matching_user(identity, user_id)
    await database.require_session(session_id, identity)
    session_id = str(int(session_id))
    filename = Path(file.filename or '').name
    suffix = Path(filename).suffix.lower()
    if suffix not in {'.pdf', '.png', '.jpg', '.jpeg'} or len(filename) > 255:
        raise HTTPException(415, 'Upload a PDF, PNG or JPEG file')
    temporary, record = None, None
    start = time.perf_counter()
    try:
        descriptor, temporary = tempfile.mkstemp(suffix=suffix)
        size = 0
        digest = hashlib.sha256()
        with os.fdopen(descriptor, 'wb') as handle:
            while block := await file.read(64*1024):
                size += len(block)
                if size > settings.MAX_FILE_SIZE:
                    raise HTTPException(413, 'File exceeds the configured size limit')
                digest.update(block)
                handle.write(block)
        if size == 0:
            raise HTTPException(422, 'File is empty')
        with open(temporary, 'rb') as handle:
            signature = handle.read(8)
        valid = ((suffix == '.pdf' and signature.startswith(b'%PDF-')) or
                 (suffix == '.png' and signature.startswith(b'\x89PNG\r\n\x1a\n')) or
                 (suffix in {'.jpg', '.jpeg'} and signature.startswith(b'\xff\xd8\xff')))
        if not valid:
            raise HTTPException(415, 'File contents do not match the declared format')
        document_id = hashlib.sha256(f'{digest.hexdigest()}:{processor.processing_version}'.encode()).hexdigest()
        async with owner_lock(identity.user_id):
            # Recheck after waiting: the session may have been deleted meanwhile.
            await database.require_session(session_id, identity)
            records = await database.uploaded_files(identity, session_id)
            record = next((r for r in records if r.get('document_id') == document_id), None)
            if record and record.get('status') == 'ready':
                return {'success': True, 'status': 'ready', 'document_id': document_id,
                        'file_name': filename, 'chunks_created': record['chunks_count'],
                        'deduplicated': True, 'processing_time_ms': (time.perf_counter()-start)*1000}
            if record:
                await database.request('PATCH', '/rest/v1/uploaded_files',
                    params={'id': f"eq.{record['id']}"}, json={'status': 'processing'})
            else:
                records = await database.request('POST', '/rest/v1/uploaded_files',
                    json={'user_id': identity.user_id, 'chat_session_id': int(session_id),
                          'document_id': document_id, 'file_name': filename, 'file_size': size,
                          'file_type': 'pdf' if suffix == '.pdf' else 'image',
                          'status': 'processing', 'processing_version': processor.processing_version},
                    headers={'Prefer': 'return=representation'})
                record = records[0]
            try:
                result = await processor.process_pdf(temporary, document_id=document_id, filename=filename)
                await store.add_documents(result['embedded_chunks'], user_id=identity.user_id, session_id=session_id)
                destination = document_path(identity.user_id, session_id, document_id)
                destination.parent.mkdir(parents=True, exist_ok=True)
                # Atomic replacement, with staging in the destination filesystem.
                import shutil
                stage = destination.with_suffix('.staging')
                await run_blocking(shutil.copyfile, temporary, stage)
                os.replace(stage, destination)
                await database.request('PATCH', '/rest/v1/uploaded_files',
                    params={'id': f"eq.{record['id']}"}, json={'status': 'ready', 'chunks_count': result['chunks_count']})
            except Exception:
                # If the database is unavailable, the record remains non-ready and
                # therefore excluded from retrieval. A later upload can retry it.
                try:
                    await database.request('PATCH', '/rest/v1/uploaded_files',
                        params={'id': f"eq.{record['id']}"}, json={'status': 'failed'})
                except HTTPException:
                    pass
                raise
        return {'success': True, 'status': 'ready', 'document_id': document_id, 'file_name': filename,
                'file_size': size, 'chunks_created': result['chunks_count'],
                'pages_processed': result['file_metadata']['num_pages'],
                'deduplicated': False, 'processing_time_ms': (time.perf_counter()-start)*1000,
                'timings_ms': result['timings_ms']}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    finally:
        await file.close()
        if temporary:
            Path(temporary).unlink(missing_ok=True)


@router.get('/documents')
async def documents(session_id: str, identity: Identity = Depends(get_identity),
                    database: DatabaseService = Depends(get_database_service)):
    await database.require_session(session_id, identity)
    return {'documents': await database.uploaded_files(identity, session_id)}


@router.get('/documents/{document_id}/source')
async def source(document_id: str, session_id: str, identity: Identity = Depends(get_identity),
                 database: DatabaseService = Depends(get_database_service)):
    async with owner_lock(identity.user_id):
        await database.require_session(session_id, identity)
        records = await database.uploaded_files(identity, session_id)
        record = next((r for r in records if r.get('document_id') == document_id and r.get('status') == 'ready'), None)
        if not record:
            raise HTTPException(404, 'Source not found')
        path = document_path(identity.user_id, session_id, document_id)
        if not path.is_file():
            raise HTTPException(409, 'Original document is unavailable; upload it again')
        data = await run_blocking(path.read_bytes)
    content_type = 'application/pdf' if data.startswith(b'%PDF-') else 'image/png' if data.startswith(b'\x89PNG') else 'image/jpeg'
    return Response(data, media_type=content_type,
                    headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


@router.delete('/documents/{document_id}')
async def delete_document(document_id: str, session_id: str, identity: Identity = Depends(get_identity),
                          database: DatabaseService = Depends(get_database_service)):
    async with owner_lock(identity.user_id):
        await database.require_session(session_id, identity)
        record = next((r for r in await database.uploaded_files(identity, session_id)
                       if r.get('document_id') == document_id), None)
        if record:
            await delete_record(database, identity, record)
    return {'success': True}


@router.delete('/sessions/{session_id}/documents')
async def clear_session_documents(session_id: str, identity: Identity = Depends(get_identity),
                                  database: DatabaseService = Depends(get_database_service)):
    async with owner_lock(identity.user_id):
        await database.require_session(session_id, identity)
        await delete_session_documents(database, identity, str(int(session_id)))
    return {'success': True}


@router.delete('/sessions/{session_id}')
async def delete_session(session_id: str, identity: Identity = Depends(get_identity),
                         database: DatabaseService = Depends(get_database_service)):
    async with owner_lock(identity.user_id):
        await database.require_session(session_id, identity)
        await delete_session_documents(database, identity, str(int(session_id)))
        await database.request('DELETE', '/rest/v1/chat_history', params={
            'chat_id': f'eq.{int(session_id)}', 'user_id': f'eq.{identity.user_id}'})
        await database.request('DELETE', '/rest/v1/chats', params={
            'id': f'eq.{int(session_id)}', 'user_id': f'eq.{identity.user_id}'})
    return {'success': True}


@router.get('/pdf_stats')
async def pdf_stats(session_id: str, identity: Identity = Depends(get_identity),
                    database: DatabaseService = Depends(get_database_service)):
    await database.require_session(session_id, identity)
    records = await database.uploaded_files(identity, session_id)
    ready = [r for r in records if r.get('status') == 'ready']
    return {'total_documents': len(ready), 'total_chunks': sum(r['chunks_count'] for r in ready),
            'supported_formats': ['pdf', 'png', 'jpeg'], 'chunk_unit': 'tokens',
            'chunk_size': settings.CHUNK_TOKENS, 'chunk_overlap': settings.CHUNK_OVERLAP_TOKENS}
