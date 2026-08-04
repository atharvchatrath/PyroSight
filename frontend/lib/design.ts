// PyroSight semantic design tokens.
//
// The rule the whole interface obeys: a colour means one thing, everywhere.
// A firefighter must be able to decode the display in under half a second, so
// hue carries meaning and everything else (weight, glow, dash) carries
// certainty. Nothing here is decorative.

import { Track } from "./types";

export type Role =
  | "nav"
  | "victim"
  | "crew"
  | "door"
  | "exit"
  | "warn"
  | "heat"
  | "critical"
  | "unknown"
  | "system";

export const COLOR: Record<Role, string> = {
  nav: "#22d3ee", // safe navigation — light blue
  victim: "#22d3ee", // civilians / victims — light blue
  crew: "#facc15", // firefighters
  door: "#4ade80",
  exit: "#34d399",
  warn: "#fbbf24", // warnings
  heat: "#fb923c", // high heat
  critical: "#f87171", // fire / critical danger
  unknown: "#94a3b8", // unidentified or low confidence
  system: "#e8f0f6", // system information
};

export const CREW_ACCENT = "#facc15";

// Deuteranopia/protanopia-safe substitutions. Green↔red separation is the
// failure case, so victims move to blue-cyan and hazards to amber-orange.
const CB_OVERRIDE: Partial<Record<Role, string>> = {
  door: "#facc15", // egress moves off green…
  exit: "#facc15",
  crew: "#e8f0f6", // …and crew off yellow so the two stay separable
  critical: "#fb923c",
  heat: "#ffc255",
};

const CLASS_ROLE: Record<string, Role> = {
  person: "victim",
  firefighter: "crew",
  door: "door",
  exit_sign: "exit",
  window: "exit",
  stairs: "nav",
  hallway: "unknown",
  fire: "critical",
  hotspot: "heat",
};

// Classes withheld from the display for now. Detection still runs and still
// records — this is a presentation decision, not a pipeline change, so it
// reverses by deleting one entry.
export const SUPPRESSED_CLASSES = new Set<string>(["firefighter"]);

export function isSuppressed(t: Pick<Track, "cls">): boolean {
  return SUPPRESSED_CLASSES.has(t.cls);
}

export function roleOf(t: Pick<Track, "cls" | "category">): Role {
  const r = CLASS_ROLE[t.cls];
  if (r) return r;
  if (t.category === "person") return "victim";
  if (t.category === "egress") return "exit";
  if (t.category === "hazard") return "heat";
  return "unknown";
}

export function colorOf(role: Role, colorblind = false): string {
  if (colorblind && CB_OVERRIDE[role]) return CB_OVERRIDE[role] as string;
  return COLOR[role];
}

// ------------------------------------------------------------- confidence

export type ConfBand = "high" | "good" | "fair" | "low";

/** 100–95 green · 94–85 cyan · 84–70 yellow · <70 gray + "POSSIBLE". */
export function confBand(conf: number): ConfBand {
  if (conf >= 0.95) return "high";
  if (conf >= 0.85) return "good";
  if (conf >= 0.7) return "fair";
  return "low";
}

export const CONF_COLOR: Record<ConfBand, string> = {
  high: "#4ade80",
  good: "#22d3ee",
  fair: "#facc15",
  low: "#94a3b8",
};

export function confColor(conf: number): string {
  return CONF_COLOR[confBand(conf)];
}

/**
 * Uncertain detections are never presented as facts. A track is "possible"
 * when the backend's temporal tier says so, when confidence sits under the
 * band floor, or when the tracker is coasting through an occlusion.
 */
export function isPossible(t: Pick<Track, "tier" | "conf" | "coasting">): boolean {
  return t.tier === "possible" || t.conf < 0.7 || t.coasting;
}

export function displayLabel(t: Pick<Track, "display" | "tier" | "conf" | "coasting">): string {
  // The tracker already prefixes its own "possible" tier (<0.50). The HUD
  // holds a stricter bar (<0.70), so it may need to add the prefix itself —
  // but never twice.
  const base = t.display.replace(/^possible\s+/i, "");
  return isPossible(t) ? `POSSIBLE ${base}` : base;
}

// ------------------------------------------------------------ mission mode

export type MissionMode = "SEARCH" | "RESCUE" | "EVAC" | "TRAINING";

export const MODE_META: Record<
  MissionMode,
  { label: string; color: string; hint: string }
> = {
  SEARCH: { label: "SEARCH", color: COLOR.nav, hint: "Victims · doors · coverage" },
  RESCUE: { label: "RESCUE", color: COLOR.victim, hint: "Victim · route · exit" },
  EVAC: { label: "EVACUATE", color: COLOR.critical, hint: "Exit · hazards only" },
  TRAINING: { label: "TRAINING", color: COLOR.warn, hint: "Full instrumentation" },
};

/** Which detection roles survive the declutter pass in each mode. */
export function roleVisible(role: Role, mode: MissionMode): boolean {
  if (mode === "EVAC") {
    // Strip everything that is not an exit, a hazard, or another person.
    return role === "exit" || role === "critical" || role === "heat" ||
      role === "victim" || role === "crew";
  }
  if (mode === "RESCUE") return role !== "unknown";
  return true;
}

// ------------------------------------------------------------------ format

export function ft(v: number | null | undefined): string {
  return v == null ? "—" : `${Math.round(v)} FT`;
}

export function pct(v: number): string {
  return `${Math.round(v * 100)}%`;
}

export function bearingText(rel: number): "AHEAD" | "LEFT" | "RIGHT" | "BEHIND" {
  const a = ((rel + 540) % 360) - 180;
  if (Math.abs(a) <= 20) return "AHEAD";
  if (Math.abs(a) >= 150) return "BEHIND";
  return a > 0 ? "RIGHT" : "LEFT";
}
