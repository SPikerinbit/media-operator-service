import { AlertCircle, CircleCheck, LoaderCircle, X } from 'lucide-react'
import { cloneElement, isValidElement, useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type ReactElement, type ReactNode } from 'react'
import { Button } from './vendor/boardui/button'
import { Chip } from './vendor/boardui/chip'
import { Collapsible, CollapsibleTrigger, CollapsibleContent, CollapsibleIndicator } from './vendor/beui/collapsible'
import { errorMessage, labels, type Status } from './api'

export { Button }
export function useMediaQuery(query: string) {
  const [matches,setMatches] = useState(() => window.matchMedia(query).matches)
  useEffect(() => {
    const media = window.matchMedia(query)
    const update = () => setMatches(media.matches)
    update();media.addEventListener('change',update)
    return () => media.removeEventListener('change',update)
  },[query])
  return matches
}

export type ToastNotice = {
  id: number
  text: string
  tone?: 'info' | 'success' | 'error'
  duration?: number
  actionLabel?: string
  onAction?: () => void
}

export function WorkbenchToast({ toast, onDismiss }: { toast: ToastNotice | null; onDismiss: () => void }) {
  const [rendered, setRendered] = useState<ToastNotice | null>(toast)
  const [leaving, setLeaving] = useState(false)
  const [paused, setPaused] = useState(false)
  const dismissRef = useRef(onDismiss)
  dismissRef.current = onDismiss

  useEffect(() => {
    if (toast) {
      setRendered(toast)
      setLeaving(false)
      return
    }
    if (!rendered) return
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduced) {
      setRendered(null)
      setLeaving(false)
      return
    }
    setLeaving(true)
    const timer = window.setTimeout(() => {
      setRendered(null)
      setLeaving(false)
    }, 180)
    return () => window.clearTimeout(timer)
  }, [toast, rendered])

  useEffect(() => {
    if (!toast || paused) return
    const ms = toast.duration ?? (toast.tone === 'error' ? 6000 : toast.actionLabel ? 6500 : 3000)
    if (ms <= 0) return
    const timer = window.setTimeout(() => dismissRef.current(), ms)
    return () => window.clearTimeout(timer)
  }, [toast, paused])

  if (!rendered) return null
  const isError = rendered.tone === 'error'
  return <div className="workbench-toast-host">
    <div
      key={rendered.id}
      className={'workbench-toast' + (isError ? ' is-error' : '') + (leaving ? ' is-leaving' : ' is-entering')}
      role={isError ? 'alert' : 'status'}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
    >
      {isError ? <AlertCircle size={16} aria-hidden="true" /> : <CircleCheck size={16} aria-hidden="true" />}
      <span className="workbench-toast-text">{rendered.text}</span>
      {rendered.actionLabel && rendered.onAction && (
        <button type="button" className="workbench-toast-action" onClick={() => rendered.onAction?.()}>
          {rendered.actionLabel}
        </button>
      )}
      <button type="button" className="workbench-toast-close" aria-label="关闭提示" onClick={() => dismissRef.current()}>
        <X size={14} aria-hidden="true" />
      </button>
    </div>
  </div>
}

export type Notice = { text: string; error?: boolean; id?: number; duration?: number }
let noticeSeq = 0
export function useActions(autoDismissMs = 3200) {
  const [notice, setNoticeRaw] = useState<Notice | null>(null)
  const setNotice = useCallback((next: Notice | null) => {
    setNoticeRaw(next ? { ...next, id: next.id ?? ++noticeSeq } : null)
  }, [])
  useEffect(() => {
    if (!notice || notice.error) return
    const ms = notice.duration ?? autoDismissMs
    if (ms <= 0) return
    const timer = window.setTimeout(() => setNoticeRaw(current => current?.id === notice.id ? null : current), ms)
    return () => window.clearTimeout(timer)
  }, [notice, autoDismissMs])
  const perform = useCallback((action: () => void | Promise<void>) => {
    setNoticeRaw(null)
    void Promise.resolve().then(action).catch((error) => setNotice({ text: errorMessage(error), error: true }))
  }, [setNotice])
  return { notice, setNotice, perform }
}

export function Feedback({ notice, onDismiss }: { notice: Notice | null; onDismiss?: () => void }) {
  return notice?.error
    ? <div className="notice error" role="alert"><AlertCircle size={17} /><span>{notice.text}</span>{onDismiss && <button type="button" className="notice-dismiss" aria-label="关闭提示" onClick={onDismiss}><X size={14} aria-hidden="true" /></button>}</div>
    : <div className={notice ? 'notice' : 'notice-empty'} role="status">{notice && <><CircleCheck size={17} /><span>{notice.text}</span>{onDismiss && <button type="button" className="notice-dismiss" aria-label="关闭提示" onClick={onDismiss}><X size={14} aria-hidden="true" /></button>}</>}</div>
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
  const id = useId()
  return <label className="field"><span id={id}>{label}</span>{isValidElement(children)
    ? cloneElement(children as ReactElement<{'aria-labelledby'?:string}>,{'aria-labelledby':id}) : children}</label>
}
export function Select({ value, onChange, options, 'aria-labelledby': labelledBy }: {
  value: string | number; onChange: (value: string) => void; options: ReadonlyArray<readonly [string | number, string]>
  'aria-labelledby'?: string
}) {
  return <select aria-labelledby={labelledBy} value={value} onChange={(e) => onChange(e.target.value)}>
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
  const dialog = useRef<HTMLDialogElement>(null)
  const restore = useRef<HTMLElement | null>(null)
  useLayoutEffect(() => {
    const node = dialog.current
    if (!node) return
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const enterFrom = drawer ? 'translate3d(20px, 0, 0)' : 'translate3d(0, 8px, 0) scale(0.985)'
    const exitTo = drawer ? 'translate3d(16px, 0, 0)' : 'translate3d(0, 6px, 0) scale(0.985)'
    let cancelled = false
    let animation: Animation | undefined
    if (open && !node.open) {
      restore.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
      node.showModal()
    }
    if (open) {
      if (!reduced) animation = node.animate([{opacity:0,transform:enterFrom},{opacity:1,transform:'none'}],
        {duration:220,easing:'cubic-bezier(0.22, 1, 0.36, 1)'})
    } else if (node.open) {
      const finish = () => {
        if (cancelled) return
        node.close()
        if (restore.current?.isConnected) restore.current.focus({preventScroll:true})
      }
      if (reduced) finish()
      else {
        animation = node.animate([{opacity:1,transform:'none'},{opacity:0,transform:exitTo}],
          {duration:150,easing:'cubic-bezier(0.2, 0, 0, 1)'})
        void animation.finished.then(finish).catch(() => {})
      }
    }
    return () => {cancelled=true;animation?.cancel()}
  }, [open,drawer])
  return <dialog ref={dialog} className={drawer ? 'drawer' : 'modal thin-scroll'} aria-label={title}
    onCancel={(event) => { event.preventDefault(); onClose() }}
    onClick={(event) => { if (event.target === dialog.current) {
      const rect = event.currentTarget.getBoundingClientRect()
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) onClose()
    } }}>
    <header className="modal-heading"><h2>{title}</h2><Button variant="ghost" iconOnly leadingIcon={X} aria-label="关闭" onClick={onClose} /></header>
    {children}
  </dialog>
}
