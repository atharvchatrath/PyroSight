"use client";

// Front door.
//
// Whoever opens this is deciding what PyroSight is in about four seconds, and
// they are almost never a firefighter — they are an investor, a chief, or a
// procurement officer. So this page leads with the problem and the claim, not
// with a menu of routes. The numbers along the bottom are the argument: the
// left half is what the platform IS (offline, $800, on-device), the right half
// is what it is DOING right now, read live off the running backend.
//
// That live half matters more than it looks. Anyone can print "real-time" on a
// slide. A frame rate that ticks while you watch it is the demo.

import Link from "next/link";
import { detectorLabel } from "@/lib/design";
import { useTelemetry } from "@/lib/useTelemetry";

const CAPABILITIES = [
  {
    title: "Sees through the smoke",
    body: "Thermal and RGB fused frame by frame. Body heat behind a smoke layer the camera cannot penetrate still reads as a human.",
  },
  {
    title: "Commits to an answer",
    body: "Mutually-exclusive classes never both claim the same pixels. A wall opening resolves to one thing, weighted by the cost of being wrong.",
  },
  {
    title: "Says when it isn't sure",
    body: "Corroborated calls are made plainly. Everything else renders as POSSIBLE — dashed, dimmed, never authoritative.",
  },
  {
    title: "Runs with no signal",
    body: "Every model is on the helmet. No cloud, no uplink, nothing to lose when the building does what buildings do.",
  },
];

function Stat({
  value,
  label,
  live = false,
}: {
  value: string;
  label: string;
  live?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1">
      <div
        className="text-[26px] leading-none font-semibold num tracking-tight"
        style={{ color: live ? "#ff8a1f" : "#ffeedd" }}
      >
        {value}
      </div>
      <div className="cap">{label}</div>
    </div>
  );
}

