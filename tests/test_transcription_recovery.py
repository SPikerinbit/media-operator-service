"""Failure paths must terminate native workers and retain useful diagnostics."""
import json
import sys
from types import SimpleNamespace

import pytest

from app import main as media, desktop_config, desktop_routes, site_profiles


@pytest.fixture
def transcription(tmp_path, monkeypatch):
    monkeypatch.setattr(media, 'DESKTOP', True)
    monkeypatch.setattr(media, 'JOBS_DIR', tmp_path)
    monkeypatch.setattr(media, 'whisper_model_status', lambda _: {'available': True})
    monkeypatch.setattr(desktop_config, 'worker_environment', lambda: {
        'WHISPER_DEVICE': 'cuda', 'WHISPER_COMPUTE_TYPE': 'int8_float16', 'MEDIA_GPU_DLL_DIR': 'gpu',
    })
    return tmp_path


def test_gpu_failure_uses_one_fresh_cpu_attempt_and_never_rewinds(transcription, monkeypatch):
    attempts, progress = [], []
    def run(_cmd, **kwargs):
        device = kwargs['env']['WHISPER_DEVICE']
        attempts.append(device)
        callback = kwargs['on_stdout_line']
        callback('WHISPER_PROGRESS\t35\tstarting transcription')
        if device == 'cuda':
            callback('WHISPER_PROGRESS\t65\tpartial segment')
            raise RuntimeError('CUDA failure at inference')
        callback('WHISPER_PROGRESS\t5\tloading CPU model')
        callback('WHISPER_PROGRESS\t100\tcomplete')
        media.artifact_path('recover', 'english.srt').write_text('subtitles', encoding='utf-8')
    monkeypatch.setattr(media, 'run_command_streaming', run)
    media.transcribe_video('recover', transcription/'source.mp4', inference_mode='auto',
                           progress_callback=lambda value, *_: progress.append(value))
    assert attempts == ['cuda', 'cpu']
    assert progress == sorted(progress)
    diagnostic = json.loads(media.artifact_path('recover', 'whisper_gpu_failure.json').read_text(encoding='utf-8'))
    assert diagnostic['device'] == 'cuda' and 'CUDA failure' in diagnostic['error']
    assert diagnostic['phase'] == 'partial segment'


def test_strict_gpu_preserves_failure_and_does_not_use_cpu(transcription, monkeypatch):
    attempts = []
    def fail(_cmd, **kwargs):
        attempts.append(kwargs['env']['WHISPER_DEVICE'])
        raise RuntimeError('CUDA out of memory')
    monkeypatch.setattr(media, 'run_command_streaming', fail)
    with pytest.raises(RuntimeError, match='CUDA out of memory'):
        media.transcribe_video('strict', transcription/'source.mp4', inference_mode='gpu_only')
    assert attempts == ['cuda']
    assert media.artifact_path('strict', 'whisper_gpu_failure.json').is_file()


def test_stalled_gpu_is_stopped_before_cpu_retry(transcription, monkeypatch):
    monkeypatch.setenv('MEDIA_WHISPER_IDLE_TIMEOUT', '-1')
    attempts = []
    def run(_cmd, **kwargs):
        attempts.append(kwargs['env']['WHISPER_DEVICE'])
        if attempts == ['cuda']:
            kwargs['on_tick']()
        else:
            media.artifact_path('stalled', 'english.srt').write_text('subtitles', encoding='utf-8')
    monkeypatch.setattr(media, 'run_command_streaming', run)
    media.transcribe_video('stalled', transcription/'source.mp4', inference_mode='auto')
    assert attempts == ['cuda', 'cpu']
    assert '没有进展' in media.artifact_path('stalled', 'whisper_gpu_failure.json').read_text(encoding='utf-8')


