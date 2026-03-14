import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, CheckCircle, AlertCircle, Info, AlertTriangle } from 'lucide-react';
import { cn } from '@/lib/utils';

export type ToastType = 'success' | 'error' | 'warning' | 'info';

interface ToastProps {
  id: string;
  type: ToastType;
  title: string;
  message?: string;
  isVisible: boolean;
  onClose: () => void;
  duration?: number;
}

const toastIcons = {
  success: CheckCircle,
  error: AlertCircle,
  warning: AlertTriangle,
  info: Info,
};

const toastStyles = {
  success: 'bg-success-bg border-success-border text-success-text',
  error: 'bg-error-bg border-error-border text-error-text',
  warning: 'bg-warning-bg border-warning-border text-warning-text',
  info: 'bg-info-bg border-info-border text-info-text',
};

const iconStyles = {
  success: 'text-success-icon',
  error: 'text-error-icon',
  warning: 'text-warning-icon',
  info: 'text-info-icon',
};

const Toast: React.FC<ToastProps> = ({
  id,
  type,
  title,
  message,
  isVisible,
  onClose,
  duration = 5000
}) => {
  const Icon = toastIcons[type];

  React.useEffect(() => {
    if (isVisible && duration > 0) {
      const timer = setTimeout(onClose, duration);
      return () => clearTimeout(timer);
    }
  }, [isVisible, duration, onClose]);

  return (
    <AnimatePresence>
      {isVisible && (
        <motion.div
          key={id}
          initial={{ opacity: 0, x: 100, scale: 0.95 }}
          animate={{ opacity: 1, x: 0, scale: 1 }}
          exit={{ opacity: 0, x: 100, scale: 0.95 }}
          transition={{ duration: 0.3, ease: "easeOut" }}
          className={cn(
            'glass-panel border-2 p-4 rounded-xl shadow-lg min-w-80 max-w-md',
            toastStyles[type]
          )}
        >
          <div className="flex items-start gap-3">
            <Icon className={cn('w-5 h-5 mt-0.5 flex-shrink-0', iconStyles[type])} />
            
            <div className="flex-1 min-w-0">
              <div className="font-medium text-sm mb-1">
                {title}
              </div>
              {message && (
                <div className="text-sm opacity-90">
                  {message}
                </div>
              )}
            </div>

            <button
              onClick={onClose}
              className="flex-shrink-0 p-1 rounded-md hover:bg-black/20 transition-colors"
            >
              <X size={14} />
            </button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
};

// Toast Manager
export interface ToastData {
  id: string;
  type: ToastType;
  title: string;
  message?: string;
}

// Global toast function
export const showToast = (type: ToastType, title: string, message?: string) => {
  const addToast = (window as Window & { addToast?: (toast: Omit<ToastData, 'id'>) => void }).addToast;
  if (addToast) {
    addToast({ type, title, message });
  }
};

export const ToastContainer: React.FC = () => {
  const [toasts, setToasts] = React.useState<ToastData[]>([]);

  const removeToast = (id: string) => {
    setToasts(prev => prev.filter(toast => toast.id !== id));
  };

  // Expose toast functions globally
  React.useEffect(() => {
    (window as Window & { addToast?: (toast: Omit<ToastData, 'id'>) => void }).addToast = (toast: Omit<ToastData, 'id'>) => {
      const id = Math.random().toString(36).substr(2, 9);
      setToasts(prev => [...prev, { ...toast, id }]);
    };
  }, []);

  return (
    <div className="fixed top-4 right-4 z-50 space-y-3">
      {toasts.map(toast => (
        <Toast
          key={toast.id}
          id={toast.id}
          type={toast.type}
          title={toast.title}
          message={toast.message}
          isVisible={true}
          onClose={() => removeToast(toast.id)}
        />
      ))}
    </div>
  );
};

export default Toast;