import { useEffect, useState } from 'react'
import { request, type LocalResources, type Settings, type SiteLogin } from './api'
import { openSiteLogin, readSites } from './siteSessions'

function whisperName(name: string) {
  return name.replace(/\s*\d+(?:\.\d+)?\s*G(?:B)?$/i, '').trim() || name
}
function whisperGigabytes(bytes: number) {
  const gb = bytes / 1e9
  const rounded = gb >= 10 ? String(Math.round(gb)) : String(Math.round(gb * 10) / 10)
  return rounded + ' GB'
}

type Step = 'accounts' | 'model' | 'key' | 'ready'

const steps: Step[] = ['accounts', 'model', 'key', 'ready']

export function SetupGuide({ settings, onSettings, onClose }: {
  settings: Settings | null
  onSettings: (next: Settings) => void
  onClose: () => void
}) {
  const [step, setStep] = useState<Step>('accounts')
  const [sites, setSites] = useState<SiteLogin[]>([])
  const [skipped, setSkipped] = useState<Record<string, boolean>>({})
  const [resources, setResources] = useState<LocalResources | null>(null)
  const [model, setModel] = useState('small')
  const [key, setKey] = useState('')
  const [modelName, setModelName] = useState(settings?.ai_model || 'deepseek-chat')
  const [notice, setNotice] = useState('')
  const [leaving, setLeaving] = useState(false)
  function close() {
    if (leaving) return
    setLeaving(true)
    window.setTimeout(onClose, matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 560)
  }
  const [busy, setBusy] = useState(false)
  const index = steps.indexOf(step)

  useEffect(() => { void readSites().then(data => setSites(data.sites)).catch(() => {}) }, [])
  useEffect(() => {
    if (step !== 'model') return
    let stop = false
    const pull = () => request<LocalResources>('/desktop/resources').then(next => { if (!stop) setResources(next) }).catch(() => {})
    void pull()
    void request<LocalResources>('/desktop/resources/check').then(next => { if (!stop) setResources(current => ({ ...current, ...next, models: next.models?.length ? next.models : current?.models || [] })) }).catch(() => {})
    const timer = window.setInterval(() => void pull(), 1200)
    return () => { stop = true; window.clearInterval(timer) }
  }, [step])

  const chosen = resources?.models.find(item => item.name === model)
  const gpu = resources?.checks?.find(item => item.label.includes('GPU') || item.label.includes('NVIDIA'))
  const accountDone = sites.length > 0 && sites.every(site => site.logged_in || skipped[site.site])

  async function login(site: SiteLogin) {
    setBusy(true)
    setNotice('')
    try {
      const done = await openSiteLogin(site.site, next => setSites(list => list.map(item => item.site === next.site ? next : item)))
      setSites(list => list.map(item => item.site === done.site ? done : item))
      setNotice(done.logged_in ? done.platform + '已登录' : done.platform + '未完成登录')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '登录窗口没有打开')
    } finally { setBusy(false) }
  }

  async function download() {
    setBusy(true)
    setNotice('')
    try {
      const next = await request<LocalResources>('/desktop/resources/models/' + model, 'POST')
      setResources(current => ({ ...current, models: next.models }))
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '模型没有开始下载')
    } finally { setBusy(false) }
  }

  async function saveKey(test: boolean) {
    setBusy(true)
    setNotice('')
    try {
      const next = await request<Settings>('/desktop/settings', 'PUT', {
        ai_model: modelName.trim() || 'deepseek-chat',
        secrets: key.trim() ? { TRANSLATE_API_KEY: key.trim() } : {},
      })
      onSettings(next)
      if (test) {
        await request('/desktop/deepseek/test', 'POST')
        setNotice('DeepSeek 已连通')
      } else setNotice(next.has_ai_key ? '密钥已保存' : '还没有密钥')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '没有保存成功')
    } finally { setBusy(false) }
  }

  function go(next: Step) {
    setNotice('')
    setStep(next)
  }

  return <div className={'onboarding' + (leaving ? ' is-leaving' : '')} role="dialog" aria-labelledby="setup-title">
    <div className={'setup-book' + (step === 'ready' ? ' is-ready' : '')}>
      <header>
        <h2 id="setup-title">安装清单</h2>
        <p>只准备账号、模型和密钥。用法留到你自己打开书桌时再看。</p>
        <ol className="setup-stamps" aria-label="步骤">
          {['账号', '模型', '密钥', '就绪'].map((label, order) => <li key={label} className={order < index ? 'is-stamped' : order === index ? 'is-current' : ''}>{label}</li>)}
        </ol>
      </header>
      <div className="setup-page" key={step}>
        {step === 'accounts' && <>
          <h3>登录要用的站点</h3>
          <ul className="setup-accounts">
            {sites.map(site => <li key={site.site}>
              <span>{site.platform}</span>
              <em className={site.logged_in ? 'is-stamped' : skipped[site.site] ? 'is-skipped' : ''}>{site.logging_in ? '正在登录' : site.logged_in ? '已登录' : skipped[site.site] ? '已跳过' : '未登录'}</em>
              {!site.logged_in && <button type="button" disabled={busy || site.logging_in} onClick={() => void login(site)}>登录</button>}
              {!site.logged_in && !skipped[site.site] && <button type="button" className="text-action" onClick={() => setSkipped(current => ({ ...current, [site.site]: true }))}>跳过</button>}
            </li>)}
          </ul>
          <button type="button" className="setup-next" disabled={!accountDone} onClick={() => go('model')}>下一页</button>
        </>}
        {step === 'model' && <>
          <h3>准备转录模型</h3>
          <p>{gpu ? (gpu.ready ? '检测到 NVIDIA，可以用 GPU 转录。' : '没有检测到可用 GPU，转录会用 CPU。') : '正在查看这台机器的环境。'}</p>
          <div className="setup-models" role="radiogroup" aria-label="模型大小">
            {(resources?.models || []).map(item => <button key={item.name} type="button" role="radio" aria-checked={model === item.name} className={model === item.name ? 'is-set' : ''} onClick={() => setModel(item.name)}>
              <strong>{whisperName(item.name)}</strong><small>{whisperGigabytes(item.size)}{item.available ? ' · 已就绪' : ''}</small>
            </button>)}
          </div>
          {chosen?.download.running && <p role="status">正在下载 {chosen.download.percent ?? 0}% {chosen.download.message || ''}</p>}
          {chosen?.available && <p className="is-stamped">模型已核验，可以离线转录。</p>}
          <div className="toolbar">
            <button type="button" className="setup-next" disabled={busy || chosen?.available || chosen?.download.running} onClick={() => void download()}>{chosen?.download.running ? '下载中' : '下载所选模型'}</button>
            <button type="button" className="text-action" onClick={() => go('key')}>{chosen?.available ? '下一页' : '跳过模型'}</button>
          </div>
        </>}
        {step === 'key' && <>
          <h3>DeepSeek 密钥</h3>
          <label>模型<input value={modelName} onChange={event => setModelName(event.target.value)} /></label>
          <label>API Key<input type="password" value={key} autoComplete="off" placeholder={settings?.has_ai_key ? '已保存，留空则保留' : '粘贴密钥'} onChange={event => setKey(event.target.value)} /></label>
          <div className="toolbar">
            <button type="button" className="setup-next" disabled={busy} onClick={() => void saveKey(false)}>保存</button>
            <button type="button" className="setup-next" disabled={busy || !(key.trim() || settings?.has_ai_key)} onClick={() => void saveKey(true)}>测试连接</button>
            <button type="button" className="text-action" onClick={() => go('ready')}>跳过密钥</button>
          </div>
        </>}
        {step === 'ready' && <>
          <h3>可以开始了</h3>
          <ul className="setup-ready">
            <li className={sites.some(site => site.logged_in) ? 'is-stamped' : ''}>账号：{sites.filter(site => site.logged_in).map(site => site.platform).join('、') || '都先跳过'}</li>
            <li className={resources?.models.some(item => item.available) ? 'is-stamped' : ''}>模型：{resources?.models.filter(item => item.available).map(item => item.name).join('、') || '尚未下载'}</li>
            <li className={settings?.has_ai_key ? 'is-stamped' : ''}>DeepSeek：{settings?.has_ai_key ? '已保存' : '尚未配置'}</li>
          </ul>
          <button type="button" className="setup-next" onClick={close}>合上清单</button>
        </>}
      </div>
      {notice && <p className="setup-slip" role="status">{notice}</p>}
      <footer>
        {index > 0 && step !== 'ready' && <button type="button" className="text-action" onClick={() => go(steps[index - 1])}>上一页</button>}
        <button type="button" className="text-action" onClick={close}>以后再说</button>
      </footer>
    </div>
  </div>
}
