import { anchorPixels, atlasPosition, currentManifest, normBox, type WorkbenchManifest } from './workbenchAnchors'
import { bindFrame } from './workbenchScheduler'
import { lerp, ramp, springAt, springSettled, SPRING } from './motionSystem'

const srcOf = (base: string, name: string) => `${base}workbench/${name}.webp`
const reducedMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches

export const DELIVERY_PHASES = [
  { id: 'fold', ms: 980 },
  { id: 'tuck', ms: 420 },
  { id: 'seal', ms: 560 },
  { id: 'insert', ms: 980 },
  { id: 'route', ms: 480 },
] as const

export type DeliveryPhase = (typeof DELIVERY_PHASES)[number]['id']

export const DELIVERY_MS = DELIVERY_PHASES.reduce((sum, phase) => sum + phase.ms, 0)

type DeliveryNodes = {
  root: HTMLElement
  env: HTMLElement
  mail: HTMLElement
  paper: HTMLElement
  flap: HTMLElement
  closed: HTMLElement
  wax: HTMLElement
  copy: HTMLElement
  sheet?: HTMLElement | null
  lines?: string[]
  isActive?: () => boolean
}

type Point = { x: number; y: number }

function phaseOf(elapsed: number): DeliveryPhase {
  let end = 0
  for (const phase of DELIVERY_PHASES) {
    end += phase.ms
    if (elapsed < end) return phase.id
  }
  return 'route'
}

/** Swing to the edge, hold the foreshortened pose, then lay the panel down. */
function foldAngle(elapsed: number, delay: number) {
  const e = elapsed - delay
  if (e <= 0) return 0
  if (e < 140) return (e / 140) * 72
  if (e < 280) return 72 + ((e - 140) / 140) * 34
  if (e < 460) return 106 + ((e - 280) / 180) * 66
  const s = Math.min(1, (e - 460) / 160)
  return 172 + 8 * ramp(s, 0, 1)
}

function cubic(a: number, b: number, c: number, d: number, t: number) {
  const u = 1 - t
  return u * u * u * a + 3 * u * u * t * b + 3 * u * t * t * c + t * t * t * d
}

function cubicTan(a: number, b: number, c: number, d: number, t: number) {
  const u = 1 - t
  return 3 * u * u * (b - a) + 6 * u * t * (c - b) + 3 * t * t * (d - c)
}

function quad(a: number, b: number, c: number, t: number) {
  const u = 1 - t
  return u * u * a + 2 * u * t * b + t * t * c
}

function quadTan(a: number, b: number, c: number, t: number) {
  return 2 * (1 - t) * (b - a) + 2 * t * (c - b)
}

function liveProcess() {
  const hosts = document.querySelectorAll<HTMLElement>('.paper-process')
  for (const host of hosts) {
    const view = host.closest('.lane-view, .home-view')
    if (!view || view.classList.contains('is-parked')) continue
    const box = host.getBoundingClientRect()
    if (box.width > 2 && box.height > 2) return host
  }
  return null
}

function ruledSheet(lines: string[], width: number, height: number) {
  const face = document.createElement('div')
  face.className = 'page-flyer-face'
  face.style.width = width + 'px'
  face.style.height = height + 'px'
  lines.forEach(text => {
    const row = document.createElement('div')
    row.className = 'flyer-line'
    row.textContent = text
    face.append(row)
  })
  return face
}

function pin(el: HTMLElement, x: number, y: number, w: number, h: number) {
  el.style.position = 'fixed'
  el.style.left = '0px'
  el.style.top = '0px'
  el.style.width = w + 'px'
  el.style.height = h + 'px'
  el.style.margin = '0'
  el.style.zIndex = '40'
  el.style.willChange = 'transform, opacity'
  el.style.transformOrigin = '0 0'
  el.style.transform = `translate3d(${x}px, ${y}px, 0)`
}

function castShadow() {
  const shade = document.createElement('div')
  shade.className = 'cast-shadow'
  shade.setAttribute('aria-hidden', 'true')
  return shade
}

/** Three stacked panels. Bottom folds up first, then the doubled sheet folds over the top. */
function buildFold(lines: string[], width: number, height: number) {
  const sheet = document.createElement('div')
  sheet.className = 'fold-sheet'
  const cam = document.createElement('div')
  cam.className = 'fold-cam'
  const stage = document.createElement('div')
  stage.className = 'fold-stage'
  const panelOf = (index: number) => {
    const panel = document.createElement('div')
    panel.className = 'fold-panel'
    const face = document.createElement('div')
    face.className = 'fold-face'
    const surface = ruledSheet(lines, width, height)
    surface.style.position = 'absolute'
    surface.style.top = `${-index * height / 3}px`
    face.append(surface)
    const edge = document.createElement('i')
    edge.className = 'fold-thickness'
    face.append(edge)
    const back = document.createElement('div')
    back.className = 'fold-backface'
    panel.append(face, back)
    return panel
  }
  const third = height / 3
  const top = panelOf(0)
  top.classList.add('is-top')
  top.style.height = third + 'px'
  const hingeMid = document.createElement('div')
  hingeMid.className = 'fold-hinge mid'
  hingeMid.style.top = third + 'px'
  hingeMid.style.height = third + 'px'
  const creaseMid = document.createElement('i')
  creaseMid.className = 'fold-crease-line'
  const mid = panelOf(1)
  const hingeBot = document.createElement('div')
  hingeBot.className = 'fold-hinge bot'
  hingeBot.style.height = third + 'px'
  const creaseBot = document.createElement('i')
  creaseBot.className = 'fold-crease-line'
  const bot = panelOf(2)
  hingeBot.append(creaseBot, bot)
  hingeMid.append(creaseMid, mid, hingeBot)
  stage.style.height = height + 'px'
  stage.append(top, hingeMid)
  cam.append(stage)
  sheet.append(cam)
  return { sheet, stage, hingeMid, hingeBot, creaseMid, creaseBot }
}

