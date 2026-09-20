"""Owner-scoped original files and retryable deletion across database and Chroma."""
import asyncio
import fcntl
import re
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import HTTPException
from config import settings
from services.shared import get_vector_store
from services.workers import run_blocking


def document_path(user_id, session_id, document_id):
    if not str(user_id).isdecimal() or not str(session_id).isdecimal() or not re.fullmatch(r'[0-9a-f]{64}', document_id):
        raise HTTPException(422, 'Invalid document reference')
    return settings.path(settings.DOCUMENT_STORE_PATH) / str(user_id) / str(int(session_id)) / document_id


@asynccontextmanager
async def owner_lock(user_id):
    """A nonblocking file lock coordinates API workers and account deletion."""
    directory = settings.path(settings.DOCUMENT_STORE_PATH) / '.locks'
    directory.mkdir(parents=True, exist_ok=True)
    handle = (directory / f'{int(user_id)}.lock').open('a')
    try:
        # A bounded wait avoids indefinitely accumulating requests behind a slow model.
        async with asyncio.timeout(settings.DOCUMENT_TIMEOUT_SECONDS + settings.GENERATION_TIMEOUT_SECONDS):
            while True:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    await asyncio.sleep(0.05)
        yield
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


async def delete_record(database, identity, record):
    params = {'id': f"eq.{record['id']}", 'user_id': f'eq.{identity.user_id}'}
    await database.request('PATCH', '/rest/v1/uploaded_files', params=params, json={'status': 'deleting'})
    document_id = record.get('document_id')
    session_id = str(record['chat_session_id'])
    if document_id:
        await get_vector_store().delete_scope(user_id=identity.user_id, session_id=session_id,
                                              document_id=document_id)
        path = document_path(identity.user_id, session_id, document_id)
        await run_blocking(path.unlink, missing_ok=True)
    await database.request('DELETE', '/rest/v1/uploaded_files', params=params)


async def delete_session_documents(database, identity, session_id):
    for record in await database.uploaded_files(identity, session_id):
        await delete_record(database, identity, record)
    # Remove orphaned vectors in this session too; this never reaches another owner.
    await get_vector_store().delete_scope(user_id=identity.user_id, session_id=session_id)


async def delete_user_documents(database, identity):
    async with owner_lock(identity.user_id):
        for record in await database.uploaded_files(identity):
            await delete_record(database, identity, record)
        await get_vector_store().delete_scope(user_id=identity.user_id)
