import { BookOpen, CircleHelp, Clock3, Download, ExternalLink, FileText, FolderOpen, Link2, Plus, Search, Sparkles } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { errorMessage, labels, native, request, saveAs, sourceNames, timestamp, watchBatch,
  type Draft, type History, type Publication, type Settings, type SourceKind, type Transcript, type TranscriptSummary } from './api'
import { Button, Busy, Feedback, Field, Modal, Select, StateChip, useActions } from './ui'
import { sourceLanguages } from './videoOptions'
import type { VideoTransfer } from './Video'

function DraftEditor({ card, value, checked, disabled, toggle, edit, save, jump, cues }: {
  card: Draft; value: Draft; checked: boolean; disabled: boolean; toggle: () => void; edit: (value: Draft) => void;
  save: () => void; jump: (cue: number) => void; cues: Map<number, Transcript['cues'][number]>
}) {
  return <article className="draft">
    <div className="draft-heading">
      <label className="check"><input type="checkbox" checked={checked} disabled={disabled} onChange={toggle}/> 选中发布</label>
      <span className="meta">草稿</span>
    </div>
    <Field label="主张"><textarea rows={2} value={value.claim} maxLength={4000} disabled={disabled}
      onChange={(e) => edit({...value,claim:e.target.value})}/></Field>
    <Field label="论据"><textarea rows={2} value={value.evidence} maxLength={6000} disabled={disabled}
      onChange={(e) => edit({...value,evidence:e.target.value})}/></Field>
    <Field label="例子"><textarea rows={2} value={value.example} maxLength={6000} disabled={disabled}
      onChange={(e) => edit({...value,example:e.target.value})}/></Field>
    <div className="evidence">{card.refs.map((id) => {
      const cue = cues.get(id)
      return cue && <button className="citation" key={id} onClick={() => jump(id)}>
        <time>{timestamp(cue.start_ms)}</time><span>{cue.text}</span>
      </button>
    })}</div>
    <Button size="small" variant="secondary" onClick={save} disabled={disabled || !value.claim.trim() || card === value}>保存草稿</Button>
  </article>
}

