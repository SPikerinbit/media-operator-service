"""Durable two-lane inbox. Receiving a letter never starts a publishing job."""
import asyncio
import json
import re
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError
from app import knowledge, desktop_jobs as jobs, desktop_sources, desktop_config, share_text
from app import workbench_cache as cache
from app import main as media

router = APIRouter(prefix='/desktop/inbox')
LOCK = threading.RLock()
POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix='letter')
SESSIONS = {}
SECRET = {'session_id', 'cookies', 'cookie', 'authorization'}
BLOCKING = {'identifying', 'ready', 'starting', 'queued', 'running', 'blocked'}
IDLE_DELETE = {'ready', 'blocked', 'failed', 'succeeded', 'rejected', 'duplicate', 'cancelled'}
LABELS = {
    'download': '获取素材', 'transcribe': '转录', 'translate': '生成译文', 'burn': '烧录字幕',
    'bilibili_upload': '投稿', 'extract': '提取观点', 'done': '已完成', 'queued': '等待处理',
    'cancelled': '已取消',
}
WAITING = {
    ('download', 'transcribe'): '素材已获取，等待转录',
    ('transcribe', 'translate'): '转录已完成，等待翻译',
    ('transcribe', 'extract'): '转录已完成，等待提取观点',
    ('translate', 'burn'): '译文已完成，等待烧录',
    ('translate', 'extract'): '译文已完成，等待提取观点',
    ('burn', 'bilibili_upload'): '成片已完成，等待投稿',
}
_URL = re.compile(r'https?://\S+|file://\S+', re.I)
_SECRET = re.compile(r'(?i)(cookie|sessionid|sessdata|bili_jct|xsec_token|authorization)([=:\s]+)[^\s;]+')
_TRACE = re.compile(r'Traceback|File "|yt-dlp|ERROR:', re.I)


def clock():
    return time.time()


def initialize():
    cache.initialize()
    with knowledge.database() as db:
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='workbench_group'").fetchone()
        if not exists:
            backup = media.DATA_DIR / 'knowledge.before-workbench.sqlite3'
            if not backup.exists():
                target = sqlite3.connect(backup)
                try: db.backup(target)
                finally: target.close()
        db.executescript('''
          CREATE TABLE IF NOT EXISTS workbench_group (id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, document TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS workbench_entry (id TEXT PRIMARY KEY, group_id TEXT NOT NULL, document TEXT NOT NULL);
          CREATE INDEX IF NOT EXISTS workbench_group_entries ON workbench_entry(group_id);
        ''')
    # Never restart an interrupted operation (especially an upload) without a user action.
    for entry in entries():
        if entry['status'] in {'identifying', 'starting'}:
            update(entry['id'], status='blocked', message='上次识别未完成，请重试')
    if not exists:
        import_history()
    cache.migrate_legacy()


def entries():
    with knowledge.database() as db:
        return [json.loads(row[0]) for row in db.execute('SELECT document FROM workbench_entry ORDER BY rowid DESC')]


def groups():
    with knowledge.database() as db:
        return [json.loads(row[0]) for row in db.execute('SELECT document FROM workbench_group ORDER BY rowid DESC')]


def get_entry(ident):
    with knowledge.database() as db:
        row = db.execute('SELECT document FROM workbench_entry WHERE id=?', (ident,)).fetchone()
    if not row: raise HTTPException(404, '找不到这封信')
    return json.loads(row[0])


def get_group(ident):
    with knowledge.database() as db:
        row = db.execute('SELECT document FROM workbench_group WHERE id=?', (ident,)).fetchone()
    if not row: raise HTTPException(404, '找不到这次投递')
    return json.loads(row[0])


def save_entry(entry):
    for key in SECRET:
        entry.pop(key, None)
    with knowledge.database() as db:
        db.execute('INSERT OR REPLACE INTO workbench_entry VALUES (?,?,?)',
                   (entry['id'], entry['group_id'], json.dumps(entry, ensure_ascii=False)))


def update(ident, **changes):
    with LOCK:
        entry = get_entry(ident)
        for key in SECRET:
            changes.pop(key, None)
        entry.update(changes)
        for key in SECRET:
            entry.pop(key, None)
        entry['run'] = int(entry.get('run') or 1)
        entry['revision'] = int(entry.get('revision') or 0) + 1
        save_entry(entry)
        return entry


def clean_line(text):
    value = ' '.join(str(text or '').split())
    value = _SECRET.sub(r'\1\2[redacted]', value)
    value = _URL.sub('', value)
    value = ' '.join(value.split())
    if not value or _TRACE.search(value):
        return ''
    if len(value) > 42:
        value = value[:42].rstrip() + '…'
    return value


def scrub_log(line):
    return _SECRET.sub(r'\1\2[redacted]', str(line or ''))


def task_started(entry):
    task = entry.get('task') or {}
    status = task.get('status') or entry.get('status')
    if status == 'running':
        return True
    details = task.get('stage_details') or {}
    if any((detail or {}).get('status') == 'running' for detail in details.values()):
        return True
    stage = task.get('stage') or entry.get('stage') or ''
    upload = details.get('bilibili_upload') or {}
    if stage == 'bilibili_upload' and upload.get('status') in {'running', 'succeeded'}:
        return True
    return False


