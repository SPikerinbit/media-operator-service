import { Aperture, AudioLines, Clapperboard, Settings2 } from 'lucide-react'
import { MotionConfig } from 'motion/react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { errorMessage, request, type Settings as Preferences } from './api'
import { Knowledge } from './Knowledge'
import { Settings } from './Settings'
import { Video, type VideoTransfer } from './Video'
import './styles.css'

const navigation = [
  {id:'video',label:'视频制作',icon:Clapperboard},
  {id:'knowledge',label:'字幕分析',icon:AudioLines},
  {id:'settings',label:'设置',icon:Settings2},
] as const
type View = typeof navigation[number]['id']

function App() {
  const [view,setView] = useState<View>('video')
  const [settings,setSettings] = useState<Preferences|null>(null)
  const [error,setError] = useState('')
  const [transcript,setTranscript] = useState<number|null>(null)
  const [transfer,setTransfer] = useState<VideoTransfer|null>(null)
  const [visited,setVisited] = useState<View[]>(['video'])
  const scroll = useRef<HTMLElement>(null)

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
    void request<Preferences>('/desktop/settings').then((data) => {
      if (active) setSettings(data)
    }).catch((e) => {if (active) setError(errorMessage(e))})
    return () => {active = false}
  },[])

  function show(next: View) {
    setView(next)
    setVisited((values) => values.includes(next) ? values : [...values,next])
    scroll.current?.scrollTo(0,0)
  }
  const clearTransfer = useCallback(() => setTransfer(null),[])

  return <MotionConfig reducedMotion="user">
    <a className="skip-link" href="#workspace">跳到工作区</a>
    <div className="shell">
      <aside className="sidebar chrome">
        <div className="brand"><div className="brand-mark"><Aperture size={23} strokeWidth={1.7}/></div>
          <div><strong>Media Operator</strong><small>本地媒体工作台</small></div></div>
        <nav aria-label="工作台">
          <div className="nav-caption">工作区</div>
          {navigation.map(({id,label,icon:Icon}) => <button type="button" key={id} className="nav-item"
            title={label} aria-label={label} aria-current={view === id ? 'page' : undefined} onClick={() => show(id)}>
            <Icon aria-hidden="true" size={18}/><span>{label}</span>
          </button>)}
        </nav>
        <div className="sidebar-footer"><span className="local-dot"/><div>本机工作区<small>Windows 桌面版</small></div></div>
      </aside>
      <div className="workarea">
        <div className="topline chrome"><span>工作台</span><span className="topline-divider">/</span>
          <strong>{navigation.find((entry) => entry.id === view)?.label}</strong><span className="version">0.2.9</span></div>
      <main className="workspace thin-scroll" id="workspace" data-view={view} ref={scroll} tabIndex={-1}>
        {error && <div className="notice error" role="alert">{error}</div>}
        <div className="workspace-content">
          <div className="video-view" hidden={view !== 'video'}><Video settings={settings} transfer={transfer} onTransferUsed={clearTransfer}
            onTranscript={(id) => {setTranscript(id);show('knowledge')}}/></div>
          {visited.includes('knowledge') && <div hidden={view !== 'knowledge'}>
            <Knowledge settings={settings} transcriptId={transcript} onSettings={() => show('settings')}
              onVideo={(value) => {setTransfer(value);show('video')}}/>
          </div>}
          {visited.includes('settings') && <div hidden={view !== 'settings'}><Settings current={settings} update={setSettings}/></div>}
        </div>
      </main>
      </div>
    </div>
  </MotionConfig>
}

createRoot(document.getElementById('root')!).render(<App/>)
