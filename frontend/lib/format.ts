export function missionClock(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `T+${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
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
