import { Home, Settings2 } from 'lucide-react'
import { MotionConfig } from 'motion/react'
import { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { errorMessage, request, type Settings as Preferences } from './api'
import { Settings, type SettingsSection } from './Settings'
import { WorkbenchHome } from './WorkbenchHome'
import { WorkbenchQueue } from './WorkbenchQueue'
import { useInbox } from './workbenchState'
import './styles.css'
import './studio.css'
import './workbench.css'

type View='home'|'publish'|'notes'|'settings'
const navigation=[{id:'home',label:'信箱'},{id:'publish',label:'投稿'},{id:'notes',label:'笔记'},{id:'settings',label:'设置'}] as const
function fromHash():View {const value=location.hash.slice(1).split('/')[0];return value==='video'?'publish':value==='knowledge'?'notes':['home','publish','notes','settings'].includes(value)?value as View:'home'}
function App(){
  const [view,setView]=useState<View>(fromHash);const [visited,setVisited]=useState<View[]>(['home',fromHash()])
  const [settings,setSettings]=useState<Preferences|null>(null);const [error,setError]=useState('')
  const [settingsFocus,setSettingsFocus]=useState<SettingsSection>('general');const inbox=useInbox()
  useEffect(()=>{
    const forced=matchMedia('(forced-colors: active)')
    const sync=()=>void window.pywebview?.api?.set_window_theme?.(false,forced.matches)?.catch(()=>{})
    sync();window.addEventListener('pywebviewready',sync);forced.addEventListener('change',sync)
    return()=>{window.removeEventListener('pywebviewready',sync);forced.removeEventListener('change',sync)}
  },[])
  useEffect(()=>{void request<Preferences>('/desktop/settings').then(setSettings).catch(e=>setError(errorMessage(e)))},[])
  useEffect(()=>{const change=()=>show(fromHash());window.addEventListener('hashchange',change);return()=>window.removeEventListener('hashchange',change)},[])
  function show(next:View){setView(next);setVisited(v=>v.includes(next)?v:[...v,next]);history.replaceState(null,'','#'+next)}
  function openSettings(section:SettingsSection){setSettingsFocus(section);show('settings')}
  return <MotionConfig reducedMotion="user"><a className="skip-link" href="#workspace">跳到工作区</a><div className="shell workbench-shell">
    <aside className="sidebar"><div className="workbench-brand" title="Media Operator">M<span>O</span></div><nav aria-label="工作台">{navigation.map(({id,label})=>{
      const count=inbox.data.entries.filter(e=>e.lane===id&&['ready','running','queued','blocked','failed','identifying','starting'].includes(e.status)).length
      return <button type="button" className="nav-item" key={id} aria-label={label} aria-current={view===id?'page':undefined} onClick={()=>show(id)}>
        {id==='home'?<Home size={20} aria-hidden="true"/>:id==='settings'?<Settings2 size={20} aria-hidden="true"/>:<span className="sidebar-mail-slot" data-mail-slot={id} aria-hidden="true"><i/></span>}
        <span>{label}</span>{count>0&&<small className="nav-count">{count}</small>}</button>
    })}</nav><small className="sidebar-version">0.5.0</small></aside>
    <main id="workspace" className="workspace" data-view={view} tabIndex={-1}><div className="workspace-content">
      {(error||inbox.error)&&<div className="notice error" role="alert">{error||inbox.error}<button type="button" onClick={()=>void inbox.refresh()}>重新连接</button></div>}
      <div className="home-view" hidden={view!=='home'}><WorkbenchHome data={inbox.data} active={view==='home'} onOpen={show}/></div>
      {(['publish','notes'] as const).map(lane=>visited.includes(lane)&&<div className="lane-view" key={lane} hidden={view!==lane}><WorkbenchQueue lane={lane} data={inbox.data} settings={settings} active={view===lane} onHome={()=>show('home')} onSettings={openSettings} refresh={inbox.refresh}/></div>)}
      {visited.includes('settings')&&<div className="settings-view" hidden={view!=='settings'}><Settings current={settings} update={setSettings} focus={settingsFocus}/></div>}
    </div></main>
  </div></MotionConfig>
}
createRoot(document.getElementById('root')!).render(<App/> )
