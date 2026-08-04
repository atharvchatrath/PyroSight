"use client";

// Navigation ribbon — the single most important graphic on the display.
//
// A floating arrow tells you a direction; a ribbon tells you a *path*. It
// leaves the firefighter's feet, curves toward the target, narrows and fades
// into the distance, and carries the turn before the turn arrives. Because it
// is anchored at the bottom centre it maps onto the real floor, so following
// it costs no interpretation at all.
//
// Everything here is smoothed at 60 Hz (lib/useSmoothValue): the bearing this
// ribbon draws comes from a heading filter and a target bearing that both
// jitter by a couple of degrees. Unsmoothed, the path would writhe.

import { NavState, SystemState } from "@/lib/types";
import { COLOR, bearingText } from "@/lib/design";
import { useSmoothAngle, useSmoothNumber } from "@/lib/useSmoothValue";
import { clamp } from "@/lib/smoothing";

const W = 420;
const H = 300;
const BASE = { x: W / 2, y: H - 8 };

const STATUS_COLOR: Record<NavState["status"], string> = {
  CLEAR: COLOR.nav,
  CAUTION: COLOR.warn,
  BLOCKED: COLOR.critical,
};

function bezier(t: number, p: [number, number][]): [number, number] {
  const [p0, p1, p2, p3] = p;
  const u = 1 - t;
  const a = u * u * u;
  const b = 3 * u * u * t;
  const c = 3 * u * t * t;
  const d = t * t * t;
  return [
    a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
    a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1],
  ];
}

