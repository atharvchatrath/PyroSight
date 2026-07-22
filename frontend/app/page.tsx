"use client";

import Link from "next/link";
import { useTelemetry } from "@/lib/useTelemetry";

export default function Home() {
  const { state, connected } = useTelemetry();

  return (
    <main className="h-screen flex flex-col items-center justify-center gap-8 p-6">
      <div className="text-center">
        <h1 className="text-4xl font-bold tracking-[0.35em] text-bright">
          PYRO<span className="text-danger">SIGHT</span>
        </h1>
        <p className="mt-2 text-dim text-sm tracking-widest">
          AI SITUATIONAL AWARENESS — FIREFIGHTER PLATFORM v6
        </p>
      </div>

      <div className="flex items-center gap-3 text-sm">
        <span
          className={`inline-block w-3 h-3 rounded-full ${
            connected ? "bg-ok" : "bg-danger animate-alarm"
          }`}
        />
        <span className="text-dim">
          {connected
            ? `BACKEND ONLINE — ${state?.mode.toUpperCase() ?? ""} MODE · ${
                state?.fps ?? "—"
              } FPS`
            : "BACKEND OFFLINE — start backend/run.py"}
        </span>
      </div>

      <Link
        href="/live"
        className="panel px-8 py-4 text-center hover:border-warn transition-colors w-full max-w-2xl"
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
          className="panel p-8 text-center hover:border-accent transition-colors"
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
          className="panel p-8 text-center hover:border-ok transition-colors"
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
        className="text-dim text-xs tracking-widest hover:text-accent"
      >
        CALIBRATION WIZARD — pre-mission sensor check
      </Link>
    </main>
  );
}
