"""Workflow contracts: receiving, explicit publishing, stage compatibility, notes."""
import json
import time
import os
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi import HTTPException
os.environ['MEDIA_DESKTOP']='1'
from app import main as media, knowledge, desktop_jobs as jobs, desktop_sources
from app import workbench_inbox as inbox, workbench_cache as cache, workbench_notes as notes

@pytest.fixture
def workspace(tmp_path,monkeypatch):
    monkeypatch.setattr(media,'DATA_DIR',tmp_path)
    monkeypatch.setattr(media,'JOBS_DIR',tmp_path/'jobs');media.JOBS_DIR.mkdir()
    monkeypatch.setattr(media,'BATCHES_DIR',tmp_path/'batches');media.BATCHES_DIR.mkdir()
    monkeypatch.setattr(inbox.desktop_config,'settings',lambda:{})
    knowledge.initialize();inbox.initialize()
    # Run identification synchronously while exercising exactly the same receiver.
    monkeypatch.setattr(inbox.POOL,'submit',lambda fn,*a:fn(*a))
    monkeypatch.setattr(desktop_sources,'probe',lambda value,*a:{'title':'测试来信','media_type':'audio' if 'audio' in value else 'video',
        'platform':'来源','has_audio':True,'audio_direct':False,'duration':120})
    return tmp_path

def delivery(lane,values,request_id='delivery'):
    return inbox.deliver(inbox.Delivery(request_id=request_id,lane=lane,entries=[{'id':str(i),'text':v} for i,v in enumerate(values)]))['group_id']

def test_publish_delivery_only_identifies_and_preserves_rejection(workspace,monkeypatch):
    started=[];monkeypatch.setattr(jobs,'submit_desktop_batch',lambda req:started.append(req))
    gid=delivery('publish',['https://example.com/video','https://example.com/audio','不是链接'])
    docs=inbox.get_delivery(gid)['entries']
    assert sorted(e['status'] for e in docs)==['ready','rejected','rejected']
    assert {e['raw'] for e in docs}=={'https://example.com/video','https://example.com/audio','不是链接'}
    assert not started
    assert delivery('publish',['https://example.com/video'])==gid
    assert len(inbox.entries())==3

def test_configuration_revision_and_explicit_start(workspace,monkeypatch):
    gid=delivery('publish',['https://example.com/video'])
    entry=inbox.get_delivery(gid)['entries'][0];group=inbox.get_group(gid)
    with pytest.raises(HTTPException):inbox.start_group(gid,inbox.Start(entry_ids=[entry['id']],revision=0,confirmed=True))
    group=inbox.edit_group(gid,inbox.GroupEdit(options=group['options'],overrides={entry['id']:{'aspect_ratio':'9:16'}},prepared=['output','style','publish','translation'],revision=0))
    with pytest.raises(HTTPException):inbox.edit_group(gid,inbox.GroupEdit(options={},revision=0))
    captured=[]
    def submit(req):
        captured.append(req)
        return SimpleNamespace(batch_id='test',items=[SimpleNamespace(client_row_id=entry['id'],item_id='one')])
    monkeypatch.setattr(jobs,'submit_desktop_batch',submit)
    with pytest.raises(HTTPException):inbox.start_group(gid,inbox.Start(entry_ids=[entry['id']],revision=1,confirmed=False))
    inbox.start_group(gid,inbox.Start(entry_ids=[entry['id']],revision=1,confirmed=True))
    inbox.start_group(gid,inbox.Start(entry_ids=[entry['id']],revision=1,confirmed=True))
    assert len(captured)==1 and captured[0].item_overrides[entry['id']]['aspect_ratio']=='9:16'
    assert captured[0].bilibili_upload.enabled and captured[0].rights_confirmed

def test_notes_start_automatically_and_remain_separate(workspace,monkeypatch):
    calls=[]
    def submit(req):
        calls.append(req);return SimpleNamespace(batch_id='notes',items=[SimpleNamespace(item_id='one')])
    monkeypatch.setattr(jobs,'submit_desktop_batch',submit)
    delivery('publish',['https://example.com/video'],'publish')
    delivery('notes',['https://example.com/video'],'notes')
    assert len(calls)==1 and calls[0].notes_auto and calls[0].knowledge_only
    assert calls[0].sources[0].allow_muxed_audio and not calls[0].bilibili_upload.enabled
    assert len(inbox.entries())==2

