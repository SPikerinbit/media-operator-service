"""Persistent source identities and verified, single-flight stage artifacts."""
import hashlib
import json
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, urlunsplit

from app import knowledge
from app import main as media

LOCK = threading.RLock()
STAGE_LOCKS = {}


def initialize():
    with knowledge.database() as db:
        db.executescript('''
          CREATE TABLE IF NOT EXISTS workbench_alias (url TEXT PRIMARY KEY, identity TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS workbench_artifact (
            signature TEXT PRIMARY KEY, stage TEXT NOT NULL, lane TEXT NOT NULL,
            result TEXT NOT NULL, created_at TEXT NOT NULL, identity TEXT NOT NULL DEFAULT '');
          CREATE TABLE IF NOT EXISTS workbench_source (
            identity TEXT PRIMARY KEY, fetch_url TEXT NOT NULL DEFAULT '',
            original_url TEXT NOT NULL DEFAULT '', canonical_url TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL DEFAULT '', metadata TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL);
        ''')
        columns = {row["name"] for row in db.execute("PRAGMA table_info(workbench_artifact)")}
        if "identity" not in columns:
            db.execute("ALTER TABLE workbench_artifact ADD COLUMN identity TEXT NOT NULL DEFAULT ''")
        db.execute("CREATE INDEX IF NOT EXISTS workbench_artifact_identity ON workbench_artifact(identity)")


def identity(source, canonical=None):
    if canonical:
        key = identity(canonical)
        with knowledge.database() as db:
            db.execute('INSERT OR REPLACE INTO workbench_alias VALUES (?,?)', (source, key))
        return key
    if not source.startswith(('http://', 'https://')):
        path = Path(source).resolve()
        try:
            stat = path.stat()
            return json.dumps([str(path).casefold(), stat.st_size, stat.st_mtime_ns])
        except OSError:
            return str(path).casefold()
    with knowledge.database() as db:
        row = db.execute('SELECT identity FROM workbench_alias WHERE url=?', (source,)).fetchone()
    if row:
        return row[0]
    from app.sites.resolve import identity as resolved
    value = resolved(source)
    url = urlsplit(value)
    host = (url.hostname or '').lower().removeprefix('www.')
    query = parse_qs(url.query)
    if host in {'youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtu.be'}:
        vid = url.path.strip('/') if host == 'youtu.be' else (query.get('v') or [url.path.rsplit('/', 1)[-1]])[0]
        return 'youtube:' + vid
    if host.endswith('bilibili.com') and '/video/' in url.path:
        return 'bilibili:' + url.path.rstrip('/').rsplit('/', 1)[-1] + ':p' + (query.get('p') or ['1'])[0]
    if host.endswith('xiaohongshu.com') and ('/explore/' in url.path or '/discovery/item/' in url.path):
        return 'xiaohongshu:' + url.path.rstrip('/').rsplit('/', 1)[-1]
    if host.endswith('douyin.com') and ('/video/' in url.path or '/note/' in url.path):
        return 'douyin:' + url.path.rstrip('/').rsplit('/', 1)[-1]
    return urlunsplit((url.scheme.lower(), url.netloc.lower(), url.path, url.query, ''))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def signature(stage, source, payload):
    clean = {k: v for k, v in payload.items() if k not in {'operator_batch_id', 'operator_item_id', 'operator_entry_id', 'execution_id', 'title', 'output_name', 'retain_cover', 'allow_muxed_audio', 'rights_confirmed'}}
    # A source artifact's content, not the transient job URL, determines downstream compatibility.
    for key in ('english_srt_url', 'bilingual_srt_url'):
        if clean.get(key):
            try:
                _, path = media.resolve_local_artifact_from_url(clean[key])
                clean[key] = hashlib.sha256(path.read_bytes()).hexdigest()
            except (OSError, ValueError):
                pass
    for key in ('source_video_url', 'source_media_url', 'source_value'):
        if clean.get(key):
            if stage == 'burn' and key == 'source_video_url':
                try:
                    _, path = media.resolve_local_artifact_from_url(clean[key])
                    stat = path.stat()
                    clean['source_media_revision'] = [str(path), stat.st_size, stat.st_mtime_ns]
                except (OSError, ValueError):
                    pass
            clean[key] = identity(source)
    return digest(['workbench-v1', stage, identity(source), clean])


def _files_ok(stage, result):
    required = {'download': 'source_video_url', 'transcribe': 'english_srt_url',
                'translate': 'bilingual_srt_url', 'burn': 'final_video_url'}.get(stage)
    try:
        if required:
            _, path = media.resolve_local_artifact_from_url(result[required])
            if not path.is_file() or not path.stat().st_size:
                return False
            if stage == 'transcribe':
                knowledge.load_cues(path)
        if stage == 'extract':
            knowledge.read_transcript(result['transcript_id'])
    except (OSError, ValueError, KeyError, FileNotFoundError):
        return False
    return True


