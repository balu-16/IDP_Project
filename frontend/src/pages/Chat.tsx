import React, { useEffect, useRef, useState } from 'react';
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Menu, Paperclip, Send, Trash2 } from 'lucide-react';
import CoffeeBackground from '@/components/CoffeeBackground';
import Sidebar from '@/components/Sidebar';
import ChatBubble from '@/components/ChatBubble';
import FileDropzone from '@/components/FileDropzone';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { useAuth } from '@/components/auth/AuthContext';
import { apiFetch, errorMessage } from '@/lib/api';
import { chatResponseSchema, type RetrievalStrategy } from '@/lib/contracts';
import chatService, { type ChatSession } from '@/services/chatService';
import { cn } from '@/lib/utils';
import { showToast } from '@/components/Toast';

interface UploadedDocument {
  id: number; document_id: string | null; file_name: string;
  status: string; chunks_count: number;
}

const Chat: React.FC = () => {
  const { user } = useAuth();
  const cache = useQueryClient();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [input, setInput] = useState('');
  const [strategy, setStrategy] = useState<RetrievalStrategy>('cosine');
  const [sidebarOpen, setSidebarOpen] = useState(window.innerWidth >= 1024);
  const [collapsed, setCollapsed] = useState(localStorage.getItem('sidebar-collapsed') === 'true');
  const [uploadOpen, setUploadOpen] = useState(false);
  const [historyLimit, setHistoryLimit] = useState(100);
  const end = useRef<HTMLDivElement>(null);
  const userId = user?.id;
  const sessionKey = (id: string) => ['session', userId, id, historyLimit] as const;
  const sessions = useInfiniteQuery({
    queryKey: ['sessions', userId],
    queryFn: ({ pageParam }) => chatService.getAllSessions(pageParam),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => last.length === 50 ? pages.length * 50 : undefined,
    enabled: !!userId,
  });
  const allSessions = sessions.data?.pages.flat() ?? [];
  useEffect(() => {
    if (!sessionId && sessions.data) {
      const first = sessions.data.pages[0]?.[0]?.id;
      const active = chatService.getActiveSessionId();
      if (active || first) setSessionId(active || first);
    }
  }, [sessionId, sessions.data]);
  const session = useQuery({
    queryKey: sessionKey(sessionId || ''),
    queryFn: () => chatService.getSession(sessionId!, historyLimit),
    enabled: !!sessionId,
  });
  const files = useQuery({
    queryKey: ['documents', userId, sessionId],
    queryFn: async ({ signal }) => {
      const response = await apiFetch('/api/v1/documents?session_id=' + encodeURIComponent(sessionId!), { signal });
      return (await response.json()).documents as UploadedDocument[];
    },
    enabled: !!sessionId,
  });
  const refresh = async (id: string) => {
    await Promise.all([
      cache.invalidateQueries({ queryKey: ['sessions', userId] }),
      cache.invalidateQueries({ queryKey: ['session', userId, id] }),
      cache.invalidateQueries({ queryKey: ['documents', userId, id] }),
    ]);
  };
  const select = (id: string) => {
    setSessionId(id); setHistoryLimit(100); setInput(''); chatService.setActiveSession(id);
    if (window.innerWidth < 1024) setSidebarOpen(false);
  };
  const create = useMutation({
    mutationFn: () => chatService.createNewSession(),
    onSuccess: async created => { select(created.id); await refresh(created.id); },
    onError: cause => showToast('error', 'Could not create chat', errorMessage(cause)),
  });
  const send = useMutation({
    mutationFn: async ({ id, text, runId }: { id: string; text: string; runId: string }) => {
      const response = await apiFetch('/api/chat', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: id, message: text, run_id: runId,
          temperature: 0, retrieval: { strategy, top_k: 5, candidate_limit: 64, threshold: 0.5, shots: 1024, seed: 0 } }),
      });
      return chatResponseSchema.parse(await response.json());
    },
    onSuccess: async (response, variables) => {
      if (response.session_id !== variables.id) throw new Error('Response session mismatch');
      // Update the originating session only, even if the user navigated meanwhile.
      cache.setQueryData<ChatSession | null>(sessionKey(variables.id), old => old ? {
        ...old, messages: [...old.messages,
          { id: variables.runId + '-user', content: variables.text, isBot: false, timestamp: new Date() },
          { id: variables.runId + '-bot', content: response.response, isBot: true, timestamp: new Date(),
            contextSources: response.context_sources, retrievalTimeMs: response.retrieval_time_ms,
            retrievalMethod: response.metadata.retrieval_method }],
      } : old);
      await refresh(variables.id);
    },
    onError: cause => showToast('error', 'Message failed', errorMessage(cause)),
  });
  const upload = useMutation({
    mutationFn: async ({ id, selected }: { id: string; selected: File[] }) => {
      // Sequential uploads keep CPU work bounded and report individual failures.
      const failures: string[] = [];
      for (const file of selected) {
        const body = new FormData(); body.append('file', file); body.append('session_id', id);
        try { await apiFetch('/api/v1/upload_pdf', { method: 'POST', body }); }
        catch (cause) { failures.push(file.name + ': ' + errorMessage(cause)); }
      }
      return failures;
    },
    onSuccess: async (failures, variables) => {
      await refresh(variables.id);
      if (failures.length) showToast('error', 'Some uploads failed', failures.join('\n'));
      else showToast('success', 'Documents processed');
    },
    onError: cause => showToast('error', 'Upload failed', errorMessage(cause)),
  });
  const removeSession = async (id: string) => {
    try {
      await chatService.deleteSession(id);
      cache.removeQueries({ queryKey: ['session', userId, id] });
      if (id === sessionId) {
        setSessionId(null);
        // Remove stale list entries before the selection effect can run.
        cache.setQueryData<typeof sessions.data>(['sessions', userId], old => old ? {
          ...old, pages: old.pages.map(page => page.filter(item => item.id !== id)),
        } : old);
      }
      await cache.invalidateQueries({ queryKey: ['sessions', userId] });
    } catch (cause) { showToast('error', 'Deletion failed', errorMessage(cause)); }
  };
  const renameSession = async (id: string, title: string) => {
    try { await chatService.updateSessionTitle(id, title); await refresh(id); }
    catch (cause) { showToast('error', 'Rename failed', errorMessage(cause)); }
  };
  const removeDocument = async (id: string) => {
    if (!sessionId || !window.confirm('Delete this document from this chat?')) return;
    const origin = sessionId;
    try {
      await apiFetch('/api/v1/documents/' + id + '?session_id=' + origin, { method: 'DELETE' });
      await refresh(origin);
    } catch (cause) { showToast('error', 'Deletion failed', errorMessage(cause)); }
  };
  const submitting = send.isPending && send.variables?.id === sessionId;
  const uploading = upload.isPending && upload.variables?.id === sessionId;
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth' }); }, [session.data?.messages.length, submitting]);
  useEffect(() => {
    const resize = () => setSidebarOpen(window.innerWidth >= 1024);
    window.addEventListener('resize', resize);
    return () => window.removeEventListener('resize', resize);
  }, []);
  const submit = (event?: React.FormEvent) => {
    event?.preventDefault();
    if (!sessionId || !input.trim() || send.isPending) return;
    const text = input.trim(); setInput('');
    send.mutate({ id: sessionId, text, runId: crypto.randomUUID() });
  };

  return <div className="relative flex h-screen overflow-hidden">
    <CoffeeBackground variant="muted" />
    <Sidebar isOpen={sidebarOpen} onToggle={() => setSidebarOpen(!sidebarOpen)}
      isCollapsed={collapsed} onToggleCollapse={() => {
        setCollapsed(!collapsed); localStorage.setItem('sidebar-collapsed', String(!collapsed));
      }}
      onNewChat={() => { if (!create.isPending) create.mutate(); }}
      chatHistory={allSessions.map(s => ({ id: s.id, title: s.title, timestamp: s.updatedAt, isActive: s.id === sessionId }))}
      onSelectChat={select} onDeleteChat={removeSession} onRenameChat={renameSession}
      onLoadMore={sessions.hasNextPage ? () => { void sessions.fetchNextPage(); } : undefined} />
    <main className={cn('relative z-10 flex min-w-0 flex-1 flex-col', collapsed ? 'lg:ml-20' : 'lg:ml-64')}>
      <header className="flex items-center gap-3 border-b border-border px-4 py-3">
        <Button variant="ghost" aria-label="Toggle chat sidebar" onClick={() => {
          if (window.innerWidth < 1024) setSidebarOpen(!sidebarOpen); else setCollapsed(!collapsed);
        }}><Menu size={20} /></Button>
        <h1 className="truncate font-semibold">{session.data?.title || 'QubitChat'}</h1>
        <label className="ml-auto flex items-center gap-2 text-sm">
          Retrieval
          <select aria-label="Retrieval method" value={strategy} onChange={e => setStrategy(e.target.value as RetrievalStrategy)}
            className="rounded border border-border bg-surface p-2">
            <option value="cosine">Cosine</option>
            <option value="grover">Grover simulation</option>
            <option value="closed_form">Analytical control</option>
            <option value="classical_sampling">Sampling control</option>
          </select>
        </label>
      </header>
      <div className="flex-1 overflow-y-auto p-4 md:p-6">
        {(sessions.error || session.error) && <p role="alert">{errorMessage(sessions.error || session.error)}</p>}
        {!sessionId && !sessions.isLoading && <Button onClick={() => create.mutate()} disabled={create.isPending}>Start a chat</Button>}
        {sessionId && session.data === null && <p>Chat unavailable. Select another chat or start a new one.</p>}
        {session.isLoading && sessionId && <p role="status">Loading chat…</p>}
        {session.data?.hasOlderMessages && <Button variant="outline" onClick={() => setHistoryLimit(historyLimit + 100)}>Load older messages</Button>}
        {session.data?.messages.map(message => <ChatBubble key={message.id}
          message={message.content} isBot={message.isBot} timestamp={message.timestamp}
          retrievalTimeMs={message.retrievalTimeMs} contextSources={message.contextSources}
          retrievalMethod={message.retrievalMethod} sessionId={sessionId || undefined} />)}
        {submitting && <>
          <ChatBubble message={send.variables.text} isBot={false} timestamp={new Date()} />
          <ChatBubble message="" isBot timestamp={new Date()} isTyping />
        </>}
        {send.isError && send.variables?.id === sessionId && <div role="alert">
          <p>{errorMessage(send.error)}</p>
          <Button variant="outline" onClick={() => send.mutate(send.variables)}>Retry message</Button>
        </div>}
        <div ref={end} />
      </div>
      <footer className="border-t border-border bg-surface/90 p-4">
        {files.error && <p role="alert">{errorMessage(files.error)}</p>}
        <div className="mb-3 flex flex-wrap gap-2">
          {files.data?.map(file => <span key={file.id} className="flex items-center gap-1 rounded border border-border px-2 py-1 text-xs">
            {file.file_name} · {file.status}
            {file.document_id && <button aria-label={'Delete ' + file.file_name}
              onClick={() => { void removeDocument(file.document_id!); }}><Trash2 size={14} /></button>}
          </span>)}
        </div>
        {uploading && <p role="status" className="mb-2 text-sm">Processing documents…</p>}
        <form onSubmit={submit} className="flex gap-2">
          <Input aria-label="Question" value={input} onChange={e => setInput(e.target.value)}
            maxLength={2000} placeholder="Ask about your documents" disabled={!session.data || send.isPending || uploading} />
          <Button type="button" variant="outline" aria-label="Upload documents" disabled={!session.data || upload.isPending}
            onClick={() => setUploadOpen(true)}><Paperclip size={20} /></Button>
          <Button type="submit" aria-label="Send question" disabled={!input.trim() || !session.data || send.isPending || uploading}>
            <Send size={18} /></Button>
        </form>
        <p className="mt-2 text-center text-xs text-text-secondary">Check the cited pages when an answer matters.</p>
      </footer>
    </main>
    <Dialog open={uploadOpen} onOpenChange={setUploadOpen}>
      <DialogContent><DialogHeader><DialogTitle>Upload documents</DialogTitle>
        <DialogDescription>PDF, PNG and JPEG files, up to 10 MB each.</DialogDescription></DialogHeader>
        <FileDropzone onFilesChange={selected => {
          if (!sessionId) return;
          setUploadOpen(false);
          upload.mutate({ id: sessionId, selected: selected.map(item => item.file) });
        }} />
      </DialogContent>
    </Dialog>
  </div>;
};
export default Chat;
