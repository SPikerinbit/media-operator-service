import { useCallback, useEffect, useState } from 'react'
import { errorMessage, request, type Item, type SourceKind, type SourceProbe } from './api'
import { resolveOptions, savedVideoOptions, type Override, type VideoOptions } from './videoOptions'

export type Lane = 'publish' | 'notes'
export type LetterState = 'identifying'|'rejected'|'blocked'|'duplicate'|'ready'|'starting'|'queued'|'running'|'succeeded'|'failed'|'removed'
export type LetterEntry = {
  id:string; client_id?:string; group_id:string; lane:Lane; raw:string; local?:boolean; source?:string; kind?:SourceKind;
  title?:string; author?:string; platform?:string; probe?:SourceProbe; status:LetterState; message:string;
  stage?:string; progress:number; batch_id?:string; item_id?:string; task?:Item; created_at:string;
  result?:NonNullable<Item['result']>&{note_notice?:string}; reuse?:{stage:string;origin_lane:Lane}[]; duplicate_of?:string
}
export type LetterGroup = { id:string;lane:Lane;created_at:string;options:Partial<VideoOptions>;overrides:Record<string,Override>;
  prepared:string[];revision:number;legacy?:boolean }
export type InboxState = {groups:LetterGroup[];entries:LetterEntry[]}
export type PaperLine = {id:string;text:string;local?:boolean}
export const sections = [{id:'output',label:'输出',summary:'画幅与转录'}, {id:'style',label:'字幕样式',summary:'字形与位置'},
  {id:'publish',label:'投稿信息',summary:'封面与内容'}, {id:'translation',label:'翻译上下文',summary:'背景与术语'}] as const
export const stageLabels:Record<string,string> = {download:'获取素材',transcribe:'Whisper 转录',translate:'生成中文译文',burn:'烧录字幕',bilibili_upload:'提交 B 站',extract:'提取观点',done:'已完成',queued:'等待处理'}

export function optionsOf(group:LetterGroup):VideoOptions {
  const original=group.options as Record<string,unknown>
  const defaults=savedVideoOptions(null)
  const bili={...defaults.bilibili_upload,...(original.bilibili_upload as object||{})}
  if(Array.isArray(bili.tags))bili.tags=bili.tags.join('，')
  bili.tid=bili.tid||0
  return resolveOptions(defaults,{...group.options,bilibili_upload:bili})
}

export function useInbox() {
  const [data,setData]=useState<InboxState>({groups:[],entries:[]})
  const [error,setError]=useState('')
  const refresh=useCallback(async()=>{try{setData(await request<InboxState>('/desktop/inbox/queue'));setError('')}catch(e){setError(errorMessage(e))}},[])
  useEffect(()=>{
    let alive=true
    let fallback:number|undefined
    const stream=new EventSource('/desktop/inbox/events')
    stream.onmessage=e=>{if(!alive)return;try{setData(JSON.parse(e.data));setError('');if(fallback){clearInterval(fallback);fallback=undefined}}catch{setError('读取来信状态失败')}}
    stream.onerror=()=>{if(alive&&!fallback)fallback=window.setInterval(()=>void refresh(),4000)}
    void refresh()
    return()=>{alive=false;stream.close();clearInterval(fallback)}
  },[refresh])
  return {data,error,refresh}
}

/** A multi-line share with one URL is one letter; distinct URL-bearing lines remain separate. */
export function splitLetters(raw:string):PaperLine[] {
  const urls=[...raw.matchAll(/https?:\/\/[^\s<>"'，。；！？、）】》]+/gi)]
  if(urls.length<=1)return raw.trim()?[{id:crypto.randomUUID(),text:raw.trim()}]:[]
  let start=0
  return urls.map((match,index)=>{
    const end=index===urls.length-1?raw.length:(match.index||0)+match[0].length
    const text=raw.slice(start,end).trim();start=end
    return {id:crypto.randomUUID(),text}
  })
}

export function reuseMark(entry?:LetterEntry):'clean'|'cut'|'charred' {
  return entry?.reuse?.some(r=>r.origin_lane!==entry.lane) ? (entry.lane==='publish'?'cut':'charred'):'clean'
}
export function entryLabel(entry:LetterEntry) {
  return entry.title||entry.raw.replace(/\s+/g,' ').slice(0,120)
}
