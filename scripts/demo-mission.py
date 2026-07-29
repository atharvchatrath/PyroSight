#!/usr/bin/env python3
"""
PyroSight mission demo — drives the real platform through a scripted incident.

This is NOT a mock: it talks to the running backend over the same REST/
WebSocket API the helmet unit uses, issues the same voice-command intents a
firefighter would speak, and reads back the live telemetry the HUD renders.
Every number printed is produced by the real perception pipeline (temporal
tracker, RGB+thermal fusion, navigation, alert engine, incident recorder).

Usage — with the backend running (scripts/run-sim.sh):

    .venv/bin/python scripts/demo-mission.py

Narrates each mission phase so an observer can follow what the system is
doing and why, and ends with the recorded-incident summary.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

API = "http://localhost:8000"


# --- terminal formatting (no emoji; readable in any log) --------------------

BOLD, DIM, CYAN, GREEN, YELLOW, RED, RESET = (
    "\033[1m", "\033[2m", "\033[36m", "\033[32m", "\033[33m", "\033[31m", "\033[0m")


def phase(n: int, title: str, why: str) -> None:
    print(f"\n{BOLD}{CYAN}[ PHASE {n} ] {title}{RESET}")
    print(f"{DIM}   {why}{RESET}")


def line(label: str, value: str, color: str = "") -> None:
    print(f"   {label.ljust(22)} {color}{value}{RESET}")


def get(path: str):
    with urllib.request.urlopen(f"{API}{path}", timeout=5) as r:
        return json.load(r)


def command(text: str) -> dict:
    req = urllib.request.Request(
        f"{API}/api/command",
        data=json.dumps({"text": text}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.load(r)


def speak(text: str) -> None:
    """Issue a voice command through the real offline grammar."""
    ack = command(text)
    status = GREEN if ack.get("ok") else RED
    print(f'   {DIM}operator says:{RESET} "{text}"')
    line("system ack", ack.get("ack", "?"), status)


def snapshot(state: dict) -> None:
    tracks = state["tracks"]
    line("mode / detector", f"{state['mode'].upper()} / {state['detector'].upper()}")
    line("throughput", f"{state['fps']:.1f} FPS, "
                       f"{state['diagnostics']['latency_ms']:.0f} ms/frame")
    vis = state["smoke"]["visibility"]
    vis_color = GREEN if vis in ("GOOD",) else YELLOW if vis == "REDUCED" else RED
    line("visibility", f"{vis} (smoke {state['smoke']['density'] * 100:.0f}%)", vis_color)
    line("heading", f"{state['heading']['deg']:.0f} deg {state['heading']['cardinal']}")
    if state.get("thermal"):
        t = state["thermal"]
        line("thermal field", f"{t['min_c']:.0f}-{t['max_c']:.0f} C "
                              f"(source: {state['thermal_source']})")
    if not tracks:
        line("tracks", "none confirmed", DIM)
    for t in sorted(tracks, key=lambda x: -x["priority"])[:6]:
        marks = []
        if t.get("thermal_confirmed"):
            marks.append("thermal-confirmed")
        elif t.get("corroborated"):
            marks.append("corroborated")
        if t["max_temp_c"] is not None:
            marks.append(f"{t['max_temp_c']:.0f} C")
        if t["dist_ft"] is not None:
            marks.append(f"{t['dist_ft']:.0f} ft")
        tier_color = (GREEN if t["tier"] == "confirmed"
                      else YELLOW if t["tier"] == "likely" else RED)
        line(f"  {t['display']}",
             f"{t['conf'] * 100:.0f}%  {DIM}{' · '.join(marks)}{RESET}", tier_color)


def guidance(state: dict) -> None:
    nav = state["nav"]
    status_color = {"CLEAR": GREEN, "CAUTION": YELLOW, "BLOCKED": RED}[nav["status"]]
    line("objective", nav["objective"].replace("_", " ").upper())
    line("route status", nav["status"], status_color)
    line("HUD instruction", nav["instruction"], BOLD)
    if nav["target"]:
        tgt = nav["target"]
        src = tgt["source"]
        line("nav target", f"{tgt['kind'].upper()} at "
                           f"{tgt['rel_bearing_deg']:+.0f} deg"
                           + (f", {tgt['dist_ft']:.0f} ft" if tgt["dist_ft"] else "")
                           + f"  {DIM}({src}){RESET}")
    bc = nav["breadcrumbs"]
    line("breadcrumb trail", f"{bc['count']} crumbs"
         + (f", entry {nav['entry_distance_ft']} ft back"
            if nav.get("entry_distance_ft") else ""))
    if state.get("assistant"):
        line("AI assistant", f'"{state["assistant"]}"', CYAN)
    if state.get("emergency"):
        line("EMERGENCY MODE", "ENGAGED — HUD brightened, clutter reduced", RED)


def wait(seconds: float, note: str = "") -> None:
    if note:
        print(f"   {DIM}...{note} ({seconds:.0f}s){RESET}")
    time.sleep(seconds)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--speed", type=float, default=1.0,
                    help="time multiplier (0.5 = twice as fast)")
    args = ap.parse_args()
    s = args.speed

    try:
        health = get("/api/health")
    except (urllib.error.URLError, OSError):
        print(f"{RED}Backend not reachable at {API}.{RESET}")
        print("Start it first:  bash scripts/run-sim.sh")
        return 1

    print("=" * 72)
    print(f"{BOLD} PYROSIGHT — MISSION DEMONSTRATION{RESET}")
    print("=" * 72)
    print(f"{DIM} Backend {health['status']} | mode {health['mode']} | "
          f"detector {health['detector']}{RESET}")
    print(f"{DIM} Every value below comes from the live perception pipeline.{RESET}")

    # ---------------------------------------------------------------- 1
    phase(1, "ARRIVAL AND SIZE-UP",
          "Unit powers on at the entry point. The system starts logging the "
          "incident, drops its first breadcrumb, and begins scanning.")
    speak("mark entry")
    wait(4 * s, "scanning the structure")
    snapshot(get("/api/state"))
    guidance(get("/api/state"))

    # ---------------------------------------------------------------- 2
    phase(2, "PRIMARY SEARCH",
          "Firefighter begins a guided room search. Coverage is tracked so "
          "no area is left unswept.")
    speak("search room")
    wait(8 * s, "advancing into the structure")
    st = get("/api/state")
    snapshot(st)
    guidance(st)
    sc = st.get("search", {})
    if sc.get("active"):
        line("search coverage", f"{sc['coverage_pct']}% swept, "
                                f"{sc['needs_pass']} cells need another pass")

    # ---------------------------------------------------------------- 3
    phase(3, "VICTIM LOCATION",
          "Operator switches the objective to victim search. Guidance now "
          "vectors to the strongest person track, thermally corroborated.")
    speak("locate person")
    wait(8 * s, "sweeping for occupants")
    st = get("/api/state")
    snapshot(st)
    guidance(st)

    # ---------------------------------------------------------------- 4
    phase(4, "HAZARD ENCOUNTER",
          "As the fire grows, the route-safety check finds heat inside the "
          "forward cone and degrades the route. Watch the instruction change.")
    wait(10 * s, "conditions deteriorating")
    st = get("/api/state")
    snapshot(st)
    guidance(st)
    alerts = [e for e in get("/api/events?limit=200") if e["kind"] == "alert"]
    if alerts:
        print(f"\n   {BOLD}Alerts raised so far:{RESET}")
        for a in alerts[-6:]:
            col = {"critical": RED, "warning": YELLOW}.get(a.get("severity"), DIM)
            print(f"     {col}{a.get('severity', '').upper().ljust(8)}{RESET} "
                  f"{a.get('text', '')}")

    # ---------------------------------------------------------------- 5
    phase(5, "EGRESS UNDER EMERGENCY",
          "Operator declares an emergency. The HUD brightens, strips "
          "non-essential overlays, and prioritises the nearest known exit.")
    speak("emergency mode")
    speak("find exit")
    wait(6 * s, "moving to egress")
    st = get("/api/state")
    snapshot(st)
    guidance(st)

    # ---------------------------------------------------------------- 6
    phase(6, "RETURN TO ENTRY",
          "Objective switches to the breadcrumb trail — guidance walks the "
          "known-safe path back rather than cutting through unexplored space.")
    speak("cancel emergency")
    speak("return to entry")
    wait(6 * s, "following the trail out")
    st = get("/api/state")
    guidance(st)

    # ---------------------------------------------------------------- 7
    phase(7, "AFTER-ACTION RECORD",
          "The whole incident was written to disk as it happened — available "
          "for mission replay and training review.")
    speak("stand down")
    incidents = get("/api/incidents")
    if incidents:
        cur = incidents[0]
        line("incident id", cur["id"])
        line("events recorded", str(cur["events"]))
        line("snapshots saved", str(cur["snapshots"]))
        events = get(f"/api/incidents/{cur['id']}?limit=400")
        kinds: dict = {}
        for e in events:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        line("event breakdown", ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
    diag = get("/api/state")["diagnostics"]
    line("mission duration", f"{get('/api/state')['mission_time_s']} s")
    line("system load", f"CPU {diag['cpu_percent']}%, memory {diag['mem_percent']}%")
    line("power", f"battery {diag['battery_percent']}%"
                  + (f", ~{diag['runtime_min']} min remaining"
                     if diag.get("runtime_min") else ""))

    print("\n" + "=" * 72)
    print(f"{BOLD} DEMONSTRATION COMPLETE{RESET}")
    print("=" * 72)
    print(" Live views of this same session:")
    print("   Helmet HUD        http://localhost:3100/hud")
    print("   Command dashboard http://localhost:3100/dashboard")
    print("   Mission replay    dashboard -> Mission Replay / Training panel")
    return 0


if __name__ == "__main__":
    sys.exit(main())
