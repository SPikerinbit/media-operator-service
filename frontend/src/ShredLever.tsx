import { motion } from 'motion/react'
import type { NotesMode } from './notesMode'
export type { NotesMode } from './notesMode'

const modes: { id: NotesMode; label: string }[] = [
  { id: 'summary', label: '摘要' },
  { id: 'curated', label: '精华观点' },
  { id: 'comprehensive', label: '大多数观点' },
]

export function ShredLever({ value, locked, onChange }: { value: NotesMode; locked?: boolean; onChange: (mode: NotesMode) => void }) {
  return <div className={'shred-lever' + (locked ? ' is-locked' : '')} role="radiogroup" aria-label="摘录档位">
    <div className="lever-plate">摘录</div>
    <div className="lever-track">
      <motion.i className="lever-knob" animate={{ y: modes.findIndex(mode => mode.id === value) * 36 }} transition={{ type: 'spring', stiffness: 420, damping: 24 }} />
      {modes.map((mode, index) => <button key={mode.id} type="button" role="radio" aria-checked={value === mode.id} tabIndex={value === mode.id ? 0 : -1} disabled={locked} className={value === mode.id ? 'is-set' : ''} onClick={() => onChange(mode.id)} onKeyDown={event => {
        const step = ['ArrowDown', 'ArrowRight'].includes(event.key) ? 1 : ['ArrowUp', 'ArrowLeft'].includes(event.key) ? -1 : 0
        if (!step && event.key !== 'Home' && event.key !== 'End') return
        event.preventDefault()
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? 2 : (index + step + modes.length) % modes.length
        onChange(modes[next].id)
        const buttons = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('button')
        buttons?.[next]?.focus()
      }}>
        <b className="mode-lamp" /><span>{mode.label}</span>
      </button>)}
    </div>
  </div>
}
