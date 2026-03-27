import React from 'react';
import { motion } from 'framer-motion';
import { Bot, User } from 'lucide-react';
import { cn } from '@/lib/utils';

interface ChatBubbleProps {
  message: string;
  isBot: boolean;
  timestamp: Date;
  isTyping?: boolean;
  retrievalTimeMs?: number;
}

const TypingDots: React.FC = () => (
  <div className="flex gap-1 p-2">
    {[0, 1, 2].map((i) => (
      <motion.div
        key={i}
        className="w-2 h-2 bg-primary rounded-full"
        animate={{ 
          scale: [1, 1.2, 1],
          opacity: [0.6, 1, 0.6] 
        }}
        transition={{
          duration: 1,
          repeat: Infinity,
          delay: i * 0.2,
          ease: "easeInOut"
        }}
      />
    ))}
  </div>
);

const ChatBubble: React.FC<ChatBubbleProps> = ({ 
  message, 
  isBot, 
  timestamp, 
  isTyping = false,
  retrievalTimeMs 
}) => {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20, scale: 0.95 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
      className={cn(
        'flex gap-4 mb-6',
        !isBot && 'flex-row-reverse'
      )}
    >
      {/* Avatar */}
      <div className={cn(
        'w-10 h-10 rounded-full flex items-center justify-center flex-shrink-0',
        isBot 
          ? 'glass-panel border-primary/30' 
          : 'bg-primary text-primary-foreground'
      )}>
        {isBot ? (
          <Bot size={18} className="text-primary" />
        ) : (
          <User size={18} />
        )}
      </div>

      {/* Message Content */}
      <div className={cn(
        'w-full space-y-2',
        !isBot && 'items-end'
      )}>
        {/* Message Bubble */}
        <div className={cn(
          'rounded-2xl px-4 py-3 relative w-full min-h-fit',
          isBot 
            ? 'border-primary/20 text-text-primary' 
            : 'text-text-primary dark:text-white'
        )}>
          {isTyping ? (
            <TypingDots />
          ) : (
            <div className={cn(
              "whitespace-pre-wrap break-words word-wrap overflow-wrap-anywhere w-full min-h-fit",
              !isBot && "text-text-primary dark:text-white",
              !isBot && "text-right"
            )}>
              {message}
            </div>
          )}
        </div>

        {/* Timestamp and Retrieval Time */}
        {!isTyping && (
          <div className={cn(
            'text-xs text-text-secondary px-2 flex gap-3',
            !isBot && 'text-right justify-end'
          )}>
            {isBot && retrievalTimeMs !== undefined && retrievalTimeMs > 0 && (
              <span className="text-primary font-medium">
                ⚡ Retrieval: {retrievalTimeMs.toFixed(2)}ms
              </span>
            )}
            <span>
              {timestamp.toLocaleTimeString([], { 
                hour: '2-digit', 
                minute: '2-digit' 
              })}
            </span>
          </div>
        )}
      </div>
    </motion.div>
  );
};

export default ChatBubble;
