import { supabaseChatService } from './supabaseChatService';
import type { Source } from '@/lib/contracts';

export interface ChatMessage {
  id: string; content: string; isBot: boolean; timestamp: Date;
  contextSources?: Source[]; retrievalTimeMs?: number; retrievalMethod?: string;
}
export interface ChatSession {
  id: string; title: string; messages: ChatMessage[];
  createdAt: Date; updatedAt: Date; isActive?: boolean; hasOlderMessages?: boolean;
}
class ChatService {
  private currentUserId: number | null = null;
  setUserId(userId: number | null) {
    if (this.currentUserId !== userId) localStorage.removeItem('activeSessionId');
    this.currentUserId = userId;
  }
  getCurrentUserId() { return this.currentUserId; }
  private owner() {
    if (!this.currentUserId) throw new Error('Sign in to access chat sessions.');
    return this.currentUserId;
  }
  async getAllSessions(offset = 0) {
    return supabaseChatService.getChatSessions(this.owner(), offset);
  }
  async getSession(sessionId: string, limit = 100) {
    return supabaseChatService.getChatSession(this.owner(), Number(sessionId), limit);
  }
  async createNewSession(): Promise<ChatSession> {
    const id = await supabaseChatService.createChatSession(this.owner());
    const session = await this.getSession(String(id));
    if (!session) throw new Error('Created chat could not be loaded.');
    this.setActiveSession(session.id);
    return session;
  }
  setActiveSession(sessionId: string) {
    localStorage.setItem('activeSessionId', this.owner() + ':' + sessionId);
  }
  getActiveSessionId(): string | null {
    const stored = localStorage.getItem('activeSessionId');
    const prefix = this.owner() + ':';
    return stored?.startsWith(prefix) ? stored.slice(prefix.length) : null;
  }
  async getActiveSession() {
    const id = this.getActiveSessionId();
    return id ? this.getSession(id) : null;
  }
  async deleteSession(id: string) {
    await supabaseChatService.deleteChatSession(this.owner(), Number(id));
    if (this.getActiveSessionId() === id) localStorage.removeItem('activeSessionId');
  }
  async updateSessionTitle(id: string, title: string) {
    await supabaseChatService.updateChatName(this.owner(), Number(id), title);
  }
}
export const chatService = new ChatService();
export default chatService;
