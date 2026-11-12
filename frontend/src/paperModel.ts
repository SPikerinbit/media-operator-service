/** One task owns one sheet, including its history marks and sampled output. */
export type PaperMark = 'clean' | 'cut' | 'charred'
export const PAPER_WIDTH = 380
export const PAPER_HEIGHT = 520
const surfaces = new Map<string, HTMLCanvasElement>()
export function paperSeed(id: string) {
  let seed = 2166136261
  for (const c of id) seed = Math.imul(seed ^ c.charCodeAt(0), 16777619)
  return seed >>> 0
}
export function paperSurface(id: string, title: string, mark: PaperMark) {
  const key = JSON.stringify([id, title, mark])
  const cached = surfaces.get(key)
  if (cached) return cached
  const paper = document.createElement('canvas')
  paper.width = PAPER_WIDTH; paper.height = PAPER_HEIGHT
  const c = paper.getContext('2d')!
  let seed = paperSeed(id) || 1
  const random = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296 }
  c.save()
  if (mark === 'charred') {
    // Perimeter damage, never a shorter sheet: history is separate from new work.
    c.beginPath(); c.moveTo(8, 3)
    for (let x = 8; x <= 372; x += 7) c.lineTo(x, 2 + random() * 7)
    for (let y = 8; y <= 512; y += 7) c.lineTo(378 - random() * 8 - (random() > .94 ? 10 : 0), y)
    for (let x = 372; x >= 8; x -= 7) c.lineTo(x, 518 - random() * 8)
    for (let y = 512; y >= 8; y -= 7) c.lineTo(2 + random() * 8 + (random() > .94 ? 9 : 0), y)
    c.closePath(); c.clip()
  }
  c.fillStyle = '#f8f4e9'; c.fillRect(0, 0, PAPER_WIDTH, PAPER_HEIGHT)
  for (let i = 0; i < 5500; i++) {
    c.fillStyle = `rgba(82,67,44,${random() * .075})`
    c.fillRect(random() * PAPER_WIDTH, random() * PAPER_HEIGHT, 1, 1)
  }
  c.fillStyle = '#354249'; c.font = '20px "Source Han Sans CN", sans-serif'
  const chars = Array.from(title)
  c.fillText(chars.slice(0, 16).join(''), 26, 46, 328)
  if (chars.length > 16) c.fillText(chars.slice(16, 32).join(''), 26, 75, 328)
  for (let y = 110; y < 490; y += 26) {
    c.fillStyle = '#c5c1b6'; c.fillRect(26, y, 240 + random() * 82, 1.2)
  }
  for (const y of [174, 347]) {
    const fold = c.createLinearGradient(0, y - 4, 0, y + 5)
    fold.addColorStop(0, '#71684b00'); fold.addColorStop(.45, '#71684b24')
    fold.addColorStop(.6, '#ffffff9c'); fold.addColorStop(1, '#ffffff00')
    c.fillStyle = fold; c.fillRect(0, y - 4, PAPER_WIDTH, 9)
  }
  if (mark === 'cut') {
    c.strokeStyle = '#a69a82'; c.lineWidth = 1.5
    for (const x of [76, 152, 228, 304]) {
      c.beginPath(); c.moveTo(x, 520); c.lineTo(x + 2, 430 + random() * 45); c.stroke()
      c.strokeStyle = '#ece5d6'; c.beginPath(); c.moveTo(x, 90); c.lineTo(x, 425); c.stroke()
      c.strokeStyle = '#a69a82'
    }
  }
  if (mark === 'charred') {
    for (let side = 0; side < 4; side++) {
      c.save(); c.translate(PAPER_WIDTH / 2, PAPER_HEIGHT / 2); c.rotate(side * Math.PI / 2)
      const w = side % 2 ? PAPER_HEIGHT : PAPER_WIDTH, h = side % 2 ? PAPER_WIDTH : PAPER_HEIGHT
      const edge = c.createLinearGradient(0, -h / 2, 0, -h / 2 + 25)
      edge.addColorStop(0, '#201914'); edge.addColorStop(.3, '#48311eeb')
      edge.addColorStop(.65, '#9b622e91'); edge.addColorStop(1, '#b2814200')
      c.fillStyle = edge; c.fillRect(-w / 2, -h / 2, w, 25); c.restore()
    }
  }
  c.restore()
  if (surfaces.size >= 80) surfaces.delete(surfaces.keys().next().value!)
  surfaces.set(key, paper)
  return paper
}

export function burnContour(x: number, cut: number, seed: number) {
  return cut - 3 + Math.sin(x * .085 + seed % 37) * 2.4 + Math.sin(x * .21 + seed % 19) * 1.6
}
export function paintBurn(ctx: CanvasRenderingContext2D, paper: HTMLCanvasElement,
  pose: { x: number; y: number; width: number; height: number; edgeY: number; remaining: number }, seed: number) {
  if (pose.remaining <= 0) return
  ctx.save(); ctx.translate(pose.x, pose.y); ctx.scale(pose.width / PAPER_WIDTH, pose.height / PAPER_HEIGHT)
  const cut = Math.min(PAPER_HEIGHT, (pose.edgeY - pose.y) * PAPER_HEIGHT / pose.height)
  ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(PAPER_WIDTH, 0)
  for (let x = PAPER_WIDTH; x >= 0; x -= 2) ctx.lineTo(x, Math.max(0, burnContour(x, cut, seed)))
  ctx.closePath(); ctx.clip(); ctx.drawImage(paper, 0, 0)
  if (pose.remaining < 1) {
    const edge = () => { ctx.beginPath(); for (let x = 0; x <= PAPER_WIDTH; x += 2) {
      const y = burnContour(x, cut, seed); if (x === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y)
    } }
    // Nested soft strokes leave paper -> brown -> charcoal -> a fine ember edge.
    for (const [width, color] of [[24, '#9a622a30'], [14, '#78411b60'], [7, '#35251de8'], [2, '#df863d'], [.7, '#ffe2a0']] as const) {
      edge(); ctx.lineWidth = width; ctx.strokeStyle = color; ctx.stroke()
    }
  }
  ctx.restore()
}
