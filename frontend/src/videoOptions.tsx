import { useEffect, useId, useRef, useState } from 'react'
import { Captions, Globe2, ImagePlus, RotateCcw, Send, SlidersHorizontal } from 'lucide-react'
import { leaf, request, type Settings, type SourceKind } from './api'
import { Button, Feedback, Field, Modal, Select, useActions } from './ui'

export type Row = { id: string; source: string; kind: SourceKind; transcriptId?: number; submitted?: boolean }
export const sourceLanguages = [['auto','自动识别'],['zh','中文'],['en','英语'],['ja','日语'],['ko','韩语'],['fr','法语'],['de','德语'],['es','西班牙语']] as const
export const defaultStyle = {
  font_family: 'Microsoft YaHei', font_size: 44, font_size_mode: 'manual', font_weight: 700,
  primary_color: '#ffffff', outline_color: '#000000', outline_width: 3, shadow: 1,
  position: 'bottom', y_offset_percent: 8, max_width_percent: 86, line_spacing: 1.15,
  bilingual_order: 'en_top_zh_bottom', background_enabled: false, background_color: '#000000',
  background_opacity: 45, background_padding: 12,
}
export const defaultBili = {
  enabled: false, auto_metadata: true, tid: 0, tags: '', desc: '', copyright: 2, source_mode: 'original_url',
  source: '', title_template: '', line: 'QN', collection_type: 'none', collection_id: '',
  cover_mode: 'source_cover', cover_source: 'frame', cover_time_percent: 50, cover_asset_url: '',
}
export const defaultOptions = {
  source_language: 'auto', target_lang: 'zh-CN', whisper_model: 'small', whisper_inference_mode: 'auto',
  subtitle_output_mode: 'en_only', translate_model: '', aspect_ratio: 'source', resolution: 'best', fps: 'source',
  output_name_mode: 'sequence', output_name_prefix: '', translation_context_profile_id: '',
  translation_context_note: '', translation_glossary: '', subtitle_style: defaultStyle, bilibili_upload: defaultBili,
}
export type VideoOptions = typeof defaultOptions
export type Override = Omit<Partial<VideoOptions>, 'subtitle_style' | 'bilibili_upload'> & {
  subtitle_style?: Partial<typeof defaultStyle>; bilibili_upload?: Partial<typeof defaultBili>
}

function differences<T extends object>(base: T, next: T): Partial<T> {
  return Object.fromEntries(Object.entries(next).filter(([key, value]) => base[key as keyof T] !== value)) as Partial<T>
}
export function getOverride(base: VideoOptions, next: VideoOptions): Override {
  const { subtitle_style, bilibili_upload, ...changed } = differences(base, next)
  const style = subtitle_style ? differences(base.subtitle_style, subtitle_style) : {}
  const bili = bilibili_upload ? differences(base.bilibili_upload, bilibili_upload) : {}
  return { ...changed, ...(Object.keys(style).length ? {subtitle_style: style} : {}),
    ...(Object.keys(bili).length ? {bilibili_upload: bili} : {}) }
}
export function resolveOptions(base: VideoOptions, override?: Override): VideoOptions {
  return { ...base, ...override, subtitle_style: { ...base.subtitle_style, ...override?.subtitle_style },
    bilibili_upload: { ...base.bilibili_upload, ...override?.bilibili_upload } }
}
export function videoPayload(options: VideoOptions, model: string, perItem = false) {
  return {
    ...options, translate_model: options.translate_model || model,
    bilibili_upload: {
      ...options.bilibili_upload,
      tid: options.bilibili_upload.tid || null,
      tags: options.bilibili_upload.tags.split(/[,，\n]+/).map((tag) => tag.trim()).filter(Boolean),
      cover_scope: perItem ? 'per_item' : 'batch',
    },
  }
}

type Profile = { profile_id: string; name: string; note: string; glossary: string }
type Collection = { id: string; name: string; type: string; collection_type?: string }
type Zone = { tid?: number; id?: number; name: string }

