const API_BASE = (import.meta.env.VITE_API_BASE_URL?.trim() ?? '').replace(/\/+$/, '');

export function apiUrl(path: string): string {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;

  if (!API_BASE) {
    return normalizedPath;
  }

  return `${API_BASE}${normalizedPath}`;
}
