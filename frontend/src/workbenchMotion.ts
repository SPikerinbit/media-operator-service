import type { PaperProcessHandle, PaperPose } from './paperScene'
import { anchorPixels, atlasPosition, currentManifest, normBox, type WorkbenchManifest } from './workbenchAnchors'
import { bindFrame } from './workbenchScheduler'
import { easeOutCubic, easeOutQuart, flapBounceAngle, lerp, ramp, springAt, springSettled, SPRING } from './motionSystem'

const srcOf = (base: string, name: string) => `${base}workbench/${name}.webp`
const reducedMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches

export const DELIVERY_PHASES = [
  { id: 'fold', ms: 680 },
  { id: 'tuck', ms: 340 },
  { id: 'seal', ms: 420 },
  { id: 'insert', ms: 680 },
  { id: 'route', ms: 360 },
] as const

export type DeliveryPhase = (typeof DELIVERY_PHASES)[number]['id']

export const DELIVERY_MS = DELIVERY_PHASES.reduce((sum, phase) => sum + phase.ms, 0)

type DeliveryNodes = {
  root: HTMLElement
  env: HTMLElement
  mail: HTMLElement
  mailFlap?: HTMLElement | null
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

/** Smooth single-equation C2 fold curve (zero piecewise velocity kinks). */
function foldAngle(elapsed: number, delay: number, duration = 440) {
  const u = Math.min(1, Math.max(0, (elapsed - delay) / duration))
  if (u <= 0) return 0
  if (u >= 1) return 180
  // C2 smootherstep blended with a gentle crisp lift so the sheet swings up fluidly and settles flat.
  const smooth = u * u * u * (u * (u * 6 - 15) + 10)
  const lift = easeOutCubic(u)
  return 180 * (0.72 * smooth + 0.28 * lift)
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

function ruledSheet(lines: string[], width: number, height: number, ruleHeight = 32) {
  const face = document.createElement('div')
  face.className = 'page-flyer-face'
  face.style.width = width + 'px'
  face.style.height = height + 'px'
  face.style.setProperty('--rule-h', ruleHeight + 'px')
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
function buildFold(lines: string[], width: number, height: number, ruleHeight: number) {
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
    const surface = ruledSheet(lines, width, height, ruleHeight)
    surface.style.position = 'absolute'
    surface.style.top = `${-index * height / 3}px`
    face.append(surface)
    const edge = document.createElement('i')
    edge.className = 'fold-thickness'
    face.append(edge)
    const shade = document.createElement('i')
    shade.className = 'fold-panel-shade'
    face.append(shade)
    const back = document.createElement('div')
    back.className = 'fold-backface'
    panel.append(face, back)
    return { panel, shade }
  }
  const third = height / 3
  const top = panelOf(0)
  top.panel.classList.add('is-top')
  top.panel.style.height = third + 'px'
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
  hingeBot.append(creaseBot, bot.panel)
  hingeMid.append(creaseMid, mid.panel, hingeBot)
  stage.style.height = height + 'px'
  stage.append(top.panel, hingeMid)
  cam.append(stage)
  sheet.append(cam)
  return { sheet, stage, hingeMid, hingeBot, creaseMid, creaseBot, shadeMid: mid.shade, shadeBot: bot.shade }
}

/** Fold, tuck, seal, insert (with 3D mailbox flap open + gravity bounce shut), and route as one continuous gesture. */
export function playDelivery(nodes: DeliveryNodes, manifest: WorkbenchManifest, base: string, onPhase: (phase: DeliveryPhase) => void, onDone?: () => void) {
  if (reducedMotion()) { onDone?.(); return () => {} }
  let stopped = false
  let previous = performance.now()
  let elapsed = 0
  let announced = ''

  // Batch all initial DOM reads before any DOM writes to avoid forced synchronous layout.
  const homeRect = nodes.sheet?.getBoundingClientRect()
  const ruleSample = nodes.sheet?.querySelector<HTMLElement>('.rule-input')
  const ruleHeight = Math.max(24, Math.round(ruleSample?.getBoundingClientRect().height || 32))
  const lines = nodes.lines?.length ? nodes.lines : [...(nodes.sheet?.querySelectorAll('input') || [])].map(node => (node as HTMLInputElement).value).filter(Boolean)
  const shell = nodes.root.closest('.workbench-shell')
  const lane = nodes.root.classList.contains('notes') ? 'notes' : 'publish'
  const sheetW = homeRect?.width || 400
  const sheetH = homeRect?.height || 220
  let originX = homeRect?.left || 0
  let originY = homeRect?.top || 0
  const restW = nodes.env.offsetWidth
  const restH = nodes.env.offsetHeight
  let envBase = nodes.env.getBoundingClientRect()
  let mailRect = nodes.mail.getBoundingClientRect()
  let hatchEl = nodes.mail.querySelector<HTMLElement>('.slot-window')
  let hatchRect = hatchEl?.getBoundingClientRect() || null
  let sideEl = shell?.querySelector<HTMLElement>(`[data-mail-slot="${lane}"]`) || null
  let sideRect = sideEl?.getBoundingClientRect() || null
  const mailFlap = nodes.mailFlap ?? nodes.mail.querySelector<HTMLElement>('.slot-flap')
  const home: Point = nodes.env.dataset.home
    ? JSON.parse(nodes.env.dataset.home) as Point
    : { x: envBase.left + envBase.width / 2, y: envBase.top + envBase.height / 2 }
  const source = (nodes.sheet?.closest('.sheet-stack') as HTMLElement | null) || nodes.sheet || null
  const hint = nodes.sheet?.closest('.writing-paper')?.querySelector<HTMLElement>('.paper-hint') || null

  // Now perform all initial DOM mutations together.
  const built = buildFold(lines.slice(0, 8), sheetW, sheetH, ruleHeight)
  const flight = built.sheet
  flight.dataset.lane = lane
  flight.setAttribute('aria-hidden', 'true')
  document.body.append(flight)
  pin(flight, originX, originY, sheetW, sheetH)
  flight.style.transformOrigin = '0 0'
  flight.style.willChange = 'transform, opacity'
  flight.style.perspective = ''
  if (source) {
    source.style.transition = 'opacity 140ms ease-out'
    source.style.opacity = '0'
  }
  if (hint) hint.style.opacity = '0'
  const shade = castShadow()
  shade.dataset.lane = lane
  document.body.append(shade)
  let route: HTMLElement | null = null
  const placeholder = document.createElement('div')
  placeholder.className = 'delivery-envelope delivery-placeholder'
  placeholder.style.visibility = 'hidden'
  placeholder.style.display = 'none'
  nodes.env.before(placeholder)
  if (mailFlap) mailFlap.style.transition = 'none'

  const remeasure = () => {
    const sheetBox = nodes.sheet?.getBoundingClientRect()
    if (sheetBox && sheetBox.width > 2) { originX = sheetBox.left; originY = sheetBox.top }
    const anchorEl = placeholder.style.display !== 'none' ? placeholder : nodes.env
    const nextEnv = anchorEl.getBoundingClientRect()
    if (nextEnv.width > 2) {
      envBase = nextEnv
      home.x = envBase.left + envBase.width / 2
      home.y = envBase.top + envBase.height / 2
    }
    const nextMail = nodes.mail.getBoundingClientRect()
    if (nextMail.width > 2) mailRect = nextMail
    hatchEl = nodes.mail.querySelector<HTMLElement>('.slot-window')
    if (hatchEl) hatchRect = hatchEl.getBoundingClientRect()
    sideEl = shell?.querySelector<HTMLElement>(`[data-mail-slot="${lane}"]`) || null
    if (sideEl) sideRect = sideEl.getBoundingClientRect()
  }
  const resizeObserver = new ResizeObserver(remeasure)
  resizeObserver.observe(nodes.root)
  window.addEventListener('resize', remeasure)

  const raise = Math.max(0, originY + sheetH - (window.innerHeight - 28))
  let flapSlamTriggered = false
  const finish = () => {
    resizeObserver.disconnect()
    window.removeEventListener('resize', remeasure)
    if (source) source.style.opacity = ''
    if (hint) hint.style.opacity = ''
    flight.remove()
    shade.remove()
    route?.remove()
    placeholder.remove()
    nodes.env.style.visibility = ''
    nodes.env.style.marginTop = ''
    if (mailFlap) {
      mailFlap.style.transform = ''
      mailFlap.style.filter = ''
      mailFlap.style.transition = ''
    }
    sideEl?.closest('.nav-item')?.classList.remove('is-receiving')
  }

  let wasPaused = false
  const tick = (now: number) => {
    if (stopped) return false
    const dt = now - previous
    previous = now
    const paused = document.hidden || nodes.isActive?.() === false
    flight.style.visibility = paused ? 'hidden' : 'visible'
    shade.style.visibility = paused ? 'hidden' : 'visible'
    if (route) route.style.visibility = paused ? 'hidden' : 'visible'
    nodes.env.style.visibility = paused ? 'hidden' : ''
    if (paused) { wasPaused = true; return true }
    if (wasPaused) { wasPaused = false; remeasure() }
    elapsed += Math.min(50, dt)
    const u = Math.min(1, elapsed / DELIVERY_MS)
    const phase = phaseOf(elapsed)
    if (phase !== announced) { announced = phase; onPhase(phase) }

    // Overlapping phase windows so momentum flows cleanly without stopping dead between steps.
    const tuckT = ramp(elapsed, 560, 1000)
    const sealT = ramp(elapsed, 960, 1440)
    const uInsert = Math.min(1, Math.max(0, (elapsed - 1380) / 740))

    // Pure GPU translate3d envelope nudge down to make room for the open flap (zero reflow).
    const room = 48 * easeOutCubic(Math.min(1, elapsed / 240)) * (1 - sealT)
    if (uInsert <= 0) {
      nodes.env.style.transform = room > 0.05 ? `translate3d(0, ${room}px, 0)` : ''
    } else if (placeholder.style.display === 'none') {
      placeholder.style.display = ''
      nodes.env.style.transform = ''
    }

    // Smooth C2 tri-fold (bottom folds first, mid overlaps cleanly at 220ms).
    const fold1 = foldAngle(elapsed, 0, 440)
    const fold2 = foldAngle(elapsed, 220, 440)
    const tiltIn = easeOutCubic(Math.min(1, elapsed / 170))
    built.stage.style.transform = `rotateX(${tiltIn * 24 * (1 - tuckT)}deg) rotateY(${tiltIn * -16 * (1 - tuckT)}deg)`
    built.hingeBot.style.transform = `rotateX(${fold1}deg)`
    built.hingeMid.style.transform = `rotateX(${fold2}deg)`
    const applyFoldLight = (creaseEl: HTMLElement, shadeEl: HTMLElement, angle: number) => {
      const edge = Math.sin(Math.min(180, Math.max(0, angle)) * Math.PI / 180)
      creaseEl.style.opacity = String(0.15 + edge * 0.85)
      shadeEl.style.opacity = String(edge * 0.22)
    }
    applyFoldLight(built.creaseBot, built.shadeBot, fold1)
    applyFoldLight(built.creaseMid, built.shadeMid, fold2)

    const present = easeOutCubic(Math.min(1, elapsed / 200))
    const yLift = raise * present
    const envTop = envBase.top + (uInsert > 0 ? 0 : room)
    const envLeft = envBase.left
    const envWidth = envBase.width
    const envHeight = envBase.height
    const mail = mailRect
    const pocket = manifest.envelope.anchors.pocket
    const pocketBox = pocket && envWidth > 2 ? {
      x: envLeft + pocket[0] * envWidth,
      y: envTop + pocket[1] * envHeight,
      w: pocket[2] * envWidth,
      h: pocket[3] * envHeight,
    } : null
    const sideGap = pocketBox ? (pocketBox.w - sheetW * Math.min(0.9, pocketBox.w * 0.82 / sheetW)) / 2 : 8
    const destX = pocketBox ? pocketBox.x + sideGap : envLeft + envWidth * 0.12
    const destY = pocketBox ? pocketBox.y + pocketBox.h * 0.15 : envTop + envHeight * 0.5
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
      flight.style.transform = `translate3d(${x - envLeft}px, ${y - envTop}px, 0) scale(${tuckScale})`
    } else {
      if (flight.parentElement !== document.body) document.body.append(flight)
      flight.style.position = 'fixed'
      flight.style.zIndex = '40'
      flight.style.transform = `translate3d(${originX}px, ${originY - yLift}px, 0) scale(${tuckScale})`
    }
    flight.style.opacity = String(tuckT > 0.9 ? 1 - ramp(sealT, 0.02, 0.25) : 1)
    nodes.copy.style.opacity = '0'
    nodes.flap.style.opacity = '1'
    nodes.closed.style.opacity = '0'

    // Envelope flap opens smoothly at start (fully open by 240ms, well before 430ms hinge test) and seals cleanly.
    if (sealT < 0.015) {
      const open = ramp(elapsed, 15, 240)
      const waxOff = ramp(elapsed, 10, 140)
      nodes.flap.style.transform = `rotateX(${open * 180}deg)`
      nodes.wax.style.opacity = String(1 - waxOff)
      nodes.wax.style.transform = `translate(-50%, -50%) translateY(${-12 * waxOff}px) scale(${lerp(1, 0.72, waxOff)})`
    } else {
      const shut = Math.min(1, sealT / 0.58)
      nodes.flap.style.transform = `rotateX(${(1 - shut) * 180}deg)`
      const pressStart = 0.58
      if (sealT < pressStart) {
        nodes.wax.style.opacity = '0'
        nodes.wax.style.transform = 'translate(-50%, -50%) scale(1.36)'
      } else {
        const local = (sealT - pressStart) / (1 - pressStart)
        const stamp = Math.max(0, springAt(local * 260, SPRING.press))
        nodes.wax.style.opacity = String(Math.min(1, local / 0.16))
        const squashY = stamp < 0.45 ? lerp(1.38, 0.80, stamp / 0.45) : lerp(0.80, 1, Math.min(1, (stamp - 0.45) / 0.55))
        const squashX = stamp < 0.45 ? lerp(0.88, 1.14, stamp / 0.45) : lerp(1.14, 1, Math.min(1, (stamp - 0.45) / 0.55))
        nodes.wax.style.transform = `translate(-50%, -50%) scale(${squashX}, ${squashY})`
      }
    }

    // 3D Mailbox Flap angle calculation (continuous from subtle ready pose -> full 72 deg open -> post-delivery bounce shut).
    let mailboxFlapDeg = 0
    if (elapsed < 1380) {
      // Gentle settle from the 6-deg identify preview down to 0 while folding/sealing
      mailboxFlapDeg = 6 * (1 - easeOutCubic(Math.min(1, elapsed / 260)))
    } else if (elapsed < 2040) {
      const openU = Math.min(1, Math.max(0, (elapsed - 1420) / 340))
      const baseOpen = 72 * easeOutCubic(openU)
      // Tiny lively brush flutter as the envelope glides under the raised flap
      const brushU = Math.min(1, Math.max(0, (elapsed - 1780) / 240))
      const flutter = brushU > 0 && brushU < 1 ? Math.sin(Math.PI * brushU) * 4 : 0
      mailboxFlapDeg = baseOpen + flutter
    } else {
      const shutU = Math.min(1, (elapsed - 2040) / 440)
      mailboxFlapDeg = flapBounceAngle(shutU, 72)
      if (shutU >= 0.34 && !flapSlamTriggered) {
        flapSlamTriggered = true
        nodes.mail.classList.add('is-fed')
      }
    }
    if (mailFlap) {
      if (mailboxFlapDeg > 0.04) {
        const bright = 1 + 0.09 * Math.min(1, mailboxFlapDeg / 72)
        mailFlap.style.transform = `rotateX(${mailboxFlapDeg.toFixed(2)}deg)`
        mailFlap.style.filter = `brightness(${bright.toFixed(3)})`
      } else {
        mailFlap.style.transform = ''
        mailFlap.style.filter = ''
      }
    }

    if (uInsert > 0 && mail.width > 2) {
      const slot = manifest.mailbox.anchors.slotFront
      if (slot) {
        const mouth = normBox(mail, slot, manifest.mailbox.size)
        const slotCenter = { x: mouth.left + mouth.width / 2, y: mouth.top + mouth.height * 0.45 }
        const metalBottom = mail.top + mail.height * 0.76
        const approachScale = 0.68
        const half = restH * approachScale * 0.5
        const approach = { x: slotCenter.x, y: metalBottom + half + 6 }
        const lift = { x: home.x - 24, y: (home.y + approach.y) / 2 - 14 }
        const peak = { x: (home.x + approach.x) / 2 - 12, y: Math.min(home.y, approach.y) - 24 }

        // Continuous non-stopping flight: approach (0..0.72) overlaps smoothly with slot entry (0.58..1.0).
        const travelU = Math.min(1, uInsert / 0.72)
        const te = travelU * travelU * (3 - 2 * travelU)
        const into = ramp(uInsert, 0.58, 1.0)
        if (uInsert > 0.08) nodes.mail.classList.add('is-accepting')

        const sample = Math.min(0.98, Math.max(0.02, te))
        const arcX = cubic(home.x, lift.x, peak.x, approach.x, te)
        const arcY = cubic(home.y, lift.y, peak.y, approach.y, te)
        const tx = cubicTan(home.x, lift.x, peak.x, approach.x, sample)
        const ty = cubicTan(home.y, lift.y, peak.y, approach.y, sample)
        let tilt = Math.atan2(ty, tx) * 180 / Math.PI
        tilt = Math.max(-16, Math.min(12, tilt * 0.30))

        const visible = manifest.envelope.visible_bounds
        const visibleW = visible ? (visible[2] - visible[0]) : 0.84
        const endScale = Math.min(0.36, (mouth.width * 0.90) / Math.max(1, visibleW * restW))

        let cx = arcX
        let cy = arcY
        let scale = lerp(1, approachScale, te)
        if (into > 0) {
          cx = lerp(arcX, slotCenter.x, into)
          // Glide cleanly through slotCenter and past mouth.top so the envelope feeds smoothly into the cavity.
          const slotTargetY = mouth.top - restH * endScale * 0.44
          cy = lerp(arcY, slotTargetY, into)
          scale = lerp(scale, endScale, into)
          tilt = lerp(tilt, 0, into)
          if (into > 0.78) nodes.mail.classList.add('is-shut')
        }

        const hatch = into > 0.02 ? hatchEl : null
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
        if (hatch && hatchRect) {
          nodes.env.style.transform = `translate3d(${cx - hatchRect.left - restW / 2}px, ${cy - hatchRect.top - restH / 2}px, 0) scale(${scale}) rotate(${tilt}deg)`
          nodes.env.style.clipPath = ''
          nodes.env.style.opacity = String(1 - ramp(into, 0.88, 1))
        } else {
          nodes.env.style.transform = `translate3d(${cx - home.x}px, ${cy - home.y}px, 0) scale(${scale}) rotate(${tilt}deg)`
          nodes.env.style.clipPath = ''
          nodes.env.style.opacity = String(1 - ramp(uInsert, 0.94, 1))
        }

        const groundY = Math.max(home.y, cy) + restH * 0.08
        shade.style.opacity = String(0.24 * (1 - into))
        shade.style.transform = `translate3d(${cx - 28}px, ${groundY}px, 0) scale(${0.55 + (1 - scale) * 0.2}, 0.55)`

        const exit = manifest.mailbox.anchors.exit
        if (elapsed >= 2120 && exit) {
          const side = sideEl
          const sideBox = sideRect
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
          const localU = Math.min(1, Math.max(0, (elapsed - 2120) / 360))
          const along = easeOutQuart(localU)
          const slotIn = Math.max(0, (along - 0.70) / 0.30)
          const midX = (exitPoint.x + dest.x) / 2 - 20
          const midY = Math.min(exitPoint.y, dest.y) - 44
          const rx = quad(exitPoint.x, midX, dest.x, along) - 18
          const ry = quad(exitPoint.y, midY, dest.y, along) - 12
          const rdx = quadTan(exitPoint.x, midX, dest.x, Math.min(0.96, Math.max(0.04, along)))
          const rdy = quadTan(exitPoint.y, midY, dest.y, Math.min(0.96, Math.max(0.04, along)))
          const rtilt = Math.max(-14, Math.min(10, Math.atan2(rdy, rdx) * 8)) * (1 - slotIn)
          const rscale = lerp(1, 0.24, slotIn)
          route.style.transformOrigin = 'center center'
          route.style.transform = `translate3d(${rx}px, ${ry}px, 0) scale(${rscale}) rotate(${rtilt}deg)`
          route.style.opacity = String(1 - slotIn)
          if (side && slotIn > 0.12) {
            const navBtn = side.closest('.nav-item')
            if (navBtn && !navBtn.classList.contains('is-receiving')) {
              navBtn.classList.add('is-receiving')
              window.setTimeout(() => navBtn.classList.remove('is-receiving'), 360)
            }
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
  if (mail) {
    mail.classList.remove('is-fed', 'is-accepting', 'is-shut')
    delete mail.dataset.fed
    const mailFlap = mail.querySelector<HTMLElement>('.slot-flap')
    if (mailFlap) {
      mailFlap.style.transform = ''
      mailFlap.style.filter = ''
      mailFlap.style.transition = ''
    }
  }
  const stack = letter?.querySelector<HTMLElement>('.sheet-stack')
  if (stack) stack.style.opacity = ''
  const hint = letter?.querySelector<HTMLElement>('.paper-hint')
  if (hint) hint.style.opacity = ''
  const lane = letter?.classList.contains('notes') ? 'notes' : 'publish'
  document.querySelectorAll('.fold-sheet,.routing-letter,.slot-letter,.cast-shadow').forEach(node => {
    if ((node as HTMLElement).dataset.lane === lane) node.remove()
  })
}

export function playPageTurn(sheet: DOMRect, dir: 'next' | 'prev', lines: string[] = [], ruleHeight = 32) {
  if (reducedMotion() || sheet.width < 2) return Promise.resolve()
  const flyer = document.createElement('div')
  flyer.className = 'page-flyer'
  flyer.dataset.motion = 'page'
  flyer.setAttribute('aria-hidden', 'true')
  const face = ruledSheet(lines, sheet.width, sheet.height, ruleHeight)
  const curl = document.createElement('div')
  curl.className = 'page-curl'
  const back = document.createElement('div')
  back.className = 'page-flyer-back'
  const shade = document.createElement('div')
  shade.className = 'page-shade'
  flyer.append(face, curl, back, shade)
  back.style.opacity = '0'
  const atlas = currentManifest()['paper-turn']
  // Set atlas image & size once outside the frame loop to avoid per-frame style invalidation.
  if (atlas) {
    const atlasName = (atlas.atlas || 'paper-turn-light-atlas.webp').replace(/\.webp$/, '')
    curl.style.backgroundImage = `url(${srcOf(import.meta.env.BASE_URL, atlasName)})`
    curl.style.backgroundSize = `${atlas.columns * 100}% ${atlas.rows * 100}%`
  }
  document.body.append(flyer)
  pin(flyer, sheet.left, sheet.top, sheet.width, sheet.height)
  const started = performance.now()
  let cancel = () => {}
  let settle = () => {}
  const promise = new Promise<void>(resolve => {
    settle = resolve
    const tick = (now: number) => {
      const elapsed = now - started
      const p = springAt(elapsed, SPRING.snappy)
      const shown = Math.max(0, Math.min(1.04, p))
      if (atlas) {
        const frame = Math.min(atlas.frames - 1, Math.floor(Math.min(1, shown) * (atlas.frames - 1)))
        const pos = atlasPosition(frame, atlas.columns, atlas.rows)
        curl.style.backgroundPosition = `${pos.x}% ${pos.y}%`
      }
      if (dir === 'next') {
        const rest = 1 - Math.min(1, shown)
        const slide = rest * Math.min(68, sheet.width * 0.25)
        const drop = rest * Math.min(54, sheet.height * 0.30)
        flyer.style.transform = `translate3d(${sheet.left + slide}px, ${sheet.top + drop}px, 0) rotate(${rest * 6}deg)`
        shade.style.opacity = String(0.12 + rest * 0.30)
        curl.style.opacity = String(0.35 * rest)
        back.style.opacity = '0'
      } else {
        const peel = Math.min(1, shown)
        flyer.style.transform = `translate3d(${sheet.left}px, ${sheet.top}px, 0)`
        face.style.clipPath = `polygon(${peel * 78}% 0, 100% 0, 100% 100%, 0 100%, 0 ${peel * 78}%)`
        back.style.transformOrigin = '0 0'
        back.style.transform = `scale(${Math.max(0.08, peel)})`
        back.style.opacity = String(Math.min(1, peel * 1.15))
        curl.style.opacity = String(Math.min(1, peel))
        shade.style.opacity = String(0.18 * (1 - peel * 0.5))
      }
      if (!springSettled(elapsed, SPRING.snappy)) return true
      flyer.remove()
      resolve()
      return false
    }
    cancel = bindFrame('page:turn:' + crypto.randomUUID(), tick)
  })
  return Object.assign(promise, { cancel: () => { cancel(); flyer.remove(); settle() } })
}

type WoodRect = { x: number; y: number; width: number; height: number; rot: number }

export function glideWood(el: HTMLElement, from: WoodRect, to: WoodRect, _ms = 380) {
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
      const elapsed = now - started
      const p = springAt(elapsed, SPRING.snappy)
      const clamped = Math.min(1, Math.max(0, p))
      // Smooth arc with gentle landing slope (sin^1.3 avoids sharp derivative kink on touchdown).
      const arc = Math.pow(Math.sin(Math.PI * clamped), 1.3) * 82
      const x = lerp(from.x, to.x, p)
      const y = lerp(from.y, to.y, p) - arc
      const scale = lerp(1, to.width / Math.max(1, from.width), clamped)
      const dx = x - from.x
      const dy = y - from.y
      el.style.transform = `translate3d(${from.x - from.width / 2 + dx}px, ${from.y - from.height / 2 + dy}px, 0) scale(${scale}) rotate(${lerp(from.rot, to.rot, p)}deg)`
      if (!springSettled(elapsed, SPRING.snappy)) return true
      parkWood(el, to)
      el.classList.remove('wood-flight')
      resolve()
      return false
    }
    cancel = bindFrame('wood:' + (el.dataset.id || 'log'), tick)
  })
  return Object.assign(promise, { cancel: () => { cancel(); settle() } })
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

/** Pure-GPU paper arrival flight (zero per-frame width/height reflow); landing draw & removal happen in one frame. */
export function flyProcessPaper(from: DOMRect, target: () => PaperProcessHandle | null, key: string, onLand: () => void) {
  const sheet = document.createElement('canvas')
  sheet.width = 380; sheet.height = 520; sheet.className = 'process-paper-flight'
  sheet.dataset.paperKey = key; sheet.setAttribute('aria-hidden', 'true')
  const c = sheet.getContext('2d')!
  const shade = castShadow(); document.body.append(sheet, shade)
  const baseW = Math.max(1, from.width)
  const baseH = Math.max(1, from.height)
  pin(sheet, from.left, from.top, baseW, baseH)
  sheet.style.transformOrigin = '0 0'
  let stop = () => {}, settle = (_landed: boolean) => {}, done = false
  let elapsed = 0, last = performance.now(), end = reducedMotion() ? 120 : 500
  let start = 0, origin: PaperPose = { x: from.left, y: from.top, width: from.width, height: from.height }
  let current = origin, previousTarget: PaperPose | null = null
  const finish = (landed: boolean) => {
    if (done) return
    done = true
    if (landed) onLand()
    sheet.remove(); shade.remove(); settle(landed)
  }
  const promise = new Promise<boolean>(resolve => {
    settle = resolve
    stop = bindFrame('arrival:' + key, now => {
      const dt = Math.min(40, now - last); last = now
      if (document.hidden) return true
      const handle = target(), dest = handle?.pose()
      if (!handle || handle.key !== key || !dest) { finish(false); return false }
      elapsed += dt
      if (previousTarget && Math.abs(dest.x - previousTarget.x) + Math.abs(dest.y - previousTarget.y) + Math.abs(dest.width - previousTarget.width) > 2) {
        origin = current; start = elapsed; end = Math.max(end, elapsed + 120)
      }
      previousTarget = dest
      const t = Math.min(1, (elapsed - start) / Math.max(1, end - start))
      const e = easeOutCubic(t)
      const gentle = reducedMotion()
      const arc = Math.sin(Math.PI * t)
      current = gentle ? dest : {
        x: lerp(origin.x, dest.x, e),
        y: lerp(origin.y, dest.y, e) - arc * arc * Math.min(34, (end - start) * 0.065),
        width: lerp(origin.width, dest.width, e),
        height: lerp(origin.height, dest.height, e),
      }
      const settlePose = Math.min(1, Math.max(0, (end - elapsed) / 110))
      const rot = gentle ? 0 : Math.sin(t * Math.PI) * -6 * settlePose
      const sx = current.width / baseW
      const sy = current.height / baseH
      // Keep transform centered around the scaled rect when rotating, exact 0-deg alignment on landing frame.
      sheet.style.transform = rot === 0
        ? `translate3d(${current.x}px, ${current.y}px, 0) scale(${sx}, ${sy})`
        : `translate3d(${current.x + current.width / 2}px, ${current.y + current.height / 2}px, 0) rotate(${rot}deg) translate3d(${-current.width / 2}px, ${-current.height / 2}px, 0) scale(${sx}, ${sy})`
      sheet.style.opacity = gentle ? String(Math.min(1, elapsed / 90)) : '1'
      c.clearRect(0, 0, 380, 520)
      const face = handle.surface(), bend = gentle ? 0 : Math.sin(t * Math.PI) * 6 * settlePose
      for (let y = 0; y < 520; y += 10) {
        const h = Math.min(10, 520 - y)
        c.drawImage(face, 0, y, 380, h, Math.sin(y / 520 * Math.PI) * bend, y, 380 - Math.abs(bend), h)
      }
      shade.style.opacity = String(0.15 * Math.sin(t * Math.PI))
      shade.style.transform = `translate3d(${current.x + current.width * 0.3}px,${current.y + current.height + 8}px,0) scale(${current.width / 100},.55)`
      if (t < 1) return true
      // Consumer paints the full, identical sheet before this canvas is removed.
      handle.land(); finish(true); return false
    })
  })
  return Object.assign(promise, { cancel: () => { stop(); finish(false) } })
}

/** Each request owns its paper, shadow and completion, including cancellation. Zero per-frame layout reads. */
export function flyTrashSheets(from: { rect: DOMRect; title: string }[], target: () => HTMLElement | null) {
  if (reducedMotion() || !from.length) return Object.assign(Promise.resolve(), { cancel: () => {} })
  const initialBin = target()
  const manifest = currentManifest()
  let cachedBinBox = initialBin?.getBoundingClientRect() || null
  let cachedHole = initialBin ? mouthOf(initialBin, manifest, cachedBinBox || undefined) : null
  if (!initialBin || !cachedHole || !cachedBinBox) return Object.assign(Promise.resolve(), { cancel: () => {} })

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
  const onResize = () => {
    const bin = target()
    if (!bin) return
    cachedBinBox = bin.getBoundingClientRect()
    cachedHole = mouthOf(bin, manifest, cachedBinBox)
  }
  window.addEventListener('resize', onResize)
  const started = performance.now()
  let cancel = () => {}
  let settle = () => {}
  let done = false
  const clear = () => {
    if (done) return
    done = true
    window.removeEventListener('resize', onResize)
    nodes.forEach(node => { node.el.remove(); node.shadow.remove() })
    settle()
  }
  const promise = new Promise<void>(resolve => {
    settle = resolve
    cancel = bindFrame('trash:' + id, now => {
      const bin = target()
      const hole = cachedHole
      const binBox = cachedBinBox
      if (!bin || !hole || !binBox || !bin.isConnected || bin.closest('[inert]')) { clear(); return false }
      let live = false
      nodes.forEach((node, index) => {
        const elapsed = now - started - index * 80
        if (elapsed < 0) { node.el.style.opacity = '0'; live = true; return }
        const ball = easeOutCubic(Math.min(1, elapsed / 240))
        const t = easeOutCubic(Math.min(1, Math.max(0, (elapsed - 130) / 540)))
        const x = lerp(node.x, hole.x, t)
        const y = lerp(node.y, hole.y + 14, t) - Math.sin(Math.PI * t) * 86
        const sx = lerp(1, 25 / node.w, ball), sy = lerp(1, 25 / node.h, ball)
        node.el.style.setProperty('--crumple', String(ball))
        node.el.style.borderRadius = `${ball * 46}%`
        let px = x, py = y
        if (t > 0.72) {
          // The actual foreground texture covers the ball as it crosses the rim.
          if (node.el.parentElement !== bin) bin.insertBefore(node.el, bin.querySelector('.trash-front'))
          px -= binBox.left; py -= binBox.top
          node.el.style.position = 'absolute'; node.el.style.zIndex = '2'
          bin.classList.add('is-fed')
        }
        node.el.style.transform = `translate3d(${px - node.w / 2}px, ${py - node.h / 2}px, 0) rotate(${ball * 28 + t * 250 + Math.sin(t * 16) * 6}deg) scale(${sx},${sy})`
        node.el.style.opacity = t >= 1 ? '0' : '1'
        node.shadow.style.transform = `translate3d(${x - 22}px, ${lerp(node.y, hole.y + 24, t)}px, 0) scale(${1 - Math.sin(Math.PI * t) * 0.55}, .4)`
        node.shadow.style.opacity = String(0.22 * (1 - ramp(t, 0.84, 1)))
        live ||= elapsed < 720
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
  const destRect = pile()?.getBoundingClientRect() || null
  rows.slice(0, 3).forEach((row, index) => {
    const el = document.createElement('div')
    el.className = 'tear-sheet' + (rows.length > 3 && index === 2 ? ' is-stack' : '')
    el.textContent = row.text
    document.body.append(el)
    const w = row.rect.width
    const h = Math.max(28, row.rect.height)
    pin(el, row.rect.left, row.rect.top, w, h)
    const started = performance.now() + index * 38
    bindFrame('tear:' + crypto.randomUUID(), now => {
      if (pile()?.closest('[inert]')) { el.remove(); return false }
      const elapsed = now - started
      if (elapsed < 0) return true
      const dest = destRect || pile()?.getBoundingClientRect()
      const p = springAt(elapsed, SPRING.snappy)
      const x = dest ? lerp(row.rect.left, dest.left, Math.min(1.04, p)) : row.rect.left
      const y = dest ? lerp(row.rect.top, dest.top + 24, Math.min(1.04, p)) : row.rect.top + 70 * Math.min(1, p)
      el.style.transform = `translate3d(${x}px, ${y}px, 0) rotate(${lerp(-6, 2, Math.min(1, p))}deg)`
      el.style.opacity = String(elapsed < 28 ? 0 : 1 - ramp(Math.min(1, p), 0.80, 1))
      if (!springSettled(Math.max(0, elapsed), SPRING.snappy)) return true
      el.remove()
      return false
    })
  })
}

export function mouthOf(host: HTMLElement, manifest: WorkbenchManifest, rect?: DOMRect) {
  const anchors = manifest.trash?.anchors
  if (!anchors) return null
  const hostBox = rect || host.getBoundingClientRect()
  const center = anchorPixels(hostBox, anchors.mouthCenter, manifest.trash?.size)
  const box = normBox(hostBox, anchors.mouth, manifest.trash?.size)
  return { x: center.x, y: center.y, width: box.width, height: box.height, left: box.left, top: box.top }
}
