import { useEffect, useRef } from 'react'

export type ThreadEnd = { id: number; x1: number; y1: number; x2: number; y2: number; hot: boolean }

function sag(a: ThreadEnd, t = 1) {
  const dx = a.x2 - a.x1
  const drop = Math.min(22, Math.abs(dx) * 0.08 + 6) * t
  const mx = a.x1 + dx * 0.5
  const my = (a.y1 + a.y2) / 2 + drop
  return `M ${a.x1.toFixed(1)} ${a.y1.toFixed(1)} Q ${mx.toFixed(1)} ${my.toFixed(1)} ${a.x2.toFixed(1)} ${a.y2.toFixed(1)}`
}

/** Cotton thread pinned between a shred and a note, eased when the ends move. */
export function NoteThreads({ threads }: { threads: ThreadEnd[] }) {
  const svg = useRef<SVGSVGElement>(null)
  const live = useRef(new Map<number, ThreadEnd & { draw: number }>())
  const props = useRef(threads)
  props.current = threads
  useEffect(() => {
    let frame = 0
    const step = () => {
      const root = svg.current
      const want = props.current
      const seen = new Set<number>()
      if (root) {
        for (const next of want) {
          seen.add(next.id)
          let cur = live.current.get(next.id)
          if (!cur) cur = { ...next, draw: 0 }
          const k = 0.16
          cur.x1 += (next.x1 - cur.x1) * k
          cur.y1 += (next.y1 - cur.y1) * k
          cur.x2 += (next.x2 - cur.x2) * k
          cur.y2 += (next.y2 - cur.y2) * k
          cur.hot = next.hot
          cur.draw = Math.min(1, cur.draw + 0.035)
          live.current.set(next.id, cur)
          const d = sag(cur, cur.draw)
          const shadow = root.querySelector<SVGPathElement>(`[data-shadow="${next.id}"]`)
          const line = root.querySelector<SVGPathElement>(`[data-thread="${next.id}"]`)
          const a = root.querySelector<SVGCircleElement>(`[data-pin="a-${next.id}"]`)
          const b = root.querySelector<SVGCircleElement>(`[data-pin="b-${next.id}"]`)
          shadow?.setAttribute('d', d)
          line?.setAttribute('d', d)
          line?.classList.toggle('is-hot', cur.hot)
          if (a) { a.setAttribute('cx', String(cur.x1)); a.setAttribute('cy', String(cur.y1)); a.classList.toggle('is-hot', cur.hot) }
          if (b) { b.setAttribute('cx', String(cur.x2)); b.setAttribute('cy', String(cur.y2)); b.classList.toggle('is-hot', cur.hot) }
        }
        for (const id of [...live.current.keys()]) if (!seen.has(id)) live.current.delete(id)
      }
      frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [])
  return <svg ref={svg} className="notes-links" aria-hidden="true">
    {threads.map(thread => <g key={thread.id}>
      <path data-shadow={thread.id} className="thread-shadow" />
      <path data-thread={thread.id} className={'thread' + (thread.hot ? ' is-hot' : '')} />
      <circle data-pin={'a-' + thread.id} r="3.2" className={'thread-pin' + (thread.hot ? ' is-hot' : '')} />
      <circle data-pin={'b-' + thread.id} r="3.2" className={'thread-pin' + (thread.hot ? ' is-hot' : '')} />
    </g>)}
  </svg>
}
