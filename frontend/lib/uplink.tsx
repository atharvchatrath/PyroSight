"use client";

// Persistent camera uplink. The MediaStream + WebSocket live in a module
// singleton, NOT in any page component — so starting the camera on /live
// and navigating to /hud or /dashboard keeps frames flowing to the
// backend. Without this, leaving the page killed the uplink and the
// backend froze on the last received frame.

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { wsUrl } from "./types";

const SEND_W = 640;
const SEND_H = 480;
const SEND_INTERVAL_MS = 90; // ~11 FPS uplink; the backend conflates

export interface UplinkState {
  running: boolean;
  sent: number;
  error: string | null;
  stream: MediaStream | null;
}

type Listener = () => void;

const singleton: {
  state: UplinkState;
  ws: WebSocket | null;
  video: HTMLVideoElement | null;
  canvas: HTMLCanvasElement | null;
  timer: ReturnType<typeof setInterval> | null;
  listeners: Set<Listener>;
} = {
  state: { running: false, sent: 0, error: null, stream: null },
  ws: null,
  video: null,
  canvas: null,
  timer: null,
  listeners: new Set(),
};

function emit(patch: Partial<UplinkState>) {
  singleton.state = { ...singleton.state, ...patch };
  singleton.listeners.forEach((l) => l());
}

export function stopUplink(): void {
  if (singleton.timer) clearInterval(singleton.timer);
  singleton.timer = null;
  singleton.ws?.close();
  singleton.ws = null;
  singleton.state.stream?.getTracks().forEach((t) => t.stop());
  if (singleton.video) singleton.video.srcObject = null;
  emit({ running: false, stream: null });
}

export async function startUplink(): Promise<void> {
  if (singleton.state.running) return;
  emit({ error: null, sent: 0 });
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { width: SEND_W, height: SEND_H, facingMode: "environment" },
      audio: false,
    });

    // Off-DOM elements owned by the singleton — never unmounted by routing.
    if (!singleton.video) {
      singleton.video = document.createElement("video");
      singleton.video.playsInline = true;
      singleton.video.muted = true;
    }
    if (!singleton.canvas) {
      singleton.canvas = document.createElement("canvas");
      singleton.canvas.width = SEND_W;
      singleton.canvas.height = SEND_H;
    }
    const video = singleton.video;
    video.srcObject = stream;
    await video.play();

    const ws = new WebSocket(wsUrl("/ws/ingest"));
    ws.binaryType = "arraybuffer";
    ws.onclose = () => {
      // Backend restart etc.: stop cleanly; user can hit START again.
      if (singleton.state.running) stopUplink();
    };
    singleton.ws = ws;

    const ctx = singleton.canvas.getContext("2d")!;
    singleton.timer = setInterval(() => {
      if (ws.readyState !== WebSocket.OPEN || video.readyState < 2) return;
      ctx.drawImage(video, 0, 0, SEND_W, SEND_H);
      singleton.canvas!.toBlob(
        (blob) => {
          if (blob && ws.readyState === WebSocket.OPEN) {
            ws.send(blob);
            emit({ sent: singleton.state.sent + 1 });
          }
        },
        "image/jpeg",
        0.7
      );
    }, SEND_INTERVAL_MS);
    emit({ running: true, stream });
  } catch (e) {
    emit({
      error:
        e instanceof Error && e.name === "NotAllowedError"
          ? "Camera permission denied — allow camera access for localhost in your browser."
          : `Camera error: ${e instanceof Error ? e.message : String(e)}`,
    });
    stopUplink();
  }
}

const UplinkContext = createContext<UplinkState>(singleton.state);

export function UplinkProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<UplinkState>(singleton.state);
  useEffect(() => {
    const listener = () => setState(singleton.state);
    singleton.listeners.add(listener);
    return () => {
      singleton.listeners.delete(listener);
    };
  }, []);
  return <UplinkContext.Provider value={state}>{children}</UplinkContext.Provider>;
}

export function useUplink(): UplinkState & {
  start: () => Promise<void>;
  stop: () => void;
} {
  const state = useContext(UplinkContext);
  const start = useCallback(() => startUplink(), []);
  const stop = useCallback(() => stopUplink(), []);
  return { ...state, start, stop };
}
