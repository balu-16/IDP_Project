import React from 'react';

interface CoffeeBackgroundProps {
  variant?: 'full' | 'muted';
  className?: string;
}

const CoffeeBackground: React.FC<CoffeeBackgroundProps> = ({ 
  variant = 'full', 
  className = '' 
}) => {
  const shapes = Array.from({ length: 8 }, (_, i) => ({
    id: i,
    size: Math.random() * 200 + 100,
    x: Math.random() * 100,
    y: Math.random() * 100,
  }));

  const opacity = variant === 'full' ? 0.4 : 0.2;

  return (
    <div className={`fixed inset-0 overflow-hidden grain-overlay ${className}`}>
      {/* Base gradient */}
      <div className="absolute inset-0 bg-gradient-to-br from-deep-black via-charcoal to-dark-espresso" />
      
      {/* Static coffee vapor shapes */}
      {shapes.map((shape) => (
        <div
          key={shape.id}
          className="absolute rounded-full filter blur-3xl"
          style={{
            width: shape.size,
            height: shape.size,
            left: `${shape.x}%`,
            top: `${shape.y}%`,
            background: `radial-gradient(circle, 
              hsl(var(--mocha)) 0%, 
              hsl(var(--caramel) / 0.6) 40%, 
              hsl(var(--honey) / 0.3) 70%, 
              transparent 100%)`,
            opacity: opacity,
          }}
        />
      ))}
      
      {/* Additional static ambient shapes for depth */}
      {variant === 'full' && (
        <>
          <div
            className="absolute top-1/4 left-1/4 w-96 h-96 rounded-full filter blur-3xl"
            style={{
              background: 'radial-gradient(circle, hsl(var(--caramel) / 0.3) 0%, transparent 70%)',
              opacity: 0.4,
            }}
          />
          <div
            className="absolute bottom-1/3 right-1/3 w-80 h-80 rounded-full filter blur-3xl"
            style={{
              background: 'radial-gradient(circle, hsl(var(--honey) / 0.2) 0%, transparent 70%)',
              opacity: 0.3,
            }}
          />
        </>
      )}
    </div>
  );
};

export default CoffeeBackground;