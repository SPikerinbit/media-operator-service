/** One frame pump. A job that returns false has finished and is dropped. */

type Frame = (now: number) => boolean
type Job = { frame: Frame; revision: number }

const jobs = new Map<string, Job>()
let raf = 0

function pump(now: number) {
  raf = 0
  let live = false
  for (const [id, job] of [...jobs]) {
    let keep = false
    try { keep = job.frame(now) } catch { jobs.delete(id) }
    if (!keep) jobs.delete(id)
    else live = true
  }
  if (live) raf = requestAnimationFrame(pump)
}

export function bindFrame(id: string, frame: Frame, revision = 0) {
  const prev = jobs.get(id)
  if (prev && revision > 0 && prev.revision > revision) return () => {}
  const next = revision > 0 ? revision : prev?.revision || 0
  jobs.set(id, { frame, revision: next })
  if (!raf) raf = requestAnimationFrame(pump)
  return () => { if (jobs.get(id)?.frame === frame) jobs.delete(id) }
}

export function cancelFrame(id: string) {
  jobs.delete(id)
}
