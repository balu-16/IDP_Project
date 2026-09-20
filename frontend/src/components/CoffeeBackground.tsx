import React, { useMemo } from 'react';

interface CoffeeBackgroundProps {
  variant?: 'full' | 'muted';
  className?: string;
}

// Deterministic PRNG so the geometry is stable across renders
// (previously Math.random() regenerated shapes on every render,
// including chat input updates).
function mulberry32(seed: number) {
  return () => {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const CoffeeBackground: React.FC<CoffeeBackgroundProps> = ({
  variant = 'full',
  className = ''
}) => {
  const shapes = useMemo(
    () => {
      const rand = mulberry32(20260911);
      return Array.from({ length: 8 }, (_, i) => ({
        id: i,
        size: rand() * 200 + 100,
        x: rand() * 100,
        y: rand() * 100,
      }));
    },
    []
  );

  const opacity = variant === 'full' ? 0.4 : 0.2;

  return (
    <div className={`fixed inset-0 overflow-hidden ${className}`}>
      {/* Light mode clean background */}
      <div className="absolute inset-0 bg-background transition-colors duration-300" />

      {/* Dark mode interactive coffee shapes & gradient */}
      <div className="absolute inset-0 transition-opacity duration-300 opacity-0 dark:opacity-100 grain-overlay">
        <div className="absolute inset-0 bg-gradient-to-br from-[#050505] via-[#0b0c0a] to-[#2c1407]" />
      
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
    </div>
  );
};

export default CoffeeBackground;