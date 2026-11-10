import { ArrowDown, ArrowRight, ArrowUp, Clapperboard, Download, Film, FolderOpen, GripVertical, HistoryIcon, Link2, ListVideo, Play, Send, SlidersHorizontal, Trash2, Headphones } from 'lucide-react'
import { Reorder, useDragControls } from 'motion/react'
import { useEffect, useRef, useState } from 'react'
import { errorMessage, historyLabel, native, request, saveAs, videoLinkKind, watchBatch, labels, linksIn, siteSession,
  timestamp, workflow, type WorkflowStage, type Preflight, type SourceProbe, type Batch, type History, type Item,
  type Settings, type SourceKind, type Transcript, type UploadCandidate } from './api'
import { Button, Busy, Feedback, Field, Modal, Select, StateChip, useActions } from './ui'
import { batchSource, useSourceTitles } from './sourceTitles'
import { getOverride, Inspector, outputDefaults, resolveOptions, savedVideoOptions, videoPayload,
  type DefaultGroup, type InspectorSection, type Override, type Row, type VideoDefaults, type VideoOptions } from './videoOptions'

const steps = workflow
const terminals = workflow.map(([key,label]) => [key, '做到' + label] as const)
const stepLabel = (key: WorkflowStage) => workflow.find(([stage]) => stage === key)?.[1]
const sourceTerminal = (row: Row | undefined, fallback: WorkflowStage) =>
  row?.probe?.ready && row.probe.media_type !== 'video' ? 'transcribe' : row?.terminal || fallback
function itemWorkflow(batch: Batch | null, item: Item) {
  if (item.planned_stages) return item.planned_stages
  const settings = batch?.request
  const override = settings?.item_overrides?.[item.client_row_id] || settings?.item_overrides?.[item.source_value]
  const stages: WorkflowStage[] = ['download','transcribe']
  if (settings?.knowledge_only) return stages
  if ((override?.subtitle_output_mode || settings?.subtitle_output_mode) !== 'en_only') stages.push('translate')
  stages.push('burn')
  if (override?.bilibili_upload?.enabled ?? settings?.bilibili_upload?.enabled) stages.push('bilibili_upload')
  return stages
}
export type VideoTransfer = { id: number; source: string; kind: SourceKind; title?: string }

function SourceDetails({row, item, title, inQueue}: {
  row?: Row; item?: Item; title?: string; inQueue: boolean
}) {
  const transcriptId = item?.result?.transcript_id
  const [doc,setDoc] = useState<Transcript | null>(null)
  const player = useRef<HTMLAudioElement>(null)
  useEffect(() => {
    let active = true
    if (transcriptId) void request<Transcript>('/desktop/knowledge/' + transcriptId).then((data) => {
      if (active) setDoc(data)
    }).catch(() => {})
    return () => {active = false}
  },[transcriptId])
  const activeDoc = doc?.id === transcriptId ? doc : null
  const probe = row?.probe?.ready ? row.probe : undefined
  const audio = (probe?.media_type || item?.media_type) === 'audio'
  const playerUrl = item?.result?.asset_type === 'audio' ? item.result.source_media_url : undefined
  const duration = item?.duration || probe?.duration
  const description = item?.result?.original_description || probe?.description
  const Icon = audio ? Headphones : Film
  return <section className="surface source-detail" aria-label="素材详情">
    {!row && !item ? <div className="empty-state"><Icon size={28}/><strong>{inQueue ? '素材详情' : '历史任务'}</strong>
      <p>{inQueue ? '从左侧素材队列添加文件或链接。' : '从左侧选择一个批次查看素材。'}</p>
    </div> : <>
      <div className="section-heading"><div className="section-icon"><Icon size={18}/></div><h2>{audio ? '音频素材' : '素材详情'}</h2></div>
      <h3>{title}</h3>
      <p className="muted">{[item?.platform || probe?.platform,duration ? timestamp(duration * 1000) : ''].filter(Boolean).join(' · ')}</p>
      {description && audio && <details className="task-log"><summary>节目简介</summary><p className="source-description">{description}</p></details>}
      {playerUrl && <audio key={playerUrl} ref={player} className="studio-audio" src={playerUrl} controls preload="metadata"/>}
      {activeDoc?.cues.length ? <ol className="studio-cues thin-scroll" aria-label="原文字幕">{activeDoc.cues.map((cue) =>
        <li key={cue.number}><button type="button" disabled={!playerUrl} onClick={() => {
          if (player.current) player.current.currentTime = cue.start_ms / 1000
        }}><time>{timestamp(cue.start_ms)}</time><span>{cue.text}</span></button></li>)}</ol> :
        <p className="muted">{audio ? '转录完成后可播放音频并按时间戳查看字幕。' :
          row?.probe && !row.probe.ready ? row.probe.message : '提交后在这里查看导入和转录结果。'}</p>}
    </>}
  </section>
}

