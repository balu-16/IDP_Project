import type { Config } from "tailwindcss";
import tailwindcssAnimate from "tailwindcss-animate";

export default {
	darkMode: ["class"],
	content: [
		"./pages/**/*.{ts,tsx}",
		"./components/**/*.{ts,tsx}",
		"./app/**/*.{ts,tsx}",
		"./src/**/*.{ts,tsx}",
	],
	prefix: "",
	theme: {
		container: {
			center: true,
			padding: '2rem',
			screens: {
				'2xl': '1400px'
			}
		},
		extend: {
			fontFamily: {
				sans: ['Inter', 'system-ui', 'sans-serif'],
			},
			colors: {
				// Coffee Palette
				'deep-black': 'hsl(var(--deep-black))',
				'charcoal': 'hsl(var(--charcoal))',
				'charcoal-ink': 'hsl(var(--charcoal-ink))',
				'dark-espresso': 'hsl(var(--dark-espresso))',
				'roast-brown': 'hsl(var(--roast-brown))',
				'mocha': 'hsl(var(--mocha))',
				'caramel': 'hsl(var(--caramel))',
				'burnt-amber': 'hsl(var(--burnt-amber))',
				'honey': 'hsl(var(--honey))',
				'toffee': 'hsl(var(--toffee))',
				'latte-beige': 'hsl(var(--latte-beige))',
				'oat-milk': 'hsl(var(--oat-milk))',
				'cashmere': 'hsl(var(--cashmere))',
				'sandstone': 'hsl(var(--sandstone))',
				'cocoa': 'hsl(var(--cocoa))',
				'walnut': 'hsl(var(--walnut))',

				// Core Theme
				border: 'hsl(var(--border))',
				input: 'hsl(var(--input))',
				ring: 'hsl(var(--ring))',
				background: 'hsl(var(--background))',
				foreground: 'hsl(var(--foreground))',
				surface: 'hsl(var(--surface))',
				
				primary: {
					DEFAULT: 'hsl(var(--primary))',
					foreground: 'hsl(var(--primary-foreground))'
				},
				secondary: {
					DEFAULT: 'hsl(var(--secondary))',
					foreground: 'hsl(var(--secondary-foreground))'
				},
				destructive: {
					DEFAULT: 'hsl(var(--destructive))',
					foreground: 'hsl(var(--destructive-foreground))'
				},
				muted: {
					DEFAULT: 'hsl(var(--muted))',
					foreground: 'hsl(var(--muted-foreground))'
				},
				accent: {
					DEFAULT: 'hsl(var(--accent))',
					foreground: 'hsl(var(--accent-foreground))'
				},
				popover: {
					DEFAULT: 'hsl(var(--popover))',
					foreground: 'hsl(var(--popover-foreground))'
				},
				card: {
					DEFAULT: 'hsl(var(--card))',
					foreground: 'hsl(var(--card-foreground))'
				},

				// Text Colors
				'text-primary': 'hsl(var(--text-primary))',
				'text-secondary': 'hsl(var(--text-secondary))',
				'text-link': 'hsl(var(--text-link))',
				'text-link-hover': 'hsl(var(--text-link-hover))',

				// Glass Panel
				'glass-panel': 'hsl(var(--glass-panel))',
				'glass-border': 'hsl(var(--glass-border))',

				// Semantic Colors
				info: {
					bg: 'hsl(var(--info-bg))',
					border: 'hsl(var(--info-border))',
					text: 'hsl(var(--info-text))',
					icon: 'hsl(var(--info-icon))'
				},
				success: {
					bg: 'hsl(var(--success-bg))',
					border: 'hsl(var(--success-border))',
					text: 'hsl(var(--success-text))',
					icon: 'hsl(var(--success-icon))'
				},
				warning: {
					bg: 'hsl(var(--warning-bg))',
					border: 'hsl(var(--warning-border))',
					text: 'hsl(var(--warning-text))',
					icon: 'hsl(var(--warning-icon))'
				},
				error: {
					bg: 'hsl(var(--error-bg))',
					border: 'hsl(var(--error-border))',
					text: 'hsl(var(--error-text))',
					icon: 'hsl(var(--error-icon))'
				}
			},
			borderRadius: {
				lg: 'var(--radius)',
				md: 'calc(var(--radius) - 2px)',
				sm: 'calc(var(--radius) - 4px)'
			},
			keyframes: {
				'accordion-down': {
					from: { height: '0' },
					to: { height: 'var(--radix-accordion-content-height)' }
				},
				'accordion-up': {
					from: { height: 'var(--radix-accordion-content-height)' },
					to: { height: '0' }
				},
				'fade-in': {
					'0%': { opacity: '0', transform: 'translateY(10px)' },
					'100%': { opacity: '1', transform: 'translateY(0)' }
				},
				'fade-out': {
					'0%': { opacity: '1', transform: 'translateY(0)' },
					'100%': { opacity: '0', transform: 'translateY(10px)' }
				},
				'scale-in': {
					'0%': { transform: 'scale(0.95)', opacity: '0' },
					'100%': { transform: 'scale(1)', opacity: '1' }
				},
				'scale-out': {
					'0%': { transform: 'scale(1)', opacity: '1' },
					'100%': { transform: 'scale(0.95)', opacity: '0' }
				},
				'slide-in-left': {
					'0%': { transform: 'translateX(-100%)' },
					'100%': { transform: 'translateX(0)' }
				},
				'slide-out-left': {
					'0%': { transform: 'translateX(0)' },
					'100%': { transform: 'translateX(-100%)' }
				},
				'float': {
					'0%, 100%': { transform: 'translateY(0px)' },
					'50%': { transform: 'translateY(-20px)' }
				},
				'drift': {
					'0%, 100%': { transform: 'translate(0px, 0px) rotate(0deg)' },
					'33%': { transform: 'translate(30px, -20px) rotate(5deg)' },
					'66%': { transform: 'translate(-20px, 10px) rotate(-3deg)' }
				},
				'pulse-glow': {
					'0%, 100%': { opacity: '0.6' },
					'50%': { opacity: '1' }
				}
			},
			animation: {
				'accordion-down': 'accordion-down 0.2s ease-out',
				'accordion-up': 'accordion-up 0.2s ease-out',
				'fade-in': 'fade-in 0.3s ease-out',
				'fade-out': 'fade-out 0.3s ease-out',
				'scale-in': 'scale-in 0.2s ease-out',
				'scale-out': 'scale-out 0.2s ease-out',
				'slide-in-left': 'slide-in-left 0.3s ease-out',
				'slide-out-left': 'slide-out-left 0.3s ease-out',
				'float': 'float 6s ease-in-out infinite',
				'drift': 'drift 60s ease-in-out infinite',
				'pulse-glow': 'pulse-glow 3s ease-in-out infinite'
			}
		}
	},
	plugins: [tailwindcssAnimate],
} satisfies Config;
