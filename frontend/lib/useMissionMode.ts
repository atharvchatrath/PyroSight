"use client";

// Adaptive interface state.
//
// The HUD changes what it shows based on what the firefighter is actually
// doing, because the information that saves a life during egress is not the
// information that finds a victim during a primary search.
//
//   SEARCH   victims · doors · unsearched area · coverage · navigation
//   RESCUE   the victim · safe route · exit · heat warnings
//   EVAC     exit · navigation · fire · hazards · critical alerts only
//   TRAINING everything, plus confidence internals and replay
//
// Mode is derived from telemetry (objective, emergency flag, what is on
// screen) with hysteresis so it cannot flap between two modes while a victim
// detection flickers at the edge of the frame. TRAINING is a deliberate
// operator choice and is never entered automatically.

import { useEffect, useRef, useState } from "react";
import { SystemState } from "./types";
import { MissionMode } from "./design";

const VICTIM_ENTER_S = 1.2; // victim must persist before we switch to RESCUE
const VICTIM_EXIT_S = 6.0; // …and stay gone this long before we leave it
const STORE_KEY = "pyrosight.training";

function victimPresent(state: SystemState): boolean {
  return state.tracks.some(
    (t) => t.cls === "person" && t.conf >= 0.7 && !t.stale
  );
}

export function useMissionMode(state: SystemState | null): {
  mode: MissionMode;
  auto: MissionMode;
  training: boolean;
  setTraining: (on: boolean) => void;
} {
  const [training, setTrainingState] = useState(false);
  const [auto, setAuto] = useState<MissionMode>("SEARCH");
  const victimSince = useRef<number | null>(null);
  const victimGone = useRef<number | null>(null);

  // Training preference survives a page reload (the instructor sets it once).
  useEffect(() => {
    try {
      setTrainingState(localStorage.getItem(STORE_KEY) === "1");
    } catch {
      /* storage unavailable: default off */
    }
  }, []);

  const setTraining = (on: boolean) => {
    setTrainingState(on);
    try {
      localStorage.setItem(STORE_KEY, on ? "1" : "0");
    } catch {
      /* ignore */
    }
  };

  useEffect(() => {
    if (!state) return;
    const now = performance.now() / 1000;
    const obj = state.nav.objective;

    if (victimPresent(state)) {
      victimGone.current = null;
      if (victimSince.current == null) victimSince.current = now;
    } else {
      victimSince.current = null;
      if (victimGone.current == null) victimGone.current = now;
    }

    const heldVictim =
      victimSince.current != null && now - victimSince.current >= VICTIM_ENTER_S;
    const recentVictim =
      victimGone.current != null && now - victimGone.current < VICTIM_EXIT_S;

    let next: MissionMode;
    if (state.emergency || obj === "find_exit" || obj === "return_to_entry") {
      next = "EVAC";
    } else if (obj === "locate_victim" || heldVictim || recentVictim) {
      next = "RESCUE";
    } else {
      next = "SEARCH";
    }
    setAuto((prev) => (prev === next ? prev : next));
  }, [state]);

  return { mode: training ? "TRAINING" : auto, auto, training, setTraining };
}
