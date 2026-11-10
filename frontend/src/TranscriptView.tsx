import { BookOpen, Download, ExternalLink, FileText, Sparkles, ChevronDown } from 'lucide-react'
import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import { request, saveAs, timestamp, type Draft, type Publication, type Settings } from './api'
import { Button, Busy, Feedback, Field, Modal, Select, useActions } from './ui'
import { transcriptSource, useSourceTitles } from './sourceTitles'
import { useDraftSession } from './draftSession'
import type { VideoTransfer } from './Video'

export function TranscriptView({id,settings,onVideo,onSettings}: {
  id:number;settings:Settings|null;onVideo:(transfer:VideoTransfer)=>void;onSettings:()=>void
}) {
  const [state,session] = useDraftSession(id)
  const {doc,edits,saves,selected,expanded,results,busy,activeCue,follow,mode,panel} = state
  const [confirm,setConfirm] = useState<'generate'|'publish'|null>(null)
  const [filter,setFilter] = useState('')
  const player = useRef<HTMLMediaElement>(null)
  const sourceBody = useRef<HTMLOListElement>(null)
  const draftBody = useRef<HTMLDivElement>(null)
  const cueNodes = useRef(new Map<number,HTMLButtonElement>())
  const {notice,setNotice,perform} = useActions()
  const path = '/desktop/knowledge/' + id
  const identity = doc && transcriptSource(doc)
  const titles = useSourceTitles(identity ? [identity] : [])
  const cues = useMemo(() => new Map(doc?.cues.map((cue) => [cue.number,cue])),[doc?.cues])
  useLayoutEffect(() => {
    if (sourceBody.current) sourceBody.current.scrollTop = session.scroll.source
    if (draftBody.current) draftBody.current.scrollTop = session.scroll.drafts
  },[session,state.loading])

  function locate(number:number,seek=true) {
    const cue = cues.get(number)
    if (!cue) return
    session.update({activeCue:number})
    const container = sourceBody.current
    const target = cueNodes.current.get(number)
    const reveal = () => {if (container && target && container.clientHeight) {
      const box = target.getBoundingClientRect(), viewport = container.getBoundingClientRect()
      if (box.top < viewport.top || box.bottom > viewport.bottom)
        container.scrollTop += box.top - viewport.top - container.clientHeight / 3
    }}
    if (container?.clientHeight) reveal(); else requestAnimationFrame(reveal)
    if (seek && player.current) {
      session.scroll.playback = cue.start_ms / 1000
      if (player.current.readyState >= 1) player.current.currentTime = session.scroll.playback
    }
  }
  async function generate() {
    setConfirm(null);session.update({busy:'generate'})
    try {
      const response = await request<{added:number}>(path + '/generate','POST',{send_subtitles:true,mode})
      await session.refresh()
      setNotice({text:response.added ? '新增 ' + response.added + ' 条摘录' : '没有新增摘录，已有内容已保留'})
    } finally {session.update({busy:''})}
  }
  async function publish(ids:number[],newVersion=false) {
    setConfirm(null);session.update({busy:'publish'})
    try {
      await Promise.all(ids.map(session.save))
      const response = await request<{results:Publication[]}>(path + '/publish','POST',{card_ids:ids,new_version:newVersion})
      session.update({results:[...session.get().results.filter((result) => !ids.includes(result.card_id)),...response.results],
        selected:session.get().selected.filter((key) => !response.results.some((result) => result.card_id === key && result.cleared))})
      await session.refresh()
      setNotice({text:'发布完成，可在下方查看每条结果'})
    } finally {session.update({busy:''})}
  }
  if (state.loading) return <div className="surface transcript-empty"><Busy>正在载入字幕</Busy></div>
  if (!doc) return <div className="surface transcript-empty"><Feedback notice={{text:state.error,error:true}}/>
    <Button variant="secondary" onClick={() => perform(session.refresh)}>重新载入</Button></div>

  const canMakeVideo = doc.media_type === 'video' || (!doc.media_type && (['youtube','bilibili'].includes(doc.source_kind) ||
    (doc.source_kind === 'local' && /\.(mp4|mkv|mov|webm|avi|m4v|wmv|mpeg|mpg|ts)$/i.test(doc.source))))
  const Player = doc.asset_type === 'audio' ? 'audio' : 'video'
  const visibleCards = doc.cards.filter((card) => {
    const value = edits[card.id] || card
    return [value.claim,value.quote_translation,value.evidence,value.example,...card.refs.map((ref) => cues.get(ref)?.text || '')]
      .join(' ').toLocaleLowerCase().includes(filter.toLocaleLowerCase())
  })
  const editField = (value:Draft,key:'claim'|'quote_translation'|'evidence'|'example',label:string) =>
    <Field label={label}><textarea rows={key === 'claim' ? 1 : 3} value={value[key] || ''}
      disabled={busy === 'publish'} maxLength={key === 'claim' ? 4000 : 6000}
      onChange={(event) => session.edit({...value,[key]:event.target.value})}/></Field>

  return <div className="transcript-view">
    <header className="transcript-header">
      <div className="source-identity"><h2 title={identity ? titles.label(identity) : doc.title}>{identity ? titles.label(identity) : doc.title}</h2>
        <p className="muted">{doc.cues.length} 段原文 · {doc.cards.length} 条摘录</p></div>
      <div className="toolbar compact">
        <Button variant="ghost" size="small" leadingIcon={Download} onClick={() => perform(async () => {await saveAs(doc.title + '.srt',{format:'srt',transcript_id:id})})}>SRT</Button>
        <Button variant="ghost" size="small" onClick={() => perform(async () => {await saveAs(doc.title + '.md',{format:'markdown',transcript_id:id})})}>Markdown</Button>
        {canMakeVideo && <Button variant="secondary" size="small" onClick={() => onVideo({id,source:doc.source,
          kind:doc.source_kind as VideoTransfer['kind'],title:identity ? titles.title(identity) : doc.title})}>制作视频</Button>}
      </div>
    </header>
    <Feedback notice={notice}/>
    <div className="segmented mobile-panels" aria-label="分析面板">
      <button aria-pressed={panel === 'source'} onClick={() => session.update({panel:'source'})}>原文字幕</button>
      <button aria-pressed={panel === 'drafts'} onClick={() => session.update({panel:'drafts'})}>观点摘录 · {doc.cards.length}</button>
    </div>
    <div className="analysis-grid" data-panel={panel}>
      <section className="surface source-pane" aria-label="原文字幕">
        <div className="pane-heading"><FileText size={17}/><h2>原文字幕</h2>
          {doc.playable && <label className="check follow-control"><input type="checkbox" checked={follow} onChange={(event) => session.update({follow:event.target.checked})}/>跟随播放</label>}</div>
        {doc.playable && <Player ref={(node) => {player.current = node}} className={Player === 'audio' ? 'studio-audio source-audio' : 'source-player'} controls preload="metadata" src={path + '/media'}
          onLoadedMetadata={() => {if(player.current) player.current.currentTime = session.scroll.playback}}
          onTimeUpdate={() => {
            if (!player.current) return
            session.scroll.playback = player.current.currentTime
            const ms = session.scroll.playback * 1000
            const cue = doc.cues.find((entry) => entry.start_ms <= ms && entry.end_ms > ms)
            if (cue && cue.number !== activeCue) {
              if (follow) locate(cue.number,false)
              else session.update({activeCue:cue.number})
            }
          }}/>}
        <ol className="cue-list thin-scroll" ref={sourceBody} onScroll={(event) => {session.scroll.source = event.currentTarget.scrollTop}}>
          {doc.cues.map((cue) => <li key={cue.number}><button className="cue" aria-pressed={activeCue === cue.number}
            onClick={() => locate(cue.number)} ref={(node) => {if(node) cueNodes.current.set(cue.number,node);else cueNodes.current.delete(cue.number)}}>
            <time>{timestamp(cue.start_ms)}</time><span>{cue.text}</span></button></li>)}
        </ol>
      </section>
      <section className="surface draft-pane" aria-label="观点摘录">
        <div className="pane-heading"><Sparkles size={17}/><h2>观点摘录</h2><span className="count">{doc.cards.length}</span></div>
        <div className="draft-controls">
          <div className="extraction-row"><label className="mode-field"><span className="sr-only">提取密度</span><Select value={mode} onChange={(value) => session.update({mode:value as typeof mode})}
            options={[[ 'curated','精选关键句' ],['comprehensive','较完整摘录']]}/></label>
            <Button variant="secondary" size="small" leadingIcon={Sparkles} disabled={Boolean(busy)}
              onClick={() => settings?.has_ai_key ? setConfirm('generate') : setNotice({text:'请在设置中配置 DeepSeek API Key',error:true})}>提取观点</Button></div>
          <input type="search" aria-label="筛选当前素材的观点" placeholder="搜索原话、译句或主题" value={filter} onChange={(event) => setFilter(event.target.value)}/>
          {busy === 'generate' && <Busy>正在筛选原话，可继续阅读和编辑</Busy>}
        </div>
        <div className="draft-list thin-scroll" ref={draftBody} onScroll={(event) => {session.scroll.drafts = event.currentTarget.scrollTop}}>
          {!visibleCards.length && <div className="empty-state"><Sparkles size={26}/><strong>{filter ? '没有匹配的摘录' : '留下值得回看的句子'}</strong>
            <p>{filter ? '换一个关键词试试。' : '提取后，对照原话整理，再发布到 Obsidian。'}</p></div>}
          {visibleCards.map((card) => {
            const value = edits[card.id] || card
            const open = expanded === card.id
            return <article className={'draft' + (open ? ' editing' : '')} key={card.id}>
              <div className="draft-heading"><label className="check"><input type="checkbox" aria-label={'选中发布：' + value.claim}
                checked={selected.includes(card.id)} disabled={busy === 'publish'} onChange={() => session.update({selected:selected.includes(card.id) ? selected.filter((key) => key !== card.id) : [...selected,card.id]})}/>
                <span className="draft-theme">{value.claim}</span></label>
                <button className="edit-toggle" aria-label={(open ? '收起编辑：' : '编辑摘录：') + value.claim} aria-expanded={open}
                  onClick={() => session.update({expanded:open ? null : card.id})}><ChevronDown size={16}/></button></div>
              {value.quote_translation && <div className="translated-quote"><span className="quote-label">中文译句</span><p>{value.quote_translation}</p></div>}
              <div className={'evidence' + (value.quote_translation ? ' with-translation' : '')}>
                {card.refs.map((ref) => {const cue = cues.get(ref);return cue && <button key={ref} className="citation" onClick={() => {session.update({panel:'source'});locate(ref)}}>
                  <time>{timestamp(cue.start_ms)}</time><span>{cue.text}</span></button>})}
              </div>
              {open && <div className="draft-editor">
                {editField(value,'claim','主题')}{editField(value,'quote_translation','中文译句（原话已是中文可留空）')}
                {editField(value,'evidence','论据或简短说明')}{editField(value,'example','原文中的例子')}
              </div>}
              {saves[card.id] && <div className={'save-status ' + saves[card.id]} role="status">
                {({dirty:'等待保存',saving:'保存中',saved:'已保存',error:'未保存成功 · 编辑已保留'})[saves[card.id]]}
                {saves[card.id] === 'error' && <Button variant="ghost" size="xs" onClick={() => perform(() => session.save(card.id))}>重试保存</Button>}</div>}
            </article>
          })}
          {results.length > 0 && <section className="publication-list" aria-label="发布结果"><h3>发布结果</h3>
            {results.map((result) => <div className="publication" key={result.publication_id || result.card_id}>
              <strong>{result.title || '摘录 ' + result.card_id}</strong><p>{result.message || (result.cleared ? '已发布 · 草稿已清理' : '已发布 · 新编辑已保留')}</p>
              {result.publication_id && <details><summary>发布 ID</summary><code>{result.publication_id}</code></details>}
              <div className="toolbar compact">{result.publication_id && <Button variant="ghost" size="small" leadingIcon={ExternalLink}
                onClick={() => perform(async () => {await request('/desktop/obsidian/' + result.publication_id + '/open','POST')})}>打开笔记</Button>}
                {result.status === 'already_published' && !result.cleared && doc.cards.some((card) => card.id === result.card_id) &&
                  <Button variant="secondary" size="small" disabled={Boolean(busy)} onClick={() => {
                    if(window.confirm('另存一篇新笔记，保留 Obsidian 中原有内容？')) perform(() => publish([result.card_id],true))
                  }}>另存新版本</Button>}</div>
            </div>)}</section>}
        </div>
        <footer className="draft-publish">
          <label className="check"><input type="checkbox" disabled={!visibleCards.length || busy === 'publish'}
            checked={visibleCards.length > 0 && visibleCards.every((card) => selected.includes(card.id))}
            onChange={(event) => session.update({selected:event.target.checked ? [...new Set([...selected,...visibleCards.map((card) => card.id)])] : selected.filter((key) => !visibleCards.some((card) => card.id === key))})}/>全选</label>
          <Button size="small" leadingIcon={BookOpen} disabled={!selected.length || Boolean(busy)}
            onClick={() => settings?.obsidian_vault ? setConfirm('publish') : onSettings()}>
            {busy === 'publish' ? '发布中' : '发布到 Obsidian' + (selected.length ? ' · ' + selected.length : '')}</Button>
        </footer>
      </section>
    </div>
    <Modal open={confirm !== null} title={confirm === 'generate' ? '提取观点' : '发布到 Obsidian'} onClose={() => setConfirm(null)}>
      <p>{confirm === 'generate' ? '将当前素材的字幕发送给 DeepSeek，筛选重要原话并生成中文译句。已有摘录和编辑会保留。' :
        '将选中的 ' + selected.length + ' 条摘录写入 Vault，成功发布且没有新编辑的草稿会自动清理。'}</p>
      <div className="toolbar modal-actions"><Button variant="ghost" onClick={() => setConfirm(null)}>取消</Button>
        <Button onClick={() => perform(() => confirm === 'generate' ? generate() : publish(selected))}>确认{confirm === 'generate' ? '提取' : '发布'}</Button></div>
    </Modal>
  </div>
}
