import { AlertCircle, CircleCheck, LoaderCircle, X } from 'lucide-react'
import { motion, useReducedMotion } from 'motion/react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Button } from './vendor/boardui/button'
import { Chip } from './vendor/boardui/chip'
import { Collapsible, CollapsibleTrigger, CollapsibleContent, CollapsibleIndicator } from './vendor/beui/collapsible'
import { errorMessage, labels, type Status } from './api'

export { Button }
export type Notice = { text: string; error?: boolean }
export function useActions() {
  const [notice, setNotice] = useState<Notice | null>(null)
  function perform(action: () => void | Promise<void>) {
    setNotice(null)
    void Promise.resolve().then(action).catch((error) => setNotice({ text: errorMessage(error), error: true }))
  }
  return { notice, setNotice, perform }
}

export function Feedback({ notice }: { notice: Notice | null }) {
  return notice?.error
    ? <div className="notice error" role="alert"><AlertCircle size={17} />{notice.text}</div>
    : <div className={notice ? 'notice' : 'notice-empty'} role="status">{notice && <><CircleCheck size={17} />{notice.text}</>}</div>
}
export function StateChip({ status }: { status: Status }) {
  return <Chip variant="caption" color={status === 'succeeded' ? 'lime' : status === 'failed' ? 'rose' : status === 'running' ? 'blue' : 'neutral'}>
    {labels[status]}
  </Chip>
}
export function Busy({ children }: { children: ReactNode }) {
  return <span className="busy" role="status"><LoaderCircle size={16} aria-hidden="true" />{children}</span>
}
export function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="field"><span>{label}</span>{children}</label>
}
export function Select({ value, onChange, options }: {
  value: string | number; onChange: (value: string) => void; options: ReadonlyArray<readonly [string | number, string]>
}) {
  return <select value={value} onChange={(e) => onChange(e.target.value)}>
    {options.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
  </select>
}
export function Disclosure({ title, children }: { title: string; children: ReactNode }) {
  return <Collapsible className="disclosure">
    <CollapsibleTrigger className="disclosure-trigger">{title}<CollapsibleIndicator /></CollapsibleTrigger>
    <CollapsibleContent className="disclosure-content">{children}</CollapsibleContent>
  </Collapsible>
}

export function Modal({ open, title, onClose, children, drawer = false }: {
  open: boolean; title: string; onClose: () => void; children: ReactNode; drawer?: boolean
}) {
  const reduce = useReducedMotion()
  const dialog = useRef<HTMLDialogElement>(null)
  const restore = useRef<HTMLElement | null>(null)
  useEffect(() => {
    const node = dialog.current
    if (!node) return
    if (open && !node.open) {
      restore.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
      node.showModal()
    } else if (!open && node.open) {
      node.close()
      if (restore.current?.isConnected) restore.current.focus()
    }
  }, [open])
  return <dialog ref={dialog} className={drawer ? 'drawer glass' : 'modal glass'} aria-label={title}
    onCancel={(event) => { event.preventDefault(); onClose() }}
    onClick={(event) => { if (event.target === dialog.current) {
      const rect = event.currentTarget.getBoundingClientRect()
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) onClose()
    } }}>
    <motion.div initial={false} animate={{opacity: open || reduce ? 1 : .8,
      x: drawer && !open && !reduce ? 15 : 0, y: !drawer && !open && !reduce ? 8 : 0}}
      transition={reduce ? {duration:0} : {type:'spring',stiffness:450,damping:40}}>
      <header className="modal-heading"><h2>{title}</h2><Button variant="ghost" iconOnly leadingIcon={X} aria-label="关闭" onClick={onClose} /></header>
      {children}
    </motion.div>
  </dialog>
}
