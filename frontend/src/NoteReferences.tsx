import { useState } from 'react'
import { request } from './api'
import { Button } from './ui'

type Ref = { id: number; cue: number; lo: number; hi: number; text: string }
export function NoteReferences({ transcript, card, onLocate }: { transcript: number; card: number; onLocate: (cue: number) => void }) {
  const [page, setPage] = useState<{ items: Ref[]; next: number | null } | null>(null)
  const [error, setError] = useState('')
  async function load(after = 0) {
    try {
      setPage(await request(`/desktop/knowledge/${transcript}/cards/${card}/references?after=${after}`))
      setError('')
    } catch {
      setError('来源暂时不可用，请重试')
    }
  }
  return <div className="note-refs">
    <Button variant="secondary" size="small" onClick={() => page ? setPage(null) : void load()}>{page ? '收起来源' : '查看来源'}</Button>
    {error && <p className="note-ref-error" role="alert">{error}</p>}
    {page && <div className="note-ref-list">
      {page.items.map(ref => (
        <div key={ref.id} className="note-ref-item">
          <button type="button" className="note-ref-jump" onClick={() => onLocate(ref.cue)}>原文 {ref.cue} · {ref.lo}–{ref.hi}</button>
          <blockquote className="note-ref-quote">{ref.text}</blockquote>
        </div>
      ))}
      {page.next != null && <Button variant="secondary" size="small" onClick={() => void load(page.next!)}>下一页来源</Button>}
    </div>}
  </div>
}

export function SourceContinuation({ transcript, number }: { transcript: number; number: number }) {
  const [chunk, setChunk] = useState<{ text: string; next_offset: number | null } | null>(null)
  const [error, setError] = useState('')
  async function load(offset: number) {
    try {
      setChunk(await request(`/desktop/knowledge/${transcript}/source/${number}?offset=${offset}`))
      setError('')
    } catch {
      setError('原文暂时不可用，请重试')
    }
  }
  return <div className="source-cont">
    {error && <p className="note-ref-error" role="alert">{error}</p>}
    {chunk && <p className="source-cont-text">{chunk.text}</p>}
    <Button variant="secondary" size="small" disabled={!!chunk && chunk.next_offset == null} onClick={() => void load(chunk?.next_offset ?? 4000)}>{chunk ? '下一段原文' : '继续阅读本段'}</Button>
  </div>
}
