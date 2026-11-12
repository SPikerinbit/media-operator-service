import { BookOpen, Cpu, Download, FolderOpen, KeyRound, LogIn, Save, SlidersHorizontal, Send, ChevronRight } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { native, request, saveAs, siteSession, type LocalResources, type Settings as Preferences, type SiteLogin } from './api'
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
type Category = SettingsSection
type SaveSection = 'directory'|'deepseek'|'gpu'|'bilibili'|'obsidian'

export function Settings({ current, update, focus, onOpenGuide, active=true }: { current: Preferences | null; update: (settings: Preferences) => void; focus?: Category; onOpenGuide?: () => void; active?:boolean }) {
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
  const [dataDir, setDataDir] = useState('')
  const [model, setModel] = useState('')
  const [gpu, setGpu] = useState(false)
  const [secrets, setSecrets] = useState<Record<string,string>>({})
  const [clearKey, setClearKey] = useState(false)
  const [saving, setSaving] = useState<SaveSection | null>(null)
  const [gpuDirectory, setGpuDirectory] = useState('')
  const [resources, setResources] = useState<LocalResources | null>(null)
  const [checking, setChecking] = useState(false)
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
    void request<LocalResources>('/desktop/resources').then(setResources).catch(() => {})
    return () => {active=false;window.removeEventListener('video-defaults-changed',reload)}
  }, [])

  useEffect(() => {
    if (!downloading) return
    const timer = window.setInterval(() => {
      void request<LocalResources>('/desktop/resources').then((next) => {
        setResources((old) => ({...old, models:next.models}))
      }).catch(() => {})
    }, 1400)
    return () => window.clearInterval(timer)
  }, [downloading])

  useEffect(() => { setVault(current?.obsidian_vault ?? '') }, [current?.obsidian_vault])
  useEffect(() => { setDataDir(current?.data_dir ?? '') }, [current?.data_dir])
  useEffect(() => { setModel(current?.ai_model ?? '') }, [current?.ai_model])
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
          {ai_model:model.trim(),secrets:fields} : section === 'directory' ? {data_dir:dataDir} :
            section === 'obsidian' ? {obsidian_vault:vault} : section === 'gpu' ? {gpu_enabled:gpu} : {secrets:fields})
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
      <Feedback notice={notice}/>
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
        <p className="muted">选择已经打开过的 Vault。发布的观点和来源笔记会写入其中的 Media Operator 文件夹。</p>
        <div className="path-row"><Field label="Vault 根目录"><input value={vault} readOnly placeholder="尚未选择" /></Field>
          <Button variant="secondary" size="small" leadingIcon={FolderOpen} onClick={() => perform(async () => {
            const path = await (await native()).choose_folder(); if (path) setVault(path)
          })}>选择 Vault</Button></div>
        <div className="toolbar">{saveButton('obsidian')}{vault && <Button variant="ghost" size="small" onClick={() => setVault('')}>解除连接</Button>}</div>
      </section>
      <section className="settings-panel" hidden={category !== 'general'}>
        <div className="section-heading"><div className="section-icon"><FolderOpen size={18}/></div><h2>本地资料</h2></div>
        <Button variant="secondary" onClick={() => onOpenGuide?.()}>重新打开安装清单</Button>
        <p className="muted">任务、媒体和待发布草稿保存在此目录。切换目录需要重启应用。</p>
        <div className="path-row"><Field label="资料目录"><input value={dataDir} readOnly/></Field>
          <Button variant="secondary" size="small" leadingIcon={FolderOpen} onClick={() => perform(async () => {
            const path = await (await native()).choose_folder(); if (path) setDataDir(path)
          })}>选择目录</Button></div>
        {saveButton('directory')}
        <Button variant="ghost" size="small" leadingIcon={Download} onClick={() => perform(async () => {
          if (await saveAs('MediaOperator-diagnostics.json',{format:'diagnostics'})) setNotice({text:'已导出脱敏诊断'})
        })}>导出脱敏诊断</Button>
      </section>
      <section className="settings-panel" hidden={category !== 'deepseek'}>
        <div className="section-heading"><div className="section-icon"><KeyRound size={18}/></div><h2>DeepSeek</h2></div>
        <p className="muted">用于字幕翻译、原话摘录与投稿信息生成。密钥由 Windows 凭据管理器保存。</p>
        <form className="form-stack" onSubmit={(event) => {event.preventDefault();save('deepseek')}}>
          <Field label="模型"><input value={model} onChange={(e) => setModel(e.target.value)} maxLength={120} disabled={saving === 'deepseek'}/></Field>
          {fieldSecret('TRANSLATE_API_KEY','API Key',current?.has_ai_key ? '已保存 · 留空保留原密钥' : '尚未配置',clearKey || saving === 'deepseek')}
          {current?.has_ai_key && <label className="check"><input type="checkbox" checked={clearKey} disabled={saving === 'deepseek'} onChange={(e) => setClearKey(e.target.checked)}/> 清除已保存的密钥</label>}
          <div><Button type="submit" variant="secondary" size="small" leadingIcon={Save} disabled={Boolean(saving) || !current || !model.trim()}>
            {saving === 'deepseek' ? '保存中' : '保存 DeepSeek 设置'}</Button></div>
        </form>
      </section>
      <section className="settings-panel" hidden={category !== 'resources'}>
        <div className="section-heading"><div className="section-icon"><Download size={18}/></div><h2>本地资源与环境</h2></div>
        <p className="muted">准备模型后可离线转录。检测会实际启动媒体工具并核验 NVIDIA 推理环境。</p>
        <Button variant="secondary" size="small" disabled={checking} onClick={() => perform(async () => {
          setChecking(true)
          try { setResources(await request<LocalResources>('/desktop/resources/check')) }
          finally { setChecking(false) }
        })}>{checking ? '正在检测' : '检测本地环境'}</Button>
        {resources?.checks && <ul className="form-stack resource-list" aria-label="环境检测结果">
          {resources.checks.map(({label,ready}) => <li key={label}><span>{label}</span>
            <span className={ready ? 'resource-ready' : 'resource-missing'}>{ready ? '通过' : '需检查'}</span></li>)}
          {resources.free_bytes !== undefined && <li><span>资料盘可用空间</span><span>{(resources.free_bytes / 1e9).toFixed(1)} GB</span></li>}
        </ul>}
        <ul className="form-stack resource-list" aria-label="本地 Whisper 模型">
          {resources?.models.map((item) => <li key={item.name}><div><strong>{item.name}</strong>
            <small>{item.available ? '本地已就绪' : item.download.message || '未下载'} · {whisperGigabytes(item.size)}</small></div>
            {!item.available && <Button variant="secondary" size="small" disabled={downloading}
              onClick={() => perform(async () => {
                const next = await request<LocalResources>('/desktop/resources/models/' + item.name,'POST')
                setResources((old) => ({...old, models:next.models}))
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
