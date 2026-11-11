import { useEffect, useRef, useState } from 'react'
import { useReducedMotion } from 'motion/react'
import { advanceProgress, anchorPixels, burnPaper, currentManifest, shredderPaper, useWorkbenchManifest, woodLanding } from './workbenchAnchors'
import type { Box } from './workbenchAnchors'
import type { Lane } from './workbenchState'
import { bindFrame } from './workbenchScheduler'
import { mountPetalFlame, warmEdge, type PetalFlame } from './workbenchFire'

export const asset = (name: string) => `${import.meta.env.BASE_URL}workbench/${name}.webp`

export function Prop({ name, layer = 'body', className = '', style }: { name: string; layer?: string; className?: string; style?: React.CSSProperties }) {
  return <picture className={'prop ' + className} style={style} aria-hidden="true">
    <img src={asset(`${name}-light-${layer}`)} alt="" draggable={false} />
  </picture>
}

export function ContactShadow({ name }: { name: string }) {
  return <img className="contact-shadow" src={asset(name + '-shadow')} alt="" draggable={false} />
}

export type StripLink = { id: number; refs: number[] }
type Mark = 'clean' | 'cut' | 'charred'

function hash(n: number) {
  const x = Math.sin(n * 127.1) * 43758.5453
  return x - Math.floor(x)
}
function edgeAt(x: number, cut: number) {
  return cut + Math.sin(x * 0.085) * 5 + Math.sin(x * 0.21 + 1.4) * 2.2 + (Math.sin(x * 0.51) > 0.84 ? 8 : 0)
}

function paperSurface(title: string, mark: Mark) {
  const paper = document.createElement('canvas')
  paper.width = 380
  paper.height = 520
  const c = paper.getContext('2d')
  if (!c) return paper
  c.fillStyle = '#FEFEFC'
  c.fillRect(0, 0, 380, 520)
  let seed = 482
  const random = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647 }
  for (let i = 0; i < 5000; i++) { c.fillStyle = `rgba(40,55,60,${random() * 0.035})`; c.fillRect(random() * 380, random() * 520, 1, 1) }
  c.fillStyle = '#28373C'
  c.font = '18px "Source Han Sans CN", sans-serif'
  c.fillText(title.slice(0, 18), 24, 42, 330)
  for (let y = 78; y < 490; y += 28) {
    c.fillStyle = '#DDE3E5'
    c.fillRect(24, y, 250 + random() * 70, 1)
  }
  if (mark === 'cut') {
    c.strokeStyle = '#C4B8A4'
    c.lineWidth = 2
    for (const x of [70, 150, 230, 310]) {
      c.beginPath()
      c.moveTo(x, 60)
      c.lineTo(x + Math.sin(x) * 4, 500)
      c.stroke()
    }
  }
  if (mark === 'charred') {
    c.globalCompositeOperation = 'destination-out'
    c.beginPath()
    c.moveTo(300, 520)
    c.lineTo(380, 430)
    c.lineTo(380, 520)
    c.closePath()
    c.fill()
    c.globalCompositeOperation = 'source-over'
    const g = c.createRadialGradient(360, 500, 8, 330, 460, 80)
    g.addColorStop(0, '#24140E')
    g.addColorStop(0.55, '#6A3A22')
    g.addColorStop(1, 'rgba(106,58,34,0)')
    c.fillStyle = g
    c.fillRect(260, 400, 120, 120)
  }
  return paper
}

const maskCanvas = document.createElement('canvas')

