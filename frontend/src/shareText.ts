export type ParsedShare = { url: string; title: string; author: string; site: string; duration?: number }

const SITES: [string, string[]][] = [
  ['抖音', ['douyin.com', 'iesdouyin.com']],
  ['小红书', ['xiaohongshu.com', 'xhslink.com', 'xhslink.cn']],
  ['YouTube', ['youtube.com', 'youtu.be', 'music.youtube.com']],
  ['B 站', ['bilibili.com', 'b23.tv']],
  ['小宇宙', ['xiaoyuzhoufm.com']],
]

const URL_PATTERN = /https?:\/\/[^\s<>"'，。；！？、）】》]+/gi

export function siteOf(value: string) {
  try {
    const host = new URL(value).hostname.toLowerCase().replace(/^www\./, '')
    for (const [name, domains] of SITES) {
      if (domains.some((domain) => host === domain || host.endsWith('.' + domain))) return name
    }
    return ''
  } catch { /* Plain text has no site. */ }
  return ''
}

function finishTitle(raw: string) {
  const text = raw.replace(/\s+/g, ' ').trim()
  if (!text) return ''
  return text.replace(/(?:[.．]{3,}|…+)$/u, '……')
}

function plainTitle(segment: string) {
  let text = segment.replace(/\s+/g, ' ').trim()
  text = text.replace(/复制这段话[\s\S]*$/, '').replace(/复制此链接[\s\S]*$/i, '').trim()
  const cjk = text.search(/[\u3400-\u9fff]/)
  if (cjk > 0) text = text.slice(cjk).trim()
  return finishTitle(text)
}

function titleFrom(segment: string) {
  const marks = [...segment.matchAll(/【([^】]+)的作品】/g)]
  const mark = marks.at(-1)
  if (mark && mark.index !== undefined) {
    return { author: mark[1].trim(), title: finishTitle(segment.slice(mark.index + mark[0].length)) }
  }
  return { author: '', title: plainTitle(segment) }
}

function shareDuration(segment: string) {
  const match = segment.trim().match(/^(\d{1,3})\.(\d{2})(?:\s|$)/)
  if (!match) return undefined
  const minutes = Number(match[1])
  const seconds = Number(match[2])
  if (seconds >= 60) return undefined
  const total = minutes * 60 + seconds
  return total > 0 && total <= 6 * 3600 ? total : undefined
}

export function parseShareText(text: string): ParsedShare[] {
  const source = text.replace(/\uFEFF/g, '')
  const found: ParsedShare[] = []
  const seen = new Set<string>()
  for (const match of source.matchAll(URL_PATTERN)) {
    const raw = match[0].replace(/[)\]}.,;]+$/, '')
    if (!raw || seen.has(raw)) continue
    seen.add(raw)
    const start = match.index ?? 0
    const previous = found.length ? source.indexOf(found[found.length - 1].url) : -1
    const previousEnd = previous >= 0 ? previous + found[found.length - 1].url.length : 0
    const segment = source.slice(previousEnd, start)
    const named = titleFrom(segment)
    found.push({ url: raw, title: named.title, author: named.author, site: siteOf(raw), duration: shareDuration(segment) })
  }
  return found
}

export function sameLink(left: string, right: string) {
  const key = (value: string) => {
    try {
      const url = new URL(value)
      const path = url.pathname.length > 1 ? url.pathname.replace(/\/+$/, '') : url.pathname
      return (url.hostname.replace(/^www\./, '') + path + url.search).toLowerCase()
    } catch { return value.trim() }
  }
  return key(left) === key(right)
}

export function matchRemote<T extends { url: string }>(local: { id: string; url: string }[], remote: T[]) {
  if (!local.length || !remote.length) return { pairs: [] as { id: string; item: T }[], extras: remote }
  if (local.length === remote.length) return {
    pairs: local.map((entry, index) => ({ id: entry.id, item: remote[index] })),
    extras: [] as T[],
  }
  const used = new Set<number>()
  const pairs: { id: string; item: T }[] = []
  for (const entry of local) {
    const index = remote.findIndex((item, position) => !used.has(position) && sameLink(item.url, entry.url))
    if (index < 0) continue
    used.add(index)
    pairs.push({ id: entry.id, item: remote[index] })
  }
  return { pairs, extras: remote.filter((_, index) => !used.has(index)) }
}
