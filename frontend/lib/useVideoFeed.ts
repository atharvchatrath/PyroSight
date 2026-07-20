"use client";

// Binary JPEG feed over WebSocket -> object URL for an <img>. Revokes the
// previous frame's URL so memory stays flat at 15 FPS for hours.

import { useEffect, useRef, useState } from "react";
import { wsUrl } from "./types";

export function useVideoFeed(feed: "rgb" | "thermal" | "fused") {
  const [src, setSrc] = useState<string | null>(null);
  const prevUrl = useRef<string | null>(null);

  useEffect(() => {
    let alive = true;
    let retry: ReturnType<typeof setTimeout>;
    let ws: WebSocket | null = null;

    const connect = () => {
      if (!alive) return;
      ws = new WebSocket(wsUrl(`/ws/video?feed=${feed}`));
      ws.binaryType = "blob";
      ws.onmessage = (msg) => {
        if (!alive || !(msg.data instanceof Blob)) return;
        const url = URL.createObjectURL(msg.data);
        if (prevUrl.current) URL.revokeObjectURL(prevUrl.current);
        prevUrl.current = url;
        setSrc(url);
      };
      ws.onclose = () => {
        if (alive) retry = setTimeout(connect, 1500);
      };
      ws.onerror = () => ws?.close();
    };

    connect();
    return () => {
      alive = false;
      clearTimeout(retry);
      ws?.close();
      if (prevUrl.current) URL.revokeObjectURL(prevUrl.current);
    };
  }, [feed]);

  return src;
}
