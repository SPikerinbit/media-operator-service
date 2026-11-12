import { errorMessage, request, type SiteLogin } from './api'
import { siteOf } from './shareText'

export type { SiteLogin }
export type SiteId = SiteLogin['site']
export type LoginSite = '抖音' | '小红书' | 'B 站' | '微信读书'
const sessions: Partial<Record<LoginSite, string>> = {}

export const loginUrl: Record<LoginSite, string> = {
  抖音: 'https://www.douyin.com/',
  小红书: 'https://www.xiaohongshu.com/',
  'B 站': 'https://passport.bilibili.com/login',
  '微信读书': 'https://weread.qq.com/',
}

export const siteKey: Record<LoginSite, SiteId> = { 抖音: 'douyin', 小红书: 'xiaohongshu', 'B 站': 'bilibili', '微信读书': 'weread' }

const wait = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms))

export function readSites() {
  return request<{ sites: SiteLogin[] }>('/desktop/sites')
}

export function readSite(site: SiteId) {
  return request<SiteLogin>('/desktop/sites/' + site)
}

async function follow(site: SiteId, status: SiteLogin, onStatus?: (status: SiteLogin) => void) {
  let current = status
  onStatus?.(current)
  while (current.logging_in) {
    await wait(1000)
    current = await readSite(site)
    onStatus?.(current)
  }
  window.dispatchEvent(new CustomEvent('site-login', { detail: current }))
  return current
}

export function loginSite(site: SiteId, onStatus?: (status: SiteLogin) => void) {
  return request<SiteLogin>('/desktop/sites/' + site + '/login', 'POST').then((status) => follow(site, status, onStatus))
}

export function resumeSiteLogin(site: SiteId, onStatus?: (status: SiteLogin) => void) {
  return readSite(site).then((status) => follow(site, status, onStatus))
}

export async function openSiteLogin(site: SiteId, onStatus?: (status: SiteLogin) => void, onDetail?: (detail: string) => void) {
  try {
    return await loginSite(site, onStatus)
  } catch (error) {
    onDetail?.(errorMessage(error))
    const status = await readSite(site).catch(() => null)
    if (!status?.logging_in) throw error
    return resumeSiteLogin(site, onStatus)
  }
}

export async function logoutSite(site: SiteId) {
  const status = await request<SiteLogin>('/desktop/sites/' + site, 'DELETE')
  clearSiteSession(site)
  window.dispatchEvent(new CustomEvent('site-login', { detail: status }))
  return status
}

export function storeSiteSession(site: LoginSite, sessionId: string) {
  sessions[site] = sessionId
  window.dispatchEvent(new CustomEvent('site-session', { detail: { site, sessionId } }))
}

export function clearSiteSession(site: SiteId) {
  delete sessions[site === 'xiaohongshu' ? '小红书' : site === 'bilibili' ? 'B 站' : site === 'weread' ? '微信读书' : '抖音']
}

export function loginLabel(detail: { platform?: string; site?: string } | undefined) {
  if (detail?.platform === '抖音' || detail?.platform === '小红书' || detail?.platform === 'B 站') return detail.platform
  if (detail?.site === '抖音' || detail?.site === '小红书' || detail?.site === 'B 站') return detail.site
  if (detail?.site === 'douyin') return '抖音'
  if (detail?.site === 'xiaohongshu') return '小红书'
  if (detail?.site === 'bilibili') return 'B 站'
  return ''
}

export function sessionForSource(url: string) {
  const site = siteOf(url)
  if (site === '抖音' || site === '小红书' || site === 'B 站' || site === '微信读书') return sessions[site] || ''
  return ''
}
