import { ToastType } from '../components/Toast';
import type { ToastData } from '../components/Toast';

// Utility functions for toast notifications
export const showToast = (type: ToastType, title: string, message?: string) => {
  const windowWithToast = window as Window & { addToast?: (toast: Omit<ToastData, 'id'>) => void };
  if (windowWithToast.addToast) {
    windowWithToast.addToast({ type, title, message });
  }
};