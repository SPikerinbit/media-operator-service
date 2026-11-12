import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useReducedMotion } from 'motion/react'
import { errorMessage, request, type EntryLog, type RemovalRow, type Settings } from './api'
import { Inspector, getOverride, outputDefaults, resolveOptions, savedVideoOptions, type DefaultGroup, type InspectorSection, type Override, type Row, type VideoDefaults, type VideoOptions } from './videoOptions'
import { Modal, Button } from './ui'
import { Presence, usePresented } from './presence'
import { TranscriptView } from './TranscriptView'
import { BrazierLogs, CoverArt, DeskTV, PaperProcess, Prop, asset } from './WorkbenchEffects'
import { anchorPixels, currentManifest, useWorkbenchManifest, woodLanding } from './workbenchAnchors'
import { flyShredPaper, flyTaskPaper, flyTrashSheets, glideWood } from './workbenchMotion'
import { entryLabel, optionsOf, reuseMark, sections, stageLabels, type InboxState, type Lane, type LetterEntry, type LetterGroup } from './workbenchState'
import { ShredLever } from './ShredLever'
import { useNotesMode, type NotesMode } from './notesMode'

const stateLabels:Record<string,string>={identifying:'识别中',rejected:'已退回',blocked:'待解决',duplicate:'已在队列',ready:'待设置',starting:'准备中',queued:'排队中',running:'处理中',succeeded:'已完成',failed:'处理暂停',removed:'已移除',cancelled:'已取消'}
function manuscriptLink(entry?:LetterEntry){const url=entry?.result?.bilibili_url||'';return /^https?:\/\//.test(url)?url:''}
function EntryLog({id}:{id:string}){
  const [lines,setLines]=useState<string[]>([]);const [total,setTotal]=useState(0);const [offset,setOffset]=useState(0);const box=useRef<HTMLDivElement>(null)
  async function more(start:number){const page=await request<EntryLog>(`/desktop/inbox/entries/${id}/log?offset=${start}&limit=80`);setLines(prev=>start? [...prev,...page.lines]:page.lines);setTotal(page.total);setOffset(page.offset+page.lines.length)}
  useEffect(()=>{void more(0).catch(()=>{})},[id])
  return <div className="entry-log" ref={box} onScroll={()=>{const node=box.current;if(node&&node.scrollTop+node.clientHeight>node.scrollHeight-24&&offset<total)void more(offset)}}><p>处理记录</p>{lines.map((line,index)=><span key={index}>{line}</span>)}{offset<total&&<button type="button" onClick={()=>void more(offset)}>继续加载</button>}</div>
}
type Editing=LetterGroup&{dirty?:boolean}
function restored():Record<string,Editing>{try{return JSON.parse(localStorage.getItem('workbench-config-drafts')||'{}')}catch{return {}}}
function asRow(e:LetterEntry):Row{return {id:e.id,source:e.source||e.raw,kind:e.kind||'url',title:e.title,probe:e.probe}}

function VideoPreview({entry,options}: {entry:LetterEntry;options:VideoOptions}) {
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
  return <div className="workbench-preview"><div className="preview-screen" style={{aspectRatio:options.aspect_ratio==='source'?'16/9':options.aspect_ratio.replace(':','/')}}>
    {playable?<video controls preload="metadata" src={playable}/>:frame?<img src={frame} alt="当前稿件字幕与画幅预览"/>:<div className="preview-wait"><span>{error?'预览暂不可用':'正在取得视频预览'}</span><small>{error||entryLabel(entry)}</small></div>}
  </div><p>{options.aspect_ratio==='source'?'原始画幅':options.aspect_ratio} / {options.resolution==='best'?'最高可用清晰度':options.resolution} / {{en_only:'原文字幕',zh_only:'译文字幕',bilingual:'双语字幕'}[options.subtitle_output_mode]||'字幕'}</p></div>
}

export function WorkbenchQueue({lane,data,settings,active,onHome,onSettings,refresh}: {
  lane:Lane;data:InboxState;settings:Settings|null;active:boolean;onHome:()=>void;onSettings:(section:'deepseek'|'bilibili'|'obsidian'|'general')=>void;refresh:()=>Promise<void>
}) {
  const [selected,setSelected]=useState(()=>localStorage.getItem('selected-letter-'+lane)||'');const [query,setQuery]=useState('');const [filter,setFilter]=useState('all')
  const [listOpen,setListOpen]=useState(false)
  const [drafts,setDrafts]=useState<Record<string,Editing>>(restored)
  const [section,setSection]=useState<InspectorSection|null>(null);const [perItem,setPerItem]=useState(false)
  const [notice,setNotice]=useState('');const [pending,setPending]=useState(false);const [confirm,setConfirm]=useState<LetterGroup|null>(null)
  const [rights,setRights]=useState(false);const [retry,setRetry]=useState<LetterEntry|null>(null);const [checked,setChecked]=useState(false)
  const [brazierBox,setBrazierBox]=useState<{host:DOMRect,image:DOMRect}|null>(null)
  const [entering,setEntering]=useState(false)
  const [settled,setSettled]=useState<string[]>([])
  const [defaultMode,rememberMode]=useNotesMode()
  const [taskModes,setTaskModes]=useState<Record<string,NotesMode>>(()=>{try{return JSON.parse(localStorage.getItem('notes-task-modes')||'{}')}catch{return {}}})
  const [defaults,setDefaults]=useState<VideoDefaults|null>(null);const [savingDefault,setSavingDefault]=useState<DefaultGroup|null>(null)
  const [picked,setPicked]=useState<string[]>([])
  const [undo,setUndo]=useState<{ids:string[];until:number}|null>(null)
  const [logOpen,setLogOpen]=useState(false)
  const [links,setLinks]=useState<{id:number;refs:number[]}[]>([])
  const [activeCard,setActiveCard]=useState<number|null>(null)
  const [arrived,setArrived]=useState(true)
  const [smoke,setSmoke]=useState(false)
  const [holding,setHolding]=useState<{entry:LetterEntry;index:number}[]>([])
  const played=useRef(new Set<string>())
  const flightRef=useRef<(() => void)|null>(null)
  const queueRef=useRef<HTMLDivElement>(null)
  const armed=useRef('')
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
  const transcriptApi=useRef<{prepare:()=>Promise<void>;refresh:()=>Promise<void>}|null>(null)
  const entries=data.entries.filter(e=>e.lane===lane&&e.status!=='removed')
  const visible=entries.filter(e=>(filter==='all'||(filter==='waiting'?['ready','blocked','rejected','failed','duplicate'].includes(e.status):filter==='processing'?['identifying','starting','queued','running'].includes(e.status):e.status==='succeeded'))&&entryLabel(e).toLowerCase().includes(query.toLowerCase()))
  const pickedEntry=entries.find(e=>e.id===selected)||visible.find(e=>['ready','running','starting','queued'].includes(e.status))||visible[0]
  const manifest=useWorkbenchManifest()
  const reduced=useReducedMotion()
  const entry=usePresented(pickedEntry, Boolean(reduced))
  const [swap,setSwap]=useState<'in'|'out'|''>('')
  useEffect(()=>{setSwap(pickedEntry&&entry&&pickedEntry.id!==entry.id?'out':'in')},[pickedEntry?.id,entry?.id])
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
    if(transcript)await transcriptApi.current?.prepare()
    await request('/desktop/inbox/groups/'+remote.id+'/start','POST',{revision:remote.revision,confirmed:true,entry_ids:[entry.id],notes_mode:notesMode,restart:entry.status!=='ready',entry_revision:entry.revision})
    await refresh()
  }
  useEffect(()=>{setActiveCard(null)},[entry?.id])
  useEffect(()=>{if(entry?.status==='succeeded')void transcriptApi.current?.refresh().catch(()=>{})},[entry?.status,entry?.run])
  const row=entry?asRow(entry):undefined
  const previous=useRef(entry?.id)
  const woodRefs=useRef<Record<string,HTMLButtonElement|null>>({})
  const brazierRef=useRef<HTMLDivElement>(null)
  const ignitionFrom=useRef<DOMRect|null>(null)
  const slipRef=useRef<HTMLFormElement>(null)
  const preparedRef=useRef<string[]>([])
  const groupId=group?.id
  useLayoutEffect(()=>{
    if(configurable||!ignitionFrom.current)return
    const before=ignitionFrom.current
    ignitionFrom.current=null
    const node=queueRef.current?.querySelector<HTMLElement>('.paper-process.publish')
    if(!node||reduced)return
    const after=node.getBoundingClientRect()
    if(after.width<2)return
    const animation=node.animate([
      {transform:`translate(${before.left-after.left}px,${before.top-after.top}px) scale(${before.width/after.width},${before.height/after.height})`,transformOrigin:'top left'},
      {transform:'none',transformOrigin:'top left'},
    ],{duration:520,easing:'cubic-bezier(.18,1.05,.32,1)'})
    return()=>animation.cancel()
  },[configurable,reduced])
  useEffect(()=>{if(!selected&&entry)setSelected(entry.id)},[entry?.id,selected])
  useEffect(()=>{if(selected)localStorage.setItem('selected-letter-'+lane,selected)},[selected,lane])
  useEffect(()=>{localStorage.setItem('workbench-config-drafts',JSON.stringify(drafts))},[drafts])
  useEffect(()=>{if(previous.current!==entry?.id){setSection(null);setPerItem(false);previous.current=entry?.id}},[entry?.id])
  useEffect(()=>{void request<VideoDefaults>('/desktop/video-defaults').then(setDefaults).catch(()=>{})},[])
  async function action(fn:()=>Promise<unknown>){if(pending)return;setPending(true);setNotice('');try{await fn()}catch(e){setNotice(errorMessage(e))}finally{setPending(false)}}
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
    });setDrafts(d=>({...d,[result.id]:result}));await refresh();return result
  }
  function restoreInheritance(){if(!entry||!group)return;const overrides={...group.overrides};delete overrides[entry.id];setDrafts(d=>({...d,[group.id]:{...group,overrides,prepared:[],dirty:true}}))}
  async function saveDefault(kind:DefaultGroup){
    setSavingDefault(kind)
    try{const next=await request<VideoDefaults>('/desktop/video-defaults','PUT',kind==='output'?{output:outputDefaults(effective)}:{subtitle_style:effective.subtitle_style});setDefaults(next);setNotice('已保存为以后投递使用的默认设置');window.dispatchEvent(new Event('video-defaults-changed'))}
    catch(e){setNotice(errorMessage(e))}finally{setSavingDefault(null)}
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
    const stagger=added.length>1?560:0
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
          timers.push(window.setTimeout(()=>puff.remove(),680))
        }
        requestAnimationFrame(()=>flyer.remove())
      })},added.includes(id)?index*stagger:0))
    })
    return()=>{disposed=true;timers.forEach(clearTimeout);flights.forEach(flight=>flight.cancel());temporary.forEach(node=>node.remove())}
  },[groupId,prepared.join(','),active,reduced])
  async function ignite(){
    if(!confirm||!entry||!rights||entering)return
    ignitionFrom.current=brazierRef.current?.getBoundingClientRect()||null
    const slip=slipRef.current
    setEntering(true);setNotice('');armed.current=entry.id
    if(slip)slip.classList.add('is-leaving')
    try{
      await request('/desktop/inbox/groups/'+confirm.id+'/start','POST',{revision:confirm.revision,confirmed:true,entry_ids:perItem?[entry.id]:ready.map(item=>item.id)})
      setConfirm(null);setSection(null);await refresh()
    }catch(e){setNotice(errorMessage(e));armed.current='';ignitionFrom.current=null}finally{setEntering(false)}
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
    if(failed.length)setNotice([...new Set(failed)].join('；'))
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
    requestAnimationFrame(()=>{requestAnimationFrame(()=>{scroller?.querySelectorAll<HTMLElement>('[data-entry-id]').forEach(node=>{const prev=before.get(node.dataset.entryId||'');if(prev==null)return;const dy=prev-node.getBoundingClientRect().top;if(Math.abs(dy)<1)return;node.style.transition='none';node.style.transform=`translateY(${dy}px)`;requestAnimationFrame(()=>{node.style.transition='transform .52s cubic-bezier(.18,1.28,.32,1)';node.style.transform=''})})})})
  }
  useEffect(()=>()=>{flightRef.current?.();flightRef.current=null},[entry?.id,active])
  useEffect(()=>{
    if(!entry||!active)return
    const run=entry.run||1
    const arrive=`${entry.id}:${run}:arrive`
    const smokeKey=`${entry.id}:${run}:smoke`
    const live=['starting','queued','running'].includes(entry.status)
    const terminal = ['succeeded','failed','blocked','rejected','duplicate','removed','cancelled'].includes(entry.status)
    if(!played.current.has('seen:'+entry.id)){
      played.current.add('seen:'+entry.id)
      if(terminal){played.current.add(arrive);played.current.add(smokeKey);setArrived(true);setSmoke(false);return}
    }
    if(entry.status==='succeeded'&&played.current.has('witness:'+entry.id)&&!played.current.has(smokeKey)){
      played.current.add(smokeKey);setSmoke(true);const timer=window.setTimeout(()=>setSmoke(false),1000);return()=>window.clearTimeout(timer)
    }
    if(played.current.has(arrive)||!live)return
    played.current.add(arrive)
    played.current.add('witness:'+entry.id)
    const root=queueRef.current
    const shell=root?.closest('.workbench-shell')
    const row=root?.querySelector(`[data-entry-id="${entry.id}"] .mini-paper`)?.getBoundingClientRect()
    const slot=shell?.querySelector(`[data-mail-slot="${lane}"]`)?.getBoundingClientRect()
    let from=row&&row.width>2&&row.bottom>0&&row.top<innerHeight?row:slot
    const machine=root?.querySelector('.paper-process .process-machine')?.getBoundingClientRect()
    // Feed the visible manuscript inside the work area, below the television.
    // The list already shows receipt; a wide flying sheet must not cover titles.
    if(lane==='publish'&&machine)from=new DOMRect(machine.left+8,machine.top+12,78,28)
    if(!from||!machine||reduced){setArrived(true);return}
    const spec=currentManifest()
    setArrived(false)
    const flight=lane==='notes'?flyShredPaper(from,()=>queueRef.current?.querySelector<HTMLElement>('.paper-process.notes .process-machine')||null,entryLabel(entry)):flyTaskPaper(from,()=>{
      const next=queueRef.current?.querySelector('.paper-process .process-machine')?.getBoundingClientRect()
      if(!next||next.width<2)return null
      return lane==='publish'?anchorPixels(next,spec.brazier.anchors.rim,spec.brazier.size):anchorPixels(next,spec.shredder.anchors.feed,spec.shredder.size)
    },entryLabel(entry),entry.id+':'+(entry.run||1))
    flightRef.current=flight.cancel
    void flight.then(()=>{flightRef.current=null;setArrived(true)})
  },[entry?.id,entry?.status,entry?.run,active,reduced,lane])
  useEffect(()=>{if(!undo)return;const timer=window.setInterval(()=>{if(Date.now()>undo.until)setUndo(null)},500);return()=>window.clearInterval(timer)},[undo])
  const ready=entries.filter(e=>e.group_id===group?.id&&e.status==='ready')
  const rows=visible.slice()
  holding.forEach(item=>{if(!rows.some(e=>e.id===item.entry.id))rows.splice(Math.min(item.index,rows.length),0,item.entry)})
  const selectable=visible.filter(e=>e.deletable)
  const allOn=selectable.length>0&&selectable.every(e=>picked.includes(e.id))
  const overridden=entry&&group&&Object.keys(group.overrides[entry.id]||{}).length>0
  const reuse=entry?.reuse?.filter(r=>r.origin_lane!==lane)||[]
  return <div className={'workbench-queue '+lane+(listOpen?' is-list-open':'')} ref={queueRef}>
    <header className="queue-heading"><div><h1>{lane==='publish'?'投稿工作台':'笔记工作台'}</h1><p>{lane==='publish'?'备齐设置，再点火处理。':'先确认摘录档位，再开始整理。'}</p></div><Presence open={Boolean(undo&&Date.now()<undo.until)}>{undo&&Date.now()<undo.until&&<Button variant="secondary" onClick={()=>void action(async()=>{await Promise.all(undo.ids.map(id=>request('/desktop/inbox/entries/'+id+'/undo','POST')));setUndo(null);setSelected(undoSelection.current.selected);setPicked(undoSelection.current.picked);await refresh()})}>撤销删除</Button>}</Presence></header>
    <button type="button" className="incoming-toggle" aria-expanded={listOpen} aria-controls={'incoming-'+lane} onClick={()=>setListOpen(open=>!open)}>{listOpen?'收起来信列表':`展开来信列表（${entries.length}）`}</button>
    <div className="queue-desk">
      <aside id={'incoming-'+lane} className="incoming-list"><div className="incoming-tools"><input type="search" aria-label="搜索来信" placeholder="搜索来信" value={query} onChange={e=>setQuery(e.target.value)}/><select aria-label="筛选来信状态" value={filter} onChange={e=>setFilter(e.target.value)}><option value="all">全部来信</option><option value="waiting">待处理</option><option value="processing">处理中</option><option value="done">已完成</option></select><button type="button" className="batch-delete" disabled={!selectable.length} onClick={()=>setPicked(allOn?picked.filter(id=>!selectable.some(e=>e.id===id)):[...new Set([...picked,...selectable.map(e=>e.id)])])}>{allOn?'取消全选':'全选当前筛选'}</button></div>
        {picked.length>0&&<button type="button" className="batch-delete" onClick={()=>void action(()=>removeIds(picked))}>删除所选 {picked.length} 封</button>}
        <div className="incoming-scroll thin-scroll">{rows.map(e=>{const detail=['identifying','starting','queued','running','failed','blocked'].includes(e.status)?(e.summary?.[0]||''):'';return <div className={'incoming-letter '+(pickedEntry?.id===e.id?'selected':'')+(holding.some(item=>item.entry.id===e.id)&&!entries.some(item=>item.id===e.id)?' is-removing':'')} data-entry-id={e.id} key={e.id}>
          <label className="check"><input type="checkbox" aria-label={'选择 '+entryLabel(e)} checked={picked.includes(e.id)} disabled={!e.deletable||holding.some(item=>item.entry.id===e.id)} onChange={()=>setPicked(list=>list.includes(e.id)?list.filter(id=>id!==e.id):[...list,e.id])}/></label>
          <button type="button" className="incoming-open" onClick={()=>{setSelected(e.id);setListOpen(false)}} aria-pressed={pickedEntry?.id===e.id}>
            <span className={'mini-paper '+e.status} style={{'--remaining':`${100-(e.progress_known?e.progress:0)}%`} as React.CSSProperties}/><span><strong>{entryLabel(e)}</strong><small>{e.platform||'来信'} <span>{lane==='notes'&&e.status==='ready'?'待确认档位':stateLabels[e.status]}</span></small>{detail&&!detail.includes('已完成')&&<small className="row-note">{detail}</small>}</span>
          </button>
          <button type="button" className="row-delete" aria-label={'删除 '+entryLabel(e)} disabled={!e.deletable||pending||holding.some(item=>item.entry.id===e.id)} onClick={()=>void action(()=>removeIds([e.id]))}>删除</button>
        </div>})}{!rows.length&&<div className="queue-empty"><p>{entries.length?'没有匹配的来信':'这里还没有来信'}</p></div>}</div>
        <footer><span>{entries.length} 封来信</span><div className="desk-trash" ref={trashRef}><Prop name="trash" layer="body"/><Prop name="trash" layer="front" className="trash-front"/></div></footer>
      </aside>
      <section className={'selected-letter thin-scroll'+(swap?' is-'+swap:'')} aria-label="当前来信">
      {!entry?<div className="workbench-empty"><Prop name={lane==='publish'?'brazier':'shredder'} layer="beauty"/><h2>{lane==='publish'?'火盆已就位':'碎纸机已就位'}</h2><p>从首页投递第一封信。</p></div>:<>
        <div className="letter-title"><div><h2>{entryLabel(entry)}</h2><p>{entry.platform||'来信'}{entry.author?' / '+entry.author:''}</p></div><span className={'letter-state '+entry.status}>{lane==='notes'&&entry.status==='ready'?'待确认档位':stateLabels[entry.status]}</span></div>
        {notice&&<div className="notice" role="status">{notice}{notice.includes('设置已')&&<button type="button" onClick={()=>{if(remote)setDrafts(d=>({...d,[remote.id]:remote}));setNotice('已重新载入保存的设置')}}>重新载入设置</button>}</div>}
        {configurable&&group&&<>
          <div className="config-scope"><div role="group" aria-label="设置作用范围"><button aria-pressed={!perItem} onClick={()=>setPerItem(false)}>本次投递 · {ready.length} 条</button><button aria-pressed={perItem} onClick={()=>setPerItem(true)}>当前稿件{overridden?' · 单独设置':''}</button></div>{perItem&&<button className="text-action" onClick={restoreInheritance}>恢复继承</button>}</div>
          <div className="fuel-row">{sections.map((s,i)=><button ref={el=>{woodRefs.current[s.id]=el}} className={'wood-setting '+(prepared.includes(s.id)?'prepared':'')} key={s.id} type="button" aria-label={`设置${s.label}`} aria-pressed={section===s.id} disabled={Boolean(confirm)||entering} onClick={()=>{setSection(s.id);if(prepared.includes(s.id))setDrafts(d=>({...d,[group.id]:{...group,prepared:prepared.filter(p=>p!==s.id),dirty:true}}))}}>
            <img className="wood-shadow" src={asset('wood-'+i+'-shadow')} alt="" /><img ref={el=>{woodImg.current[s.id]=el}} data-id={s.id} className="wood-piece" src={asset('wood-'+i+'-light-beauty')} alt="" /><strong>{s.label}</strong><small>{prepared.includes(s.id)?'已备齐，可重新编辑':s.summary}</small>
          </button>)}</div>
          <div className="hearth">
            <div className="preparation-scene"><Presence open={Boolean(confirm)}>{confirm&&<form ref={slipRef} className={'ignition-slip'+(entering?' is-entering':'')} onSubmit={event=>{event.preventDefault();void ignite()}}><h3>确认开始处理</h3><p>将处理{perItem?'当前稿件':`本次投递中 ${ready.length} 条稿件`}，完成字幕与成片后提交 B 站。</p><p>本次使用已备齐的输出、字幕样式、投稿信息和翻译上下文；单条设置优先。</p><label className="check"><input type="checkbox" checked={rights} disabled={entering} onChange={e=>setRights(e.target.checked)}/>我已确认素材使用权限及本次投稿信息</label><div className="toolbar"><Button type="button" variant="secondary" onClick={()=>setConfirm(null)} disabled={entering}>返回检查</Button><Button type="submit" disabled={!rights||entering}>确认并点火</Button></div></form>}</Presence><div className="fuel-brazier" ref={brazierRef}><Prop name="brazier"/>{brazierBox&&<BrazierLogs box={{left:brazierBox.image.left-brazierBox.host.left,top:brazierBox.image.top-brazierBox.host.top,width:brazierBox.image.width,height:brazierBox.image.height}} ids={sections.flatMap((section,index)=>settled.includes(section.id)?[index]:[])}/>}<i className="hearth-glow"/><Prop name="brazier" layer="front" className="foreground"/></div><p>{prepared.length===4?'四类设置已备齐，可以开始处理。':'选择木块修改设置，或直接使用当前设置。'}</p></div>
            <Presence open={Boolean(section)}>{section&&<div className="setting-letter"><div className="setting-letter-head"><h3>{sections.find(s=>s.id===section)?.label}</h3><button type="button" className="text-action" disabled={pending} onClick={()=>void action(async()=>{await save(group,[...new Set([...prepared,section])]);setSection(null)})}>保存并放入火盆</button></div>
            <div className="settings-and-preview"><Inspector options={effective} change={change} settings={settings} row={row} rowLabel={entryLabel(entry)} perItem={perItem} onScope={setPerItem} reset={restoreInheritance} section={section} onSection={setSection} only={section}
              defaultsReady={Boolean(defaults)} savingDefault={savingDefault} onSaveDefault={kind=>void saveDefault(kind)} onResetDefault={kind=>change(kind==='output'?{...effective,...outputDefaults(savedVideoOptions(defaults))}:{...effective,subtitle_style:savedVideoOptions(defaults).subtitle_style})}/>
              <VideoPreview entry={entry} options={effective}/></div></div>}</Presence>
          </div>
          <div className="prepare-actions"><Button variant="secondary" disabled={pending||entering} onClick={()=>void action(async()=>{await save(group,sections.map(s=>s.id));setSection(null)})}>使用当前设置备齐</Button><Button disabled={pending||entering||prepared.length!==4||Boolean(confirm)} onClick={()=>void action(async()=>{const saved=await save(group);setSection(null);setRights(false);setConfirm(saved)})}>开始处理{!perItem&&ready.length>1?` ${ready.length} 条`:''}</Button></div>
        </>}
        {!configurable&&<>
          {lane==='notes'?<div className="notes-completion" ref={deskRef}>
            <div className="shredder-station">
              <PaperProcess key={entry.id+':'+(entry.run||1)} frameKey={entry.id+':'+(entry.run||1)} lane={lane} stage={entry.stage} progress={entry.progress_known?entry.progress:0} progressKnown={entry.progress_known!==false} status={entry.status} title={entryLabel(entry)} mark={reuseMark(entry)} active={active} arrived={arrived} links={links} onStrip={link=>{setActiveCard(link.id);if(link.refs[0])locateRef.current(link.refs[0])}} parked={entry.message.includes('等待已有任务完成可共享步骤')}/>
              <ShredLever value={notesMode} locked={running||pending} onChange={chooseMode}/>
              <div className="notes-plaque">
                <strong>{entry.status==='succeeded'?'整理完成':entry.status==='ready'?'待确认档位':stageLabels[entry.stage||'']||stateLabels[entry.status]}</strong>
                <p>{running?'本次档位：'+({summary:'摘要',curated:'精华观点',comprehensive:'大多数观点'}[entry.execution_mode||notesMode]):entry.status==='ready'?'选择侧面拨杆，确认后开始获取原文。':entry.status==='succeeded'?'本次档位：'+({summary:'摘要',curated:'精华观点',comprehensive:'大多数观点'}[entry.execution_mode||notesMode]):entry.message}</p>
                <Button disabled={pending||running||!['ready','succeeded','blocked','failed','cancelled'].includes(entry.status)} onClick={()=>void action(startNotes)}>{running?'正在整理':transcript?'重新整理':'开始整理'}</Button>
                {entry.progress_known&&running&&<span>{Math.round(entry.progress)}%</span>}
                {['failed','blocked'].includes(entry.status)&&<button className="text-action" onClick={()=>onSettings(entry.message.includes('DeepSeek')?'deepseek':'general')}>打开相关设置</button>}
                {entry.status==='running'&&entry.stage==='transcribe'&&<button className="text-action" disabled={pending} onClick={()=>void action(async()=>{await request('/desktop/inbox/entries/'+entry.id+'/cancel-transcription','POST',{});await refresh()})}>取消转录</button>}
                <button className="text-action" onClick={()=>setLogOpen(open=>!open)}>{logOpen?'收起详情':'查看详情'}</button>
                <div className="notes-log-slot">{logOpen&&<EntryLog id={entry.id}/>}</div>
              </div>
            </div>
            {transcript?<TranscriptView key={transcript} id={transcript} settings={settings} translationUrl={entry.result?.translated_srt_url} onSettings={onSettings} variant="desk" highlightCard={activeCard} onActivateCard={card=>{setActiveCard(card.id);if(card.refs[0])locateRef.current(card.refs[0])}} onVisibleCards={setLinks} onReady={api=>{locateRef.current=api.locate;transcriptApi.current=api}} managed/>
              :<div className="notes-awaiting"><h3>{running?'正在取得原文':'原文与观点将在这里展开'}</h3><p>{running?'可以查看机器下方的处理记录。':'确认档位并开始整理后，原文和观点会分别保留在各自的阅读框中。'}</p></div>}
          </div>:<div className="task-scene">
            <div className="task-column">
              {lane==='publish'&&<DeskTV url={entry.status==='succeeded'?entry.result?.final_video_url:undefined}/>}
              <div className="task-stage">
                <PaperProcess key={entry.id+':'+(entry.run||1)} frameKey={entry.id+':'+(entry.run||1)} lane={lane} stage={entry.stage} progress={entry.progress_known?entry.progress:0} progressKnown={entry.progress_known!==false} status={entry.status} title={entryLabel(entry)} mark={reuseMark(entry)} active={active} arrived={arrived} replaySmoke={smoke} parked={entry.message.includes('等待已有任务完成可共享步骤')}/>
                <Presence open={Boolean(lane==='publish'&&entry.status==='succeeded'&&manuscriptLink(entry))}>{lane==='publish'&&entry&&entry.status==='succeeded'&&manuscriptLink(entry)&&<button type="button" className="success-card" onClick={()=>window.open(manuscriptLink(entry),'_blank','noopener')}><CoverArt cover={entry.result?.cover} video={entry.result?.final_video_url}/><strong>{entry.result?.upload_title||entryLabel(entry)}</strong><small>投稿成功，等待审核</small></button>}</Presence>
              </div>
            </div>
            <div className="process-description" role="status">
              <strong className="stage-line">{entry.status==='succeeded'&&lane==='publish'&&manuscriptLink(entry)?'投稿成功，等待审核':stageLabels[entry.stage||'']||stateLabels[entry.status]}</strong>
              <span className="progress-number">{entry.progress_known?Math.round(entry.progress)+'%':'等待'}</span>
              <p className="stage-copy">{(entry.summary||[]).slice(0,2).join(' ')||stateLabels[entry.status]}</p>
              <button type="button" className="text-action" onClick={()=>setLogOpen(open=>!open)}>查看详情</button>
              <div className="log-slot">{logOpen&&<EntryLog id={entry.id}/>}</div>
              {entry.status==='running'&&entry.stage==='transcribe'&&<Button variant="secondary" disabled={pending} onClick={()=>void action(async()=>{await request('/desktop/inbox/entries/'+entry.id+'/cancel-transcription','POST',{});setNotice('正在停止转录，已完成的素材会保留；停止后可重试恢复。')})}>取消转录</Button>}
            </div>
          </div>}
          {lane==='publish'&&reuse.length>0&&<div className="reuse-banner"><Prop name={reuseMark(entry)==='cut'?'paper-cut':'paper-charred'} layer="beauty" className="reuse-sheet"/><p className="reuse-note">已复用{[...new Set(reuse.map(r=>({download:'源媒体',transcribe:'字幕',translate:'译文',burn:'成片'}[r.stage]||r.stage)))].join('、')}，继续{lane==='publish'?'成片与投稿':'整理笔记'}。</p></div>}
          {lane==='publish'&&['failed','blocked'].includes(entry.status)&&<div className="resolve-letter"><p>{(entry.summary||[entry.message]).slice(0,2).join(' ')}</p><div className="toolbar"><Button variant="secondary" disabled={pending} onClick={()=>{if(entry.stage==='bilibili_upload'){setRetry(entry);setChecked(false)}else{armed.current=entry.id;void action(async()=>{await request('/desktop/inbox/entries/'+entry.id+'/retry','POST',{});await refresh()})}}}>重试</Button><Button variant="secondary" onClick={()=>onSettings(entry.message.includes('DeepSeek')?'deepseek':entry.stage==='bilibili_upload'?'bilibili':'general')}>打开相关设置</Button></div></div>}
          {entry.status==='rejected'&&<div className="resolve-letter"><p>{(entry.summary||[entry.message])[0]}</p><blockquote>{entry.raw}</blockquote></div>}
          {entry.status==='duplicate'&&<div className="resolve-letter"><p>{(entry.summary||[entry.message])[0]}</p><Button variant="secondary" onClick={()=>setSelected(entry.duplicate_of||'')}>查看已有任务</Button></div>}

        </>}
      </>}
      </section>
    </div>
    <Modal open={Boolean(retry)} title="确认上次投稿结果" onClose={()=>setRetry(null)}><p>请先检查 B 站稿件管理，确认这条稿件没有投稿成功，再重试上传。</p><label className="check"><input type="checkbox" checked={checked} onChange={e=>setChecked(e.target.checked)}/>已检查，尚未投稿成功</label><Button disabled={!checked||pending} onClick={()=>void action(async()=>{if(retry)await request('/desktop/inbox/entries/'+retry.id+'/retry','POST',{upload_checked:true});setRetry(null);await refresh()})}>重试上传</Button></Modal>
  </div>
}
