import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { ArrowLeft, Coffee, Mail, Lock } from 'lucide-react';
import { useNavigate, Link } from 'react-router-dom';
import CoffeeBackground from '@/components/CoffeeBackground';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import PasswordField from '@/components/PasswordField';
import { useAuth } from '@/components/auth/AuthContext';
import { showToast } from '@/components/Toast';
import GoogleSignInButton from '@/components/auth/GoogleSignInButton';

const Login: React.FC = () => {
  const navigate = useNavigate();
  const { login, user, loading } = useAuth();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');

  // Redirect authenticated users to chat
  useEffect(() => {
    if (!loading && user) {
      navigate('/chat', { replace: true });
    }
  }, [user, loading, navigate]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!email || !password) {
      showToast('error', 'Please fill in all fields');
      return;
    }

    setError('');
    setIsLoading(true);

    try {
      const result = await login(email, password);
      
      if (result.success) {
        showToast('success', 'Welcome back!');
        navigate('/chat', { replace: true });
      } else {
        setError(result.error || 'Login failed');
        showToast('error', result.error || 'Login failed');
      }
    } catch (error) {
      setError('Login failed');
      showToast('error', 'Login failed');
    } finally {
      setIsLoading(false);
    }
  };

  const handleGoogleSuccess = () => {
    showToast('success', 'Welcome back!');
    navigate('/chat', { replace: true });
  };

  return (
    <div className="relative min-h-screen flex items-center justify-center p-6">
      {/* Muted Coffee Background */}
      <CoffeeBackground variant="muted" />

      {/* Back Button */}
      <Button
        variant="ghost"
        onClick={() => navigate('/')}
        className="absolute top-6 left-6 z-10 text-text-secondary hover:text-text-primary"
      >
        <ArrowLeft className="mr-2" size={18} />
        Back to Home
      </Button>

      {/* Login Form */}
      <motion.div
        initial={{ opacity: 0, y: 30, scale: 0.95 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.5, ease: "easeOut" }}
        className="relative z-10 w-full max-w-md"
      >
        <div className="glass-panel p-8 space-y-6">
          {/* Header */}
          <div className="text-center space-y-4">
            <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-caramel to-honey flex items-center justify-center mx-auto">
              <Coffee size={32} className="text-deep-black" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-text-primary">Welcome Back</h1>
              <p className="text-text-secondary">Sign in to continue your AI conversations</p>
            </div>
          </div>

          {/* Google Sign In */}
          <GoogleSignInButton onSuccess={handleGoogleSuccess} className="w-full" />

          {/* Divider */}
          <div className="relative">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-white/20" />
            </div>
            <div className="relative flex justify-center text-sm">
              <span className="px-2 bg-surface text-text-secondary">Or continue with email</span>
            </div>
          </div>

          {/* Email Form */}
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium text-text-primary">Email</label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary z-10" size={18} />
                <Input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="your@email.com"
                  className="pl-10 glass-panel border-white/15 focus:border-primary/50 focus:ring-primary/20"
                  disabled={isLoading}
                />
              </div>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium text-text-primary">Password</label>
              <PasswordField
                value={password}
                onChange={(value) => setPassword(value)}
                placeholder="Your password"
                showIcon={true}
              />
            </div>

            {error && (
              <div className="text-sm text-error-text bg-error-background border border-error-border rounded-lg p-3">
                {error}
              </div>
            )}

            <Button
              type="submit"
              disabled={isLoading}
              className="w-full bg-primary hover:bg-primary/90 text-primary-foreground py-6 glow-caramel"
            >
              {isLoading ? 'Signing in...' : 'Sign In'}
            </Button>
          </form>

          {/* Sign Up Link */}
          <div className="text-center text-sm">
            <span className="text-text-secondary">Don't have an account? </span>
            <Link 
              to="/signup" 
              className="text-text-link hover:text-text-link-hover transition-colors font-medium"
            >
              Sign up
            </Link>
          </div>
        </div>
      </motion.div>
    </div>
  );
};

export default Login;