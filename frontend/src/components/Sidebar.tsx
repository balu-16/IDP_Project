import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Plus, MessageSquare, Settings, LogOut, Menu, X, MoreVertical, Edit, Trash2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useAuth } from '@/components/auth/AuthContext';
import { useNavigate } from 'react-router-dom';

interface ChatHistory {
  id: string;
  title: string;
  timestamp: Date;
  isActive?: boolean;
}

interface SidebarProps {
  isOpen: boolean;
  onToggle: () => void;
  onNewChat: () => void;
  chatHistory: any[];
  onSelectChat: (chatId: string) => void;
  onDeleteChat?: (chatId: string) => void;
  onRenameChat?: (chatId: string, newTitle: string) => void;
  className?: string;
  isCollapsed?: boolean;
  onToggleCollapse?: () => void;
}

interface DropdownMenuProps {
  chatId: string;
  onRename: (chatId: string) => void;
  onDelete: (chatId: string) => void;
  onClose: () => void;
}

const DropdownMenu: React.FC<DropdownMenuProps> = ({ chatId, onRename, onDelete, onClose }) => {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95, y: -10 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.95, y: -10 }}
      className="absolute right-0 top-8 z-50 glass-panel border border-white/20 rounded-xl p-1 min-w-[140px]"
      onClick={(e) => e.stopPropagation()}
    >
      <button
        onClick={() => { onRename(chatId); onClose(); }}
        className="w-full flex items-center gap-2 px-3 py-2 text-sm text-text-secondary hover:text-text-primary hover:bg-white/10 rounded-lg transition-colors"
      >
        <Edit size={14} />
        Rename
      </button>
      <button
        onClick={() => { onDelete(chatId); onClose(); }}
        className="w-full flex items-center gap-2 px-3 py-2 text-sm text-text-secondary hover:text-error-text hover:bg-error-bg/20 rounded-lg transition-colors"
      >
        <Trash2 size={14} />
        Delete Chat
      </button>
    </motion.div>
  );
};