export default function Home() {
  const { state, connected } = useTelemetry();

  const fps = state?.fps ? state.fps.toFixed(0) : "—";
  const latency = state?.diagnostics?.latency_ms
    ? `${Math.round(state.diagnostics.latency_ms)}`
    : "—";
  const detector = detectorLabel(state?.detector);

  return (
    <main className="min-h-screen">
      {/* Ember light from below — the only decorative element on the page, and
          it earns its place by making a pure-black screen feel like a room
          with a fire in it rather than an unpainted background. */}
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 -z-10"
        style={{
          background:
            "radial-gradient(120% 80% at 50% 118%, rgba(255,106,0,0.22) 0%, rgba(255,59,15,0.09) 38%, rgba(10,6,3,0) 72%)",
        }}
      />

      {/* ---------------------------------------------------------- header */}
      <header className="flex items-center justify-between gap-4 px-6 sm:px-10 py-5 border-b border-edge">
        <div className="flex items-baseline gap-3">
          <span className="text-[19px] font-semibold tracking-[0.3em] text-bright">
            PYRO<span style={{ color: "#ff6a00" }}>SIGHT</span>
          </span>
        </div>
        <div className="flex items-center gap-2.5">
          <span
            className={`inline-block w-1.5 h-1.5 rounded-full ${
              connected ? "" : "animate-alarm"
            }`}
            style={{
              background: connected ? "#ff8a1f" : "#ff3b0f",
              boxShadow: connected ? "0 0 9px #ff8a1f" : undefined,
            }}
          />
          <span className="cap">
            {connected ? `${detector} · ${fps} FPS` : "BACKEND OFFLINE"}
          </span>
        </div>
      </header>

      {/* ------------------------------------------------------------ hero */}
      {/* Not vertically centred inside the viewport: centring pushed the
          capability row entirely below the fold and left the hero floating in
          dead space. A pitch page should show its claim AND signal that there
          is more underneath it. */}
      <section className="px-6 sm:px-10 pt-12 sm:pt-16 pb-12 max-w-[1180px] w-full mx-auto">
        <p className="cap animate-riseIn" style={{ color: "#ff8a1f" }}>
          Wearable AI for the fireground
        </p>

        <h1
          className="mt-4 animate-riseIn font-semibold text-bright"
          style={{
            fontSize: "clamp(2.4rem, 6.4vw, 4.6rem)",
            lineHeight: 1.02,
            letterSpacing: "-0.02em",
          }}
        >
          Nobody should have to
          <br />
          search a burning building
          <br />
          <span style={{ color: "#ff6a00" }}>by touch.</span>
        </h1>

        <p className="mt-7 max-w-[46rem] text-[15px] sm:text-[16.5px] leading-relaxed text-dim animate-riseIn">
          Inside a working fire, visibility goes to zero in seconds. Crews
          navigate by feel, count doorways to find their way back out, and can
          pass within arm&apos;s reach of an unconscious victim without knowing
          it. PyroSight puts thermal and computer vision into the helmet — it
          finds humans, exits and fire in real time, points the way out, and is
          honest about what it does not know.
        </p>

        {/* -------------------------------------------------------- actions */}
        <div className="mt-10 flex flex-wrap items-stretch gap-3 animate-riseIn">
          <Link
            href="/live"
            className="group inline-flex items-center justify-center gap-3 min-h-[54px] px-7
              text-[13px] font-semibold tracking-hud whitespace-nowrap
              transition-all duration-300 ease-hud hover:-translate-y-[1px]"
            style={{ background: "#ff6a00", color: "#150d06" }}
          >
            RUN THE LIVE DEMO
            <span className="transition-transform duration-300 ease-hud group-hover:translate-x-1">
              →
            </span>
          </Link>
          <Link
            href="/hud"
            className="btn inline-flex items-center justify-center min-h-[54px] text-[13px] whitespace-nowrap"
          >
            HELMET HUD
          </Link>
          <Link
            href="/dashboard"
            className="btn inline-flex items-center justify-center min-h-[54px] text-[13px] whitespace-nowrap"
          >
            COMMAND DASHBOARD
          </Link>
        </div>

        <p className="mt-4 text-[12.5px] leading-relaxed text-dim max-w-[40rem]">
          The live demo runs the real pipeline on this device&apos;s camera.
          Nothing is pre-recorded.
        </p>

        {/* ---------------------------------------------------------- stats */}
        <div className="mt-12 pt-8 border-t border-edge grid grid-cols-2 sm:grid-cols-4 gap-8 sm:gap-6 animate-riseIn">
          <Stat value="$800" label="Hardware, per helmet" />
          <Stat value="100%" label="On-device · no network" />
          <Stat value={fps} label="Frames / sec, live" live />
          <Stat value={latency === "—" ? "—" : `${latency}ms`} label="Pipeline latency" live />
        </div>
      </section>

      {/* ---------------------------------------------------- capabilities */}
      <section className="border-t border-edge">
        <div className="max-w-[1180px] w-full mx-auto px-6 sm:px-10 py-12 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-px bg-edge">
          {CAPABILITIES.map((c) => (
            <div key={c.title} className="bg-ink p-6 sm:p-7 flex flex-col gap-2.5">
              <h2 className="text-[14px] font-semibold tracking-hud text-bright">
                {c.title}
              </h2>
              <p className="text-[13px] leading-relaxed text-dim">{c.body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ---------------------------------------------------------- footer */}
      <footer className="border-t border-edge">
        <div className="max-w-[1180px] w-full mx-auto px-6 sm:px-10 py-6 flex flex-wrap items-center gap-x-6 gap-y-2">
          <span className="cap">
            Raspberry Pi 5 · FLIR Lepton 3.5 · Camera Module 3 · BNO085
          </span>
          <Link
            href="/calibrate"
            className="cap ml-auto hover:text-bright transition-colors"
          >
            Calibration wizard →
          </Link>
        </div>
      </footer>
    </main>
  );
}
