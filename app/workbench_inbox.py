"""Durable two-lane inbox. Receiving a letter never starts a publishing job."""
import asyncio
import json
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from app import knowledge, desktop_jobs as jobs, desktop_sources, desktop_config, share_text
from app import workbench_cache as cache
from app import main as media

router = APIRouter(prefix='/desktop/inbox')
LOCK = threading.RLock()
POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix='letter')


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
    with knowledge.database() as db:
        db.execute('INSERT OR REPLACE INTO workbench_entry VALUES (?,?,?)',
                   (entry['id'], entry['group_id'], json.dumps(entry, ensure_ascii=False)))


def update(ident, **changes):
    with LOCK:
        entry = get_entry(ident)
        entry.update(changes)
        save_entry(entry)
        return entry


def default_options():
    prefs = desktop_config.settings()
    return {**(prefs.get('video_output_defaults') or {}),
            'subtitle_style': prefs.get('video_subtitle_style_defaults') or {},
            'translate_model': prefs.get('ai_model', 'deepseek-flash')}


def merge(base, override):
    result = {**base, **override}
    for key in ('subtitle_style', 'bilibili_upload'):
        result[key] = {**base.get(key, {}), **override.get(key, {})}
    return result


def settings_payload(options):
    options = dict(options)
    upload = dict(options.get('bilibili_upload') or {})
    if isinstance(upload.get('tags'), str):
        import re
        upload['tags'] = [tag.strip() for tag in re.split('[,，\n]', upload['tags']) if tag.strip()]
    if upload.get('tid') == 0: upload['tid'] = None
    options['bilibili_upload'] = upload
    return options


def source_of(entry, notes=False):
    return {'source_kind': entry['kind'], 'source_value': entry['source'],
            'client_row_id': entry['id'], 'source_title': entry.get('title', '')[:500],
            'stop_after': ('download' if entry.get('probe', {}).get('media_type') == 'note' else 'transcribe') if notes else 'bilibili_upload',
            'allow_muxed_audio': True, 'allow_unknown_audio': notes}


def sync(entry, batches):
    if not entry.get('batch_id'): return entry
    try:
        batch = batches.setdefault(entry['batch_id'], None)
        if batch is None:
            batch = jobs.batch_item(entry['batch_id'], entry['item_id'])[0]
            batches[entry['batch_id']] = batch
        item = next(i for i in batch.items if i.item_id == entry['item_id'])
        return {**entry, 'status': item.status, 'title': item.source_title or entry.get('title'),
                'stage': item.stage, 'progress': item.progress, 'message': item.message,
                'task': item.model_dump(), 'result': item.result or {}, 'reuse': (item.result or {}).get('reuse', [])}
    except (OSError, ValueError, StopIteration):
        return {**entry, 'status': 'blocked', 'message': '任务记录不可用，原始输入已保留'}


@router.get('/queue')
def snapshot(lane: Literal['publish', 'notes'] | None = None):
    batches = {}
    return {'groups': [g for g in groups() if not lane or g['lane'] == lane],
            'entries': [sync(e, batches) for e in entries() if not lane or e['lane'] == lane]}


class Letter(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=20000)
    local: bool = False


class Delivery(BaseModel):
    request_id: str = Field(min_length=1, max_length=100)
    lane: Literal['publish', 'notes']
    entries: list[Letter] = Field(min_length=1, max_length=300)


@router.post('/deliveries')
def deliver(request: Delivery):
    with LOCK:
        with knowledge.database() as db:
            existing = db.execute('SELECT id FROM workbench_group WHERE request_id=?', (request.request_id,)).fetchone()
            if existing: return {'group_id': existing[0]}
        ident = str(uuid.uuid4())
        group = {'id': ident, 'lane': request.lane, 'created_at': media.now_iso(), 'options': default_options(),
                 'overrides': {}, 'prepared': [], 'revision': 0}
        with knowledge.database() as db:
            db.execute('INSERT INTO workbench_group VALUES (?,?,?)', (ident, request.request_id, json.dumps(group, ensure_ascii=False)))
            for letter in request.entries:
                entry_id = str(uuid.uuid4())
                entry = {'id': entry_id, 'client_id': letter.id, 'group_id': ident, 'lane': request.lane,
                         'raw': letter.text, 'local': letter.local, 'status': 'identifying', 'message': '正在识别来源',
                         'progress': 0, 'created_at': media.now_iso()}
                db.execute('INSERT INTO workbench_entry VALUES (?,?,?)', (entry_id, ident, json.dumps(entry, ensure_ascii=False)))
        ids = [e['id'] for e in entries() if e['group_id'] == ident]
    for entry_id in ids: POOL.submit(identify, entry_id)
    return {'group_id': ident}


