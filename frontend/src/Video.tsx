import { useEffect, useRef, useState } from 'react'
import { errorMessage, leaf, native, parseSources, request, siteSession, videoLinkKind, watchBatch, type Batch, type Cue,
  type History, type Item, type Preflight, type Settings, type SourceKind, type SourceProbe, type Transcript } from './api'
import { actionLabel, activityLine, blockedNote, describedProbe, filePath, InboxCard, InboxSplit, isImageNote, mergeRemoteShares,
  PasteBar, pathsFromUriList, presentCard, publishEmpty, rowSite, rowTitle, useWindowInbox, type CardAction, type NoteHandoff, type VideoTransfer } from './inbox'
import { parseShareText, siteOf, type ParsedShare } from './shareText'
import { clearSiteSession, loginLabel, loginUrl, openSiteLogin, sessionForSource, storeSiteSession, type LoginSite, type SiteLogin } from './siteSessions'
import { parseSrt } from './srt'
import { Button, Feedback, Modal, useActions } from './ui'
import { getOverride, Inspector, outputDefaults, resolveOptions, savedVideoOptions, videoPayload,
  type DefaultGroup, type InspectorSection, type Row, type VideoDefaults, type VideoOptions } from './videoOptions'

export type { VideoTransfer }

type Confirm = { titles: string[]; run: () => Promise<void> }
type TaskRecord = { batchId: string; task: Item }

function kindOf(url: string): SourceKind {
  try { return videoLinkKind(url) } catch { return 'url' }
}

function captionText(mode: string, order: string, original: string, translated?: string) {
  if (mode === 'zh_only') return translated || original
  if (mode !== 'bilingual') return original
  return (order === 'zh_top_en_bottom' ? [translated, original] : [original, translated]).filter(Boolean).join('\n')
}

function readyVideo(title: string, platform: string): SourceProbe {
  return { ready: true, title, platform, media_type: 'video', duration: null, has_audio: true, audio_direct: true }
}

function handoffOf(row: Row, task?: Item): NoteHandoff {
  const note = blockedNote(row)
  const probe = row.probe?.ready && note && row.probe.media_type !== 'note'
    ? { ...row.probe, media_type: 'note' as const, has_audio: false, audio_direct: false, body: row.probe.body || row.body }
    : row.probe
  return {
    source: row.source, kind: row.kind, title: rowTitle(row, task), author: row.author || (probe?.ready ? probe.author : undefined),
    site: rowSite(row), transcriptId: row.transcriptId || task?.result?.transcript_id,
    translationUrl: row.translationUrl || task?.result?.translated_srt_url,
    probe, imageNote: note || isImageNote(row), images: row.images || probe?.images,
    body: row.body || (probe?.ready ? probe.body || probe.description : ''), sessionId: row.sessionId,
  }
}

