"use client";

// Command-dashboard panels. Each is a small, self-contained card; the grid
// in app/dashboard/page.tsx composes them.

import { useEffect, useMemo, useState } from "react";
import {
  Diagnostics,
  SystemState,
  TelemetryEvent,
  apiUrl,
} from "@/lib/types";
import { clockTime, severityColor } from "@/lib/format";

export function Panel({
  title,
  children,
  className = "",
}: {
  title: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel flex flex-col min-h-0 ${className}`}>
      <h2 className="panel-title">{title}</h2>
      <div className="flex-1 min-h-0 overflow-auto p-2">{children}</div>
    </section>
  );
}

// ---------------------------------------------------------------- detections

export function DetectionLog({ state }: { state: SystemState }) {
  return (
    <table className="w-full text-xs">
      <thead className="text-dim text-left">
        <tr>
          <th className="pb-1">OBJECT</th>
          <th>CONF</th>
          <th>DIST</th>
          <th>THERM</th>
        </tr>
      </thead>
      <tbody>
        {state.tracks.map((t) => (
          <tr key={t.id} className="border-t border-edge/50">
            <td className="py-1 font-bold" style={{ color: t.color }}>
              {t.display}
            </td>
            <td className={t.tier === "possible" ? "text-danger" : "text-bright"}>
              {Math.round(t.conf * 100)}%
            </td>
            <td className="text-dim">
              {t.dist_ft != null ? `${Math.round(t.dist_ft)} ft` : "—"}
            </td>
            <td>{t.thermal_confirmed ? "✓" : ""}</td>
          </tr>
        ))}
        {state.tracks.length === 0 && (
          <tr>
            <td colSpan={4} className="text-dim py-2">
              No confirmed tracks.
            </td>
          </tr>
        )}
      </tbody>
    </table>
  );
}

// ------------------------------------------------------------------ timeline

export function EventTimeline({
  events,
  kinds,
}: {
  events: TelemetryEvent[];
  kinds?: string[];
}) {
  const list = (kinds ? events.filter((e) => kinds.includes(e.kind)) : events)
    .slice()
    .reverse();
  return (
    <ul className="text-xs space-y-1">
      {list.map((e) => (
        <li key={e.seq} className="flex gap-2 border-b border-edge/40 pb-1">
          <span className="text-dim shrink-0">{clockTime(e.ts)}</span>
          <span className={`shrink-0 ${severityColor[e.severity ?? "info"]}`}>
            {e.kind.toUpperCase()}
          </span>
          <span className="text-bright truncate">
            {e.text ?? e.ack ?? e.transcript ?? ""}
          </span>
        </li>
      ))}
      {list.length === 0 && <li className="text-dim">No events yet.</li>}
    </ul>
  );
}

// ----------------------------------------------------------------- heat map

export function HeatPanel({ state }: { state: SystemState }) {
  const t = state.thermal;
  if (!t) return <div className="text-dim text-xs">No thermal data.</div>;
  return (
    <div className="text-xs space-y-2">
      <div className="grid grid-cols-3 gap-2 text-center">
        {[
          ["MIN", t.min_c, "text-accent"],
          ["MEAN", t.mean_c, "text-bright"],
          ["MAX", t.max_c, t.max_c > 250 ? "text-danger" : "text-warn"],
        ].map(([label, val, cls]) => (
          <div key={label as string} className="panel p-2">
            <div className="text-dim">{label}</div>
            <div className={`text-lg font-bold ${cls}`}>
              {Math.round(val as number)}°C
            </div>
          </div>
        ))}
      </div>
      <div>
        <div className="text-dim mb-1">HOTSPOTS ({state.hotspots.length})</div>
        {state.hotspots.map((h, i) => (
          <div key={i} className="flex justify-between border-t border-edge/40 py-1">
            <span
              className={
                h.severity === "critical"
                  ? "text-danger font-bold"
                  : h.severity === "severe"
                  ? "text-warn font-bold"
                  : "text-bright"
              }
            >
              {h.severity.toUpperCase()}
            </span>
            <span>{Math.round(h.max_temp_c)}°C max</span>
          </div>
        ))}
        {state.hotspots.length === 0 && (
          <div className="text-dim">None above threshold.</div>
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ sensors

export function SensorPanel({ diag }: { diag: Diagnostics }) {
  const rows = Object.entries(diag.sensors);
  return (
    <ul className="text-xs space-y-2">
      {rows.map(([kind, s]) => (
        <li key={kind} className="flex items-center gap-2">
          <span
            className={`w-2.5 h-2.5 rounded-full shrink-0 ${
              s.status === "ok"
                ? "bg-ok"
                : s.status === "simulated"
                ? "bg-accent"
                : s.status === "degraded" || s.status === "estimated"
                ? "bg-warn"
                : "bg-danger"
            }`}
          />
          <span className="font-bold text-bright w-16">{kind.toUpperCase()}</span>
          <span className="text-dim truncate">{s.detail}</span>
        </li>
      ))}
    </ul>
  );
}

// -------------------------------------------------------------- diagnostics

export function DiagnosticsPanel({ state }: { state: SystemState }) {
  const d = state.diagnostics;
  const rows: [string, string, string][] = [
    ["MODE", state.mode.toUpperCase(), "text-accent"],
    ["DETECTOR", state.detector.toUpperCase(), "text-bright"],
    ["INFERENCE", state.inference?.ms != null ? `${Math.round(state.inference.ms)} ms` : "—",
      "text-bright"],
    ["THERMAL SRC", (state.thermal_source ?? "—").toUpperCase(), "text-bright"],
    ["FPS", d.fps.toFixed(1), d.fps >= 12 ? "text-ok" : "text-warn"],
    ["LATENCY", `${Math.round(d.latency_ms)} ms`,
      d.latency_ms < 80 ? "text-ok" : "text-warn"],
    ["CPU", d.cpu_percent != null ? `${d.cpu_percent}%` : "—", "text-bright"],
    ["MEMORY", d.mem_percent != null ? `${d.mem_percent}%` : "—", "text-bright"],
    ["STORAGE", d.disk_percent != null ? `${d.disk_percent}%` : "—", "text-bright"],
    ["CORE TEMP", d.cpu_temp_c != null ? `${d.cpu_temp_c}°C` : "n/a",
      (d.cpu_temp_c ?? 0) < 75 ? "text-bright" : "text-warn"],
    ["BATTERY", d.battery_percent != null ? `${d.battery_percent}%` : "—",
      (d.battery_percent ?? 100) > 20 ? "text-ok" : "text-danger"],
    ["RUNTIME", d.runtime_min != null ? `~${d.runtime_min} min` : "estimating…",
      "text-bright"],
    ["POWER", (d.power_state ?? "—").toUpperCase(),
      d.power_state === "normal" ? "text-ok" : "text-warn"],
    ["UPTIME", `${Math.floor(d.uptime_s / 60)}m ${d.uptime_s % 60}s`, "text-dim"],
  ];
  return (
    <table className="w-full text-xs">
      <tbody>
        {rows.map(([k, v, cls]) => (
          <tr key={k} className="border-t border-edge/40 first:border-t-0">
            <td className="py-1 text-dim">{k}</td>
            <td className={`text-right font-bold ${cls}`}>{v}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// -------------------------------------------------------------- incidents

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
  return (
    <ul className="text-xs space-y-1">
      {sessions.map((s) => (
        <li key={s.id} className="flex justify-between border-b border-edge/40 pb-1">
          <span className="text-bright font-bold">{s.id}</span>
          <span className="text-dim">
            {s.events} ev · {s.snapshots} snap
          </span>
        </li>
      ))}
      {sessions.length === 0 && <li className="text-dim">No recordings.</li>}
    </ul>
  );
}

// ------------------------------------------------------------- search mode

export function SearchPanel({ state }: { state: SystemState }) {
  const s = state.search;
  if (!s?.active) {
    return (
      <div className="text-xs text-dim">
        Search mode inactive. Say <span className="text-bright">“search room”</span>{" "}
        or use the command bar to begin guided room search.
      </div>
    );
  }
  // Coarse occupancy grid, centered on the entry origin.
  const cells = s.cells ?? [];
  const xs = cells.map((c) => c.x);
  const ys = cells.map((c) => c.y);
  const minX = Math.min(-4, ...xs);
  const maxX = Math.max(4, ...xs);
  const minY = Math.min(-4, ...ys);
  const maxY = Math.max(4, ...ys);
  const cols = maxX - minX + 1;
  const rows = maxY - minY + 1;
  const px = Math.min(10, Math.floor(180 / Math.max(cols, rows)));

  return (
    <div className="flex items-start gap-3">
      <svg width={cols * px} height={rows * px} className="shrink-0">
        {cells.map((c, i) => (
          <rect
            key={i}
            x={(c.x - minX) * px}
            y={(maxY - c.y) * px}
            width={px - 1}
            height={px - 1}
            fill={c.level === 2 ? "#4ade80" : "#facc15"}
            opacity={c.level === 2 ? 0.8 : 0.5}
          />
        ))}
      </svg>
      <div className="text-xs space-y-1">
        <div className="text-ok font-bold">{s.coverage_pct}% EXPLORED</div>
        <div className="text-dim">{s.explored_cells} cells cleared</div>
        <div className="text-warn">{s.needs_pass} cells need another pass</div>
        <div className="text-dim mt-2">
          <span className="inline-block w-2 h-2 bg-ok mr-1" />explored{" "}
          <span className="inline-block w-2 h-2 bg-warn ml-2 mr-1" />partial
        </div>
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

  // Step-by-step playback (Training Mode): advance one event per tick.
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
  const window = useMemo(
    () => events.slice(Math.max(0, idx - 6), idx + 1),
    [events, idx]
  );

  return (
    <div className="text-xs flex flex-col gap-2">
      <div className="flex items-center gap-2 flex-wrap">
        <select
          className="min-h-[36px] px-2 rounded border border-edge bg-ink text-bright"
          value={selected ?? ""}
          onChange={(e) => setSelected(e.target.value)}
        >
          {sessions.map((s) => (
            <option key={s.id} value={s.id}>
              {s.id} ({s.events} ev)
            </option>
          ))}
          {sessions.length === 0 && <option>no recordings</option>}
        </select>
        <button className="btn text-xs" onClick={() => setPlaying((p) => !p)}>
          {playing ? "PAUSE" : "PLAY"}
        </button>
        <button
          className="btn text-xs"
          onClick={() => setIdx((i) => Math.max(0, i - 1))}
        >
          ◂ STEP
        </button>
        <button
          className="btn text-xs"
          onClick={() => setIdx((i) => Math.min(events.length - 1, i + 1))}
        >
          STEP ▸
        </button>
      </div>

      {events.length > 0 && (
        <>
          <input
            type="range"
            min={0}
            max={events.length - 1}
            value={idx}
            onChange={(e) => setIdx(Number(e.target.value))}
            className="w-full accent-accent"
          />
          <div className="text-dim">
            EVENT {idx + 1}/{events.length} · T+
            {cur ? Math.round(cur.ts - t0) : 0}s
          </div>
          <ul className="space-y-0.5">
            {window.map((e, i) => (
              <li
                key={i}
                className={`flex gap-2 ${
                  i === window.length - 1 ? "text-bright" : "text-dim"
                }`}
              >
                <span className={severityColor[e.severity ?? "info"]}>
                  {e.kind.toUpperCase()}
                </span>
                <span className="truncate">
                  {e.text ?? e.display ?? JSON.stringify(e).slice(0, 40)}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
      {events.length === 0 && (
        <div className="text-dim">
          No recorded mission selected. Recordings appear here after a session.
        </div>
      )}
    </div>
  );
}
