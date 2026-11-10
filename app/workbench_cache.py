"""Persistent source identities and verified, single-flight stage artifacts."""
import hashlib
import json
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, urlencode, urlunsplit

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
            result TEXT NOT NULL, created_at TEXT NOT NULL);
        ''')


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
    clean = {k: v for k, v in payload.items() if k not in {'operator_batch_id', 'operator_item_id', 'title', 'output_name', 'retain_cover', 'allow_muxed_audio', 'rights_confirmed'}}
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
            clean[key] = identity(source)
    return digest(['workbench-v1', stage, identity(source), clean])


def read(key):
    with knowledge.database() as db:
        row = db.execute('SELECT * FROM workbench_artifact WHERE signature=?', (key,)).fetchone()
    if not row:
        return None
    result = json.loads(row['result'])
    required = {'download': 'source_video_url', 'transcribe': 'english_srt_url',
                'translate': 'bilingual_srt_url', 'burn': 'final_video_url'}.get(row['stage'])
    try:
        if required:
            _, path = media.resolve_local_artifact_from_url(result[required])
            if not path.is_file() or not path.stat().st_size:
                return None
            if row['stage'] == 'transcribe':
                knowledge.load_cues(path)
        if row['stage'] == 'extract':
            knowledge.read_transcript(result['transcript_id'])
    except (OSError, ValueError, KeyError):
        return None
    return {'lane': row['lane'], 'result': result}


def save(key, stage, lane, result):
    with knowledge.database() as db:
        db.execute('INSERT OR REPLACE INTO workbench_artifact VALUES (?,?,?,?,?)',
                   (key, stage, lane, json.dumps(result, ensure_ascii=False), media.now_iso()))


@contextmanager
def flight(key, waiting=None):
    with LOCK:
        lock = STAGE_LOCKS.setdefault((str(media.DATA_DIR), key), threading.Lock())
    if not lock.acquire(blocking=False):
        if waiting:
            waiting()
        lock.acquire()
    try:
        yield
    finally:
        lock.release()