def can_delete(entry):
    status = entry.get('status')
    if status in {'removed', 'running'}:
        return False
    if status in IDLE_DELETE or status == 'identifying':
        return True
    if status in {'queued', 'starting'}:
        return not task_started(entry)
    return False


def delete_reason(entry):
    stage = (entry.get('task') or {}).get('stage') or entry.get('stage') or ''
    if stage == 'bilibili_upload':
        return '投稿已开始，不能删除'
    return '任务已开始执行，不能删除'


def measured_progress(task, lane, fallback=0):
    if not task:
        return fallback or 0
    if task.get('status') == 'succeeded':
        return 100
    details = task.get('stage_details') or {}
    planned = list(task.get('planned_stages') or [])
    if not planned:
        local = task.get('local_progress') or 0
        return task.get('progress') or fallback or 0 if local else (fallback or 0)
    best_index = -1
    best_local = 0
    for index, name in enumerate(planned):
        detail = details.get(name) or {}
        local = int(detail.get('progress') or 0)
        if detail.get('status') == 'succeeded':
            best_index, best_local = index, 100
        elif local > 0 and index >= best_index:
            best_index, best_local = index, local
    if best_index < 0:
        return fallback or 0
    name = planned[best_index]
    if lane == 'notes':
        ranges = {'download': (0, 15), 'transcribe': (15, 60), 'translate': (60, 80), 'extract': (80, 99)}
        lower, upper = ranges.get(name, (0, 99))
        value = upper if best_local >= 100 else round(lower + (upper - lower) * best_local / 100)
        return min(99, value)
    value = round(100 * (best_index + best_local / 100) / len(planned))
    return min(100, value)


def waiting_line(entry):
    task = entry.get('task') or {}
    details = task.get('stage_details') or {}
    planned = list(task.get('planned_stages') or [])
    stage = task.get('stage') or entry.get('stage') or ''
    if stage == 'extract':
        return '转录已完成，等待提取观点' if not details.get('extract') else ''
    if stage not in planned:
        return ''
    index = planned.index(stage)
    if index <= 0:
        return ''
    previous = planned[index - 1]
    if (details.get(previous) or {}).get('status') != 'succeeded':
        return ''
    current = details.get(stage) or {}
    if current.get('status') in {None, 'queued', ''} and not current.get('progress'):
        return WAITING.get((previous, stage), '')
    return ''


def summary_of(entry):
    status = entry.get('status')
    stage = entry.get('stage') or ''
    if status == 'ready':
        lines = ['待确认档位' if entry.get('lane') == 'notes' else '待设置']
    elif status == 'identifying':
        lines = ['正在识别来源']
    elif status == 'removed':
        lines = ['已删除']
    elif status == 'cancelled':
        lines = ['已取消']
    elif status == 'duplicate':
        lines = ['已在队列中']
    elif status == 'succeeded':
        if entry.get('lane') == 'publish' and (entry.get('result') or {}).get('bilibili_url'):
            lines = ['投稿成功，等待审核']
        elif entry.get('lane') == 'notes':
            lines = ['笔记已完成']
        else:
            lines = ['已完成']
    elif status in {'rejected', 'blocked', 'failed'}:
        lines = [clean_line(entry.get('message')) or {'rejected': '无法处理', 'blocked': '需要处理', 'failed': '处理失败'}[status]]
    else:
        waiting = waiting_line(entry)
        if waiting:
            lines = [waiting]
        else:
            lines = [LABELS.get(stage, '处理中')]
            task = entry.get('task') or {}
            local = int(((task.get('stage_details') or {}).get(stage) or {}).get('progress') or 0)
            if entry.get('progress_known') and 0 < local < 100:
                lines.append(f"进度 {entry.get('progress')}%")
            activity = task.get('progress_detail') or task.get('message') or ''
            if '最近阶段活动' in activity or 'GPU 转录失败' in activity or 'NVIDIA GPU' in activity or 'CPU ·' in activity:
                lines = [LABELS.get(stage, '处理中'), clean_line(activity)]
    return [line for line in lines if line][:2]


def _public_cover(result):
    for key in ('cover', 'cover_url', 'thumbnail'):
        value = result.get(key)
        if isinstance(value, str) and (value.startswith('/files/') or value.startswith('http://') or value.startswith('https://')):
            try:
                if value.startswith('/files/'):
                    _, path = media.resolve_local_artifact_from_url(value)
                    if path.is_file() and path.stat().st_size:
                        return value
                else:
                    return value
            except (OSError, ValueError):
                continue
    path = result.get('cover_path')
    if isinstance(path, str) and path:
        file = Path(path)
        try:
            relative = file.resolve().relative_to(media.JOBS_DIR.resolve())
        except (OSError, ValueError):
            return ''
        if file.is_file() and relative.parts:
            return media.public_file_url(relative.parts[0], file.name)
    return ''


