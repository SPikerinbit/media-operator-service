/** Wallpaper campfire. Broad petals share one base. The center peak is tallest. */

export type Pt = { x: number; y: number }
type Role = 'body' | 'side' | 'peak' | 'core'
type RGB = [number, number, number]

const COLOR: Record<Role, [string, string, string]> = {
  body: ['#FF9A1F', '#FFB02A', '#FFC83C'],
  side: ['#FF9A1F', '#FFC04A', '#FFD36A'],
  peak: ['#FFB02A', '#FFC83C', '#FFE56A'],
  core: ['#FFE56A', '#FFF3C4', '#FFF6C4'],
}

type Spec = { role: Role; h: number; w: number; lean: number; phase: number; melt: number }

/** Wide through the middle, then a short blunt end. The last tenth is the only pinch. */
function halfAt(t: number) {
  const straight = 1 - t * 0.7
  const bow = Math.sin(t * Math.PI) * 0.36 * (1 - t * 0.15)
  return straight + bow
}

const PETALS: Spec[] = [
  { role: 'body', h: 42, w: 40, lean: 0, phase: 0.15, melt: 0.08 },
  { role: 'side', h: 32, w: 30, lean: -10, phase: 1.8, melt: 0.55 },
  { role: 'side', h: 38, w: 26, lean: 12, phase: 2.4, melt: 0.48 },
  { role: 'peak', h: 68, w: 30, lean: -2, phase: 0.55, melt: 0.12 },
  { role: 'core', h: 30, w: 22, lean: 0, phase: 1.1, melt: 0.05 },
]

const CLUSTERS = [
  { x: -30, scale: 0.86, phase: 1.3 },
  { x: 28, scale: 0.9, phase: 2.2 },
  { x: 0, scale: 1, phase: 0 },
]

export type FlameOrigin = { x: number; y: number }

type PetalDraw = {
  role: Role
  points: Pt[]
  base: Pt
  tip: Pt
  cluster: number
}

function rgb(hex: string): RGB {
  const n = Number.parseInt(hex.slice(1), 16)
  return [(n >> 16) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255]
}

function mix(a: RGB, b: RGB, t: number): RGB {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]
}

function localOutline(h: number, w: number, lean: number): Pt[] {
  const steps = 16
  const left: Pt[] = []
  const right: Pt[] = []
  for (let i = 0; i <= steps; i++) {
    const t = i / steps
    const half = w * halfAt(t)
    const y = -h * t
    const x = lean * t * t
    left.push({ x: x - half, y })
    right.push({ x: x + half, y })
  }
  const tipL = left[left.length - 1]
  const tipR = right[right.length - 1]
  const cx = (tipL.x + tipR.x) / 2
  const cy = tipL.y
  const rx = Math.max(2, (tipR.x - tipL.x) / 2)
  const ry = rx * 0.72
  const cap: Pt[] = []
  for (let i = 1; i < 8; i++) {
    const a = (i / 8) * Math.PI
    cap.push({ x: cx + Math.cos(a) * rx, y: cy - Math.sin(a) * ry })
  }
  return [...left, ...cap, ...right.reverse()]
}

function place(points: Pt[], ox: number, oy: number, rot: number): Pt[] {
  const c = Math.cos(rot)
  const s = Math.sin(rot)
  return points.map(p => ({ x: ox + p.x * c - p.y * s, y: oy + p.x * s + p.y * c }))
}

function clusterPetals(time: number, intensity: number, origin: FlameOrigin, unit: number): PetalDraw[] {
  const drawn: PetalDraw[] = []
  if (intensity <= 0.01) return drawn
  CLUSTERS.forEach((cluster, index) => {
    const ox = origin.x + cluster.x * unit
    const oy = origin.y
    const rot = Math.sin(time * 0.75 + cluster.phase) * 0.05 * intensity
    const scale = cluster.scale * unit
    const ready: { spec: Spec; h: number; w: number; lean: number }[] = []
    for (const spec of PETALS) {
      const t = time + spec.phase + cluster.phase
      const wave = 0.5 + 0.5 * Math.sin(t * 0.92)
      const presence = 1 - spec.melt * (1 - wave)
      const breathe = 0.9 + 0.1 * Math.sin(t * 1.65)
      const lean = (spec.lean + Math.sin(t * 1.08) * 2.2) * scale
      const h = spec.h * scale * breathe * (0.55 + 0.45 * presence) * intensity
      const w = spec.w * scale * (0.88 + 0.12 * presence) * (0.75 + 0.25 * Math.sqrt(intensity))
      ready.push({ spec, h, w, lean })
    }
    for (const item of ready) {
      const h = item.h
      const lean = item.lean
      if (h < 1.5 || item.w < 0.5) continue
      const local = localOutline(h, item.w, lean)
      const points = place(local, ox, oy, rot)
      const base = place([{ x: 0, y: 0 }], ox, oy, rot)[0]
      const tip = place([{ x: lean, y: -h }], ox, oy, rot)[0]
      drawn.push({ role: item.spec.role, points, base, tip, cluster: index })
    }
  })
  return drawn
}

