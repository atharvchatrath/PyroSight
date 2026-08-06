/** Elapsed mission time, MM:SS — rolling up to H:MM:SS past the hour.
 *
 * Without the hour rollover the minutes field just grows: a display left
 * running overnight reads "T+654:39", which is not a clock and reads as a
 * fault. Real entries are nowhere near an hour, but the HUD is also left on
 * through standbys, drills and demos, and it has to stay legible in all of
 * them. */
export function missionClock(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `T+${h}:${mm}:${ss}` : `T+${mm}:${ss}`;
}

export function pct(v: number): string {
  return `${Math.round(v * 100)}%`;
}

export function clockTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString([], {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export const severityColor: Record<string, string> = {
  critical: "text-danger",
  warning: "text-warn",
  info: "text-accent",
};
