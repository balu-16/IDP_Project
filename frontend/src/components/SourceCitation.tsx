import { useEffect, useState } from 'react';
import type { Source } from '@/lib/contracts';
import { apiFetch, errorMessage } from '@/lib/api';

export default function SourceCitation({ source, index, sessionId }: {
  source: Source; index: number; sessionId: string;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const documentId = source.metadata.document_id;
  const page = Number(source.metadata.page_start || 1);
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);
  const load = async () => {
    setLoading(true); setError(null);
    try {
      const response = await apiFetch('/api/v1/documents/' + encodeURIComponent(String(documentId)) +
        '/source?session_id=' + encodeURIComponent(sessionId));
      setUrl(URL.createObjectURL(await response.blob()));
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setLoading(false); }
  };
  return <details className="rounded border border-border p-2 text-xs">
    <summary className="cursor-pointer">[S{index + 1}] {String(source.metadata.file_name || 'Document')} · page {page}</summary>
    <p className="my-2 whitespace-pre-wrap">{source.document}</p>
    {documentId && !url && <button onClick={() => { void load(); }} disabled={loading} className="text-primary underline">
      {loading ? 'Loading original…' : 'Load original document'}
    </button>}
    {url && <a href={url + '#page=' + page} target="_blank" rel="noopener noreferrer" className="text-primary underline">Open original at page {page}</a>}
    {error && <p role="alert">{error}</p>}
  </details>;
}
