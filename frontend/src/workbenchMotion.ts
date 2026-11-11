import { anchorPixels, atlasPosition, currentManifest, easeOut, foldPaperTarget, lerp, normBox, type WorkbenchManifest } from './workbenchAnchors'
import { bindFrame } from './workbenchScheduler'

const srcOf = (base: string, name: string) => `${base}workbench/${name}.webp`
const reducedMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches

export const DELIVERY_PHASES = [
  { id: 'fold', ms: 550 },
  { id: 'tuck', ms: 300 },
  { id: 'seal', ms: 350 },
  { id: 'insert', ms: 450 },
  { id: 'route', ms: 400 },
] as const

export type DeliveryPhase = (typeof DELIVERY_PHASES)[number]['id']

function phaseAt(ms: number) {
  let cursor = ms
  for (const phase of DELIVERY_PHASES) {
    if (cursor <= phase.ms) return { phase: phase.id, local: phase.ms ? cursor / phase.ms : 1 }
    cursor -= phase.ms
  }
  return { phase: 'route' as const, local: 1 }
}

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
}

type Point = { x: number; y: number }

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

/** Fold the edited sheet, tuck it, seal, then carry the envelope into the slot and out to the sidebar. */
export function playDelivery(nodes: DeliveryNodes, manifest: WorkbenchManifest, base: string, onPhase: (phase: DeliveryPhase) => void, onDone?: () => void) {
  if (reducedMotion()) { onDone?.(); return () => {} }
  let stopped = false
  const started = performance.now()
  let announced = ''
  const homeRect = nodes.sheet?.getBoundingClientRect()
  const lines = nodes.lines?.length ? nodes.lines : [...(nodes.sheet?.querySelectorAll('input') || [])].map(node => (node as HTMLInputElement).value).filter(Boolean)
  const shell = nodes.root.closest('.workbench-shell')
  const lane = nodes.root.classList.contains('notes') ? 'notes' : 'publish'
  const flight = document.createElement('div')
  flight.className = 'fold-sheet'
  flight.dataset.lane = lane
  flight.setAttribute('aria-hidden', 'true')
  const face = ruledSheet(lines.slice(0, 7), homeRect?.width || 400, homeRect?.height || 220)
  flight.append(face)
  document.body.append(flight)
  let route: HTMLElement | null = null
  let from = homeRect ? { x: homeRect.left, y: homeRect.top, w: homeRect.width, h: homeRect.height } : null
  let phaseMark = ''
  let phaseFrom = from
  const restW = nodes.env.offsetWidth
  const restH = nodes.env.offsetHeight
  const tick = (now: number) => {
    if (stopped) return false
    const ms = Math.min(DELIVERY_MS, now - started)
    const { phase, local } = phaseAt(ms)
    if (phase !== announced) { announced = phase; onPhase(phase) }
    if (phase !== phaseMark) { phaseMark = phase; phaseFrom = from }
    const eased = easeOut(local)
    const envBox = nodes.env.getBoundingClientRect()
    const mail = nodes.mail.getBoundingClientRect()
    const stage = nodes.root.getBoundingClientRect()
    const pocket = manifest.envelope.anchors.pocket
    const imageW = mail.width
    const slot = manifest.mailbox.anchors.slotFront
    const exit = manifest.mailbox.anchors.exit
    const pocketBox = pocket && envBox.width > 2 ? {
      x: envBox.left + pocket[0] * envBox.width,
      y: envBox.top + pocket[1] * envBox.height,
      w: pocket[2] * envBox.width,
      h: pocket[3] * envBox.height,
    } : null
    const sheetW = homeRect?.width || 400
    const sheetH = homeRect?.height || 220
    const foldedH = Math.max(72, sheetH / 3)
    if (phase === 'fold' || phase === 'tuck') {
      const origin = phaseFrom || { x: homeRect?.left || envBox.left, y: homeRect?.top || envBox.top, w: sheetW, h: sheetH }
      const sideGap = pocketBox ? Math.max(6, (pocketBox.w - sheetW) / 2) : 6
      const dest = pocketBox
        ? { x: pocketBox.x + sideGap, y: pocketBox.y + 8, w: sheetW, h: foldedH }
        : { x: envBox.left, y: envBox.top + envBox.height * 0.45, w: sheetW, h: foldedH }
      const foldT = phase === 'fold' ? eased : 1
      const tuckT = phase === 'tuck' ? eased : 0
      const pose = {
        x: lerp(origin.x, dest.x, tuckT),
        y: lerp(origin.y - foldT * 16, dest.y, tuckT),
        w: sheetW,
        h: lerp(sheetH, foldedH, foldT),
      }
      from = pose
      flight.style.left = pose.x + 'px'
      flight.style.top = pose.y + 'px'
      flight.style.width = pose.w + 'px'
      flight.style.height = pose.h + 'px'
      flight.style.transform = `perspective(800px) rotateX(${foldT * 62}deg)`
      flight.style.opacity = '1'
      flight.style.zIndex = tuckT > 0.72 ? '3' : '30'
      const target = foldPaperTarget({ left: 0, top: 0, width: nodes.env.offsetWidth, height: nodes.env.offsetHeight }, manifest, foldT, tuckT)
      const fold = manifest['paper-fold']
      if (target && fold) {
        const pos = atlasPosition(target.frame, fold.columns, fold.rows)
        nodes.paper.style.visibility = 'visible'
        nodes.paper.style.backgroundImage = `url(${srcOf(base, 'paper-fold-light-atlas')})`
        nodes.paper.style.backgroundSize = `${fold.columns * 100}% ${fold.rows * 100}%`
        nodes.paper.style.backgroundPosition = `${pos.x}% ${pos.y}%`
        nodes.paper.style.opacity = phase === 'tuck' ? String(Math.min(1, eased * 1.15)) : '0'
      }
      nodes.flap.style.transform = 'rotateX(0deg)'
      nodes.closed.style.opacity = '0'
      nodes.wax.style.transform = 'translate(-50%, -50%)'
    } else flight.style.opacity = '0'
    if (phase === 'seal' || phase === 'insert' || phase === 'route') {
      const seal = phase === 'seal' ? eased : 1
      const angle = Math.min(180, seal / 0.82 * 180)
      nodes.flap.style.transform = `rotateX(${angle}deg)`
      nodes.closed.style.opacity = String(seal < 0.82 ? 0 : (seal - 0.82) / 0.18)
      nodes.wax.style.left = ''
      nodes.wax.style.top = ''
      nodes.wax.style.transform = `translate(-50%, -50%) translateY(${(1 - seal) * -4}px)`
    }
    if ((phase === 'insert' || phase === 'route') && slot && mail.width > 2) {
      const slotCenter = { x: mail.left + (slot[0] + slot[2] / 2) * mail.width, y: mail.top + (slot[1] + slot[3] / 2) * mail.height }
      const home = nodes.env.dataset.home ? JSON.parse(nodes.env.dataset.home) as Point : { x: envBox.left + envBox.width / 2, y: envBox.top + envBox.height / 2 }
      const visible = manifest.envelope.visible_bounds
      const visibleW = visible ? (visible[2] - visible[0]) : 0.84
      const endScale = (slot[2] * imageW) / Math.max(1, visibleW * restW)
      let center = slotCenter
      let scale = endScale
      let clip = 72
      if (phase === 'insert') {
        const travel = Math.min(1, eased / 0.8)
        center = { x: lerp(home.x, slotCenter.x, travel), y: lerp(home.y, slotCenter.y, travel) }
        scale = lerp(1, endScale, Math.max(0, (eased - 0.4) / 0.6))
        clip = eased < 0.82 ? 0 : ((eased - 0.82) / 0.18) * 72
      }
      const width = restW * scale
      const height = restH * scale
      nodes.env.style.position = 'absolute'
      nodes.env.style.margin = '0'
      nodes.env.style.left = (center.x - stage.left - width / 2) + 'px'
      nodes.env.style.top = (center.y - stage.top - height / 2) + 'px'
      nodes.env.style.width = width + 'px'
      nodes.env.style.height = height + 'px'
      nodes.env.style.transform = 'none'
      nodes.env.style.clipPath = clip > 0 ? `inset(${clip}% 0 0 0)` : ''
      if (phase === 'route' && exit) {
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
        }
        const exitPoint = { x: mail.left + exit[0] * mail.width, y: mail.top + exit[1] * mail.height }
        const side = shell?.querySelector(`[data-mail-slot="${lane}"]`)?.getBoundingClientRect()
        const dest = side && side.width > 2 ? { x: side.left + side.width / 2, y: side.top + side.height / 2 } : { x: exitPoint.x - 80, y: exitPoint.y }
        const x = lerp(exitPoint.x, dest.x, eased)
        const y = lerp(exitPoint.y, dest.y, eased) - Math.sin(Math.PI * eased) * 18
        route.style.left = (x - 18) + 'px'
        route.style.top = (y - 12) + 'px'
        route.style.width = '36px'
        route.style.height = '24px'
      }
    }
    if (ms < DELIVERY_MS) return true
    flight.remove()
    route?.remove()
    onDone?.()
    return false
  }
  const cancel = bindFrame('delivery:' + lane + ':send', tick)
  return () => { stopped = true; cancel(); flight.remove(); route?.remove() }
}

