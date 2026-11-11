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
  const [warm,setWarm]=useState(false)
  const [leaving,setLeaving]=useState<View|null>(null)
  const [deck,setDeck]=useState<{kind:string;dir:number}>({kind:'drawer',dir:1})
  const [welcome,setWelcome]=useState(()=>localStorage.getItem('workbench-onboarding')!=='done')
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
  useEffect(()=>{
    const base=import.meta.env.BASE_URL
    ;['workbench/materials/walnut.webp','workbench/materials/leather.webp','workbench/materials/linen.webp','workbench/materials/paper.webp','workbench/materials/brass.webp','workbench/mailbox-light-body.webp','workbench/mailbox-light-front.webp','workbench/mailbox-light-slot-front.webp','workbench/mailbox-light-slot-back.webp','workbench/envelope-light-front.webp','workbench/envelope-light-body.webp','workbench/brazier-light-body.webp','workbench/brazier-light-front.webp','workbench/shredder-light-body.webp','workbench/shredder-light-front.webp','workbench/trash-light-body.webp','workbench/trash-light-front.webp'].forEach(path=>{const img=new Image();img.src=base+path})
    let alive=true
    requestAnimationFrame(()=>requestAnimationFrame(()=>{if(alive)setWarm(true)}))
    return()=>{alive=false}
  },[])
  useEffect(()=>{const change=()=>show(fromHash());window.addEventListener('hashchange',change);return()=>window.removeEventListener('hashchange',change)},[])
  function show(next:View){
    const current=viewRef.current
    if(next===current)return
    const dir=order.indexOf(next)>=order.indexOf(current)?1:-1
    setDeck({kind:metaphor(current,next),dir})
    if(!reduced){
      setLeaving(current)
      window.clearTimeout(leaveTimer.current)
      leaveTimer.current=window.setTimeout(()=>setLeaving(shown=>shown===current?null:shown),820)
    }
    setView(next);setVisited(v=>v.includes(next)?v:[...v,next]);history.replaceState(null,'','#'+next)
  }
  function openSettings(section:SettingsSection){setSettingsFocus(section);show('settings')}
  function dismissWelcome(){localStorage.setItem('workbench-onboarding','done');setWelcome(false)}
  function deckClass(id:View){
    if(leaving===id)return 'is-deck-out'
    if(view===id&&leaving)return 'is-deck-in'
    return ''
  }
  return <MotionConfig reducedMotion="user"><a className="skip-link" href="#workspace">跳到工作区</a><div className="shell workbench-shell">
    <aside className="sidebar"><div className="workbench-brand" title="Media Operator">M<span>O</span></div><nav aria-label="工作台">{navigation.map(({id,label})=>{
      const count=inbox.data.entries.filter(e=>e.lane===id&&['ready','running','queued','blocked','failed','identifying','starting'].includes(e.status)).length
      return <button type="button" className="nav-item" key={id} aria-label={label} aria-current={view===id?'page':undefined} onClick={()=>show(id)}>
        {id==='home'?<Home size={20} aria-hidden="true"/>:id==='settings'?<Settings2 size={20} aria-hidden="true"/>:<span className="sidebar-mail-slot" aria-hidden="true"><span className="slot-mouth" data-mail-slot={id}/><i/></span>}
        <span>{label}</span>{count>0&&<small className="nav-count">{count}</small>}</button>
    })}</nav><small className="sidebar-version">{__APP_VERSION__}</small></aside>
    <main id="workspace" className={'workspace'+(leaving?' is-decking':'')} data-view={view} data-motion={deck.kind} data-dir={deck.dir} tabIndex={-1}><div className="workspace-content">
      {(error||inbox.error)&&<div className="notice error" role="alert">{error||inbox.error}<button type="button" onClick={()=>void inbox.refresh()}>重新连接</button></div>}
      <div className={'home-view '+deckClass('home')+(warm&&view!=='home'&&leaving!=='home'?' is-parked':'')} hidden={!warm&&view!=='home'&&leaving!=='home'}><WorkbenchHome data={inbox.data} active={view==='home'} onOpen={show}/></div>
      {(['publish','notes'] as const).map(lane=>(warm||visited.includes(lane))&&<div className={'lane-view '+deckClass(lane)+(warm&&view!==lane&&leaving!==lane?' is-parked':'')} key={lane} hidden={!warm&&view!==lane&&leaving!==lane}><WorkbenchQueue lane={lane} data={inbox.data} settings={settings} active={view===lane} onHome={()=>show('home')} onSettings={openSettings} refresh={inbox.refresh}/></div>)}
      {(warm||visited.includes('settings'))&&<div className={'settings-view '+deckClass('settings')+(warm&&view!=='settings'&&leaving!=='settings'?' is-parked':'')} hidden={!warm&&view!=='settings'&&leaving!=='settings'}><Settings current={settings} update={setSettings} focus={settingsFocus}/></div>}
    </div></main>
    {welcome&&<div className="onboarding" role="dialog" aria-labelledby="onboarding-title">
      <div className="onboarding-sheet">
        <h2 id="onboarding-title">先把要用的账号准备好</h2>
        <p>投稿需要 B 站登录。笔记里的抖音、小红书链接也需要各自的登录。可以现在去设置，也可以稍后再说。</p>
        <div className="toolbar">
          <button type="button" className="button-press-motion" onClick={()=>{dismissWelcome();openSettings('sites')}}>去登录</button>
          <button type="button" className="text-action" onClick={dismissWelcome}>稍后再说</button>
        </div>
      </div>
    </div>}
  </div></MotionConfig>
}
createRoot(document.getElementById('root')!).render(<App/> )
