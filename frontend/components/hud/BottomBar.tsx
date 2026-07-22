"use client";

// Bottom HUD band: current objective, warning banner, AI confidence pill.

import { SystemState } from "@/lib/types";

const OBJECTIVE_LABEL: Record<string, string> = {
  explore: "SEARCH & SIZE-UP",
  find_exit: "FIND EXIT",
  locate_victim: "LOCATE VICTIM",
  return_to_entry: "RETURN TO ENTRY",
  search: "GUIDED SEARCH",
};

export default function BottomBar({ state }: { state: SystemState }) {
  const alert = state.last_alert;
  const alertFresh = alert != null && state.ts - alert.ts < 8;
  const tracks = state.tracks;
  const avgConf =
    tracks.length > 0
      ? tracks.reduce((acc, t) => acc + t.conf, 0) / tracks.length
      : null;
  const confColor =
    avgConf == null
      ? "text-dim"
      : avgConf >= 0.75
      ? "text-ok"
      : avgConf >= 0.5
      ? "text-warn"
      : "text-danger";

  return (
    <div className="flex flex-col gap-1.5">
      {alertFresh && (
        <div
          className={`self-center px-5 py-1.5 rounded font-bold tracking-wider text-[17px] ${
            alert.severity === "critical"
              ? "bg-danger text-ink animate-alarm"
              : alert.severity === "warning"
              ? "bg-warn text-ink"
              : "bg-panel border border-edge text-accent"
          }`}
        >
          {alert.text}
        </div>
      )}
      <div className="flex items-center justify-between gap-4 text-[15px]">
        <div className="font-bold tracking-widest text-bright">
          ▸ {OBJECTIVE_LABEL[state.nav.objective] ?? state.nav.objective.toUpperCase()}
        </div>
        <div className="text-dim flex-1 text-center truncate">
          {state.nav.instruction}
        </div>
        <div className={`font-bold ${confColor}`}>
          AI {avgConf != null ? `${Math.round(avgConf * 100)}%` : "—"}
          <span className="text-dim font-normal text-xs ml-1">
            {tracks.length} TRK
          </span>
        </div>
      </div>
    </div>
  );
}