/** Fold, tuck, seal, insert, and route as one continuous gesture. */
export function playDelivery(nodes: DeliveryNodes, manifest: WorkbenchManifest, base: string, onPhase: (phase: DeliveryPhase) => void, onDone?: () => void) {
  if (reducedMotion()) { onDone?.(); return () => {} }
  let stopped = false
  let previous = performance.now()
  let elapsed = 0
  let announced = ''
  const homeRect = nodes.sheet?.getBoundingClientRect()
  const lines = nodes.lines?.length ? nodes.lines : [...(nodes.sheet?.querySelectorAll('input') || [])].map(node => (node as HTMLInputElement).value).filter(Boolean)
  const shell = nodes.root.closest('.workbench-shell')
  const lane = nodes.root.classList.contains('notes') ? 'notes' : 'publish'
  const sheetW = homeRect?.width || 400
  const sheetH = homeRect?.height || 220
  const built = buildFold(lines.slice(0, 8), sheetW, sheetH)
  const flight = built.sheet
  flight.dataset.lane = lane
  flight.setAttribute('aria-hidden', 'true')
  document.body.append(flight)
  let originX = homeRect?.left || 0
  let originY = homeRect?.top || 0
  pin(flight, originX, originY, sheetW, sheetH)
  flight.style.transformOrigin = '0 0'
  flight.style.willChange = 'auto'
  flight.style.perspective = ''
  const source = (nodes.sheet?.closest('.sheet-stack') as HTMLElement | null) || nodes.sheet || null
  const hint = nodes.sheet?.closest('.writing-paper')?.querySelector<HTMLElement>('.paper-hint') || null
  if (source) {
    source.style.transition = 'opacity 160ms linear'
    source.style.opacity = '0'
  }
  if (hint) hint.style.opacity = '0'
  const shade = castShadow()
  shade.dataset.lane = lane
  document.body.append(shade)
  let route: HTMLElement | null = null
  const restW = nodes.env.offsetWidth
  const restH = nodes.env.offsetHeight
  const home = nodes.env.dataset.home
    ? JSON.parse(nodes.env.dataset.home) as Point
    : { x: originX + sheetW / 2, y: originY }
  const placeholder = document.createElement('div')
  placeholder.className = 'delivery-envelope delivery-placeholder'
  placeholder.style.visibility = 'hidden'
  placeholder.style.display = 'none'
  nodes.env.before(placeholder)
  const raise = Math.max(0, originY + sheetH - (window.innerHeight - 28))
  const finish = () => {
    if (source) source.style.opacity = ''
    if (hint) hint.style.opacity = ''
    flight.remove()
    shade.remove()
    route?.remove()
    placeholder.remove()
    nodes.env.style.visibility = ''
    nodes.env.style.marginTop = ''
  }
  const tick = (now: number) => {
    if (stopped) return false
    const dt = now - previous
    previous = now
    const paused = document.hidden || nodes.isActive?.() === false
    flight.style.visibility = paused ? 'hidden' : 'visible'
    shade.style.visibility = paused ? 'hidden' : 'visible'
    if (route) route.style.visibility = paused ? 'hidden' : 'visible'
    nodes.env.style.visibility = paused ? 'hidden' : ''
    if (paused) return true
    elapsed += Math.min(50, dt)
    const u = Math.min(1, elapsed / DELIVERY_MS)
    const phase = phaseOf(elapsed)
    if (phase !== announced) { announced = phase; onPhase(phase) }
    const tuckT = ramp(elapsed, 980, 1400)
    const sealT = ramp(elapsed, 1400, 1960)
    const insertT = ramp(elapsed, 1960, 2940)
    const sheetBox = nodes.sheet?.getBoundingClientRect()
    if (sheetBox) { originX = lerp(originX, sheetBox.left, .24); originY = lerp(originY, sheetBox.top, .24) }
    const room = 64 * ramp(elapsed, 0, 320) * (1 - sealT)
    if (!insertT) nodes.env.style.marginTop = `calc(var(--env-tuck) + ${room}px)`
    else { placeholder.style.display = ''; nodes.env.style.marginTop = '' }
    const anchor = (insertT ? placeholder : nodes.env).getBoundingClientRect()
    home.x = lerp(home.x, anchor.left + anchor.width / 2, .24)
    home.y = lerp(home.y, anchor.top + anchor.height / 2, .24)
    const openT = ramp(elapsed, 40, 240)
    const fold1 = foldAngle(elapsed, 0)
    const fold2 = foldAngle(elapsed, 360)
    const tiltIn = ramp(elapsed, 0, 180)
    built.stage.style.transform = `rotateX(${tiltIn * 26 * (1-tuckT)}deg) rotateY(${tiltIn * -18 * (1-tuckT)}deg)`
    built.hingeBot.style.transform = `rotateX(${fold1}deg)`
    built.hingeMid.style.transform = `rotateX(${fold2}deg)`
    const crease = (el: HTMLElement, angle: number) => {
      const edge = Math.sin(Math.min(180, Math.max(0, angle)) * Math.PI / 180)
      el.style.opacity = String(0.15 + edge * 0.85)
    }
    crease(built.creaseBot, fold1)
    crease(built.creaseMid, fold2)
    const present = ramp(elapsed / 240, 0, 1)
    const yLift = raise * present
    const envBox = nodes.env.getBoundingClientRect()
    const mail = nodes.mail.getBoundingClientRect()
    const pocket = manifest.envelope.anchors.pocket
    const pocketBox = pocket && envBox.width > 2 ? {
      x: envBox.left + pocket[0] * envBox.width,
      y: envBox.top + pocket[1] * envBox.height,
      w: pocket[2] * envBox.width,
      h: pocket[3] * envBox.height,
    } : null
    const sideGap = pocketBox ? (pocketBox.w - sheetW * Math.min(.9, pocketBox.w*.82/sheetW))/2 : 8
    const destX = pocketBox ? pocketBox.x + sideGap : envBox.left + envBox.width * 0.12
    const destY = pocketBox ? pocketBox.y + pocketBox.h * 0.15 : envBox.top + envBox.height * 0.5
    const x = lerp(originX, destX, tuckT)
    const y = lerp(originY - yLift, destY, tuckT)
    const tuckScale = lerp(1, pocketBox ? Math.min(0.9, (pocketBox.w * 0.82) / sheetW) : 0.68, tuckT)
    flight.style.transformOrigin = '0 0'
    if (tuckT > 0.08) {
      nodes.paper.style.visibility = 'visible'
      nodes.paper.style.overflow = 'visible'
      nodes.paper.style.inset = '0'
      if (flight.parentElement !== nodes.paper) nodes.paper.append(flight)
      flight.style.visibility = 'visible'
      flight.style.position = 'absolute'
      flight.style.zIndex = '1'
      flight.style.left = '0'
      flight.style.top = '0'
      flight.style.transform = `translate3d(${x - envBox.left}px, ${y - envBox.top}px, 0) scale(${tuckScale})`
    } else {
      if (flight.parentElement !== document.body) document.body.append(flight)
      flight.style.position = 'fixed'
      flight.style.zIndex = '40'
      flight.style.transform = `translate3d(${originX}px, ${originY - yLift}px, 0) scale(${tuckScale})`
    }
    flight.style.opacity = String(tuckT > 0.92 ? 1 - ramp(sealT, 0.02, 0.28) : 1)
    nodes.copy.style.opacity = '0'
    nodes.flap.style.opacity = '1'
    nodes.closed.style.opacity = '0'
    if (sealT < 0.02) {
      const open = ramp(elapsed, 40, 320)
      const waxOff = ramp(elapsed, 20, 160)
      nodes.flap.style.transform = `rotateX(${open * 180}deg)`
      nodes.wax.style.opacity = String(1 - waxOff)
      nodes.wax.style.transform = `translate(-50%, -50%) translateY(${-14 * waxOff}px) scale(${lerp(1, 0.7, waxOff)})`
    } else {
      const shut = Math.min(1, sealT / 0.62)
      nodes.flap.style.transform = `rotateX(${(1 - shut) * 180}deg)`
      const pressStart = 0.62
      if (sealT < pressStart) {
        nodes.wax.style.opacity = '0'
        nodes.wax.style.transform = 'translate(-50%, -50%) scale(1.42)'
      } else {
        const local = (sealT - pressStart) / (1 - pressStart)
        const stamp = Math.max(0, springAt(local * 340, SPRING.press))
        nodes.wax.style.opacity = String(Math.min(1, local / 0.16))
        const squashY = stamp < 0.48 ? lerp(1.46, 0.76, stamp / 0.48) : lerp(0.76, 1, Math.min(1, (stamp - 0.48) / 0.52))
        const squashX = stamp < 0.48 ? lerp(0.86, 1.16, stamp / 0.48) : lerp(1.16, 1, Math.min(1, (stamp - 0.48) / 0.52))
        nodes.wax.style.transform = `translate(-50%, -50%) scale(${squashX}, ${squashY})`
      }
    }
    if (insertT > 0 && mail.width > 2) {
      const slot = manifest.mailbox.anchors.slotFront
      if (slot) {
        const mouth = normBox(mail, slot, manifest.mailbox.size)
        const slotCenter = { x: mouth.left + mouth.width / 2, y: mouth.top + mouth.height * 0.35 }
        const metalBottom = mail.top + mail.height * 0.8
        const approachScale = 0.7
        const half = restH * approachScale * 0.5
        const approach = { x: slotCenter.x, y: metalBottom + half + 10 }
        const lift = { x: home.x - 28, y: (home.y + approach.y) / 2 - 18 }
        const peak = { x: (home.x + approach.x) / 2 - 16, y: Math.min(home.y, approach.y) - 28 }
        const wind = ramp(insertT, 0, 0.16)
        const travel = Math.min(1, Math.max(0, (insertT - 0.16) / 0.62))
        const into = ramp(insertT, 0.82, 1)
        const te = travel * travel * travel * (travel * (travel * 6 - 15) + 10)
        if (wind > 0.2) nodes.mail.classList.add('is-accepting')
        const sample = Math.min(0.98, Math.max(0.02, into > 0 ? 1 : te))
        let cx = cubic(home.x, lift.x, peak.x, approach.x, into > 0 ? 1 : te)
        let cy = cubic(home.y, lift.y, peak.y, approach.y, into > 0 ? 1 : te)
        const tx = cubicTan(home.x, lift.x, peak.x, approach.x, sample)
        const ty = cubicTan(home.y, lift.y, peak.y, approach.y, sample)
        let tilt = Math.atan2(ty, tx) * 180 / Math.PI
        tilt = Math.max(-18, Math.min(14, tilt * 0.35))
        const visible = manifest.envelope.visible_bounds
        const visibleW = visible ? (visible[2] - visible[0]) : 0.84
        const endScale = Math.min(0.28, (mouth.width * 0.92) / Math.max(1, visibleW * restW))
        let scale = lerp(1, approachScale, te)
        if (wind < 1 && travel <= 0) {
          cy = home.y + Math.sin(wind * Math.PI) * 12
          scale = lerp(1, 0.97, wind)
        }
        if (into > 0) {
          cx = lerp(approach.x, slotCenter.x, into)
          cy = lerp(approach.y, slotCenter.y, into)
          scale = lerp(approachScale, endScale, into)
          tilt = lerp(tilt, 0, into)
          if (!nodes.mail.dataset.fed) {
            nodes.mail.dataset.fed = '1'
            nodes.mail.classList.add('is-fed')
          }
          if (into > 0.72) nodes.mail.classList.add('is-shut')
        }
        const hatch = into > 0.02 ? nodes.mail.querySelector<HTMLElement>('.slot-window') : null
        if (hatch && nodes.env.parentElement !== hatch) {
          hatch.append(nodes.env)
          nodes.env.style.position = 'absolute'
          nodes.env.style.margin = '0'
          nodes.env.style.left = '0'
          nodes.env.style.top = '0'
          nodes.env.style.width = restW + 'px'
          nodes.env.style.height = restH + 'px'
          nodes.env.style.zIndex = '1'
        }
        nodes.env.style.zIndex = hatch ? '1' : '6'
        nodes.env.style.transformOrigin = 'center center'
        if (hatch) {
          const hatchBox = hatch.getBoundingClientRect()
          nodes.env.style.transform = `translate3d(${cx - hatchBox.left - restW / 2}px, ${cy - hatchBox.top - restH / 2}px, 0) scale(${scale}) rotate(${tilt}deg)`
          nodes.env.style.clipPath = ''
          nodes.env.style.opacity = String(1 - ramp(into, 0.86, 1))
        } else {
          nodes.env.style.transform = `translate3d(${cx - home.x}px, ${cy - home.y}px, 0) scale(${scale}) rotate(${tilt}deg)`
        }
        if (!hatch && into > 0.02) {
          const s = Math.max(0.05, scale)
          const top = Math.max(0, (mouth.top - cy) / s + restH / 2 - 4 / s)
          const bottom = Math.max(0, restH - ((mouth.top + mouth.height - cy) / s + restH / 2) - 3 / s)
          const left = Math.max(0, (mouth.left - cx) / s + restW / 2 - 2 / s)
          const right = Math.max(0, restW - ((mouth.left + mouth.width - cx) / s + restW / 2) - 2 / s)
          nodes.env.style.clipPath = top + bottom < restH - 1 && left + right < restW - 1
            ? `inset(${top}px ${right}px ${bottom}px ${left}px)`
            : ''
        } else if (!hatch) nodes.env.style.clipPath = ''
        if (!hatch) nodes.env.style.opacity = String(1 - ramp(insertT, 0.94, 1))
        const groundY = Math.max(home.y, cy) + restH * 0.08
        shade.style.opacity = String(0.28 * (1 - into))
        shade.style.transform = `translate3d(${cx - 28}px, ${groundY}px, 0) scale(${0.55 + (1 - scale) * 0.2}, 0.55)`
        const exit = manifest.mailbox.anchors.exit
        if (elapsed >= 2940 && exit) {
          const side = shell?.querySelector<HTMLElement>(`[data-mail-slot="${lane}"]`)
          const sideBox = side?.getBoundingClientRect()
          const exitPoint = { x: mail.left + exit[0] * mail.width, y: mail.top + exit[1] * mail.height }
          const dest = sideBox && sideBox.width > 2 ? { x: sideBox.left + sideBox.width / 2, y: sideBox.top + sideBox.height / 2 } : { x: exitPoint.x - 80, y: exitPoint.y }
          if (!route) {
            route = document.createElement('div')
            route.className = 'routing-letter'
            route.dataset.lane = lane
            route.setAttribute('aria-hidden', 'true')
            const img = document.createElement('img')
            img.src = srcOf(base, 'envelope-light-closed')
            img.alt = ''
            route.append(img)
            document.body.append(route)
            pin(route, 0, 0, 36, 24)
          }
          const local = ramp(elapsed, 2940, 3420)
          const p = Math.min(1.04, Math.max(0, springAt(local * 520, SPRING.mass)))
          const along = Math.min(1, p)
          const slotIn = Math.max(0, (along - 0.62) / 0.38)
          if (side && slotIn > 0.04 && route.parentElement !== side) side.append(route)
          if (route.parentElement === side && sideBox) {
            route.style.position = 'absolute'
            route.style.left = '0'
            route.style.top = '0'
            route.style.width = '34px'
            route.style.height = '18px'
            route.style.margin = '0'
            route.style.transformOrigin = 'center top'
            route.style.transform = `translate3d(${sideBox.width / 2 - 17}px, ${lerp(2, -22, slotIn)}px, 0) scale(${lerp(0.9, 0.5, slotIn)})`
            route.style.opacity = '1'
          } else {
            const midX = (exitPoint.x + dest.x) / 2 - 20
            const midY = Math.min(exitPoint.y, dest.y) - 48
            const rx = quad(exitPoint.x, midX, dest.x, along) - 18
            const ry = quad(exitPoint.y, midY, dest.y, along) - 12
            const rdx = quadTan(exitPoint.x, midX, dest.x, Math.min(0.96, Math.max(0.04, along)))
            const rdy = quadTan(exitPoint.y, midY, dest.y, Math.min(0.96, Math.max(0.04, along)))
            const rtilt = Math.max(-14, Math.min(10, Math.atan2(rdy, rdx) * 8))
            route.style.transform = `translate3d(${rx}px, ${ry}px, 0) rotate(${rtilt}deg)`
            route.style.opacity = '1'
          }
        }
      }
    } else shade.style.opacity = '0'
    if (u < 1) return true
    finish()
    onDone?.()
    return false
  }
  const cancel = bindFrame('delivery:' + lane + ':send', tick)
  return () => { stopped = true; cancel(); finish() }
}

