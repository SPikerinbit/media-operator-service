/** Layered canvas hearth flame: glowing ember bed, multi-harmonic tongues, incandescent core, and drifting sparks. */
import { bindFrame } from './workbenchScheduler'

let flameSeq = 0

export type FlameVisual = {
  intensity: number
  loop: boolean
  reduced: boolean
  hidden: boolean
}

export type PetalFlame = {
  set: (next: FlameVisual) => void
  resize: (cssWidth: number, cssHeight: number) => void
  dispose: () => void
}

type RGB = [number, number, number]

function rgb(hex: string): RGB {
  const n = Number.parseInt(hex.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function css(color: RGB, alpha: number) {
  return `rgba(${color[0] | 0},${color[1] | 0},${color[2] | 0},${Math.max(0, Math.min(1, alpha))})`
}

const EMBER = rgb('#C83B0E')
const DEEP = rgb('#E25A12')
const ORANGE = rgb('#FF8A1A')
const AMBER = rgb('#FFB434')
const GOLD = rgb('#FFD25A')
const CORE = rgb('#FFF2C8')

function tongue(
  ctx: CanvasRenderingContext2D,
  time: number,
  phase: number,
  offsetX: number,
  height: number,
  width: number,
  lean: number,
  colors: [RGB, RGB, RGB],
  opacity = 1,
) {
  const fast = time * (Math.PI * 2 / 1.18) + phase
  const mid = Math.sin(time * (Math.PI * 2 / 2.75) + phase * 1.4)
  const slow = Math.sin(time * (Math.PI * 2 / 5.1) + phase)
  const stretch = 0.85 + 0.14 * Math.sin(fast) + mid * 0.05 + slow * 0.04
  const bend = Math.sin(fast * 0.55 + phase) * lean + mid * lean * 0.45
  const tipX = offsetX + bend * width * 0.28
  const tipY = -height * stretch
  ctx.beginPath()
  ctx.moveTo(offsetX - width * 0.48, 2)
  ctx.bezierCurveTo(
    offsetX - width * 0.58,
    -height * 0.28,
    tipX - width * 0.2,
    tipY * 0.68,
    tipX,
    tipY,
  )
  ctx.bezierCurveTo(
    tipX + width * 0.12,
    tipY * 0.65,
    offsetX + width * 0.42,
    -height * 0.24,
    offsetX + width * 0.38,
    2,
  )
  ctx.closePath()
  const paint = ctx.createLinearGradient(offsetX, 6, tipX, tipY)
  paint.addColorStop(0, css(colors[0], 0.94 * opacity))
  paint.addColorStop(0.5, css(colors[1], 0.86 * opacity))
  paint.addColorStop(1, css(colors[2], 0))
  ctx.fillStyle = paint
  ctx.fill()
}

function paintFlame(ctx: CanvasRenderingContext2D, width: number, height: number, time: number, alpha: number) {
  ctx.clearRect(0, 0, width, height)
  if (alpha <= 0.02) return
  ctx.save()
  ctx.translate(width / 2, height * 0.8)
  ctx.globalCompositeOperation = 'lighter'

  const pulse = 0.88 + 0.12 * Math.sin(time * 4.3)
  const sway = Math.sin(time * 2.8) * 4

  // Glowing coal/ember bed seated inside the brazier mouth (fades to 0 strictly inside canvas bounds).
  const coalR = Math.min(width * 0.34, height * 0.24)
  const coal = ctx.createRadialGradient(0, 6, 3, 0, 6, coalR)
  coal.addColorStop(0, css(AMBER, 0.44 * alpha * pulse))
  coal.addColorStop(0.5, css(EMBER, 0.24 * alpha * pulse))
  coal.addColorStop(1, 'rgba(180, 42, 8, 0)')
  ctx.fillStyle = coal
  ctx.beginPath()
  ctx.arc(0, 6, coalR, 0, Math.PI * 2)
  ctx.fill()

  // Soft ambient warmth halo (circular radius bounded inside canvas so no rectangular/ring cutoff ever appears).
  const haloR = Math.min(width * 0.42, height * 0.46)
  const glow = ctx.createRadialGradient(sway * 0.25, -height * 0.08, 4, sway * 0.25, -height * 0.08, haloR)
  glow.addColorStop(0, `rgba(255, 196, 86, ${0.38 * alpha * pulse})`)
  glow.addColorStop(0.45, `rgba(255, 128, 30, ${0.15 * alpha})`)
  glow.addColorStop(0.78, `rgba(255, 96, 18, ${0.04 * alpha})`)
  glow.addColorStop(1, 'rgba(255, 80, 10, 0)')
  ctx.fillStyle = glow
  ctx.beginPath()
  ctx.arc(sway * 0.25, -height * 0.08, haloR, 0, Math.PI * 2)
  ctx.fill()

  ctx.globalAlpha = Math.min(1, 0.38 + alpha * 0.62)
  const scale = 0.38 + 0.62 * alpha
  ctx.save()
  ctx.translate(0, 4)
  ctx.scale(scale, scale)
  const h = height * 0.58
  const w = width * 0.21

  // Multi-layered tongues: deep base -> side licks -> main golden flame -> bright core.
  tongue(ctx, time, 2.6, -w * 0.38, h * 0.56, w * 0.92, -1.05, [EMBER, DEEP, ORANGE], 0.88)
  tongue(ctx, time, 0.9, w * 0.34, h * 0.64, w * 0.86, 1.0, [DEEP, ORANGE, AMBER], 0.9)
  tongue(ctx, time + 0.3, 4.1, -w * 0.14, h * 0.76, w * 0.78, -0.55, [ORANGE, AMBER, GOLD], 0.92)
  tongue(ctx, time + Math.sin(time * 2.1) * 0.05, 0, 0, h * 1.02, w * 0.74, 0.35, [ORANGE, GOLD, AMBER], 0.98)
  tongue(ctx, time + 0.16, 1.3, w * 0.05, h * 0.48, w * 0.32, 0.08, [AMBER, GOLD, CORE], 0.96)
  ctx.restore()

  // Drifting ember sparks rising gently from the coal bed.
  for (let i = 0; i < 9; i++) {
    const speed = 0.52 + (i % 3) * 0.18
    const life = (time * speed + i * 0.29) % 1
    const rise = life * h * 0.96
    const drift = Math.sin(time * (2.2 + i * 0.35) + i * 1.7) * w * (0.45 + life * 0.55)
    const radius = (1.1 + (i % 3) * 0.45) * (1 - life * 0.55)
    ctx.fillStyle = css(life < 0.35 ? CORE : life < 0.7 ? GOLD : ORANGE, (1 - life) * 0.85 * alpha)
    ctx.beginPath()
    ctx.arc(drift, -rise, radius, 0, Math.PI * 2)
    ctx.fill()
  }
  ctx.restore()
}

export function mountPetalFlame(canvas: HTMLCanvasElement): PetalFlame {
  const ctx = canvas.getContext('2d')
  const jobId = 'flame:' + (++flameSeq)
  let disposed = false
  let stopJob: (() => void) | null = null
  let last = 0
  let shown = 0
  let visual: FlameVisual = { intensity: 0, loop: false, reduced: false, hidden: true }
  let cssWidth = 140
  let cssHeight = 150

  function applySize() {
    const dpr = Math.min(devicePixelRatio || 1, 2)
    canvas.width = Math.max(1, Math.round(cssWidth * dpr))
    canvas.height = Math.max(1, Math.round(cssHeight * dpr))
    ctx?.setTransform(dpr, 0, 0, dpr, 0, 0)
  }

  function paint(now: number) {
    if (!ctx) return
    paintFlame(ctx, cssWidth, cssHeight, visual.reduced ? 0.4 : now / 1000, shown)
  }

  function stop() {
    stopJob?.()
    stopJob = null
  }

  function ease(now: number) {
    const dt = last ? Math.min(50, now - last) : 16
    last = now
    const step = visual.reduced ? 1 : 1 - Math.exp(-dt / 140)
    shown += (visual.intensity - shown) * step
    if (Math.abs(visual.intensity - shown) < 0.004) shown = visual.intensity
  }

  function keep() {
    return !disposed && !visual.hidden && ((visual.loop && !visual.reduced) || shown !== visual.intensity)
  }

  function tick(now: number) {
    if (disposed || !ctx) { stopJob = null; return false }
    if (visual.hidden) {
      shown = 0
      ctx.clearRect(0, 0, cssWidth, cssHeight)
      stopJob = null
      return false
    }
    ease(now)
    paint(now)
    if (keep()) return true
    stopJob = null
    return false
  }

  function start() {
    if (!stopJob && !disposed) stopJob = bindFrame(jobId, tick)
  }

  applySize()
  return {
    set(next) {
      visual = next
      if (disposed || !ctx) return
      if (next.hidden) {
        shown = 0
        last = 0
        stop()
        ctx.clearRect(0, 0, cssWidth, cssHeight)
        return
      }
      if (next.loop && !next.reduced) start()
      else { stop(); ease(performance.now()); paint(performance.now()) }
    },
    resize(width, height) {
      if (width < 2 || height < 2) return
      cssWidth = width
      cssHeight = height
      applySize()
      if (!visual.hidden) paint(performance.now())
    },
    dispose() {
      disposed = true
      stop()
      canvas.width = canvas.height = 0
    },
  }
}

export function warmEdge(ctx: CanvasRenderingContext2D, x: number, y: number, width: number) {
  const band = ctx.createLinearGradient(x, y - 18, x, y + 6)
  band.addColorStop(0, 'rgba(255,176,42,0)')
  band.addColorStop(0.7, 'rgba(255,154,31,0.22)')
  band.addColorStop(1, 'rgba(255,120,30,0)')
  ctx.fillStyle = band
  ctx.fillRect(x, y - 18, width, 24)
}
