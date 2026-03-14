import React, { useState } from 'react';
import { Eye, EyeOff, Lock } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';

interface PasswordFieldProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  showStrength?: boolean;
  className?: string;
  error?: string;
  showIcon?: boolean;
}

const getPasswordStrength = (password: string): { score: number; label: string; className: string } => {
  let score = 0;
  
  if (password.length >= 8) score++;
  if (/[a-z]/.test(password)) score++;
  if (/[A-Z]/.test(password)) score++;
  if (/\d/.test(password)) score++;
  if (/[^A-Za-z0-9]/.test(password)) score++;

  if (score <= 2) return { score, label: 'Weak', className: 'password-weak' };
  if (score <= 3) return { score, label: 'Medium', className: 'password-medium' };
  return { score, label: 'Strong', className: 'password-strong' };
};

const PasswordField: React.FC<PasswordFieldProps> = ({
  value,
  onChange,
  placeholder = "Password",
  showStrength = false,
  className = '',
  error,
  showIcon = false
}) => {
  const [isVisible, setIsVisible] = useState(false);
  const strength = getPasswordStrength(value);

  return (
    <div className="space-y-2">
      <div className="relative">
        {showIcon && (
          <Lock className="absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary z-10" size={18} />
        )}
        <Input
          type={isVisible ? 'text' : 'password'}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className={cn(
            'glass-panel pr-10 border-white/15 focus:border-primary/50 focus:ring-primary/20',
            showIcon && 'pl-10',
            error && 'border-error-border focus:border-error-border focus:ring-error-border/20',
            className
          )}
        />
        <button
          type="button"
          onClick={() => setIsVisible(!isVisible)}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-text-secondary hover:text-text-primary transition-colors"
        >
          {isVisible ? <EyeOff size={18} /> : <Eye size={18} />}
        </button>
      </div>
      
      {error && (
        <div className="text-sm text-error-text">{error}</div>
      )}
      
      {showStrength && value.length > 0 && (
        <div className="space-y-2">
          <div className="flex gap-1">
            {[1, 2, 3, 4, 5].map((level) => (
              <div
                key={level}
                className={cn(
                  'h-1 flex-1 rounded-full transition-colors',
                  level <= strength.score
                    ? strength.className.includes('weak')
                      ? 'bg-roast-brown'
                      : strength.className.includes('medium')
                      ? 'bg-honey'
                      : 'bg-caramel'
                    : 'bg-charcoal'
                )}
              />
            ))}
          </div>
          <div className={cn('text-xs px-2 py-1 rounded-md inline-block', strength.className)}>
            {strength.label}
          </div>
        </div>
      )}
    </div>
  );
};

export default PasswordField;