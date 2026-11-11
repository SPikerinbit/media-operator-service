/** In-memory inbox so the workbench can be driven without the Python backend. */
const now = () => new Date().toISOString()

function entry(partial) {
  return {
    progress: 0, progress_known: false, message: '', raw: partial.title || '', source: partial.title || '',
    kind: 'url', platform: 'B 站', author: '书房', created_at: now(), run: 1, revision: 1,
    deletable: true, summary: [], result: {}, reuse: [], ...partial,
  }
}

const state = {
  groups: [
    { id: 'g-ready', lane: 'publish', created_at: now(), options: {}, overrides: {}, prepared: [], revision: 1 },
    { id: 'g-run', lane: 'publish', created_at: now(), options: {}, overrides: {}, prepared: ['output', 'style', 'publish', 'translation'], revision: 2 },
    { id: 'g-ok', lane: 'publish', created_at: now(), options: {}, overrides: {}, prepared: ['output', 'style', 'publish', 'translation'], revision: 3 },
    { id: 'g-fail', lane: 'publish', created_at: now(), options: {}, overrides: {}, prepared: [], revision: 1 },
    { id: 'g-notes', lane: 'notes', created_at: now(), options: {}, overrides: {}, prepared: [], revision: 1 },
  ],
  entries: [
    entry({ id: 'e-ready', group_id: 'g-ready', lane: 'publish', status: 'ready', title: '如何把一个想法变成作品', raw: 'https://www.bilibili.com/video/BV1ready', message: '待设置', deletable: true }),
    entry({ id: 'e-run', group_id: 'g-run', lane: 'publish', status: 'running', title: '火盆里的信', stage: 'transcribe', progress: 42, progress_known: true, message: '正在转录', summary: ['Whisper 转录'], deletable: false }),
    entry({ id: 'e-ok', group_id: 'g-ok', lane: 'publish', status: 'succeeded', title: '已经寄出的作品', progress: 100, progress_known: true, stage: 'done', message: '投稿成功', deletable: true,
      result: { bilibili_url: 'https://www.bilibili.com/video/BV1ok', upload_title: '已经寄出的作品', final_video_url: '/static/desktop-ui/workbench/fixture-reel.mp4' } }),
    entry({ id: 'e-fail', group_id: 'g-fail', lane: 'publish', status: 'failed', title: '卡住的一封', stage: 'translate', message: '请配置 DeepSeek', summary: ['翻译没有完成'], deletable: true }),
    entry({ id: 'e-note', group_id: 'g-notes', lane: 'notes', status: 'succeeded', title: '值得留下的一段', progress: 100, progress_known: true, stage: 'done', message: '已完成', deletable: true,
      result: { transcript_id: 7 } }),
  ],
}

const clients = new Set()

function snapshot() {
  return { groups: state.groups, entries: state.entries }
}

function push() {
  const data = `data: ${JSON.stringify(snapshot())}\n\n`
  for (const res of clients) res.write(data)
}

function readBody(req) {
  return new Promise((resolve) => {
    const chunks = []
    req.on('data', (c) => chunks.push(c))
    req.on('end', () => {
      const raw = Buffer.concat(chunks).toString('utf8')
      if (!raw) return resolve({})
      try { resolve(JSON.parse(raw)) } catch { resolve({}) }
    })
  })
}

const settings = {
  data_dir: '/data', active_data_dir: '/data', obsidian_vault: '', ai_model: 'deepseek-chat',
  has_ai_key: true, has_bilibili_credentials: true, gpu_enabled: false, gpu_ready: false,
  gpu_install_dir: '', gpu: { running: false, message: '' },
  site_logins: [
    { site: 'douyin', platform: '抖音', logged_in: false, logging_in: false },
    { site: 'xiaohongshu', platform: '小红书', logged_in: false, logging_in: false },
    { site: 'bilibili', platform: 'B 站', logged_in: false, logging_in: false },
  ],
}

const transcript = {
  id: 7, title: '值得留下的一段', source_kind: 'url', source: 'https://example.com/note', created_at: now(),
  playable: false, media_type: 'video', cues: [
    { number: 1, start_ms: 0, end_ms: 2400, text: '先把想法写在纸上。' },
    { number: 2, start_ms: 2400, end_ms: 5000, text: '纸有了重量，句子才站得住。' },
  ],
  cards: [
    { id: 1, claim: '写下来，想法才开始存在', evidence: '口述往往会散', example: '一封信比一条动态更完整', quote_translation: 'Write it down.', refs: [1] },
    { id: 2, claim: '重量来自纸，不来自进度条', evidence: '桌上的物件要有影子', example: '火漆按下会回弹', quote_translation: 'Weight lives in the paper.', refs: [2] },
  ],
}

function send(res, code, body) {
  const payload = typeof body === 'string' ? body : JSON.stringify(body)
  res.statusCode = code
  res.setHeader('content-type', 'application/json')
  res.end(payload)
}

