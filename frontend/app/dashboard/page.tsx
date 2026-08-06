"use client";

// Command Dashboard — incident command's view of the same mission the helmet
// is flying. Feeds on the left, the people/egress/hazard picture in the
// middle, machine and mission state on the right. Same palette and the same
// confidence bands as the HUD, so a call made here means the same thing as a
// call made in the eyebox.

import Link from "next/link";
import VideoCanvas from "@/components/VideoCanvas";
import MiniMap from "@/components/hud/MiniMap";
import AssistantStack from "@/components/hud/AssistantStack";
import {
  AlertsPanel,
  DiagnosticsPanel,
  EventTimeline,
  HeatPanel,
  IncidentsPanel,
  MissionReplayPanel,
  Panel,
  SearchPanel,
  SensorPanel,
  TrackList,
} from "@/components/dashboard/Panels";
import { MODE_META, detectorLabel } from "@/lib/design";
import { missionClock } from "@/lib/format";
import { useMissionMode } from "@/lib/useMissionMode";
import { useTelemetry } from "@/lib/useTelemetry";
import Wordmark from "@/components/Wordmark";

export default function DashboardPage() {
  const { state, events, connected } = useTelemetry();
  const { mode, training, setTraining } = useMissionMode(state);
  const meta = MODE_META[mode];

  return (
    <main className="min-h-screen p-4 flex flex-col gap-4">
      {/* One row that degrades by DROPPING detail, not by wrapping. A header
          that reflows to a second line shoves the whole grid down and the
          mission clock lands in a different place on every screen — the one
          element an incident commander looks for without reading. */}
      <header className="panel flex items-center gap-3 xl:gap-4 px-4 py-3 overflow-hidden">
        <Wordmark size="md" />
        <span className="cap hidden lg:inline whitespace-nowrap">COMMAND DASHBOARD</span>

        <span
          className="flex items-center gap-2 border px-3 py-1 shrink-0 whitespace-nowrap"
          style={{ borderColor: `${meta.color}66`, background: `${meta.color}12` }}
        >
          <span className="w-1.5 h-1.5" style={{ background: meta.color }} />
          <span className="text-[12px] font-semibold tracking-wide2" style={{ color: meta.color }}>
            {meta.label}
          </span>
          <span className="cap hidden md:inline">{meta.hint}</span>
        </span>

        <span
          className={`text-[11px] tracking-wide2 px-2.5 py-1 border shrink-0 whitespace-nowrap ${
            connected ? "border-ok/60 text-ok" : "border-danger/70 text-danger animate-alarm"
          }`}
        >
          {connected ? "LINK OK" : "LINK DOWN"}
        </span>

        {state && (
          <>
            <span className="cap hidden xl:inline whitespace-nowrap">
              {state.mode.toUpperCase()} · {detectorLabel(state.detector)} · {state.fps.toFixed(0)} FPS
            </span>
            <span className="ml-auto shrink-0 text-[19px] font-semibold text-bright num tracking-hud">
              {missionClock(state.mission_time_s)}
            </span>
            <button className="btn btn-sm shrink-0 hidden md:inline-flex items-center" onClick={() => setTraining(!training)}>
              {training ? "TRAINING ON" : "TRAINING"}
            </button>
            <Link href="/live" className="btn btn-sm shrink-0 hidden sm:inline-flex items-center whitespace-nowrap">
              LIVE CAM →
            </Link>
            <Link href="/hud" className="btn btn-sm shrink-0 inline-flex items-center whitespace-nowrap">
              HUD VIEW →
            </Link>
          </>
        )}
      </header>

      {state ? (
        <>
          {/* ---- feeds ---- */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <Panel title="Fused view — HUD source" right={<span className="cap">PRIMARY</span>}>
              <VideoCanvas feed="fused" state={state} mode={mode} />
            </Panel>
            <Panel title="RGB feed">
              <VideoCanvas feed="rgb" state={state} mode={mode} />
            </Panel>
            <Panel
              title="Thermal feed"
              right={<span className="cap">{state.thermal_source?.toUpperCase()}</span>}
            >
              <VideoCanvas feed="thermal" state={state} showOverlay={false} showThermal={false} />
            </Panel>
          </div>

          {/* ---- situation ---- */}
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
            <div className="flex flex-col gap-4 min-h-0">
              <Panel
                title="People"
                right={
                  <span className="cap">{state.counts.persons} DETECTED</span>
                }
              >
                <TrackList state={state} category="person" empty="NO PEOPLE DETECTED" />
              </Panel>
              <Panel title="Egress — doors, exits, windows" right={<span className="cap">{state.counts.egress}</span>}>
                <TrackList state={state} category="egress" empty="NO EGRESS DETECTED" />
              </Panel>
              <Panel title="Hazards" right={<span className="cap">{state.counts.hazards}</span>}>
                <TrackList state={state} category="hazard" empty="NO HAZARDS DETECTED" />
              </Panel>
            </div>

            <div className="flex flex-col gap-4 min-h-0">
              <Panel title="Active alerts" className="max-h-72">
                <AlertsPanel state={state} />
              </Panel>
              <Panel title="AI event log" className="max-h-[26rem]">
                <EventTimeline events={events} />
              </Panel>
            </div>

            <div className="flex flex-col gap-4 min-h-0">
              <Panel title="Orientation & trail">
                <div className="flex items-start gap-4">
                  <MiniMap state={state} size={160} />
                  <div className="space-y-1.5">
                    <div className="text-[13px] text-bright tracking-hud">
                      {state.nav.instruction}
                    </div>
                    <div className="cap">OBJECTIVE {state.nav.objective.replace(/_/g, " ")}</div>
                    <div className="cap">
                      HEADING {Math.round(state.heading.deg)}° {state.heading.cardinal}
                    </div>
                    <div className="cap">CRUMBS {state.nav.breadcrumbs.count}</div>
                    {state.nav.entry_distance_ft != null && (
                      <div className="cap">ENTRY {state.nav.entry_distance_ft} FT</div>
                    )}
                    <div className="cap">
                      VISIBILITY {state.smoke.visibility} · SMOKE{" "}
                      {Math.round(state.smoke.density * 100)}%
                    </div>
                  </div>
                </div>
              </Panel>
              <Panel title="Thermal analysis">
                <HeatPanel state={state} />
              </Panel>
              <Panel title="Search coverage">
                <SearchPanel state={state} />
              </Panel>
            </div>
          </div>

          {/* ---- machine ---- */}
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
            <Panel title="System diagnostics" className="xl:col-span-2">
              <DiagnosticsPanel state={state} />
            </Panel>
            <Panel title="Sensor health">
              <SensorPanel diag={state.diagnostics} />
            </Panel>
          </div>

          {/* ---- record & replay ---- */}
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
            <Panel title="Alert history" className="max-h-64">
              <EventTimeline events={events} kinds={["alert"]} />
            </Panel>
            <Panel title="Mission replay / training" className="max-h-64">
              <MissionReplayPanel />
            </Panel>
            <Panel title="Recorded incidents" className="max-h-64">
              <IncidentsPanel />
            </Panel>
          </div>


          {/* assistant cards mirror the helmet, bottom-right */}
          <div className="fixed bottom-5 right-5 z-30">
            <AssistantStack message={state.assistant} />
          </div>
        </>
      ) : (
        <div className="flex-1 flex items-center justify-center">
          <span className="cap animate-breathe">
            {connected ? "SYNCING TELEMETRY" : "WAITING FOR BACKEND — backend/run.py"}
          </span>
        </div>
      )}
    </main>
  );
}