export function resetDelivery(env: HTMLElement, flap: HTMLElement, paper: HTMLElement, closed: HTMLElement, wax: HTMLElement) {
  const station = env.closest('.delivery-apparatus')
  if (station && env.parentElement !== station) station.append(env)
  delete env.dataset.slotted
  env.style.zIndex = ''
  env.style.position = ''
  env.style.margin = ''
  env.style.left = ''
  env.style.top = ''
  env.style.width = ''
  env.style.height = ''
  env.style.transform = ''
  env.style.transformOrigin = ''
  env.style.clipPath = ''
  env.style.opacity = ''
  flap.style.transform = ''
  flap.style.opacity = ''
  paper.style.display = ''
  paper.style.visibility = 'hidden'
  paper.style.opacity = ''
  closed.style.opacity = ''
  wax.style.opacity = ''
  wax.style.left = ''
  wax.style.top = ''
  wax.style.transform = ''
  paper.style.inset = ''
  paper.style.overflow = ''
  const copy = paper.querySelector<HTMLElement>('.letter-insert-copy')
  if (copy) copy.style.opacity = ''
  const letter = env.closest('.letter-station')
  const mail = letter?.querySelector<HTMLElement>('.desk-mailbox')
  if (mail) { mail.classList.remove('is-fed', 'is-accepting', 'is-shut'); delete mail.dataset.fed }
  const stack = letter?.querySelector<HTMLElement>('.sheet-stack')
  if (stack) stack.style.opacity = ''
  const hint = letter?.querySelector<HTMLElement>('.paper-hint')
  if (hint) hint.style.opacity = ''
  const lane = letter?.classList.contains('notes') ? 'notes' : 'publish'
  document.querySelectorAll('.fold-sheet,.routing-letter,.slot-letter,.cast-shadow').forEach(node => {
    if ((node as HTMLElement).dataset.lane === lane) node.remove()
  })
}

