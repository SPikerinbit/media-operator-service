import { ArrowLeft, ArrowRight, Sparkles, X } from 'lucide-react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

type TourStop = {
  id: string
  selector: string
  title: string
  body: string
  hint: string
  prefer: 'right' | 'top' | 'bottom'
}

const STOPS: TourStop[] = [
  {
    id: 'paper',
    selector: '[data-tour="paper"]',
    title: '第一步 · 写下链接或拖入本地文件',
    body: '直接粘贴 YouTube、B 站、抖音、小红书、小宇宙或微信读书分享文案，一行一条；也可以直接填入/拖入本地音视频、字幕或图书（txt / epub / mobi / azw3 / pdf 等）路径，右下角翻页可批量填写。',
    hint: '快捷键 Ctrl + K 或 / 可随时回到信纸输入',
    prefer: 'right',
  },
  {
    id: 'wax',
    selector: '[data-tour="wax"]',
    title: '第二步 · 盖下火漆印即刻投递',
    body: '点击这枚火漆印（或按 Ctrl + Enter），信纸会折入信封投进信箱。左箱送往「投稿」做字幕与成片，右箱送往「笔记」提炼多层级摘要与观点。',
    hint: '同一素材在两边投递会自动复用，不重复下载与转录',
    prefer: 'top',
  },
  {
    id: 'nav',
    selector: '.sidebar nav',
    title: '第三步 · 在工作台点火或拨档整理',
    body: '信件投递后切换到左侧「投稿」添柴点火，或进入「笔记」拨动碎纸机三档开始整理；随时可点击左下角「教程」重温指南。',
    hint: '快捷键 Ctrl + 1～4 可快速切换四个工作台',
    prefer: 'right',
  },
]

type Box = { left: number; top: number; width: number; height: number }
type CardPos = { left: number; top: number; side: 'left' | 'right' | 'top' | 'bottom' }

function computeCardPosition(target: Box, prefer: TourStop['prefer'], cardW: number, cardH: number): CardPos {
  const margin = 16
  const gap = 16
  const vw = window.innerWidth
  const vh = window.innerHeight
  const clampX = (x: number) => Math.max(margin, Math.min(vw - cardW - margin, x))
  const clampY = (y: number) => Math.max(margin, Math.min(vh - cardH - margin, y))

  const fitsRight = target.left + target.width + gap + cardW + margin <= vw
  const fitsLeft = target.left - gap - cardW - margin >= 0
  const fitsTop = target.top - gap - cardH - margin >= 0
  const fitsBottom = target.top + target.height + gap + cardH + margin <= vh

  let side: CardPos['side'] = 'right'
  let left = margin
  let top = margin

  if (prefer === 'right' && fitsRight) {
    side = 'right'
    left = target.left + target.width + gap
    top = clampY(target.top + target.height / 2 - cardH / 2)
  } else if (prefer === 'top' && fitsTop) {
    side = 'top'
    left = clampX(target.left + target.width / 2 - cardW / 2)
    top = target.top - gap - cardH
  } else if (fitsRight) {
    side = 'right'
    left = target.left + target.width + gap
    top = clampY(target.top + target.height / 2 - cardH / 2)
  } else if (fitsLeft) {
    side = 'left'
    left = target.left - gap - cardW
    top = clampY(target.top + target.height / 2 - cardH / 2)
  } else if (fitsBottom) {
    side = 'bottom'
    left = clampX(target.left + target.width / 2 - cardW / 2)
    top = target.top + target.height + gap
  } else {
    side = 'top'
    left = clampX(target.left + target.width / 2 - cardW / 2)
    top = clampY(target.top - gap - cardH)
  }
  return { left: Math.round(left), top: Math.round(top), side }
}

