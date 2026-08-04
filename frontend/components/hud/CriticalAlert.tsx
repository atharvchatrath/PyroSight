"use client";

// Critical alerting with an explicit anti-fatigue policy.
//
// Every condition the platform can shout about is scored, and only the single
// highest-ranked one is ever on screen; the rest collapse into a "+2 MORE"
// count that the dashboard can expand. A HUD that shows four warnings at once
// has, in practice, shown none of them.
//
// Conditions are re-derived from telemetry each frame rather than latched, so
// an alert disappears the moment the world stops justifying it.

import { SystemState } from "@/lib/types";
import { COLOR } from "@/lib/design";

export interface DerivedAlert {
  rule: string;
  text: string;
  rank: number; // higher wins
  severity: "critical" | "warning" | "info";
}

export function deriveAlerts(state: SystemState): DerivedAlert[] {
  const out: DerivedAlert[] = [];
  const d = state.diagnostics;
  const sensors = d.sensors ?? {};

  if (state.nav.status === "BLOCKED") {
    out.push({ rule: "exit_blocked", text: "ROUTE BLOCKED — REROUTING", rank: 95, severity: "critical" });
  }

  // Temperature alarms require a MEASURED field. An RGB-derived estimate is
  // not a thermometer — a warm-lit face must never be able to raise EXTREME
  // HEAT — so estimated thermal is excluded from every heat rule below.
  const measured =
    state.thermal_source === "lepton" || state.thermal_source === "sim";
  const hottest = measured ? state.thermal?.max_c ?? null : null;
  const critHot =
    measured && (state.hotspots ?? []).some((h) => h.severity === "critical");
  if (critHot || (hottest != null && hottest >= 250)) {
    out.push({
      rule: "extreme_heat",
      text: `EXTREME HEAT${hottest != null ? ` — ${Math.round(hottest)}°C` : ""}`,
      rank: 90,
      severity: "critical",
    });
  }

  // Fire must be corroborated before it alarms: either measured thermal at
  // the same place, or the flicker/colour check. An uncorroborated visual
  // guess stays a POSSIBLE label on the display and never reaches this rail.
  const fire = state.tracks.find(
    (t) => t.cls === "fire" && t.conf >= 0.7 && (t.thermal_confirmed || t.corroborated)
  );
  if (fire) {
    out.push({
      rule: "fire",
      text: `FIRE${fire.dist_ft != null ? ` ${Math.round(fire.dist_ft)} FT` : ""}`,
      rank: 85,
      severity: "critical",
    });
  }

  if (sensors.rgb && (sensors.rgb.status === "offline" || sensors.rgb.status === "degraded")) {
    out.push({ rule: "camera", text: "CAMERA FAILURE — CV DEGRADED", rank: 80, severity: "critical" });
  }

  const badSensor = Object.entries(sensors).find(
    ([k, s]) => k !== "rgb" && s.status === "offline"
  );
  if (badSensor) {
    out.push({
      rule: `sensor_${badSensor[0]}`,
      text: `${badSensor[0].toUpperCase()} SENSOR ERROR — FALLBACK ACTIVE`,
      rank: 60,
      severity: "warning",
    });
  }

  const bat = d.battery_percent;
  if (bat != null && bat <= 10) {
    out.push({ rule: "battery_crit", text: `BATTERY ${Math.round(bat)}% — EXIT NOW`, rank: 88, severity: "critical" });
  } else if (bat != null && bat <= 20) {
    out.push({ rule: "battery_low", text: `LOW BATTERY ${Math.round(bat)}%`, rank: 55, severity: "warning" });
  }

  if (state.smoke.density >= 0.85) {
    out.push({ rule: "visibility", text: "VISIBILITY NEAR ZERO", rank: 50, severity: "warning" });
  }

  const victim = state.tracks.find((t) => t.cls === "person" && t.conf >= 0.75 && !t.coasting);
  if (victim) {
    out.push({
      rule: "person",
      text: `PERSON DETECTED — ${Math.round(victim.conf * 100)}%${
        victim.dist_ft != null ? ` · ${Math.round(victim.dist_ft)} FT` : ""
      }`,
      rank: 70,
      severity: "info",
    });
  }

  // The backend's own rule engine, folded in on equal terms.
  const la = state.last_alert;
  if (la && state.ts - la.ts < 8) {
    out.push({
      rule: la.rule,
      text: la.text,
      rank: la.severity === "critical" ? 92 : la.severity === "warning" ? 58 : 40,
      severity: (la.severity as DerivedAlert["severity"]) ?? "info",
    });
  }

  // Deduplicate by rule, keep the strongest phrasing of each.
  const byRule = new Map<string, DerivedAlert>();
  for (const a of out) {
    const prev = byRule.get(a.rule);
    if (!prev || a.rank > prev.rank) byRule.set(a.rule, a);
  }
  return [...byRule.values()].sort((a, b) => b.rank - a.rank);
}

const TONE: Record<DerivedAlert["severity"], { fg: string; bg: string }> = {
  critical: { fg: COLOR.critical, bg: "rgba(248,113,113,0.14)" },
  warning: { fg: COLOR.warn, bg: "rgba(251,191,36,0.12)" },
  info: { fg: COLOR.nav, bg: "rgba(34,211,238,0.10)" },
};

export default function CriticalAlert({ state }: { state: SystemState }) {
  const alerts = deriveAlerts(state);
  const top = alerts[0];
  if (!top) return null;
  const tone = TONE[top.severity];
  const extra = alerts.length - 1;

  return (
    <div
      className={`panel-float flex items-center gap-3 px-4 py-2 ${
        top.severity === "critical" ? "animate-alarm" : "animate-riseIn"
      }`}
      style={{ borderColor: `${tone.fg}80`, background: tone.bg }}
      role="status"
    >
      <span
        className="w-1.5 h-6 rounded-full shrink-0"
        style={{ background: tone.fg, boxShadow: `0 0 14px ${tone.fg}` }}
      />
      <span
        className="text-[16px] font-semibold tracking-wide2"
        style={{ color: tone.fg }}
      >
        {top.text}
      </span>
      {extra > 0 && <span className="cap ml-1">+{extra} MORE</span>}
    </div>
  );
}
