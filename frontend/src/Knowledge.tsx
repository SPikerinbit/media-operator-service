import { useEffect, useRef, useState } from 'react'
import { errorMessage, leaf, native, parseSources, request, siteSession, videoLinkKind, watchBatch, type Batch, type History,
  type Item, type Preflight, type Settings, type SourceKind, type SourceProbe, type Transcript, type TranscriptSummary } from './api'
import { actionLabel, activityLine, describedProbe, filePath, InboxCard, InboxSplit, isImageNote, mergeRemoteShares, notesEmpty,
  PasteBar, pathsFromUriList, presentCard, rowSite, rowTitle, useWindowInbox, type CardAction, type NoteHandoff, type VideoTransfer } from './inbox'
import { parseShareText, siteOf, type ParsedShare } from './shareText'
import { clearSiteSession, loginLabel, loginUrl, openSiteLogin, sessionForSource, storeSiteSession, type LoginSite, type SiteLogin } from './siteSessions'
import { TranscriptView } from './TranscriptView'
import { Button, Feedback, useActions } from './ui'
import { resolveOptions, savedVideoOptions, videoPayload, type Row, type VideoDefaults } from './videoOptions'

function kindOf(url: string): SourceKind {
  try { return videoLinkKind(url) } catch { return 'url' }
}
const subtitleFile = (source: string) => /\.(srt|vtt)$/i.test(source)

