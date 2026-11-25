import { AlertCircle, CheckCircle2, ChevronDown, ChevronUp, Download, RefreshCw, X } from 'lucide-react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { useState } from 'react'
import { formatModelBytes, whisperDisplayName, type ModelDownloadsController } from './modelDownloads'

export function BackgroundModelBanner({
  controller,
  hidden,
  onOpenResources,
}: {
  controller: ModelDownloadsController
  hidden?: boolean
  onOpenResources: () => void
}) {
  const [collapsed, setCollapsed] = useState(false)
  const [retrying, setRetrying] = useState(false)
  const reduced = useReducedMotion()
  const { activeDownload, notice, startDownload, dismissNotice } = controller

  const visible = !hidden && Boolean(activeDownload || notice)
  const percent = Math.max(0, Math.min(100, Math.round(activeDownload?.download?.percent ?? 0)))
  const downloaded = activeDownload?.download?.downloaded_bytes ?? 0
  const total = activeDownload?.download?.total_bytes ?? activeDownload?.size ?? 0

  async function retry(name: string) {
    setRetrying(true)
    try {
      await startDownload(name)
    } catch {
      /* notice already updated on next poll or controller */
    } finally {
      setRetrying(false)
    }
  }

  return (
    <AnimatePresence>
      {visible && (
        <motion.aside
          key={activeDownload ? 'dl-' + activeDownload.name : 'notice-' + (notice?.model || 'msg')}
          className={
            'bg-model-banner'
            + (collapsed && activeDownload ? ' is-collapsed' : '')
            + (!activeDownload && notice?.kind === 'done' ? ' is-done' : '')
            + (!activeDownload && notice?.kind === 'error' ? ' is-error' : '')
          }
          role={!activeDownload && notice?.kind === 'error' ? 'alert' : 'status'}
          aria-live="polite"
          aria-label="后台模型下载状态"
          initial={reduced ? { opacity: 0 } : { opacity: 0, y: 14, scale: 0.97 }}
          animate={reduced ? { opacity: 1 } : { opacity: 1, y: 0, scale: 1 }}
          exit={reduced ? { opacity: 0 } : { opacity: 0, y: 10, scale: 0.97 }}
          transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
        >
          {activeDownload ? (
            collapsed ? (
              <div className="bg-model-pill">
                <span className="bg-model-spin" aria-hidden="true"><Download size={13} /></span>
                <strong>{whisperDisplayName(activeDownload.name)}</strong>
                <span className="bg-model-pct">{percent}%</span>
                <button
                  type="button"
                  className="bg-model-icon-btn"
                  aria-label="展开后台下载详情"
                  onClick={() => setCollapsed(false)}
                >
                  <ChevronUp size={14} />
                </button>
              </div>
            ) : (
              <>
                <header className="bg-model-head">
                  <span className="bg-model-badge">
                    <Download size={13} aria-hidden="true" />
                    <span>后台下载模型</span>
                  </span>
                  <strong>Whisper {whisperDisplayName(activeDownload.name)}</strong>
                  <span className="bg-model-pct">{percent}%</span>
                  <button
                    type="button"
                    className="bg-model-icon-btn"
                    aria-label="收起后台下载浮卡"
                    onClick={() => setCollapsed(true)}
                  >
                    <ChevronDown size={14} />
                  </button>
                </header>
                <div className="bg-model-track" aria-hidden="true">
                  <i style={{ width: `${Math.max(4, percent)}%` }} />
                </div>
                <footer className="bg-model-foot">
                  <span>
                    {activeDownload.download?.message || `正在后台下载 · ${percent}%`}
                    {downloaded > 0 && total > 0 ? `（${formatModelBytes(downloaded)} / ${formatModelBytes(total)}）` : ''}
                  </span>
                  <button type="button" className="bg-model-link" onClick={onOpenResources}>查看资源</button>
                </footer>
              </>
            )
          ) : notice ? (
            <div className="bg-model-notice">
              <span className="bg-model-notice-icon" aria-hidden="true">
                {notice.kind === 'done' ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
              </span>
              <div className="bg-model-notice-body">
                <strong>{notice.kind === 'done' ? '转录模型已就绪' : '后台下载暂停'}</strong>
                <p>{notice.text}</p>
              </div>
              <div className="bg-model-notice-actions">
                {notice.kind === 'error' && (
                  <button
                    type="button"
                    className="bg-model-retry"
                    disabled={retrying}
                    onClick={() => void retry(notice.model)}
                  >
                    <RefreshCw size={12} aria-hidden="true" />
                    <span>{retrying ? '重试中' : '重试'}</span>
                  </button>
                )}
                <button
                  type="button"
                  className="bg-model-icon-btn"
                  aria-label="关闭模型状态提示"
                  onClick={dismissNotice}
                >
                  <X size={14} />
                </button>
              </div>
            </div>
          ) : null}
        </motion.aside>
      )}
    </AnimatePresence>
  )
}
