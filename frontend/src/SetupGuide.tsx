import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  Cpu,
  Download,
  FileText,
  Flame,
  Inbox,
  KeyRound,
  Keyboard,
  Layers,
  ShieldCheck,
  Sparkles,
} from 'lucide-react'
import { motion, useReducedMotion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'
import { defaultSites, mergeSites, SiteMark } from './SiteMark'
import { asset } from './WorkbenchEffects'
import { request, type Settings, type SiteLogin } from './api'
import {
  formatDownloadError,
  formatModelBytes,
  whisperDisplayName,
  whisperModelCaption,
  type ModelDownloadsController,
} from './modelDownloads'
import { openSiteLogin, readSites } from './siteSessions'

type Step = 'welcome' | 'workflow' | 'model' | 'connect' | 'ready'
type DemoTab = 'deliver' | 'publish' | 'notes'

const STEPS: { id: Step; label: string }[] = [
  { id: 'welcome', label: '认识书桌' },
  { id: 'workflow', label: '上手演示' },
  { id: 'model', label: '转录模型' },
  { id: 'connect', label: '账号与 AI' },
  { id: 'ready', label: '启封开用' },
]

const DEMO_TABS: { id: DemoTab; label: string; badge: string }[] = [
  { id: 'deliver', label: '① 写信投递', badge: '首页信箱' },
  { id: 'publish', label: '② 添柴点火', badge: '投稿成片' },
  { id: 'notes', label: '③ 拨档整理', badge: '知识笔记' },
]

export function SetupGuide({
  settings,
  downloads,
  onSettings,
  onClose,
}: {
  settings: Settings | null
  downloads: ModelDownloadsController
  onSettings: (next: Settings) => void
  onClose: (opts?: { startCoachmarks?: boolean }) => void
}) {
  const [step, setStep] = useState<Step>('welcome')
  const [dir, setDir] = useState(1)
  const [demoTab, setDemoTab] = useState<DemoTab>('deliver')
  const [demoPaused, setDemoPaused] = useState(false)
  const [sites, setSites] = useState<SiteLogin[]>(() =>
    settings?.site_logins?.length ? mergeSites(settings.site_logins) : defaultSites,
  )
  const [model, setModel] = useState('small')
  const [modelTouched, setModelTouched] = useState(false)
  const [setAsDefault, setSetAsDefault] = useState(true)
  const [key, setKey] = useState('')
  const [modelName, setModelName] = useState(settings?.ai_model || 'deepseek-flash')
  const [notice, setNotice] = useState<{ text: string; tone?: 'info' | 'ok' | 'error' } | null>(null)
  const [leaving, setLeaving] = useState(false)
  const [busy, setBusy] = useState(false)
  const [wantCoachmarks, setWantCoachmarks] = useState(true)

  const dialog = useRef<HTMLDialogElement>(null)
  const pendingCoachmarks = useRef(false)
  const checkedEnv = useRef(false)
  const reduced = useReducedMotion()

  const index = STEPS.findIndex(item => item.id === step)
  const resources = downloads.resources
  const activeDownload = downloads.activeDownload
  const gpuCheck = resources?.checks?.find(item => item.label.includes('GPU') || item.label.includes('NVIDIA'))
  const hasGpu = Boolean(gpuCheck?.ready || settings?.gpu_ready)
  const chosen = resources?.models.find(item => item.name === model)

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    dialog.current?.showModal()
    return () => {
      dialog.current?.close()
      if (previous?.isConnected) previous.focus({ preventScroll: true })
    }
  }, [])

  useEffect(() => {
    void readSites().then(data => setSites(mergeSites(data.sites))).catch(() => {})
    void downloads.refresh()
  }, [])

  useEffect(() => {
    if (step !== 'model' || checkedEnv.current) return
    checkedEnv.current = true
    void downloads.checkEnvironment()
  }, [step, downloads])

  // Auto-select the best model before the user makes a manual choice.
  useEffect(() => {
    if (modelTouched || !resources?.models?.length) return
    if (activeDownload) {
      setModel(activeDownload.name)
      return
    }
    const preferred = hasGpu ? 'large-v3-turbo' : 'small'
    if (resources.models.some(item => item.name === preferred)) setModel(preferred)
  }, [hasGpu, activeDownload, resources?.models, modelTouched])

  // Gentle auto-advance across the 3 interactive demo scenes unless hovered or reduced motion is active.
  useEffect(() => {
    if (step !== 'workflow' || demoPaused || reduced) return
    const timer = window.setInterval(() => {
      setDemoTab(current => {
        const order: DemoTab[] = ['deliver', 'publish', 'notes']
        return order[(order.indexOf(current) + 1) % order.length]
      })
    }, 6200)
    return () => window.clearInterval(timer)
  }, [step, demoPaused, reduced])

  function close(startCoachmarks = false) {
    if (leaving) return
    pendingCoachmarks.current = startCoachmarks
    setLeaving(true)
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
      onClose({ startCoachmarks })
    }
  }

  function go(next: Step) {
    const nextIdx = STEPS.findIndex(item => item.id === next)
    setDir(nextIdx >= index ? 1 : -1)
    setNotice(null)
    setStep(next)
  }

  async function login(site: SiteLogin) {
    setBusy(true)
    setNotice(null)
    try {
      const done = await openSiteLogin(site.site, next =>
        setSites(list => list.map(item => (item.site === next.site ? next : item))),
      )
      setSites(list => list.map(item => (item.site === done.site ? done : item)))
      setNotice({
        text: done.logged_in ? `${done.platform}已登录并保存凭据` : `${done.platform}未完成登录`,
        tone: done.logged_in ? 'ok' : 'info',
      })
    } catch (error) {
      setNotice({ text: error instanceof Error ? error.message : '登录窗口没有打开', tone: 'error' })
    } finally {
      setBusy(false)
    }
  }

  async function startModelDownload(andAdvance: boolean) {
    setBusy(true)
    setNotice(null)
    try {
      await downloads.startDownload(model, { setAsDefault })
      if (andAdvance) {
        go('connect')
        setNotice({
          text: `Whisper ${whisperDisplayName(model)} 已在后台开始下载，随时可继续操作或进入书桌。`,
          tone: 'ok',
        })
      } else {
        setNotice({
          text: `Whisper ${whisperDisplayName(model)} 已转入后台下载，你现在就可以点「下一步」或关闭手册。`,
          tone: 'ok',
        })
      }
    } catch (error) {
      setNotice({ text: formatDownloadError(error) || '模型没有开始下载', tone: 'error' })
    } finally {
      setBusy(false)
    }
  }

  async function saveKey(test: boolean) {
    setBusy(true)
    setNotice(null)
    try {
      const next = await request<Settings>('/desktop/settings', 'PUT', {
        ai_model: modelName.trim() || 'deepseek-flash',
        secrets: key.trim() ? { TRANSLATE_API_KEY: key.trim() } : {},
      })
      onSettings(next)
      if (test) {
        await request('/desktop/deepseek/test', 'POST')
        setNotice({ text: 'DeepSeek 已连通，可正常翻译字幕与整理笔记', tone: 'ok' })
      } else {
        setNotice({ text: next.has_ai_key ? 'AI 密钥与模型已安全保存' : '模型名已保存（尚未填写密钥）', tone: 'ok' })
      }
    } catch (error) {
      setNotice({ text: error instanceof Error ? error.message : '没有保存成功', tone: 'error' })
    } finally {
      setBusy(false)
    }
  }

  const readyModels = (resources?.models || []).filter(item => item.available)
  const loggedInSites = sites.filter(site => site.logged_in)
  const activePct = Math.max(0, Math.min(100, Math.round(activeDownload?.download?.percent ?? 0)))

  return (
    <dialog
      ref={dialog}
      className={'onboarding' + (leaving ? ' is-leaving' : '')}
      aria-labelledby="setup-title"
      onCancel={event => {
        event.preventDefault()
        close(false)
      }}
    >
      <div
        className={'setup-book' + (step === 'ready' ? ' is-ready' : '')}
        onAnimationEnd={event => {
          if (leaving && event.target === event.currentTarget) {
            onClose({ startCoachmarks: pendingCoachmarks.current })
          }
        }}
      >
        <header className="setup-head">
          <div className="setup-head-top">
            <div>
              <h2 id="setup-title">书桌启封手册</h2>
              <p>两分钟上手双线书桌；模型可在后台静默下载，不阻塞使用。</p>
            </div>
            {activeDownload && (
              <div className="setup-bg-pill" role="status" aria-live="polite">
                <Download size={12} aria-hidden="true" />
                <span>
                  {whisperDisplayName(activeDownload.name)} 后台下载 {activePct}%
                </span>
                <b className="setup-bg-bar" aria-hidden="true">
                  <i style={{ width: `${Math.max(6, activePct)}%` }} />
                </b>
              </div>
            )}
          </div>
          <ol className="setup-stamps" aria-label="引导步骤">
            {STEPS.map((item, order) => {
              const state = order < index ? 'is-stamped' : order === index ? 'is-current' : ''
              return (
                <li key={item.id} className={state}>
                  <button
                    type="button"
                    aria-current={order === index ? 'step' : undefined}
                    onClick={() => go(item.id)}
                  >
                    <span className="stamp-num" aria-hidden="true">
                      {order < index ? <Check size={11} strokeWidth={2.6} /> : order + 1}
                    </span>
                    <span>{item.label}</span>
                  </button>
                </li>
              )
            })}
          </ol>
        </header>

        <div className="setup-stage-wrap">
          <motion.div
            key={step}
            className="setup-page"
            initial={reduced ? { opacity: 0 } : { opacity: 0, x: dir * 14 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: reduced ? 0.06 : 0.2, ease: [0.22, 1, 0.36, 1] }}
          >
              {step === 'welcome' && (
                <>
                  <div className="tour-diorama" aria-label="Media Operator 双线工作流示意图">
                    <div className="tour-lane is-publish">
                      <span className="tour-lane-tag">
                        <Flame size={12} aria-hidden="true" />
                        <span>左箱 · 投稿成片</span>
                      </span>
                      <div className="tour-lane-visual" aria-hidden="true">
                        <span className="tour-prop-stack">
                          <img className="tour-prop-img" src={asset('mailbox-light-beauty')} alt="" />
                          <img className="tour-wax-mini" src={asset('wax-light-beauty')} alt="" />
                        </span>
                        <span className="tour-flow-arrow">
                          <i />
                        </span>
                        <img className="tour-prop-img" src={asset('brazier-light-beauty')} alt="" />
                        <span className="tour-flow-arrow">
                          <i />
                        </span>
                        <img className="tour-prop-img is-tv" src={asset('desk-tv-frame')} alt="" />
                      </div>
                      <p>链接 / 本地视频 → 自动转录与翻译 → 压制双语成片或直接投稿 B 站</p>
                    </div>

                    <div className="tour-lane is-notes">
                      <span className="tour-lane-tag">
                        <FileText size={12} aria-hidden="true" />
                        <span>右箱 · 知识笔记</span>
                      </span>
                      <div className="tour-lane-visual" aria-hidden="true">
                        <span className="tour-prop-stack">
                          <img className="tour-prop-img" src={asset('mailbox-light-beauty')} alt="" />
                          <img className="tour-wax-mini" src={asset('wax-blue-light-beauty')} alt="" />
                        </span>
                        <span className="tour-flow-arrow">
                          <i />
                        </span>
                        <img className="tour-prop-img" src={asset('shredder-light-beauty')} alt="" />
                        <span className="tour-flow-arrow">
                          <i />
                        </span>
                        <span className="tour-card-stack">
                          <b />
                          <b />
                          <b />
                        </span>
                      </div>
                      <p>音视频 / 图文 / 本地电子书（txt · epub · mobi · azw3 · pdf）→ 提炼摘要与观点 → 写入 Obsidian</p>
                    </div>

                    <div className="tour-reuse-ribbon">
                      <Layers size={13} aria-hidden="true" />
                      <span>同一条素材先后投进左右信箱时，已下载音视频与转录结果会自动复用，不重复耗时</span>
                    </div>
                  </div>

                  <div className="tour-pillars">
                    <div>
                      <strong>
                        <Inbox size={14} aria-hidden="true" /> 多源直接投递
                      </strong>
                      <small>支持 YouTube、B 站、抖音、小红书、小宇宙、微信读书与本地音视频/字幕/图书。</small>
                    </div>
                    <div>
                      <strong>
                        <ShieldCheck size={14} aria-hidden="true" /> 本地优先保存
                      </strong>
                      <small>Whisper 离线转录，所有账号与 API 密钥仅存于本机 Windows 凭据管理器。</small>
                    </div>
                    <div>
                      <strong>
                        <Sparkles size={14} aria-hidden="true" /> 零阻塞随时开用
                      </strong>
                      <small>模型支持后台静默下载，账号与密钥随时可后补，现在即可逛完书桌。</small>
                    </div>
                  </div>

                  <div className="setup-actions-bar">
                    <button type="button" className="setup-next" onClick={() => go('workflow')}>
                      <span>看 3 步动态演示</span>
                      <ArrowRight size={14} aria-hidden="true" />
                    </button>
                    <button type="button" className="text-action" onClick={() => go('model')}>
                      直接去下模型
                    </button>
                  </div>
                </>
              )}

              {step === 'workflow' && (
                <>
                  <div
                    className="demo-tabs"
                    role="tablist"
                    aria-label="操作演示场景"
                    onMouseEnter={() => setDemoPaused(true)}
                    onMouseLeave={() => setDemoPaused(false)}
                  >
                    {DEMO_TABS.map(tab => (
                      <button
                        key={tab.id}
                        type="button"
                        role="tab"
                        aria-selected={demoTab === tab.id}
                        className={demoTab === tab.id ? 'is-active' : ''}
                        onClick={() => {
                          setDemoPaused(true)
                          setDemoTab(tab.id)
                        }}
                      >
                        <strong>{tab.label}</strong>
                        <small>{tab.badge}</small>
                      </button>
                    ))}
                  </div>

                  <div
                    className="demo-viewport"
                    onMouseEnter={() => setDemoPaused(true)}
                    onMouseLeave={() => setDemoPaused(false)}
                  >
                    <motion.div
                      key={demoTab}
                      className="demo-card"
                      initial={reduced ? { opacity: 0 } : { opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: reduced ? 0.06 : 0.18, ease: [0.22, 1, 0.36, 1] }}
                    >
                        {demoTab === 'deliver' && (
                          <>
                            <div className="demo-stage is-deliver" aria-hidden="true">
                              <img className="demo-mailbox-art" src={asset('mailbox-light-beauty')} alt="" />
                              <div className="demo-paper-sheet">
                                <span className="demo-ink-line l1" />
                                <span className="demo-ink-line l2" />
                                <span className="demo-ink-line l3" />
                              </div>
                              <div className="demo-env-flight">
                                <img src={asset('envelope-light-closed')} alt="" />
                              </div>
                              <div className="demo-wax-pulse">
                                <img src={asset('wax-light-beauty')} alt="" />
                              </div>
                            </div>
                            <div className="demo-copy">
                              <h3>像写信一样批量投递灵感</h3>
                              <ol>
                                <li>把分享文案、链接或本地文件路径粘贴进信纸，<strong>一行一条</strong>；也可点「选本地文件」或直接把音视频与图书拖进信纸。</li>
                                <li>右下角折角可翻页批量填写多条；点下方<strong>火漆印</strong>（或按 <kbd>Ctrl</kbd>+<kbd>Enter</kbd>）即刻投递。</li>
                                <li>若某行链接无法识别，系统会撕下退回纸条留在信箱下方，点<strong>「恢复编辑」</strong>即可修改重投。</li>
                              </ol>
                            </div>
                          </>
                        )}

                        {demoTab === 'publish' && (
                          <>
                            <div className="demo-stage is-publish" aria-hidden="true">
                              <div className="demo-hearth-scene">
                                <i className="demo-ember-glow" />
                                <img className="demo-brazier-art" src={asset('brazier-light-beauty')} alt="" />
                                <img className="demo-wood-log w1" src={asset('wood-0-light-beauty')} alt="" />
                                <img className="demo-wood-log w2" src={asset('wood-1-light-beauty')} alt="" />
                                <img className="demo-wood-log w3" src={asset('wood-2-light-beauty')} alt="" />
                                <img className="demo-wood-log w4" src={asset('wood-3-light-beauty')} alt="" />
                              </div>
                              <div className="demo-tv-mini">
                                <div className="demo-tv-glow">双语成片</div>
                                <img src={asset('desk-tv-frame')} alt="" />
                              </div>
                            </div>
                            <div className="demo-copy">
                              <h3>四块木柴备齐参数，点火即出成片</h3>
                              <ol>
                                <li>切到左侧<strong>「投稿」</strong>页，点击火盆下方的 4 块木柴（输出、字幕样式、投稿信息、翻译上下文）按需微调。</li>
                                <li>沿用默认参数时，直接点<strong>「使用当前设置备齐」</strong>，四块木柴会依次落入火盆。</li>
                                <li>点<strong>「开始处理」</strong>确认点火；完成后在右侧复古电视直接放映，并支持打开成片目录或导出 SRT 字幕。</li>
                              </ol>
                            </div>
                          </>
                        )}

                        {demoTab === 'notes' && (
                          <>
                            <div className="demo-stage is-notes" aria-hidden="true">
                              <div className="demo-shred-scene">
                                <div className="demo-shred-paper" />
                                <img className="demo-shredder-art" src={asset('shredder-light-beauty')} alt="" />
                                <div className="demo-lever-mini">
                                  <i className="demo-lever-thumb" />
                                  <span>摘要</span>
                                  <span>核心</span>
                                  <span>详尽</span>
                                </div>
                              </div>
                              <div className="demo-tree-preview">
                                <div className="demo-tree-root">全篇主旨总览</div>
                                <div className="demo-tree-branch">
                                  <span>核心脉络 · 观点卡</span>
                                  <em>02:14 跳原文</em>
                                </div>
                                <div className="demo-tree-branch is-alt">
                                  <span>启发性事实 · 方法</span>
                                  <em>写 Obsidian</em>
                                </div>
                              </div>
                            </div>
                            <div className="demo-copy">
                              <h3>拨动碎纸机三档，一次衍生全部视图</h3>
                              <ol>
                                <li>切到左侧<strong>「笔记」</strong>页，在碎纸机下方拨动档位（摘要 / 核心观点 / 大多数观点）并点击<strong>「开始整理」</strong>。</li>
                                <li>整理后可在右侧自由切换三份视图，点击时间戳徽章即可直跳「原文」并联动视音频播控。</li>
                                <li>在「设置 → Obsidian」分别绑定摘要库与观点库后，可一键写入树状笔记与语义卡片。</li>
                              </ol>
                            </div>
                          </>
                        )}
                      </motion.div>
                  </div>

                  <div className="setup-actions-bar">
                    <button type="button" className="setup-next" onClick={() => go('model')}>
                      <span>下一步：准备转录模型</span>
                      <ArrowRight size={14} aria-hidden="true" />
                    </button>
                    <span className="setup-subtle-tip">悬停在演示区可暂停自动切换</span>
                  </div>
                </>
              )}

              {step === 'model' && (
                <>
                  <div className="setup-env-banner">
                    <span className="setup-env-icon" aria-hidden="true">
                      <Cpu size={15} />
                    </span>
                    <div>
                      <strong>
                        {gpuCheck
                          ? gpuCheck.ready
                            ? '已检测到 NVIDIA GPU，支持高速显卡转录'
                            : '未检测到可用 GPU，将使用 CPU 离线转录'
                          : downloads.checking
                            ? '正在检测本机硬件与可用磁盘空间…'
                            : '离线语音转录模型（下载在后台进行，绝不阻塞）'}
                      </strong>
                      <small>
                        {hasGpu ? '推荐选择 large-v3-turbo（高精度快版）或 small（轻快均衡）' : '推荐选择 small（速度与准确度均衡）或 base（最快体验）'}
                        {resources?.free_bytes !== undefined
                          ? ` · 资料盘剩余 ${(resources.free_bytes / 1e9).toFixed(1)} GB`
                          : ''}
                      </small>
                    </div>
                  </div>

                  <div className="setup-models" role="radiogroup" aria-label="模型大小">
                    {(resources?.models || []).map(item => {
                      const meta = whisperModelCaption(item.name, hasGpu)
                      const isSelected = model === item.name
                      const isItemRunning = Boolean(item.download?.running)
                      return (
                        <button
                          key={item.name}
                          type="button"
                          role="radio"
                          aria-checked={isSelected}
                          className={
                            'setup-model-card'
                            + (isSelected ? ' is-set' : '')
                            + (item.available ? ' is-ready' : '')
                            + (isItemRunning ? ' is-downloading' : '')
                          }
                          onClick={() => {
                            setModelTouched(true)
                            setModel(item.name)
                          }}
                        >
                          <div className="setup-model-top">
                            <strong>{whisperDisplayName(item.name)}</strong>
                            <span className={'setup-model-tag' + (meta.recommended ? ' is-rec' : '')}>
                              {item.available ? '已就绪' : isItemRunning ? `${item.download.percent ?? 0}%` : meta.tag}
                            </span>
                          </div>
                          <small className="setup-model-size">{formatModelBytes(item.size)}</small>
                          <span className="setup-model-desc">{meta.detail}</span>
                        </button>
                      )
                    })}
                  </div>

                  <label className="check setup-default-check">
                    <input
                      type="checkbox"
                      checked={setAsDefault}
                      onChange={event => setSetAsDefault(event.target.checked)}
                    />
                    <span>下载所选模型后，同时设为投稿与笔记的默认转录模型</span>
                  </label>

                  {activeDownload && (
                    <div className="setup-dl-live" role="status" aria-live="polite">
                      <div className="setup-dl-live-head">
                        <strong>
                          正在后台下载 Whisper {whisperDisplayName(activeDownload.name)} · {activePct}%
                        </strong>
                        <span>
                          {activeDownload.download?.downloaded_bytes && activeDownload.download?.total_bytes
                            ? `${formatModelBytes(activeDownload.download.downloaded_bytes)} / ${formatModelBytes(activeDownload.download.total_bytes)}`
                            : activeDownload.download?.message || '连接中…'}
                        </span>
                      </div>
                      <div className="setup-dl-track" aria-hidden="true">
                        <i style={{ width: `${Math.max(4, activePct)}%` }} />
                      </div>
                      <small>无需停留等待——你可以直接点「下一步」继续浏览，或立即关闭手册进入 App，右下角会持续显示进度。</small>
                    </div>
                  )}

                  {!activeDownload && chosen?.available && (
                    <p className="setup-ok-line">
                      <CheckCircle2 size={14} aria-hidden="true" />
                      <span>Whisper {whisperDisplayName(chosen.name)} 已核验就绪，可直接离线转录。</span>
                    </p>
                  )}

                  <div className="setup-actions-bar">
                    {activeDownload ? (
                      <button type="button" className="setup-next" onClick={() => go('connect')}>
                        <span>后台下载中，继续下一步</span>
                        <ArrowRight size={14} aria-hidden="true" />
                      </button>
                    ) : chosen?.available ? (
                      <button type="button" className="setup-next" onClick={() => go('connect')}>
                        <span>模型已就绪，下一步</span>
                        <ArrowRight size={14} aria-hidden="true" />
                      </button>
                    ) : (
                      <>
                        <button
                          type="button"
                          className="setup-next"
                          disabled={busy || !chosen}
                          onClick={() => void startModelDownload(true)}
                        >
                          <Download size={14} aria-hidden="true" />
                          <span>{busy ? '正在启动…' : '后台下载并继续'}</span>
                        </button>
                        <button
                          type="button"
                          className="setup-secondary"
                          disabled={busy || !chosen}
                          onClick={() => void startModelDownload(false)}
                        >
                          仅开始后台下载
                        </button>
                        <button type="button" className="text-action" onClick={() => go('connect')}>
                          暂不下载，下一步
                        </button>
                      </>
                    )}
                  </div>
                </>
              )}

              {step === 'connect' && (
                <>
                  <div className="setup-connect-grid">
                    <section className="setup-connect-card">
                      <header>
                        <h3>平台账号（按需登录）</h3>
                        <p>YouTube 与本地文件免登录即可用；以下平台可按需登录，也可随时跳过。</p>
                      </header>
                      <ul className="setup-accounts">
                        {sites.map(site => (
                          <li key={site.site}>
                            <SiteMark site={site.site} />
                            <span className="setup-site-name">{site.platform}</span>
                            <em className={site.logged_in ? 'is-stamped' : 'is-skipped'}>
                              {site.logging_in ? '正在登录' : site.logged_in ? '已登录' : '未登录'}
                            </em>
                            {!site.logged_in && (
                              <button
                                type="button"
                                className="setup-mini-btn"
                                disabled={busy || site.logging_in}
                                onClick={() => void login(site)}
                              >
                                登录
                              </button>
                            )}
                          </li>
                        ))}
                      </ul>
                    </section>

                    <section className="setup-connect-card">
                      <header>
                        <h3>
                          <KeyRound size={14} aria-hidden="true" /> DeepSeek / AI 密钥（可选）
                        </h3>
                        <p>用于双语字幕翻译与 AI 摘要观点整理，仅保存在 Windows 凭据管理器。</p>
                      </header>
                      <div className="setup-key-form">
                        <label>
                          模型名称
                          <input
                            value={modelName}
                            onChange={event => setModelName(event.target.value)}
                            placeholder="deepseek-flash"
                          />
                        </label>
                        <label>
                          API Key
                          <input
                            type="password"
                            value={key}
                            autoComplete="off"
                            placeholder={settings?.has_ai_key ? '已保存，留空则保留原密钥' : '粘贴 sk-... 密钥'}
                            onChange={event => setKey(event.target.value)}
                          />
                        </label>
                        <div className="toolbar">
                          <button
                            type="button"
                            className="setup-secondary"
                            disabled={busy}
                            onClick={() => void saveKey(false)}
                          >
                            保存密钥
                          </button>
                          <button
                            type="button"
                            className="setup-secondary"
                            disabled={busy || !(key.trim() || settings?.has_ai_key)}
                            onClick={() => void saveKey(true)}
                          >
                            测试连接
                          </button>
                        </div>
                      </div>
                    </section>
                  </div>

                  <div className="setup-actions-bar">
                    <button type="button" className="setup-next" onClick={() => go('ready')}>
                      <span>下一步：启封开用</span>
                      <ArrowRight size={14} aria-hidden="true" />
                    </button>
                    <span className="setup-subtle-tip">以上配置均可稍后在「设置」中随时修改</span>
                  </div>
                </>
              )}

              {step === 'ready' && (
                <>
                  <h3>书桌已就绪，欢迎开始创作与整理</h3>
                  <ul className="setup-ready">
                    <li className={readyModels.length > 0 ? 'is-stamped' : activeDownload ? 'is-running' : ''}>
                      <strong>转录模型：</strong>
                      <span>
                        {readyModels.length > 0
                          ? `已就绪（${readyModels.map(item => whisperDisplayName(item.name)).join('、')}）`
                          : activeDownload
                            ? `正在后台下载 Whisper ${whisperDisplayName(activeDownload.name)}（${activePct}%），进入书桌后右下角继续展示`
                            : '暂未下载，稍后可随时在「设置 → 转录与本地资源」获取'}
                      </span>
                    </li>
                    <li className={loggedInSites.length > 0 ? 'is-stamped' : ''}>
                      <strong>站点账号：</strong>
                      <span>
                        {loggedInSites.length > 0
                          ? loggedInSites.map(site => site.platform).join('、')
                          : '暂未登录（YouTube 与本地音视频/字幕可直接投递）'}
                      </span>
                    </li>
                    <li className={settings?.has_ai_key ? 'is-stamped' : ''}>
                      <strong>DeepSeek AI：</strong>
                      <span>{settings?.has_ai_key ? `已配置（${settings.ai_model || modelName}）` : '暂未配置（稍后可在「设置 → DeepSeek」填写）'}</span>
                    </li>
                  </ul>

                  <div className="setup-shortcuts-box">
                    <div className="setup-shortcuts-title">
                      <Keyboard size={14} aria-hidden="true" />
                      <span>书桌常用快捷键</span>
                    </div>
                    <div className="setup-shortcuts-list">
                      <span><kbd>Ctrl</kbd>+<kbd>1–4</kbd> 切换信箱 / 投稿 / 笔记 / 设置</span>
                      <span><kbd>Ctrl</kbd>+<kbd>K</kbd> 或 <kbd>/</kbd> 聚焦输入与搜索</span>
                      <span><kbd>Ctrl</kbd>+<kbd>Enter</kbd> 投递当前信件</span>
                      <span><kbd>Space</kbd> 播放 / 暂停视音频</span>
                    </div>
                  </div>

                  <label className="check setup-coachmark-opt">
                    <input
                      type="checkbox"
                      checked={wantCoachmarks}
                      onChange={event => setWantCoachmarks(event.target.checked)}
                    />
                    <span>合上手册后，在首页开启 3 步实景气泡指引（随时可按 Esc 跳过）</span>
                  </label>

                  <div className="setup-actions-bar">
                    <button type="button" className="setup-next" onClick={() => close(wantCoachmarks)}>
                      <span>合上手册，开始使用</span>
                      <ArrowRight size={14} aria-hidden="true" />
                    </button>
                  </div>
                </>
              )}
          </motion.div>
        </div>

        {notice && (
          <p className={'setup-slip' + (notice.tone ? ' is-' + notice.tone : '')} role="status">
            {notice.text}
          </p>
        )}

        <footer className="setup-foot">
          <div className="setup-foot-left">
            {index > 0 && (
              <button
                type="button"
                className="text-action setup-prev-btn"
                onClick={() => go(STEPS[index - 1].id)}
              >
                <ArrowLeft size={13} aria-hidden="true" />
                <span>上一页</span>
              </button>
            )}
          </div>
          <button type="button" className="text-action" onClick={() => close(false)}>
            以后再说
          </button>
        </footer>
      </div>
    </dialog>
  )
}
