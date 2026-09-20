import { getSupabase } from '@/integration/client';
import { apiFetch } from '@/lib/api';
import { chatResponseSchema } from '@/lib/contracts';
import type { ChatMessage, ChatSession } from './chatService';

const welcome = (createdAt: string): ChatMessage => ({
  id: 'welcome', content: 'Upload a document, then ask a question about it.',
  isBot: true, timestamp: new Date(createdAt),
});

export const supabaseChatService = {
  async createChatSession(userId: number): Promise<number> {
    const { data, error } = await getSupabase().from('chats')
      .insert({ user_id: userId, chat_name: 'New Chat' }).select('id').single();
    if (error) throw error;
    return data.id;
  },

  async getChatSessions(userId: number, offset = 0): Promise<ChatSession[]> {
    const { data, error } = await getSupabase().from('chats')
      .select('id,chat_name,created_at').eq('user_id', userId)
      .order('created_at', { ascending: false }).order('id', { ascending: false }).range(offset, offset + 49);
    if (error) throw error;
    return (data ?? []).map(chat => ({
      id: String(chat.id), title: chat.chat_name || 'New Chat', messages: [],
      createdAt: new Date(chat.created_at), updatedAt: new Date(chat.created_at),
    }));
  },

  async getChatSession(userId: number, chatId: number, limit = 100): Promise<ChatSession | null> {
    const client = getSupabase();
    const { data: chat, error } = await client.from('chats').select('id,chat_name,created_at')
      .eq('id', chatId).eq('user_id', userId).maybeSingle();
    if (error) throw error;
    if (!chat) return null;
    const { data: history, error: historyError } = await client.from('chat_history')
      .select('id,input_data,output_data,created_at,provenance')
      .eq('chat_id', chatId).eq('user_id', userId)
      .order('created_at', { ascending: false }).order('id', { ascending: false }).limit(limit);
    if (historyError) throw historyError;
    const messages: ChatMessage[] = [];
    for (const row of [...(history ?? [])].reverse()) {
      if (row.input_data.trim()) messages.push({
        id: 'user_' + row.id, content: row.input_data, isBot: false, timestamp: new Date(row.created_at),
      });
      if (row.output_data.trim()) {
        const parsed = chatResponseSchema.safeParse(row.provenance);
        messages.push({
          id: 'bot_' + row.id, content: row.output_data, isBot: true, timestamp: new Date(row.created_at),
          contextSources: parsed.success ? parsed.data.context_sources : [],
          retrievalTimeMs: parsed.success ? parsed.data.retrieval_time_ms : undefined,
          retrievalMethod: parsed.success ? parsed.data.metadata.retrieval_method : undefined,
        });
      }
    }
    return {
      id: String(chat.id), title: chat.chat_name || 'New Chat', messages: messages.length ? messages : [welcome(chat.created_at)],
      createdAt: new Date(chat.created_at), updatedAt: new Date(history?.[0]?.created_at || chat.created_at),
      hasOlderMessages: history?.length === limit,
    };
  },

  async deleteChatSession(_userId: number, chatId: number): Promise<void> {
    await apiFetch('/api/v1/sessions/' + chatId, { method: 'DELETE' });
  },

  async updateChatName(userId: number, chatId: number, title: string): Promise<void> {
    const { error } = await getSupabase().from('chats').update({ chat_name: title.trim().slice(0, 100) })
      .eq('id', chatId).eq('user_id', userId);
    if (error) throw error;
  },
};