def shape_result(result):
    if not result:
        return {}
    out = dict(result)
    out.pop('refresh_reason', None)
    link = result.get('bilibili_url') or ''
    if not link and result.get('bvid'):
        link = f"https://www.bilibili.com/video/{result['bvid']}"
    if link:
        out['bilibili_url'] = link
        meta_title = (result.get('bilibili_metadata') or {}).get('title')
        title = meta_title or result.get('upload_title') or result.get('title') or ''
        if title and not media.is_http_url(str(title)):
            out['upload_title'] = str(title)
    else:
        out.pop('upload_title', None)
        out.pop('bilibili_url', None)
    cover = _public_cover(result)
    if cover:
        out['cover'] = cover
    else:
        out.pop('cover', None)
    final = result.get('final_video_url') or ''
    if final:
        try:
            _, path = media.resolve_local_artifact_from_url(final)
            if path.is_file() and path.stat().st_size:
                out['final_video_url'] = final
                out['final_video_path'] = str(path)
            else:
                out.pop('final_video_url', None)
        except (OSError, ValueError):
            out.pop('final_video_url', None)
    reason = result.get('refresh_reason')
    if reason in {'login', 'network', 'signature_expired', 'no_media'}:
        out['refresh_reason'] = reason
    return out


def present(entry):
    shown = dict(entry)
    undo = shown.pop('undo', None) or {}
    if undo.get('until'):
        shown['undo_until'] = undo['until']
    for key in SECRET:
        shown.pop(key, None)
    shown['run'] = int(shown.get('run') or 1)
    shown['revision'] = int(shown.get('revision') or 1)
    progress = measured_progress(shown.get('task') or {}, shown.get('lane') or '', shown.get('progress') or 0)
    if shown.get('status') == 'succeeded':
        progress = 100
    shown['progress'] = progress
    shown['progress_known'] = bool(progress) or shown.get('status') == 'succeeded'
    shown['result'] = shape_result(shown.get('result') or {})
    if shown['result'].get('refresh_reason'):
        shown['refresh_reason'] = shown['result']['refresh_reason']
    shown.pop('weread_text', None)
    shown['summary'] = summary_of(shown)
    shown['deletable'] = can_delete(shown)
    return shown


def default_options():
    prefs = desktop_config.settings()
    return {**(prefs.get('video_output_defaults') or {}),
            'subtitle_style': prefs.get('video_subtitle_style_defaults') or {},
            'subtitle_output_mode': (prefs.get('video_output_defaults') or {}).get('subtitle_output_mode', 'bilingual'),
            'translate_model': prefs.get('ai_model', media.DEFAULT_TRANSLATE_MODEL)}


def merge(base, override):
    result = {**base, **override}
    for key in ('subtitle_style', 'bilibili_upload'):
        result[key] = {**base.get(key, {}), **override.get(key, {})}
    return result


def settings_payload(options):
    options = dict(options)
    upload = dict(options.get('bilibili_upload') or {})
    if isinstance(upload.get('tags'), str):
        upload['tags'] = [tag.strip() for tag in re.split('[,，\n]', upload['tags']) if tag.strip()]
    if upload.get('tid') == 0: upload['tid'] = None
    options['bilibili_upload'] = upload
    return options


def source_of(entry, notes=False):
    payload = {'source_kind': entry['kind'], 'source_value': entry.get('resolved_fetch_url') or entry['source'],
            'client_row_id': entry['id'], 'source_title': entry.get('title', '')[:500],
            'stop_after': ('download' if entry.get('probe', {}).get('media_type') == 'note' else 'transcribe') if notes else 'bilibili_upload',
            'allow_muxed_audio': True, 'allow_unknown_audio': notes}
    session = SESSIONS.get(entry['id']) or ''
    if session:
        payload['session_id'] = session
    return payload


def sync(entry, batches):
    if entry.get('status') == 'removed':
        return present(entry)
    merged = dict(entry)
    if entry.get('batch_id'):
        try:
            batch = batches.setdefault(entry['batch_id'], None)
            if batch is None:
                batch = jobs.batch_item(entry['batch_id'], entry['item_id'])[0]
                batches[entry['batch_id']] = batch
            item = next(i for i in batch.items if i.item_id == entry['item_id'])
            task = item.model_dump()
            merged.update(status=item.status, title=item.source_title or entry.get('title'),
                          stage=item.stage, message=item.message, task=task,
                          result=item.result or {}, reuse=(item.result or {}).get('reuse', []))
        except (OSError, ValueError, StopIteration):
            merged.update(status='blocked', message='任务记录不可用，原始输入已保留')
    return present(merged)


@router.get('/queue')
def snapshot(lane: Literal['publish', 'notes'] | None = None):
    batches = {}
    return {'groups': [g for g in groups() if not lane or g['lane'] == lane],
            'entries': [sync(e, batches) for e in entries() if not lane or e['lane'] == lane]}


class Letter(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=20000)
    local: bool = False
    session_id: str = Field(default='', max_length=200, exclude=True)


