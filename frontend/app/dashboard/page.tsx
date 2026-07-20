"use client";

// Command Dashboard — incident command view: live feeds, detection log,
// event timeline, heat map, sensors, diagnostics, recordings, alerts,
// and the voice/command interface.

import Link from "next/link";
import VideoCanvas from "@/components/VideoCanvas";
import MiniMap from "@/components/hud/MiniMap";
import CommandBar from "@/components/dashboard/CommandBar";
import {
  DetectionLog,
  DiagnosticsPanel,
  EventTimeline,
  HeatPanel,
  IncidentsPanel,
  Panel,
  SensorPanel,
} from "@/components/dashboard/Panels";
import { missionClock } from "@/lib/format";
import { useTelemetry } from "@/lib/useTelemetry";

export default function DashboardPage() {
  const { state, events, connected, sendCommand } = useTelemetry();

  return (
    <main className="min-h-screen p-3 flex flex-col gap-3">
      {/* header */}
      <header className="flex items-center gap-4 flex-wrap">
        <Link href="/" className="text-xl font-bold tracking-[0.3em] text-bright">
          PYRO<span className="text-danger">SIGHT</span>
        </Link>
        <span className="text-dim text-xs tracking-widest">COMMAND DASHBOARD</span>
        <span
          className={`text-xs px-2 py-1 rounded border ${
            connected
              ? "border-ok text-ok"
              : "border-danger text-danger animate-alarm"
          }`}
        >
          {connected ? "LINK OK" : "LINK DOWN"}
        </span>
        {state && (
          <>
            <span className="text-xs text-dim">
              {state.mode.toUpperCase()} · {state.detector.toUpperCase()} ·{" "}
              {state.fps.toFixed(0)} FPS
            </span>
            <span className="ml-auto text-lg font-bold text-bright">
              {missionClock(state.mission_time_s)}
            </span>
            <Link href="/hud" className="btn text-xs">
              HUD VIEW →
            </Link>
          </>
        )}
      </header>

      {state ? (
        <>
          {/* feeds row */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
            <Panel title="RGB Feed" className="lg:col-span-1">
              <VideoCanvas feed="rgb" state={state} />
            </Panel>
            <Panel title="Thermal Feed (relative heat map)">
              <VideoCanvas feed="thermal" state={state} showOverlay={false} />
            </Panel>
            <Panel title="Fused View (HUD source)">
              <VideoCanvas feed="fused" state={state} />
            </Panel>
          </div>

          {/* data row */}
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3 flex-1 min-h-0">
            <Panel title={`Detections (${state.tracks.length})`}>
              <DetectionLog state={state} />
            </Panel>
            <Panel title="Event Timeline">
              <EventTimeline events={events} />
            </Panel>
            <Panel title="Thermal Analysis">
              <HeatPanel state={state} />
            </Panel>
            <div className="flex flex-col gap-3 min-h-0">
              <Panel title="Sensors">
                <SensorPanel diag={state.diagnostics} />
              </Panel>
              <Panel title="System Diagnostics">
                <DiagnosticsPanel state={state} />
              </Panel>
            </div>
          </div>

          {/* history + navigation row */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <Panel title="Alert History" className="max-h-64">
              <EventTimeline events={events} kinds={["alert"]} />
            </Panel>
            <Panel title="Recorded Incidents" className="max-h-64">
              <IncidentsPanel />
            </Panel>
            <Panel title="Navigation — position &amp; trail" className="max-h-64">
              <div className="flex items-start gap-3">
                <MiniMap state={state} />
                <div className="text-xs text-dim space-y-1 pt-1">
                  <div className="text-bright font-bold">
                    {state.nav.instruction}
                  </div>
                  <div>OBJECTIVE {state.nav.objective.toUpperCase()}</div>
                  <div>HEADING {Math.round(state.heading.deg)}° {state.heading.cardinal}</div>
                  <div>CRUMBS {state.nav.breadcrumbs.count}</div>
                  {state.nav.entry_distance_ft != null && (
                    <div>ENTRY {state.nav.entry_distance_ft} FT</div>
                  )}
                </div>
              </div>
            </Panel>
          </div>

          {/* command row */}
          <Panel title="Voice / Command Interface">
            <CommandBar onCommand={sendCommand} />
          </Panel>
        </>
      ) : (
        <div className="flex-1 flex items-center justify-center text-dim tracking-[0.3em] animate-alarm">
          {connected ? "SYNCING TELEMETRY…" : "WAITING FOR BACKEND (backend/run.py)…"}
        </div>
      )}
    </main>
  );
}
