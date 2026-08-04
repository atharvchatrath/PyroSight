"use client";

// Tactical mini-map — north-up, small, and deliberately quiet.
//
// It answers "where am I, where have I been, what's around me" and nothing
// else. Detections are placed by projecting each track's horizontal position
// through the camera FOV at its ranged distance; that is an estimate, so the
// map draws them as soft marks rather than precise pins, and the map never
// grows large enough to compete with the real world for attention.

import { NavState, SystemState } from "@/lib/types";
import { COLOR, colorOf, isSuppressed, roleOf } from "@/lib/design";
import { useSmoothAngle } from "@/lib/useSmoothValue";

const HFOV_DEG = 70; // Pi Camera Module 3 wide-ish horizontal field of view
const FT_PER_M = 3.28084;

const STATUS_COLOR: Record<NavState["status"], string> = {
  CLEAR: COLOR.nav,
  CAUTION: COLOR.warn,
  BLOCKED: COLOR.critical,
};

export default function MiniMap({
  state,
  size = 150,
  showDetections = true,
}: {
  state: SystemState;
  size?: number;
  showDetections?: boolean;
}) {
  const nav = state.nav;
  const bc = nav.breadcrumbs;
  const heading = useSmoothAngle(state.heading.deg, 1.2, 0.02);
  const pos = bc.position;
  const trail = bc.trail ?? [];
  const entry = bc.entry;
  const R = size / 2 - 9;

  // Window: fit trail + entry, minimum 12 m across.
  const cx0 = pos ? pos[0] : 0;
  const cy0 = pos ? pos[1] : 0;
  let span = 12;
  const pts: [number, number][] = [...trail];
  if (pos) pts.push(pos);
  if (entry) pts.push(entry);
  for (const [x, y] of pts) {
    span = Math.max(span, Math.abs(x - cx0) * 2.4, Math.abs(y - cy0) * 2.4);
  }
  const scale = (size - 26) / span;
  const toPx = (x: number, y: number): [number, number] => [
    size / 2 + (x - cx0) * scale,
    size / 2 - (y - cy0) * scale,
  ];

  const trailPath = trail
    .map(([x, y], i) => {
      const [px, py] = toPx(x, y);
      return `${i === 0 ? "M" : "L"} ${px.toFixed(1)} ${py.toFixed(1)}`;
    })
    .join(" ");

  // Detections projected into map space (estimate — see header note).
  const marks = showDetections
    ? state.tracks
        .filter((t) => t.dist_ft != null && t.conf >= 0.45 && !isSuppressed(t))
        .map((t) => {
          const cxFrac = (t.box[0] + t.box[2]) / 2 / (state.frame.w || 640);
          const bearing = heading + (cxFrac - 0.5) * HFOV_DEG;
          const rangeM = (t.dist_ft as number) / FT_PER_M;
          const a = (bearing * Math.PI) / 180;
          const x = size / 2 + Math.sin(a) * rangeM * scale;
          const y = size / 2 - Math.cos(a) * rangeM * scale;
          return { id: t.id, x, y, color: colorOf(roleOf(t)), r: t.category === "hazard" ? 4.5 : 3.5 };
        })
        .filter((m) => Math.hypot(m.x - size / 2, m.y - size / 2) < R - 2)
    : [];

  // Coverage cells, drawn faintly beneath everything else.
  const cells = state.search?.cells ?? [];
  const cellM = state.search?.cell_m ?? 1.5;

  let ray: string | null = null;
  if (nav.target) {
    const abs = ((heading + nav.target.rel_bearing_deg) * Math.PI) / 180;
    ray = `M ${size / 2} ${size / 2} l ${Math.sin(abs) * R} ${-Math.cos(abs) * R}`;
  }

  const headRad = (heading * Math.PI) / 180;
  const wedge = (() => {
    const p = (r: number, a: number) =>
      `${size / 2 + Math.sin(headRad + a) * r},${size / 2 - Math.cos(headRad + a) * r}`;
    return `${p(10, 0)} ${p(6.5, 2.4)} ${p(2.5, Math.PI)} ${p(6.5, -2.4)}`;
  })();

  return (
    <div className="panel-float p-1.5" style={{ fontFamily: "var(--font-sans)" }}>
      <svg width={size} height={size}>
        <defs>
          <radialGradient id="ps-map-fade">
            <stop offset="60%" stopColor="#22d3ee" stopOpacity="0.05" />
            <stop offset="100%" stopColor="#22d3ee" stopOpacity="0" />
          </radialGradient>
        </defs>
        <circle cx={size / 2} cy={size / 2} r={R} fill="url(#ps-map-fade)" />

        {/* search coverage */}
        {cells.map((c, i) => {
          const [x, y] = toPx(c.x * cellM, c.y * cellM);
          const s = Math.max(2, cellM * scale);
          return (
            <rect
              key={i}
              x={x - s / 2}
              y={y - s / 2}
              width={s}
              height={s}
              fill={c.level === 2 ? COLOR.victim : COLOR.warn}
              opacity={c.level === 2 ? 0.14 : 0.09}
            />
          );
        })}

        {/* range rings */}
        <circle cx={size / 2} cy={size / 2} r={R} fill="none" stroke="rgba(150,180,210,0.18)" />
        <circle cx={size / 2} cy={size / 2} r={R / 2} fill="none" stroke="rgba(150,180,210,0.12)" />
        <text x={size / 2} y={11} textAnchor="middle" fontSize="9" fontWeight={600}
          letterSpacing="0.1em" fill="#8b9bab">
          N
        </text>

        {trailPath && (
          <path d={trailPath} fill="none" stroke={COLOR.nav} strokeWidth="1.6"
            strokeOpacity="0.55" strokeLinecap="round" strokeLinejoin="round" />
        )}

        {entry &&
          (() => {
            const [ex, ey] = toPx(entry[0], entry[1]);
            return (
              <g>
                <rect x={ex - 4} y={ey - 4} width="8" height="8" rx="1.5" fill="none"
                  stroke={COLOR.victim} strokeWidth="1.5" />
                <text x={ex} y={ey + 14} textAnchor="middle" fontSize="8"
                  letterSpacing="0.1em" fill={COLOR.victim}>
                  ENT
                </text>
              </g>
            );
          })()}

        {ray && (
          <path d={ray} stroke={STATUS_COLOR[nav.status]} strokeWidth="1.4"
            strokeDasharray="5 4" strokeOpacity="0.8" />
        )}

        {marks.map((m) => (
          <g key={m.id}>
            <circle cx={m.x} cy={m.y} r={m.r + 3} fill={m.color} opacity={0.16} />
            <circle cx={m.x} cy={m.y} r={m.r} fill={m.color} opacity={0.85} />
          </g>
        ))}

        <polygon points={wedge} fill={COLOR.nav} stroke="#04070a" strokeWidth="0.8" />
      </svg>
      {/* Explicit separators, not just flex spacing: at 150 px the three
          fields sat shoulder to shoulder and read as one run-on string
          ("0,19M29 CRUMBSENT 124FT"). */}
      <div className="flex items-center justify-center gap-1.5 px-1 pt-1
        text-[9px] text-dim num tracking-hud whitespace-nowrap">
        <span>{pos ? `${pos[0].toFixed(0)}, ${pos[1].toFixed(0)} M` : "NO FIX"}</span>
        <span className="opacity-40">·</span>
        <span>{bc.count} CRUMBS</span>
        {nav.entry_distance_ft != null && (
          <>
            <span className="opacity-40">·</span>
            <span>ENT {nav.entry_distance_ft} FT</span>
          </>
        )}
      </div>
    </div>
  );
}