function TranscriptView({ id, settings, onVideo, onSettings }: {
  id: number; settings: Settings | null; onVideo: (transfer: VideoTransfer) => void; onSettings: () => void
}) {
  const [doc, setDoc] = useState<Transcript | null>(null)
  const [loading, setLoading] = useState(true)
  const [edits, setEdits] = useState<Record<number,Draft>>({})
  const [selected, setSelected] = useState<number[]>([])
  const [results, setResults] = useState<Publication[]>([])
  const [activeCue, setActiveCue] = useState<number>()
  const [busy, setBusy] = useState<'generate'|'publish'|'save'|''>('')
  const [confirm, setConfirm] = useState<'generate'|'publish'|null>(null)
  const player = useRef<HTMLVideoElement>(null)
  const cueNodes = useRef(new Map<number, HTMLButtonElement>())
  const { notice, setNotice, perform } = useActions()
  const path = '/desktop/knowledge/' + id

  useEffect(() => {
    let active = true
    void request<Transcript>(path).then((value) => {
      if (active) setDoc(value)
    }).catch((error) => {if (active) setNotice({text:errorMessage(error),error:true})})
      .finally(() => {if (active) setLoading(false)})
    return () => {active = false}
  }, [path,setNotice])
  if (loading) return <div className="surface transcript-empty"><Busy>正在载入字幕</Busy></div>
  if (!doc) return <div className="surface transcript-empty"><Feedback notice={notice}/></div>

  const cues = new Map(doc.cues.map((cue) => [cue.number,cue]))
  function jump(number: number) {
    const cue = cues.get(number)
    if (!cue) return
    setActiveCue(number)
    const target = cueNodes.current.get(number)
    if (target) {
      target.scrollIntoView({block:'nearest',behavior:'instant'})
      target.focus({preventScroll:true})
    }
    const video = player.current
    if (!video) return
    const seek = () => {video.currentTime = cue.start_ms / 1000}
    if (video.readyState >= 1) seek()
    else video.addEventListener('loadedmetadata',seek,{once:true})
  }

  async function saveDraft(cardId: number) {
    const draft = edits[cardId]
    if (!draft) return
    if (!draft.claim.trim()) throw new Error('请填写要发布的观点主张')
    const data = await request<Transcript>(path + '/cards/' + cardId,'PUT', {
      claim:draft.claim, evidence:draft.evidence, example:draft.example,
    })
    setDoc(data)
    setEdits((current) => Object.fromEntries(Object.entries(current).filter(([key]) => Number(key) !== cardId)))
  }
  function publish(ids: number[], newVersion = false) {
    setConfirm(null)
    perform(async () => {
      setBusy('publish')
      try {
        for (const cardId of ids) await saveDraft(cardId)
        const data = await request<{results:Publication[]}>(path + '/publish','POST',{card_ids:ids,new_version:newVersion})
        setResults((current) => [...current.filter((r) => !ids.includes(r.card_id)),...data.results])
        setSelected((current) => current.filter((cardId) => !data.results.some((r) => r.card_id === cardId && r.cleared)))
        setDoc(await request<Transcript>(path))
        const count = data.results.filter((r) => r.status === 'published').length
        if (count) setNotice({text:'已发布 ' + count + ' 张观点卡'})
      } finally {setBusy('')}
    })
  }
  function generate() {
    setConfirm(null)
    perform(async () => {
      setBusy('generate')
      try {
        const response = await request<{added:number}>(path + '/generate','POST',{send_subtitles:true})
        setDoc(await request<Transcript>(path))
        setNotice({text:'新增 ' + response.added + ' 张草稿'})
      } finally {setBusy('')}
    })
  }

  const canMakeVideo = doc.source_kind === 'youtube' || doc.source_kind === 'bilibili' ||
    (doc.source_kind === 'local' && /\.(mp4|mkv|mov|webm|avi|m4v|wmv|mpeg|mpg|ts)$/i.test(doc.source))
  return <div className="transcript-view">
    <section className="surface transcript-header">
      <div><div className="eyebrow">SOURCE MATERIAL</div><h2>{doc.title}</h2><p className="muted">{doc.cues.length} 段原文 · {doc.cards.length} 张草稿</p></div>
      <div className="toolbar compact">
        <Button variant="secondary" size="small" leadingIcon={Download} onClick={() => perform(async () => {
          await saveAs(doc.title + '.srt',{format:'srt',transcript_id:id})
        })}>导出 SRT</Button>
        <Button variant="secondary" size="small" onClick={() => perform(async () => {
          await saveAs(doc.title + '.md',{format:'markdown',transcript_id:id})
        })}>导出 Markdown</Button>
        {canMakeVideo && <Button variant="ghost" size="small" onClick={() =>
          onVideo({id,source:doc.source,kind:doc.source_kind as SourceKind})}>用此字幕制作视频</Button>}
      </div>
    </section>
    <Feedback notice={notice}/>
    <div className="analysis-grid">
      <section className="surface source-pane">
        <div className="section-heading"><div className="section-icon"><FileText size={17}/></div><h2>原文字幕</h2></div>
        {doc.playable && <video ref={player} className="source-player" controls preload="metadata" src={path + '/media'}/>}
        <ol className="cue-list">
          {doc.cues.map((cue) => <li key={cue.number}><button className="cue" aria-pressed={activeCue === cue.number}
            onClick={() => jump(cue.number)} ref={(node) => {if(node) cueNodes.current.set(cue.number,node); else cueNodes.current.delete(cue.number)}}>
            <time>{timestamp(cue.start_ms)}</time><span>{cue.text}</span>
          </button></li>)}
        </ol>
      </section>
      <section className="surface draft-pane">
        <div className="section-heading"><div className="section-icon"><Sparkles size={17}/></div><h2>观点草稿</h2><span className="count">{doc.cards.length}</span></div>
        <p className="muted draft-explainer">在这里整理草稿，把值得长期保留的观点发布到 Obsidian。</p>
        <div className="toolbar draft-toolbar">
          <Button variant="secondary" size="small" leadingIcon={Sparkles} disabled={Boolean(busy)}
            onClick={() => settings?.has_ai_key ? setConfirm('generate') : setNotice({text:'请在设置中配置 DeepSeek API Key',error:true})}>提取观点</Button>
          <Button size="small" leadingIcon={BookOpen} disabled={!selected.length || Boolean(busy)}
            onClick={() => settings?.obsidian_vault ? setConfirm('publish') : onSettings()}>发布到 Obsidian{selected.length ? ' · ' + selected.length : ''}</Button>
        </div>
        {busy === 'generate' && <Busy>正在提取观点，可继续阅读原文</Busy>}
        {busy === 'publish' && <Busy>正在写入本地 Vault</Busy>}
        {!settings?.obsidian_vault && <button type="button" className="text-button" onClick={onSettings}>选择 Obsidian Vault</button>}
        {results.length > 0 && <section className="publication-list" aria-label="发布结果">
          <h3>发布结果</h3>
          {results.map((result) => <div className="publication" key={result.publication_id || result.card_id}>
            <div><strong>{result.title || '草稿 ' + result.card_id}</strong>
              <p>{result.message || (result.status === 'published' ? (result.cleared ? '已发布 · 草稿已清理' : '已发布 · 保留了更新的草稿') :
                result.cleared ? '此前已发布 · 草稿已清理' : '此前已发布 · 当前草稿已保留')}</p>
              {result.publication_id && <details><summary>发布 ID</summary><code>{result.publication_id}</code></details>}
            </div>
            <div className="toolbar compact">
              {result.publication_id && <Button variant="ghost" size="xs" leadingIcon={ExternalLink}
                onClick={() => perform(async () => {await request('/desktop/obsidian/' + result.publication_id + '/open','POST')})}>打开笔记</Button>}
              {result.status === 'already_published' && !result.cleared && doc.cards.some((card) => card.id === result.card_id) &&
                <Button variant="secondary" size="xs" disabled={Boolean(busy)} onClick={() => {
                  if (window.confirm('在 Vault 中另存一篇新笔记，并清理发布成功的草稿？')) publish([result.card_id],true)
                }}>另存新版本</Button>}
            </div>
          </div>)}
        </section>}
        {doc.cards.length === 0 && <div className="empty-state compact"><CircleHelp size={24}/><strong>还没有待整理的观点</strong><p>提取观点后，你可以核对原话再决定保留哪些。</p></div>}
        {doc.cards.map((card) => <DraftEditor key={card.id} card={card} value={edits[card.id] || card} cues={cues}
          checked={selected.includes(card.id)} disabled={Boolean(busy)} jump={jump}
          toggle={() => setSelected((current) => current.includes(card.id) ? current.filter((x) => x !== card.id) : [...current,card.id])}
          edit={(value) => setEdits((current) => ({...current,[card.id]:value}))}
          save={() => perform(async () => {
            setBusy('save')
            try {await saveDraft(card.id); setNotice({text:'草稿已保存'})}
            finally {setBusy('')}
          })}/>)}
      </section>
    </div>
    <Modal open={confirm !== null} title={confirm === 'generate' ? '提取观点' : '发布到 Obsidian'} onClose={() => setConfirm(null)}>
      <p>{confirm === 'generate' ? '允许将当前素材的字幕文本发送给 DeepSeek，以提取观点和引用？' :
        '将选中的 ' + selected.length + ' 张观点卡写入 Vault。成功发布的草稿会自动清理。'}</p>
      <div className="toolbar modal-actions"><Button variant="ghost" onClick={() => setConfirm(null)}>取消</Button>
        <Button onClick={() => confirm === 'generate' ? generate() : publish(selected)}>确认</Button></div>
    </Modal>
  </div>
}