def read(key):
    with knowledge.database() as db:
        row = db.execute('SELECT * FROM workbench_artifact WHERE signature=?', (key,)).fetchone()
    if not row:
        return None
    result = json.loads(row['result'])
    if not _files_ok(row['stage'], result):
        return None
    return {'lane': row['lane'], 'result': result}


def save(key, stage, lane, result, source=None):
    ident = identity(source) if source else ''
    with knowledge.database() as db:
        if not ident:
            row = db.execute('SELECT identity FROM workbench_artifact WHERE signature=?', (key,)).fetchone()
            ident = (row['identity'] if row else '') or ''
        db.execute('''INSERT OR REPLACE INTO workbench_artifact
                      (signature, stage, lane, result, created_at, identity) VALUES (?,?,?,?,?,?)''',
                   (key, stage, lane, json.dumps(result, ensure_ascii=False), media.now_iso(), ident))


def _prefer_fetch(old, new):
    from urllib.parse import urlsplit
    if new and urlsplit(new).query and not urlsplit(old or '').query:
        return new
    return old or new or ''


def remember_source(fetch_url, original_url='', canonical_url='', metadata=None, kind=''):
    """Idempotent source relation. The canonical value is stored beside the fetch URL, never instead of it."""
    if not fetch_url:
        return ''
    ident = identity(fetch_url, canonical_url or None)
    if original_url and original_url != fetch_url:
        identity(original_url, canonical_url or None)
    current = source_record(ident) or {}
    merged = dict(current.get('metadata') or {})
    for key, value in (metadata or {}).items():
        if value not in (None, ''):
            merged[key] = value
    fetch = _prefer_fetch(current.get('fetch_url') or '', fetch_url)
    original = _prefer_fetch(current.get('original_url') or '', original_url or fetch_url)
    canonical = canonical_url or current.get('canonical_url') or ''
    with knowledge.database() as db:
        db.execute('''INSERT OR REPLACE INTO workbench_source
                      (identity, fetch_url, original_url, canonical_url, kind, metadata, updated_at)
                      VALUES (?,?,?,?,?,?,?)''',
                   (ident, fetch, original, canonical, kind or current.get('kind') or '',
                    json.dumps(merged, ensure_ascii=False), media.now_iso()))
    return ident


def source_record(ident):
    with knowledge.database() as db:
        row = db.execute('SELECT * FROM workbench_source WHERE identity=?', (ident,)).fetchone()
    if not row:
        return None
    try:
        metadata = json.loads(row['metadata'] or '{}')
    except ValueError:
        metadata = {}
    return {'identity': row['identity'], 'fetch_url': row['fetch_url'], 'original_url': row['original_url'],
            'canonical_url': row['canonical_url'], 'kind': row['kind'], 'metadata': metadata}


def verified(source, stage=None):
    ident = identity(source)
    with knowledge.database() as db:
        if stage:
            rows = db.execute('SELECT * FROM workbench_artifact WHERE identity=? AND stage=?', (ident, stage)).fetchall()
        else:
            rows = db.execute('SELECT * FROM workbench_artifact WHERE identity=?', (ident,)).fetchall()
    found = []
    for row in rows:
        try:
            result = json.loads(row['result'])
        except ValueError:
            continue
        if _files_ok(row['stage'], result):
            found.append({'signature': row['signature'], 'stage': row['stage'], 'lane': row['lane'], 'result': result})
    return found


def stage_satisfied(source, stage):
    """A finished transcribe artifact does not satisfy extract."""
    return bool(verified(source, stage))


def media_ready(source):
    found = verified(source, 'download')
    return found[0] if found else None


def reused_probe(source):
    found = media_ready(source)
    if not found:
        return None
    result = found['result']
    record = source_record(identity(source)) or {}
    meta = record.get('metadata') or {}
    # The source's media type outranks an extracted audio file. A transcript is not a note.
    media_type = result.get('media_type') or meta.get('media_type') or result.get('asset_type') or 'video'
    if media_type not in {'audio', 'video', 'note', 'unknown'}:
        media_type = 'video'
    return {
        'title': result.get('title') or meta.get('title') or '',
        'platform': meta.get('platform') or result.get('platform') or '',
        'media_type': media_type,
        'has_audio': bool(result.get('has_audio', media_type != 'note')),
        'audio_direct': bool(result.get('audio_direct', False)),
        'duration': result.get('duration') if result.get('duration') is not None else meta.get('duration'),
        'description': result.get('original_description') or result.get('description') or '',
        'body': result.get('body') or '',
        'author': result.get('author') or meta.get('author') or '',
        'canonical_url': record.get('canonical_url') or '',
        'resolved_fetch_url': record.get('fetch_url') or source,
        'original_url': record.get('original_url') or source,
        'reused_local': True,
    }


