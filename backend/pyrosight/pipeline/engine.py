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

The engine is autonomous: it has no command input. Everything it reports is
derived from what the sensors see, on one thread.
"""

from __future__ import annotations

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
from ..navigation.mesh import MeshLink, buddy_bearings
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
from ..vision.egress import EgressDetector
from ..vision.fire import FireDetector
from ..vision.floor import FloorIntegrityAnalyzer
from ..vision.spoof import StaticSubjectMonitor, framed_by_rectangle
from ..vision.fusion import fuse
from ..vision.smoke import SmokeEstimator
from ..vision.thermal_analysis import ThermalAnalyzer
from ..vision.tracker import TemporalTracker
from ..vision.visual_odometry import VisualYaw
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
        self.egress = EgressDetector()
        # Anti-spoof state: is that a person, or a picture of one.
        self.static_subjects = StaticSubjectMonitor()
        self._last_spoof_event = 0.0
        # Live mode auto-baselines smoke estimation on this camera/scene.
        self.smoke = SmokeEstimator(calibrate=not self.sim_mode)
        self.visual_yaw = VisualYaw()
        self.thermal_analyzer = ThermalAnalyzer(config.vision)
        self.tracker = TemporalTracker(config.tracker, config.vision)
        self.heading = HeadingFilter()
        self.breadcrumbs = BreadcrumbTrail(config.nav.crumb_spacing_m)
        self.guidance = GuidanceEngine(config.nav)
        self.alerts = AlertEngine(config.physio)
        self.floor_analyzer = FloorIntegrityAnalyzer()
        self.mesh = MeshLink(config.mesh)
        # ESP32 alert channel (LEDs / buzzer / haptic) and pack telemetry:
        # silent no-op when no board is attached.
        self.peripherals = Esp32Peripherals()
        # The ESP32 is also the only source of battery state on the helmet —
        # a USB-C PD power bank exposes no gauge to the Pi.
        self.diagnostics = Diagnostics(esp32=self.peripherals)
        self.recorder = IncidentRecorder(DATA_DIR, config.engine.record_incidents)

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

        # HUD presentation defaults. Fixed for the run — nothing mutates them
        # now that the platform takes no commands.
        self.prefs = {
            "primary_view": "fused",
            "highlight_doors": False,
            "show_labels": True,
            "brightness": 1.0,          # HUD gain, 0.6..1.5
            "colorblind": False,        # deuteranopia-safe palette
            "emergency": False,         # raised automatically by conditions
            "power_saving": False,
            # Anti-spoof disabled for bench testing. Published so the HUD can
            # say so — a display that silently accepts a photograph of a
            # person as a victim must never look identical to one that does
            # not.
            "bench_mode": config.vision.allow_screens,
        }
        self._search = SearchCoverage()
        self.assistant = SmartAssistant()

    # ------------------------------------------------------------------

    def start(self) -> None:
        self.sensors.start()
        self.mesh.start()
        # Booted with RGB_SOURCE=browser: the suite's BrowserRGB is the
        # standing ingest buffer.
        if isinstance(self.sensors.rgb, BrowserRGB):
            self._browser_rgb = self.sensors.rgb
            self._live_ingest_active = not self.sim_mode
        if self.worker is not None:
            self.worker.start()
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
        self.peripherals.close()
        self.sensors.stop()
        self.mesh.stop()
        self.recorder.log("session_end", {})
        self.recorder.close()

    # ------------------------------------------------------------------

    def _reject_framed_people(self, rgb: np.ndarray,
                              detections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Drop person detections enclosed by a picture frame or screen bezel.

        Rejections are announced rather than silent: a suppressed victim is
        exactly the kind of decision that must be auditable after the fact, so
        each one is pushed as a system event and written to the incident log.
        """
        out: List[Dict[str, Any]] = []
        for det in detections:
            if det.get("cls") not in ("person", "firefighter"):
                out.append(det)
                continue
            framed = framed_by_rectangle(rgb, det["box"])
            if framed is None:
                out.append(det)
                continue
            now = time.time()
            if now - self._last_spoof_event > 8.0:
                self._last_spoof_event = now
                payload = {
                    "severity": "info",
                    "text": ("PERSON REJECTED — FRAMED IMAGE (screen or picture), "
                             f"{int(det['conf'] * 100)}% raw"),
                    "rect": framed["rect"],
                }
                self.hub.push_event("system", payload)
                self.recorder.log("spoof_reject", payload)
        return out

    def _apply_static_subject_policy(self, tracks: List[Dict[str, Any]]) -> None:
        """Cap motionless, thermally-uncorroborated people below CONFIRMED.

        A living person is never perfectly still relative to the room. An
        image of one is. But an unconscious victim is very nearly still too,
        so this only lowers the claim — it never removes the detection.
        """
        live_ids = set()
        for t in tracks:
            if t["cls"] not in ("person", "firefighter"):
                continue
            live_ids.add(t["id"])
            self.static_subjects.update(t["id"], t["box"])
            if t.get("thermal_confirmed"):
                continue          # body heat settles it; motion is moot
            if not self.static_subjects.is_static(t["id"]):
                continue
            if t["conf"] >= self.config.vision.confirmed_conf:
                t["conf"] = round(self.config.vision.confirmed_conf - 0.06, 3)
                t["tier"] = "likely"
                t["display"] = t["display"].replace("POSSIBLE ", "")
            t["label_hint"] = "no independent motion"
        self.static_subjects.forget(live_ids)

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

    def _service_camera_source(self) -> None:
        """Runtime sim <-> live camera switching, on the engine thread.

        Both transitions rebuild perception state, so they must not happen
        underneath a tick that is mid-way through using it.
        """
        if self._want_live_switch and not self._live_ingest_active:
            self._perform_live_switch()
        # Dead-feed failsafe: a browser camera that stops sending (tab
        # closed, sleep, navigation in an old build) must never leave the
        # system frozen on one stale frame — fall back to the sim demo and
        # re-switch automatically when frames return.
        if (self._live_ingest_active
                and time.time() - self._browser_rgb._last_read_ts > 8.0):
            self._revert_to_sim()

    # ------------------------------------------------------------------

    def _loop(self) -> None:
        target_dt = 1.0 / max(1.0, self.config.engine.target_fps)
        last = time.time()
        while self._running:
            t0 = time.time()
            self._service_camera_source()
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
        physio = self.sensors.physio.read() if self.sensors.physio else None
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
        # Exit signs and windows are engineered targets that classical CV
        # reads more reliably than an open-vocabulary model does; fusion
        # treats this as corroboration, not as a second opinion to average.
        egress_regions = self.egress.detect(rgb)

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

        # ---- anti-spoof: a picture of a person is not a person ----
        # Applied before fusion so a framed subject never reaches the tracker,
        # the alert engine, or the victim count. Sim ground truth is exempt —
        # there are no posters in the SITL world, and the test would only cost
        # frame time.
        if (not (self.sim_mode and self.sensors.rgb_is_sim)
                and not cfg.vision.allow_screens):
            detections = self._reject_framed_people(rgb, detections)

        # ---- fusion + temporal tracking ----
        # An RGB-derived thermal field is NOT independent evidence.
        fused_dets = fuse(detections, fire_regions, thermal_result, (w, h),
                          thermal_wh,
                          thermal_independent=(thermal_source in ("lepton", "sim")),
                          egress_regions=egress_regions)
        # Stereo depth (Waveshare dual IMX219): attach MEASURED range so the
        # tracker uses observation instead of the monocular size assumption.
        depth = getattr(self.sensors.rgb, "depth", None)
        if depth is not None:
            for det in fused_dets:
                measured = depth.distance_for_box(det["box"], (w, h))
                if measured is not None:
                    det["dist_m_measured"] = measured
            # Floor integrity rides the same fused-detection -> tracker path
            # as everything else, so a hole gets the same multi-frame
            # confirmation and honest tiering as a fire or a victim.
            fused_dets.extend(self.floor_analyzer.analyze(depth, (w, h)))
        tracks = self.tracker.update(fused_dets, (w, h))
        if not (self.sim_mode and self.sensors.rgb_is_sim):
            self._apply_static_subject_policy(tracks)
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

        # ---- mesh position sharing + buddy bearing ----
        # `emergency` for this broadcast lags one tick (computed below) —
        # a status flag one frame stale is a non-issue for a team map.
        self.mesh.publish(self.breadcrumbs.position, heading,
                          emergency=self.prefs.get("emergency", False))
        buddies = buddy_bearings(self.breadcrumbs.position, heading,
                                 self.mesh.teammates())

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
                                     nav, diag, physio=physio, buddies=buddies)

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
        # Purely condition-driven: it raises itself when the conditions above
        # hold and clears itself the moment they stop. With no command input
        # there is no operator dismissal, so the specificity of that list is
        # the ONLY thing standing between this and alarm fatigue.
        emergency = auto_emergency
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
            "physio": physio,
            "mesh": {"unit_id": self.mesh.unit_id, "buddies": buddies},
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