def test_signatures_validate_parameters_and_deleted_outputs(workspace):
    source='https://youtube.com/watch?v=abc'
    a={'source_video_url':'/files/one/video.mp4','language':'auto','whisper_model':'small','whisper_inference_mode':'auto'}
    same={**a,'source_video_url':'/files/two/audio.m4a'}
    assert cache.signature('transcribe',source,a)==cache.signature('transcribe','https://youtu.be/abc',same)
    assert cache.signature('transcribe',source,a)!=cache.signature('transcribe',source,{**a,'whisper_model':'medium'})
    job=media.JOBS_DIR/'one';job.mkdir();srt=job/'english.srt';srt.write_text('1\n00:00:00,000 --> 00:00:02,000\nhello\n')
    key=cache.signature('transcribe',source,a)
    cache.save(key,'transcribe','publish',{'english_srt_url':media.public_file_url('one','english.srt')})
    assert cache.read(key)['lane']=='publish'
    srt.unlink();assert cache.read(key) is None

def test_same_stage_concurrent_work_runs_once(workspace):
    calls=[]
    def execute():
        with cache.flight('same'):
            if not cache.read('same'):
                calls.append(1);time.sleep(.02);cache.save('same','metadata','notes',{'value':'done'})
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(lambda _:execute(),range(4)))
    assert len(calls)==1 and not cache.STAGE_LOCKS

@pytest.mark.parametrize('text,language,translate',[
    ('这是一段中文。','zh',False),('Whisper 是一个工具。','zh',False),
    ('这是一段中文。 Make a prediction before you read.','zh',True),('日本語の文章です','ja',True),('Hello world','en',True)])
def test_note_language_branch(text,language,translate):
    assert notes.language_of({'detected_language':language},{'cues':[{'text':text}]})[1] is translate


@pytest.mark.skipif(os.name != "nt", reason="local letters are Windows paths")
def test_paths_are_validated_and_publish_stays_video_only(workspace, monkeypatch):
    from pathlib import Path
    missing = Path(r'D:\missing\no-such-clip.mp4')
    gid = delivery('publish', [str(missing)], 'missing-file')
    assert inbox.get_delivery(gid)['entries'][0]['status'] == 'rejected'
    folder = workspace / 'not-a-file'
    folder.mkdir()
    gid = delivery('publish', [str(folder)], 'directory')
    assert '文件' in inbox.get_delivery(gid)['entries'][0]['message']
    video = workspace / 'my clip.mp4'
    video.write_bytes(b'clip')
    audio = workspace / 'song audio.mp3'
    audio.write_bytes(b'audio')
    subtitle = workspace / 'imported.srt'
    subtitle.write_text('1\n00:00:00,000 --> 00:00:01,000\nhello\n', encoding='utf-8')
    gid = delivery('publish', [str(video), str(audio), str(subtitle)], 'local-lane')
    statuses = {Path(entry['raw']).name: entry['status'] for entry in inbox.get_delivery(gid)['entries']}
    assert statuses == {'my clip.mp4': 'ready', 'song audio.mp3': 'rejected', 'imported.srt': 'rejected'}
    monkeypatch.setattr(media, 'TRANSLATE_API_KEY', '')
    gid = delivery('notes', [str(subtitle)], 'subtitle-note')
    note = inbox.get_delivery(gid)['entries'][0]
    assert note['status'] == 'blocked' and '字幕' in note['message']


