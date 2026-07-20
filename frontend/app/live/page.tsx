"use client";

// LIVE CAMERA TEST — real end-to-end run on this machine's camera.
// The browser owns the camera permission (getUserMedia), streams JPEG
// frames to the backend over /ws/ingest, and the full perception pipeline
// (neural detection, fire + smoke analysis, thermal estimate, fusion,
// temporal tracking, navigation) runs on the real feed. The right panel
// shows exactly what the helmet HUD would show.

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import VideoCanvas from "@/components/VideoCanvas";
import CommandBar from "@/components/dashboard/CommandBar";
import MiniMap from "@/components/hud/MiniMap";
import StatusCluster from "@/components/hud/StatusCluster";
import { useTelemetry } from "@/lib/useTelemetry";
import { wsUrl } from "@/lib/types";

const SEND_W = 640;
const SEND_H = 480;
const SEND_INTERVAL_MS = 90; // ~11 FPS uplink; the backend conflates

export default function LiveTestPage() {
  const { state, events, connected, sendCommand } = useTelemetry();
  const lastAck = [...events].reverse().find((e) => e.kind === "command");
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [running, setRunning] = useState(false);
  const [sent, setSent] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const stop = useCallback(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = null;
    wsRef.current?.close();
    wsRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setRunning(false);
  }, []);

  useEffect(() => stop, [stop]);

  const start = useCallback(async () => {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: SEND_W, height: SEND_H, facingMode: "environment" },
        audio: false,
      });
      streamRef.current = stream;
      const video = videoRef.current!;
      video.srcObject = stream;
      await video.play();

      const ws = new WebSocket(wsUrl("/ws/ingest"));
      ws.binaryType = "arraybuffer";
      ws.onclose = () => stop();
      wsRef.current = ws;

      const canvas = canvasRef.current!;
      canvas.width = SEND_W;
      canvas.height = SEND_H;
      const ctx = canvas.getContext("2d")!;

      timerRef.current = setInterval(() => {
        if (ws.readyState !== WebSocket.OPEN || video.readyState < 2) return;
        ctx.drawImage(video, 0, 0, SEND_W, SEND_H);
        canvas.toBlob(
          (blob) => {
            if (blob && ws.readyState === WebSocket.OPEN) {
              ws.send(blob);
              setSent((n) => n + 1);
            }
          },
          "image/jpeg",
          0.7
        );
      }, SEND_INTERVAL_MS);
      setRunning(true);
    } catch (e) {
      setError(
        e instanceof Error && e.name === "NotAllowedError"
          ? "Camera permission denied — allow camera access for localhost in your browser."
          : `Camera error: ${e instanceof Error ? e.message : String(e)}`
      );
      stop();
    }
  }, [stop]);

  const simMode = state != null && state.mode === "sim";

  return (
    <main className="min-h-screen p-4 flex flex-col gap-4">
      <header className="flex items-center gap-4 flex-wrap">
        <Link href="/" className="text-xl font-bold tracking-[0.3em] text-bright">
          PYRO<span className="text-danger">SIGHT</span>
        </Link>
        <span className="text-dim text-xs tracking-widest">LIVE CAMERA TEST</span>
        <span
          className={`text-xs px-2 py-1 rounded border ${
            connected ? "border-ok text-ok" : "border-danger text-danger animate-alarm"
          }`}
        >
          {connected ? "BACKEND LINKED" : "BACKEND OFFLINE"}
        </span>
        <Link href="/hud" className="btn text-xs ml-auto">HUD →</Link>
        <Link href="/dashboard" className="btn text-xs">DASHBOARD →</Link>
      </header>

      {simMode && (
        <div className="panel p-3 text-accent text-sm">
          Backend is running the SIM demo. Press <b>START CAMERA</b> — the
          backend switches to LIVE processing automatically when your feed
          connects (the AI model loads in the background, ~15 s to first
          detection).
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
            <canvas ref={canvasRef} className="hidden" />
            <div className="flex items-center gap-3 flex-wrap">
              {!running ? (
                <button className="btn border-ok text-ok" onClick={start}>
                  ▶ START CAMERA
                </button>
              ) : (
                <button className="btn border-danger text-danger" onClick={stop}>
                  ■ STOP
                </button>
              )}
              <span className="text-xs text-dim">
                {running ? `streaming — ${sent} frames sent` : "browser asks for permission on start"}
              </span>
            </div>
            {error && <div className="text-danger text-sm">{error}</div>}
            <p className="text-xs text-dim leading-relaxed">
              Frames go to the backend over WebSocket; the full pipeline
              (YOLO-World detection, HSV+flicker fire check, smoke density,
              thermal estimate, fusion, temporal tracking) runs on the real
              feed. Point the camera at people, doors, or a flame video on
              your phone and watch the right panel.
            </p>
          </div>
        </section>

        <section className="panel">
          <h2 className="panel-title">
            AI output (fused view{state ? ` — ${state.detector.toUpperCase()}` : ""})
          </h2>
          <div className="p-2 flex flex-col gap-2">
            {/* Same overlay furniture as the helmet HUD: status details
                top-left, position mini-map top-right — over the live feed. */}
            <div className="relative">
              <VideoCanvas feed="fused" state={state} />
              {state && (
                <>
                  <div className="absolute top-2 left-2 rounded border border-edge/60 bg-ink/60 backdrop-blur-[2px] px-2.5 py-2">
                    <StatusCluster state={state} />
                  </div>
                  <div className="absolute top-2 right-2">
                    <MiniMap state={state} />
                  </div>
                </>
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

      {/* Voice / command control, same grammar as the helmet unit. */}
      <section className="panel">
        <h2 className="panel-title">
          Voice / Command
          {lastAck && (
            <span className="ml-3 text-accent normal-case tracking-normal">
              ◂ {lastAck.ack}
            </span>
          )}
        </h2>
        <div className="p-3">
          <CommandBar onCommand={sendCommand} />
        </div>
      </section>
    </main>
  );
}
