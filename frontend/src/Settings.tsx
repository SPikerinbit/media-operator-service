import { BookOpen, Cpu, Download, FolderOpen, KeyRound, Save } from 'lucide-react'
import { useEffect, useState } from 'react'
import { native, request, saveAs, type Settings as Preferences } from './api'
import { Button, Busy, Disclosure, Feedback, Field, useActions } from './ui'

const secretsList = [['BILI_SESSDATA','SESSDATA'],['BILI_JCT','bili_jct'],['BILI_BUVID3','buvid3'],
  ['BILI_DEDEUSERID','DedeUserID'],['BILI_AC_TIME_VALUE','ac_time_value']] as const

export function Settings({ current, update }: { current: Preferences | null; update: (settings: Preferences) => void }) {
  const [vault, setVault] = useState('')
  const [dataDir, setDataDir] = useState('')
  const [model, setModel] = useState('')
  const [gpu, setGpu] = useState(false)
  const [secrets, setSecrets] = useState<Record<string,string>>({})
  const [clearKey, setClearKey] = useState(false)
  const [saving, setSaving] = useState(false)
  const { notice, setNotice, perform } = useActions()

  useEffect(() => {
    if (current) {setVault(current.obsidian_vault);setDataDir(current.data_dir);setModel(current.ai_model);setGpu(current.gpu_enabled)}
  }, [current?.obsidian_vault,current?.data_dir,current?.ai_model,current?.gpu_enabled])

  useEffect(() => {
    if (!current?.gpu.running) return
    const timer = window.setInterval(() => {
      void request<Preferences>('/desktop/settings').then(update).catch((error: Error) => setNotice({text:error.message,error:true}))
    },2500)
    return () => window.clearInterval(timer)
  }, [current?.gpu.running,update,setNotice])

  const fieldSecret = (key: string, name: string, placeholder?: string) => <Field key={key} label={name}>
    <input type="password" value={secrets[key] || ''} onChange={(e) => setSecrets((values) => ({...values,[key]:e.target.value}))}
      placeholder={placeholder} autoComplete="new-password" />
  </Field>

  function save() {
    perform(async () => {
      setSaving(true)
      try {
        const fields = Object.fromEntries(Object.entries(secrets).map(([k,v]) => [k,v.trim()]).filter(([,v]) => v))
        if (clearKey) fields.TRANSLATE_API_KEY = ''
        const next = await request<Preferences>('/desktop/settings','PUT',{
          obsidian_vault:vault,data_dir:dataDir,ai_model:model.trim(),gpu_enabled:gpu,secrets:fields,
        })
        setSecrets({});setClearKey(false);update(next)
        setNotice({text:next.active_data_dir !== next.data_dir ? '已保存。新资料目录会在重启后生效。' : '设置已保存'})
      } finally {setSaving(false)}
    })
  }

  return <>
    <div className="workspace-heading">
      <div><div className="eyebrow">PREFERENCES</div><h1>应用设置</h1><p>配置本地工作目录、知识库和可选服务。</p></div>
      <Button leadingIcon={Save} disabled={saving || !model.trim() || !current} onClick={save}>{saving ? '保存中' : '保存设置'}</Button>
    </div>
    <Feedback notice={notice}/>
    <div className="settings-grid">
      <section className="surface settings-panel">
        <div className="section-heading"><div className="section-icon"><BookOpen size={18}/></div><h2>Obsidian 知识库</h2></div>
        <p className="muted">选择已经打开过的 Vault。发布的观点和来源笔记会写入其中的 Media Operator 文件夹。</p>
        <div className="path-row"><Field label="Vault 根目录"><input value={vault} readOnly placeholder="尚未选择" /></Field>
          <Button variant="secondary" size="small" leadingIcon={FolderOpen} onClick={() => perform(async () => {
            const path = await (await native()).choose_folder(); if (path) setVault(path)
          })}>选择 Vault</Button></div>
        {vault && <Button variant="ghost" size="small" onClick={() => setVault('')}>解除连接</Button>}
      </section>
      <section className="surface settings-panel">
        <div className="section-heading"><div className="section-icon"><FolderOpen size={18}/></div><h2>本地资料</h2></div>
        <p className="muted">任务、媒体和待发布草稿保存在此目录。切换目录需要重启应用。</p>
        <div className="path-row"><Field label="资料目录"><input value={dataDir} readOnly/></Field>
          <Button variant="secondary" size="small" leadingIcon={FolderOpen} onClick={() => perform(async () => {
            const path = await (await native()).choose_folder(); if (path) setDataDir(path)
          })}>选择目录</Button></div>
        <Button variant="ghost" size="small" leadingIcon={Download} onClick={() => perform(async () => {
          if (await saveAs('MediaOperator-diagnostics.json',{format:'diagnostics'})) setNotice({text:'已导出脱敏诊断'})
        })}>导出脱敏诊断</Button>
      </section>
      <section className="surface settings-panel">
        <div className="section-heading"><div className="section-icon"><KeyRound size={18}/></div><h2>DeepSeek</h2></div>
        <p className="muted">用于翻译字幕和提取观点。密钥由 Windows 凭据管理器保存。</p>
        <Field label="模型"><input value={model} onChange={(e) => setModel(e.target.value)} maxLength={120}/></Field>
        {fieldSecret('TRANSLATE_API_KEY','API Key',current?.has_ai_key ? '已保存 · 留空保留原密钥' : '尚未配置')}
        {current?.has_ai_key && <label className="check"><input type="checkbox" checked={clearKey} onChange={(e) => setClearKey(e.target.checked)}/> 清除已保存的密钥</label>}
      </section>
      <section className="surface settings-panel">
        <div className="section-heading"><div className="section-icon"><Cpu size={18}/></div><h2>转录加速</h2></div>
        <p className="muted">默认使用 CPU。支持的 NVIDIA 设备可以选用 GPU。</p>
        {current?.gpu.running ? <Busy>{current.gpu.message || '正在准备 NVIDIA 运行库'}</Busy> : <>
          {current?.gpu.message && <p className="muted">{current.gpu.message}</p>}
          <label className="check"><input type="checkbox" checked={gpu} disabled={!current?.gpu_ready} onChange={(e) => setGpu(e.target.checked)}/> 使用 NVIDIA 加速</label>
          {!current?.gpu_ready && <Button variant="secondary" size="small" onClick={() => {
            if (window.confirm('下载约 1.2 GB 的 NVIDIA 运行库？')) perform(async () => update(await request<Preferences>('/desktop/gpu','POST',{})))
          }}>安装并启用 NVIDIA 加速</Button>}
        </>}
      </section>
      <section className="surface settings-panel">
        <div className="section-heading"><div className="section-icon"><KeyRound size={18}/></div><h2>B 站投稿</h2></div>
        <p className="muted">{current?.has_bilibili_credentials ? '已保存投稿凭据。' : '配置后可在视频制作中启用投稿。'}</p>
        <Disclosure title="投稿凭据"><div className="form-stack">{secretsList.map(([key,name]) => fieldSecret(key,name,'留空保留已保存内容'))}</div></Disclosure>
      </section>
    </div>
  </>
}
