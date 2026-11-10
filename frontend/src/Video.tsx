import { ArrowDown, ArrowRight, ArrowUp, Clapperboard, Download, Film, FolderOpen, GripVertical, HistoryIcon, Link2, ListVideo, Play, Send, SlidersHorizontal, Trash2 } from 'lucide-react'
import { motion, Reorder, useDragControls } from 'motion/react'
import { useEffect, useState } from 'react'
import { errorMessage, leaf, native, request, saveAs, sourceNames, videoLinkKind, watchBatch, labels, type Batch, type History, type Item, type Settings, type SourceKind, type UploadCandidate } from './api'
import { Button, Busy, Feedback, Field, Modal, Select, StateChip, useActions } from './ui'
import { getOverride, Inspector, outputDefaults, resolveOptions, savedVideoOptions, videoPayload,
  type DefaultGroup, type InspectorSection, type Override, type Row, type VideoDefaults, type VideoOptions } from './videoOptions'

const steps = [['download','导入'],['transcribe','转录'],['translate','翻译'],['burn','压制'],['bilibili_upload','投稿']]
export type VideoTransfer = { id: number; source: string; kind: SourceKind }

function sourceLabel(source: string, kind: SourceKind) {
  if (kind === 'local') return leaf(source)
  try { const url = new URL(source); return sourceNames[kind] + ' · ' + (url.searchParams.get('v') || leaf(url.pathname) || url.hostname) }
  catch { return source }
}

function QueueRow({ row, selected, index, count, onSelect, move, remove, onDragStart, onDragEnd, onDragCancel }: {
  row: Row; selected: boolean; index: number; count: number; onSelect: () => void; move: (delta: number) => void;
  remove: () => void; onDragStart: () => void; onDragEnd: () => void; onDragCancel: () => void
}) {
  const controls = useDragControls()
  return <Reorder.Item value={row.id} dragListener={false} dragControls={controls} dragMomentum={false}
    onDragStart={onDragStart} onDragEnd={onDragEnd} className={'queue-row' + (selected ? ' selected' : '')}>
    <Button variant="ghost" size="small" iconOnly leadingIcon={GripVertical} className="drag-handle"
      aria-label={'拖动排序：' + sourceLabel(row.source, row.kind)}
      title="拖动排序，也可用 Alt + 方向键"
      onPointerDown={(event) => {event.currentTarget.focus({preventScroll:true}); controls.start(event)}}
      onKeyDown={(event) => {
        if (event.key === 'Escape') {onDragCancel(); controls.cancel()}
        if (event.altKey && (event.key === 'ArrowUp' || event.key === 'ArrowDown')) {
          event.preventDefault(); move(event.key === 'ArrowUp' ? -1 : 1)
        }
      }}/>
    <button className="queue-main" type="button" onClick={onSelect} aria-pressed={selected} title={row.source}>
      <strong>{sourceLabel(row.source,row.kind)}</strong>
      <small>{row.submitted ? '已提交' : row.transcriptId ? '复用原文字幕' : row.kind === 'local' ? '本地视频' : '在线视频'}</small>
    </button>
    <div className="row-actions">
      <Button variant="ghost" size="xs" iconOnly leadingIcon={ArrowUp} disabled={index === 0} aria-label="上移素材" onClick={() => move(-1)}/>
      <Button variant="ghost" size="xs" iconOnly leadingIcon={ArrowDown} disabled={index === count - 1} aria-label="下移素材" onClick={() => move(1)}/>
      <Button variant="ghost" size="xs" iconOnly leadingIcon={Trash2} aria-label="从队列移除素材" onClick={remove}/>
    </div>
  </Reorder.Item>
}

