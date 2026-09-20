"""Request-scoped Supabase access using the user's verified session and RLS.

No service-role key, shared mutable session, local password hash or anonymous
fallback is used. Database failures are errors, never empty successful results.
"""
from dataclasses import dataclass
from typing import Any
import httpx
from fastapi import Depends, HTTPException, Request
from config import settings

PROFILE_COLUMNS = 'id,auth_user_id,full_name,email,phone_number,created_at'


@dataclass(frozen=True)
class Identity:
    user_id: int
    auth_user_id: str
    profile: dict[str, Any]


class DatabaseService:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def request(self, method, path, *, params=None, json=None, headers=None):
        try:
            response = await self.client.request(method, path, params=params, json=json, headers=headers)
        except httpx.RequestError:
            raise HTTPException(503, 'Database service unavailable') from None
        if response.status_code in (401, 403):
            raise HTTPException(response.status_code, 'Access denied')
        if response.status_code >= 400:
            raise HTTPException(503, 'Database operation failed; check the configured schema and policies')
        return response.json() if response.content else None

    async def verify_identity(self):
        user = await self.request('GET', '/auth/v1/user')
        if not user or not user.get('id'):
            raise HTTPException(401, 'Invalid session')
        if not user.get('email_confirmed_at'):
            raise HTTPException(403, 'Verify your email before signing in')
        profiles = await self.request('GET', '/rest/v1/signup_users', params={
            'select': PROFILE_COLUMNS, 'auth_user_id': f"eq.{user['id']}", 'limit': '1'})
        if not profiles:
            raise HTTPException(403, 'No linked profile; an existing account needs verified migration')
        profile = profiles[0]
        if profile.get('auth_user_id') != user['id']:
            raise HTTPException(403, 'Profile ownership mismatch')
        return Identity(int(profile['id']), user['id'], profile)

    async def require_session(self, session_id: str, identity: Identity):
        if not session_id or not session_id.isascii() or not session_id.isdecimal():
            raise HTTPException(422, 'session_id must be a database chat ID encoded as a string')
        rows = await self.request('GET', '/rest/v1/chats', params={
            'select': 'id,user_id,chat_name', 'id': f'eq.{int(session_id)}',
            'user_id': f'eq.{identity.user_id}', 'limit': '1'})
        if not rows or int(rows[0]['user_id']) != identity.user_id:
            raise HTTPException(404, 'Chat session not found')
        return rows[0]

    async def history(self, session_id, identity, limit=6):
        rows = await self.request('GET', '/rest/v1/chat_history', params={
            'select': 'input_data,output_data', 'chat_id': f'eq.{int(session_id)}',
            'user_id': f'eq.{identity.user_id}', 'order': 'created_at.desc,id.desc', 'limit': str(limit)})
        return list(reversed(rows))

    async def uploaded_files(self, identity, session_id=None):
        params = {'select': '*', 'user_id': f'eq.{identity.user_id}', 'order': 'id.asc'}
        if session_id is not None:
            params['chat_session_id'] = f'eq.{int(session_id)}'
        # Explicit pagination avoids PostgREST's default server row limit.
        rows, offset = [], 0
        while True:
            page = await self.request('GET', '/rest/v1/uploaded_files',
                                      params={**params, 'offset': str(offset), 'limit': '500'})
            rows.extend(page)
            if len(page) < 500:
                return rows
            offset += 500


async def get_database_service(request: Request):
    header = request.headers.get('Authorization', '')
    scheme, _, token = header.partition(' ')
    if scheme.lower() != 'bearer' or not token.strip():
        raise HTTPException(401, 'A verified bearer session is required')
    if not settings.SUPABASE_URL or not settings.SUPABASE_ANON_KEY:
        raise HTTPException(503, 'Supabase authentication is not configured')
    async with httpx.AsyncClient(
        base_url=settings.SUPABASE_URL.rstrip('/'), timeout=15,
        headers={'apikey': settings.SUPABASE_ANON_KEY, 'Authorization': f'Bearer {token.strip()}'},
    ) as client:
        yield DatabaseService(client)


async def get_identity(database: DatabaseService = Depends(get_database_service)):
    return await database.verify_identity()


def require_matching_user(identity: Identity, user_id: int | str | None):
    if user_id is not None and str(user_id) != str(identity.user_id):
        raise HTTPException(403, 'User scope does not match the authenticated session')
