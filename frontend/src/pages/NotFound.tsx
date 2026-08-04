import { useLocation, Link } from "react-router-dom";
import { useEffect } from "react";
import CoffeeBackground from "@/components/CoffeeBackground";
import { Button } from "@/components/ui/button";
import { Coffee, Home } from "lucide-react";

const NotFound = () => {
  const location = useLocation();

  useEffect(() => {
    console.error(
      "404 Error: User attempted to access non-existent route:",
      location.pathname
    );
  }, [location.pathname]);

  return (
    <div className="relative min-h-screen flex items-center justify-center">
      <CoffeeBackground variant="muted" />
      
      <div className="relative z-10 text-center space-y-8 p-6">
        <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-caramel to-honey flex items-center justify-center mx-auto">
          <Coffee size={40} className="text-deep-black" />
        </div>
        
        <div className="space-y-4">
          <h1 className="text-6xl font-bold text-text-primary">404</h1>
          <h2 className="text-2xl font-semibold text-text-primary">Brew Not Found</h2>
          <p className="text-lg text-text-secondary max-w-md mx-auto">
            Looks like this page went cold. Let's get you back to something warm and familiar.
          </p>
        </div>
        
        <div className="flex flex-col sm:flex-row gap-4 justify-center">
          <Button
            asChild
            className="bg-primary hover:bg-primary/90 text-primary-foreground px-6 py-3 glow-caramel"
          >
            <Link to="/">
              <Home className="mr-2" size={18} />
              Back to Home
            </Link>
          </Button>
          <Button
            asChild
            variant="outline"
            className="glass-panel border-primary/30 text-text-primary hover:bg-primary/10 px-6 py-3"
          >
            <Link to="/chat">
              Start Chatting
            </Link>
          </Button>
        </div>
      </div>
    </div>
  );
};

export default NotFound;
