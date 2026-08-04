"use client";

// Live feed surface + perception overlays.
//
// The <img> is the MJPEG-ish frame stream; everything drawn on top shares the
// frame's pixel coordinate system through the SVG viewBox, so overlays track
// the image exactly at any display size. Track geometry is conditioned by
// useSmoothTracks before it reaches the screen — see that module for why.

import { useVideoFeed } from "@/lib/useVideoFeed";
import { useSmoothTracks } from "@/lib/useSmoothTracks";
import { SystemState } from "@/lib/types";
import { MissionMode } from "@/lib/design";
import DetectionLayer from "@/components/hud/DetectionLayer";
import ThermalOverlay from "@/components/hud/ThermalOverlay";

export default function VideoCanvas({
  feed,
  state,
  showOverlay = true,
  showThermal = true,
  mode = "SEARCH",
  insetTop = 0,
  insetBottom = 0,
  reserved = [],
  className = "",
}: {
  feed: "rgb" | "thermal" | "fused";
  state: SystemState | null;
  showOverlay?: boolean;
  showThermal?: boolean;
  mode?: MissionMode;
  /** Fraction of frame height reserved for HUD chrome, so labels avoid it. */
  insetTop?: number;
  insetBottom?: number;
  /** Card regions as [x1,y1,x2,y2] fractions of the frame; labels route around. */
  reserved?: [number, number, number, number][];
  className?: string;
}) {
  const src = useVideoFeed(feed);
  const tracks = useSmoothTracks(showOverlay ? state : null);
  const fw = state?.frame.w ?? 640;
  const fh = state?.frame.h ?? 480;

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
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="cap animate-breathe">AWAITING {feed.toUpperCase()} FEED</span>
        </div>
      )}

      {/* Thermal contours sit under the detection graphics: heat is context,
          detections are the decision layer. Skipped on the thermal feed
          itself, which is already a heat image. */}
      {state && showThermal && feed !== "thermal" && (
        <ThermalOverlay state={state} opacity={0.95} showLabels={mode !== "EVAC"} />
      )}

      {state && showOverlay && (
        <DetectionLayer
          tracks={tracks}
          fw={fw}
          fh={fh}
          mode={mode}
          smoke={state.smoke?.density ?? 0}
          colorblind={state.prefs.colorblind}
          showLabels={state.prefs.show_labels}
          emphasizeDoors={state.prefs.highlight_doors}
          safeTop={fh * insetTop}
          safeBottom={fh * insetBottom}
          reserved={reserved.map(
            (r) => [r[0] * fw, r[1] * fh, r[2] * fw, r[3] * fh] as [number, number, number, number]
          )}
        />
      )}
    </div>
  );
}
