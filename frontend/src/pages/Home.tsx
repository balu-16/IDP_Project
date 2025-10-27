import React from 'react';
import { motion } from 'framer-motion';
import { ArrowRight, Upload, MessageCircle, Sparkles, Coffee } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import CoffeeBackground from '@/components/CoffeeBackground';
import Navbar from '@/components/Navbar';
import { Button } from '@/components/ui/button';

const Home: React.FC = () => {
  const navigate = useNavigate();

  const features = [
    {
      icon: Upload,
      title: "Upload Documents",
      description: "Drop your PDFs and images to get started with AI-powered analysis"
    },
    {
      icon: MessageCircle,
      title: "Ask Questions",
      description: "Chat naturally with our AI about your uploaded content"
    },
    {
      icon: Sparkles,
      title: "Get Insights",
      description: "Receive intelligent answers and deep insights from your documents"
    }
  ];

  return (
    <div className="relative min-h-screen overflow-hidden">
      {/* 3D Coffee Background */}
      <CoffeeBackground variant="full" />

      {/* Navbar */}
      <Navbar />

      {/* Hero Section */}
      <main className="relative z-10 flex flex-col items-center justify-center min-h-screen px-6 pt-24">
        <div className="max-w-4xl mx-auto text-center space-y-8">
          <motion.div
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, ease: "easeOut" }}
          >
            <h1 className="text-5xl md:text-7xl font-bold text-text-primary mb-6">
              AI-Powered{' '}
              <span className="bg-gradient-to-r from-caramel via-honey to-burnt-amber bg-clip-text text-transparent">
                Document
              </span>{' '}
              Intelligence
            </h1>
            <p className="text-xl md:text-2xl text-text-secondary max-w-3xl mx-auto leading-relaxed">
              Upload your documents, chat with our AI, and unlock insights like never before. 
              Experience the future of document analysis with warm, intelligent conversations.
            </p>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.2, ease: "easeOut" }}
            className="flex flex-col sm:flex-row gap-4 justify-center items-center"
          >
            <Button
              size="lg"
              onClick={() => navigate('/signup')}
              className="bg-primary hover:bg-primary/90 text-primary-foreground px-8 py-4 text-lg font-medium glow-caramel hover:glow-honey transition-all"
            >
              Get Started
              <ArrowRight className="ml-2" size={20} />
            </Button>
            <Button
              size="lg"
              variant="outline"
              onClick={() => navigate('/login')}
              className="glass-panel border-primary/30 text-text-primary hover:bg-primary/10 px-8 py-4 text-lg font-medium"
            >
              Try Demo
            </Button>
          </motion.div>
        </div>

        {/* How It Works Section */}
        <motion.div
          initial={{ opacity: 0, y: 40 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.4, ease: "easeOut" }}
          className="max-w-6xl mx-auto mt-32 mb-20"
        >
          <h2 className="text-3xl md:text-4xl font-bold text-center text-text-primary mb-16">
            How It Works
          </h2>
          
          <div className="grid md:grid-cols-3 gap-8">
            {features.map((feature, index) => (
              <motion.div
                key={feature.title}
                initial={{ opacity: 0, y: 30 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.6, delay: 0.5 + index * 0.1 }}
                whileHover={{ 
                  scale: 1.05,
                  transition: { duration: 0.2 } 
                }}
                className="glass-panel p-8 text-center hover:glow-caramel transition-all group"
              >
                <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-caramel to-honey flex items-center justify-center mx-auto mb-6 group-hover:scale-110 transition-transform">
                  <feature.icon size={32} className="text-deep-black" />
                </div>
                <h3 className="text-xl font-semibold text-text-primary mb-4">
                  {feature.title}
                </h3>
                <p className="text-text-secondary leading-relaxed">
                  {feature.description}
                </p>
              </motion.div>
            ))}
          </div>
        </motion.div>
      </main>

      {/* Footer */}
      <footer className="relative z-10 border-t border-white/15 p-8">
        <div className="max-w-7xl mx-auto text-center">
          <div className="flex items-center justify-center gap-3 mb-4">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-caramel to-honey flex items-center justify-center">
              <Coffee size={18} className="text-deep-black" />
            </div>
            <span className="text-lg font-semibold text-text-primary">QubitChat AI</span>
          </div>
          <p className="text-text-secondary">
            © 2024 QubitChat AI. Brewing intelligence, one conversation at a time.
          </p>
        </div>
      </footer>
    </div>
  );
};

export default Home;