"""Protocol fault injection is isolated from the real-data experiment runner."""
import unittest
import httpx
from fastapi import HTTPException
from main import app, global_exception_handler
from config import Settings
from services.database import DatabaseService, Identity, require_matching_user
from starlette.requests import Request

AUTH_ID = '00000000-0000-4000-8000-000000000001'


class AuthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_private_route_rejects_missing_authentication(self):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            for method, path, body in [
                ('GET', '/api/auth/me', None),
                ('PUT', '/api/auth/user/1', {'full_name': 'Updated name'}),
                ('GET', '/api/v1/documents?session_id=1', None),
                ('GET', '/api/v1/pdf_stats?session_id=1', None),
                ('GET', '/api/v1/documents/abc/source?session_id=1', None),
                ('DELETE', '/api/v1/sessions/1', None),
                ('POST', '/api/v1/query', {'query': 'test', 'session_id': '1'}),
                ('POST', '/api/chat', {'message': 'test', 'session_id': '1'}),
            ]:
                with self.subTest(path=path):
                    response = await client.request(method, path, json=body)
                    self.assertEqual(response.status_code, 401)

    async def test_provider_rejecting_arbitrary_token_is_not_accepted_locally(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(401, json={'message': 'invalid token'})),
            base_url='https://auth.invalid') as client:
            with self.assertRaises(HTTPException) as ctx:
                await DatabaseService(client).verify_identity()
            self.assertEqual(ctx.exception.status_code, 401)

    async def test_verified_identity_requires_a_linked_profile(self):
        def transport(request):
            if request.url.path == '/auth/v1/user':
                return httpx.Response(200, json={'id': AUTH_ID, 'email_confirmed_at': '2026-09-10'})
            return httpx.Response(200, json=[])
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport), base_url='https://auth.invalid') as client:
            with self.assertRaises(HTTPException) as ctx:
                await DatabaseService(client).verify_identity()
            self.assertEqual(ctx.exception.status_code, 403)

    async def test_unverified_email_is_rejected(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={'id': AUTH_ID, 'email_confirmed_at': None})),
            base_url='https://auth.invalid') as client:
            with self.assertRaises(HTTPException) as ctx:
                await DatabaseService(client).verify_identity()
            self.assertEqual(ctx.exception.status_code, 403)

    def test_client_user_id_cannot_override_identity(self):
        identity = Identity(1, AUTH_ID, {})
        with self.assertRaises(HTTPException) as ctx:
            require_matching_user(identity, 2)
        self.assertEqual(ctx.exception.status_code, 403)
        require_matching_user(identity, 1)

    async def test_database_failure_does_not_turn_into_empty_success(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(500, json={'secret': 'not for clients'})),
            base_url='https://auth.invalid') as client:
            with self.assertRaises(HTTPException) as ctx:
                await DatabaseService(client).uploaded_files(Identity(1, AUTH_ID, {}))
            self.assertEqual(ctx.exception.status_code, 503)
            self.assertNotIn('secret', ctx.exception.detail)

    async def test_profile_update_contract_accepts_json_and_forbids_identity_fields(self):
        from routes.auth_routes import ProfileUpdate
        self.assertEqual(ProfileUpdate.model_validate({'full_name': 'Updated name'}).full_name, 'Updated name')
        with self.assertRaises(ValueError):
            ProfileUpdate.model_validate({'auth_user_id': AUTH_ID})

    async def test_legacy_auth_and_global_reset_are_disabled(self):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            self.assertEqual((await client.post('/api/auth/login', json={})).status_code, 410)
            self.assertEqual((await client.delete('/api/v1/clear_pdfs')).status_code, 404)

    async def test_exception_details_are_not_returned_to_clients(self):
        request = Request({'type': 'http', 'method': 'GET', 'path': '/', 'headers': []})
        response = await global_exception_handler(request, RuntimeError('secret-db-password'))
        self.assertNotIn(b'secret-db-password', response.body)

    def test_explicit_cors_configuration_is_not_extended(self):
        config = Settings(_env_file=None, ALLOWED_ORIGINS='https://college.example')
        self.assertEqual(config.allowed_origins_list, ['https://college.example'])

    def test_debug_release_is_parsed(self):
        self.assertFalse(Settings(_env_file=None, DEBUG='release').DEBUG)
