import { useEffect, useState } from 'react'
import { leaf, request, sourceNames, type Item, type SourceKind, type TranscriptSummary } from './api'

type Source = { kind: SourceKind | 'subtitle'; source: string; title?: string }
type OnlineSource = [source: string, kind: 'youtube' | 'bilibili']
const lookups = new Map<string, Promise<string>>()
const queue: (() => void)[] = []
let activeLookups = 0

function startLookups() {
  while (activeLookups < 3 && queue.length) {
    activeLookups++
    queue.shift()?.()
  }
}

function lookup(source: string, kind: OnlineSource[1]): Promise<string> {
  const existing = lookups.get(source)
  if (existing) return existing
  const pending = new Promise<string>((resolve) => {
    queue.push(() => {
      void request<{title: string}>('/desktop/source-title', 'POST', {source_kind:kind, source_value:source})
        .then((response) => resolve(response.title || ''), () => resolve(''))
        .finally(() => { activeLookups--; startLookups() })
    })
    startLookups()
  })
  lookups.set(source, pending)
  return pending
}

function legacyTitle(title?: string) {
  const text = title?.trim()
  return text && !/^(https?:\/\/|(?:source|video)\s*\d*$|YouTube 视频$|B 站视频$)/i.test(text) ? text : undefined
}

export function batchSource(item: Item): Source {
  return {
    source: item.source_value, kind: item.source_kind,
    title: item.source_title || (!item.result?.bilibili_url && !item.result?.bvid && !item.result?.aid
      ? legacyTitle(item.result?.title) : undefined),
  }
}

export function transcriptSource(entry: TranscriptSummary): Source {
  return { source: entry.source || entry.title, kind: entry.source_kind, title: legacyTitle(entry.title) }
}

export function useSourceTitles(entries: Source[]) {
  const [titles, setTitles] = useState<Record<string,string>>({})
  const known = new Map(entries.filter((entry) => entry.title).map((entry) => [entry.source,entry.title]))
  const unknown = JSON.stringify([...new Map(entries.flatMap(({source,kind}): OnlineSource[] =>
    !known.has(source) && (kind === 'youtube' || kind === 'bilibili') ? [[source,kind]] : [])).entries()])

  useEffect(() => {
    let active = true
    for (const [source, kind] of JSON.parse(unknown) as OnlineSource[]) {
      void lookup(source, kind).then((title) => {
        if (active) setTitles((current) => current[source] === title ? current : {...current,[source]:title})
      })
    }
    return () => { active = false }
  }, [unknown])

  const title = (entry: Source) => entry.kind === 'local' || entry.kind === 'subtitle'
    ? leaf(entry.source) : entry.title || known.get(entry.source) || titles[entry.source] || undefined
  return {
    title,
    label: (entry: Source) => title(entry) || sourceNames[entry.kind] +
      (Object.hasOwn(titles, entry.source) ? ' 视频' : ' · 正在获取标题…'),
  }
}
