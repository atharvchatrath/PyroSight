"use client";

// Detection rendering — squared-off instrument style.
//
// Corner brackets, not full boxes: the four corners fix the object's extent
// exactly while leaving the middle of it unobstructed, which is the whole
// point when the "object" is a person you are about to drag out. Certainty is
// carried by stroke weight and dashing, never by colour — colour is reserved
// for what a thing *is*.
//
// Geometry arrives pre-conditioned from lib/useSmoothTracks (one-euro filter
// + capped extrapolation), so brackets sit still on a still object and track
// a moving one without lag or overshoot.

import { RenderTrack } from "@/lib/useSmoothTracks";
import {
  MissionMode,
  colorOf,
  confColor,
  displayLabel,
  isPossible,
  isSuppressed,
  roleOf,
  roleVisible,
} from "@/lib/design";

const LABEL_H = 18;
const LABEL_PAD = 4;
const CHAR_W = 6.5; // measured for the UI sans at 11.5px
// The eyebox is not a report. Five labels is roughly what can be read in one
// glance; past that the display costs more attention than it returns.
const MAX_LABELS = 5;
// Training blocks are three lines tall instead of two, so fewer fit before
// the text starts colliding with itself.
const MAX_LABELS_TRAINING = 4;
const MAX_HOTSPOT_LABELS = 2;
// Only the things a decision hangs on carry a second line of detail. A door
// needs an outline; a victim needs range, thermal state and why we're unsure.
const DETAIL_ROLES = new Set(["victim", "crew", "critical", "heat", "exit"]);
// Tracker vitals are instrumentation, not situational awareness: only the
// most important tracks carry them, the rest stay two lines.
const MAX_DETAIL_LABELS = 2;

interface Placed {
  t: RenderTrack;
  x: number;
  y: number;
  w: number;
  h: number;
  text: string;
  sub: string;
  detail: string;
}

/** [x1, y1, x2, y2] in frame pixels — screen space owned by HUD chrome. */
export type Rect = [number, number, number, number];

function detailText(t: RenderTrack): string {
  return (
    `ID ${t.id} · STAB ${Math.round(t.stability * 100)}% · AGE ${t.age.toFixed(1)}S · ` +
    `UPD ${t.staleness < 0.25 ? "NOW" : `${t.staleness.toFixed(1)}S`}`
  );
}