def identify(ident):
    entry = get_entry(ident)
    try:
        if entry.get('local'):
            source = str(media.normalize_local_source_path(entry['raw']))
            parsed = {'url': source, 'source_kind': 'local', 'title': Path(source).name}
        else:
            found = share_text.parse(entry['raw'])
            if len(found) != 1:
                update(ident, status='rejected', message='每行请放一条有效链接或含链接的分享文案')
                return
            parsed = found[0]
            source = parsed['url']
        subtitle = entry.get('local') and Path(source).suffix.lower() in {'.srt', '.vtt'}
        probe = {'title': parsed['title'], 'media_type': 'subtitle', 'platform': '字幕文件', 'has_audio': False} if subtitle else desktop_sources.probe(source, parsed['source_kind'])
        key = cache.identity(source, probe.get('canonical_url'))
        data = dict(source=source, kind=parsed['source_kind'], title=probe.get('title') or parsed.get('title') or source,
                    author=probe.get('author', ''), platform=probe.get('platform', ''), probe={'ready': True, **probe}, identity=key)
        if entry['lane'] == 'publish' and probe.get('media_type') != 'video':
            update(ident, **data, status='rejected', message='这是音频，投稿需要视频' if probe.get('media_type') == 'audio' else '这份内容没有可投稿的视频')
            return
        with LOCK:
            duplicate = next((e for e in entries() if e['id'] != ident and e.get('identity') == key
                              and e['lane'] == entry['lane'] and e['status'] not in {'identifying','rejected','duplicate','removed'}), None)
            if duplicate:
                update(ident, **data, status='duplicate', duplicate_of=duplicate['id'], message='已在队列中，未重复创建')
                return
            update(ident, **data, status='ready' if entry['lane']=='publish' else 'starting', message='待设置' if entry['lane']=='publish' else '准备生成笔记')
        if entry['lane'] == 'notes': start_notes(ident)
    except Exception as error:
        message = getattr(error, 'detail', None) or str(error)
        code = getattr(error, 'code', '')
        status = 'rejected' if code in {'invalid_url','unsupported_scheme','private_address'} else 'blocked'
        update(ident, status=status, message=message or '识别失败，请重试', code=code)


def start_notes(ident):
    entry = get_entry(ident)
    try:
        options = settings_payload(get_group(entry['group_id'])['options'])
        options.update(knowledge_only=True, notes_auto=True, rights_confirmed=True,
                       subtitle_output_mode='en_only', bilibili_upload={'enabled': False}, batch_concurrency=2)
        if entry['probe']['media_type'] == 'subtitle':
            transcript_id = knowledge.register(entry['source'], source_kind='subtitle', source=entry['source'], title=entry['title'])
            # A local subtitle has no media job; finish it as a persisted inbox task.
            finish_subtitle(ident, transcript_id, options)
            return
        batch = jobs.submit_desktop_batch(media.BatchCreateRequest(**options, sources=[source_of(entry, True)]))
        item = batch.items[0]
        update(ident, batch_id=batch.batch_id, item_id=item.item_id, status='queued', message='已进入笔记队列')
    except Exception as error:
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
        entry = get_entry(ident)
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
    key=cache.digest(['extract-v3',transcript['digest'],transcript['source'],'curated',options.get('translate_model') or media.TRANSLATE_MODEL])
    with cache.flight(key):
        if not cache.read(key):
            count=knowledge.generate_cards(transcript_id,media.TRANSLATE_API_KEY,options.get('translate_model') or media.TRANSLATE_MODEL,
                                           progress=lambda value,message:update(ident,progress=80+int(value*.19),message=message))
            cache.save(key,'extract','notes',{'transcript_id':transcript_id,'count':count})
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
        media.BatchCreateRequest.model_validate(settings_payload(request.options))
        for override in request.overrides.values():
            media.BatchCreateRequest.model_validate(settings_payload(merge(request.options, override)))
        group.update(options=request.options, overrides=request.overrides, prepared=request.prepared, revision=group['revision']+1)
        with knowledge.database() as db:
            db.execute('UPDATE workbench_group SET document=? WHERE id=?', (json.dumps(group,ensure_ascii=False),ident))
        return group


class Start(BaseModel):
    entry_ids: list[str] = Field(min_length=1)
    revision: int
    confirmed: bool = False


@router.post('/groups/{ident}/start')
def start_group(ident: str, request: Start):
    with LOCK:
        group = get_group(ident)
        if group['lane'] != 'publish' or not request.confirmed: raise HTTPException(400, '请确认本次投稿')
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


@router.post('/entries/{ident}/retry')
def retry_entry(ident: str, request: Retry):
    with LOCK:
        entry=get_entry(ident)
        if entry.get('batch_id'):
            jobs.retry(entry['batch_id'],entry['item_id'],request.upload_checked)
        else:
            if entry['status'] in {'identifying','starting','running'}: return {'ok': True}
            update(ident,status='identifying',message='重新识别')
            POOL.submit(identify,ident)
    return {'ok':True}


@router.delete('/entries/{ident}')
def remove_entry(ident: str):
    entry=sync(get_entry(ident),{})
    if entry['status'] in {'running','queued','starting','identifying'}:raise HTTPException(409,'处理中的信件暂不能移除')
    update(ident,status='removed',batch_id=None,item_id=None)
    return {'ok':True}


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
                        'identity':cache.identity(item.source_value),'probe':{'ready':True,'media_type':item.media_type or 'video','platform':item.platform or ''}})
    standalone=[t for t in knowledge.list_transcripts('') if t['id'] not in seen]
    if standalone:
        gid='imported-notes';group={'id':gid,'lane':'notes','created_at':media.now_iso(),'options':default_options(),'overrides':{},'prepared':[],'revision':0,'legacy':True}
        with knowledge.database() as db:db.execute('INSERT OR IGNORE INTO workbench_group VALUES (?,?,?)',(gid,gid,json.dumps(group,ensure_ascii=False)))
        for t in standalone:
            full=knowledge.read_transcript(t['id'])
            save_entry({'id':'transcript:'+str(t['id']),'group_id':gid,'lane':'notes','raw':full['source'],'source':full['source'],
                        'kind':full['source_kind'],'title':full['title'],'status':'succeeded','stage':'done','progress':100,
                        'message':'已保存的笔记','created_at':t['created_at'],'result':{'transcript_id':t['id']}})
