import React, { createContext, useContext, useEffect, useState } from 'react';
import { Database } from '@/integration/types';
import { apiUrl } from '@/lib/api';

// Define user type based on our database schema
type User = Database['public']['Tables']['signup_users']['Row'];

interface AuthContextType {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<{ success: boolean; error?: string }>;
  register: (userData: {
    full_name: string;
    email: string;
    password: string;
    phone_number?: string;
  }) => Promise<{ success: boolean; error?: string }>;
  logout: () => Promise<void>;
  token: string | null;
}

export const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [token, setToken] = useState<string | null>(null);

  const parseResponseData = async (response: Response): Promise<any> => {
    const contentType = response.headers.get('content-type') || '';
    const rawBody = await response.text();

    if (!rawBody) {
      return {};
    }

    if (contentType.includes('application/json')) {
      try {
        return JSON.parse(rawBody);
      } catch {
        return {};
      }
    }

    return { detail: rawBody };
  };

  // Initialize auth state from localStorage
  useEffect(() => {
    const initializeAuth = () => {
      try {
        const storedUser = localStorage.getItem('user');
        const storedToken = localStorage.getItem('token');
        
        if (storedUser && storedToken) {
          setUser(JSON.parse(storedUser));
          setToken(storedToken);
        }
      } catch (error) {
        console.error('Error initializing auth:', error);
        // Clear invalid data
        localStorage.removeItem('user');
        localStorage.removeItem('token');
      } finally {
        setLoading(false);
      }
    };

    initializeAuth();
  }, []);

  const login = async (email: string, password: string): Promise<{ success: boolean; error?: string }> => {
    try {
      setLoading(true);
      
      const response = await fetch(apiUrl('/api/auth/login'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ email, password }),
      });

      const data = await parseResponseData(response);

      if (response.ok && data.success) {
        const userData = data.user;
        const userToken = data.token;
        
        setUser(userData);
        setToken(userToken);
        
        // Store in localStorage
        localStorage.setItem('user', JSON.stringify(userData));
        localStorage.setItem('token', userToken);
        
        return { success: true };
      } else {
        return {
          success: false,
          error: data.detail || data.message || `Login failed (HTTP ${response.status})`
        };
      }
    } catch (error) {
      console.error('Login error:', error);
      return { success: false, error: 'Network error. Please try again.' };
    } finally {
      setLoading(false);
    }
  };

  const register = async (userData: {
    full_name: string;
    email: string;
    password: string;
    phone_number?: string;
  }): Promise<{ success: boolean; error?: string }> => {
    try {
      setLoading(true);
      
      const response = await fetch(apiUrl('/api/auth/register'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(userData),
      });

      const data = await parseResponseData(response);

      if (response.ok && data.success) {
        const newUser = data.user;
        const userToken = data.token;
        
        setUser(newUser);
        setToken(userToken);
        
        // Store in localStorage
        localStorage.setItem('user', JSON.stringify(newUser));
        localStorage.setItem('token', userToken);
        
        return { success: true };
      } else {
        return {
          success: false,
          error: data.detail || data.message || `Registration failed (HTTP ${response.status})`
        };
      }
    } catch (error) {
      console.error('Registration error:', error);
      return { success: false, error: 'Network error. Please try again.' };
    } finally {
      setLoading(false);
    }
  };

  const logout = async () => {
    setUser(null);
    setToken(null);
    localStorage.removeItem('user');
    localStorage.removeItem('token');
  };

  const value = {
    user,
    loading,
    login,
    register,
    logout,
    token
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
