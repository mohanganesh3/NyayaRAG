import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "var(--color-ink-950)",
          900: "var(--color-ink-900)",
          800: "var(--color-ink-800)",
          700: "var(--color-ink-700)",
        },
        paper: {
          50: "var(--color-paper-50)",
          100: "var(--color-paper-100)",
          200: "var(--color-paper-200)",
          300: "var(--color-paper-300)",
        },
        brass: {
          500: "var(--color-brass-500)",
          300: "var(--color-brass-300)",
        },
        teal: {
          500: "var(--color-teal-500)",
          400: "var(--color-teal-400)",
        },
        garnet: {
          500: "var(--color-garnet-500)",
        },
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        serif: ["var(--font-serif)", "Georgia", "serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      boxShadow: {
        dossier: "var(--shadow-panel)",
        card: "var(--shadow-card)",
      },
    },
  },
  plugins: [],
};

export default config;
