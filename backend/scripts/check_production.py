"""Read-only integration checks against configured real services.

Run from backend: .venv/bin/python scripts/check_production.py
Optional QUBIT_TEST_ACCESS_TOKEN verifies a real signed-in user without printing
their profile. DATABASE_URL is only reported as configured/not configured.
No accounts, rows, uploads, emails or database policies are changed.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from dotenv import dotenv_values
from config import settings


async def checks():
    environment = {**dotenv_values(Path(__file__).resolve().parents[1] / '.env'), **os.environ}
    report = {'database_owner_connection_configured': bool(environment.get('DATABASE_URL')),
              'checks_are_read_only': True}
    async with httpx.AsyncClient(timeout=20) as client:
        if settings.SUPABASE_URL and settings.SUPABASE_ANON_KEY:
            base = settings.SUPABASE_URL.rstrip('/')
            headers = {'apikey': settings.SUPABASE_ANON_KEY, 'Authorization': 'Bearer ' + settings.SUPABASE_ANON_KEY}
            report['anonymous_table_access'] = {}
            for table in ('signup_users', 'chats', 'chat_history', 'uploaded_files'):
                response = await client.get(base + '/rest/v1/' + table,
                                            params={'select': 'id', 'limit': 1}, headers=headers)
                report['anonymous_table_access'][table] = {
                    'http_status': response.status_code,
                    'private_row_readable': response.status_code == 200 and bool(response.json())}
            response = await client.get(base + '/auth/v1/user', headers={
                'apikey': settings.SUPABASE_ANON_KEY, 'Authorization': 'Bearer unissued-regression-token'})
            report['unissued_token_rejected'] = response.status_code in (401, 403)
            response = await client.get(base + '/rest/v1/signup_users',
                params={'select': 'auth_user_id', 'limit': 0}, headers=headers)
            report['profile_mapping_probe_status'] = response.status_code
            token = environment.get('QUBIT_TEST_ACCESS_TOKEN')
            if token:
                response = await client.get(base + '/auth/v1/user',
                    headers={'apikey': settings.SUPABASE_ANON_KEY, 'Authorization': 'Bearer ' + token})
                report['real_user_session_status'] = response.status_code
            else:
                report['real_user_session_status'] = 'not run: no signed-in test session configured'
        else:
            report['supabase'] = 'not configured'
        if settings.GEMINI_API_KEY:
            response = await client.get('https://generativelanguage.googleapis.com/v1beta/models',
                                       headers={'x-goog-api-key': settings.GEMINI_API_KEY})
            report['gemini_models_status'] = response.status_code
            report['configured_gemini_model_listed'] = response.status_code == 200 and any(
                model.get('name') == 'models/' + settings.GEMINI_MODEL
                for model in response.json().get('models', []))
    return report


if __name__ == '__main__':
    print(json.dumps(asyncio.run(checks()), indent=2))
