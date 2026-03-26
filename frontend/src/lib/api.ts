const DEFAULT_API_BASE = 'https://idp-backend-798522160894.asia-south1.run.app';

const API_BASE = (import.meta.env.VITE_API_BASE_URL?.trim() || DEFAULT_API_BASE).replace(/\/+$/, '');

export function apiUrl(path: string): string {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;

  return `${API_BASE}${normalizedPath}`;
}
