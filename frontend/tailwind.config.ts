import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        navy: {
          900: "#0B1426",
          800: "#1A2744",
        },
        cream: {
          50: "#F8F6F0",
          100: "#F0EDE4",
        },
        gold: {
          400: "#C9A227",
        },
        text: {
          primary: "#1A1A2E",
          secondary: "#4A4A6A",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        serif: ["Lora", "Georgia", "serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;

