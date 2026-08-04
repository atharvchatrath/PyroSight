"use client";

// 60 Hz smoothing for the scalar values the HUD draws continuously — heading,
// relative bearing, distance. Telemetry lands at ~18 Hz; without this the
// compass tape and the navigation ribbon step visibly, which reads as lag.

import { useEffect, useRef, useState } from "react";
import { AngleFilter, OneEuroFilter, approach } from "./smoothing";

/** Smooth a plain number (distance, density, percentage). */
export function useSmoothNumber(value: number | null, tau = 0.14): number | null {
  const cur = useRef<number | null>(null);
  const target = useRef<number | null>(value);
  const [, tick] = useState(0);
  target.current = value;

  useEffect(() => {
    let raf = 0;
    let prev = performance.now();
    const frame = (now: number) => {
      const dt = Math.min(0.05, (now - prev) / 1000);
      prev = now;
      const t = target.current;
      if (t == null) {
        cur.current = null;
      } else if (cur.current == null) {
        cur.current = t;
      } else {
        cur.current = approach(cur.current, t, dt, tau);
      }
      tick((n) => (n + 1) % 1000);
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [tau]);

  return cur.current;
}

/** Smooth a heading/bearing in degrees the short way around the circle. */
export function useSmoothAngle(deg: number, minCutoff = 1.4, beta = 0.03): number {
  const filter = useRef<AngleFilter | null>(null);
  const target = useRef(deg);
  const cur = useRef(deg);
  const [, tick] = useState(0);
  target.current = deg;

  useEffect(() => {
    filter.current = new AngleFilter(minCutoff, beta);
    let raf = 0;
    let prev = performance.now();
    const frame = (now: number) => {
      const dt = Math.min(0.05, (now - prev) / 1000);
      prev = now;
      cur.current = filter.current!.filter(target.current, dt);
      tick((n) => (n + 1) % 1000);
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [minCutoff, beta]);

  return cur.current;
}

/** One-euro smoothing for a value that can also be absent. */
export function useEuro(value: number, minCutoff = 1.0, beta = 0.02): number {
  const filter = useRef<OneEuroFilter | null>(null);
  const target = useRef(value);
  const cur = useRef(value);
  const [, tick] = useState(0);
  target.current = value;

  useEffect(() => {
    filter.current = new OneEuroFilter(minCutoff, beta);
    let raf = 0;
    let prev = performance.now();
    const frame = (now: number) => {
      const dt = Math.min(0.05, (now - prev) / 1000);
      prev = now;
      cur.current = filter.current!.filter(target.current, dt);
      tick((n) => (n + 1) % 1000);
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [minCutoff, beta]);

  return cur.current;
}
