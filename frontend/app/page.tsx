"use client";

import Link from "next/link";
import { useTelemetry } from "@/lib/useTelemetry";

export default function Home() {
  const { state, connected } = useTelemetry();

  return (
    <main className="h-screen flex flex-col items-center justify-center gap-9 p-6">
      <div className="text-center animate-riseIn">
        <h1 className="text-[42px] font-semibold tracking-[0.32em] text-bright leading-none">
          PYRO<span className="text-danger">SIGHT</span>
        </h1>
        <p className="mt-3 cap">AI SITUATIONAL AWARENESS — FIREFIGHTER PLATFORM</p>
      </div>

      <div className="panel-float flex items-center gap-3 px-4 py-2 text-sm animate-riseIn">
        <span
          className={`inline-block w-2.5 h-2.5 rounded-full ${
            connected ? "bg-ok" : "bg-danger animate-alarm"
          }`}
          style={connected ? { boxShadow: "0 0 10px #4ade80" } : undefined}
        />
        <span className="text-dim text-[13px] tracking-hud">
          {connected
            ? `BACKEND ONLINE — ${state?.mode.toUpperCase() ?? ""} · ${
                state?.fps?.toFixed(0) ?? "—"
              } FPS`
            : "BACKEND OFFLINE — start backend/run.py"}
        </span>
      </div>

      <Link
        href="/live"
        className="panel px-8 py-5 text-center w-full max-w-2xl transition-all duration-300 ease-hud
          hover:border-warn/60 hover:-translate-y-0.5 animate-riseIn"
      >
        <div className="text-lg font-semibold text-warn tracking-wide2">▶ LIVE CAMERA TEST</div>
        <p className="mt-1.5 text-dim text-xs tracking-hud">
          Use this device&apos;s camera — real AI detection end to end
        </p>
      </Link>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-5 w-full max-w-2xl">
        <Link
          href="/hud"
          className="panel p-8 text-center transition-all duration-300 ease-hud
            hover:border-nav/60 hover:-translate-y-0.5 animate-riseIn"
        >
          <div className="text-[22px] font-semibold text-nav tracking-wide2">HELMET HUD</div>
          <p className="mt-2 text-dim text-xs tracking-hud">
            Monocular display — what the firefighter sees
          </p>
        </Link>
        <Link
          href="/dashboard"
          className="panel p-8 text-center transition-all duration-300 ease-hud
            hover:border-ok/60 hover:-translate-y-0.5 animate-riseIn"
        >
          <div className="text-[22px] font-semibold text-ok tracking-wide2">COMMAND DASHBOARD</div>
          <p className="mt-2 text-dim text-xs tracking-hud">
            Incident command — feeds, logs, diagnostics
          </p>
        </Link>
      </div>

      <Link href="/calibrate" className="cap hover:text-nav transition-colors">
        CALIBRATION WIZARD — PRE-MISSION SENSOR CHECK
      </Link>
    </main>
  );
}