function paintBurn(ctx: CanvasRenderingContext2D, paper: HTMLCanvasElement, pose: { x: number; y: number; width: number; height: number; edgeY: number }) {
  const cut = Math.max(0, Math.min(paper.height, ((pose.edgeY - pose.y) / Math.max(1, pose.height)) * paper.height))
  if (maskCanvas.width !== paper.width || maskCanvas.height !== paper.height) {
    maskCanvas.width = paper.width
    maskCanvas.height = paper.height
  }
  const c = maskCanvas.getContext('2d')
  if (!c) return
  c.clearRect(0, 0, paper.width, paper.height)
  c.save()
  c.beginPath()
  c.moveTo(0, 0)
  c.lineTo(paper.width, 0)
  for (let x = paper.width; x >= 0; x -= 3) c.lineTo(x, Math.max(0, edgeAt(x, cut)))
  c.closePath()
  c.clip()
  c.drawImage(paper, 0, 0)
  c.restore()
  c.beginPath()
  for (let x = 0; x <= paper.width; x += 3) {
    const y = edgeAt(x, cut)
    if (x === 0) c.moveTo(x, y)
    else c.lineTo(x, y)
  }
  c.strokeStyle = '#3A241C'
  c.lineWidth = 5
  c.stroke()
  c.strokeStyle = '#FF9A1F'
  c.lineWidth = 3
  c.stroke()
  c.strokeStyle = '#FFE7A0'
  c.lineWidth = 1.2
  c.stroke()
  c.fillStyle = 'rgba(90,78,70,.55)'
  for (let x = 8; x < paper.width; x += 14) {
    if (hash(x) < 0.45) c.fillRect(x, edgeAt(x, cut) + 3 + hash(x + 3) * 7, 2, 2)
  }
  let lowest = cut
  for (let x = 0; x <= paper.width; x += 3) lowest = Math.max(lowest, edgeAt(x, cut))
  const srcH = Math.min(paper.height, Math.ceil(lowest + 6))
  const destH = pose.height * (srcH / paper.height)
  ctx.drawImage(maskCanvas, 0, 0, paper.width, srcH, pose.x, pose.y, pose.width, destH)
}

let smokeImage: HTMLImageElement | null = null
function drawSmoke(ctx: CanvasRenderingContext2D, x: number, y: number, t: number) {
  if (!smokeImage) {
    smokeImage = new Image()
    smokeImage.src = asset('smoke-atlas')
  }
  if (!smokeImage.complete || smokeImage.naturalWidth < 2) return
  const frame = Math.min(23, Math.floor(Math.max(0, t) * 23))
  const col = frame % 6
  const row = Math.floor(frame / 6)
  const fw = smokeImage.naturalWidth / 6
  const fh = smokeImage.naturalHeight / 4
  ctx.drawImage(smokeImage, col * fw, row * fh, fw, fh, x - 36, y - 90 - t * 20, 72, 80)
}

function layoutOf(el: HTMLElement, origin: HTMLElement): Box {
  const a = el.getBoundingClientRect()
  const b = origin.getBoundingClientRect()
  const sx = b.width ? origin.clientWidth / b.width : 1
  const sy = b.height ? origin.clientHeight / b.height : 1
  return { left: (a.left - b.left) * sx, top: (a.top - b.top) * sy, width: a.width * sx, height: a.height * sy }
}

type Fallen = { id: number; x: number; length: number; bend: number; born: number }

