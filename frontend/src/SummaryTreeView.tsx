import { ChevronDown, ChevronRight, Copy, Edit3, Layers } from 'lucide-react'
import { useMemo, useState } from 'react'
import {
  VIEWPOINT_KIND_LABELS,
  request,
  saveAs,
  timestamp,
  type SummaryPublication,
  type SummaryTree,
  type SummaryTreeNode,
  type SummaryViewpoint,
} from './api'
import { Button } from './ui'

type RefItem = { id: number; cue: number; lo: number; hi: number; start_ms: number; end_ms: number; text: string }

function spanRangeText(node: SummaryTreeNode, isParagraph: boolean) {
  if (isParagraph) {
    if (node.start_cue && node.end_cue) {
      return node.start_cue === node.end_cue ? `第 ${node.start_cue} 段` : `第 ${node.start_cue}–${node.end_cue} 段`
    }
    return ''
  }
  if (node.start_ms != null && node.end_ms != null) {
    return `${timestamp(node.start_ms)}–${timestamp(node.end_ms)}`
  }
  if (node.start_cue && node.end_cue) return `#${node.start_cue}–#${node.end_cue}`
  return ''
}

function collectExpandableIds(nodes: SummaryTreeNode[]): number[] {
  const ids: number[] = []
  const walk = (list: SummaryTreeNode[]) => {
    for (const node of list) {
      if (node.children.length > 0 || node.viewpoints.length > 0) ids.push(node.id)
      walk(node.children)
    }
  }
  walk(nodes)
  return ids
}

function nodeMatches(node: SummaryTreeNode, q: string): boolean {
  if (!q) return true
  const hay = [node.title, node.summary, ...(node.highlights || [])].join(' ').toLocaleLowerCase()
  if (hay.includes(q)) return true
  if (node.viewpoints.some(vp => [vp.claim, vp.topic, vp.evidence, vp.example, vp.quote_translation].join(' ').toLocaleLowerCase().includes(q))) {
    return true
  }
  return node.children.some(child => nodeMatches(child, q))
}

function countTreeViewpoints(node: SummaryTreeNode): number {
  if (!node.children.length) return node.viewpoints.length
  return node.children.reduce((sum, child) => sum + countTreeViewpoints(child), 0)
}

function treeToMarkdown(title: string, tree: SummaryTree, isParagraph: boolean): string {
  const lines: string[] = [`# ${title}`, '']
  if (tree.overview?.summary) {
    lines.push(`> **全篇总览**：${tree.overview.summary}`, '')
  }
  const emit = (node: SummaryTreeNode, prefix: string, depth: number) => {
    const hashes = '#'.repeat(Math.min(6, depth + 1))
    const range = spanRangeText(node, isParagraph)
    lines.push(`${hashes} ${prefix} ${node.title}${range ? `（${range}）` : ''}`, '')
    if (node.summary) lines.push(node.summary, '')
    for (const hl of node.highlights || []) lines.push(`- ${hl}`)
    if (node.highlights?.length) lines.push('')
    node.children.forEach((child, idx) => emit(child, `${prefix}.${idx + 1}`, depth + 1))
    if (node.viewpoints.length) {
      for (const vp of node.viewpoints) {
        const label = VIEWPOINT_KIND_LABELS[vp.kind || ''] || '观点'
        lines.push(`- **[${label}] ${vp.claim}**`)
        if (vp.quote_translation) lines.push(`  - 译文：${vp.quote_translation}`)
        if (vp.evidence) lines.push(`  - 论据：${vp.evidence}`)
        if (vp.example) lines.push(`  - 例子：${vp.example}`)
      }
      lines.push('')
    }
  }
  tree.nodes.forEach((top, idx) => emit(top, String(idx + 1), 1))
  return lines.join('\n').trim() + '\n'
}

function LazySpanRefs({ endpoint, isParagraph, onLocate }: {
  endpoint: string
  isParagraph: boolean
  onLocate: (cue: number) => void
}) {
  const [page, setPage] = useState<{ items: RefItem[]; next: number | null } | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  async function load(after = 0) {
    setLoading(true)
    try {
      setPage(await request(`${endpoint}?after=${after}`))
      setError('')
    } catch {
      setError('原文来源暂不可用，请重试')
    } finally {
      setLoading(false)
    }
  }
  return <div className="tree-lazy-refs">
    <button type="button" className="tree-inline-btn" disabled={loading} onClick={() => page ? setPage(null) : void load()}>
      {loading ? '读取原文…' : page ? '收起原文' : '查看原文'}
    </button>
    {error && <p className="note-ref-error" role="alert">{error}</p>}
    {page && <div className="note-ref-list">
      {page.items.map(ref => (
        <div key={ref.id} className="note-ref-item">
          <button type="button" className="note-ref-jump" onClick={() => onLocate(ref.cue)}>
            {isParagraph ? `第 ${ref.cue} 段 · ${ref.lo}–${ref.hi}` : `${timestamp(ref.start_ms)} · 原文 #${ref.cue}`} ↗
          </button>
          <blockquote className="note-ref-quote">{ref.text}</blockquote>
        </div>
      ))}
      {page.next != null && <Button variant="secondary" size="small" onClick={() => void load(page.next!)}>下一页原文</Button>}
    </div>}
  </div>
}