export function playPageTurn(sheet: DOMRect, dir: 'next' | 'prev', lines: string[] = []) {
  if (reducedMotion() || sheet.width < 2) return Promise.resolve()
  const flyer = document.createElement('div')
  flyer.className = 'page-flyer'
  flyer.dataset.motion = 'page'
  flyer.setAttribute('aria-hidden', 'true')
  const face = ruledSheet(lines, sheet.width, sheet.height)
  const curl = document.createElement('div')
  curl.className = 'page-curl'
  const back = document.createElement('div')
  back.className = 'page-flyer-back'
  const shade = document.createElement('div')
  shade.className = 'page-shade'
  flyer.append(face, curl, back, shade)
  back.style.opacity = '0'
  document.body.append(flyer)
  pin(flyer, sheet.left, sheet.top, sheet.width, sheet.height)
  const atlas = currentManifest()['paper-turn']
  const started = performance.now()
  let cancel = () => {}
  let settle = () => {}
  const promise = new Promise<void>(resolve => {
    settle = resolve
    const tick = (now: number) => {
      const p = springAt(now - started, SPRING.soft)
      const shown = Math.max(0, Math.min(1.08, p))
      if (atlas) {
        const frame = Math.min(atlas.frames - 1, Math.floor(Math.min(1, shown) * (atlas.frames - 1)))
        const pos = atlasPosition(frame, atlas.columns, atlas.rows)
        const atlasName = (atlas.atlas || 'paper-turn-light-atlas.webp').replace(/\.webp$/, '')
        curl.style.backgroundImage = `url(${srcOf(import.meta.env.BASE_URL, atlasName)})`
        curl.style.backgroundSize = `${atlas.columns * 100}% ${atlas.rows * 100}%`
        curl.style.backgroundPosition = `${pos.x}% ${pos.y}%`
      }
      if (dir === 'next') {
        const slide = (1 - Math.min(1, shown)) * Math.min(72, sheet.width * 0.28)
        const drop = (1 - Math.min(1, shown)) * Math.min(64, sheet.height * 0.36)
        flyer.style.transform = `translate3d(${sheet.left + slide}px, ${sheet.top + drop}px, 0) rotate(${(1 - Math.min(1, shown)) * 7}deg)`
        shade.style.opacity = String(0.15 + (1 - Math.min(1, shown)) * 0.35)
        curl.style.opacity = String(0.4 * (1 - Math.min(1, shown)))
        back.style.opacity = '0'
      } else {
        const peel = Math.min(1, shown)
        flyer.style.transform = `translate3d(${sheet.left}px, ${sheet.top}px, 0)`
        face.style.clipPath = `polygon(${peel * 78}% 0, 100% 0, 100% 100%, 0 100%, 0 ${peel * 78}%)`
        back.style.transformOrigin = '0 0'
        back.style.transform = `scale(${Math.max(0.08, peel)})`
        back.style.opacity = String(Math.min(1, peel * 1.15))
        curl.style.opacity = String(Math.min(1, peel))
        shade.style.opacity = String(0.2 * (1 - peel * 0.5))
      }
      if (!springSettled(now - started)) return true
      flyer.remove()
      resolve()
      return false
    }
    cancel = bindFrame('page:turn:'+crypto.randomUUID(), tick)
  })
  return Object.assign(promise, { cancel: () => { cancel(); flyer.remove(); settle() } })
}

