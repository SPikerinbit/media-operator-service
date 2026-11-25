import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useReducedMotion } from 'motion/react'
import { flushSync } from 'react-dom'
import type { PaperProcessHandle } from './paperScene'
import { errorMessage, request, saveAs, type EntryLog, type RemovalRow, type Settings } from './api'
import { Inspector, getOverride, outputDefaults, resolveOptions, savedVideoOptions, type DefaultGroup, type InspectorSection, type Override, type Row, type VideoDefaults, type VideoOptions } from './videoOptions'
import { Modal, Button, WorkbenchToast, type ToastNotice } from './ui'
import { Presence } from './presence'
import { TranscriptView, type NotesDocMeta, type NotesTab } from './TranscriptView'
import { CoverArt, DeskTV, PaperProcess, Prop, asset } from './WorkbenchEffects'
import { currentManifest, woodLanding } from './workbenchAnchors'
import { flyProcessPaper, flyTrashSheets, glideWood } from './workbenchMotion'
import { executionKey, workKnown, workProgress, entryLabel, optionsOf, reuseMark, sections, stageLabels, type InboxState, type Lane, type LetterEntry, type LetterGroup } from './workbenchState'
import { ShredLever } from './ShredLever'
import { useNotesMode, type NotesMode } from './notesMode'