export function Knowledge({ settings, transcriptId, incoming, onIncomingUsed, onVideo, onActivity, onSettings, active }: {
  settings: Settings | null
  transcriptId: number | null
  incoming: NoteHandoff | null
  onIncomingUsed: () => void
  onVideo: (transfer: VideoTransfer) => void
  onActivity: (line: string) => void
  onSettings: (section: 'deepseek' | 'obsidian') => void
  active: boolean
}) {
  const [rows, setRows] = useState<Row[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [draft, setDraft] = useState('')
  const [hint, setHint] = useState('')
  const [replacing, setReplacing] = useState('')
  const [defaults, setDefaults] = useState<VideoDefaults | null>(null)
  const [tasks, setTasks] = useState<Record<string, { batchId: string; task: Item }>>({})
  const [pending, setPending] = useState(false)
  const watches = useRef(new Map<string, () => void>())
  const rowsRef = useRef(rows)
  const fileInput = useRef<HTMLInputElement>(null)
  const loginRow = useRef<Row | null>(null)
  const { notice, setNotice, perform } = useActions()
  rowsRef.current = rows
  const base = resolveOptions(savedVideoOptions(defaults), { subtitle_output_mode: 'bilingual', bilibili_upload: { enabled: false } })
  const row = rows.find((entry) => entry.id === selectedId)
  const task = row ? tasks[row.id]?.task : undefined

  function changeRow(id: string, change: Partial<Row>) {
    setRows((current) => current.map((entry) => entry.id === id ? { ...entry, ...change } : entry))
  }
  function remove(id: string) {
    setRows((current) => current.filter((entry) => entry.id !== id))
    setSelectedId((current) => current === id ? '' : current)
  }
  async function identify(entry: Row, refresh = false) {
    if (entry.imageNote || subtitleFile(entry.source)) return
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
    created.forEach((entry) => { if (!entry.imageNote && !entry.probe && !subtitleFile(entry.source)) void identify(entry) })
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
              site: share.site, probe: undefined, hold: undefined, submitted: false, transcriptId: undefined,
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
    added.forEach((entry) => { if (!entry.imageNote && !subtitleFile(entry.source)) void identify(entry) })
    reprobe.forEach((entry) => { if (!entry.imageNote && !subtitleFile(entry.source)) void identify(entry) })
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
        const subtitle = subtitleFile(source)
        const entry: Row = {
          id: crypto.randomUUID(), source, kind: 'local', title: leaf(source), site: subtitle ? '字幕文件' : '本地文件', fresh: true,
          imageNote: image,
          probe: image || subtitle ? {
            ready: true, title: leaf(source), platform: subtitle ? '字幕文件' : '本地文件',
            media_type: image ? 'image' : 'unknown', duration: null, has_audio: false, audio_direct: true,
          } : undefined,
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
    if (!paths.length && files.some((file) => !file.type.startsWith('image/') && !filePath(file))) setHint('本地文件请用加入笔记从磁盘选择。')
  }
  useWindowInbox(active, (text) => addShares(parseShareText(text), text), addFiles)

  useEffect(() => {
    let alive = true
    void request<VideoDefaults>('/desktop/video-defaults').then((data) => { if (alive) setDefaults(data) }).catch(() => {})
    return () => { alive = false }
  }, [])
  useEffect(() => () => { watches.current.forEach((stop) => stop()); watches.current.clear() }, [])

  useEffect(() => {
    let alive = true
    void (async () => {
      try {
        const [library, history] = await Promise.all([
          request<TranscriptSummary[]>('/desktop/knowledge?q='),
          request<History[]>('/desktop/batches?knowledge_only=true'),
        ])
        if (!alive) return
        const seeded: Row[] = library.map((entry) => ({
          id: 'note-' + entry.id, source: entry.source || entry.title, kind: entry.source_kind === 'subtitle' ? 'local' : entry.source_kind,
          title: entry.title, site: entry.source_kind === 'subtitle' ? '字幕文件' : siteOf(entry.source), transcriptId: entry.id, submitted: true,
        }))
        const seededTasks: Record<string, { batchId: string; task: Item }> = {}
        const batches = await Promise.all(history.slice(0, 3).map((entry) => request<Batch>('/ui/batches/' + encodeURIComponent(entry.batch_id))))
        if (!alive) return
        for (const batch of batches) {
          for (const item of batch.items) {
            if (item.result?.transcript_id && seeded.some((entry) => entry.transcriptId === item.result?.transcript_id)) {
              const found = seeded.find((entry) => entry.transcriptId === item.result?.transcript_id)
              if (found) {
                found.batchId = batch.batch_id
                found.itemId = item.item_id
                found.translationUrl = item.result.translated_srt_url
                found.probe = item.media_type ? {
                  ready: true, platform: item.platform || found.site || '', media_type: item.media_type, duration: item.duration ?? null,
                  has_audio: item.media_type !== 'note', audio_direct: item.media_type !== 'video' && item.media_type !== 'note',
                  title: found.title,
                } : found.probe
                if (item.media_type === 'note') found.imageNote = true
              }
              continue
            }
            if (item.status === 'succeeded') continue
            const id = batch.batch_id + ':' + (item.client_row_id || item.item_id)
            seeded.unshift({
              id, source: item.source_value, kind: item.source_kind, title: item.source_title, site: item.platform || siteOf(item.source_value),
              submitted: true, batchId: batch.batch_id, itemId: item.item_id, translationUrl: item.result?.translated_srt_url,
              transcriptId: item.result?.transcript_id,
              probe: item.media_type ? {
                ready: true, title: item.source_title, platform: item.platform || siteOf(item.source_value) || '链接',
                media_type: item.media_type, duration: item.duration ?? null, has_audio: item.media_type !== 'note',
                audio_direct: item.media_type !== 'video' && item.media_type !== 'note',
              } : undefined,
              imageNote: item.media_type === 'note',
            })
            seededTasks[id] = { batchId: batch.batch_id, task: item }
          }
        }
        setRows((current) => {
          const known = new Set(current.flatMap((entry) => [entry.source, entry.transcriptId ? 'id:' + entry.transcriptId : '']))
          return [...current, ...seeded.filter((entry) => !known.has(entry.source) && !known.has('id:' + entry.transcriptId))]
        })
        setTasks((current) => ({ ...seededTasks, ...current }))
        batches.filter((batch) => batch.queued || batch.running).forEach((batch) => watch(batch.batch_id))
      } catch (error) { if (alive) setNotice({ error: true, text: errorMessage(error) }) }
    })()
    return () => { alive = false }
  }, [setNotice])

  useEffect(() => {
    if (!incoming) return
    let picked = ''
    setRows((current) => {
      const existing = current.find((entry) => (incoming.transcriptId && entry.transcriptId === incoming.transcriptId) || entry.source === incoming.source)
      if (existing) {
        picked = existing.id
        return current.map((entry) => entry.id === existing.id ? {
          ...entry, ...incoming, id: entry.id, fresh: false, title: incoming.title || entry.title, probe: incoming.probe || entry.probe,
          imageNote: incoming.imageNote || entry.imageNote, transcriptId: incoming.transcriptId || entry.transcriptId,
        } : entry)
      }
      picked = crypto.randomUUID()
      return [...current, { ...incoming, id: picked, fresh: true, site: incoming.site || siteOf(incoming.source) }]
    })
    setSelectedId(picked)
    onIncomingUsed()
  }, [incoming, onIncomingUsed])

  useEffect(() => {
    if (!row?.transcriptId || row.probe?.ready) return
    let alive = true
    void request<Transcript>('/desktop/knowledge/' + row.transcriptId).then((doc) => {
      if (!alive || !doc.media_type) return
      changeRow(row.id, {
        title: row.title || doc.title,
        body: row.body || doc.body || doc.description,
        images: row.images?.length ? row.images : doc.images,
        imageNote: row.imageNote || doc.media_type === 'note' || doc.media_type === 'image',
        probe: {
          ready: true, title: doc.title, platform: row.site || siteOf(row.source), media_type: doc.media_type,
          duration: null, has_audio: doc.media_type === 'audio' || doc.media_type === 'video',
          audio_direct: doc.media_type === 'audio', body: doc.body || doc.description, images: doc.images,
        },
      })
    }).catch(() => {})
    return () => { alive = false }
  }, [row?.id, row?.transcriptId, row?.probe?.ready])

  const opened = useRef(false)
  useEffect(() => {
    if (!transcriptId || opened.current) return
    const existing = rows.find((entry) => entry.transcriptId === transcriptId)
    if (!existing) return
    opened.current = true
    setSelectedId(existing.id)
  }, [transcriptId, rows])

  useEffect(() => {
    setRows((current) => {
      let changed = false
      const next = current.map((entry) => {
        const record = tasks[entry.id]
        if (!record) return entry
        const id = record.task.result?.transcript_id || entry.transcriptId
        const translationUrl = record.task.result?.translated_srt_url || entry.translationUrl
        if (entry.transcriptId === id && entry.translationUrl === translationUrl && entry.batchId === record.batchId && entry.itemId === record.task.item_id) return entry
        changed = true
        return { ...entry, transcriptId: id, translationUrl, batchId: record.batchId, itemId: record.task.item_id, submitted: true }
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

  function canOrganize(entry: Row) {
    if (entry.submitted) return false
    if (subtitleFile(entry.source)) return true
    if (!entry.probe?.ready) return false
    if (entry.probe.media_type === 'note') return true
    if (isImageNote(entry) || entry.probe.media_type === 'image') return false
    if (entry.probe.media_type === 'video' && !entry.probe.audio_direct && !entry.allowMuxed) return false
    return entry.probe.media_type === 'video' || entry.probe.media_type === 'audio' || entry.probe.has_audio
  }
  function payloadFor(candidates: Row[]) {
    return {
      ...videoPayload(base, settings?.ai_model || 'deepseek-flash'),
      knowledge_only: true, batch_concurrency: 2, rights_confirmed: true, item_overrides: {}, publish_confirmed: [] as string[],
      sources: candidates.map((entry) => ({
        source_kind: entry.kind, source_value: entry.source, source_title: rowTitle(entry).slice(0, 500), client_row_id: entry.id,
        stop_after: entry.probe?.ready && entry.probe.media_type === 'note' ? 'download' as const : 'translate' as const,
        allow_muxed_audio: Boolean(entry.allowMuxed), allow_unknown_audio: true,
        session_id: entry.sessionId || sessionForSource(entry.source),
        ...(entry.expectedDuration ? { expected_duration: entry.expectedDuration } : {}),
      })),
      transcript_ids: Object.fromEntries(candidates.flatMap((entry) => entry.transcriptId ? [[entry.id, entry.transcriptId]] : [])),
    }
  }
  function start() {
    const subtitles = rows.filter((entry) => !entry.submitted && subtitleFile(entry.source))
    const candidates = rows.filter(canOrganize).filter((entry) => !subtitleFile(entry.source))
    if (!subtitles.length && !candidates.length) return
    const needsModel = candidates.some((entry) => !(entry.probe?.ready && entry.probe.media_type === 'note'))
    if (needsModel && !settings?.has_ai_key) { onSettings('deepseek'); return }
    perform(async () => {
      setPending(true)
      try {
        for (const entry of subtitles) {
          const result = await request<{ transcript_id?: number }>('/desktop/knowledge/import', 'POST', {
            kind: 'local', source: entry.source, rights_confirmed: true, language: base.source_language || 'auto',
          })
          if (result.transcript_id) changeRow(entry.id, { transcriptId: result.transcript_id, submitted: true, hold: undefined })
        }
        if (!candidates.length) return
        const payload = payloadFor(candidates)
        const decisions = await request<Preflight>('/desktop/batches/preflight', 'POST', payload)
        setRows((current) => current.map((entry) => {
          const decision = decisions[entry.id]
          if (!decision || decision.ready) return entry.hold ? { ...entry, hold: undefined } : entry
          return { ...entry, hold: decision.message }
        }))
        const ready = candidates.filter((entry) => decisions[entry.id]?.ready)
        if (!ready.length) return
        const sources = payload.sources.filter((source) => ready.some((entry) => entry.id === source.client_row_id))
        const data = await request<Batch>('/ui/batches', 'POST', { ...payload, sources, publish_confirmed: [] })
        setRows((current) => current.map((entry) => sources.some((source) => source.client_row_id === entry.id) ? { ...entry, submitted: true, hold: undefined, sessionId: undefined } : entry))
        setTasks((current) => ({ ...current, ...Object.fromEntries(data.items.map((item) => [item.client_row_id, { task: item, batchId: data.batch_id }])) }))
        if (data.queued || data.running) watch(data.batch_id)
      } finally { setPending(false) }
    })
  }
  function runAction(entry: Row, action: CardAction) {
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
    if (action === 'replace') { setReplacing(entry.id); setSelectedId(entry.id); setDraft(''); return }
    if (action === 'to-publish' && entry.transcriptId) {
      onVideo({
        id: entry.transcriptId, source: entry.source, kind: entry.kind, title: rowTitle(entry, tasks[entry.id]?.task),
        continueFrom: entry.batchId && entry.itemId ? [entry.batchId, entry.itemId] : entry.continueFrom,
        author: entry.author, site: rowSite(entry),
      })
      return
    }
    const current = tasks[entry.id]?.task
    if (action === 'retry' && current && entry.batchId && entry.itemId) {
      const batchId = entry.batchId
      const itemId = entry.itemId
      perform(async () => {
        const data = await request<Batch>('/desktop/batches/' + batchId + '/' + itemId + '/retry', 'POST', {})
        setTasks((existing) => {
          const updated = { ...existing }
          for (const item of data.items) {
            const key = Object.keys(updated).find((id) => updated[id].batchId === data.batch_id && updated[id].task.item_id === item.item_id) || item.client_row_id
            updated[key] = { batchId: data.batch_id, task: item }
          }
          return updated
        })
        watch(data.batch_id)
      })
    }
  }
  const body = row?.body || (row?.probe && 'description' in row.probe ? row.probe.description : '') || ''
  const images = row?.images || row?.probe?.images || []
  const ready = rows.some((entry) => canOrganize(entry))

  return <div className="inbox">
    <PasteBar value={draft} onChange={(value) => { setDraft(value); setHint('') }}
      placeholder={replacing ? '贴上新的链接，更换这一条' : '链接或分享文案'} hint={hint}
      onAdd={() => { if (draft.trim()) addShares(parseShareText(draft), draft); else perform(async () => addPaths(await (await native()).choose_media(true))) }}
      addLabel="加入笔记" onStart={start} startLabel={pending ? '正在检查' : '开始整理'} startDisabled={pending || !ready}/>
    {!rows.length ? <p className="inbox-empty">{notesEmpty}</p> : <InboxSplit
      queue={rows.map((entry) => {
        const view = presentCard(entry, 'notes', tasks[entry.id]?.task)
        const cookie = view.action === 'login-douyin' || view.action === 'login-xhs'
        return <InboxCard key={entry.id} id={entry.id} title={view.title} status={view.status} selected={entry.id === selectedId}
          fresh={entry.fresh} action={view.action ? actionLabel[view.action] : undefined}
          extra={cookie ? '导入 Cookie' : undefined}
          onSelect={() => setSelectedId(entry.id)}
          onAction={view.action ? () => runAction(entry, view.action!) : undefined}
          onExtra={cookie ? () => { loginRow.current = entry; fileInput.current?.click() } : undefined}
          onSettled={() => changeRow(entry.id, { fresh: false })}/>
      })}
      work={row?.transcriptId ? <TranscriptView key={row.transcriptId} id={row.transcriptId} settings={settings}
        translationUrl={row.translationUrl || task?.result?.translated_srt_url} onSettings={onSettings}/> :
        <article className="note-column">
          <h2 className="note-title">{row ? rowTitle(row, task) : ''}</h2>
          {images.map((src) => <img key={src} className="note-picture" src={src} alt=""/>)}
          {body && <p className="note-prose">{body}</p>}
        </article>}/>}
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
        changeRow(entry.id, { sessionId, hold: undefined })
        await identify({ ...entry, sessionId, hold: undefined }, true)
      })
    }}/>
  </div>
}
