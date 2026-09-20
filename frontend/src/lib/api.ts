import { getSupabase } from '@/integration/client';

const API_BASE = (import.meta.env.VITE_API_BASE_URL?.trim() || 'http://localhost:8000').replace(/\/+$/, '');
export function apiUrl(path: string): string {
  return API_BASE + (path.startsWith('/') ? path : '/' + path);
}
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const { data, error } = await getSupabase().auth.getSession();
  if (error || !data.session) throw new Error('Please sign in again.');
  const headers = new Headers(init.headers);
  headers.set('Authorization', 'Bearer ' + data.session.access_token);
  const response = await fetch(apiUrl(path), { ...init, headers });
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    const message = body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string'
      ? body.detail : 'Request failed (HTTP ' + response.status + ')';
    throw new Error(message);
  }
  return response;
}
export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'The operation failed.';
}
