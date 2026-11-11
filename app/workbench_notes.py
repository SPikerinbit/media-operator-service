"""Language-aware, checkpointed note completion shared by automatic and manual flows."""
import json
import re
from app import knowledge, desktop_config
from app import main as media
from app import workbench_cache as cache


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


def complete(batch_id, item_id, result, settings, run):
    transcript_id = result['transcript_id']
    transcript = knowledge.read_transcript(transcript_id)
    _, needs_translation = language_of(result, transcript)
    result['detected_language'], _ = language_of(result, transcript)
    if not transcript['cues'] or not any(c['text'].strip() for c in transcript['cues']):
        result['note_notice'] = '没有可供摘录的正文'
        return
    if needs_translation:
        if not media.TRANSLATE_API_KEY:
            raise ValueError('请在设置中配置 DeepSeek，已有原文已保留')
        run('translate', {'english_srt_url': result['english_srt_url'], 'target_lang': 'zh-CN',
                          'translate_model': settings.get('translate_model') or desktop_config.settings().get('ai_model'),
                          'subtitle_output_mode': 'bilingual',
                          'translation_context_note': '保留已经是中文的原句，仅将非中文内容译为中文。',
                          'translation_glossary': settings.get('translation_glossary', '')})
    else:
        current = media.load_batch(batch_id)
        item = next(i for i in current.items if i.item_id == item_id)
        media.update_batch_item(batch_id, item_id, progress=max(item.progress, 78),
                                stage_details={**item.stage_details, 'translate': {'status': 'succeeded', 'progress': 100, 'message': '中文原文，无需翻译', 'skipped': True}})
    if not media.TRANSLATE_API_KEY:
        raise ValueError('请在设置中配置 DeepSeek，已有原文已保留')
    mode = settings.get('notes_mode', 'curated')
    model = settings.get('translate_model') or desktop_config.settings().get('ai_model', media.TRANSLATE_MODEL)
    signature = cache.digest(['extract-v3', transcript['digest'], transcript['source'], mode, model])
    def progress(value, message):
        media.update_batch_item(batch_id, item_id, stage='extract', status='running',
                                progress=80+round(value*.19), message=message, result=dict(result))
    with cache.flight(signature, lambda: progress(0, '等待已有观点摘录完成')):
        existing = cache.read(signature)
        if existing:
            result['note_notice'] = '已有观点摘录已保留'
            result['excerpt_reused'] = True
        else:
            progress(0, '正在提取观点')
            count = knowledge.generate_cards(transcript_id, media.TRANSLATE_API_KEY, model, mode, progress=progress)
            result['note_notice'] = f'已生成 {count} 条观点' if count else '未找到值得摘录的观点'
            cache.save(signature, 'extract', 'notes', {'transcript_id': transcript_id, 'count': count}, transcript.get('source') or '')
    progress(100, result['note_notice'])
