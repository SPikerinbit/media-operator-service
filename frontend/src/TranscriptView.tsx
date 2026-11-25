import { Copy, Layers, List, Pause, Play, Plus, Sparkles, Trash2 } from 'lucide-react'
import { NoteReferences, SourceContinuation } from './NoteReferences'
import { SummaryTreeView } from './SummaryTreeView'
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  VIEWPOINT_KINDS,
  VIEWPOINT_KIND_LABELS,
  request,
  saveAs,
  timestamp,
  type Draft,
  type Publication,
  type Settings,
  type SummaryPublication,
  type Transcript,
  type ViewpointKind,
} from './api'
import { useDraftSession } from './draftSession'
import { useNotesMode, type NotesMode } from './notesMode'
import { transcriptSource, useSourceTitles } from './sourceTitles'
import { Button, Busy, Feedback, Field, Select, WorkbenchToast, useActions } from './ui'

const SPEEDS = [1, 1.25, 1.5, 1.75, 2] as const

const ORGANIZE_MODES: { id: NotesMode; label: string; subtitle: string }[] = [
  { id: 'summary', label: '摘要', subtitle: '树状层级' },
  { id: 'curated', label: '核心观点', subtitle: '精炼陈述' },
  { id: 'comprehensive', label: '大多数观点', subtitle: '详尽全览' },
]

function StudyAudioBar({ src, mediaRef, initialTime, follow, onFollow, onTimeChange }: {
  src: string
  mediaRef: React.MutableRefObject<HTMLMediaElement | null>
  initialTime: number
  follow: boolean
  onFollow: (next: boolean) => void
  onTimeChange: (seconds: number) => void
}) {
  const [playing, setPlaying] = useState(false)
  const [current, setCurrent] = useState(0)
  const [duration, setDuration] = useState(0)
  const [rateIndex, setRateIndex] = useState(0)
  const rate = SPEEDS[rateIndex]
  function togglePlay() {
    const el = mediaRef.current
    if (!el) return
    if (el.paused) void el.play().catch(() => {})
    else el.pause()
  }
  function cycleRate() {
    const next = (rateIndex + 1) % SPEEDS.length
    setRateIndex(next)
    if (mediaRef.current) mediaRef.current.playbackRate = SPEEDS[next]
  }
  return <div className="study-audio-bar" aria-label="音频播放器">
    <audio
      ref={node => { mediaRef.current = node }}
      preload="metadata"
      src={src}
      onLoadedMetadata={() => {
        const el = mediaRef.current
        if (!el) return
        setDuration(Number.isFinite(el.duration) ? el.duration : 0)
        if (initialTime > 0) el.currentTime = initialTime
        el.playbackRate = rate
      }}
      onPlay={() => setPlaying(true)}
      onPause={() => setPlaying(false)}
      onEnded={() => setPlaying(false)}
      onTimeUpdate={() => {
        const el = mediaRef.current
        if (!el) return
        setCurrent(el.currentTime)
        onTimeChange(el.currentTime)
      }}
    />
    <button type="button" className="audio-play-btn" aria-label={playing ? '暂停播放' : '开始播放'} onClick={togglePlay}>
      {playing ? <Pause size={15} /> : <Play size={15} />}
    </button>
    <span className="audio-time">{timestamp(current * 1000)}</span>
    <input
      type="range"
      className="audio-seek"
      aria-label="播放进度"
      min={0}
      max={Math.max(1, duration)}
      step={0.25}
      value={Math.min(current, Math.max(1, duration))}
      onChange={e => {
        const next = Number(e.target.value)
        setCurrent(next)
        if (mediaRef.current) mediaRef.current.currentTime = next
      }}
    />
    <span className="audio-time">{duration > 0 ? timestamp(duration * 1000) : '00:00'}</span>
    <button type="button" className="audio-pill-btn" title="切换播放倍速" onClick={cycleRate}>{rate}×</button>
    <button type="button" className={'audio-pill-btn' + (follow ? ' is-on' : '')} aria-pressed={follow} title="播放时自动定位当前原话" onClick={() => onFollow(!follow)}>跟随</button>
  </div>
}

export type NotesTab = 'drafts' | 'source' | 'records'
export type NotesDocMeta = { cardCount: number; cueCount: number; langLabel: string; langClass: string; summaryLayers?: number }

