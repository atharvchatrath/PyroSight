"""
PerceptionEngine — the real-time heart of PyroSight.

Runs as a plain daemon thread (never starved by the asyncio event loop):

    capture (RGB / thermal / IMU)
      -> smoke density estimation          (classical, every frame)
      -> object detection                  (ONNX / YOLO-World, every Nth frame;
                                            SITL ground truth in sim mode)
      -> HSV fire detection                (classical, every frame)
      -> thermal analysis                  (hotspots, body regions, stats)
      -> RGB+thermal fusion                (cross-modal corroboration)
      -> temporal tracking                 (confidence over frames)
      -> navigation                        (heading, breadcrumbs, guidance)
      -> alerts, recording
      -> publish: state snapshot + JPEG feeds (rgb / thermal / fused)

Commands (voice or dashboard) arrive on a thread-safe queue and are applied
at the top of the loop, so all mutation happens on one thread.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

from ..config import DATA_DIR, PyroSightConfig
from ..core.alerts import AlertEngine
from ..core.diagnostics import Diagnostics
from ..core.events import FrameStore, TelemetryHub
from ..navigation.assistant import SmartAssistant
from ..navigation.breadcrumbs import BreadcrumbTrail
from ..navigation.guidance import GuidanceEngine
from ..navigation.heading import HeadingFilter
from ..navigation.search import SearchCoverage
from ..peripherals.esp32 import Esp32Peripherals
from ..recording.incidents import IncidentRecorder
from ..sensors.imu import StaticIMU
from ..sensors.manager import SensorSuite
from ..sensors.rgb import BrowserRGB
from ..sim.render import RGB_FX
from ..sim.world import SimWorld
from ..vision import pseudo_thermal
from ..vision.detector import NullDetector, build_detector
from ..vision.fire import FireDetector
from ..vision.fusion import fuse
from ..vision.smoke import SmokeEstimator
from ..vision.thermal_analysis import ThermalAnalyzer
from ..vision.tracker import TemporalTracker
from ..vision.visual_odometry import VisualYaw
from ..voice import commands as voice_grammar
from .worker import DetectionWorker


class PerceptionEngine:
    def __init__(self, config: PyroSightConfig, hub: TelemetryHub,
                 frames: FrameStore):
        self.config = config
        self.hub = hub
        self.frames = frames
        self.sim_mode = config.resolved_mode() == "sim"

        self.world = SimWorld()
        self.sensors = SensorSuite(config, self.world)
        # Sim mode never runs neural inference (SITL ground truth stands in),
        # so don't load model weights — keeps startup instant and offline.
        self.detector = (NullDetector() if self.sim_mode
                         else build_detector(config.vision))
        # Live mode: inference runs on its own thread so the HUD never stalls.
        self.worker = (None if self.sim_mode
                       else DetectionWorker(self.detector))
        self.fire = FireDetector()
        # Live mode auto-baselines smoke estimation on this camera/scene.
        self.smoke = SmokeEstimator(calibrate=not self.sim_mode)
        self.visual_yaw = VisualYaw()
        self.thermal_analyzer = ThermalAnalyzer(config.vision)
        self.tracker = TemporalTracker(config.tracker, config.vision)
        self.heading = HeadingFilter()
        self.breadcrumbs = BreadcrumbTrail(config.nav.crumb_spacing_m)
        self.guidance = GuidanceEngine(config.nav)
        self.alerts = AlertEngine()
        self.diagnostics = Diagnostics()
        # ESP32 alert channel (LEDs / buzzer / haptic): silent no-op when
        # no board is attached.
        self.peripherals = Esp32Peripherals()
        self.recorder = IncidentRecorder(DATA_DIR, config.engine.record_incidents)

        self._commands: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        # Browser-camera ingest: standing buffer + runtime live-switch flags.
        self._browser_rgb = BrowserRGB()
        self._browser_rgb.start()
        self._want_live_switch = False
        self._live_ingest_active = not self.sim_mode and isinstance(
            self.sensors.rgb, BrowserRGB)
        self._mission_t0 = time.time()
        self._frame_count = 0
        self._fps = 0.0
        self._latency_ms = 0.0
        self._known_track_ids: set = set()
        self._det_event_ts: Dict[str, float] = {}  # class -> last event time
        self._cached_detections: List[Dict[str, Any]] = []

        # HUD preferences mutated by voice/dashboard commands.
        self.prefs = {
            "primary_view": "fused",
            "highlight_doors": False,
            "show_labels": True,
            "brightness": 1.0,          # HUD gain, 0.6..1.5
            "colorblind": False,        # deuteranopia-safe palette
            "emergency": False,         # emergency mode (auto or manual)
            "power_saving": False,
        }
        self._emergency_manual = False
        self._search = SearchCoverage()
        self.assistant = SmartAssistant()

    # ------------------------------------------------------------------

    def start(self) -> None:
        self.sensors.start()
        # Booted with RGB_SOURCE=browser: the suite's BrowserRGB is the
        # standing ingest buffer.
        if isinstance(self.sensors.rgb, BrowserRGB):
            self._browser_rgb = self.sensors.rgb
            self._live_ingest_active = not self.sim_mode
        if self.worker is not None:
            self.worker.start()
        self._voice_listener = None
        if not self.sim_mode:
            try:
                from ..voice.listener import VoskListener
                self._voice_listener = VoskListener(self.submit_command)
                self._voice_listener.start()
            except Exception:  # noqa: BLE001 - voice is optional
                self._voice_listener = None
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="pyrosight-engine")
        self._thread.start()
        self.hub.push_event("system", {
            "severity": "info",
            "text": f"PYROSIGHT ONLINE — MODE {self.config.resolved_mode().upper()}, "
                    f"DETECTOR {self.detector.name.upper()}",
        })
        self.recorder.log("session_start", {
            "mode": self.config.resolved_mode(),
            "detector": self.detector.name,
            "platform": self.config.platform,
        })

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self.worker is not None:
            self.worker.stop()
        if getattr(self, "_voice_listener", None) is not None:
            self._voice_listener.stop()
        self.peripherals.close()
        self.sensors.stop()
        self.recorder.log("session_end", {})
        self.recorder.close()

    # ------------------------------------------------------------------

    def submit_command(self, text: str) -> Dict[str, Any]:
        """Voice/typed command in, ack out (grammar runs synchronously; the
        state change is applied on the engine thread)."""
        result = voice_grammar.match(text)
        if result is None:
            ack = {"ok": False, "transcript": text,
                   "ack": "UNRECOGNIZED — SAY 'STATUS' FOR OPTIONS"}
            self.hub.push_event("command", {"severity": "info", **ack})
            return ack
        self._commands.put(result)
        ack = {"ok": True, "intent": result["intent"], "ack": result["ack"],
               "transcript": text}
        self.hub.push_event("command", {"severity": "info", **ack})
        self.recorder.log("command", ack)
        return ack

    def ingest_frame(self, jpeg: bytes) -> bool:
        """Browser camera ingest (/ws/ingest). Frames land in a standing
        BrowserRGB buffer; the first frame requests a runtime switch to live
        processing, which the engine thread performs safely at the top of
        its next tick — even if the backend booted in sim/demo mode."""
        if not self._browser_rgb.push(jpeg):
            return False
        if not self._live_ingest_active:
            self._want_live_switch = True
        return True

    def _perform_live_switch(self) -> None:
        """Runs ON THE ENGINE THREAD. Sim demo -> live camera pipeline."""
        self._want_live_switch = False
        self._live_ingest_active = True
        for old in (self.sensors.rgb, self.sensors.thermal, self.sensors.imu):
            if old is not None:
                try:
                    old.stop()
                except Exception:  # noqa: BLE001
                    pass
        self.sensors.rgb = self._browser_rgb
        self.sensors.rgb_is_sim = False
        self.sensors.thermal = None            # -> RGB-derived estimate
        static_imu = StaticIMU()
        static_imu.start()
        self.sensors.imu = static_imu          # -> visual heading
        self.sim_mode = False
        if self.worker is None:
            # Detector loads lazily on the worker thread; HUD keeps running.
            vis_cfg = self.config.vision
            self.worker = DetectionWorker(
                factory=lambda: build_detector(vis_cfg))
            self.worker.start()
        # Fresh perception state: sim tracks/trail must not haunt the live run.
        self.tracker = TemporalTracker(self.config.tracker, self.config.vision)
        self.smoke = SmokeEstimator(calibrate=True)
        self.breadcrumbs = BreadcrumbTrail(self.config.nav.crumb_spacing_m)
        self.guidance = GuidanceEngine(self.config.nav)
        self.heading = HeadingFilter()
        self.visual_yaw = VisualYaw()
        self._known_track_ids.clear()
        self._cached_detections = []
        self.hub.push_event("system", {
            "severity": "info",
            "text": "BROWSER CAMERA LINKED — SWITCHED TO LIVE PIPELINE",
        })
        self.recorder.log("live_switch", {"source": "browser_ingest"})

    def _revert_to_sim(self) -> None:
        """Runs ON THE ENGINE THREAD. Live camera feed died -> sim demo."""
        from ..sensors.imu import SimulatedIMU
        from ..sensors.rgb import SimulatedRGB
        from ..sensors.thermal import SimulatedThermal
        self._live_ingest_active = False
        self._want_live_switch = False
        s = self.config.sensors
        rgb = SimulatedRGB(self.world, s.rgb_width, s.rgb_height)
        rgb.start()
        thermal = SimulatedThermal(self.world)
        thermal.start()
        imu = SimulatedIMU(self.world)
        imu.start()
        self.sensors.rgb = rgb
        self.sensors.thermal = thermal
        self.sensors.imu = imu
        self.sensors.rgb_is_sim = True
        self.sim_mode = True
        # Fresh perception state; live tracks must not haunt the demo.
        self.tracker = TemporalTracker(self.config.tracker, self.config.vision)
        self.smoke = SmokeEstimator()
        self.breadcrumbs = BreadcrumbTrail(self.config.nav.crumb_spacing_m)
        self.guidance = GuidanceEngine(self.config.nav)
        self.heading = HeadingFilter()
        self._known_track_ids.clear()
        self._cached_detections = []
        self.hub.push_event("system", {
            "severity": "warning",
            "text": "CAMERA FEED LOST — SIM DEMO RESUMED (restart camera to go live)",
        })
        self.recorder.log("live_revert", {"reason": "browser feed stalled"})

    def _apply_commands(self) -> None:
        if self._want_live_switch and not self._live_ingest_active:
            self._perform_live_switch()
        # Dead-feed failsafe: a browser camera that stops sending (tab
        # closed, sleep, navigation in an old build) must never leave the
        # system frozen on one stale frame — fall back to the sim demo and
        # re-switch automatically when frames return.
        if (self._live_ingest_active
                and time.time() - self._browser_rgb._last_read_ts > 8.0):
            self._revert_to_sim()
        while True:
            try:
                cmd = self._commands.get_nowait()
            except queue.Empty:
                return
            intent = cmd["intent"]
            if intent == "FIND_EXIT":
                self.guidance.set_objective("find_exit")
                self._search.stop()
            elif intent == "LOCATE_VICTIM":
                self.guidance.set_objective("locate_victim")
                self._search.stop()
            elif intent == "RETURN_TO_ENTRY":
                self.guidance.set_objective("return_to_entry")
                self._search.stop()
            elif intent == "CLEAR_OBJECTIVE":
                self.guidance.set_objective("explore")
                self._search.stop()
            elif intent == "MARK_ENTRY":
                self.breadcrumbs.mark_entry_here()
            elif intent == "SHOW_THERMAL":
                self.prefs["primary_view"] = "thermal"
            elif intent == "SHOW_RGB":
                self.prefs["primary_view"] = "rgb"
            elif intent == "HIGHLIGHT_DOORS":
                self.prefs["highlight_doors"] = not self.prefs["highlight_doors"]
            elif intent == "HIDE_LABELS":
                self.prefs["show_labels"] = False
            elif intent == "SHOW_LABELS":
                self.prefs["show_labels"] = True
            elif intent == "BRIGHTNESS_UP":
                self.prefs["brightness"] = round(
                    min(1.5, self.prefs["brightness"] + 0.15), 2)
            elif intent == "BRIGHTNESS_DOWN":
                self.prefs["brightness"] = round(
                    max(0.6, self.prefs["brightness"] - 0.15), 2)
            elif intent == "EMERGENCY_MODE":
                self._emergency_manual = True
            elif intent == "EXIT_EMERGENCY":
                self._emergency_manual = False
            elif intent == "SEARCH_MODE":
                self.guidance.set_objective("search")
                self._search.start(self.breadcrumbs.position)
            elif intent == "REPEAT_ALERT":
                if self.alerts.latest is not None:
                    self.hub.push_event("alert", dict(self.alerts.latest))

    # ------------------------------------------------------------------

    def _loop(self) -> None:
        target_dt = 1.0 / max(1.0, self.config.engine.target_fps)
        last = time.time()
        while self._running:
            t0 = time.time()
            self._apply_commands()
            try:
                self._tick()
            except Exception as exc:  # noqa: BLE001 - engine must survive
                self.hub.push_event("system", {
                    "severity": "warning",
                    "text": f"PIPELINE FAULT RECOVERED: {type(exc).__name__}: {exc}",
                })
                time.sleep(0.1)
            elapsed = time.time() - t0
            self._latency_ms = elapsed * 1000.0
            dt = time.time() - last
            last = time.time()
            if dt > 0:
                inst = 1.0 / dt
                self._fps = inst if self._fps == 0 else self._fps * 0.9 + inst * 0.1
            if elapsed < target_dt:
                time.sleep(target_dt - elapsed)

    # ------------------------------------------------------------------

    def _tick(self) -> None:
        self._frame_count += 1
        cfg = self.config

        rgb = self.sensors.rgb.read() if self.sensors.rgb else None
        temp_c = self.sensors.thermal.read() if self.sensors.thermal else None
        imu = self.sensors.imu.read() if self.sensors.imu else None
        if rgb is None:
            # No imagery yet (e.g. waiting for the browser camera link):
            # publish a heartbeat so the UI can show status instead of a
            # blank "syncing" screen.
            self._publish_heartbeat()
            time.sleep(0.05)
            return
        h, w = rgb.shape[:2]

        # ---- classical CV (every frame) ----
        smoke_density = self.smoke.update(rgb)
        fire_regions = self.fire.detect(rgb)

        # ---- neural / sim detections ----
        if self.sim_mode and self.sensors.rgb_is_sim:
            if self._frame_count % max(1, cfg.vision.detect_every_n) == 0:
                self._cached_detections = self.world.detections(w, h, RGB_FX)
            detections = self._cached_detections
        else:
            # Async: submit the freshest frame; the worker conflates. The
            # tracker coasts between detector updates.
            if self.worker is not None:
                if self._frame_count % max(1, cfg.vision.detect_every_n) == 0:
                    self.worker.submit(rgb)
                detections = self.worker.latest()
            else:
                detections = []

        # ---- thermal (measured, or honestly-labeled RGB estimate) ----
        if temp_c is not None:
            thermal_source = "sim" if self.sim_mode else "lepton"
        elif not self.sim_mode:
            temp_c = pseudo_thermal.estimate_from_rgb(
                rgb, cfg.sensors.thermal_width, cfg.sensors.thermal_height)
            thermal_source = "rgb-estimate"
        else:
            thermal_source = "none"
        if temp_c is not None:
            thermal_result = self.thermal_analyzer.analyze(temp_c)
            thermal_wh = (temp_c.shape[1], temp_c.shape[0])
        else:
            thermal_result = {"stats": None, "hotspots": [], "body_regions": []}
            thermal_wh = (cfg.sensors.thermal_width, cfg.sensors.thermal_height)

        # ---- fusion + temporal tracking ----
        # An RGB-derived thermal field is NOT independent evidence.
        fused_dets = fuse(detections, fire_regions, thermal_result, (w, h),
                          thermal_wh,
                          thermal_independent=(thermal_source in ("lepton", "sim")))
        tracks = self.tracker.update(fused_dets, (w, h))
        self._emit_track_events(tracks)

        # ---- navigation ----
        yaw = imu.get("yaw_deg") if imu else None
        if yaw is None and not self.sim_mode:
            # No IMU: derive heading from camera pan (visual odometry).
            yaw = self.visual_yaw.update(rgb)
        heading = self.heading.update(yaw)
        if self.sim_mode:
            x, y = self.world.true_position()
            self.breadcrumbs.update_absolute(x, y)
        elif imu and imu.get("step"):
            self.breadcrumbs.update_step(heading)
        nav = self.guidance.update(tracks, heading, self.breadcrumbs, w)

        # ---- search coverage + smart assistant ----
        self._search.update(self.breadcrumbs.position, heading)
        smoke_vis = ("CALIBRATING" if self.smoke.calibrating
                     else SmokeEstimator.visibility_label(smoke_density))
        suggestion = self.assistant.update(tracks, nav, smoke_vis, heading)
        if suggestion is not None:
            self.hub.push_event("assistant", {"severity": "info",
                                              "text": suggestion})

        # ---- diagnostics + alerts ----
        sensor_health = self.sensors.health()
        if self.sensors.thermal is None:
            sensor_health["thermal"] = {
                "name": "thermal_estimate", "kind": "thermal",
                "status": "estimated",
                "detail": "RGB-derived estimate (no Lepton attached)",
                "last_read_age_s": 0.0,
            }
        diag = self.diagnostics.sample(self._fps, self._latency_ms,
                                       sensor_health, self.sim_mode)
        fired = self.alerts.evaluate(tracks, thermal_result, smoke_density,
                                     nav, diag)

        # ---- emergency mode (manual OR auto on genuinely critical
        # conditions) — a fire visible across the room is NOT an emergency;
        # being cut off by one, a flashover-risk hotspot, blackout smoke, or
        # a dying battery is. Keeping this specific avoids alarm fatigue. ----
        auto_emergency = (
            nav.get("status") == "BLOCKED"
            or any(t["cls"] == "hotspot" and t.get("severity") == "critical"
                   and t.get("thermal_confirmed") for t in tracks)
            or (diag.get("battery_percent") is not None
                and diag["battery_percent"] < 12)
            or smoke_vis == "NEAR ZERO")
        emergency = self._emergency_manual or auto_emergency
        self.prefs["emergency"] = emergency
        # Power-saving engages automatically on low battery.
        self.prefs["power_saving"] = diag.get("power_state") in ("saver", "critical")
        # Effective brightness: emergency forces a high-visibility floor.
        eff_brightness = (max(self.prefs["brightness"], 1.35) if emergency
                          else self.prefs["brightness"])

        fused_jpeg = self._publish_frames(rgb, temp_c, thermal_result)
        self.peripherals.heartbeat()
        for alert in fired:
            self.hub.push_event("alert", dict(alert))
            self.recorder.log("alert", alert)
            self.peripherals.notify_alert(alert["severity"])
            if alert["severity"] == "critical" and fused_jpeg is not None:
                self.recorder.snapshot(alert["rule"], fused_jpeg)

        # ---- state snapshot ----
        self.hub.set_state({
            "ts": time.time(),
            "mission_time_s": int(time.time() - self._mission_t0),
            "mode": "live" if self._live_ingest_active else cfg.resolved_mode(),
            "detector": ("sitl-truth" if self.sim_mode
                         else self.worker.detector_name if self.worker is not None
                         else self.detector.name),
            "fps": round(self._fps, 1),
            "frame": {"w": w, "h": h},
            "thermal_frame": {"w": thermal_wh[0], "h": thermal_wh[1]},
            "tracks": tracks,
            "counts": {
                "persons": sum(1 for t in tracks if t["cls"] == "person"),
                "firefighters": sum(1 for t in tracks if t["cls"] == "firefighter"),
                "egress": sum(1 for t in tracks if t["category"] == "egress"),
                "hazards": sum(1 for t in tracks if t["category"] == "hazard"),
            },
            "thermal": thermal_result["stats"],
            "thermal_source": thermal_source,
            "hotspots": thermal_result["hotspots"],
            "inference": {
                "ms": round(self.worker.infer_ms, 1) if self.worker else None,
                "age_s": round(self.worker.age_s, 2)
                if self.worker and self.worker.age_s != float("inf") else None,
            },
            "smoke": {
                "density": smoke_density,
                "visibility": "CALIBRATING" if self.smoke.calibrating
                else SmokeEstimator.visibility_label(smoke_density),
            },
            "heading": {
                "deg": round(heading, 1),
                "cardinal": HeadingFilter.cardinal(heading),
            },
            "nav": nav,
            "search": self._search.to_dict(),
            "assistant": self.assistant.current,
            "emergency": emergency,
            "diagnostics": diag,
            "prefs": {**self.prefs, "effective_brightness": round(eff_brightness, 2)},
            "last_alert": self.alerts.latest,
        })

    # ------------------------------------------------------------------

    def _publish_heartbeat(self) -> None:
        cfg = self.config
        sensor_health = self.sensors.health()
        diag = self.diagnostics.sample(0.0, 0.0, sensor_health, self.sim_mode)
        self.hub.set_state({
            "ts": time.time(),
            "mission_time_s": int(time.time() - self._mission_t0),
            "mode": cfg.resolved_mode(),
            "detector": self.detector.name,
            "fps": 0.0,
            "awaiting_rgb": True,
            "frame": {"w": cfg.sensors.rgb_width, "h": cfg.sensors.rgb_height},
            "thermal_frame": {"w": cfg.sensors.thermal_width,
                              "h": cfg.sensors.thermal_height},
            "tracks": [],
            "counts": {"persons": 0, "firefighters": 0, "egress": 0, "hazards": 0},
            "thermal": None,
            "thermal_source": "none",
            "hotspots": [],
            "inference": {"ms": None, "age_s": None},
            "smoke": {"density": 0.0, "visibility": "AWAITING FEED"},
            "heading": {"deg": self.heading.heading_deg,
                        "cardinal": HeadingFilter.cardinal(self.heading.heading_deg)},
            "nav": {"objective": self.guidance.objective, "status": "CLEAR",
                    "instruction": "AWAITING CAMERA FEED", "target": None,
                    "entry_distance_ft": None,
                    "breadcrumbs": self.breadcrumbs.to_dict()},
            "diagnostics": diag,
            "prefs": dict(self.prefs),
            "last_alert": self.alerts.latest,
        })

    def _emit_track_events(self, tracks: List[Dict[str, Any]]) -> None:
        current = set()
        now = time.time()
        for t in tracks:
            current.add(t["id"])
            if t["id"] not in self._known_track_ids:
                self._known_track_ids.add(t["id"])
                # Per-class cooldown: heavy smoke churns track ids, and
                # re-logging DOOR five times a second is noise, not signal.
                if now - self._det_event_ts.get(t["cls"], 0.0) < 8.0:
                    continue
                self._det_event_ts[t["cls"]] = now
                event = {
                    "severity": "info",
                    "text": f"{t['display']} — {int(t['conf'] * 100)}%",
                    "track": {k: t[k] for k in
                              ("id", "cls", "display", "conf", "tier",
                               "thermal_confirmed", "dist_ft")},
                }
                self.hub.push_event("detection", event)
                self.recorder.log("detection", event["track"])
        # Forget ids that fully died so a re-appearing object logs again.
        self._known_track_ids &= {t.id for t in self.tracker.tracks} | current

    def _publish_frames(self, rgb: np.ndarray, temp_c: Optional[np.ndarray],
                        thermal_result: Dict[str, Any]) -> Optional[bytes]:
        quality = [int(cv2.IMWRITE_JPEG_QUALITY), self.config.server.jpeg_quality]

        ok, buf = cv2.imencode(".jpg", rgb, quality)
        if ok:
            self.frames.put("rgb", buf.tobytes())

        fused_jpeg: Optional[bytes] = None
        if temp_c is not None:
            colorized = ThermalAnalyzer.colorize(temp_c)
            big = cv2.resize(colorized, (rgb.shape[1], rgb.shape[0]),
                             interpolation=cv2.INTER_NEAREST)
            ok, buf = cv2.imencode(".jpg", big, quality)
            if ok:
                self.frames.put("thermal", buf.tobytes())

            # Fused: thermal energy bleeds through where the scene is HOT —
            # threshold at 60°C so warm-but-normal surfaces (skin, lamps)
            # never tint the view; only genuine heat paints through.
            heat = np.clip((temp_c - 60.0) / 160.0, 0.0, 0.6)
            heat = cv2.resize(heat, (rgb.shape[1], rgb.shape[0]))
            alpha = cv2.GaussianBlur(heat, (9, 9), 3.0)[..., None]
            fused = (rgb.astype(np.float32) * (1 - alpha)
                     + big.astype(np.float32) * alpha).astype(np.uint8)
            ok, buf = cv2.imencode(".jpg", fused, quality)
            if ok:
                fused_jpeg = buf.tobytes()
                self.frames.put("fused", fused_jpeg)
        else:
            ok, buf = cv2.imencode(".jpg", rgb, quality)
            if ok:
                fused_jpeg = buf.tobytes()
                self.frames.put("fused", fused_jpeg)
        return fused_jpeg