def test_reuse_skips_network_and_transcribe_is_not_extract(workspace, monkeypatch):
    source = 'https://www.youtube.com/watch?v=abcdefghijk'
    folder = media.JOBS_DIR / 'reuse1'
    folder.mkdir()
    video = folder / 'source.mp4'
    video.write_bytes(b'1234')
    srt = folder / 'english.srt'
    srt.write_text('1\n00:00:00,000 --> 00:00:01,000\nhello\n', encoding='utf-8')
    media_url = media.public_file_url('reuse1', 'source.mp4')
    cache.save(cache.signature('download', source, {'source_value': source, 'audio_only': False}),
               'download', 'notes',
               {'source_video_url': media_url, 'source_media_url': media_url, 'asset_type': 'video',
                'media_type': 'video', 'has_audio': True, 'audio_direct': True, 'duration': 12, 'title': '已有素材'},
               source)
    cache.save(cache.signature('transcribe', source, {'source_video_url': source, 'language': 'auto',
               'whisper_model': 'small', 'whisper_inference_mode': 'auto'}),
               'transcribe', 'notes', {'english_srt_url': media.public_file_url('reuse1', 'english.srt')}, source)
    assert cache.stage_satisfied(source, 'transcribe') is True
    assert cache.stage_satisfied(source, 'extract') is False
    assert cache.read(cache.signature('transcribe', source, {'source_video_url': source, 'language': 'auto',
                      'whisper_model': 'medium', 'whisper_inference_mode': 'auto'})) is None
    calls = []

    def explode(*args, **kwargs):
        calls.append(args)
        raise AssertionError('network probe')

    monkeypatch.setattr(desktop_sources, 'probe', explode)
    gid = delivery('publish', [source], 'reuse-letter')
    entry = inbox.get_delivery(gid)['entries'][0]
    assert entry['status'] == 'ready' and calls == []
    assert entry['resolved_fetch_url'] == source
    monkeypatch.setattr(media, 'whisper_model_status', lambda model: {'available': True, 'name': model})
    plan = jobs.plan_batch(media.BatchCreateRequest(
        rights_confirmed=True, knowledge_only=True, whisper_model='medium',
        sources=[media.SourceInput(source_kind='url', source_value=source, client_row_id='row',
                                    stop_after='transcribe', allow_muxed_audio=True)],
    ))
    assert plan['row']['ready'] is True and calls == []


def test_legacy_migration_keeps_query_and_does_not_invent_extract(workspace):
    source = 'https://www.xiaohongshu.com/explore/64f0aabbccddeeff00112233?xsec_token=keep'
    folder = media.JOBS_DIR / 'legacyjob'
    folder.mkdir()
    video = folder / 'source.mp4'
    video.write_bytes(b'1234')
    srt = workspace / 'old.srt'
    srt.write_text('1\n00:00:00,000 --> 00:00:01,000\n旧字幕\n', encoding='utf-8')
    key = json.dumps(['url', ['xiaohongshu:64f0aabbccddeeff00112233'], 'zh', 'small', 'auto'], ensure_ascii=False)
    knowledge.register(srt, source_kind='url', source=source, title='旧素材', playable=video,
                       cache_key=key, media_type='video', asset_type='video')
    cache.migrate_legacy()
    cache.migrate_legacy()
    record = cache.source_record(cache.identity(source))
    assert record['metadata']['language'] == 'zh' and record['metadata']['model'] == 'small'
    assert 'xsec_token=keep' in record['fetch_url']
    assert cache.media_ready(source)
    assert cache.stage_satisfied(source, 'extract') is False
    video.unlink()
    assert cache.media_ready(source) is None