def test_cancellation_does_not_trigger_cpu_fallback(transcription, monkeypatch):
    attempts = []
    def run(_cmd, **kwargs):
        attempts.append(kwargs['env']['WHISPER_DEVICE'])
        media.artifact_path('cancel', 'cancel-transcription.requested').touch()
        kwargs['on_tick']()
    monkeypatch.setattr(media, 'run_command_streaming', run)
    with pytest.raises(RuntimeError, match='转录已取消'):
        media.transcribe_video('cancel', transcription/'source.mp4', inference_mode='auto')
    assert attempts == ['cuda']


def test_heartbeat_reports_device_and_actual_activity_age(transcription, monkeypatch):
    clock = iter([0, 16, 16, 16])
    monkeypatch.setattr(media.time, 'monotonic', lambda: next(clock))
    messages = []
    def run(_cmd, **kwargs):
        kwargs['on_tick']()
        media.artifact_path('heartbeat', 'english.srt').write_text('subtitles', encoding='utf-8')
    monkeypatch.setattr(media, 'run_command_streaming', run)
    media.transcribe_video('heartbeat', transcription/'source.mp4', inference_mode='auto',
                           progress_callback=lambda percent, message, _: messages.append(message))
    heartbeat = json.loads(media.artifact_path('heartbeat', 'whisper_heartbeat.json').read_text(encoding='utf-8'))
    assert heartbeat['idle_seconds'] == 16 and heartbeat['device'] == 'NVIDIA GPU'
    assert '16 秒前' in messages[0]


def test_supervisor_reaps_the_child_when_tick_aborts(tmp_path, monkeypatch):
    import subprocess
    processes = []
    popen = subprocess.Popen
    def start(*args, **kwargs):
        child = popen(*args, **kwargs)
        processes.append(child)
        return child
    monkeypatch.setattr(media.subprocess, 'Popen', start)
    def stop():
        raise RuntimeError('cancel')
    with pytest.raises(RuntimeError, match='cancel'):
        media.run_command_streaming([sys.executable, '-c', 'import time; time.sleep(60)'],
                                    log_dir=tmp_path, on_tick=stop)
    assert processes[0].poll() is not None


@pytest.mark.parametrize('mode', ['summary', 'curated', 'comprehensive'])
def test_generate_passes_each_mode_to_the_model(mode, monkeypatch):
    calls = []
    monkeypatch.setattr(media, 'TRANSLATE_API_KEY', 'test')
    monkeypatch.setattr(desktop_routes, 'transcript_or_404', lambda _: None)
    monkeypatch.setattr(desktop_config, 'settings', lambda: {})
    monkeypatch.setattr(desktop_routes.knowledge, 'generate_cards', lambda *args: calls.append(args) or 0)
    assert desktop_routes.generate(5, desktop_routes.Consent(send_subtitles=True, mode=mode)) == {'added': 0}
    assert calls[0][-1] == mode


def test_expired_cookie_and_incomplete_upload_login_are_not_lit(tmp_path, monkeypatch):
    monkeypatch.setattr(media, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(desktop_config, 'update', lambda *_: None)
    monkeypatch.setattr(site_profiles, '_store_bilibili', lambda _: None)
    site_profiles.write_cookies('douyin', ['.douyin.com\tTRUE\t/\tTRUE\t1\tsessionid\texpired'], True)
    assert site_profiles.status('douyin')['state'] == 'expired'
    site_profiles.write_cookies('bilibili', ['.bilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA\tone'], True)
    assert not site_profiles.status('bilibili')['logged_in']


def test_cancelling_only_targets_the_active_transcription(tmp_path, monkeypatch):
    from app import workbench_inbox as inbox
    monkeypatch.setattr(media, 'JOBS_DIR', tmp_path)
    media.job_dir('stage_transcribe_cancel').mkdir()
    monkeypatch.setattr(inbox, 'get_entry', lambda _: {'batch_id':'batch', 'item_id':'item'})
    item = SimpleNamespace(status='running',stage='transcribe',stage_jobs={'transcribe':'stage_transcribe_cancel'})
    monkeypatch.setattr(inbox.jobs, 'batch_item', lambda *_: (None, item))
    assert inbox.cancel_transcription('letter')['ok']
    assert media.artifact_path('stage_transcribe_cancel', 'cancel-transcription.requested').is_file()