function Context({ options, change }: { options: VideoOptions; change: (options: VideoOptions) => void }) {
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [name, setName] = useState('')
  const { notice, setNotice, perform } = useActions()
  async function refresh() {
    setProfiles((await request<{profiles: Profile[]}>('/ui/translation-contexts')).profiles)
  }
  useEffect(() => { void refresh().catch(() => {}) }, [])
  const choose = (id: string) => {
    const found = profiles.find((p) => p.profile_id === id)
    setName(found?.name || '')
    change({ ...options, translation_context_profile_id: id, translation_context_note: found?.note || '',
      translation_glossary: found?.glossary || '' })
  }
  function save(asNew: boolean) {
    perform(async () => {
      const id = asNew ? '' : options.translation_context_profile_id
      const saved = await request<Profile>('/ui/translation-contexts' + (id ? '/' + id : ''), id ? 'PUT' : 'POST',
        {name: name.trim(), note: options.translation_context_note, glossary: options.translation_glossary})
      change({ ...options, translation_context_profile_id: saved.profile_id })
      await refresh()
      setNotice({ text: '翻译上下文已保存' })
    })
  }
  return <div className="form-stack">
    <Field label="已保存的上下文"><Select value={options.translation_context_profile_id} onChange={choose}
      options={[[ '', '自定义' ], ...profiles.map((p) => [p.profile_id, p.name] as const)]} /></Field>
    <Field label="方案名称"><input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} /></Field>
    <Field label="背景说明"><textarea rows={3} maxLength={4000} value={options.translation_context_note} onChange={(e) =>
      change({...options, translation_context_note: e.target.value})}/></Field>
    <Field label="术语表"><textarea rows={3} maxLength={4000} value={options.translation_glossary} onChange={(e) =>
      change({...options, translation_glossary: e.target.value})}/></Field>
    <div className="toolbar compact">
      <Button variant="secondary" size="small" disabled={!name.trim()} onClick={() => save(true)}>另存方案</Button>
      <Button variant="secondary" size="small" disabled={!name.trim() || !options.translation_context_profile_id}
        onClick={() => save(false)}>更新方案</Button>
      {options.translation_context_profile_id && <Button variant="ghost" size="small" onClick={() => {
        if (window.confirm('删除这个翻译上下文方案？')) perform(async () => {
          await request('/ui/translation-contexts/' + options.translation_context_profile_id, 'DELETE')
          choose(''); await refresh()
        })
      }}>删除</Button>}
    </div>
    <Feedback notice={notice} />
  </div>
}

function CoverPicker({ row, options, change }: {
  row?: Row; options: typeof defaultBili; change: (options: typeof defaultBili) => void
}) {
  const [open, setOpen] = useState(false)
  const [time, setTime] = useState(options.cover_time_percent)
  const [busy, setBusy] = useState(false)
  const { notice, perform } = useActions()
  function capture(mode: 'frame' | 'youtube_thumbnail', file?: File) {
    perform(async () => {
      setBusy(true)
      try {
        const data = new FormData()
        if (file) data.set('file', file)
        const result = await request<{cover_asset_url: string}>(
          file ? '/ui/bilibili/cover-upload' : '/ui/bilibili/cover-preview', 'POST', file ? data :
          {source_kind: row?.kind, source_value: row?.source, preview_time_percent: time, cover_source_mode: mode})
        change({...options, cover_mode: file ? 'uploaded_image' : mode === 'frame' ? 'selected_frame' : 'youtube_thumbnail',
          cover_source: file ? 'uploaded_image' : mode, cover_time_percent: time, cover_asset_url: result.cover_asset_url})
      } finally { setBusy(false) }
    })
  }
  return <>
    <Button variant="secondary" size="small" leadingIcon={ImagePlus} onClick={() => {setTime(options.cover_time_percent); setOpen(true)}}>选择封面</Button>
    <Modal open={open} title="B 站封面" onClose={() => setOpen(false)}>
      <div className="form-stack">
        {options.cover_asset_url ? <img className="cover-image" src={options.cover_asset_url} alt="当前投稿封面" /> :
          <p className="muted">默认逐条使用来源封面。本地视频优先使用内嵌封面，取不到封面时使用视频画面。</p>}
        <Field label={'取帧位置 ' + time + '%'}><input type="range" min="0" max="100" value={time} onChange={(e) => setTime(Number(e.target.value))}/></Field>
        <div className="toolbar compact">
          <Button variant="secondary" size="small" disabled={!row || busy} onClick={() => capture('frame')}>抓取画面</Button>
          <Button variant="secondary" size="small" disabled={!row || row.kind === 'local' || busy} onClick={() => capture('youtube_thumbnail')}>使用当前素材的封面</Button>
        </div>
        <Field label="上传封面图片"><input disabled={busy} type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => {
          const file = e.target.files?.[0]; if (file) capture('frame', file)
        }}/></Field>
        <Feedback notice={notice} />
        <div className="toolbar compact"><Button variant="ghost" size="small" onClick={() => change({...options,
          cover_mode:'source_cover', cover_source:'frame', cover_time_percent:50, cover_asset_url:''})}>逐条使用来源封面</Button>
          <Button onClick={() => setOpen(false)}>完成</Button></div>
      </div>
    </Modal>
  </>
}

