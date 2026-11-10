import { useEffect, useRef, type ReactNode } from 'react'
import { leaf, workflow, type Item, type ParsedSource, type SourceKind, type SourceProbe } from './api'
import { matchRemote, sameLink, siteOf } from './shareText'
import { Button } from './ui'
import type { Row } from './videoOptions'

export type VideoTransfer = {
  id: number; source: string; kind: SourceKind; title?: string; continueFrom?: [string, string]; author?: string; site?: string
}
export type NoteHandoff = {
  source: string; kind: SourceKind; title?: string; author?: string; site?: string; transcriptId?: number
  translationUrl?: string; probe?: SourceProbe; imageNote?: boolean; images?: string[]; body?: string; sessionId?: string
}

export const publishEmpty = '把视频链接或分享文案贴在这里，做成带字幕的 B 站稿件。'
export const notesEmpty = '把链接或分享文案贴在这里，整理成可检索的笔记。'

const stageName = (key: string) => workflow.find(([stage]) => stage === key)?.[1] || ''

export const noteOnlyMessage = '没有可烧录的视频。请改到笔记。'

export function isImageNote(row: Pick<Row, 'imageNote' | 'probe' | 'source' | 'site'>) {
  if (row.imageNote) return true
  if (/\.(png|jpe?g|gif|webp|avif|bmp|heic)$/i.test(row.source.split(/[?#]/, 1)[0])) return true
  const probe = row.probe
  if (!probe) return false
  if (probe.ready && (probe.media_type === 'image' || probe.media_type === 'note')) return true
  if (!probe.ready && probe.code === 'no_stream' && (row.site === '小红书' || /小红书|图文|笔记页面/.test(probe.message))) return true
  if (probe.ready && probe.media_type !== 'video' && probe.media_type !== 'audio' && !probe.has_audio && Boolean(probe.body || probe.images?.length)) return true
  return false
}

export function blockedNote(row: Pick<Row, 'hold' | 'probe'>) {
  return Boolean(row.hold?.includes('没有可烧录的视频') || (row.probe?.ready && row.probe.media_type === 'note'))
}

export function describedProbe(item: Row, probe: SourceProbe): Row {
  if (!probe.ready) return { ...item, probe, hold: undefined }
  const next: Row = {
    ...item, probe, hold: undefined,
    title: probe.title?.trim() ? probe.title : item.title,
    site: probe.platform || item.site,
    author: probe.author || item.author,
    body: item.body || probe.body || probe.description,
    images: item.images?.length ? item.images : probe.images,
  }
  return { ...next, imageNote: Boolean(item.imageNote || isImageNote(next)) }
}

export function withRemoteShare(row: Row, item: ParsedSource) {
  const reprobe = row.source !== item.url || row.kind !== item.source_kind
  const titled = !reprobe && row.probe?.ready && Boolean(row.probe.title?.trim())
  return {
    reprobe,
    row: {
      ...row, source: item.url, kind: item.source_kind,
      title: titled ? row.title : (item.title || row.title),
      author: item.author || row.author, site: item.platform || row.site,
      expectedDuration: item.duration || row.expectedDuration,
      probe: reprobe ? undefined : row.probe, hold: reprobe ? undefined : row.hold,
    } satisfies Row,
  }
}

export function mergeRemoteShares(rows: Row[], created: Row[], items: ParsedSource[], clientFound: boolean) {
  const added: Row[] = []
  const reprobe: Row[] = []
  if (!items.length || (!created.length && clientFound)) return { rows, added, reprobe }
  if (!created.length) {
    const seen = new Set(rows.map((entry) => entry.source))
    const next = rows.slice()
    for (const item of items) {
      if ([...seen].some((url) => sameLink(url, item.url))) continue
      seen.add(item.url)
      const entry: Row = {
        id: crypto.randomUUID(), source: item.url, kind: item.source_kind, title: item.title,
        author: item.author, site: item.platform, expectedDuration: item.duration, fresh: true,
      }
      added.push(entry)
      next.push(entry)
    }
    return { rows: next, added, reprobe }
  }
  const { pairs, extras } = matchRemote(created.map((row) => ({ id: row.id, url: row.source })), items)
  const seen = new Set(rows.map((entry) => entry.source))
  const next = rows.map((row) => {
    const pair = pairs.find((entry) => entry.id === row.id)
    if (!pair) return row
    const patched = withRemoteShare(row, pair.item)
    if (patched.reprobe) reprobe.push(patched.row)
    if (patched.row.source !== row.source) {
      seen.delete(row.source)
      seen.add(patched.row.source)
    }
    return patched.row
  })
  for (const item of extras) {
    if ([...seen].some((url) => sameLink(url, item.url))) continue
    seen.add(item.url)
    const entry: Row = {
      id: crypto.randomUUID(), source: item.url, kind: item.source_kind, title: item.title,
      author: item.author, site: item.platform, expectedDuration: item.duration, fresh: true,
    }
    added.push(entry)
    next.push(entry)
  }
  return { rows: next, added, reprobe }
}

export function rowTitle(row: Row, task?: Item) {
  const probed = row.probe?.ready ? row.probe.title?.trim() : ''
  const taskTitle = task?.source_title || (!task?.result?.bilibili_url ? task?.result?.title : '')
  if (probed) return probed
  if (row.title?.trim()) return row.title.trim()
  if (taskTitle?.trim()) return taskTitle.trim()
  if (row.kind === 'local') return leaf(row.source)
  return row.site || '未命名'
}

export function rowSite(row: Row) {
  if (row.probe?.ready && row.probe.platform) return row.probe.platform
  return row.site || (row.kind === 'local' ? '本地文件' : siteOf(row.source))
}

export type CardAction = 'login-douyin' | 'login-xhs' | 'muxed' | 'replace' | 'to-notes' | 'open-note' | 'to-publish' | 'retry'

export const actionLabel: Record<CardAction, string> = {
  'login-douyin': '登录抖音',
  'login-xhs': '登录小红书',
  muxed: '允许提取音轨',
  replace: '更换链接',
  'to-notes': '改到笔记',
  'open-note': '打开笔记',
  'to-publish': '做成投稿',
  retry: '重试这一条',
}

function loginAction(row: Row, message: string): CardAction | null {
  const site = rowSite(row)
  if (site === '抖音' || /抖音/.test(message)) return 'login-douyin'
  if (site === '小红书' || /小红书/.test(message)) return 'login-xhs'
  return null
}

function readableFailure(text: string) {
  if (text.includes('ffmpeg version') || text.includes('does not contain any stream')) return '这条视频只有画面，没有音轨，无法听写。'
  const line = text.split('\n').map((item) => item.trim()).filter(Boolean).at(-1) || text
  return line.length > 180 ? line.slice(0, 180) + '…' : line
}

function needsLogin(message: string, code?: string) {
  return code === 'session_required' || code === 'site_blocked' || /登录|Cookie|403|会话/.test(message)
}

function videoNote(row: Row) {
  if (row.probe?.ready) return row.probe.media_type === 'video'
  return row.kind === 'youtube' || row.kind === 'bilibili' || /\.(mp4|mkv|mov|webm|avi|m4v|wmv|mpeg|mpg|ts)$/i.test(row.source)
}

export function presentCard(row: Row, inbox: 'publish' | 'notes', task?: Item) {
  const title = rowTitle(row, task)
  const site = rowSite(row)
  const transcriptId = row.transcriptId || task?.result?.transcript_id
  const image = isImageNote(row)
  const failed = task?.status === 'failed'
  const failure = failed ? readableFailure(task?.error?.message || task?.message || '失败') : ''
  let action: CardAction | undefined

  if (inbox === 'publish' && (blockedNote(row) || (row.probe && (image || (row.probe.ready && row.probe.media_type !== 'video'))))) action = 'to-notes'
  else if (row.probe && !row.probe.ready) {
    if (!(inbox === 'notes' && image)) {
      action = needsLogin(row.probe.message, row.probe.code) ? (loginAction(row, row.probe.message) || 'replace') :
        row.probe.code === 'muxed_audio' ? 'muxed' : 'replace'
    }
  } else if (!transcriptId && inbox === 'notes' && row.probe?.ready && row.probe.media_type === 'video' && !row.probe.audio_direct && !row.allowMuxed && !row.submitted) {
    action = 'muxed'
  } else if (failed) {
    if (needsLogin(failure)) action = loginAction(row, failure) || 'replace'
    else if (/合流|提取音轨/.test(failure)) action = 'muxed'
    else if (transcriptId && inbox === 'publish') action = 'open-note'
    else if (task?.stage === 'download') action = /没有找到可下载|尚未解析/.test(failure) ? 'replace' : 'retry'
    else action = 'retry'
  } else if (row.hold && needsLogin(row.hold)) action = loginAction(row, row.hold) || undefined
  else if (row.hold && /合流|提取音轨/.test(row.hold)) action = 'muxed'
  else if (inbox === 'publish' && transcriptId) action = 'open-note'
  else if (inbox === 'notes' && transcriptId && videoNote(row)) action = 'to-publish'

  let status = ''
  if (failed) status = failure
  else if (task && (task.status === 'running' || task.status === 'queued')) {
    status = [site, task.status === 'queued' ? '排队' : stageName(task.stage), task.status === 'running' && task.progress ? task.progress + '%' : ''].filter(Boolean).join(' · ')
  } else if (task?.status === 'succeeded') status = [site, inbox === 'publish' ? '已投稿' : '可以阅读'].filter(Boolean).join(' · ')
  else if (row.submitted) status = '正在提交'
  else if (inbox === 'publish' && blockedNote(row)) status = row.hold?.includes('没有可烧录的视频') ? row.hold : noteOnlyMessage
  else if (inbox === 'publish' && row.probe && (image || (row.probe.ready && row.probe.media_type !== 'video'))) status = '没有可烧录的视频'
  else if (!row.probe) status = [site, row.author, '正在识别'].filter(Boolean).join(' · ')
  else if (!row.probe.ready) status = inbox === 'notes' && image ? [site, '图文笔记'].filter(Boolean).join(' · ') : row.probe.message
  else if (image) status = [site, '图文笔记'].filter(Boolean).join(' · ')
  else if (action === 'muxed') status = '只有合流，允许后才能提取音轨'
  else if (inbox === 'publish' && row.transcriptId && !row.submitted) status = row.continueFrom ? '已有字幕，从烧录继续' : '已有字幕，待投稿'
  else if (row.hold) status = row.hold
  else status = [site, row.author, inbox === 'publish' ? '待投稿' : '待整理'].filter(Boolean).join(' · ')

  return { title, status, action }
}

export function activityLine(rows: Row[], taskOf: (row: Row) => Item | undefined) {
  const active = rows.flatMap((row) => {
    const task = taskOf(row)
    return task && (task.status === 'running' || task.status === 'queued') ? [{ row, task }] : []
  })
  if (!active.length) return ''
  const current = active.find((entry) => entry.task.status === 'running') || active[0]
  const verb = current.task.status === 'queued' ? '排队' : '正在' + (stageName(current.task.stage) || '处理')
  return verb + ' · ' + rowTitle(current.row, current.task) + (active.length > 1 ? ' · 共 ' + active.length + ' 项' : '')
}

export function filePath(file: File) {
  const path = (file as File & { path?: string }).path
  return path || ''
}

export function pathsFromUriList(value: string) {
  return value.split(/\r?\n/).flatMap((line) => {
    if (!line.startsWith('file:')) return []
    try {
      const url = new URL(line)
      let path = decodeURIComponent(url.pathname)
      if (/^\/[A-Za-z]:/.test(path)) path = path.slice(1)
      return path ? [path] : []
    } catch { return [] }
  })
}

export function useWindowInbox(active: boolean, onText: (text: string) => void, onFiles: (files: File[], uris: string) => void) {
  const textRef = useRef(onText)
  const fileRef = useRef(onFiles)
  textRef.current = onText
  fileRef.current = onFiles
  useEffect(() => {
    if (!active) return
    const typing = (target: EventTarget | null) => target instanceof HTMLElement &&
      Boolean(target.closest('input, textarea, [contenteditable="true"]') && !target.closest('.paste-input'))
    const onPaste = (event: ClipboardEvent) => {
      if (document.querySelector('dialog[open]') || typing(event.target)) return
      const files = event.clipboardData ? [...event.clipboardData.files] : []
      const text = event.clipboardData?.getData('text/plain') || ''
      if (!files.length && !text.trim()) return
      event.preventDefault()
      if (files.length) fileRef.current(files, '')
      else textRef.current(text)
    }
    const over = (event: DragEvent) => {
      if (!event.dataTransfer) return
      event.preventDefault()
      event.dataTransfer.dropEffect = 'copy'
    }
    const drop = (event: DragEvent) => {
      if (document.querySelector('dialog[open]')) return
      event.preventDefault()
      const files = event.dataTransfer ? [...event.dataTransfer.files] : []
      const text = event.dataTransfer?.getData('text/plain') || ''
      const uris = event.dataTransfer?.getData('text/uri-list') || ''
      if (files.length || uris) fileRef.current(files, uris)
      else if (text.trim()) textRef.current(text)
    }
    window.addEventListener('paste', onPaste)
    window.addEventListener('dragover', over)
    window.addEventListener('drop', drop)
    return () => {
      window.removeEventListener('paste', onPaste)
      window.removeEventListener('dragover', over)
      window.removeEventListener('drop', drop)
    }
  }, [active])
}

export function PasteBar({ value, onChange, placeholder, onAdd, addLabel, onStart, startLabel, startDisabled, hint }: {
  value: string; onChange: (value: string) => void; placeholder: string; onAdd: () => void; addLabel: string
  onStart: () => void; startLabel: string; startDisabled?: boolean; hint?: string
}) {
  return <form className="paste-bar" onSubmit={(event) => { event.preventDefault(); onAdd() }}>
    <textarea className="paste-input" rows={2} value={value} placeholder={placeholder}
      aria-label={placeholder} onChange={(event) => onChange(event.target.value)}
      onKeyDown={(event) => {
        if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) { event.preventDefault(); onAdd() }
      }}/>
    <div className="paste-actions">
      <Button variant="secondary" type="submit">{addLabel}</Button>
      <Button type="button" disabled={startDisabled} onClick={onStart}>{startLabel}</Button>
    </div>
    {hint && <p className="paste-hint" role="alert">{hint}</p>}
  </form>
}

export function InboxCard({ id, title, status, selected, fresh, action, extra, onSelect, onAction, onExtra, onSettled }: {
  id: string; title: string; status: string; selected: boolean; fresh?: boolean; action?: string; extra?: string
  onSelect: () => void; onAction?: () => void; onExtra?: () => void; onSettled: () => void
}) {
  const settled = useRef(onSettled)
  settled.current = onSettled
  useEffect(() => {
    if (!fresh) return
    const timer = window.setTimeout(() => settled.current(), 450)
    return () => window.clearTimeout(timer)
  }, [fresh])
  return <article id={'card-' + id} className={'inbox-card' + (selected ? ' selected' : '')} data-fresh={fresh ? '' : undefined}
    onAnimationEnd={(event) => { if (event.target === event.currentTarget) onSettled() }}>
    <button type="button" className="inbox-card-hit" aria-pressed={selected} onClick={onSelect}>
      <strong>{title}</strong>
      <span>{status}</span>
    </button>
    {(action && onAction || extra && onExtra) && <div className="inbox-card-actions">
      {action && onAction && <Button variant="secondary" size="small" onClick={(event) => { event.stopPropagation(); onSelect(); onAction() }}>{action}</Button>}
      {extra && onExtra && <Button variant="ghost" size="small" onClick={(event) => { event.stopPropagation(); onSelect(); onExtra() }}>{extra}</Button>}
    </div>}
  </article>
}

export function InboxSplit({ queue, work }: { queue: ReactNode; work: ReactNode }) {
  return <div className="inbox-split">
    <div className="inbox-queue thin-scroll">{queue}</div>
    <div className="inbox-work thin-scroll">{work}</div>
  </div>
}
