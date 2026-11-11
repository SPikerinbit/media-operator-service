import { useCallback, useEffect, useState } from 'react'
import { errorMessage, request, type Item, type SourceKind, type SourceProbe } from './api'
import { resolveOptions, savedVideoOptions, type Override, type VideoOptions } from './videoOptions'

export type Lane = 'publish' | 'notes'
export type LetterState = 'identifying'|'rejected'|'blocked'|'duplicate'|'ready'|'starting'|'queued'|'running'|'succeeded'|'failed'|'removed'|'cancelled'
export type LetterEntry = {
  id:string; client_id?:string; group_id:string; lane:Lane; raw:string; local?:boolean; source?:string; kind?:SourceKind;
  title?:string; author?:string; platform?:string; probe?:SourceProbe; status:LetterState; message:string;
  stage?:string; progress:number; batch_id?:string; item_id?:string; task?:Item; created_at:string;
  result?:NonNullable<Item['result']>&{note_notice?:string}; reuse?:{stage:string;origin_lane:Lane}[]; duplicate_of?:string;
  run?:number; revision?:number; summary?:string[]; progress_known?:boolean; deletable?:boolean;
  original_url?:string; resolved_fetch_url?:string; canonical_url?:string; identity?:string;
  refresh_reason?:string; undo_until?:number
}
export type LetterGroup = { id:string;lane:Lane;created_at:string;options:Partial<VideoOptions>;overrides:Record<string,Override>;
  prepared:string[];revision:number;legacy?:boolean }
export type InboxState = {groups:LetterGroup[];entries:LetterEntry[]}
export type PaperLine = {id:string;text:string;local?:boolean}
export const sections = [{id:'output',label:'输出',summary:'画幅与转录'}, {id:'style',label:'字幕样式',summary:'字形与位置'},
  {id:'publish',label:'投稿信息',summary:'封面与内容'}, {id:'translation',label:'翻译上下文',summary:'背景与术语'}] as const
export const stageLabels:Record<string,string> = {download:'获取素材',transcribe:'Whisper 转录',translate:'生成中文译文',burn:'烧录字幕',bilibili_upload:'提交 B 站',extract:'提取观点',done:'已完成',queued:'等待处理'}

export function optionsOf(group:LetterGroup):VideoOptions {
  const original=group.options as Record<string,unknown>
  const defaults=savedVideoOptions(null)
  const bili={...defaults.bilibili_upload,...(original.bilibili_upload as object||{})}
  if(Array.isArray(bili.tags))bili.tags=bili.tags.join('，')
  bili.tid=bili.tid||0
  return resolveOptions(defaults,{...group.options,bilibili_upload:bili})
}

export function useInbox() {
  const [data,setData]=useState<InboxState>({groups:[],entries:[]})
  const [error,setError]=useState('')
  const refresh=useCallback(async()=>{try{setData(await request<InboxState>('/desktop/inbox/queue'));setError('')}catch(e){setError(errorMessage(e))}},[])
  useEffect(()=>{
    let alive=true
    let fallback:number|undefined
    const stream=new EventSource('/desktop/inbox/events')
    stream.onmessage=e=>{if(!alive)return;try{setData(JSON.parse(e.data));setError('');if(fallback){clearInterval(fallback);fallback=undefined}}catch{setError('读取来信状态失败')}}
    stream.onerror=()=>{if(alive&&!fallback)fallback=window.setInterval(()=>void refresh(),4000)}
    void refresh()
    return()=>{alive=false;stream.close();clearInterval(fallback)}
  },[refresh])
  return {data,error,refresh}
}

