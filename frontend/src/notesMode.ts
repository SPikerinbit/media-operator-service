import { useSyncExternalStore } from 'react'

export type NotesMode = 'summary' | 'curated' | 'comprehensive'
const key = 'workbench-notes-mode'
const listeners = new Set<() => void>()
function read(): NotesMode {
  const value = localStorage.getItem(key)
  return value === 'summary' || value === 'comprehensive' ? value : 'curated'
}
export function setNotesMode(value: NotesMode) {
  localStorage.setItem(key, value)
  listeners.forEach(listener => listener())
}
export function useNotesMode() {
  return [useSyncExternalStore(listener => {
    listeners.add(listener)
    window.addEventListener('storage', listener)
    return () => { listeners.delete(listener); window.removeEventListener('storage', listener) }
  }, read), setNotesMode] as const
}
