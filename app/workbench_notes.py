"""Language-aware, checkpointed note completion shared by automatic and manual flows."""
import json
import re
from app import knowledge, desktop_config
from app import main as media
from app import workbench_cache as cache
from app import work_progress as work


def language_of(result, transcript):
    requested = result.get('detected_language')
    if not requested and result.get('english_srt_url'):
        try:
            _, path = media.resolve_local_artifact_from_url(result['english_srt_url'])
            runtime = path.with_name('transcribe_runtime.json')
            if runtime.is_file():
                requested = json.loads(runtime.read_text(encoding='utf-8')).get('language')
        except (OSError, ValueError):
            pass
    text = '\n'.join(c['text'] for c in transcript['cues'])
    cjk = len(re.findall(r'[\u3400-\u9fff]', text))
    # English sentences inside a Chinese transcript still need translation. Product names do not.
    foreign = bool(re.search(r'[A-Za-z]{2,}(?:[ ,]+[A-Za-z]{2,}){3,}|[\u3040-\u30ff\uac00-\ud7af\u0400-\u04ff]', text))
    chinese = requested in {'zh', 'yue'} or (cjk > 0 and not foreign)
    return requested or ('zh' if chinese else 'auto'), bool(text.strip()) and (not chinese or foreign)


def extract_signature(transcript, settings):
    return cache.digest(['extract-v3', transcript['digest'], transcript['source'], settings.get('notes_mode', 'curated'),
                         settings.get('translate_model') or desktop_config.settings().get('ai_model', media.TRANSLATE_MODEL)])


def complete(batch_id, item_id, result, settings, run):
    item = next(i for i in media.load_batch(batch_id).items if i.item_id == item_id)
    execution_id = item.execution_id
    def report(stage, value, message, kind='progress'):
        current = next(i for i in media.load_batch(batch_id).items if i.item_id == item_id)
        detail = {'status': 'succeeded' if kind in {'complete', 'reused', 'skipped'} else 'running',
                  'progress': value, 'message': message, 'reused': kind == 'reused', 'skipped': kind == 'skipped'}
        media.update_batch_item(batch_id, item_id, stage=stage, status='running', message=message,
                                progress=80+round(value*.19) if stage == 'extract' and kind != 'waiting' else None,
                                result=dict(result), stage_details={**current.stage_details, stage: detail},
                                work_event=work.event(stage, value, kind, execution_id))
    transcript_id = result['transcript_id']
    transcript = knowledge.read_transcript(transcript_id)
    _, needs_translation = language_of(result, transcript)
    result['detected_language'], _ = language_of(result, transcript)
    if not transcript['cues'] or not any(c['text'].strip() for c in transcript['cues']):
        result['note_notice'] = '没有可供摘录的正文'
        report('translate', 100, result['note_notice'], 'skipped')
        report('extract', 100, result['note_notice'], 'skipped')
        return
    if needs_translation:
        if not media.TRANSLATE_API_KEY:
            raise ValueError('请在设置中配置 DeepSeek，已有原文已保留')
        from app.desktop_jobs import translation_payload
        run('translate', translation_payload(settings, result, notes=True))
    else:
        report('translate', 100, '中文原文，无需翻译', 'skipped')
    if not media.TRANSLATE_API_KEY:
        raise ValueError('请在设置中配置 DeepSeek，已有原文已保留')
    mode = settings.get('notes_mode', 'curated')
    model = settings.get('translate_model') or desktop_config.settings().get('ai_model', media.TRANSLATE_MODEL)
    signature = extract_signature(transcript, settings)
    def progress(value, message):
        report('extract', value, message)
    with cache.flight(signature, lambda: report('extract', 0, '等待已有观点摘录完成', 'waiting')):
        existing = cache.read(signature)
        if existing:
            result['note_notice'] = '已有观点摘录已保留'
            result['excerpt_reused'] = True
            report('extract', 100, result['note_notice'], 'reused')
        else:
            progress(0, '正在提取观点')
            count = knowledge.generate_cards(transcript_id, media.TRANSLATE_API_KEY, model, mode, progress=progress)
            result['note_notice'] = f'已生成 {count} 条观点' if count else '未找到值得摘录的观点'
            cache.save(signature, 'extract', 'notes', {'transcript_id': transcript_id, 'count': count}, transcript.get('source') or '')
            report('extract', 100, result['note_notice'], 'complete')
