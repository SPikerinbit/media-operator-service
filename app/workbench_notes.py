"""Language-aware, checkpointed note completion shared by automatic and manual flows."""
import json
from app import knowledge, desktop_config
from app import main as media
from app import workbench_cache as cache
from app import work_progress as work


def language_of(result, transcript):
    from app import note_engine
    requested = result.get('detected_language')
    if not requested and result.get('english_srt_url'):
        try:
            _, path = media.resolve_local_artifact_from_url(result['english_srt_url'])
            runtime = path.with_name('transcribe_runtime.json')
            if runtime.is_file():
                requested = json.loads(runtime.read_text(encoding='utf-8')).get('language')
        except (OSError, ValueError):
            pass
    if isinstance(transcript, dict) and transcript.get('id'):
        profile = note_engine.detect_document_language(transcript['id'], hint=requested or '')
        return profile['lang_code'], profile['lang_class'] != 'zh_native'
    text = '\n'.join(c['text'] for c in (transcript.get('cues') or []))
    needs = bool(text.strip()) and note_engine.is_foreign_span(text)
    return requested or ('auto' if needs else 'zh'), needs


def extract_signature(transcript, settings):
    from app import note_engine
    return cache.digest([
        note_engine.VERSION,
        transcript['digest'],
        transcript['source'],
        settings.get('notes_mode', 'curated'),
        settings.get('translate_model') or desktop_config.settings().get('ai_model', media.TRANSLATE_MODEL),
    ])


def complete(batch_id, item_id, result, settings, run):
    item = next(i for i in media.load_batch(batch_id).items if i.item_id == item_id)
    execution_id = item.execution_id

    def report(stage, value, message, kind='progress'):
        current = next(i for i in media.load_batch(batch_id).items if i.item_id == item_id)
        detail = {
            'status': 'succeeded' if kind in {'complete', 'reused', 'skipped'} else 'running',
            'progress': value,
            'message': message,
            'reused': kind == 'reused',
            'skipped': kind == 'skipped',
        }
        media.update_batch_item(
            batch_id, item_id, stage=stage, status='running', message=message,
            progress=80 + round(value * 0.19) if stage == 'extract' and kind != 'waiting' else None,
            result=dict(result), stage_details={**current.stage_details, stage: detail},
            work_event=work.event(stage, value, kind, execution_id),
        )

    transcript_id = result['transcript_id']
    from app import note_engine
    note_engine.initialize()
    transcript = note_engine.metadata(transcript_id)
    profile = note_engine.detect_document_language(transcript_id, hint=result.get('detected_language') or '')
    result['detected_language'] = profile['lang_code']
    result['language_class'] = profile['lang_class']
    if profile['total_chars'] == 0:
        result['note_notice'] = '没有可供摘录的正文'
        report('translate', 100, result['note_notice'], 'skipped')
        report('extract', 100, result['note_notice'], 'skipped')
        return
    mode = settings.get('notes_mode', 'curated')
    strategy = note_engine.choose_translation_strategy(profile['lang_class'], mode)
    translate_notice = {
        'none': '中文原文，无需翻译',
        'direct_cross_lingual': '直接跨语提炼中文树状摘要（免全文翻译）',
        'cited_only': '跨语精选并仅译核心观点引用原句',
        'foreign_spans_only': '仅译外语片段并缓存复用',
        'full_cached': '分块译文与观点同步处理并缓存',
    }.get(strategy, '译文随正文分块处理并复用')
    report('translate', 100, translate_notice, 'skipped')
    if not media.TRANSLATE_API_KEY:
        raise ValueError('请在设置中配置 DeepSeek，已有原文已保留')
    model = settings.get('translate_model') or desktop_config.settings().get('ai_model', media.TRANSLATE_MODEL)
    signature = extract_signature(transcript, settings)

    def progress(value, message):
        result['note_run'] = note_engine.status(transcript_id)
        report('extract', value, message)

    with cache.flight(signature, lambda: report('extract', 0, '等待已有整理完成', 'waiting')):
        existing = cache.read(signature)
        with knowledge.database() as db:
            mode_ready = db.execute(
                '''SELECT r.id FROM note_active_mode am JOIN note_run r ON am.run=r.id
                   WHERE am.transcript_id=? AND am.mode=? AND r.status='succeeded' AND r.version=? AND r.model=?''',
                (transcript_id, mode, note_engine.VERSION, model),
            ).fetchone()
            active = db.execute(
                'SELECT mode FROM note_run JOIN note_active ON note_run.id=note_active.run WHERE note_active.transcript_id=?',
                (transcript_id,),
            ).fetchone()
        if (existing and (not active or active[0] == mode)) or mode_ready:
            if mode_ready:
                with knowledge.database() as db:
                    db.execute('INSERT OR REPLACE INTO note_active VALUES(?,?)', (transcript_id, mode_ready[0]))
            result['note_notice'] = '已有整理结果已保留'
            result['excerpt_reused'] = True
            report('extract', 100, result['note_notice'], 'reused')
        else:
            progress(0, '正在整理素材')
            count = knowledge.generate_cards(transcript_id, media.TRANSLATE_API_KEY, model, mode, progress=progress)
            if mode == 'summary':
                result['note_notice'] = f'已生成多层级树状摘要（{count} 个节点）' if count else '未找到可摘要正文'
            elif mode == 'curated':
                result['note_notice'] = f'已生成 {count} 条核心观点并同步生成摘要树' if count else '未找到值得摘录的观点'
            else:
                result['note_notice'] = f'已生成 {count} 条观点并并行衍生核心观点与摘要树' if count else '未找到值得摘录的观点'
            cache.save(signature, 'extract', 'notes', {'transcript_id': transcript_id, 'count': count}, transcript.get('source') or '')
            report('extract', 100, result['note_notice'], 'complete')
