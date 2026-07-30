"use client";

import Link from "next/link";
import { useTelemetry } from "@/lib/useTelemetry";

export default function Home() {
  const { state, connected } = useTelemetry();

  return (
    <main className="h-screen flex flex-col items-center justify-center gap-8 p-6 animate-rise">
      <div className="text-center">
        <div className="relative inline-block">
          <div
            aria-hidden
            className="absolute inset-0 -z-10 blur-3xl opacity-30 bg-accent rounded-full scale-150"
          />
          <h1 className="text-5xl font-bold tracking-[0.35em] text-bright">
            PYRO<span className="text-danger">SIGHT</span>
          </h1>
        </div>
        <p className="mt-3 text-dim text-sm tracking-widest">
          AI SITUATIONAL AWARENESS — FIREFIGHTER PLATFORM v6
        </p>
      </div>

      <div
        className={`flex items-center gap-2.5 text-sm px-3.5 py-1.5 rounded-full border ${
          connected ? "border-ok/30 bg-ok/[0.06]" : "border-danger/30 bg-danger/[0.06]"
        }`}
      >
        <span className="relative flex w-2.5 h-2.5">
          {connected && (
            <span className="absolute inline-flex h-full w-full rounded-full bg-ok opacity-60 animate-ping" />
          )}
          <span
            className={`relative inline-flex rounded-full w-2.5 h-2.5 ${
              connected ? "bg-ok" : "bg-danger animate-alarm"
            }`}
          />
        </span>
        <span className={connected ? "text-bright" : "text-dim"}>
          {connected
            ? `BACKEND ONLINE — ${state?.mode.toUpperCase() ?? ""} MODE · ${
                state?.fps ?? "—"
              } FPS`
            : "BACKEND OFFLINE — start backend/run.py"}
        </span>
      </div>

      <Link
        href="/live"
        className="panel panel-hover px-8 py-4 text-center w-full max-w-2xl hover:border-warn/60"
      >
        <div className="text-lg font-bold text-warn tracking-widest">
          ▶ LIVE CAMERA TEST
        </div>
        <p className="mt-1 text-dim text-xs">
          Use this device&apos;s camera — real AI detection end to end
        </p>
      </Link>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-6 w-full max-w-2xl">
        <Link
          href="/hud"
          className="panel panel-hover p-8 text-center hover:border-accent/60"
        >
          <div className="text-2xl font-bold text-accent tracking-widest">
            HELMET HUD
          </div>
          <p className="mt-2 text-dim text-xs">
            Monocular display view — what the firefighter sees
          </p>
        </Link>
        <Link
          href="/dashboard"
          className="panel panel-hover p-8 text-center hover:border-ok/60"
        >
          <div className="text-2xl font-bold text-ok tracking-widest">
            COMMAND DASHBOARD
          </div>
          <p className="mt-2 text-dim text-xs">
            Incident command view — feeds, logs, diagnostics
          </p>
        </Link>
      </div>

      <Link
        href="/calibrate"
        className="text-dim text-xs tracking-widest hover:text-accent transition-colors"
      >
        CALIBRATION WIZARD — pre-mission sensor check
      </Link>
    </main>
  );
}
