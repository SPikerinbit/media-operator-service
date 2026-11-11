import { useEffect, useMemo, useRef, useState } from 'react'
import { request, saveAs, timestamp, type Draft, type Publication, type Settings } from './api'
import { useDraftSession } from './draftSession'
import { parseSrt } from './srt'
import { transcriptSource, useSourceTitles } from './sourceTitles'
import { Button, Busy, Feedback, Field, Select, useActions } from './ui'

export function TranscriptView({ id, settings, translationUrl, onSettings, variant = 'stack', highlightCard = null, onActivateCard, onVisibleCards, onReady }: {
  id: number
  settings: Settings | null
  translationUrl?: string
  onSettings: (section: 'deepseek' | 'obsidian') => void
  variant?: 'stack' | 'desk'
  highlightCard?: number | null
  onActivateCard?: (card: { id: number; refs: number[] }) => void
  onVisibleCards?: (cards: { id: number; refs: number[] }[]) => void
  onReady?: (api: { locate: (cue: number) => void }) => void
}) {
  const [state, session] = useDraftSession(id)
  const { doc, edits, saves, selected, expanded, results, busy, activeCue, mode } = state
  const [filter, setFilter] = useState('')
  const [cueQuery, setCueQuery] = useState('')
  const [slipPage, setSlipPage] = useState(0)
  const readyRef = useRef(onReady)
  readyRef.current = onReady
  const [translations, setTranslations] = useState<Map<number, string>>(new Map())
  const player = useRef<HTMLMediaElement>(null)
  const sourceBody = useRef<HTMLOListElement>(null)
  const cueNodes = useRef(new Map<number, HTMLButtonElement>())
  const { notice, setNotice, perform } = useActions()
  const path = '/desktop/knowledge/' + id
  const identity = doc && transcriptSource(doc)
  const titles = useSourceTitles(identity ? [identity] : [])
  const cues = useMemo(() => new Map(doc?.cues.map((cue) => [cue.number, cue])), [doc?.cues])

  useEffect(() => {
    if (!translationUrl) { setTranslations(new Map()); return }
    let alive = true
    void fetch(translationUrl).then((response) => response.text()).then((text) => { if (alive) setTranslations(parseSrt(text)) }).catch(() => {})
    return () => { alive = false }
  }, [translationUrl])

  function locate(number: number, seek = true) {
    const cue = cues.get(number)
    if (!cue) return
    session.update({ activeCue: number })
    cueNodes.current.get(number)?.scrollIntoView({ block: 'nearest' })
    if (seek && player.current) {
      session.scroll.playback = cue.start_ms / 1000
      if (player.current.readyState >= 1) player.current.currentTime = session.scroll.playback
    }
  }
  async function publishIds(ids: number[], newVersion = false) {
    await Promise.all(ids.map((cardId) => session.save(cardId)))
    const response = await request<{ results: Publication[] }>(path + '/publish', 'POST', { card_ids: ids, new_version: newVersion })
    session.update({
      results: [...session.get().results.filter((result) => !ids.includes(result.card_id)), ...response.results],
      selected: session.get().selected.filter((key) => !response.results.some((result) => result.card_id === key && result.cleared)),
    })
    await session.refresh()
  }
  async function generate() {
    if (!settings?.has_ai_key) { onSettings('deepseek'); return }
    session.update({ busy: 'generate' })
    try {
      const response = await request<{ added: number }>(path + '/generate', 'POST', { send_subtitles: true, mode })
      await session.refresh()
      setNotice({ text: response.added ? '新增 ' + response.added + ' 条观点' : '没有新增观点，已有内容已保留' })
    } finally { session.update({ busy: '' }) }
  }
  async function publish(ids: number[], newVersion = false) {
    if (!settings?.obsidian_vault) { onSettings('obsidian'); return }
    session.update({ busy: 'publish' })
    try {
      await publishIds(ids, newVersion)
      setNotice({ text: '已写入 Obsidian' })
    } finally { session.update({ busy: '' }) }
  }

  useEffect(() => {
    if (!doc || variant !== 'desk') return
    const cards = doc.cards.filter(card => {
      const value = edits[card.id] || card
      return [value.claim, value.quote_translation, value.evidence, value.example].join(' ').toLocaleLowerCase().includes(filter.toLocaleLowerCase())
    }).slice(slipPage * 8, slipPage * 8 + 8)
    onVisibleCards?.(cards.map(card => ({ id: card.id, refs: card.refs })))
  }, [doc, edits, filter, slipPage, variant, onVisibleCards])
  useEffect(() => { if (doc) readyRef.current?.({ locate }) }, [doc])

  if (state.loading) return <Busy>正在载入笔记</Busy>
  if (!doc) return <div><Feedback notice={{ text: state.error, error: true }}/>
    <Button variant="secondary" onClick={() => perform(session.refresh)}>重新载入</Button></div>

  const note = doc.media_type === 'note' || doc.asset_type === 'note'
  const Player = doc.asset_type === 'audio' ? 'audio' : 'video'
  const pictures = (doc.images || []).filter((src) => src.trim())
  const prose = doc.body || doc.description || ''
  const visibleCards = doc.cards.filter((card) => {
    const value = edits[card.id] || card
    return [value.claim, value.quote_translation, value.evidence, value.example, ...card.refs.map((ref) => cues.get(ref)?.text || '')]
      .join(' ').toLocaleLowerCase().includes(filter.toLocaleLowerCase())
  })
  const chosen = selected.length ? selected : doc.cards.map((card) => card.id)
  const slipCards = visibleCards.slice(slipPage * 8, slipPage * 8 + 8)
  const editField = (value: Draft, key: 'claim' | 'quote_translation' | 'evidence' | 'example', label: string) =>
    <Field label={label}><textarea rows={key === 'claim' ? 2 : 3} value={value[key] || ''} disabled={busy === 'publish'}
      maxLength={key === 'claim' ? 4000 : 6000} onChange={(event) => session.edit({ ...value, [key]: event.target.value })}/></Field>
  if (variant === 'desk') {
    const shownCues = doc.cues.filter(cue => !cueQuery || (cue.text + ' ' + (translations.get(cue.number) || '')).toLocaleLowerCase().includes(cueQuery.toLocaleLowerCase()))
    const pages = Math.max(1, Math.ceil(visibleCards.length / 8))
    return <div className="note-desk">
      <div className="note-slips">
        <div className="note-actions">
          <Button variant="secondary" disabled={Boolean(busy)} onClick={() => perform(generate)}>{busy === 'generate' ? '正在提取' : '提取观点'}</Button>
        </div>
        <input type="search" aria-label="筛选观点" placeholder="搜索观点" value={filter} onChange={event => { setFilter(event.target.value); setSlipPage(0) }} />
        {slipCards.map(card => {
          const value = edits[card.id] || card
          const open = expanded === card.id
          return <article key={card.id} className={'viewpoint-slip' + (highlightCard === card.id ? ' is-linked' : '')} data-slip-id={card.id}>
            <button type="button" className="slip-body" onClick={() => onActivateCard?.({ id: card.id, refs: card.refs })}><strong>{value.claim}</strong></button>
            <Button variant="secondary" size="small" onClick={() => session.update({ expanded: open ? null : card.id })}>{open ? '收起' : '编辑'}</Button>
            {open && <div className="draft-editor">{editField(value, 'claim', '主题')}{editField(value, 'quote_translation', '译文')}{editField(value, 'evidence', '说明')}{editField(value, 'example', '例子')}</div>}
          </article>
        })}
        {!visibleCards.length && <p className="slip-empty">还没有观点。</p>}
        {pages > 1 && <div className="slip-pages"><button type="button" disabled={slipPage === 0} onClick={() => setSlipPage(page => page - 1)}>上一组</button><span>{slipPage + 1} / {pages}</span><button type="button" disabled={slipPage >= pages - 1} onClick={() => setSlipPage(page => page + 1)}>下一组</button></div>}
      </div>
      <div className="note-read">
        <div className="note-actions">
          <Button variant="secondary" disabled={!doc.cards.length || Boolean(busy)} onClick={() => perform(() => publish(chosen))}>{busy === 'publish' ? '正在写入' : '写入 Obsidian'}</Button>
          {!note && <Button variant="secondary" onClick={() => perform(async () => { await saveAs(doc.title + '.srt', { format: 'srt', transcript_id: id }) })}>导出字幕</Button>}
          <Button variant="secondary" onClick={() => perform(async () => { await saveAs(doc.title + '.md', { format: 'markdown', transcript_id: id }) })}>导出 Markdown</Button>
        </div>
        <Feedback notice={notice}/>
        <input type="search" aria-label="搜索字幕" placeholder="搜索原文或译文" value={cueQuery} onChange={event => setCueQuery(event.target.value)} />
        {doc.playable && !note && <Player ref={(node) => { player.current = node }} className={Player === 'audio' ? 'note-audio' : 'note-player'}
          controls preload="metadata" src={path + '/media'}
          onLoadedMetadata={() => { if (player.current) player.current.currentTime = session.scroll.playback }}
          onTimeUpdate={() => {
            if (!player.current) return
            session.scroll.playback = player.current.currentTime
            const ms = session.scroll.playback * 1000
            const current = doc.cues.find((entry) => entry.start_ms <= ms && entry.end_ms > ms)
            if (current && current.number !== activeCue) locate(current.number, false)
          }}/>}
        {pictures.length > 0 && <div className="note-images">{pictures.map((src) => <img key={src} src={src} alt=""/>)}</div>}
        {prose && !doc.cues.length && <p className="note-prose">{prose}</p>}
        <ol className="note-cues" ref={sourceBody}>
          {shownCues.map(cue => <li key={cue.number}><button type="button" className="sentence" aria-pressed={activeCue === cue.number} onClick={() => locate(cue.number)} ref={node => { if (node) cueNodes.current.set(cue.number, node); else cueNodes.current.delete(cue.number) }}>
            <time>{note ? '段落 ' + cue.number : timestamp(cue.start_ms)}</time>
            <span>{cue.text}</span>
            {translations.get(cue.number) && <span className="sentence-translation">{translations.get(cue.number)}</span>}
          </button></li>)}
        </ol>
      </div>
    </div>
  }
  return <div className="note-work">
    <div className="note-chrome">
      <h2>{identity ? titles.label(identity) : doc.title}</h2>
      <div className="note-actions">
        <Select value={mode} onChange={(value) => session.update({ mode: value as typeof mode })}
          options={[['curated', '精选关键句'], ['comprehensive', '较完整摘录']]}/>
        <Button variant="secondary" disabled={Boolean(busy)} onClick={() => perform(generate)}>{busy === 'generate' ? '正在提取' : '提取观点'}</Button>
        <Button variant="secondary" disabled={!doc.cards.length || Boolean(busy)} onClick={() => perform(() => publish(chosen))}>
          {busy === 'publish' ? '正在写入' : '写入 Obsidian'}</Button>
        {!note&&<Button variant="secondary" onClick={() => perform(async () => { await saveAs(doc.title + '.srt', { format: 'srt', transcript_id: id }) })}>导出字幕</Button>}
        <Button variant="secondary" onClick={() => perform(async () => { await saveAs(doc.title + '.md', { format: 'markdown', transcript_id: id }) })}>导出 Markdown</Button>
      </div>
      <Feedback notice={notice}/>
      {busy === 'generate' && <Busy>正在提取观点，可以继续读</Busy>}
    </div>
    <div className="note-column">
      {doc.playable && !note && <Player ref={(node) => { player.current = node }} className={Player === 'audio' ? 'note-audio' : 'note-player'}
        controls preload="metadata" src={path + '/media'}
        onLoadedMetadata={() => { if (player.current) player.current.currentTime = session.scroll.playback }}
        onTimeUpdate={() => {
          if (!player.current) return
          session.scroll.playback = player.current.currentTime
          const ms = session.scroll.playback * 1000
          const current = doc.cues.find((entry) => entry.start_ms <= ms && entry.end_ms > ms)
          if (current && current.number !== activeCue) locate(current.number, false)
        }}/>}
      {pictures.length > 0 && <div className="note-images">{pictures.map((src) => <img key={src} src={src} alt=""/>)}</div>}
      {prose && !doc.cues.length && <p className="note-prose">{prose}</p>}
      {<ol className="note-cues" ref={sourceBody}>
        {doc.cues.map((cue) => <li key={cue.number}><button type="button" className="sentence" aria-pressed={activeCue === cue.number}
          onClick={() => locate(cue.number)} ref={(node) => { if (node) cueNodes.current.set(cue.number, node); else cueNodes.current.delete(cue.number) }}>
          <time>{note?'段落 '+cue.number:timestamp(cue.start_ms)}</time>
          <span>{cue.text}</span>
          {translations.get(cue.number) && <span className="sentence-translation">{translations.get(cue.number)}</span>}
        </button></li>)}
      </ol>}
      <div className="viewpoint-list">
        <div className="note-chrome viewpoint-tools">
          <input type="search" aria-label="筛选观点" placeholder="搜索原话、译句或主题" value={filter} onChange={(event) => setFilter(event.target.value)}/>
        </div>
        {visibleCards.map((card) => {
          const value = edits[card.id] || card
          const open = expanded === card.id
          return <article className="viewpoint" key={card.id}>
            <div className="viewpoint-head">
              <label className="check"><input type="checkbox" aria-label={'选中写入：' + value.claim} checked={selected.includes(card.id)}
                disabled={busy === 'publish'} onChange={() => session.update({ selected: selected.includes(card.id) ? selected.filter((key) => key !== card.id) : [...selected, card.id] })}/>
                <strong>{value.claim}</strong></label>
              <Button variant="secondary" size="small" onClick={() => session.update({ expanded: open ? null : card.id })}>{open ? '收起' : '编辑'}</Button>
            </div>
            {value.quote_translation && <p className="viewpoint-translation">{value.quote_translation}</p>}
            <div className="viewpoint-evidence">
              {card.refs.map((ref) => { const cue = cues.get(ref); return cue && <button type="button" key={ref} onClick={() => locate(ref)}>
                <time>{note?'段落 '+cue.number:timestamp(cue.start_ms)}</time><span>{cue.text}</span></button> })}
            </div>
            {open && <div className="draft-editor">{editField(value, 'claim', '主题')}{editField(value, 'quote_translation', '译文')}
              {editField(value, 'evidence', '说明')}{editField(value, 'example', '例子')}</div>}
            {saves[card.id] && <p className={'save-status ' + saves[card.id]}>{({ dirty: '等待保存', saving: '保存中', saved: '已保存', error: '未保存成功' })[saves[card.id]]}
              {saves[card.id] === 'error' && <Button variant="secondary" size="small" onClick={() => perform(() => session.save(card.id))}>重试保存</Button>}</p>}
          </article>
        })}
        {results.length > 0 && <div className="viewpoint-results">{results.map((result) => <div key={result.publication_id || result.card_id}>
          <strong>{result.title || '观点 ' + result.card_id}</strong> {result.message || (result.cleared ? '已写入' : '已写入，新编辑已保留')}
          {result.publication_id && <Button variant="secondary" size="small" onClick={() => perform(async () => {
            await request('/desktop/obsidian/' + result.publication_id + '/open', 'POST')
          })}>打开文稿</Button>}
          {result.status === 'already_published' && !result.cleared && doc.cards.some((card) => card.id === result.card_id) &&
            <Button variant="secondary" size="small" disabled={Boolean(busy)} onClick={() => perform(() => publish([result.card_id], true))}>另存一篇</Button>}
        </div>)}</div>}
      </div>
    </div>
  </div>
}
