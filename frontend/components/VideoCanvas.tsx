"use client";

// Live video surface + SVG detection overlay. The SVG shares the frame's
// pixel coordinate system via viewBox, so boxes track the video perfectly
// at any display size.

import { useVideoFeed } from "@/lib/useVideoFeed";
import { SystemState, Track } from "@/lib/types";

// Deuteranopia-safe palette (avoids red/green confusion) keyed by category —
// used when the colorblind pref is on. Blue/orange/yellow are distinguishable
// across the common CVD types.
const CB_PALETTE: Record<string, string> = {
  person: "#4da3ff", // blue
  egress: "#ffd60a", // yellow
  hazard: "#ff7b00", // orange
  structure: "#c0c0c0",
};

function trackColor(t: Track, colorblind: boolean): string {
  if (colorblind) return CB_PALETTE[t.category] ?? t.color;
  return t.color;
}

function bracketPath(x1: number, y1: number, x2: number, y2: number): string {
  const arm = Math.max(6, Math.min(x2 - x1, y2 - y1) * 0.25);
  return [
    `M ${x1} ${y1 + arm} L ${x1} ${y1} L ${x1 + arm} ${y1}`,
    `M ${x2 - arm} ${y1} L ${x2} ${y1} L ${x2} ${y1 + arm}`,
    `M ${x2} ${y2 - arm} L ${x2} ${y2} L ${x2 - arm} ${y2}`,
    `M ${x1 + arm} ${y2} L ${x1} ${y2} L ${x1} ${y2 - arm}`,
  ].join(" ");
}

function TrackBox({
  t,
  highlight,
  showLabels,
  colorblind,
}: {
  t: Track;
  highlight: boolean;
  showLabels: boolean;
  colorblind: boolean;
}) {
  const [x1, y1, x2, y2] = t.box;
  const possible = t.tier === "possible";
  const stroke = trackColor(t, colorblind);
  const label = `${t.display} ${Math.round(t.conf * 100)}%`;
  const sub = [
    t.dist_ft != null ? `${Math.round(t.dist_ft)} FT` : null,
    t.max_temp_c != null ? `${Math.round(t.max_temp_c)}°C` : null,
    t.thermal_confirmed ? "THERM✓" : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <g opacity={t.coasting ? 0.55 : 1}>
      <path
        d={bracketPath(x1, y1, x2, y2)}
        stroke={stroke}
        strokeWidth={highlight ? 4 : 2.5}
        strokeDasharray={possible ? "6 5" : undefined}
        fill="none"
      />
      {!showLabels && null}
      {showLabels && (
      <>
      <rect
        x={x1}
        y={Math.max(0, y1 - 20)}
        width={label.length * 8.4 + 8}
        height={18}
        fill={possible ? "#111827" : stroke}
        opacity={0.92}
      />
      <text
        x={x1 + 4}
        y={Math.max(12, y1 - 6)}
        fontSize={13}
        fontFamily="ui-monospace, Menlo, monospace"
        fontWeight={700}
        fill={possible ? stroke : "#04070a"}
      >
        {label}
      </text>
      {sub && (
        <text
          x={x1 + 2}
          y={y2 + 16}
          fontSize={12}
          fontFamily="ui-monospace, Menlo, monospace"
          fill={stroke}
        >
          {sub}
        </text>
      )}
      </>
      )}
    </g>
  );
}

export default function VideoCanvas({
  feed,
  state,
  showOverlay = true,
  className = "",
}: {
  feed: "rgb" | "thermal" | "fused";
  state: SystemState | null;
  showOverlay?: boolean;
  className?: string;
}) {
  const src = useVideoFeed(feed);
  const fw = state?.frame.w ?? 640;
  const fh = state?.frame.h ?? 480;
  const highlightDoors = state?.prefs.highlight_doors ?? false;
  const showLabels = state?.prefs.show_labels ?? true;
  const colorblind = state?.prefs.colorblind ?? false;
  const emergency = state?.emergency ?? false;
  // Emergency mode reduces clutter: only people, egress, and hazards remain.
  const visibleTracks =
    state && emergency
      ? state.tracks.filter((t) => t.category !== "structure")
      : state?.tracks ?? [];

  return (
    <div
      className={`relative bg-black overflow-hidden ${className}`}
      style={{ aspectRatio: `${fw} / ${fh}` }}
    >
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={src}
          alt={`${feed} live feed`}
          className="absolute inset-0 w-full h-full"
          draggable={false}
        />
      ) : (
        <div className="absolute inset-0 flex items-center justify-center text-dim text-sm tracking-widest">
          AWAITING {feed.toUpperCase()} FEED…
        </div>
      )}
      {showOverlay && state && (
        <svg
          viewBox={`0 0 ${fw} ${fh}`}
          preserveAspectRatio="none"
          className="absolute inset-0 w-full h-full pointer-events-none"
        >
          {visibleTracks.map((t) => (
            <TrackBox
              key={t.id}
              t={t}
              highlight={
                (highlightDoors || emergency) &&
                (t.cls === "door" || t.cls === "exit_sign")
              }
              showLabels={showLabels}
              colorblind={colorblind}
            />
          ))}
        </svg>
      )}
    </div>
  );
}
