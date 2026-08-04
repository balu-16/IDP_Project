const LOCAL_API_BASE = 'http://localhost:8000';

const configuredApiBase = import.meta.env.VITE_API_BASE_URL?.trim() || '';
const runningOnLocalhost =
  typeof window !== 'undefined' &&
  ['localhost', '127.0.0.1', '::1'].includes(window.location.hostname);

// Keep local development pinned to local backend even if a remote env value is present.
const API_BASE = (runningOnLocalhost ? LOCAL_API_BASE : configuredApiBase || LOCAL_API_BASE).replace(
  /\/+$/,
  ''
);

export function apiUrl(path: string): string {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;

  return `${API_BASE}${normalizedPath}`;
}
