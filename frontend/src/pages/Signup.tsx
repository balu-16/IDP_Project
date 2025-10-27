import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { ArrowLeft, Coffee, Mail, Lock, User, Phone } from 'lucide-react';
import { useNavigate, Link } from 'react-router-dom';
import CoffeeBackground from '@/components/CoffeeBackground';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import PasswordField from '@/components/PasswordField';
import { useAuth } from '@/components/auth/AuthContext';
import { showToast } from '@/components/Toast';
import GoogleSignInButton from '@/components/auth/GoogleSignInButton';

const Signup: React.FC = () => {
  const navigate = useNavigate();
  const { register, user, loading } = useAuth();

  // Redirect authenticated users to chat
  useEffect(() => {
    if (!loading && user) {
      navigate('/chat', { replace: true });
    }
  }, [user, loading, navigate]);

  const [formData, setFormData] = useState({
    fullName: '',
    email: '',
    phoneNumber: '',
    password: '',
    confirmPassword: ''
  });
  const [isLoading, setIsLoading] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const validateForm = () => {
    const newErrors: Record<string, string> = {};

    if (!formData.fullName.trim()) {
      newErrors.fullName = 'Full name is required';
    }

    if (!formData.email.trim()) {
      newErrors.email = 'Email is required';
    } else if (!/\S+@\S+\.\S+/.test(formData.email)) {
      newErrors.email = 'Invalid email address';
    }

    if (!formData.phoneNumber.trim()) {
      newErrors.phoneNumber = 'Phone number is required';
    }

    if (!formData.password) {
      newErrors.password = 'Password is required';
    } else if (formData.password.length < 8) {
      newErrors.password = 'Password must be at least 8 characters';
    }

    if (!formData.confirmPassword) {
      newErrors.confirmPassword = 'Please confirm your password';
    } else if (formData.password !== formData.confirmPassword) {
      newErrors.confirmPassword = 'Passwords do not match';
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleInputChange = (field: string, value: string) => {
    setFormData(prev => ({ ...prev, [field]: value }));
    if (errors[field]) {
      setErrors(prev => ({ ...prev, [field]: '' }));
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validateForm()) return;

    setIsLoading(true);
    try {
      const result = await register({
        full_name: formData.fullName,
        email: formData.email,
        password: formData.password,
        phone_number: formData.phoneNumber
      });
      
      if (result.success) {
        showToast('success', `Welcome to QubitChat AI, ${formData.fullName}!`);
        navigate('/chat', { replace: true });
      } else {
        showToast('error', result.error || 'Registration failed');
      }
    } catch (error) {
      showToast('error', 'Signup failed - An unexpected error occurred');
    } finally {
      setIsLoading(false);
    }
  };

  const handleGoogleSuccess = () => {
    showToast('success', 'Welcome to QubitChat AI!');
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

      {/* Signup Form */}
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
              <h1 className="text-2xl font-bold text-text-primary">Create Account</h1>
              <p className="text-text-secondary">Join QubitChat AI and start your intelligent conversations</p>
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
              <span className="px-2 bg-surface text-text-secondary">Or create account with email</span>
            </div>
          </div>

          {/* General Error */}
          {errors.general && (
            <div className="text-sm text-error-text bg-error-background border border-error-border rounded-lg p-3">
              {errors.general}
            </div>
          )}

          {/* Email Form */}
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Full Name */}
            <div className="space-y-2">
              <label className="text-sm font-medium text-text-primary">Full Name</label>
              <div className="relative">
                <User className="absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary z-10" size={18} />
                <Input
                  type="text"
                  value={formData.fullName}
                  onChange={(e) => handleInputChange('fullName', e.target.value)}
                  placeholder="John Doe"
                  className="pl-10 glass-panel border-white/15 focus:border-primary/50 focus:ring-primary/20"
                  disabled={isLoading}
                />
              </div>
              {errors.fullName && (
                <div className="text-sm text-error-text">{errors.fullName}</div>
              )}
            </div>

            {/* Email */}
            <div className="space-y-2">
              <label className="text-sm font-medium text-text-primary">Email</label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary z-10" size={18} />
                <Input
                  type="email"
                  value={formData.email}
                  onChange={(e) => handleInputChange('email', e.target.value)}
                  placeholder="your@email.com"
                  className="pl-10 glass-panel border-white/15 focus:border-primary/50 focus:ring-primary/20"
                  disabled={isLoading}
                />
              </div>
              {errors.email && (
                <div className="text-sm text-error-text">{errors.email}</div>
              )}
            </div>

            {/* Phone Number */}
            <div className="space-y-2">
              <label className="text-sm font-medium text-text-primary">Phone Number</label>
              <div className="relative">
                <Phone className="absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary z-10" size={18} />
                <Input
                  type="tel"
                  value={formData.phoneNumber}
                  onChange={(e) => handleInputChange('phoneNumber', e.target.value)}
                  placeholder="+1 (555) 123-4567"
                  className="pl-10 glass-panel border-white/15 focus:border-primary/50 focus:ring-primary/20"
                  disabled={isLoading}
                />
              </div>
              {errors.phoneNumber && (
                <div className="text-sm text-error-text">{errors.phoneNumber}</div>
              )}
            </div>

            {/* Password */}
            <div className="space-y-2">
              <label className="text-sm font-medium text-text-primary">Password</label>
              <PasswordField
                value={formData.password}
                onChange={(value) => handleInputChange('password', value)}
                placeholder="Create a strong password"
                showStrength={true}
                showIcon={true}
                error={errors.password}
              />
            </div>

            {/* Confirm Password */}
            <div className="space-y-2">
              <label className="text-sm font-medium text-text-primary">Confirm Password</label>
              <PasswordField
                value={formData.confirmPassword}
                onChange={(value) => handleInputChange('confirmPassword', value)}
                placeholder="Confirm your password"
                showIcon={true}
                error={errors.confirmPassword}
              />
            </div>

            <Button
              type="submit"
              disabled={isLoading}
              className="w-full bg-primary hover:bg-primary/90 text-primary-foreground py-6 glow-caramel"
            >
              {isLoading ? 'Creating Account...' : 'Create Account'}
            </Button>
          </form>

          {/* Login Link */}
          <div className="text-center text-sm">
            <span className="text-text-secondary">Already have an account? </span>
            <Link 
              to="/login" 
              className="text-text-link hover:text-text-link-hover transition-colors font-medium"
            >
              Sign in
            </Link>
          </div>
        </div>
      </motion.div>
    </div>
  );
};

export default Signup;