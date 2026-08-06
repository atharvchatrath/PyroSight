"use client";

// Compass tape. Cardinal letters, 15° ticks, a lubber line, and — the part
// that matters — a pip showing where the current objective sits relative to
// where the firefighter is looking. Turning until the pip meets the line is a
// motor task, not a reading task.

import { SystemState } from "@/lib/types";
import { COLOR } from "@/lib/design";
import { useSmoothAngle } from "@/lib/useSmoothValue";
import { angleDelta } from "@/lib/smoothing";

const CARDINALS = [
  { deg: 0, label: "N" },
  { deg: 45, label: "NE" },
  { deg: 90, label: "E" },
  { deg: 135, label: "SE" },
  { deg: 180, label: "S" },
  { deg: 225, label: "SW" },
  { deg: 270, label: "W" },
  { deg: 315, label: "NW" },
];

export default function CompassStrip({
  state,
  width = 300,
  half = 55,
}: {
  state: SystemState;
  width?: number;
  half?: number;
}) {
  const heading = useSmoothAngle(state.heading.deg, 1.2, 0.02);
  const H = 34;
  const xFor = (deg: number) => width / 2 + (angleDelta(deg, heading) / half) * (width / 2);

  const ticks: { x: number; major: boolean }[] = [];
  for (let d = 0; d < 360; d += 15) {
    const delta = angleDelta(d, heading);
    if (Math.abs(delta) <= half) {
      ticks.push({ x: xFor(d), major: d % 45 === 0 });
    }
  }

  const target = state.nav.target;
  const targetX =
    target != null ? width / 2 + (angleDelta(target.rel_bearing_deg, 0) / half) * (width / 2) : null;
  const targetVisible = targetX != null && Math.abs(target!.rel_bearing_deg) <= half;

  return (
    <svg width={width} height={H} style={{ fontFamily: "var(--font-sans)" }}>
      {ticks.map((t, i) => (
        <line
          key={i}
          x1={t.x}
          x2={t.x}
          y1={t.major ? 16 : 20}
          y2={26}
          stroke="#a8815e"
          strokeOpacity={t.major ? 0.75 : 0.35}
          strokeWidth={1}
        />
      ))}
      {CARDINALS.filter((c) => Math.abs(angleDelta(c.deg, heading)) <= half).map((c) => (
        <text
          key={c.label}
          x={xFor(c.deg)}
          y={12}
          textAnchor="middle"
          fontSize={11}
          fontWeight={600}
          letterSpacing="0.1em"
          fill={c.label === "N" ? COLOR.system : "#a8815e"}
        >
          {c.label}
        </text>
      ))}

      {/* objective pip */}
      {targetVisible && (
        <g transform={`translate(${targetX} 0)`}>
          <path d="M -5 30 L 0 22 L 5 30 Z" fill={COLOR.nav} />
        </g>
      )}

      {/* lubber line */}
      <line x1={width / 2} x2={width / 2} y1={4} y2={30} stroke={COLOR.nav} strokeWidth={1.5} />
      <rect x={width / 2 - 26} y={-1} width={52} height={15} rx={7} fill="#0d0704" fillOpacity={0.75} />
      <text
        x={width / 2}
        y={10}
        textAnchor="middle"
        fontSize={11}
        fontWeight={700}
        letterSpacing="0.08em"
        fill={COLOR.nav}
      >
        {`${String(Math.round((heading + 360) % 360)).padStart(3, "0")}°`}
      </text>
    </svg>
  );
}
