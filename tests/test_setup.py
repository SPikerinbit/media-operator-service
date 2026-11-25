from fastapi import HTTPException

from app import desktop_routes


def test_deepseek_probe_checks_the_saved_key(monkeypatch):
    monkeypatch.setattr(desktop_routes.config, "credentials", lambda: {"TRANSLATE_API_KEY": "k"})
    monkeypatch.setattr(desktop_routes.config, "settings", lambda: {"ai_model": "deepseek-chat"})

    class Response:
        status_code = 200

    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: Response())
    assert desktop_routes.test_deepseek() == {"ok": True, "model": "deepseek-chat"}
    monkeypatch.setattr(desktop_routes.config, "credentials", lambda: {"TRANSLATE_API_KEY": ""})
    try:
        desktop_routes.test_deepseek()
    except HTTPException as error:
        assert error.status_code == 400
    else:
        raise AssertionError("expected a missing key")


def test_guide_completion_is_persisted_independently_of_browser_storage(tmp_path, monkeypatch):
    config = desktop_routes.config
    monkeypatch.setattr(config, 'HOME', tmp_path)
    monkeypatch.setattr(config, 'SETTINGS', tmp_path/'settings.json')
    monkeypatch.setattr(config, 'credentials', lambda: {key:'' for key in config.CREDENTIALS})
    desktop_routes.save_settings(desktop_routes.Preferences(onboarding_complete=True))
    assert config.settings()['onboarding_complete'] is True
    assert desktop_routes.settings()['onboarding_complete'] is True


def test_model_download_reports_byte_progress_and_verify_stage(tmp_path):
    import hashlib
    from contextlib import contextmanager
    from app import desktop_models

    payload = b"media-operator-whisper-weights" * 64
    checksum = hashlib.sha256(payload).hexdigest()
    size = len(payload)

    class FakeResponse:
        status_code = 206
        headers = {"Content-Range": f"bytes 0-{size - 1}/{size}"}

        def raise_for_status(self):
            return None

        def iter_raw(self, chunk_size=1024):
            half = size // 2
            yield payload[:half]
            yield payload[half:]

    class FakeClient:
        @contextmanager
        def stream(self, *args, **kwargs):
            yield FakeResponse()

    events = []
    dest = tmp_path / "model.bin"
    desktop_models.download_weights(
        FakeClient(),
        "https://example.com/model.bin",
        dest,
        size,
        checksum,
        lambda pct: None,
        status_cb=lambda pct, downloaded, msg: events.append((pct, downloaded, msg)),
    )
    assert dest.read_bytes() == payload
    assert any(downloaded == size and msg == "正在校验模型完整性…" for _, downloaded, msg in events), events
    assert any(downloaded > 0 and downloaded < size for _, downloaded, _ in events), events


def test_plan_batch_reports_background_model_download_in_progress(tmp_path, monkeypatch):
    from app import desktop_jobs, knowledge, main as media

    monkeypatch.setattr(media, "DATA_DIR", tmp_path)
    knowledge.initialize()
    monkeypatch.setattr(desktop_jobs.desktop_sources, "probe", lambda *a, **kw: {
        "title": "Demo", "platform": "YouTube", "media_type": "video", "duration": 60, "has_audio": True, "audio_direct": True
    })
    monkeypatch.setattr(media, "whisper_model_status", lambda name: {
        "name": name, "available": False, "download": {"running": True, "percent": 42, "message": "正在后台下载 · 42%"}
    })
    req = media.BatchCreateRequest(
        sources=[media.SourceInput(source_kind="youtube", source_value="https://youtu.be/abc12345678", client_row_id="r1", stop_after="transcribe")],
        rights_confirmed=True,
        subtitle_output_mode="en_only",
        whisper_model="small",
    )
    planned = desktop_jobs.plan_batch(req)
    assert planned["r1"]["ready"] is False
    assert "正在后台下载中（42%）" in planned["r1"]["message"], planned
