"use client";

// Command-dashboard panels. Each is a small, self-contained card; the grid
// in app/dashboard/page.tsx composes them.

import { useEffect, useState } from "react";
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
    ["MEM", d.mem_percent != null ? `${d.mem_percent}%` : "—", "text-bright"],
    ["CORE TEMP", d.cpu_temp_c != null ? `${d.cpu_temp_c}°C` : "n/a", "text-bright"],
    ["BATTERY", d.battery_percent != null ? `${d.battery_percent}%` : "—",
      (d.battery_percent ?? 100) > 20 ? "text-ok" : "text-danger"],
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
