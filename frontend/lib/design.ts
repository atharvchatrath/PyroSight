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

// The warm ramp. Hue no longer separates ten classes on its own — LUMINANCE
// does, and it is ordered by operational priority so the brightest thing on
// the display is always the thing that matters most:
//
//   white   a human
//   amber   a way out
//   orange  something structural
//   red     fire
//   brown   we don't know
//
// That ordering survives a colourblind eye, a monochrome panel, and a visor
// with soot on it, none of which a blue/green/red scheme does.
export const COLOR: Record<Role, string> = {
  nav: "#ff8a1f", // safe navigation
  victim: "#ffffff", // humans — brightest mark on the display, always
  crew: "#ffd9a8", // firefighters
  door: "#ff8a1f",
  exit: "#ffc24b", // exit signs and windows
  warn: "#ffab2e", // warnings
  heat: "#ff6a00", // high heat
  critical: "#ff3b0f", // fire / critical danger
  unknown: "#9a7358", // unidentified or low confidence
  system: "#ffeedd", // system information
};

export const CREW_ACCENT = "#ffd9a8";

// An all-warm palette removes the red↔green failure entirely, which is the
// one that used to matter here. What replaces it is a subtler risk: to a
// deuteranope, orange and red sit closer together than they do to a
// trichromat. So the fix is no longer substitution — it is widening the
// LUMINANCE gaps between neighbours in the ramp, which every kind of vision
// can read.
const CB_OVERRIDE: Partial<Record<Role, string>> = {
  critical: "#ff2a00", // fire goes darker and more saturated…
  heat: "#ffa64d", // …and heat goes much brighter, so the two separate
  warn: "#ffd98a",
  exit: "#fff0cc", // egress lifts toward white, well clear of door orange
  door: "#ff7a00",
  crew: "#d9c3ae", // crew drops below victim white so bodies stay distinct
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

/** Brighter is more certain: 100–95 cream · 94–85 amber · 84–70 orange ·
 *  <70 muted + "POSSIBLE". The ramp is a dimmer, not a traffic light. */
export function confBand(conf: number): ConfBand {
  if (conf >= 0.95) return "high";
  if (conf >= 0.85) return "good";
  if (conf >= 0.7) return "fair";
  return "low";
}

export const CONF_COLOR: Record<ConfBand, string> = {
  high: "#ffe9c7",
  good: "#ffc24b",
  fair: "#ff8a1f",
  low: "#9a7358",
};

export function confColor(conf: number): string {
  return CONF_COLOR[confBand(conf)];
}

/**
 * POSSIBLE answers exactly one question: do we know WHAT this is?
 *
 * It used to answer two, and produced nonsense doing it — an exit sign seen
 * clearly and then stepped behind rendered as "POSSIBLE EXIT SIGN 93%",
 * hedging the identity of a thing whose identity was never in doubt. What
 * had changed was visibility, not recognition. Two different facts were
 * being pushed through one word, so the word stopped meaning either.
 *
 * The interface already had a separate channel for visibility, matching the
 * rule this file opens with — colour and wording say what a thing IS, weight
 * and dashing and opacity say how sure we are we can still see it. So:
 *
 *   POSSIBLE    identity is uncertain  -> name is hedged
 *   stale       we've lost sight of it -> dashed, dimmed, tagged OCCLUDED
 *
 * Corroboration settles identity. A track a second independent modality
 * agreed with — Lepton body heat, flame flicker, a classical egress match —
 * is called by its name; everything else keeps the strict 0.70 bar.
 */
export function isPossible(
  t: Pick<Track, "tier" | "conf" | "corroborated">
): boolean {
  if (t.tier === "possible") return true;
  if (t.corroborated) return false;
  return t.conf < 0.7;
}

/** Render provisionally: identity is uncertain, or we've lost sight of it. */
export function isProvisional(
  t: Pick<Track, "tier" | "conf" | "corroborated" | "stale">
): boolean {
  return isPossible(t) || !!t.stale;
}

export function displayLabel(
  t: Pick<Track, "display" | "tier" | "conf" | "corroborated">
): string {
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

/** Human-readable name for the active perception backend.
 *
 * The wire value is an internal id — "sitl-truth" is meaningful to whoever
 * wrote the simulator and to nobody else. Anything shown outside the training
 * overlay goes through here, because a chief or an investor reading
 * "SITL-TRUTH" on a status bar learns nothing except that this was built for
 * its own authors. */
export function detectorLabel(detector: string | undefined): string {
  switch (detector) {
    case "sitl-truth":
      return "SIMULATION";
    case "yolo-world":
      return "YOLO-WORLD";
    case "onnx":
      return "YOLOV8 ONNX";
    case "none":
      return "CLASSICAL CV";
    default:
      return (detector ?? "—").toUpperCase();
  }
}

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