export function PaperProcess({ lane, progress, progressKnown = true, status, title, mark = 'clean', active = true, parked = false, arrived = true, links = [], replaySmoke = false, onStrip, frameKey = '' }: {
  lane: Lane; progress: number; progressKnown?: boolean; status: string; title: string; mark?: Mark; active?: boolean; parked?: boolean
  arrived?: boolean; links?: StripLink[]; replaySmoke?: boolean; onStrip?: (link: StripLink) => void; frameKey?: string
}) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const fireNode = useRef<HTMLCanvasElement>(null)
  const root = useRef<HTMLDivElement>(null)
  const flame = useRef<PetalFlame | null>(null)
  const previous = useRef(status)
  const smokeUntil = useRef(0)
  const goal = useRef(Math.max(0, Math.min(1, progressKnown ? progress / 100 : 0)))
  const displayed = useRef(goal.current)
  const progressRef = useRef(progress)
  const knownRef = useRef(progressKnown)
  const statusRef = useRef(status)
  const parkedRef = useRef(parked)
  const activeRef = useRef(active)
  const arrivedRef = useRef(arrived)
  const landedAt = useRef(0)
  const markRef = useRef(mark)
  const reducedRef = useRef(false)
  const paint = useRef<(now: number) => boolean>(() => false)
  const draws = useRef(0)
  const litAt = useRef(0)
  const painted = useRef(-1)
  const fallen = useRef<Fallen[]>([])
  const fed = useRef(0)
  progressRef.current = progress
  knownRef.current = progressKnown
  statusRef.current = status
  parkedRef.current = parked
  activeRef.current = Boolean(active)
  arrivedRef.current = arrived
  if (arrived && status === 'running' && landedAt.current === 0) landedAt.current = performance.now()
  if (!arrived) landedAt.current = 0
  markRef.current = mark
  const reduced = useReducedMotion()
  reducedRef.current = Boolean(reduced)
  const manifest = useWorkbenchManifest()
  const [box, setBox] = useState<Box | null>(null)
  const [textures, setTextures] = useState<Record<number, string>>({})
  const [tray, setTray] = useState<{ left: number; top: number; width: number } | null>(null)
  const trayKey = useRef('')

  useEffect(() => {
    if (!replaySmoke) return
    smokeUntil.current = performance.now() + 1000
    previous.current = 'succeeded'
  }, [replaySmoke])
  useEffect(() => {
    if (status === 'succeeded' && previous.current !== 'succeeded' && replaySmoke) smokeUntil.current = performance.now() + 1000
    previous.current = status
  }, [status, replaySmoke])
  useEffect(() => {
    const node = fireNode.current
    if (!node || lane !== 'publish') return
    const mounted = mountPetalFlame(node)
    flame.current = mounted
    return () => { mounted.dispose(); flame.current = null }
  }, [lane])
  useEffect(() => {
    if (!links.length) return
    const paper = paperSurface(title, mark)
    const count = Math.max(1, links.length)
    const next: Record<number, string> = {}
    links.forEach((link, index) => {
      const slice = document.createElement('canvas')
      const sw = Math.max(1, Math.floor(paper.width / count))
      slice.width = sw
      slice.height = paper.height
      slice.getContext('2d')?.drawImage(paper, index * sw, 0, sw, paper.height, 0, 0, sw, slice.height)
      next[link.id] = slice.toDataURL()
    })
    setTextures(next)
  }, [links, title, mark])

  useEffect(() => {
    const node = canvas.current
    const host = root.current
    if (!node || !host) return
    const context = node.getContext('2d')
    if (!context) return
    const paper = paperSurface(title, mark)
    let last = performance.now()
    let visible = !document.hidden
    let wasAway = !activeRef.current
    const resize = () => {
      const dpr = Math.min(devicePixelRatio || 1, 2)
      node.width = Math.round(Math.max(1, host.clientWidth) * dpr)
      node.height = Math.round(Math.max(1, host.clientHeight) * dpr)
      context.setTransform(dpr, 0, 0, dpr, 0, 0)
      const machine = host.querySelector('.process-machine') as HTMLElement | null
      if (machine) setBox(layoutOf(machine, host))
    }
    resize()
    const draw = (now: number) => {
      const machine = host.querySelector('.process-machine') as HTMLElement | null
      if (!machine || host.clientWidth < 2) return false
      const dt = Math.min(80, Math.max(0, now - last))
      last = now
      const spec = currentManifest()
      const state = statusRef.current
      if (knownRef.current) goal.current = advanceProgress(goal.current, Math.max(0, Math.min(1, progressRef.current / 100)), state)
      const running = state === 'running' && !parkedRef.current
      const smoking = now < smokeUntil.current
      const away = !activeRef.current || !visible
      if (away) wasAway = true
      else if (wasAway) { displayed.current = goal.current; wasAway = false }
      const decorative = Boolean(!away && !reducedRef.current && (running || smoking || Math.abs(goal.current - displayed.current) > 0.004 || (lane === 'publish' && running)))
      const smooth = decorative && !reducedRef.current ? 1 - Math.exp(-dt / 160) : 1
      let shown = displayed.current + (goal.current - displayed.current) * smooth
      if (!running && !decorative) shown = goal.current
      if (goal.current < displayed.current && !running) shown = goal.current
      displayed.current = shown
      const since = landedAt.current ? now - landedAt.current : 0
      const intro = landedAt.current ? Math.min(1, since / 700) : (arrivedRef.current ? 1 : 0)
      const ash = landedAt.current && statusRef.current === 'running' ? Math.max(0, Math.min(1, (since - 760) / 1500)) : 0
      const visual = !arrivedRef.current ? 0 : statusRef.current === 'running' ? Math.min(1, shown * intro + (1 - shown) * ash) : shown
      const sheet = canvas.current
      if (lane === 'publish' && sheet) sheet.style.opacity = ''
      const layoutKey = host.clientWidth + 'x' + host.clientHeight
      const paperChanged = Math.abs(visual - painted.current) > 0.001 || host.dataset.layout !== layoutKey
      const local = layoutOf(machine, host)
      let edgeViewport = 0
      if (lane === 'publish') {
        const pose = burnPaper(local, spec, arrivedRef.current ? 1 - visual : 1)
        const drop = local.height * 0.07
        pose.y += drop
        pose.edgeY += drop
        const hostBox = host.getBoundingClientRect()
        const rim = anchorPixels(local, spec.brazier.anchors.rim, spec.brazier.size)
        edgeViewport = hostBox.top + rim.y * (hostBox.height / Math.max(1, host.clientHeight))
        if (paperChanged || smoking) {
          context.clearRect(0, 0, host.clientWidth, host.clientHeight)
          if (arrivedRef.current && pose.height > 1 && pose.edgeY - pose.y > 1) paintBurn(context, paper, pose)
          if (visual > 0.01 && (running || smoking)) warmEdge(context, pose.x, pose.edgeY, pose.width)
          if (smoking) drawSmoke(context, pose.edgeX, pose.y + pose.height * (1 - visual), 1 - (smokeUntil.current - now) / 1000)
          painted.current = visual
          host.dataset.layout = layoutKey
        }
        const fire = fireNode.current
        if (fire && flame.current) {
          const width = Math.min(240, Math.max(180, local.width * 0.5))
          const height = Math.min(220, Math.max(170, width * 0.9))
          if (fire.dataset.size !== width + 'x' + height) {
            fire.dataset.size = width + 'x' + height
            fire.style.left = '0'
            fire.style.top = '0'
            fire.style.width = width + 'px'
            fire.style.height = height + 'px'
            flame.current.resize(width, height)
          }
          fire.style.transform = `translate3d(${rim.x - width / 2}px, ${rim.y - height * 0.62}px, 0)`
          const lit = running && arrivedRef.current
          if (lit && !litAt.current) litAt.current = now
          if (!lit) litAt.current = 0
          const ramp = !lit || reducedRef.current ? (lit ? 1 : 0) : Math.min(1, (now - litAt.current) / 600)
          const glow = state === 'failed' ? 0 : lit ? Math.max(0.18, ramp) : smoking ? 0.28 : 0
          flame.current.set({
            intensity: glow,
            loop: Boolean(!away && !reducedRef.current && glow > 0),
            reduced: Boolean(reducedRef.current),
            hidden: away || glow <= 0,
          })
        }
      } else {
        const pose = shredderPaper(local, spec, !arrivedRef.current ? 1 : 1 - visual)
        if (paperChanged) context.clearRect(0, 0, host.clientWidth, host.clientHeight)
        const hostBox = host.getBoundingClientRect()
        edgeViewport = hostBox.top + pose.feed.y * (hostBox.height / Math.max(1, host.clientHeight))
        if (paperChanged && arrivedRef.current && pose.height > 1) {
          context.save()
          context.beginPath()
          context.rect(pose.x - 4, pose.y - 8, pose.width + 8, Math.max(0, pose.feed.y - pose.y))
          context.clip()
          context.drawImage(paper, pose.x, pose.y, pose.width, pose.height)
          context.restore()
        }
        const entered = pose.entered
        if (entered > fed.current + 8 && fallen.current.length < 8) {
          fed.current = entered
          fallen.current.push({ id: fallen.current.length, x: (fallen.current.length % 8) / 8, length: 0.55 + hash(fallen.current.length + 3) * 0.4, bend: hash(fallen.current.length) * 10 - 5, born: visual })
        }
        if (paperChanged && !links.length) {
          fallen.current.forEach(strip => {
            const sw = pose.width / 8
            const drop = Math.min(1, Math.max(0, (visual - strip.born) * 1.4))
            const length = (pose.tray.y - pose.output.y) * strip.length * Math.max(drop, state === 'succeeded' ? 1 : drop)
            const y = state === 'succeeded' ? pose.tray.y - length : pose.output.y + (pose.tray.y - pose.output.y - length) * drop
            context.save()
            context.translate(pose.x + strip.x * pose.width + sw / 2, y)
            context.rotate((strip.bend * Math.PI) / 180)
            context.drawImage(paper, strip.x * paper.width, 0, paper.width / 8, paper.height, -sw / 2, 0, sw - 2, length)
            context.restore()
          })
        }
        const nextKey = `${Math.round(pose.x)}:${Math.round(pose.tray.y)}:${Math.round(pose.width)}`
        if (nextKey !== trayKey.current) {
          trayKey.current = nextKey
          setTray({ left: pose.x, top: pose.tray.y, width: pose.width })
        }
        if (paperChanged) { painted.current = visual; host.dataset.layout = layoutKey }
      }
      draws.current += 1
      host.dataset.shown = visual.toFixed(4)
      host.dataset.edge = String(Math.round(edgeViewport))
      host.dataset.draws = String(draws.current)
      host.dataset.live = decorative && arrivedRef.current ? '1' : '0'
      const flameLive = lane === 'publish' && running && arrivedRef.current && !away && !reducedRef.current
      return Boolean(decorative || flameLive || smoking || (ash > 0 && ash < 1))
    }
    paint.current = draw
    const job = 'paper:' + (frameKey || lane + ':' + title) + ':burn'
    const stop = bindFrame(job, now => paint.current(now))
    const visibility = () => {
      visible = !document.hidden
      painted.current = -1
      draw(performance.now())
      if (visible && activeRef.current) bindFrame(job, now => paint.current(now))
    }
    const onResize = () => { resize(); host.dataset.layout = ''; paint.current(performance.now()) }
    document.addEventListener('visibilitychange', visibility)
    window.addEventListener('resize', onResize)
    const kick = () => { draw(performance.now()) }
    kick()
    return () => {
      stop()
      document.removeEventListener('visibilitychange', visibility)
      window.removeEventListener('resize', onResize)
    }
  }, [lane, title, mark, reduced, links.length, frameKey])
  useEffect(() => {
    painted.current = -1
    paint.current(performance.now())
    const job = 'paper:' + (frameKey || lane + ':' + title) + ':burn'
    return bindFrame(job, now => paint.current(now))
  }, [active, progress, status, arrived, parked, replaySmoke, lane, title, frameKey])

  const showStrips = lane === 'notes' && arrived && (status === 'succeeded' || progress >= 92) && links.length > 0
  return <div ref={root} className={'paper-process ' + lane} data-mark={mark} data-arrived={arrived ? '1' : '0'}>
    <Prop name={lane === 'publish' ? 'brazier' : 'shredder'} className="process-machine" />
    {lane === 'publish' && box && [0, 1, 2, 3].map(index => {
      const land = woodLanding(box, manifest, index)
      return <span key={index} className="task-log" style={{ left: land.x, top: land.y, transform: `translate(-50%,-50%) rotate(${land.rot}deg)` }}>
        <img className="wood-shadow" alt="" src={asset(`wood-${index}-shadow`)} />
        <img alt="" src={asset(`wood-${index}-light-beauty`)} />
      </span>
    })}
    <canvas ref={canvas} className="process-paper" aria-hidden="true" />
    {lane === 'publish' && <canvas ref={fireNode} className="flame-layer" aria-hidden="true" />}
    {showStrips && <div className="strip-tray" style={tray ? { left: tray.left + tray.width * 0.62, top: tray.top + 64, width: Math.max(108, tray.width * 0.55) } : undefined}>{links.slice(0, 8).map(link => <button type="button" key={link.id} className="shred-strip" data-card-id={link.id} data-refs={link.refs.join(' ')} style={{ backgroundImage: textures[link.id] ? `url(${textures[link.id]})` : undefined }} onClick={() => onStrip?.(link)} aria-label={'碎纸 ' + link.id} />)}</div>}
    <Prop name={lane === 'publish' ? 'brazier' : 'shredder'} layer="front" className="process-machine foreground" />
  </div>
}

