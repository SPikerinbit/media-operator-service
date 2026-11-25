import { motion } from 'motion/react'
import type { NotesMode } from './notesMode'
export type { NotesMode } from './notesMode'

const modes: { id: NotesMode; label: string; caption: string }[] = [
  { id: 'summary', label: '摘要', caption: '多层树状' },
  { id: 'curated', label: '核心观点', caption: '精选陈述' },
  { id: 'comprehensive', label: '大多数观点', caption: '详尽全览' },
]

export function ShredLever({ value, locked, onChange }: { value: NotesMode; locked?: boolean; onChange: (mode: NotesMode) => void }) {
  const activeIndex = Math.max(0, modes.findIndex(mode => mode.id === value))
  return <div className={'shred-lever' + (locked ? ' is-locked' : '')} role="radiogroup" aria-label="整理档位">
    <div className="lever-track">
      <motion.i
        className="lever-knob"
        aria-hidden="true"
        animate={{ x: `${activeIndex * 100}%` }}
        transition={{ type: 'spring', stiffness: 500, damping: 36 }}
      />
      {modes.map((mode, index) => <button key={mode.id} type="button" role="radio" aria-label={mode.label} aria-checked={value === mode.id} tabIndex={value === mode.id ? 0 : -1} disabled={locked} className={value === mode.id ? 'is-set' : ''} onClick={() => onChange(mode.id)} onKeyDown={event => {
        const step = ['ArrowDown', 'ArrowRight'].includes(event.key) ? 1 : ['ArrowUp', 'ArrowLeft'].includes(event.key) ? -1 : 0
        if (!step && event.key !== 'Home' && event.key !== 'End') return
        event.preventDefault()
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? 2 : (index + step + modes.length) % modes.length
        onChange(modes[next].id)
        const buttons = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('button')
        buttons?.[next]?.focus()
      }}>
        <span className="lever-title"><b className="mode-lamp" aria-hidden="true" /><strong>{mode.label}</strong></span>
        <small aria-hidden="true">{mode.caption}</small>
      </button>)}
    </div>
  </div>
}