export function Video({ settings, transfer, onTransferUsed, onTranscript }: {
  settings: Settings | null; transfer: VideoTransfer | null; onTransferUsed: () => void; onTranscript: (id: number) => void
}) {
  const [rows, setRows] = useState<Row[]>([])
  const [dragStart, setDragStart] = useState<string[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [defaults, setDefaults] = useState<VideoDefaults | null>(null)
  const [batchEdits, setBatchEdits] = useState<Override>({})
  const [savingDefault, setSavingDefault] = useState<DefaultGroup | null>(null)
  const [overrides, setOverrides] = useState<Record<string, Override>>({})
  const [perItem, setPerItem] = useState(false)
  const [inspector, setInspector] = useState(false)
  const [inspectorSection, setInspectorSection] = useState<InspectorSection>('output')
  const [linkError, setLinkError] = useState('')
  const [narrow, setNarrow] = useState(() => window.matchMedia('(max-width: 1150px)').matches)
  const [paste, setPaste] = useState(false)
  const [links, setLinks] = useState('')
  const [concurrency, setConcurrency] = useState(2)
  const [history, setHistory] = useState<History[]>([])
  const [batchId, setBatchId] = useState('')
  const [batch, setBatch] = useState<Batch | null>(null)
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

  useEffect(() => {
    let active = true
    void request<VideoDefaults>('/desktop/video-defaults').then((data) => {
      if (active) setDefaults(data)
    }).catch((error) => {if (active) setNotice({error: true, text: errorMessage(error)})})
    return () => {active = false}
  }, [setNotice])

  useEffect(() => {
    const query = window.matchMedia('(max-width: 1150px)')
    const update = () => { setNarrow(query.matches); if (!query.matches) setInspector(false) }
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])

  useEffect(() => {
    if (!transfer) return
    const id = crypto.randomUUID()
    setRows((current) => [...current, { id, source: transfer.source, kind: transfer.kind, transcriptId: transfer.id }])
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
    return watchBatch(batchId, setBatch, (text) => setNotice({text,error:true}))
  }, [batchId, watchRevision, setNotice])

  useEffect(() => {
    if (!batch) return
    setHistory((current) => current.map((entry) => entry.batch_id === batch.batch_id
      ? {...entry, status: batch.status} : entry))
  }, [batch])

  function reorder(ids: string[]) {
    setRows((current) => ids.map((id) => current.find((candidate) => candidate.id === id)).filter((x): x is Row => Boolean(x)))
  }
  function move(index: number, delta: number) {
    const ids = rows.map((candidate) => candidate.id)
    const next = index + delta
    if (next < 0 || next >= ids.length) return
    const [id] = ids.splice(index, 1)
    ids.splice(next, 0, id); reorder(ids)
    setNotice({text: '素材已移至第 ' + (next + 1) + ' 项'})
  }
  function add(sources: string[], kind?: 'local') {
    const seen = new Set(rows.map((entry) => entry.source))
    const entries: Row[] = []
    for (const source of sources) {
      if (!source || seen.has(source)) continue
      seen.add(source)
      entries.push({id: crypto.randomUUID(), source, kind:kind ?? videoLinkKind(source)})
    }
    setRows([...rows, ...entries])
    if (entries[0]) setSelectedId(entries[0].id)
  }
  function submit(selectedOnly = false) {
    const candidates = selectedOnly ? (row ? [row] : []) : rows.filter((entry) => !entry.submitted)
    if (pending || !candidates.length) return
    perform(async () => {
      setPending(true)
      try {
        const model = settings?.ai_model || 'deepseek-flash'
        const data = await request<Batch>('/ui/batches', 'POST', {
          ...videoPayload(base,model), batch_concurrency: concurrency, rights_confirmed: true,
          sources: candidates.map((entry) => ({source_kind:entry.kind, source_value:entry.source, client_row_id:entry.id})),
          item_overrides: Object.fromEntries(candidates.filter((entry) => overrides[entry.id] && Object.keys(overrides[entry.id]).length)
            .map((entry) => [entry.id,videoPayload(resolveOptions(base,overrides[entry.id]),model,true)])),
          transcript_ids: Object.fromEntries(candidates.filter((entry) => entry.transcriptId).map((entry) => [entry.id,entry.transcriptId])),
        })
        setRows((current) => current.map((entry) => candidates.some((added) => added.id === entry.id) ? {...entry,submitted:true} : entry))
        setBatch(data); setBatchId(data.batch_id); setSelectedTask(data.items[0]?.item_id || '')
        setHistory(await request<History[]>('/desktop/batches'))
        setNotice({text:'批次已提交'})
      } finally {setPending(false)}
    })
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
  const previewKey = JSON.stringify([row?.id,options.aspect_ratio,options.resolution,options.fps,options.subtitle_output_mode,options.subtitle_style,framePosition])
  const frame = preview.key === previewKey ? preview.url : ''
  function captureFrame() {
    if (!row) return
    perform(async () => {
      setPreviewBusy(true)
      try {
        const data = await request<{preview_image_url?: string; preview_source?: string}>('/ui/preview-frame','POST',{
          source_kind:row.kind, source_value:row.source, aspect_ratio:options.aspect_ratio, resolution:options.resolution,
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
  const inspectorContent = <Inspector options={options} change={updateOptions} settings={settings} row={row} perItem={perItem}
    section={inspectorSection} onSection={setInspectorSection} onScope={setPerItem}
    defaultsReady={defaults !== null} savingDefault={savingDefault} onSaveDefault={saveDefault} onResetDefault={resetDefault}
    reset={() => row && setOverrides((current) => ({...current,[row.id]:{}}))}/>

  return <>
    <div className="workspace-heading">
      <div><div className="eyebrow">PRODUCTION STUDIO</div><h1>视频制作</h1><p>导入素材、调整字幕，再交付成片。</p></div>
      <div className="toolbar">
        {narrow && <Button variant="secondary" leadingIcon={SlidersHorizontal} onClick={() => setInspector(true)}>输出参数</Button>}
        <Button leadingIcon={Play} disabled={pending || !rows.some((entry) => !entry.submitted)} onClick={() => submit()}>
          {pending ? '提交中' : '开始处理'}
        </Button>
      </div>
    </div>
    <Feedback notice={notice}/>
    <div className="video-layout">
      <motion.div className="production-main thin-scroll" layoutScroll>
      <section className="surface queue-pane" aria-label="素材与任务">
        <div className="section-heading"><div className="section-icon"><ListVideo size={18}/></div><h2>素材队列</h2>
          <span className="count">{rows.length}</span></div>
        <div className="toolbar queue-import">
          <Button variant="secondary" size="small" leadingIcon={FolderOpen} onClick={() => perform(async () => add(await (await native()).choose_media(true), 'local'))}>添加文件</Button>
          <Button variant="ghost" size="small" leadingIcon={Link2} onClick={() => setPaste(true)}>添加链接</Button>
        </div>
        {rows.length ? <Reorder.Group axis="y" values={rows.map((entry) => entry.id)} onReorder={reorder} className="queue-list">
          {rows.map((entry,index) => <QueueRow key={entry.id} row={entry} selected={entry.id === selectedId}
            index={index} count={rows.length} onSelect={() => setSelectedId(entry.id)}
            move={(delta) => move(index,delta)} remove={() => {
              const remaining = rows.filter((candidate) => candidate.id !== entry.id)
              setRows(remaining)
              if (selectedId === entry.id) setSelectedId(remaining[index]?.id || remaining.at(-1)?.id || '')
            }} onDragStart={() => setDragStart(rows.map((candidate) => candidate.id))}
            onDragEnd={() => setDragStart([])} onDragCancel={() => {if(dragStart.length) reorder(dragStart); setDragStart([])}}/>)}
        </Reorder.Group> : <div className="empty-state compact"><Film size={23}/><strong>还没有素材</strong><p>添加本地视频或粘贴 YouTube、B 站链接。</p></div>}
        <div className="queue-bottom">
          <Field label="并发任务"><Select value={concurrency} onChange={(v) => setConcurrency(Number(v))}
            options={[[1,'1 项'],[2,'2 项 · 推荐'],[3,'3 项'],[4,'4 项'],[5,'5 项']]}/></Field>
          {row?.submitted && <Button variant="ghost" size="small" leadingIcon={ArrowRight} onClick={() => submit(true)}>重新提交当前素材</Button>}
        </div>
        <div className="section-heading task-heading"><HistoryIcon size={17}/><h2>任务记录</h2></div>
        <Field label="批次"><Select value={batchId} onChange={showHistory}
          options={[[ '', '选择历史批次' ],...history.map((record) => [record.batch_id,record.title + ' · ' + labels[record.status]] as const)]}/></Field>
        {batch && <div className="history-actions"><Button variant="secondary" size="small" leadingIcon={Send}
          onClick={() => openHistoryUpload()}>批量投稿到 B 站</Button></div>}
        {batch?.items.length ? <div className="task-list">{batch.items.map((entry) => <button type="button" className="task-row"
          key={entry.item_id} aria-pressed={item?.item_id === entry.item_id} onClick={() => setSelectedTask(entry.item_id)}>
          <span>{entry.output_name || sourceLabel(entry.source_value,entry.source_kind)}</span><StateChip status={entry.status}/>
          <progress aria-label="任务进度" max={100} value={entry.progress}/>
        </button>)}</div> : <p className="muted task-placeholder">提交后可在这里跟踪进度。</p>}
      </section>

      <div className="preview-column">
        <section className="surface preview-pane" aria-label="字幕预览">
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
              <Button variant="secondary" size="small" disabled={!row || previewBusy} onClick={captureFrame}>
                {previewBusy ? '取帧中' : '抓取预览'}</Button>
            </div>
          </div>
        </section>
        <section className="surface task-detail" aria-label="任务详情">
          <div className="section-heading"><h2>任务详情</h2>{item && <StateChip status={item.status}/>}</div>
          {!item ? <p className="muted">选择一项任务查看阶段、错误和导出结果。</p> : <>
            <p className="item-title">{item.output_name || sourceLabel(item.source_value,item.source_kind)}</p>
            <ol className="stage-strip">{steps.map(([key, label]) => {
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
              {([
                [item.result?.final_video_url,'导出 MP4','.mp4'],[item.result?.english_srt_url,'原文 SRT','-原文.srt'],
                [item.result?.translated_srt_url,'译文 SRT','-译文.srt'],[item.result?.bilingual_srt_url,'双语 SRT','-双语.srt'],
              ] as const).map(([url,label,suffix]) => url && <Button key={suffix} variant="secondary" size="small" leadingIcon={Download}
                onClick={() => perform(async () => {
                  if (await saveAs((item.output_name || '视频') + suffix,{format:'artifact',artifact_url:url})) setNotice({text:'文件已导出'})
                })}>{label}</Button>)}
              {item.result?.transcript_id && <Button variant="ghost" size="small" onClick={() => onTranscript(item.result!.transcript_id!)}>查看字幕</Button>}
              {item.result?.bilibili_url && <a target="_blank" rel="noreferrer" href={item.result.bilibili_url}>查看 B 站稿件</a>}
            </div>
          </>}
        </section>
      </div>
      </motion.div>
      {!narrow && <aside className="surface inspector" aria-label="输出参数">
        <div className="section-heading inspector-heading"><div className="section-icon"><SlidersHorizontal size={18}/></div><h2>输出参数</h2></div>
        {inspectorContent}
      </aside>}
    </div>
    {narrow && <Modal open={inspector} title="输出参数" onClose={() => setInspector(false)} drawer>{inspectorContent}</Modal>}
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
              <span><strong>{entry.output_name || sourceLabel(entry.source_value,entry.source_kind)}</strong>
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
    <Modal open={paste} title="添加 YouTube 或 B 站链接" onClose={() => setPaste(false)}>
      <form className="form-stack" onSubmit={(event) => {
        event.preventDefault()
        try {
          add(links.split(/[\s,，]+/).filter(Boolean))
          setLinks(''); setLinkError(''); setPaste(false)
        } catch (error) { setLinkError(errorMessage(error)) }
      }}>
        <Field label="链接（每行一个）"><textarea value={links} rows={5} placeholder={'https://www.youtube.com/watch?v=…\nhttps://www.bilibili.com/video/BV…'}
          onChange={(event) => {setLinks(event.target.value); setLinkError('')}}/></Field>
        {linkError && <Feedback notice={{text:linkError,error:true}}/>}
        <div className="toolbar"><Button variant="ghost" onClick={() => setPaste(false)}>取消</Button>
          <Button type="submit" disabled={!links.trim()}>加入队列</Button></div>
      </form>
    </Modal>
  </>
}
