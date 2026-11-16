// Plain var() colors make Tailwind drop opacity modifiers (bg-muted/40 generates no CSS);
// <alpha-value> lets bg-x/NN, border-x/NN etc. work on CSS-variable tokens.
const cssVarColor = (name) =>
  `color-mix(in srgb, var(--${name}) calc(<alpha-value> * 100%), transparent)`

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // shadcn semantic tokens (mapped to FrigoLoco mockup CSS variables)
        border: cssVarColor('border'),
        input: cssVarColor('input'),
        ring: cssVarColor('ring'),
        background: cssVarColor('background'),
        foreground: cssVarColor('foreground'),
        primary: {
          DEFAULT: cssVarColor('primary'),
          foreground: cssVarColor('primary-foreground'),
        },
        secondary: {
          DEFAULT: cssVarColor('secondary'),
          foreground: cssVarColor('secondary-foreground'),
        },
        destructive: {
          DEFAULT: cssVarColor('destructive'),
          foreground: cssVarColor('destructive-foreground'),
        },
        muted: {
          DEFAULT: cssVarColor('muted'),
          foreground: cssVarColor('muted-foreground'),
        },
        accent: {
          DEFAULT: cssVarColor('accent'),
          foreground: cssVarColor('accent-foreground'),
        },
        popover: {
          DEFAULT: cssVarColor('popover'),
          foreground: cssVarColor('popover-foreground'),
        },
        card: {
          DEFAULT: cssVarColor('card'),
          foreground: cssVarColor('card-foreground'),
        },
        // FrigoLoco brand tokens (from the canonical mockup)
        sidebar: {
          DEFAULT: cssVarColor('sidebar-bg'),
          ink: cssVarColor('sidebar-ink'),
        },
        series: {
          1: cssVarColor('series-1'),
          2: cssVarColor('series-2'),
          3: cssVarColor('series-3'),
        },
        good: cssVarColor('good'),
        'good-text': cssVarColor('good-text'),
        warning: cssVarColor('warning'),
        critical: cssVarColor('critical'),
        teal: cssVarColor('teal'),
      },
      borderRadius: {
        lg: cssVarColor('radius'),
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
      },
      fontFamily: {
        sans: [
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'sans-serif',
        ],
      },
      keyframes: {
        'accordion-down': {
          from: { height: '0' },
          to: { height: 'var(--radix-accordion-content-height)' },
        },
        'accordion-up': {
          from: { height: 'var(--radix-accordion-content-height)' },
          to: { height: '0' },
        },
      },
      animation: {
        'accordion-down': 'accordion-down 0.2s ease-out',
        'accordion-up': 'accordion-up 0.2s ease-out',
      },
    },
  },
  plugins: [require('tailwindcss-animate')],
}