const stateLabels:Record<string,string>={identifying:'识别中',rejected:'已退回',blocked:'待解决',duplicate:'已在队列',ready:'待设置',starting:'准备中',queued:'排队中',running:'处理中',succeeded:'已完成',failed:'处理暂停',removed:'已移除',cancelled:'已取消'}
function manuscriptLink(entry?:LetterEntry){const url=entry?.result?.bilibili_url||'';return /^https?:\/\//.test(url)?url:''}
const logStageBadges: Record<string, string> = {
  succeeded: '已完成',
  running: '进行中',
  failed: '失败',
  queued: '排队中',
  reused: '已复用',
  skipped: '已跳过',
  pending: '等待中',
}
function EntryLog({entry,active}:{entry:LetterEntry;active:boolean}){
  const [log,setLog]=useState<EntryLog|null>(null)
  const [copied,setCopied]=useState(false)
  const [showRaw,setShowRaw]=useState(false)
  const [rawLines,setRawLines]=useState<string[]>([])
  const [rawTotal,setRawTotal]=useState(0)
  const [rawOffset,setRawOffset]=useState(0)
  const [rawLoading,setRawLoading]=useState(false)
  const rawBox=useRef<HTMLDivElement>(null)
  const refreshKey=`${entry.id}:${entry.status}:${entry.stage||''}:${entry.revision||0}:${Math.floor(entry.progress||0)}`
  useEffect(()=>{
    setShowRaw(false);setRawLines([]);setRawTotal(0);setRawOffset(0);setCopied(false)
  },[entry.id])
  useEffect(()=>{
    if(!active)return
    let alive=true
    void request<EntryLog>(`/desktop/inbox/entries/${entry.id}/log?offset=0&limit=120`)
      .then(page=>{if(alive)setLog(page)})
      .catch(()=>{})
    return()=>{alive=false}
  },[refreshKey,active,entry.id])
  async function loadRaw(start:number){
    setRawLoading(true)
    try{
      const page=await request<EntryLog>(`/desktop/inbox/entries/${entry.id}/log?raw=1&offset=${start}&limit=80`)
      setRawLines(prev=>start?[...prev,...page.lines]:page.lines)
      setRawTotal(page.total)
      setRawOffset(page.offset+page.lines.length)
    }finally{setRawLoading(false)}
  }
  function toggleRaw(){
    const next=!showRaw
    setShowRaw(next)
    if(next&&rawLines.length===0)void loadRaw(0).catch(()=>{})
  }
  async function copySummary(){
    const text=(log?.lines||[]).join('\n').trim()
    if(!text)return
    try{
      await navigator.clipboard.writeText(text)
      setCopied(true)
      window.setTimeout(()=>setCopied(false),1800)
    }catch{ /* clipboard unavailable */ }
  }
  const stages=log?.stages||[]
  const foldedCount=log?.folded_count||0
  const totalRaw=log?.raw_total||0
  const totalDuration=log?.overview?.total_duration_label||''
  return <div className="entry-log entry-log-curated">
    <div className="entry-log-head">
      <div className="entry-log-title">
        <strong>处理记录</strong>
        {totalDuration&&<span className="entry-log-meta">总耗时 {totalDuration}</span>}
        {foldedCount>0&&<span className="entry-log-meta">已精简，折叠 {foldedCount.toLocaleString()} 条过程日志</span>}
      </div>
      <div className="entry-log-tools">
        {Boolean(log?.lines?.length)&&<button type="button" className="entry-log-btn" onClick={()=>void copySummary()}>{copied?'已复制':'复制记录'}</button>}
        {totalRaw>0&&<button type="button" className="entry-log-btn" aria-expanded={showRaw} onClick={toggleRaw}>{showRaw?'收起原始日志':`原始日志 (${totalRaw.toLocaleString()})`}</button>}
      </div>
    </div>
    {stages.length>0?<div className="entry-log-stages">
      {stages.map(stage=><section key={stage.stage} className={'log-stage is-'+stage.status}>
        <header className="log-stage-head">
          <span className="log-stage-dot" aria-hidden="true"/>
          <h4>{stage.label}</h4>
          <span className={'log-stage-badge is-'+stage.status}>{logStageBadges[stage.status]||stage.status}{stage.status==='running'&&stage.progress>0&&stage.progress<100?` ${stage.progress}%`:''}</span>
          <span className="log-stage-right">
            {(stage.collapsed_count ?? 0) > 0 && <small className="log-stage-folded">已合并 {(stage.collapsed_count ?? 0).toLocaleString()} 条</small>}
            {stage.duration_label&&<small className="log-stage-dur">{stage.duration_label}</small>}
          </span>
        </header>
        <ul className="log-stage-events">
          {stage.events.map((ev,idx)=><li key={idx} className={'log-ev is-'+ev.level}>
            {ev.clock&&<time>{ev.clock}</time>}
            <span>{ev.text}</span>
          </li>)}
        </ul>
      </section>)}
    </div>:<div className="entry-log-fallback">{(log?.lines||[]).map((line,index)=><span key={index}>{line}</span>)}</div>}
    {showRaw&&<div className="entry-log-raw" ref={rawBox} onScroll={()=>{const node=rawBox.current;if(!rawLoading&&node&&node.scrollTop+node.clientHeight>node.scrollHeight-24&&rawOffset<rawTotal)void loadRaw(rawOffset)}}>
      <div className="entry-log-raw-head"><span>原始日志（已脱敏，共 {rawTotal.toLocaleString()} 行）</span><span>已显示 {rawLines.length.toLocaleString()} 行</span></div>
      <div className="entry-log-raw-body">{rawLines.map((line,index)=><span key={index}>{line}</span>)}</div>
      {rawOffset<rawTotal&&<button type="button" className="entry-log-btn" disabled={rawLoading} onClick={()=>void loadRaw(rawOffset)}>{rawLoading?'加载中…':'继续加载'}</button>}
    </div>}
  </div>
}
type Editing=LetterGroup&{dirty?:boolean}
function restored():Record<string,Editing>{try{return JSON.parse(localStorage.getItem('workbench-config-drafts')||'{}')}catch{return {}}}
function asRow(e:LetterEntry):Row{return {id:e.id,source:e.source||e.raw,kind:e.kind||'url',title:e.title,probe:e.probe}}

function VideoPreview({entry,options,active}: {entry:LetterEntry;options:VideoOptions;active:boolean}) {
  const [frame,setFrame]=useState('');const [error,setError]=useState('')
  const key=JSON.stringify([entry.id,entry.source,options.aspect_ratio,options.resolution,options.fps,options.subtitle_output_mode,options.subtitle_style])
  const playable=entry.result?.final_video_url||entry.result?.source_video_url
  useEffect(()=>{
    setFrame('');setError('');if(playable||!entry.source||entry.probe?.ready!==true)return
    let alive=true
    const timer=setTimeout(()=>void request<{preview_image_url?:string}>('/ui/preview-frame','POST',{
      source_kind:entry.kind,source_value:entry.source,aspect_ratio:options.aspect_ratio,resolution:options.resolution,
      fps:options.fps,subtitle_output_mode:options.subtitle_output_mode,subtitle_style:options.subtitle_style,preview_time_percent:50,
    }).then(r=>{if(alive)setFrame(r.preview_image_url||'')}).catch(e=>{if(alive)setError(errorMessage(e))}),550)
    return()=>{alive=false;clearTimeout(timer)}
  },[key,playable])
  const caption=`${options.aspect_ratio==='source'?'原始画幅':options.aspect_ratio} · ${options.resolution==='best'?'最高可用清晰度':options.resolution} · ${{en_only:'原文字幕',zh_only:'译文字幕',bilingual:'双语字幕'}[options.subtitle_output_mode]||'字幕'}`
  return <DeskTV url={playable} active={active} label={entry.result?.final_video_url?'成片放映':playable?'源片预览':'画面预览'} caption={caption}>
    {frame?<img className="tv-preview-frame" src={frame} alt="当前稿件字幕与画幅预览"/>:<div className="tv-placeholder"><span>{error?'预览暂不可用':'正在取得视频预览'}</span><small>{error||entryLabel(entry)}</small></div>}
  </DeskTV>
}

export function WorkbenchQueue({lane,data,settings,active,onHome,onSettings,refresh}: {
  lane:Lane;data:InboxState;settings:Settings|null;active:boolean;onHome:()=>void;onSettings:(section:'deepseek'|'bilibili'|'obsidian'|'general')=>void;refresh:()=>Promise<void>
}) {
  const [selected,setSelected]=useState(()=>localStorage.getItem('selected-letter-'+lane)||'');const [query,setQuery]=useState('');const [filter,setFilter]=useState('all')
  const [listOpen,setListOpen]=useState(false)
  const [listCollapsed,setListCollapsed]=useState(false)
  const [drafts,setDrafts]=useState<Record<string,Editing>>(restored)
  const [section,setSection]=useState<InspectorSection|null>(null);const [perItem,setPerItem]=useState(false)
  const [toast,setToast]=useState<ToastNotice|null>(null);const toastSeq=useRef(0)
  const [pending,setPending]=useState(false);const [confirm,setConfirm]=useState<LetterGroup|null>(null)
  function showToast(text:string,opts:Omit<ToastNotice,'id'|'text'>={}){
    if(!text){setToast(null);return}
    setToast({id:++toastSeq.current,text,...opts})
  }
  const [rights,setRights]=useState(false);const [retry,setRetry]=useState<LetterEntry|null>(null);const [checked,setChecked]=useState(false)
  const [brazierBox,setBrazierBox]=useState<{host:DOMRect,image:DOMRect}|null>(null)
  const [entering,setEntering]=useState(false)
  const [settled,setSettled]=useState<string[]>([])
  const [defaultMode,rememberMode]=useNotesMode()
  const [taskModes,setTaskModes]=useState<Record<string,NotesMode>>(()=>{try{return JSON.parse(localStorage.getItem('notes-task-modes')||'{}')}catch{return {}}})
  const [defaults,setDefaults]=useState<VideoDefaults|null>(null);const [savingDefault,setSavingDefault]=useState<DefaultGroup|null>(null)
  const [picked,setPicked]=useState<string[]>([])
  const [undo,setUndo]=useState<{ids:string[];until:number}|null>(null)
  const [notesTab,setNotesTab]=useState<NotesTab>('drafts')
  const [notesMeta,setNotesMeta]=useState<NotesDocMeta>({cardCount:0,cueCount:0,langLabel:'',langClass:''})
  const [links,setLinks]=useState<{id:number;refs:number[]}[]>([])
  const [activeCard,setActiveCard]=useState<number|null>(null)
  const [arrived,setArrived]=useState(true)
  const [smokeFor,setSmokeFor]=useState<{id:string;nonce:number}|null>(null)
  const smokeNonce=useRef(0)
  const smoked=useRef(new Set<string>())
  const [holding,setHolding]=useState<{entry:LetterEntry;index:number}[]>([])
  const played=useRef(new Set<string>())
  const flightRef=useRef<(() => void)|null>(null)
  const queueRef=useRef<HTMLDivElement>(null)
  const armed=useRef<{id:string;from:DOMRect;accepted:boolean;previous:string}|null>(null)
  const processRef=useRef<PaperProcessHandle|null>(null)
  const flightGeneration=useRef(0)
  const [startVersion,setStartVersion]=useState(0)
  const [contentTab,setContentTab]=useState<'settings'|'preview'|'records'>('settings')
  const trashRef=useRef<HTMLDivElement>(null)
  const trashFlights=useRef(new Set<() => void>())
  const activeRef=useRef(active)
  activeRef.current=active
  const undoSelection=useRef({selected:'',picked:[] as string[]})
  useEffect(()=>{if(!active)trashFlights.current.forEach(cancel=>cancel());return()=>{trashFlights.current.forEach(cancel=>cancel())}},[active])
  const woodImg=useRef<Record<string,HTMLImageElement|null>>({})
  const woodHome=useRef<Record<string,DOMRect>>({})
  const locateRef=useRef<(cue:number)=>void>(()=>{})
  const deskRef=useRef<HTMLDivElement>(null)
  const transcriptApi=useRef<{prepare:()=>Promise<void>;refresh:(focusMode?:NotesMode)=>Promise<void>}|null>(null)
  const entries=data.entries.filter(e=>e.lane===lane&&e.status!=='removed')
  const visible=entries.filter(e=>(filter==='all'||(filter==='waiting'?['ready','blocked','rejected','failed','duplicate'].includes(e.status):filter==='processing'?['identifying','starting','queued','running'].includes(e.status):e.status==='succeeded'))&&entryLabel(e).toLowerCase().includes(query.toLowerCase()))
  const pickedEntry=entries.find(e=>e.id===selected)||visible.find(e=>['ready','running','starting','queued'].includes(e.status))||visible[0]
  const reduced=useReducedMotion()
  const entry=pickedEntry
  const remote=data.groups.find(g=>g.id===entry?.group_id)
  const group=remote&&(drafts[remote.id]||remote)
  const base=group?optionsOf(group):savedVideoOptions(defaults)
  const effective=entry&&group&&perItem?resolveOptions(base,group.overrides[entry.id]):base
  const configurable=lane==='publish'&&entry?.status==='ready'
  const prepared=group?.prepared||[]
  const running=['running','queued','starting'].includes(entry?.status||'')
  const transcript=entry?.result?.transcript_id
  const notesMode=(running?entry?.execution_mode:taskModes[entry?.id||''])||entry?.notes_mode||defaultMode
  function chooseMode(mode:NotesMode){
    if(!entry||running)return
    rememberMode(mode)
    setTaskModes(current=>{const next={...current,[entry.id]:mode};localStorage.setItem('notes-task-modes',JSON.stringify(next));return next})
  }
  async function startNotes(){
    if(!entry||!remote||running)return
    armPaper()
    if(transcript)await transcriptApi.current?.prepare()
    const latest = await request<{entries: Array<{id:string;status:string;revision:number}>}>(`/desktop/inbox/deliveries/${remote.id}`)
    const current = latest.entries.find(item=>item.id===entry.id) || entry
    await request('/desktop/inbox/groups/'+remote.id+'/start','POST',{revision:remote.revision,confirmed:true,entry_ids:[entry.id],notes_mode:notesMode,restart:current.status!=='ready',entry_revision:current.revision})
    acceptPaper();await refresh()
  }
  useEffect(()=>{setActiveCard(null);setNotesMeta({cardCount:0,cueCount:0,langLabel:'',langClass:''});setNotesTab('drafts')},[entry?.id])
  useEffect(()=>{if(entry?.status==='succeeded')void transcriptApi.current?.refresh(entry.execution_mode as NotesMode | undefined).catch(()=>{})},[entry?.status,entry?.run,entry?.execution_mode])
  const row=entry?asRow(entry):undefined
  const previous=useRef(entry?.id)
  const woodRefs=useRef<Record<string,HTMLButtonElement|null>>({})
  const brazierRef=useRef<HTMLDivElement>(null)
  const slipRef=useRef<HTMLFormElement>(null)
  const preparedRef=useRef<string[]>([])
  const groupId=group?.id
  useEffect(()=>{if(!selected&&entry)setSelected(entry.id)},[entry?.id,selected])
  useEffect(()=>{if(selected)localStorage.setItem('selected-letter-'+lane,selected)},[selected,lane])
  useEffect(()=>{localStorage.setItem('workbench-config-drafts',JSON.stringify(drafts))},[drafts])
  useEffect(()=>{if(previous.current!==entry?.id){setSection(null);setPerItem(false);setToast(current=>current?.tone==='error'?current:null);previous.current=entry?.id}},[entry?.id])
  useEffect(()=>{if(!active)setToast(current=>current?.tone==='error'?current:null)},[active])
  useEffect(()=>{void request<VideoDefaults>('/desktop/video-defaults').then(setDefaults).catch(()=>{})},[])
  function reportError(reason:unknown){
    const text=errorMessage(reason)
    showToast(text,{
      tone:'error',
      actionLabel:text.includes('设置已')?'重新载入设置':undefined,
      onAction:text.includes('设置已')?()=>{if(remote)setDrafts(d=>({...d,[remote.id]:remote}));showToast('已重新载入保存的设置',{tone:'success'})}:undefined,
    })
  }
  async function action(fn:()=>Promise<unknown>){if(pending)return;setPending(true);setToast(null);try{await fn()}catch(e){armed.current=null;setArrived(true);reportError(e)}finally{setPending(false)}}
  function change(next:VideoOptions){
    if(!group||!entry)return
    const changed={...group,dirty:true,prepared:group.prepared.filter(s=>s!==section)}
    if(perItem)changed.overrides={...group.overrides,[entry.id]:getOverride(base,next)}
    else changed.options=next
    setDrafts(d=>({...d,[group.id]:changed}))
  }
  async function save(values:Editing,prepare?:string[]):Promise<LetterGroup>{
    for(const [id,node] of Object.entries(woodImg.current)){const box=node?.getBoundingClientRect();if(box&&box.width>0)woodHome.current[id]=box}
    const result=await request<LetterGroup>('/desktop/inbox/groups/'+values.id,'PATCH',{
      revision:values.revision,options:values.options,overrides:values.overrides,prepared:prepare||values.prepared,
    });setDrafts(d=>({...d,[result.id]:result}));void refresh();return result
  }
  function restoreInheritance(){if(!entry||!group)return;const overrides={...group.overrides};delete overrides[entry.id];setDrafts(d=>({...d,[group.id]:{...group,overrides,prepared:[],dirty:true}}))}
  async function saveDefault(kind:DefaultGroup){
    setSavingDefault(kind)
    try{const next=await request<VideoDefaults>('/desktop/video-defaults','PUT',kind==='output'?{output:outputDefaults(effective)}:{subtitle_style:effective.subtitle_style});setDefaults(next);showToast('已保存为以后投递使用的默认设置',{tone:'success'});window.dispatchEvent(new Event('video-defaults-changed'))}
    catch(e){reportError(e)}finally{setSavingDefault(null)}
  }
  useEffect(()=>{
    preparedRef.current=group?.prepared||[]
    setSettled(group?.prepared||[])
    brazierRef.current?.querySelectorAll('.wood-flight').forEach(node=>node.remove())
  },[groupId])
  useLayoutEffect(()=>{
    const node=brazierRef.current
    if(!node){setBrazierBox(null);return}
    const measure=()=>{
      const imageNode=node.querySelector('.prop:not(.foreground)')
      const image=(imageNode instanceof HTMLElement?imageNode:node).getBoundingClientRect()
      const host=node.getBoundingClientRect()
      setBrazierBox(prev=>prev&&Math.abs(prev.image.left-image.left)<0.5&&Math.abs(prev.image.top-image.top)<0.5&&Math.abs(prev.image.width-image.width)<0.5&&Math.abs(prev.host.left-host.left)<0.5&&Math.abs(prev.host.top-host.top)<0.5?prev:{host,image})
    }
    measure()
    const observer=new ResizeObserver(measure)
    observer.observe(node)
    window.addEventListener('resize',measure)
    return()=>{observer.disconnect();window.removeEventListener('resize',measure)}
  },[section,confirm,groupId,prepared.join(',')])
  useEffect(()=>{
    if(!group)return
    const next=group.prepared
    const prev=preparedRef.current
    const added=next.filter(id=>!prev.includes(id))
    const removed=prev.filter(id=>!next.includes(id))
    preparedRef.current=next
    if(!active||reduced||(!added.length&&!removed.length)){setSettled(next);return}
    let disposed=false
    const timers:number[]=[]
    const flights:{cancel:()=>void}[]=[]
    const temporary:HTMLElement[]=[]
    if(removed.length)setSettled(list=>list.filter(id=>next.includes(id)))
    const host=brazierRef.current
    const box=host?.querySelector('.prop:not(.foreground)')?.getBoundingClientRect()||brazierBox?.image||null
    const stagger=added.length>1?110:0
    ;[...added,...removed].forEach((id,index)=>{
      const order=Math.max(0,sections.findIndex(item=>item.id===id))
      const source=woodImg.current[id]
      if(!source||!box){if(added.includes(id))setSettled(list=>[...new Set([...list,id])]);return}
      const measured=source.getBoundingClientRect()
      const home=measured.width>0?measured:woodHome.current[id]||measured
      const land={...woodLanding(box,currentManifest(),order),width:box.width*.22,height:box.height*.145}
      const button={x:home.left+home.width/2,y:home.top+home.height/2,width:home.width||120,height:home.height||78,rot:0}
      const from=added.includes(id)?button:land
      const to=added.includes(id)?land:button
      const flyer=source.cloneNode(true) as HTMLImageElement
      flyer.className='wood-piece wood-flight'
      flyer.style.visibility='hidden'
      document.body.append(flyer)
      temporary.push(flyer)
      timers.push(window.setTimeout(()=>{
        flyer.style.visibility='visible'
        const flight=glideWood(flyer,from,to)
        flights.push(flight)
        void flight.then(()=>{
        if(disposed)return
        if(added.includes(id)){
          setSettled(list=>[...new Set([...list,id])])
          const puff=document.createElement('i')
          puff.className='ash-puff'
          puff.style.left=land.x+'px'
          puff.style.top=land.y+'px'
          document.body.append(puff)
          temporary.push(puff)
          timers.push(window.setTimeout(()=>puff.remove(),560))
        }
        requestAnimationFrame(()=>flyer.remove())
      })},added.includes(id)?index*stagger:0))
    })
    return()=>{disposed=true;timers.forEach(clearTimeout);flights.forEach(flight=>flight.cancel());temporary.forEach(node=>node.remove())}
  },[groupId,prepared.join(','),active,reduced])
  async function ignite(){
    if(!confirm||!entry||!rights||entering)return
    armPaper()
    const slip=slipRef.current
    setEntering(true);setToast(null)
    if(slip)slip.classList.add('is-leaving')
    try{
      await request('/desktop/inbox/groups/'+confirm.id+'/start','POST',{revision:confirm.revision,confirmed:true,entry_ids:perItem?[entry.id]:ready.map(item=>item.id)})
      acceptPaper();setConfirm(null);setSection(null);setContentTab('records');await refresh()
    }catch(e){reportError(e);armed.current=null;setArrived(true)}finally{setEntering(false)}
  }
  async function removeIds(ids:string[]){
    const root=queueRef.current
    const shots=ids.flatMap(id=>{
      const item=entries.find(e=>e.id===id)
      const rect=root?.querySelector(`[data-entry-id="${id}"] .incoming-open`)?.getBoundingClientRect()
      const index=visible.findIndex(e=>e.id===id)
      return item&&rect&&rect.width?[{entry:item,index:Math.max(0,index),rect,title:entryLabel(item)}]:[]
    })
    undoSelection.current={selected,picked:[...picked]}
    setHolding(shots.map(shot=>({entry:shot.entry,index:shot.index})))
    let response:{results:RemovalRow[];cancelled:number}
    try { response=await request('/desktop/inbox/entries/remove','POST',{ids}) }
    catch(error) { setHolding([]); throw error }
    const okRows=response.results.filter(row=>row.ok)
    const ok=okRows.map(row=>row.id)
    const failed=response.results.filter(row=>!row.ok&&row.message).map(row=>row.message||'')
    if(failed.length)showToast([...new Set(failed)].join('；'),{tone:'error'})
    setHolding(current=>current.filter(item=>ok.includes(item.entry.id)))
    if(!ok.length){setHolding([]);return}
    const untils=okRows.map(row=>Number(row.undo_until)||0).filter(value=>value>0)
    setUndo({ids:ok,until:untils.length?Math.min(...untils)*1000:Date.now()+10000})
    setPicked(current=>current.filter(id=>!ok.includes(id)))
    const flight=flyTrashSheets(activeRef.current?shots.filter(shot=>ok.includes(shot.entry.id)):[],()=>trashRef.current)
    trashFlights.current.add(flight.cancel)
    await refresh()
    await flight
    trashFlights.current.delete(flight.cancel)
    const scroller=root?.querySelector('.incoming-scroll')
    const before=new Map([...(scroller?.querySelectorAll<HTMLElement>('[data-entry-id]')||[])].map(node=>[node.dataset.entryId||'',node.getBoundingClientRect().top]))
    setHolding([])
    requestAnimationFrame(()=>{requestAnimationFrame(()=>{scroller?.querySelectorAll<HTMLElement>('[data-entry-id]').forEach(node=>{const prev=before.get(node.dataset.entryId||'');if(prev==null)return;const dy=prev-node.getBoundingClientRect().top;if(Math.abs(dy)<1)return;node.style.transition='none';node.style.transform=`translateY(${dy}px)`;requestAnimationFrame(()=>{node.style.transition='transform 260ms cubic-bezier(0.22, 1, 0.36, 1)';node.style.transform=''})})})})
  }
  function armPaper(){
    if(!entry)return
    const row=queueRef.current?.querySelector(`[data-entry-id="${entry.id}"] .mini-paper`)?.getBoundingClientRect()
    const fallback=queueRef.current?.querySelector('.title-paper')?.getBoundingClientRect()
    const from=row&&row.width>2&&row.top>=0&&row.bottom<=innerHeight?row:fallback
    if(from)armed.current={id:entry.id,from,accepted:false,previous:executionKey(entry)}
  }
  function acceptPaper(){if(armed.current){armed.current.accepted=true;setStartVersion(n=>n+1)}}
  useEffect(()=>{
    const generation=++flightGeneration.current
    flightRef.current?.();flightRef.current=null;armed.current=null;setArrived(true)
    return()=>{if(flightGeneration.current===generation)flightGeneration.current++;flightRef.current?.();flightRef.current=null}
  },[entry?.id,active])
  useLayoutEffect(()=>{
    if(!entry||!active)return
    const key=executionKey(entry), launch=armed.current
    if(!launch?.accepted||launch.id!==entry.id||played.current.has(key))return
    // The HTTP response can precede SSE; never animate a previous successful run.
    if(key===launch.previous)return
    armed.current=null;played.current.add(key)
    const generation=++flightGeneration.current
    flightRef.current?.();setArrived(false)
    const land=()=>{if(generation!==flightGeneration.current)return;flushSync(()=>setArrived(true));flightRef.current=null}
    if(entry.status==='succeeded'){
      setArrived(true);return
    }
    const flight=flyProcessPaper(launch.from,()=>processRef.current?.key===key?processRef.current:null,key,land)
    flightRef.current=flight.cancel
  },[entry?.id,entry?.status,entry?.execution_id,entry?.run,active,reduced,lane,startVersion])
  useEffect(()=>{if(lane==='publish'&&entry?.status==='succeeded')setContentTab('preview')},[entry?.status,entry?.id,lane])
  useEffect(()=>{
    const onFocusSearch=(event:Event)=>{
      if(!activeRef.current)return
      const detail=(event as CustomEvent<{view?:string}>).detail
      if(detail?.view&&detail.view!==lane)return
      setListCollapsed(false);setListOpen(true)
      requestAnimationFrame(()=>queueRef.current?.querySelector<HTMLInputElement>('.incoming-tools input[type="search"]')?.focus())
    }
    const onEscape=()=>{
      if(!activeRef.current)return
      setConfirm(null);setRetry(null)
    }
    window.addEventListener('workbench-focus-search',onFocusSearch)
    window.addEventListener('workbench-escape',onEscape)
    return()=>{window.removeEventListener('workbench-focus-search',onFocusSearch);window.removeEventListener('workbench-escape',onEscape)}
  },[lane])
  useEffect(()=>{if(!undo)return;const timer=window.setInterval(()=>{if(Date.now()>undo.until)setUndo(null)},500);return()=>window.clearInterval(timer)},[undo])
  const ready=entries.filter(e=>e.group_id===group?.id&&e.status==='ready')
  const rows=visible.slice()
  holding.forEach(item=>{if(!rows.some(e=>e.id===item.entry.id))rows.splice(Math.min(item.index,rows.length),0,item.entry)})
  const selectable=visible.filter(e=>e.deletable)
  const allOn=selectable.length>0&&selectable.every(e=>picked.includes(e.id))
  const overridden=entry&&group&&Object.keys(group.overrides[entry.id]||{}).length>0
  const reuse=entry?.reuse?.filter(r=>r.origin_lane!==lane)||[]
  const notesModeHints: Record<NotesMode, string> = {
    summary: '多层级树状摘要 · 动态分层压缩至底层观点与原文',
    curated: '核心观点 · 陈述、判断、事实与典故，同步生成摘要树',
    comprehensive: '大多数观点 · 详尽保留细节，并行衍生全部三份视图',
  }
  const publishSteps = ['download', 'transcribe', 'translate', 'burn', 'bilibili_upload'] as const
  const activeStepIndex = entry?.stage ? publishSteps.indexOf(entry.stage as (typeof publishSteps)[number]) : -1
  const notesSteps = ['download', 'transcribe', 'translate', 'extract'] as const
  const activeNotesStep = entry?.stage ? notesSteps.indexOf(entry.stage as (typeof notesSteps)[number]) : -1
  const gpuWaitingText = running && entry?.message?.includes('显卡队列') ? entry.message : ''
  return <div className={'workbench-queue '+lane+(listOpen?' is-list-open':'')+(listCollapsed?' is-list-collapsed':'')} ref={queueRef}>
    <header className="queue-heading"><div><h1>{lane==='publish'?'投稿工作台':'笔记工作台'}</h1><p>{lane==='publish'?'备齐设置，再点火处理。':'先确认整理档位，再开始整理。'}</p></div><div className="queue-heading-actions"><button type="button" className="text-action desk-list-toggle" aria-pressed={listCollapsed} onClick={()=>setListCollapsed(c=>!c)}>{listCollapsed?`展开来信（${entries.length}）`:'收起侧栏'}</button><Presence open={Boolean(undo&&Date.now()<undo.until)}>{undo&&Date.now()<undo.until&&<Button variant="secondary" disabled={pending} onClick={()=>void action(async()=>{await Promise.all(undo.ids.map(id=>request('/desktop/inbox/entries/'+id+'/undo','POST')));setUndo(null);setSelected(undoSelection.current.selected);setPicked(undoSelection.current.picked);await refresh()})}>撤销删除</Button>}</Presence></div></header>
    <button type="button" className="incoming-toggle" aria-expanded={listOpen} aria-controls={'incoming-'+lane} onClick={()=>setListOpen(open=>!open)}>{listOpen?'收起来信列表':`展开来信列表（${entries.length}）`}</button>
    <div className="queue-desk">
      <aside id={'incoming-'+lane} className="incoming-list"><div className="incoming-tools"><input type="search" aria-label="搜索来信" placeholder="搜索来信" value={query} onChange={e=>setQuery(e.target.value)}/><select aria-label="筛选来信状态" value={filter} onChange={e=>setFilter(e.target.value)}><option value="all">全部来信</option><option value="waiting">待处理</option><option value="processing">处理中</option><option value="done">已完成</option></select><button type="button" className="batch-delete" disabled={!selectable.length} onClick={()=>setPicked(allOn?picked.filter(id=>!selectable.some(e=>e.id===id)):[...new Set([...picked,...selectable.map(e=>e.id)])])}>{allOn?'取消全选':'全选当前筛选'}</button></div>
        {picked.length>0&&<button type="button" className="batch-delete" onClick={()=>void action(()=>removeIds(picked))}>删除所选 {picked.length} 封</button>}
        <div className="incoming-scroll thin-scroll">{rows.map(e=>{const detail=['identifying','starting','queued','running','failed','blocked'].includes(e.status)?(e.summary?.[0]||''):'';return <div className={'incoming-letter '+(pickedEntry?.id===e.id?'selected':'')+(holding.some(item=>item.entry.id===e.id)&&!entries.some(item=>item.id===e.id)?' is-removing':'')} data-entry-id={e.id} key={e.id}>
          <label className="check"><input type="checkbox" aria-label={'选择 '+entryLabel(e)} checked={picked.includes(e.id)} disabled={!e.deletable||holding.some(item=>item.entry.id===e.id)} onChange={()=>setPicked(list=>list.includes(e.id)?list.filter(id=>id!==e.id):[...list,e.id])}/></label>
          <button type="button" className="incoming-open" onClick={()=>{setSelected(e.id);setListOpen(false);if(lane==='publish'&&e.status==='succeeded'){const key=executionKey(e);if(!smoked.current.has(key)){smoked.current.add(key);smokeNonce.current+=1;setSmokeFor({id:e.id,nonce:smokeNonce.current})}}}} aria-pressed={pickedEntry?.id===e.id}>
            <span className={'mini-paper '+e.status} style={{'--remaining':`${100-(workKnown(e)?workProgress(e):0)}%`} as React.CSSProperties}/><span><strong>{entryLabel(e)}</strong><small>{e.platform||'来信'} <span>{lane==='notes'&&e.status==='ready'?'待确认档位':stateLabels[e.status]}</span></small>{detail&&!detail.includes('已完成')&&<small className="row-note">{detail}</small>}</span>
          </button>
          <button type="button" className="row-delete" aria-label={'删除 '+entryLabel(e)} disabled={!e.deletable||pending||holding.some(item=>item.entry.id===e.id)} onClick={()=>void action(()=>removeIds([e.id]))}>删除</button>
        </div>})}{!rows.length&&<div className="queue-empty"><p>{entries.length?'没有匹配的来信':'这里还没有来信'}</p></div>}</div>
        <footer><span>{entries.length} 封来信</span><div className="desk-trash" ref={trashRef}><Prop name="trash" layer="body"/><Prop name="trash" layer="front" className="trash-front"/></div></footer>
      </aside>
      <section className="selected-letter" aria-label="当前来信">
      {!entry?<div className="workbench-empty"><Prop name={lane==='publish'?'brazier':'shredder'} layer="beauty"/><h2>{lane==='publish'?'火盆已就位':'碎纸机已就位'}</h2><p>从首页投递第一封信。</p></div>:<>
        <div className="letter-title" key={entry.id}><span className="mini-paper title-paper" aria-hidden="true"/><div><h2>{entryLabel(entry)}</h2><p>{entry.platform||'来信'}{entry.author?' / '+entry.author:''}</p></div><span className={'letter-state '+entry.status}>{lane==='notes'&&entry.status==='ready'?'待确认档位':stateLabels[entry.status]}</span></div>
        {lane==='publish'?<div className="publish-workspace">
          <div className="publish-station">
            <div className="publish-scene" ref={brazierRef}>
              <PaperProcess frameKey={executionKey(entry)} paperId={entry.id} processRef={processRef} lane="publish"
                stage={entry.stage} progress={workProgress(entry)} progressKnown={workKnown(entry)} status={entry.status}
                title={entryLabel(entry)} mark={reuseMark(entry)} active={active} arrived={arrived} replaySmoke={smokeFor?.id===entry.id?smokeFor.nonce:0}
                onSmoked={()=>smoked.current.add(executionKey(entry))}
                showPaper={!configurable} logs={configurable?sections.flatMap((s,i)=>settled.includes(s.id)?[i]:[]):[0,1,2,3]}
                parked={entry.waiting_for_shared??entry.message.includes('等待已有任务完成可共享步骤')}/>
            </div>
            <div className="fuel-row">{sections.map((s,i)=><button ref={el=>{woodRefs.current[s.id]=el}}
              className={'wood-setting '+(prepared.includes(s.id)?'prepared':'')} key={s.id} type="button" aria-label={`设置${s.label}`}
              aria-pressed={section===s.id&&contentTab==='settings'} disabled={!configurable||Boolean(confirm)||entering}
              onClick={()=>{setContentTab('settings');setSection(s.id);if(group&&prepared.includes(s.id))setDrafts(d=>({...d,[group.id]:{...group,prepared:prepared.filter(p=>p!==s.id),dirty:true}}))}}>
              <img className="wood-shadow" src={asset('wood-'+i+'-shadow')} alt=""/>
              <img ref={el=>{woodImg.current[s.id]=el}} data-id={s.id} className="wood-piece" src={asset('wood-'+i+'-light-beauty')} alt=""/>
              <strong>{s.label}</strong><small>{prepared.includes(s.id)?'已备齐':s.id==='publish'&&!effective.bilibili_upload.enabled?'仅本地成片':s.summary}</small>
            </button>)}</div>
            <div className="publish-status" role="status">
              <strong>{configurable?(prepared.length===4?'四类设置已备齐':'选择木块修改设置'):gpuWaitingText?gpuWaitingText:entry.waiting_for_shared?'等待共享结果':stageLabels[entry.stage||'']||stateLabels[entry.status]}</strong>
              {!configurable&&<div className="publish-progress-row">
                <div className="stage-pips" aria-hidden="true">{publishSteps.map((step, idx) => <i key={step} className={entry.status==='succeeded'||(activeStepIndex>idx)?'is-done':activeStepIndex===idx&&running?'is-now':''} title={stageLabels[step]||step}/>)}</div>
                <span>{workKnown(entry)?`本次处理进度 ${entry.status==='succeeded'?100:Math.min(99,Math.round(workProgress(entry)))}%`:running?'准备中':'等待处理'}</span>
              </div>}
            </div>
            <div className="prepare-actions">
              {configurable&&group?<><Button variant="secondary" disabled={pending||entering} onClick={()=>void action(async()=>{await save(group,sections.map(s=>s.id));setSection(null)})}>使用当前设置备齐</Button>
              <Button disabled={pending||entering||prepared.length!==4||Boolean(confirm)} onClick={()=>void action(async()=>{const saved=await save(group);setContentTab('settings');setSection(null);setRights(false);setConfirm(saved)})}>开始处理{!perItem&&ready.length>1?` ${ready.length} 条`:''}</Button></>
              :['failed','blocked'].includes(entry.status)?<><Button variant="secondary" disabled={pending} onClick={()=>{if(entry.stage==='bilibili_upload'){setRetry(entry);setChecked(false)}else void action(async()=>{armPaper();await request('/desktop/inbox/entries/'+entry.id+'/retry','POST',{});acceptPaper();await refresh()})}}>重试</Button><Button variant="secondary" onClick={()=>onSettings(entry.message.includes('DeepSeek')?'deepseek':entry.stage==='bilibili_upload'?'bilibili':'general')}>打开相关设置</Button></>
              :entry.status==='running'&&entry.stage==='transcribe'?<Button variant="secondary" disabled={pending} onClick={()=>void action(async()=>{await request('/desktop/inbox/entries/'+entry.id+'/cancel-transcription','POST',{});showToast('正在停止转录，已完成的素材会保留。',{tone:'info',duration:3600})})}>取消转录</Button>
              :<button type="button" className="text-action" onClick={()=>setContentTab('records')}>查看处理记录</button>}
            </div>
          </div>
          <aside className="publish-content" aria-label="稿件内容">
            <div className="publish-tabs" role="tablist" aria-label="稿件内容标签">{([['settings','设置'],['preview','预览'],['records','记录']] as const).map(([tab,label])=><button key={tab} type="button" role="tab" aria-selected={contentTab===tab} aria-controls={'publish-'+tab} id={'tab-'+tab} onClick={()=>setContentTab(tab)}>{label}</button>)}</div>
            <div className="publish-panel" role="tabpanel" id="publish-settings" aria-labelledby="tab-settings" hidden={contentTab!=='settings'}>
              {confirm?<form ref={slipRef} className={'ignition-slip'+(entering?' is-entering':'')} onSubmit={event=>{event.preventDefault();void ignite()}}>
                <h3>确认开始处理</h3><p>将处理{perItem?'当前稿件':`本次投递中 ${ready.length} 条稿件`}，{effective.bilibili_upload.enabled?'完成字幕与成片后提交 B 站。':'完成字幕与本地成片，不提交 B 站。'}</p>
                <p>本次使用已备齐的输出、字幕样式、投稿信息和翻译上下文；单条设置优先。</p>
                <label className="check"><input type="checkbox" checked={rights} disabled={entering} onChange={e=>setRights(e.target.checked)}/>{effective.bilibili_upload.enabled?'我已确认素材使用权限及本次投稿信息':'我已确认素材使用权限及本次处理设置'}</label>
                <div className="toolbar"><Button type="button" variant="secondary" onClick={()=>setConfirm(null)} disabled={entering}>返回检查</Button><Button type="submit" disabled={!rights||entering}>确认并点火</Button></div>
              </form>:configurable&&group?<>
                <div className="config-scope"><div role="group" aria-label="设置作用范围"><button aria-pressed={!perItem} onClick={()=>setPerItem(false)}>本次投递 · {ready.length} 条</button><button aria-pressed={perItem} onClick={()=>setPerItem(true)}>当前稿件{overridden?' · 单独设置':''}</button></div>{perItem&&<button className="text-action" onClick={restoreInheritance}>恢复继承</button>}</div>
                {section?<div className="setting-letter"><div className="setting-letter-head"><h3>{sections.find(s=>s.id===section)?.label}</h3><button type="button" className="text-action" disabled={pending} onClick={()=>void action(async()=>{await save(group,[...new Set([...prepared,section])]);setSection(null)})}>保存并放入火盆</button></div>
                  <Inspector options={effective} change={change} settings={settings} row={row} rowLabel={entryLabel(entry)} perItem={perItem} onScope={setPerItem} reset={restoreInheritance} section={section} onSection={setSection} only={section}
                    defaultsReady={Boolean(defaults)} savingDefault={savingDefault} onSaveDefault={kind=>void saveDefault(kind)} onResetDefault={kind=>change(kind==='output'?{...effective,...outputDefaults(savedVideoOptions(defaults))}:{...effective,subtitle_style:savedVideoOptions(defaults).subtitle_style})}/>
                </div>:<p className="panel-guidance">点击左侧木块检查对应设置，保存后木块会落入火盆。也可以直接使用当前设置备齐。</p>}
              </>:<div className="panel-guidance"><h3>本次设置</h3><p>{effective.aspect_ratio==='source'?'原始画幅':effective.aspect_ratio} · {effective.resolution==='best'?'最高可用清晰度':effective.resolution}</p><p>本次处理使用启动时保存的设置。</p></div>}
            </div>
            <div className="publish-panel preview-panel" role="tabpanel" id="publish-preview" aria-labelledby="tab-preview" hidden={contentTab!=='preview'}>
              <div className="publish-screening">
                <VideoPreview entry={entry} options={effective} active={active&&contentTab==='preview'}/>
                {entry.status==='succeeded'&&<div className="publish-finish-actions">
                  {entry.result?.final_video_url&&<Button variant="secondary" size="small" onClick={()=>void action(async()=>{await request('/desktop/open-path','POST',{target:'artifact',artifact_url:entry.result?.final_video_url});showToast('已在资源管理器中定位成片',{tone:'success',duration:2800})})}>打开成片目录</Button>}
                  {(entry.result?.bilingual_srt_url||entry.result?.translated_srt_url||entry.result?.english_srt_url)&&<Button variant="secondary" size="small" onClick={()=>void action(async()=>{
                    const url=entry.result?.bilingual_srt_url||entry.result?.translated_srt_url||entry.result?.english_srt_url
                    if(url&&await saveAs(entryLabel(entry)+'.srt',{format:'artifact',artifact_url:url}))showToast('字幕文件已导出',{tone:'success',duration:2800})
                  })}>导出字幕</Button>}
                </div>}
                {entry.status==='succeeded'&&manuscriptLink(entry)&&<button type="button" className="success-card" onClick={()=>window.open(manuscriptLink(entry),'_blank','noopener')}><CoverArt cover={entry.result?.cover} video={entry.result?.final_video_url}/><span><strong>{entry.result?.upload_title||entryLabel(entry)}</strong><small>投稿成功，查看稿件 ↗</small></span></button>}
              </div>
            </div>
            <div className="publish-panel records-panel" role="tabpanel" id="publish-records" aria-labelledby="tab-records" hidden={contentTab!=='records'}>
              <p className="stage-copy">{(entry.summary||[]).slice(0,2).join(' · ')||entry.message||stateLabels[entry.status]}</p>
              {reuse.length>0&&<p className="reuse-note">已复用{[...new Set(reuse.map(r=>({download:'源媒体',transcribe:'字幕',translate:'译文',burn:'成片'}[r.stage]||r.stage)))].join('、')}，不计入本次待完成工作。</p>}
              <EntryLog entry={entry} active={active&&contentTab==='records'}/>
              {entry.status==='rejected'&&<blockquote>{entry.raw}</blockquote>}
              {entry.status==='duplicate'&&<Button variant="secondary" onClick={()=>setSelected(entry.duplicate_of||'')}>查看已有任务</Button>}
            </div>
          </aside>
        </div>:<div className="notes-completion" ref={deskRef}>
            <div className="shredder-station">
              <div className="notes-scene">
                <PaperProcess frameKey={executionKey(entry)} paperId={entry.id} processRef={processRef} lane={lane} stage={entry.stage} progress={workProgress(entry)} progressKnown={workKnown(entry)} status={entry.status} title={entryLabel(entry)} mark={reuseMark(entry)} active={active} arrived={arrived} links={links} activeCard={activeCard} onStrip={link=>{setActiveCard(link.id);setNotesTab('drafts');if(link.refs[0])locateRef.current(link.refs[0])}} parked={entry.waiting_for_shared??entry.message.includes('等待已有任务完成可共享步骤')}/>
              </div>
              <div className="notes-mode-row">
                <ShredLever value={notesMode} locked={running||pending} onChange={chooseMode}/>
              </div>
              <div className="publish-status notes-status" role="status">
                <strong>{entry.status==='succeeded'?'整理完成':entry.status==='ready'?'待确认档位':gpuWaitingText?'显卡排队中':entry.waiting_for_shared?'等待共享结果':stageLabels[entry.stage||'']||stateLabels[entry.status]}</strong>
                {entry.status==='ready'?<span className="notes-mode-hint">{notesModeHints[notesMode]}</span>:<div className="publish-progress-row">
                  <div className="stage-pips" aria-hidden="true">{notesSteps.map((step, idx) => <i key={step} className={entry.status==='succeeded'||(activeNotesStep>idx)?'is-done':activeNotesStep===idx&&running?'is-now':''} title={stageLabels[step]||step}/>)}</div>
                  <span>{entry.status==='succeeded'?'本次档位：'+({summary:'摘要',curated:'核心观点',comprehensive:'大多数观点'}[entry.execution_mode||notesMode]):entry.waiting_for_shared?'等待共享结果':workKnown(entry)?`本次处理进度 ${Math.min(99,Math.round(workProgress(entry)))}%`:running?'准备中':entry.message||stateLabels[entry.status]}</span>
                </div>}
              </div>
              <div className="prepare-actions">
                <Button disabled={pending||running||!['ready','succeeded','blocked','failed','cancelled'].includes(entry.status)} onClick={()=>void action(startNotes)}>{running?'正在整理':transcript?'重新整理':'开始整理'}</Button>
                {['failed','blocked'].includes(entry.status)&&<Button variant="secondary" onClick={()=>onSettings(entry.message.includes('DeepSeek')?'deepseek':'general')}>打开相关设置</Button>}
                {entry.status==='running'&&entry.stage==='transcribe'&&<Button variant="secondary" disabled={pending} onClick={()=>void action(async()=>{await request('/desktop/inbox/entries/'+entry.id+'/cancel-transcription','POST',{});await refresh()})}>取消转录</Button>}
                <button type="button" className="text-action" onClick={()=>setNotesTab('records')}>查看处理记录</button>
              </div>
            </div>
            <aside className="publish-content notes-content" aria-label="笔记内容">
              <div className="publish-tabs notes-tabs" role="tablist" aria-label="笔记内容标签">
                <button type="button" role="tab" id="tab-notes-drafts" aria-controls="notes-drafts" aria-selected={notesTab==='drafts'} onClick={()=>setNotesTab('drafts')}>
                  整理{notesMeta.cardCount>0&&<small className="tab-count">{notesMeta.cardCount}</small>}
                </button>
                <button type="button" role="tab" id="tab-notes-source" aria-controls="notes-source" aria-selected={notesTab==='source'} onClick={()=>setNotesTab('source')}>
                  原文{notesMeta.langLabel&&<small className={'tab-lang '+notesMeta.langClass}>{notesMeta.langLabel}</small>}
                </button>
                <button type="button" role="tab" id="tab-notes-records" aria-controls="notes-records" aria-selected={notesTab==='records'} onClick={()=>setNotesTab('records')}>
                  记录
                </button>
              </div>
              {transcript?<TranscriptView key={transcript} id={transcript} settings={settings} translationUrl={entry.result?.translated_srt_url} onSettings={onSettings} variant="desk" activeTab={notesTab} onChangeTab={setNotesTab} onMeta={setNotesMeta} highlightCard={activeCard} onActivateCard={card=>{setActiveCard(card.id)}} onVisibleCards={setLinks} onReady={api=>{locateRef.current=api.locate;transcriptApi.current=api}} managed/>
                :<>
                  <div className="publish-panel notes-awaiting-panel" role="tabpanel" id="notes-drafts" aria-labelledby="tab-notes-drafts" hidden={notesTab!=='drafts'}>
                    <div className="notes-awaiting"><h3>{running?'正在整理内容':'整理结果将在这里展开'}</h3><p>{running?'可切换至「记录」查看实时处理日志。':'在左侧选择整理档位并点击「开始整理」，可在此切换查看多层级摘要、核心观点与大多数观点。'}</p></div>
                  </div>
                  <div className="publish-panel notes-awaiting-panel" role="tabpanel" id="notes-source" aria-labelledby="tab-notes-source" hidden={notesTab!=='source'}>
                    <div className="notes-awaiting"><h3>{running?'正在取得原文':'原文将在这里展开'}</h3><p>{running?'转录或抓取正文完成后即可阅读对照与播控。':'开始整理后，时间戳原文与按需译文会保留在此页。'}</p></div>
                  </div>
                </>}
              <div className="publish-panel records-panel" role="tabpanel" id="notes-records" aria-labelledby="tab-notes-records" hidden={notesTab!=='records'}>
                <p className="stage-copy">{(entry.summary||[]).slice(0,2).join(' · ')||entry.message||stateLabels[entry.status]}</p>
                {reuse.length>0&&<p className="reuse-note">已复用{[...new Set(reuse.map(r=>({download:'源媒体',transcribe:'字幕',translate:'译文',extract:'观点'}[r.stage]||r.stage)))].join('、')}，不计入本次待完成工作。</p>}
                <EntryLog entry={entry} active={active&&notesTab==='records'}/>
                {entry.status==='rejected'&&<blockquote>{entry.raw}</blockquote>}
                {entry.status==='duplicate'&&<Button variant="secondary" onClick={()=>setSelected(entry.duplicate_of||'')}>查看已有任务</Button>}
              </div>
            </aside>
          </div>}

      </>}
      <WorkbenchToast toast={toast} onDismiss={()=>setToast(null)}/>
      </section>
    </div>
    <Modal open={Boolean(retry)} title="确认上次投稿结果" onClose={()=>setRetry(null)}><p>请先检查 B 站稿件管理，确认这条稿件没有投稿成功，再重试上传。</p><label className="check"><input type="checkbox" checked={checked} onChange={e=>setChecked(e.target.checked)}/>已检查，尚未投稿成功</label><Button disabled={!checked||pending} onClick={()=>void action(async()=>{if(retry){armPaper();await request('/desktop/inbox/entries/'+retry.id+'/retry','POST',{upload_checked:true});acceptPaper()}setRetry(null);await refresh()})}>重试上传</Button></Modal>
  </div>
}
