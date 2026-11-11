/** Shared study-room motion. Springs overshoot about 5% and then settle. */

export const SPRING = {
  /** Landing and flights. ζ ≈ 0.70 → ~5% overshoot. */
  soft: { stiffness: 180, damping: 18.8, mass: 1 },
  /** Drawers and pushed desks. Heavier, slower to leave, ~3% overshoot. */
  mass: { stiffness: 92, damping: 14.2, mass: 1.7 },
  /** Button and wax release. */
  press: { stiffness: 460, damping: 30, mass: 1 },
} as const

export type Spring = { stiffness: number; damping: number; mass: number }

/** Unit step response. 0 at t=0, passes 1, settles near 1. */
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
  const min = spring.mass > 1.2 ? 420 : 240
  return ms > min && Math.abs(springAt(ms, spring) - 1) < 0.0035
}

/** C2 ramp from 0 to 1 between a and b. Overlapping windows keep multi-stage motion moving. */
export function ramp(u: number, a: number, b: number) {
  if (u <= a) return 0
  if (u >= b) return 1
  const t = (u - a) / (b - a)
  return t * t * t * (t * (t * 6 - 15) + 10)
}

export function lerp(a: number, b: number, t: number) {
  return a + (b - a) * t
}

export const EASE_SPRING = 'cubic-bezier(.18, 1.28, .32, 1)'
