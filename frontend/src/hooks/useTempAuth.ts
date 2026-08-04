import { useState, useEffect } from 'react';

interface TempUser {
  email: string;
  fullName: string;
  id: string;
}

export const useTempAuth = () => {
  const [user, setUser] = useState<TempUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Check for existing session in localStorage
    const savedUser = localStorage.getItem('tempUser');
    if (savedUser) {
      try {
        setUser(JSON.parse(savedUser));
      } catch (error) {
        localStorage.removeItem('tempUser');
      }
    }
    setLoading(false);
  }, []);

  const login = (email: string, password: string): Promise<{ success: boolean; error?: string }> => {
    return new Promise((resolve) => {
      setTimeout(() => {
        // Basic validation
        if (!email || !password) {
          resolve({ success: false, error: 'Please fill in all fields' });
          return;
        }

        if (!email.includes('@')) {
          resolve({ success: false, error: 'Please enter a valid email address' });
          return;
        }

        if (password.length < 6) {
          resolve({ success: false, error: 'Password must be at least 6 characters' });
          return;
        }

        // Create temp user
        const tempUser: TempUser = {
          email,
          fullName: email.split('@')[0], // Use email prefix as name
          id: Date.now().toString(),
        };

        localStorage.setItem('tempUser', JSON.stringify(tempUser));
        setUser(tempUser);
        resolve({ success: true });
      }, 500); // Simulate API delay
    });
  };

  const signup = (
    fullName: string,
    email: string,
    phoneNumber: string,
    password: string,
    confirmPassword: string
  ): Promise<{ success: boolean; error?: string }> => {
    return new Promise((resolve) => {
      setTimeout(() => {
        // Basic validation
        if (!fullName || !email || !phoneNumber || !password || !confirmPassword) {
          resolve({ success: false, error: 'Please fill in all fields' });
          return;
        }

        if (!email.includes('@')) {
          resolve({ success: false, error: 'Please enter a valid email address' });
          return;
        }

        if (password.length < 8) {
          resolve({ success: false, error: 'Password must be at least 8 characters' });
          return;
        }

        if (password !== confirmPassword) {
          resolve({ success: false, error: 'Passwords do not match' });
          return;
        }

        // Create temp user
        const tempUser: TempUser = {
          email,
          fullName,
          id: Date.now().toString(),
        };

        localStorage.setItem('tempUser', JSON.stringify(tempUser));
        setUser(tempUser);
        resolve({ success: true });
      }, 500); // Simulate API delay
    });
  };

  const logout = () => {
    localStorage.removeItem('tempUser');
    setUser(null);
  };

  return {
    user,
    loading,
    login,
    signup,
    logout,
  };
};