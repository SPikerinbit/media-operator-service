"""Headless API behavior that must stay true on any platform."""
import pytest
from fastapi.testclient import TestClient

from app import desktop_gpu
from app.defaults import DEFAULT_TRANSLATE_MODEL
from app.desktop_config import _profile_home
from app import main as media


def test_default_translation_model_is_shared():
    assert DEFAULT_TRANSLATE_MODEL == "deepseek-flash"
    assert media.DEFAULT_TRANSLATE_MODEL == "deepseek-flash"


def test_create_job_queues_without_an_undefined_stage(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(media, "BATCHES_DIR", tmp_path / "batches")
    monkeypatch.setattr(media, "PREVIEW_CACHE_DIR", tmp_path / "preview")
    monkeypatch.setattr(media, "TRANSLATION_CONTEXTS_PATH", tmp_path / "contexts.json")
    state = media.create_job(media.VideoJobRequest(
        youtube_url="https://youtu.be/example",
        rights_confirmed=True,
    ))
    assert state.status == "queued"
    assert state.stage == "queued"
    saved = media.load_state(state.job_id)
    assert saved.progress == 0
    assert saved.message == "queued"


def test_gpu_progress_keeps_each_download_index():
    first, second = desktop_gpu.progress_reporter(1, 3), desktop_gpu.progress_reporter(2, 3)
    first(4)
    assert desktop_gpu.PROGRESS["message"] == "正在下载 NVIDIA 运行库 1/3 · 4%"
    second(8)
    assert desktop_gpu.PROGRESS["message"] == "正在下载 NVIDIA 运行库 2/3 · 8%"
    first(6)
    assert desktop_gpu.PROGRESS["message"] == "正在下载 NVIDIA 运行库 1/3 · 6%"


def test_profile_home_does_not_require_localappdata(monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("MEDIA_DESKTOP_HOME", raising=False)
    assert _profile_home() == media.Path.home() / ".media-operator"
    monkeypatch.setenv("MEDIA_DESKTOP_HOME", str(media.Path("/tmp/media-profile")))
    assert _profile_home() == media.Path("/tmp/media-profile")


def test_health_is_open_on_loopback_until_a_token_is_set(monkeypatch):
    monkeypatch.setenv("MEDIA_DESKTOP", "")
    monkeypatch.delenv("MEDIA_API_TOKEN", raising=False)
    client = TestClient(media.app)
    assert client.get("/health").status_code == 200


def test_configured_token_guards_the_headless_api(monkeypatch):
    monkeypatch.setenv("MEDIA_DESKTOP", "")
    monkeypatch.setenv("MEDIA_API_TOKEN", "secret-token")
    client = TestClient(media.app)
    assert client.get("/health").status_code == 401
    assert client.get("/health", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/health", headers={"Authorization": "Bearer secret-token"}).status_code == 200
    assert client.get("/health", headers={"X-Media-Token": "secret-token"}).status_code == 200


def test_desktop_mode_keeps_its_own_session_instead_of_the_api_token(monkeypatch):
    monkeypatch.setenv("MEDIA_DESKTOP", "1")
    monkeypatch.setenv("MEDIA_API_TOKEN", "secret-token")
    client = TestClient(media.app)
    assert client.get("/health").status_code == 200


def test_exposed_bind_requires_a_token(monkeypatch):
    monkeypatch.setenv("MEDIA_DESKTOP", "")
    monkeypatch.delenv("MEDIA_API_TOKEN", raising=False)
    with pytest.raises(SystemExit):
        media.require_token_when_exposed("0.0.0.0")
    media.require_token_when_exposed("127.0.0.1")
    monkeypatch.setenv("MEDIA_API_TOKEN", "secret-token")
    media.require_token_when_exposed("0.0.0.0")
    monkeypatch.setenv("MEDIA_DESKTOP", "1")
    monkeypatch.delenv("MEDIA_API_TOKEN", raising=False)
    media.require_token_when_exposed("0.0.0.0")
