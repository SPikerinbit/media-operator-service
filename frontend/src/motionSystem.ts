/** Shared study-room motion. Responsive, instant-takeoff curves with refined physical settle. */

export const SPRING = {
  /** Fast, crisp physical flights: page turn, wood throw, returned tears (~330ms). */
  snappy: { stiffness: 320, damping: 28, mass: 1 },
  /** Landing and gentle settles (~420ms, subtle ~3% overshoot). */
  soft: { stiffness: 240, damping: 24, mass: 1 },
  /** Weighted parcels and routing letters — decisive takeoff without sluggish lag. */
  mass: { stiffness: 185, damping: 22, mass: 1.15 },
  /** Button, wax seal stamp, and mechanical detent. */
  press: { stiffness: 520, damping: 34, mass: 1 },
} as const

export type Spring = { stiffness: number; damping: number; mass: number }

/** Unit step response. 0 at t=0, smoothly reaches 1 with optional light overshoot. */
export function springAt(ms: number, spring: Spring = SPRING.soft) {
  const t = Math.max(0, ms) / 1000
  const w0 = Math.sqrt(spring.stiffness / spring.mass)
  const zeta = spring.damping / (2 * Math.sqrt(spring.stiffness * spring.mass))
  if (zeta < 1) {
    const wd = w0 * Math.sqrt(1 - zeta * zeta)
    const e = Math.exp(-zeta * w0 * t)
    return 1 - e * (Math.cos(wd * t) + (zeta * w0 / wd) * Math.sin(wd * t))
  }
  const e = Math.exp(-w0 * t)
  return 1 - e * (1 + w0 * t)
}

export function springSettled(ms: number, spring: Spring = SPRING.soft) {
  const min = spring.mass > 1.1 ? 260 : 180
  return ms > min && Math.abs(springAt(ms, spring) - 1) < 0.004
}

/** C2 quintic smootherstep from 0 to 1 between a and b. */
export function ramp(u: number, a: number, b: number) {
  if (u <= a) return 0
  if (u >= b) return 1
  const t = (u - a) / (b - a)
  return t * t * t * (t * (t * 6 - 15) + 10)
}

/** Smooth C1 ease-out with immediate initial velocity (zero start lag). */
export function easeOutCubic(t: number) {
  const u = Math.min(1, Math.max(0, t))
  const inv = 1 - u
  return 1 - inv * inv * inv
}

/** Stronger deceleration ease-out for crisp flights and settles. */
export function easeOutQuart(t: number) {
  const u = Math.min(1, Math.max(0, t))
  const inv = 1 - u
  return 1 - inv * inv * inv * inv
}

/** Gravity shut + two damped metallic rebounds for the top-hinged 3D mailbox flap (always >= 0 deg). */
export function flapBounceAngle(t: number, openDeg = 72) {
  const u = Math.min(1, Math.max(0, t))
  if (u < 0.34) {
    const k = u / 0.34
    return openDeg * (1 - k * k)
  }
  if (u < 0.72) {
    const k = (u - 0.34) / 0.38
    return 14 * Math.sin(Math.PI * k)
  }
  const k = (u - 0.72) / 0.28
  return 3.5 * Math.sin(Math.PI * k)
}

export function lerp(a: number, b: number, t: number) {
  return a + (b - a) * t
}

export const EASE_SETTLE = 'cubic-bezier(0.22, 1, 0.36, 1)'
export const EASE_SPRING = 'cubic-bezier(0.22, 1.10, 0.36, 1)'
