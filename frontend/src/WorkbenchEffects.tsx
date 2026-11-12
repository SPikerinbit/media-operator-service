import { useEffect, useRef, useState } from 'react'
import { useReducedMotion } from 'motion/react'
import { advanceProgress, anchorPixels, bowlMouth, burnPaper, currentManifest, shredderPaper, useWorkbenchManifest, woodLanding } from './workbenchAnchors'
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
export function BrazierLogs({box, ids=[0,1,2,3]}:{box:Box;ids?:number[]}) {
  const spec=currentManifest(), mouth=bowlMouth(box,spec)
  return <div className="bowl-well" data-bowl-well style={{left:mouth.cx-mouth.rx,top:mouth.cy-mouth.ry,width:mouth.rx*2,height:mouth.ry*2}}>
    {ids.map(index=>{
      const spot=woodLanding(box,spec,index)
      return <span key={index} className="task-log" style={{left:spot.x-(mouth.cx-mouth.rx),top:spot.y-(mouth.cy-mouth.ry),width:box.width*.22,height:box.height*.145,transform:`translate(-50%,-50%) rotate(${spot.rot}deg)`}}><img alt="" src={asset(`wood-${index}-light-beauty`)}/></span>
    })}
  </div>
}
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

export function PaperProcess({ lane, stage, progress, progressKnown = true, status, title, mark = 'clean', active = true, parked = false, arrived = true, links = [], replaySmoke = false, onStrip, frameKey = '' }: {
  lane: Lane; stage?: string; progress: number; progressKnown?: boolean; status: string; title: string; mark?: Mark; active?: boolean; parked?: boolean
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
  const stageRef = useRef(stage)
  stageRef.current = stage
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
      const visual = !arrivedRef.current ? 0 : lane==='notes' ? (state==='succeeded'?1:stageRef.current==='extract'?.88:stageRef.current==='translate'?.7:stageRef.current==='transcribe'?Math.max(.18,shown):0) : statusRef.current === 'running' ? Math.min(1, shown * intro + (1 - shown) * ash) : shown
      const sheet = canvas.current
      if (lane === 'publish' && sheet) sheet.style.opacity = ''
      const layoutKey = host.clientWidth + 'x' + host.clientHeight
      const paperChanged = Math.abs(visual - painted.current) > 0.001 || host.dataset.layout !== layoutKey
      const local = layoutOf(machine, host)
      let edgeViewport = 0
      if (lane === 'publish') {
        const pose = burnPaper(local, spec, arrivedRef.current ? 1 - visual : 1)
        const mouth = bowlMouth(local, spec)
        const hostBox = host.getBoundingClientRect()
        const rim = anchorPixels(local, spec.brazier.anchors.rim, spec.brazier.size)
        edgeViewport = hostBox.top + rim.y * (hostBox.height / Math.max(1, host.clientHeight))
        if (paperChanged || smoking) {
          context.clearRect(0, 0, host.clientWidth, host.clientHeight)
          context.save()
          context.beginPath()
          context.ellipse(mouth.cx, mouth.cy, mouth.rx, mouth.ry, 0, 0, Math.PI * 2)
          context.clip()
          if ((arrivedRef.current || statusRef.current === 'running') && pose.height > 1) {
            context.save()
            context.translate(mouth.cx, mouth.cy + mouth.ry * 0.28)
            context.rotate(-0.08)
            const width = mouth.rx * 0.92
            const height = mouth.ry * 1.7
            context.beginPath()
            context.moveTo(-width * 0.48, height * 0.05)
            context.quadraticCurveTo(-width * 0.1, -height * 0.72, width * 0.46, -height * 0.02)
            context.quadraticCurveTo(width * 0.18, height * 0.42, -width * 0.42, height * 0.28)
            context.closePath()
            context.clip()
            const curled = { x: -width / 2, y: -height * 0.55, width, height, edgeY: -height * 0.55 + height * Math.max(0.5, pose.remaining) }
            paintBurn(context, paper, curled)
            const char = context.createLinearGradient(0, -height * 0.2, 0, height * 0.35)
            char.addColorStop(0, 'rgba(90, 50, 24, 0)')
            char.addColorStop(0.55, 'rgba(90, 42, 18, 0.35)')
            char.addColorStop(1, 'rgba(40, 18, 8, 0.85)')
            context.fillStyle = char
            context.fillRect(-width / 2, -height / 2, width, height)
            context.restore()
          }
          if (smoking) drawSmoke(context, mouth.cx, mouth.cy, 1 - (smokeUntil.current - now) / 1000)
          context.restore()
          painted.current = visual
          host.dataset.layout = layoutKey
        }
        const fire = fireNode.current
        if (fire && flame.current) {
          const width = Math.min(150, Math.max(110, mouth.rx * 1.3))
          const height = Math.min(160, Math.max(120, width * 1.05))
          if (fire.dataset.size !== width + 'x' + height) {
            fire.dataset.size = width + 'x' + height
            fire.style.left = '0'
            fire.style.top = '0'
            fire.style.width = width + 'px'
            fire.style.height = height + 'px'
            flame.current.resize(width, height)
          }
          fire.style.zIndex = '4'
          fire.style.transform = `translate3d(${mouth.cx - width / 2}px, ${mouth.cy - height * 0.8}px, 0)`
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
        const nextKey = `${Math.round(pose.x)}:${Math.round(pose.tray.y)}:${Math.round(pose.width)}`
        if (nextKey !== trayKey.current) {
          trayKey.current = nextKey
          setTray({ left: pose.tray.x, top: pose.tray.y, width: pose.width })
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

  const showStrips = lane === 'notes' && arrived && (status === 'succeeded' || stage === 'extract')
  const falling = lane==='notes' && active && arrived && status==='running' && ['transcribe','translate','extract'].includes(stage||'')
  const mouth = lane === 'publish' && box ? bowlMouth(box, manifest) : null
  const scraps = showStrips ? [
    ...links.slice(0, 8).map((link, index) => ({ key: 'card-' + link.id, link, index })),
    ...[0, 1, 2, 3, 4].map(index => ({ key: 'scrap-' + index, link: null, index: index + 8 })),
  ] : []
  return <div ref={root} className={'paper-process ' + lane} data-mark={mark} data-arrived={arrived ? '1' : '0'} data-burning={lane==='publish'&&status==='running'&&arrived?'1':'0'}>
    {mouth&&box&&<i className="process-warmth" style={{left:mouth.cx-mouth.rx*1.2,top:box.top+box.height*.78,width:mouth.rx*2.4,height:box.height*.06}}/>}
    <Prop name={lane === 'publish' ? 'brazier' : 'shredder'} className="process-machine" />
    {mouth && box && <BrazierLogs box={box}/>}
    <canvas ref={canvas} className="process-paper" aria-hidden="true" />
    {lane === 'publish' && <canvas ref={fireNode} className="flame-layer" aria-hidden="true" />}
    {falling&&<div className="shred-fall" aria-hidden="true">{Array.from({length:14},(_,i)=><i key={i} style={{'--x':`${8+(i*17)%84}%`,'--spin':`${(i%2?1:-1)*(70+i*13)}deg`,animationDelay:`${-i*.19}s`,animationDuration:`${1.2+i%4*.15}s`} as React.CSSProperties}/>)}</div>}
    {showStrips && <div className="strip-tray">{scraps.map(scrap => {
      const size=[14,12,16,13,15][scrap.index%5]
      const style = { transform: `rotate(${[-18, 11, -7, 16, -13][scrap.index%5]}deg)`, width:size, height:size, backgroundImage:scrap.link?`url(${textures[scrap.link.id]||''})`:undefined, animationDelay:`${scrap.index*65}ms` }
      return scrap.link
        ? <button type="button" key={scrap.key} className="shred-strip" data-card-id={scrap.link.id} data-refs={scrap.link.refs.join(' ')} style={style} onClick={() => onStrip?.(scrap.link!)} aria-label={'碎纸 ' + scrap.link.id} />
        : <i key={scrap.key} className="shred-strip" style={style} />
    })}</div>}
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
  const [state,setState]=useState<'loading'|'ready'|'error'>('loading')
  const [attempt,setAttempt]=useState(0)
  useEffect(()=>{setState('loading');setAttempt(0)},[url])
  return <div className="desk-tv" aria-label={url ? '成片' : '成片预留'}>
    <div className="tv-bezel">
      <div className="tv-screen">
        {url ? <>
          <video key={url+attempt} src={url} controls playsInline preload="metadata" onLoadedData={()=>setState('ready')} onError={()=>setState('error')}/>
          {state==='loading'&&<span className="tv-status" role="status">正在载入成片</span>}
          {state==='error'&&<div className="tv-status" role="alert">成片播放失败<button type="button" onClick={()=>{setState('loading');setAttempt(value=>value+1)}}>重新载入</button></div>}
        </> : <span>成片将在这里放映</span>}
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