export function fixturePlugin() {
  return {
    name: 'workbench-fixture',
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        const url = new URL(req.url, 'http://fixture.local')
        const path = url.pathname
        if (!path.startsWith('/desktop') && !path.startsWith('/ui/')) return next()
        if (path === '/desktop/inbox/events') {
          res.statusCode = 200
          res.setHeader('content-type', 'text/event-stream')
          res.setHeader('cache-control', 'no-cache')
          res.setHeader('connection', 'keep-alive')
          res.write(`data: ${JSON.stringify(snapshot())}\n\n`)
          clients.add(res)
          req.on('close', () => clients.delete(res))
          return
        }
        if (path === '/desktop/inbox/queue') return send(res, 200, snapshot())
        if (path === '/desktop/settings' && req.method === 'GET') return send(res, 200, settings)
        if (path === '/desktop/settings' && req.method === 'PUT') {
          const body = await readBody(req)
          Object.assign(settings, body)
          return send(res, 200, settings)
        }
        if (path === '/desktop/video-defaults' && req.method === 'GET') return send(res, 200, { output: null, subtitle_style: null })
        if (path === '/desktop/video-defaults' && req.method === 'PUT') return send(res, 200, await readBody(req))
        if (path === '/desktop/resources') return send(res, 200, { models: [{ name: 'small', available: true, size: 5e8, download: {} }], checks: [], free_bytes: 2e10 })
        if (path === '/desktop/resources/check') return send(res, 200, { models: [], checks: [{ label: 'ffmpeg', ready: true }], free_bytes: 2e10 })
        if (path === '/desktop/sites') return send(res, 200, { sites: settings.site_logins })
        if (path.startsWith('/desktop/sites/')) return send(res, 200, settings.site_logins[0])
        if (path === '/desktop/inbox/deliveries' && req.method === 'POST') {
          const body = await readBody(req)
          const id = 'g-' + Math.random().toString(36).slice(2, 8)
          const lane = body.lane || 'publish'
          state.groups.push({ id, lane, created_at: now(), options: {}, overrides: {}, prepared: [], revision: 1 })
          const made = (body.entries || []).map((line) => entry({
            id: 'e-' + Math.random().toString(36).slice(2, 8),
            client_id: line.id, group_id: id, lane, status: 'identifying', title: line.text, raw: line.text,
            message: '正在识别来源', deletable: false,
          }))
          state.entries.push(...made)
          send(res, 200, { group_id: id })
          setTimeout(() => {
            for (const item of made) {
              const audio = /音频|audio/i.test(item.raw)
              Object.assign(item, audio
                ? { status: 'rejected', message: '这是音频，投稿需要视频', deletable: true }
                : { status: lane === 'publish' ? 'ready' : 'queued', message: lane === 'publish' ? '待设置' : '已进入笔记队列', title: item.raw.slice(0, 40), deletable: true, progress: lane === 'notes' ? 10 : 0, progress_known: lane === 'notes' })
            }
            push()
          }, 700)
          push()
          return
        }
        const groupPatch = path.match(/^\/desktop\/inbox\/groups\/([^/]+)$/)
        if (groupPatch && req.method === 'PATCH') {
          const body = await readBody(req)
          const group = state.groups.find((g) => g.id === groupPatch[1])
          if (group) Object.assign(group, { options: body.options ?? group.options, overrides: body.overrides ?? group.overrides, prepared: body.prepared ?? group.prepared, revision: group.revision + 1 })
          push()
          return send(res, 200, group || {})
        }
        const start = path.match(/^\/desktop\/inbox\/groups\/([^/]+)\/start$/)
        if (start && req.method === 'POST') {
          const body = await readBody(req)
          for (const id of body.entry_ids || []) {
            const item = state.entries.find((e) => e.id === id)
            if (item) Object.assign(item, { status: 'running', stage: 'burn', progress: 15, progress_known: true, message: '正在制作成片', deletable: false })
          }
          push()
          return send(res, 200, { ok: true })
        }
        if (path === '/desktop/inbox/entries/remove' && req.method === 'POST') {
          const body = await readBody(req)
          const until = Math.floor(Date.now() / 1000) + 30
          const results = (body.ids || []).map((id) => {
            const item = state.entries.find((e) => e.id === id)
            if (item) Object.assign(item, { status: 'removed', deletable: false, undo_until: until })
            return { id, ok: true, undo_until: until }
          })
          push()
          return send(res, 200, { results, cancelled: 0 })
        }
        const undo = path.match(/^\/desktop\/inbox\/entries\/([^/]+)\/undo$/)
        if (undo && req.method === 'POST') {
          const item = state.entries.find((e) => e.id === undo[1])
          if (item) Object.assign(item, { status: 'ready', deletable: true, message: '待设置' })
          push()
          return send(res, 200, { ok: true })
        }
        const retry = path.match(/^\/desktop\/inbox\/entries\/([^/]+)\/retry$/)
        if (retry && req.method === 'POST') {
          const item = state.entries.find((e) => e.id === retry[1])
          if (item) Object.assign(item, { status: 'running', progress: 5, progress_known: true, message: '正在重试' })
          push()
          return send(res, 200, { ok: true })
        }
        const log = path.match(/^\/desktop\/inbox\/entries\/([^/]+)\/log$/)
        if (log) {
          return send(res, 200, { offset: 0, limit: 80, total: 2, lines: ['获取素材完成', '开始转录原文'] })
        }
        if (path === '/ui/preview-frame') return send(res, 200, { preview_image_url: '' })
        if (path === '/ui/bilibili/zones') return send(res, 200, { flat: [{ tid: 201, id: 201, name: '知识' }] })
        if (path === '/ui/bilibili/collections') return send(res, 200, { collections: [] })
        if (path === '/ui/translation-contexts') return send(res, 200, { profiles: [] })
        if (path === '/desktop/knowledge/7') return send(res, 200, transcript)
        if (path.startsWith('/desktop/knowledge/7/')) return send(res, 200, transcript)
        if (path === '/desktop/fonts/SourceHanSansCN-Regular.otf' || path.endsWith('.otf')) {
          res.statusCode = 404
          return res.end()
        }
        return send(res, 200, {})
      })
    },
  }
}
