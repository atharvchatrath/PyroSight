"use client";

// Top information band: mission mode, current objective, compass, indoor
// position, mission clock. Four facts, one line, always in the same place —
// the operator's eye learns the geography once and never searches again.

import { SystemState } from "@/lib/types";
import { MODE_META, MissionMode } from "@/lib/design";
import { missionClock } from "@/lib/format";
import CompassStrip from "./CompassStrip";

const OBJECTIVE_LABEL: Record<string, string> = {
  explore: "SEARCH & SIZE-UP",
  find_exit: "FIND EXIT",
  locate_victim: "LOCATE VICTIM",
  return_to_entry: "RETURN TO ENTRY",
  search: "GUIDED SEARCH",
};

export default function TopBar({
  state,
  mode,
  compact = false,
}: {
  state: SystemState;
  mode: MissionMode;
  compact?: boolean;
}) {
  const meta = MODE_META[mode];
  const pos = state.nav.breadcrumbs.position;
  const objective =
    OBJECTIVE_LABEL[state.nav.objective] ?? state.nav.objective.toUpperCase();

  return (
    <div className="panel-float flex items-center gap-4 px-3.5 py-2">
      {/* mission mode */}
      <div className="flex items-center gap-2 shrink-0">
        <span
          className="w-2 h-2 rounded-full shrink-0"
          style={{ background: meta.color, boxShadow: `0 0 10px ${meta.color}` }}
        />
        <span
          className="text-[13px] font-semibold tracking-wide2"
          style={{ color: meta.color }}
        >
          {meta.label}
        </span>
      </div>

      <div className="h-5 w-px bg-white/10 shrink-0" />

      <div className="min-w-0 shrink">
        <div className="cap leading-none">OBJECTIVE</div>
        <div className="text-[13px] font-medium text-bright tracking-hud truncate">
          {objective}
        </div>
      </div>

      <div className="flex-1 flex justify-center min-w-0">
        <CompassStrip state={state} width={compact ? 220 : 300} />
      </div>

      {!compact && (
        <div className="text-right shrink-0">
          <div className="cap leading-none">POSITION</div>
          <div className="text-[13px] text-bright num tracking-hud">
            {pos ? `${pos[0].toFixed(1)} · ${pos[1].toFixed(1)} m` : "NO FIX"}
          </div>
        </div>
      )}

      <div className="h-5 w-px bg-white/10 shrink-0" />

      <div className="text-right shrink-0">
        <div className="cap leading-none">MISSION</div>
        <div className="text-[15px] font-semibold text-bright num tracking-hud">
          {missionClock(state.mission_time_s)}
        </div>
      </div>
    </div>
  );
}