def migrate_legacy():
    """Backfill source relations and verified artifacts. Safe to run more than once."""
    try:
        from app import desktop_jobs as jobs
        batches = jobs.stored_batches()
    except Exception:
        batches = []
    for batch in batches:
        lane = 'notes' if (batch.request or {}).get('knowledge_only') else 'publish'
        for item in batch.items:
            try:
                _adopt_item(batch, item, lane)
            except Exception:
                continue
    try:
        transcripts = knowledge.list_transcripts('')
    except Exception:
        transcripts = []
    for row in transcripts:
        try:
            _adopt_transcript(row['id'])
        except Exception:
            continue


def _public_job_file(path):
    file = Path(path)
    if not file.is_file() or not file.stat().st_size:
        return ''
    try:
        relative = file.resolve().relative_to(media.JOBS_DIR.resolve())
    except (OSError, ValueError):
        return ''
    if not relative.parts:
        return ''
    return media.public_file_url(relative.parts[0], file.name)


def _adopt_item(batch, item, lane):
    source = item.source_value or ''
    if not source:
        return
    settings = media.batch_item_settings(batch.request or {}, item)
    remember_source(source, source, '', {
        'title': item.source_title or '', 'platform': item.platform or '',
        'media_type': item.media_type or '', 'language': settings.get('source_language') or '',
        'model': settings.get('whisper_model') or '', 'inference': settings.get('whisper_inference_mode') or '',
        'kind': item.source_kind or '',
    }, kind=item.source_kind or '')
    result = dict(item.result or {})
    if result.get('source_video_url') and _files_ok('download', result):
        payload = {'source_kind': item.source_kind, 'source_value': source,
                   'resolution': settings.get('resolution'), 'fps': settings.get('fps'),
                   'audio_only': False, 'managed': item.planned_stages is not None}
        result.setdefault('resolution', settings.get('resolution'))
        result.setdefault('fps', settings.get('fps'))
        save(signature('download', source, payload), 'download', lane, result, source)
    if result.get('english_srt_url') and _files_ok('transcribe', result):
        payload = {'source_video_url': source, 'language': settings.get('source_language') or 'auto',
                   'whisper_model': settings.get('whisper_model') or '',
                   'whisper_inference_mode': settings.get('whisper_inference_mode') or 'auto'}
        save(signature('transcribe', source, payload), 'transcribe', lane, result, source)
    if result.get('bilingual_srt_url') and _files_ok('translate', result):
        save(signature('translate', source, {'english_srt_url': result.get('english_srt_url'),
             'target_lang': settings.get('target_lang'), 'translate_model': settings.get('translate_model')}),
             'translate', lane, result, source)
    if result.get('final_video_url') and _files_ok('burn', result):
        save(signature('burn', source, {'source_video_url': source, 'final_video_url': result.get('final_video_url')}),
             'burn', lane, result, source)


def _adopt_transcript(transcript_id):
    record = knowledge.read_transcript(transcript_id)
    source = record.get('source') or ''
    if not source:
        return
    language = model = ''
    try:
        parsed = json.loads(record.get('cache_key') or '')
        if isinstance(parsed, list) and len(parsed) >= 4:
            language, model = parsed[2], parsed[3]
    except (TypeError, ValueError):
        pass
    remember_source(source, source, '', {
        'title': record.get('title') or '', 'kind': record.get('source_kind') or '',
        'media_type': record.get('media_type') or '', 'language': language, 'model': model,
    }, kind=record.get('source_kind') or '')
    playable = _public_job_file(record.get('playable') or '')
    if playable:
        result = {'source_video_url': playable, 'source_media_url': playable,
                  'title': record.get('title') or '', 'has_audio': record.get('media_type') != 'note',
                  'media_type': record.get('media_type') or record.get('asset_type') or 'video',
                  'asset_type': record.get('asset_type') or record.get('media_type') or 'video'}
        if record.get('media_type') == 'note':
            result['body'] = record.get('note_body') or ''
        save(signature('download', source, {'source_kind': record.get('source_kind'), 'source_value': source,
             'audio_only': False}), 'download', 'notes', result, source)
    cards = record.get('cards') or []
    if cards and model:
        # Viewpoint reuse follows an extract artifact. A transcript alone is not one.
        key = digest(['extract-v3', record.get('digest'), source, 'curated', model])
        save(key, 'extract', 'notes', {'transcript_id': transcript_id, 'count': len(cards)}, source)


@contextmanager
def flight(key, waiting=None):
    with LOCK:
        identity_key = (str(media.DATA_DIR), key)
        state = STAGE_LOCKS.setdefault(identity_key, [threading.Lock(), 0])
        state[1] += 1
        lock = state[0]
    if not lock.acquire(blocking=False):
        if waiting:
            waiting()
        lock.acquire()
    try:
        yield
    finally:
        lock.release()
        with LOCK:
            state[1] -= 1
            if not state[1]:STAGE_LOCKS.pop(identity_key, None)
