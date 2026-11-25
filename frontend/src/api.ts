export type SourceKind = 'local' | 'youtube' | 'bilibili' | 'url'
export const sourceNames = { local: '本地媒体', youtube: 'YouTube', bilibili: 'B 站', url: '在线素材', subtitle: '字幕文件' }
export const workflow = [['download','导入'],['transcribe','字幕'],['translate','翻译'],['burn','成片'],['bilibili_upload','投稿']] as const
export type WorkflowStage = typeof workflow[number][0]
export type MediaType = 'audio' | 'video' | 'unknown' | 'image' | 'note'
export type SourceProbe = { ready: true; title?: string; platform: string; media_type: MediaType;
  duration: number | null; has_audio: boolean; audio_direct: boolean; description?: string;
  images?: string[]; body?: string; author?: string; canonical_url?: string } |
  { ready: false; code: string; message: string; images?: string[]; body?: string }
export type ParsedSource = { url: string; platform: string; author: string; title: string; source_kind: Exclude<SourceKind, 'local'>; duration?: number }
export type SiteLogin = { site: 'douyin' | 'xiaohongshu' | 'bilibili' | 'weread'; platform: string; logged_in: boolean; logging_in: boolean; state?: 'saved'|'expired'|'signed_out' }
export type Preflight = Record<string, { ready: true; title: string; planned_stages: WorkflowStage[] } |
  { ready: false; title: string; message: string; code: string }>

export function linksIn(text: string) {
  return [...new Set((text.match(/https?:\/\/[^\s<>"'，。；！？、）】》]+/gi) || [])
    .map((url) => url.replace(/[)\]}.,;]+$/, '')))]
}

export async function siteSession(source: string, file: File) {
  const body = new FormData()
  body.set('source', source)
  body.set('file', file)
  return (await request<{session_id: string}>('/desktop/sources/session', 'POST', body)).session_id
}

export function parseSources(text: string) {
  return request<{ items: ParsedSource[] }>('/desktop/sources/parse', 'POST', { text })
}

export function videoLinkKind(value: string): Exclude<SourceKind, 'local'> {
  try {
    const url = new URL(value)
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.port) throw new Error()
    if (['youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtu.be'].includes(url.hostname)) return 'youtube'
    if (['bilibili.com', 'www.bilibili.com', 'm.bilibili.com', 'b23.tv'].includes(url.hostname)) return 'bilibili'
    return 'url'
  } catch { /* invalid link */ }
  throw new Error('请输入有效的 HTTP 或 HTTPS 链接')
}
export type Status = 'queued' | 'running' | 'succeeded' | 'failed'
export type PostingMetadata = {
  tid: number; zone: string; title: string; desc: string; tags: string[]; generated_fields: string[]; notice: string
}
export type Item = {
  item_id: string
  client_row_id: string
  index: number
  source_kind: SourceKind
  source_value: string
  source_title?: string
  output_name?: string
  media_type?: MediaType
  stop_after?: WorkflowStage
  planned_stages?: WorkflowStage[]
  platform?: string
  duration?: number
  status: Status
  stage: string
  progress: number
  execution_id?: string
  updated_at?: string
  work_progress?: number
  work_progress_known?: boolean
  waiting_for_shared?: boolean
  message: string
  progress_detail?: string
  log_tail?: string[]
  error?: { message: string }
  stage_details?: Record<string, { status: Status; progress: number; message: string }>
  result?: { title?: string; bvid?: string; aid?: number; final_video_url?: string; final_video_path?: string; english_srt_url?: string; translated_srt_url?: string;
    bilingual_srt_url?: string; transcript_id?: number; bilibili_url?: string; bilibili_metadata?: PostingMetadata;
    cover?: string; upload_title?: string; cover_asset_url?: string; cover_source?: string; cover_mode?: string; burn_encoder?: 'cpu' | 'nvenc';
    source_media_url?: string; source_video_url?: string; asset_type?: 'audio' | 'video'; original_description?: string; refresh_reason?: string }
}
type LegacyWorkflow = { subtitle_output_mode?: string; bilibili_upload?: {enabled?: boolean} }
export type Batch = { batch_id: string; status: Status; queued: number; running: number; items: Item[];
  request?: LegacyWorkflow & {knowledge_only?: boolean; item_overrides?: Record<string,LegacyWorkflow>} }
