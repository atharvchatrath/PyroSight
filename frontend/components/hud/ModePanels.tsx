"use client";

// Mode-specific HUD furniture. Each of these appears in exactly one mission
// mode, which is what keeps the display from accumulating everything the
// platform knows: search coverage matters during a primary search and is pure
// clutter during egress.

import { SystemState } from "@/lib/types";
import { COLOR, confColor, displayLabel, ft } from "@/lib/design";
import { useHeatTrend } from "./ThermalOverlay";

// --------------------------------------------------------- ALL MODES
/**
 * Thermal penetration status. When the camera is blind — heavy smoke, zero
 * visibility — the thermal path is the only thing still finding fire, and the
 * firefighter needs to know that the marks on screen came from heat, not from
 * an image nobody can see. Shown whenever smoke is thick enough to matter.
 */
export function ThermalPenetrationChip({ state }: { state: SystemState }) {
  const smoke = state.smoke?.density ?? 0;
  const spots = state.hotspots ?? [];
  const measured =
    state.thermal_source === "lepton" || state.thermal_source === "sim";
  // Without a radiometric sensor there is no penetration to claim: the
  // estimate is derived from the same image the smoke is blinding.
  if (!measured) {
    if (smoke < 0.3) return null;
    return (
      <div className="panel-float px-3 py-2 min-w-[13rem]"
        style={{ borderColor: `${COLOR.warn}66` }}>
        <div className="text-[12px] font-semibold tracking-wide2" style={{ color: COLOR.warn }}>
          NO MEASURED THERMAL
        </div>
        <div className="cap mt-0.5">
          SMOKE {Math.round(smoke * 100)}% · RGB ESTIMATE ONLY
        </div>
      </div>
    );
  }
  if (smoke < 0.3 || spots.length === 0) return null;

  const estimated = false;
  const hottest = Math.max(...spots.map((h) => h.max_temp_c));
  const worst = spots.some((h) => h.severity === "critical");
  const color = worst ? COLOR.critical : COLOR.heat;

  return (
    <div className="panel-float px-3 py-2 min-w-[13rem]" style={{ borderColor: `${color}66` }}>
      <div className="flex items-center gap-2">
        <svg viewBox="0 0 24 24" className="w-3.5 h-3.5 shrink-0" fill="none" stroke={color}
          strokeWidth={1.7} strokeLinecap="round">
          <path d="M4 15c2-3 4-3 6 0s4 3 6 0 2-3 4-1.5" />
          <path d="M4 9c2-3 4-3 6 0s4 3 6 0 2-3 4-1.5" />
        </svg>
        <span className="text-[12px] font-semibold tracking-wide2" style={{ color }}>
          {estimated ? "THERMAL ESTIMATE" : "THERMAL PENETRATION"}
        </span>
      </div>
      <div className="mt-1 text-[12px] text-bright tracking-hud num">
        {spots.length} HEAT SOURCE{spots.length === 1 ? "" : "S"} · {Math.round(hottest)}°C MAX
      </div>
      <div className="cap mt-0.5">
        {estimated
          ? "RGB-DERIVED · NOT RADIOMETRIC"
          : `SMOKE ${Math.round(smoke * 100)}% · SEEING THROUGH IT`}
      </div>
    </div>
  );
}

// -------------------------------------------------------------- RESCUE
/** The victim being worked: one card, the four facts that drive the carry. */
export function FocusCard({ state }: { state: SystemState }) {
  const victim = state.tracks
    .filter((t) => t.category === "person" && t.cls === "person")
    .sort((a, b) => (a.dist_ft ?? 999) - (b.dist_ft ?? 999))[0];
  if (!victim) return null;

  return (
    <div className="panel-float px-3.5 py-2.5 min-w-[13rem] animate-riseIn"
      style={{ borderColor: `${COLOR.victim}55` }}>
      <div className="flex items-center gap-2">
        <span className="w-2 h-2 rounded-full" style={{ background: COLOR.victim,
          boxShadow: `0 0 10px ${COLOR.victim}` }} />
        <span className="text-[13px] font-semibold tracking-wide2"
          style={{ color: COLOR.victim }}>
          {displayLabel(victim)}
        </span>
      </div>
      <div className="mt-1.5 flex items-baseline gap-3">
        <span className="text-[26px] font-semibold text-bright num leading-none">
          {ft(victim.dist_ft)}
        </span>
        <span className="text-[13px] num" style={{ color: confColor(victim.conf) }}>
          {Math.round(victim.conf * 100)}%
        </span>
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 cap">
        <span>{victim.thermal_confirmed ? "BODY HEAT ✓" : "NO THERMAL MATCH"}</span>
        <span>TRACKED {victim.age.toFixed(0)}S</span>
        {victim.coasting && <span style={{ color: COLOR.warn }}>THROUGH SMOKE</span>}
      </div>
    </div>
  );
}