function TreeViewpointItem({ transcriptId, vp, isParagraph, onJump }: {
  transcriptId: number
  vp: SummaryViewpoint
  isParagraph: boolean
  onJump: (cue: number) => void
}) {
  const kindLabel = VIEWPOINT_KIND_LABELS[vp.kind || ''] || '陈述'
  return <div className="tree-viewpoint-card">
    <div className="tree-vp-head">
      <span className={'slip-kind kind-' + (vp.kind || 'statement')}>{kindLabel}</span>
      {vp.topic && <span className="slip-topic">{vp.topic}</span>}
    </div>
    <p className="tree-vp-claim">{vp.claim}</p>
    {vp.quote_translation && <p className="slip-translation">{vp.quote_translation}</p>}
    {vp.evidence && <p className="slip-detail"><span>论据</span>{vp.evidence}</p>}
    {vp.example && <p className="slip-detail"><span>例子</span>{vp.example}</p>}
    <div className="tree-vp-foot">
      {vp.refs.length > 0 && <div className="slip-ref-chips">
        {vp.refs.slice(0, 4).map(ref => (
          <button type="button" key={ref} className="slip-ref-chip" title="跳转到原文" onClick={() => onJump(ref)}>
            {isParagraph ? `段落 ${ref}` : `原文 #${ref}`} ↗
          </button>
        ))}
      </div>}
      <LazySpanRefs endpoint={`/desktop/knowledge/${transcriptId}/candidates/${vp.id}/references`} isParagraph={isParagraph} onLocate={onJump} />
    </div>
  </div>
}