type WoodRect = { x: number; y: number; width: number; height: number; rot: number }

export function glideWood(el: HTMLElement, from: WoodRect, to: WoodRect, _ms = 450) {
  el.classList.add('wood-flight')
  if (reducedMotion()) {
    parkWood(el, to)
    el.classList.remove('wood-flight')
    return Object.assign(Promise.resolve(), { cancel: () => {} })
  }
  const started = performance.now()
  pin(el, from.x - from.width / 2, from.y - from.height / 2, from.width, from.height)
  el.style.transformOrigin = 'center center'
  let cancel = () => {}
  let settle = () => {}
  const promise = new Promise<void>(resolve => {
    settle = resolve
    const tick = (now: number) => {
      const p = springAt(now - started, SPRING.soft)
      const arc = p > 0 && p < 1 ? Math.sin(Math.PI * p) * 92 : 0
      const x = lerp(from.x, to.x, p)
      const y = lerp(from.y, to.y, p) - arc
      const scale = lerp(1, to.width / Math.max(1, from.width), p)
      const dx = x - from.x
      const dy = y - from.y
      el.style.transform = `translate3d(${from.x - from.width / 2 + dx}px, ${from.y - from.height / 2 + dy}px, 0) scale(${scale}) rotate(${lerp(from.rot, to.rot, p)}deg)`
      if (!springSettled(now - started)) return true
      parkWood(el, to)
      el.classList.remove('wood-flight')
      resolve()
      return false
    }
    cancel = bindFrame('wood:' + (el.dataset.id || 'log'), tick)
  })
  return Object.assign(promise, { cancel:()=>{cancel();settle()} })
}

