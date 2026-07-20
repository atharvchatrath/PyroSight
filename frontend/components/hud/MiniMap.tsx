"use client";

// Top-right navigation tracker ("GPS panel"): a north-up mini-map plotting
// where the firefighter has been (breadcrumb trail), where they are now
// (position + heading wedge), the entry point, and where they're going
// (target bearing ray). Position comes from the positioning stack — SITL
// truth in sim, pedestrian dead reckoning on the helmet, UWB when fitted.

import { NavState, SystemState } from "@/lib/types";

const SIZE = 148;
const STATUS_COLOR: Record<NavState["status"], string> = {
  CLEAR: "#4ade80",
  CAUTION: "#fbbf24",
  BLOCKED: "#f87171",
};

export default function MiniMap({ state }: { state: SystemState }) {
  const nav = state.nav;
  const bc = nav.breadcrumbs;
  const heading = state.heading.deg;
  const pos = bc.position;
  const trail = bc.trail ?? [];
  const entry = bc.entry;

  // Fit all points (position, trail, entry) with padding; ≥12 m window.
  const pts: [number, number][] = [...trail];
  if (pos) pts.push(pos);
  if (entry) pts.push(entry);
  const cx = pos ? pos[0] : 0;
  const cy = pos ? pos[1] : 0;
  let span = 12;
  for (const [x, y] of pts) {
    span = Math.max(span, Math.abs(x - cx) * 2.4, Math.abs(y - cy) * 2.4);
  }
  const scale = (SIZE - 24) / span;
  const toPx = (x: number, y: number): [number, number] => [
    SIZE / 2 + (x - cx) * scale,
    SIZE / 2 - (y - cy) * scale,
  ];

  const trailPath = trail
    .map(([x, y], i) => {
      const [px, py] = toPx(x, y);
      return `${i === 0 ? "M" : "L"} ${px.toFixed(1)} ${py.toFixed(1)}`;
    })
    .join(" ");

  // Target ray: absolute bearing = heading + relative bearing.
  let ray: string | null = null;
  if (nav.target) {
    const abs = ((heading + nav.target.rel_bearing_deg) * Math.PI) / 180;
    const len = SIZE / 2 - 10;
    ray = `M ${SIZE / 2} ${SIZE / 2} l ${Math.sin(abs) * len} ${-Math.cos(abs) * len}`;
  }

  const headRad = (heading * Math.PI) / 180;
  const wedge = (() => {
    const [px, py] = [SIZE / 2, SIZE / 2];
    const p = (r: number, a: number) =>
      `${px + Math.sin(headRad + a) * r},${py - Math.cos(headRad + a) * r}`;
    return `${p(9, 0)} ${p(6, 2.5)} ${p(2.5, Math.PI)} ${p(6, -2.5)}`;
  })();

  return (
    <div className="rounded border border-edge bg-ink/70 backdrop-blur-[2px] p-1">
      <svg width={SIZE} height={SIZE}>
        {/* range rings + north */}
        <circle cx={SIZE / 2} cy={SIZE / 2} r={SIZE / 2 - 10} fill="none"
          stroke="#1d2833" strokeWidth="1" />
        <circle cx={SIZE / 2} cy={SIZE / 2} r={(SIZE / 2 - 10) / 2} fill="none"
          stroke="#1d2833" strokeWidth="1" />
        <text x={SIZE / 2} y={11} textAnchor="middle" fontSize="9"
          fill="#8b9bab" fontFamily="ui-monospace, monospace">N</text>

        {/* breadcrumb trail */}
        {trailPath && (
          <path d={trailPath} fill="none" stroke="#22d3ee" strokeWidth="1.5"
            strokeOpacity="0.65" strokeDasharray="3 2" />
        )}

        {/* entry point */}
        {entry && (() => {
          const [ex, ey] = toPx(entry[0], entry[1]);
          return (
            <g>
              <rect x={ex - 4} y={ey - 4} width="8" height="8" fill="none"
                stroke="#4ade80" strokeWidth="1.5" />
              <text x={ex} y={ey + 14} textAnchor="middle" fontSize="8"
                fill="#4ade80" fontFamily="ui-monospace, monospace">ENT</text>
            </g>
          );
        })()}

        {/* target bearing ray */}
        {ray && (
          <path d={ray} stroke={STATUS_COLOR[nav.status]} strokeWidth="1.5"
            strokeDasharray="4 3" strokeOpacity="0.9" />
        )}

        {/* current position + heading wedge */}
        <polygon points={wedge} fill="#22d3ee" stroke="#04070a" strokeWidth="0.8" />
      </svg>
      <div className="flex justify-between px-1 text-[9px] text-dim font-mono">
        <span>{pos ? `${pos[0].toFixed(0)},${pos[1].toFixed(0)}m` : "NO FIX"}</span>
        <span>{bc.count} CRUMBS</span>
        <span>
          {nav.entry_distance_ft != null ? `ENT ${nav.entry_distance_ft}FT` : ""}
        </span>
      </div>
    </div>
  );
}
