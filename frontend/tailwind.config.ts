import type { Config } from "tailwindcss";

// PyroSight design system — mission-critical dark UI.
//
// Every colour codes one meaning (see lib/design.ts for the semantic map).
// Surfaces are frosted glass over the live feed so the firefighter's view of
// the real world is never occluded by opaque chrome.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#04070a", // page background
        panel: "#0b1015", // card background
        panelSolid: "#0b1015",
        edge: "#1d2833", // borders — solid hairline, not a wash
        dim: "#8b9bab", // secondary text
        bright: "#e8f0f6", // primary text

        nav: "#22d3ee", // navigation — light blue
        victim: "#22d3ee", // persons / victims — light blue
        crew: "#facc15", // firefighters
        crewAccent: "#facc15",
        door: "#4ade80", // doors
        exit: "#34d399", // exit signs
        warn: "#fbbf24", // warnings
        heat: "#fb923c", // high heat
        danger: "#f87171", // critical danger
        unknown: "#94a3b8", // unknown / low confidence

        accent: "#22d3ee",
        ok: "#4ade80",
      },
      fontFamily: {
        sans: ["var(--font-sans)"],
        mono: ["var(--font-sans)"], // one typeface everywhere, per spec
      },
      letterSpacing: {
        hud: "0.14em",
        wide2: "0.22em",
      },
      backdropBlur: { glass: "14px" },
      boxShadow: {
        glass: "0 8px 32px rgba(0,0,0,0.55), inset 0 1px 0 rgba(255,255,255,0.06)",
        glow: "0 0 24px -4px currentColor",
      },
      transitionTimingFunction: {
        // One easing curve for the whole product: fast out, settle soft.
        hud: "cubic-bezier(0.22, 1, 0.36, 1)",
      },
      animation: {
        alarm: "alarm 1.1s cubic-bezier(0.4,0,0.6,1) infinite",
        breathe: "breathe 2.6s cubic-bezier(0.4,0,0.6,1) infinite",
        riseIn: "riseIn 260ms cubic-bezier(0.22,1,0.36,1) both",
        fadeIn: "fadeIn 220ms cubic-bezier(0.22,1,0.36,1) both",
        sweep: "sweep 2.4s linear infinite",
      },
      keyframes: {
        // Critical warnings breathe rather than blink: a hard strobe is
        // fatiguing and reads as a display fault in low visibility.
        alarm: { "0%,100%": { opacity: "1" }, "50%": { opacity: "0.45" } },
        breathe: { "0%,100%": { opacity: "0.85" }, "50%": { opacity: "0.35" } },
        riseIn: {
          from: { opacity: "0", transform: "translateY(6px) scale(0.985)" },
          to: { opacity: "1", transform: "translateY(0) scale(1)" },
        },
        fadeIn: { from: { opacity: "0" }, to: { opacity: "1" } },
        sweep: {
          from: { strokeDashoffset: "0" },
          to: { strokeDashoffset: "-40" },
        },
      },
    },
  },
  plugins: [],
};
export default config;
