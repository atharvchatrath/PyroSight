"use client";

// LIVE CAMERA TEST — real end-to-end run on this machine's camera.
// The camera uplink lives in a global singleton (lib/uplink.tsx): starting
// it here keeps frames flowing to the backend even when you navigate to
// the HUD or dashboard. The backend auto-switches sim -> live on the first
// frame and falls back to the sim demo if the feed dies.

import Link from "next/link";
import { useEffect, useRef } from "react";
import VideoCanvas from "@/components/VideoCanvas";
import MiniMap from "@/components/hud/MiniMap";
import { useTelemetry } from "@/lib/useTelemetry";
import { useUplink } from "@/lib/uplink";
import Wordmark from "@/components/Wordmark";
import { detectorLabel } from "@/lib/design";

export default function LiveTestPage() {
  const { state, connected } = useTelemetry();
  const { running, sent, error, stream, start, stop } = useUplink();
  const videoRef = useRef<HTMLVideoElement | null>(null);

  // Mirror the shared stream into this page's preview element.
  useEffect(() => {
    const video = videoRef.current;
    if (video) {
      video.srcObject = stream;
      if (stream) video.play().catch(() => {});
    }
  }, [stream]);

  const simMode = state != null && state.mode === "sim";

  return (
    <main className="min-h-screen p-4 flex flex-col gap-4">
      <header className="flex items-center gap-4 flex-wrap">
        <Wordmark size="md" />
        <span className="cap">Live demo · this device’s camera</span>
        <span
          className={`text-xs px-2 py-1 rounded border ${
            connected ? "border-ok text-ok" : "border-danger text-danger animate-alarm"
          }`}
        >
          {connected ? "BACKEND LINKED" : "BACKEND OFFLINE"}
        </span>
        {running && (
          <span className="text-xs px-2 py-1 rounded border border-warn text-warn">
            ● CAM STREAMING
          </span>
        )}
        <Link href="/hud" className="btn text-xs ml-auto">HUD →</Link>
        <Link href="/dashboard" className="btn text-xs">DASHBOARD →</Link>
      </header>

      {simMode && !running && (
        <div className="panel p-3 text-accent text-sm">
          Backend is running the SIM demo. Press <b>START CAMERA</b> — the
          backend switches to LIVE processing automatically when your feed
          connects (the AI model loads in the background, ~15 s to first
          detection). The camera keeps streaming while you browse the HUD
          and dashboard.
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <section className="panel">
          <h2 className="panel-title">Your camera (uplink)</h2>
          <div className="p-2 flex flex-col gap-3">
            <div className="relative bg-black" style={{ aspectRatio: "4 / 3" }}>
              {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
              <video
                ref={videoRef}
                playsInline
                muted
                className="absolute inset-0 w-full h-full object-cover"
              />
              {!running && (
                <div className="absolute inset-0 flex items-center justify-center text-dim text-sm tracking-widest">
                  CAMERA OFF
                </div>
              )}
            </div>
            <div className="flex items-center gap-3 flex-wrap">
              {!running ? (
                <button className="btn border-ok text-ok" onClick={() => start()}>
                  ▶ START CAMERA
                </button>
              ) : (
                <button className="btn border-danger text-danger" onClick={stop}>
                  ■ STOP
                </button>
              )}
              <span className="text-xs text-dim">
                {running
                  ? `streaming — ${sent} frames sent (keeps running across pages)`
                  : "browser asks for permission on start"}
              </span>
            </div>
            {error && <div className="text-danger text-sm">{error}</div>}
            <p className="text-xs text-dim leading-relaxed">
              Frames go to the backend over WebSocket; the full pipeline
              (YOLO-World detection, HSV+flicker fire check, smoke density,
              thermal estimate, fusion, temporal tracking) runs on the real
              feed. Point the camera at people, doors, or a flame and watch
              the right panel.
            </p>
          </div>
        </section>

        <section className="panel">
          <h2 className="panel-title">
            AI output — fused view{state ? ` · ${detectorLabel(state.detector)}` : ""}
          </h2>
          <div className="p-2 flex flex-col gap-2">
            {/* Same overlay furniture as the helmet HUD: status details
                top-left, position mini-map top-right — over the live feed. */}
            <div className="relative">
              <VideoCanvas feed="fused" state={state} />
              {state && (
                <div className="absolute top-2 right-2">
                  <MiniMap state={state} size={130} />
                </div>
              )}
            </div>
            {state && (
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-dim">
                <span>FPS {state.fps.toFixed(0)}</span>
                <span>
                  INFER {state.inference?.ms != null ? `${Math.round(state.inference.ms)} ms` : "—"}
                </span>
                <span>TRACKS {state.tracks.length}</span>
                <span>SMOKE {Math.round(state.smoke.density * 100)}% ({state.smoke.visibility})</span>
                <span>THERMAL {state.thermal_source?.toUpperCase()}</span>
              </div>
            )}
          </div>
        </section>
      </div>

    </main>
  );
}
