const rawApiBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim() ?? '';

const normalizedApiBaseUrl = rawApiBaseUrl.replace(/\/+$/, '');

export function apiUrl(path: string): string {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;

  if (!normalizedApiBaseUrl) {
    return normalizedPath;
  }

  return `${normalizedApiBaseUrl}${normalizedPath}`;
}
