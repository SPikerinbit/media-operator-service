import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useReducedMotion } from 'motion/react'

type Phase = 'in' | 'out'

/** Keeps a node mounted through its exit so every show/hide has both sides. */
export function Presence({ open, className = '', children }: { open: boolean; className?: string; children: ReactNode }) {
  const reduced = useReducedMotion()
  const cache = useRef(children)
  const [mounted, setMounted] = useState(open)
  const [phase, setPhase] = useState<Phase>(open ? 'in' : 'out')
  if (open) cache.current = children
  useEffect(() => {
    if (open) {
      setMounted(true)
      setPhase('in')
      return
    }
    if (!mounted) return
    if (reduced) { setMounted(false); return }
    setPhase('out')
  }, [open, reduced, mounted])
  if (!mounted) return null
  return <div className={'wb-presence ' + className + ' is-' + phase} onAnimationEnd={(event) => {
    if (event.target !== event.currentTarget) return
    if (phase === 'out') setMounted(false)
  }}>{phase === 'out' ? cache.current : children}</div>
}
