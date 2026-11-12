import { useEffect, useRef } from 'react'
import { springAt, SPRING } from './motionSystem'

export type ThreadEnd = { id: number; x1: number; y1: number; x2: number; y2: number; hot: boolean; clear: number }

type Live = ThreadEnd & { born: number; index: number }

function curve(a: ThreadEnd, _bias: number, _settle: number) {
  const gate = Math.max(a.x1 + 24, a.clear || a.x1 + 36)
  const c1x = gate
  const c1y = a.y1
  const c2x = Math.max(gate, a.x2 - 16)
  const c2y = a.y2
  return `M ${a.x1.toFixed(1)} ${a.y1.toFixed(1)} C ${c1x.toFixed(1)} ${c1y.toFixed(1)}, ${c2x.toFixed(1)} ${c2y.toFixed(1)}, ${a.x2.toFixed(1)} ${a.y2.toFixed(1)}`
}

/** Hang most threads. When two links would cross, send one above and one below. */
function biases(list: ThreadEnd[]) {
  const bias = new Map<number, number>()
  for (const thread of list) bias.set(thread.id, 1)
  for (let i = 0; i < list.length; i++) {
    for (let j = i + 1; j < list.length; j++) {
      const a = list[i]
      const b = list[j]
      if ((a.y1 - b.y1) * (a.y2 - b.y2) >= 0) continue
      if (a.y1 < b.y1) { bias.set(a.id, -0.55); bias.set(b.id, 1.25) }
      else { bias.set(b.id, -0.55); bias.set(a.id, 1.25) }
    }
  }
  return bias
}

/** Cotton thread pinned between a shred and a note. Draw-in is staggered and springy. */
export function NoteThreads({ threads, active=true }: { threads: ThreadEnd[]; active?:boolean }) {
  const svg = useRef<SVGSVGElement>(null)
  const live = useRef(new Map<number, Live>())
  const props = useRef(threads)
  props.current = threads
  useEffect(() => {
    if(!active)return
    const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches
    let frame = 0
    const step = (now: number) => {
      const root = svg.current
      const want = props.current
      const seen = new Set<number>()
      const bias = biases(want)
      const desk = root?.closest('.notes-completion')
      if (root) {
        desk?.querySelectorAll('.shred-strip.is-linked, .viewpoint-slip.is-linked').forEach(node => node.classList.remove('is-linked'))
        want.forEach((next, index) => {
          seen.add(next.id)
          let cur = live.current.get(next.id)
          if (!cur) cur = { ...next, born: now, index }
          const k = 0.18
          cur.x1 += (next.x1 - cur.x1) * k
          cur.y1 += (next.y1 - cur.y1) * k
          cur.x2 += (next.x2 - cur.x2) * k
          cur.y2 += (next.y2 - cur.y2) * k
          cur.hot = next.hot
          cur.clear = next.clear
          cur.index = index
          live.current.set(next.id, cur)
          const sprung = reduced ? 1 : springAt(Math.max(0, now - cur.born - index * 90), SPRING.soft)
          const shown = Math.max(0, Math.min(1.06, sprung))
          const d = curve(cur, bias.get(next.id) || 1, shown)
          const shadow = root.querySelector<SVGPathElement>(`[data-shadow="${next.id}"]`)
          const line = root.querySelector<SVGPathElement>(`[data-thread="${next.id}"]`)
          const twist = root.querySelector<SVGPathElement>(`[data-twist="${next.id}"]`)
          const pins = root.querySelectorAll<SVGCircleElement>(`[data-pin="a-${next.id}"], [data-pin="a-knot-${next.id}"], [data-pin="b-${next.id}"], [data-pin="b-knot-${next.id}"]`)
          shadow?.setAttribute('d', d)
          line?.setAttribute('d', d)
          twist?.setAttribute('d', d)
          line?.classList.toggle('is-hot', cur.hot)
          twist?.classList.toggle('is-hot', cur.hot)
          const paint = (path: SVGPathElement | null) => {
            if (!path) return
            const length = path.getTotalLength()
            const offset = length * (1 - Math.min(1, shown))
            path.style.strokeDasharray = `${length}`
            path.style.strokeDashoffset = `${offset}`
          }
          paint(line)
          if (twist) {
            if (shown < 0.98) {
              const length = line?.getTotalLength() || twist.getTotalLength()
              twist.style.strokeDasharray = `${length}`
              twist.style.strokeDashoffset = `${length * (1 - Math.min(1, shown))}`
            } else {
              twist.style.strokeDasharray = ''
              twist.style.strokeDashoffset = ''
            }
          }
          if (shadow) shadow.style.opacity = String(Math.min(1, shown))
          pins.forEach(pin => {
            const end = pin.dataset.pin?.startsWith('a-')
            pin.setAttribute('cx', String(end ? cur.x1 : cur.x2))
            pin.setAttribute('cy', String(end ? cur.y1 : cur.y2))
            pin.classList.toggle('is-hot', cur.hot)
            pin.style.opacity = String(shown > 0.08 ? 1 : 0)
          })
          if (cur.hot && desk) {
            desk.querySelector(`[data-card-id="${next.id}"]`)?.classList.add('is-linked')
            desk.querySelector(`[data-slip-id="${next.id}"]`)?.classList.add('is-linked')
          }
        })
        for (const id of [...live.current.keys()]) if (!seen.has(id)) live.current.delete(id)
      }
      const moving=want.some(next=>{
        const cur=live.current.get(next.id)
        return cur&&((!reduced&&now-cur.born<1400)||Math.hypot(cur.x1-next.x1,cur.y1-next.y1,cur.x2-next.x2,cur.y2-next.y2)>.2)
      })
      frame = moving ? requestAnimationFrame(step) : 0
    }
    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [threads,active])
  return <svg ref={svg} className="notes-links" aria-hidden="true">
    {threads.map(thread => <g key={thread.id}>
      <path data-shadow={thread.id} className="thread-shadow" />
      <path data-thread={thread.id} className={'thread' + (thread.hot ? ' is-hot' : '')} />
      <path data-twist={thread.id} className={'thread-twist' + (thread.hot ? ' is-hot' : '')} />
      <circle data-pin={'a-' + thread.id} r="3.4" className={'thread-pin' + (thread.hot ? ' is-hot' : '')} />
      <circle data-pin={'a-knot-' + thread.id} r="1.4" className="thread-knot" />
      <circle data-pin={'b-' + thread.id} r="3.4" className={'thread-pin' + (thread.hot ? ' is-hot' : '')} />
      <circle data-pin={'b-knot-' + thread.id} r="1.4" className="thread-knot" />
    </g>)}
  </svg>
}
