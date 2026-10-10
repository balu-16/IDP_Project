"""Read-only integration checks against configured real services.

Run from backend: .venv/bin/python scripts/check_production.py
Optional QUBIT_TEST_ACCESS_TOKEN and QUBIT_TEST_OTHER_ACCESS_TOKEN check
owner isolation without printing profile data. No records are modified.
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
from services.database import PROFILE_COLUMNS


def json_rows(response):
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload if isinstance(payload, list) else None


def postgrest_error_code(response):
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload.get('code') if isinstance(payload, dict) else None


def auth_headers(anon_key, token):
    return {'apikey': anon_key, 'Authorization': 'Bearer ' + token}


async def auth_user(client, base, anon_key, token):
    response = await client.get(base + '/auth/v1/user', headers=auth_headers(anon_key, token))
    return response, response.json() if response.status_code == 200 else None


async def checks():
    environment = {**dotenv_values(Path(__file__).resolve().parents[1] / '.env'), **os.environ}
    report = {'database_owner_connection_configured': bool(environment.get('DATABASE_URL')),
              'service_role_key_configured': bool(environment.get('SUPABASE_SERVICE_ROLE_KEY')),
              'checks_are_read_only': True}
    async with httpx.AsyncClient(timeout=20) as client:
        if settings.SUPABASE_URL and settings.SUPABASE_ANON_KEY:
            base = settings.SUPABASE_URL.rstrip('/')
            anon_headers = auth_headers(settings.SUPABASE_ANON_KEY, settings.SUPABASE_ANON_KEY)
            report['anonymous_table_access'] = {}
            for table in ('signup_users', 'chats', 'chat_history', 'uploaded_files'):
                response = await client.get(base + '/rest/v1/' + table,
                                            params={'select': 'id', 'limit': 1}, headers=anon_headers)
                rows = json_rows(response)
                report['anonymous_table_access'][table] = {
                    'http_status': response.status_code,
                    'postgrest_code': postgrest_error_code(response),
                    'private_row_readable': response.status_code == 200 and bool(rows)}
            report['anonymous_access_closed'] = all(
                result['postgrest_code'] == '42501' and not result['private_row_readable']
                for result in report['anonymous_table_access'].values())

            profile_params = {
                'select': PROFILE_COLUMNS,
                'auth_user_id': 'eq.00000000-0000-0000-0000-000000000000',
                'limit': '0',
            }
            response = await client.get(base + '/rest/v1/signup_users',
                                        params=profile_params, headers=anon_headers)
            report['anonymous_profile_mapping_probe'] = {
                'http_status': response.status_code,
                'postgrest_code': postgrest_error_code(response),
            }

            response = await client.get(base + '/auth/v1/user', headers={
                'apikey': settings.SUPABASE_ANON_KEY, 'Authorization': 'Bearer unissued-regression-token'})
            report['unissued_token_rejected'] = response.status_code in (401, 403)
            token = environment.get('QUBIT_TEST_ACCESS_TOKEN')
            if token:
                response, user = await auth_user(client, base, settings.SUPABASE_ANON_KEY, token)
                report['real_user_session_status'] = response.status_code
                if user:
                    own_response = await client.get(base + '/rest/v1/signup_users',
                        params={'select': PROFILE_COLUMNS, 'auth_user_id': f"eq.{user['id']}", 'limit': '1'},
                        headers=auth_headers(settings.SUPABASE_ANON_KEY, token))
                    own_profiles = json_rows(own_response) or []
                    report['real_user_profile_status'] = own_response.status_code
                    report['real_user_profile_linked'] = (
                        len(own_profiles) == 1 and own_profiles[0].get('auth_user_id') == user['id'])
                    if report['real_user_profile_linked']:
                        own_profile_id = own_profiles[0]['id']
                        report['real_user_owner_access'] = {}
                        for table in ('chats', 'chat_history', 'uploaded_files'):
                            own_rows_response = await client.get(base + '/rest/v1/' + table,
                                params={'select': 'id', 'user_id': f'eq.{own_profile_id}', 'limit': '1'},
                                headers=auth_headers(settings.SUPABASE_ANON_KEY, token))
                            report['real_user_owner_access'][table] = own_rows_response.status_code

                    other_token = environment.get('QUBIT_TEST_OTHER_ACCESS_TOKEN')
                    if other_token and report['real_user_profile_linked']:
                        other_response, other_user = await auth_user(
                            client, base, settings.SUPABASE_ANON_KEY, other_token)
                        report['second_user_session_status'] = other_response.status_code
                        if other_user:
                            other_profile_response = await client.get(base + '/rest/v1/signup_users',
                                params={'select': 'id', 'auth_user_id': f"eq.{other_user['id']}", 'limit': '1'},
                                headers=auth_headers(settings.SUPABASE_ANON_KEY, other_token))
                            other_profiles = json_rows(other_profile_response) or []
                            cross_results = {}
                            if len(other_profiles) == 1:
                                other_profile_id = other_profiles[0]['id']
                                for table in ('signup_users', 'chats', 'chat_history', 'uploaded_files'):
                                    if table == 'signup_users':
                                        path = base + '/rest/v1/signup_users'
                                        params = {'select': 'id', 'id': f'eq.{other_profile_id}', 'limit': '1'}
                                    else:
                                        path = base + '/rest/v1/' + table
                                        params = {'select': 'id', 'user_id': f'eq.{other_profile_id}', 'limit': '1'}
                                    cross_response = await client.get(path, params=params,
                                        headers=auth_headers(settings.SUPABASE_ANON_KEY, token))
                                    cross_rows = json_rows(cross_response)
                                    cross_results[table] = {
                                        'http_status': cross_response.status_code,
                                        'other_user_rows_visible': (
                                            cross_response.status_code == 200 and bool(cross_rows)),
                                    }
                            report['cross_user_access'] = cross_results
                            report['cross_user_reads_isolated'] = len(cross_results) == 4 and all(
                                result['http_status'] in (200, 401, 403)
                                and not result['other_user_rows_visible']
                                for result in cross_results.values())
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
