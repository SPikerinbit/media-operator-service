import { useCallback, useEffect, useRef, useState } from 'react'
import { errorMessage, request, type LocalModel, type LocalResources } from './api'
import { outputDefaults, savedVideoOptions, type VideoDefaults } from './videoOptions'

export const MODEL_DOWNLOAD_EVENT = 'model-download-changed'

export function notifyModelDownloadChanged() {
  window.dispatchEvent(new CustomEvent(MODEL_DOWNLOAD_EVENT))
}

export function formatModelBytes(bytes: number) {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 MB'
  if (bytes >= 1e9) return (bytes / 1e9).toFixed(bytes >= 10e9 ? 0 : 1) + ' GB'
  return Math.max(1, Math.round(bytes / 1e6)) + ' MB'
}

export function whisperDisplayName(name: string) {
  return name.replace(/\s*\d+(?:\.\d+)?\s*G(?:B)?$/i, '').trim() || name
}

export function whisperModelCaption(name: string, hasGpu: boolean): { tag: string; detail: string; recommended: boolean } {
  switch (name) {
    case 'base':
      return { tag: '轻快尝鲜', detail: '体积最小、下载最快，适合先快速体验流程', recommended: false }
    case 'small':
      return {
        tag: hasGpu ? '均衡轻量' : 'CPU 推荐',
        detail: '速度与中文/英文准确度平衡，入门最省心',
        recommended: !hasGpu,
      }
    case 'medium':
      return { tag: '进阶准确', detail: '适合长视频与口音较复杂的外语内容', recommended: false }
    case 'large-v3-turbo':
      return {
        tag: hasGpu ? 'GPU 推荐' : '高精度快版',
        detail: '接近最高精度但速度更快，配备 NVIDIA 显卡首选',
        recommended: hasGpu,
      }
    case 'large-v3':
      return { tag: '旗舰精度', detail: '完整大模型，适合显存充裕时追求极致准确度', recommended: false }
    default:
      return { tag: '本地模型', detail: '离线语音转录模型', recommended: false }
  }
}

export type ModelDownloadNotice = {
  kind: 'done' | 'error'
  model: string
  text: string
}

export type ModelDownloadsController = {
  resources: LocalResources | null
  activeDownload: LocalModel | null
  notice: ModelDownloadNotice | null
  checking: boolean
  refresh: () => Promise<LocalResources | null>
  checkEnvironment: () => Promise<LocalResources | null>
  startDownload: (name: string, opts?: { setAsDefault?: boolean }) => Promise<LocalResources>
  dismissNotice: () => void
}

export function useModelDownloads(): ModelDownloadsController {
  const [resources, setResources] = useState<LocalResources | null>(null)
  const [notice, setNotice] = useState<ModelDownloadNotice | null>(null)
  const [checking, setChecking] = useState(false)
  const trackedRef = useRef<string>('')
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  const mergeResources = useCallback((next: LocalResources) => {
    setResources(current => ({
      ...current,
      ...next,
      models: next.models?.length ? next.models : current?.models || [],
      checks: next.checks ?? current?.checks,
      free_bytes: next.free_bytes ?? current?.free_bytes,
      proxy: next.proxy ?? current?.proxy,
      storage: next.storage ?? current?.storage,
    }))
    const running = next.models?.find(item => item.download?.running)
    if (running) {
      trackedRef.current = running.name
      setNotice(prev => prev?.model === running.name && prev.kind === 'error' ? null : prev)
      return
    }
    const prevName = trackedRef.current
    if (!prevName) return
    const finished = next.models?.find(item => item.name === prevName)
    if (!finished) return
    trackedRef.current = ''
    if (finished.available) {
      const text = `Whisper ${whisperDisplayName(finished.name)} 已在后台下载并核验完成，可直接离线转录`
      setNotice({ kind: 'done', model: finished.name, text })
      void window.pywebview?.api?.notify_complete?.('转录模型已就绪', text)?.catch(() => {})
    } else if (finished.download?.failed || finished.download?.message?.includes('失败')) {
      setNotice({
        kind: 'error',
        model: finished.name,
        text: finished.download?.message || `Whisper ${whisperDisplayName(finished.name)} 下载失败，请检查网络后重试。`,
      })
    }
  }, [])

  const refresh = useCallback(async () => {
    try {
      const next = await request<LocalResources>('/desktop/resources')
      if (mountedRef.current) mergeResources(next)
      return next
    } catch {
      return null
    }
  }, [mergeResources])

  const checkEnvironment = useCallback(async () => {
    setChecking(true)
    try {
      const next = await request<LocalResources>('/desktop/resources/check')
      if (mountedRef.current) mergeResources(next)
      return next
    } catch {
      return null
    } finally {
      if (mountedRef.current) setChecking(false)
    }
  }, [mergeResources])

  const startDownload = useCallback(async (name: string, opts?: { setAsDefault?: boolean }) => {
    setNotice(prev => prev?.model === name ? null : prev)
    trackedRef.current = name
    const next = await request<LocalResources>('/desktop/resources/models/' + encodeURIComponent(name), 'POST')
    if (mountedRef.current) mergeResources(next)
    notifyModelDownloadChanged()
    if (opts?.setAsDefault) {
      void request<VideoDefaults>('/desktop/video-defaults')
        .then(defaults => {
          const merged = outputDefaults({ ...savedVideoOptions(defaults), whisper_model: name })
          return request<VideoDefaults>('/desktop/video-defaults', 'PUT', { output: merged })
        })
        .then(() => { window.dispatchEvent(new Event('video-defaults-changed')) })
        .catch(() => {})
    }
    return next
  }, [mergeResources])

  const activeDownload = resources?.models.find(item => item.download?.running) ?? null
  const isDownloading = Boolean(activeDownload)

  useEffect(() => {
    void refresh()
    const onChanged = () => { void refresh() }
    window.addEventListener(MODEL_DOWNLOAD_EVENT, onChanged)
    return () => window.removeEventListener(MODEL_DOWNLOAD_EVENT, onChanged)
  }, [refresh])

  useEffect(() => {
    if (!isDownloading) return
    const timer = window.setInterval(() => { void refresh() }, 1000)
    return () => window.clearInterval(timer)
  }, [isDownloading, refresh])

  useEffect(() => {
    if (!notice || notice.kind !== 'done') return
    const timer = window.setTimeout(() => {
      setNotice(current => current === notice ? null : current)
    }, 5000)
    return () => window.clearTimeout(timer)
  }, [notice])

  const dismissNotice = useCallback(() => setNotice(null), [])

  return {
    resources,
    activeDownload,
    notice,
    checking,
    refresh,
    checkEnvironment,
    startDownload,
    dismissNotice,
  }
}

export function formatDownloadError(error: unknown) {
  return errorMessage(error)
}
