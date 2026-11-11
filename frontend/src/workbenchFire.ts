/** Canvas flame. One tall tongue, two lower sides, a thin bright core, a fixed root. */

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

function mix(a: RGB, b: RGB, t: number): RGB {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]
}

function css(color: RGB, alpha: number) {
  return `rgba(${color[0] | 0},${color[1] | 0},${color[2] | 0},${alpha})`
}

const GOLD = rgb('#FFC83C')
const AMBER = rgb('#FFB02A')
const ORANGE = rgb('#FF8A1A')
const DEEP = rgb('#E25A12')
const CORE = rgb('#FFE7A0')

function tongue(ctx: CanvasRenderingContext2D, time: number, phase: number, height: number, width: number, lean: number, colors: [RGB, RGB, RGB]) {
  const cycle = time * (Math.PI * 2 / 1.25) + phase
  const slow = Math.sin(time * (Math.PI * 2 / 4.6) + phase)
  const stretch = 0.84 + 0.16 * Math.sin(cycle) + slow * 0.04
  const bend = Math.sin(cycle * 0.5 + phase) * lean + slow * lean * 0.5
  const tipX = bend * width * 0.22
  const tipY = -height * stretch
  ctx.beginPath()
  ctx.moveTo(-width * 0.46, 0)
  ctx.bezierCurveTo(-width * 0.55, -height * 0.28, tipX - width * 0.16, tipY * 0.72, tipX, tipY)
  ctx.bezierCurveTo(tipX + width * 0.07, tipY * 0.68, width * 0.32, -height * 0.22, width * 0.34, 0)
  ctx.closePath()
  const paint = ctx.createLinearGradient(0, 4, tipX, tipY)
  paint.addColorStop(0, css(colors[0], 0.96))
  paint.addColorStop(0.55, css(colors[1], 0.9))
  paint.addColorStop(1, css(colors[2], 0))
  ctx.fillStyle = paint
  ctx.fill()
}

function paintFlame(ctx: CanvasRenderingContext2D, width: number, height: number, time: number, alpha: number) {
  ctx.clearRect(0, 0, width, height)
  if (alpha <= 0.02) return
  ctx.save()
  ctx.translate(width / 2, height - 2)
  ctx.globalAlpha = Math.min(1, 0.45 + alpha * 0.55)
  const scale = 0.28 + 0.72 * alpha
  ctx.scale(scale, scale)
  const h = height * 0.96
  const w = width * 0.42
  tongue(ctx, time, 2.4, h * 0.58, w * 0.72, -1, [DEEP, ORANGE, AMBER])
  tongue(ctx, time, 0.8, h * 0.64, w * 0.66, 1.05, [ORANGE, AMBER, GOLD])
  tongue(ctx, time, 0, h, w * 0.62, 0.42, [ORANGE, GOLD, AMBER])
  tongue(ctx, time + 0.15, 1.1, h * 0.34, w * 0.16, 0.08, [AMBER, GOLD, CORE])
  const spark = Math.sin(time * 2.2) * Math.sin(time * 0.31)
  if (spark > 0.82) {
    const life = (spark - 0.82) / 0.18
    ctx.fillStyle = css(GOLD, life * 0.85)
    ctx.beginPath()
    ctx.arc(Math.sin(time * 3.4) * w * 1.4, -h * (0.62 + life * 0.28), 1.5, 0, Math.PI * 2)
    ctx.fill()
  }
  ctx.restore()
}

export function mountPetalFlame(canvas: HTMLCanvasElement): PetalFlame {
  const ctx = canvas.getContext('2d')
  let disposed = false
  let raf = 0
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
    cancelAnimationFrame(raf)
    raf = 0
  }

  applySize()
  return {
    set(next) {
      visual = next
      if (disposed || !ctx) return
      const now = performance.now()
      const dt = last ? Math.min(50, now - last) : 16
      last = now
      if (next.hidden) {
        shown = 0
        ctx.clearRect(0, 0, cssWidth, cssHeight)
        return
      }
      const ease = next.reduced ? 1 : 1 - Math.exp(-dt / 180)
      shown += (next.intensity - shown) * ease
      if (Math.abs(next.intensity - shown) < 0.004) shown = next.intensity
      paint(now)
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
