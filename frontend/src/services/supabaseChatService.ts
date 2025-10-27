import { supabase } from '../integration/client';
import { ChatSession, ChatMessage } from './chatService';
import { Database } from '../integration/types';

type ChatRow = Database['public']['Tables']['chats']['Row'];
type ChatInsert = Database['public']['Tables']['chats']['Insert'];
type ChatHistoryRow = Database['public']['Tables']['chat_history']['Row'];
type ChatHistoryInsert = Database['public']['Tables']['chat_history']['Insert'];
type UploadedFileRow = Database['public']['Tables']['uploaded_files']['Row'];
type UploadedFileInsert = Database['public']['Tables']['uploaded_files']['Insert'];

export const supabaseChatService = {
  // Create a new chat session in Supabase
  async createChatSession(userId: number, session: ChatSession): Promise<number> {
    try {
      // Create the chat record
      const { data: chatData, error: chatError } = await supabase
        .from('chats')
        .insert({
          user_id: userId,
          chat_name: session.title
        })
        .select('id')
        .single();

      if (chatError) {
        console.error('Error creating chat in Supabase:', chatError);
        throw chatError;
      }

      const chatId = chatData.id;

      // If the session has messages, add the initial welcome message to chat_history
      if (session.messages.length > 0) {
        const welcomeMessage = session.messages[0];
        if (welcomeMessage.isBot) {
          await this.addMessageToSession(userId, chatId, '', welcomeMessage.content);
        }
      }

      return chatId;
    } catch (error) {
      console.error('Failed to create chat session in Supabase:', error);
      throw error;
    }
  },

  // Get all chat sessions for a user
  async getChatSessions(userId: number): Promise<ChatSession[]> {
    try {
      // Get all chats for the user
      const { data: chats, error: chatsError } = await supabase
        .from('chats')
        .select('*')
        .eq('user_id', userId)
        .order('created_at', { ascending: false });

      if (chatsError) {
        console.error('Error fetching chats from Supabase:', chatsError);
        throw chatsError;
      }

      if (!chats || chats.length === 0) {
        return [];
      }

      // Get chat history for all chats
      const chatIds = chats.map(chat => chat.id);
      const { data: chatHistory, error: historyError } = await supabase
        .from('chat_history')
        .select('*')
        .in('chat_id', chatIds)
        .order('created_at', { ascending: true });

      if (historyError) {
        console.error('Error fetching chat history from Supabase:', historyError);
        throw historyError;
      }

      // Convert to ChatSession format
      const sessions: ChatSession[] = chats.map(chat => {
        const messages: ChatMessage[] = [];
        const chatMessages = chatHistory?.filter(h => h.chat_id === chat.id) || [];

        // Convert chat history to messages
        chatMessages.forEach(history => {
          // Add user message if input_data exists
          if (history.input_data && history.input_data.trim()) {
            messages.push({
              id: `user_${history.id}`,
              content: history.input_data,
              isBot: false,
              timestamp: new Date(history.created_at)
            });
          }

          // Add bot message if output_data exists
          if (history.output_data && history.output_data.trim()) {
            messages.push({
              id: `bot_${history.id}`,
              content: history.output_data,
              isBot: true,
              timestamp: new Date(history.created_at)
            });
          }
        });

        // If no messages, add default welcome message
        if (messages.length === 0) {
          messages.push({
            id: '1',
            content: "Hello! I'm QubitChat AI, your intelligent document assistant. Upload some files and let's start a conversation!",
            isBot: true,
            timestamp: new Date(chat.created_at)
          });
        }

        return {
          id: chat.id.toString(),
          title: chat.chat_name || 'New Chat',
          messages,
          createdAt: new Date(chat.created_at),
          updatedAt: new Date(chat.created_at),
          isActive: false
        };
      });

      return sessions;
    } catch (error) {
      console.error('Failed to fetch chat sessions from Supabase:', error);
      throw error;
    }
  },

  // Delete a chat session
  async deleteChatSession(userId: number, chatId: number): Promise<void> {
    try {
      // First delete all chat history for this chat
      const { error: historyError } = await supabase
        .from('chat_history')
        .delete()
        .eq('chat_id', chatId)
        .eq('user_id', userId);

      if (historyError) {
        console.error('Error deleting chat history:', historyError);
        throw historyError;
      }

      // Then delete the chat
      const { error: chatError } = await supabase
        .from('chats')
        .delete()
        .eq('id', chatId)
        .eq('user_id', userId);

      if (chatError) {
        console.error('Error deleting chat:', chatError);
        throw chatError;
      }
    } catch (error) {
      console.error('Failed to delete chat session:', error);
      throw error;
    }
  },

  // Add a message pair (user input + bot output) to a chat session
  async addMessageToSession(userId: number, chatId: number, userMessage: string, assistantMessage: string): Promise<void> {
    try {
      const { error } = await supabase
        .from('chat_history')
        .insert({
          chat_id: chatId,
          user_id: userId,
          input_data: userMessage || '',
          output_data: assistantMessage || '',
          is_active: true,
          title: null
        });

      if (error) {
        console.error('Error adding message to chat history:', error);
        throw error;
      }
    } catch (error) {
      console.error('Failed to add message to session:', error);
      throw error;
    }
  },

  // Update chat name
  async updateChatName(userId: number, chatId: number, newName: string): Promise<void> {
    try {
      const { error } = await supabase
        .from('chats')
        .update({ chat_name: newName })
        .eq('id', chatId)
        .eq('user_id', userId);

      if (error) {
        console.error('Error updating chat name:', error);
        throw error;
      }
    } catch (error) {
      console.error('Failed to update chat name:', error);
      throw error;
    }
  },

  // Get a specific chat session
  async getChatSession(userId: number, chatId: number): Promise<ChatSession | null> {
    try {
      // Get the chat
      const { data: chat, error: chatError } = await supabase
        .from('chats')
        .select('*')
        .eq('id', chatId)
        .eq('user_id', userId)
        .single();

      if (chatError) {
        console.error('Error fetching chat:', chatError);
        return null;
      }

      if (!chat) {
        return null;
      }

      // Get chat history
      const { data: chatHistory, error: historyError } = await supabase
        .from('chat_history')
        .select('*')
        .eq('chat_id', chatId)
        .eq('user_id', userId)
        .order('created_at', { ascending: true });

      if (historyError) {
        console.error('Error fetching chat history:', historyError);
        throw historyError;
      }

      const messages: ChatMessage[] = [];

      // Convert chat history to messages
      if (chatHistory) {
        chatHistory.forEach(history => {
          // Add user message if input_data exists
          if (history.input_data && history.input_data.trim()) {
            messages.push({
              id: `user_${history.id}`,
              content: history.input_data,
              isBot: false,
              timestamp: new Date(history.created_at)
            });
          }

          // Add bot message if output_data exists
          if (history.output_data && history.output_data.trim()) {
            messages.push({
              id: `bot_${history.id}`,
              content: history.output_data,
              isBot: true,
              timestamp: new Date(history.created_at)
            });
          }
        });
      }

      // If no messages, add default welcome message
      if (messages.length === 0) {
        messages.push({
          id: '1',
          content: "Hello! I'm QubitChat AI, your intelligent document assistant. Upload some files and let's start a conversation!",
          isBot: true,
          timestamp: new Date(chat.created_at)
        });
      }

      return {
        id: chat.id.toString(),
        title: chat.chat_name || 'New Chat',
        messages,
        createdAt: new Date(chat.created_at),
        updatedAt: new Date(chat.created_at),
        isActive: false
      };
    } catch (error) {
      console.error('Failed to get chat session:', error);
      throw error;
    }
  },

  // Add uploaded file record to database
  async addUploadedFile(userId: number, chatSessionId: number, fileName: string, fileSize: number, fileType: string = 'pdf'): Promise<void> {
    try {
      const { error } = await supabase
        .from('uploaded_files')
        .insert({
          chat_session_id: chatSessionId,
          file_name: fileName,
          file_size: fileSize,
          file_type: fileType,
          user_id: userId
        });

      if (error) {
        console.error('Error saving uploaded file record:', error);
        throw error;
      }
    } catch (error) {
      console.error('Failed to save uploaded file record:', error);
      throw error;
    }
  },

  // Get uploaded files for a chat session
  async getUploadedFiles(chatSessionId: number): Promise<Array<{id: number, fileName: string, fileSize: number, fileType: string, uploadTimestamp: Date}>> {
    try {
      console.log('getUploadedFiles: Querying for chat session ID:', chatSessionId);
      
      const { data, error } = await supabase
        .from('uploaded_files')
        .select('id, file_name, file_size, file_type, upload_timestamp')
        .eq('chat_session_id', chatSessionId)
        .order('upload_timestamp', { ascending: true });

      if (error) {
        console.error('getUploadedFiles: Supabase error:', error);
        throw error;
      }

      console.log('getUploadedFiles: Raw data from Supabase:', data);

      const result = (data || []).map(file => ({
        id: file.id,
        fileName: file.file_name,
        fileSize: file.file_size,
        fileType: file.file_type,
        uploadTimestamp: new Date(file.upload_timestamp)
      }));
      
      console.log('getUploadedFiles: Mapped result:', result);
      return result;
    } catch (error) {
      console.error('getUploadedFiles: Failed to fetch uploaded files:', error);
      return [];
    }
  },

  // Delete uploaded file record
  async deleteUploadedFile(fileId: number): Promise<void> {
    try {
      const { error } = await supabase
        .from('uploaded_files')
        .delete()
        .eq('id', fileId);

      if (error) {
        console.error('Error deleting uploaded file record:', error);
        throw error;
      }
    } catch (error) {
      console.error('Failed to delete uploaded file record:', error);
      throw error;
    }
  }
};