"use client";

// Command-dashboard panels.
//
// The dashboard is the same design language as the helmet — same palette,
// same confidence bands, same typography — at desk density instead of glance
// density. Incident command and the firefighter must never be looking at two
// different vocabularies for the same situation.

import { useEffect, useMemo, useState } from "react";
import {
  Diagnostics,
  SystemState,
  TelemetryEvent,
  Track,
  apiUrl,
} from "@/lib/types";
import {
  COLOR,
  colorOf,
  confColor,
  displayLabel,
  isPossible,
  isSuppressed,
  roleOf,
} from "@/lib/design";
import { clockTime } from "@/lib/format";
import { deriveAlerts } from "@/components/hud/CriticalAlert";
import { useHeatTrend } from "@/components/hud/ThermalOverlay";

export function Panel({
  title,
  right,
  children,
  className = "",
}: {
  title: string;
  right?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel flex flex-col min-h-0 ${className}`}>
      <div className="flex items-center justify-between gap-3 border-b border-edge px-4 py-2.5">
        <h2 className="text-[11px] font-semibold tracking-wide2 text-dim uppercase">
          {title}
        </h2>
        {right}
      </div>
      <div className="flex-1 min-h-0 overflow-auto p-3">{children}</div>
    </section>
  );
}

export function StatTile({
  label,
  value,
  sub,
  color = "#ffeedd",
  fill,
}: {
  label: string;
  value: string;
  sub?: string;
  color?: string;
  fill?: number; // 0..1 → progress bar
}) {
  return (
    <div className="border border-edge bg-white/[0.02] px-3 py-2.5">
      <div className="cap leading-none">{label}</div>
      <div className="mt-1.5 text-[19px] font-semibold num leading-none" style={{ color }}>
        {value}
      </div>
      {fill != null && (
        <div className="mt-2 h-1 rounded-full bg-white/10 overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-500 ease-hud"
            style={{ width: `${Math.max(2, Math.min(100, fill * 100))}%`, background: color }}
          />
        </div>
      )}
      {sub && <div className="mt-1.5 cap">{sub}</div>}
    </div>
  );
}

// ---------------------------------------------------------------- detections

function TrackRow({ t }: { t: Track }) {
  const color = colorOf(roleOf(t));
  const possible = isPossible(t);
  return (
    <li className="flex items-center gap-3 py-2 border-b border-edge/60 last:border-0">
      <span
        className="w-2 h-2 rounded-full shrink-0"
        style={{ background: color, boxShadow: `0 0 8px ${color}`, opacity: possible ? 0.5 : 1 }}
      />
      <span
        className="text-[13px] font-medium tracking-hud w-[11.5rem] truncate"
        style={{ color: possible ? COLOR.unknown : "#ffeedd" }}
      >
        {displayLabel(t)}
      </span>
      <div className="w-16 h-1.5 rounded-full bg-white/10 overflow-hidden shrink-0">
        <div
          className="h-full rounded-full"
          style={{ width: `${Math.round(t.conf * 100)}%`, background: confColor(t.conf) }}
        />
      </div>
      <span className="text-[12px] num w-10 text-right" style={{ color: confColor(t.conf) }}>
        {Math.round(t.conf * 100)}%
      </span>
      <span className="text-[12px] num text-dim w-14 text-right">
        {t.dist_ft != null ? `${Math.round(t.dist_ft)} ft` : "—"}
      </span>
      <span className="text-[12px] num text-dim w-16 text-right">
        {t.max_temp_c != null ? `${Math.round(t.max_temp_c)}°C` : ""}
      </span>
      <span className="cap w-24 text-right truncate">
        {t.thermal_confirmed ? "THERMAL ✓" : t.stale ? "OCCLUDED" : `${t.age.toFixed(0)}s`}
      </span>
    </li>
  );
}

export function TrackList({
  state,
  category,
  empty,
}: {
  state: SystemState;
  category: Track["category"] | "all";
  empty: string;
}) {
  const rows = state.tracks
    .filter((t) => !isSuppressed(t))
    .filter((t) => category === "all" || t.category === category)
    .sort((a, b) => b.priority - a.priority || b.conf - a.conf);
  if (rows.length === 0) return <div className="cap py-1">{empty}</div>;
  return (
    <ul>
      {rows.map((t) => (
        <TrackRow key={t.id} t={t} />
      ))}
    </ul>
  );
}

/** Kept for compatibility with older imports. */
export function DetectionLog({ state }: { state: SystemState }) {
  return <TrackList state={state} category="all" empty="NO TRACKS" />;
}

// ------------------------------------------------------------------ alerts

export function AlertsPanel({ state }: { state: SystemState }) {
  const alerts = deriveAlerts(state);
  if (alerts.length === 0) return <div className="cap">NOTHING REQUIRING ATTENTION</div>;
  return (
    <ul className="space-y-1.5">
      {alerts.map((a) => {
        const c =
          a.severity === "critical" ? COLOR.critical : a.severity === "warning" ? COLOR.warn : COLOR.nav;
        return (
          <li
            key={a.rule}
            className="flex items-center gap-2.5 border px-3 py-2"
            style={{ borderColor: `${c}44`, background: `${c}0f` }}
          >
            <span className="w-1 h-4 rounded-full" style={{ background: c }} />
            <span className="text-[13px] tracking-hud" style={{ color: c }}>
              {a.text}
            </span>
            <span className="cap ml-auto">{a.severity}</span>
          </li>
        );
      })}
    </ul>
  );
}

// ------------------------------------------------------------------ timeline

const SEV_COLOR: Record<string, string> = {
  critical: COLOR.critical,
  warning: COLOR.warn,
  info: COLOR.nav,
};

export function EventTimeline({
  events,
  kinds,
}: {
  events: TelemetryEvent[];
  kinds?: string[];
}) {
  const list = (kinds ? events.filter((e) => kinds.includes(e.kind)) : events).slice().reverse();
  if (list.length === 0) return <div className="cap">NO EVENTS YET</div>;
  return (
    <ul className="space-y-1.5">
      {list.map((e) => {
        const c = SEV_COLOR[e.severity ?? "info"] ?? COLOR.unknown;
        return (
          <li key={e.seq} className="flex gap-2.5 items-baseline">
            <span className="text-[11px] num text-dim shrink-0 w-14">{clockTime(e.ts)}</span>
            <span
              className="text-[10px] font-semibold tracking-wide2 uppercase shrink-0 w-[4.5rem]"
              style={{ color: c }}
            >
              {e.kind}
            </span>
            <span className="text-[12.5px] text-bright/90 truncate">
              {e.text ?? ""}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

// ----------------------------------------------------------------- heat map

export function HeatPanel({ state }: { state: SystemState }) {
  const trend = useHeatTrend(state);
  const t = state.thermal;
  if (!t) return <div className="cap">NO THERMAL DATA</div>;
  const estimated = state.thermal_source === "rgb-estimate";

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-2">
        <StatTile label="MIN" value={`${Math.round(t.min_c)}°C`} color={COLOR.nav} />
        <StatTile label="MEAN" value={`${Math.round(t.mean_c)}°C`} />
        <StatTile
          label="MAX"
          value={`${Math.round(t.max_c)}°C`}
          color={t.max_c > 250 ? COLOR.critical : COLOR.heat}
          sub={
            trend == null
              ? "TREND SETTLING"
              : `${trend >= 0 ? "▲" : "▼"} ${Math.abs(trend).toFixed(1)} °C/MIN`
          }
        />
      </div>
      {estimated && (
        <div className="cap" style={{ color: COLOR.warn }}>
          RGB-DERIVED ESTIMATE — NOT RADIOMETRIC
        </div>
      )}
      <div>
        <div className="cap mb-1.5">HOTSPOTS ({state.hotspots.length})</div>
        {state.hotspots.length === 0 && <div className="cap">NONE ABOVE THRESHOLD</div>}
        <ul className="space-y-1">
          {state.hotspots.map((h, i) => {
            const c =
              h.severity === "critical" ? COLOR.critical : h.severity === "severe" ? COLOR.heat : COLOR.warn;
            return (
              <li key={i} className="flex items-center gap-2 text-[12px]">
                <span className="w-1.5 h-1.5 rounded-full" style={{ background: c }} />
                <span className="tracking-hud" style={{ color: c }}>
                  {h.severity.toUpperCase()}
                </span>
                <span className="num text-dim ml-auto">{Math.round(h.mean_temp_c)}°C mean</span>
                <span className="num text-bright w-16 text-right">{Math.round(h.max_temp_c)}°C</span>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ sensors

export function SensorPanel({ diag }: { diag: Diagnostics }) {
  const rows = Object.entries(diag.sensors ?? {});
  return (
    <ul className="space-y-2">
      {rows.map(([kind, s]) => {
        const c =
          s.status === "ok"
            ? COLOR.victim
            : s.status === "simulated"
            ? COLOR.nav
            : s.status === "degraded" || s.status === "estimated"
            ? COLOR.warn
            : COLOR.critical;
        return (
          <li key={kind} className="flex items-center gap-2.5">
            <span className="w-2 h-2 rounded-full shrink-0" style={{ background: c, boxShadow: `0 0 8px ${c}` }} />
            <span className="text-[12.5px] font-medium tracking-hud w-20">{kind.toUpperCase()}</span>
            <span className="text-[12px] text-dim truncate flex-1">{s.detail}</span>
            <span className="cap shrink-0">
              {s.last_read_age_s != null ? `${s.last_read_age_s.toFixed(1)}s` : ""}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

// -------------------------------------------------------------- diagnostics

const BATTERY_SOURCE_LABEL: Record<string, string> = {
  gauge: "FUEL GAUGE",
  counted: "COULOMB COUNT",
  host: "HOST BATTERY",
  simulated: "SIMULATED",
  none: "NO PACK TELEMETRY",
};

export function DiagnosticsPanel({ state }: { state: SystemState }) {
  const d = state.diagnostics;
  const pctColor = (v: number | null) =>
    v == null ? COLOR.unknown : v > 88 ? COLOR.critical : v > 70 ? COLOR.warn : "#ffeedd";

  return (
    <div className="grid grid-cols-2 gap-2">
      <StatTile
        label="BATTERY"
        value={
          d.battery_percent != null
            ? `${d.battery_source === "counted" ? "≈" : ""}${Math.round(d.battery_percent)}%`
            : "NO GAUGE"
        }
        // Command must be able to tell a measured state of charge from a
        // coulomb count that has been drifting since boot.
        sub={
          [
            d.runtime_min != null ? `~${d.runtime_min} MIN LEFT` : null,
            BATTERY_SOURCE_LABEL[d.battery_source ?? "none"],
          ]
            .filter(Boolean)
            .join(" · ") || undefined
        }
        color={
          d.battery_percent == null
            ? COLOR.unknown
            : d.battery_percent > 40
            ? COLOR.victim
            : d.battery_percent > 20
            ? COLOR.warn
            : COLOR.critical
        }
        fill={d.battery_percent != null ? d.battery_percent / 100 : undefined}
      />
      <StatTile
        label="CPU"
        value={d.cpu_percent != null ? `${Math.round(d.cpu_percent)}%` : "—"}
        sub={d.cpu_temp_c != null ? `CORE ${Math.round(d.cpu_temp_c)}°C` : undefined}
        color={pctColor(d.cpu_percent)}
        fill={d.cpu_percent != null ? d.cpu_percent / 100 : undefined}
      />
      <StatTile
        label="MEMORY"
        value={d.mem_percent != null ? `${Math.round(d.mem_percent)}%` : "—"}
        color={pctColor(d.mem_percent)}
        fill={d.mem_percent != null ? d.mem_percent / 100 : undefined}
      />
      <StatTile
        label="STORAGE"
        value={d.disk_percent != null ? `${Math.round(d.disk_percent)}%` : "—"}
        color={pctColor(d.disk_percent)}
        fill={d.disk_percent != null ? d.disk_percent / 100 : undefined}
      />
      <StatTile
        label="FRAME RATE"
        value={`${d.fps.toFixed(1)} FPS`}
        color={d.fps >= 12 ? COLOR.victim : COLOR.warn}
      />
      <StatTile
        label="LATENCY"
        value={`${Math.round(d.latency_ms)} MS`}
        color={d.latency_ms < 80 ? COLOR.victim : COLOR.warn}
      />
      <StatTile
        label="DETECTOR"
        value={state.detector.toUpperCase()}
        sub={state.inference?.ms != null ? `${Math.round(state.inference.ms)} MS INFERENCE` : undefined}
      />
      <StatTile
        label="POWER"
        value={(d.power_state ?? "—").toUpperCase()}
        sub={`UPTIME ${Math.floor(d.uptime_s / 60)}M ${d.uptime_s % 60}S`}
        color={d.power_state === "normal" ? COLOR.victim : COLOR.warn}
      />
    </div>
  );
}

// --------------------------------------------------------------- incidents

interface IncidentSession {
  id: string;
  events: number;
  snapshots: number;
}

export function IncidentsPanel() {
  const [sessions, setSessions] = useState<IncidentSession[]>([]);
  useEffect(() => {
    const load = () =>
      fetch(apiUrl("/api/incidents"))
        .then((r) => r.json())
        .then(setSessions)
        .catch(() => {});
    load();
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, []);
  if (sessions.length === 0) return <div className="cap">NO RECORDINGS</div>;
  return (
    <ul className="space-y-1.5">
      {sessions.map((s) => (
        <li key={s.id} className="flex items-center gap-3 text-[12.5px]">
          <span className="num text-bright">{s.id}</span>
          <span className="cap ml-auto">
            {s.events} EVENTS · {s.snapshots} SNAPSHOTS
          </span>
        </li>
      ))}
    </ul>
  );
}

// -------------------------------------------------------------- search mode

export function SearchPanel({ state }: { state: SystemState }) {
  const s = state.search;
  if (!s?.active) {
    return (
      <div className="text-[12.5px] text-dim leading-relaxed">
        Search mode inactive. Say <span className="text-bright">“search room”</span> or use the
        command bar to begin a guided room search.
      </div>
    );
  }
  const cells = s.cells ?? [];
  const xs = cells.map((c) => c.x);
  const ys = cells.map((c) => c.y);
  const minX = Math.min(-4, ...xs);
  const maxX = Math.max(4, ...xs);
  const minY = Math.min(-4, ...ys);
  const maxY = Math.max(4, ...ys);
  const cols = maxX - minX + 1;
  const rows = maxY - minY + 1;
  const px = Math.min(12, Math.floor(190 / Math.max(cols, rows)));

  return (
    <div className="flex items-start gap-4">
      <svg width={cols * px} height={rows * px} className="shrink-0">
        {cells.map((c, i) => (
          <rect
            key={i}
            x={(c.x - minX) * px}
            y={(maxY - c.y) * px}
            width={px - 1.5}
            height={px - 1.5}
            rx={2}
            fill={c.level === 2 ? COLOR.victim : COLOR.warn}
            opacity={c.level === 2 ? 0.75 : 0.4}
          />
        ))}
      </svg>
      <div className="space-y-2">
        <div className="text-[22px] font-semibold num" style={{ color: COLOR.nav }}>
          {Math.round(s.coverage_pct)}%
        </div>
        <div className="cap">EXPLORED</div>
        <div className="text-[12.5px] text-dim">{s.explored_cells} cells cleared</div>
        {s.needs_pass > 0 && (
          <div className="text-[12.5px]" style={{ color: COLOR.warn }}>
            {s.needs_pass} cells need another pass
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------- mission replay

interface ReplayEvent {
  ts: number;
  kind: string;
  text?: string;
  display?: string;
  conf?: number;
  severity?: string;
}

export function MissionReplayPanel() {
  const [sessions, setSessions] = useState<IncidentSession[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [events, setEvents] = useState<ReplayEvent[]>([]);
  const [idx, setIdx] = useState(0);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    fetch(apiUrl("/api/incidents"))
      .then((r) => r.json())
      .then((rows: IncidentSession[]) => {
        setSessions(rows);
        if (rows.length && !selected) setSelected(rows[0].id);
      })
      .catch(() => {});
  }, [selected]);

  useEffect(() => {
    if (!selected) return;
    fetch(apiUrl(`/api/incidents/${selected}`))
      .then((r) => r.json())
      .then((rows: ReplayEvent[]) => {
        setEvents(rows);
        setIdx(0);
      })
      .catch(() => setEvents([]));
  }, [selected]);

  useEffect(() => {
    if (!playing || events.length === 0) return;
    const t = setInterval(() => {
      setIdx((i) => {
        if (i >= events.length - 1) {
          setPlaying(false);
          return i;
        }
        return i + 1;
      });
    }, 700);
    return () => clearInterval(t);
  }, [playing, events.length]);

  const t0 = events[0]?.ts ?? 0;
  const cur = events[idx];
  const window = useMemo(() => events.slice(Math.max(0, idx - 6), idx + 1), [events, idx]);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2 flex-wrap">
        <select
          className="btn btn-sm max-w-[13rem]"
          value={selected ?? ""}
          onChange={(e) => setSelected(e.target.value)}
        >
          {sessions.map((s) => (
            <option key={s.id} value={s.id} className="bg-panelSolid">
              {s.id} ({s.events})
            </option>
          ))}
          {sessions.length === 0 && <option>no recordings</option>}
        </select>
        <button className="btn btn-sm" onClick={() => setPlaying((p) => !p)}>
          {playing ? "❚❚ PAUSE" : "▶ PLAY"}
        </button>
        <button className="btn btn-sm" onClick={() => setIdx((i) => Math.max(0, i - 1))}>
          ◂
        </button>
        <button
          className="btn btn-sm"
          onClick={() => setIdx((i) => Math.min(events.length - 1, i + 1))}
        >
          ▸
        </button>
      </div>

      {events.length > 0 ? (
        <>
          <input
            type="range"
            min={0}
            max={events.length - 1}
            value={idx}
            onChange={(e) => setIdx(Number(e.target.value))}
            className="w-full accent-[#ff7a18]"
          />
          <div className="cap">
            EVENT {idx + 1}/{events.length} · T+{cur ? Math.round(cur.ts - t0) : 0}S
          </div>
          <ul className="space-y-1">
            {window.map((e, i) => (
              <li
                key={i}
                className={`flex gap-2.5 text-[12px] ${
                  i === window.length - 1 ? "text-bright" : "text-dim"
                }`}
              >
                <span
                  className="uppercase text-[10px] tracking-wide2 w-[4.5rem] shrink-0"
                  style={{ color: SEV_COLOR[e.severity ?? "info"] ?? COLOR.unknown }}
                >
                  {e.kind}
                </span>
                <span className="truncate">{e.text ?? e.display ?? ""}</span>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <div className="cap">NO RECORDED MISSION SELECTED</div>
      )}
    </div>
  );
}