export default function NavRibbon({
  state,
  compact = false,
}: {
  state: SystemState;
  compact?: boolean;
}) {
  const nav = state.nav;
  const target = nav.target;
  // Hooks must run unconditionally — smooth first, decide after.
  const relRaw = target?.rel_bearing_deg ?? 0;
  const rel = useSmoothAngle(relRaw, 1.1, 0.02);
  const dist = useSmoothNumber(target?.dist_ft ?? null, 0.25);

  if (!target) return null;

  const color = STATUS_COLOR[nav.status];
  const uturn = Math.abs(rel) >= 150;
  const offscreen = !uturn && Math.abs(rel) > 62;
  // On-screen bend is compressed: 60° of real bearing maps to the frame edge,
  // so the ribbon stays inside the eyebox instead of sliding out of view.
  const bend = clamp(rel, -62, 62) / 62;
  const endX = BASE.x + bend * (W * 0.42);
  const endY = 54;

  const curve: [number, number][] = [
    [BASE.x, BASE.y],
    [BASE.x, BASE.y - 90],
    [BASE.x + bend * (W * 0.3), endY + 70],
    [endX, endY],
  ];

  const SEG = 22;
  const bands: { d: string; op: number }[] = [];
  for (let i = 0; i < SEG; i++) {
    const t0 = i / SEG;
    const t1 = (i + 1) / SEG;
    const [x0, y0] = bezier(t0, curve);
    const [x1, y1] = bezier(t1, curve);
    const hw0 = 52 * Math.pow(1 - t0, 1.45) + 3;
    const hw1 = 52 * Math.pow(1 - t1, 1.45) + 3;
    // Perspective ribbon: widen perpendicular to the local tangent.
    const ang = Math.atan2(y1 - y0, x1 - x0) + Math.PI / 2;
    const dx = Math.cos(ang);
    const dy = Math.sin(ang);
    bands.push({
      d:
        `M ${x0 + dx * hw0} ${y0 + dy * hw0} L ${x1 + dx * hw1} ${y1 + dy * hw1} ` +
        `L ${x1 - dx * hw1} ${y1 - dy * hw1} L ${x0 - dx * hw0} ${y0 - dy * hw0} Z`,
      op: 0.3 * Math.pow(1 - t0, 1.5) + 0.04,
    });
  }

  // Chevrons ride the same curve: motion cue without animating the ribbon.
  const rungs = [0.18, 0.34, 0.5, 0.66, 0.8].map((t, i) => {
    const [x, y] = bezier(t, curve);
    const [xn, yn] = bezier(Math.min(1, t + 0.02), curve);
    const a = (Math.atan2(yn - y, xn - x) * 180) / Math.PI + 90;
    const s = (1 - t) * 0.85 + 0.25;
    return { x, y, a, s, op: (1 - t) * 0.75 + 0.15, i };
  });

  const turn = bearingText(rel);
  const stairsOnRoute = state.tracks.some((t) => t.cls === "stairs" && t.conf >= 0.5);

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="w-full h-full pointer-events-none overflow-visible"
      style={{ fontFamily: "var(--font-sans)" }}
    >
      <defs>
        <filter id="ps-ribbon-glow" x="-40%" y="-40%" width="180%" height="180%">
          <feGaussianBlur stdDeviation="6" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        <linearGradient id="ps-ribbon-edge" x1="0" y1="1" x2="0" y2="0">
          <stop offset="0%" stopColor={color} stopOpacity="0.95" />
          <stop offset="70%" stopColor={color} stopOpacity="0.35" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>

      {uturn ? (
        // Behind you. A rotated arrow reads as "walk into the floor", so the
        // turnaround gets its own unambiguous glyph.
        <g
          transform={`translate(${BASE.x} ${H - 120})`}
          stroke={color}
          fill="none"
          strokeWidth={9}
          strokeLinecap="round"
          filter="url(#ps-ribbon-glow)"
        >
          <path d="M -34 62 L -34 -6 A 34 34 0 0 1 34 -6 L 34 26" />
          <path d="M 14 8 L 34 34 L 54 8" />
        </g>
      ) : (
        <>
          {bands.map((b, i) => (
            <path key={i} d={b.d} fill={color} fillOpacity={b.op} />
          ))}
          {/* rails */}
          <path
            d={`M ${BASE.x - 52} ${BASE.y} ${bands
              .map((_, i) => {
                const t = (i + 1) / SEG;
                const [x, y] = bezier(t, curve);
                const hw = 52 * Math.pow(1 - t, 1.45) + 3;
                const [xp, yp] = bezier(Math.max(0, t - 0.02), curve);
                const ang = Math.atan2(y - yp, x - xp) + Math.PI / 2;
                return `L ${x - Math.cos(ang) * hw} ${y - Math.sin(ang) * hw}`;
              })
              .join(" ")}`}
            fill="none"
            stroke="url(#ps-ribbon-edge)"
            strokeWidth={2}
          />
          <path
            d={`M ${BASE.x + 52} ${BASE.y} ${bands
              .map((_, i) => {
                const t = (i + 1) / SEG;
                const [x, y] = bezier(t, curve);
                const hw = 52 * Math.pow(1 - t, 1.45) + 3;
                const [xp, yp] = bezier(Math.max(0, t - 0.02), curve);
                const ang = Math.atan2(y - yp, x - xp) + Math.PI / 2;
                return `L ${x + Math.cos(ang) * hw} ${y + Math.sin(ang) * hw}`;
              })
              .join(" ")}`}
            fill="none"
            stroke="url(#ps-ribbon-edge)"
            strokeWidth={2}
          />
          {rungs.map((r) => (
            <path
              key={r.i}
              d="M -16 6 L 0 -8 L 16 6"
              fill="none"
              stroke={color}
              strokeWidth={4}
              strokeLinecap="round"
              strokeLinejoin="round"
              opacity={r.op}
              transform={`translate(${r.x} ${r.y}) rotate(${r.a}) scale(${r.s})`}
            />
          ))}
        </>
      )}

      {/* Off-screen target: an edge marker rather than a lie about where it is */}
      {offscreen && (
        <g
          transform={`translate(${rel > 0 ? W - 26 : 26} ${H / 2}) rotate(${rel > 0 ? 90 : -90})`}
          filter="url(#ps-ribbon-glow)"
        >
          <path d="M -14 10 L 0 -12 L 14 10 Z" fill={color} />
        </g>
      )}

      {/* Distance + turn call-out, at the far end of the path */}
      {!compact && (
        <g transform={`translate(${clamp(endX, 70, W - 70)} ${endY - 26})`}>
          <rect x={-64} y={-19} width={128} height={30}
            fill="#050a10" fillOpacity={0.7} stroke={color} strokeOpacity={0.6} />
          <text x={0} y={2} textAnchor="middle" fontSize={16} fontWeight={700}
            letterSpacing="0.1em" fill={color}>
            {dist != null ? `${Math.round(dist)} FT` : turn}
          </text>
          <text x={0} y={26} textAnchor="middle" fontSize={10.5}
            letterSpacing="0.16em" fill="#8b9bab">
            {[
              turn !== "AHEAD" ? `BEAR ${turn}` : "STRAIGHT AHEAD",
              target.source === "memory" ? "LAST KNOWN" : null,
              target.source === "breadcrumbs" ? "BY TRAIL" : null,
              stairsOnRoute ? "STAIRS ON ROUTE" : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </text>
        </g>
      )}
    </svg>
  );
}