const URL_RE = /https?:\/\/[^\s<>"'，。；！？、）】》]+/gi
const FILE_URL = /file:\/\/[^\s<>"']+/gi
const QUOTED_PATH = /(["'])((?:[A-Za-z]:[\\/]|\\\\)[^"']+)\1/g
const LINE_PATH = /^[ \t]*((?:[A-Za-z]:[\\/]|\\\\)[^\r\n]*\S)[ \t]*$/gm
const AUTHOR = /【\s*(.+?)\s*的作品】/
const SHARE_PREFIX = /^(?:\d+(?:\.\d+)?\s+)?(?:复制打开(?:抖音|小红书)[，,]?\s*(?:看看)?)/
const TRAILING_DOTS = /(?:\.{3,}|…+|。{2,})$/u
const SITES: [string, string, string[]][] = [
  ['YouTube', 'youtube', ['youtube.com', 'youtu.be']],
  ['B 站', 'bilibili', ['bilibili.com', 'b23.tv']],
  ['抖音', 'url', ['douyin.com', 'iesdouyin.com']],
  ['小红书', 'url', ['xiaohongshu.com', 'xhslink.com', 'xhslink.cn']],
  ['小宇宙', 'url', ['xiaoyuzhoufm.com']],
]

export type ClassifiedLetter = {
  kind: 'url' | 'local'; local: boolean; text: string; source: string; url: string; source_kind: string;
  platform: string; title: string; author: string
}
type Span = { start: number; end: number; kind: 'url' | 'local'; source: string; raw: string }

function domainMatches(host: string, domain: string) {
  const left = host.toLowerCase().replace(/\.$/, '')
  const right = domain.toLowerCase().replace(/\.$/, '')
  return left === right || left.endsWith('.' + right)
}
function platformOf(url: string) {
  let host = ''
  try { host = new URL(url).hostname.toLowerCase() } catch { host = '' }
  for (const [label, kind, domains] of SITES) {
    if (domains.some(domain => domainMatches(host, domain))) return { platform: label, source_kind: kind }
  }
  return { platform: host, source_kind: 'url' }
}
function cleanTitle(value: string) {
  const stripped = value.replace(/\s+/g, ' ').replace(/^[\s\-—:：]+|[\s\-—:：]+$/g, '')
  return stripped.replace(SHARE_PREFIX, '').trim().replace(TRAILING_DOTS, '……').trim()
}
function titleLine(prefix: string) {
  const lines = prefix.split(/\r?\n/).map(line => line.trim()).filter(Boolean)
  return lines.at(-1) || ''
}
function rstripUrl(url: string) { return url.replace(/[.,;:)\]}]+$/, '') }
function fileUrlPath(url: string) {
  const parsed = new URL(url)
  let path = decodeURIComponent(parsed.pathname || '')
  const host = parsed.hostname.toLowerCase()
  if (host && host !== 'localhost') return '\\\\' + parsed.hostname + '\\' + path.replace(/\//g, '\\').replace(/^\\+/, '')
  if (path.startsWith('/') && path.length >= 3 && path[2] === ':') path = path.slice(1)
  return path.replace(/\//g, '\\')
}
function normalizePath(value: string) {
  const text = value.trim().replace(/^["']|["']$/g, '')
  return text.toLowerCase().startsWith('file:') ? fileUrlPath(text) : text.replace(/\//g, '\\')
}
function overlaps(span: Span, others: Span[]) {
  return others.some(item => !(span.end <= item.start || span.start >= item.end))
}
function spansOf(text: string) {
  const found: Span[] = []
  for (const match of text.matchAll(FILE_URL)) {
    const raw = match[0]
    const start = match.index ?? 0
    found.push({ start, end: start + raw.length, kind: 'local', source: fileUrlPath(raw), raw })
  }
  for (const match of text.matchAll(QUOTED_PATH)) {
    const raw = match[0]
    const start = match.index ?? 0
    found.push({ start, end: start + raw.length, kind: 'local', source: normalizePath(match[2]), raw })
  }
  for (const match of text.matchAll(URL_RE)) {
    const raw = rstripUrl(match[0])
    const start = match.index ?? 0
    found.push({ start, end: start + raw.length, kind: 'url', source: raw, raw })
  }
  for (const match of text.matchAll(LINE_PATH)) {
    const body = match[1].trim()
    if (body.includes('://')) continue
    const lead = match[0].length - match[0].trimStart().length
    const start = (match.index ?? 0) + lead
    const span: Span = { start, end: start + body.length, kind: 'local', source: normalizePath(body), raw: body }
    if (!overlaps(span, found)) found.push(span)
  }
  found.sort((a, b) => a.start - b.start || (a.kind === 'local' ? 0 : 1) - (b.kind === 'local' ? 0 : 1))
  const kept: Span[] = []
  for (const span of found) if (!overlaps(span, kept)) kept.push(span)
  return kept
}
function urlItem(segment: string, url: string): ClassifiedLetter {
  const authorMatch = AUTHOR.exec(segment || '')
  const author = authorMatch ? authorMatch[1].trim() : ''
  const titleSource = authorMatch ? segment.slice((authorMatch.index ?? 0) + authorMatch[0].length) : segment
  const info = platformOf(url)
  return {
    kind: 'url', local: false, text: (segment || '').trim() || url, source: url, url,
    source_kind: info.source_kind, platform: info.platform, author, title: cleanTitle(titleLine(titleSource) || titleSource),
  }
}
function attachUrl(segment: string, url: string): ClassifiedLetter {
  let picked = urlItem('', url)
  const source = segment || ''
  for (const match of source.matchAll(URL_RE)) {
    const found = rstripUrl(match[0])
    if (found !== url) continue
    picked = urlItem(titleLine(source.slice(0, match.index ?? 0)), url)
    break
  }
  return { ...picked, text: source.trim() || url, source: url }
}
function localItem(span: Span): ClassifiedLetter {
  const title = span.source.split(/[\\/]/).filter(Boolean).at(-1) || span.source
  return { kind: 'local', local: true, text: span.raw.trim(), source: span.source, url: span.source, source_kind: 'local', platform: '本地文件', author: '', title }
}

/** Same letter boundaries as app.share_text.classify_letters. */
export function classifyLetters(text: string): ClassifiedLetter[] {
  const raw = text || ''
  if (!raw.trim()) return []
  const spans = spansOf(raw)
  const urls = spans.filter(span => span.kind === 'url')
  const locals = spans.filter(span => span.kind === 'local')
  const distinct = [...new Set(urls.map(span => span.source))]
  if (distinct.length === 1 && !locals.length) return [attachUrl(raw.trim(), distinct[0])]
  if (!spans.length) return []
  if (!locals.length && distinct.length > 1) {
    const chosen: Span[] = []
    const seen = new Set<string>()
    for (const span of urls) {
      if (seen.has(span.source)) continue
      seen.add(span.source)
      chosen.push(span)
    }
    let start = 0
    return chosen.map((span, index) => {
      const end = index === chosen.length - 1 ? raw.length : span.end
      const item = attachUrl(raw.slice(start, end), span.source)
      start = span.end
      return item
    })
  }
  const items: ClassifiedLetter[] = []
  const seen = new Set<string>()
  for (const span of spans) {
    const key = (span.kind === 'local' ? 'local:' : 'url:') + span.source.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    if (span.kind === 'local') items.push(localItem(span))
    else items.push(attachUrl(raw.slice(raw.lastIndexOf('\n', span.start - 1) + 1, span.end), span.source))
  }
  return items
}

/** One pasted share stays one line. Distinct links and local paths become separate lines. */
export function splitLetters(raw: string): PaperLine[] {
  return classifyLetters(raw).flatMap(item => {
    const text = item.text.replace(/[ \t]*\r?\n[ \t]*/g, ' ').replace(/ {2,}/g, ' ').trim()
    return text ? [{ id: crypto.randomUUID(), text, local: item.local || undefined }] : []
  })
}

export function reuseMark(entry?:LetterEntry):'clean'|'cut'|'charred' {
  return entry?.reuse?.some(r=>r.origin_lane!==entry.lane) ? (entry.lane==='publish'?'cut':'charred'):'clean'
}
export function entryLabel(entry:LetterEntry) {
  return entry.title||entry.raw.replace(/\s+/g,' ').slice(0,120)
}
