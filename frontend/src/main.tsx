import { Home, Settings2 } from 'lucide-react'
import { MotionConfig, useReducedMotion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { errorMessage, request, type Settings as Preferences } from './api'
import { Settings, type SettingsSection } from './Settings'
import { WorkbenchHome } from './WorkbenchHome'
import { WorkbenchQueue } from './WorkbenchQueue'
import { useInbox } from './workbenchState'
import './styles.css'
import './studio.css'
import './workbench.css'
import './study.css'

type View='home'|'publish'|'notes'|'settings'
const navigation=[{id:'home',label:'信箱'},{id:'publish',label:'投稿'},{id:'notes',label:'笔记'},{id:'settings',label:'设置'}] as const
const order: View[] = ['home', 'publish', 'notes', 'settings']
function fromHash():View {const value=location.hash.slice(1).split('/')[0];return value==='video'?'publish':value==='knowledge'?'notes':['home','publish','notes','settings'].includes(value)?value as View:'home'}
function metaphor(from: View, to: View) {
  if (from === 'settings' || to === 'settings') return 'book'
  if (from === 'home' || to === 'home') return 'drawer'
  return 'push'
}
function App(){
  const [view,setView]=useState<View>(fromHash);const [visited,setVisited]=useState<View[]>(['home',fromHash()])
  const [settings,setSettings]=useState<Preferences|null>(null);const [error,setError]=useState('')
  const [settingsFocus,setSettingsFocus]=useState<SettingsSection>('general');const inbox=useInbox()
  const [leaving,setLeaving]=useState<View|null>(null)
  const [deck,setDeck]=useState<{kind:string;dir:number}>({kind:'drawer',dir:1})
  const reduced=useReducedMotion()
  const leaveTimer=useRef(0)
  const viewRef=useRef(view)
  viewRef.current=view
  useEffect(()=>{
    const forced=matchMedia('(forced-colors: active)')
    const sync=()=>void window.pywebview?.api?.set_window_theme?.(false,forced.matches)?.catch(()=>{})
    sync();window.addEventListener('pywebviewready',sync);forced.addEventListener('change',sync)
    return()=>{window.removeEventListener('pywebviewready',sync);forced.removeEventListener('change',sync)}
  },[])
  useEffect(()=>{void request<Preferences>('/desktop/settings').then(setSettings).catch(e=>setError(errorMessage(e)))},[])
  useEffect(()=>{const change=()=>show(fromHash());window.addEventListener('hashchange',change);return()=>window.removeEventListener('hashchange',change)},[])
  function show(next:View){
    const current=viewRef.current
    if(next===current)return
    const dir=order.indexOf(next)>=order.indexOf(current)?1:-1
    setDeck({kind:metaphor(current,next),dir})
    if(!reduced){
      setLeaving(current)
      window.clearTimeout(leaveTimer.current)
      leaveTimer.current=window.setTimeout(()=>setLeaving(shown=>shown===current?null:shown),680)
    }
    setView(next);setVisited(v=>v.includes(next)?v:[...v,next]);history.replaceState(null,'','#'+next)
  }
  function openSettings(section:SettingsSection){setSettingsFocus(section);show('settings')}
  function deckClass(id:View){
    if(leaving===id)return 'is-deck-out'
    if(view===id&&leaving)return 'is-deck-in'
    return ''
  }
  return <MotionConfig reducedMotion="user"><a className="skip-link" href="#workspace">跳到工作区</a><div className="shell workbench-shell">
    <aside className="sidebar"><div className="workbench-brand" title="Media Operator">M<span>O</span></div><nav aria-label="工作台">{navigation.map(({id,label})=>{
      const count=inbox.data.entries.filter(e=>e.lane===id&&['ready','running','queued','blocked','failed','identifying','starting'].includes(e.status)).length
      return <button type="button" className="nav-item" key={id} aria-label={label} aria-current={view===id?'page':undefined} onClick={()=>show(id)}>
        {id==='home'?<Home size={20} aria-hidden="true"/>:id==='settings'?<Settings2 size={20} aria-hidden="true"/>:<span className="sidebar-mail-slot" data-mail-slot={id} aria-hidden="true"><i/></span>}
        <span>{label}</span>{count>0&&<small className="nav-count">{count}</small>}</button>
    })}</nav><small className="sidebar-version">{__APP_VERSION__}</small></aside>
    <main id="workspace" className={'workspace'+(leaving?' is-decking':'')} data-view={view} data-motion={deck.kind} data-dir={deck.dir} tabIndex={-1}><div className="workspace-content">
      {(error||inbox.error)&&<div className="notice error" role="alert">{error||inbox.error}<button type="button" onClick={()=>void inbox.refresh()}>重新连接</button></div>}
      <div className={'home-view '+deckClass('home')} hidden={view!=='home'&&leaving!=='home'}><WorkbenchHome data={inbox.data} active={view==='home'} onOpen={show}/></div>
      {(['publish','notes'] as const).map(lane=>visited.includes(lane)&&<div className={'lane-view '+deckClass(lane)} key={lane} hidden={view!==lane&&leaving!==lane}><WorkbenchQueue lane={lane} data={inbox.data} settings={settings} active={view===lane} onHome={()=>show('home')} onSettings={openSettings} refresh={inbox.refresh}/></div>)}
      {visited.includes('settings')&&<div className={'settings-view '+deckClass('settings')} hidden={view!=='settings'&&leaving!=='settings'}><Settings current={settings} update={setSettings} focus={settingsFocus}/></div>}
    </div></main>
  </div></MotionConfig>
}
createRoot(document.getElementById('root')!).render(<App/> )