const Sidebar: React.FC<SidebarProps> = ({
  isOpen,
  onToggle,
  onNewChat,
  chatHistory,
  onSelectChat,
  onDeleteChat,
  onRenameChat,
  className = "",
  isCollapsed: externalIsCollapsed,
  onToggleCollapse: externalOnToggleCollapse,
}) => {
  const navigate = useNavigate();
  const { logout } = useAuth();
  // State for sidebar collapse (use external state if provided)
  const [internalIsCollapsed, setInternalIsCollapsed] = useState(false);
  
  const isCollapsed = externalIsCollapsed !== undefined ? externalIsCollapsed : internalIsCollapsed;
  const [activeDropdown, setActiveDropdown] = useState<string | null>(null);

  // Load collapsed state from localStorage
  useEffect(() => {
    const savedCollapsed = localStorage.getItem('sidebar-collapsed');
    if (savedCollapsed) {
      setInternalIsCollapsed(JSON.parse(savedCollapsed));
    }
  }, []);

  // Save collapse state to localStorage (only for internal state)
  useEffect(() => {
    if (externalIsCollapsed === undefined) {
      localStorage.setItem('sidebar-collapsed', JSON.stringify(internalIsCollapsed));
    }
  }, [internalIsCollapsed, externalIsCollapsed]);

  // Save chat history to localStorage
  useEffect(() => {
    localStorage.setItem('chat-history', JSON.stringify(chatHistory));
  }, [chatHistory]);

  const handleLogout = () => {
    logout();
    localStorage.removeItem('chat-history');
    navigate('/');
  };

  const handleToggleCollapse = () => {
    if (externalOnToggleCollapse) {
      externalOnToggleCollapse();
    } else {
      setInternalIsCollapsed(!isCollapsed);
    }
    setActiveDropdown(null);
  };

  const handleDropdownToggle = (chatId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setActiveDropdown(activeDropdown === chatId ? null : chatId);
  };

  const handleRename = (chatId: string) => {
    const currentChat = chatHistory.find(chat => chat.id === chatId);
    if (currentChat && onRenameChat) {
      const newTitle = prompt('Enter new chat title:', currentChat.title);
      if (newTitle && newTitle.trim() !== '' && newTitle !== currentChat.title) {
        onRenameChat(chatId, newTitle.trim());
      }
    }
  };

  const [deletingChats, setDeletingChats] = useState<Set<string>>(new Set());

  const handleDelete = async (chatId: string) => {
    // Prevent multiple deletion attempts for the same chat
    if (deletingChats.has(chatId)) {
      return;
    }

    if (onDeleteChat && confirm('Are you sure you want to delete this chat?')) {
      setDeletingChats(prev => new Set(prev).add(chatId));
      
      try {
        await onDeleteChat(chatId);
      } finally {
        // Remove from deleting set after a delay to prevent rapid re-deletion
        setTimeout(() => {
          setDeletingChats(prev => {
            const newSet = new Set(prev);
            newSet.delete(chatId);
            return newSet;
          });
        }, 1000);
      }
    }
  };



  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = () => setActiveDropdown(null);
    document.addEventListener('click', handleClickOutside);
    return () => document.removeEventListener('click', handleClickOutside);
  }, []);

  const sidebarWidth = isCollapsed ? 'w-20' : 'w-64';

  return (
    <>
      {/* Mobile Overlay */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onToggle}
            className="fixed inset-0 bg-black/50 backdrop-blur-sm z-40 lg:hidden"
          />
        )}
      </AnimatePresence>



      {/* Sidebar */}
      <motion.aside
        initial={false}
        animate={{ 
          x: isOpen ? 0 : '-100%',
          width: isCollapsed ? 80 : 260,
          transition: { duration: 0.3, ease: "easeInOut" }
        }}
        className={cn(
          'h-screen backdrop-blur-md bg-white/5 border-r border-white/10 z-50',
          'flex flex-col flex-shrink-0',
          'fixed top-0 left-0',
          sidebarWidth,
          className
        )}
      >
        {/* Header */}
        <div className="p-4 border-b border-white/10">
          <div className="flex items-center justify-between mb-4">
            {!isCollapsed && (
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-caramel to-honey flex items-center justify-center">
                  <MessageSquare size={18} className="text-deep-black" />
                </div>
                <h1 className="text-lg font-bold text-text-primary">
                  QubitChat AI
                </h1>
              </div>
            )}
            {isCollapsed && (
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-caramel to-honey flex items-center justify-center mx-auto">
                <MessageSquare size={18} className="text-deep-black" />
              </div>
            )}
            {/* Mobile Close Button */}
            <button
              onClick={onToggle}
              className="lg:hidden p-2 rounded-lg hover:bg-white/10 text-text-secondary hover:text-text-primary transition-colors"
            >
              <X size={20} />
            </button>
          </div>

          {/* New Chat Button */}
          <motion.button
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            onClick={onNewChat}
            className={cn(
              "w-full bg-caramel hover:bg-caramel/90 text-deep-black rounded-xl font-medium transition-all glow-caramel hover:glow-honey",
              isCollapsed ? "p-3 flex items-center justify-center" : "px-4 py-3 flex items-center gap-3"
            )}
            title={isCollapsed ? "New Chat" : undefined}
          >
            <Plus size={18} />
            {!isCollapsed && "New Chat"}
          </motion.button>
        </div>

        {/* Chat History */}
        <div className="flex-1 overflow-y-auto custom-scrollbar p-3 space-y-1">
          {!isCollapsed && (
            <h2 className="text-sm font-medium text-text-secondary mb-3 px-2">
              Recent Chats
            </h2>
          )}
          
          {chatHistory.length === 0 ? (
            <div className="text-center py-8 text-text-secondary">
              <MessageSquare size={isCollapsed ? 20 : 24} className="mx-auto mb-2 opacity-50" />
              {!isCollapsed && <p className="text-sm">No chats yet</p>}
            </div>
          ) : (
            chatHistory.map((chat) => (
              <div key={chat.id} className="relative group">
                <motion.button
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.98 }}
                  onClick={() => onSelectChat(chat.id)}
                  className={cn(
                    'w-full text-left rounded-xl transition-all relative',
                    'hover:bg-white/10 hover:glow-caramel',
                    chat.isActive && 'bg-caramel/20 border border-caramel/30 glow-caramel',
                    isCollapsed ? 'p-3 flex items-center justify-center' : 'p-3 pr-10'
                  )}
                  title={isCollapsed ? chat.title : undefined}
                >
                  {isCollapsed ? (
                    <MessageSquare size={18} className="text-text-primary" />
                  ) : (
                    <>
                      <div className="font-medium text-text-primary mb-1 truncate text-sm">
                        {chat.title}
                      </div>
                      <div className="text-xs text-text-secondary">
                        {chat.timestamp.toLocaleDateString()}
                      </div>
                    </>
                  )}
                </motion.button>
                
                {!isCollapsed && (
                  <button
                    onClick={(e) => handleDropdownToggle(chat.id, e)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded-lg hover:bg-white/10 text-text-secondary hover:text-text-primary transition-colors opacity-0 group-hover:opacity-100"
                  >
                    <MoreVertical size={14} />
                  </button>
                )}
                
                <AnimatePresence>
                  {activeDropdown === chat.id && (
                    <DropdownMenu
                      chatId={chat.id}
                      onRename={handleRename}
                          onDelete={handleDelete}
                          onClose={() => setActiveDropdown(null)}
                    />
                  )}
                </AnimatePresence>
              </div>
            ))
          )}
        </div>

        {/* Footer */}
        <div className="p-3 border-t border-white/10 space-y-1">
          <button
            onClick={() => navigate('/settings')}
            className={cn(
              "w-full rounded-xl hover:bg-white/10 text-text-secondary hover:text-text-primary transition-colors",
              isCollapsed ? "p-3 flex items-center justify-center" : "flex items-center gap-3 p-3"
            )}
            title={isCollapsed ? "Settings" : undefined}
          >
            <Settings size={18} />
            {!isCollapsed && "Settings"}
          </button>
          <button
            onClick={handleLogout}
            className={cn(
              "w-full rounded-xl hover:bg-white/10 text-text-secondary hover:text-caramel transition-colors",
              isCollapsed ? "p-3 flex items-center justify-center" : "flex items-center gap-3 p-3"
            )}
            title={isCollapsed ? "Logout" : undefined}
          >
            <LogOut size={18} />
            {!isCollapsed && "Logout"}
          </button>
        </div>
      </motion.aside>


    </>
  );
};

export default Sidebar;