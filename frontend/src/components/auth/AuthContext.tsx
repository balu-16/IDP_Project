import React, { createContext, useContext, useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { Session } from '@supabase/supabase-js';
import { getSupabase, isSupabaseConfigured } from '@/integration/client';
import { apiUrl, errorMessage } from '@/lib/api';
import { profileSchema, type Profile } from '@/lib/contracts';
import chatService from '@/services/chatService';

type AuthResult = { success: boolean; error?: string; confirmationRequired?: boolean };
interface AuthContextType {
  user: Profile | null;
  loading: boolean;
  error: string | null;
  token: string | null;
  login: (email: string, password: string) => Promise<AuthResult>;
  register: (data: { full_name: string; email: string; password: string; phone_number?: string }) => Promise<AuthResult>;
  logout: () => Promise<void>;
  updateUser: (data: Partial<Profile>) => void;
}
export const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const cache = useQueryClient();
  const [user, setUser] = useState<Profile | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);

  const synchronize = async (session: Session | null) => {
    const request = ++generation.current;
    setLoading(true);
    setError(null);
    if (!session) {
      setUser(null); setToken(null); chatService.setUserId(null); cache.clear(); setLoading(false);
      return;
    }
    try {
      const response = await fetch(apiUrl('/api/auth/me'), {
        headers: { Authorization: 'Bearer ' + session.access_token },
      });
      const body = await response.json();
      if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Profile verification failed.');
      const profile = profileSchema.parse(body.user);
      if (request !== generation.current) return;
      setUser(profile); setToken(session.access_token); chatService.setUserId(profile.id);
    } catch (cause) {
      if (request === generation.current) {
        setUser(null); setToken(null); chatService.setUserId(null); setError(errorMessage(cause));
      }
    } finally {
      if (request === generation.current) setLoading(false);
    }
  };

  useEffect(() => {
    // Legacy locally supplied identity is never accepted.
    localStorage.removeItem('user'); localStorage.removeItem('token');
    if (!isSupabaseConfigured()) {
      setError('Supabase is not configured.'); setLoading(false); return;
    }
    const client = getSupabase();
    const { data: subscription } = client.auth.onAuthStateChange((_event, session) => {
      void synchronize(session);
    });
    void client.auth.getSession().then(({ data, error: failure }) => {
      if (failure) { setError(failure.message); setLoading(false); }
      else void synchronize(data.session);
    });
    return () => { generation.current++; subscription.subscription.unsubscribe(); };
  }, []);

  const login = async (email: string, password: string): Promise<AuthResult> => {
    try {
      const { data, error: failure } = await getSupabase().auth.signInWithPassword({ email, password });
      if (failure) throw failure;
      await synchronize(data.session);
      // Verify linkage before announcing successful login.
      const response = await fetch(apiUrl('/api/auth/me'), {
        headers: { Authorization: 'Bearer ' + data.session.access_token },
      });
      if (!response.ok) {
        const body = await response.json();
        throw new Error(typeof body.detail === 'string' ? body.detail : 'Profile verification failed.');
      }
      return { success: true };
    } catch (cause) { return { success: false, error: errorMessage(cause) }; }
  };
  const register: AuthContextType['register'] = async ({ email, password, ...metadata }) => {
    try {
      const { data, error: failure } = await getSupabase().auth.signUp({
        email, password, options: { data: metadata, emailRedirectTo: window.location.origin + '/login' },
      });
      if (failure) throw failure;
      if (data.session) await synchronize(data.session);
      return { success: true, confirmationRequired: !data.session };
    } catch (cause) { return { success: false, error: errorMessage(cause) }; }
  };
  const logout = async () => {
    generation.current++; cache.clear();
    setUser(null); setToken(null); chatService.setUserId(null);
    const { error: failure } = await getSupabase().auth.signOut();
    if (failure) throw failure;
  };
  const updateUser = (data: Partial<Profile>) => setUser(previous => previous ? profileSchema.parse({ ...previous, ...data }) : null);
  return <AuthContext.Provider value={{ user, token, loading, error, login, register, logout, updateUser }}>
    {children}
  </AuthContext.Provider>;
};

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth requires AuthProvider');
  return context;
}