function colorAt(role: Role, y: number, baseY: number, tipY: number, inner: boolean): [number, number, number, number] {
  const span = tipY - baseY || -1
  const t = Math.min(1, Math.max(0, (y - baseY) / span))
  const stops = COLOR[role].map(rgb) as [RGB, RGB, RGB]
  let color = t < 0.45 ? mix(stops[0], stops[1], t / 0.45) : mix(stops[1], stops[2], (t - 0.45) / 0.55)
  if (inner) color = mix(color, stops[2], 0.5)
  return [color[0], color[1], color[2], 1]
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  const radius = Math.min(r, w / 2, h / 2)
  ctx.beginPath()
  ctx.moveTo(x + radius, y)
  ctx.arcTo(x + w, y, x + w, y + h, radius)
  ctx.arcTo(x + w, y + h, x, y + h, radius)
  ctx.arcTo(x, y + h, x, y, radius)
  ctx.arcTo(x, y, x + w, y, radius)
  ctx.closePath()
}

/** Paint the basin. Callers choose the origin at the brazier rim. */
export function paintPetalFire(ctx: CanvasRenderingContext2D, width: number, height: number, time: number, intensity: number, origin: FlameOrigin, unit = width / 520) {
  ctx.clearRect(0, 0, width, height)
  if (intensity <= 0.01) return
  const glow = Math.min(0.3, 0.28 * intensity)
  const pool = ctx.createRadialGradient(origin.x, origin.y, 2, origin.x, origin.y + 4 * unit, 78 * unit)
  pool.addColorStop(0, `rgba(255,154,31,${glow})`)
  pool.addColorStop(0.42, `rgba(255,122,28,${glow * 0.38})`)
  pool.addColorStop(1, 'rgba(255,122,28,0)')
  ctx.fillStyle = pool
  ctx.beginPath()
  ctx.ellipse(origin.x, origin.y + 3 * unit, 74 * unit, 16 * unit, 0, 0, Math.PI * 2)
  ctx.fill()

  const petals = clusterPetals(time, intensity, origin, unit)
  for (const role of ['body', 'side', 'peak', 'core'] as const) {
    for (const petal of petals) {
      if (petal.role !== role) continue
      ctx.beginPath()
      ctx.moveTo(petal.points[0].x, petal.points[0].y)
      for (const pt of petal.points.slice(1)) ctx.lineTo(pt.x, pt.y)
      ctx.closePath()
      const g = ctx.createLinearGradient(petal.base.x, petal.base.y, petal.tip.x, petal.tip.y)
      const stops = COLOR[petal.role]
      g.addColorStop(0, stops[0])
      g.addColorStop(0.46, stops[1])
      g.addColorStop(1, stops[2])
      ctx.fillStyle = g
      ctx.fill()
    }
  }

  const logW = 148 * unit
  const logH = Math.max(4, 8 * unit)
  ctx.fillStyle = '#1C100C'
  roundRect(ctx, origin.x - logW / 2, origin.y - logH * 0.35, logW, logH, logH / 2)
  ctx.fill()
  ctx.fillStyle = 'rgba(90,48,24,0.9)'
  ctx.fillRect(origin.x - logW / 2 + 6 * unit, origin.y - logH * 0.12, logW - 12 * unit, Math.max(1, unit))

  for (const petal of petals) {
    if (petal.role !== 'peak') continue
    const cycle = (time * 0.33 + petal.cluster * 0.37) % 1
    const alpha = cycle < 0.12 ? cycle / 0.12 : cycle > 0.78 ? (1 - cycle) / 0.22 : 1
    ctx.save()
    ctx.globalAlpha = alpha * Math.min(1, intensity * 1.3)
    ctx.translate(petal.tip.x - 6 * unit, petal.tip.y - cycle * 16 * unit)
    ctx.rotate(-0.2)
    ctx.fillStyle = '#FFF1C2'
    roundRect(ctx, -2.2 * unit, -1.6 * unit, 4.4 * unit, 3.2 * unit, 1.1 * unit)
    ctx.fill()
    ctx.restore()
  }
}