function parkWood(el: HTMLElement, to: WoodRect) {
  el.style.position = 'fixed'
  el.style.left = (to.x - to.width / 2) + 'px'
  el.style.top = (to.y - to.height / 2) + 'px'
  el.style.width = to.width + 'px'
  el.style.height = to.height + 'px'
  el.style.transform = `rotate(${to.rot}deg)`
  el.style.zIndex = '2'
  el.style.willChange = ''
}

/** Notes land above the rollers; the machine canvas then owns the same feed. */
export function flyShredPaper(from: DOMRect, machine: () => HTMLElement | null, title: string) {
  if (reducedMotion()) return Object.assign(Promise.resolve(), {cancel:()=>{}})
  const paper=document.createElement('div')
  paper.className='task-paper-flight shred-paper-flight'
  paper.textContent=title
  document.body.append(paper)
  const started=performance.now(), key=crypto.randomUUID()
  let stop=()=>{}, finish=()=>{}
  const promise=new Promise<void>(resolve=>{
    finish=()=>{paper.remove();resolve()}
    stop=bindFrame('feed:'+key,now=>{
      const host=machine()
      if(!host||host.closest('[inert]')){finish();return false}
      const rect=host.getBoundingClientRect(), feed=anchorPixels(rect,currentManifest().shredder.anchors.feed)
      const t=ramp(now-started,0,700), ease=t*t*(3-2*t)
      const width=rect.width*.42, height=rect.height*.46
      pin(paper,lerp(from.left,feed.x-width/2,ease),lerp(from.top,feed.y-height,ease)-Math.sin(t*Math.PI)*20,lerp(from.width,width,ease),lerp(from.height,height,ease))
      paper.style.rotate=`${(1-ease)*-6}deg`
      if(t<1)return true
      finish();return false
    })
  })
  return Object.assign(promise,{cancel:()=>{stop();finish()}})
}

