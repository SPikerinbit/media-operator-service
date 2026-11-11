export type NotesMode = 'summary' | 'curated' | 'comprehensive'

const modes: { id: NotesMode; label: string }[] = [
  { id: 'summary', label: '摘要' },
  { id: 'curated', label: '精华观点' },
  { id: 'comprehensive', label: '大多数观点' },
]

export function ShredLever({ value, locked, onChange }: { value: NotesMode; locked?: boolean; onChange: (mode: NotesMode) => void }) {
  return <div className={'shred-lever' + (locked ? ' is-locked' : '')} role="radiogroup" aria-label="摘录档位">
    <div className="lever-plate">摘录</div>
    <div className="lever-track">
      {modes.map(mode => <button key={mode.id} type="button" role="radio" aria-checked={value === mode.id} disabled={locked} className={value === mode.id ? 'is-set' : ''} onClick={() => onChange(mode.id)}>
        <i /><span>{mode.label}</span>
      </button>)}
    </div>
  </div>
}
