# PyroSight Hardware

## Bill of materials (~$800)

| Component | Recommended model | Role | Approx. |
|---|---|---|---:|
| Edge computer | **Raspberry Pi 5 (8 GB)** | Perception engine + web stack | $90 |
| Thermal camera | **FLIR Lepton 3.5 + PureThermal 3** | 160×120 radiometric thermal (UVC Y16, centikelvin) | $320 |
| RGB camera | **Raspberry Pi Camera Module 3** | Autofocus RGB, run at 640×480 | $30 |
| IMU | **Bosch BNO085** | On-chip 9-DoF fusion, heading, steps | $25 |
| Alert MCU | **ESP32** | LEDs / buzzer / haptic via USB serial (JSON protocol, see below) | $10 |
| HUD | **0.39–0.49" HDMI micro-OLED monocular** | Chromium kiosk renders `/hud` | $110–120 |
| Battery | **20,000 mAh USB-C PD power bank** | 5V/5A, ~4–6 h runtime | $60 |
| Cooling | **Official Pi Active Cooler** | Sustained inference load | $10–25 |
| Storage | **128 GB industrial microSD** | OS + incident recordings, endurance-rated | $25–30 |
| Feedback | **LEDs + buzzer + haptic motor** | Driven by the ESP32 alert channel | $25 |
| Enclosure | **PETG/ABS printed case + rugged helmet mount + wiring** | Field prototype | $60–105 |

Optional depth upgrade: **Waveshare Dual IMX219 8MP stereo camera** — slots
in as a future RGB source for true stereo ranging (see Expansion below).

## Wiring

- **Lepton/PureThermal 3** → USB-A. Enumerates as a UVC camera; the backend
  auto-detects it by its 160×120 geometry and reads radiometric centikelvin.
- **Camera Module 3** → CSI ribbon (Picamera2/libcamera).
- **BNO085** → I²C (3V3, SDA=GPIO2, SCL=GPIO3, 400 kHz). The installer
  enables I²C automatically.
- **ESP32** → USB serial @115200. The backend auto-detects common USB-UART
  bridges (CP210x/CH340) or honor `PYROSIGHT_ESP32_PORT`. Protocol: one JSON
  line per event —
  `{"kind":"alert","severity":"critical|warning|info"}` and periodic
  `{"kind":"heartbeat"}`. Firmware maps severity → LED color, buzzer
  pattern, haptic pulse; loss of heartbeat >5 s should flash "system down".
- **Micro-OLED** → micro-HDMI; set the panel's native mode in
  `/boot/firmware/config.txt`. The `pyrosight-hud` kiosk service fills it.
- **Microphone** (offline voice) → small USB mic; Vosk uses default ALSA in.

## Performance envelope (Pi 5)

| Stage | Budget |
|---|---|
| Engine loop (capture→publish) | 20 Hz target, 15 Hz floor |
| Vocabulary ONNX detector @ 320 (exported from YOLO-World) | ~130–190 ms → 5–7 Hz async, tracker coasts between |
| Thermal analysis (160×120 radiometric) | < 3 ms |
| Fire (color+flicker) + smoke estimation | < 6 ms |
| JPEG encode ×3 feeds | ~8 ms |
| Glass-to-glass latency | < 250 ms |

Run with the active cooler; sustained CPU ~55–75%. In hot environments,
re-export at 256 (`--imgsz 256`) for headroom at some small-object recall
cost.

## Expansion points

- **Stereo camera (Waveshare dual IMX219)**: subclass `sensors.rgb` with a
  stereo source; disparity replaces pinhole ranging in
  `vision/tracker.estimate_distance_m` — the rest of the stack is agnostic.
- **UWB indoor positioning**: feed `BreadcrumbTrail.update_absolute()`;
  mini-map, return-to-entry, and guidance work unchanged.
- **LiDAR / gas sensors / drone link / multi-firefighter mesh**: add a
  `Sensor` subclass and publish through the existing telemetry channel
  (see docs/ARCHITECTURE.md, Extension points).
