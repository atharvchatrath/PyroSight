"use client";

// Helmet HUD — the monocular OLED view. Layout per the HUD spec:
//   top-left: system health · top-right: compass + mission timer + mini-map
//   center:   live fused view + detections + nav arrow + assistant line
//   bottom:   objective, warnings, AI confidence
//
// Reads runtime prefs from telemetry: effective brightness (gain on the whole
// HUD), label visibility, and EMERGENCY MODE — which brightens the display,
// strips clutter, and throws a large exit banner.

import Link from "next/link";
import VideoCanvas from "@/components/VideoCanvas";
import BottomBar from "@/components/hud/BottomBar";
import CompassStrip from "@/components/hud/CompassStrip";
import MiniMap from "@/components/hud/MiniMap";
import NavArrow from "@/components/hud/NavArrow";
import StatusCluster from "@/components/hud/StatusCluster";
import { useTelemetry } from "@/lib/useTelemetry";
import { useUplink } from "@/lib/uplink";

export default function HudPage() {
  const { state, connected } = useTelemetry();
  const { running: camRunning } = useUplink();

  if (!state) {
    return (
      <main className="h-screen flex items-center justify-center">
        <div className="text-center">
          <div className="text-dim tracking-[0.3em] animate-alarm">
            {connected ? "SYNCING TELEMETRY…" : "LINK DOWN — RECONNECTING"}
          </div>
          <Link href="/" className="block mt-6 text-accent underline text-sm">
            ← back
          </Link>
        </div>
      </main>
    );
  }

  const view = state.prefs.primary_view;
  const emergency = state.emergency;
  const brightness = state.prefs.effective_brightness ?? 1;

  return (
    <main
      className={`h-screen flex flex-col bg-ink select-none ${
        emergency ? "ring-4 ring-inset ring-danger" : ""
      }`}
      style={{ filter: `brightness(${brightness}) contrast(${emergency ? 1.15 : 1})` }}
    >
      <div className="relative flex-1 min-h-0 flex items-center justify-center p-2">
        <div className="relative h-full max-w-full" style={{ aspectRatio: "4 / 3" }}>
          <VideoCanvas feed={view} state={state} className="h-full w-full" />

          {/* Emergency banner: full-width strip pinned to the very top so it
              never collides with the corner clusters. */}
          {emergency && (
            <div className="absolute top-0 inset-x-0 bg-danger text-ink font-bold text-center py-1.5 text-lg tracking-widest animate-alarm z-10">
              ⚠ EMERGENCY —{" "}
              {state.nav.target?.kind === "exit"
                ? `EXIT ${nearestExitText(state)}`
                : state.nav.instruction}
            </div>
          )}

          {/* corner clusters float over the video (pushed below the banner
              when emergency is active) */}
          <div
            className={`absolute left-3 rounded border border-edge/60 bg-ink/60 backdrop-blur-[2px] px-2.5 py-2 ${
              emergency ? "top-12" : "top-3"
            }`}
          >
            <StatusCluster state={state} />
          </div>
          <div
            className={`absolute right-3 flex flex-col items-end gap-2 ${
              emergency ? "top-12" : "top-3"
            }`}
          >
            <div className="rounded border border-edge/60 bg-ink/60 backdrop-blur-[2px] px-2.5 py-2">
              <CompassStrip state={state} />
            </div>
            {/* Emergency reduces clutter: mini-map hidden, exit cue enlarged. */}
            {!emergency && <MiniMap state={state} />}
          </div>

          {/* Smart AI Assistant — one calm line, center-top. Hidden in
              emergency mode to reduce clutter. */}
          {state.assistant && !emergency && (
            <div className="absolute top-3 left-1/2 -translate-x-1/2 max-w-[55%]">
              <div className="rounded bg-ink/70 border border-accent/40 px-3 py-1 text-accent text-sm text-center">
                💬 {state.assistant}
              </div>
            </div>
          )}

          {/* nav arrow: lower center, above the bottom band */}
          <div className="absolute bottom-6 left-1/2 -translate-x-1/2">
            <NavArrow nav={state.nav} big={emergency} />
          </div>

          {/* view mode + link badges */}
          <div className="absolute bottom-3 left-3 text-xs text-dim">
            VIEW {view.toUpperCase()}
            {camRunning && <span className="ml-2 text-warn">● CAM LIVE</span>}
            {!connected && (
              <span className="ml-2 text-danger animate-alarm">LINK LOST</span>
            )}
          </div>
          <Link
            href="/dashboard"
            className="absolute bottom-3 right-3 text-xs text-dim hover:text-accent"
          >
            CMD →
          </Link>
        </div>
      </div>

      <div className="px-4 pb-3 pt-1">
        <BottomBar state={state} />
      </div>
    </main>
  );
}

function nearestExitText(state: {
  nav: { target: { rel_bearing_deg: number; dist_ft: number | null } | null };
}): string {
  const t = state.nav.target;
  if (!t) return "";
  const rel = t.rel_bearing_deg;
  const dir =
    Math.abs(rel) <= 20
      ? "AHEAD"
      : Math.abs(rel) >= 150
      ? "BEHIND"
      : rel > 0
      ? "RIGHT"
      : "LEFT";
  return `${dir}${t.dist_ft != null ? ` ${Math.round(t.dist_ft)} FT` : ""}`;
}