function Bilibili({ options, change, row, configured, aiConfigured }: {
  options: typeof defaultBili; change: (options: typeof defaultBili) => void; row?: Row; configured: boolean; aiConfigured: boolean
}) {
  const [zones, setZones] = useState<Zone[]>([])
  const [collections, setCollections] = useState<Collection[]>([])
  const uploadOptions = useId()
  useEffect(() => {
    if (!options.enabled) return
    let alive = true
    void request<{flat: Zone[]}>('/ui/bilibili/zones').then((data) => {if (alive) setZones(data.flat)}).catch(() => {})
    if (configured) void request<{collections: Collection[]}>('/ui/bilibili/collections')
      .then((data) => {if (alive) setCollections(data.collections)}).catch(() => {})
    return () => { alive = false }
  }, [configured, options.enabled])
  const set = <K extends keyof typeof defaultBili>(key: K, value: typeof defaultBili[K]) => change({...options, [key]: value})
  const text = (key: 'tags'|'title_template'|'source', placeholder?: string, maxLength?: number) =>
    <input value={options[key]} placeholder={placeholder} maxLength={maxLength} onChange={(e) => set(key,e.target.value)} />
  return <div className="form-stack">
    <label className="upload-toggle">
      <span>成片后投稿到 B 站</span>
      <input type="checkbox" role="switch" aria-controls={uploadOptions} checked={options.enabled}
        onChange={(e) => set('enabled',e.target.checked)} />
    </label>
    {!configured && <p className="muted">投稿凭据可在设置中配置。</p>}
    <div id={uploadOptions} hidden={!options.enabled} className="form-stack upload-options">
      <label className="check"><input type="checkbox" checked={options.auto_metadata}
        onChange={(event) => set('auto_metadata', event.target.checked)}/>用 DeepSeek 填写空白投稿信息</label>
      {options.auto_metadata && <p className="muted">{aiConfigured ?
        '每条视频会发送来源标题和部分原文字幕，用于填写分区、标题、简介和标签。' :
        '尚未配置 DeepSeek。请先在设置中配置，或手动选择分区。'}</p>}
      <Field label="分区">{zones.length ? <Select value={options.tid} onChange={(v) => set('tid',Number(v))}
        options={Array.from(new Map([[0, options.auto_metadata ? '自动选择（DeepSeek）' : '请选择分区'],
          ...(options.tid ? [[options.tid,'当前分区 · ' + options.tid] as const] : []), ...zones.filter((z) => z.tid || z.id)
          .map((z) => [Number(z.tid || z.id),z.name] as [number,string])]).entries())}/> :
        <input type="number" min={1} value={options.tid || ''} onChange={(e) => set('tid',Number(e.target.value))}/>}</Field>
      <Field label="标签（逗号分隔）">{text('tags', options.auto_metadata ? '留空由 DeepSeek 生成' : undefined)}</Field>
      <Field label="标题模板">{text('title_template', options.auto_metadata ? '留空由 DeepSeek 生成' : '{output_name}', 80)}</Field>
      <Field label="简介"><textarea rows={3} maxLength={2000} value={options.desc}
        placeholder={options.auto_metadata ? '留空由 DeepSeek 生成' : undefined}
        onChange={(e) => set('desc', e.target.value)}/></Field>
      <Field label="版权"><Select value={options.copyright} onChange={(v) => set('copyright',Number(v))}
        options={[[2,'转载'],[1,'自制']]}/></Field>
      <Field label="转载来源"><Select value={options.source_mode} onChange={(v) => set('source_mode',v)}
        options={[[ 'original_url','原始链接' ],[ 'custom','手动填写' ]]}/></Field>
      {options.source_mode === 'custom' && <Field label="来源地址">{text('source')}</Field>}
      <Field label="上传线路"><Select value={options.line} onChange={(v) => set('line',v)}
        options={[[ 'QN','QN' ],['BDA2','BDA2'],['WS','WS'],['auto','自动']]}/></Field>
      <Field label="合集或系列"><Select value={options.collection_id ? options.collection_type + ':' + options.collection_id : ''}
        onChange={(v) => {
          const [kind, id] = v.split(':'); change({...options,collection_type:kind || 'none',collection_id:id || ''})
        }} options={[[ '', '不加入' ], ...collections.map((c) => [(c.collection_type || c.type) + ':' + c.id,c.name] as const)]}/></Field>
      <div className="toolbar compact"><CoverPicker row={row} options={options} change={change} />
        <span className="muted">{options.cover_mode === 'source_cover' ? '每条使用来源封面' : '已自定义封面'}</span></div>
    </div>
  </div>
}

