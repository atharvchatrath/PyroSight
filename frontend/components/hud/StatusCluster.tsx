"use client";

// Top-left HUD cluster: system health, battery, sensor status.
// Icons + short codes only — readable at a glance through a monocular lens.

import { SystemState } from "@/lib/types";

const SENSOR_CODE: Record<string, string> = {
  rgb: "CAM",
  thermal: "THM",
  imu: "IMU",
};

function statusColor(status: string): string {
  if (status === "ok" || status === "simulated") return "text-ok";
  if (status === "degraded" || status === "estimated") return "text-warn";
  return "text-danger";
}

export default function StatusCluster({ state }: { state: SystemState }) {
  const d = state.diagnostics;
  const battery = d.battery_percent;
  const batteryColor =
    battery == null
      ? "text-dim"
      : battery > 40
      ? "text-ok"
      : battery > 20
      ? "text-warn"
      : "text-danger animate-alarm";

  return (
    <div className="flex flex-col gap-1 text-[15px] leading-tight">
      <div className="flex items-baseline gap-2">
        <span className="text-accent font-bold tracking-widest">PYROSIGHT</span>
        <span className="text-dim text-xs">{state.mode.toUpperCase()}</span>
      </div>
      <div className="flex gap-3">
        <span className={batteryColor}>
          BAT {battery != null ? `${Math.round(battery)}%` : "—"}
          {d.runtime_min != null && (
            <span className="text-dim text-xs ml-1">~{d.runtime_min}m</span>
          )}
        </span>
        <span className={state.fps >= 12 ? "text-ok" : "text-warn"}>
          {state.fps.toFixed(0)} FPS
        </span>
      </div>
      {d.power_state === "saver" && (
        <div className="text-warn text-xs">⚡ POWER SAVER</div>
      )}
      <div className="flex gap-3">
        {Object.entries(d.sensors).map(([kind, s]) => (
          <span key={kind} className={statusColor(s.status)}>
            {SENSOR_CODE[kind] ?? kind.toUpperCase()}
            {s.status === "simulated" ? "*" : ""}
          </span>
        ))}
      </div>
      <div className="text-dim text-xs">
        VIS {state.smoke.visibility} · SMK {Math.round(state.smoke.density * 100)}%
      </div>
    </div>
  );
}