class Delivery(BaseModel):
    request_id: str = Field(min_length=1, max_length=100)
    lane: Literal['publish', 'notes']
    notes_mode: Literal['summary', 'curated', 'comprehensive'] = 'curated'
    entries: list[Letter] = Field(min_length=1, max_length=300)


@router.post('/deliveries')
def deliver(request: Delivery):
    with LOCK:
        with knowledge.database() as db:
            existing = db.execute('SELECT id FROM workbench_group WHERE request_id=?', (request.request_id,)).fetchone()
            if existing: return {'group_id': existing[0]}
        ident = str(uuid.uuid4())
        options = default_options()
        if request.lane == 'notes':
            options['notes_mode'] = request.notes_mode
        group = {'id': ident, 'lane': request.lane, 'created_at': media.now_iso(), 'options': options,
                 'overrides': {}, 'prepared': [], 'revision': 0}
        sessions = {}
        with knowledge.database() as db:
            db.execute('INSERT INTO workbench_group VALUES (?,?,?)', (ident, request.request_id, json.dumps(group, ensure_ascii=False)))
            for letter in request.entries:
                entry_id = str(uuid.uuid4())
                entry = {'id': entry_id, 'client_id': letter.id, 'group_id': ident, 'lane': request.lane,
                         'raw': letter.text, 'local': letter.local, 'status': 'identifying', 'message': '正在识别来源',
                         'progress': 0, 'run': 1, 'revision': 1, 'created_at': media.now_iso(),
                         'notes_mode': request.notes_mode}
                db.execute('INSERT INTO workbench_entry VALUES (?,?,?)', (entry_id, ident, json.dumps(entry, ensure_ascii=False)))
                if letter.session_id:
                    sessions[entry_id] = letter.session_id
                    SESSIONS[entry_id] = letter.session_id
        ids = [e['id'] for e in entries() if e['group_id'] == ident]
    for entry_id in ids: POOL.submit(identify, entry_id, sessions.get(entry_id, ''))
    return {'group_id': ident}


def _classified(entry):
    if entry.get('local'):
        source = entry['raw'].strip().strip('"').strip("'")
        return {'kind': 'local', 'local': True, 'source': source, 'source_kind': 'local', 'title': Path(source).name,
                'url': source, 'platform': '本地文件', 'author': ''}
    found = share_text.classify_letters(entry.get('raw') or '')
    if len(found) != 1:
        return None
    return found[0]


def identify(ident, session_id=''):
    if session_id:
        SESSIONS[ident] = session_id
    entry = get_entry(ident)
    run = int(entry.get('run') or 1)

    def alive():
        current = get_entry(ident)
        return int(current.get('run') or 1) == run and current.get('status') not in {'removed', 'cancelled'}

    try:
        parsed = _classified(entry)
        if not parsed:
            if alive():
                update(ident, status='rejected', message='每行只能放一条链接、分享文案或文件路径')
            return
        local = parsed.get('kind') == 'local' or parsed.get('source_kind') == 'local'
        source = parsed.get('source') or parsed.get('url')
        if local:
            try:
                source = str(media.normalize_local_source_path(source))
            except ValueError as error:
                text = str(error)
                if not alive():
                    return
                if 'not found' in text:
                    message = '找不到这个文件'
                elif 'not a file' in text:
                    message = '请选择文件，不能是文件夹'
                else:
                    message = '无法读取这个本地文件'
                update(ident, status='rejected', message=message, kind='local', source=parsed.get('source') or '')
                return
        subtitle = Path(source).suffix.lower() in {'.srt', '.vtt'}
        if entry['lane'] == 'publish' and subtitle:
            if alive():
                update(ident, status='rejected', message='投稿只接收视频', kind='local', source=source)
            return
        weread_text = ''
        if subtitle:
            probe = {'title': Path(source).name, 'media_type': 'subtitle', 'platform': '字幕文件', 'has_audio': False}
        elif entry['lane'] == 'notes':
            # Receiving only classifies. Source pages can contain an entire book/note;
            # even probing them belongs to the explicit start operation.
            host = urlsplit(source or '').hostname or ''
            probe = {'title': parsed.get('title') or Path(source).name or source,
                     'platform': parsed.get('platform') or host,
                     'media_type': 'weread' if host == 'weread.qq.com' else 'unknown',
                     'deferred': True}
        else:
            reused = cache.reused_probe(source)
            probe = reused if reused else desktop_sources.probe(source, parsed.get('source_kind') or 'url', session_id)
        if not alive():
            return
        key = cache.identity(source, probe.get('canonical_url'))
        fetch = probe.get('resolved_fetch_url') or source
        original = probe.get('original_url') or source
        try:
            cache.remember_source(fetch, original, probe.get('canonical_url') or '', {
                'title': probe.get('title') or parsed.get('title') or '',
                'author': probe.get('author') or parsed.get('author') or '',
                'platform': probe.get('platform') or parsed.get('platform') or '',
                'media_type': probe.get('media_type') or '',
            }, kind='local' if local else (parsed.get('source_kind') or 'url'))
        except Exception:
            pass
        data = dict(source=fetch, kind='local' if local else parsed.get('source_kind') or 'url',
                    title=probe.get('title') or parsed.get('title') or source,
                    author=probe.get('author') or parsed.get('author') or '',
                    platform=probe.get('platform') or parsed.get('platform') or '',
                    probe={'ready': True, **probe}, identity=key,
                    original_url=original, resolved_fetch_url=fetch,
                    canonical_url=probe.get('canonical_url') or '')
        if entry['lane'] == 'publish' and probe.get('media_type') != 'video':
            if alive():
                update(ident, **data, status='rejected', message='这是音频，投稿需要视频' if probe.get('media_type') == 'audio' else '这份内容没有可投稿的视频')
            return
        with LOCK:
            if not alive():
                return
            duplicate = next((e for e in entries() if e['id'] != ident and e.get('identity') == key
                              and e['lane'] == entry['lane'] and e['status'] in BLOCKING), None)
            if duplicate:
                update(ident, **data, status='duplicate', duplicate_of=duplicate['id'], message='已在队列中，未重复创建')
                return
            update(ident, **data, weread_text=weread_text, status='ready', message='待设置' if entry['lane']=='publish' else '待确认档位')
    except Exception as error:
        if not alive():
            return
        message = getattr(error, 'detail', None) or str(error)
        code = getattr(error, 'code', '')
        reason = desktop_sources.refresh_reason(error)
        status = 'rejected' if code in {'invalid_url','unsupported_scheme','private_address'} else 'blocked'
        if _TRACE.search(str(message)) or _URL.search(str(message)):
            message = clean_line(message) or '识别失败，请重试'
        fields = {'status': status, 'message': message or '识别失败，请重试', 'code': code}
        if reason:
            fields['refresh_reason'] = reason
        update(ident, **fields)


