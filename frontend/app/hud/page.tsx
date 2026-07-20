"use client";

// Helmet HUD — the monocular OLED view. Layout per the HUD spec:
//   top-left: system health · top-right: compass + mission timer
//   center:   live fused view + detections + nav arrow
//   bottom:   objective, warnings, AI confidence

import Link from "next/link";
import VideoCanvas from "@/components/VideoCanvas";
import BottomBar from "@/components/hud/BottomBar";
import CompassStrip from "@/components/hud/CompassStrip";
import MiniMap from "@/components/hud/MiniMap";
import NavArrow from "@/components/hud/NavArrow";
import StatusCluster from "@/components/hud/StatusCluster";
import { useTelemetry } from "@/lib/useTelemetry";

export default function HudPage() {
  const { state, connected } = useTelemetry();

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

  return (
    <main className="h-screen flex flex-col bg-ink select-none">
      <div className="relative flex-1 min-h-0 flex items-center justify-center p-2">
        <div className="relative h-full max-w-full" style={{ aspectRatio: "4 / 3" }}>
          <VideoCanvas feed={view} state={state} className="h-full w-full" />

          {/* corner clusters float over the video */}
          <div className="absolute top-3 left-3 rounded border border-edge/60 bg-ink/60 backdrop-blur-[2px] px-2.5 py-2">
            <StatusCluster state={state} />
          </div>
          <div className="absolute top-3 right-3 flex flex-col items-end gap-2">
            <div className="rounded border border-edge/60 bg-ink/60 backdrop-blur-[2px] px-2.5 py-2">
              <CompassStrip state={state} />
            </div>
            <MiniMap state={state} />
          </div>

          {/* nav arrow: lower center, above the bottom band */}
          <div className="absolute bottom-6 left-1/2 -translate-x-1/2">
            <NavArrow nav={state.nav} />
          </div>

          {/* view mode + link badge */}
          <div className="absolute bottom-3 left-3 text-xs text-dim">
            VIEW {view.toUpperCase()}
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