// -------------------------------------------------------------- SEARCH
/** Coverage progress: how much of this floor has actually been swept. */
export function CoverageChip({ state }: { state: SystemState }) {
  const s = state.search;
  if (!s?.active) return null;
  const pct = Math.max(0, Math.min(100, s.coverage_pct));
  const R = 15;
  const C = 2 * Math.PI * R;

  return (
    <div className="panel-float px-3 py-2 flex items-center gap-3 animate-riseIn">
      <svg width={38} height={38} className="shrink-0">
        <circle cx={19} cy={19} r={R} fill="none" stroke="rgba(150,180,210,0.18)" strokeWidth={3} />
        <circle
          cx={19}
          cy={19}
          r={R}
          fill="none"
          stroke={COLOR.nav}
          strokeWidth={3}
          strokeLinecap="round"
          strokeDasharray={`${(C * pct) / 100} ${C}`}
          transform="rotate(-90 19 19)"
          style={{ transition: "stroke-dasharray 600ms cubic-bezier(0.22,1,0.36,1)" }}
        />
        <text x={19} y={22.5} textAnchor="middle" fontSize={10.5} fontWeight={600}
          fill="#e8f0f6" style={{ fontFamily: "var(--font-sans)" }}>
          {Math.round(pct)}
        </text>
      </svg>
      <div>
        <div className="cap leading-none">SEARCH COVERAGE</div>
        <div className="text-[12px] text-bright tracking-hud mt-1">
          {s.explored_cells} CLEARED
          {s.needs_pass > 0 && (
            <span style={{ color: COLOR.warn }}> · {s.needs_pass} NEED PASS</span>
          )}
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------- TRAINING
/** Instructor instrumentation: what the pipeline is doing, live. */
export function TrainingPanel({ state }: { state: SystemState }) {
  const trend = useHeatTrend(state);
  const rows: [string, string, string?][] = [
    ["DETECTOR", state.detector.toUpperCase()],
    ["INFERENCE", state.inference?.ms != null ? `${Math.round(state.inference.ms)} MS` : "—"],
    ["MODEL AGE", state.inference?.age_s != null ? `${state.inference.age_s.toFixed(1)} S` : "—"],
    ["THERMAL SRC", (state.thermal_source ?? "—").toUpperCase(),
      state.thermal_source === "rgb-estimate" ? COLOR.warn : undefined],
    ["SMOKE", `${Math.round(state.smoke.density * 100)}% · ${state.smoke.visibility}`],
    ["HOTSPOTS", String(state.hotspots.length)],
    // A flame entering frame produces slopes in the thousands of °C/min,
    // which is arithmetically true and operationally meaningless. Past the
    // point where the number stops informing, say what it means instead.
    ["HEAT TREND",
      trend == null
        ? "SETTLING"
        : Math.abs(trend) > 200
        ? trend > 0 ? "RISING FAST" : "FALLING FAST"
        : `${trend >= 0 ? "+" : ""}${trend.toFixed(1)} °C/MIN`,
      trend != null && trend > 8 ? COLOR.critical : undefined],
    ["COVERAGE", state.search?.active ? `${Math.round(state.search.coverage_pct)}%` : "INACTIVE"],
    ["TRACKS", `${state.tracks.length} · ${state.tracks.filter((t) => t.coasting).length} COASTING`],
  ];

  return (
    <div className="panel-float px-3 py-2.5 w-[15.5rem] animate-riseIn">
      <div className="cap mb-1.5" style={{ color: COLOR.warn }}>
        TRAINING INSTRUMENTATION
      </div>
      <div className="space-y-1">
        {rows.map(([k, v, c]) => (
          <div key={k} className="flex items-baseline justify-between gap-3">
            <span className="cap">{k}</span>
            <span className="text-[12px] num tracking-hud" style={{ color: c ?? "#e8f0f6" }}>
              {v}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