def start_notes(ident, run=None):
    entry = get_entry(ident)
    if run is not None and int(entry.get('run') or 1) != int(run):
        return
    if entry.get('status') in {'removed', 'cancelled'}:
        return
    try:
        options = settings_payload(entry.get('execution_options') or get_group(entry['group_id'])['options'])
        options['notes_mode'] = entry.get('execution_mode') or entry.get('notes_mode') or options.get('notes_mode', 'curated')
        options.update(knowledge_only=True, notes_auto=True, rights_confirmed=True,
                       subtitle_output_mode='en_only', bilibili_upload={'enabled': False}, batch_concurrency=2)
        transcript_id = (entry.get('result') or {}).get('transcript_id')
        if transcript_id:
            finish_subtitle(ident, transcript_id, options)
            return
        if entry.get('probe', {}).get('media_type') == 'weread':
            from app import weread
            update(ident, stage='download', message='正在获取微信读书正文')
            book = weread.fetch_book(entry['source'], weread.cookie_header(
                desktop_sources.cookies_for(entry['source'], SESSIONS.get(ident, '')) or ''))
            if get_entry(ident).get('status') in {'removed', 'cancelled'}:
                return
            transcript_id = knowledge.register(Path('weread.txt'), source_kind='url', source=entry['source'],
                                               title=book['title'] or entry['title'], media_type='note', note_body=book['text'])
            finish_subtitle(ident, transcript_id, options)
            return
        if entry.get('probe', {}).get('deferred'):
            update(ident, stage='download', message='正在获取来源信息')
            probe = cache.reused_probe(entry['source']) or desktop_sources.probe(
                entry['source'], entry['kind'], SESSIONS.get(ident, ''))
            entry.update(probe={'ready': True, **probe}, title=probe.get('title') or entry['title'],
                         resolved_fetch_url=probe.get('resolved_fetch_url') or entry['source'])
            update(ident, probe=entry['probe'], title=entry['title'], resolved_fetch_url=entry['resolved_fetch_url'])
        if entry['probe']['media_type'] == 'subtitle':
            transcript_id = knowledge.register(Path(entry['source']), source_kind='subtitle', source=entry['source'], title=entry['title'])
            # A local subtitle has no media job; finish it as a persisted inbox task.
            finish_subtitle(ident, transcript_id, options)
            return
        current = get_entry(ident)
        if run is not None and int(current.get('run') or 1) != int(run):
            return
        if current.get('status') in {'removed', 'cancelled'}:
            return
        batch = jobs.submit_desktop_batch(media.BatchCreateRequest(**options, sources=[source_of(entry, True)]))
        item = batch.items[0]
        if run is not None and int(get_entry(ident).get('run') or 1) != int(run):
            return
        update(ident, batch_id=batch.batch_id, item_id=item.item_id, status='queued', message='已进入笔记队列')
    except Exception as error:
        if run is not None and int(get_entry(ident).get('run') or 1) != int(run):
            return
        update(ident, status='blocked', message=getattr(error,'detail',None) or str(error))


