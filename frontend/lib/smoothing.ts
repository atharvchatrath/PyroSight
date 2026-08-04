// Signal conditioning for the HUD.
//
// The perception engine publishes state at ~18 Hz; the display runs at 60 Hz.
// Drawing raw telemetry therefore looks stepped, and raw per-frame detector
// output shakes — both read as "the AI is unsure" even when it is not, which
// is exactly the wrong message to send under stress.
//
// Two tools fix that:
//   • OneEuroFilter — adaptive low-pass. Heavy smoothing when an object is
//     still (kills jitter), light smoothing when it moves fast (kills lag).
//     Standard in AR tracking for precisely this trade-off.
//   • AngleFilter  — the same, wrapped for headings so 359°→1° never spins
//     the compass the long way round.

class LowPass {
  private y: number | null = null;
  private s: number | null = null;

  filter(x: number, alpha: number): number {
    this.s = this.s == null ? x : alpha * x + (1 - alpha) * this.s;
    this.y = x;
    return this.s;
  }

  get last(): number | null {
    return this.y;
  }

  get value(): number | null {
    return this.s;
  }

  reset(): void {
    this.y = null;
    this.s = null;
  }
}

function alphaFor(cutoff: number, dt: number): number {
  const tau = 1 / (2 * Math.PI * cutoff);
  return 1 / (1 + tau / dt);
}

export class OneEuroFilter {
  private x = new LowPass();
  private dx = new LowPass();
  private prev: number | null = null;

  constructor(
    private minCutoff = 1.1,
    private beta = 0.045,
    private dCutoff = 1.2
  ) {}

  /** dt in seconds. */
  filter(value: number, dt: number): number {
    if (!Number.isFinite(value)) return this.prev ?? 0;
    const step = dt > 0 ? dt : 1 / 60;
    const rate = this.prev == null ? 0 : (value - this.prev) / step;
    this.prev = value;
    const edx = this.dx.filter(rate, alphaFor(this.dCutoff, step));
    const cutoff = this.minCutoff + this.beta * Math.abs(edx);
    return this.x.filter(value, alphaFor(cutoff, step));
  }

  get velocity(): number {
    return this.dx.value ?? 0;
  }

  get value(): number | null {
    return this.x.value;
  }
}

/** Shortest-path angular difference in degrees, wrapped to [-180, 180). */
export function angleDelta(a: number, b: number): number {
  return ((a - b + 540) % 360) - 180;
}

/** One-euro filter that lives on the circle (headings, relative bearings). */
export class AngleFilter {
  private acc: number | null = null;
  private inner: OneEuroFilter;

  constructor(minCutoff = 1.4, beta = 0.03) {
    this.inner = new OneEuroFilter(minCutoff, beta, 1.2);
  }

  filter(deg: number, dt: number): number {
    if (this.acc == null) {
      this.acc = deg;
      return this.inner.filter(deg, dt);
    }
    // Unwrap into a continuous accumulator before filtering.
    this.acc += angleDelta(deg, this.acc);
    return this.inner.filter(this.acc, dt);
  }
}

/** Critically-damped approach — used for scalar UI values (opacity, scale). */
export function approach(current: number, target: number, dt: number, tau = 0.12): number {
  if (tau <= 0) return target;
  const k = 1 - Math.exp(-dt / tau);
  return current + (target - current) * k;
}

export const clamp = (v: number, lo: number, hi: number): number =>
  v < lo ? lo : v > hi ? hi : v;