function QueueRow({ row, label, selected, index, count, onSelect, move, remove, onDragStart, onDragEnd, onDragCancel,
  terminal, setTerminal, checked, toggle, retry, replace, cookie, allowMuxed, allowUnknown, task, showTask }: {
  row: Row; selected: boolean; index: number; count: number; onSelect: () => void; move: (delta: number) => void;
  label: string; remove: () => void; onDragStart: () => void; onDragEnd: () => void; onDragCancel: () => void
  terminal: WorkflowStage; setTerminal: (stage?: WorkflowStage) => void; checked: boolean; toggle: () => void;
  retry: () => void; replace: () => void; cookie: (file: File) => void; allowMuxed: (value: boolean) => void;
  allowUnknown: (value: boolean) => void;
  task?: Item; showTask: () => void;
}) {
  const controls = useDragControls()
  const probe = row.probe
  const step = workflow.findIndex(([key]) => key === terminal)
  return <Reorder.Item value={row.id} dragListener={false} dragControls={controls} dragMomentum={false}
    onDragStart={onDragStart} onDragEnd={onDragEnd} className={'queue-row' + (selected ? ' selected' : '')}>
    <Button variant="ghost" size="small" iconOnly leadingIcon={GripVertical} className="drag-handle"
      aria-label={'拖动排序：' + label}
      title="拖动排序，也可用 Alt + 方向键"
      onPointerDown={(event) => {event.currentTarget.focus({preventScroll:true}); controls.start(event)}}
      onKeyDown={(event) => {
        if (event.key === 'Escape') {onDragCancel(); controls.cancel()}
        if (event.altKey && (event.key === 'ArrowUp' || event.key === 'ArrowDown')) {
          event.preventDefault(); move(event.key === 'ArrowUp' ? -1 : 1)
        }
      }}/>
    <button className="queue-main" type="button" onClick={onSelect} aria-pressed={selected} title={label}>
      <strong>{label}</strong>
      <small>{row.submitted ? '已提交' : probe?.ready ? [probe.platform,
        {audio:'音频',video:'视频',unknown:'类型待核验'}[probe.media_type],
        probe.duration ? timestamp(probe.duration * 1000) : '', row.transcriptId ? '复用字幕' : ''].filter(Boolean).join(' · ') :
        probe ? '读取失败' : '正在识别'}</small>
    </button>
    <div className="row-actions">
      <Button variant="ghost" size="xs" iconOnly leadingIcon={ArrowUp} disabled={index === 0} aria-label="上移素材" onClick={() => move(-1)}/>
      <Button variant="ghost" size="xs" iconOnly leadingIcon={ArrowDown} disabled={index === count - 1} aria-label="下移素材" onClick={() => move(1)}/>
      <Button variant="ghost" size="xs" iconOnly leadingIcon={Trash2} aria-label="从队列移除素材" onClick={remove}/>
    </div>
    {!row.submitted && <div className="queue-workflow">
      {probe?.ready && probe.media_type === 'video' && <>
        <div className="workflow-summary">
          <label className="check"><input type="checkbox" checked={checked} onChange={toggle}
            aria-label={'选择视频 ' + label}/>做到{stepLabel(terminal)}</label>
          {row.terminal ? <Button variant="ghost" size="xs" onClick={() => setTerminal()}>恢复继承</Button> :
            <small>继承批次</small>}
        </div>
        <input type="range" min={0} max={4} step={1} value={step} aria-label={label + '的处理终点'}
          aria-valuetext={'做到' + stepLabel(terminal)} onChange={(e) => setTerminal(workflow[Number(e.target.value)][0])}/>
        <div className="workflow-labels">{workflow.map(([key, name], index) =>
          <button type="button" key={key} aria-pressed={key === terminal} data-reached={index <= step}
            onClick={() => setTerminal(key)}>{name}</button>)}</div>
        {row.kind !== 'local' && !probe.audio_direct && (terminal === 'transcribe' || terminal === 'translate') &&
          <label className="check muxed-option"><input type="checkbox" checked={Boolean(row.allowMuxed)}
            onChange={(e) => allowMuxed(e.target.checked)}/>仅提供合流，允许下载后提取音轨</label>}
      </>}
      {probe?.ready && probe.media_type !== 'video' && <div className="audio-workflow">导入 <ArrowRight size={12}/>
        {probe.media_type === 'unknown' ? '核验音轨并提取字幕' : '字幕'}</div>}
      {probe?.ready && probe.media_type === 'unknown' && <label className="check muxed-option">
        <input type="checkbox" checked={Boolean(row.unknownAudio)} onChange={(event) => allowUnknown(event.target.checked)}/>
        按字幕导入</label>}
      {probe && !probe.ready && <>
        <small className="source-error">{probe.message}</small>
        <div className="toolbar compact">
          <Button variant="ghost" size="xs" onClick={retry}>重试解析</Button>
          {row.kind !== 'local' && <Button variant="ghost" size="xs" onClick={replace}>更换链接</Button>}
          {probe.code === 'session_required' && <label className="cookie-picker">选择本站 Cookie
            <input type="file" accept=".txt,text/plain" aria-label="选择本站 Cookie 文件" onChange={(event) => {
              const file = event.target.files?.[0]; event.target.value = ''; if (file) cookie(file)
            }}/></label>}
        </div>
      </>}
    </div>}
    {row.submitted && task && <div className="queue-workflow">
      <div className="workflow-summary"><StateChip status={task.status}/>
        <Button variant="ghost" size="xs" onClick={showTask}>查看任务</Button></div>
      <progress max={100} value={task.progress} aria-label={label + '的任务进度'}/>
      <small className="muted">{stepLabel(task.stage as WorkflowStage) || '已提交'} · {task.progress}%</small>
    </div>}
  </Reorder.Item>
}

