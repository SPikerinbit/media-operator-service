import { BookOpen, Cpu, Download, ExternalLink, FolderOpen, HardDrive, KeyRound, LogIn, Save, SlidersHorizontal, Send, ChevronRight, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { native, request, saveAs, siteSession, type LocalResources, type Settings as Preferences, type SiteLogin, type StorageSnapshot } from './api'
import { MODEL_DOWNLOAD_EVENT, notifyModelDownloadChanged } from './modelDownloads'
import { loginUrl, logoutSite, openSiteLogin, readSites, storeSiteSession, type LoginSite, type SiteId } from './siteSessions'
import { Button, Busy, Disclosure, Feedback, Field, useActions } from './ui'
import { Inspector, outputDefaults, savedVideoOptions, type VideoDefaults, type VideoOptions, type DefaultGroup, type InspectorSection } from './videoOptions'
import { defaultSites, mergeSites, SiteMark } from './SiteMark'

const secretsList = [['BILI_SESSDATA','SESSDATA'],['BILI_JCT','bili_jct'],['BILI_BUVID3','buvid3'],
  ['BILI_DEDEUSERID','DedeUserID'],['BILI_AC_TIME_VALUE','ac_time_value']] as const

const categories = [
  ['general','常规与目录',FolderOpen],['sites','账号与凭据',LogIn],['defaults','输出与字幕默认值',SlidersHorizontal],
  ['resources','转录与本地资源',Cpu],['deepseek','DeepSeek',KeyRound],
  ['bilibili','B 站投稿',Send],['obsidian','Obsidian',BookOpen],
] as const
export type SettingsSection = typeof categories[number][0]
function whisperGigabytes(bytes: number) {
  const gb = bytes / 1e9
  const rounded = gb >= 10 ? String(Math.round(gb)) : String(Math.round(gb * 10) / 10)
  return rounded + ' GB'
}
function formatBytes(bytes: number) {
  if (bytes >= 1e9) return (bytes / 1e9).toFixed(2) + ' GB'
  if (bytes >= 1e6) return (bytes / 1e6).toFixed(1) + ' MB'
  if (bytes >= 1e3) return Math.round(bytes / 1e3) + ' KB'
  return bytes + ' B'
}
type Category = SettingsSection
type SaveSection = 'directory'|'deepseek'|'gpu'|'bilibili'|'obsidian'

export function Settings({ current, update, focus, onOpenGuide, onReplayTour, active=true }: { current: Preferences | null; update: (settings: Preferences) => void; focus?: Category; onOpenGuide?: () => void; onReplayTour?: () => void; active?:boolean }) {
  const [category,setCategory] = useState<Category>(focus || 'general')
  const loginInput = useRef<HTMLInputElement>(null)
  const loginSite = useRef<LoginSite>('抖音')
  const [sites, setSites] = useState<SiteLogin[]>(() => current?.site_logins?.length ? mergeSites(current.site_logins) : defaultSites)
  const rememberSite = (status: SiteLogin) => setSites((list) => list.some((item) => item.site === status.site)
    ? list.map((item) => item.site === status.site ? status : item) : [...list, status])
  useEffect(() => { if (focus) setCategory(focus) }, [focus])
  useEffect(() => {
    let alive = true
    void readSites().then((data) => { if (alive) setSites(mergeSites(data.sites)) }).catch(() => {})
    return () => { alive = false }
  }, [])
  useEffect(()=>{
    if(!active||category!=='sites')return
    let alive=true
    const refresh=()=>void readSites().then(data=>{if(alive)setSites(mergeSites(data.sites))}).catch(()=>{})
    refresh()
    const timer=window.setInterval(refresh,15000)
    return()=>{alive=false;clearInterval(timer)}
  },[active,category])
  useEffect(() => {
    if (!current?.site_logins?.length) return
    setSites((local) => mergeSites(current.site_logins!).map((item) => {
      const previous = local.find((entry) => entry.site === item.site)
      return previous?.logging_in ? previous : item
    }))
  }, [current?.site_logins])
  useEffect(() => {
    const onSite = (event: Event) => {
      const detail = (event as CustomEvent<SiteLogin>).detail
      if (!detail?.site) return
      setSites((list) => list.some((item) => item.site === detail.site)
        ? list.map((item) => item.site === detail.site ? detail : item) : [...list, detail])
    }
    window.addEventListener('site-login', onSite)
    return () => window.removeEventListener('site-login', onSite)
  }, [])
  const [defaults,setDefaults] = useState<VideoDefaults|null>(null)
  const lastDefaults = useRef<VideoDefaults|null>(null)
  const [options,setOptions] = useState<VideoOptions>(() => savedVideoOptions(null))
  const [defaultSection,setDefaultSection] = useState<InspectorSection>('output')
  const [savingDefault,setSavingDefault] = useState<DefaultGroup|null>(null)
  const [vault, setVault] = useState('')
  const [summaryVault, setSummaryVault] = useState('')
  const [dataDir, setDataDir] = useState('')
  const [model, setModel] = useState('')
  const [apiBase, setApiBase] = useState('https://api.deepseek.com')
  const [gpu, setGpu] = useState(false)
  const [secrets, setSecrets] = useState<Record<string,string>>({})
  const [clearKey, setClearKey] = useState(false)
  const [saving, setSaving] = useState<SaveSection | null>(null)
  const [gpuDirectory, setGpuDirectory] = useState('')
  const [resources, setResources] = useState<LocalResources | null>(null)
  const [storage, setStorage] = useState<StorageSnapshot | null>(null)
  const [cleaningCache, setCleaningCache] = useState(false)
  const [checking, setChecking] = useState(false)
  const [testingDeepseek, setTestingDeepseek] = useState(false)
  const { notice, setNotice, perform } = useActions()
  const downloading = resources?.models.some((item) => item.download.running) ?? false

  useEffect(() => {
    let active = true
    const reload = () => {void request<VideoDefaults>('/desktop/video-defaults').then((next) => {
      if (!active) return
      const old = savedVideoOptions(lastDefaults.current), fresh = savedVideoOptions(next)
      lastDefaults.current = next;setDefaults(next)
      setOptions((current) => ({...current,
        ...(JSON.stringify(outputDefaults(current)) === JSON.stringify(outputDefaults(old)) ? outputDefaults(fresh) : {}),
        subtitle_style:JSON.stringify(current.subtitle_style) === JSON.stringify(old.subtitle_style) ? fresh.subtitle_style : current.subtitle_style}))
    }).catch(() => {})}
    reload();window.addEventListener('video-defaults-changed',reload)
    const pullResources = () => { void request<LocalResources>('/desktop/resources').then(next => { if (active) setResources(old => ({ ...old, models: next.models, gpu_queue: next.gpu_queue })) }).catch(() => {}) }
    pullResources()
    window.addEventListener(MODEL_DOWNLOAD_EVENT, pullResources)
    void request<StorageSnapshot>('/desktop/storage').then(setStorage).catch(() => {})
    return () => {active=false;window.removeEventListener('video-defaults-changed',reload);window.removeEventListener(MODEL_DOWNLOAD_EVENT, pullResources)}
  }, [])
  useEffect(() => {
    if (!active || category !== 'general') return
    void request<StorageSnapshot>('/desktop/storage').then(setStorage).catch(() => {})
  }, [active, category])

  useEffect(() => {
    if (!active || category !== 'resources') return
    let alive = true
    const refreshGpu = () => void request<LocalResources>('/desktop/resources').then((next) => {
      if (alive) setResources((old) => ({ ...old, models: next.models, gpu_queue: next.gpu_queue }))
    }).catch(() => {})
    refreshGpu()
    const timer = window.setInterval(refreshGpu, 4000)
    return () => { alive = false; window.clearInterval(timer) }
  }, [active, category])

  useEffect(() => {
    if (!downloading) return
    const timer = window.setInterval(() => {
      void request<LocalResources>('/desktop/resources').then((next) => {
        setResources((old) => ({...old, models:next.models, gpu_queue: next.gpu_queue}))
      }).catch(() => {})
    }, 1400)
    return () => window.clearInterval(timer)
  }, [downloading])

  useEffect(() => { setVault(current?.obsidian_viewpoint_vault ?? current?.obsidian_vault ?? '') }, [current?.obsidian_viewpoint_vault, current?.obsidian_vault])
  useEffect(() => { setSummaryVault(current?.obsidian_summary_vault ?? '') }, [current?.obsidian_summary_vault])
  useEffect(() => { setDataDir(current?.data_dir ?? '') }, [current?.data_dir])
  useEffect(() => { setModel(current?.ai_model ?? '') }, [current?.ai_model])
  useEffect(() => { setApiBase(current?.ai_api_base || 'https://api.deepseek.com') }, [current?.ai_api_base])
  useEffect(() => { setGpu(current?.gpu_enabled ?? false) }, [current?.gpu_enabled])
  useEffect(() => { setGpuDirectory(current?.gpu_install_dir ?? '') }, [current?.gpu_install_dir])

  useEffect(() => {
    if (!current?.gpu.running) return
    const timer = window.setInterval(() => {
      void request<Preferences>('/desktop/settings').then(update).catch((error: Error) => setNotice({text:error.message,error:true}))
    },2500)
    return () => window.clearInterval(timer)
  }, [current?.gpu.running,update,setNotice])

  const fieldSecret = (key: string, name: string, placeholder?: string, disabled = false) => <Field key={key} label={name}>
    <input type="password" value={secrets[key] || ''} onChange={(e) => setSecrets((values) => ({...values,[key]:e.target.value}))}
      placeholder={placeholder} autoComplete="new-password" disabled={disabled} />
  </Field>

  function save(section: SaveSection) {
    perform(async () => {
      setSaving(section)
      try {
        const key = secrets.TRANSLATE_API_KEY?.trim()
        const fields = section === 'deepseek' ? clearKey ? {TRANSLATE_API_KEY:''} : key ? {TRANSLATE_API_KEY:key} : {} :
          section === 'bilibili' ? Object.fromEntries(secretsList.map(([name]) => [name,secrets[name]?.trim()]).filter(([,value]) => value)) : {}
        const next = await request<Preferences>('/desktop/settings','PUT',section === 'deepseek' ?
          {ai_model:model.trim(),ai_api_base:apiBase.trim(),secrets:fields} : section === 'directory' ? {data_dir:dataDir} :
            section === 'obsidian' ? {obsidian_viewpoint_vault:vault,obsidian_summary_vault:summaryVault} : section === 'gpu' ? {gpu_enabled:gpu} : {secrets:fields})
        if (section === 'deepseek') {
          setSecrets((values) => ({...values,TRANSLATE_API_KEY:''}));setClearKey(false)
        } else if (section === 'bilibili') {
          setSecrets((values) => ({TRANSLATE_API_KEY:values.TRANSLATE_API_KEY || ''}))
        }
        update(next)
        setNotice({text:section === 'deepseek' ? next.has_ai_key ? 'DeepSeek 密钥和模型已保存' : 'DeepSeek 设置已保存' :
          section === 'directory' && next.active_data_dir !== next.data_dir ? '目录已保存，重启后生效。' : '当前分类设置已保存'})
      } finally {setSaving(null)}
    })
  }

  function saveDefault(group:DefaultGroup) {
    perform(async () => {
      setSavingDefault(group)
      try {
        const next = await request<VideoDefaults>('/desktop/video-defaults','PUT',
          group === 'output' ? {output:outputDefaults(options)} : {subtitle_style:options.subtitle_style})
        setDefaults(next)
        window.dispatchEvent(new Event('video-defaults-changed'))
        setNotice({text:group === 'output' ? '默认输出已保存' : '默认字幕样式已保存'})
      } finally {setSavingDefault(null)}
    })
  }
  const saveButton = (section:SaveSection) => <Button variant="secondary" leadingIcon={Save} disabled={Boolean(saving) || !current}
    onClick={() => save(section)}>{saving === section ? '保存中' : '保存设置'}</Button>
  function signIn(site: SiteId) {
    perform(async () => {
      let detail = ''
      const done = await openSiteLogin(site, rememberSite, (text) => { detail = text; setNotice({ text, error: true }) })
      rememberSite(done)
      if (done.logged_in) setNotice({ text: done.platform + '已登录' })
      else if (!detail) setNotice({ text: done.platform + '未完成登录', error: true })
    })
  }
  function signOut(site: SiteId) {
    perform(async () => {
      const status = await logoutSite(site)
      rememberSite(status)
      setNotice({ text: '已退出' + status.platform })
    })
  }
  return <>
    <div className="workspace-heading"><div><h1>设置</h1></div></div>
    <div className="settings-layout">
      <nav className="settings-nav thin-scroll" aria-label="设置分类">
        {categories.map(([key,label,Icon]) => <button key={key} aria-current={category === key ? 'page' : undefined}
          onClick={() => {setCategory(key);setNotice(null)}}><Icon size={17}/><span>{label}</span><ChevronRight size={14}/></button>)}
      </nav>
      <div className="settings-body thin-scroll">
      <Feedback notice={notice} onDismiss={() => setNotice(null)}/>
      <section className="settings-panel" hidden={category !== 'sites'}>
        <h2>账号与凭据</h2>
        <p className="muted">在桌面窗口登录。登录完成后会记下该站点的凭据。</p>
        <ul className="account-rows" aria-label="站点登录状态">
          {sites.map((status) => <li key={status.site}>
            <SiteMark site={status.site}/>
            <span className="account-name">{status.platform}</span>
            <span className={'account-lamp' + (status.logged_in ? ' is-on' : '')}>{status.logging_in ? '正在登录' : status.logged_in ? '已保存登录' : status.state==='expired'?'登录已失效':'未登录'}</span>
            {status.logged_in && !status.logging_in
              ? <button type="button" onClick={() => signOut(status.site)}>退出</button>
              : <button type="button" disabled={status.logging_in} onClick={() => signIn(status.site)}>登录</button>}
          </li>)}
        </ul>
        <Disclosure title="高级 / 导入 Cookie"><p className="muted">导入 Netscape Cookie 后，一小时内的本站链接会使用这份临时会话。它不更改上方的持久登录状态；B 站投稿仍需完整的投稿凭据。</p>
        <div className="toolbar">
          {(Object.keys(loginUrl) as LoginSite[]).map(site=><Button key={site} variant="ghost" size="small" onClick={() => { loginSite.current = site; loginInput.current?.click() }}>导入{site} Cookie</Button>)}
        </div></Disclosure>
        <input ref={loginInput} hidden type="file" accept=".txt,text/plain" aria-label="选择本站 Cookie 文件" onChange={(event) => {
          const file = event.target.files?.[0]
          const site = loginSite.current
          event.target.value = ''
          if (!file) return
          perform(async () => {
            const sessionId = await siteSession(loginUrl[site], file)
            storeSiteSession(site, sessionId)
            setNotice({ text: '已读取' + site + ' Cookie，一小时内的链接会使用这次登录。' })
          })
        }}/>
      </section>
      <section className="settings-panel defaults-settings" hidden={category !== 'defaults'}>
        <h2>输出与字幕默认值</h2><p className="muted">新批次使用这里的默认值。工作台的「重置」会回到已保存的默认值。</p>
        <Inspector defaultsOnly options={options} change={setOptions} settings={current} perItem={false} onScope={() => {}} reset={() => {}}
          section={defaultSection} onSection={setDefaultSection} defaultsReady={Boolean(defaults)} savingDefault={savingDefault}
          onSaveDefault={saveDefault} onResetDefault={(group) => setOptions((value) => ({...value,
            ...(group === 'output' ? outputDefaults(savedVideoOptions(defaults)) : {subtitle_style:savedVideoOptions(defaults).subtitle_style})}))}/>
      </section>
      <section className="settings-panel" hidden={category !== 'obsidian'}>
        <div className="section-heading"><div className="section-icon"><BookOpen size={18}/></div><h2>Obsidian 知识库</h2></div>
        <p className="muted">分别为「多层级摘要」与「核心/大多数观点」配置目标 Obsidian Vault（两者也可指向同一目录）。摘要按整篇树状层级笔记写入 Media Operator/摘要，两种观点共用观点库写入 Media Operator/观点。</p>
        <div className="obsidian-vault-card">
          <strong>摘要 Obsidian 库</strong>
          <small className="muted">接收多层级树状摘要（含全篇总览、主题锚点速览表、Mermaid 脉络图与可折叠底层观点）。</small>
          <div className="path-row"><Field label="摘要 Vault 根目录"><input value={summaryVault} readOnly placeholder="尚未选择" /></Field>
            <Button variant="secondary" size="small" leadingIcon={FolderOpen} onClick={() => perform(async () => {
              const path = await (await native()).choose_folder(); if (path) setSummaryVault(path)
            })}>选择摘要库</Button></div>
          <div className="toolbar">
            {vault && summaryVault !== vault && <Button variant="ghost" size="small" onClick={() => setSummaryVault(vault)}>与观点库相同</Button>}
            {current?.obsidian_summary_vault && <Button variant="ghost" size="small" leadingIcon={ExternalLink} onClick={() => perform(async () => {
              await request('/desktop/open-path', 'POST', { target: 'obsidian_summary_vault' })
            })}>打开目录</Button>}
            {summaryVault && <Button variant="ghost" size="small" onClick={() => setSummaryVault('')}>解除连接</Button>}
          </div>
        </div>
        <div className="obsidian-vault-card">
          <strong>观点 Obsidian 库</strong>
          <small className="muted">核心观点与大多数观点共用此库，按陈述、判断、启发性事实、典故故事与方法以语义卡片形式写入。</small>
          <div className="path-row"><Field label="观点 Vault 根目录"><input value={vault} readOnly placeholder="尚未选择" /></Field>
            <Button variant="secondary" size="small" leadingIcon={FolderOpen} onClick={() => perform(async () => {
              const path = await (await native()).choose_folder(); if (path) setVault(path)
            })}>选择观点库</Button></div>
          <div className="toolbar">
            {summaryVault && vault !== summaryVault && <Button variant="ghost" size="small" onClick={() => setVault(summaryVault)}>与摘要库相同</Button>}
            {(current?.obsidian_viewpoint_vault || current?.obsidian_vault) && <Button variant="ghost" size="small" leadingIcon={ExternalLink} onClick={() => perform(async () => {
              await request('/desktop/open-path', 'POST', { target: 'obsidian_viewpoint_vault' })
            })}>打开目录</Button>}
            {vault && <Button variant="ghost" size="small" onClick={() => setVault('')}>解除连接</Button>}
          </div>
        </div>
        <div className="toolbar">{saveButton('obsidian')}</div>
      </section>
      <section className="settings-panel" hidden={category !== 'general'}>
        <div className="section-heading"><div className="section-icon"><FolderOpen size={18}/></div><h2>本地资料</h2></div>
        <div className="toolbar">
          <Button variant="secondary" size="small" onClick={() => onOpenGuide?.()}>重新打开新手教程</Button>
          {onReplayTour && <Button variant="ghost" size="small" onClick={() => onReplayTour()}>首页实景导览</Button>}
          <Button variant="secondary" size="small" leadingIcon={ExternalLink} onClick={() => perform(async () => {
            await request('/desktop/open-path', 'POST', { target: 'data_dir' })
          })}>打开资料目录</Button>
          <Button variant="secondary" size="small" leadingIcon={ExternalLink} onClick={() => perform(async () => {
            await request('/desktop/open-path', 'POST', { target: 'log_dir' })
          })}>打开日志目录</Button>
        </div>
        <p className="muted">任务、媒体和待发布草稿保存在此目录。切换目录需要重启应用。</p>
        <div className="path-row"><Field label="资料目录"><input value={dataDir} readOnly/></Field>
          <Button variant="secondary" size="small" leadingIcon={FolderOpen} onClick={() => perform(async () => {
            const path = await (await native()).choose_folder(); if (path) setDataDir(path)
          })}>选择目录</Button></div>
        <div className="toolbar">
          {saveButton('directory')}
          <Button variant="ghost" size="small" leadingIcon={Download} onClick={() => perform(async () => {
            if (await saveAs('MediaOperator-diagnostics.json',{format:'diagnostics'})) setNotice({text:'已导出脱敏诊断'})
          })}>导出脱敏诊断</Button>
        </div>
        <div className="settings-cards-grid">
        {storage && <div className="storage-card" aria-label="本地磁盘占用">
          <div className="gpu-status-head">
            <strong><HardDrive size={15} aria-hidden="true" style={{display:'inline',verticalAlign:'-2px',marginRight:6}}/>存储与缓存管理</strong>
            <span className="gpu-status-pill">磁盘可用 {formatBytes(storage.free_bytes)}</span>
          </div>
          <div className="storage-grid">
            <div><small>Whisper 模型</small><strong>{formatBytes(storage.models_bytes)}</strong></div>
            <div><small>任务与成片</small><strong>{formatBytes(storage.jobs_bytes)}</strong></div>
            <div><small>笔记数据库</small><strong>{formatBytes(storage.database_bytes)}</strong></div>
            <div><small>可清理缓存</small><strong>{formatBytes(storage.cleanable_bytes)}</strong></div>
          </div>
          <div className="toolbar">
            <Button variant="secondary" size="small" leadingIcon={Trash2} disabled={cleaningCache || storage.cleanable_bytes === 0} onClick={() => perform(async () => {
              setCleaningCache(true)
              try {
                const res = await request<{ freed_bytes: number; storage: StorageSnapshot }>('/desktop/storage/clean-cache', 'POST')
                setStorage(res.storage)
                setNotice({ text: res.freed_bytes > 0 ? `已清理临时缓存 ${formatBytes(res.freed_bytes)}` : '暂无可清理的临时缓存' })
              } finally { setCleaningCache(false) }
            })}>{cleaningCache ? '清理中' : '清理临时缓存'}</Button>
          </div>
        </div>}
        <div className="about-card" aria-label="关于应用">
          <strong>Media Operator {current?.version || __APP_VERSION__}</strong>
          <p className="muted">本地优先的媒体转录、双语字幕压制与 Obsidian 知识工作台。所有凭据仅保存在 Windows 凭据管理器，服务仅监听本机回环地址。</p>
          <dl className="shortcut-grid" aria-label="常用快捷键">
            <div><dt><kbd>Ctrl</kbd>+<kbd>1</kbd>–<kbd>4</kbd></dt><dd>切换信箱 / 投稿 / 笔记 / 设置</dd></div>
            <div><dt><kbd>Ctrl</kbd>+<kbd>K</kbd> 或 <kbd>/</kbd></dt><dd>聚焦搜索框或信纸</dd></div>
            <div><dt><kbd>Ctrl</kbd>+<kbd>Enter</kbd></dt><dd>投递当前信箱信件</dd></div>
            <div><dt><kbd>Space</kbd></dt><dd>播放 / 暂停当前视音频</dd></div>
            <div><dt><kbd>Esc</kbd></dt><dd>关闭当前浮层或新建表单</dd></div>
          </dl>
        </div>
        </div>
      </section>
      <section className="settings-panel" hidden={category !== 'deepseek'}>
        <div className="section-heading"><div className="section-icon"><KeyRound size={18}/></div><h2>DeepSeek / AI 接口</h2></div>
        <p className="muted">用于字幕翻译、原话摘录与投稿信息生成。默认使用 DeepSeek，也兼容标准 OpenAI 对话端点。密钥由 Windows 凭据管理器保存。</p>
        <form className="form-stack" onSubmit={(event) => {event.preventDefault();save('deepseek')}}>
          <Field label="API 地址（默认 https://api.deepseek.com）">
            <div className="path-row">
              <input value={apiBase} onChange={(e) => setApiBase(e.target.value)} maxLength={300} placeholder="https://api.deepseek.com" disabled={saving === 'deepseek'}/>
              {apiBase !== 'https://api.deepseek.com' && <Button type="button" variant="ghost" size="small" onClick={() => setApiBase('https://api.deepseek.com')}>恢复默认</Button>}
            </div>
          </Field>
          <Field label="模型"><input value={model} onChange={(e) => setModel(e.target.value)} maxLength={120} disabled={saving === 'deepseek'}/></Field>
          {fieldSecret('TRANSLATE_API_KEY','API Key',current?.has_ai_key ? '已保存 · 留空保留原密钥' : '尚未配置',clearKey || saving === 'deepseek')}
          {current?.has_ai_key && <label className="check"><input type="checkbox" checked={clearKey} disabled={saving === 'deepseek'} onChange={(e) => setClearKey(e.target.checked)}/> 清除已保存的密钥</label>}
          <div className="toolbar">
            <Button type="submit" variant="secondary" size="small" leadingIcon={Save} disabled={Boolean(saving) || !current || !model.trim()}>
              {saving === 'deepseek' ? '保存中' : '保存 DeepSeek 设置'}</Button>
            <Button type="button" variant="secondary" size="small" disabled={testingDeepseek || Boolean(saving) || !current?.has_ai_key} onClick={() => perform(async () => {
              setTestingDeepseek(true)
              try {
                const res = await request<{ ok: boolean; model: string }>('/desktop/deepseek/test', 'POST')
                setNotice({ text: `AI 接口连接正常（模型：${res.model}）` })
              } finally { setTestingDeepseek(false) }
            })}>{testingDeepseek ? '正在测试' : '测试连接'}</Button>
          </div>
        </form>
      </section>
      <section className="settings-panel" hidden={category !== 'resources'}>
        <div className="section-heading"><div className="section-icon"><Download size={18}/></div><h2>本地资源与环境</h2></div>
        <p className="muted">准备模型后可离线转录。检测会实际启动媒体工具并核验 NVIDIA 推理环境。</p>
        {resources?.gpu_queue && <div className="gpu-status-card" aria-label="显卡与双线调度状态">
          <div className="gpu-status-head">
            <strong>显卡与双线调度</strong>
            <span className={'gpu-status-pill' + (resources.gpu_queue.busy ? ' is-busy' : '')}>
              {resources.gpu_queue.busy ? `占用中 · ${resources.gpu_queue.holder_text || '显卡任务'}` : '显卡空闲'}
              {resources.gpu_queue.waiting_count > 0 ? ` · 排队 ${resources.gpu_queue.waiting_count}` : ''}
            </span>
          </div>
          {resources.gpu_queue.vram ? <div className="vram-meter">
            <div className="vram-bar"><i style={{ width: `${Math.min(100, Math.round((resources.gpu_queue.vram.used_mb / Math.max(1, resources.gpu_queue.vram.total_mb)) * 100))}%` }} /></div>
            <small>可用显存 {(resources.gpu_queue.vram.free_mb / 1024).toFixed(1)} GB / 共 {(resources.gpu_queue.vram.total_mb / 1024).toFixed(1)} GB（已用 {(resources.gpu_queue.vram.used_mb / 1024).toFixed(1)} GB）</small>
          </div> : <small className="muted">未检测到 NVIDIA 显存读数（使用 CPU 或未安装 nvidia-smi）</small>}
        </div>}
        <Button variant="secondary" size="small" disabled={checking} onClick={() => perform(async () => {
          setChecking(true)
          try { setResources(await request<LocalResources>('/desktop/resources/check')) }
          finally { setChecking(false) }
        })}>{checking ? '正在检测' : '检测本地环境'}</Button>
        {resources?.checks && <ul className="form-stack resource-list" aria-label="环境检测结果">
          {resources.checks.map(({label,ready}) => <li key={label}><span>{label}</span>
            <span className={ready ? 'resource-ready' : 'resource-missing'}>{ready ? '通过' : '需检查'}</span></li>)}
          <li><span>系统网络代理</span><span>{resources.proxy ? `已检测（${resources.proxy}）` : '直连（未配置系统代理）'}</span></li>
          {resources.free_bytes !== undefined && <li><span>资料盘可用空间</span><span>{(resources.free_bytes / 1e9).toFixed(1)} GB</span></li>}
        </ul>}
        <ul className="form-stack resource-list" aria-label="本地 Whisper 模型">
          {resources?.models.map((item) => <li key={item.name}><div><strong>{item.name}</strong>
            <small>{item.available ? '本地已就绪' : item.download.message || '未下载'} · {whisperGigabytes(item.size)}</small></div>
            {item.available ? <Button variant="ghost" size="small" leadingIcon={Trash2} disabled={downloading} onClick={() => {
              if (!window.confirm(`删除本地 Whisper 模型 ${item.name}（约 ${whisperGigabytes(item.size)}）？删除后可随时重新下载。`)) return
              perform(async () => {
                const next = await request<LocalResources & { freed_bytes: number }>('/desktop/resources/models/' + item.name, 'DELETE')
                setResources((old) => ({ ...old, models: next.models }))
                notifyModelDownloadChanged()
                setNotice({ text: `已删除模型 ${item.name}` })
              })
            }}>删除模型</Button> : <Button variant="secondary" size="small" disabled={downloading}
              onClick={() => perform(async () => {
                const next = await request<LocalResources>('/desktop/resources/models/' + item.name,'POST')
                setResources((old) => ({...old, models:next.models}))
                notifyModelDownloadChanged()
              })}>{item.download.running ? '下载中' : '下载模型'}</Button>}
          </li>)}
        </ul>
      </section>
      <section className="settings-panel" hidden={category !== 'resources'}>
        <div className="section-heading"><div className="section-icon"><Cpu size={18}/></div><h2>转录加速</h2></div>
        <p className="muted">启用后，自动模式优先使用 NVIDIA 批量转录。GPU 不可用时会用 CPU 重试。</p>
        {current?.gpu.running ? <Busy>{current.gpu.message || '正在准备 NVIDIA 运行库'}</Busy> : <>
          {current?.gpu.message && <p className="muted">{current.gpu.message}</p>}
          <label className="check"><input type="checkbox" checked={gpu} disabled={!current?.gpu_ready} onChange={(e) => setGpu(e.target.checked)}/> 使用 NVIDIA 加速</label>
          <div className="path-row"><Field label="NVIDIA 运行库安装位置"><input value={gpuDirectory} readOnly /></Field>
            <Button variant="secondary" size="small" leadingIcon={FolderOpen} onClick={() => perform(async () => {
              const path = await (await native()).choose_folder(); if (path) setGpuDirectory(path)
            })}>选择目录</Button></div>
          {(!current?.gpu_ready || gpuDirectory !== current.gpu_install_dir) &&
            <Button variant="secondary" size="small" disabled={!gpuDirectory} onClick={() => {
              if (window.confirm('将 NVIDIA 运行库安装到以下目录？首次下载约 1.2 GB。\n\n' + gpuDirectory))
                perform(async () => update(await request<Preferences>('/desktop/gpu','POST',{directory:gpuDirectory})))
            }}>安装并启用 NVIDIA 加速</Button>}
          {saveButton('gpu')}
        </>}
      </section>
      <section className="settings-panel" hidden={category !== 'bilibili'}>
        <div className="section-heading"><div className="section-icon"><KeyRound size={18}/></div><h2>B 站投稿</h2></div>
        <p className="muted">{current?.has_bilibili_credentials ? 'B 站已登录，投稿可以使用这次凭据。' : '请到「账号与凭据」登录 B 站。下面只在需要时手动填写。'}</p>
        <Disclosure title="高级 / 手动填写"><div className="form-stack">{secretsList.map(([key,name]) => fieldSecret(key,name,'留空则保留已保存的值'))}</div></Disclosure>
        {saveButton('bilibili')}
      </section>
      </div>
    </div>
  </>
}
