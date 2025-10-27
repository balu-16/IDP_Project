/**
 * Frontend Chat Service
 * Handles all chat operations using Supabase only
 * No localStorage usage - all data is stored in Supabase
 */

import { supabaseChatService } from './supabaseChatService';

export interface ChatMessage {
  id: string;
  content: string;
  isBot: boolean;
  timestamp: Date;
  contextSources?: any[];
}

export interface ChatSession {
  id: string;
  title: string;
  messages: ChatMessage[];
  createdAt: Date;
  updatedAt: Date;
  isActive?: boolean;
}

class ChatService {
  private activeSessionId: string | null = null;
  private currentUserId: number | null = null;

  /**
   * Set the current user ID for all operations
   */
  setUserId(userId: number | null): void {
    this.currentUserId = userId;
  }

  /**
   * Get all chat sessions from Supabase
   */
  async getAllSessions(): Promise<ChatSession[]> {
    if (!this.currentUserId) {
      console.warn('No user ID set, cannot fetch chat sessions');
      return [];
    }

    try {
      return await supabaseChatService.getChatSessions(this.currentUserId);
    } catch (error) {
      console.error('Error loading chat sessions:', error);
      return [];
    }
  }

  /**
   * Create a new chat session
   */
  async createNewSession(): Promise<ChatSession> {
    if (!this.currentUserId) {
      throw new Error('No user ID set, cannot create chat session');
    }

    const newSession: ChatSession = {
      id: Date.now().toString(),
      title: 'New Chat',
      messages: [
        {
          id: '1',
          content: "Hello! I'm QubitChat AI, your intelligent document assistant. Upload some files and let's start a conversation!",
          isBot: true,
          timestamp: new Date()
        }
      ],
      createdAt: new Date(),
      updatedAt: new Date(),
      isActive: true
    };

    try {
      // Save to Supabase and get the database ID
      const chatId = await supabaseChatService.createChatSession(this.currentUserId, newSession);
      newSession.id = chatId.toString();
      this.setActiveSession(newSession.id);
      return newSession;
    } catch (error) {
      console.error('Failed to create new chat session:', error);
      throw error;
    }
  }

  /**
   * Get a specific chat session by ID
   */
  async getSession(sessionId: string): Promise<ChatSession | null> {
    if (!this.currentUserId) {
      console.warn('No user ID set, cannot fetch chat session');
      return null;
    }

    try {
      const sessions = await this.getAllSessions();
      return sessions.find(s => s.id === sessionId) || null;
    } catch (error) {
      console.error('Error fetching chat session:', error);
      return null;
    }
  }

  /**
   * Add a message pair to a chat session (user message + bot response)
   */
  async addMessagePair(sessionId: string, userMessage: string, botResponse: string): Promise<void> {
    if (!this.currentUserId) {
      throw new Error('No user ID set, cannot add message');
    }

    try {
      const chatId = parseInt(sessionId);
      await supabaseChatService.addMessageToSession(this.currentUserId, chatId, userMessage, botResponse);
      
      // Update chat name based on first user message if it's still "New Chat"
      const session = await this.getSession(sessionId);
      if (session && session.title === 'New Chat') {
        const newTitle = userMessage.substring(0, 50) + (userMessage.length > 50 ? '...' : '');
        await this.updateSessionTitle(sessionId, newTitle);
      }
    } catch (error) {
      console.error('Failed to add message pair:', error);
      throw error;
    }
  }

  /**
   * Delete a chat session
   */
  async deleteSession(sessionId: string): Promise<void> {
    if (!this.currentUserId) {
      throw new Error('No user ID set, cannot delete chat session');
    }

    try {
      const chatId = parseInt(sessionId);
      await supabaseChatService.deleteChatSession(this.currentUserId, chatId);
      
      // If the deleted session was active, clear the active session
      if (this.activeSessionId === sessionId) {
        this.activeSessionId = null;
        localStorage.removeItem('activeSessionId');
      }
    } catch (error) {
      console.error('Error deleting chat session:', error);
      throw error;
    }
  }

  /**
   * Set the active chat session
   */
  setActiveSession(sessionId: string): void {
    this.activeSessionId = sessionId;
    // Persist to localStorage so it survives page refreshes
    localStorage.setItem('activeSessionId', sessionId);
  }

  /**
   * Get the active chat session ID
   */
  getActiveSessionId(): string | null {
    // First check memory, then localStorage
    if (this.activeSessionId) {
      return this.activeSessionId;
    }
    
    // Try to recover from localStorage
    const stored = localStorage.getItem('activeSessionId');
    if (stored) {
      this.activeSessionId = stored;
      return stored;
    }
    
    return null;
  }

  /**
   * Get the active chat session
   */
  async getActiveSession(): Promise<ChatSession | null> {
    const activeId = this.getActiveSessionId();
    return activeId ? await this.getSession(activeId) : null;
  }

  /**
   * Clear all chat sessions (for logout or reset)
   */
  async clearAllSessions(): Promise<void> {
    if (!this.currentUserId) {
      throw new Error('No user ID set, cannot clear chat sessions');
    }

    try {
      const sessions = await this.getAllSessions();
      for (const session of sessions) {
        await this.deleteSession(session.id);
      }
      this.activeSessionId = null;
    } catch (error) {
      console.error('Error clearing all sessions:', error);
      throw error;
    }
  }

  /**
   * Update the title of a chat session
   */
  async updateSessionTitle(sessionId: string, newTitle: string): Promise<void> {
    if (!this.currentUserId) {
      throw new Error('No user ID set, cannot update session title');
    }

    try {
      const chatId = parseInt(sessionId);
      await supabaseChatService.updateChatName(this.currentUserId, chatId, newTitle);
    } catch (error) {
      console.error('Error updating session title:', error);
      throw error;
    }
  }

  /**
   * Get current user ID
   */
  getCurrentUserId(): number | null {
    return this.currentUserId;
  }
}

// Export singleton instance
export const chatService = new ChatService();
export default chatService;