export function Video({ settings, transfer, onTransferUsed, onOpenNote, onActivity, onSettings, active }: {
  settings: Settings | null
  transfer: VideoTransfer | null
  onTransferUsed: () => void
  onOpenNote: (note: NoteHandoff) => void
  onActivity: (line: string) => void
  onSettings: (section: 'deepseek' | 'bilibili') => void
  active: boolean
}) {
  const [rows, setRows] = useState<Row[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [draft, setDraft] = useState('')
  const [hint, setHint] = useState('')
  const [replacing, setReplacing] = useState('')
  const [panel, setPanel] = useState<'preview' | 'style' | 'publish'>('preview')
  const [defaults, setDefaults] = useState<VideoDefaults | null>(null)
  const [batchEdits, setBatchEdits] = useState<ReturnType<typeof getOverride>>({})
  const [section, setSection] = useState<InspectorSection>('style')
  const [savingDefault, setSavingDefault] = useState<DefaultGroup | null>(null)
  const [tasks, setTasks] = useState<Record<string, TaskRecord>>({})
  const [confirm, setConfirm] = useState<Confirm | null>(null)
  const [pending, setPending] = useState(false)
  const [preview, setPreview] = useState({ key: '', url: '' })
  const [cues, setCues] = useState<Cue[]>([])
  const [translations, setTranslations] = useState<Map<number, string>>(new Map())
  const [played, setPlayed] = useState(0)
  const watches = useRef(new Map<string, () => void>())
  const rowsRef = useRef(rows)
  const fileInput = useRef<HTMLInputElement>(null)
  const loginRow = useRef<Row | null>(null)
  const { notice, setNotice, perform } = useActions()
  rowsRef.current = rows
  const saved = savedVideoOptions(defaults)
  const publishSaved = { ...saved, subtitle_output_mode: saved.subtitle_output_mode === 'en_only' ? 'bilingual' : saved.subtitle_output_mode }
  const base = resolveOptions(publishSaved, batchEdits)
  const row = rows.find((entry) => entry.id === selectedId)
  const task = row ? tasks[row.id]?.task : undefined
  const card = row ? presentCard(row, 'publish', task) : undefined

  function changeRow(id: string, change: Partial<Row>) {
    setRows((current) => current.map((entry) => entry.id === id ? { ...entry, ...change } : entry))
  }
  function remove(id: string) {
    setRows((current) => current.filter((entry) => entry.id !== id))
    setSelectedId((current) => current === id ? '' : current)
  }
  async function identify(entry: Row, refresh = false) {
    changeRow(entry.id, { probe: undefined })
    let probe: SourceProbe
    try {
      probe = await request<SourceProbe>('/desktop/sources/probe' + (refresh ? '?refresh=true' : ''), 'POST', {
        source_kind: entry.kind, source_value: entry.source, session_id: entry.sessionId || sessionForSource(entry.source),
      })
    } catch (error) { probe = { ready: false, code: 'unavailable', message: errorMessage(error) } }
    setRows((current) => current.map((item) => item.id === entry.id && item.source === entry.source ? describedProbe(item, probe) : item))
  }
  function watch(batchId: string) {
    if (watches.current.has(batchId)) return
    const stop = watchBatch(batchId, (next) => {
      setTasks((current) => {
        const updated = { ...current }
        for (const item of next.items) {
          const alias = Object.keys(updated).find((key) => updated[key].batchId === next.batch_id && updated[key].task.item_id === item.item_id)
          const key = alias || (updated[item.client_row_id] ? item.client_row_id : next.batch_id + ':' + item.client_row_id)
          if (alias || updated[item.client_row_id] || rowsRef.current.some((entry) => entry.id === key)) updated[key] = { batchId: next.batch_id, task: item }
        }
        return updated
      })
      if (!next.queued && !next.running) {
        watches.current.get(next.batch_id)?.()
        watches.current.delete(next.batch_id)
      }
    }, () => {})
    watches.current.set(batchId, stop)
  }
  function remember(created: Row[]) {
    if (!created.length) return
    setSelectedId(created[0].id)
    setPanel('preview')
    created.forEach((entry) => { if (!entry.imageNote && !entry.probe) void identify(entry) })
    window.setTimeout(() => document.getElementById('card-' + created[0].id)?.scrollIntoView({ block: 'nearest' }), 40)
  }
  function addShares(parsed: ParsedShare[], text = '') {
    if (!parsed.length) {
      setHint('没有找到链接')
      if (text.trim()) void adoptShares([], text, false)
      return
    }
    setHint('')
    const created: Row[] = []
    const replaceId = replacing
    setRows((current) => {
      const seen = new Set(current.map((entry) => entry.source))
      let next = current
      const shares = parsed.slice()
      if (replaceId) {
        const share = shares.shift()
        if (share) {
          seen.delete(current.find((entry) => entry.id === replaceId)?.source || '')
          if (!seen.has(share.url)) {
            seen.add(share.url)
            next = current.map((entry) => entry.id === replaceId ? {
              ...entry, source: share.url, kind: kindOf(share.url), title: share.title || entry.title, author: share.author,
              site: share.site, expectedDuration: share.duration, probe: undefined, hold: undefined, submitted: false, transcriptId: undefined,
              continueFrom: undefined, translationUrl: undefined, sessionId: undefined, fresh: true, imageNote: false,
              batchId: undefined, itemId: undefined,
            } : entry)
            const updated = next.find((entry) => entry.id === replaceId)
            if (updated) created.push(updated)
          }
        }
      }
      for (const share of shares) {
        if (seen.has(share.url)) continue
        seen.add(share.url)
        const entry: Row = {
          id: crypto.randomUUID(), source: share.url, kind: kindOf(share.url), title: share.title, author: share.author,
          site: share.site, expectedDuration: share.duration, fresh: true,
        }
        created.push(entry)
        next = [...next, entry]
      }
      return next
    })
    setReplacing('')
    setDraft('')
    remember(created)
    if (text.trim()) void adoptShares(created, text, true)
  }
  async function adoptShares(created: Row[], text: string, clientFound: boolean) {
    let items: Awaited<ReturnType<typeof parseSources>>['items'] = []
    try { items = (await parseSources(text)).items } catch { return }
    let added: Row[] = []
    let reprobe: Row[] = []
    setRows((current) => {
      const merged = mergeRemoteShares(current, created, items, clientFound)
      added = merged.added
      reprobe = merged.reprobe
      return merged.rows
    })
    if (added.length) setHint('')
    added.forEach((entry) => { if (!entry.probe) void identify(entry) })
    reprobe.forEach((entry) => { if (!entry.imageNote) void identify(entry) })
  }
  function addPaths(paths: string[]) {
    const created: Row[] = []
    setRows((current) => {
      const seen = new Set(current.map((entry) => entry.source))
      let next = current
      for (const source of paths) {
        if (!source || seen.has(source)) continue
        seen.add(source)
        const image = isImageNote({ source, site: '本地文件' })
        const entry: Row = {
          id: crypto.randomUUID(), source, kind: 'local', title: leaf(source), site: '本地文件', fresh: true, imageNote: image,
          probe: image ? { ready: true, title: leaf(source), platform: '本地文件', media_type: 'image', duration: null, has_audio: false, audio_direct: false } : undefined,
        }
        created.push(entry)
        next = [...next, entry]
      }
      return next
    })
    remember(created)
  }
  function addImageFiles(files: File[]) {
    const created: Row[] = files.map((file) => ({
      id: crypto.randomUUID(), source: file.name, kind: 'local' as const, title: file.name.replace(/\.[^.]+$/, ''),
      site: '本地文件', fresh: true, imageNote: true, images: [URL.createObjectURL(file)],
      probe: { ready: true, title: file.name, platform: '本地文件', media_type: 'image' as const, duration: null, has_audio: false, audio_direct: false },
    }))
    setRows((current) => [...current, ...created])
    remember(created)
  }
  function addFiles(files: File[], uris: string) {
    const paths = [...new Set([...files.map(filePath).filter(Boolean), ...pathsFromUriList(uris)])]
    const looseImages = files.filter((file) => file.type.startsWith('image/') && !filePath(file))
    if (paths.length) addPaths(paths)
    if (looseImages.length) addImageFiles(looseImages)
    if (!paths.length && files.some((file) => !file.type.startsWith('image/') && !filePath(file))) setHint('本地视频请用加入投稿从磁盘选择。')
  }
  useWindowInbox(active, (text) => addShares(parseShareText(text), text), addFiles)

  useEffect(() => {
    let alive = true
    void request<VideoDefaults>('/desktop/video-defaults').then((data) => { if (alive) setDefaults(data) }).catch((error) => {
      if (alive) setNotice({ error: true, text: errorMessage(error) })
    })
    const reload = () => { void request<VideoDefaults>('/desktop/video-defaults').then((next) => { if (alive) setDefaults(next) }).catch(() => {}) }
    window.addEventListener('video-defaults-changed', reload)
    return () => { alive = false; window.removeEventListener('video-defaults-changed', reload) }
  }, [setNotice])

  useEffect(() => () => { watches.current.forEach((stop) => stop()); watches.current.clear() }, [])

  useEffect(() => {
    let alive = true
    void (async () => {
      try {
        const history = await request<History[]>('/desktop/batches')
        const batches = await Promise.all(history.slice(0, 4).map((entry) => request<Batch>('/ui/batches/' + encodeURIComponent(entry.batch_id))))
        if (!alive) return
        const seeded: Row[] = []
        const seededTasks: Record<string, TaskRecord> = {}
        for (const batch of batches) {
          for (const item of batch.items) {
            const id = batch.batch_id + ':' + (item.client_row_id || item.item_id)
            seeded.push({
              id, source: item.source_value, kind: item.source_kind, title: item.source_title || item.result?.title,
              site: item.platform || siteOf(item.source_value) || (item.source_kind === 'local' ? '本地文件' : ''),
              transcriptId: item.result?.transcript_id, translationUrl: item.result?.translated_srt_url, submitted: true,
              batchId: batch.batch_id, itemId: item.item_id,
              probe: item.media_type ? {
                ready: true, title: item.source_title || item.result?.title, platform: item.platform || siteOf(item.source_value) || '链接',
                media_type: item.media_type, duration: item.duration ?? null, has_audio: item.media_type !== 'note',
                audio_direct: item.media_type !== 'video' && item.media_type !== 'note',
                description: item.result?.original_description,
              } : undefined,
              imageNote: item.media_type === 'note',
            })
            seededTasks[id] = { batchId: batch.batch_id, task: item }
          }
        }
        if (!seeded.length) return
        setRows((current) => {
          const known = new Set(current.map((entry) => entry.source))
          return [...current, ...seeded.filter((entry) => !known.has(entry.source))]
        })
        setTasks((current) => ({ ...seededTasks, ...current }))
        setSelectedId((current) => current || seeded[0].id)
        new Set(batches.filter((batch) => batch.queued || batch.running).map((batch) => batch.batch_id)).forEach(watch)
      } catch { /* A history miss still leaves the paste field usable. */ }
    })()
    return () => { alive = false }
  }, [])

  useEffect(() => {
    if (!transfer) return
    const id = crypto.randomUUID()
    const site = transfer.site || siteOf(transfer.source)
    let picked: string = id
    setRows((current) => {
      const existing = current.find((entry) => entry.source === transfer.source && entry.kind === transfer.kind)
      if (existing) {
        picked = existing.id
        return current.map((entry) => entry.id === existing.id ? {
          ...entry, transcriptId: transfer.id, continueFrom: transfer.continueFrom || entry.continueFrom,
          title: entry.title || transfer.title, author: entry.author || transfer.author, site: entry.site || site,
          probe: entry.probe?.ready ? entry.probe : readyVideo(transfer.title || entry.title || '', site || '视频'),
        } : entry)
      }
      return [...current, {
        id, source: transfer.source, kind: transfer.kind, title: transfer.title, author: transfer.author, site,
        transcriptId: transfer.id, continueFrom: transfer.continueFrom, fresh: true,
        probe: readyVideo(transfer.title || '', site || '视频'),
      }]
    })
    setSelectedId(picked)
    setPanel('preview')
    onTransferUsed()
  }, [transfer, onTransferUsed])

  useEffect(() => {
    setRows((current) => {
      let changed = false
      const next = current.map((entry) => {
        const record = tasks[entry.id]
        if (!record) return entry
        const transcriptId = record.task.result?.transcript_id || entry.transcriptId
        const translationUrl = record.task.result?.translated_srt_url || entry.translationUrl
        if (entry.transcriptId === transcriptId && entry.translationUrl === translationUrl && entry.batchId === record.batchId && entry.itemId === record.task.item_id) return entry
        changed = true
        return { ...entry, transcriptId, translationUrl, batchId: record.batchId, itemId: record.task.item_id, submitted: true }
      })
      return changed ? next : current
    })
  }, [tasks])

  useEffect(() => { onActivity(activityLine(rows, (entry) => tasks[entry.id]?.task)) }, [rows, tasks, onActivity])

  useEffect(() => {
    if (!active) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Delete' && event.key !== 'Backspace') return
      if (event.target instanceof HTMLElement && event.target.closest('input, textarea, [contenteditable="true"]')) return
      const current = rowsRef.current.find((entry) => entry.id === selectedId)
      const running = current && tasks[current.id]?.task
      if (!current || running?.status === 'running' || running?.status === 'queued') return
      event.preventDefault()
      remove(current.id)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [active, selectedId, tasks])

  useEffect(() => {
    const onSite = (event: Event) => {
      const detail = (event as CustomEvent<Partial<SiteLogin> & { site?: string }>).detail
      if (detail && 'logged_in' in detail && !detail.logged_in) return
      const label = loginLabel(detail)
      const siteId = detail?.logged_in === true && (detail.site === 'douyin' || detail.site === 'xiaohongshu') ? detail.site : ''
      if (siteId) clearSiteSession(siteId)
      rowsRef.current.filter((entry) => entry.probe && !entry.probe.ready && (label ? rowSite(entry) === label : rowSite(entry) === '抖音' || rowSite(entry) === '小红书'))
        .forEach((entry) => {
          const sessionId = siteId ? '' : (sessionForSource(entry.source) || entry.sessionId || '')
          if (siteId && entry.sessionId) changeRow(entry.id, { sessionId: '' })
          void identify({ ...entry, sessionId }, true)
        })
    }
    window.addEventListener('site-session', onSite)
    window.addEventListener('site-login', onSite)
    return () => {
      window.removeEventListener('site-session', onSite)
      window.removeEventListener('site-login', onSite)
    }
  }, [])

  useEffect(() => {
    const transcriptId = row?.transcriptId || task?.result?.transcript_id
    if (!transcriptId) { setCues([]); return }
    let alive = true
    void request<Transcript>('/desktop/knowledge/' + transcriptId).then((data) => { if (alive) setCues(data.cues) }).catch(() => {})
    return () => { alive = false }
  }, [row?.transcriptId, task?.result?.transcript_id])

  const translationUrl = row?.translationUrl || task?.result?.translated_srt_url || ''
  useEffect(() => {
    if (!translationUrl) { setTranslations(new Map()); return }
    let alive = true
    void fetch(translationUrl).then((response) => response.text()).then((text) => { if (alive) setTranslations(parseSrt(text)) }).catch(() => {})
    return () => { alive = false }
  }, [translationUrl])

  const finalUrl = task?.result?.final_video_url || ''
  const sourceUrl = task?.result?.asset_type === 'video' ? task.result.source_video_url || '' : ''
  const previewKey = JSON.stringify([row?.id, row?.source, base.aspect_ratio, base.resolution, base.subtitle_output_mode, base.subtitle_style])
  const previewable = panel === 'preview' && Boolean(row?.probe?.ready && row.probe.media_type === 'video' && !finalUrl && !sourceUrl)
  useEffect(() => {
    if (!previewable || !row) return
    let alive = true
    const timer = window.setTimeout(() => {
      void request<{ preview_image_url?: string }>('/ui/preview-frame', 'POST', {
        source_kind: row.kind, source_value: row.source, aspect_ratio: base.aspect_ratio, resolution: base.resolution,
        fps: base.fps, subtitle_output_mode: base.subtitle_output_mode, subtitle_style: base.subtitle_style, preview_time_percent: 50,
      }).then((data) => {
        if (alive && data.preview_image_url?.startsWith('/files/')) setPreview({ key: previewKey, url: data.preview_image_url })
      }).catch(() => {})
    }, 280)
    return () => { alive = false; window.clearTimeout(timer) }
  }, [previewable, previewKey])

  function payloadFor(candidates: Row[]) {
    const filing = resolveOptions(base, { bilibili_upload: { enabled: true } })
    return {
      ...videoPayload(filing, settings?.ai_model || 'deepseek-flash'),
      batch_concurrency: 2, rights_confirmed: true, item_overrides: {}, publish_confirmed: [] as string[],
      sources: candidates.map((entry) => ({
        source_kind: entry.kind, source_value: entry.source, source_title: rowTitle(entry).slice(0, 500), client_row_id: entry.id,
        stop_after: 'bilibili_upload' as const, allow_muxed_audio: Boolean(entry.allowMuxed), allow_unknown_audio: Boolean(entry.unknownAudio),
        session_id: entry.sessionId || sessionForSource(entry.source),
        ...(entry.expectedDuration ? { expected_duration: entry.expectedDuration } : {}),
        ...(entry.continueFrom ? { continue_from: entry.continueFrom } : {}),
      })),
      transcript_ids: Object.fromEntries(candidates.flatMap((entry) => entry.transcriptId ? [[entry.id, entry.transcriptId]] : [])),
    }
  }
  async function postStart(payload: ReturnType<typeof payloadFor>, ids: string[]) {
    const sources = payload.sources.filter((source) => ids.includes(source.client_row_id))
    const filed = { ...payload, sources, publish_confirmed: sources.map((source) => source.client_row_id) }
    const { knowledge_only: _knowledgeOnly, ...body } = filed as typeof filed & { knowledge_only?: boolean }
    void _knowledgeOnly
    let data: Batch
    try {
      data = await request<Batch>('/ui/batches', 'POST', body)
    } catch (error) {
      const message = errorMessage(error)
      if (message.includes('没有可烧录的视频')) {
        setRows((current) => current.map((entry) => ids.includes(entry.id) ? { ...entry, submitted: false, hold: message } : entry))
        return
      }
      throw error
    }
    setRows((current) => current.map((entry) => sources.some((source) => source.client_row_id === entry.id) ? { ...entry, submitted: true, hold: undefined, sessionId: undefined } : entry))
    setTasks((current) => ({ ...current, ...Object.fromEntries(data.items.map((item) => [item.client_row_id, { task: item, batchId: data.batch_id }])) }))
    if (data.queued || data.running) watch(data.batch_id)
  }
  async function postRetry(batchId: string, itemId: string, uploadChecked: boolean) {
    const data = await request<Batch>('/desktop/batches/' + batchId + '/' + itemId + '/retry', 'POST', { upload_checked: uploadChecked })
    setTasks((current) => {
      const updated = { ...current }
      for (const item of data.items) {
        const key = Object.keys(updated).find((id) => updated[id].batchId === data.batch_id && updated[id].task.item_id === item.item_id) || item.client_row_id
        updated[key] = { batchId: data.batch_id, task: item }
      }
      return updated
    })
    watch(data.batch_id)
  }
  function start() {
    if (!settings?.has_ai_key) { onSettings('deepseek'); return }
    if (!settings.has_bilibili_credentials) { onSettings('bilibili'); return }
    const candidates = rows.filter((entry) => !entry.submitted && !blockedNote(entry) && entry.probe?.ready && entry.probe.media_type === 'video' && !isImageNote(entry))
    if (pending || !candidates.length) return
    perform(async () => {
      setPending(true)
      try {
        let payload = payloadFor(candidates)
        let decisions = await request<Preflight>('/desktop/batches/preflight', 'POST', payload)
        const stale = new Set(candidates.filter((entry) => {
          const decision = decisions[entry.id]
          return decision && !decision.ready && decision.message.includes('原任务没有可继续处理的字幕')
        }).map((entry) => entry.id))
        if (stale.size) {
          payload = { ...payload, sources: payload.sources.map((source) => stale.has(source.client_row_id) ? { ...source, continue_from: undefined } : source) }
          decisions = await request<Preflight>('/desktop/batches/preflight', 'POST', payload)
        }
        setRows((current) => current.map((entry) => {
          const decision = decisions[entry.id]
          if (!decision || decision.ready) return entry.hold ? { ...entry, hold: undefined } : entry
          return { ...entry, hold: decision.message }
        }))
        const publishing = candidates.filter((entry) => {
          const decision = decisions[entry.id]
          return Boolean(decision?.ready && decision.planned_stages.includes('bilibili_upload'))
        })
        if (!publishing.length) return
        const ids = publishing.map((entry) => entry.id)
        setConfirm({ titles: publishing.map((entry) => rowTitle(entry)), run: () => postStart(payload, ids) })
      } finally { setPending(false) }
    })
  }
  function runAction(entry: Row, action: CardAction) {
    const current = tasks[entry.id]?.task
    if (action === 'login-douyin' || action === 'login-xhs') {
      const site = action === 'login-xhs' ? 'xiaohongshu' : 'douyin'
      perform(async () => {
        let detail = ''
        const done = await openSiteLogin(site, undefined, (text) => { detail = text; setNotice({ text, error: true }) })
        if (done.logged_in) setNotice({ text: done.platform + '已登录' })
        else if (!detail) setNotice({ text: done.platform + '未完成登录', error: true })
      })
      return
    }
    if (action === 'muxed') { changeRow(entry.id, { allowMuxed: true, hold: undefined }); return }
    if (action === 'replace') { setReplacing(entry.id); setSelectedId(entry.id); setDraft(''); setPanel('preview'); return }
    if (action === 'to-notes') { onOpenNote(handoffOf(entry, current)); remove(entry.id); return }
    if (action === 'open-note') onOpenNote(handoffOf(entry, current))
    else if (action === 'retry' && current && entry.batchId && entry.itemId) {
      const batchId = entry.batchId
      const itemId = entry.itemId
      if (current.stage === 'bilibili_upload') setConfirm({ titles: [rowTitle(entry, current)], run: () => postRetry(batchId, itemId, true) })
      else perform(() => postRetry(batchId, itemId, false))
    }
  }
  function updateOptions(value: VideoOptions) { setBatchEdits(getOverride(publishSaved, value)) }
  function saveDefault(group: DefaultGroup) {
    perform(async () => {
      setSavingDefault(group)
      try {
        const next = await request<VideoDefaults>('/desktop/video-defaults', 'PUT', group === 'output' ? { output: outputDefaults(base) } : { subtitle_style: base.subtitle_style })
        setDefaults(next)
        window.dispatchEvent(new Event('video-defaults-changed'))
        setNotice({ text: group === 'output' ? '已保存默认输出参数' : '已保存默认字幕样式' })
      } finally { setSavingDefault(null) }
    })
  }
  const frame = preview.key === previewKey ? preview.url : ''
  const cue = cues.find((entry) => entry.start_ms <= played && entry.end_ms > played) || (played === 0 ? cues[0] : undefined)
  const translated = cue ? translations.get(cue.number) : ''
  const style = base.subtitle_style
  const ratio = base.aspect_ratio === '9:16' ? 'portrait' : base.aspect_ratio === '1:1' ? 'square' : ''
  const ready = rows.some((entry) => !entry.submitted && !blockedNote(entry) && entry.probe?.ready && entry.probe.media_type === 'video' && !isImageNote(entry))
  const showFrame = !row?.probe || Boolean(row.probe.ready && row.probe.media_type === 'video')

  return <div className="inbox">
    <PasteBar value={draft} onChange={(value) => { setDraft(value); setHint('') }}
      placeholder={replacing ? '贴上新的链接，更换这一条' : '链接或分享文案'} hint={hint}
      onAdd={() => { if (draft.trim()) addShares(parseShareText(draft), draft); else perform(async () => addPaths(await (await native()).choose_media(true))) }}
      addLabel="加入投稿" onStart={start} startLabel={pending ? '正在检查' : '开始投稿'} startDisabled={pending || !ready}/>
    {!rows.length ? <p className="inbox-empty">{publishEmpty}</p> : <InboxSplit
      queue={rows.map((entry) => {
        const view = presentCard(entry, 'publish', tasks[entry.id]?.task)
        const cookie = view.action === 'login-douyin' || view.action === 'login-xhs'
        return <InboxCard key={entry.id} id={entry.id} title={view.title} status={view.status} selected={entry.id === selectedId}
          fresh={entry.fresh} action={view.action ? actionLabel[view.action] : undefined}
          extra={cookie ? '导入 Cookie' : undefined}
          onSelect={() => { setSelectedId(entry.id); setPanel('preview') }}
          onAction={view.action ? () => runAction(entry, view.action!) : undefined}
          onExtra={cookie ? () => { loginRow.current = entry; fileInput.current?.click() } : undefined}
          onSettled={() => changeRow(entry.id, { fresh: false })}/>
      })}
      work={panel !== 'preview' ? <div className="work-sheet">
        <Button variant="secondary" onClick={() => setPanel('preview')}>返回预览</Button>
        <Inspector options={base} change={updateOptions} settings={settings} row={row} rowLabel={card?.title} perItem={false}
          onScope={() => {}} reset={() => setBatchEdits({})} section={panel === 'style' ? 'style' : 'publish'} onSection={setSection}
          defaultsReady={defaults !== null} savingDefault={savingDefault} onSaveDefault={saveDefault}
          onResetDefault={(group) => updateOptions({ ...base, ...(group === 'output' ? outputDefaults(publishSaved) : { subtitle_style: publishSaved.subtitle_style }) })}
          only={panel === 'style' ? 'style' : 'publish'} terminal="bilibili_upload"/>
      </div> : showFrame ? <div className="frame-row">
        <div className={'video-frame ' + ratio}>
          {finalUrl ? <video key={finalUrl} src={finalUrl} controls playsInline/> :
            sourceUrl ? <video key={sourceUrl} src={sourceUrl} controls playsInline onTimeUpdate={(event) => setPlayed(event.currentTarget.currentTime * 1000)}/> :
            frame ? <img src={frame} alt=""/> : null}
          {sourceUrl && cue && !finalUrl && <p className={'burn-caption ' + style.position} style={{
            color: style.primary_color, fontFamily: style.font_family, fontWeight: style.font_weight,
            textShadow: '0 1px ' + Math.max(1, style.outline_width) + 'px ' + style.outline_color,
          }}>{captionText(base.subtitle_output_mode, style.bilingual_order, cue.text, translated)}</p>}
        </div>
        <div className="frame-side">
          <p className="frame-status">{card?.status || '选择一条稿件'}</p>
          <Button variant="secondary" onClick={() => setPanel('style')}>调整字幕</Button>
          <Button variant="secondary" onClick={() => setPanel('publish')}>封面和分区</Button>
          {task?.status === 'failed' && card?.action !== 'retry' && row?.batchId && row.itemId &&
            <Button variant="secondary" onClick={() => runAction(row, 'retry')}>重试这一条</Button>}
          {task?.result?.bilibili_url && <Button variant="secondary" onClick={() => window.open(task.result?.bilibili_url, '_blank', 'noopener')}>查看稿件</Button>}
        </div>
      </div> : <p className="frame-status">{card?.status}</p>}/>}
    <Feedback notice={notice}/>
    <input ref={fileInput} hidden type="file" accept=".txt,text/plain" aria-label="选择本站 Cookie 文件" onChange={(event) => {
      const file = event.target.files?.[0]
      const entry = loginRow.current
      event.target.value = ''
      loginRow.current = null
      if (!file || !entry) return
      const site: LoginSite = rowSite(entry) === '小红书' ? '小红书' : '抖音'
      perform(async () => {
        const sessionId = await siteSession(entry.source || loginUrl[site], file)
        storeSiteSession(site, sessionId)
        const next = { ...entry, sessionId, hold: undefined }
        changeRow(entry.id, { sessionId, hold: undefined })
        await identify(next, true)
      })
    }}/>
    <Modal open={Boolean(confirm)} title="确认投稿" onClose={() => { if (!pending) setConfirm(null) }}>
      <p>这些标题会提交 B 站审核。</p>
      <ul className="launch-list">{confirm?.titles.map((title, index) => <li key={index}>{title}</li>)}</ul>
      <div className="toolbar modal-actions">
        <Button variant="secondary" disabled={pending} onClick={() => setConfirm(null)}>取消</Button>
        <Button disabled={pending} onClick={() => { if (!confirm) return; perform(async () => {
          setPending(true)
          try { await confirm.run(); setConfirm(null) } finally { setPending(false) }
        }) }}>确认投稿</Button>
      </div>
    </Modal>
  </div>
}
