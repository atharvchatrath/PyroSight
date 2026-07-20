import type { Config } from "tailwindcss";

// Industrial dark theme tuned for high contrast in bad viewing conditions.
// No decorative gradients; every color codes a meaning.
const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        ink: "#04070a",       // page background
        panel: "#0b1015",     // card background
        edge: "#1d2833",      // borders
        dim: "#8b9bab",       // secondary text
        bright: "#e8f0f6",    // primary text
        accent: "#22d3ee",    // system / persons
        ok: "#4ade80",        // egress / good
        warn: "#fbbf24",      // caution
        danger: "#f87171",    // hazard / critical
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      animation: {
        // The single permitted animation: critical warnings must pulse.
        alarm: "alarm 0.8s steps(2, start) infinite",
      },
      keyframes: {
        alarm: {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.35" },
        },
      },
    },
  },
  plugins: [],
};
export default config;
