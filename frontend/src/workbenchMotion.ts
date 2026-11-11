import { anchorPixels, atlasPosition, currentManifest, foldPaperTarget, normBox, type WorkbenchManifest } from './workbenchAnchors'
import { bindFrame } from './workbenchScheduler'
import { lerp, ramp, springAt, springSettled, SPRING } from './motionSystem'

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

function phaseOf(u: number): DeliveryPhase {
  if (u < 0.22) return 'fold'
  if (u < 0.42) return 'tuck'
  if (u < 0.6) return 'seal'
  if (u < 0.8) return 'insert'
  return 'route'
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

/** Fold, tuck, seal, insert, and route as one continuous gesture. */
export function playDelivery(nodes: DeliveryNodes, manifest: WorkbenchManifest, base: string, onPhase: (phase: DeliveryPhase) => void, onDone?: () => void) {
  if (reducedMotion()) { onDone?.(); return () => {} }
  let stopped = false
  const started = performance.now()
  let announced = ''
  const homeRect = nodes.sheet?.getBoundingClientRect()
  const lines = nodes.lines?.length ? nodes.lines : [...(nodes.sheet?.querySelectorAll('input') || [])].map(node => (node as HTMLInputElement).value).filter(Boolean)
  const shell = nodes.root.closest('.workbench-shell')
  const lane = nodes.root.classList.contains('notes') ? 'notes' : 'publish'
  const sheetW = homeRect?.width || 400
  const sheetH = homeRect?.height || 220
  const foldedH = Math.max(72, sheetH / 3)
  const flight = document.createElement('div')
  flight.className = 'fold-sheet'
  flight.dataset.lane = lane
  flight.setAttribute('aria-hidden', 'true')
  const face = ruledSheet(lines.slice(0, 7), sheetW, sheetH)
  const bend = document.createElement('div')
  bend.className = 'fold-bend'
  const crease = document.createElement('div')
  crease.className = 'fold-crease'
  flight.append(face, bend, crease)
  document.body.append(flight)
  const originX = homeRect?.left || 0
  const originY = homeRect?.top || 0
  pin(flight, originX, originY, sheetW, sheetH)
  flight.style.transformOrigin = '50% 0%'
  let route: HTMLElement | null = null
  const restW = nodes.env.offsetWidth
  const restH = nodes.env.offsetHeight
  const home = nodes.env.dataset.home
    ? JSON.parse(nodes.env.dataset.home) as Point
    : { x: originX, y: originY }
  const tick = (now: number) => {
    if (stopped) return false
    const u = Math.min(1, (now - started) / DELIVERY_MS)
    const phase = phaseOf(u)
    if (phase !== announced) { announced = phase; onPhase(phase) }
    const foldT = ramp(u, 0, 0.36)
    const tuckT = ramp(u, 0.2, 0.5)
    const sealT = ramp(u, 0.38, 0.66)
    const insertT = ramp(u, 0.56, 0.88)
    const envBox = nodes.env.getBoundingClientRect()
    const mail = nodes.mail.getBoundingClientRect()
    const pocket = manifest.envelope.anchors.pocket
    const pocketBox = pocket && envBox.width > 2 ? {
      x: envBox.left + pocket[0] * envBox.width,
      y: envBox.top + pocket[1] * envBox.height,
      w: pocket[2] * envBox.width,
      h: pocket[3] * envBox.height,
    } : null
    const sideGap = pocketBox ? Math.max(6, (pocketBox.w - sheetW) / 2) : 6
    const destX = pocketBox ? pocketBox.x + sideGap : envBox.left
    const destY = pocketBox ? pocketBox.y + 8 : envBox.top + envBox.height * 0.45
    const x = lerp(originX, destX, tuckT)
    const y = lerp(originY, destY, tuckT) - foldT * (1 - tuckT) * 14
    const scaleY = lerp(1, foldedH / sheetH, foldT)
    const lift = foldT * (1 - tuckT) * 26
    flight.style.transformOrigin = '50% 0%'
    flight.style.transform = `perspective(1100px) translate3d(${x}px, ${y - lift}px, 0) rotateX(${foldT * 74}deg) scaleY(${scaleY})`
    crease.style.opacity = String(Math.min(1, foldT * 1.4) * (1 - tuckT))
    crease.style.transform = `scaleX(${0.4 + foldT * 0.6})`
    flight.style.opacity = String(1 - ramp(u, 0.42, 0.56))
    const bendAtlas = manifest['paper-bend']
    if (bendAtlas) {
      const frame = Math.min(bendAtlas.frames - 1, Math.round(foldT * (bendAtlas.frames - 1)))
      const pos = atlasPosition(frame, bendAtlas.columns, bendAtlas.rows)
      const atlasName = (bendAtlas.atlas || 'paper-bend-light-atlas.webp').replace(/\.webp$/, '')
      bend.style.backgroundImage = `url(${srcOf(base, atlasName)})`
      bend.style.backgroundSize = `${bendAtlas.columns * 100}% ${bendAtlas.rows * 100}%`
      bend.style.backgroundPosition = `${pos.x}% ${pos.y}%`
      bend.style.opacity = String(Math.min(1, foldT * 1.2) * (1 - ramp(u, 0.4, 0.52)))
    }
    const target = foldPaperTarget({ left: 0, top: 0, width: nodes.env.offsetWidth, height: nodes.env.offsetHeight }, manifest, foldT, tuckT)
    const fold = manifest['paper-fold']
    if (target && fold) {
      const pos = atlasPosition(target.frame, fold.columns, fold.rows)
      nodes.paper.style.visibility = 'visible'
      nodes.paper.style.backgroundImage = `url(${srcOf(base, 'paper-fold-light-atlas')})`
      nodes.paper.style.backgroundSize = `${fold.columns * 100}% ${fold.rows * 100}%`
      nodes.paper.style.backgroundPosition = `${pos.x}% ${pos.y}%`
      nodes.paper.style.opacity = String(ramp(u, 0.28, 0.48))
    }
    nodes.flap.style.transform = `rotateX(${sealT * 180}deg)`
    nodes.closed.style.opacity = String(ramp(u, 0.5, 0.68))
    nodes.wax.style.transform = `translate(-50%, -50%) translateY(${(1 - sealT) * -6}px) scale(${lerp(1.05, 1, sealT)})`
    if (insertT > 0 && mail.width > 2) {
      const slot = manifest.mailbox.anchors.slotFront
      if (slot) {
        const mouth = normBox(mail, slot, manifest.mailbox.size)
        const slotCenter = { x: mouth.left + mouth.width / 2, y: mouth.top + mouth.height * 0.55 }
        const visible = manifest.envelope.visible_bounds
        const visibleW = visible ? (visible[2] - visible[0]) : 0.84
        const endScale = Math.min(0.28, (mouth.width * 0.9) / Math.max(1, visibleW * restW))
        const bow = Math.sin(Math.PI * insertT) * 28
        const center = { x: lerp(home.x, slotCenter.x, insertT), y: lerp(home.y, slotCenter.y, insertT) - bow }
        const scale = lerp(1, endScale, insertT)
        nodes.env.style.zIndex = '2'
        nodes.env.style.transformOrigin = 'center center'
        nodes.env.style.transform = `translate3d(${center.x - home.x}px, ${center.y - home.y}px, 0) scale(${scale})`
        nodes.env.style.clipPath = ''
        nodes.env.style.opacity = String(1 - ramp(u, 0.9, 1))
        const exit = manifest.mailbox.anchors.exit
        if (u > 0.74 && exit) {
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
          const local = Math.min(1, (u - 0.74) / 0.26)
          const p = springAt(local * 640, SPRING.mass)
          const into = Math.max(0, (p - 0.55) / 0.45)
          if (side && into > 0.02 && route.parentElement !== side) side.append(route)
          if (route.parentElement === side && sideBox) {
            route.style.position = 'absolute'
            route.style.left = '0'
            route.style.top = '0'
            route.style.width = '34px'
            route.style.height = '18px'
            route.style.margin = '0'
            route.style.transformOrigin = 'center top'
            route.style.transform = `translate3d(${sideBox.width / 2 - 17}px, ${lerp(4, -20, into)}px, 0) scale(${lerp(0.85, 0.55, into)})`
            route.style.opacity = '1'
          } else {
            const arc = p > 0 && p < 1 ? Math.sin(Math.PI * Math.min(1, p)) * 34 : 0
            const rx = lerp(exitPoint.x, dest.x, Math.min(1, p)) - 18
            const ry = lerp(exitPoint.y, dest.y, Math.min(1, p)) - 12 - arc
            route.style.transform = `translate3d(${rx}px, ${ry}px, 0) rotate(${lerp(-6, 2, Math.min(1, p))}deg)`
            route.style.opacity = '1'
          }
        }
      }
    }
    if (u < 1) return true
    flight.remove()
    route?.remove()
    onDone?.()
    return false
  }
  const cancel = bindFrame('delivery:' + lane + ':send', tick)
  return () => { stopped = true; cancel(); flight.remove(); route?.remove() }
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
  paper.style.display = ''
  paper.style.visibility = 'hidden'
  paper.style.opacity = ''
  closed.style.opacity = ''
  wax.style.opacity = ''
  wax.style.left = ''
  wax.style.top = ''
  wax.style.transform = ''
  const lane = env.closest('.letter-station')?.classList.contains('notes') ? 'notes' : 'publish'
  document.querySelectorAll('.fold-sheet,.routing-letter,.slot-letter').forEach(node => {
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
  const promise = new Promise<void>(resolve => {
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
    cancel = bindFrame('page:turn', tick)
  })
  return Object.assign(promise, { cancel: () => { cancel(); flyer.remove() } })
}

type WoodRect = { x: number; y: number; width: number; height: number; rot: number }

export function glideWood(el: HTMLElement, from: WoodRect, to: WoodRect, _ms = 450) {
  el.classList.add('wood-flight')
  if (reducedMotion()) {
    parkWood(el, to)
    el.classList.remove('wood-flight')
    return Promise.resolve()
  }
  const started = performance.now()
  pin(el, from.x - from.width / 2, from.y - from.height / 2, from.width, from.height)
  el.style.transformOrigin = 'center center'
  let cancel = () => {}
  const promise = new Promise<void>(resolve => {
    const tick = (now: number) => {
      const p = springAt(now - started, SPRING.soft)
      const arc = p > 0 && p < 1 ? Math.sin(Math.PI * p) * 28 : 0
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
  el.style.willChange = ''
}

export function flyTaskPaper(from: DOMRect, to: () => Point | null, title: string, key = 'task') {
  if (from.width < 2) return Object.assign(Promise.resolve(), { cancel: () => {} })
  const card = document.createElement('div')
  card.className = 'task-paper-flight'
  card.setAttribute('aria-hidden', 'true')
  card.textContent = title
  document.body.append(card)
  const w0 = Math.max(from.width, 88)
  const h0 = Math.max(from.height, 36)
  pin(card, from.left, from.top, w0, h0)
  let sx = from.left + from.width / 2
  let sy = from.top + from.height / 2
  let started = performance.now()
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
        started = now
      }
      prev = dest
      const p = springAt(now - started, SPRING.mass)
      const along = Math.min(1, Math.max(0, p))
      const arc = along > 0 && along < 1 ? Math.sin(Math.PI * along) * 54 : 0
      const x = lerp(sx, dest.x, p)
      const y = lerp(sy, dest.y, p) - arc
      const scaleX = lerp(1, 132 / w0, along)
      const scaleY = lerp(1, 86 / h0, along)
      const rot = lerp(-8, 4, along) + (p > 1 ? (p - 1) * -12 : 0)
      card.style.transform = `perspective(800px) translate3d(${x - w0 / 2}px, ${y - h0 / 2}px, 0) scale(${scaleX}, ${scaleY}) rotate(${rot}deg) rotateX(${along * 18}deg)`
      card.style.opacity = springSettled(now - started, SPRING.mass) ? String(Math.max(0, 1 - (now - started - 720) / 220)) : '1'
      if (!springSettled(now - started, SPRING.mass) || now - started < 920) return true
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
    const w = Math.max(item.rect.width, 96)
    const h = Math.max(item.rect.height, 72)
    pin(el, item.rect.left, item.rect.top, w, h)
    return { el, w, h, x: item.rect.left + w / 2, y: item.rect.top + h / 2 }
  })
  let started = performance.now()
  let prev: { x: number; y: number } | null = null
  let cancel = () => {}
  const promise = new Promise<void>(resolve => {
    const tick = (now: number) => {
      const hole = mouth()
      if (!hole) { nodes.forEach(node => node.el.remove()); resolve(); return false }
      if (prev && Math.hypot(hole.x - prev.x, hole.y - prev.y) > 12) {
        nodes.forEach(node => {
          const box = node.el.getBoundingClientRect()
          node.x = box.left + box.width / 2
          node.y = box.top + box.height / 2
        })
        started = now
      }
      prev = hole
      const p = springAt(now - started, SPRING.soft)
      const travel = Math.min(1, Math.max(0, p))
      const sink = ramp(travel, 0.62, 1)
      nodes.forEach((node, index) => {
        const arc = travel > 0 && travel < 1 ? Math.sin(Math.PI * travel) * 16 : 0
        const x = lerp(node.x, hole.x, travel) + index * 8
        const y = lerp(node.y, hole.y, travel) + sink * (hole.height * 0.35) - arc
        node.el.style.transform = `translate3d(${x - node.w / 2}px, ${y - node.h / 2}px, 0) rotateX(${sink * 22}deg)`
        node.el.style.transformOrigin = 'center top'
        node.el.style.clipPath = sink > 0.02 ? `inset(${sink * 100}% 0 0 0)` : ''
        node.el.style.opacity = String(1 - ramp(sink, 0.72, 1))
      })
      if (!springSettled(now - started)) return true
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
    document.body.append(el)
    const w = row.rect.width
    const h = Math.max(28, row.rect.height)
    pin(el, row.rect.left, row.rect.top, w, h)
    const started = performance.now() + index * 46
    bindFrame('tear:' + index, now => {
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
