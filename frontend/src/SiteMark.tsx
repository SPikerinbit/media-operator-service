import type { SiteLogin } from './api'
export const defaultSites: SiteLogin[] = [
  {site:'douyin',platform:'抖音',logged_in:false,logging_in:false},
  {site:'xiaohongshu',platform:'小红书',logged_in:false,logging_in:false},
  {site:'bilibili',platform:'B 站',logged_in:false,logging_in:false},
  {site:'weread',platform:'微信读书',logged_in:false,logging_in:false},
]
export function mergeSites(sites: SiteLogin[]) {
  return defaultSites.map(site => sites.find(item => item.site === site.site) || site)
}
export function SiteMark({site}:{site:SiteLogin['site']}) {
  return <span className={'account-mark '+site} aria-hidden="true">{{douyin:'♪',xiaohongshu:'小红书',bilibili:'bili',weread:'读'}[site]}</span>
}
