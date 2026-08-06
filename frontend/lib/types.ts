// TypeScript mirror of the backend telemetry schema (pyrosight/pipeline/engine.py).

export interface Track {
  id: number;
  cls: string;
  display: string;
  category: "person" | "egress" | "hazard" | "structure";
  priority: number;
  color: string;
  box: [number, number, number, number];
  /** Belief that the class call is correct — the number the HUD prints. */
  conf: number;
  /** The detector's own smoothed score. Diagnostics only; see tracker.py. */
  raw_conf?: number;
  tier: "confirmed" | "likely" | "possible";
  thermal_confirmed: boolean;
  corroborated?: boolean;
  max_temp_c: number | null;
  severity: string | null;
  dist_ft: number | null;
  age: number;
  /** Missed the last detector pass — drives motion extrapolation only. */
  coasting: boolean;
  /** Genuinely unseen for several passes. This is the one the UI may say. */
  stale?: boolean;
  misses?: number;
  label_hint: string;
}

export interface NavTarget {
  kind: "exit" | "victim" | "entry" | "hazard";
  cls: string;
  source: "live" | "memory" | "breadcrumbs";
  rel_bearing_deg: number;
  dist_ft: number | null;
  conf: number;
  age_s?: number;
  /** Set by locate-objectives so the arrow names what was asked for. */
  label?: string;
}


export interface NavState {
  objective: string;
  status: "CLEAR" | "CAUTION" | "BLOCKED";
  instruction: string;
  target: NavTarget | null;
  entry_distance_ft: number | null;
  breadcrumbs: {
    count: number;
    entry: [number, number] | null;
    position: [number, number] | null;
    trail: [number, number][];
  };
}

export interface SensorHealth {
  name: string;
  kind: string;
  status: "ok" | "degraded" | "offline" | "simulated" | "estimated";
  detail: string;
  last_read_age_s: number | null;
}

export interface Diagnostics {
  cpu_percent: number | null;
  mem_percent: number | null;
  disk_percent: number | null;
  cpu_temp_c: number | null;
  battery_percent: number | null;
  /** How the percentage was obtained — see core/diagnostics.py. */
  battery_source?: "gauge" | "counted" | "host" | "simulated" | "none";
  runtime_min: number | null;
  power_state: "normal" | "saver" | "critical" | "unknown";
  fps: number;
  latency_ms: number;
  uptime_s: number;
  sensors: Record<string, SensorHealth>;
}

export interface SearchCoverage {
  active: boolean;
  explored_cells: number;
  partial_cells: number;
  coverage_pct: number;
  needs_pass: number;
  cell_m?: number;
  cells: { x: number; y: number; level: 1 | 2 }[];
}

export interface HudPrefs {
  primary_view: "rgb" | "thermal" | "fused";
  highlight_doors: boolean;
  show_labels: boolean;
  brightness: number;
  colorblind: boolean;
  emergency: boolean;
  power_saving: boolean;
  effective_brightness: number;
  /** Anti-spoof disabled for bench testing — never set operationally. */
  bench_mode?: boolean;
}

export interface Hotspot {
  box: [number, number, number, number];
  max_temp_c: number;
  mean_temp_c: number;
  area_px: number;
  severity: "elevated" | "severe" | "critical";
}

export interface SystemState {
  seq: number;
  ts: number;
  mission_time_s: number;
  mode: string;
  detector: string;
  fps: number;
  frame: { w: number; h: number };
  thermal_frame: { w: number; h: number };
  tracks: Track[];
  counts: { persons: number; firefighters: number; egress: number; hazards: number };
  thermal: {
    min_c: number; max_c: number; mean_c: number;
    hottest_px: [number, number]; width: number; height: number;
  } | null;
  thermal_source: "lepton" | "sim" | "rgb-estimate" | "none";
  inference: { ms: number | null; age_s: number | null };
  hotspots: Hotspot[];
  smoke: { density: number; visibility: string };
  heading: { deg: number; cardinal: string };
  nav: NavState;
  search: SearchCoverage;
  assistant: string | null;
  emergency: boolean;
  diagnostics: Diagnostics;
  prefs: HudPrefs;
  last_alert: { rule: string; severity: string; text: string; ts: number } | null;
}

export interface TelemetryEvent {
  seq: number;
  ts: number;
  kind: "alert" | "detection" | "system" | "assistant";
  severity?: "critical" | "warning" | "info";
  text?: string;
  rule?: string;
  track?: Partial<Track>;
}

export const BACKEND_HOST =
  typeof window !== "undefined"
    ? `${window.location.hostname}:8000`
    : "localhost:8000";

export const wsUrl = (path: string) => `ws://${BACKEND_HOST}${path}`;
export const apiUrl = (path: string) => `http://${BACKEND_HOST}${path}`;