export function Video({ settings, transfer, onTransferUsed, onTranscript }: {
  settings: Settings | null; transfer: VideoTransfer | null; onTransferUsed: () => void; onTranscript: (id: number) => void
}) {
  const [leftTab,setLeftTab] = useState<'queue'|'history'>('queue')
  const [mobilePanel,setMobilePanel] = useState<'queue'|'preview'>('queue')
  const [rows, setRows] = useState<Row[]>([])
  const [dragStart, setDragStart] = useState<string[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [batchTerminal, setBatchTerminal] = useState<WorkflowStage>('bilibili_upload')
  const [checkedIds, setCheckedIds] = useState<string[]>([])
  const [bulkTerminal, setBulkTerminal] = useState<WorkflowStage>('bilibili_upload')
  const [replacing, setReplacing] = useState('')
  const [launch, setLaunch] = useState<{ decisions: Preflight; payload: ReturnType<typeof payloadFor> } | null>(null)
  const [defaults, setDefaults] = useState<VideoDefaults | null>(null)
  const [batchEdits, setBatchEdits] = useState<Override>({})
  const [savingDefault, setSavingDefault] = useState<DefaultGroup | null>(null)
  const [overrides, setOverrides] = useState<Record<string, Override>>({})
  const [perItem, setPerItem] = useState(false)
  const [inspector, setInspector] = useState(false)
  const [inspectorSection, setInspectorSection] = useState<InspectorSection>('output')
  const [linkError, setLinkError] = useState('')
  const [narrow, setNarrow] = useState(() => window.matchMedia('(max-width: 1279px)').matches)
  const [paste, setPaste] = useState(false)
  const [links, setLinks] = useState('')
  const [concurrency, setConcurrency] = useState(2)
  const [history, setHistory] = useState<History[]>([])
  const [batchId, setBatchId] = useState('')
  const [batch, setBatch] = useState<Batch | null>(null)
  const [queueTasks,setQueueTasks] = useState<Record<string,{batchId:string;task:Item}>>({})
  const queueWatches = useRef(new Map<string,() => void>())
  const [selectedTask, setSelectedTask] = useState('')
  const [watchRevision, setWatchRevision] = useState(0)
  const [uploadPlan, setUploadPlan] = useState<Record<string,UploadCandidate> | null>(null)
  const [uploadSelection, setUploadSelection] = useState<string[]>([])
  const [uploadChecked, setUploadChecked] = useState(false)
  const [useCurrentUploadSettings, setUseCurrentUploadSettings] = useState(false)
  const [uploadPending, setUploadPending] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const [pending, setPending] = useState(false)
  const [preview, setPreview] = useState<{ key: string; url: string; cover?: boolean }>({ key: '', url: '' })
  const [framePosition, setFramePosition] = useState(50)
  const [previewBusy, setPreviewBusy] = useState(false)
  const { notice, setNotice, perform } = useActions()
  const saved = savedVideoOptions(defaults)
  const base = resolveOptions(saved, batchEdits)
  const row = rows.find((entry) => entry.id === selectedId)
  const options = resolveOptions(base, perItem && row ? overrides[row.id] : undefined)
  const item = batch?.items.find((entry) => entry.item_id === selectedTask) || batch?.items[0]
  const terminal = sourceTerminal(row, batchTerminal)
  const relevantItem = leftTab === 'history' ? item : row && queueTasks[row.id]?.task
  const relevantProbe = row?.probe?.ready ? row.probe : undefined
  const showPreview = leftTab === 'queue' ? Boolean(row && relevantProbe?.media_type === 'video' &&
    (terminal === 'burn' || terminal === 'bilibili_upload')) : Boolean(item &&
    (item.stop_after ? ['burn','bilibili_upload'].includes(item.stop_after) : item.result?.final_video_url))
  const titles = useSourceTitles(batch?.items.map(batchSource) || [])
  const taskTitle = (entry: Item) => titles.label(batchSource(entry))
  function rowLabel(entry: Row) {
    const title = titles.title(entry)
    if (title) return title
    if (entry.probe?.ready) return entry.probe.platform
    try {return new URL(entry.source).hostname} catch {return '在线素材'}
  }

  useEffect(() => {
    let active = true
    void request<VideoDefaults>('/desktop/video-defaults').then((data) => {
      if (active) setDefaults(data)
    }).catch((error) => {if (active) setNotice({error: true, text: errorMessage(error)})})
    const reload = () => {void request<VideoDefaults>('/desktop/video-defaults').then((next) => {
      if (active) setDefaults(next)
    }).catch(() => {})}
    window.addEventListener('video-defaults-changed',reload)
    return () => {active = false;window.removeEventListener('video-defaults-changed',reload)}
  }, [setNotice])

  useEffect(() => {
    const query = window.matchMedia('(max-width: 1279px)')
    const update = () => { setNarrow(query.matches); if (!query.matches) setInspector(false) }
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])

  useEffect(() => {
    if (!transfer) return
    const id = crypto.randomUUID()
    const entry = { id, source: transfer.source, kind: transfer.kind, title: transfer.title, transcriptId: transfer.id }
    setRows((current) => [...current, entry])
    void identify(entry)
    setSelectedId(id)
    onTransferUsed()
  }, [transfer, onTransferUsed])

  useEffect(() => {
    let active = true
    void request<History[]>('/desktop/batches').then((entries) => {
      if (active) setHistory(entries)
    }).catch((error: Error) => {if(active) setNotice({error:true,text:error.message})})
    return () => {active = false}
  }, [setNotice])

  useEffect(() => {
    if (!batchId) return
    return watchBatch(batchId, (next) => {setBatch(next);updateQueueTasks(next)}, (text) => setNotice({text,error:true}))
  }, [batchId, watchRevision, setNotice])

  useEffect(() => {
    const watches = queueWatches.current
    return () => {watches.forEach((stop) => stop());watches.clear()}
  }, [])

  useEffect(() => {
    if (!batch) return
    setHistory((current) => current.map((entry) => entry.batch_id === batch.batch_id
      ? {...entry, status: batch.status} : entry))
  }, [batch])

  function reorder(ids: string[]) {
    setRows((current) => ids.map((id) => current.find((candidate) => candidate.id === id)).filter((x): x is Row => Boolean(x)))
  }
  function updateQueueTasks(next: Batch, recordNew = false) {
    setQueueTasks((current) => {
      const items = next.items.filter((entry) => recordNew || current[entry.client_row_id]?.batchId === next.batch_id)
      if (!items.length) return current
      return {...current,...Object.fromEntries(items.map((task) => [task.client_row_id,{task,batchId:next.batch_id}]))}
    })
  }
  function move(index: number, delta: number) {
    const ids = rows.map((candidate) => candidate.id)
    const next = index + delta
    if (next < 0 || next >= ids.length) return
    const [id] = ids.splice(index, 1)
    ids.splice(next, 0, id); reorder(ids)
    setNotice({text: '素材已移至第 ' + (next + 1) + ' 项'})
  }
  function changeRow(id: string, change: Partial<Row>) {
    setRows((current) => current.map((entry) => entry.id === id ? {...entry,...change} : entry))
  }
  async function identify(entry: Row, refresh = false) {
    changeRow(entry.id,{probe:undefined})
    let probe: SourceProbe
    try {
      probe = await request<SourceProbe>('/desktop/sources/probe' + (refresh ? '?refresh=true' : ''),'POST',{
        source_kind:entry.kind, source_value:entry.source, session_id:entry.sessionId,
      })
    } catch (error) {probe = {ready:false,code:'unavailable',message:errorMessage(error)}}
    setRows((current) => current.map((row) => row.id === entry.id && row.source === entry.source
      ? {...row,probe,title:probe.ready ? probe.title || row.title : row.title} : row))
  }
  function dropSession(entry: Row) {
    if (entry.sessionId) void request('/desktop/sources/session/' + entry.sessionId,'DELETE').catch(() => {})
  }
  function add(sources: string[], kind?: 'local') {
    const seen = new Set(rows.map((entry) => entry.source))
    const entries: Row[] = []
    for (const source of sources) {
      if (!source || seen.has(source)) continue
      seen.add(source)
      let sourceKind: SourceKind = kind || 'url'
      if (!kind) {
        try {sourceKind = videoLinkKind(source)} catch { /* Probe each invalid source independently. */ }
      }
      entries.push({id: crypto.randomUUID(), source, kind:sourceKind})
    }
    setRows([...rows, ...entries])
    if (entries[0]) setSelectedId(entries[0].id)
    entries.forEach((entry) => void identify(entry))
  }
  function payloadFor(candidates: Row[]) {
    const model = settings?.ai_model || 'deepseek-flash'
    return {
      ...videoPayload(base,model), batch_concurrency: concurrency, rights_confirmed: true,
      sources: candidates.map((entry) => ({source_kind:entry.kind, source_value:entry.source,
        source_title:titles.title(entry), client_row_id:entry.id, stop_after:sourceTerminal(entry,batchTerminal),
        allow_muxed_audio:entry.allowMuxed, allow_unknown_audio:entry.unknownAudio,
        session_id:entry.sessionId, continue_from:entry.continueFrom})),
      item_overrides: Object.fromEntries(candidates.filter((entry) => overrides[entry.id] && Object.keys(overrides[entry.id]).length)
        .map((entry) => [entry.id,videoPayload(resolveOptions(base,overrides[entry.id]),model,true)])),
      transcript_ids: Object.fromEntries(candidates.filter((entry) => entry.transcriptId).map((entry) => [entry.id,entry.transcriptId])),
    }
  }
  function submit(selectedOnly = false) {
    const candidates = selectedOnly ? (row ? [row] : []) : rows.filter((entry) => !entry.submitted)
    if (pending || !candidates.length) return
    perform(async () => {
      setPending(true)
      try {
        const payload = payloadFor(candidates)
        const unresolved = candidates.filter((entry) => !entry.probe?.ready)
        payload.sources = payload.sources.filter((source) => !unresolved.some((entry) => entry.id === source.client_row_id))
        const decisions = payload.sources.length ? await request<Preflight>('/desktop/batches/preflight','POST',payload) : {}
        for (const entry of unresolved) {
          const reason = entry.probe && !entry.probe.ready ? entry.probe :
            {ready:false as const,code:'probing',message:'素材仍在识别'}
          decisions[entry.id] = {...reason,title:rowLabel(entry)}
        }
        const consent = Object.values(decisions).some((value) => !value.ready || value.planned_stages.includes('bilibili_upload'))
        if (consent) setLaunch({decisions,payload})
        else await start(payload,decisions)
      } finally {setPending(false)}
    })
  }
  async function start(payload: ReturnType<typeof payloadFor>, decisions: Preflight) {
    const sources = payload.sources.filter((source) => decisions[source.client_row_id]?.ready)
    const publish = sources.filter(({client_row_id}) => {
      const decision = decisions[client_row_id]
      return decision.ready && decision.planned_stages.includes('bilibili_upload')
    })
    const data = await request<Batch>('/ui/batches','POST',{
      ...payload,sources,publish_confirmed:publish.map(({client_row_id}) => client_row_id),
    })
    setRows((current) => current.map((entry) => sources.some((source) => source.client_row_id === entry.id)
      ? {...entry,submitted:true,sessionId:undefined} : entry))
    updateQueueTasks(data,true)
    if (data.queued || data.running) {
      const stop = watchBatch(data.batch_id,(next) => {
        updateQueueTasks(next)
        if (!next.queued && !next.running) {
          queueWatches.current.get(next.batch_id)?.()
          queueWatches.current.delete(next.batch_id)
        }
      },() => {})
      queueWatches.current.set(data.batch_id,stop)
    }
    setLaunch(null)
    setBatch(data);setBatchId(data.batch_id);setSelectedTask(data.items[0]?.item_id || '')
    setHistory(await request<History[]>('/desktop/batches'))
    setLeftTab('history');setMobilePanel('preview')
    setNotice({text:'已启动 ' + data.items.length + ' 项'})
  }
  function continueToVideo(task: Item) {
    if (!batch) return
    const entry: Row = {id:crypto.randomUUID(), source:task.source_value, kind:task.source_kind,
      title:taskTitle(task), terminal:'burn', continueFrom:[batch.batch_id,task.item_id]}
    setRows((current) => [...current,entry])
    setSelectedId(entry.id);setLeftTab('queue');setMobilePanel('queue')
    void identify(entry)
  }
  function retry(task: Item) {
    if (task.stage === 'bilibili_upload') {
      openHistoryUpload(task.item_id)
      return
    }
    perform(async () => {
      const result = await request<Batch>('/desktop/batches/' + batchId + '/' + task.item_id + '/retry','POST',
        {})
      setBatch(result)
      setWatchRevision((revision) => revision + 1)
    })
  }
  const uploadable = batch?.items.filter((entry) => {
    const state = uploadPlan?.[entry.item_id]?.state
    return state === 'retry' || state === 'ready'
  }) || []
  const hasUploadRetries = uploadSelection.some((id) => uploadPlan?.[id]?.state === 'retry')
  const useBatchDefaults = uploadSelection.some((id) => uploadPlan?.[id]?.state === 'ready') ||
    (hasUploadRetries && useCurrentUploadSettings)
  const posting = item?.result?.bilibili_metadata

  function openHistoryUpload(itemId?: string) {
    const current = batch?.batch_id
    if (!current || uploadPending) return
    perform(async () => {
      const candidates = await request<Record<string,UploadCandidate>>('/desktop/batches/' + current + '/upload-candidates')
      setUploadSelection(itemId && ['retry','ready'].includes(candidates[itemId]?.state) ? [itemId] : [])
      setUploadChecked(false)
      setUseCurrentUploadSettings(false)
      setUploadError('')
      setUploadPlan(candidates)
    })
  }
  function submitHistoryUpload() {
    if (!batch || uploadPending || !uploadChecked || !uploadSelection.length) return
    setUploadPending(true)
    setUploadError('')
    const defaults = videoPayload(base,settings?.ai_model || 'deepseek-flash').bilibili_upload
    void request<Batch>('/desktop/batches/' + batch.batch_id + '/upload', 'POST', {
      item_ids: uploadSelection, upload_checked: true,
      use_current_settings: hasUploadRetries && useCurrentUploadSettings,
      ...(useBatchDefaults ? {upload_settings: {...defaults, enabled:true}} : {}),
    }).then((next) => {
      setBatch(next)
      setWatchRevision((revision) => revision + 1)
      setUploadPlan(null)
      setNotice({text:'已加入 B 站投稿队列'})
    }).catch((error) => setUploadError(errorMessage(error))).finally(() => setUploadPending(false))
  }
  const previewSource = leftTab === 'history' ? item && {kind:item.source_kind,source:item.source_value} : row
  const previewKey = JSON.stringify([previewSource?.source,relevantItem?.item_id,options.aspect_ratio,options.resolution,
    options.fps,options.subtitle_output_mode,options.subtitle_style,framePosition])
  const frame = preview.key === previewKey ? preview.url : ''
  function captureFrame() {
    if (!previewSource) return
    perform(async () => {
      setPreviewBusy(true)
      try {
        const imported = relevantItem?.result?.asset_type === 'video' ? relevantItem.result.source_video_url : undefined
        const data = await request<{preview_image_url?: string; preview_source?: string}>('/ui/preview-frame','POST',{
          source_kind:imported ? 'local' : previewSource.kind, source_value:imported || previewSource.source,
          aspect_ratio:options.aspect_ratio, resolution:options.resolution,
          fps:options.fps, subtitle_output_mode:options.subtitle_output_mode, subtitle_style:options.subtitle_style,
          preview_time_percent:framePosition,
        })
        if (!data.preview_image_url?.startsWith('/files/')) throw new Error('未能取得本地预览，请尝试其他时间点。')
        setPreview({key:previewKey,url:data.preview_image_url,cover:data.preview_source === 'thumbnail_fallback'})
      } finally {setPreviewBusy(false)}
    })
  }
  function updateOptions(value: VideoOptions) {
    if (!perItem || !row) setBatchEdits(getOverride(saved,value))
    else setOverrides((current) => ({...current,[row.id]:getOverride(base,value)}))
  }
  function saveDefault(group: DefaultGroup) {
    if (!defaults || perItem || savingDefault) return
    perform(async () => {
      setSavingDefault(group)
      try {
        const payload = group === 'output' ? {output:outputDefaults(base)} : {subtitle_style:base.subtitle_style}
        const next = await request<VideoDefaults>('/desktop/video-defaults','PUT',payload)
        setDefaults(next)
        window.dispatchEvent(new Event('video-defaults-changed'))
        setBatchEdits((edits) => getOverride(savedVideoOptions(next),resolveOptions(saved,edits)))
        setNotice({text: group === 'output' ? '已保存默认输出参数' : '已保存默认字幕样式'})
      } finally {setSavingDefault(null)}
    })
  }
  function resetDefault(group: DefaultGroup) {
    updateOptions({...options, ...(group === 'output' ? outputDefaults(saved) : {subtitle_style:saved.subtitle_style})})
    setNotice({text: group === 'output' ? '已恢复默认输出参数' : '已恢复默认字幕样式'})
  }
  function showHistory(id: string) {
    setBatchId(id); setBatch(null); setSelectedTask(''); setUploadPlan(null)
  }
  const addFiles = () => perform(async () => add(await (await native()).choose_media(true),'local'))
  const pasteLinks = () => {setReplacing('');setLinkError('');setPaste(true)}
  const checkedVideos = rows.filter((entry) => entry.probe?.ready && entry.probe.media_type === 'video' &&
    !entry.submitted && checkedIds.includes(entry.id))
  const inheriting = rows.filter((entry) => entry.probe?.ready && entry.probe.media_type === 'video' &&
    !entry.submitted && !entry.terminal).length
  const launchItems = Object.values(launch?.decisions || {})
  const readyItems = launchItems.filter((entry) => entry.ready)
  const publishingItems = readyItems.filter((entry) => entry.ready && entry.planned_stages.includes('bilibili_upload'))
  const inspectorTerminal = leftTab === 'history' ? item?.result?.final_video_url ? 'bilibili_upload' :
    item?.stop_after || batchTerminal : terminal
  const inspectorContent = <Inspector options={options} change={updateOptions} settings={settings} row={row} rowLabel={row && rowLabel(row)} perItem={perItem}
    section={inspectorSection} onSection={setInspectorSection} onScope={setPerItem}
    terminal={inspectorTerminal} batchExecution={{concurrency,onChange:setConcurrency}}
    defaultsReady={defaults !== null} savingDefault={savingDefault} onSaveDefault={saveDefault} onResetDefault={resetDefault}
    reset={() => row && setOverrides((current) => ({...current,[row.id]:{}}))}/>

  return <>
    <div className="workspace-heading">
      <div><h1>素材处理</h1><p>{rows.length} 项素材 · {rows.filter((entry) => !entry.submitted).length} 项待处理</p></div>
      <div className="toolbar">
        {narrow && <Button variant="secondary" leadingIcon={SlidersHorizontal} onClick={() => setInspector(true)}>处理参数</Button>}
        <Button leadingIcon={Play} disabled={pending || !rows.some((entry) => !entry.submitted && entry.probe)} onClick={() => submit()}>
          {pending ? '检查中' : '开始处理'}
        </Button>
      </div>
    </div>
    <Feedback notice={notice}/>
    <div className="segmented mobile-panels" aria-label="制作面板">
      <button aria-pressed={mobilePanel === 'queue'} onClick={() => setMobilePanel('queue')}>素材与任务</button>
      <button aria-pressed={mobilePanel === 'preview'} onClick={() => setMobilePanel('preview')}>预览与详情</button>
    </div>
    <div className="video-layout" data-panel={mobilePanel}>
      <section className="surface queue-pane" aria-label="素材与任务">
        <div className="segmented queue-tabs" aria-label="素材与任务">
          <button aria-pressed={leftTab === 'queue'} onClick={() => setLeftTab('queue')}><ListVideo size={16}/>素材队列 <span className="count">{rows.length}</span></button>
          <button aria-pressed={leftTab === 'history'} onClick={() => setLeftTab('history')}><HistoryIcon size={16}/>历史任务</button>
        </div>
        <div className="queue-content" hidden={leftTab !== 'queue'}>
        <div className="toolbar queue-import">
          <Button variant="secondary" size="small" leadingIcon={FolderOpen} onClick={addFiles}>添加文件</Button>
          <Button variant="ghost" size="small" leadingIcon={Link2} onClick={pasteLinks}>粘贴链接</Button>
        </div>
        {rows.length > 0 && <div className="batch-terminal">
          <Field label="本批默认终点"><Select value={batchTerminal} options={terminals} onChange={(value) => {
            setBatchTerminal(value as WorkflowStage);setNotice({text:'已更新 ' + inheriting + ' 个继承批次默认的视频'})
          }}/></Field>
          {checkedVideos.length > 0 && <div className="bulk-terminal">
            <Field label={'所选视频 · ' + checkedVideos.length}><Select value={bulkTerminal} options={terminals}
              onChange={(value) => setBulkTerminal(value as WorkflowStage)}/></Field>
            <Button variant="secondary" size="small" onClick={() => {
              setRows((current) => current.map((entry) => checkedVideos.some((checked) => checked.id === entry.id)
                ? {...entry,terminal:bulkTerminal} : entry))
              setNotice({text:'已更新所选 ' + checkedVideos.length + ' 个视频'});setCheckedIds([])
            }}>应用</Button>
          </div>}
        </div>}
        {rows.length ? <Reorder.Group axis="y" values={rows.map((entry) => entry.id)} onReorder={reorder} className="queue-list thin-scroll">
          {rows.map((entry,index) => <QueueRow key={entry.id} row={entry} label={rowLabel(entry)} selected={entry.id === selectedId}
            index={index} count={rows.length} onSelect={() => setSelectedId(entry.id)}
            terminal={sourceTerminal(entry,batchTerminal)} setTerminal={(terminal) => {changeRow(entry.id,{terminal});setSelectedId(entry.id)}}
            checked={checkedIds.includes(entry.id)}
            toggle={() => setCheckedIds((current) => current.includes(entry.id) ? current.filter((id) => id !== entry.id) : [...current,entry.id])}
            retry={() => void identify(entry,true)} replace={() => {setReplacing(entry.id);setLinks('');setLinkError('');setPaste(true)}}
            cookie={(file) => perform(async () => {
              const sessionId = await siteSession(entry.source,file)
              dropSession(entry);changeRow(entry.id,{sessionId});await identify({...entry,sessionId},true)
            })}
            allowMuxed={(allowMuxed) => changeRow(entry.id,{allowMuxed})}
            allowUnknown={(unknownAudio) => changeRow(entry.id,{unknownAudio})}
            task={queueTasks[entry.id]?.task} showTask={() => {
              const target = queueTasks[entry.id]
              if (!target) return
              if (batchId !== target.batchId) showHistory(target.batchId)
              setSelectedTask(target.task.item_id);setLeftTab('history');setMobilePanel('preview')
            }}
            move={(delta) => move(index,delta)} remove={() => {
              dropSession(entry)
              const remaining = rows.filter((candidate) => candidate.id !== entry.id)
              setRows(remaining)
              if (selectedId === entry.id) setSelectedId(remaining[index]?.id || remaining.at(-1)?.id || '')
            }} onDragStart={() => setDragStart(rows.map((candidate) => candidate.id))}
            onDragEnd={() => setDragStart([])} onDragCancel={() => {if(dragStart.length) reorder(dragStart); setDragStart([])}}/>)}
        </Reorder.Group> : <div className="empty-state compact"><Film size={23}/><strong>还没有素材</strong></div>}
        {row?.submitted && <div className="queue-resubmit">
          <Button variant="ghost" size="small" leadingIcon={ArrowRight}
            disabled={pending || ['queued','running'].includes(queueTasks[row.id]?.task.status)}
            onClick={() => submit(true)}>重新提交当前素材</Button>
        </div>}
        </div>
        <div className="history-content" hidden={leftTab !== 'history'}>
        <Field label="批次"><Select value={batchId} onChange={showHistory}
          options={[[ '', '选择历史批次' ],...history.map((record) => [record.batch_id,historyLabel(record)] as const)]}/></Field>
        {batch && <div className="history-actions"><Button variant="secondary" size="small" leadingIcon={Send}
          onClick={() => openHistoryUpload()}>批量投稿到 B 站</Button></div>}
        {batch?.items.length ? <div className="task-list thin-scroll">{batch.items.map((entry) => <button type="button" className="task-row"
          key={entry.item_id} aria-pressed={item?.item_id === entry.item_id} onClick={() => setSelectedTask(entry.item_id)}>
          <span title={taskTitle(entry)}>{taskTitle(entry)}</span><StateChip status={entry.status}/>
          <progress aria-label="任务进度" max={100} value={entry.progress}/>
        </button>)}</div> : <p className="muted task-placeholder">提交后可在这里跟踪进度。</p>}
        </div>
      </section>

      <div className="preview-column thin-scroll">
        {showPreview ? <section className="surface preview-pane" aria-label="字幕预览">
          <div className="section-heading"><div className="section-icon"><Clapperboard size={18}/></div><h2>字幕预览</h2>
            <span className="preview-mode">{frame ? preview.cover ? '封面图 · 示例字幕' : '实际画面 · 示例字幕' : '样式示意'}</span></div>
          <div className="preview-body">
            <div className={'video-canvas ' + (options.aspect_ratio === '9:16' ? 'portrait' : options.aspect_ratio === '1:1' ? 'square' : '')}>
              {frame ? <img src={frame} alt={preview.cover ? '含所选字幕样式的封面图' : '含所选字幕样式的视频帧'}/> : <>
                <div className="preview-art" aria-hidden="true"><div/><div/><div/></div>
                <div className={'sample-caption ' + options.subtitle_style.position} style={{
                  color: options.subtitle_style.primary_color, fontFamily: options.subtitle_style.font_family,
                  fontWeight: options.subtitle_style.font_weight, fontSize: Math.max(12,options.subtitle_style.font_size / 2.7),
                  textShadow: '0 1px ' + Math.max(1,options.subtitle_style.outline_width) + 'px ' + options.subtitle_style.outline_color,
                  maxWidth: options.subtitle_style.max_width_percent + '%', lineHeight:options.subtitle_style.line_spacing,
                  backgroundColor: options.subtitle_style.background_enabled ?
                    options.subtitle_style.background_color + Math.round(options.subtitle_style.background_opacity * 2.55).toString(16).padStart(2,'0') : undefined,
                  padding: options.subtitle_style.background_enabled ? options.subtitle_style.background_padding / 2 : undefined,
                }}>
                  {options.subtitle_output_mode === 'en_only' ? 'Every idea starts with a moment.' :
                    options.subtitle_output_mode === 'zh_only' ? '每个想法都有一个起点。' :
                    options.subtitle_style.bilingual_order === 'en_top_zh_bottom' ?
                      <>Every idea starts with a moment.<br/>每个想法都有一个起点。</> :
                      <>每个想法都有一个起点。<br/>Every idea starts with a moment.</>}
                </div>
              </>}
            </div>
            <div className="preview-controls">
              <Field label={'取帧位置 · ' + framePosition + '%'}><input type="range" min={0} max={100} value={framePosition}
                onChange={(e) => setFramePosition(Number(e.target.value))}/></Field>
              <Button variant="secondary" size="small" disabled={!previewSource || previewBusy} onClick={captureFrame}>
                {previewBusy ? '取帧中' : '抓取预览'}</Button>
            </div>
          </div>
        </section> : <SourceDetails row={leftTab === 'queue' ? row : undefined} item={relevantItem}
          title={leftTab === 'history' ? (item && taskTitle(item)) : (row && rowLabel(row))} inQueue={leftTab === 'queue'}/>}
        {leftTab === 'history' && <section className="surface task-detail" aria-label="任务详情">
          <div className="section-heading"><h2>任务详情</h2>{item && <StateChip status={item.status}/>}</div>
          {!item ? <p className="muted">选择一项任务查看阶段、错误和导出结果。</p> : <>
            <p className="item-title">{taskTitle(item)}</p>
            {item.result?.burn_encoder && <p className="muted">烧录编码 · {item.result.burn_encoder === 'nvenc' ? 'NVIDIA NVENC' : 'CPU · libx264'}</p>}
            <ol className="stage-strip">{steps.filter(([key]) => itemWorkflow(batch,item).includes(key) ||
              key === 'bilibili_upload' && item.stage_details?.[key]).map(([key, label]) => {
              const stage = item.stage_details?.[key]
              return <li key={key} data-state={stage?.status || 'idle'} title={stage?.message}>
                <span>{label}</span><small>{stage ? labels[stage.status] : '—'}</small></li>
            })}</ol>
            {item.status === 'running' && <Busy>{item.progress_detail || item.message}</Busy>}
            {item.error && <div className="notice error" role="alert">{item.error.message}</div>}
            {posting && <details className="task-log">
              <summary>{posting.generated_fields.length ? '投稿信息 · DeepSeek 已填写' : '投稿信息'}</summary>
              <div className="posting-summary">
                <p><strong>分区</strong> {posting.zone || posting.tid}</p>
                <p><strong>标题</strong> {posting.title}</p>
                {posting.desc && <p><strong>简介</strong> {posting.desc}</p>}
                <p><strong>标签</strong> {posting.tags.join(' · ')}</p>
                {posting.notice && <p className="muted">{posting.notice}</p>}
                {item.result?.cover_asset_url?.startsWith('/files/') && <img className="cover-image"
                  src={item.result.cover_asset_url} alt={item.result.cover_source === 'source_thumbnail' ||
                    item.result.cover_source === 'embedded_picture' ? '来源封面' : '实际投稿封面'}/>}
              </div>
            </details>}
            {item.log_tail?.length ? <details className="task-log"><summary>运行详情</summary><pre>{item.log_tail.join('\n')}</pre></details> : null}
            <div className="toolbar compact">
              {item.status === 'failed' && <Button size="small" onClick={() => retry(item)}>
                {item.stage === 'bilibili_upload' ? '重试 B 站投稿' : '从失败阶段重试'}</Button>}
              {item.status === 'failed' && item.stage === 'download' && item.source_kind !== 'local' &&
                <label className="cookie-picker">用本站 Cookie 重试<input type="file" accept=".txt,text/plain"
                  aria-label="用本站 Cookie 重试" onChange={(event) => {
                    const file = event.target.files?.[0];event.target.value = ''
                    if (file) perform(async () => {
                      const session_id = await siteSession(item.source_value,file)
                      try {
                        setBatch(await request<Batch>('/desktop/batches/' + batchId + '/' + item.item_id + '/retry','POST',{session_id}))
                        setWatchRevision((revision) => revision + 1)
                      } finally {void request('/desktop/sources/session/' + session_id,'DELETE').catch(() => {})}
                    })
                  }}/></label>}
              {item.status === 'succeeded' && item.media_type === 'video' && item.result?.transcript_id &&
                !item.result.final_video_url && <Button size="small" variant="secondary" onClick={() => continueToVideo(item)}>继续到成片</Button>}
              {([
                [item.result?.final_video_url,'导出 MP4','.mp4'],[item.result?.english_srt_url,'原文 SRT','-原文.srt'],
                [item.result?.translated_srt_url,'译文 SRT','-译文.srt'],[item.result?.bilingual_srt_url,'双语 SRT','-双语.srt'],
                [item.stop_after === 'download' ? item.result?.source_media_url : undefined,'导出源素材',
                  item.result?.source_media_url?.match(/\.[a-z0-9]+$/i)?.[0] || ''],
              ] as const).map(([url,label,suffix]) => url && <Button key={suffix} variant="secondary" size="small" leadingIcon={Download}
                onClick={() => perform(async () => {
                  const name = taskTitle(item).replace(/\.[a-z0-9]{2,5}$/i,'')
                  if (await saveAs(name + suffix,{format:'artifact',artifact_url:url})) setNotice({text:'文件已导出'})
                })}>{label}</Button>)}
              {item.result?.transcript_id && <Button variant="ghost" size="small" onClick={() => onTranscript(item.result!.transcript_id!)}>查看字幕</Button>}
              {item.result?.bilibili_url && <a target="_blank" rel="noreferrer" href={item.result.bilibili_url}>查看 B 站稿件</a>}
            </div>
          </>}
        </section>}
      </div>
      {!narrow && <aside className="surface inspector" aria-label="处理参数">
        <div className="section-heading inspector-heading"><div className="section-icon"><SlidersHorizontal size={18}/></div><h2>处理参数</h2></div>
        {inspectorContent}
      </aside>}
    </div>
    {narrow && <Modal open={inspector} title="处理参数" onClose={() => setInspector(false)} drawer>{inspectorContent}</Modal>}
    <Modal open={Boolean(launch)} title={publishingItems.length ? '确认本批处理和投稿' : '检查处理条件'}
      onClose={() => {if (!pending) setLaunch(null)}}>
      <div className="form-stack">
        {publishingItems.length > 0 && <><p>以下 {publishingItems.length} 条视频成片后会自动提交 B 站审核。</p>
          <ul className="launch-list thin-scroll">{publishingItems.map((entry,index) => <li key={index}>{entry.title}</li>)}</ul></>}
        {readyItems.length < launchItems.length && <><p>以下素材需要处理后再启动。</p>
          <ul className="launch-list thin-scroll">{launchItems.map((entry,index) => !entry.ready &&
            <li key={index}><strong>{entry.title}</strong><small>{entry.message}</small></li>)}</ul></>}
        <div className="toolbar modal-actions">
          <Button variant="ghost" disabled={pending} onClick={() => setLaunch(null)}>{readyItems.length ? '取消' : '返回队列'}</Button>
          {readyItems.length > 0 && <Button disabled={pending} leadingIcon={Play} onClick={() => {
            if (!launch) return
            perform(async () => {setPending(true);try {await start(launch.payload,launch.decisions)} finally {setPending(false)}})
          }}>{(publishingItems.length ? '确认并启动 ' : '仅启动就绪的 ') + readyItems.length + ' 项'}</Button>}
        </div>
      </div>
    </Modal>
    <Modal open={Boolean(uploadPlan)} title="从历史成片投稿到 B 站" onClose={() => {if (!uploadPending) setUploadPlan(null)}}>
      <div className="form-stack">
        <p className="muted">直接使用已生成的成片。重试沿用原投稿参数，首次投稿使用当前「输出参数 → 投稿」的批次默认参数。</p>
        {uploadable.length > 0 && <Button variant="secondary" size="small" disabled={uploadPending}
          onClick={() => setUploadSelection(uploadSelection.length === uploadable.length ? [] : uploadable.map((entry) => entry.item_id))}>
          {uploadSelection.length === uploadable.length ? '取消全选' : '全选可投稿项'}</Button>}
        <ul className="history-upload-list thin-scroll" aria-label="历史成片">
          {batch?.items.map((entry) => {
            const candidate = uploadPlan?.[entry.item_id]
            const available = candidate?.state === 'ready' || candidate?.state === 'retry'
            return <li key={entry.item_id}><label className="check">
              <input type="checkbox" disabled={!available || uploadPending} checked={uploadSelection.includes(entry.item_id)}
                onChange={(event) => setUploadSelection((current) => event.target.checked ?
                  [...current,entry.item_id] : current.filter((id) => id !== entry.item_id))}/>
              <span><strong>{taskTitle(entry)}</strong>
                <small>{candidate?.message}</small></span>
            </label></li>
          })}
        </ul>
        {hasUploadRetries && <label className="check"><input type="checkbox" checked={useCurrentUploadSettings} disabled={uploadPending}
          onChange={(event) => setUseCurrentUploadSettings(event.target.checked)}/>重试项改用当前批次投稿参数</label>}
        {useBatchDefaults && <p className="muted">当前默认参数 · {base.bilibili_upload.copyright === 1 ? '自制' : '转载'} ·
          {' '}{base.bilibili_upload.cover_mode === 'source_cover' ? '每条使用来源封面' : '自定义封面'} ·
          {' '}{base.bilibili_upload.tid ? '分区 ' + base.bilibili_upload.tid :
            base.bilibili_upload.auto_metadata ? 'DeepSeek 自动选择分区' : '尚未选择分区'}
          {base.bilibili_upload.auto_metadata && '。空白投稿字段会用来源标题和部分原文字幕生成。'}</p>}
        {uploadable.length > 0 && <label className="check"><input type="checkbox" checked={uploadChecked} disabled={uploadPending}
          onChange={(event) => setUploadChecked(event.target.checked)}/> 我已在 B 站创作中心核对所选成片，确认可以投稿。</label>}
        {uploadError && <Feedback notice={{text:uploadError,error:true}}/>}
        <div className="toolbar modal-actions">
          <Button variant="ghost" disabled={uploadPending} onClick={() => setUploadPlan(null)}>取消</Button>
          <Button leadingIcon={Send} disabled={uploadPending || !uploadSelection.length || !uploadChecked} onClick={submitHistoryUpload}>
            {uploadPending ? '正在加入队列' : '投稿所选（' + uploadSelection.length + '）'}</Button>
        </div>
      </div>
    </Modal>
    <Modal open={paste} title={replacing ? '更换素材链接' : '粘贴素材链接'} onClose={() => setPaste(false)}>
      <form className="form-stack" onSubmit={(event) => {
        event.preventDefault()
        try {
          const sources = linksIn(links)
          if (!sources.length) throw new Error('未找到 HTTP 或 HTTPS 链接')
          const previous = rows.find((entry) => entry.id === replacing)
          if (previous) {
            if (sources.length !== 1) throw new Error('请为这条素材提供一个链接')
            const next = {source:sources[0],kind:videoLinkKind(sources[0]), title:undefined, sessionId:undefined,
              probe:undefined,allowMuxed:false,unknownAudio:false,transcriptId:undefined,continueFrom:undefined}
            dropSession(previous);changeRow(previous.id,next);void identify({...previous,...next})
          } else add(sources)
          setLinks(''); setLinkError(''); setPaste(false)
        } catch (error) { setLinkError(errorMessage(error)) }
      }}>
        <Field label="链接或分享文案"><textarea value={links} rows={5} placeholder={'粘贴音视频链接，支持一次粘贴多条'}
          onChange={(event) => {setLinks(event.target.value); setLinkError('')}}/></Field>
        {linkError && <Feedback notice={{text:linkError,error:true}}/>}
        <div className="toolbar"><Button variant="ghost" onClick={() => setPaste(false)}>取消</Button>
          <Button type="submit" disabled={!links.trim()}>加入队列</Button></div>
      </form>
    </Modal>
  </>
}