export type History = { batch_id: string; status: Status; total: number; created_at: string }
export type UploadCandidate = {state: 'retry' | 'ready' | 'posted' | 'missing' | 'busy'; message: string}
export type Settings = {
  onboarding_complete?: boolean
  data_dir: string
  active_data_dir: string
  log_dir?: string
  obsidian_vault: string
  obsidian_viewpoint_vault?: string
  obsidian_summary_vault?: string
  ai_model: string
  ai_api_base?: string
  has_ai_key: boolean
  has_bilibili_credentials: boolean
  gpu_enabled: boolean
  gpu_ready: boolean
  gpu_install_dir: string
  gpu: { running: boolean; message: string }
  site_logins?: SiteLogin[]
  version?: string
}
export type StorageSnapshot = {
  data_dir: string
  log_dir: string
  models_bytes: number
  jobs_bytes: number
  cleanable_bytes: number
  database_bytes: number
  total_bytes: number
  free_bytes: number
}
export type GpuQueueSnapshot = {
  busy: boolean
  holder?: { lane: string; operation: string; label: string; elapsed_seconds: number } | null
  holder_text?: string
  waiting_count: number
  waiting_by_lane: Record<string, number>
  vram?: { total_mb: number; free_mb: number; used_mb: number } | null
}
export type LocalResources = {
  models: {name:string; available:boolean; size:number; download:{running?:boolean; percent?:number; message?:string}}[]
  checks?: {label:string; ready:boolean}[]
  free_bytes?: number
  proxy?: string
  storage?: StorageSnapshot
  gpu_queue?: GpuQueueSnapshot
}
export type ViewpointKind = 'statement' | 'judgment' | 'fact' | 'story' | 'method' | ''
export const VIEWPOINT_KINDS: { id: Exclude<ViewpointKind, ''>; label: string; short: string }[] = [
  { id: 'statement', label: '核心陈述', short: '陈述' },
  { id: 'judgment', label: '判断', short: '判断' },
  { id: 'fact', label: '启发性事实', short: '事实' },
  { id: 'story', label: '典故/故事', short: '典故故事' },
  { id: 'method', label: '方法/框架', short: '方法' },
]
export const VIEWPOINT_KIND_LABELS: Record<string, string> = {
  statement: '陈述',
  judgment: '判断',
  fact: '启发性事实',
  story: '典故/故事',
  method: '方法/框架',
}
export type TranscriptSummary = { id: number; title: string; source_kind: SourceKind | 'subtitle'; source: string; created_at: string }
export type Cue = { translation?: string; truncated?: boolean; number: number; start_ms: number; end_ms: number; text: string }
export type Draft = { id: number; topic?: string; kind?: ViewpointKind; mode?: string; claim: string; evidence: string; example: string; quote_translation: string; refs: number[] }
export type SummaryViewpoint = {
  id: number
  kind: ViewpointKind
  topic: string
  claim: string
  evidence: string
  example: string
  quote_translation: string
  importance: number
  specificity: number
  refs: number[]
}
export type SummaryTreeNode = {
  id: number
  level: number
  depth: number
  role: 'overview' | 'branch' | 'leaf'
  title: string
  summary: string
  highlights: string[]
  start_cue: number | null
  end_cue: number | null
  start_ms: number | null
  end_ms: number | null
  edited: boolean
  children: SummaryTreeNode[]
  viewpoints: SummaryViewpoint[]
}
export type SummaryTreePlan = {
  total_tokens: number
  leaf_count: number
  viewpoint_count: number
  summary_layers: number
  branching_factor: number
  top_count: number
  level_sizes: number[]
  cost: number
}
export type SummaryTree = {
  run_id: string
  root_id: number
  plan: SummaryTreePlan
  overview: SummaryTreeNode | null
  nodes: SummaryTreeNode[]
}
export type ModeAvailability = {
  available: boolean
  run_id?: string | null
  status: string
  count: number
  viewpoint_count?: number
  layers?: number
  plan?: SummaryTreePlan | null
  can_reuse_leaves: boolean
  updated?: number
}
export type LanguageProfile = {
  lang_class: 'zh_native' | 'mixed' | 'foreign'
  lang_code: string
  cjk_ratio: number
  foreign_cue_ratio: number
  total_chars: number
}
export type Transcript = TranscriptSummary & { source: string; playable: boolean; media_type?: MediaType;
  note_run?: {phase:string;status:string;completed_blocks:number;total_blocks:number;input_tokens:number;output_tokens:number;detected_language?:string;translation_strategy?:string;saved_tokens?:number};
  language_profile?: LanguageProfile;
  active_mode?: 'summary' | 'curated' | 'comprehensive' | '';
  view_mode?: 'summary' | 'curated' | 'comprehensive';
  modes?: Record<'summary' | 'curated' | 'comprehensive', ModeAvailability>;
  summary_tree?: SummaryTree | null;
  prev_card?: number; cue_after?: number; card_after?: number; next_cue?: number | null; next_card?: number | null; cue_count?: number; card_count?: number; asset_type?: 'audio' | 'video' | 'note'; cues: Cue[]; cards: Draft[]; images?: string[]; body?: string; description?: string }
