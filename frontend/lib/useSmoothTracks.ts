"use client";

// Render-side track conditioning.
//
// Telemetry tracks arrive at the engine rate (~18 Hz) with per-frame detector
// noise. This hook turns them into a 60 Hz render stream where:
//   • boxes are one-euro filtered  → no shake while standing still
//   • motion is extrapolated between telemetry frames → no visible stepping
//   • identity is preserved        → labels never jump between objects
//   • appearing/disappearing tracks fade → nothing pops into the eye
//   • confidence is smoothed        → the percentage stops flickering ±3%
//
// Extrapolation is deliberately conservative: capped at 120 ms and at 6% of
// the frame width. A HUD that guesses further than the sensor can confirm is
// lying to the person wearing it.

import { useEffect, useRef, useState } from "react";
import { SystemState, Track } from "./types";
import { OneEuroFilter, approach, clamp } from "./smoothing";

export interface RenderTrack extends Track {
  /** Smoothed + extrapolated box in frame pixels. */
  rbox: [number, number, number, number];
  /** Smoothed confidence (display only; never inflates the raw value). */
  rconf: number;
  /** 0..1 fade — appearance ramp, coasting dip, disappearance ramp. */
  alpha: number;
  /** 0..1 tracker stability: age, continuity, freshness. */
  stability: number;
  /** Seconds since this track last had a telemetry update. */
  staleness: number;
  /** Horizontal drift in px/s (used for the motion tick). */
  vx: number;
}

const MAX_PREDICT_S = 0.12;
const FADE_IN_S = 0.18;
const FADE_OUT_S = 0.28;

interface Entry {
  track: Track;
  cx: OneEuroFilter;
  cy: OneEuroFilter;
  w: OneEuroFilter;
  h: OneEuroFilter;
  conf: OneEuroFilter;
  sx: number; // last filtered centre
  sy: number;
  sw: number;
  sh: number;
  sconf: number;
  vx: number; // smoothed velocity, px/s
  vy: number;
  alpha: number;
  target: number; // fade target
  lastUpdate: number; // ms timestamp of last telemetry frame carrying it
  born: number;
  gone: boolean;
}

function boxCenter(b: [number, number, number, number]) {
  return {
    cx: (b[0] + b[2]) / 2,
    cy: (b[1] + b[3]) / 2,
    w: Math.max(1, b[2] - b[0]),
    h: Math.max(1, b[3] - b[1]),
  };
}

export function useSmoothTracks(state: SystemState | null): RenderTrack[] {
  const entries = useRef<Map<number, Entry>>(new Map());
  const lastSeq = useRef<number>(-1);
  const lastStateAt = useRef<number>(0);
  const [out, setOut] = useState<RenderTrack[]>([]);

  // ---- ingest: only when a genuinely new telemetry frame arrives ----------
  useEffect(() => {
    if (!state || state.seq === lastSeq.current) return;
    const now = performance.now();
    const dt = lastStateAt.current ? (now - lastStateAt.current) / 1000 : 1 / 18;
    lastSeq.current = state.seq;
    lastStateAt.current = now;

    const seen = new Set<number>();
    for (const t of state.tracks) {
      seen.add(t.id);
      const g = boxCenter(t.box);
      let e = entries.current.get(t.id);
      if (!e) {
        e = {
          track: t,
          // Position filters run looser than size filters: a box that breathes
          // in width is far more distracting than one that slides a pixel.
          cx: new OneEuroFilter(1.3, 0.055),
          cy: new OneEuroFilter(1.3, 0.055),
          w: new OneEuroFilter(0.8, 0.02),
          h: new OneEuroFilter(0.8, 0.02),
          conf: new OneEuroFilter(0.5, 0.004),
          sx: g.cx,
          sy: g.cy,
          sw: g.w,
          sh: g.h,
          sconf: t.conf,
          vx: 0,
          vy: 0,
          alpha: 0,
          target: 1,
          lastUpdate: now,
          born: now,
          gone: false,
        };
        entries.current.set(t.id, e);
      }
      const px = e.sx;
      const py = e.sy;
      e.track = t;
      e.sx = e.cx.filter(g.cx, dt);
      e.sy = e.cy.filter(g.cy, dt);
      e.sw = e.w.filter(g.w, dt);
      e.sh = e.h.filter(g.h, dt);
      e.sconf = e.conf.filter(t.conf, dt);
      // Velocity is itself smoothed hard — prediction must not amplify noise.
      const instVx = dt > 0 ? (e.sx - px) / dt : 0;
      const instVy = dt > 0 ? (e.sy - py) / dt : 0;
      e.vx = e.vx * 0.72 + instVx * 0.28;
      e.vy = e.vy * 0.72 + instVy * 0.28;
      e.lastUpdate = now;
      e.gone = false;
      // Coasting tracks (occluded, kept alive by the tracker) sit back.
      e.target = t.coasting ? 0.55 : 1;
    }

    for (const [id, e] of entries.current) {
      if (!seen.has(id)) {
        e.gone = true;
        e.target = 0;
      }
    }
  }, [state]);

  // ---- render loop: 60 Hz interpolation + extrapolation ------------------
  useEffect(() => {
    let raf = 0;
    let prev = performance.now();

    const frame = (now: number) => {
      const dt = clamp((now - prev) / 1000, 0, 0.05);
      prev = now;

      const fw = state?.frame.w ?? 640;
      const maxDrift = fw * 0.06;
      const list: RenderTrack[] = [];

      for (const [id, e] of entries.current) {
        e.alpha = approach(e.alpha, e.target, dt, e.gone ? FADE_OUT_S : FADE_IN_S);
        if (e.gone && e.alpha < 0.02) {
          entries.current.delete(id);
          continue;
        }

        const ahead = clamp((now - e.lastUpdate) / 1000, 0, MAX_PREDICT_S);
        const dx = clamp(e.vx * ahead, -maxDrift, maxDrift);
        const dy = clamp(e.vy * ahead, -maxDrift, maxDrift);
        const cx = e.sx + dx;
        const cy = e.sy + dy;
        const hw = e.sw / 2;
        const hh = e.sh / 2;

        const staleness = (now - e.lastUpdate) / 1000;
        const ageS = e.track.age;
        // Stability blends how long we've held the track, whether the tracker
        // is coasting, and how fresh the last real observation is.
        const stability = clamp(
          Math.min(1, ageS / 12) * (e.track.coasting ? 0.55 : 1) *
            (staleness > 0.5 ? 0.6 : 1),
          0,
          1
        );

        list.push({
          ...e.track,
          rbox: [cx - hw, cy - hh, cx + hw, cy + hh],
          rconf: e.sconf,
          alpha: e.alpha,
          stability,
          staleness,
          vx: e.vx,
        });
      }

      // Draw order = priority order, so the most important label wins the top
      // of the stack and never gets covered by a hallway box.
      list.sort((a, b) => a.priority - b.priority);
      setOut(list);
      raf = requestAnimationFrame(frame);
    };

    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
    // `state` is read for frame dimensions only; the loop must not restart.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state?.frame.w]);

  return out;
}
