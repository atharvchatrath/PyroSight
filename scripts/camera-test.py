#!/usr/bin/env python3
"""
PyroSight camera test — measured accuracy validation on real hardware.

This is not a demonstration. It runs the live perception pipeline against
your actual cameras and reports MEASURED accuracy, including the numbers that
are usually left unmeasured:

  1. Throughput      — real FPS, frame latency, detector inference time.
  2. False positives — point the camera at an ordinary room with no people
                       and no fire; anything the system reports here is a
                       false positive, counted and named.
  3. Detection recall — you place a known object (person, door, exit sign) in
                       view and confirm; the tool records whether the system
                       found it and at what confidence.
  4. Range accuracy  — you enter the true distance (tape measure); the tool
                       compares it against the reported range and reports the
                       error and whether it came from stereo or mono.
  5. Thermal check   — verifies the Lepton reports plausible temperatures for
                       a known warm target (your hand).

Run it with the backend already up and pointed at real hardware:

    # on the Pi
    sudo systemctl start pyrosight-backend
    .venv/bin/python scripts/camera-test.py

    # or on a laptop, driving the browser camera at /live
    PYROSIGHT_MODE=live PYROSIGHT_RGB_SOURCE=browser .venv/bin/python backend/run.py
    .venv/bin/python scripts/camera-test.py

Results are written to backend/data/camera_test_<timestamp>.json so runs can
be compared after a change.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "http://localhost:8000"
BOLD, DIM, GREEN, YELLOW, RED, CYAN, RESET = (
    "\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[31m", "\033[36m", "\033[0m")

FEET_PER_M = 3.28084
results: dict = {"started": time.time(), "sections": {}}


def get(path: str):
    with urllib.request.urlopen(f"{API}{path}", timeout=5) as r:
        return json.load(r)


def hdr(title: str) -> None:
    print(f"\n{BOLD}{CYAN}{title}{RESET}")
    print(f"{DIM}{'-' * len(title)}{RESET}")


def row(label: str, value: str, color: str = "") -> None:
    print(f"  {label.ljust(26)} {color}{value}{RESET}")


def verdict(ok: bool, text: str) -> None:
    print(f"  {(GREEN + '[PASS]') if ok else (RED + '[FAIL]')}{RESET} {text}")


NON_INTERACTIVE = False
WINDOW = 1.0


def ask(prompt: str) -> str:
    """Prompt the operator. In --quick / piped runs there is nobody to answer,
    so proceed rather than aborting the whole test."""
    if NON_INTERACTIVE or not sys.stdin.isatty():
        print(f"{DIM}  > {prompt}(auto-continue){RESET}")
        return ""
    try:
        return input(f"{YELLOW}  ?{RESET} {prompt}").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit(130)


def sample(seconds: float, hz: float = 5.0) -> list:
    """Collect telemetry snapshots over a window."""
    out = []
    deadline = time.time() + seconds * WINDOW
    while time.time() < deadline:
        try:
            out.append(get("/api/state"))
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(1.0 / hz)
    return out


# --------------------------------------------------------------------------

def section_environment() -> bool:
    hdr("1. ENVIRONMENT")
    st = get("/api/state")
    sensors = st["diagnostics"]["sensors"]
    rgb = sensors.get("rgb", {})
    row("mode", st["mode"].upper())
    row("detector", st["detector"].upper())
    row("RGB source", f"{rgb.get('name', '?')} — {rgb.get('detail', '')}")
    row("thermal source", st.get("thermal_source", "?").upper())
    row("frame size", f"{st['frame']['w']}x{st['frame']['h']}")

    live = st["mode"] == "live"
    simulated = rgb.get("status") == "simulated"
    if simulated or not live:
        print(f"\n  {RED}This run is using SIMULATED imagery.{RESET}")
        print(f"  {DIM}A camera test must run against a real sensor. Either:{RESET}")
        print(f"  {DIM}  - on the Pi:  PYROSIGHT_RGB_SOURCE=auto (stereo/CSI camera), or{RESET}")
        print(f"  {DIM}  - on a laptop: start the backend with RGB_SOURCE=browser and{RESET}")
        print(f"  {DIM}    open http://localhost:3100/live, press START CAMERA, then rerun.{RESET}")
        results["sections"]["environment"] = {"live": False}
        return False
    results["sections"]["environment"] = {
        "live": True, "rgb": rgb.get("name"), "detector": st["detector"],
        "thermal_source": st.get("thermal_source")}
    verdict(True, "live sensor imagery confirmed")
    return True


def section_throughput() -> None:
    hdr("2. THROUGHPUT (10 s window)")
    print(f"  {DIM}Move the camera around normally while this samples.{RESET}")
    snaps = sample(10.0)
    if not snaps:
        verdict(False, "no telemetry received")
        return
    fps = [s["fps"] for s in snaps]
    lat = [s["diagnostics"]["latency_ms"] for s in snaps]
    inf = [s["inference"]["ms"] for s in snaps if s["inference"].get("ms")]
    row("FPS", f"mean {statistics.mean(fps):.1f}, min {min(fps):.1f}")
    row("frame latency", f"mean {statistics.mean(lat):.0f} ms, "
                        f"max {max(lat):.0f} ms")
    if inf:
        row("detector inference", f"mean {statistics.mean(inf):.0f} ms, "
                                 f"max {max(inf):.0f} ms")
    cpu = [s["diagnostics"]["cpu_percent"] for s in snaps
           if s["diagnostics"].get("cpu_percent") is not None]
    if cpu:
        row("CPU", f"mean {statistics.mean(cpu):.0f}%, peak {max(cpu):.0f}%")
    temp = snaps[-1]["diagnostics"].get("cpu_temp_c")
    if temp:
        row("CPU temperature", f"{temp:.0f} C",
            GREEN if temp < 70 else YELLOW if temp < 80 else RED)
    results["sections"]["throughput"] = {
        "fps_mean": statistics.mean(fps), "fps_min": min(fps),
        "latency_ms_mean": statistics.mean(lat),
        "inference_ms_mean": statistics.mean(inf) if inf else None}
    verdict(statistics.mean(fps) >= 12.0,
            f"sustained {statistics.mean(fps):.1f} FPS (target >= 15, floor 12)")


def section_false_positives() -> None:
    hdr("3. FALSE POSITIVES (20 s window)")
    print(f"  {DIM}Point the camera at an ordinary scene with NO people and{RESET}")
    print(f"  {DIM}NO fire. Anything reported below is a false positive.{RESET}")
    ask("Camera aimed at an empty scene? [Enter] ")
    snaps = sample(20.0)
    seen: dict = {}
    for s in snaps:
        for t in s["tracks"]:
            key = t["cls"]
            entry = seen.setdefault(key, {"frames": 0, "max_conf": 0.0,
                                          "tiers": set()})
            entry["frames"] += 1
            entry["max_conf"] = max(entry["max_conf"], t["conf"])
            entry["tiers"].add(t["tier"])
    total = max(1, len(snaps))
    # People and fire are unambiguous false positives in an empty scene.
    # Doors/windows/hallways may legitimately be present, so they are noted
    # rather than counted as errors.
    critical = {"person", "firefighter", "fire", "hotspot"}
    bad = {k: v for k, v in seen.items() if k in critical}
    structural = {k: v for k, v in seen.items() if k not in critical}
    if structural:
        row("structure seen", ", ".join(
            f"{k} ({v['frames'] * 100 // total}% of frames)"
            for k, v in structural.items()), DIM)
    if not bad:
        verdict(True, "no false people, fire, or hotspots in an empty scene")
    else:
        for cls, v in bad.items():
            row(f"FALSE {cls.upper()}",
                f"{v['frames']} / {total} frames, peak {v['max_conf'] * 100:.0f}%, "
                f"tiers {'/'.join(sorted(v['tiers']))}", RED)
        verdict(False, f"{len(bad)} false-positive class(es) — investigate before use")
    results["sections"]["false_positives"] = {
        "frames": total,
        "critical": {k: {"frames": v["frames"], "max_conf": v["max_conf"]}
                     for k, v in bad.items()},
        "structural": {k: v["frames"] for k, v in structural.items()}}


def section_detection(cls_name: str, human: str) -> None:
    print()
    ans = ask(f"Place a {human} in clear view, then [Enter] (or 's' to skip): ")
    if ans.lower() == "s":
        return
    snaps = sample(6.0)
    hits = [t for s in snaps for t in s["tracks"] if t["cls"] == cls_name]
    total = max(1, len(snaps))
    frames_with = sum(1 for s in snaps
                      if any(t["cls"] == cls_name for t in s["tracks"]))
    if hits:
        confs = [t["conf"] for t in hits]
        best = max(hits, key=lambda t: t["conf"])
        row(f"{human} detected",
            f"{frames_with}/{total} frames ({frames_with * 100 // total}%), "
            f"conf mean {statistics.mean(confs) * 100:.0f}% peak "
            f"{max(confs) * 100:.0f}%, tier {best['tier']}",
            GREEN if frames_with / total > 0.6 else YELLOW)
        detail = []
        if best.get("dist_ft") is not None:
            detail.append(f"range {best['dist_ft']:.0f} ft "
                          f"({best.get('range_source', 'mono')})")
        if best.get("thermal_confirmed"):
            detail.append("thermal-confirmed")
        if detail:
            row("", ", ".join(detail), DIM)
        results["sections"].setdefault("recall", {})[cls_name] = {
            "detected_frames_pct": frames_with * 100 // total,
            "conf_mean": statistics.mean(confs), "conf_peak": max(confs)}
    else:
        row(f"{human} detected", "NOT DETECTED in 6 s", RED)
        results["sections"].setdefault("recall", {})[cls_name] = {
            "detected_frames_pct": 0}


def section_recall() -> None:
    hdr("4. DETECTION RECALL")
    print(f"  {DIM}For each prompt, place the object in view and press Enter.{RESET}")
    section_detection("person", "person (stand in frame)")
    section_detection("door", "door")
    section_detection("exit_sign", "exit sign (or a printed green EXIT sign)")
    section_detection("window", "window")


def section_range() -> None:
    hdr("5. RANGE ACCURACY")
    print(f"  {DIM}Stand a measured distance from the camera. Tape-measure it —{RESET}")
    print(f"  {DIM}guessed ground truth makes this test worthless.{RESET}")
    errors = []
    for _ in range(3):
        ans = ask("True distance to the person in FEET (or 'd' when done): ")
        if ans.lower().startswith("d") or not ans:
            break
        try:
            truth = float(ans)
        except ValueError:
            print(f"  {DIM}not a number, skipping{RESET}")
            continue
        snaps = sample(4.0)
        reported = [t["dist_ft"] for s in snaps for t in s["tracks"]
                    if t["cls"] == "person" and t["dist_ft"] is not None]
        if not reported:
            row("reported range", "no person with a range reading", RED)
            continue
        src = next((t.get("range_source", "mono") for s in snaps
                    for t in s["tracks"] if t["cls"] == "person"), "mono")
        est = statistics.median(reported)
        err = est - truth
        pct = abs(err) / truth * 100
        color = GREEN if pct <= 15 else YELLOW if pct <= 30 else RED
        row(f"truth {truth:.1f} ft",
            f"reported {est:.1f} ft  error {err:+.1f} ft ({pct:.0f}%)  "
            f"[{src}]", color)
        errors.append({"truth_ft": truth, "reported_ft": est,
                       "error_ft": err, "error_pct": pct, "source": src})
    if errors:
        mean_pct = statistics.mean(e["error_pct"] for e in errors)
        results["sections"]["range"] = {"samples": errors,
                                       "mean_error_pct": mean_pct}
        verdict(mean_pct <= 20.0,
                f"mean range error {mean_pct:.0f}% "
                f"({'stereo measured' if errors[0]['source'] == 'stereo' else 'monocular estimate'})")
        if errors[0]["source"] == "mono":
            print(f"  {DIM}Monocular ranging assumes standard object height. "
                  f"A stereo pair measures it — see docs/HARDWARE.md.{RESET}")


def section_thermal() -> None:
    hdr("6. THERMAL")
    st = get("/api/state")
    src = st.get("thermal_source")
    if src != "lepton":
        row("thermal source", f"{src} (no Lepton attached)", YELLOW)
        print(f"  {DIM}Without a Lepton the system uses an RGB-derived estimate "
              f"and will NOT confirm fire or hotspots. Skipping.{RESET}")
        results["sections"]["thermal"] = {"source": src, "tested": False}
        return
    print(f"  {DIM}Hold your palm ~30 cm in front of the thermal camera.{RESET}")
    ask("Palm in view? [Enter] ")
    snaps = sample(5.0)
    maxes = [s["thermal"]["max_c"] for s in snaps if s.get("thermal")]
    if not maxes:
        verdict(False, "no thermal frames")
        return
    peak = max(maxes)
    row("peak scene temperature", f"{peak:.1f} C")
    # Skin through air reads roughly 28-36 C; well outside that suggests a
    # radiometry or scaling fault.
    ok = 26.0 <= peak <= 40.0
    verdict(ok, f"palm reads {peak:.1f} C "
                f"({'plausible skin temperature' if ok else 'IMPLAUSIBLE — check TLinear/radiometry'})")
    results["sections"]["thermal"] = {"source": src, "tested": True,
                                      "palm_peak_c": peak, "plausible": ok}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true",
                    help="throughput + false positives only (no prompts)")
    ap.add_argument("--window", type=float, default=1.0,
                    help="sampling-window multiplier (0.5 = half as long)")
    args = ap.parse_args()
    global NON_INTERACTIVE, WINDOW
    NON_INTERACTIVE = args.quick
    WINDOW = max(0.2, args.window)

    print("=" * 72)
    print(f"{BOLD} PYROSIGHT CAMERA TEST — measured accuracy on real hardware{RESET}")
    print("=" * 72)
    try:
        get("/api/health")
    except (urllib.error.URLError, OSError):
        print(f"{RED}Backend not reachable at {API}.{RESET}")
        print("Start it, then rerun. See docs/DEPLOYMENT.md.")
        return 1

    if not section_environment():
        return 2
    section_throughput()
    section_false_positives()
    if not args.quick:
        section_recall()
        section_range()
        section_thermal()

    out = Path(__file__).resolve().parent.parent / "backend" / "data"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"camera_test_{time.strftime('%Y%m%d_%H%M%S')}.json"
    results["finished"] = time.time()
    path.write_text(json.dumps(results, indent=2, default=str))

    print("\n" + "=" * 72)
    print(f"{BOLD} CAMERA TEST COMPLETE{RESET}")
    print("=" * 72)
    print(f" Results saved: {path}")
    print(" Compare runs after any change to the detection pipeline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
