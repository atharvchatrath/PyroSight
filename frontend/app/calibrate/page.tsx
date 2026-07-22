"use client";

// Calibration Wizard — guided pre-mission verification of every sensor and
// the HUD. Reads live sensor health from telemetry to auto-verify steps that
// can be checked in software (camera producing frames, thermal present, IMU
// heading responding); the physical-alignment steps are manual confirmations.
// Designed glove-friendly: large targets, one step at a time.

import Link from "next/link";
import { useMemo, useState } from "react";
import { useTelemetry } from "@/lib/useTelemetry";
import { SystemState } from "@/lib/types";

interface Step {
  id: string;
  title: string;
  instruction: string;
  auto: (s: SystemState) => "pass" | "fail" | "manual";
  detail: (s: SystemState) => string;
}

const STEPS: Step[] = [
  {
    id: "camera",
    title: "RGB Camera",
    instruction:
      "Confirm the RGB feed is live and in focus. Point at a high-contrast scene.",
    auto: (s) => {
      const cam = s.diagnostics.sensors.rgb;
      if (!cam) return "fail";
      return cam.status === "ok" || cam.status === "simulated" ? "pass" : "fail";
    },
    detail: (s) => s.diagnostics.sensors.rgb?.detail ?? "no camera",
  },
  {
    id: "thermal",
    title: "Thermal Camera",
    instruction:
      "Confirm the Lepton is delivering radiometric frames. A warm hand should read hot.",
    auto: (s) => {
      const th = s.diagnostics.sensors.thermal;
      if (!th) return "fail";
      if (th.status === "estimated") return "manual";
      return th.status === "ok" || th.status === "simulated" ? "pass" : "fail";
    },
    detail: (s) => s.diagnostics.sensors.thermal?.detail ?? "no thermal",
  },
  {
    id: "thermal_align",
    title: "Thermal ↔ RGB Alignment",
    instruction:
      "Point at a warm object with a sharp visual edge (a lamp). Confirm the hot region in the thermal feed lines up with the object in the RGB feed. Adjust the mount if offset.",
    auto: () => "manual",
    detail: () => "Visual check on the dashboard fused view.",
  },
  {
    id: "imu",
    title: "IMU / Heading",
    instruction:
      "Rotate your head slowly left then right. The compass heading should track smoothly.",
    auto: (s) => {
      const imu = s.diagnostics.sensors.imu;
      if (!imu) return "fail";
      if (imu.status === "estimated") return "manual";
      return imu.status === "ok" || imu.status === "simulated" ? "pass" : "fail";
    },
    detail: (s) =>
      `heading ${Math.round(s.heading.deg)}° ${s.heading.cardinal} · ${
        s.diagnostics.sensors.imu?.detail ?? ""
      }`,
  },
  {
    id: "hud",
    title: "HUD Positioning",
    instruction:
      "Confirm the full HUD frame is visible in the monocular eyepiece with no clipping. Adjust the combiner arm until corners are readable.",
    auto: () => "manual",
    detail: () => "Physical eyepiece adjustment.",
  },
  {
    id: "alerts",
    title: "Sensor & Alert Verification",
    instruction:
      "Confirm the ESP32 alert channel: trigger a test alert and verify LED, buzzer, and haptic fire together.",
    auto: (s) => {
      const anyOffline = Object.values(s.diagnostics.sensors).some(
        (x) => x.status === "offline"
      );
      return anyOffline ? "fail" : "pass";
    },
    detail: (s) =>
      Object.entries(s.diagnostics.sensors)
        .map(([k, v]) => `${k}:${v.status}`)
        .join("  "),
  },
];

const RESULT_STYLE: Record<string, string> = {
  pass: "text-ok border-ok",
  fail: "text-danger border-danger",
  manual: "text-warn border-warn",
};

export default function CalibratePage() {
  const { state, connected } = useTelemetry();
  const [step, setStep] = useState(0);
  const [confirmed, setConfirmed] = useState<Record<string, boolean>>({});

  const current = STEPS[step];
  const autoResult = useMemo(
    () => (state ? current.auto(state) : "fail"),
    [state, current]
  );
  const done = autoResult === "pass" || confirmed[current.id];

  if (!state) {
    return (
      <main className="h-screen flex items-center justify-center text-dim tracking-[0.3em] animate-alarm">
        {connected ? "SYNCING…" : "WAITING FOR BACKEND…"}
      </main>
    );
  }

  return (
    <main className="min-h-screen p-6 flex flex-col gap-6 max-w-3xl mx-auto">
      <header className="flex items-center gap-4">
        <Link href="/" className="text-xl font-bold tracking-[0.3em] text-bright">
          PYRO<span className="text-danger">SIGHT</span>
        </Link>
        <span className="text-dim text-xs tracking-widest">CALIBRATION WIZARD</span>
        <Link href="/dashboard" className="btn text-xs ml-auto">
          DASHBOARD →
        </Link>
      </header>

      {/* progress */}
      <div className="flex gap-2">
        {STEPS.map((s, i) => (
          <div
            key={s.id}
            className={`flex-1 h-2 rounded ${
              i < step
                ? "bg-ok"
                : i === step
                ? "bg-accent"
                : "bg-edge"
            }`}
          />
        ))}
      </div>

      <section className="panel p-6 flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <h2 className="text-2xl font-bold text-bright">
            {step + 1}. {current.title}
          </h2>
          <span
            className={`text-sm px-3 py-1 rounded border ${RESULT_STYLE[autoResult]}`}
          >
            {autoResult === "pass"
              ? "AUTO-VERIFIED"
              : autoResult === "fail"
              ? "CHECK FAILED"
              : "MANUAL CHECK"}
          </span>
        </div>
        <p className="text-dim text-lg leading-relaxed">{current.instruction}</p>
        <div className="text-xs text-dim font-mono border-t border-edge pt-2">
          {current.detail(state)}
        </div>

        {autoResult !== "pass" && (
          <label className="flex items-center gap-3 text-bright cursor-pointer select-none">
            <input
              type="checkbox"
              className="w-6 h-6 accent-ok"
              checked={!!confirmed[current.id]}
              onChange={(e) =>
                setConfirmed((c) => ({ ...c, [current.id]: e.target.checked }))
              }
            />
            I have verified this step
          </label>
        )}
      </section>

      <div className="flex items-center justify-between">
        <button
          className="btn"
          disabled={step === 0}
          onClick={() => setStep((s) => Math.max(0, s - 1))}
        >
          ← BACK
        </button>
        <span className="text-dim text-sm">
          Step {step + 1} of {STEPS.length}
        </span>
        {step < STEPS.length - 1 ? (
          <button
            className={`btn ${done ? "border-ok text-ok" : ""}`}
            disabled={!done}
            onClick={() => setStep((s) => s + 1)}
          >
            NEXT →
          </button>
        ) : (
          <Link
            href="/hud"
            className={`btn ${done ? "border-ok text-ok" : "pointer-events-none opacity-40"}`}
          >
            FINISH — GO LIVE →
          </Link>
        )}
      </div>
    </main>
  );
}
