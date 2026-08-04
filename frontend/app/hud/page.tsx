"use client";

// Helmet HUD — the monocular OLED view.
//
// Layout is fixed and learned once: mission band across the top, live world in
// the middle with the navigation ribbon leaving the operator's feet, machine
// vitals along the bottom. Mode decides what else is allowed on screen
// (lib/useMissionMode). In EVACUATE the display strips itself down to exit,
// path, hazards — nothing that isn't part of getting out.

import Link from "next/link";
import { useEffect } from "react";
import VideoCanvas from "@/components/VideoCanvas";
import AssistantStack from "@/components/hud/AssistantStack";
import CriticalAlert from "@/components/hud/CriticalAlert";
import MiniMap from "@/components/hud/MiniMap";
import NavRibbon from "@/components/hud/NavRibbon";
import StatusRail from "@/components/hud/StatusRail";
import TopBar from "@/components/hud/TopBar";
import {
  CoverageChip,
  FocusCard,
  ThermalPenetrationChip,
  TrainingPanel,
} from "@/components/hud/ModePanels";
import { MODE_META } from "@/lib/design";
import { useMissionMode } from "@/lib/useMissionMode";
import { useTelemetry } from "@/lib/useTelemetry";
import { useUplink } from "@/lib/uplink";

export default function HudPage() {
  const { state, connected } = useTelemetry();
  const { running: camRunning } = useUplink();
  const { mode, training, setTraining } = useMissionMode(state);

  // T toggles training instrumentation — instructor-side, never automatic.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "t" || e.key === "T") setTraining(!training);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [training, setTraining]);

  if (!state) {
    return (
      <main className="h-screen flex items-center justify-center">
        <div className="text-center">
          <div className="text-[13px] tracking-wide2 text-dim animate-breathe">
            {connected ? "SYNCING TELEMETRY" : "LINK DOWN — RECONNECTING"}
          </div>
          <Link href="/" className="btn btn-sm mt-6 inline-flex items-center">
            ← BACK
          </Link>
        </div>
      </main>
    );
  }

  const view = state.prefs.primary_view;
  const evac = mode === "EVAC";
  const brightness = state.prefs.effective_brightness ?? 1;
  const meta = MODE_META[mode];

  // Screen space owned by the rails, as fractions of the frame. Detection
  // labels route around these instead of landing underneath a card.
  const leftCard =
    (mode === "RESCUE" && state.tracks.some((t) => t.cls === "person")) ||
    (mode === "SEARCH" && state.search?.active) ||
    (state.smoke?.density ?? 0) >= 0.3;
  // The right rail grows with what it carries: map alone in SEARCH/RESCUE,
  // map + instrumentation + assistant in TRAINING.
  const rightRailBottom = mode === "TRAINING" ? 0.86 : 0.62;
  const reservedRegions: [number, number, number, number][] = [
    ...(leftCard ? ([[0, 0.18, 0.46, 0.44]] as [number, number, number, number][]) : []),
    ...(!evac
      ? ([[0.62, 0.16, 1, rightRailBottom]] as [number, number, number, number][])
      : []),
  ];

  return (
    <main
      className="h-screen flex flex-col bg-ink select-none overflow-hidden"
      style={{
        filter: `brightness(${brightness}) contrast(${evac ? 1.12 : 1})`,
        transition: "filter 400ms cubic-bezier(0.22,1,0.36,1)",
      }}
    >
      {/* Mode is also signalled structurally: a hairline in the mode colour
          frames the whole eyebox, readable in peripheral vision alone. */}
      <div
        className="relative flex-1 min-h-0 flex items-center justify-center p-3"
        style={{
          boxShadow: `inset 0 0 0 1px ${meta.color}33${
            // A frame, not a wash: EVAC gets a heavier border, never a tint
            // over the live image.
            evac ? `, inset 0 0 0 3px ${meta.color}55` : ""
          }`,
        }}
      >
        {/* The eyebox follows the CAMERA's aspect, not a hardcoded 4:3. The
            helmet panel is a 16:9 micro-OLED; a fixed 4:3 box would black-bar
            a third of a 0.39" display. Set PYROSIGHT_RGB_WIDTH/HEIGHT to the
            panel's ratio (e.g. 1280x720) and the HUD fills it exactly. */}
        <div
          className="relative h-full max-w-full"
          style={{ aspectRatio: `${state.frame.w} / ${state.frame.h}` }}
        >
          <VideoCanvas
            feed={view}
            state={state}
            mode={mode}
            insetTop={0.20}
            insetBottom={0.10}
            reserved={reservedRegions}
            className="h-full w-full"
          />

          {/* ---- navigation ribbon: lower half, anchored to the floor ---- */}
          <div className="absolute inset-x-0 bottom-0 h-[62%] z-0 flex items-end justify-center">
            <div className="w-[70%] h-full">
              <NavRibbon state={state} compact={evac} />
            </div>
          </div>

          {/* ---- HUD chrome ----
              One flow, not four floating boxes: mission band, then the single
              alert, then the two rails. Laid out rather than absolutely
              positioned so nothing can ever overlap anything else, whatever
              the alert says or how wide a card grows. */}
          <div className="absolute inset-0 z-20 flex flex-col p-3 gap-2 pointer-events-none">
            <TopBar state={state} mode={mode} />

            <div className="flex justify-center">
              <div className="max-w-[85%]">
                <CriticalAlert state={state} />
              </div>
            </div>

            <div className="flex-1 min-h-0 flex items-start justify-between gap-3">
              {/* left rail: the focus of the current mode */}
              <div className="flex flex-col gap-2 max-w-[38%]">
                {mode === "RESCUE" && <FocusCard state={state} />}
                {mode === "SEARCH" && <CoverageChip state={state} />}
                {/* Kept in every mode, including egress: when the camera is
                    blind this is the only sensor still finding the fire. */}
                <ThermalPenetrationChip state={state} />
              </div>

              {/* right rail: map, instrumentation, assistant */}
              <div className="flex flex-col items-end gap-2">
                {!evac && <MiniMap state={state} size={mode === "TRAINING" ? 132 : 150} />}
                {mode === "TRAINING" && <TrainingPanel state={state} />}
                {!evac && (
                  <AssistantStack
                    message={state.assistant}
                    tone={state.emergency ? "warn" : "info"}
                  />
                )}
              </div>
            </div>

            {/* corner metadata */}
            <div className="flex items-end justify-between cap">
              <div className="flex items-center gap-2">
                <span>VIEW {view.toUpperCase()}</span>
                {camRunning && <span style={{ color: MODE_META.TRAINING.color }}>● CAM LIVE</span>}
                {!connected && <span className="text-danger animate-alarm">LINK LOST</span>}
              </div>
              <div className="flex items-center gap-3 pointer-events-auto">
                <button
                  className="cap hover:text-bright transition-colors"
                  onClick={() => setTraining(!training)}
                  title="Toggle training instrumentation (T)"
                >
                  {training ? "TRAINING ON" : "TRAINING"}
                </button>
                <Link href="/dashboard" className="cap hover:text-bright transition-colors">
                  COMMAND →
                </Link>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="px-3 pb-3">
        <StatusRail state={state} connected={connected} />
      </div>
    </main>
  );
}
