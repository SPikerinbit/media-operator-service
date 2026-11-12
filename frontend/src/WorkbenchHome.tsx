import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useReducedMotion } from 'motion/react'
import { errorMessage, request } from './api'
import { Prop, asset } from './WorkbenchEffects'
import { currentManifest, flapOrigin, useWorkbenchManifest } from './workbenchAnchors'
import { useNotesMode } from './notesMode'
import { ShredLever } from './ShredLever'
import { sessionForSource } from './siteSessions'
import { launchTear, playDelivery, playPageTurn, resetDelivery, type DeliveryPhase } from './workbenchMotion'
import { useMediaQuery } from './ui'
import { classifyLetters, splitLetters, type InboxState, type Lane, type PaperLine } from './workbenchState'

type Returned = { id: string; text: string; reason: string }
type Draft = { lines: PaperLine[]; returned: Returned[]; caretId?: string }
type Frozen = { id: string; text: string; local?: boolean }

function readDraft(lane: Lane): Draft {
  try {
    const raw = JSON.parse(localStorage.getItem('workbench-draft-' + lane) || 'null') as Partial<Draft> & { composer?: string } | null
    const lines = Array.isArray(raw?.lines) ? raw.lines.filter(line => line && typeof line.id === 'string' && typeof line.text === 'string') : []
    if (raw?.composer?.trim()) lines.push(...splitLetters(raw.composer))
    return { lines, returned: Array.isArray(raw?.returned) ? raw.returned : [], caretId: raw?.caretId }
  } catch { return { lines: [], returned: [] } }
}
function trimLines(lines: PaperLine[], caretId?: string) {
  const next = lines.slice()
  while (next.length && !next[next.length - 1].text && next[next.length - 1].id !== caretId) next.pop()
  return next
}
function padLines(lines: PaperLine[], count: number) {
  const next = lines.slice()
  while (next.length < count) next.push({ id: crypto.randomUUID(), text: '' })
  return next
}
function maxPage(count: number, size: number) { return Math.max(1, Math.ceil(count / size)) }
function span(bounds: number[] | undefined, fallback: number[]) {
  const box = bounds && bounds.length === 4 ? bounds : fallback
  return { x: box[0], y: box[1], w: box[2] - box[0], bottom: box[3] }
}