export function CoverArt({ cover, video }: { cover?: string; video?: string }) {
  const [frame, setFrame] = useState(cover || '')
  useEffect(() => {
    if (cover) { setFrame(cover); return }
    if (!video) { setFrame(''); return }
    const el = document.createElement('video')
    el.preload = 'auto'
    el.muted = true
    el.src = video
    const grab = () => { try { el.currentTime = Math.min(0.2, (el.duration || 1) * 0.05) } catch { /* seek after metadata */ } }
    el.onloadeddata = grab
    el.onseeked = () => {
      const canvas = document.createElement('canvas')
      canvas.width = 320
      canvas.height = 180
      canvas.getContext('2d')?.drawImage(el, 0, 0, 320, 180)
      try { setFrame(canvas.toDataURL('image/jpeg', 0.82)) } catch { setFrame('') }
    }
    return () => { el.src = '' }
  }, [cover, video])
  return frame ? <img src={frame} alt="" /> : null
}

export function DeskTV({ url }: { url?: string }) {
  return <div className="desk-tv" aria-label={url ? '成片' : '成片预留'}>
    <div className="tv-bezel">
      <div className="tv-screen">
        {url ? <video src={url} controls playsInline preload="metadata" /> : <span>成片将在这里放映</span>}
      </div>
      <i className="tv-foot" />
    </div>
  </div>
}

export function DeskProjector({ url }: { url?: string }) {
  const [open, setOpen] = useState(false)
  const video = useRef<HTMLVideoElement>(null)
  const place = useRef(0)
  const reduced = useReducedMotion()
  function toggle() {
    if (!url) return
    if (open) {
      place.current = video.current?.currentTime || 0
      video.current?.pause()
    } else requestAnimationFrame(() => {
      if (!video.current) return
      video.current.currentTime = place.current
      void video.current.play().catch(() => {})
    })
    setOpen(value => !value)
  }
  return <div className={'desk-projector' + (open ? ' is-open' : '') + (reduced ? ' is-reduced' : '')}>
    <button type="button" className="projector-hit" aria-expanded={open} aria-label={open ? '收起投影幕' : '展开投影幕放映成片'} onClick={toggle} disabled={!url}>
      <img src={asset('projector-light-body')} alt="" />
    </button>
    <div className="projector-screen">
      <img className="screen-plate" src={asset('projector-light-screen-open')} alt="" />
      {url && <video ref={video} src={url} controls playsInline preload="metadata" />}
    </div>
  </div>
}
