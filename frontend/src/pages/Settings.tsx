import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { ArrowLeft, User, Mail, Phone, Calendar, Edit2, Save, X } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/components/auth/AuthContext';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { showToast } from '@/components/Toast';
import CoffeeBackground from '@/components/CoffeeBackground';
import { apiFetch } from '@/lib/api';
import { profileSchema } from '@/lib/contracts';
import { cn } from '@/lib/utils';

const Settings: React.FC = () => {
  const navigate = useNavigate();
  const { user, updateUser, token } = useAuth();
  
  const [isEditing, setIsEditing] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  
  const [formData, setFormData] = useState({
    full_name: '',
    email: '',
    phone_number: ''
  });

  // Initialize form data when user data is available
  useEffect(() => {
    if (user) {
      setFormData({
        full_name: user.full_name || '',
        email: user.email || '',
        phone_number: user.phone_number || ''
      });
    }
  }, [user]);

  const handleInputChange = (field: string, value: string) => {
    setFormData(prev => ({
      ...prev,
      [field]: value
    }));
  };

  const handleSaveChanges = async () => {
    if (!user || !token) return;

    setIsLoading(true);
    try {
      const response = await apiFetch(`/api/auth/user/${user.id}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ full_name: formData.full_name, phone_number: formData.phone_number || null })
      });

      const data = await response.json();

      if (response.ok && data.success) {
        showToast('success', 'Profile Updated', 'Your profile has been updated.');
        setIsEditing(false);
        // Refresh user data in AuthContext so the UI reflects the changes
        updateUser(profileSchema.parse(data.user));
      } else {
        showToast('error', 'Update Failed', data.detail || 'Failed to update profile.');
      }
    } catch (error) {
      console.error('Error updating profile:', error);
      showToast('error', 'Network Error', 'Failed to update profile. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric'
    });
  };

  if (!user) {
    return null;
  }

  return (
    <div className="min-h-screen relative">
      <CoffeeBackground variant="muted" />
      
      <div className="relative z-10 min-h-screen flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-border">
          <div className="flex items-center gap-4">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate('/chat')}
              className="text-text-secondary hover:text-text-primary"
            >
              <ArrowLeft size={20} />
            </Button>
            <h1 className="text-2xl font-bold text-text-primary">Settings</h1>
          </div>
        </div>

        {/* Main Content */}
        <div className="flex-1 p-6">
          <div className="max-w-2xl mx-auto space-y-8">
            
            {/* Profile Section */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5 }}
              className="glass-panel p-6 space-y-6"
            >
              <div className="flex items-center justify-between">
                <h2 className="text-xl font-semibold text-text-primary flex items-center gap-2">
                  <User size={20} />
                  Profile Information
                </h2>
                {!isEditing && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setIsEditing(true)}
                    className="text-text-secondary hover:text-text-primary"
                  >
                    <Edit2 size={16} className="mr-2" />
                    Edit
                  </Button>
                )}
              </div>

              <div className="space-y-4">
                {/* Full Name */}
                <div className="space-y-2">
                  <label className="text-sm font-medium text-text-secondary flex items-center gap-2">
                    <User size={16} />
                    Full Name
                  </label>
                  {isEditing ? (
                    <Input
                      value={formData.full_name}
                      onChange={(e) => handleInputChange('full_name', e.target.value)}
                      className="glass-input"
                      placeholder="Enter your full name"
                    />
                  ) : (
                    <p className="text-text-primary bg-surface/50 dark:bg-glass-bg p-3 rounded-lg border border-border">
                      {user.full_name}
                    </p>
                  )}
                </div>

                {/* Email (read-only; contact support to change) */}
                <div className="space-y-2">
                  <label className="text-sm font-medium text-text-secondary flex items-center gap-2">
                    <Mail size={16} />
                    Email Address
                  </label>
                  <p className="text-text-primary bg-surface/50 dark:bg-glass-bg p-3 rounded-lg border border-border">
                    {user.email}
                  </p>
                </div>

                {/* Phone Number */}
                <div className="space-y-2">
                  <label className="text-sm font-medium text-text-secondary flex items-center gap-2">
                    <Phone size={16} />
                    Phone Number
                  </label>
                  {isEditing ? (
                    <Input
                      value={formData.phone_number}
                      onChange={(e) => handleInputChange('phone_number', e.target.value)}
                      className="glass-input"
                      placeholder="Enter your phone number"
                    />
                  ) : (
                    <p className="text-text-primary bg-surface/50 dark:bg-glass-bg p-3 rounded-lg border border-border">
                      {user.phone_number || 'Not provided'}
                    </p>
                  )}
                </div>

                {/* Account Created */}
                <div className="space-y-2">
                  <label className="text-sm font-medium text-text-secondary flex items-center gap-2">
                    <Calendar size={16} />
                    Account Created
                  </label>
                  <p className="text-text-primary bg-white/5 p-3 rounded-lg border border-white/10">
                    {user.created_at ? formatDate(user.created_at) : 'Unknown'}
                  </p>
                </div>
              </div>

              {/* Edit Actions */}
              {isEditing && (
                <div className="flex gap-3 pt-4 border-t border-border">
                  <Button
                    onClick={handleSaveChanges}
                    disabled={isLoading}
                    className="bg-primary hover:bg-primary/90 text-primary-foreground"
                  >
                    <Save size={16} className="mr-2" />
                    {isLoading ? 'Saving...' : 'Save Changes'}
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => {
                      setIsEditing(false);
                      // Reset form data
                      setFormData({
                        full_name: user.full_name || '',
                        email: user.email || '',
                        phone_number: user.phone_number || ''
                      });
                    }}
                    className="text-text-secondary hover:text-text-primary"
                  >
                    <X size={16} className="mr-2" />
                    Cancel
                  </Button>
                </div>
              )}
            </motion.div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Settings;