export function resetDelivery(env: HTMLElement, flap: HTMLElement, paper: HTMLElement, closed: HTMLElement, wax: HTMLElement) {
  env.style.position = ''
  env.style.margin = ''
  env.style.left = ''
  env.style.top = ''
  env.style.width = ''
  env.style.height = ''
  env.style.transform = ''
  env.style.clipPath = ''
  flap.style.transform = ''
  paper.style.display = ''
  paper.style.visibility = 'hidden'
  paper.style.opacity = ''
  closed.style.opacity = ''
  wax.style.opacity = ''
  wax.style.left = ''
  wax.style.top = ''
  wax.style.transform = ''
  const lane = env.closest('.letter-station')?.classList.contains('notes') ? 'notes' : 'publish'
  document.querySelectorAll('.fold-sheet,.routing-letter').forEach(node => {
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
  flyer.append(face, curl, back)
  back.style.opacity = '0'
  flyer.style.left = sheet.left + 'px'
  flyer.style.top = sheet.top + 'px'
  flyer.style.width = sheet.width + 'px'
  flyer.style.height = sheet.height + 'px'
  document.body.append(flyer)
  const atlas = currentManifest()['paper-turn']
  const ms = 440
  const started = performance.now()
  let cancel = () => {}
  const promise = new Promise<void>(resolve => {
    const tick = (now: number) => {
      const t = Math.min(1, (now - started) / ms)
      const eased = easeOut(t)
      flyer.style.width = sheet.width + 'px'
      flyer.style.height = sheet.height + 'px'
      if (atlas) {
        const frame = Math.min(atlas.frames - 1, Math.floor(eased * (atlas.frames - 1)))
        const pos = atlasPosition(frame, atlas.columns, atlas.rows)
        const atlasName = (atlas.atlas || 'paper-turn-light-atlas.webp').replace(/\.webp$/, '')
        curl.style.backgroundImage = `url(${srcOf(import.meta.env.BASE_URL, atlasName)})`
        curl.style.backgroundSize = `${atlas.columns * 100}% ${atlas.rows * 100}%`
        curl.style.backgroundPosition = `${pos.x}% ${pos.y}%`
      }
      if (dir === 'next') {
        const x = sheet.left + (1 - eased) * Math.min(72, sheet.width * 0.28)
        const y = sheet.top + (1 - eased) * Math.min(64, sheet.height * 0.36)
        flyer.style.left = x + 'px'
        flyer.style.top = y + 'px'
        flyer.style.transform = `rotate(${(1 - eased) * 7}deg)`
        flyer.style.boxShadow = `0 ${8 + (1 - eased) * 14}px 16px rgba(24,40,48,${0.08 + (1 - eased) * 0.1})`
        back.style.opacity = '0'
        curl.style.opacity = String(0.35 * (1 - eased))
      } else {
        flyer.style.left = sheet.left + 'px'
        flyer.style.top = sheet.top + 'px'
        const peel = eased
        face.style.clipPath = `polygon(${peel * 78}% 0, 100% 0, 100% 100%, 0 100%, 0 ${peel * 78}%)`
        const size = Math.max(36, peel * Math.min(sheet.width, sheet.height) * 0.72)
        back.style.left = '0'
        back.style.top = '0'
        back.style.width = size + 'px'
        back.style.height = size + 'px'
        back.style.opacity = String(Math.min(1, peel * 1.2))
        back.style.boxShadow = '6px 8px 12px rgba(24,40,48,.18)'
        curl.style.opacity = String(Math.min(1, peel))
        flyer.style.boxShadow = `${4 + peel * 10}px ${4 + peel * 6}px 14px rgba(24,40,48,${0.12 * (1 - peel * 0.4)})`
      }
      if (t < 1) return true
      flyer.remove()
      resolve()
      return false
    }
    cancel = bindFrame('page:turn', tick)
  })
  return Object.assign(promise, { cancel: () => { cancel(); flyer.remove() } })
}

type WoodRect = { x: number; y: number; width: number; height: number; rot: number }

export function glideWood(el: HTMLElement, from: WoodRect, to: WoodRect, ms = 450) {
  el.classList.add('wood-flight')
  if (reducedMotion()) {
    parkWood(el, to)
    el.classList.remove('wood-flight')
    return Promise.resolve()
  }
  const started = performance.now()
  let cancel = () => {}
  const promise = new Promise<void>(resolve => {
    const tick = (now: number) => {
      const t = Math.min(1, (now - started) / ms)
      const eased = easeOut(Math.min(1, t / 0.86))
      const lift = Math.sin(Math.PI * Math.min(1, t / 0.7)) * (t < 0.84 ? 34 : 34 * (1 - t) / 0.16)
      const x = lerp(from.x, to.x, eased)
      const y = lerp(from.y, to.y, eased) - lift
      const width = lerp(from.width, to.width, eased)
      const height = lerp(from.height, to.height, eased)
      el.style.position = 'fixed'
      el.style.left = (x - width / 2) + 'px'
      el.style.top = (y - height / 2) + 'px'
      el.style.width = width + 'px'
      el.style.height = height + 'px'
      el.style.margin = '0'
      el.style.transform = `rotate(${lerp(from.rot, to.rot, eased)}deg)`
      el.style.zIndex = t > 0.68 ? '2' : '30'
      if (t < 1) return true
      parkWood(el, to)
      el.classList.remove('wood-flight')
      resolve()
      return false
    }
    cancel = bindFrame('wood:' + (el.dataset.id || Math.random().toString(36).slice(2)), tick)
  })
  return Object.assign(promise, { cancel })
}

function parkWood(el: HTMLElement, to: WoodRect) {
  el.style.position = 'fixed'
  el.style.left = (to.x - to.width / 2) + 'px'
  el.style.top = (to.y - to.height / 2) + 'px'
  el.style.width = to.width + 'px'
  el.style.height = to.height + 'px'
  el.style.transform = `rotate(${to.rot}deg)`
  el.style.zIndex = '2'
}

export function flyTaskPaper(from: DOMRect, to: () => Point | null, title: string, key = 'task') {
  if (from.width < 2) return Object.assign(Promise.resolve(), { cancel: () => {} })
  const card = document.createElement('div')
  card.className = 'task-paper-flight'
  card.setAttribute('aria-hidden', 'true')
  card.textContent = title
  document.body.append(card)
  const started = { t: performance.now() }
  let sx = from.left + from.width / 2
  let sy = from.top + from.height / 2
  let prev: Point | null = null
  let cancel = () => {}
  const promise = new Promise<void>(resolve => {
    const tick = (now: number) => {
      const dest = to()
      if (!dest) { card.remove(); resolve(); return false }
      if (prev && Math.hypot(dest.x - prev.x, dest.y - prev.y) > 12) {
        const current = card.getBoundingClientRect()
        sx = current.left + current.width / 2
        sy = current.top + current.height / 2
        started.t = now
      }
      prev = dest
      const t = Math.min(1, (now - started.t) / 460)
      const eased = easeOut(t)
      const x = lerp(sx, dest.x, eased)
      const y = lerp(sy, dest.y, eased) - Math.sin(Math.PI * eased) * 28
      const width = lerp(Math.max(from.width, 88), 168, Math.min(1, eased * 1.4))
      const height = lerp(Math.max(from.height, 36), 220, Math.min(1, eased * 1.4))
      card.style.left = (x - width / 2) + 'px'
      card.style.top = (y - height / 2) + 'px'
      card.style.width = width + 'px'
      card.style.height = height + 'px'
      if (t < 1) return true
      card.remove()
      resolve()
      return false
    }
    cancel = bindFrame('arrive:' + key, tick)
  })
  return Object.assign(promise, { cancel: () => { cancel(); card.remove() } })
}

export function flyTrashSheets(from: { rect: DOMRect; title: string }[], mouth: () => { x: number; y: number; width: number; height: number } | null) {
  if (reducedMotion() || !from.length) return Object.assign(Promise.resolve(), { cancel: () => {} })
  const shown = from.slice(0, 3)
  const stack = from.length > 3
  const nodes = shown.map((item, index) => {
    const el = document.createElement('div')
    el.className = 'trash-sheet' + (stack && index === shown.length - 1 ? ' is-stack' : '')
    el.setAttribute('aria-hidden', 'true')
    el.textContent = item.title
    document.body.append(el)
    return { el, rect: item.rect, x: item.rect.left, y: item.rect.top }
  })
  const total = 720
  const started = { t: performance.now() }
  let prev: { x: number; y: number } | null = null
  let cancel = () => {}
  const promise = new Promise<void>(resolve => {
    const tick = (now: number) => {
      const hole = mouth()
      if (!hole) { nodes.forEach(node => node.el.remove()); resolve(); return false }
      if (prev && Math.hypot(hole.x - prev.x, hole.y - prev.y) > 12) {
        nodes.forEach(node => {
          const box = node.el.getBoundingClientRect()
          node.x = box.left
          node.y = box.top
        })
        started.t = now
      }
      prev = hole
      const t = Math.min(1, (now - started.t) / total)
      nodes.forEach((node, index) => {
        const lift = t < 120 / total ? t / (120 / total) : 1
        const travel = t < 120 / total ? 0 : t < 540 / total ? (t - 120 / total) / ((540 - 120) / total) : 1
        const sink = t < 540 / total ? 0 : (t - 540 / total) / (180 / total)
        const eased = easeOut(travel)
        const width = Math.max(node.rect.width, 96)
        const height = Math.max(node.rect.height, 72)
        const x = lerp(node.x, hole.x - width / 2, eased) + index * 8
        const y = lerp(node.y - lift * 12, hole.y - height * 0.2, eased) + sink * (hole.height * 0.65)
        node.el.style.left = x + 'px'
        node.el.style.top = y + 'px'
        node.el.style.width = width + 'px'
        node.el.style.height = height + 'px'
        node.el.style.boxShadow = lift > 0 ? '0 10px 16px rgba(24,40,48,.18)' : ''
        node.el.style.transform = `perspective(500px) rotateX(${sink * 22}deg)`
        node.el.style.clipPath = sink > 0 ? `inset(${sink * 100}% 0 0 0)` : ''
        node.el.style.zIndex = sink > 0.2 ? '2' : '40'
      })
      if (t < 1) return true
      nodes.forEach(node => node.el.remove())
      resolve()
      return false
    }
    cancel = bindFrame('trash', tick)
  })
  return Object.assign(promise, { cancel: () => { cancel(); nodes.forEach(node => node.el.remove()) } })
}

export function launchTear(rows: { text: string; rect: DOMRect }[], pile: () => HTMLElement | null) {
  if (reducedMotion()) return
  rows.slice(0, 3).forEach((row, index) => {
    const el = document.createElement('div')
    el.className = 'tear-sheet' + (rows.length > 3 && index === 2 ? ' is-stack' : '')
    el.textContent = row.text
    el.style.width = row.rect.width + 'px'
    el.style.height = Math.max(28, row.rect.height) + 'px'
    document.body.append(el)
    const started = performance.now() + index * 40
    bindFrame('tear:' + index, now => {
      const raw = (now - started) / 420
      const t = Math.min(1, Math.max(0, raw))
      const dest = pile()?.getBoundingClientRect()
      const x = dest ? lerp(row.rect.left, dest.left, easeOut(t)) : row.rect.left
      const y = dest ? lerp(row.rect.top, dest.top + 24, easeOut(t)) : row.rect.top + 70 * t
      el.style.left = x + 'px'
      el.style.top = y + 'px'
      el.style.opacity = raw < 0 ? '0' : '1'
      if (raw < 1) return true
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
