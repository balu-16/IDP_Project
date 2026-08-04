import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Coffee, Menu, X } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { ThemeToggle } from './ThemeToggle';

const Navbar: React.FC = () => {
  const navigate = useNavigate();
  const [isScrolled, setIsScrolled] = useState(false);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);

  useEffect(() => {
    const handleScroll = () => {
      setIsScrolled(window.scrollY > 50);
    };

    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);



  return (
    <motion.header
      initial={{ opacity: 0, y: -20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6 }}
      className={`fixed top-0 left-0 right-0 z-50 transition-all duration-300 ${
        isScrolled
          ? 'bg-surface/90 dark:bg-glass-bg backdrop-blur-xl border-b border-border dark:border-glass-border shadow-sm dark:shadow-glass'
          : 'bg-transparent border-b border-transparent'
      }`}
    >
      <nav className="h-16 flex items-center justify-between max-w-7xl mx-auto px-6">
        {/* Logo */}
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-caramel to-honey flex items-center justify-center">
            <Coffee size={18} className="text-deep-black" />
          </div>
          <h1 className="text-lg font-bold text-text-primary">
            QubitChat<span className="text-roast-brown">AI</span>
          </h1>
        </div>



        {/* Desktop Actions */}
        <div className="hidden md:flex items-center gap-4">
          <ThemeToggle />
          <Button
            variant="ghost"
            onClick={() => navigate('/login')}
            className="text-text-secondary hover:text-primary hover:bg-transparent hover:underline px-4"
          >
            Login
          </Button>
          <Button
            onClick={() => navigate('/signup')}
            className="bg-primary hover:bg-primary/90 text-primary-foreground rounded-xl px-6 shadow-sm"
          >
            Get Started
          </Button>
        </div>

        {/* Mobile Menu Button */}
        <button
          onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
          className="md:hidden p-2 text-text-secondary hover:text-text-primary transition-colors"
        >
          {isMobileMenuOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
      </nav>

      {/* Mobile Menu */}
      <AnimatePresence>
        {isMobileMenuOpen && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.3 }}
            className="md:hidden bg-surface dark:bg-glass-bg backdrop-blur-xl border-b border-border dark:border-glass-border shadow-sm dark:shadow-glass"
          >
            <div className="px-6 py-4 space-y-4">
              <div className="flex justify-between items-center mb-2">
                <span className="text-sm text-text-secondary font-medium">Theme</span>
                <ThemeToggle />
              </div>
              <div className="space-y-3">
                <Button
                  variant="ghost"
                  onClick={() => {
                    navigate('/login');
                    setIsMobileMenuOpen(false);
                  }}
                  className="w-full justify-start text-text-secondary hover:text-caramel hover:bg-transparent"
                >
                  Login
                </Button>
                <Button
                  onClick={() => {
                    navigate('/signup');
                    setIsMobileMenuOpen(false);
                  }}
                  className="w-full bg-primary hover:bg-primary/90 text-primary-foreground rounded-xl"
                >
                  Get Started
                </Button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.header>
  );
};

export default Navbar;