function TreeBranch({
  transcriptId,
  node,
  prefix,
  isParagraph,
  expandedIds,
  toggle,
  query,
  editingId,
  setEditingId,
  onSaveNode,
  onJump,
}: {
  transcriptId: number
  node: SummaryTreeNode
  prefix: string
  isParagraph: boolean
  expandedIds: Set<number>
  toggle: (id: number) => void
  query: string
  editingId: number | null
  setEditingId: (id: number | null) => void
  onSaveNode: (nodeId: number, title: string, summary: string) => void | Promise<void>
  onJump: (cue: number) => void
}) {
  const [draftTitle, setDraftTitle] = useState(node.title)
  const [draftSummary, setDraftSummary] = useState(node.summary)
  const [saving, setSaving] = useState(false)
  const hasChildren = node.children.length > 0 || node.viewpoints.length > 0
  const isOpen = Boolean(query) || expandedIds.has(node.id)
  const isEditing = editingId === node.id
  const range = spanRangeText(node, isParagraph)
  const vpCount = countTreeViewpoints(node)

  async function saveEdit(event: React.FormEvent) {
    event.preventDefault()
    if (!draftSummary.trim()) return
    setSaving(true)
    try {
      await onSaveNode(node.id, draftTitle.trim(), draftSummary.trim())
      setEditingId(null)
    } finally {
      setSaving(false)
    }
  }

  return <article className={`tree-node depth-${Math.min(3, node.depth)}${isOpen ? ' is-open' : ''}`} data-tree-node={node.id}>
    <div className="tree-node-head">
      <button
        type="button"
        className="tree-toggle-btn"
        aria-expanded={hasChildren ? isOpen : undefined}
        aria-label={isOpen ? `折叠 ${node.title}` : `展开 ${node.title}`}
        disabled={!hasChildren}
        onClick={() => hasChildren && toggle(node.id)}
      >
        {hasChildren ? (isOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />) : <span className="tree-leaf-dot" />}
      </button>
      <div className="tree-node-main">
        <div className="tree-node-title-row">
          <span className="tree-index">{prefix}</span>
          <strong className="tree-title" onClick={() => hasChildren && toggle(node.id)}>{node.title}</strong>
          {node.edited && <span className="tree-edited-tag">已编辑</span>}
          <div className="tree-node-meta">
            {range && (
              <button
                type="button"
                className="slip-ref-chip"
                title="跳转到此节原文"
                onClick={() => node.start_cue && onJump(node.start_cue)}
              >
                {range} ↗
              </button>
            )}
            {node.children.length > 0 && <span className="tree-count-pill">{node.children.length} 子节</span>}
            {vpCount > 0 && <span className="tree-count-pill is-vp">{vpCount} 观点</span>}
            <button
              type="button"
              className="tree-inline-btn"
              title="编辑本层摘要"
              onClick={() => {
                if (isEditing) setEditingId(null)
                else { setDraftTitle(node.title); setDraftSummary(node.summary); setEditingId(node.id) }
              }}
            >
              <Edit3 size={12} /> {isEditing ? '取消' : '编辑'}
            </button>
          </div>
        </div>
        {isEditing ? <form className="tree-edit-form" onSubmit={e => void saveEdit(e)}>
          <input value={draftTitle} maxLength={120} placeholder="节标题" onChange={e => setDraftTitle(e.target.value)} />
          <textarea rows={3} value={draftSummary} maxLength={4000} placeholder="压缩概述" onChange={e => setDraftSummary(e.target.value)} required />
          <div className="tree-edit-actions">
            <Button type="submit" size="small" disabled={saving || !draftSummary.trim()}>{saving ? '保存中…' : '保存'}</Button>
            <Button type="button" variant="secondary" size="small" onClick={() => setEditingId(null)}>取消</Button>
          </div>
        </form> : <>
          {node.summary && <p className="tree-summary">{node.summary}</p>}
          {node.highlights?.length > 0 && <ul className="tree-highlights">
            {node.highlights.map((hl, idx) => <li key={idx}>{hl}</li>)}
          </ul>}
        </>}
        {!node.viewpoints.length && !node.children.length && (
          <LazySpanRefs endpoint={`/desktop/knowledge/${transcriptId}/tree-nodes/${node.id}/references`} isParagraph={isParagraph} onLocate={onJump} />
        )}
      </div>
    </div>
    {hasChildren && isOpen && <div className="tree-branch-children">
      {node.children.map((child, idx) => (
        (!query || nodeMatches(child, query)) && (
          <TreeBranch
            key={child.id}
            transcriptId={transcriptId}
            node={child}
            prefix={`${prefix}.${idx + 1}`}
            isParagraph={isParagraph}
            expandedIds={expandedIds}
            toggle={toggle}
            query={query}
            editingId={editingId}
            setEditingId={setEditingId}
            onSaveNode={onSaveNode}
            onJump={onJump}
          />
        )
      ))}
      {node.viewpoints.length > 0 && <div className="tree-viewpoint-list">
        {node.viewpoints
          .filter(vp => !query || [vp.claim, vp.topic, vp.evidence, vp.example, vp.quote_translation].join(' ').toLocaleLowerCase().includes(query))
          .map(vp => (
            <TreeViewpointItem key={vp.id} transcriptId={transcriptId} vp={vp} isParagraph={isParagraph} onJump={onJump} />
          ))}
      </div>}
    </div>}
  </article>
}

