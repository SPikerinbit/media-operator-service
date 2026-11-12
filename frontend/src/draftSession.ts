import { useSyncExternalStore } from 'react'
import { errorMessage, request, type Draft, type Publication, type Transcript } from './api'

type SaveState = 'dirty' | 'saving' | 'saved' | 'error'
type Session = {
  doc: Transcript | null; loading: boolean; error: string; edits: Record<number, Draft>;
  saves: Record<number, SaveState>; selected: number[]; expanded: number | null;
  results: Publication[]; busy: 'generate' | 'publish' | ''; activeCue?: number;
  follow: boolean; panel: 'source' | 'drafts';
}
function createSession(id: number) {
  const storageKey = 'media-operator.pending-drafts.' + id
  let pending: Record<number,Draft> = {}
  try {
    const stored = JSON.parse(localStorage.getItem(storageKey) || '{}')
    for (const value of Object.values(stored)) {
      const draft = value as Draft
      if (Number.isInteger(draft?.id) && typeof draft.claim === 'string' && typeof draft.evidence === 'string'
          && typeof draft.example === 'string' && Array.isArray(draft.refs)) pending[draft.id] = draft
    }
  } catch { /* The database still holds every previously acknowledged edit. */ }
  let state: Session = {doc:null,loading:true,error:'',edits:{},saves:{},selected:[],expanded:null,
    results:[],busy:'',follow:false,panel:'source'}
  state.edits = pending
  state.saves = Object.fromEntries(Object.keys(pending).map((key) => [key,'error']))
  const listeners = new Set<() => void>()
  const timers = new Map<number, ReturnType<typeof setTimeout>>()
  const inflight = new Map<number, Promise<void>>()
  const path = '/desktop/knowledge/' + id
  const scroll = {source:0,drafts:0,playback:0}
  const update = (patch: Partial<Session>) => {
    state = {...state,...patch}
    if (patch.edits) {
      try {
        if (Object.keys(patch.edits).length) localStorage.setItem(storageKey,JSON.stringify(patch.edits))
        else localStorage.removeItem(storageKey)
      } catch { /* In-memory editing and database saves remain available. */ }
    }
    listeners.forEach((listener) => listener())
  }
  async function refresh() {
    const before = state.doc
    try {
      const doc = await request<Transcript>(path)
      // Preserve saves acknowledged while this refresh was in flight.
      if (before && state.doc && before !== state.doc) {
        doc.cards = doc.cards.map((card) => {
          const old = before.cards.find((entry) => entry.id === card.id)
          const current = state.doc?.cards.find((entry) => entry.id === card.id)
          return old && current && current !== old ? current : card
        })
      }
      update({doc,error:'',loading:false})
    }
    catch (error) {update({error:errorMessage(error),loading:false}); throw error}
  }
  function save(cardId: number): Promise<void> {
    clearTimeout(timers.get(cardId))
    if (inflight.has(cardId)) return inflight.get(cardId)!
    const work = (async () => {
      while (state.edits[cardId]) {
        const value = state.edits[cardId]
        if (!value.claim.trim()) {
          update({saves:{...state.saves,[cardId]:'error'}})
          throw new Error('请填写观点主题，当前编辑已保留')
        }
        update({saves:{...state.saves,[cardId]:'saving'}})
        try {
          const response = await request<Transcript>(path + '/cards/' + cardId,'PUT',{
            claim:value.claim,evidence:value.evidence,example:value.example,quote_translation:value.quote_translation,
          })
          // A different card can be saving simultaneously. Merge only the acknowledged card.
          const saved = response.cards.find((card) => card.id === cardId)
          const edits = {...state.edits}
          if (edits[cardId] === value) delete edits[cardId]
          update({edits,saves:{...state.saves,[cardId]:edits[cardId] ? 'dirty' : 'saved'},
            doc:state.doc && saved ? {...state.doc,cards:state.doc.cards.map((card) => card.id === cardId ? saved : card)} : state.doc})
        } catch (error) {
          update({saves:{...state.saves,[cardId]:'error'}})
          throw error
        }
      }
    })().finally(() => inflight.delete(cardId))
    inflight.set(cardId,work)
    return work
  }
  function edit(value: Draft) {
    update({edits:{...state.edits,[value.id]:value},saves:{...state.saves,[value.id]:'dirty'}})
    clearTimeout(timers.get(value.id))
    timers.set(value.id,setTimeout(() => {void save(value.id).catch(() => {})},800))
  }
  void refresh().catch(() => {})
  return {get:() => state,update,refresh,edit,save,scroll,
    subscribe:(listener:() => void) => {listeners.add(listener); return () => {listeners.delete(listener)}}}
}
const sessions = new Map<number,ReturnType<typeof createSession>>()
export function useDraftSession(id: number) {
  if (!sessions.has(id)) sessions.set(id,createSession(id))
  const session = sessions.get(id)!
  return [useSyncExternalStore(session.subscribe,session.get),session] as const
}
