import { ArrowDown, ArrowRight, ArrowUp, Clapperboard, Download, Film, FolderOpen, GripVertical, HistoryIcon, Link2, ListVideo, Play, SlidersHorizontal, Trash2 } from 'lucide-react'
import { Reorder, useDragControls } from 'motion/react'
import { useEffect, useState } from 'react'
import { leaf, native, request, saveAs, watchBatch, labels, type Batch, type History, type Item, type Settings, type SourceKind } from './api'
import { Button, Busy, Feedback, Field, Modal, Select, StateChip, useActions } from './ui'
import { defaultOptions, getOverride, Inspector, resolveOptions, videoPayload, type Override, type Row, type VideoOptions } from './videoOptions'

const steps = [['download','导入'],['transcribe','转录'],['translate','翻译'],['burn','压制'],['bilibili_upload','投稿']]
export type VideoTransfer = { id: number; source: string; kind: SourceKind }

function sourceLabel(source: string, kind: SourceKind) {
  if (kind === 'local') return leaf(source)
  try { const url = new URL(source); return 'YouTube · ' + (url.searchParams.get('v') || leaf(url.pathname) || url.hostname) }
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
  const [base, setBase] = useState<VideoOptions>(defaultOptions)
  const [overrides, setOverrides] = useState<Record<string, Override>>({})
  const [perItem, setPerItem] = useState(false)
  const [inspector, setInspector] = useState(false)
  const [narrow, setNarrow] = useState(() => window.matchMedia('(max-width: 1150px)').matches)
  const [paste, setPaste] = useState(false)
  const [links, setLinks] = useState('')
  const [rights, setRights] = useState(false)
  const [concurrency, setConcurrency] = useState(2)
  const [history, setHistory] = useState<History[]>([])
  const [batchId, setBatchId] = useState('')
  const [batch, setBatch] = useState<Batch | null>(null)
  const [selectedTask, setSelectedTask] = useState('')
  const [pending, setPending] = useState(false)
  const [preview, setPreview] = useState<{ key: string; url: string }>({ key: '', url: '' })
  const [framePosition, setFramePosition] = useState(50)
  const [previewBusy, setPreviewBusy] = useState(false)
  const { notice, setNotice, perform } = useActions()
  const row = rows.find((entry) => entry.id === selectedId)
  const options = resolveOptions(base, perItem && row ? overrides[row.id] : undefined)
  const item = batch?.items.find((entry) => entry.item_id === selectedTask) || batch?.items[0]

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
  }, [batchId, setNotice])

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
  function add(sources: string[], kind: SourceKind) {
    const seen = new Set(rows.map((entry) => entry.source))
    const entries: Row[] = []
    for (const source of sources) {
      if (!source || seen.has(source)) continue
      seen.add(source)
      entries.push({id: crypto.randomUUID(), source, kind})
    }
    setRows([...rows, ...entries])
    if (entries[0]) setSelectedId(entries[0].id)
  }
  function submit(selectedOnly = false) {
    const candidates = selectedOnly ? (row ? [row] : []) : rows.filter((entry) => !entry.submitted)
    if (pending || !candidates.length) return
    perform(async () => {
      if (!rights) throw new Error('请先确认你有权处理这些素材')
      setPending(true)
      try {
        const model = settings?.ai_model || 'deepseek-flash'
        const data = await request<Batch>('/ui/batches', 'POST', {
          ...videoPayload(base,model), batch_concurrency: concurrency, rights_confirmed: rights,
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
    if (task.stage === 'bilibili_upload' && !window.confirm('请先核对 B 站稿件。确认没有重复投稿后再重试。')) return
    perform(async () => {
      const result = await request<Batch>('/desktop/batches/' + batchId + '/' + task.item_id + '/retry','POST',
        {upload_checked:task.stage === 'bilibili_upload'})
      setBatch(result)
      // Start a fresh stream even when this is the currently displayed batch.
      setBatchId('')
      requestAnimationFrame(() => setBatchId(result.batch_id))
    })
  }
  const previewKey = JSON.stringify([row?.id,options.aspect_ratio,options.resolution,options.fps,options.subtitle_output_mode,options.subtitle_style,framePosition])
  const frame = preview.key === previewKey ? preview.url : ''
  function captureFrame() {
    if (!row) return
    perform(async () => {
      setPreviewBusy(true)
      try {
        const data = await request<{preview_image_url?: string}>('/ui/preview-frame','POST',{
          source_kind:row.kind, source_value:row.source, aspect_ratio:options.aspect_ratio, resolution:options.resolution,
          fps:options.fps, subtitle_output_mode:options.subtitle_output_mode, subtitle_style:options.subtitle_style,
          preview_time_percent:framePosition,
        })
        if (!data.preview_image_url?.startsWith('/files/')) throw new Error('未能取得本地预览，请尝试其他时间点。')
        setPreview({key:previewKey,url:data.preview_image_url})
      } finally {setPreviewBusy(false)}
    })
  }
  function updateOptions(value: VideoOptions) {
    if (!perItem || !row) setBase(value)
    else setOverrides((current) => ({...current,[row.id]:getOverride(base,value)}))
  }
  function showHistory(id: string) {
    setBatchId(id); setBatch(null); setSelectedTask('')
  }
  const inspectorContent = <Inspector options={options} change={updateOptions} settings={settings} row={row} perItem={perItem}
    onScope={setPerItem} reset={() => row && setOverrides((current) => ({...current,[row.id]:{}}))}/>

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
        </Reorder.Group> : <div className="empty-state compact"><Film size={23}/><strong>还没有素材</strong><p>添加本地视频或粘贴 YouTube 链接。</p></div>}
        <div className="queue-bottom">
          <label className="check"><input type="checkbox" checked={rights} onChange={(e) => setRights(e.target.checked)}/> 我有权处理这些素材</label>
          <Field label="并发任务"><Select value={concurrency} onChange={(v) => setConcurrency(Number(v))}
            options={[[1,'1 项'],[2,'2 项 · 推荐'],[3,'3 项'],[4,'4 项'],[5,'5 项']]}/></Field>
          {row?.submitted && <Button variant="ghost" size="small" leadingIcon={ArrowRight} onClick={() => submit(true)}>重新提交当前素材</Button>}
        </div>
        <div className="section-heading task-heading"><HistoryIcon size={17}/><h2>任务记录</h2></div>
        <Field label="批次"><Select value={batchId} onChange={showHistory}
          options={[[ '', '选择历史批次' ],...history.map((record) => [record.batch_id,record.title + ' · ' + labels[record.status]] as const)]}/></Field>
        {batch?.items.length ? <div className="task-list">{batch.items.map((entry) => <button type="button" className="task-row"
          key={entry.item_id} aria-pressed={item?.item_id === entry.item_id} onClick={() => setSelectedTask(entry.item_id)}>
          <span>{entry.output_name || sourceLabel(entry.source_value,entry.source_kind)}</span><StateChip status={entry.status}/>
          <progress aria-label="任务进度" max={100} value={entry.progress}/>
        </button>)}</div> : <p className="muted task-placeholder">提交后可在这里跟踪进度。</p>}
      </section>

      <div className="preview-column">
        <section className="surface preview-pane" aria-label="字幕预览">
          <div className="section-heading"><div className="section-icon"><Clapperboard size={18}/></div><h2>字幕预览</h2>
            <span className="preview-mode">{frame ? '实际画面 · 示例字幕' : '样式示意'}</span></div>
          <div className="preview-body">
            <div className={'video-canvas ' + (options.aspect_ratio === '9:16' ? 'portrait' : options.aspect_ratio === '1:1' ? 'square' : '')}>
              {frame ? <img src={frame} alt="含所选字幕样式的视频帧"/> : <>
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
            {item.log_tail?.length ? <details className="task-log"><summary>运行详情</summary><pre>{item.log_tail.join('\n')}</pre></details> : null}
            <div className="toolbar compact">
              {item.status === 'failed' && <Button size="small" onClick={() => retry(item)}>从失败阶段重试</Button>}
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
      {!narrow && <aside className="surface inspector" aria-label="输出参数">
        <div className="section-heading"><div className="section-icon"><SlidersHorizontal size={18}/></div><h2>输出参数</h2></div>
        {inspectorContent}
      </aside>}
    </div>
    {narrow && <Modal open={inspector} title="输出参数" onClose={() => setInspector(false)} drawer>{inspectorContent}</Modal>}
    <Modal open={paste} title="添加 YouTube 链接" onClose={() => setPaste(false)}>
      <form className="form-stack" onSubmit={(event) => {
        event.preventDefault()
        add(links.split(/[\s,，]+/).map((text) => text.trim()).filter(Boolean),'youtube')
        setLinks(''); setPaste(false)
      }}>
        <Field label="链接（每行一个）"><textarea value={links} rows={5} placeholder="https://www.youtube.com/watch?v=…"
          onChange={(event) => setLinks(event.target.value)}/></Field>
        <div className="toolbar"><Button variant="ghost" onClick={() => setPaste(false)}>取消</Button>
          <Button type="submit" disabled={!links.trim()}>加入队列</Button></div>
      </form>
    </Modal>
  </>
}