function LetterStation({ lane, data, active }: { lane: Lane; data: InboxState; active: boolean }) {
  const [draft, setDraft] = useState<Draft>(() => readDraft(lane))
  const [page, setPage] = useState(0)
  const [phase, setPhase] = useState<DeliveryPhase | 'idle' | 'identifying'>('idle')
  const [error, setError] = useState('')
  const [snapshot, setSnapshot] = useState<string[]>([])
  const [press, setPress] = useState(false)
  const [notesMode, setNotesMode] = useNotesMode()
  const [turning, setTurning] = useState(false)
  const [arrived, setArrived] = useState(false)
  const [leavingId, setLeavingId] = useState('')
  const tight = useMediaQuery('(max-height: 700px)')
  const compact = useMediaQuery('(max-height: 820px)')
  const pageSize = tight ? 3 : compact ? 4 : 5
  const manifest = useWorkbenchManifest()
  const reduced = useReducedMotion()
  const root = useRef<HTMLElement>(null)
  const envRef = useRef<HTMLDivElement>(null)
  const mailRef = useRef<HTMLDivElement>(null)
  const paperRef = useRef<HTMLDivElement>(null)
  const flapRef = useRef<HTMLDivElement>(null)
  const closedRef = useRef<HTMLImageElement>(null)
  const waxRef = useRef<HTMLDivElement>(null)
  const copyRef = useRef<HTMLDivElement>(null)
  const pile = useRef<HTMLDivElement>(null)
  const sheetRef = useRef<HTMLDivElement>(null)
  const inputs = useRef<Record<string, HTMLInputElement | null>>({})
  const stopDelivery = useRef<(() => void) | null>(null)
  const requestId = useRef('')
  const pending = useRef('')
  const handled = useRef('')
  const focusId = useRef('')
  const composing = useRef(false)
  const title = lane === 'publish' ? '投稿' : '笔记'
  const busy = phase !== 'idle'
  const origin = flapOrigin(manifest)
  const seal = manifest.envelope.anchors.seal
  const filled = draft.lines.some(line => line.text.trim())
  const lineRects = useRef<Record<string, DOMRect>>({})
  const mailBox = span(manifest.mailbox.visible_bounds, [0.08398, 0.22266, 0.91504, 0.79102])
  const envBox = span(manifest.envelope.visible_bounds, [0.07617, 0.3877, 0.9209, 0.85156])
  const mailVisible = tight ? 156 : compact ? 188 : 220
  const envVisible = tight ? 250 : compact ? 290 : 330
  const stackGap = tight ? 4 : compact ? 6 : 8
  const mailSize = mailVisible / mailBox.w
  const envSize = envVisible / envBox.w
  const flapTop = 0.102
  const envTuck = -(flapTop * envSize) + stackGap
  const mailTop = mailBox.y * mailSize
  const mailBot = (1 - mailBox.bottom) * mailSize
  const envBot = (1 - 0.852) * envSize
  const paperW = tight ? 300 : compact ? 360 : 400

  useEffect(() => {
    const stored = { lines: trimLines(draft.lines, draft.caretId), returned: draft.returned, caretId: draft.caretId }
    localStorage.setItem('workbench-draft-' + lane, JSON.stringify(stored))
  }, [draft, lane])
  useLayoutEffect(() => {
    const index = draft.lines.findIndex(line => line.id === draft.caretId)
    if (index >= 0) setPage(Math.floor(index / pageSize))
  }, [pageSize])
  useEffect(() => {
    if (composing.current) return
    const node = inputs.current[focusId.current]
    if (node) node.focus()
    focusId.current = ''
  }, [page, draft.lines])

  function commit(index: number, text: string) {
    requestId.current = ''
    setDraft(current => {
      const created = !current.lines[index]
      const next = padLines(current.lines, index + 1)
      next[index] = { ...next[index], text }
      if (created) focusId.current = next[index].id
      return { ...current, lines: next, caretId: next[index].id }
    })
  }
  function focusIndex(index: number) {
    const nextPage = Math.floor(index / pageSize)
    setDraft(current => {
      const next = padLines(current.lines, index + 1)
      focusId.current = next[index].id
      return { ...current, lines: next, caretId: next[index].id }
    })
    setPage(Math.min(nextPage, maxPage(Math.max(draft.lines.length, index + 1), pageSize)))
  }
  function pageLines(index: number) {
    return draft.lines.slice(index, index + pageSize).map(line => line.text)
  }
  async function turn(dir: 'next' | 'prev') {
    if (turning || busy || composing.current) return
    const limit = maxPage(draft.lines.length, pageSize)
    const target = dir === 'next' ? Math.min(limit, page + 1) : page - 1
    if (target === page || target < 0) return
    const rect = sheetRef.current?.getBoundingClientRect()
    setTurning(true)
    if (dir === 'prev') {
      const outgoing = pageLines(page * pageSize)
      const id = draft.lines[target * pageSize]?.id
      if (id) focusId.current = id
      if (rect && !reduced) {
        const flight = playPageTurn(rect, 'prev', outgoing)
        setPage(target)
        await flight
      } else setPage(target)
    } else {
      const incoming = pageLines(target * pageSize)
      if (rect && !reduced) await playPageTurn(rect, 'next', incoming.length ? incoming : [''])
      focusIndex(target * pageSize)
    }
    setTurning(false)
  }
  function onPaste(index: number, event: React.ClipboardEvent<HTMLInputElement>) {
    if (composing.current) return
    const raw = event.clipboardData.getData('text')
    const items = classifyLetters(raw)
    if (!items.length) return
    event.preventDefault()
    const made = items.map(item => ({ id: crypto.randomUUID(), text: item.text.replace(/[ \t]*\r?\n[ \t]*/g, ' ').replace(/ {2,}/g, ' ').trim(), local: item.local || undefined })).filter(line => line.text)
    if (!made.length) return
    const before = page
    setDraft(current => {
      const next = padLines(current.lines, index + 1)
      next.splice(index, 1, ...made)
      return { ...current, lines: next, caretId: made[made.length - 1].id }
    })
    const landing = Math.floor((index + made.length - 1) / pageSize)
    focusId.current = made[made.length - 1].id
    if (made.length > 1 && landing !== before) {
      setTurning(true)
      const rect = sheetRef.current?.getBoundingClientRect()
      void (rect && !reduced ? playPageTurn(rect, 'next', made.map(line => line.text)) : Promise.resolve()).finally(() => {
        setPage(landing)
        setTurning(false)
      })
    }
  }
  useEffect(() => {
    const id = pending.current
    if (!id || handled.current === id) return
    const received = data.entries.filter(entry => entry.group_id === id)
    if (!received.length || received.some(entry => entry.status === 'identifying')) return
    handled.current = id
    const returned = received.filter(entry => entry.status === 'rejected')
    const accepted = received.filter(entry => entry.status !== 'rejected')
    const tears = returned.slice(0, 3).flatMap(entry => {
      const rect = entry.client_id ? lineRects.current[entry.client_id] : undefined
      return rect && rect.width > 0 ? [{ text: entry.raw, rect }] : []
    })
    setDraft(current => ({
      ...current,
      returned: [...current.returned, ...returned.map(entry => ({ id: entry.id, text: entry.raw, reason: entry.message }))],
    }))
    if (tears.length && !reduced) launchTear(tears, () => pile.current)
    const acceptedLines = accepted.map(entry => entry.raw)
    setSnapshot(acceptedLines)
    if (!accepted.length || !active || reduced) { setPhase('idle'); return }
    const env = envRef.current
    const mail = mailRef.current
    const paper = paperRef.current
    const flap = flapRef.current
    const closed = closedRef.current
    const wax = waxRef.current
    const copy = copyRef.current
    const station = root.current
    if (!env || !mail || !paper || !flap || !closed || !wax || !copy || !station) { setPhase('idle'); return }
    const home = env.getBoundingClientRect()
    env.dataset.home = JSON.stringify({ x: home.left + home.width / 2, y: home.top + home.height / 2 })
    stopDelivery.current?.()
    stopDelivery.current = playDelivery({
      root: station, env, mail, paper, flap, closed, wax, copy, sheet: sheetRef.current, lines: acceptedLines,
    }, currentManifest(), import.meta.env.BASE_URL, next => setPhase(next), () => {
      resetDelivery(env, flap, paper, closed, wax)
      setPhase('idle')
    })
  }, [data, active, reduced])
  useEffect(() => () => { stopDelivery.current?.(); stopDelivery.current = null }, [])
  useEffect(() => {
    if (active) return
    stopDelivery.current?.()
    stopDelivery.current = null
    const env = envRef.current
    const flap = flapRef.current
    const paper = paperRef.current
    const closed = closedRef.current
    const wax = waxRef.current
    if (env && flap && paper && closed && wax) resetDelivery(env, flap, paper, closed, wax)
    if (phase !== 'idle' && phase !== 'identifying') setPhase('idle')
  }, [active])
  useEffect(() => {
    const cancel = () => {
      stopDelivery.current?.(); stopDelivery.current = null
      const env=envRef.current, flap=flapRef.current, paper=paperRef.current, closed=closedRef.current, wax=waxRef.current
      if(env&&flap&&paper&&closed&&wax)resetDelivery(env,flap,paper,closed,wax)
      setPhase(current=>current==='identifying'?current:'idle')
    }
    window.addEventListener('resize',cancel)
    return()=>window.removeEventListener('resize',cancel)
  }, [])

  async function deliver() {
    if (busy || composing.current) return
    const frozen: Frozen[] = draft.lines.filter(line => line.text.trim()).map(line => {
      const found = classifyLetters(line.text)
      return { id: line.id, text: line.text.trim(), local: found.length === 1 ? found[0].local : line.local }
    })
    if (!frozen.length) return
    setPress(true)
    window.setTimeout(() => setPress(false), 160)
    const ids = new Set(frozen.map(line => line.id))
    frozen.forEach(line => { const rect = inputs.current[line.id]?.getBoundingClientRect(); if (rect) lineRects.current[line.id] = rect })
    setSnapshot(frozen.map(line => line.text))
    setDraft(current => ({ ...current, lines: current.lines.filter(line => !ids.has(line.id)) }))
    setPage(0)
    setError('')
    setPhase('identifying')
    requestId.current ||= crypto.randomUUID()
    try {
      const response = await request<{ group_id: string }>('/desktop/inbox/deliveries', 'POST', {
        request_id: requestId.current, lane, notes_mode: lane === 'notes' ? notesMode : 'curated', entries: frozen.map(line => ({ id: line.id, text: line.text, local: Boolean(line.local), session_id:sessionForSource(classifyLetters(line.text)[0]?.source||line.text) })),
      })
      requestId.current = ''
      pending.current = response.group_id
    } catch (reason) {
      requestId.current = ''
      setDraft(current => ({ ...current, lines: [...frozen.map(line => ({ id: line.id, text: line.text, local: line.local })), ...current.lines] }))
      setPhase('idle')
      setError(errorMessage(reason))
    }
  }
  function restore(item: Returned) {
    const line = { id: crypto.randomUUID(), text: item.text }
    focusId.current = line.id
    setLeavingId(item.id)
    window.setTimeout(() => {
      setDraft(current => ({ ...current, lines: [...trimLines(current.lines, line.id), line], caretId: line.id, returned: current.returned.filter(entry => entry.id !== item.id) }))
      setLeavingId('')
    }, reduced ? 0 : 240)
    setPage(Math.floor(trimLines(draft.lines).length / pageSize))
  }
  const returnedCount = useRef(draft.returned.length)
  useEffect(() => {
    if (draft.returned.length <= returnedCount.current) { returnedCount.current = draft.returned.length; return }
    returnedCount.current = draft.returned.length
    setArrived(true)
    const timer = window.setTimeout(() => setArrived(false), 640)
    return () => window.clearTimeout(timer)
  }, [draft.returned.length])

    return <section ref={root} className={'letter-station ' + lane + (tight ? ' is-tight' : compact ? ' is-short' : '')} data-phase={phase === 'identifying' ? 'identify' : phase} aria-label={title + '信箱'} style={{ '--hinge-x': origin[0], '--hinge-y': origin[1], '--plaque-x': manifest.mailbox.anchors.plaque[0], '--plaque-y': manifest.mailbox.anchors.plaque[1], '--seal-x': seal[0], '--seal-y': seal[1], '--lines': pageSize, '--mail-box': mailSize + 'px', '--env-box': envSize + 'px', '--paper-w': paperW + 'px', '--env-tuck': envTuck + 'px', '--mail-top': mailTop + 'px', '--mail-bot': mailBot + 'px', '--env-bot': envBot + 'px', '--stack-gap': stackGap + 'px' } as React.CSSProperties}>
    <header className="station-heading"><h2>{title}</h2><p>{lane === 'publish' ? '投递后再设置。' : '投递后自动整理。'}</p></header>
    <div className="delivery-apparatus">
      <div className="desk-mailbox" ref={mailRef}>
        <Prop name="mailbox" layer="body" className="mailbox-body" />
        <Prop name="mailbox" layer="slot-back" className="mailbox-slot" />
        <div className="slot-window" data-slot-window />
        <Prop name="mailbox" layer="slot-front" className="mailbox-slot mailbox-slot-front" />
        <Prop name="mailbox" layer="front" className="mailbox-front" />
        <span className="slot-flap" aria-hidden="true" />
        <span className="mailbox-name">{title}</span>
      </div>
      <div className="writing-paper">
        <div className="sheet-stack">
          <div className="sheet-under" aria-hidden="true" />
          <div className="sheet-current" ref={sheetRef}>
            <div className="sheet-rules">
              {Array.from({ length: pageSize }, (_, slot) => {
                const index = page * pageSize + slot
                const line = draft.lines[index]
                return <input key={slot} data-line-id={line?.id || ''} ref={node => { if (line) inputs.current[line.id] = node }} className="rule-input" aria-label={`${title}第 ${index + 1} 行`} placeholder={page === 0 && slot === 0 ? '写在这里' : ''} value={line?.text ?? ''}
                  onCompositionStart={() => { composing.current = true }}
                  onCompositionEnd={() => { composing.current = false }}
                  onFocus={() => { if (line) setDraft(current => ({ ...current, caretId: line.id })); else if (!composing.current) focusIndex(index) }}
                  onChange={event => commit(index, event.target.value)}
                  onPaste={event => onPaste(index, event)}
                  onKeyDown={event => {
                    if (composing.current || event.nativeEvent.isComposing) return
                    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') { event.preventDefault(); void deliver(); return }
                    if (event.key === 'Enter') {
                      event.preventDefault()
                      if (slot === pageSize - 1) void turn('next')
                      else focusIndex(index + 1)
                    } else if (event.key === 'ArrowDown') {
                      event.preventDefault()
                      if (slot === pageSize - 1) void turn('next')
                      else focusIndex(index + 1)
                    } else if (event.key === 'ArrowUp' && index > 0) {
                      event.preventDefault()
                      if (slot === 0) void turn('prev')
                      else focusIndex(index - 1)
                    }
                  }} />
              })}
            </div>
            {page > 0 && <button type="button" className={'page-corner prev' + (turning ? ' is-lifted' : '')} aria-label="上一页" disabled={turning || busy} onClick={() => void turn('prev')} />}
            <button type="button" className={'page-corner next' + (turning ? ' is-lifted' : '')} aria-label="下一页" disabled={turning || busy || page >= maxPage(draft.lines.length, pageSize)} onClick={() => void turn('next')} />
          </div>
        </div>
        <p className="paper-hint">Ctrl + Enter</p>
      </div>
      {lane==='notes'&&<div className="home-mode"><ShredLever value={notesMode} locked={busy} onChange={setNotesMode}/></div>}
      <div className="delivery-envelope" ref={envRef}>
        <Prop name="envelope" layer="body" className="envelope-back" />
        <div className="letter-insert" ref={paperRef} aria-hidden="true"><div className="letter-insert-copy" ref={copyRef}>{snapshot.slice(0, 6).map(line => <span key={line}>{line.replace(/\s+/g, ' ')}</span>)}</div></div>
        <Prop name="envelope" layer="front" className="envelope-front" />
        <div className="envelope-flap" ref={flapRef}><img className="flap-face" src={asset('flap-light-closed')} alt="" /><img className="flap-lining" src={asset('flap-light-back')} alt="" /></div>
        <img ref={closedRef} className="flap-closed" src={asset('flap-light-closed')} alt="" />
        <div className="wax-seal" ref={waxRef}>
          <button className={'wax-button' + (press ? ' is-pressing' : '')} type="button" aria-label={`投递${title}信件`} disabled={!filled || busy} onClick={() => void deliver()}><Prop name={lane === 'publish' ? 'wax' : 'wax-blue'} layer="beauty" /></button>
        </div>
      </div>
    </div>
    <p className="sr-only" role="status">{phase === 'identifying' ? '正在识别来源' : phase !== 'idle' ? '信件正在送达' : ''}</p>
    {error && <p className="notice error" role="alert">{error}</p>}
    {draft.returned.length > 0 && <div className={'returned-letters' + (arrived ? ' tear-in' : '')} ref={pile}><details open><summary>退回 {draft.returned.length} 张纸条</summary>
      {draft.returned.slice(-3).map(item => <div className={'returned-strip' + (leavingId === item.id ? ' is-leaving' : '')} key={item.id}><span title={item.text}>{item.text}</span><small>{item.reason}</small><button type="button" onClick={() => restore(item)}>恢复编辑</button></div>)}
      {draft.returned.length > 3 && <p className="returned-more">另有 {draft.returned.length - 3} 张叠在下面</p>}
    </details></div>}
  </section>
}

export function WorkbenchHome({ data, active }: { data: InboxState; active: boolean; onOpen?: (lane: Lane) => void }) {
  return <div className="mailroom"><header className="mailroom-heading"><div><h1>把灵感寄出去</h1><p>一封准备发布，一封留作笔记。</p></div></header><div className="two-mailboxes">
    <LetterStation lane="publish" data={data} active={active} />
    <LetterStation lane="notes" data={data} active={active} />
  </div></div>
}