export function TranscriptView({ id, settings, onSettings, variant = 'stack', activeTab, onChangeTab, onMeta, highlightCard = null, onActivateCard, onVisibleCards, onReady, managed = false }: {
  id: number
  settings: Settings | null
  translationUrl?: string
  onSettings: (section: 'deepseek' | 'obsidian') => void
  variant?: 'stack' | 'desk'
  activeTab?: NotesTab
  onChangeTab?: (tab: NotesTab) => void
  onMeta?: (meta: NotesDocMeta) => void
  highlightCard?: number | null
  onActivateCard?: (card: { id: number; refs: number[] }) => void
  onVisibleCards?: (cards: { id: number; refs: number[] }[]) => void
  managed?: boolean
  onReady?: (api: { locate: (cue: number) => void; prepare: () => Promise<void>; refresh: (focusMode?: NotesMode) => Promise<void> }) => void
}) {
  const [state, session] = useDraftSession(id)
  const { doc, edits, saves, selected, expanded, results, summaryResult, busy, activeCue, viewMode } = state
  const [mode, setMode] = useNotesMode()
  const [filter, setFilter] = useState('')
  const [kindFilter, setKindFilter] = useState<string>('all')
  const [cueQuery, setCueQuery] = useState('')
  const [slipPage, setSlipPage] = useState(0)
  const [returnCard, setReturnCard] = useState<number | null>(null)
  const [addingCard, setAddingCard] = useState(false)
  const [newClaim, setNewClaim] = useState('')
  const [newTopic, setNewTopic] = useState('')
  const [newKind, setNewKind] = useState<ViewpointKind>('statement')
  const [newEvidence, setNewEvidence] = useState('')
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null)
  const [followScroll, setFollowScroll] = useState(true)
  const [videoRateIdx, setVideoRateIdx] = useState(0)
  const readyRef = useRef(onReady)
  readyRef.current = onReady
  const metaRef = useRef(onMeta)
  metaRef.current = onMeta
  const tab = activeTab ?? state.panel
  const activeViewMode: NotesMode = (viewMode || doc?.view_mode || doc?.active_mode || 'curated') as NotesMode
  const translations = useMemo(() => new Map(doc?.cues.map(cue => [cue.number, cue.translation || ''])), [doc?.cues])
  const player = useRef<HTMLMediaElement>(null)
  const sourceBody = useRef<HTMLOListElement>(null)
  const readScroll = useRef<HTMLDivElement>(null)
  const slipScroll = useRef<HTMLDivElement>(null)
  const cueNodes = useRef(new Map<number, HTMLButtonElement>())
  const { notice, setNotice, perform } = useActions()
  const path = '/desktop/knowledge/' + id
  const [generationRun, setGenerationRun] = useState<Transcript['note_run']>()
  useEffect(() => {
    if (busy !== 'generate') { setGenerationRun(doc?.note_run); return }
    let alive = true
    const poll = () => void request<Transcript['note_run']>(path + '/run').then(value => { if (alive) setGenerationRun(value) }).catch(() => {})
    poll(); const timer = setInterval(poll, 2000)
    return () => { alive = false; clearInterval(timer) }
  }, [busy, doc?.note_run, path])
  const identity = doc && transcriptSource(doc)
  const titles = useSourceTitles(identity ? [identity] : [])
  const cues = useMemo(() => new Map(doc?.cues.map((cue) => [cue.number, cue])), [doc?.cues])

  const pendingLocate = useRef<{ number: number; seek: boolean } | null>(null)
  useEffect(() => {
    const pending = pendingLocate.current
    if (pending && cues.has(pending.number)) { pendingLocate.current = null; locate(pending.number, pending.seek) }
  }, [cues])
  function locate(number: number, seek = true) {
    const cue = cues.get(number)
    if (!cue) {
      pendingLocate.current = { number, seek }
      void session.refresh(Math.max(0, number - 10), doc?.card_after || 0, activeViewMode).catch(() => { pendingLocate.current = null })
      return
    }
    session.update({ activeCue: number })
    const target = cueNodes.current.get(number)
    if (target && readScroll.current) { const box = readScroll.current; box.scrollTop += target.getBoundingClientRect().top - box.getBoundingClientRect().top - 12 }
    else if (variant !== 'desk') target?.scrollIntoView({ block: 'nearest' })
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
    await session.refresh(doc?.cue_after || 0, doc?.card_after || 0, activeViewMode)
  }
  async function publishSummary(newVersion = false) {
    if (!settings?.obsidian_summary_vault) { onSettings('obsidian'); return }
    session.update({ busy: 'publish-summary' })
    try {
      const response = await request<{ result: SummaryPublication }>(path + '/publish-summary', 'POST', {
        run_id: doc?.summary_tree?.run_id || null,
        new_version: newVersion,
      })
      session.update({ summaryResult: response.result })
      setNotice({ text: response.result.message || '已写入摘要 Obsidian 库' })
    } finally { session.update({ busy: '' }) }
  }
  async function generateMode(targetMode: NotesMode, deriveSiblings = true) {
    if (!settings?.has_ai_key) { onSettings('deepseek'); return }
    session.update({ busy: 'generate' })
    try {
      await Promise.all(Object.keys(session.get().edits).map(cardId => session.save(Number(cardId))))
      const response = await request<{ added: number }>(path + '/generate', 'POST', {
        send_subtitles: true,
        mode: targetMode,
        derive_siblings: deriveSiblings,
      })
      await session.setViewMode(targetMode)
      setSlipPage(0)
      const label = targetMode === 'summary' ? '多层级摘要' : targetMode === 'curated' ? '核心观点' : '大多数观点'
      setNotice({ text: response.added ? `已生成${label}（${response.added} 项）` : `${label}已是最新，已有内容已保留` })
    } finally { session.update({ busy: '' }) }
  }
  async function translateCurrentPage() {
    if (!settings?.has_ai_key) { onSettings('deepseek'); return }
    session.update({ busy: 'translate-page' })
    try {
      const response = await request<{ translated_count: number }>(path + '/translate-page', 'POST', {
        cue_after: doc?.cue_after || 0,
        limit: 64,
      })
      await session.refresh(doc?.cue_after || 0, doc?.card_after || 0, activeViewMode)
      setNotice({ text: response.translated_count ? `已翻译本页 ${response.translated_count} 段原文并缓存` : '本页原文已全部有译文或为中文' })
    } finally { session.update({ busy: '' }) }
  }
  async function createManualCard(event: React.FormEvent) {
    event.preventDefault()
    if (!newClaim.trim()) return
    const targetMode = activeViewMode === 'comprehensive' ? 'comprehensive' : 'curated'
    await perform(async () => {
      await request(path + '/cards', 'POST', {
        claim: newClaim.trim(),
        topic: newTopic.trim(),
        kind: newKind,
        mode: targetMode,
        evidence: newEvidence.trim(),
        refs: activeCue ? [activeCue] : undefined,
      })
      setNewClaim(''); setNewTopic(''); setNewKind('statement'); setNewEvidence(''); setAddingCard(false)
      await session.refresh(doc?.cue_after || 0, 0, targetMode)
      setNotice({ text: '已新增一条手动观点' })
    })
  }
  async function deleteCard(cardId: number) {
    await perform(async () => {
      await request(path + '/cards/' + cardId, 'DELETE')
      setConfirmDeleteId(null)
      session.update({ selected: selected.filter(k => k !== cardId), expanded: expanded === cardId ? null : expanded })
      await session.refresh(doc?.cue_after || 0, doc?.card_after || 0, activeViewMode)
      setNotice({ text: '已删除观点卡' })
    })
  }
  async function copyMarkdown() {
    if (!doc) return
    const lines = [`# ${doc.title}`, '']
    for (const card of doc.cards) {
      const value = edits[card.id] || card
      const kindLabel = value.kind ? VIEWPOINT_KIND_LABELS[value.kind] || '' : ''
      const tags = [kindLabel, value.topic].filter(Boolean).join(' · ')
      lines.push(`## ${tags ? `[${tags}] ` : ''}${value.claim}`, '')
      if (value.quote_translation) lines.push(`> ${value.quote_translation}`, '')
      if (value.evidence) lines.push(`- 论据：${value.evidence}`)
      if (value.example) lines.push(`- 例子：${value.example}`)
      lines.push('')
    }
    try {
      await navigator.clipboard.writeText(lines.join('\n').trim() + '\n')
      setNotice({ text: `已复制 ${doc.cards.length} 条观点 Markdown 到剪贴板` })
    } catch {
      setNotice({ text: '无法访问剪贴板，请使用「导出 Markdown」', error: true })
    }
  }
  async function publish(ids: number[], newVersion = false) {
    const viewpointVault = settings?.obsidian_viewpoint_vault || settings?.obsidian_vault
    if (!viewpointVault) { onSettings('obsidian'); return }
    session.update({ busy: 'publish' })
    try {
      await publishIds(ids, newVersion)
      setNotice({ text: '已写入观点 Obsidian 库' })
    } finally { session.update({ busy: '' }) }
  }

  function jumpToSource(number: number, fromCard?: number) {
    setReturnCard(fromCard ?? 0)
    session.update({ panel: 'source' })
    onChangeTab?.('source')
    requestAnimationFrame(() => locate(number, true))
  }
  function backToDrafts() {
    setReturnCard(null)
    session.update({ panel: 'drafts' })
    onChangeTab?.('drafts')
  }
  useEffect(() => {
    if (!doc) return
    const label = doc.language_profile?.lang_class === 'foreign' ? '外语原文' : doc.language_profile?.lang_class === 'mixed' ? '中英混合' : doc.language_profile?.lang_class === 'zh_native' ? '中文原文' : ''
    const totalCount = activeViewMode === 'summary'
      ? (doc.summary_tree?.nodes.length ?? doc.modes?.summary?.count ?? 0)
      : (doc.card_count ?? doc.cards.length)
    metaRef.current?.({
      cardCount: totalCount,
      cueCount: doc.cue_count ?? doc.cues.length,
      langLabel: label,
      langClass: doc.language_profile?.lang_class || '',
      summaryLayers: doc.summary_tree?.plan?.summary_layers,
    })
  }, [doc, activeViewMode])

  useEffect(() => {
    if (!doc || variant !== 'desk') return
    if (activeViewMode === 'summary' && doc.summary_tree) {
      onVisibleCards?.(doc.summary_tree.nodes.slice(0, 8).map(node => ({
        id: node.id,
        refs: node.start_cue ? [node.start_cue] : [],
      })))
      return
    }
    const cards = doc.cards.filter(card => {
      const value = edits[card.id] || card
      if (kindFilter !== 'all' && (value.kind || 'statement') !== kindFilter) return false
      return [value.claim, value.topic || '', value.quote_translation, value.evidence, value.example].join(' ').toLocaleLowerCase().includes(filter.toLocaleLowerCase())
    }).slice(slipPage * 8, slipPage * 8 + 8)
    onVisibleCards?.(cards.map(card => ({ id: card.id, refs: card.refs })))
  }, [doc, edits, filter, kindFilter, slipPage, variant, activeViewMode, onVisibleCards])

  useEffect(() => {
    if (doc) {
      readyRef.current?.({
        locate,
        prepare: async () => { await Promise.all(Object.keys(session.get().edits).map(key => session.save(Number(key)))) },
        refresh: async (focusMode?: NotesMode) => {
          if (focusMode) {
            await session.setViewMode(focusMode)
            setSlipPage(0)
          } else {
            await session.refresh(doc.cue_after || 0, doc.card_after || 0, activeViewMode)
          }
        },
      })
    }
  }, [doc, activeViewMode])

  useEffect(() => {
    if (highlightCard == null) return
    const node = slipScroll.current?.querySelector<HTMLElement>(`[data-slip-id="${highlightCard}"]`)
    const box = slipScroll.current
    if (node && box) { box.scrollTop += node.getBoundingClientRect().top - box.getBoundingClientRect().top - 12 }
  }, [highlightCard, slipPage, tab])
  useEffect(() => {
    const onEscape = () => { setAddingCard(false); setConfirmDeleteId(null) }
    window.addEventListener('workbench-escape', onEscape)
    return () => window.removeEventListener('workbench-escape', onEscape)
  }, [])

  if (state.loading) return <Busy>正在载入笔记</Busy>
  if (!doc) return <div><Feedback notice={{ text: state.error, error: true }} />
    <Button variant="secondary" onClick={() => perform(() => session.refresh())}>重新载入</Button></div>

  const note = doc.media_type === 'note' || doc.asset_type === 'note'
  const Player = doc.asset_type === 'audio' ? 'audio' : 'video'
  const pictures = (doc.images || []).filter((src) => src.trim())
  const prose = doc.body || doc.description || ''
  const visibleCards = doc.cards.filter((card) => {
    const value = edits[card.id] || card
    if (kindFilter !== 'all' && (value.kind || 'statement') !== kindFilter) return false
    return [value.claim, value.topic || '', value.quote_translation, value.evidence, value.example, ...card.refs.map((ref) => cues.get(ref)?.text || '')]
      .join(' ').toLocaleLowerCase().includes(filter.toLocaleLowerCase())
  })
  const chosen = selected.length ? selected : doc.cards.map((card) => card.id)
  const slipCards = visibleCards.slice(slipPage * 8, slipPage * 8 + 8)
  const editField = (value: Draft, key: 'claim' | 'quote_translation' | 'evidence' | 'example', label: string) =>
    <Field label={label}><textarea rows={key === 'claim' ? 2 : 3} value={value[key] || ''} disabled={busy === 'publish'}
      maxLength={key === 'claim' ? 4000 : 6000} onChange={(event) => session.edit({ ...value, [key]: event.target.value })} /></Field>
  const sourcePaging = <div className="slip-pages">
    <Button variant="secondary" size="small" disabled={!doc.cue_after} onClick={() => perform(() => session.refresh(Math.max(0, (doc.cue_after || 0) - 64), doc.card_after || 0, activeViewMode))}>上一页原文</Button>
    <Button variant="secondary" size="small" disabled={doc.next_cue == null} onClick={() => perform(() => session.refresh(doc.next_cue!, doc.card_after || 0, activeViewMode))}>下一页原文</Button>
  </div>
  const cardPaging = <div className="slip-pages">
    <Button variant="secondary" size="small" disabled={!doc.card_after} onClick={() => perform(async () => { await session.refresh(doc.cue_after, doc.prev_card || 0, activeViewMode); setSlipPage(0) })}>上一页观点</Button>
    <Button variant="secondary" size="small" disabled={doc.next_card == null} onClick={() => perform(async () => { await session.refresh(doc.cue_after, doc.next_card!, activeViewMode); setSlipPage(0) })}>下一页观点</Button>
  </div>
  const totalTokens = generationRun ? generationRun.input_tokens + generationRun.output_tokens : 0
  const runRatio = generationRun && generationRun.total_blocks > 0 ? Math.min(100, Math.round((generationRun.completed_blocks / generationRun.total_blocks) * 100)) : 0
  const canTranslatePage = Boolean(doc.language_profile && doc.language_profile.lang_class !== 'zh_native')
  const usage = generationRun && <div className="note-run-meta">
    <small>正文 {generationRun.completed_blocks}/{generationRun.total_blocks} 块 · {totalTokens.toLocaleString()} token{generationRun.saved_tokens ? ` · 复用省额` : ''}</small>
    {generationRun.total_blocks > 0 && <div className="note-run-bar" aria-hidden="true"><i style={{ width: `${runRatio}%` }} /></div>}
  </div>

  const modeInfo = doc.modes?.[activeViewMode]
  const isViewpointMode = activeViewMode === 'curated' || activeViewMode === 'comprehensive'
  const showViewpointEmptyCTA = isViewpointMode && !doc.cards.length && !modeInfo?.available

  if (variant === 'desk') {
    const shownCues = doc.cues.filter(cue => !cueQuery || (cue.text + ' ' + (translations.get(cue.number) || '')).toLocaleLowerCase().includes(cueQuery.toLocaleLowerCase()))
    const pages = Math.max(1, Math.ceil(visibleCards.length / 8))
    const allCardsSelected = doc.cards.length > 0 && doc.cards.every(card => selected.includes(card.id))
    const hasCardServerPages = Boolean(doc.card_after) || doc.next_card != null
    const hasCueServerPages = Boolean(doc.cue_after) || doc.next_cue != null
    return <>
      <div className="publish-panel note-slips" role="tabpanel" id="notes-drafts" aria-labelledby="tab-notes-drafts" hidden={tab !== 'drafts'}>
        <div className="organize-mode-bar" role="tablist" aria-label="整理呈现方式">
          {ORGANIZE_MODES.map(item => {
            const info = doc.modes?.[item.id]
            const ready = Boolean(info?.available)
            const activeSub = activeViewMode === item.id
            const badge = item.id === 'summary'
              ? (ready ? `${info?.layers || 1}层` : '')
              : (info && info.count > 0 ? String(info.count) : '')
            return <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={activeSub}
              className={'organize-mode-btn' + (activeSub ? ' is-active' : '') + (ready ? ' is-ready' : '')}
              onClick={() => {
                setKindFilter('all')
                setSlipPage(0)
                void session.setViewMode(item.id).catch(() => {})
              }}
            >
              {item.id === 'summary' ? <Layers size={13} aria-hidden="true" /> : <List size={13} aria-hidden="true" />}
              <span>{item.label}</span>
              {badge ? <small className="organize-mode-badge">{badge}</small> : ready ? <i className="organize-ready-dot" aria-hidden="true" /> : null}
            </button>
          })}
        </div>

        {activeViewMode === 'summary' ? (
          doc.summary_tree ? (
            <SummaryTreeView
              transcriptId={id}
              title={doc.title}
              tree={doc.summary_tree}
              isParagraph={note}
              busy={busy === 'publish-summary' || busy === 'generate'}
              publishResult={summaryResult}
              onPublishSummary={newVer => perform(() => publishSummary(Boolean(newVer)))}
              onOpenObsidian={pubId => perform(async () => {
                await request(`/desktop/obsidian/${pubId}/open?vault_kind=summary`, 'POST')
              })}
              onSaveNode={(nodeId, nodeTitle, nodeSummary) => perform(() => session.saveTreeNode(nodeId, nodeTitle, nodeSummary))}
              onJumpToSource={cueNum => jumpToSource(cueNum)}
              onNotice={setNotice}
            />
          ) : (
            <div className="organize-empty-state">
              <Layers size={24} aria-hidden="true" />
              <h3>尚未生成多层级摘要</h3>
              <p>摘要会根据素材长度通过代价模型动态规划压缩层数与分支数量，逐层展开至底层具象观点与原文。</p>
              {modeInfo?.can_reuse_leaves && <span className="reuse-pill"><Sparkles size={12} aria-hidden="true" /> 已检测到可复用底层节点，免重读原文</span>}
              <Button disabled={Boolean(busy)} onClick={() => perform(() => generateMode('summary', false))}>
                {busy === 'generate' ? '正在生成摘要…' : modeInfo?.can_reuse_leaves ? '基于已有底层生成摘要树' : '生成多层级摘要'}
              </Button>
            </div>
          )
        ) : showViewpointEmptyCTA ? (
          <div className="organize-empty-state">
            <List size={24} aria-hidden="true" />
            <h3>{activeViewMode === 'curated' ? '尚未生成核心观点' : '尚未生成大多数观点'}</h3>
            <p>
              {activeViewMode === 'curated'
                ? '核心观点会提炼全篇最具信息量的陈述、判断、启发性事实与典故故事，并做跨主题去重与论据融合。'
                : '大多数观点会高密度扫描原文，保留绝大多数独立陈述、判断、事实、典故、条件与例外，并自动并行衍生核心观点与摘要树。'}
            </p>
            {modeInfo?.can_reuse_leaves && <span className="reuse-pill"><Sparkles size={12} aria-hidden="true" /> 可复用已有底层观点，无需重读原文</span>}
            <Button disabled={Boolean(busy)} onClick={() => perform(() => generateMode(activeViewMode, activeViewMode === 'comprehensive'))}>
              {busy === 'generate'
                ? '正在整理…'
                : modeInfo?.can_reuse_leaves
                  ? '基于已有底层生成核心观点'
                  : activeViewMode === 'curated' ? '生成核心观点' : '生成大多数观点'}
            </Button>
          </div>
        ) : <>
          <div className="note-panel-toolbar">
            <div className="note-actions">
              {!managed && <Button variant="secondary" size="small" disabled={Boolean(busy)} onClick={() => perform(() => generateMode(activeViewMode))}>{busy === 'generate' ? '正在整理' : '重新提取'}</Button>}
              <Button variant="secondary" size="small" disabled={!doc.cards.length || Boolean(busy)} onClick={() => perform(() => publish(chosen))}>
                {busy === 'publish' ? '正在写入' : selected.length ? `写入观点库（${selected.length}）` : '写入观点库'}
              </Button>
              {doc.cards.length > 0 && <Button variant="secondary" size="small" onClick={() => session.update({ selected: allCardsSelected ? [] : doc.cards.map(c => c.id) })}>
                {allCardsSelected ? '取消全选' : '全选本页'}
              </Button>}
              <Button variant="secondary" size="small" leadingIcon={Plus} onClick={() => setAddingCard(v => !v)}>{addingCard ? '取消新建' : '新建观点'}</Button>
              {doc.cards.length > 0 && <Button variant="secondary" size="small" leadingIcon={Copy} onClick={() => void copyMarkdown()}>复制</Button>}
              <Button variant="secondary" size="small" onClick={() => perform(async () => { await saveAs(doc.title + '.md', { format: 'markdown', transcript_id: id, view_mode: activeViewMode }) })}>导出 Markdown</Button>
            </div>
            {addingCard && <form className="new-card-box" onSubmit={e => void createManualCard(e)}>
              <input placeholder="核心陈述、判断、事实或典故（必填）" value={newClaim} maxLength={4000} onChange={e => setNewClaim(e.target.value)} required />
              <div className="new-card-row">
                <select aria-label="观点类型" value={newKind} onChange={e => setNewKind(e.target.value as ViewpointKind)}>
                  {VIEWPOINT_KINDS.map(k => <option key={k.id} value={k.id}>{k.label}</option>)}
                </select>
                <input placeholder="主题标签（可选）" value={newTopic} maxLength={120} onChange={e => setNewTopic(e.target.value)} />
                <Button type="submit" size="small" disabled={!newClaim.trim()}>保存观点</Button>
              </div>
              <textarea rows={2} placeholder="补充论据、背景或案例（可选）" value={newEvidence} maxLength={6000} onChange={e => setNewEvidence(e.target.value)} />
            </form>}
            {usage}
            {hasCardServerPages && cardPaging}
            {results.length > 0 && <div className="viewpoint-results note-publish-results">{results.map((result) => <div key={result.publication_id || result.card_id} className="note-publish-row">
              <span><strong>{result.title || '观点 ' + result.card_id}</strong> · {result.message || (result.cleared ? '已写入观点库' : '已写入观点库，新编辑已保留')}</span>
              <span className="note-publish-actions">
                {result.publication_id && <Button variant="secondary" size="small" onClick={() => perform(async () => {
                  await request('/desktop/obsidian/' + result.publication_id + '/open?vault_kind=viewpoint', 'POST')
                })}>打开文稿</Button>}
                {result.status === 'already_published' && !result.cleared && doc.cards.some((card) => card.id === result.card_id) &&
                  <Button variant="secondary" size="small" disabled={Boolean(busy)} onClick={() => perform(() => publish([result.card_id], true))}>另存一篇</Button>}
              </span>
            </div>)}</div>}
            <div className="kind-filter-row" role="group" aria-label="按观点类型筛选">
              <button type="button" className={'kind-chip' + (kindFilter === 'all' ? ' is-on' : '')} onClick={() => { setKindFilter('all'); setSlipPage(0) }}>全部</button>
              {VIEWPOINT_KINDS.map(k => (
                <button key={k.id} type="button" className={'kind-chip' + (kindFilter === k.id ? ' is-on' : '')} onClick={() => { setKindFilter(k.id); setSlipPage(0) }}>{k.short}</button>
              ))}
            </div>
            <input type="search" aria-label="筛选观点" placeholder="筛选本页陈述、事实、故事、译文或主题" value={filter} onChange={event => { setFilter(event.target.value); setSlipPage(0) }} />
          </div>
          <div className="slip-scroll thin-scroll" ref={slipScroll}>
            {slipCards.map(card => {
              const value = edits[card.id] || card
              const open = expanded === card.id
              const checked = selected.includes(card.id)
              const kindCode = value.kind || ''
              const kindLabel = kindCode ? VIEWPOINT_KIND_LABELS[kindCode] || '' : ''
              return <article key={card.id} className={'viewpoint-slip' + (highlightCard === card.id ? ' is-linked' : '') + (checked ? ' is-picked' : '')} data-slip-id={card.id}>
                <div className="slip-head">
                  <label className="check slip-check"><input type="checkbox" aria-label={'选中写入：' + value.claim} checked={checked} disabled={busy === 'publish'}
                    onChange={() => session.update({ selected: checked ? selected.filter(k => k !== card.id) : [...selected, card.id] })} /></label>
                  <button type="button" className="slip-body" onClick={() => { onActivateCard?.({ id: card.id, refs: card.refs }); if (card.refs[0]) locate(card.refs[0], false) }}>
                    {(kindLabel || value.topic) && <span className="slip-badges">
                      {kindLabel && <span className={'slip-kind kind-' + kindCode}>{kindLabel}</span>}
                      {value.topic && <span className="slip-topic">{value.topic}</span>}
                    </span>}
                    <strong>{value.claim}</strong>
                  </button>
                  <div className="slip-head-actions">
                    <Button variant="secondary" size="small" onClick={() => session.update({ expanded: open ? null : card.id })}>{open ? '收起' : '编辑'}</Button>
                    {confirmDeleteId === card.id ? <>
                      <button type="button" className="slip-delete-confirm" onClick={() => void deleteCard(card.id)}>确认删</button>
                      <button type="button" className="row-delete" onClick={() => setConfirmDeleteId(null)}>取消</button>
                    </> : <button type="button" className="row-delete slip-delete-btn" aria-label={'删除观点：' + value.claim} title="删除此观点" onClick={() => setConfirmDeleteId(card.id)}><Trash2 size={13} /></button>}
                  </div>
                </div>
                {value.quote_translation && <p className="slip-translation">{value.quote_translation}</p>}
                {value.evidence && <p className="slip-detail"><span>论据</span>{value.evidence}</p>}
                {value.example && <p className="slip-detail"><span>例子</span>{value.example}</p>}
                <div className="slip-foot">
                  {card.refs.length > 0 && <div className="slip-ref-chips">
                    {card.refs.slice(0, 4).map(ref => {
                      const cue = cues.get(ref)
                      return <button type="button" key={ref} className="slip-ref-chip" title="跳转到原文" onClick={() => jumpToSource(ref, card.id)}>
                        {note ? `段落 ${ref}` : cue ? timestamp(cue.start_ms) : `#${ref}`} ↗
                      </button>
                    })}
                  </div>}
                  {saves[card.id] && <span className={'save-status ' + saves[card.id]}>
                    {({ dirty: '待保存', saving: '保存中…', saved: '已保存', error: '保存失败' })[saves[card.id]]}
                    {saves[card.id] === 'error' && <button type="button" className="text-action" onClick={() => perform(() => session.save(card.id))}>重试</button>}
                  </span>}
                </div>
                <NoteReferences transcript={id} card={card.id} onLocate={cueNum => jumpToSource(cueNum, card.id)} />
                {open && <div className="draft-editor">
                  <div className="draft-editor-meta">
                    <Field label="类型"><select value={value.kind || 'statement'} disabled={busy === 'publish'} onChange={e => session.edit({ ...value, kind: e.target.value as ViewpointKind })}>
                      {VIEWPOINT_KINDS.map(k => <option key={k.id} value={k.id}>{k.label}</option>)}
                    </select></Field>
                    <Field label="分类标签"><input value={value.topic || ''} maxLength={120} disabled={busy === 'publish'} onChange={e => session.edit({ ...value, topic: e.target.value })} /></Field>
                  </div>
                  {editField(value, 'claim', '主题')}{editField(value, 'quote_translation', '译文')}{editField(value, 'evidence', '说明')}{editField(value, 'example', '例子')}
                </div>}
              </article>
            })}
            {!visibleCards.length && <p className="slip-empty">{doc.cards.length ? '没有匹配的观点。' : '当前视图暂无观点。'}</p>}
          </div>
          {pages > 1 && <div className="slip-pages"><Button variant="secondary" size="small" disabled={slipPage === 0} onClick={() => setSlipPage(page => page - 1)}>上一组</Button><span>{slipPage + 1} / {pages}</span><Button variant="secondary" size="small" disabled={slipPage >= pages - 1} onClick={() => setSlipPage(page => page + 1)}>下一组</Button></div>}
        </>}
      </div>
      <div className="publish-panel note-read" role="tabpanel" id="notes-source" aria-labelledby="tab-notes-source" hidden={tab !== 'source'}>
        <div className="note-panel-toolbar">
          {returnCard != null && <div className="source-return-bar">
            <span>已从整理跳转至此原文</span>
            <button type="button" className="text-action" onClick={backToDrafts}>← 返回整理</button>
          </div>}
          <div className="note-read-bar">
            <div className="note-actions">
              {canTranslatePage && <Button variant="secondary" size="small" disabled={Boolean(busy)} onClick={() => perform(translateCurrentPage)}>{busy === 'translate-page' ? '正在翻译' : '翻译本页原文'}</Button>}
              {!note && <Button variant="secondary" size="small" onClick={() => perform(async () => { await saveAs(doc.title + '.srt', { format: 'srt', transcript_id: id }) })}>导出字幕</Button>}
              <Button variant="secondary" size="small" onClick={() => perform(async () => { await saveAs(doc.title + '.md', { format: 'markdown', transcript_id: id, view_mode: activeViewMode }) })}>导出 Markdown</Button>
            </div>
          </div>
          {hasCueServerPages && sourcePaging}
          <input type="search" aria-label="搜索字幕" placeholder="筛选本页原文" value={cueQuery} onChange={event => setCueQuery(event.target.value)} />
        </div>
        <div className="source-scroll thin-scroll" ref={readScroll}>
          {doc.playable && !note && (Player === 'audio' ? <StudyAudioBar
            src={path + '/media'}
            mediaRef={player}
            initialTime={session.scroll.playback}
            follow={followScroll}
            onFollow={setFollowScroll}
            onTimeChange={seconds => {
              session.scroll.playback = seconds
              if (!followScroll) return
              const ms = seconds * 1000
              const current = doc.cues.find((entry) => entry.start_ms <= ms && entry.end_ms > ms)
              if (current && current.number !== activeCue) locate(current.number, false)
            }}
          /> : <div className="study-video-wrap">
            <video ref={(node) => { player.current = node }} className="note-player"
              controls preload="metadata" src={path + '/media'}
              onLoadedMetadata={() => { if (player.current) { player.current.currentTime = session.scroll.playback; player.current.playbackRate = SPEEDS[videoRateIdx] } }}
              onTimeUpdate={() => {
                if (!player.current) return
                session.scroll.playback = player.current.currentTime
                if (!followScroll) return
                const ms = session.scroll.playback * 1000
                const current = doc.cues.find((entry) => entry.start_ms <= ms && entry.end_ms > ms)
                if (current && current.number !== activeCue) locate(current.number, false)
              }} />
            <div className="study-video-meta">
              <button type="button" className="audio-pill-btn" onClick={() => {
                const next = (videoRateIdx + 1) % SPEEDS.length
                setVideoRateIdx(next)
                if (player.current) player.current.playbackRate = SPEEDS[next]
              }}>倍速 {SPEEDS[videoRateIdx]}×</button>
              <button type="button" className={'audio-pill-btn' + (followScroll ? ' is-on' : '')} aria-pressed={followScroll} onClick={() => setFollowScroll(v => !v)}>跟随原话</button>
            </div>
          </div>)}
          {pictures.length > 0 && <div className="note-images">{pictures.map((src) => <img key={src} src={src} alt="" />)}</div>}
          {prose && !doc.cues.length && <p className="note-prose">{prose}</p>}
          <ol className="note-cues" ref={sourceBody}>
            {shownCues.map(cue => <li key={cue.number}><button type="button" className="sentence" aria-pressed={activeCue === cue.number} onClick={() => locate(cue.number)} ref={node => { if (node) cueNodes.current.set(cue.number, node); else cueNodes.current.delete(cue.number) }}>
              <time>{note ? '段落 ' + cue.number : timestamp(cue.start_ms)}</time>
              <span>{cue.text}</span>
              {translations.get(cue.number) && <span className="sentence-translation">{translations.get(cue.number)}</span>}
            </button>{Boolean(cue.truncated) && <SourceContinuation transcript={id} number={cue.number} />}</li>)}
          </ol>
        </div>
      </div>
      <WorkbenchToast
        toast={notice ? { id: notice.id || 1, text: notice.text, tone: notice.error ? 'error' : 'success', duration: notice.duration } : null}
        onDismiss={() => setNotice(null)}
      />
    </>
  }
  return <div className="note-work">
    <div className="note-chrome">
      {sourcePaging}{cardPaging}{usage}<h2>{identity ? titles.label(identity) : doc.title}</h2>
      <div className="note-actions">
        <Select value={mode} onChange={(value) => setMode(value as NotesMode)}
          options={[['summary', '摘要'], ['curated', '核心观点'], ['comprehensive', '大多数观点']]} />
        <Button variant="secondary" disabled={Boolean(busy)} onClick={() => perform(() => generateMode(mode))}>{busy === 'generate' ? '正在整理' : '开始整理'}</Button>
        <Button variant="secondary" disabled={!doc.cards.length || Boolean(busy)} onClick={() => perform(() => publish(chosen))}>
          {busy === 'publish' ? '正在写入' : '写入观点库'}</Button>
        {!note && <Button variant="secondary" onClick={() => perform(async () => { await saveAs(doc.title + '.srt', { format: 'srt', transcript_id: id }) })}>导出字幕</Button>}
        <Button variant="secondary" onClick={() => perform(async () => { await saveAs(doc.title + '.md', { format: 'markdown', transcript_id: id, view_mode: activeViewMode }) })}>导出 Markdown</Button>
      </div>
      <Feedback notice={notice} />
      {busy === 'generate' && <Busy>正在整理素材，可以继续阅读</Busy>}
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
        }} />}
      {pictures.length > 0 && <div className="note-images">{pictures.map((src) => <img key={src} src={src} alt="" />)}</div>}
      {prose && !doc.cues.length && <p className="note-prose">{prose}</p>}
      <ol className="note-cues" ref={sourceBody}>
        {doc.cues.map((cue) => <li key={cue.number}><button type="button" className="sentence" aria-pressed={activeCue === cue.number}
          onClick={() => locate(cue.number)} ref={(node) => { if (node) cueNodes.current.set(cue.number, node); else cueNodes.current.delete(cue.number) }}>
          <time>{note ? '段落 ' + cue.number : timestamp(cue.start_ms)}</time>
          <span>{cue.text}</span>
          {translations.get(cue.number) && <span className="sentence-translation">{translations.get(cue.number)}</span>}
        </button>{Boolean(cue.truncated) && <SourceContinuation transcript={id} number={cue.number} />}</li>)}
      </ol>
      <div className="viewpoint-list">
        <div className="note-chrome viewpoint-tools">
          <input type="search" aria-label="筛选观点" placeholder="搜索原话、译句或主题" value={filter} onChange={(event) => setFilter(event.target.value)} />
        </div>
        {visibleCards.map((card) => {
          const value = edits[card.id] || card
          const open = expanded === card.id
          return <article className="viewpoint" key={card.id}>
            <div className="viewpoint-head">
              <label className="check"><input type="checkbox" aria-label={'选中写入：' + value.claim} checked={selected.includes(card.id)}
                disabled={busy === 'publish'} onChange={() => session.update({ selected: selected.includes(card.id) ? selected.filter((key) => key !== card.id) : [...selected, card.id] })} />
                <strong>{value.claim}</strong></label>
              <div className="slip-head-actions">
                <Button variant="secondary" size="small" onClick={() => session.update({ expanded: open ? null : card.id })}>{open ? '收起' : '编辑'}</Button>
                {confirmDeleteId === card.id ? <>
                  <button type="button" className="slip-delete-confirm" onClick={() => void deleteCard(card.id)}>确认删</button>
                  <button type="button" className="row-delete" onClick={() => setConfirmDeleteId(null)}>取消</button>
                </> : <button type="button" className="row-delete slip-delete-btn" aria-label={'删除观点：' + value.claim} title="删除此观点" onClick={() => setConfirmDeleteId(card.id)}><Trash2 size={13} /></button>}
              </div>
            </div>
            {value.quote_translation && <p className="viewpoint-translation">{value.quote_translation}</p>}
            <div className="viewpoint-evidence">
              {card.refs.map((ref) => { const cue = cues.get(ref); return cue && <button type="button" key={ref} onClick={() => locate(ref)}>
                <time>{note ? '段落 ' + cue.number : timestamp(cue.start_ms)}</time><span>{cue.text}</span></button> })}
            </div>
            <NoteReferences transcript={id} card={card.id} onLocate={locate} />{open && <div className="draft-editor">{editField(value, 'claim', '主题')}{editField(value, 'quote_translation', '译文')}
              {editField(value, 'evidence', '说明')}{editField(value, 'example', '例子')}</div>}
            {saves[card.id] && <p className={'save-status ' + saves[card.id]}>{({ dirty: '等待保存', saving: '保存中', saved: '已保存', error: '未保存成功' })[saves[card.id]]}
              {saves[card.id] === 'error' && <Button variant="secondary" size="small" onClick={() => perform(() => session.save(card.id))}>重试保存</Button>}</p>}
          </article>
        })}
        {results.length > 0 && <div className="viewpoint-results">{results.map((result) => <div key={result.publication_id || result.card_id}>
          <strong>{result.title || '观点 ' + result.card_id}</strong> {result.message || (result.cleared ? '已写入观点库' : '已写入观点库，新编辑已保留')}
          {result.publication_id && <Button variant="secondary" size="small" onClick={() => perform(async () => {
            await request('/desktop/obsidian/' + result.publication_id + '/open?vault_kind=viewpoint', 'POST')
          })}>打开文稿</Button>}
          {result.status === 'already_published' && !result.cleared && doc.cards.some((card) => card.id === result.card_id) &&
            <Button variant="secondary" size="small" disabled={Boolean(busy)} onClick={() => perform(() => publish([result.card_id], true))}>另存一篇</Button>}
        </div>)}</div>}
      </div>
    </div>
  </div>
}
