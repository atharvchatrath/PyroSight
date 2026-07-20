# PyroSight Architecture

## Process model

One Python process (the **perception backend**) and one Node process (the
**web frontend**). On the helmet unit both run as systemd services plus a
Chromium kiosk on the monocular display.

```
┌──────────────────────────────── backend (FastAPI) ────────────────────────────────┐
│                                                                                   │
│  PerceptionEngine (dedicated thread, ~20 Hz)                                      │
│  ┌──────────┐  ┌──────────────┐  ┌────────┐  ┌─────────┐  ┌──────────┐            │
│  │ Sensors  │→ │ Vision       │→ │ Fusion │→ │ Tracker │→ │ Guidance │→ state     │
│  │ rgb/therm│  │ smoke, fire, │  └────────┘  └─────────┘  └──────────┘  alerts    │
│  │ /imu     │  │ thermal      │       ↑                                 frames    │
│  └──────────┘  └──────────────┘  DetectionWorker (2nd thread,                     │
│                                  async neural inference)                          │
│                                                                                   │
│  TelemetryHub (thread-safe state + event ring)     FrameStore (latest JPEGs)      │
│        │                                                 │                        │
│  ══ asyncio boundary ═════════════════════════════════════════════════            │
│        ▼                                                 ▼                        │
│  /ws/telemetry (JSON @15Hz)                 /ws/video?feed=rgb|thermal|fused      │
│  /api/* REST (config, commands, incidents, history)                               │
└───────────────────────────────────────────────────────────────────────────────────┘
```

**Why a plain thread for the engine?** Sensor I/O and OpenCV are blocking;
running perception inside the event loop would let a slow frame starve every
WebSocket. The engine publishes into thread-safe stores; async handlers poll
at their own rate and always ship the *latest* state — a slow client never
builds a backlog, it just skips frames.

**Why a second thread for inference?** Neural inference costs 50–400 ms
depending on hardware. The DetectionWorker conflates frames (always infers on
the newest) while the temporal tracker coasts detections between updates with
constant-velocity prediction. Result: 15–20 FPS HUD regardless of model speed.

## Data flow details

- **Detections** — sim mode uses ground-truth boxes from the SITL world,
  degraded with smoke/distance-dependent confidence, dropouts, and jitter
  *before* the tracker, so the temporal machinery is exercised identically to
  live mode. Live mode runs ONNX (Pi) or YOLO-World (dev) with per-class
  confidence floors, geometry sanity gates, and cross-prompt NMS.
- **Fusion** — thermal body-band regions boost person confidence
  (`thermal_confirmed`); hotspots corroborate fire; visually-unsupported
  hotspots become first-class detections; thermally-unsupported "fire" is
  capped at 60%.
- **Confidence tiers** — track confidence = EMA of detection confidence +
  bounded persistence bonus − coasting decay. `confirmed ≥ 0.75`,
  `likely ≥ 0.5`, else `possible` → rendered as "POSSIBLE X" with dashed
  brackets.
- **Navigation** — exit target priority: live exit-sign > door > window >
  remembered bearing (decays, expires at 120 s, labeled "LAST SEEN").
  Return-to-entry walks the breadcrumb trail backwards. Hazards inside a
  ±25° forward cone within ~6 m degrade route status CLEAR→CAUTION→BLOCKED.
- **Events vs state** — continuous values ride the 15 Hz state snapshot;
  discrete happenings (alerts, new detections, command acks) ride a
  monotonic-sequence ring so nothing is lost between polls.

## Failure & degradation matrix

| Failure | Behavior | HUD indication |
|---|---|---|
| No Lepton | RGB-derived thermal estimate | THM amber, "estimated" |
| No BNO085 | Visual heading from camera pan | IMU amber, "estimated" |
| Camera stall | Watchdog reopens device | CAM amber while stalled |
| No neural model | Classical CV only (fire/hotspot/smoke) | DETECTOR: NONE |
| Pipeline exception | Caught, logged as event, loop continues | system event |
| Backend link lost | Frontend auto-reconnects (1.5 s) | LINK DOWN banner |

## Extension points (future versions)

- **Sensors**: subclass `sensors.base.Sensor`, register in `SensorSuite`
  (LiDAR, UWB anchors, gas sensors slot in here).
- **Positioning**: `BreadcrumbTrail.update_absolute()` is the seam where UWB
  or SLAM replaces dead reckoning — guidance and the mini-map are agnostic.
- **Detection classes**: add to `vision/classes.py`; tracker, fusion, HUD and
  dashboard pick them up from the registry.
- **Multi-firefighter**: each helmet backend already exposes telemetry over
  WebSocket; a command server aggregating multiple units is an additive
  service, no engine changes.
- **Digital twins / drones**: consume `/ws/telemetry` + incident JSONL.
