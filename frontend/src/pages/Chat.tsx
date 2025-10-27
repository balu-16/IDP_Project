import React, { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Send, Paperclip, Plus, Menu, Mic, MicOff } from 'lucide-react';
import CoffeeBackground from '@/components/CoffeeBackground';
import Sidebar from '@/components/Sidebar';
import ChatBubble from '@/components/ChatBubble';
import FileDropzone from '@/components/FileDropzone';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { showToast } from '@/components/Toast';
import { cn } from '@/lib/utils';
import { useAuth } from '@/components/auth/AuthContext';
import chatService, { ChatMessage, ChatSession } from '@/services/chatService';
import { supabaseChatService } from '@/services/supabaseChatService';

// Use local chat service types
type Message = ChatMessage;

interface ChatHistory {
  id: string;
  title: string;
  timestamp: Date;
  isActive?: boolean;
  message_count: number;
  latest_input?: string;
  latest_output?: string;
}

interface FileItem {
  id: string;
  file: File;
  type: 'pdf' | 'image';
}

interface UploadedFileRecord {
  id: number;
  fileName: string;
  fileSize: number;
  fileType: string;
  uploadTimestamp: Date;
}

const Chat: React.FC = () => {
  const { user, token } = useAuth();
  const [currentSession, setCurrentSession] = useState<ChatSession | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [isUploadingFiles, setIsUploadingFiles] = useState(false);
  const [uploadingFileNames, setUploadingFileNames] = useState<string[]>([]);
  const [isSidebarOpen, setIsSidebarOpen] = useState(() => {
    // Initialize sidebar as open on desktop, closed on mobile
    if (typeof window !== 'undefined') {
      return window.innerWidth >= 1024;
    }
    return false;
  });
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(() => {
    const saved = localStorage.getItem('sidebar-collapsed');
    return saved ? JSON.parse(saved) : false;
  });
  const [showFileDropzone, setShowFileDropzone] = useState(false);
  const [uploadedFiles, setUploadedFiles] = useState<FileItem[]>([]);
  const [uploadedFileRecords, setUploadedFileRecords] = useState<UploadedFileRecord[]>([]);
  const [chatHistory, setChatHistory] = useState<ChatHistory[]>([]);


  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Handle window resize for sidebar responsiveness
  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth >= 1024) {
        setIsSidebarOpen(true);
      } else {
        setIsSidebarOpen(false);
      }
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // Initialize chat session when component mounts
  useEffect(() => {
    if (user) {
      // Set user ID in chat service
      chatService.setUserId(user.id);
      initializeChatSession();
      loadChatHistory().catch(error => console.error('Failed to load chat history:', error));
    }
  }, [user]);

  const initializeChatSession = async () => {
    if (!user) {
      console.error('No user available for initializing chat session');
      return;
    }
    
    try {
      // Try to load active session first
      let activeSession = await chatService.getActiveSession();
      
      if (!activeSession) {
        // No active session found, check if there are any existing sessions
        const allSessions = await chatService.getAllSessions();
        
        if (allSessions.length > 0) {
          // Use the most recent session
          activeSession = allSessions[0];
          chatService.setActiveSession(activeSession.id);
        } else {
          // No sessions exist, create a new one
          activeSession = await chatService.createNewSession();
        }
      }
      
      setCurrentSession(activeSession);
      setMessages(activeSession.messages);
      
      // Load uploaded files for the active session
      await loadUploadedFiles(activeSession.id);
    } catch (error) {
      console.error('Failed to initialize chat session:', error);
      showToast('error', 'Error', 'Failed to initialize chat session');
    }
  };

  const handleSendMessage = async () => {
    if (!inputValue.trim() || !user || !currentSession) {
      if (!user) {
        showToast('error', 'Authentication Required', 'Please log in to send messages');
      }
      return;
    }

    const currentMessage = inputValue;
    setInputValue('');
    setIsTyping(true);

    // Add user message to UI immediately
    const userMessage = {
      id: `msg_${Date.now()}_user`,
      content: currentMessage,
      isBot: false,
      timestamp: new Date()
    };

    setMessages(prev => [...prev, userMessage]);

    try {
      // Call the chat API with authentication and session ID for filtering
      const response = await fetch('http://localhost:8000/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': token ? `Bearer ${token}` : '',
        },
        body: JSON.stringify({
          message: currentMessage,
          user_id: user.id,
          session_id: currentSession?.id, // Add session ID to filter documents
          use_context: true,
          force_general: false,
          max_context_results: 5, // Increased to check more documents
          temperature: 0.7
        })
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();
      
      const botResponse = data.response || "I apologize, but I couldn't generate a response. Please try again.";
      
      // Add bot message to UI
      const botMessage = {
        id: `msg_${Date.now()}_bot`,
        content: botResponse,
        isBot: true,
        timestamp: new Date(),
        contextSources: data.context_sources
      };

      setMessages(prev => [...prev, botMessage]);
      
      // Save message pair to Supabase
      await chatService.addMessagePair(currentSession.id, currentMessage, botResponse);
      
      // Show success toast if context was used
      if (data.context_used && data.context_sources?.length > 0) {
        showToast('success', 'Context Found', `Used ${data.context_sources.length} document(s) for context`);
      }
      
      // Refresh chat history display
      await loadChatHistory().catch(error => console.error('Failed to refresh chat history:', error));
      
    } catch (error) {
      console.error('Chat API error:', error);
      
      // Add error message to UI
      const errorMessage = {
        id: `msg_${Date.now()}_error`,
        content: "I'm sorry, I'm having trouble connecting to the server right now. Please check if the backend is running and try again.",
        isBot: true,
        timestamp: new Date()
      };
      
      setMessages(prev => [...prev, errorMessage]);
      
      // Try to save error message pair to Supabase
      try {
        await chatService.addMessagePair(currentSession.id, currentMessage, errorMessage.content);
      } catch (saveError) {
        console.error('Failed to save error message:', saveError);
      }
      
      showToast('error', 'Connection Error', 'Failed to get response from AI');
    } finally {
      setIsTyping(false);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  // Load uploaded files for a chat session
  const loadUploadedFiles = async (chatSessionId: string) => {
    if (!chatSessionId) {
      console.log('loadUploadedFiles: No chatSessionId provided');
      return;
    }
    
    try {
      console.log('loadUploadedFiles: Loading files for session:', chatSessionId);
      const sessionIdNumber = parseInt(chatSessionId, 10);
      
      if (isNaN(sessionIdNumber)) {
        console.error('loadUploadedFiles: Invalid session ID:', chatSessionId);
        return;
      }
      
      const files = await supabaseChatService.getUploadedFiles(sessionIdNumber);
      console.log('loadUploadedFiles: Retrieved files:', files);
      
      setUploadedFileRecords(files);
      
      if (files.length > 0) {
        console.log('loadUploadedFiles: Successfully loaded', files.length, 'files');
      } else {
        console.log('loadUploadedFiles: No files found for session', sessionIdNumber);
      }
    } catch (error) {
      console.error('Failed to load uploaded files:', error);
      setUploadedFileRecords([]);
    }
  };

  // Load chat history from Supabase
  const loadChatHistory = async () => {
    if (!user) return;
    
    try {
      const sessions = await chatService.getAllSessions();
      const activeSessionId = currentSession?.id;
      
      const chatHistoryItems: ChatHistory[] = sessions.map((session) => ({
        id: session.id,
        title: session.title,
        timestamp: session.updatedAt,
        message_count: session.messages.length,
        latest_input: session.messages.filter(m => !m.isBot).pop()?.content,
        latest_output: session.messages.filter(m => m.isBot).pop()?.content,
        isActive: session.id === activeSessionId
      }));
      
      // Sort by most recent first
      chatHistoryItems.sort((a, b) => b.timestamp.getTime() - a.timestamp.getTime());
      setChatHistory(chatHistoryItems);
    } catch (error) {
      console.error('Failed to load chat history:', error);
    }
  };

  const handleNewChat = async () => {
    if (!user) {
      console.error('No user available for creating new chat');
      showToast('error', 'Error', 'Please log in to create a new chat');
      return;
    }
    
    try {
      // Create a new chat session
      const newSession = await chatService.createNewSession();
      setCurrentSession(newSession);
      
      // Set initial welcome message
      setMessages([{
        id: '1',
        content: "Hello! I'm QubitChat AI, your intelligent document assistant. Upload some files and let's start a conversation!",
        isBot: true,
        timestamp: new Date()
      }]);
      setUploadedFiles([]);
      setUploadedFileRecords([]);
      
      // Set new session as active
      await chatService.setActiveSession(newSession.id);
      
      // Refresh chat history to include the new session
      await loadChatHistory().catch(error => console.error('Failed to refresh chat history:', error));
      
      // Only close sidebar on mobile devices
      if (window.innerWidth < 1024) {
        setIsSidebarOpen(false);
      }
      showToast('success', 'New Chat Started', 'Ready for your questions!');
    } catch (error) {
      console.error('Error creating new chat:', error);
      showToast('error', 'Error', 'Failed to create new chat');
    }
  };

  const handleSelectChat = async (sessionId: string) => {
    if (!user) return;
    
    try {
      const session = await chatService.getSession(sessionId);
      if (session) {
        setCurrentSession(session);
        setMessages(session.messages);
        
        // Load uploaded files for this session
        await loadUploadedFiles(sessionId);
        
        // Set this session as active
        chatService.setActiveSession(sessionId);
        
        // Update chat history to mark this chat as active
        setChatHistory(prev => prev.map(chat => ({
          ...chat,
          isActive: chat.id === sessionId
        })));
        
        // Close sidebar on mobile after selecting a chat
        if (window.innerWidth < 1024) {
          setIsSidebarOpen(false);
        }
      }
    } catch (error) {
      console.error('Failed to load chat session:', error);
      showToast('error', 'Error', 'Failed to load chat session');
    }
  };

  const toggleSidebarCollapse = () => {
    const newCollapsed = !isSidebarCollapsed;
    setIsSidebarCollapsed(newCollapsed);
    localStorage.setItem('sidebar-collapsed', JSON.stringify(newCollapsed));
  };

  const handleDeleteChat = async (sessionId: string) => {
    if (!user) return;
    
    try {
      // Delete session using chat service
      await chatService.deleteSession(sessionId);
      
      // Remove the deleted chat from the UI immediately
      setChatHistory(prev => prev.filter(chat => chat.id !== sessionId));
      
      // Check if we deleted the active session
      const wasActive = currentSession?.id === sessionId;
      
      if (wasActive) {
        // Get remaining chats after deletion
        const remainingChats = chatHistory.filter(chat => chat.id !== sessionId);
        
        if (remainingChats.length > 0) {
          // Switch to the most recent remaining chat
          const mostRecentChat = remainingChats[0];
          await handleSelectChat(mostRecentChat.id);
        } else {
          // Only create a new chat if no other chats exist
          const newSession = await chatService.createNewSession();
          setCurrentSession(newSession);
          setMessages([{
            id: '1',
            content: "Hello! I'm QubitChat AI, your intelligent document assistant. Upload some files and let's start a conversation!",
            isBot: true,
            timestamp: new Date()
          }]);
          setUploadedFiles([]);
          chatService.setActiveSession(newSession.id);
        }
      }
      
      // Refresh chat history to ensure consistency with backend
      await loadChatHistory().catch(error => console.error('Failed to refresh chat history:', error));
      
      showToast('success', 'Chat Deleted', 'Chat has been successfully deleted.');
    } catch (error) {
      console.error('Error deleting chat:', error);
      showToast('error', 'Error', 'Failed to delete chat');
      // Refresh chat history on error to restore correct state
      await loadChatHistory().catch(refreshError => console.error('Failed to refresh chat history after error:', refreshError));
    }
  };

  const handleRenameChat = async (sessionId: string, newTitle: string) => {
    try {
      // Update session title using chat service
      await chatService.updateSessionTitle(sessionId, newTitle);
      
      // Refresh chat history to reflect the change
      loadChatHistory().catch(error => console.error('Failed to refresh chat history:', error));
      
      showToast('success', 'Chat Renamed', `Chat renamed to "${newTitle}"`);
    } catch (error) {
      console.error('Error renaming chat:', error);
      showToast('error', 'Error', 'Failed to rename chat');
    }
  };

  const clearDatabase = async () => {
    try {
      const response = await fetch('http://localhost:8000/api/v1/clear_pdfs', {
        method: 'DELETE',
        headers: {
          'Authorization': token ? `Bearer ${token}` : '',
        },
      });
      
      if (!response.ok) {
        throw new Error(`Failed to clear database: ${response.status}`);
      }
      
      showToast('success', 'Database Cleared', 'All previous documents have been removed from the database.');
      return true;
    } catch (error) {
      console.error('Failed to clear database:', error);
      showToast('error', 'Clear Failed', 'Failed to clear the database. Please try again.');
      return false;
    }
  };

  const handleFilesChange = async (files: FileItem[]) => {
    setUploadedFiles(files);
    if (files.length > 0) {
      setShowFileDropzone(false);
      setIsUploadingFiles(true);
      setUploadingFileNames(files.map(f => f.file.name));
      
      // Add processing message immediately
      const processingMessage: Message = {
        id: `processing_${Date.now()}`,
        content: `Please wait while I process ${files.length} file(s): ${files.map(f => f.file.name).join(', ')}...`,
        isBot: true,
        timestamp: new Date()
      };
      setMessages(prev => [...prev, processingMessage]);
      
      try {
        // Upload each file to the backend with session ID
        const uploadPromises = files.map(async (fileItem) => {
          const formData = new FormData();
          formData.append('file', fileItem.file);
          
          // Add session ID to associate PDF with this chat session
          if (currentSession?.id) {
            formData.append('session_id', currentSession.id);
          }
          if (user?.id) {
            formData.append('user_id', user.id.toString());
          }
          
          try {
            const response = await fetch('http://localhost:8000/api/v1/upload_pdf', {
              method: 'POST',
              headers: {
                'Authorization': token ? `Bearer ${token}` : '',
              },
              body: formData
            });
            
            if (!response.ok) {
              throw new Error(`Upload failed: ${response.status}`);
            }
            
            const result = await response.json();
            return { success: true, filename: fileItem.file.name, result };
          } catch (error) {
            console.error(`Failed to upload ${fileItem.file.name}:`, error);
            return { success: false, filename: fileItem.file.name, error: error.message };
          }
        });
        
        const uploadResults = await Promise.all(uploadPromises);
        const successfulUploads = uploadResults.filter(r => r.success);
        const failedUploads = uploadResults.filter(r => !r.success);
        
        // Remove the processing message
        setMessages(prev => prev.filter(msg => msg.id !== processingMessage.id));
        
        if (successfulUploads.length > 0) {
          showToast('success', 'Files Uploaded', `Successfully uploaded ${successfulUploads.length} file(s)`);
          
          // Save uploaded file records to database
          if (currentSession && user) {
            const savePromises = successfulUploads.map(async (upload, index) => {
              const fileItem = files[uploadResults.findIndex(r => r.filename === upload.filename)];
              if (fileItem) {
                try {
                  await supabaseChatService.addUploadedFile(
                    user.id,
                    parseInt(currentSession.id, 10),
                    upload.filename,
                    fileItem.file.size,
                    fileItem.type
                  );
                } catch (error) {
                  console.error(`Failed to save file record for ${upload.filename}:`, error);
                }
              }
            });
            
            await Promise.all(savePromises);
            
            // Refresh uploaded file records
            await loadUploadedFiles(currentSession.id);
          }
          
          // Add system message about successful uploads
          const systemMessage: Message = {
            id: Date.now().toString(),
            content: `I've successfully processed ${successfulUploads.length} file(s): ${successfulUploads.map(r => r.filename).join(', ')}. You can now ask me questions about their content!`,
            isBot: true,
            timestamp: new Date()
          };
          
          setMessages(prev => [...prev, systemMessage]);
        }
        
        if (failedUploads.length > 0) {
          showToast('error', 'Upload Failed', `Failed to upload ${failedUploads.length} file(s): ${failedUploads.map(r => r.filename).join(', ')}`);
          
          // Add error message about failed uploads
          const errorMessage: Message = {
            id: Date.now().toString(),
            content: `Failed to process ${failedUploads.length} file(s): ${failedUploads.map(r => r.filename).join(', ')}. Please try uploading them again.`,
            isBot: true,
            timestamp: new Date()
          };
          
          setMessages(prev => [...prev, errorMessage]);
        }
      } catch (error) {
        console.error('Upload process failed:', error);
        // Remove the processing message
        setMessages(prev => prev.filter(msg => msg.id !== processingMessage.id));
        
        showToast('error', 'Upload Error', 'An unexpected error occurred during file upload');
        
        const errorMessage: Message = {
          id: Date.now().toString(),
          content: 'An unexpected error occurred while processing your files. Please try again.',
          isBot: true,
          timestamp: new Date()
        };
        
        setMessages(prev => [...prev, errorMessage]);
      } finally {
        setIsUploadingFiles(false);
        setUploadingFileNames([]);
      }
    }
  };

  return (
    <div className="relative min-h-screen flex">
      {/* Muted Coffee Background */}
      <CoffeeBackground variant="muted" />

      {/* Sidebar */}
      <Sidebar
        isOpen={isSidebarOpen}
        onToggle={() => setIsSidebarOpen(!isSidebarOpen)}
        onNewChat={handleNewChat}
        chatHistory={chatHistory}
        onSelectChat={handleSelectChat}
        onDeleteChat={handleDeleteChat}
        onRenameChat={handleRenameChat}
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={toggleSidebarCollapse}
      />



      {/* Hamburger Menu Button */}
      <div className={cn(
        "fixed top-6 z-50 transition-all duration-300",
        isSidebarCollapsed ? "left-[88px]" : "left-[272px]"
      )}>
        <button
          onClick={toggleSidebarCollapse}
          className="p-2 rounded-lg bg-surface-secondary/80 backdrop-blur-sm text-text-secondary hover:text-text-primary transition-colors"
          title={isSidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          <Menu size={16} />
        </button>
      </div>

      {/* Main Chat Area */}
        <div className={cn(
          "flex-1 flex flex-col relative z-10 min-w-0 transition-all duration-300",
          isSidebarCollapsed ? "ml-20 pl-12" : "ml-64 pl-12"
        )}>
        {/* Chat Messages */}
          <div className={cn(
            "flex-1 overflow-y-auto custom-scrollbar p-6 min-h-0",
            uploadedFileRecords.length > 0 ? "pb-40" : "pb-32"
          )}>
          <div className="w-full space-y-6">
            {messages.map((message) => (
              <ChatBubble
                key={message.id}
                message={message.content}
                isBot={message.isBot}
                timestamp={message.timestamp}
              />
            ))}
            
            {isTyping && (
              <ChatBubble
                message=""
                isBot={true}
                timestamp={new Date()}
                isTyping={true}
              />
            )}
            
            <div ref={messagesEndRef} />
          </div>
        </div>

        {/* File Dropzone Modal */}
        <AnimatePresence>
          {showFileDropzone && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-6"
              onClick={() => setShowFileDropzone(false)}
            >
              <motion.div
                initial={{ scale: 0.95, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.95, opacity: 0 }}
                onClick={(e) => e.stopPropagation()}
                className="w-full max-w-2xl"
              >
                <FileDropzone
                  onFilesChange={handleFilesChange}
                  className="mb-4"
                />
                <div className="text-center">
                  <Button
                    onClick={() => setShowFileDropzone(false)}
                    variant="outline"
                    className="glass-panel border-white/15 text-text-secondary"
                  >
                    Close
                  </Button>
                </div>
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Chat Input */}
        <div className={cn(
          "fixed bottom-0 right-0 p-6 bg-background/95 backdrop-blur-md border-t border-white/10 transition-all duration-300",
          isSidebarCollapsed ? "left-20 pl-12" : "left-64 pl-12"
        )}>
          <div className="w-full max-w-full">
            {/* File Upload Status - Above input, always visible */}
            {uploadedFileRecords.length > 0 && !isUploadingFiles && (
              <div className="mb-2 px-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xs text-text-secondary flex-shrink-0">
                    📎 {uploadedFileRecords.length} file{uploadedFileRecords.length > 1 ? 's' : ''}:
                  </span>
                  {uploadedFileRecords.slice(0, 3).map((file) => (
                    <span
                      key={file.id}
                      className="text-xs px-2 py-1 bg-primary/10 text-primary rounded border border-primary/20 truncate max-w-[150px]"
                      title={file.fileName}
                    >
                      {file.fileName.length > 18 ? `${file.fileName.substring(0, 18)}...` : file.fileName}
                    </span>
                  ))}
                  {uploadedFileRecords.length > 3 && (
                    <span className="text-xs text-primary font-medium">
                      +{uploadedFileRecords.length - 3} more
                    </span>
                  )}
                </div>
              </div>
            )}

            {/* Upload Progress Indicator */}
            {isUploadingFiles && (
              <div className="mb-3">
                <div className="glass-panel px-4 py-3 border border-caramel/30 rounded-lg bg-caramel/10">
                  <div className="flex items-center gap-3">
                    <div className="flex-shrink-0">
                      <div className="w-5 h-5 border-2 border-caramel border-t-transparent rounded-full animate-spin"></div>
                    </div>
                    <div className="flex-1">
                      <div className="text-sm font-medium text-caramel">
                        Processing {uploadingFileNames.length} file{uploadingFileNames.length > 1 ? 's' : ''}...
                      </div>
                      <div className="text-xs text-text-secondary mt-1">
                        Please wait while your PDFs are being processed
                      </div>
                    </div>
                  </div>
                  {uploadingFileNames.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {uploadingFileNames.slice(0, 3).map((fileName, index) => (
                        <span
                          key={index}
                          className="text-xs px-2 py-1 bg-caramel/20 text-caramel rounded"
                        >
                          {fileName.length > 15 ? `${fileName.substring(0, 15)}...` : fileName}
                        </span>
                      ))}
                      {uploadingFileNames.length > 3 && (
                        <span className="text-xs px-2 py-1 bg-caramel/20 text-caramel rounded">
                          +{uploadingFileNames.length - 3} more
                        </span>
                      )}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Input Area */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div className="text-xs text-text-secondary">
                  Upload documents to get started
                </div>
                <Button
                  onClick={clearDatabase}
                  disabled={isUploadingFiles}
                  className={cn(
                    "text-xs px-3 py-1 h-auto",
                    "glass-panel border-red-500/30 text-red-400 hover:bg-red-500/10",
                    isUploadingFiles && "opacity-50 cursor-not-allowed"
                  )}
                  variant="outline"
                >
                  Clear Database
                </Button>
              </div>
              
              <div className="flex items-end gap-3">
                <div className="flex-1">
                  <Input
                    ref={inputRef}
                    value={inputValue}
                    onChange={(e) => setInputValue(e.target.value)}
                    onKeyPress={handleKeyPress}
                    placeholder="Ask me anything about your documents..."
                    className="py-6 bg-transparent border-white/15 focus:border-primary/50 focus:ring-primary/20 text-white placeholder:text-text-secondary"
                    disabled={isTyping || isUploadingFiles}
                  />
                </div>
                
                <Button
                  onClick={() => setShowFileDropzone(true)}
                  disabled={isUploadingFiles}
                  className={cn(
                    "glass-panel border-white/15 text-text-secondary p-3",
                    isUploadingFiles && "opacity-50 cursor-not-allowed"
                  )}
                  variant="outline"
                >
                  <Paperclip size={20} />
                </Button>

                <Button
                  onClick={handleSendMessage}
                  disabled={!inputValue.trim() || isTyping || isUploadingFiles}
                  className={cn(
                    'p-3 rounded-lg',
                    'bg-primary text-primary-foreground',
                    'disabled:opacity-50 disabled:cursor-not-allowed',
                    'glow-caramel'
                  )}
                >
                  <Send size={18} />
                </Button>
              </div>
            </div>

            <div className="text-xs text-text-secondary text-center mt-3">
              QubitChat AI can make mistakes. Check important information.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Chat;