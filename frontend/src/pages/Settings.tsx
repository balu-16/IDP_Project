import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { ArrowLeft, User, Mail, Phone, Calendar, Trash2, Edit2, Save, X, AlertTriangle } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/components/auth/AuthContext';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { showToast } from '@/components/Toast';
import CoffeeBackground from '@/components/CoffeeBackground';
import { cn } from '@/lib/utils';

const Settings: React.FC = () => {
  const navigate = useNavigate();
  const { user, logout, token } = useAuth();
  
  const [isEditing, setIsEditing] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [showDeleteConfirmation, setShowDeleteConfirmation] = useState(false);
  const [deleteConfirmationText, setDeleteConfirmationText] = useState('');
  
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

  // Redirect if not authenticated
  useEffect(() => {
    if (!user) {
      navigate('/login');
    }
  }, [user, navigate]);

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
      const response = await fetch(`http://localhost:8000/api/auth/user/${user.id}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify(formData)
      });

      const data = await response.json();

      if (response.ok && data.success) {
        showToast('success', 'Profile Updated', 'Your profile has been updated successfully.');
        setIsEditing(false);
        // Update user data in context if needed
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

  const handleDeleteAccount = async () => {
    if (!user || !token) return;
    
    if (deleteConfirmationText !== 'Confirm to delete My account') {
      showToast('error', 'Invalid Confirmation', 'Please type the exact confirmation text.');
      return;
    }

    setIsLoading(true);
    try {
      const response = await fetch(`http://localhost:8000/api/auth/user/${user.id}`, {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });

      const data = await response.json();

      if (response.ok && data.success) {
        showToast('success', 'Account Deleted', 'Your account has been deleted successfully.');
        logout();
        navigate('/');
      } else {
        showToast('error', 'Deletion Failed', data.detail || 'Failed to delete account.');
      }
    } catch (error) {
      console.error('Error deleting account:', error);
      showToast('error', 'Network Error', 'Failed to delete account. Please try again.');
    } finally {
      setIsLoading(false);
      setShowDeleteConfirmation(false);
      setDeleteConfirmationText('');
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
    return null; // Will redirect via useEffect
  }

  return (
    <div className="min-h-screen relative">
      <CoffeeBackground variant="muted" />
      
      <div className="relative z-10 min-h-screen flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-white/10">
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
                    <p className="text-text-primary bg-white/5 p-3 rounded-lg border border-white/10">
                      {user.full_name}
                    </p>
                  )}
                </div>

                {/* Email */}
                <div className="space-y-2">
                  <label className="text-sm font-medium text-text-secondary flex items-center gap-2">
                    <Mail size={16} />
                    Email Address
                  </label>
                  {isEditing ? (
                    <Input
                      type="email"
                      value={formData.email}
                      onChange={(e) => handleInputChange('email', e.target.value)}
                      className="glass-input"
                      placeholder="Enter your email"
                    />
                  ) : (
                    <p className="text-text-primary bg-white/5 p-3 rounded-lg border border-white/10">
                      {user.email}
                    </p>
                  )}
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
                    <p className="text-text-primary bg-white/5 p-3 rounded-lg border border-white/10">
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
                <div className="flex gap-3 pt-4 border-t border-white/10">
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

            {/* Danger Zone */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.1 }}
              className="glass-panel p-6 space-y-4 border-red-500/20"
            >
              <h2 className="text-xl font-semibold text-red-400 flex items-center gap-2">
                <AlertTriangle size={20} />
                Danger Zone
              </h2>
              <p className="text-text-secondary">
                Once you delete your account, there is no going back. Please be certain.
              </p>
              
              {!showDeleteConfirmation ? (
                <Button
                  variant="destructive"
                  onClick={() => setShowDeleteConfirmation(true)}
                  className="bg-red-600 hover:bg-red-700 text-white"
                >
                  <Trash2 size={16} className="mr-2" />
                  Delete Account
                </Button>
              ) : (
                <div className="space-y-4 p-4 bg-red-500/10 border border-red-500/20 rounded-lg">
                  <p className="text-red-400 font-medium">
                    Are you absolutely sure? This action cannot be undone.
                  </p>
                  <p className="text-text-secondary text-sm">
                    Type <span className="font-mono bg-white/10 px-2 py-1 rounded">Confirm to delete My account</span> to confirm:
                  </p>
                  <Input
                    value={deleteConfirmationText}
                    onChange={(e) => setDeleteConfirmationText(e.target.value)}
                    className="glass-input border-red-500/30"
                    placeholder="Type the confirmation text"
                  />
                  <div className="flex gap-3">
                    <Button
                      variant="destructive"
                      onClick={handleDeleteAccount}
                      disabled={isLoading || deleteConfirmationText !== 'Confirm to delete My account'}
                      className="bg-red-600 hover:bg-red-700 text-white"
                    >
                      <Trash2 size={16} className="mr-2" />
                      {isLoading ? 'Deleting...' : 'Delete Account'}
                    </Button>
                    <Button
                      variant="outline"
                      onClick={() => {
                        setShowDeleteConfirmation(false);
                        setDeleteConfirmationText('');
                      }}
                      className="text-text-secondary hover:text-text-primary"
                    >
                      Cancel
                    </Button>
                  </div>
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