export type Publication = {
  card_id: number; title?: string; status: 'published' | 'already_published' | 'failed';
  publication_id?: string; cleared?: boolean; message?: string; vault_kind?: 'viewpoint' | 'summary';
}
export type SummaryPublication = {
  transcript_id: number
  title: string
  status: 'published' | 'already_published'
  publication_id: string
  path: string
  unchanged: boolean
  vault_kind: 'summary'
  message: string
}
export type LogEvent = { time: string; clock: string; level: 'info' | 'success' | 'warn' | 'error'; text: string }
export type LogStage = {
  stage: string
  label: string
  status: 'succeeded' | 'running' | 'failed' | 'queued' | 'reused' | 'skipped' | 'pending'
  progress: number
  duration_seconds?: number | null
  duration_label?: string
  collapsed_count?: number
  events: LogEvent[]
}
export type EntryLog = {
  offset: number
  limit: number
  total: number
  lines: string[]
  raw?: boolean
  raw_total?: number
  folded_count?: number
  stages?: LogStage[]
  overview?: {
    lane: string
    status: string
    total_duration_label?: string
    folded_count?: number
    raw_total?: number
  }
}
export type RemovalRow = { id: string; ok: boolean; kept?: boolean; status?: string; message?: string; cancelled?: number; undo_until?: number }

type NativeBridge = {
  choose_media(multiple?: boolean): Promise<string[]>
  choose_folder(): Promise<string>
  save_as(filename: string): Promise<string>
  set_window_theme?(dark: boolean, forcedColors: boolean): Promise<void>
  set_taskbar_progress?(state: 'none' | 'indeterminate' | 'normal' | 'error' | 'paused', percent?: number): Promise<void>
  notify_complete?(title: string, body: string): Promise<boolean>
}
declare global { interface Window { pywebview?: { api?: NativeBridge } } }

export async function native(): Promise<NativeBridge> {
  if (window.pywebview?.api) return window.pywebview.api
  await new Promise<void>((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      window.removeEventListener('pywebviewready', ready)
      reject(new Error('请从 Media Operator 桌面应用打开此功能'))
    }, 3000)
    function ready() { window.clearTimeout(timeout); resolve() }
    window.addEventListener('pywebviewready', ready, { once: true })
  })
  if (!window.pywebview?.api) throw new Error('系统文件对话框暂不可用')
  return window.pywebview.api
}

export async function request<T>(path: string, method = 'GET', data?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    body: data instanceof FormData ? data : data === undefined ? undefined : JSON.stringify(data),
    headers: data === undefined || data instanceof FormData ? undefined : { 'Content-Type': 'application/json' },
  })
  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    const detail: unknown = payload?.detail
    const message = typeof detail === 'string' ? detail :
      Array.isArray(detail) ? detail.map((entry) => entry.msg).filter(Boolean).join('；') : ''
    throw new Error(message || '操作失败（' + response.status + '）')
  }
  return payload as T
}

export async function saveAs(filename: string, data: Record<string, unknown>) {
  const safe = filename.replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').slice(0, 140)
  const destination = await (await native()).save_as(safe)
  if (!destination) return false
  await request('/desktop/export', 'POST', { ...data, destination })
  return true
}

export function watchBatch(id: string, update: (batch: Batch) => void, onError: (message: string) => void) {
  const path = '/ui/batches/' + encodeURIComponent(id)
  let alive = true
  let stream: EventSource | undefined
  const read = async () => {
    try {
      const batch = await request<Batch>(path)
      if (!alive) return
      update(batch)
      if (!batch.queued && !batch.running) stream?.close()
      return batch
    } catch (error) {
      if (alive) onError(errorMessage(error))
    }
  }
  void read().then((batch) => {
    if (!alive || !batch || (!batch.queued && !batch.running)) return
    stream = new EventSource(path + '/events')
    stream.onmessage = (event) => {
      if (!alive) return
      try {
        const current: Batch = JSON.parse(event.data)
        update(current)
        if (!current.queued && !current.running) stream?.close()
      } catch { onError('读取任务进度失败') }
    }
    stream.onerror = () => { if (alive) void read() }
  })
  return () => { alive = false; stream?.close() }
}

export const labels: Record<Status, string> = { queued: '排队中', running: '处理中', succeeded: '已完成', failed: '失败' }
export function errorMessage(error: unknown) { return error instanceof Error ? error.message : '操作失败' }
export function leaf(path: string) { return path.split(/[\\/]/).filter(Boolean).at(-1) || path }
const batchDate = new Intl.DateTimeFormat('sv-SE', {
  year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit', hourCycle:'h23',
})
export function historyLabel(entry: History) {
  const date = new Date(entry.created_at)
  return (Number.isNaN(date.getTime()) ? '—' : batchDate.format(date)) + ' · ' + entry.total
}
export function timestamp(ms: number) {
  const s = Math.floor(ms / 1000)
  return [Math.floor(s / 3600), Math.floor(s / 60) % 60, s % 60].map((part) => String(part).padStart(2, '0')).join(':')
}
