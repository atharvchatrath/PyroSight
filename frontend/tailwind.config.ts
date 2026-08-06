import type { Config } from "tailwindcss";

// PyroSight design system — mission-critical dark UI, orange on black.
//
// The palette is deliberately monochromatic-warm. A helmet display is read
// through a scratched visor, in smoke, by an eye that has been staring at
// flame: the cool blues and greens the interface used to lean on are the first
// hues to disappear under that condition, and they fight the fireground itself
// for attention. Warm hues survive it, and orange on true black is the
// highest-contrast combination the OLED panel can produce at low duty cycle —
// which also matters because lit pixels are battery.
//
// Since hue alone can no longer separate ten classes, LUMINANCE carries the
// hierarchy: white is a human, amber is a way out, deep red-orange is fire.
// Ordered brightest to darkest, the ramp reads as a priority list even to a
// colourblind operator, and still reads on a monochrome panel.
// See lib/design.ts for the semantic map.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0a0603", // page background — black, warm cast
        panel: "#150d06", // card background
        panelSolid: "#150d06",
        edge: "#3d2412", // borders — solid hairline, not a wash
        dim: "#a8815e", // secondary text
        bright: "#ffeedd", // primary text

        nav: "#ff8a1f", // navigation
        victim: "#ffffff", // humans — the brightest mark on the display
        crew: "#ffd9a8", // firefighters
        crewAccent: "#ffd9a8",
        door: "#ff8a1f", // doors
        exit: "#ffc24b", // exit signs and windows
        warn: "#ffab2e", // warnings
        heat: "#ff6a00", // high heat
        danger: "#ff3b0f", // fire / critical danger
        unknown: "#9a7358", // unknown / low confidence

        accent: "#ff7a18",
        ok: "#ffc24b",
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
        glass: "0 8px 32px rgba(0,0,0,0.6), inset 0 1px 0 rgba(255,180,110,0.07)",
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
        listen: "listen 1.4s cubic-bezier(0.4,0,0.6,1) infinite",
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
        // The voice console's "I'm listening" pulse. Distinct from `alarm`
        // on purpose — the system waiting for you must never look like the
        // system warning you.
        listen: {
          "0%,100%": { opacity: "1", transform: "scaleY(1)" },
          "50%": { opacity: "0.5", transform: "scaleY(0.55)" },
        },
      },
    },
  },
  plugins: [],
};
export default config;
