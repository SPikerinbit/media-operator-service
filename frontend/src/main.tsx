import { Clapperboard, FileText, HelpCircle, Inbox, Settings2 } from 'lucide-react'
import { MotionConfig, useReducedMotion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { errorMessage, request, type Settings as Preferences } from './api'
import { BackgroundModelBanner } from './BackgroundModelBanner'
import { DeskCoachmarks } from './DeskCoachmarks'
import { useModelDownloads } from './modelDownloads'
import { Settings, type SettingsSection } from './Settings'
import { WorkbenchHome } from './WorkbenchHome'
import { WorkbenchQueue } from './WorkbenchQueue'
import { entryLabel, useInbox, workKnown, workProgress } from './workbenchState'
import { SetupGuide } from './SetupGuide'
import './styles.css'
import './studio.css'
import './workbench.css'
import './study.css'
import './workspaceLayout.css'

type View='home'|'publish'|'notes'|'settings'
const navigation=[
  {id:'home',label:'信箱',Icon:Inbox},
  {id:'publish',label:'投稿',Icon:Clapperboard},
  {id:'notes',label:'笔记',Icon:FileText},
  {id:'settings',label:'设置',Icon:Settings2},
] as const
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
  const [pendingLetters,setPendingLetters]=useState<string[]>([])
  useEffect(()=>{const update=(event:Event)=>{const {ids,on}=(event as CustomEvent<{ids:string[];on:boolean}>).detail;setPendingLetters(current=>on?[...new Set([...current,...ids])]:current.filter(id=>!ids.includes(id)))};window.addEventListener('delivery-pending',update);return()=>window.removeEventListener('delivery-pending',update)},[])
  const [leaving,setLeaving]=useState<View|null>(null)
  const [deck,setDeck]=useState<{kind:string;dir:number}>({kind:'drawer',dir:1})
  const deckTimer=useRef<number|null>(null)
  const [welcome,setWelcome]=useState(false)
  const [coachmarks,setCoachmarks]=useState(false)
  const downloads=useModelDownloads()
  const reduced=useReducedMotion()
  const viewRef=useRef(view)
  const workspace=useRef<HTMLElement>(null)
  const entryStates=useRef<Map<string,string>>(new Map())
  const hydratedRef=useRef(false)
  viewRef.current=view
  useEffect(()=>{if(reduced)setLeaving(null)},[reduced])
  useEffect(()=>{
    const activeEntries=inbox.data.entries.filter(e=>['running','starting','queued'].includes(e.status))
    const api=window.pywebview?.api
    if(api?.set_taskbar_progress){
      if(!activeEntries.length){
        const dl=downloads.activeDownload
        if(dl){
          const pct=Math.round(dl.download?.percent ?? 0)
          if(pct>0)void api.set_taskbar_progress('normal',Math.max(2,Math.min(99,pct)))?.catch(()=>{})
          else void api.set_taskbar_progress('indeterminate',0)?.catch(()=>{})
        }else{
          void api.set_taskbar_progress('none',0)?.catch(()=>{})
        }
      }else{
        const known=activeEntries.filter(e=>workKnown(e))
        if(known.length){
          const pct=Math.round(known.reduce((sum,e)=>sum+workProgress(e),0)/known.length)
          void api.set_taskbar_progress('normal',Math.max(2,Math.min(99,pct)))?.catch(()=>{})
        }else{
          void api.set_taskbar_progress('indeterminate',0)?.catch(()=>{})
        }
      }
    }
    const prev=entryStates.current
    if(!hydratedRef.current){
      if(inbox.data.entries.length||inbox.data.groups.length){
        inbox.data.entries.forEach(e=>prev.set(e.id,e.status))
        hydratedRef.current=true
      }
      return
    }
    for(const item of inbox.data.entries){
      const old=prev.get(item.id)
      if(old&&['running','starting','queued'].includes(old)&&['succeeded','failed'].includes(item.status)){
        const laneName=item.lane==='publish'?'投稿':'笔记'
        const ok=item.status==='succeeded'
        void api?.notify_complete?.(
          ok?`${laneName}任务已完成`:`${laneName}任务已暂停`,
          `${entryLabel(item)}${ok?' 已处理完成':(item.message?'：'+item.message:'')}`,
        )?.catch(()=>{})
      }
    }
    prev.clear()
    inbox.data.entries.forEach(e=>prev.set(e.id,e.status))
  },[inbox.data.entries,inbox.data.groups.length,downloads.activeDownload])
  useEffect(()=>{
    const timer=window.setTimeout(()=>{hydratedRef.current=true},1500)
    return()=>clearTimeout(timer)
  },[])
  useEffect(()=>{
    function onKeyDown(event:KeyboardEvent){
      if(welcome||event.isComposing)return
      const target=event.target as HTMLElement|null
      const typing=Boolean(target&&(['INPUT','TEXTAREA','SELECT'].includes(target.tagName)||target.isContentEditable))
      if((event.ctrlKey||event.metaKey)&&!event.altKey&&!event.shiftKey){
        const idx={'1':0,'2':1,'3':2,'4':3}[event.key]
        if(idx!==undefined){
          event.preventDefault();show(order[idx]);return
        }
        if(event.key.toLowerCase()==='k'){
          event.preventDefault()
          if(viewRef.current==='home'){
            document.querySelector<HTMLInputElement>('.home-view .rule-input')?.focus()
          }else{
            window.dispatchEvent(new CustomEvent('workbench-focus-search',{detail:{view:viewRef.current}}))
          }
          return
        }
      }
      if(!typing&&!event.ctrlKey&&!event.metaKey&&!event.altKey){
        if(event.key==='/'){
          event.preventDefault()
          if(viewRef.current==='home'){
            document.querySelector<HTMLInputElement>('.home-view .rule-input')?.focus()
          }else{
            window.dispatchEvent(new CustomEvent('workbench-focus-search',{detail:{view:viewRef.current}}))
          }
          return
        }
        if(event.key===' '&&!target?.closest('button,a,[role="radio"],[role="tab"],summary')){
          const activePane=workspace.current?.querySelector<HTMLElement>(`.${viewRef.current}-view, .lane-view:not([inert])`)
          const media=[...(activePane?.querySelectorAll<HTMLMediaElement>('video,audio')||[])].find(el=>el.offsetParent!==null||el.tagName==='AUDIO')
          if(media&&media.src){
            event.preventDefault()
            if(media.paused)void media.play().catch(()=>{})
            else media.pause()
            return
          }
        }
      }
      if(event.key==='Escape'){
        window.dispatchEvent(new CustomEvent('workbench-escape'))
      }
    }
    window.addEventListener('keydown',onKeyDown)
    return()=>window.removeEventListener('keydown',onKeyDown)
  },[welcome])
  useEffect(()=>{
    const forced=matchMedia('(forced-colors: active)')
    const sync=()=>void window.pywebview?.api?.set_window_theme?.(false,forced.matches)?.catch(()=>{})
    sync();window.addEventListener('pywebviewready',sync);forced.addEventListener('change',sync)
    return()=>{window.removeEventListener('pywebviewready',sync);forced.removeEventListener('change',sync)}
  },[])
  useEffect(()=>{void request<Preferences>('/desktop/settings').then(next=>{
    setSettings(next)
    setWelcome(!next.onboarding_complete&&localStorage.getItem('workbench-onboarding')!=='done')
  }).catch(e=>setError(errorMessage(e)))},[])
  useEffect(()=>{
    const base=import.meta.env.BASE_URL
    ;['workbench/materials/paper.webp','workbench/materials/brass.webp','workbench/mailbox-light-body.webp','workbench/mailbox-light-front.webp','workbench/mailbox-light-flap.webp','workbench/mailbox-light-slot-front.webp','workbench/mailbox-light-slot-back.webp','workbench/envelope-light-front.webp','workbench/envelope-light-body.webp','workbench/brazier-light-body.webp','workbench/brazier-light-front.webp','workbench/shredder-light-body.webp','workbench/shredder-light-front.webp','workbench/shred-switch-plate.webp','workbench/desk-tv-frame.webp','workbench/trash-light-body.webp','workbench/trash-light-front.webp'].forEach(path=>{const img=new Image();img.src=base+path;void img.decode?.().catch(()=>{})})
    let alive=true
    requestAnimationFrame(()=>requestAnimationFrame(()=>{if(alive)setWarm(true)}))
    return()=>{alive=false}
  },[])
  useEffect(()=>{const change=()=>show(fromHash());window.addEventListener('hashchange',change);return()=>window.removeEventListener('hashchange',change)},[])
  useEffect(()=>()=>{if(deckTimer.current!=null)window.clearTimeout(deckTimer.current)},[])
  function show(next:View){
    const current=viewRef.current
    if(next===current)return
    const dir=order.indexOf(next)>=order.indexOf(current)?1:-1
    setDeck({kind:metaphor(current,next),dir})
    if(deckTimer.current!=null){window.clearTimeout(deckTimer.current);deckTimer.current=null}
    if(!matchMedia('(prefers-reduced-motion: reduce)').matches){
      setLeaving(current)
      deckTimer.current=window.setTimeout(()=>{deckTimer.current=null;setLeaving(null)},460)
    }
    else setLeaving(null)
    setView(next);setVisited(v=>v.includes(next)?v:[...v,next]);history.replaceState(null,'','#'+next)
  }
  function openSettings(section:SettingsSection){setCoachmarks(false);setSettingsFocus(section);show('settings')}
  function dismissWelcome(opts?:{startCoachmarks?:boolean}){
    localStorage.setItem('workbench-onboarding','done');setWelcome(false)
    void request<Preferences>('/desktop/settings','PUT',{onboarding_complete:true}).then(setSettings).catch(e=>setError(errorMessage(e)))
    if(opts?.startCoachmarks){
      show('home')
      window.setTimeout(()=>setCoachmarks(true),120)
    }
  }
  function reopenGuide(){setCoachmarks(false);localStorage.removeItem('workbench-onboarding');setWelcome(true)}
  function replayCoachmarks(){setWelcome(false);show('home');window.setTimeout(()=>setCoachmarks(true),160)}
  function deckClass(id:View){
    if(leaving===id)return 'is-deck-out'
    if(view===id&&leaving)return 'is-deck-in'
    return ''
  }
  useEffect(()=>{if(!leaving&&!welcome)workspace.current?.focus({preventScroll:true})},[view,leaving,welcome])
  function pageAccess(id:View){return {inert:view!==id||welcome,'aria-hidden':view!==id||welcome,
    onAnimationEnd:(event:React.AnimationEvent<HTMLDivElement>)=>{
      if(event.target===event.currentTarget&&view===id){
        if(deckTimer.current!=null){window.clearTimeout(deckTimer.current);deckTimer.current=null}
        setLeaving(null)
      }
    }}}
  return <MotionConfig reducedMotion="user"><a className="skip-link" href="#workspace">跳到工作区</a><div className="shell workbench-shell">
    <aside className="sidebar"><div className="workbench-brand" title="Media Operator">M<span>O</span></div><nav aria-label="工作台">{navigation.map(({id,label,Icon})=>{
      const count=inbox.data.entries.filter(e=>e.lane===id&&!pendingLetters.includes(e.client_id||'')&&['ready','running','queued','blocked','failed','identifying','starting'].includes(e.status)).length
      return <button type="button" className="nav-item" key={id} aria-label={label} aria-current={view===id?'page':undefined} onClick={()=>{setCoachmarks(false);show(id)}}>
        <span className="nav-icon" data-mail-slot={id==='publish'||id==='notes'?id:undefined} aria-hidden="true"><Icon size={20} strokeWidth={1.75}/></span>
        <span>{label}</span>{count>0&&<small key={count} className="nav-count">{count}</small>}</button>
    })}</nav><div className="sidebar-bottom"><button type="button" className="sidebar-help-btn" aria-label="打开使用教程" title="打开新手教程与使用演示" onClick={reopenGuide}><HelpCircle size={15} strokeWidth={1.85} aria-hidden="true"/><span>教程</span></button><small className="sidebar-version">{__APP_VERSION__}</small></div></aside>
    <main ref={workspace} id="workspace" className={'workspace'+(leaving?' is-decking':'')} data-view={view} data-motion={deck.kind} data-dir={deck.dir} tabIndex={-1}><div className="workspace-content">
      {(error||inbox.error)&&<div className="notice error" role="alert">{error||inbox.error}<button type="button" onClick={()=>void inbox.refresh()}>重新连接</button></div>}
      <div {...pageAccess('home')} className={'home-view '+deckClass('home')+(warm&&view!=='home'&&leaving!=='home'?' is-parked':'')} hidden={!warm&&view!=='home'&&leaving!=='home'}><WorkbenchHome data={inbox.data} active={view==='home'} onOpen={show}/></div>
      {(['publish','notes'] as const).map(lane=>(warm||visited.includes(lane))&&<div {...pageAccess(lane)} className={'lane-view '+deckClass(lane)+(warm&&view!==lane&&leaving!==lane?' is-parked':'')} key={lane} hidden={!warm&&view!==lane&&leaving!==lane}><WorkbenchQueue lane={lane} data={inbox.data} settings={settings} active={view===lane} onHome={()=>show('home')} onSettings={openSettings} refresh={inbox.refresh}/></div>)}
      {(warm||visited.includes('settings'))&&<div {...pageAccess('settings')} className={'settings-view '+deckClass('settings')+(warm&&view!=='settings'&&leaving!=='settings'?' is-parked':'')} hidden={!warm&&view!=='settings'&&leaving!=='settings'}><Settings current={settings} update={setSettings} focus={settingsFocus} onOpenGuide={reopenGuide} onReplayTour={replayCoachmarks} active={view==='settings'}/></div>}
    </div></main>
    <BackgroundModelBanner controller={downloads} hidden={welcome} onOpenResources={()=>openSettings('resources')}/>
    <DeskCoachmarks open={coachmarks&&!welcome&&view==='home'} onClose={()=>setCoachmarks(false)}/>
    {welcome&&<SetupGuide settings={settings} downloads={downloads} onSettings={setSettings} onClose={dismissWelcome}/>}
  </div></MotionConfig>
}
createRoot(document.getElementById('root')!).render(<App/> )