export function Knowledge({ settings, transcriptId, onVideo, onSettings }: {
  settings: Settings | null; transcriptId: number | null; onVideo: (transfer: VideoTransfer) => void; onSettings: () => void
}) {
  const [current, setCurrent] = useState<number|null>(transcriptId)
  const [query, setQuery] = useState('')
  const [rows, setRows] = useState<TranscriptSummary[]>([])
  const [revision, setRevision] = useState(0)
  const [showImport,setShowImport] = useState(false)
  const [kind,setKind] = useState<SourceKind>('local')
  const [source,setSource] = useState('')
  const [language,setLanguage] = useState('auto')
  const [importing,setImporting] = useState(false)
  const [history,setHistory] = useState<History[]>([])
  const [taskId,setTaskId] = useState('')
  const [task,setTask] = useState<import('./api').Batch|null>(null)
  const {notice,setNotice,perform} = useActions()

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
      try {
        const result = await request<{transcript_id?:number;batch_id?:string}>('/desktop/knowledge/import','POST',
          {kind,source,language,rights_confirmed:true})
        if (result.transcript_id) setCurrent(result.transcript_id)
        if (result.batch_id) {setTask(null); setTaskId(result.batch_id)}
        setRevision((n) => n+1); setShowImport(false); setSource('')
      } finally {setImporting(false)}
    })
  }
  const imported = task?.items[0]
  return <>
    <div className="workspace-heading">
      <div><div className="eyebrow">KNOWLEDGE WORKBENCH</div><h1>字幕分析</h1><p>对照原话整理观点，把有价值的内容发布到长期知识库。</p></div>
      <Button leadingIcon={Plus} onClick={() => setShowImport(true)}>导入素材</Button>
    </div>
    {!showImport && <Feedback notice={notice}/>}
    <div className="knowledge-layout">
      <section className="surface library">
        <div className="section-heading"><div className="section-icon"><BookOpen size={17}/></div><h2>待分析素材</h2><span className="count">{rows.length}</span></div>
        <label className="search"><Search size={16}/><input type="search" aria-label="搜索标题、字幕或观点" placeholder="搜索标题、字幕或观点"
          value={query} onChange={(e) => setQuery(e.target.value)}/></label>
        <ul className="library-list">{rows.map((entry) => <li key={entry.id}><button type="button" aria-pressed={current === entry.id}
          onClick={() => setCurrent(entry.id)} title={entry.title}><FileText size={17}/><span><strong>{entry.title}</strong>
            <small>{sourceNames[entry.source_kind]}</small></span>
        </button></li>)}</ul>
        {!rows.length && <div className="empty-state compact"><FileText size={22}/><p>{query ? '没有匹配的素材' : '导入媒体或现成字幕后，在这里查看原文。'}</p></div>}
        {history.length > 0 && <div className="library-jobs">
          <Field label="导入任务"><Select value={taskId} onChange={(id) => {setTask(null);setTaskId(id)}}
            options={[[ '', '查看导入记录' ],...history.map((entry) => [entry.batch_id,entry.title + ' · ' + labels[entry.status]] as const)]}/></Field>
          {imported && <div className="import-task"><StateChip status={imported.status}/><progress aria-label="导入进度" max={100} value={imported.progress}/>
            <p className="muted">{imported.error?.message || imported.progress_detail || imported.message}</p>
            {imported.status === 'failed' && <Button variant="secondary" size="small" onClick={() => perform(async () => {
              const result = await request<import('./api').Batch>('/desktop/batches/' + taskId + '/' + imported.item_id + '/retry','POST',{})
              setTask(result); setTaskId(''); requestAnimationFrame(() => setTaskId(result.batch_id))
            })}>重试导入</Button>}
          </div>}
        </div>}
      </section>
      {current ? <TranscriptView key={current} id={current} settings={settings} onVideo={onVideo} onSettings={onSettings}/> :
        <section className="surface transcript-empty"><div className="empty-state"><div className="empty-icon"><Clock3 size={31}/></div>
          <h2>从一份字幕开始</h2><p>原文、时间戳和待发布观点会在这里并排呈现。</p>
          <Button variant="secondary" leadingIcon={Plus} onClick={() => setShowImport(true)}>导入素材</Button></div></section>}
    </div>
    <Modal open={showImport} title="导入到字幕分析" onClose={() => {if(!importing) setShowImport(false)}}>
      <form className="form-stack" onSubmit={(e) => {e.preventDefault();startImport()}}>
        <Field label="素材类型"><Select value={kind} onChange={(v) => setKind(v as SourceKind)}
          options={[[ 'local','本地音视频或字幕' ],['youtube','YouTube 链接'],['bilibili','B 站链接']]}/></Field>
        <div className="path-row"><Field label={kind === 'local' ? '文件路径' : sourceNames[kind] + '链接'}>
          <input value={source} onChange={(e) => setSource(e.target.value)} placeholder={kind === 'local' ? '选择本地文件' :
            kind === 'youtube' ? 'https://www.youtube.com/watch?v=…' : 'https://www.bilibili.com/video/BV…'}/>
        </Field>
          {kind === 'local' && <Button variant="secondary" leadingIcon={FolderOpen} onClick={() => perform(async () => {
            const files = await (await native()).choose_media(); if(files[0]) setSource(files[0])
          })}>选择文件</Button>}
        </div>
        <Field label="转录语言"><Select value={language} onChange={setLanguage} options={sourceLanguages}/></Field>
        <Feedback notice={notice}/>
        <div className="toolbar"><Button variant="ghost" disabled={importing} onClick={() => setShowImport(false)}>取消</Button>
          <Button leadingIcon={kind === 'local' ? Plus : Link2} type="submit" disabled={importing || !source.trim()}>
            {importing ? '导入中' : '导入'}</Button></div>
      </form>
    </Modal>
  </>
}
