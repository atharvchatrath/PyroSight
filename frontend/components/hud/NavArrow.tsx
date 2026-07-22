"use client";

// Central navigation cue: one big chevron rotated to the target's relative
// bearing. Behind you (>150°) becomes an explicit U-turn glyph — a rotated
// arrow pointing "down" reads as "go backward through the floor", which is
// exactly the ambiguity a stressed operator can't afford.

import { NavState } from "@/lib/types";

const STATUS_COLOR: Record<NavState["status"], string> = {
  CLEAR: "#4ade80",
  CAUTION: "#fbbf24",
  BLOCKED: "#f87171",
};

export default function NavArrow({ nav, big = false }: { nav: NavState; big?: boolean }) {
  const target = nav.target;
  if (!target) return null;
  const color = STATUS_COLOR[nav.status];
  const rel = target.rel_bearing_deg;
  const uturn = Math.abs(rel) >= 150;
  const dim = big ? 150 : 110;

  return (
    <div className="flex flex-col items-center gap-1 pointer-events-none">
      <svg width={dim} height={dim} viewBox="-55 -55 110 110">
        {uturn ? (
          <g stroke={color} strokeWidth="9" fill="none" strokeLinecap="round">
            <path d="M -18 30 L -18 -8 A 18 18 0 0 1 18 -8 L 18 6" />
            <path d="M 4 -6 L 18 10 L 32 -6" fill="none" />
          </g>
        ) : (
          <g transform={`rotate(${rel})`}>
            <path
              d="M 0 -40 L 26 18 L 0 4 L -26 18 Z"
              fill={color}
              stroke="#04070a"
              strokeWidth="3"
            />
          </g>
        )}
      </svg>
      <div
        className="text-[15px] font-bold tracking-wider px-2 py-0.5 rounded bg-ink/70"
        style={{ color }}
      >
        {target.dist_ft != null ? `${Math.round(target.dist_ft)} FT` : ""}
        {target.source === "memory" ? " (LAST SEEN)" : ""}
      </div>
    </div>
  );
}
