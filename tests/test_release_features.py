"""Tests for Phase C (v0.8.0) & Phase D (v0.9.0) product features."""
import time
from types import SimpleNamespace

from fastapi import HTTPException
import pytest

from app import desktop_config as config
from app import desktop_jobs as jobs
from app import desktop_models
from app import desktop_native
from app import desktop_routes as routes
from app import desktop_sources
from app import knowledge
from app import main as media
from app import workbench_inbox as inbox


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    home = tmp_path / "home"
    data.mkdir()
    home.mkdir()
    monkeypatch.setattr(media, "DATA_DIR", data)
    monkeypatch.setattr(media, "JOBS_DIR", data / "jobs")
    monkeypatch.setattr(media, "BATCHES_DIR", data / "batches")
    for attr, sub in (("PREVIEWS_DIR", "previews"), ("CONTEXTS_DIR", "contexts"), ("COVERS_DIR", "covers")):
        if hasattr(media, attr):
            monkeypatch.setattr(media, attr, data / sub)
    monkeypatch.setattr(config, "HOME", home)
    monkeypatch.setattr(config, "SETTINGS", home / "settings.json")

    class MemoryVault:
        def __init__(self):
            self.store = {}

        def get_password(self, service, name):
            return self.store.get((service, name))

        def set_password(self, service, name, value):
            self.store[(service, name)] = value

        def delete_password(self, service, name):
            self.store.pop((service, name), None)

    monkeypatch.setattr(config, "VAULT", MemoryVault())
    media.ensure_dirs()
    knowledge.initialize()
    inbox.initialize()
    return data, home


def test_publish_local_only_mode_sets_stop_after_burn(isolated_env, monkeypatch):
    monkeypatch.setattr(
        desktop_sources,
        "probe",
        lambda *a, **kw: {"title": "本地出片样本", "media_type": "video", "platform": "YouTube", "has_audio": True},
    )
    captured = []

    def fake_submit(req):
        captured.append(req)
        return SimpleNamespace(batch_id="batch-local", items=[SimpleNamespace(client_row_id=req.sources[0].client_row_id, item_id="item-1")])

    monkeypatch.setattr(jobs, "submit_desktop_batch", fake_submit)
    res = inbox.deliver(inbox.Delivery(request_id="req-local-only", lane="publish", entries=[{"id": "e1", "text": "https://youtu.be/abc123"}]))
    gid = res["group_id"]
    for _ in range(40):
        entry = next(e for e in inbox.entries() if e["group_id"] == gid)
        if entry["status"] == "ready":
            break
        time.sleep(0.05)
    assert entry["status"] == "ready"
    inbox.edit_group(
        gid,
        inbox.GroupEdit(
            revision=0,
            options={"bilibili_upload": {"enabled": False}},
            overrides={},
            prepared=["output", "style", "publish", "translation"],
        ),
    )
    inbox.start_group(gid, inbox.Start(entry_ids=[entry["id"]], revision=1, confirmed=True))
    assert len(captured) == 1
    assert captured[0].bilibili_upload.enabled is False
    assert captured[0].sources[0].stop_after == "burn"

    monkeypatch.setattr(media, "TRANSLATE_API_KEY", "sk-test")
    monkeypatch.setattr(media, "whisper_model_status", lambda _m: {"available": True})
    monkeypatch.setattr(media, "bilibili_configured", lambda: False)
    plan = jobs.plan_batch(captured[0])
    row = plan[captured[0].sources[0].client_row_id]
    assert row["ready"] is True
    assert row["stop_after"] == "burn"
    assert row["planned_stages"] == ["download", "transcribe", "translate", "burn"]