def finish_subtitle(ident, transcript_id, options):
    from app import workbench_notes
    transcript = knowledge.read_transcript(transcript_id)
    _, translate = workbench_notes.language_of({}, transcript)
    result = {'transcript_id': transcript_id}
    if not media.TRANSLATE_API_KEY:
        update(ident, status='blocked', message='请配置 DeepSeek，字幕已导入', result=result)
        return
    if translate:
        get_entry(ident)
        job_dir = media.JOBS_DIR / ('subtitle_' + ident)
        job_dir.mkdir(parents=True, exist_ok=True)
        knowledge.subtitle_file(transcript_id, job_dir/'original.srt')
        job = media.create_stage_job('translate', {'english_srt_url':media.public_file_url(job_dir.name,'original.srt'), 'target_lang':'zh-CN', 'subtitle_output_mode':'bilingual', 'translate_model':options.get('translate_model') or media.TRANSLATE_MODEL})
        update(ident,status='running',stage='translate',progress=40,message='正在生成中文译文',result=result)
        media.run_stage_translate(job.job_id)
        done=media.load_state(job.job_id)
        if done.status!='succeeded':raise ValueError((done.error or {}).get('message') or done.message)
        result.update(done.result or {})
    update(ident,status='running',stage='extract',progress=80,message='正在提取观点',result=result)
    mode=options.get('notes_mode') or 'curated'
    key=cache.digest(['extract-v3',transcript['digest'],transcript['source'],mode,options.get('translate_model') or media.TRANSLATE_MODEL])
    with cache.flight(key):
        if not cache.read(key):
            count=knowledge.generate_cards(transcript_id,media.TRANSLATE_API_KEY,options.get('translate_model') or media.TRANSLATE_MODEL,mode,
                                           progress=lambda value,message:update(ident,progress=80+int(value*.19),message=message))
            cache.save(key,'extract','notes',{'transcript_id':transcript_id,'count':count}, transcript.get('source') or '')
    update(ident,status='succeeded',stage='done',progress=100,message='笔记已完成',result=result)


class GroupEdit(BaseModel):
    options: dict
    overrides: dict = Field(default_factory=dict)
    prepared: list[str] = Field(default_factory=list)
    revision: int


@router.patch('/groups/{ident}')
def edit_group(ident: str, request: GroupEdit):
    with LOCK:
        group = get_group(ident)
        if request.revision != group['revision']:
            raise HTTPException(409, '设置已在其他操作中更新，请重新载入')
        # Validate before saving; full effective per-item settings preserve nested style fields.
        sources=[source_of(e) for e in entries() if e['group_id']==ident and e.get('source') and e['status']!='rejected']
        if not sources:raise HTTPException(400,'本次投递没有可设置的稿件')
        try:
            media.BatchCreateRequest.model_validate({**settings_payload(request.options),'sources':sources})
            for override in request.overrides.values():
                media.BatchCreateRequest.model_validate({**settings_payload(merge(request.options, override)),'sources':sources})
        except ValidationError as error:
            raise HTTPException(422,'；'.join(e['msg'] for e in error.errors())) from error
        group.update(options=request.options, overrides=request.overrides, prepared=request.prepared, revision=group['revision']+1)
        with knowledge.database() as db:
            db.execute('UPDATE workbench_group SET document=? WHERE id=?', (json.dumps(group,ensure_ascii=False),ident))
        return group


class Start(BaseModel):
    entry_ids: list[str] = Field(min_length=1)
    revision: int
    confirmed: bool = False
    notes_mode: Literal['summary', 'curated', 'comprehensive'] | None = None
    restart: bool = False
    entry_revision: int | None = None


@router.post('/groups/{ident}/start')
def start_group(ident: str, request: Start):
    with LOCK:
        group = get_group(ident)
        if group['lane'] == 'notes':
            if not request.confirmed or not request.notes_mode:
                raise HTTPException(400, '请先确认本次整理档位')
            if group['revision'] != request.revision:
                raise HTTPException(409, '设置已变化，请重新确认')
            chosen = [get_entry(i) for i in dict.fromkeys(request.entry_ids)]
            if any(e['group_id'] != ident for e in chosen):
                raise HTTPException(400, '来信不属于本次投递')
            # Claim every task under the same lock before submitting any work.
            # Idempotency survives fast completion, repeated clicks and SSE reentry.
            pending = []
            for entry in chosen:
                if entry.get('execution_mode') and not request.restart:
                    continue
                current = sync(entry, {}) if request.restart else entry
                if current['status'] in {'starting', 'queued', 'running'}:
                    continue
                if request.restart:
                    if current['status'] not in {'succeeded', 'blocked', 'failed', 'cancelled'}:
                        raise HTTPException(409, '当前任务尚未结束')
                    if request.entry_revision != entry['revision']:
                        raise HTTPException(409, '任务已变化，请重新载入')
                    entry.update(result=current.get('result') or {})
                elif entry['status'] != 'ready':
                    raise HTTPException(409, '请先完成来源识别')
                pending.append(entry)
            for entry in pending:
                run = int(entry.get('run') or 1) + (1 if request.restart else 0)
                update(entry['id'], status='starting', stage='download', progress=0,
                       message='正在获取原文', notes_mode=request.notes_mode,
                       execution_mode=request.notes_mode, execution_options=dict(group['options']),
                       run=run, batch_id=None, item_id=None, result=entry.get('result') or {})
            for entry in pending:
                POOL.submit(start_notes, entry['id'], get_entry(entry['id'])['run'])
            return {'entry_ids': [e['id'] for e in chosen]}
        if group['lane'] != 'publish' or not request.confirmed: raise HTTPException(400, '请确认本次投稿')
        if not {'output','style','publish','translation'}.issubset(group['prepared']):raise HTTPException(400, '请先备齐四类设置')
        if group['revision'] != request.revision: raise HTTPException(409, '设置已变化，请重新确认')
        chosen = [get_entry(i) for i in dict.fromkeys(request.entry_ids)]
        if any(e['group_id'] != ident for e in chosen): raise HTTPException(400, '稿件不属于本次投递')
        if all(e.get('batch_id') for e in chosen): return {'batch_ids':list({e['batch_id'] for e in chosen})}
        if any(e['status']!='ready' or e.get('batch_id') for e in chosen): raise HTTPException(409, '只能开始尚未处理的稿件')
        options=settings_payload(group['options'])
        options.update(knowledge_only=False,notes_auto=False,rights_confirmed=True,batch_concurrency=2,
                       publish_confirmed=[e['id'] for e in chosen],sources=[source_of(e) for e in chosen],
                       item_overrides={e['id']:settings_payload(merge(group['options'],group['overrides'].get(e['id'],{}))) for e in chosen})
        for values in [options, *options['item_overrides'].values()]:
            values['bilibili_upload']={**values.get('bilibili_upload',{}),'enabled':True}
        batch=jobs.submit_desktop_batch(media.BatchCreateRequest.model_validate(options))
        for item in batch.items:
            update(item.client_row_id,batch_id=batch.batch_id,item_id=item.item_id,status='queued',message='等待处理')
        return {'batch_ids':[batch.batch_id]}