const inspectorSections = [
  { id: 'output', label: '输出', heading: '转录与输出', icon: SlidersHorizontal },
  { id: 'style', label: '样式', heading: '字幕样式', icon: Captions },
  { id: 'translation', label: '翻译', heading: '翻译上下文', icon: Globe2 },
  { id: 'publish', label: '投稿', heading: 'B 站投稿', icon: Send },
] as const
export type InspectorSection = typeof inspectorSections[number]['id']

export function Inspector({ options, change, settings, row, perItem, onScope, reset, section, onSection }: {
  options: VideoOptions; change: (options: VideoOptions) => void; settings: Settings | null; row?: Row;
  perItem: boolean; onScope: (perItem: boolean) => void; reset: () => void
  section: InspectorSection; onSection: (section: InspectorSection) => void
}) {
  const id = useId()
  const body = useRef<HTMLDivElement>(null)
  function selectSection(next: InspectorSection) {
    if (next === section) return
    if (body.current) body.current.scrollTop = 0
    onSection(next)
  }
  const set = <K extends keyof VideoOptions>(key: K, value: VideoOptions[K]) => change({...options, [key]: value})
  const style = options.subtitle_style
  const setStyle = <K extends keyof typeof style>(key: K, value: typeof style[K]) =>
    set('subtitle_style', {...style, [key]: value})
  const range = (label: string, key: 'font_size'|'outline_width'|'shadow'|'y_offset_percent'|'max_width_percent'|'line_spacing'|'background_opacity'|'background_padding',
    min: number, max: number, step = 1) => <Field label={label + ' · ' + style[key]}><input type="range" min={min} max={max}
      step={step} value={style[key]} onChange={(e) => setStyle(key,Number(e.target.value))}/></Field>
  return <div className="inspector-inner">
    <div className="inspector-controls">
    <div className="segmented" role="group" aria-label="设置应用范围">
      <button type="button" aria-pressed={!perItem} onClick={() => onScope(false)}>批次默认</button>
      <button type="button" aria-pressed={perItem} disabled={!row} onClick={() => onScope(true)}>当前素材</button>
    </div>
    {perItem && row && <div className="scope-note"><span>{leaf(row.source)}</span>
      <Button size="xs" variant="ghost" onClick={reset}>恢复继承</Button></div>}
    <div className="inspector-tabs" role="tablist" aria-label="参数分类">
      {inspectorSections.map(({id: key,label,heading,icon: Icon},index) => <button
        type="button" key={key} id={id + '-tab-' + key} role="tab" aria-label={heading} title={heading}
        aria-selected={section === key} aria-controls={id + '-panel-' + key} tabIndex={section === key ? 0 : -1}
        onClick={() => selectSection(key)} onKeyDown={(event) => {
          const count = inspectorSections.length
          const next = event.key === 'ArrowRight' ? (index + 1) % count :
            event.key === 'ArrowLeft' ? (index + count - 1) % count :
            event.key === 'Home' ? 0 : event.key === 'End' ? count - 1 : -1
          if (next === -1) return
          event.preventDefault()
          const destination = inspectorSections[next].id
          selectSection(destination)
          document.getElementById(id + '-tab-' + destination)?.focus({preventScroll:true})
        }}><Icon size={15} aria-hidden="true"/><span>{label}</span></button>)}
    </div>
    </div>
    <div className="inspector-scroll thin-scroll" ref={body}>
    <section id={id + '-panel-output'} role="tabpanel" aria-labelledby={id + '-tab-output'} tabIndex={0} hidden={section !== 'output'}>
      <h3>转录与输出</h3>
    <div className="form-stack">
      <Field label="字幕输出"><Select value={options.subtitle_output_mode} onChange={(v) => set('subtitle_output_mode',v)}
        options={[[ 'en_only','原文字幕' ],[ 'zh_only','译文字幕' ],[ 'bilingual','双语字幕' ]]}/></Field>
      <Field label="素材语言"><Select value={options.source_language} onChange={(v) => set('source_language',v)} options={sourceLanguages}/></Field>
      <Field label="输出画幅"><Select value={options.aspect_ratio} onChange={(v) => set('aspect_ratio',v)}
        options={[[ 'source','保留原比例' ],['16:9','16:9 横屏'],['9:16','9:16 竖屏'],['1:1','1:1 方形']]}/></Field>
      {options.subtitle_output_mode !== 'en_only' && <Field label="译文目标语言"><input value={options.target_lang} onChange={(e) => set('target_lang',e.target.value)} /></Field>}
        <div className="inspector-divider">高级参数</div>
        <Field label="Whisper 模型"><Select value={options.whisper_model} onChange={(v) => set('whisper_model',v)}
          options={[[ 'small','small · 推荐' ],['base','base'],['medium','medium'],['large-v3','large-v3']]}/></Field>
        <Field label="推理模式"><Select value={options.whisper_inference_mode} onChange={(v) => set('whisper_inference_mode',v)}
          options={[[ 'auto','自动 · NVIDIA 加速优先' ],['gpu_only','严格 GPU · 仅本地模型'],[ 'standard','精准' ],['auto_repair','自动补漏'],['batched','快速']]}/></Field>
        <Field label="下载清晰度"><Select value={options.resolution} onChange={(v) => set('resolution',v)}
          options={[[ 'best','最高可用' ],['1080p','1080p'],['1440p','1440p'],['2160p','2160p']]}/></Field>
        <Field label="下载帧率"><Select value={options.fps} onChange={(v) => set('fps',v)}
          options={[[ 'source','源帧率' ],['30','30 fps'],['60','60 fps']]}/></Field>
        <Field label="命名方式"><Select value={options.output_name_mode} onChange={(v) => set('output_name_mode',v)}
          options={[[ 'sequence','顺序编号' ],['original','原文件名'],['custom','自定义前缀']]}/></Field>
        {options.output_name_mode === 'custom' && <Field label="输出名称前缀"><input value={options.output_name_prefix}
          onChange={(e) => set('output_name_prefix',e.target.value)}/></Field>}
      </div>
    </section>
    <section id={id + '-panel-style'} role="tabpanel" aria-labelledby={id + '-tab-style'} tabIndex={0} hidden={section !== 'style'}>
      <h3>字幕样式</h3>
      <div className="form-stack">
        <Field label="字体"><input list={id + '-subtitle-fonts'} value={style.font_family}
          onChange={(e) => setStyle('font_family',e.target.value)} /></Field>
        <datalist id={id + '-subtitle-fonts'}>
          <option value="Source Han Sans CN">思源黑体</option>
          <option value="Source Han Serif CN">思源宋体</option>
          <option value="Microsoft YaHei">微软雅黑</option>
          <option value="SimHei">黑体</option>
          <option value="SimSun">宋体</option>
          <option value="KaiTi">楷体</option>
          <option value="Segoe UI"/>
          <option value="Arial"/>
        </datalist>
        <Field label="字号模式"><Select value={style.font_size_mode} onChange={(v) => setStyle('font_size_mode',v)}
          options={[[ 'manual','手动' ],[ 'auto','自动' ]]}/></Field>
        {style.font_size_mode !== 'auto' && range('字号','font_size',18,96)}
        <Field label="字重"><Select value={style.font_weight} onChange={(v) => setStyle('font_weight',Number(v))}
          options={[[400,'常规'],[600,'半粗体'],[700,'粗体'],[900,'特粗']]}/></Field>
        <Field label="字幕位置"><Select value={style.position} onChange={(v) => setStyle('position',v)}
          options={[[ 'bottom','底部' ],[ 'middle','居中' ],[ 'top','顶部' ]]}/></Field>
        <div className="field-pair">
          <Field label="文字颜色"><input type="color" value={style.primary_color} onChange={(e) => setStyle('primary_color',e.target.value)}/></Field>
          <Field label="描边颜色"><input type="color" value={style.outline_color} onChange={(e) => setStyle('outline_color',e.target.value)}/></Field>
        </div>
        {range('描边','outline_width',0,12)}{range('阴影','shadow',0,12)}
        {range('边距 %','y_offset_percent',0,30)}{range('最大宽度 %','max_width_percent',50,95)}
        {range('行距','line_spacing',.9,1.6,.05)}
        <Field label="双语顺序"><Select value={style.bilingual_order} onChange={(v) => setStyle('bilingual_order',v)}
          options={[[ 'en_top_zh_bottom','原文在上' ],[ 'zh_top_en_bottom','译文在上' ]]}/></Field>
        <label className="check"><input type="checkbox" checked={style.background_enabled}
          onChange={(e) => setStyle('background_enabled',e.target.checked)}/> 字幕背景条</label>
        {style.background_enabled && <>
          <Field label="背景颜色"><input type="color" value={style.background_color} onChange={(e) => setStyle('background_color',e.target.value)}/></Field>
          {range('背景不透明度 %','background_opacity',0,90)}{range('背景内边距','background_padding',0,32)}
        </>}
        <Button size="small" variant="ghost" leadingIcon={RotateCcw} onClick={() => set('subtitle_style',defaultStyle)}>重置字幕样式</Button>
      </div>
    </section>
    <section id={id + '-panel-translation'} role="tabpanel" aria-labelledby={id + '-tab-translation'} tabIndex={0} hidden={section !== 'translation'}>
      <h3>翻译上下文</h3>
      <Context options={options} change={change}/>
    </section>
    <section id={id + '-panel-publish'} role="tabpanel" aria-labelledby={id + '-tab-publish'} tabIndex={0} hidden={section !== 'publish'}>
      <h3>B 站投稿</h3>
      <Bilibili options={options.bilibili_upload} change={(v) => set('bilibili_upload',v)} aiConfigured={Boolean(settings?.has_ai_key)}
        row={row} configured={Boolean(settings?.has_bilibili_credentials)}/>
    </section>
    </div>
  </div>
}