def test_manual_viewpoint_card_create_and_delete(isolated_env):
    data, _ = isolated_env
    srt_file = data / "sample.srt"
    srt_file.write_text("1\n00:00:00,000 --> 00:00:03,000\n第一段测试字幕。\n", encoding="utf-8")
    tid = knowledge.register(srt_file, source_kind="local", source=str(srt_file), title="测试字幕")

    created = routes.add_card(
        tid,
        knowledge.CardText(claim="手动补充的核心洞见", topic="方法论", evidence="来自第一段复盘"),
    )
    card_id = created["created_card_id"]
    assert any(c["id"] == card_id and c["claim"] == "手动补充的核心洞见" and c["topic"] == "方法论" for c in created["cards"])

    after_del = routes.remove_card(tid, card_id)
    assert all(c["id"] != card_id for c in after_del["cards"])

    with pytest.raises(HTTPException) as exc:
        routes.remove_card(tid, card_id)
    assert exc.value.status_code == 404


def test_storage_snapshot_cache_cleanup_and_model_delete(isolated_env):
    data, _ = isolated_env
    preview = data / "previews" / "frame.jpg"
    preview.parent.mkdir(parents=True, exist_ok=True)
    preview.write_bytes(b"x" * 4096)

    model_dir = data / "models" / "faster-whisper-base"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "model.bin").write_bytes(b"0" * 2048)

    snap = routes.storage_info()
    assert snap["cleanable_bytes"] >= 4096
    assert snap["models_bytes"] >= 2048

    cleaned = routes.clean_storage_cache()
    assert cleaned["freed_bytes"] >= 4096
    assert not preview.exists()
    assert (data / "knowledge.sqlite3").exists()

    removed = routes.delete_model("base")
    assert removed["freed_bytes"] >= 2048
    assert not model_dir.exists()
    assert not desktop_models.status(data, "base")["available"]


def test_custom_ai_api_base_validation(isolated_env):
    saved = routes.save_settings(routes.Preferences(ai_api_base="https://api.example.com/v1/"))
    assert saved["ai_api_base"] == "https://api.example.com/v1"
    assert media.TRANSLATE_API_BASE == "https://api.example.com/v1"

    local_saved = routes.save_settings(routes.Preferences(ai_api_base="http://127.0.0.1:11434/v1"))
    assert local_saved["ai_api_base"] == "http://127.0.0.1:11434/v1"

    with pytest.raises(HTTPException) as exc:
        routes.save_settings(routes.Preferences(ai_api_base="http://insecure.example.com/v1"))
    assert exc.value.status_code == 400


def test_open_path_rejects_invalid_artifact_url(isolated_env):
    with pytest.raises(HTTPException) as exc:
        routes.open_local_path(routes.OpenPathRequest(target="artifact", artifact_url="../../Windows/System32/cmd.exe"))
    assert exc.value.status_code == 400


def test_window_bounds_clamp_normal_and_unplugged_monitor():
    monitors = [(0, 0, 1920, 1040)]
    restored = desktop_native.clamp_window_bounds(
        {"x": 120, "y": 80, "width": 1360, "height": 880, "maximized": False}, monitors
    )
    assert restored == {"x": 120, "y": 80, "width": 1360, "height": 880, "maximized": False}

    # Unplugged second monitor (was at x=2400) snaps safely back onto primary monitor.
    recovered = desktop_native.clamp_window_bounds(
        {"x": 2400, "y": 100, "width": 1440, "height": 900, "maximized": True}, monitors
    )
    assert 0 <= recovered["x"] < 1920
    assert 0 <= recovered["y"] < 1040
    assert recovered["width"] <= 1920
    assert recovered["height"] <= 1040
    assert recovered["maximized"] is True

    # Invalid / tiny saved bounds fall back to None.
    assert desktop_native.clamp_window_bounds({"width": 200, "height": 100}, monitors) is None
    assert desktop_native.clamp_window_bounds(None, monitors) is None


def test_taskbar_and_notify_handle_missing_hwnd_safely():
    tb = desktop_native.TaskbarProgress()
    tb.update(None, "normal", 50)
    assert desktop_native.notify_if_unfocused(None, "标题", "内容") is False
    assert desktop_native.notify_if_unfocused(12345, "标题", "") is False