export function flyTaskPaper(from: DOMRect, to: () => Point | null, title: string, key = 'task') {
  if (from.width < 2) return Object.assign(Promise.resolve(), { cancel: () => {} })
  const card = document.createElement('div')
  card.className = 'task-paper-flight'
  card.dataset.lane = 'task'
  card.setAttribute('aria-hidden', 'true')
  card.textContent = title
  const lip = document.createElement('i')
  lip.className = 'burn-lip'
  card.append(lip)
  const shade = castShadow()
  shade.dataset.lane = 'task'
  document.body.append(card, shade)
  const w0 = 112
  const h0 = 28
  card.style.fontSize = '11px'
  card.style.lineHeight = '28px'
  card.style.overflow = 'hidden'
  card.style.whiteSpace = 'nowrap'
  card.style.textOverflow = 'ellipsis'
  pin(card, from.left, from.top, w0, h0)
  card.style.opacity = '0'
  card.style.transformOrigin = 'center center'
  const started = performance.now()
  let host: HTMLElement | null = null
  let told = false
  let cancel = () => {}
  let settle = () => {}
  const clear = () => { card.remove(); shade.remove(); settle() }
  const promise = new Promise<void>(resolve => {
    settle = resolve
    const tick = (now: number) => {
      const dest = to()
      if (!dest) { clear(); if (!told) { told = true; resolve() }; return false }
      const elapsed = now - started
      const travel = Math.min(1, elapsed / 1100)
      const te = travel * travel * (3 - 2 * travel)
      const fadeIn = ramp(elapsed, 0, 140)
      const sx = from.left + w0 / 2
      const sy = from.top + h0 / 2
      const end = { x: dest.x, y: dest.y + 6 }
      const c1 = { x: sx + Math.min(70, Math.max(16, (end.x - sx) * 0.28)), y: sy + 28 }
      const c2 = { x: end.x - 36, y: end.y + 18 }
      const tx = cubicTan(sx, c1.x, c2.x, end.x, Math.min(0.98, Math.max(0.02, te)))
      const ty = cubicTan(sy, c1.y, c2.y, end.y, Math.min(0.98, Math.max(0.02, te)))
      const len = Math.hypot(tx, ty) || 1
      const sway = Math.sin(te * Math.PI * 2.1) * 8 * (1 - te * 0.35)
      let x = cubic(sx, c1.x, c2.x, end.x, te) + (-ty / len) * sway
      let y = cubic(sy, c1.y, c2.y, end.y, te) + (tx / len) * sway
      x = Math.min(x, end.x + 10)
      y = Math.max(y, end.y - 28)
      const rot = Math.max(-22, Math.min(18, Math.atan2(ty, tx) * 180 / Math.PI * 0.18)) + Math.sin(te * 9) * 4 * (1 - te)
      if (!host) host = liveProcess()
      if(host?.closest('[inert]')){clear();return false}
      const sink = ramp(te, 0.58, 0.92)
      const burn = ramp(te, 0.72, 1)
      let scaleX = lerp(1, 78 / w0, Math.min(1, te * 1.3))
      let scaleY = lerp(1, 26 / h0, Math.min(1, te * 1.3))
      if (sink > 0.04 && host) {
        const front = host.querySelector('.process-machine.foreground')
        if (card.parentElement !== host) {
          if (front) host.insertBefore(card, front)
          else host.append(card)
        }
        const box = host.getBoundingClientRect()
        scaleX = lerp(scaleX, 72 / w0, sink)
        scaleY = lerp(scaleY, 22 / h0, sink)
        card.style.position = 'absolute'
        card.style.zIndex = '3'
        card.style.left = '0'
        card.style.top = '0'
        card.style.transformOrigin = 'center center'
        card.style.transform = `translate3d(${x - box.left - w0 / 2}px, ${y - box.top - h0 / 2}px, 0) scale(${scaleX}, ${scaleY}) rotate(${rot * (1 - sink)}deg)`
      } else {
        if (card.parentElement !== document.body) document.body.append(card)
        card.style.position = 'fixed'
        card.style.zIndex = '60'
        card.style.transformOrigin = 'center center'
        card.style.transform = `translate3d(${x - w0 / 2}px, ${y - h0 / 2}px, 0) scale(${scaleX}, ${scaleY}) rotate(${rot}deg)`
      }
      lip.style.opacity = String(Math.min(1, burn * 1.6))
      lip.style.bottom = `${burn * 42}%`
      card.style.clipPath = burn > 0.03 ? `inset(0 0 ${burn * 42}% 0)` : ''
      const fade = Math.max(ramp(sink, 0.02, 0.32), ramp(burn, 0.45, 1))
      card.style.opacity = String(fadeIn * (1 - fade))
      card.classList.toggle('is-ember', burn > 0.08)
      shade.style.opacity = String(0.3 * fadeIn * (1 - sink) * (1 - fade))
      shade.style.transform = `translate3d(${x - 30}px, ${Math.max(sy, y) + 10}px, 0) scale(${0.8 + Math.sin(Math.PI * te) * 0.4}, .6)`
      if (!told && te > 0.74) { told = true; resolve() }
      if (fade < 1) return true
      clear()
      return false
    }
    cancel = bindFrame('arrive:' + key, tick)
  })
  return Object.assign(promise, { cancel: () => { cancel(); clear() } })
}