export function SummaryTreeView({
  transcriptId,
  title,
  tree,
  isParagraph,
  busy,
  publishResult,
  onPublishSummary,
  onOpenObsidian,
  onSaveNode,
  onJumpToSource,
  onNotice,
}: {
  transcriptId: number
  title: string
  tree: SummaryTree
  isParagraph: boolean
  busy: boolean
  publishResult: SummaryPublication | null
  onPublishSummary: (newVersion?: boolean) => void | Promise<void>
  onOpenObsidian: (publicationId: string) => void | Promise<void>
  onSaveNode: (nodeId: number, title: string, summary: string) => void | Promise<void>
  onJumpToSource: (cue: number) => void
  onNotice: (notice: { text: string; error?: boolean }) => void
}) {
  const [expandedIds, setExpandedIds] = useState<Set<number>>(() => new Set())
  const [query, setQuery] = useState('')
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editingOverview, setEditingOverview] = useState(false)
  const [ovTitle, setOvTitle] = useState('')
  const [ovSummary, setOvSummary] = useState('')

  const allExpandable = useMemo(() => collectExpandableIds(tree.nodes), [tree.nodes])
  const allExpanded = allExpandable.length > 0 && allExpandable.every(id => expandedIds.has(id))
  const normQuery = query.trim().toLocaleLowerCase()
  const visibleNodes = useMemo(
    () => tree.nodes.filter(node => nodeMatches(node, normQuery)),
    [tree.nodes, normQuery],
  )

  function toggle(id: number) {
    setExpandedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function copyTree() {
    try {
      await navigator.clipboard.writeText(treeToMarkdown(title, tree, isParagraph))
      onNotice({ text: '已复制多层级摘要 Markdown 到剪贴板' })
    } catch {
      onNotice({ text: '无法访问剪贴板，请使用「导出 Markdown」', error: true })
    }
  }

  const plan = tree.plan
  return <div className="summary-tree-pane">
    <div className="note-panel-toolbar">
      <div className="note-actions">
        <Button variant="secondary" size="small" disabled={busy} onClick={() => void onPublishSummary(false)}>
          {busy ? '正在写入' : '写入摘要库'}
        </Button>
        {allExpandable.length > 0 && (
          <Button
            variant="secondary"
            size="small"
            onClick={() => setExpandedIds(allExpanded ? new Set() : new Set(allExpandable))}
          >
            {allExpanded ? '折叠到顶层' : '全部展开'}
          </Button>
        )}
        <Button variant="secondary" size="small" leadingIcon={Copy} onClick={() => void copyTree()}>复制</Button>
        <Button
          variant="secondary"
          size="small"
          onClick={() => void saveAs(title + '-摘要.md', { format: 'markdown', transcript_id: transcriptId, view_mode: 'summary' })}
        >
          导出 Markdown
        </Button>
      </div>
      <div className="tree-stats-bar">
        <span><Layers size={12} aria-hidden="true" /> {plan.summary_layers} 层压缩 · {tree.nodes.length} 主题 · {plan.leaf_count} 小节 · {plan.viewpoint_count} 观点</span>
        {plan.branching_factor > 1 && <small>动态分支 ~{plan.branching_factor}</small>}
      </div>
      {publishResult && <div className="viewpoint-results note-publish-results">
        <div className="note-publish-row">
          <span><strong>{publishResult.title}</strong> · {publishResult.message}</span>
          <span className="note-publish-actions">
            <Button variant="secondary" size="small" onClick={() => void onOpenObsidian(publishResult.publication_id)}>打开文稿</Button>
            {publishResult.status === 'already_published' && !publishResult.unchanged && (
              <Button variant="secondary" size="small" disabled={busy} onClick={() => void onPublishSummary(true)}>另存一篇</Button>
            )}
          </span>
        </div>
      </div>}
      <input
        type="search"
        aria-label="筛选摘要"
        placeholder="筛选多层级摘要、底层观点或典故故事"
        value={query}
        onChange={e => setQuery(e.target.value)}
      />
    </div>

    <div className="slip-scroll thin-scroll summary-tree-scroll">
      {tree.overview && <section className="summary-overview-card" aria-label="全篇总览">
        <div className="summary-overview-head">
          <span className="summary-overview-badge">全篇总览</span>
          <strong>{tree.overview.title}</strong>
          <button
            type="button"
            className="tree-inline-btn"
            onClick={() => {
              if (editingOverview) setEditingOverview(false)
              else { setOvTitle(tree.overview!.title); setOvSummary(tree.overview!.summary); setEditingOverview(true) }
            }}
          >
            <Edit3 size={12} /> {editingOverview ? '取消' : '编辑'}
          </button>
        </div>
        {editingOverview ? <form
          className="tree-edit-form"
          onSubmit={async e => {
            e.preventDefault()
            if (!ovSummary.trim()) return
            await onSaveNode(tree.overview!.id, ovTitle.trim(), ovSummary.trim())
            setEditingOverview(false)
          }}
        >
          <input value={ovTitle} maxLength={120} onChange={e => setOvTitle(e.target.value)} />
          <textarea rows={3} value={ovSummary} maxLength={4000} onChange={e => setOvSummary(e.target.value)} required />
          <div className="tree-edit-actions">
            <Button type="submit" size="small">保存总览</Button>
            <Button type="button" variant="secondary" size="small" onClick={() => setEditingOverview(false)}>取消</Button>
          </div>
        </form> : <>
          <p>{tree.overview.summary}</p>
          {tree.overview.highlights?.length > 0 && <ul className="tree-highlights">
            {tree.overview.highlights.map((hl, idx) => <li key={idx}>{hl}</li>)}
          </ul>}
        </>}
      </section>}

      <div className="summary-tree-list">
        {visibleNodes.map((node, idx) => (
          <TreeBranch
            key={node.id}
            transcriptId={transcriptId}
            node={node}
            prefix={String(idx + 1)}
            isParagraph={isParagraph}
            expandedIds={expandedIds}
            toggle={toggle}
            query={normQuery}
            editingId={editingId}
            setEditingId={setEditingId}
            onSaveNode={onSaveNode}
            onJump={onJumpToSource}
          />
        ))}
        {!visibleNodes.length && <p className="slip-empty">没有匹配的摘要节点或观点。</p>}
      </div>
    </div>
  </div>
}
