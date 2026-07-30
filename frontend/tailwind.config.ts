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
        ink: "#050a0e",        // page background
        panel: "#0d1319",      // card background
        panel2: "#121a22",     // elevated / nested card background
        edge: "#212e3a",       // borders
        dim: "#8b9bab",        // secondary text
        bright: "#eef4f9",     // primary text
        accent: "#2dd4ee",     // system / persons
        ok: "#3ee08a",         // egress / good
        warn: "#fbbf24",       // caution
        danger: "#fb6a6a",     // hazard / critical
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      animation: {
        // Critical warnings must pulse — the one permitted looping animation.
        alarm: "alarm 0.8s steps(2, start) infinite",
        // Non-repeating entrance only; never used on data that needs to be
        // trusted at a glance mid-incident.
        rise: "rise 0.35s ease-out",
      },
      keyframes: {
        alarm: {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.35" },
        },
        rise: {
          "0%": { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
    },
  },
  plugins: [],
};
export default config;