class Retry(BaseModel):
    upload_checked: bool = False
    session_id: str = Field(default='', max_length=200, exclude=True)


@router.post('/entries/{ident}/cancel-transcription')
def cancel_transcription(ident: str):
    entry = get_entry(ident)
    if not entry.get('batch_id') or not entry.get('item_id'):
        raise HTTPException(409, '当前来信没有可取消的转录')
    _, item = jobs.batch_item(entry['batch_id'], entry['item_id'])
    if item.status != 'running' or item.stage != 'transcribe':
        raise HTTPException(409, '只有正在转录的任务可以取消')
    job_id = (item.stage_jobs or {}).get('transcribe')
    if not job_id or not re.fullmatch(r'[a-zA-Z0-9_-]+', job_id):
        raise HTTPException(409, '转录尚未启动，请稍后重试')
    media.artifact_path(job_id, 'cancel-transcription.requested').write_text(media.now_iso(), encoding='utf-8')
    return {'ok': True, 'message': '正在停止转录，完成后可重试恢复'}


@router.post('/entries/{ident}/retry')
def retry_entry(ident: str, request: Retry):
    session = request.session_id or SESSIONS.get(ident, '')
    if session:
        SESSIONS[ident] = session
    with LOCK:
        entry=get_entry(ident)
        if entry.get('batch_id'):
            jobs.retry(entry['batch_id'],entry['item_id'],request.upload_checked, session)
        else:
            if entry['status'] in {'identifying','starting','running'}: return {'ok': True}
            update(ident,status='identifying',message='重新识别',run=int(entry.get('run') or 1)+1)
            POOL.submit(identify,ident,session)
    return {'ok':True}


def remove_one(ident):
    try:
        stored = get_entry(ident)
    except HTTPException:
        return {'id': ident, 'ok': False, 'kept': True, 'message': '找不到这封信'}
    entry = sync(stored, {})
    if stored.get('status') == 'removed':
        return {'id': ident, 'ok': True, 'status': 'removed', 'cancelled': 0}
    if not can_delete(entry):
        return {'id': ident, 'ok': False, 'kept': True, 'status': entry.get('status'), 'message': delete_reason(entry)}
    cancelled = 0
    if entry.get('status') in {'queued', 'starting'} and stored.get('batch_id') and stored.get('item_id'):
        ok, message = jobs.cancel_queued(stored['batch_id'], stored['item_id'])
        if not ok:
            return {'id': ident, 'ok': False, 'kept': True, 'status': entry.get('status'), 'message': message}
        cancelled = 1
    previous = {key: stored.get(key) for key in ('status', 'message', 'stage', 'progress')}
    changes = {
        'status': 'removed',
        'undo': {'until': clock() + 10, **previous},
        'removed_at': media.now_iso(),
    }
    if stored.get('status') in {'identifying', 'starting'}:
        changes['run'] = int(stored.get('run') or 1) + 1
    update(ident, **changes)
    return {'id': ident, 'ok': True, 'status': 'removed', 'cancelled': cancelled, 'undo_until': changes['undo']['until']}


class Removal(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=300)


@router.post('/entries/remove')
def remove_entries(request: Removal):
    results = []
    cancelled = 0
    for ident in dict.fromkeys(request.ids):
        row = remove_one(ident)
        results.append(row)
        cancelled += int(row.get('cancelled') or 0)
    return {'results': results, 'cancelled': cancelled}