function labelText(t: RenderTrack, smoke: number,
                   detail: boolean): { text: string; sub: string } {
  // A thermal-only detection is the whole reason this platform exists: the
  // camera sees nothing through the smoke layer, the Lepton sees the fire. Say
  // that out loud instead of calling it a generic "hotspot".
  const thermalOnly = t.cls === "hotspot";
  // Only a severe/critical measured region is called fire. A warm pipe, a
  // radiator or a smouldering wall is a heat source and gets said so.
  const burning =
    (t.severity === "critical" || t.severity === "severe") &&
    (t.max_temp_c ?? 0) >= 250;
  const base = thermalOnly
    ? burning
      ? "FIRE — THERMAL"
      : "HEAT SOURCE"
    : displayLabel(t);

  const text = `${base} ${Math.round(t.rconf * 100)}%`;
  if (!detail) return { text, sub: "" };
  const sub = [
    t.dist_ft != null ? `${Math.round(t.dist_ft)} FT` : null,
    t.max_temp_c != null ? `${Math.round(t.max_temp_c)}°C` : null,
    thermalOnly && smoke >= 0.35 ? "SEEN THROUGH SMOKE" : null,
    thermalOnly && smoke < 0.35 ? "NO VISUAL MATCH" : null,
    !thermalOnly && t.thermal_confirmed ? "THERM ✓" : null,
    t.coasting ? "OCCLUDED" : null,
    // Why a person is uncertain matters more than that they are: a subject
    // with no independent motion may be an image — or an unconscious victim.
    // Hints that merely echo the class name (sim ground truth does this) say
    // nothing the label doesn't.
    t.label_hint && t.label_hint.toLowerCase() !== t.cls.replace(/_/g, " ") &&
    t.label_hint.toLowerCase() !== t.cls
      ? t.label_hint.toUpperCase()
      : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return { text, sub };
}

/**
 * Resolve label overlaps by pushing lower-priority labels clear, and keep
 * every label inside the safe area — the top band and bottom rail belong to
 * mission chrome, and a detection label sliding under them is unreadable.
 */
function layout(
  tracks: RenderTrack[],
  fw: number,
  fh: number,
  smoke: number,
  safeTop: number,
  safeBottom: number,
  reserved: Rect[],
  detailIds: number[]
): Placed[] {
  const placed: Placed[] = [];
  const ordered = [...tracks].sort((a, b) => b.priority - a.priority);
  const minY = safeTop;
  const maxY = fh - safeBottom - LABEL_H;

  // Collision is tested against the whole label BLOCK — chip, sub-line and
  // (in training) the tracker-vitals line. Testing the chip alone let two
  // labels sit clear of each other while their text ran together underneath.
  const hits = (x: number, y: number, w: number, h: number): boolean => {
    for (const p of placed) {
      if (x < p.x + p.w + 4 && p.x < x + w + 4 &&
          y < p.y + p.h + 3 && p.y < y + h + 3) {
        return true;
      }
    }
    for (const r of reserved) {
      if (x < r[2] && r[0] < x + w && y < r[3] && r[1] < y + h) return true;
    }
    return false;
  };

  for (const t of ordered) {
    const [x1, y1, , y2] = t.rbox;
    const { text, sub } = labelText(t, smoke, DETAIL_ROLES.has(roleOf(t)));
    const detail = detailIds.includes(t.id) ? detailText(t) : "";
    // Width is the widest line, not just the chip: the sub-line and the
    // training detail line are routinely longer than the label itself.
    // Sub/detail lines render smaller but with wider tracking; measure them
    // generously — under-measuring is what let two sub-lines touch.
    const w = Math.max(
      text.length * CHAR_W + LABEL_PAD * 2 + 24,
      sub.length * (CHAR_W * 0.98),
      detail.length * (CHAR_W * 0.9)
    );
    const h = LABEL_H + (sub ? 13 : 0) + (detail ? 11 : 0);
    const x = Math.min(Math.max(2, x1), fw - w - 2);

    // Try the natural anchor first (just above the object), then below it,
    // then progressively further away. A label that cannot find clear space
    // still lands somewhere legible rather than on top of mission chrome.
    const step = h + 4;
    const yCandidates: number[] = [y1 - h - 4, y2 + 4];
    for (let k = 1; k <= 6; k++) {
      yCandidates.push(y1 - h - 4 - k * step);
      yCandidates.push(y2 + 4 + k * step);
    }
    // Sideways escapes: park the label just clear of a chrome card instead of
    // stacking it further and further from the object it describes.
    const xCandidates = [x];
    for (const r of reserved) {
      const leftOfCard = r[0] - w - 4;
      if (leftOfCard > 2) xCandidates.push(leftOfCard);
      const rightOfCard = r[2] + 4;
      if (rightOfCard + w < fw - 2) xCandidates.push(rightOfCard);
    }

    let px = x;
    let py: number | null = null;
    outer: for (const cy of yCandidates) {
      if (cy < minY || cy > maxY) continue;
      for (const cx of xCandidates) {
        if (!hits(cx, cy, w, h)) {
          px = cx;
          py = cy;
          break outer;
        }
      }
    }
    if (py == null) {
      // Second pass: overlapping another label is bad, but sitting under the
      // mini-map or the instrumentation card is worse — that text is simply
      // gone. Relax label-label collision, keep chrome inviolate.
      const clearOfChrome = (cx: number, cy: number) =>
        !reserved.some((r) => cx < r[2] && r[0] < cx + w && cy < r[3] && r[1] < cy + h);
      outer2: for (const cy of yCandidates) {
        if (cy < minY || cy > maxY) continue;
        for (const cx of xCandidates) {
          if (clearOfChrome(cx, cy)) {
            px = cx;
            py = cy;
            break outer2;
          }
        }
      }
    }
    if (py == null) {
      // Nowhere clear at all. A person or a fire keeps its label even if it
      // has to overlap something — losing that label is unacceptable. A door
      // or a window gives its label up and keeps only its outline, because
      // unreadable stacked text tells the firefighter nothing anyway.
      if (t.priority < 8) continue;
      py = Math.max(minY, Math.min(y1 - h - 4, maxY));
    }
    placed.push({ t, x: px, y: py, w, h, text, sub, detail });
  }
  return placed;
}

// ------------------------------------------------------------- geometry

function bracketPath(x1: number, y1: number, x2: number, y2: number): string {
  const arm = Math.max(7, Math.min(x2 - x1, y2 - y1) * 0.24);
  return [
    `M ${x1} ${y1 + arm} L ${x1} ${y1} L ${x1 + arm} ${y1}`,
    `M ${x2 - arm} ${y1} L ${x2} ${y1} L ${x2} ${y1 + arm}`,
    `M ${x2} ${y2 - arm} L ${x2} ${y2} L ${x2 - arm} ${y2}`,
    `M ${x1 + arm} ${y2} L ${x1} ${y2} L ${x1} ${y2 - arm}`,
  ].join(" ");
}

/** Person / firefighter: brackets + centre tick + soft halo. */
function PersonMark({ t, color }: { t: RenderTrack; color: string }) {
  const [x1, y1, x2, y2] = t.rbox;
  const possible = isPossible(t);
  return (
    <g>
      <path d={bracketPath(x1, y1, x2, y2)} stroke={color} strokeWidth={4}
        strokeOpacity={0.28} fill="none" filter="url(#ps-glow)" />
      <path
        d={bracketPath(x1, y1, x2, y2)}
        stroke={color}
        strokeWidth={possible ? 2 : 2.8}
        strokeDasharray={possible ? "6 5" : undefined}
        fill="none"
      />
      {/* where the body actually stands — for fast pointing and range calls */}
      <line x1={(x1 + x2) / 2} y1={y2 - 1} x2={(x1 + x2) / 2} y2={y2 + 6}
        stroke={color} strokeWidth={1.6} strokeOpacity={0.8} />
    </g>
  );
}

/** Fire / hotspot: bracketed box, light fill, breathing outline. */
function HazardMark({ t, color }: { t: RenderTrack; color: string }) {
  const [x1, y1, x2, y2] = t.rbox;
  const possible = isPossible(t);
  return (
    <g>
      <rect x={x1} y={y1} width={x2 - x1} height={y2 - y1} fill={color}
        fillOpacity={0.08} />
      <rect x={x1} y={y1} width={x2 - x1} height={y2 - y1} fill="none"
        stroke={color} strokeWidth={3.5} strokeOpacity={0.22}
        filter="url(#ps-glow)" className="animate-breathe" />
      <path d={bracketPath(x1, y1, x2, y2)} stroke={color}
        strokeWidth={possible ? 2 : 3} strokeDasharray={possible ? "6 5" : undefined}
        fill="none" />
    </g>
  );
}

/** Door: uprights + head rail + threshold, the shape you step through. */
function DoorMark({
  t,
  color,
  emphasize,
}: {
  t: RenderTrack;
  color: string;
  emphasize: boolean;
}) {
  const [x1, y1, x2, y2] = t.rbox;
  const possible = isPossible(t);
  return (
    <g>
      {emphasize && (
        <rect x={x1} y={y1} width={x2 - x1} height={y2 - y1} fill={color}
          fillOpacity={0.09} stroke={color} strokeWidth={3.5} strokeOpacity={0.3}
          filter="url(#ps-glow)" />
      )}
      <path
        d={`M ${x1} ${y2} L ${x1} ${y1} L ${x2} ${y1} L ${x2} ${y2}`}
        fill="none"
        stroke={color}
        strokeWidth={possible ? 2 : 2.6}
        strokeDasharray={possible ? "6 5" : undefined}
      />
      <line x1={x1} y1={y2} x2={x2} y2={y2} stroke={color} strokeWidth={3}
        strokeOpacity={0.95} />
    </g>
  );
}

/** Exit sign / window: bracketed box with an outer glow frame. */
function ExitMark({ t, color }: { t: RenderTrack; color: string }) {
  const [x1, y1, x2, y2] = t.rbox;
  return (
    <g>
      <rect x={x1 - 2} y={y1 - 2} width={x2 - x1 + 4} height={y2 - y1 + 4}
        fill="none" stroke={color} strokeWidth={4} strokeOpacity={0.3}
        filter="url(#ps-glow)" />
      <rect x={x1} y={y1} width={x2 - x1} height={y2 - y1} fill={color}
        fillOpacity={0.1} stroke={color} strokeWidth={2.4} />
    </g>
  );
}

function UnknownMark({ t, color }: { t: RenderTrack; color: string }) {
  const [x1, y1, x2, y2] = t.rbox;
  return (
    <rect x={x1} y={y1} width={x2 - x1} height={y2 - y1} fill="none" stroke={color}
      strokeWidth={1.4} strokeOpacity={0.7} strokeDasharray="4 6" />
  );
}

// ------------------------------------------------------------------ labels

function LabelChip({ p, color, detail }: { p: Placed; color: string; detail: boolean }) {
  const t = p.t;
  const possible = isPossible(t);
  const cc = confColor(t.rconf);
  const barW = 16;
  return (
    <g opacity={t.alpha}>
      {/* Confirmed detections get a filled chip (fast to read), uncertain ones
          a dark chip with a coloured rule — visually subordinate on purpose. */}
      <rect x={p.x} y={p.y} width={p.w} height={LABEL_H}
        fill={possible ? "#070c12" : color} fillOpacity={possible ? 0.88 : 0.92}
        stroke={possible ? color : "none"} strokeOpacity={0.55} strokeWidth={1} />
      <rect x={p.x} y={p.y} width={2.5} height={LABEL_H} fill={cc} />
      <rect x={p.x + LABEL_PAD + 2} y={p.y + LABEL_H / 2 - 2} width={barW} height={4}
        fill={possible ? "#ffffff" : "#04070a"} fillOpacity={0.22} />
      <rect x={p.x + LABEL_PAD + 2} y={p.y + LABEL_H / 2 - 2}
        width={Math.max(1.5, barW * Math.min(1, t.rconf))} height={4} fill={cc} />
      <text x={p.x + LABEL_PAD + barW + 7} y={p.y + LABEL_H / 2 + 4} fontSize={11.5}
        fontWeight={700} letterSpacing="0.05em" fill={possible ? "#e8f0f6" : "#04070a"}>
        {p.text}
      </text>
      {p.sub && (
        <text x={p.x + 1} y={p.y + LABEL_H + 11} fontSize={10} letterSpacing="0.07em"
          fill={color} fillOpacity={0.95}>
          {p.sub}
        </text>
      )}
      {detail && p.detail && (
        // Training mode: the tracker's own vitals, so an instructor can see
        // why a label degraded rather than guessing. Laid out by `layout`, so
        // the collision solver knows this line exists.
        <text x={p.x + 1} y={p.y + LABEL_H + (p.sub ? 22 : 11)} fontSize={9}
          letterSpacing="0.07em" fill="#94a3b8">
          {p.detail}
        </text>
      )}
    </g>
  );
}

// ------------------------------------------------------------------- layer

export default function DetectionLayer({
  tracks,
  fw,
  fh,
  mode,
  smoke = 0,
  colorblind = false,
  showLabels = true,
  emphasizeDoors = false,
  safeTop = 0,
  safeBottom = 0,
  reserved = [],
}: {
  tracks: RenderTrack[];
  fw: number;
  fh: number;
  mode: MissionMode;
  smoke?: number;
  colorblind?: boolean;
  showLabels?: boolean;
  emphasizeDoors?: boolean;
  safeTop?: number;
  safeBottom?: number;
  /** Regions occupied by HUD cards, which labels must route around. */
  reserved?: Rect[];
}) {
  const visible = tracks.filter(
    (t) => !isSuppressed(t) && roleVisible(roleOf(t), mode)
  );

  // Outlines are cheap to read; a wall of text is not. A ceiling full of warm
  // patches gets its outlines and one line in the thermal chip — only the
  // hottest few earn a label, and only the most important things overall do.
  const hotspotRank = visible
    .filter((t) => t.cls === "hotspot")
    .sort((a, b) => (b.max_temp_c ?? 0) - (a.max_temp_c ?? 0))
    .slice(0, MAX_HOTSPOT_LABELS)
    .map((t) => t.id);
  const ranked = visible
    .filter((t) => t.cls !== "hotspot" || hotspotRank.includes(t.id))
    .sort((a, b) => b.priority - a.priority || b.rconf - a.rconf);
  const labelled = ranked.slice(
    0, mode === "TRAINING" ? MAX_LABELS_TRAINING : MAX_LABELS
  );
  const detailIds = mode === "TRAINING"
    ? labelled.slice(0, MAX_DETAIL_LABELS).map((t) => t.id)
    : [];

  const placed = showLabels
    ? layout(labelled, fw, fh, smoke, safeTop, safeBottom, reserved, detailIds)
    : [];

  return (
    <svg
      viewBox={`0 0 ${fw} ${fh}`}
      preserveAspectRatio="none"
      className="absolute inset-0 w-full h-full pointer-events-none"
      style={{ fontFamily: "var(--font-sans)" }}
    >
      <defs>
        <filter id="ps-glow" x="-60%" y="-60%" width="220%" height="220%">
          <feGaussianBlur stdDeviation="3.5" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {visible.map((t) => {
        const role = roleOf(t);
        const color = colorOf(role, colorblind);
        return (
          <g key={t.id} opacity={t.alpha}>
            {role === "victim" || role === "crew" ? (
              <PersonMark t={t} color={color} />
            ) : role === "critical" || role === "heat" ? (
              <HazardMark t={t} color={color} />
            ) : role === "door" ? (
              <DoorMark t={t} color={color} emphasize={emphasizeDoors} />
            ) : role === "exit" ? (
              <ExitMark t={t} color={color} />
            ) : (
              <UnknownMark t={t} color={color} />
            )}
          </g>
        );
      })}

      {placed.map((p) => (
        <LabelChip
          key={p.t.id}
          p={p}
          color={colorOf(roleOf(p.t), colorblind)}
          detail={mode === "TRAINING"}
        />
      ))}
    </svg>
  );
}