/** Each request owns its paper, shadow and completion, including cancellation. */
export function flyTrashSheets(from: { rect: DOMRect; title: string }[], target: () => HTMLElement | null) {
  if (reducedMotion() || !from.length) return Object.assign(Promise.resolve(), { cancel: () => {} })
  const id = crypto.randomUUID()
  const nodes = from.slice(0, 3).map((item, index) => {
    const el = document.createElement('div')
    el.className = 'trash-sheet' + (from.length > 3 && index === 2 ? ' is-stack' : '')
    el.dataset.flightId = id
    el.setAttribute('aria-hidden', 'true')
    const face = document.createElement('span')
    face.textContent = item.title
    el.append(face)
    for (let i = 0; i < 6; i++) { const fold = document.createElement('i'); fold.className = 'trash-fold'; fold.style.setProperty('--facet', String(i)); el.append(fold) }
    const shadow = castShadow()
    document.body.append(el, shadow)
    const w = Math.max(item.rect.width, 96), h = Math.max(item.rect.height, 64)
    pin(el, item.rect.left, item.rect.top, w, h)
    el.style.transformOrigin = 'center'
    return { el, shadow, w, h, x: item.rect.left + w / 2, y: item.rect.top + h / 2 }
  })
  const started = performance.now()
  let cancel = () => {}
  let settle = () => {}
  let done = false
  const clear = () => {
    if (done) return
    done = true
    nodes.forEach(node => { node.el.remove(); node.shadow.remove() })
    settle()
  }
  const promise = new Promise<void>(resolve => {
    settle = resolve
    cancel = bindFrame('trash:' + id, now => {
      const bin = target()
      const hole = bin && mouthOf(bin, currentManifest())
      if (!bin || !hole || !bin.isConnected || bin.closest('[inert]')) { clear(); return false }
      let live = false
      nodes.forEach((node, index) => {
        const elapsed = now - started - index * 140
        if (elapsed < 0) { node.el.style.opacity = '0'; live = true; return }
        const ball = ramp(elapsed, 0, 360)
        const t = ramp(elapsed, 340, 1080)
        const x = lerp(node.x, hole.x, t)
        const y = lerp(node.y, hole.y + 16, t) - Math.sin(Math.PI * t) * 100
        const sx = lerp(1, 25 / node.w, ball), sy = lerp(1, 25 / node.h, ball)
        node.el.style.setProperty('--crumple', String(ball))
        node.el.style.borderRadius = `${ball * 44}%`
        node.el.style.clipPath = ball > .3 ? 'polygon(8% 20%,28% 3%,64% 0,90% 19%,100% 60%,79% 95%,38% 100%,3% 71%)' : ''
        let px = x, py = y
        if (t > .9) {
          // The actual foreground texture covers the ball as it crosses the rim.
          if (node.el.parentElement !== bin) bin.insertBefore(node.el, bin.querySelector('.trash-front'))
          const box = bin.getBoundingClientRect()
          px -= box.left; py -= box.top
          node.el.style.position = 'absolute'; node.el.style.zIndex = '2'
          bin.classList.add('is-fed')
        }
        node.el.style.transform = `translate3d(${px - node.w / 2}px, ${py - node.h / 2}px, 0) rotate(${ball * 30 + t * 270 + Math.sin(t * 18) * 8}deg) scale(${sx},${sy})`
        node.el.style.opacity = t >= 1 ? '0' : '1'
        node.shadow.style.transform = `translate3d(${x - 22}px, ${lerp(node.y, hole.y + 25, t)}px, 0) scale(${1 - Math.sin(Math.PI * t) * .55}, .4)`
        node.shadow.style.opacity = String(.24 * (1 - ramp(t, .85, 1)))
        live ||= elapsed < 1190
      })
      if (live) return true
      bin.classList.remove('is-fed')
      clear(); return false
    })
  })
  return Object.assign(promise, { cancel: () => { cancel(); target()?.classList.remove('is-fed'); clear() } })
}

export function launchTear(rows: { text: string; rect: DOMRect }[], pile: () => HTMLElement | null) {
  if (reducedMotion()) return
  rows.slice(0, 3).forEach((row, index) => {
    const el = document.createElement('div')
    el.className = 'tear-sheet' + (rows.length > 3 && index === 2 ? ' is-stack' : '')
    el.textContent = row.text
    document.body.append(el)
    const w = row.rect.width
    const h = Math.max(28, row.rect.height)
    pin(el, row.rect.left, row.rect.top, w, h)
    const started = performance.now() + index * 46
    bindFrame('tear:' + crypto.randomUUID(), now => {
      if(pile()?.closest('[inert]')){el.remove();return false}
      const elapsed = now - started
      if (elapsed < 0) return true
      const dest = pile()?.getBoundingClientRect()
      const p = springAt(elapsed, SPRING.soft)
      const x = dest ? lerp(row.rect.left, dest.left, Math.min(1.06, p)) : row.rect.left
      const y = dest ? lerp(row.rect.top, dest.top + 24, Math.min(1.06, p)) : row.rect.top + 70 * Math.min(1, p)
      el.style.transform = `translate3d(${x}px, ${y}px, 0) rotate(${lerp(-6, 2, Math.min(1, p))}deg)`
      el.style.opacity = String(elapsed < 40 ? 0 : 1 - ramp(Math.min(1, p), 0.82, 1))
      if (!springSettled(Math.max(0, elapsed))) return true
      el.remove()
      return false
    })
  })
}

export function mouthOf(host: HTMLElement, manifest: WorkbenchManifest) {
  const anchors = manifest.trash?.anchors
  if (!anchors) return null
  const center = anchorPixels(host.getBoundingClientRect(), anchors.mouthCenter, manifest.trash?.size)
  const box = normBox(host.getBoundingClientRect(), anchors.mouth, manifest.trash?.size)
  return { x: center.x, y: center.y, width: box.width, height: box.height, left: box.left, top: box.top }
}