@router.delete('/entries/{ident}')
def remove_entry(ident: str):
    row = remove_one(ident)
    if not row.get('ok'):
        raise HTTPException(409 if row.get('kept') else 404, row.get('message') or '不能删除')
    return row


@router.post('/entries/{ident}/undo')
def undo_entry(ident: str):
    with LOCK:
        entry = get_entry(ident)
        undo = entry.get('undo') or {}
        if entry.get('status') != 'removed' or not undo:
            raise HTTPException(409, '这封信不在可撤销状态')
        if clock() > float(undo.get('until') or 0):
            raise HTTPException(409, '已超过 10 秒，不能撤销')
        restored = {key: undo[key] for key in ('status', 'message', 'stage', 'progress') if key in undo and undo[key] is not None}
        entry.update(restored)
        entry['undo'] = None
        entry['revision'] = int(entry.get('revision') or 1) + 1
        save_entry(entry)
        current = get_entry(ident)
    return sync(current, {})


def _log_lines(entry):
    lines = []
    task = entry.get('task') or {}
    for job_id in (task.get('stage_jobs') or {}).values():
        path = media.stage_progress_log_path(job_id)
        if path.is_file():
            lines.extend(path.read_text(encoding='utf-8', errors='replace').splitlines())
        folder = media.job_dir(job_id) if re.fullmatch(r'[a-zA-Z0-9_-]+', str(job_id)) else None
        if folder is not None:
            for name in ('yt-dlp.err.log', 'yt-dlp.out.log'):
                extra = folder / name
                if extra.is_file():
                    lines.extend(extra.read_text(encoding='utf-8', errors='replace').splitlines())
    return [scrub_log(line) for line in lines if str(line).strip()]


@router.get('/entries/{ident}/log')
def entry_log(ident: str, offset: int = 0, limit: int = 80):
    offset = max(0, offset)
    limit = min(200, max(1, limit))
    entry = sync(get_entry(ident), {})
    lines = _log_lines(entry)
    return {'offset': offset, 'limit': limit, 'total': len(lines), 'lines': lines[offset:offset + limit]}


@router.get('/deliveries/{ident}')
def get_delivery(ident: str):
    return {'group':get_group(ident),'entries':[sync(e,{}) for e in entries() if e['group_id']==ident]}


@router.get('/events')
async def events():
    async def stream():
        previous=''
        while True:
            current=await asyncio.to_thread(snapshot)
            value=json.dumps(current,ensure_ascii=False)
            if value!=previous:
                yield 'data: '+value+'\n\n'
                previous=value
            else:yield ': heartbeat\n\n'
            await asyncio.sleep(1)
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache'})


def import_history():
    seen=set()
    for batch in jobs.stored_batches():
        lane='notes' if batch.request.get('knowledge_only') else 'publish'
        group={'id':batch.batch_id,'lane':lane,'created_at':batch.created_at,'options':batch.request,
               'overrides':batch.request.get('item_overrides',{}),'prepared':[],'revision':0,'legacy':True}
        with knowledge.database() as db:
            db.execute('INSERT OR IGNORE INTO workbench_group VALUES (?,?,?)',(group['id'],'history:'+group['id'],json.dumps(group,ensure_ascii=False)))
        for item in batch.items:
            result=item.result or {}
            if result.get('transcript_id'):seen.add(result['transcript_id'])
            save_entry({'id':'history:'+batch.batch_id+':'+item.item_id,'group_id':batch.batch_id,'lane':lane,
                        'raw':item.source_value,'source':item.source_value,'kind':item.source_kind,'title':item.source_title or item.output_name or '历史稿件',
                        'status':item.status,'batch_id':batch.batch_id,'item_id':item.item_id,'created_at':batch.created_at,
                        'run':1,'revision':1,'original_url':item.source_value,'resolved_fetch_url':item.source_value,
                        'identity':cache.identity(item.source_value),'probe':{'ready':True,'media_type':item.media_type or 'video','platform':item.platform or ''}})
    standalone=[t for t in knowledge.list_transcripts('') if t['id'] not in seen]
    if standalone:
        gid='imported-notes';group={'id':gid,'lane':'notes','created_at':media.now_iso(),'options':default_options(),'overrides':{},'prepared':[],'revision':0,'legacy':True}
        with knowledge.database() as db:db.execute('INSERT OR IGNORE INTO workbench_group VALUES (?,?,?)',(gid,gid,json.dumps(group,ensure_ascii=False)))
        for t in standalone:
            full=knowledge.read_transcript(t['id'])
            save_entry({'id':'transcript:'+str(t['id']),'group_id':gid,'lane':'notes','raw':full['source'],'source':full['source'],
                        'kind':full['source_kind'],'title':full['title'],'status':'succeeded','stage':'done','progress':100,
                        'run':1,'revision':1,'original_url':full['source'],'resolved_fetch_url':full['source'],
                        'message':'已保存的笔记','created_at':t['created_at'],'result':{'transcript_id':t['id']}})
