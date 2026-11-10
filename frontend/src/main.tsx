import { BookOpen, Clapperboard, Settings2 } from 'lucide-react'
import { MotionConfig } from 'motion/react'
import { useCallback, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { errorMessage, request, type Settings as Preferences } from './api'
import type { NoteHandoff, VideoTransfer } from './inbox'
import { Knowledge } from './Knowledge'
import { Settings, type SettingsSection } from './Settings'
import { Video } from './Video'
import './styles.css'
import './studio.css'

const navigation = [
  { id: 'publish', label: '投稿', icon: Clapperboard },
  { id: 'notes', label: '笔记', icon: BookOpen },
  { id: 'settings', label: '设置', icon: Settings2 },
] as const
type View = typeof navigation[number]['id']

function viewFrom(hash: string): View {
  if (hash === 'video' || hash === 'publish') return 'publish'
  if (hash === 'knowledge' || hash === 'notes') return 'notes'
  if (hash === 'settings') return 'settings'
  return 'publish'
}

const initial = window.location.hash.slice(1).split('/')
const initialView = viewFrom(initial[0] || '')

function App() {
  const [view, setView] = useState<View>(initialView)
  const [settings, setSettings] = useState<Preferences | null>(null)
  const [error, setError] = useState('')
  const [settingsFocus, setSettingsFocus] = useState<SettingsSection>('general')
  const [transcript, setTranscript] = useState<number | null>(initialView === 'notes' && /^\d+$/.test(initial[1] || '') ? Number(initial[1]) : null)
  const [transfer, setTransfer] = useState<VideoTransfer | null>(null)
  const [noteHandoff, setNoteHandoff] = useState<NoteHandoff | null>(null)
  const [activity, setActivity] = useState({ publish: '', notes: '' })
  const [visited, setVisited] = useState<View[]>(['publish', initialView])
  const setPublishActivity = useCallback((line: string) => setActivity((current) => current.publish === line ? current : { ...current, publish: line }), [])
  const setNotesActivity = useCallback((line: string) => setActivity((current) => current.notes === line ? current : { ...current, notes: line }), [])
  const clearTransfer = useCallback(() => setTransfer(null), [])
  const clearHandoff = useCallback(() => setNoteHandoff(null), [])

  useEffect(() => {
    const dark = window.matchMedia('(prefers-color-scheme: dark)')
    const forcedColors = window.matchMedia('(forced-colors: active)')
    const syncTitle = () => {
      void window.pywebview?.api?.set_window_theme?.(dark.matches, forcedColors.matches)?.catch(() => {})
    }
    syncTitle()
    window.addEventListener('pywebviewready', syncTitle)
    dark.addEventListener('change', syncTitle)
    forcedColors.addEventListener('change', syncTitle)
    return () => {
      window.removeEventListener('pywebviewready', syncTitle)
      dark.removeEventListener('change', syncTitle)
      forcedColors.removeEventListener('change', syncTitle)
    }
  }, [])

  useEffect(() => {
    let active = true
    void request<Preferences>('/desktop/settings').then((data) => { if (active) setSettings(data) })
      .catch((reason) => { if (active) setError(errorMessage(reason)) })
    return () => { active = false }
  }, [])

  function show(next: View) {
    setView(next)
    setVisited((values) => values.includes(next) ? values : [...values, next])
    window.history.replaceState(null, '', '#' + next)
  }
  function openSettings(section: SettingsSection) {
    setSettingsFocus(section)
    show('settings')
  }
  const progress = view === 'publish' ? activity.publish : view === 'notes' ? activity.notes : ''

  return <MotionConfig reducedMotion="user">
    <a className="skip-link" href="#workspace">跳到工作区</a>
    <div className="shell">
      <aside className="sidebar">
        <nav aria-label="工作台">
          {navigation.map(({ id, label, icon: Icon }) => <button type="button" key={id} className="nav-item"
            aria-label={label} aria-current={view === id ? 'page' : undefined} onClick={() => show(id)}>
            <Icon aria-hidden="true" size={18}/><span>{label}</span>
          </button>)}
        </nav>
        <p className="sidebar-progress" role="status">{progress}</p>
      </aside>
      <main className="workspace thin-scroll" id="workspace" data-view={view} tabIndex={-1}>
        {error && <div className="notice error" role="alert">{error}</div>}
        <div className="workspace-content">
          <div className="publish-view" hidden={view !== 'publish'}>
            <Video settings={settings} transfer={transfer} onTransferUsed={clearTransfer} active={view === 'publish'}
              onActivity={setPublishActivity} onSettings={openSettings}
              onOpenNote={(note) => { setNoteHandoff(note); if (note.transcriptId) setTranscript(note.transcriptId); show('notes') }}/>
          </div>
          {visited.includes('notes') && <div className="notes-view" hidden={view !== 'notes'}>
            <Knowledge settings={settings} transcriptId={transcript} incoming={noteHandoff} onIncomingUsed={clearHandoff}
              active={view === 'notes'} onActivity={setNotesActivity} onSettings={openSettings}
              onVideo={(value) => { setTransfer(value); show('publish') }}/>
          </div>}
          {visited.includes('settings') && <div className="settings-view" hidden={view !== 'settings'}>
            <Settings current={settings} update={setSettings} focus={settingsFocus}/>
          </div>}
        </div>
      </main>
    </div>
  </MotionConfig>
}

createRoot(document.getElementById('root')!).render(<App/>)