def test_delete_undo_queue_race_and_late_identify(workspace, monkeypatch):
    calls = []
    monkeypatch.setattr(jobs, 'enqueue', lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(desktop_sources, 'probe', lambda value, *args, **kwargs: {
        'title': '图', 'media_type': 'note', 'platform': '小红书', 'has_audio': False,
        'audio_direct': False, 'duration': None, 'body': '正文',
    })
    batch = jobs.submit_desktop_batch(media.BatchCreateRequest(
        rights_confirmed=True, knowledge_only=True, subtitle_output_mode='en_only',
        sources=[
            media.SourceInput(source_kind='url', source_value='https://www.xiaohongshu.com/explore/note-running',
                              client_row_id='running', stop_after='download'),
            media.SourceInput(source_kind='url', source_value='https://www.xiaohongshu.com/explore/note-queued',
                              client_row_id='queued', stop_after='download'),
        ],
    ))
    items = {item.client_row_id: item for item in batch.items}
    calls.clear()
    media.update_batch_item(batch.batch_id, items['running'].item_id, status='running', stage='download')
    for key, item in items.items():
        inbox.save_entry({
            'id': key, 'group_id': 'queued-group', 'lane': 'notes', 'raw': item.source_value,
            'source': item.source_value, 'kind': 'url', 'status': 'queued', 'message': '等待处理',
            'batch_id': batch.batch_id, 'item_id': item.item_id, 'run': 1, 'revision': 1,
            'progress': 0, 'created_at': media.now_iso(),
        })
    removed = inbox.remove_entries(inbox.Removal(ids=['running', 'queued']))
    by_id = {row['id']: row for row in removed['results']}
    assert by_id['running']['ok'] is False and by_id['running']['kept'] is True
    assert '不能删除' in by_id['running']['message']
    assert by_id['queued']['ok'] is True and removed['cancelled'] == 1
    assert by_id['queued']['undo_until'] > inbox.clock()
    assert inbox.get_entry('queued')['batch_id'] == batch.batch_id
    assert media.load_batch(batch.batch_id).items[1].status == 'cancelled' or any(
        item.status == 'cancelled' for item in media.load_batch(batch.batch_id).items if item.client_row_id == 'queued')
    ran = []
    monkeypatch.setitem(jobs.RUNNERS, 'download', lambda job_id: ran.append(job_id))
    jobs.run_item(batch.batch_id, items['queued'].item_id)
    assert ran == []
    restored = inbox.undo_entry('queued')
    assert restored['status'] == 'cancelled'
    assert restored['batch_id'] == batch.batch_id
    assert calls == []
    now = {'value': 1_000.0}
    monkeypatch.setattr(inbox, 'clock', lambda: now['value'])
    gid = delivery('publish', ['https://example.com/undo-me'], 'undo-letter')
    letter = inbox.get_delivery(gid)['entries'][0]
    inbox.remove_entry(letter['id'])
    now['value'] = 1_011
    with pytest.raises(HTTPException):
        inbox.undo_entry(letter['id'])
    assert inbox.get_entry(letter['id'])['status'] == 'removed'

    started = []
    monkeypatch.setattr(jobs, 'submit_desktop_batch', lambda request: started.append(request))

    def late(value, *args, **kwargs):
        for entry in inbox.entries():
            if entry.get('status') == 'identifying' and entry.get('raw') == 'https://example.com/late':
                inbox.remove_entry(entry['id'])
        return {'title': '晚到', 'media_type': 'video', 'platform': '来源', 'has_audio': True,
                'audio_direct': True, 'duration': 1}

    monkeypatch.setattr(desktop_sources, 'probe', late)
    delivery('notes', ['https://example.com/late'], 'late-identify')
    assert started == []
    late_entry = next(entry for entry in inbox.entries() if entry.get('raw') == 'https://example.com/late')
    assert late_entry['status'] == 'removed' and late_entry['run'] == 2


def test_retry_refreshes_fetch_url_only_when_media_is_missing(workspace, monkeypatch):
    source = 'https://www.xiaohongshu.com/explore/64f0aabbccddeeff00112233?xsec_token=abc&xsec_source=pc_share'
    monkeypatch.setattr(jobs, 'enqueue', lambda *args, **kwargs: None)
    monkeypatch.setattr(media, 'whisper_model_status', lambda model: {'available': True, 'name': model})
    monkeypatch.setattr(desktop_sources, 'probe', lambda value, *args, **kwargs: {
        'title': '笔记', 'media_type': 'video', 'platform': '小红书', 'has_audio': True,
        'audio_direct': True, 'duration': 8, 'resolved_fetch_url': value,
    })
    batch = jobs.submit_desktop_batch(media.BatchCreateRequest(
        rights_confirmed=True, knowledge_only=True, whisper_model='small',
        sources=[media.SourceInput(source_kind='url', source_value=source, client_row_id='row',
                                    stop_after='transcribe', allow_muxed_audio=True)],
    ))
    item = batch.items[0]
    media.update_batch_item(batch.batch_id, item.item_id, status='failed', stage='download',
                            message='未找到可用的视频流',
                            error={'stage': 'download', 'message': '未找到可用的视频流', 'refresh_reason': 'no_media'})
    calls = []

    def refresh(value, kind='', session='', refresh=False, **kwargs):
        calls.append((value, refresh, session))
        return {'title': '笔记', 'media_type': 'video', 'platform': '小红书', 'has_audio': True,
                'audio_direct': True, 'duration': 8, 'resolved_fetch_url': value}

    monkeypatch.setattr(desktop_sources, 'probe', refresh)
    jobs.retry(batch.batch_id, item.item_id, False, 'temp-session')
    assert calls and calls[0][1] is True and 'xsec_token=abc' in calls[0][0]
    assert calls[0][0] != 'https://www.xiaohongshu.com/explore/64f0aabbccddeeff00112233'
    stored = media.batch_state_path(batch.batch_id).read_text(encoding='utf-8')
    assert 'temp-session' not in stored
    folder = media.JOBS_DIR / 'retrymedia'
    folder.mkdir()
    (folder / 'source.mp4').write_bytes(b'1234')
    cache.save(cache.signature('download', source, {'source_value': source, 'audio_only': False}),
               'download', 'notes',
               {'source_video_url': media.public_file_url('retrymedia', 'source.mp4'),
                'source_media_url': media.public_file_url('retrymedia', 'source.mp4'),
                'asset_type': 'video', 'media_type': 'video', 'has_audio': True, 'duration': 8, 'title': '笔记'},
               source)
    media.update_batch_item(batch.batch_id, item.item_id, status='failed', stage='transcribe', message='转录失败')
    calls.clear()
    jobs.retry(batch.batch_id, item.item_id, False, 'temp-session')
    assert calls == []


def test_snapshot_summary_result_and_paged_log(workspace, monkeypatch):
    gid = delivery('publish', ['https://example.com/video'], 'snapshot')
    entry = inbox.get_delivery(gid)['entries'][0]
    inbox.update(entry['id'], status='running', stage='transcribe', message='https://evil.example/secret Traceback (most recent call last)')
    task = {
        'status': 'running', 'stage': 'transcribe', 'progress': 40, 'local_progress': 0,
        'planned_stages': ['download', 'transcribe', 'burn', 'bilibili_upload'],
        'stage_details': {
            'download': {'status': 'succeeded', 'progress': 100},
            'transcribe': {'status': 'queued', 'progress': 0},
        },
    }
    assert inbox.measured_progress(task, 'publish', 0) == 25
    assert inbox.measured_progress({'status': 'running', 'stage': 'transcribe', 'progress': 15, 'local_progress': 0,
                                     'planned_stages': ['download', 'transcribe'],
                                     'stage_details': {'transcribe': {'status': 'running', 'progress': 0}}}, 'notes', 0) == 0
    shown = {'lane': 'notes', 'status': 'running', 'stage': 'transcribe', 'task': task, 'progress_known': False, 'result': {}}
    assert inbox.summary_of({**shown, 'task': {'stage': 'transcribe', 'planned_stages': ['download', 'transcribe'],
            'stage_details': {'download': {'status': 'succeeded', 'progress': 100},
                              'transcribe': {'status': 'queued', 'progress': 0}}}}) == ['素材已获取，等待转录']
    inbox.update(entry['id'], status='failed', message='ERROR: https://www.xiaohongshu.com/explore/abc?xsec_token=secret\nTraceback')
    failed = next(item for item in inbox.snapshot()['entries'] if item['id'] == entry['id'])
    text = ' '.join(failed['summary'])
    assert 'http' not in text and 'xsec_token' not in text and 'Traceback' not in text
    assert failed['deletable'] is True and failed['run'] >= 1
    folder = media.JOBS_DIR / 'finaljob'
    folder.mkdir()
    (folder / 'final.mp4').write_bytes(b'1234')
    (folder / 'cover.jpg').write_bytes(b'img')
    inbox.update(entry['id'], status='succeeded', stage='done', progress=100, result={
        'title': '实际上传标题', 'bvid': 'BV1test',
        'bilibili_metadata': {'title': '实际上传标题'},
        'final_video_url': media.public_file_url('finaljob', 'final.mp4'),
        'thumbnail': media.public_file_url('finaljob', 'cover.jpg'),
    })
    done = next(item for item in inbox.snapshot()['entries'] if item['id'] == entry['id'])
    assert done['result']['upload_title'] == '实际上传标题'
    assert done['result']['bilibili_url'] == 'https://www.bilibili.com/video/BV1test'
    assert done['result']['cover'].endswith('cover.jpg')
    assert done['result']['final_video_path']
    assert done['summary'] == ['投稿成功，等待审核']
    job = 'joblog1'
    (media.JOBS_DIR / job).mkdir()
    payload = [f'row {index}' for index in range(5)] + ['sessionid=super-secret']
    media.stage_progress_log_path(job).write_text('\n'.join(payload), encoding='utf-8')
    inbox.update(entry['id'], batch_id='', item_id='')
    # A letter without a batch has no stage log. Attach one through a queued note item.
    monkeypatch.setattr(jobs, 'enqueue', lambda *args, **kwargs: None)
    monkeypatch.setattr(desktop_sources, 'probe', lambda value, *args, **kwargs: {
        'title': '图', 'media_type': 'note', 'platform': '小红书', 'has_audio': False, 'audio_direct': False,
    })
    batch = jobs.submit_desktop_batch(media.BatchCreateRequest(
        rights_confirmed=True, knowledge_only=True, subtitle_output_mode='en_only',
        sources=[media.SourceInput(source_kind='url', source_value='https://www.xiaohongshu.com/explore/log-note',
                                    client_row_id='log', stop_after='download')],
    ))
    item = batch.items[0]
    media.update_batch_item(batch.batch_id, item.item_id, stage_jobs={'download': job})
    inbox.save_entry({
        'id': 'log-letter', 'group_id': 'log-group', 'lane': 'notes', 'raw': item.source_value,
        'source': item.source_value, 'kind': 'url', 'status': 'running', 'message': '处理中',
        'batch_id': batch.batch_id, 'item_id': item.item_id, 'run': 1, 'revision': 1,
        'progress': 0, 'created_at': media.now_iso(),
    })
    first = inbox.entry_log('log-letter', offset=0, limit=2)
    second = inbox.entry_log('log-letter', offset=4, limit=2)
    assert first['total'] == 6 and len(first['lines']) == 2 and second['lines']
    assert 'super-secret' not in ''.join(first['lines'] + second['lines'])
    assert 'redacted' in ''.join(second['lines'])


def test_session_stays_out_of_the_letter_and_history_does_not_block_retry(workspace, monkeypatch):
    seen = []

    def probe(value, kind='', session='', **kwargs):
        seen.append(session)
        return {'title': '视频', 'media_type': 'video', 'platform': '来源', 'has_audio': True,
                'audio_direct': True, 'duration': 3}

    monkeypatch.setattr(desktop_sources, 'probe', probe)
    inbox.deliver(inbox.Delivery(request_id='session', lane='publish', entries=[
        {'id': '1', 'text': 'https://example.com/session-check', 'session_id': 'secret-session'},
    ]))
    assert seen == ['secret-session']
    assert 'secret-session' not in json.dumps(inbox.entries(), ensure_ascii=False)
    gid = delivery('publish', ['https://example.com/history'], 'history-a')
    first = inbox.get_delivery(gid)['entries'][0]
    inbox.update(first['id'], status='succeeded', stage='done', progress=100, message='已完成')
    gid = delivery('publish', ['https://example.com/history'], 'history-b')
    second = inbox.get_delivery(gid)['entries'][0]
    assert second['status'] == 'ready'
    inbox.update(second['id'], status='failed', message='转录失败')
    inbox.retry_entry(second['id'], inbox.Retry())
    assert inbox.get_entry(second['id'])['status'] == 'ready'
    gid = delivery('publish', ['https://example.com/same', 'https://example.com/same'], 'active-dup')
    assert sorted(entry['status'] for entry in inbox.get_delivery(gid)['entries']) == ['duplicate', 'ready']
