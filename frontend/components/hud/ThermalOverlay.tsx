"use client";

// Thermal layer drawn over the visible feed.
//
// Hotspots arrive in thermal-sensor pixels (160×120 on a Lepton 3.5) and are
// mapped into RGB frame coordinates here. The overlay is deliberately thin:
// contours and a glow, never a filled mask — the firefighter must keep seeing
// the room through it. Anything hot enough to matter also gets a temperature
// and a trend, because "how fast is it climbing" drives the go/no-go call.

import { useEffect, useRef } from "react";
import { Hotspot, SystemState } from "@/lib/types";
import { COLOR } from "@/lib/design";

const SEVERITY_COLOR: Record<Hotspot["severity"], string> = {
  elevated: COLOR.warn,
  severe: COLOR.heat,
  critical: COLOR.critical,
};

/** °C/min slope of the scene maximum, from a short rolling window. */
export function useHeatTrend(state: SystemState | null): number | null {
  const hist = useRef<{ t: number; c: number }[]>([]);
  const max = state?.thermal?.max_c ?? null;

  useEffect(() => {
    if (max == null) return;
    const now = performance.now() / 1000;
    hist.current.push({ t: now, c: max });
    hist.current = hist.current.filter((s) => now - s.t <= 20);
  }, [max]);

  const h = hist.current;
  if (h.length < 6) return null;
  const first = h[0];
  const last = h[h.length - 1];
  const dt = last.t - first.t;
  if (dt < 4) return null;
  return ((last.c - first.c) / dt) * 60;
}

export default function ThermalOverlay({
  state,
  opacity = 0.9,
  showLabels = true,
}: {
  state: SystemState;
  opacity?: number;
  showLabels?: boolean;
}) {
  const fw = state.frame.w;
  const fh = state.frame.h;
  const tw = state.thermal_frame?.w || fw;
  const th = state.thermal_frame?.h || fh;
  const sx = fw / tw;
  const sy = fh / th;
  const estimated = state.thermal_source === "rgb-estimate";

  if (!state.hotspots?.length) return null;

  return (
    <svg
      viewBox={`0 0 ${fw} ${fh}`}
      preserveAspectRatio="none"
      className="absolute inset-0 w-full h-full pointer-events-none"
      style={{ opacity, fontFamily: "var(--font-sans)" }}
    >
      <defs>
        <filter id="ps-heat" x="-70%" y="-70%" width="240%" height="240%">
          <feGaussianBlur stdDeviation="9" />
        </filter>
      </defs>

      {state.hotspots.map((h, i) => {
        const x1 = h.box[0] * sx;
        const y1 = h.box[1] * sy;
        const x2 = h.box[2] * sx;
        const y2 = h.box[3] * sy;
        const cx = (x1 + x2) / 2;
        const cy = (y1 + y2) / 2;
        const rx = Math.max(6, (x2 - x1) / 2);
        const ry = Math.max(6, (y2 - y1) / 2);
        // An estimated field never gets to look like a measurement: dashed
        // contours, no bloom, and no number on screen.
        const color = estimated ? COLOR.unknown : SEVERITY_COLOR[h.severity];
        // A hotspot filling the frame must not fill the *display*: the bloom
        // fades out as the region grows, otherwise a large fire washes the
        // whole eyebox in orange and hides the room it is burning.
        const areaFrac = ((x2 - x1) * (y2 - y1)) / (fw * fh);
        const bloom = estimated
          ? 0
          : Math.max(
              0,
              (h.severity === "critical" ? 0.18 : 0.11) * (1 - areaFrac * 6)
            );
        return (
          <g key={i}>
            {/* soft bloom = "heat here", readable in peripheral vision */}
            {bloom > 0.01 && (
              <ellipse cx={cx} cy={cy} rx={rx * 1.2} ry={ry * 1.2} fill={color}
                fillOpacity={bloom} filter="url(#ps-heat)" />
            )}
            {/* Contour rings = relative intensity. A large region drops the
                outer rings entirely: rings spanning the frame stop reading as
                "this is hot" and start reading as "the display is broken". */}
            {(areaFrac > 0.12 ? [0.9, 0.55] : [1.15, 0.85, 0.55]).map((k, j) => (
              <ellipse key={j} cx={cx} cy={cy}
                rx={Math.min(rx * k, fw * 0.34)} ry={Math.min(ry * k, fh * 0.34)}
                fill="none" stroke={color} strokeWidth={1.3}
                strokeOpacity={(areaFrac > 0.12 ? 0.3 : 0.35) + j * 0.15}
                strokeDasharray={estimated ? "5 5" : undefined} />
            ))}
            {showLabels && (
              <text x={cx} y={y1 - 6} textAnchor="middle" fontSize={11}
                fontWeight={600} letterSpacing="0.08em" fill={color}>
                {/* No degrees without a radiometric sensor: a number implies a
                    measurement, and this field is inferred from colour. */}
                {estimated ? "WARM (EST)" : `${Math.round(h.max_temp_c)}°C`}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}