/** Same fire as triangles: x, y, r, g, b, a. */
export function buildPetalMesh(width: number, height: number, time: number, intensity: number, origin: FlameOrigin, unit = width / 520) {
  const data: number[] = []
  const push = (x: number, y: number, r: number, g: number, b: number, a: number) => data.push(x, y, r, g, b, a)
  if (intensity <= 0.01) return new Float32Array()
  const glow = Math.min(0.3, 0.28 * intensity)
  const rings = 20
  for (let i = 0; i < rings; i++) {
    const a0 = (i / rings) * Math.PI * 2
    const a1 = ((i + 1) / rings) * Math.PI * 2
    push(origin.x, origin.y + 3 * unit, 1, 0.604, 0.122, glow)
    push(origin.x + Math.cos(a0) * 74 * unit, origin.y + 3 * unit + Math.sin(a0) * 16 * unit, 1, 0.48, 0.11, 0)
    push(origin.x + Math.cos(a1) * 74 * unit, origin.y + 3 * unit + Math.sin(a1) * 16 * unit, 1, 0.48, 0.11, 0)
  }
  const petals = clusterPetals(time, intensity, origin, unit)
  for (const role of ['body', 'side', 'peak', 'core'] as const) {
    for (const petal of petals) {
      if (petal.role !== role || petal.points.length < 3) continue
      const pts = petal.points
      const mid = pts.reduce((acc, pt) => ({ x: acc.x + pt.x / pts.length, y: acc.y + pt.y / pts.length }), { x: 0, y: 0 })
      const inner = colorAt(role, mid.y, petal.base.y, petal.tip.y, true)
      for (let i = 0; i < pts.length; i++) {
        const p = pts[i]
        const q = pts[(i + 1) % pts.length]
        const pc = colorAt(role, p.y, petal.base.y, petal.tip.y, false)
        const qc = colorAt(role, q.y, petal.base.y, petal.tip.y, false)
        push(mid.x, mid.y, inner[0], inner[1], inner[2], 1)
        push(p.x, p.y, pc[0], pc[1], pc[2], 1)
        push(q.x, q.y, qc[0], qc[1], qc[2], 1)
      }
    }
  }
  const logW = 148 * unit
  const logH = Math.max(4, 8 * unit)
  const x0 = origin.x - logW / 2
  const y0 = origin.y - logH * 0.35
  push(x0, y0, 0.11, 0.063, 0.047, 1)
  push(x0 + logW, y0, 0.11, 0.063, 0.047, 1)
  push(x0 + logW, y0 + logH, 0.11, 0.063, 0.047, 1)
  push(x0, y0, 0.11, 0.063, 0.047, 1)
  push(x0 + logW, y0 + logH, 0.11, 0.063, 0.047, 1)
  push(x0, y0 + logH, 0.11, 0.063, 0.047, 1)
  for (const petal of petals) {
    if (petal.role !== 'peak') continue
    const cycle = (time * 0.33 + petal.cluster * 0.37) % 1
    const alpha = (cycle < 0.12 ? cycle / 0.12 : cycle > 0.78 ? (1 - cycle) / 0.22 : 1) * Math.min(1, intensity * 1.3)
    const cx = petal.tip.x - 6 * unit
    const cy = petal.tip.y - cycle * 16 * unit
    const s = 2.2 * unit
    push(cx - s, cy - s, 1, 0.945, 0.761, alpha)
    push(cx + s, cy - s, 1, 0.945, 0.761, alpha)
    push(cx + s, cy + s, 1, 0.945, 0.761, alpha)
    push(cx - s, cy - s, 1, 0.945, 0.761, alpha)
    push(cx + s, cy + s, 1, 0.945, 0.761, alpha)
    push(cx - s, cy + s, 1, 0.945, 0.761, alpha)
  }
  return new Float32Array(data)
}

/** Twelve stills of the same fire, for a lost WebGL context. */
export function petalSequence(frames = 12, width = 256, height = 192) {
  const sheet = document.createElement('canvas')
  sheet.width = width * frames
  sheet.height = height
  const ctx = sheet.getContext('2d')
  if (!ctx) return null
  const origin = { x: width / 2, y: height - 16 }
  for (let i = 0; i < frames; i++) {
    const frame = document.createElement('canvas')
    frame.width = width
    frame.height = height
    const pen = frame.getContext('2d')
    if (!pen) continue
    paintPetalFire(pen, width, height, (i / frames) * 2.6, 1, origin, width / 520)
    ctx.drawImage(frame, i * width, 0)
  }
  return { sheet, frames, width, height }
}
