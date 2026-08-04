"use client";

// Bottom status rail: the machine's own vitals, plus the one instruction the
// firefighter is currently meant to act on and the one confidence number that
// says how much to trust the display right now.
//
// Icons are thin single-colour vectors — colour is the whole status channel,
// so the rail can be decoded without reading a word of it.

import { SystemState } from "@/lib/types";
import { COLOR, confColor, isSuppressed } from "@/lib/design";

function statusColor(status: string): string {
  if (status === "ok") return COLOR.victim;
  if (status === "simulated") return COLOR.nav;
  if (status === "degraded" || status === "estimated") return COLOR.warn;
  return COLOR.critical;
}

const ICON = "w-[15px] h-[15px] shrink-0";

function BatteryIcon({ pct, color }: { pct: number; color: string }) {
  return (
    <svg viewBox="0 0 24 24" className={ICON} fill="none" stroke={color} strokeWidth={1.6}>
      <rect x="2" y="7" width="17" height="10" rx="0.5" />
      <path d="M21 10.5v3" strokeLinecap="round" />
      <rect
        x="3.8"
        y="8.8"
        width={Math.max(1, 13.4 * Math.min(1, Math.max(0, pct / 100)))}
        height="6.4"
        rx="0"
        fill={color}
        stroke="none"
      />
    </svg>
  );
}

function CamIcon({ color }: { color: string }) {
  return (
    <svg viewBox="0 0 24 24" className={ICON} fill="none" stroke={color} strokeWidth={1.6}>
      <rect x="2.5" y="6.5" width="19" height="12" rx="0.5" />
      <circle cx="12" cy="12.5" r="3.4" />
    </svg>
  );
}

function ThermalIcon({ color }: { color: string }) {
  return (
    <svg viewBox="0 0 24 24" className={ICON} fill="none" stroke={color} strokeWidth={1.6}
      strokeLinecap="round">
      <path d="M4 16c2-3 4-3 6 0s4 3 6 0 2-3 4-1.5" />
      <path d="M4 10c2-3 4-3 6 0s4 3 6 0 2-3 4-1.5" />
    </svg>
  );
}

function ImuIcon({ color }: { color: string }) {
  return (
    <svg viewBox="0 0 24 24" className={ICON} fill="none" stroke={color} strokeWidth={1.6}>
      <circle cx="12" cy="12" r="8" />
      <ellipse cx="12" cy="12" rx="8" ry="3.4" />
      <path d="M12 4v16" strokeOpacity={0.6} />
    </svg>
  );
}

function AiIcon({ color }: { color: string }) {
  return (
    <svg viewBox="0 0 24 24" className={ICON} fill="none" stroke={color} strokeWidth={1.6}
      strokeLinecap="round">
      <rect x="7" y="7" width="10" height="10" rx="0.5" />
      <path d="M10 4v3M14 4v3M10 17v3M14 17v3M4 10h3M4 14h3M17 10h3M17 14h3" />
    </svg>
  );
}

function LinkIcon({ color, on }: { color: string; on: boolean }) {
  return (
    <svg viewBox="0 0 24 24" className={ICON} fill="none" stroke={color} strokeWidth={1.6}
      strokeLinecap="round">
      <path d="M4.5 10a11 11 0 0 1 15 0" strokeOpacity={on ? 1 : 0.25} />
      <path d="M7.5 13.5a7 7 0 0 1 9 0" strokeOpacity={on ? 1 : 0.4} />
      <circle cx="12" cy="17.5" r="1.3" fill={color} stroke="none" />
    </svg>
  );
}

function Item({
  icon,
  value,
  label,
  color,
}: {
  icon: React.ReactNode;
  value: string;
  label: string;
  color?: string;
}) {
  return (
    <div className="flex items-center gap-1.5" title={label}>
      {icon}
      <span className="text-[12px] num tracking-hud" style={{ color: color ?? "#e8f0f6" }}>
        {value}
      </span>
    </div>
  );
}

export default function StatusRail({
  state,
  connected,
  recording = true,
}: {
  state: SystemState;
  connected: boolean;
  recording?: boolean;
}) {
  const d = state.diagnostics;
  const battery = d.battery_percent;
  const batteryColor =
    battery == null
      ? COLOR.unknown
      : battery > 40
      ? COLOR.victim
      : battery > 20
      ? COLOR.warn
      : COLOR.critical;

  const sensors = d.sensors ?? {};
  const cam = sensors.rgb;
  const thm = sensors.thermal;
  const imu = sensors.imu;

  // Suppressed classes are excluded from the trust number as well — the rail
  // must describe what the operator can actually see on the display.
  const tracked = state.tracks.filter((t) => !t.coasting && !isSuppressed(t));
  const avgConf =
    tracked.length > 0
      ? tracked.reduce((a, t) => a + t.conf, 0) / tracked.length
      : null;

  const aiColor =
    state.inference?.ms == null
      ? COLOR.unknown
      : state.inference.ms < 120
      ? COLOR.victim
      : COLOR.warn;

  return (
    <div className="panel-float flex items-center gap-4 px-3.5 py-2 text-dim">
      <Item
        icon={<BatteryIcon pct={battery ?? 0} color={batteryColor} />}
        // A USB-C PD pack has no gauge the Pi can read. Say so rather than
        // showing a dash the operator might read as "still fine", and mark a
        // coulomb-counted figure as approximate.
        value={
          battery != null
            ? `${d.battery_source === "counted" ? "≈" : ""}${Math.round(battery)}%`
            : "NO GAUGE"
        }
        label={`Battery (${d.battery_source ?? "unknown"} source)`}
        color={batteryColor}
      />
      {d.runtime_min != null && (
        <span className="cap -ml-2.5">~{d.runtime_min}M</span>
      )}

      <div className="h-4 w-px bg-white/10" />

      <div className="flex items-center gap-3">
        <CamIcon color={cam ? statusColor(cam.status) : COLOR.unknown} />
        <ThermalIcon color={thm ? statusColor(thm.status) : COLOR.unknown} />
        <ImuIcon color={imu ? statusColor(imu.status) : COLOR.unknown} />
      </div>

      <div className="h-4 w-px bg-white/10" />

      <Item
        icon={<AiIcon color={aiColor} />}
        value={
          state.inference?.ms != null
            ? `${Math.round(state.inference.ms)} MS`
            : state.detector.toUpperCase()
        }
        label="AI inference"
        color={aiColor}
      />
      <Item
        icon={<LinkIcon color={connected ? COLOR.victim : COLOR.critical} on={connected} />}
        value={`${state.fps.toFixed(0)} FPS`}
        label="Link / frame rate"
        color={connected ? undefined : COLOR.critical}
      />
      {recording && (
        <div className="flex items-center gap-1.5" title="Incident recording">
          <span className="w-2 h-2 rounded-full bg-danger animate-breathe" />
          <span className="text-[12px] tracking-hud">REC</span>
        </div>
      )}

      {/* the one instruction */}
      <div className="flex-1 min-w-0 px-2">
        <div className="text-[14px] text-bright tracking-hud text-center truncate">
          {state.nav.instruction}
        </div>
      </div>

      {/* the one confidence number */}
      <div className="flex items-baseline gap-1.5 shrink-0">
        <span className="cap">AI CONF</span>
        <span
          className="text-[15px] font-semibold num"
          style={{ color: avgConf != null ? confColor(avgConf) : COLOR.unknown }}
        >
          {avgConf != null ? `${Math.round(avgConf * 100)}%` : "—"}
        </span>
        <span className="cap">{tracked.length} TRK</span>
      </div>
    </div>
  );
}
