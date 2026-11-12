import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useReducedMotion } from 'motion/react'
import { advanceProgress, bowlMouth, currentManifest, woodLanding } from './workbenchAnchors'
import type { Box } from './workbenchAnchors'
import type { Lane } from './workbenchState'
import { bindFrame } from './workbenchScheduler'
import { mountPetalFlame, warmEdge, type PetalFlame } from './workbenchFire'

import { paperSurface, paperSeed, paintBurn, type PaperMark } from './paperModel'
import { sceneMachine, scenePaper, type PaperProcessHandle } from './paperScene'

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

type Fragment = { row: number; column: number; born: number; ash: boolean }
export function PaperProcess({ lane, stage, progress, progressKnown = true, status, title, mark = 'clean', active = true,
  parked = false, arrived = true, links = [], replaySmoke = false, onStrip, frameKey = '', paperId = frameKey,
  processRef, logs = [0, 1, 2, 3], showPaper = true }: {
  lane: Lane; stage?: string; progress: number; progressKnown?: boolean; status: string; title: string; mark?: PaperMark
  active?: boolean; parked?: boolean; arrived?: boolean; links?: StripLink[]; replaySmoke?: boolean
  onStrip?: (link: StripLink) => void; frameKey?: string; paperId?: string
  processRef?: React.RefObject<PaperProcessHandle | null>; logs?: number[]; showPaper?: boolean
}) {
  const canvas = useRef<HTMLCanvasElement>(null), fireNode = useRef<HTMLCanvasElement>(null), root = useRef<HTMLDivElement>(null)
  const flame = useRef<PetalFlame | null>(null), paint = useRef<(now: number, force?: boolean) => boolean>(() => false)
  const reduced = Boolean(useReducedMotion())
  const live = useRef({progress, progressKnown, status, active, parked, arrived, replaySmoke, reduced, showPaper})
  live.current = {progress, progressKnown, status, active, parked, arrived, replaySmoke, reduced, showPaper}
  const surface = paperSurface(paperId, title, mark), paper = useRef(surface)
  paper.current = surface
  const [box, setBox] = useState<Box | null>(null)
  const geometry = useRef<Box | null>(null)
  const shown = useRef(0), target = useRef(0), emitted = useRef(0), fragments = useRef<Fragment[]>([])
  const seed = paperSeed(paperId)
  const job = 'paper:' + lane + ':' + frameKey

  useLayoutEffect(() => {
    shown.current = arrived && progressKnown ? Math.min(status === 'succeeded' ? 1 : .99, progress / 100) : 0
    target.current = shown.current; emitted.current = Math.floor(shown.current * 48); fragments.current = []
  }, [frameKey])
  useEffect(() => {
    if (!fireNode.current || lane !== 'publish') return
    const mounted = mountPetalFlame(fireNode.current); flame.current = mounted
    return () => { mounted.dispose(); flame.current = null }
  }, [lane])
  useLayoutEffect(() => {
    const node = canvas.current, host = root.current
    if (!node || !host) return
    const context = node.getContext('2d')!
    let last = performance.now(), smokeStart = 0, completeSeen = live.current.status === 'succeeded', replaySeen = false
    let lastDraw = '', wasAway = !live.current.active || document.hidden
    const resize = () => {
      const dpr = Math.min(devicePixelRatio || 1, 2)
      node.width = Math.round(Math.max(1, host.clientWidth) * dpr)
      node.height = Math.round(Math.max(1, host.clientHeight) * dpr)
      context.setTransform(dpr, 0, 0, dpr, 0, 0)
      const local = sceneMachine(lane, host.clientWidth, host.clientHeight)
      geometry.current = local; setBox(local); lastDraw = ''
    }
    let transient = false
    const draw = (now: number, force = false, landing = false) => {
      const local = geometry.current
      if (!local) return false
      const state = live.current, dt = Math.min(50, Math.max(0, now - last)); last = now
      const away = !state.active || document.hidden
      if (away) { wasAway = true; return false }
      if (state.progressKnown) target.current = advanceProgress(target.current, Math.min(state.status === 'succeeded' ? 1 : .99, state.progress / 100), state.status)
      if (state.status === 'succeeded') target.current = 1
      if (!state.arrived) { shown.current = 0; emitted.current = 0 }
      else if (wasAway || state.reduced) {
        shown.current = target.current; emitted.current = Math.floor(shown.current * 48); fragments.current = []; wasAway = false
      } else if (!landing && !state.parked && ['running', 'succeeded'].includes(state.status)) {
        shown.current += (target.current - shown.current) * (1 - Math.exp(-dt / 95))
        if (Math.abs(target.current - shown.current) < .0001) shown.current = target.current
      }
      const visual = shown.current
      const row = Math.floor(visual * 48)
      if (state.arrived && !state.parked && !state.reduced && ['running', 'succeeded'].includes(state.status)) {
        for (let i = emitted.current; i < row; i++) for (let column = 0; column < (lane === 'notes' ? 8 : 3); column++) {
          fragments.current.push({row: i, column, born: now, ash: lane === 'publish'})
        }
      }
      emitted.current = Math.max(emitted.current, row)
      fragments.current = fragments.current.filter(f => now - f.born < 1150)
      if (state.status === 'succeeded' && !completeSeen && visual === 1) {
        completeSeen = true; smokeStart = now
      }
      if (state.replaySmoke && !replaySeen) { replaySeen = true; smokeStart = now }
      const smoking = lane === 'publish' && smokeStart > 0 && now - smokeStart < 1000
      const pose = scenePaper(lane, local, 1 - visual)
      const drawKey = [visual.toFixed(5), state.arrived, state.showPaper, node.width, node.height, mark].join(':')
      if (force || drawKey !== lastDraw || fragments.current.length || smoking || transient) {
        context.clearRect(0, 0, host.clientWidth, host.clientHeight)
        if (state.arrived && state.showPaper && visual < 1) {
          if (lane === 'publish' && 'edgeY' in pose) paintBurn(context, paper.current, pose, seed)
          else if ('feed' in pose) {
            context.save(); context.beginPath(); context.rect(0, 0, host.clientWidth, pose.feed.y)
            context.clip(); context.drawImage(paper.current, pose.x, pose.y, pose.width, pose.height); context.restore()
          }
        }
        for (const fragment of fragments.current) {
          const t = Math.min(1, (now - fragment.born) / 1050), sign = fragment.column % 2 ? 1 : -1
          context.save()
          if (fragment.ash && 'edgeY' in pose) {
            context.translate(pose.x + pose.width * ((fragment.row * 7 + fragment.column * 13) % 31) / 31 + Math.sin(t * 5) * 7, pose.edgeY - t * 40)
            context.globalAlpha = (1 - t) * .55; context.rotate(t * sign * 4)
            context.fillStyle = '#6a4a32'; context.fillRect(-1, -1, 2, 3)
          } else if ('output' in pose) {
            const x = pose.output.x - pose.width / 2 + (fragment.column + .5) * pose.width / 8
            const fall = Math.min(1, t * 1.4)
            context.translate(x + sign * Math.sin(t * 4) * 6, pose.output.y + (pose.tray.y - pose.output.y) * fall * fall)
            context.rotate(sign * t * (1.5 + fragment.row % 3))
            context.scale(Math.max(.12, Math.abs(Math.cos(t * Math.PI * 2))), 1)
            context.globalAlpha = t > .85 ? (1 - t) / .15 : 1
            const sy = 520 * (1 - (fragment.row + 1) / 48), sw = 380 / 8
            const dw = pose.width / 8 * .9, dh = Math.max(3, pose.height / 48)
            context.drawImage(paper.current, fragment.column * sw, sy, sw, 520 / 48, -dw / 2, -dh / 2, dw, dh)
          }
          context.restore()
        }
        // Settled scraps are sampled from the already-consumed paper, not a loop.
        if ('tray' in pose && visual > 0) {
          const count = Math.min(36, Math.floor(visual * 48))
          for (let i = 0; i < count; i++) {
            const x = pose.tray.x + ((i * 37 % 101) / 100 - .5) * pose.width * 1.35
            const y = pose.tray.y + (i * 13 % 17) - 6
            context.save(); context.translate(x, y); context.rotate((i * 17 % 45 - 22) * Math.PI / 180)
            const sourceY = Math.max(0, 520 * (1 - (i + 1) / 48))
            context.drawImage(paper.current, (i * 47) % 340, sourceY, 35, 10, -5, -2, 10, 4)
            context.restore()
          }
        }
        if (smoking && 'edgeY' in pose) drawSmoke(context, pose.edgeX, pose.edgeY, (now - smokeStart) / 1000)
        lastDraw = drawKey
        transient = fragments.current.length > 0 || smoking
      }
      if (lane === 'publish' && flame.current && fireNode.current) {
        const mouth = bowlMouth(local, currentManifest()), fire = fireNode.current
        const width = mouth.rx * 1.6, height = width * 1.05
        const size = width + 'x' + height
        if (fire.dataset.size !== size) {
          fire.dataset.size = size; fire.style.width = width + 'px'; fire.style.height = height + 'px'; flame.current.resize(width, height)
        }
        fire.style.transform = `translate3d(${mouth.cx - width / 2}px,${mouth.cy - height * .8}px,0)`
        const lit = state.status === 'running' && state.arrived
        flame.current.set({intensity: lit ? .85 : smoking ? .25 : 0, loop: !state.reduced && (lit || smoking), reduced: state.reduced, hidden: !lit && !smoking})
      }
      host.dataset.shown = visual.toFixed(4); host.dataset.emitted = String(emitted.current)
      host.dataset.fragments = String(fragments.current.length)
      host.dataset.edge = String(('edgeY' in pose ? pose.edgeY : pose.feed.y) + host.getBoundingClientRect().top)
      const changing = state.arrived && !state.parked && ['running', 'succeeded'].includes(state.status) && Math.abs(target.current - visual) > .0001
      return changing || fragments.current.length > 0 || smoking
    }
    resize(); paint.current = draw
    const handle: PaperProcessHandle = {
      key: frameKey, surface: () => paper.current,
      pose: () => {
        if (!host.isConnected || host.closest('[inert]') || !geometry.current) return null
        const pose = scenePaper(lane, geometry.current), rect = host.getBoundingClientRect()
        const sx = rect.width / host.clientWidth, sy = rect.height / host.clientHeight
        return {x: rect.left + pose.x * sx, y: rect.top + pose.y * sy, width: pose.width * sx, height: pose.height * sy}
      },
      land: () => { live.current.arrived = true; shown.current = 0; emitted.current = 0; draw(performance.now(), true, true) },
    }
    if (processRef) processRef.current = handle
    draw(performance.now(), true)
    let stop = bindFrame(job, draw)
    const observer = new ResizeObserver(() => {resize(); draw(performance.now(), true)})
    observer.observe(host)
    const visibility = () => {
      if (document.hidden) { wasAway = true; flame.current?.set({hidden:true, loop:false, reduced:live.current.reduced, intensity:0}); return }
      stop(); stop = bindFrame(job, draw)
    }
    document.addEventListener('visibilitychange', visibility)
    return () => { stop(); observer.disconnect(); document.removeEventListener('visibilitychange', visibility)
      if (processRef?.current === handle) processRef.current = null }
  }, [lane, frameKey, job, processRef])
  useEffect(() => {
    if (!active) flame.current?.set({hidden:true, loop:false, reduced:live.current.reduced, intensity:0})
    paint.current(performance.now(), true)
    return bindFrame(job, now => paint.current(now))
  }, [progress, progressKnown, status, arrived, parked, active, reduced, showPaper, surface, replaySmoke, job])

  const showStrips = lane === 'notes' && arrived && (status === 'succeeded' || stage === 'extract')
  const pose = box ? scenePaper(lane, box) : null
  const mouth = lane === 'publish' && box ? bowlMouth(box, currentManifest()) : null
  return <div ref={root} className={'paper-process ' + lane} data-paper-key={frameKey} data-mark={mark} data-arrived={arrived ? '1' : '0'} data-burning={lane === 'publish' && status === 'running' && arrived ? '1' : '0'}>
    {mouth && box && <i className="process-warmth" style={{left:mouth.cx-mouth.rx*1.2,top:mouth.cy,width:mouth.rx*2.4,height:box.height*.18}}/>}
    <Prop name={lane === 'publish' ? 'brazier' : 'shredder'} className="process-machine" style={box || undefined}/>
    {mouth && box && <BrazierLogs box={box} ids={logs}/>}
    <canvas ref={canvas} className="process-paper" aria-hidden="true"/>
    {lane === 'publish' && <canvas ref={fireNode} className="flame-layer" aria-hidden="true"/>}
    {showStrips && pose && 'tray' in pose && <div className="strip-tray" style={{left:pose.tray.x-pose.width*.65,top:pose.tray.y-8,width:pose.width*1.3}}>
      {links.slice(0,8).map(link => {
        const index = paperSeed(String(link.id))
        const crop = document.createElement('canvas'); crop.width = 30; crop.height = 34
        crop.getContext('2d')?.drawImage(surface, index % 350, (index >>> 8) % 486, 30, 34, 0, 0, 30, 34)
        return <button type="button" key={link.id} className="shred-strip" data-card-id={link.id} data-refs={link.refs.join(' ')}
          style={{transform:`rotate(${index % 39-19}deg)`,width:16,height:18,backgroundImage:`url(${crop.toDataURL()})`}}
          onClick={() => onStrip?.(link)} aria-label={'碎纸 ' + link.id}/>
      })}
    </div>}
    <Prop name={lane === 'publish' ? 'brazier' : 'shredder'} layer="front" className="process-machine foreground" style={box || undefined}/>
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

export function DeskTV({ url, children, caption, active = true, label = '成片放映' }: {
  url?: string; children?: React.ReactNode; caption?: string; active?: boolean; label?: string
}) {
  const [state,setState]=useState<'loading'|'ready'|'error'>('loading')
  const [attempt,setAttempt]=useState(0)
  const video=useRef<HTMLVideoElement>(null)
  useEffect(()=>{setState('loading');setAttempt(0)},[url])
  useEffect(()=>{if(!active)video.current?.pause()},[active])
  return <figure className="desk-tv" aria-label={label}>
    <div className="tv-bezel">
      <div className="tv-screen">
        {url ? <>
          <video ref={video} key={url+attempt} src={url} controls playsInline preload="metadata" onLoadedData={()=>setState('ready')} onError={()=>setState('error')}/>
          {state==='loading'&&<span className="tv-status" role="status">正在载入成片</span>}
          {state==='error'&&<div className="tv-status" role="alert">成片播放失败<button type="button" onClick={()=>{setState('loading');setAttempt(value=>value+1)}}>重新载入</button></div>}
        </> : children || <span>成片将在这里放映</span>}
      </div>
      <div className="tv-controls" aria-hidden="true"><i className={'tv-lamp'+(url&&state==='ready'?' is-on':'')}/><span>MEDIA OPERATOR</span><i className="tv-speaker"/><i className="tv-dial"/></div>
    </div>
    <i className="tv-foot" aria-hidden="true"/>
    <figcaption><strong>{label}</strong>{caption&&<span>{caption}</span>}</figcaption>
  </figure>
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
