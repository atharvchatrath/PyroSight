"use client";

// Top-right HUD cluster: rolling compass tape + mission timer.

import { SystemState } from "@/lib/types";
import { missionClock } from "@/lib/format";

const MARKS = [
  { deg: 0, label: "N" },
  { deg: 45, label: "NE" },
  { deg: 90, label: "E" },
  { deg: 135, label: "SE" },
  { deg: 180, label: "S" },
  { deg: 225, label: "SW" },
  { deg: 270, label: "W" },
  { deg: 315, label: "NW" },
];

export default function CompassStrip({ state }: { state: SystemState }) {
  const heading = state.heading.deg;
  const halfWindow = 60; // degrees visible on each side
  const width = 220;

  const ticks: { x: number; label: string }[] = [];
  for (const m of MARKS) {
    let delta = ((m.deg - heading + 540) % 360) - 180;
    if (Math.abs(delta) <= halfWindow) {
      ticks.push({ x: width / 2 + (delta / halfWindow) * (width / 2), label: m.label });
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <div className="text-[17px] font-bold text-bright tracking-wider">
        {missionClock(state.mission_time_s)}
      </div>
      <div
        className="relative h-9 border border-edge bg-panel/80 rounded overflow-hidden"
        style={{ width }}
      >
        {ticks.map((t) => (
          <span
            key={t.label}
            className="absolute top-1 text-xs text-dim -translate-x-1/2"
            style={{ left: t.x }}
          >
            {t.label}
          </span>
        ))}
        {/* center lubber line + numeric heading */}
        <div className="absolute left-1/2 top-0 bottom-0 w-px bg-accent" />
        <div className="absolute left-1/2 bottom-0 -translate-x-1/2 text-[13px] font-bold text-accent">
          {String(Math.round(heading)).padStart(3, "0")}°{state.heading.cardinal}
        </div>
      </div>
    </div>
  );
}
