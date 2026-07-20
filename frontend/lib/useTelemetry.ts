"use client";

// Telemetry WebSocket hook: auto-reconnecting state + event stream shared
// by the HUD and the dashboard.

import { useCallback, useEffect, useRef, useState } from "react";
import { SystemState, TelemetryEvent, wsUrl } from "./types";

const MAX_EVENTS = 300;

export function useTelemetry() {
  const [state, setState] = useState<SystemState | null>(null);
  const [events, setEvents] = useState<TelemetryEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    // `alive` must be local to this effect run: React StrictMode invokes
    // effect -> cleanup -> effect on one mount, and a shared ref would let
    // the first socket's onclose see the second run's "alive" and spawn a
    // duplicate connection (every event then arrives twice).
    let alive = true;
    let retry: ReturnType<typeof setTimeout>;

    const connect = () => {
      if (!alive) return;
      const ws = new WebSocket(wsUrl("/ws/telemetry"));
      wsRef.current = ws;

      ws.onopen = () => setConnected(true);
      ws.onmessage = (msg) => {
        if (!alive) return;
        try {
          const data = JSON.parse(msg.data);
          if (data.type === "state") {
            setState(data.state as SystemState);
          } else if (data.type === "event") {
            setEvents((prev) => {
              // Events are seq-ordered per connection; drop stale re-deliveries.
              const last = prev.length ? prev[prev.length - 1].seq : -1;
              if (data.event.seq <= last) return prev;
              return [...prev.slice(-MAX_EVENTS + 1), data.event];
            });
          } else if (data.type === "hello") {
            setEvents(data.history ?? []);
          }
        } catch {
          /* malformed frame: ignore */
        }
      };
      ws.onclose = () => {
        setConnected(false);
        if (alive) retry = setTimeout(connect, 1500);
      };
      ws.onerror = () => ws.close();
    };

    connect();
    const opened = wsRef.current;
    return () => {
      alive = false;
      clearTimeout(retry);
      opened?.close();
    };
  }, []);

  const sendCommand = useCallback((text: string) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "command", text }));
    }
  }, []);

  return { state, events, connected, sendCommand };
}
