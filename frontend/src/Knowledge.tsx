import { BookOpen, Clock3, FileText, FolderOpen, Link2, Plus, Search, PanelLeft } from 'lucide-react'
import { useEffect, useState } from 'react'
import { errorMessage, historyLabel, native, request, sourceNames, watchBatch, videoLinkKind, linksIn, siteSession,
  type SourceProbe,
  type History, type Settings, type SourceKind, type TranscriptSummary } from './api'
import { Button, Feedback, Field, Modal, Select, StateChip, useActions, useMediaQuery } from './ui'
import { sourceLanguages } from './videoOptions'
import { batchSource, transcriptSource, useSourceTitles } from './sourceTitles'
import { TranscriptView } from './TranscriptView'
import type { VideoTransfer } from './Video'

export function Knowledge({ settings, transcriptId, onVideo, onSettings }: {
  settings: Settings | null; transcriptId: number | null; onVideo: (transfer: VideoTransfer) => void; onSettings: () => void
}) {
  const narrow = useMediaQuery('(max-width: 1279px)')
  const [libraryOpen,setLibraryOpen] = useState(false)
  const [current, setCurrent] = useState<number|null>(transcriptId)
  const [query, setQuery] = useState('')
  const [rows, setRows] = useState<TranscriptSummary[]>([])
  const [revision, setRevision] = useState(0)
  const [showImport,setShowImport] = useState(false)
  const [kind,setKind] = useState<SourceKind>('local')
  const [source,setSource] = useState('')
  const [probe,setProbe] = useState<SourceProbe>()
  const [allowMuxed,setAllowMuxed] = useState(false)
  const [cookie,setCookie] = useState<File>()
  const [language,setLanguage] = useState('auto')
  const [importing,setImporting] = useState(false)
  const [history,setHistory] = useState<History[]>([])
  const [taskId,setTaskId] = useState('')
  const [task,setTask] = useState<import('./api').Batch|null>(null)
  const {notice,setNotice,perform} = useActions()
  const imported = task?.items[0]
  const importSource = imported && batchSource(imported)
  const titles = useSourceTitles([...rows.map(transcriptSource),...(importSource ? [importSource] : [])])

  useEffect(() => {if(transcriptId) setCurrent(transcriptId)},[transcriptId])
  useEffect(() => {
    let active = true
    void request<TranscriptSummary[]>('/desktop/knowledge?q=' + encodeURIComponent(query)).then((data) => {
      if(active) setRows(data)
    }).catch((error) => {if(active) setNotice({text:errorMessage(error),error:true})})
    return () => {active = false}
  },[query,revision,setNotice])
  useEffect(() => {
    let active = true
    void request<History[]>('/desktop/batches?knowledge_only=true').then((data) => {if(active) setHistory(data)}).catch(() => {})
    return () => {active = false}
  },[revision,setNotice])
  useEffect(() => {
    if (!taskId) return
    return watchBatch(taskId,(batch) => {
      setTask(batch)
      const item = batch.items[0]
      if (item?.status === 'succeeded' && item.result?.transcript_id) {
        setCurrent(item.result.transcript_id); setRevision((n) => n+1)
      }
    },(text) => setNotice({text,error:true}))
  },[taskId,setNotice])

  function startImport() {
    perform(async () => {
      setImporting(true)
      let session_id: string | undefined
      try {
        const online = kind !== 'local'
        const link = online ? linksIn(source)[0] : source
        if (!link) throw new Error('请输入公开音视频链接')
        const sourceKind = online ? videoLinkKind(link) : 'local'
        if (online) {
          if (cookie) session_id = await siteSession(link,cookie)
          const result = await request<SourceProbe>('/desktop/sources/probe','POST',{
            source_kind:sourceKind,source_value:link,session_id,
          })
          setProbe(result)
          if (!result.ready) return
          if (result.media_type === 'video' && !result.audio_direct && !allowMuxed) return
        }
        const result = await request<{transcript_id?:number;batch_id?:string}>('/desktop/knowledge/import','POST',
          {kind:sourceKind,source:link,language,rights_confirmed:true,allow_muxed_audio:allowMuxed,session_id})
        if (result.transcript_id) setCurrent(result.transcript_id)
        if (result.batch_id) {setTask(null); setTaskId(result.batch_id)}
        setRevision((n) => n+1); setShowImport(false); setSource('');setProbe(undefined);setCookie(undefined);setAllowMuxed(false)
      } finally {
        if (session_id) void request('/desktop/sources/session/' + session_id,'DELETE').catch(() => {})
        setImporting(false)
      }
    })
  }
  const library = <>
        <div className="section-heading"><div className="section-icon"><BookOpen size={17}/></div><h2>待分析素材</h2><span className="count">{rows.length}</span></div>
        <label className="search"><Search size={16}/><input type="search" aria-label="搜索标题、字幕或观点" placeholder="搜索标题、字幕或观点"
          value={query} onChange={(e) => setQuery(e.target.value)}/></label>
        <ul className="library-list thin-scroll">{rows.map((entry) => <li key={entry.id}><button type="button" aria-pressed={current === entry.id}
          onClick={() => {setCurrent(entry.id);setLibraryOpen(false)}} title={titles.label(transcriptSource(entry))}><FileText size={17}/><span><strong>{titles.label(transcriptSource(entry))}</strong>
            <small>{sourceNames[entry.source_kind]}</small></span>
        </button></li>)}</ul>
        {!rows.length && <div className="empty-state compact"><FileText size={22}/><p>{query ? '没有匹配的素材' : '导入媒体或现成字幕后，在这里查看原文。'}</p></div>}
        {history.length > 0 && <div className="library-jobs">
          <Field label="导入任务"><Select value={taskId} onChange={(id) => {setTask(null);setTaskId(id)}}
            options={[[ '', '查看导入记录' ],...history.map((entry) => [entry.batch_id,historyLabel(entry)] as const)]}/></Field>
          {imported && importSource && <div className="import-task"><strong>{titles.label(importSource)}</strong>
            <StateChip status={imported.status}/><progress aria-label="导入进度" max={100} value={imported.progress}/>
            <p className="muted">{imported.error?.message || imported.progress_detail || imported.message}</p>
            {imported.status === 'failed' && <Button variant="secondary" size="small" onClick={() => perform(async () => {
              const result = await request<import('./api').Batch>('/desktop/batches/' + taskId + '/' + imported.item_id + '/retry','POST',{})
              setTask(result); setTaskId(''); requestAnimationFrame(() => setTaskId(result.batch_id))
            })}>重试导入</Button>}
          </div>}
        </div>}

  </>
  return <>
    <div className="workspace-heading">
      <div><h1>字幕分析</h1></div>
      <div className="toolbar">{narrow && <Button variant="secondary" leadingIcon={PanelLeft} onClick={() => setLibraryOpen(true)}>素材</Button>}
      <Button leadingIcon={Plus} onClick={() => setShowImport(true)}>导入素材</Button></div>
    </div>
    {!showImport && <Feedback notice={notice}/>}
    <div className="knowledge-layout">
      {!narrow && <section className="surface library">{library}</section>}
      {current ? <TranscriptView key={current} id={current} settings={settings} onVideo={onVideo} onSettings={onSettings}/> :
        <section className="surface transcript-empty"><div className="empty-state"><div className="empty-icon"><Clock3 size={31}/></div>
          <h2>从一份字幕开始</h2><p>原文、时间戳和待发布观点会在这里并排呈现。</p>
          <Button variant="secondary" leadingIcon={Plus} onClick={() => setShowImport(true)}>导入素材</Button></div></section>}
    </div>
    {narrow && <Modal drawer open={libraryOpen} title="待分析素材" onClose={() => setLibraryOpen(false)}><div className="library drawer-library">{library}</div></Modal>}
    <Modal open={showImport} title="导入到字幕分析" onClose={() => {if(!importing) setShowImport(false)}}>
      <form className="form-stack" onSubmit={(e) => {e.preventDefault();startImport()}}>
        <Field label="素材类型"><Select value={kind} onChange={(v) => {setKind(v as SourceKind);setSource('');setProbe(undefined);setCookie(undefined);setAllowMuxed(false)}}
          options={[[ 'local','本地音视频或字幕' ],['url','在线音视频链接']]}/></Field>
        <div className="path-row"><Field label={kind === 'local' ? '文件路径' : sourceNames[kind] + '链接'}>
          <input value={source} onChange={(e) => {setSource(e.target.value);setProbe(undefined);setCookie(undefined);setAllowMuxed(false)}}
            placeholder={kind === 'local' ? '选择本地文件' : '粘贴链接或分享文案'}/>
        </Field>
          {kind === 'local' && <Button variant="secondary" leadingIcon={FolderOpen} onClick={() => perform(async () => {
            const files = await (await native()).choose_media(); if(files[0]) setSource(files[0])
          })}>选择文件</Button>}
        </div>
        <Field label="转录语言"><Select value={language} onChange={setLanguage} options={sourceLanguages}/></Field>
        {probe && !probe.ready && <><Feedback notice={{text:probe.message,error:true}}/>
          {probe.code === 'session_required' && <Field label="选择本站 Cookie 文件"><input type="file" accept=".txt,text/plain"
            onChange={(e) => setCookie(e.target.files?.[0])}/></Field>}</>}
        {probe?.ready && probe.media_type === 'video' && !probe.audio_direct && <label className="check">
          <input type="checkbox" checked={allowMuxed} onChange={(e) => setAllowMuxed(e.target.checked)}/>
          该来源只提供合流，允许下载后提取音轨</label>}
        <Feedback notice={notice}/>
        <div className="toolbar"><Button variant="ghost" disabled={importing} onClick={() => setShowImport(false)}>取消</Button>
          <Button leadingIcon={kind === 'local' ? Plus : Link2} type="submit" disabled={importing || !source.trim()}>
            {importing ? '导入中' : '导入'}</Button></div>
      </form>
    </Modal>
  </>
}
