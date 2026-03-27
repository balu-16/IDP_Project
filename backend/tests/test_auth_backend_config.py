import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from main import global_exception_handler
import services.database as database_module
from services.database import DatabaseService


class SupabaseConfigTests(unittest.IsolatedAsyncioTestCase):
    async def test_initialize_uses_supabase_url_and_anon_key(self):
        service = DatabaseService()

        with patch.dict(
            os.environ,
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_ANON_KEY": "frontend-anon-key",
            },
            clear=False,
        ):
            with patch("services.database.create_client") as create_client_mock:
                fake_client = object()
                create_client_mock.return_value = fake_client

                await service.initialize()

        create_client_mock.assert_called_once_with(
            "https://example.supabase.co",
            "frontend-anon-key",
        )
        self.assertTrue(service._initialized)
        self.assertIs(service.client, fake_client)

    async def test_initialize_requires_supabase_anon_key(self):
        service = DatabaseService()

        with patch.dict(
            os.environ,
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_ANON_KEY": "",
            },
            clear=False,
        ):
            with patch("services.database.settings.SUPABASE_URL", None), patch(
                "services.database.settings.SUPABASE_ANON_KEY",
                None,
            ):
                with patch("services.database.create_client") as create_client_mock:
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "SUPABASE_URL and SUPABASE_ANON_KEY must be set",
                    ):
                        await service.initialize()

        create_client_mock.assert_not_called()


class GlobalExceptionHandlerTests(unittest.TestCase):
    def test_global_exception_handler_preserves_http_exception_status(self):
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/boom",
            "headers": [],
        }
        request = Request(scope)
        response = self._run_async(
            global_exception_handler(
                request,
                HTTPException(
                    status_code=503,
                    detail="Authentication backend initialization failed",
                ),
            )
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.body,
            b'{"detail":"Authentication backend initialization failed"}',
        )

    def _run_async(self, coroutine):
        import asyncio

        return asyncio.run(coroutine)


class DatabaseDependencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_database_service_returns_503_when_supabase_env_is_missing(self):
        with patch.dict(
            os.environ,
            {
                "SUPABASE_URL": "",
                "SUPABASE_ANON_KEY": "",
            },
            clear=False,
        ):
            with patch("services.database.settings.SUPABASE_URL", None), patch(
                "services.database.settings.SUPABASE_ANON_KEY",
                None,
            ), patch.object(database_module, "_database_service", None):
                with self.assertRaises(HTTPException) as ctx:
                    await database_module.get_database_service()

        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(
            ctx.exception.detail,
            "SUPABASE_URL and SUPABASE_ANON_KEY must be set for authentication endpoints",
        )

    async def test_get_database_service_surfaces_supabase_httpx_version_mismatch(self):
        with patch.dict(
            os.environ,
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_ANON_KEY": "anon-key",
            },
            clear=False,
        ):
            with patch.object(database_module, "_database_service", None), patch(
                "services.database.create_client",
                side_effect=TypeError("Client.__init__() got an unexpected keyword argument 'proxy'"),
            ):
                with self.assertRaises(HTTPException) as ctx:
                    await database_module.get_database_service()

        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(
            ctx.exception.detail,
            "Authentication backend initialization failed: incompatible Supabase/httpx dependency versions in the deployed container",
        )