export function DeskCoachmarks({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const [index, setIndex] = useState(0)
  const [layout, setLayout] = useState<{ target: Box; card: CardPos } | null>(null)
  const cardRef = useRef<HTMLDivElement>(null)
  const reduced = useReducedMotion()
  const stop = STOPS[Math.min(index, STOPS.length - 1)]

  useEffect(() => {
    if (open) setIndex(0)
    else setLayout(null)
  }, [open])

  const measure = useCallback(() => {
    if (!open) return
    const node = document.querySelector<HTMLElement>(stop.selector)
    if (!node) {
      setLayout(null)
      return
    }
    const rect = node.getBoundingClientRect()
    if (rect.width < 2 || rect.height < 2) {
      setLayout(null)
      return
    }
    const pad = stop.id === 'wax' ? 10 : 8
    const target: Box = {
      left: Math.max(6, rect.left - pad),
      top: Math.max(6, rect.top - pad),
      width: Math.min(window.innerWidth - 12, rect.width + pad * 2),
      height: Math.min(window.innerHeight - 12, rect.height + pad * 2),
    }
    const cardW = cardRef.current?.offsetWidth || Math.min(332, window.innerWidth - 32)
    const cardH = cardRef.current?.offsetHeight || 214
    const card = computeCardPosition(target, stop.prefer, cardW, cardH)
    setLayout({ target, card })
  }, [open, stop.id, stop.prefer, stop.selector])

  useLayoutEffect(() => {
    if (!open) return
    measure()
    const raf = requestAnimationFrame(measure)
    window.addEventListener('resize', measure)
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', measure)
    }
  }, [open, index, measure])

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
      } else if (event.key === 'ArrowRight') {
        event.preventDefault()
        if (index < STOPS.length - 1) setIndex(i => i + 1)
        else onClose()
      } else if (event.key === 'ArrowLeft' && index > 0) {
        event.preventDefault()
        setIndex(i => i - 1)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, index, onClose])

  return (
    <AnimatePresence>
      {open && layout && (
        <motion.div
          className="coachmark-layer"
          role="dialog"
          aria-modal="false"
          aria-label="书桌实景导览"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
        >
          <div className="coachmark-backdrop-hit" onClick={onClose} aria-hidden="true" />
          <motion.div
            className="coachmark-spotlight"
            aria-hidden="true"
            initial={layout.target}
            animate={layout.target}
            transition={reduced ? { duration: 0 } : { type: 'spring', stiffness: 320, damping: 30 }}
          />
          <motion.div
            ref={cardRef}
            className={'coachmark-card is-' + layout.card.side}
            initial={
              reduced
                ? { opacity: 0, left: layout.card.left, top: layout.card.top }
                : { opacity: 0, scale: 0.96, left: layout.card.left, top: layout.card.top + 8 }
            }
            animate={{
              opacity: 1,
              scale: 1,
              left: layout.card.left,
              top: layout.card.top,
            }}
            exit={reduced ? { opacity: 0 } : { opacity: 0, scale: 0.96 }}
            transition={reduced ? { duration: 0.08 } : { type: 'spring', stiffness: 320, damping: 28 }}
          >
            <header className="coachmark-head">
              <span className="coachmark-step">
                <Sparkles size={13} aria-hidden="true" />
                <span>实景指引 {index + 1} / {STOPS.length}</span>
              </span>
              <button type="button" className="coachmark-close" aria-label="关闭实景指引" onClick={onClose}>
                <X size={14} />
              </button>
            </header>
            <motion.div
              key={stop.id}
              className="coachmark-body"
              initial={reduced ? { opacity: 0 } : { opacity: 0, x: 8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.16, ease: [0.22, 1, 0.36, 1] }}
            >
              <h3>{stop.title}</h3>
              <p>{stop.body}</p>
              <small className="coachmark-hint">{stop.hint}</small>
            </motion.div>
            <footer className="coachmark-foot">
              <button type="button" className="text-action" onClick={onClose}>跳过指引</button>
              <div className="coachmark-actions">
                {index > 0 && (
                  <button type="button" className="coachmark-btn is-ghost" onClick={() => setIndex(i => i - 1)}>
                    <ArrowLeft size={13} aria-hidden="true" />
                    <span>上一步</span>
                  </button>
                )}
                {index < STOPS.length - 1 ? (
                  <button type="button" className="coachmark-btn is-primary" onClick={() => setIndex(i => i + 1)}>
                    <span>下一步</span>
                    <ArrowRight size={13} aria-hidden="true" />
                  </button>
                ) : (
                  <button type="button" className="coachmark-btn is-primary" onClick={onClose}>
                    <span>知道了，开始用</span>
                  </button>
                )}
              </div>
            </footer>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
