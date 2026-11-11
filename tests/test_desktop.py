
"""Windows desktop integration tests. Media binaries are optional for the unit tests."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
import time
import sqlite3

from fastapi.testclient import TestClient
import httpx
import pytest

if os.name != "nt":
    pytest.skip("Windows desktop tests", allow_module_level=True)

os.environ["MEDIA_DESKTOP"] = "1"

from app import desktop, desktop_routes, desktop_jobs, knowledge
from app import main as media

ORIGIN = "http://127.0.0.1:9810"


def test_legacy_card_migration_preserves_ids_and_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "DATA_DIR", tmp_path)
    with sqlite3.connect(tmp_path / "knowledge.sqlite3") as db:
        db.execute("""CREATE TABLE card(id INTEGER PRIMARY KEY, transcript_id INTEGER NOT NULL,
                   claim TEXT, evidence TEXT, example TEXT, refs TEXT, origin_key TEXT,
                   UNIQUE(transcript_id, origin_key))""")
        db.execute("INSERT INTO card VALUES(42,1,'edited','evidence','','[1]','legacy-id')")
    knowledge.initialize()
    knowledge.initialize()
    with knowledge.database() as db:
        row = dict(db.execute("SELECT * FROM card WHERE id=42").fetchone())
        assert row["claim"] == "edited" and row["origin_key"] == "legacy-id"
        assert row["quote_translation"] == ""
    with sqlite3.connect(tmp_path / "knowledge.before-0.3.0.sqlite3") as backup:
        assert "quote_translation" not in {row[1] for row in backup.execute("PRAGMA table_info(card)")}
        assert backup.execute("SELECT claim FROM card WHERE id=42").fetchone()[0] == "edited"


def test_legacy_transcript_media_fields_preserve_source_and_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "DATA_DIR", tmp_path)
    with sqlite3.connect(tmp_path / "knowledge.sqlite3") as db:
        db.execute("""CREATE TABLE transcript(id INTEGER PRIMARY KEY, title TEXT, source_kind TEXT,
                      source TEXT, cache_key TEXT, digest TEXT, playable TEXT, created_at TEXT,
                      UNIQUE(source, digest))""")
        db.execute("INSERT INTO transcript VALUES(11,'saved title','youtube','https://youtu.be/example',NULL,'hash',NULL,'')")
    knowledge.initialize()
    knowledge.initialize()
    transcript = knowledge.read_transcript(11)
    assert transcript["title"] == "saved title" and transcript["source"] == "https://youtu.be/example"
    assert transcript["media_type"] is None and transcript["asset_type"] is None
    with sqlite3.connect(tmp_path / "knowledge.before-0.4.0.sqlite3") as backup:
        assert "asset_type" not in {row[1] for row in backup.execute("PRAGMA table_info(transcript)")}
        assert backup.execute("SELECT title FROM transcript WHERE id=11").fetchone()[0] == "saved title"


@pytest.fixture(scope="module")
def desktop_app(tmp_path_factory):
    root = tmp_path_factory.mktemp("desktop")
    patch = pytest.MonkeyPatch()
    for name, path in {
        "DATA_DIR": root, "JOBS_DIR": root / "jobs", "BATCHES_DIR": root / "batches",
        "PREVIEW_CACHE_DIR": root / "preview", "TRANSLATION_CONTEXTS_PATH": root / "contexts.json",
    }.items():
        patch.setattr(media, name, path)
    patch.setattr(desktop_routes, "sync_credentials", lambda: None)
    patch.setattr(desktop_routes.config, "settings", lambda: {})
    with TestClient(desktop.application(ORIGIN, "test-session"), base_url=ORIGIN) as client:
        assert client.get("/media-ui").status_code == 403
        assert client.get("/desktop/connect?token=wrong").status_code == 403
        assert client.get("/desktop/connect?token=test-session", follow_redirects=False).status_code == 303
        assert client.get("/media-ui").status_code == 200
        assert client.post("/desktop/gpu", headers={"Origin": "https://example.test"}).status_code == 403
        assert client.get("/desktop/knowledge", headers={"Host": "example.test"}).status_code == 403
        client.headers["Origin"] = ORIGIN
        yield client, root
    patch.undo()


def test_knowledge_workflow(desktop_app, monkeypatch):
    client, root = desktop_app
    subtitle = root / "播客 测试.vtt"
    subtitle.write_text("WEBVTT\n\n00:00:01.250 --> 00:00:02.750\n复习方法：间隔学习。\n\n"
                        "00:00:03.000 --> 00:00:05.000\nPractice recalling the answer.\n", encoding="utf-8-sig")
    payload = {"kind": "local", "source": str(subtitle), "rights_confirmed": True}
    response = client.post("/desktop/knowledge/import", json=payload)
    assert response.status_code == 200, response.text
    transcript = response.json()["transcript_id"]
    assert client.post("/desktop/knowledge/import", json=payload).json()["transcript_id"] == transcript
    for term in ("间隔", "间隔学习", "recalling"):
        assert [entry["id"] for entry in client.get("/desktop/knowledge", params={"q": term}).json()] == [transcript]

    route = f"/desktop/knowledge/{transcript}"
    assert client.post(route + "/generate", json={}).status_code == 400
    assert client.post(route + "/generate", json={"send_subtitles": True}).status_code == 400
    real_client = httpx.Client

    def fake_model(request):
        nonlocal ref
        body = json.loads(request.content)
        sent = json.loads(body["messages"][1]["content"])
        assert sent[0]["text"].startswith("复习方法")
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
            "cards": [{"claim": "使用间隔复习", "evidence": "按间隔安排学习", "refs": [ref]}],
        })}}]})

    ref = 1
    monkeypatch.setattr(media, "TRANSLATE_API_KEY", "test")
    monkeypatch.setattr(knowledge, "httpx", SimpleNamespace(
        Client=lambda **kwargs: real_client(transport=httpx.MockTransport(fake_model), **kwargs),
    ))
    assert client.post(route + "/generate", json={"send_subtitles": True}).json() == {"added": 1}
    data = client.get(route).json()
    assert data["cues"][0]["start_ms"] == 1250
    assert data["cards"][0]["refs"] == [1]
    card = data["cards"][0]["id"]
    assert client.put(route + f"/cards/{card}", json={"claim": "我编辑的观点"}).status_code == 200
    assert client.post(route + "/generate", json={"send_subtitles": True}).json() == {"added": 0}
    ref = 999
    assert client.post(route + "/generate", json={"send_subtitles": True}).status_code == 502
    assert client.get(route).json()["cards"][0]["claim"] == "我编辑的观点"
    destination = root / "观点.md"
    assert client.post("/desktop/export", json={
        "format": "markdown", "transcript_id": transcript, "destination": str(destination),
    }).status_code == 200
    exported = destination.read_text(encoding="utf-8")
    assert "我编辑的观点" in exported and "00:00:01.250" in exported and "间隔学习" in exported


def test_save_deepseek_with_unavailable_vault(desktop_app, monkeypatch):
    client, root = desktop_app
    config = desktop_routes.config
    settings_file = root / "settings-test.json"
    stale_vault = str(root / "disconnected")
    settings_file.write_text(json.dumps({"obsidian_vault": stale_vault}), encoding="utf-8")
    keychain = {}
    monkeypatch.setattr(config, "HOME", root)
    monkeypatch.setattr(config, "SETTINGS", settings_file)
    monkeypatch.setattr(config, "settings", lambda: json.loads(settings_file.read_text(encoding="utf-8")))
    monkeypatch.setattr(config, "VAULT", SimpleNamespace(
        get_password=lambda _service, name: keychain.get(name),
        set_password=lambda _service, name, value: keychain.__setitem__(name, value),
        delete_password=lambda _service, name: keychain.pop(name),
    ))
    monkeypatch.setattr(media, "TRANSLATE_MODEL", media.TRANSLATE_MODEL)
    saved = client.put("/desktop/settings", json={"ai_model": "deepseek-flash", "secrets": {"TRANSLATE_API_KEY": "fake-key"}})
    assert saved.status_code == 200 and saved.json()["has_ai_key"]
    assert saved.json()["obsidian_vault"] == stale_vault
    assert "fake-key" not in saved.text and "fake-key" not in settings_file.read_text(encoding="utf-8")
    assert media.TRANSLATE_MODEL == "deepseek-flash"
    assert client.put("/desktop/settings", json={"ai_model": "deepseek-flash"}).json()["has_ai_key"]
    assert not client.put("/desktop/settings", json={"secrets": {"TRANSLATE_API_KEY": ""}}).json()["has_ai_key"]


def test_supported_video_links():
    assert media.video_url_kind("https://youtu.be/jNQXAC9IVRw") == "youtube"
    assert media.video_url_kind("https://www.bilibili.com/video/BV1pJ411X7mA/") == "bilibili"
    assert media.video_url_kind("https://b23.tv/example") == "bilibili"
    assert media.video_url_kind("https://youtube.com.example.org/watch?v=jNQXAC9IVRw") is None
    assert media.video_url_kind("https://bilibili.com@example.org/video/BV1pJ411X7mA/") is None


def test_preview_uses_system_proxy_and_hides_console(desktop_app, monkeypatch):
    client, root = desktop_app
    proxy = "http://127.0.0.1:8123"
    monkeypatch.setattr(media, "YT_DLP_PROXY", "")
    monkeypatch.setattr(media.urllib_request, "getproxies_registry", lambda: {"https": proxy})
    monkeypatch.setattr(media.urllib_request, "proxy_bypass_registry", lambda _host: False)
    details = "WinError 10061: Failed to establish a new connection"

    def refuse(cmd, **options):
        assert cmd[cmd.index("--proxy") + 1] == proxy
        assert options["creationflags"] == media.subprocess.CREATE_NO_WINDOW
        return SimpleNamespace(returncode=1, stderr=details)

    monkeypatch.setattr(media.subprocess, "run", refuse)
    response = client.post("/ui/preview-frame", json={
        "source_kind": "youtube", "source_value": "https://youtu.be/preview-test",
    })
    assert not response.is_success
    assert "Windows 系统代理" in response.json()["detail"]
    assert "10061" not in response.json()["detail"]
    assert any(details in path.read_text(encoding="utf-8") for path in (root / "preview").glob("*.log"))


def wait_batch(client, batch_id):
    for _ in range(200):
        data = client.get(f"/ui/batches/{batch_id}").json()
        if data["status"] in {"failed", "succeeded"}:
            return data
        time.sleep(0.05)
    pytest.fail("batch did not settle")


def test_managed_batch_plans_each_source_and_confirms_exact_uploads(desktop_app, monkeypatch):
    from app import desktop_sources

    client, _ = desktop_app
    sources = [
        {"source_kind": "url", "source_value": f"https://example.org/{row}",
         "stop_after": stop, "client_row_id": row}
        for row, stop in (("download", "download"), ("audio", "bilibili_upload"), ("sub", "transcribe"),
                          ("translate", "translate"), ("burn", "burn"), ("publish", "bilibili_upload"),
                          ("muxed", "transcribe"), ("broken", "burn"))
    ]

    def probe(value, *_args):
        name = value.rsplit("/", 1)[-1]
        if name == "broken":
            raise desktop_sources.SourceError("no_stream", "媒体不可用")
        return {"title": name, "media_type": "audio" if name == "audio" else "video",
                "platform": "fixture", "has_audio": True, "audio_direct": name != "muxed"}

    calls = []

    def runner(stage):
        def run(job_id):
            request = media.load_state(job_id).request
            batch, item = desktop_jobs.batch_item(request["operator_batch_id"], request["operator_item_id"])
            calls.append((item.client_row_id, stage))
            filename = "english.srt" if stage == "transcribe" else "artifact"
            result = {"bvid": "mock"} if stage == "bilibili_upload" else {
                desktop_jobs.OUTPUTS[stage]: media.public_file_url(job_id, filename),
            }
            media.artifact_path(job_id, filename).write_bytes(b"1\n00:00:00,100 --> 00:00:02,000\nWords.\n")
            if stage == "download":
                result["asset_type"] = "audio" if request["audio_only"] else "video"
            if stage == "bilibili_upload":
                assert request["upload_settings"]["enabled"]
            media.report_stage_progress(job_id, stage, 100, "done", status="succeeded", force=True, result=result)
        return run

    monkeypatch.setattr(desktop_sources, "probe", probe)
    monkeypatch.setattr(media, "whisper_model_status", lambda _: {"available": True})
    monkeypatch.setattr(media, "TRANSLATE_API_KEY", "mock")
    monkeypatch.setattr(media, "bilibili_configured", lambda: True)
    for stage in desktop_jobs.RUNNERS:
        monkeypatch.setitem(desktop_jobs.RUNNERS, stage, runner(stage))

    payload = {"rights_confirmed": True, "sources": sources, "subtitle_output_mode": "en_only",
               "bilibili_upload": {"tid": 201, "copyright": 1}}
    check = client.post("/desktop/batches/preflight", json=payload).json()
    assert check["download"]["planned_stages"] == ["download"]
    assert check["audio"]["planned_stages"] == check["sub"]["planned_stages"] == ["download", "transcribe"]
    assert check["translate"]["planned_stages"] == ["download", "transcribe", "translate"]
    assert check["burn"]["planned_stages"] == ["download", "transcribe", "burn"]
    assert check["publish"]["planned_stages"][-1] == "bilibili_upload"
    assert check["muxed"]["code"] == "muxed_audio" and check["broken"]["code"] == "no_stream"
    assert client.post("/ui/batches", json=payload).status_code == 409
    payload["sources"] = [row for row in sources if check[row["client_row_id"]]["ready"]]
    assert client.post("/ui/batches", json={**payload, "publish_confirmed": ["audio", "publish"]}).status_code == 409
    response = client.post("/ui/batches", json={**payload, "publish_confirmed": ["publish"]})
    assert response.is_success, response.text
    batch = wait_batch(client, response.json()["batch_id"])
    assert batch["status"] == "succeeded", batch
    assert [row for row, stage in calls if stage == "bilibili_upload"] == ["publish"]
    original = next(item for item in batch["items"] if item["client_row_id"] == "sub")
    followup = client.post("/ui/batches", json={**payload, "sources": [{
        **sources[2], "stop_after": "burn", "continue_from": [batch["batch_id"], original["item_id"]],
    }]})
    assert followup.is_success, followup.text
    continued = wait_batch(client, followup.json()["batch_id"])["items"][0]
    assert continued["result"]["transcript_id"] == original["result"]["transcript_id"]
    assert calls.count(("sub", "transcribe")) == 1 and calls.count(("sub", "download")) == 2


def test_source_cookie_scope_and_public_addresses(monkeypatch):
    from app import desktop_sources, source_network

    monkeypatch.setattr(desktop_sources, "public_target", lambda *_: None)
    content = ("# Netscape HTTP Cookie File\n.douyin.com\tTRUE\t/\tTRUE\t0\tname\tsite-value\n"
               ".youtube.com\tTRUE\t/\tTRUE\t0\tname\tother-value\n").encode()
    link = "https://v.douyin.com/demo"
    session = desktop_sources.register_session(link, content)
    assert "site-value" in desktop_sources.session_for(link, session)
    assert "other-value" not in desktop_sources.session_for(link, session)
    with pytest.raises(desktop_sources.SourceError):
        desktop_sources.session_for("https://www.youtube.com/watch?v=demo", session)
    assert "session_id" not in media.SourceInput(source_kind="url", source_value=link, session_id=session).model_dump()
    desktop_sources.forget_session(session)
    with pytest.raises(desktop_sources.SourceError):
        desktop_sources.session_for(link, session)
    for url in ("http://127.0.0.1", "http://169.254.169.254", "http://10.0.0.1", "http://[::1]", "file:///demo"):
        with pytest.raises(ValueError):
            source_network.public_target(url)


def test_social_share_cookie_scope_and_diagnostics(monkeypatch):
    from app import desktop_sources as sources

    monkeypatch.setattr(sources, "public_target", lambda *_: None)
    xhs = "https://xhslink.cn/o/test-share"
    douyin = "https://v.douyin.com/test-share/"
    content = ("# Netscape HTTP Cookie File\n.xiaohongshu.com\tTRUE\t/\tTRUE\t0\tname\txhs-value\n"
               ".douyin.com\tTRUE\t/\tTRUE\t0\tname\tother-value\n").encode()
    assert sources.site(xhs)[0] == "小红书"
    session = sources.register_session(xhs, content)
    try:
        scoped = sources.session_for("https://www.xiaohongshu.com/explore/test", session)
        assert "xhs-value" in scoped and "other-value" not in scoped
        with pytest.raises(sources.SourceError, match="站点会话已失效"):
            sources.session_for(douyin, session)
    finally:
        sources.forget_session(session)
    assert session not in sources.SESSIONS

    login = sources.extract_error(xhs, "ERROR: Unsupported URL: https://www.xiaohongshu.com/login?redirectPath=%2Fexplore")
    assert login.code == "session_required" and "跳转到了登录页" in str(login)
    missing = sources.extract_error(xhs, "ERROR: [XiaoHongShu] No video formats found!")
    assert missing.code == "no_stream" and "未找到可用的视频流" in str(missing)
    detail = "WARNING: [Douyin] Failed to download web detail JSON: HTTP Error 403: Forbidden\nERROR: Fresh cookies are needed"
    assert sources.extract_error(douyin, detail).code == "session_required"
    blocked = sources.extract_error(douyin, detail, has_session=True)
    assert blocked.code == "site_blocked" and "已使用本站 Cookie" in str(blocked)


def test_video_defaults_are_saved_independently(desktop_app, monkeypatch, tmp_path):
    client, _ = desktop_app
    config = desktop_routes.config
    path = tmp_path / "settings.json"
    existing = {"data_dir": "D:/资料目录", "ai_model": "deepseek-chat", "gpu_enabled": True}
    path.write_text(json.dumps(existing), encoding="utf-8")
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(config, "SETTINGS", path)
    monkeypatch.setattr(config, "settings", lambda: json.loads(path.read_text(encoding="utf-8")))
    endpoint = "/desktop/video-defaults"
    assert client.get(endpoint).json() == {"output": None, "subtitle_style": None}
    output = {"whisper_model": "large-v3-turbo", "aspect_ratio": "9:16", "output_name_prefix": "成片"}
    response = client.put(endpoint, json={"output": output})
    assert response.is_success and response.json()["subtitle_style"] is None
    style = {"font_family": "Source Han Sans CN", "font_size": 52, "background_enabled": True}
    response = client.put(endpoint, json={"subtitle_style": style})
    saved = response.json()
    assert response.is_success and saved == client.get(endpoint).json()
    assert {key: saved["output"][key] for key in output} == output
    assert {key: saved["subtitle_style"][key] for key in style} == style
    assert client.put(endpoint, json={"output": {"whisper_model": "large-v4"}}).status_code == 422
    assert client.get(endpoint).json() == saved
    assert json.loads(path.read_text(encoding="utf-8")) == {
        **existing, "video_output_defaults": saved["output"], "video_subtitle_style_defaults": saved["subtitle_style"],
    }


def test_turbo_resource_can_be_selected_and_downloaded(desktop_app, monkeypatch):
    client, root = desktop_app
    model_name = "large-v3-turbo"
    models = client.get("/ui/whisper-models").json()["models"]
    assert next(model for model in models if model["name"] == model_name)["available"] is False
    called = []
    monkeypatch.setattr(desktop_routes.desktop_models, "prepare", lambda data, name, proxy: called.append((data, name)))
    response = client.post(f"/desktop/resources/models/{model_name}")
    assert response.is_success and called == [(root, model_name)]
    resource = next(model for model in response.json()["models"] if model["name"] == model_name)
    assert resource["preferred_path"] == str(root / "models" / "faster-whisper-large-v3-turbo")
    assert resource["size"] == 1617884929


def test_source_titles_and_batch_history_count(desktop_app, monkeypatch):
    client, root = desktop_app
    links = {"https://youtu.be/FirstVideo1": "A YouTube title", "https://www.bilibili.com/video/BV1pJ411X7mA/": "B 站标题"}
    monkeypatch.setattr(media, "load_youtube_preview_metadata", lambda source: {"title": links[source]})
    local = root / "本地 文件.mp4"
    youtube, bilibili = links
    cases = [("local", str(local), local.name), ("youtube", youtube, links[youtube]), ("bilibili", bilibili, links[bilibili])]
    sources = []
    for kind, value, title in cases:
        source = {"source_kind": kind, "source_value": value}
        response = client.post("/desktop/source-title", json=source)
        assert response.is_success and response.json()["title"] == title
        sources.append({**source, "source_title": title})
    assert client.post("/desktop/source-title", json={"source_kind": "youtube", "source_value": bilibili}).status_code == 400
    batch = media.create_batch(media.BatchCreateRequest(sources=sources, rights_confirmed=True))
    item_data = client.get(f"/ui/batches/{batch.batch_id}").json()["items"]
    assert [item["source_title"] for item in item_data] == [title for _, _, title in cases]
    history = next(entry for entry in client.get("/desktop/batches").json() if entry["batch_id"] == batch.batch_id)
    assert history["created_at"] == batch.created_at and history["total"] == 3 and "title" not in history
    for item in batch.items:
        media.update_batch_item(batch.batch_id, item.item_id, status="succeeded")


def test_burn_encoder_checks_real_runtime_and_respects_cpu(monkeypatch):
    monkeypatch.setattr(media, "nvenc_runtime_error", lambda _binary: "driver incompatible")
    assert media.selected_burn_encoder("auto") == "cpu"
    with pytest.raises(RuntimeError, match="NVENC 无法启动"):
        media.burn_subtitle("strict", Path("video.mp4"), Path("captions.srt"), burn_encoder="nvenc")
    monkeypatch.setattr(media, "nvenc_runtime_error", lambda _binary: "")
    assert media.selected_burn_encoder("auto") == "nvenc"
    assert media.selected_burn_encoder("cpu") == "cpu"


def test_missing_model_blocks_before_download(desktop_app, monkeypatch):
    client, root = desktop_app
    model = root / "models" / "faster-whisper-large-v3"
    model.mkdir(parents=True)
    (model / "model.bin").write_bytes(b"partial")
    source = root / "preflight.mp4"
    source.write_bytes(b"video")
    submitted = client.post("/ui/batches", json={
        "sources": [{"source_kind": "local", "source_value": str(source)}],
        "rights_confirmed": True, "whisper_model": "large-v3", "subtitle_output_mode": "en_only",
    })
    assert submitted.is_success, submitted.text
    item = wait_batch(client, submitted.json()["batch_id"])["items"][0]
    assert item["status"] == "failed" and item["stage"] == "transcribe"
    assert item["stage_jobs"] == {}
    assert "设置 → 转录与本地资源" in item["error"]["message"]


def test_strict_gpu_does_not_fall_back(desktop_app, monkeypatch):
    monkeypatch.setattr(media, "whisper_model_status", lambda _name: {"available": True})
    monkeypatch.setattr(desktop_routes.config, "worker_environment", lambda: {"WHISPER_DEVICE": "cuda"})
    calls = []

    def fail(*args, **kwargs):
        calls.append(kwargs["env"]["WHISPER_DEVICE"])
        raise RuntimeError("CUDA unavailable")

    monkeypatch.setattr(media, "run_command_streaming", fail)
    with pytest.raises(RuntimeError, match="严格 GPU"):
        media.transcribe_video("strict-no-fallback", Path("placeholder.mp4"), inference_mode="gpu_only")
    assert calls == ["cuda"]


def test_resume_and_bilibili_confirmation(desktop_app, monkeypatch):
    monkeypatch.setattr(media, "whisper_model_status", lambda _name: {"available": True})
    client, root = desktop_app
    source = root / "course.mp4"
    source.write_bytes(b"fake video")
    calls = []

    def mock_stage(stage, filename, contents):
        def run(job_id):
            calls.append(stage)
            path = media.artifact_path(job_id, filename)
            path.write_bytes(contents)
            key = desktop_jobs.OUTPUTS[stage]
            media.report_stage_progress(job_id, stage, 100, "done", status="succeeded",
                                        force=True, result={key: media.public_file_url(job_id, filename)})
        return run

    monkeypatch.setitem(desktop_jobs.RUNNERS, "download", mock_stage("download", "source.mp4", b"video"))
    monkeypatch.setitem(desktop_jobs.RUNNERS, "transcribe", mock_stage(
        "transcribe", "english.srt", b"1\n00:00:00,100 --> 00:00:02,000\ncourse content\n",
    ))
    monkeypatch.setitem(desktop_jobs.RUNNERS, "burn", mock_stage("burn", "final.mp4", b"rendered"))
    monkeypatch.setattr(media, "bilibili_configured", lambda: True)

    def fail_upload(job_id):
        calls.append("upload_failed")
        media.fail_job(job_id, "bilibili_upload", RuntimeError("network disconnected"))

    monkeypatch.setitem(desktop_jobs.RUNNERS, "bilibili_upload", fail_upload)
    response = client.post("/ui/batches", json={
        "sources": [{"source_kind": "local", "source_value": str(source)}],
        "subtitle_output_mode": "en_only", "rights_confirmed": True, "bilibili_upload": {"enabled": True, "copyright": 1},
    })
    assert response.status_code == 200, response.text
    batch_id = response.json()["batch_id"]
    failed = wait_batch(client, batch_id)["items"][0]
    assert failed["stage"] == "bilibili_upload", failed
    assert failed["result"]["transcript_id"]
    endpoint = f"/desktop/batches/{batch_id}/{failed['item_id']}/retry"
    assert client.post(endpoint, json={}).status_code == 409

    def upload_success(job_id):
        calls.append("upload_ok")
        media.report_stage_progress(job_id, "bilibili_upload", 100, "done", status="succeeded",
                                    force=True, result={"bvid": "mock"})

    monkeypatch.setitem(desktop_jobs.RUNNERS, "bilibili_upload", upload_success)
    assert client.post(endpoint, json={"upload_checked": True}).status_code == 200
    finished = wait_batch(client, batch_id)["items"][0]
    assert finished["status"] == "succeeded"
    assert finished["result"]["bvid"] == "mock"
    assert calls == ["download", "transcribe", "burn", "upload_failed", "upload_ok"]


def test_history_batch_upload_reuses_only_finished_videos(desktop_app, monkeypatch):
    client, _ = desktop_app
    monkeypatch.setattr(media, "bilibili_configured", lambda: True)
    monkeypatch.setattr(media, "whisper_model_status", lambda _name: {"available": False})
    sources = [media.SourceInput(source_kind="youtube", source_value=f"https://youtu.be/history-{i}") for i in range(5)]
    batch = media.create_batch(media.BatchCreateRequest(
        sources=sources, rights_confirmed=True, subtitle_output_mode="en_only", batch_concurrency=1,
        bilibili_upload={"enabled": True, "tid": 130, "tags": ["历史标签"]},
    ))
    failed, ready, missing, posted, removed = batch.items
    for item in (failed, ready, posted, removed):
        filename = item.item_id + ".mp4"
        path = media.artifact_path(batch.batch_id, filename)
        if item is not removed:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"completed render")
        result = {"final_video_url": media.public_file_url(batch.batch_id, filename), "transcript_id": 42}
        if item is posted:
            result["bvid"] = "BVAlreadyPosted"
        media.update_batch_item(batch.batch_id, item.item_id, status="succeeded", stage="done", result=result)
    original = media.create_stage_job("bilibili_upload", {"upload_settings": {"tid": 24, "tags": ["原投稿标签"]}})
    media.update_batch_item(batch.batch_id, failed.item_id, status="failed", stage="bilibili_upload",
                            stage_jobs={"bilibili_upload": original.job_id})
    media.update_batch_item(batch.batch_id, missing.item_id, status="failed", stage="transcribe")
    endpoint = f"/desktop/batches/{batch.batch_id}"
    states = client.get(endpoint + "/upload-candidates").json()
    assert [states[item.item_id]["state"] for item in batch.items] == ["retry", "ready", "missing", "posted", "missing"]
    calls = []

    def upload(job_id):
        job = media.load_state(job_id)
        calls.append(job.request)
        if job.request["operator_item_id"] == ready.item_id:
            media.fail_job(job_id, "bilibili_upload", RuntimeError("mock upload failure"))
        else:
            media.report_stage_progress(job_id, "bilibili_upload", 100, "done", status="succeeded",
                                        force=True, result={"bvid": "BVMockResult"})

    monkeypatch.setitem(desktop_jobs.RUNNERS, "bilibili_upload", upload)
    payload = {"item_ids": [failed.item_id, ready.item_id], "upload_settings": {"tid": 17, "tags": ["新投稿标签"]}}
    assert client.post(endpoint + "/upload", json=payload).status_code == 409
    payload["upload_checked"] = True
    invalid = {**payload, "item_ids": [failed.item_id, posted.item_id]}
    assert client.post(endpoint + "/upload", json=invalid).status_code == 409
    assert not calls
    assert client.post(endpoint + "/upload", json=payload).is_success
    result = wait_batch(client, batch.batch_id)["items"]
    assert [entry["status"] for entry in result[:2]] == ["succeeded", "failed"]
    assert result[0]["result"]["transcript_id"] == 42 and result[0]["result"]["bvid"] == "BVMockResult"
    assert result[1]["result"]["final_video_url"] and result[1]["stage"] == "bilibili_upload"
    assert [call["upload_settings"]["tid"] for call in calls] == [24, 17]
    assert all(call["allow_automatic_retry"] is False for call in calls)
    assert all(set(entry["stage_jobs"]) == {"bilibili_upload"} for entry in result[:2])
    assert client.post(endpoint + "/upload", json={**payload, "item_ids": [failed.item_id]}).status_code == 409
    assert len(calls) == 2


def test_batch_posting_uses_per_video_covers_and_deepseek_fields(desktop_app, monkeypatch):
    from app import desktop_bilibili

    client, _ = desktop_app
    sources = [
        media.SourceInput(source_kind="youtube", source_value="https://youtu.be/FirstVideo1"),
        media.SourceInput(source_kind="bilibili", source_value="https://www.bilibili.com/video/BV1pJ411X7mA/"),
    ]
    batch = media.create_batch(media.BatchCreateRequest(
        sources=sources, rights_confirmed=True, subtitle_output_mode="en_only", batch_concurrency=1,
    ))
    for index, item in enumerate(batch.items, 1):
        folder = media.job_dir(f"mock_posting_source_{index}")
        folder.mkdir(parents=True)
        (folder / "video.mp4").write_bytes(b"finished render")
        (folder / "english.srt").write_text(
            f"1\n00:00:00,000 --> 00:00:03,000\nSubtitle {index}\n", encoding="utf-8",
        )
        (folder / "source-metadata.jsonl").write_text(json.dumps({
            "title": f"Video {index}", "description": f"Original description {index}",
            "thumbnail": f"https://images.example.test/{index}.jpg",
        }), encoding="utf-8")
        media.update_batch_item(batch.batch_id, item.item_id, status="succeeded", stage="done", result={
            "final_video_url": media.public_file_url(folder.name, "video.mp4"),
            "source_video_url": media.public_file_url(folder.name, "video.mp4"),
            "english_srt_url": media.public_file_url(folder.name, "english.srt"),
        })

    real_client = httpx.Client
    model_calls = []
    covers = []
    uploads = []

    def deepseek(request):
        body = json.loads(request.content)
        data = json.loads(body["messages"][1]["content"])
        assert body["response_format"] == {"type": "json_object"}
        if "tid" in data["fields_to_fill"]:
            assert set(data["fields_to_fill"]) == {"tid", "title", "tags"}
            assert set(data) == {"source_title", "source_description", "description_available", "subtitle_excerpt", "fields_to_fill", "allowed_zones"}
        else:
            assert data["fields_to_fill"] == ["desc"] and "allowed_zones" not in data
        number = int(data["source_title"][-1])
        assert data["source_description"] == f"Original description {number}"
        assert data["description_available"] is True
        assert "先忠实翻译" in body["messages"][0]["content"]
        assert "3–6条" in body["messages"][0]["content"]
        assert data["subtitle_excerpt"] == f"Subtitle {number}"
        model_calls.append(number)
        output = {"tid": 201 if number == 1 else 999999, "title": f"自动标题 {number}",
                  "desc": f"自动简介 {number}", "tags": [f"标签{number}", f"标签{number}"]}
        return httpx.Response(200, json={"choices": [
            {"finish_reason": "stop", "message": {"content": json.dumps(output)}},
        ]})

    def thumbnail(job_id, url):
        covers.append(url)
        return media.artifact_path(job_id, "thumbnail.jpg")

    def upload(job_id, path, request, progress_callback):
        _, cover = media.create_bilibili_cover(
            job_id, path, request.upload_settings, request.original_source,
            source_video_url=request.source_video_url, source_thumbnail=request.source_thumbnail,
        )
        uploads.append(request.upload_settings)
        if len(uploads) == 1:
            raise RuntimeError("模拟投稿超时")
        return {"bvid": f"BVMock{len(uploads)}", **cover}

    monkeypatch.setattr(media, "bilibili_configured", lambda: True)
    monkeypatch.setattr(media, "TRANSLATE_API_KEY", "test")
    monkeypatch.setattr(desktop_bilibili, "posting_zones", lambda: {201: "知识 / 科学", 202: "知识 / 人文"})
    monkeypatch.setattr(desktop_bilibili, "httpx", SimpleNamespace(
        Client=lambda **kwargs: real_client(transport=httpx.MockTransport(deepseek), **kwargs),
        Timeout=httpx.Timeout, HTTPError=httpx.HTTPError,
    ))
    monkeypatch.setattr(media, "download_thumbnail_for_preview", thumbnail)
    monkeypatch.setattr(media, "normalize_bilibili_cover_image", lambda _, image: image)
    monkeypatch.setattr(media, "upload_video_to_bilibili", upload)
    endpoint = f"/desktop/batches/{batch.batch_id}"
    first, second = [item.item_id for item in batch.items]
    payload = {"item_ids": [first, second], "upload_checked": True,
               "upload_settings": {"auto_metadata": True, "tid": None, "title_template": "", "tags": [], "desc": "手写简介"}}
    assert client.post(endpoint + "/upload", json=payload).is_success
    a, b = wait_batch(client, batch.batch_id)["items"]
    assert a["result"]["bilibili_metadata"]["generated_fields"] == ["tid", "title", "tags"]
    assert a["result"]["bilibili_metadata"]["desc"] == "手写简介"
    assert b["status"] == "failed" and "请选择投稿分区" in b["error"]["message"]
    assert model_calls == [1, 2] and len(uploads) == 1

    assert client.post(endpoint + "/upload", json={"item_ids": [first], "upload_checked": True}).is_success
    a, _ = wait_batch(client, batch.batch_id)["items"]
    assert a["status"] == "succeeded" and uploads[1].tid == 201 and uploads[1].tags == ["标签1"]
    assert client.post(endpoint + "/upload", json={
        "item_ids": [second], "upload_checked": True, "use_current_settings": True,
        "upload_settings": {"auto_metadata": True, "tid": 202, "title_template": "手写标题", "tags": ["手写标签"]},
    }).is_success
    _, b = wait_batch(client, batch.batch_id)["items"]
    assert b["status"] == "succeeded" and b["result"]["bilibili_metadata"]["tid"] == 202
    assert uploads[2].desc == "自动简介 2" and uploads[2].title_template == "手写标题" and uploads[2].tags == ["手写标签"]
    assert covers == ["https://images.example.test/1.jpg"] * 2 + ["https://images.example.test/2.jpg"]
    assert model_calls == [1, 2, 2]


def test_gpu_download_resumes(tmp_path):
    from hashlib import sha256
    from app.desktop_gpu import download

    contents = b"downloaded NVIDIA runtime"
    archive = tmp_path / "runtime.zip"
    archive.with_suffix(".part").write_bytes(contents[:10])

    def server(request):
        assert request.headers["Range"] == "bytes=10-"
        return httpx.Response(206, content=contents[10:], headers={
            "Content-Range": f"bytes 10-{len(contents) - 1}/{len(contents)}",
        })

    with httpx.Client(transport=httpx.MockTransport(server)) as client:
        result = download(client, "https://example.test/runtime", archive,
                          sha256(contents).hexdigest(), len(contents), lambda _: None)
    assert result == archive
    assert result.read_bytes() == contents
    assert not archive.with_suffix(".part").exists()


def test_interrupted_batch_requires_manual_resume(desktop_app):
    client, root = desktop_app
    source = root / "resume.mp4"
    request = media.BatchCreateRequest(
        sources=[media.SourceInput(source_kind="local", source_value=str(source))],
        rights_confirmed=True, subtitle_output_mode="en_only",
    )
    batch = media.create_batch(request)
    item = batch.items[0]
    media.update_batch_item(batch.batch_id, item.item_id, status="running", stage="transcribe")
    desktop_jobs.recover_interrupted()
    data = client.get(f"/ui/batches/{batch.batch_id}").json()
    assert data["status"] == "failed"
    assert data["items"][0]["stage"] == "transcribe"

def test_desktop_reports_translation_provider_error(monkeypatch):
    def unavailable(texts, target_lang, **kwargs):
        raise httpx.ConnectError("provider unavailable")

    monkeypatch.setattr(media, "_translate_lines_via_provider", unavailable)
    with pytest.raises(httpx.ConnectError):
        media.translate_lines(["Original text"], "zh-CN")


def _publish_fixture(client, root, monkeypatch):
    vault = root / "长期 知识库 # 测试"
    (vault / ".obsidian").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(desktop_routes.config, "settings", lambda: {"obsidian_vault": str(vault)})
    subtitle = root / "发布样片.srt"
    subtitle.write_text("1\n00:00:01,250 --> 00:00:03,000\n引用的原文：复盘能改善学习。\n", encoding="utf-8")
    transcript = knowledge.register(subtitle, source_kind="youtube",
                                    source="https://youtu.be/aqz-KE-bpKQ?fixture=" + root.name, title="样片与长期学习")
    return vault, transcript, f"/desktop/knowledge/{transcript}/publish"


def _draft(transcript, title, key, *, evidence="用可核查的引用"):
    with knowledge.database() as db:
        return db.execute("""
            INSERT INTO card(transcript_id, claim, evidence, example, refs, origin_key)
            VALUES(?, ?, ?, '课堂复盘', '[1]', ?) RETURNING id
        """, (transcript, title, evidence, key)).fetchone()["id"]


def test_obsidian_publication_respects_ownership(desktop_app, monkeypatch):
    client, root = desktop_app
    vault, transcript, route = _publish_fixture(client, root / "ownership", monkeypatch)
    first = _draft(transcript, "第一次观点", "stable-origin-1")
    retained = _draft(transcript, "留在应用的草稿", "stable-origin-2")
    result = client.post(route, json={"card_ids":[first]}).json()["results"][0]
    assert (result["status"], result["cleared"]) == ("published", True)
    assert [card["id"] for card in knowledge.read_transcript(transcript)["cards"]] == [retained]
    note = next((vault / "Media Operator" / "观点").glob("*.md"))
    source = next((vault / "Media Operator" / "素材").glob("*.md"))
    text = note.read_text(encoding="utf-8")
    assert "第一次观点" in text and "引用的原文" in text
    assert "v=aqz-KE-bpKQ&t=1s" in text and "00:00:01.250" in text
    assert result["publication_id"] in text and "media_operator_type: viewpoint" in text
    assert "Media%20Operator/" in text and source.stem.split("-")[-1] in text
    moved = vault / "已归档 观点.md"
    note.rename(moved)
    moved.write_text(text + "\n这是在 Obsidian 补写的内容。\n", encoding="utf-8")
    captured = []
    monkeypatch.setattr(desktop_routes.os, "startfile", captured.append)
    assert client.post("/desktop/obsidian/" + result["publication_id"] + "/open").status_code == 200
    assert captured[0].startswith("obsidian://open?path=") and "%20" in captured[0]
    source.rename(vault / "已归档 来源.md")

    revised = _draft(transcript, "观点修订版", "stable-origin-1")
    duplicate = client.post(route, json={"card_ids":[revised]}).json()["results"][0]
    assert duplicate["status"] == "already_published" and not duplicate["cleared"]
    assert duplicate["publication_id"] == result["publication_id"]
    version = client.post(route, json={"card_ids":[revised],"new_version":True}).json()["results"][0]
    assert version["status"] == "published" and version["cleared"]
    assert version["publication_id"] != result["publication_id"]
    assert "补写的内容" in moved.read_text(encoding="utf-8")
    assert "观点修订版" in next((vault / "Media Operator" / "观点").glob("*.md")).read_text(encoding="utf-8")


def test_obsidian_partial_write_and_recovery(desktop_app, monkeypatch):
    from app import obsidian

    client, root = desktop_app
    vault, transcript, route = _publish_fixture(client, root / "recovery", monkeypatch)
    a = _draft(transcript, "写入中断的卡片", "retry-origin")
    b = _draft(transcript, "同一批成功的卡片", "success-origin")
    doc = knowledge.read_transcript(transcript)
    source_id = obsidian._digest("source", doc["source_kind"], doc["source"], doc["digest"])
    note_id = obsidian._digest("card", source_id, "retry-origin")
    real_write = obsidian._write_new

    def reject_receipt(path, contents):
        if path.name == note_id + ".json":
            raise PermissionError("simulated read-only receipt directory")
        return real_write(path, contents)

    monkeypatch.setattr(obsidian, "_write_new", reject_receipt)
    results = client.post(route, json={"card_ids":[a,b]}).json()["results"]
    assert [item["status"] for item in results] == ["failed","published"]
    assert [card["id"] for card in knowledge.read_transcript(transcript)["cards"]] == [a]
    notes = vault / "Media Operator" / "观点"
    assert len(list(notes.glob("*.md"))) == 2

    monkeypatch.setattr(obsidian, "_write_new", real_write)
    retried = client.post(route, json={"card_ids":[a]}).json()["results"][0]
    assert retried["cleared"] and retried["publication_id"] == note_id
    assert len(list(notes.glob("*.md"))) == 2


def test_obsidian_keeps_newer_draft_revision(desktop_app, monkeypatch):
    from app import obsidian

    client, root = desktop_app
    _, transcript, route = _publish_fixture(client, root / "newer", monkeypatch)
    card = _draft(transcript, "旧草稿", "editing-origin")
    real_create = obsidian._create

    def update_during_write(vault, path, text, note_id, snapshot):
        if path.parent.name == "观点":
            knowledge.update_card(transcript, card, knowledge.CardText(claim="并发的新草稿"))
        return real_create(vault, path, text, note_id, snapshot)

    monkeypatch.setattr(obsidian, "_create", update_during_write)
    result = client.post(route, json={"card_ids":[card]}).json()["results"][0]
    assert result["status"] == "published" and not result["cleared"]
    assert knowledge.read_transcript(transcript)["cards"][0]["claim"] == "并发的新草稿"



def test_quote_modes_validation_and_translated_publication(desktop_app, monkeypatch):
    from app import obsidian
    client, root = desktop_app
    subtitle = root / "quote-modes.srt"
    subtitle.write_text("1\n00:00:01,000 --> 00:00:03,000\nTest a prediction before you explain it.\n\n"
                        "2\n00:00:03,000 --> 00:00:05,000\nA wrong answer tells you what to revisit.\n\n"
                        "3\n00:00:06,000 --> 00:00:08,000\nThen try again.\n", encoding="utf-8")
    ident = knowledge.register(subtitle, source_kind="subtitle", source=str(subtitle), title="Recall")
    refs = [1, 2]
    real_client = httpx.Client
    calls = []

    def fake(request):
        body = json.loads(request.content)
        calls.append(body)
        assert "不是写简介" in body["messages"][0]["content"]
        assert "较完整" in body["messages"][0]["content"]
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
            "cards": [{"claim": "先做预测再解释", "refs": refs,
                       "quote_translation": "解释之前，先检验预测。错误的答案会告诉你需要回顾什么。"}],
        })}}]})

    monkeypatch.setattr(knowledge, "httpx", SimpleNamespace(Client=lambda **kw: real_client(transport=httpx.MockTransport(fake), **kw)))
    monkeypatch.setattr(media, "TRANSLATE_API_KEY", "test")
    route = f"/desktop/knowledge/{ident}"
    assert client.post(route + "/generate", json={"send_subtitles": True, "mode": "invalid"}).status_code == 422
    assert client.post(route + "/generate", json={"send_subtitles": True, "mode": "comprehensive"}).json() == {"added": 1}
    doc = knowledge.read_transcript(ident)
    card = doc["cards"][0]
    assert card["quote_translation"].startswith("解释之前")
    assert any(row["id"] == ident for row in knowledge.list_transcripts("检验预测"))
    assert "中文译句" in knowledge.markdown(ident)
    assert "Test a prediction" in knowledge.markdown(ident)
    assert client.put(route + f"/cards/{card['id']}", json={"claim": "我修改的主题"}).is_success
    assert knowledge.read_transcript(ident)["cards"][0]["quote_translation"] == card["quote_translation"]
    assert client.post(route + "/generate", json={"send_subtitles": True, "mode": "comprehensive"}).json() == {"added": 0}
    for refs in ([1, 3], [999], [0]):
        assert client.post(route + "/generate", json={"send_subtitles": True, "mode": "comprehensive"}).status_code == 502
    assert knowledge.read_transcript(ident)["cards"][0]["claim"] == "我修改的主题"
    vault = root / "译句知识库"
    (vault / ".obsidian").mkdir(parents=True)
    original_create = obsidian._create

    def create_and_edit(*args):
        result = original_create(*args)
        if "观点" in str(args[1]):
            knowledge.update_card(ident, card["id"], knowledge.CardText(claim="我修改的主题", quote_translation="发布期间的新译句"))
        return result

    monkeypatch.setattr(obsidian, "_create", create_and_edit)
    result = obsidian.publish(vault, ident, [card["id"]])[0]
    assert result["status"] == "published" and result["cleared"] is False
    note = next((vault / "Media Operator" / "观点").glob("*.md"))
    assert "解释之前" in note.read_text(encoding="utf-8")
    assert knowledge.read_transcript(ident)["cards"][0]["quote_translation"] == "发布期间的新译句"
    monkeypatch.setattr(obsidian, "_create", original_create)
    assert obsidian.publish(vault, ident, [card["id"]])[0]["status"] == "already_published"
    new = obsidian.publish(vault, ident, [card["id"]], new_version=True)[0]
    assert new["cleared"] and not knowledge.read_transcript(ident)["cards"]


def test_long_transcript_global_selection_is_grounded(desktop_app, monkeypatch):
    _, root = desktop_app
    subtitle = root / "long-quotes.srt"
    subtitle.write_text("\n\n".join(f"{n}\n00:{n // 60:02d}:{n % 60:02d},000 --> 00:{(n+1) // 60:02d}:{(n+1) % 60:02d},000\n"
                                   + "A concrete example shows which assumption can be tested. " * 3 for n in range(1,180)), encoding="utf-8")
    ident = knowledge.register(subtitle, source_kind="subtitle", source=str(subtitle), title="Long")
    real_client = httpx.Client
    ranking = []
    bad = False

    def fake(request):
        payload = json.loads(request.content)
        data = json.loads(payload["messages"][1]["content"])
        if "quote" in data[0]:
            ranking.append(data)
            result = {"ids": [99999] if bad else [len(data)-1, 0]}
        else:
            result = {"cards": [{"claim": "可验证的假设", "refs": [data[0]["id"]], "quote_translation": "具体例子揭示了可检验的假设。"}]}
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}]})

    monkeypatch.setattr(knowledge, "httpx", SimpleNamespace(Client=lambda **kw: real_client(transport=httpx.MockTransport(fake), **kw)))
    assert knowledge.generate_cards(ident, "test", "mock", "comprehensive") == 2
    cards = knowledge.read_transcript(ident)["cards"]
    assert cards[0]["refs"][0] < cards[1]["refs"][0] and ranking
    bad = True
    with pytest.raises(ValueError):
        knowledge.generate_cards(ident, "test", "mock", "comprehensive")
    assert knowledge.read_transcript(ident)["cards"] == cards


def test_legacy_source_metadata_retained_when_refresh_fails(desktop_app, monkeypatch):
    _, root = desktop_app
    folder = media.job_dir("legacy-description")
    folder.mkdir()
    source = folder / "source.mp4"
    source.write_bytes(b"source")
    metadata = {"title": "Original", "thumbnail": "https://images.example.test/cover.jpg"}
    (folder / "source-metadata.jsonl").write_text(json.dumps(metadata), encoding="utf-8")
    monkeypatch.setattr(media, "load_youtube_preview_metadata", lambda _: (_ for _ in ()).throw(RuntimeError("offline")))
    assert media.bilibili_source_metadata("https://youtu.be/FirstVideo1", media.public_file_url(folder.name, source.name)) == metadata


DOUYIN_SHARE = ("4.35 复制打开抖音，看看【内语者TheInward的作品】宇宙想让你和谁在一起？这些迹象不是巧合，而是...... "
                "https://v.douyin.com/aDqmydz7iGA/ z@T.YM 02/03 ipD:/ :1pm")
XHS_SHARE = "没有创伤就没有魅力，最顶级的性张力就是破碎感 https://xhslink.cn/o/4LXLtDW6SVI 复制这段话，打开【小红书】就能找到对应笔记。"


def test_share_text_parses_douyin_and_xiaohongshu_samples(desktop_app):
    from app import share_text

    client, _ = desktop_app
    douyin, xhs = share_text.parse(DOUYIN_SHARE), share_text.parse(XHS_SHARE)
    assert douyin == [{
        "url": "https://v.douyin.com/aDqmydz7iGA/", "platform": "抖音", "author": "内语者TheInward",
        "title": "宇宙想让你和谁在一起？这些迹象不是巧合，而是……", "source_kind": "url",
        "duration": 275,
    }]
    assert xhs == [{
        "url": "https://xhslink.cn/o/4LXLtDW6SVI", "platform": "小红书", "author": "",
        "title": "没有创伤就没有魅力，最顶级的性张力就是破碎感", "source_kind": "url",
    }]
    response = client.post("/desktop/sources/parse", json={"text": DOUYIN_SHARE + "\n" + XHS_SHARE})
    assert response.status_code == 200, response.text
    assert response.json()["items"] == douyin + xhs
    assert client.post("/desktop/sites/douyin/login").status_code == 409
    sites = client.get("/desktop/sites").json()["sites"]
    assert [item["site"] for item in sites] == ["douyin", "xiaohongshu", "bilibili", "weread"]
    assert client.get("/desktop/settings").json()["site_logins"] == sites


def test_short_link_classification_and_error_mapping(monkeypatch, tmp_path):
    monkeypatch.setattr(media, "DATA_DIR", tmp_path)
    from contextlib import nullcontext
    from app import desktop_sources, site_profiles
    from app.sites import resolve

    douyin = "https://v.douyin.com/aDqmydz7iGA/"
    xhs = "https://xhslink.cn/o/4LXLtDW6SVI"
    assert resolve.classify(douyin)["kind"] == "short" and resolve.classify(douyin)["platform"] == "抖音"
    assert resolve.classify(xhs)["form"] == "/o/" and resolve.classify(xhs)["platform"] == "小红书"
    page = resolve.parse_document(
        "https://www.douyin.com/share/video/7123456789012345678",
        '<meta property="og:title" content="宇宙"><meta property="og:description" content="简介">'
        '<meta name="author" content="内语者">',
    )
    assert page["video_id"] == page["aweme_id"] == "7123456789012345678"
    assert page["canonical_url"] == "https://www.douyin.com/video/7123456789012345678"
    assert page["title"] == "宇宙" and page["author"] == "内语者" and page["description"] == "简介"
    note = resolve.parse_document(xhs, (
        '<meta property="og:title" content="没有创伤就没有魅力"><meta property="og:description" content="破碎感">'
        '"noteId":"64f0aabbccddeeff00112233","type":"normal",'
        '"url":"https://sns-img.xhscdn.com/note.jpg"'
    ))
    assert note["note_id"] == "64f0aabbccddeeff00112233"
    assert note["canonical_url"] == "https://www.xiaohongshu.com/explore/64f0aabbccddeeff00112233"
    assert note["image_note"] is True and note["images"] == ["https://sns-img.xhscdn.com/note.jpg"]
    video = resolve.parse_document("https://www.xiaohongshu.com/explore/64f0aabbccddeeff00112233",
                                   '"type":"video","masterUrl":"https://sns-video.xhscdn.com/a.mp4"')
    assert video["image_note"] is False and video["video_url"].endswith(".mp4")
    assert resolve.parse_document("https://www.xiaohongshu.com/login", "login")["login_wall"] is True

    detail = "WARNING: [Douyin] Failed to download web detail JSON: HTTP Error 403: Forbidden"
    blocked = desktop_sources.extract_error(douyin, detail, has_session=True)
    assert blocked.code == "site_blocked" and "抖音拒绝了详情接口" in str(blocked) and "已登录页面" in str(blocked)
    assert "尚未登录抖音" in str(desktop_sources.extract_error(douyin, detail))
    login = desktop_sources.extract_error(xhs, "ERROR: Unsupported URL: https://www.xiaohongshu.com/login?redirectPath=%2Fexplore")
    assert login.code == "session_required" and "尚未登录小红书" in str(login) and "跳转到了登录页" in str(login)
    missing = desktop_sources.extract_error(xhs, "ERROR: [XiaoHongShu] No video formats found!")
    assert missing.code == "no_stream" and "未找到可用的视频流" in str(missing)

    monkeypatch.setattr(desktop_sources, "public_target", lambda *args, **kwargs: None)
    monkeypatch.setattr(desktop_sources, "public_proxy", lambda *args, **kwargs: nullcontext("http://media:secret@127.0.0.1:9"))
    with desktop_sources.downloader(douyin, None) as (cmd, _folder):
        assert cmd[cmd.index("--socket-timeout") + 1] == "60"
        assert cmd[cmd.index("--extractor-retries") + 1] == "3"
        assert cmd[cmd.index("--referer") + 1] == "https://www.douyin.com/"
        assert any("deno" in part for part in cmd)
    resolve.remember(douyin, "https://www.douyin.com/video/7123456789012345678")
    assert knowledge.transcription_key("url", douyin, "auto", "small", "auto") == knowledge.transcription_key(
        "url", "https://www.douyin.com/video/7123456789012345678", "auto", "small", "auto",
    )
    site_profiles.write_cookies("douyin", [".douyin.com\tTRUE\t/\tTRUE\t0\tsessionid\tabc"], True)
    try:
        assert "sessionid" in desktop_sources.cookies_for(douyin, "")
        uploaded = desktop_sources.register_session(douyin, (
            "# Netscape HTTP Cookie File\n.douyin.com\tTRUE\t/\tTRUE\t0\tname\tuploaded\n"
        ).encode())
        assert "uploaded" in desktop_sources.cookies_for(douyin, uploaded)
        assert "sessionid" not in desktop_sources.cookies_for(douyin, uploaded)
        desktop_sources.forget_session(uploaded)
    finally:
        site_profiles.logout("douyin")
    assert desktop_sources.cookies_for(douyin, "") is None


def _note_probe(value, *_args, **_kwargs):
    from app import desktop_sources
    if value.endswith("broken"):
        raise desktop_sources.SourceError("no_stream", "媒体不可用")
    return {"title": "图文", "media_type": "note", "platform": "小红书", "has_audio": False,
            "audio_direct": False, "description": "正文", "body": "正文"}


def test_image_notes_do_not_run_whisper(desktop_app, monkeypatch):
    from app import desktop_sources

    client, _ = desktop_app
    calls = []

    def runner(stage):
        def run(job_id):
            calls.append(stage)
            filename = "artifact"
            media.artifact_path(job_id, filename).write_bytes(b"1\n00:00:00,100 --> 00:00:02,000\nWords.\n")
            media.report_stage_progress(job_id, stage, 100, "done", status="succeeded", force=True, result={
                desktop_jobs.OUTPUTS[stage]: media.public_file_url(job_id, filename),
                "asset_type": "audio",
            })
        return run

    monkeypatch.setattr(desktop_sources, "probe", _note_probe)
    for stage in desktop_jobs.RUNNERS:
        monkeypatch.setitem(desktop_jobs.RUNNERS, stage, runner(stage))
    payload = {"rights_confirmed": True, "knowledge_only": True, "subtitle_output_mode": "en_only", "sources": [{
        "source_kind": "url", "source_value": "https://www.xiaohongshu.com/explore/note-sample",
        "client_row_id": "note", "stop_after": "transcribe",
    }]}
    check = client.post("/desktop/batches/preflight", json=payload).json()["note"]
    assert check["ready"] is True and check["planned_stages"] == ["download"] and check["media_type"] == "note"
    response = client.post("/ui/batches", json=payload)
    assert response.is_success, response.text
    item = wait_batch(client, response.json()["batch_id"])["items"][0]
    assert item["status"] == "succeeded", item
    assert calls == ["download"]
    transcript = knowledge.read_transcript(item["result"]["transcript_id"])
    assert transcript["media_type"] == "note" and transcript["note_body"] == "图文"
    assert "transcribe" not in calls


def test_publish_pipeline_rejects_image_notes(desktop_app, monkeypatch):
    from app import desktop_sources

    client, _ = desktop_app
    monkeypatch.setattr(desktop_sources, "probe", _note_probe)
    payload = {"rights_confirmed": True, "subtitle_output_mode": "en_only", "sources": [{
        "source_kind": "url", "source_value": "https://www.xiaohongshu.com/explore/note-sample",
        "client_row_id": "note", "stop_after": "bilibili_upload",
    }], "bilibili_upload": {"tid": 201, "copyright": 1}}
    decision = client.post("/desktop/batches/preflight", json=payload).json()["note"]
    assert decision["ready"] is False and decision["code"] == "note_only"
    assert "没有可烧录的视频" in decision["message"]
    rejected = client.post("/ui/batches", json=payload)
    assert rejected.status_code == 409 and "没有可烧录的视频" in rejected.json()["detail"]


def test_silent_video_is_not_an_ffmpeg_dump():
    from app import desktop_sources

    request = SimpleNamespace(audio_only=True, allow_muxed_audio=True)
    try:
        desktop_sources.finish_media(
            Path("source.mp4"), {}, {"media_type": "video", "has_audio": False, "audio_direct": False},
            request, Path("."),
        )
    except desktop_sources.SourceError as error:
        assert "没有音轨" in str(error)
        assert "ffmpeg version" not in str(error)
    else:
        raise AssertionError("silent video should fail before ffmpeg")


def test_player_audio_track_is_separate_from_picture():
    from app.sites.resolve import player_feature

    aweme = "7659704469512359206"
    picture = "https://v26-web.douyinvod.com/picture.mp4"
    audio = "https://v26-web.douyinvod.com/speech.m4a"
    payload = {"aweme_id": aweme, "video": {
        "duration": 1923067,
        "playAddr": [{"src": picture}],
        "bitRateAudio": [
            {"bitRate": 64000, "playAddr": [{"src": "https://cdn.example/low.m4a"}]},
            {"bitRate": 128000, "playAddr": [{"src": audio}]},
        ],
    }}
    chosen = player_feature(json.dumps(payload, ensure_ascii=False), aweme)
    assert chosen["url"] == picture
    assert chosen["audio_url"] == audio
    assert chosen["duration"] == 1923.067 or abs(chosen["duration"] - 1923.067) < 0.01


def test_player_feature_ignores_unrelated_preview():
    from app.sites.resolve import player_feature
    from app import desktop_sources

    aweme = "7123456789012345678"
    preview = "https://v9-web.douyinvod.com/preview.mp4"
    feature = "https://v26-web.douyinvod.com/aweme/feature-high.mp4"
    payload = {"list": [
        {"aweme_id": "999000111222", "video": {"duration": 9000, "playAddr": [{"src": preview}]}},
        {"aweme_id": aweme, "video": {
            "duration": 275000,
            "bitRateList": [
                {"bitRate": 400000, "playAddr": [{"src": "https://cdn.example/low.mp4"}]},
                {"bitRate": 2500000, "playAddr": [{"src": feature}]},
            ],
            "playAddr": [{"src": feature}],
        }},
    ]}
    chosen = player_feature(json.dumps(payload, ensure_ascii=False), aweme)
    assert chosen["url"] == feature
    assert chosen["duration"] == 275
    assert aweme not in preview
    assert desktop_sources.duration_matches(9, 275) is False
    assert desktop_sources.duration_matches(270, 275) is True
    assert desktop_sources.duration_matches(1923, 275) is False


def test_percent_encoded_render_data_yields_feature():
    from urllib.parse import quote
    from app.sites.resolve import format_notes, page_notes, player_feature

    aweme = "7123456789012345678"
    feature = "https://v26-web.douyinvod.com/aweme/feature-high.mp4"
    payload = {"aweme_id": aweme, "video": {"duration": 275000, "playAddr": [{"src": feature}]}}
    encoded = quote(json.dumps(payload, ensure_ascii=False), safe="")
    html = f'<script id="RENDER_DATA" type="application/json">{encoded}</script>'
    chosen = player_feature(html, aweme)
    assert chosen["url"] == feature
    assert chosen["duration"] == 275
    notes = page_notes(html, f"https://www.douyin.com/video/{aweme}")
    assert notes["render_data"] is True and notes["play_addr"] is True
    assert "解码后play_addr=有" in format_notes(notes)
    assert f"页面=https://www.douyin.com/video/{aweme}" in format_notes(notes)


def test_player_entries_skip_short_preview(monkeypatch, tmp_path):
    from app.sites.resolve import order_player_urls
    from app import desktop_sources

    preview = "https://v9-web.douyinvod.com/preview.mp4"
    feature = "https://v26-web.douyinvod.com/aweme/feature-high.mp4"
    play = "https://www.douyin.com/aweme/v1/play/?video_id=real"
    ordered = order_player_urls(play, preview, [preview, feature])
    assert ordered[0] == play
    assert feature in ordered and preview in ordered
    monkeypatch.setattr(media, "DATA_DIR", tmp_path)
    monkeypatch.setattr(media, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(desktop_sources, "prepare_social", lambda url, cookies: (
        "https://www.douyin.com/video/7659704469512359206",
        {"duration": 275, "video_url": ordered[0], "play_urls": ordered,
         "page_notes": {"render_data": True, "play_addr": False, "page": "https://www.douyin.com/video/7659704469512359206"}},
    ))
    seen = []

    def fake_direct(url, folder, cookies, progress, referer):
        seen.append(url)
        path = folder / "source.mp4"
        path.write_bytes(b"media")
        return path

    monkeypatch.setattr(desktop_sources, "download_direct", fake_direct)
    monkeypatch.setattr(desktop_sources, "inspect_file", lambda path: {
        "media_type": "video", "has_audio": True, "audio_direct": False,
        "duration": 9 if seen[-1] == preview or seen[-1] == play else 270,
    })
    request = media.StageDownloadRequest(
        source_kind="url", source_value="https://v.douyin.com/aDqmydz7iGA/", rights_confirmed=True, managed=True,
    )
    _path, _info, actual = desktop_sources.download(
        "stage_download_entries001", request, {"media_type": "video", "duration": 275}, "", lambda *_: None,
    )
    assert actual["duration"] == 270
    assert feature in seen
    assert seen.index(feature) > seen.index(play)


def test_short_douyin_file_fails_before_transcription(monkeypatch, tmp_path):
    from app import desktop_sources

    monkeypatch.setattr(media, "DATA_DIR", tmp_path)
    monkeypatch.setattr(media, "JOBS_DIR", tmp_path / "jobs")
    feature = "https://v26-web.douyinvod.com/aweme/feature-high.mp4"
    monkeypatch.setattr(desktop_sources, "prepare_social", lambda url, cookies: (
        "https://www.douyin.com/video/7123456789012345678",
        {"canonical_url": "https://www.douyin.com/video/7123456789012345678", "duration": 275,
         "video_url": feature, "play_urls": [feature]},
    ))

    def fake_direct(url, folder, cookies, progress, referer):
        assert url == feature
        path = folder / "source.mp4"
        path.write_bytes(b"short")
        return path

    monkeypatch.setattr(desktop_sources, "download_direct", fake_direct)
    monkeypatch.setattr(desktop_sources, "inspect_file", lambda path: {
        "media_type": "video", "has_audio": True, "audio_direct": False, "duration": 9,
    })
    request = media.StageDownloadRequest(
        source_kind="url", source_value="https://v.douyin.com/aDqmydz7iGA/", rights_confirmed=True, managed=True,
    )
    with pytest.raises(desktop_sources.SourceError, match="下载到的不是正片"):
        desktop_sources.download("stage_download_short0001", request, {"media_type": "video", "duration": 275}, "", lambda *_: None)


def test_retry_does_not_reuse_empty_douyin_subtitle(tmp_path, monkeypatch):
    from app import desktop_jobs

    monkeypatch.setattr(media, "DATA_DIR", tmp_path)
    monkeypatch.setattr(media, "JOBS_DIR", tmp_path / "jobs")
    folder = tmp_path / "jobs" / "stage_transcribe_empty0001"
    folder.mkdir(parents=True)
    (folder / "english.srt").write_text("", encoding="utf-8")
    item = SimpleNamespace(
        platform="抖音", source_value="https://v.douyin.com/aDqmydz7iGA/", duration=275,
        result={"duration": 8.98, "english_srt_url": "/files/stage_transcribe_empty0001/english.srt"},
        stage_jobs={"download": "stage_download_old", "transcribe": "stage_transcribe_empty0001"},
        stage_details={},
    )
    assert desktop_jobs.douyin_result_stale(item) is True
    previous = SimpleNamespace(status="succeeded", request={}, result={
        "duration": 9, "source_video_url": "/files/stage_download_old/source.mp4",
        "english_srt_url": "/files/stage_transcribe_empty0001/english.srt",
    })
    assert desktop_jobs.reusable_stage(item, "download", previous, {}) is None
    assert desktop_jobs.reusable_stage(item, "transcribe", previous, {}) is None


def test_empty_transcription_is_not_success(monkeypatch, tmp_path):
    monkeypatch.setattr(media, "DATA_DIR", tmp_path)
    monkeypatch.setattr(media, "JOBS_DIR", tmp_path / "jobs")
    source_job = "stage_download_emptysource1"
    folder = tmp_path / "jobs" / source_job
    folder.mkdir(parents=True)
    (folder / "source.mp4").write_bytes(b"source")
    state = media.create_stage_job("transcribe", {"source_video_url": f"/files/{source_job}/source.mp4", "language": "auto"})

    def empty_transcript(job_id, source_path, **kwargs):
        path = media.artifact_path(job_id, "english.srt")
        path.write_text("", encoding="utf-8")
        return path

    monkeypatch.setattr(media, "transcribe_video", empty_transcript)
    media.run_stage_transcribe(state.job_id)
    saved = json.loads(media.state_path(state.job_id).read_text(encoding="utf-8"))
    assert saved["status"] == "failed"
    assert saved["message"] == "字幕没有可用的时间戳片段"
    assert "transcription completed" not in saved["message"]


NOTE_ID = "64f0aabbccddeeff00112233"
BARE_NOTE = f"https://www.xiaohongshu.com/explore/{NOTE_ID}"
LONG_NOTE = BARE_NOTE + "?xsec_token=abc&xsec_source=pc_share"


def _xhs_state(kind="video"):
    note = {
        "noteId": NOTE_ID, "type": kind, "title": "夜航" if kind == "video" else "图文",
        "desc": "正文一段", "user": {"nickname": "航线"},
        "imageList": [{"urlDefault": "https://sns-img.xhscdn.com/cover.jpg"}],
    }
    if kind == "video":
        note["video"] = {"capa": {"duration": 12500}, "media": {"stream": {
            "h264": [{"masterUrl": "https://sns-video.xhscdn.com/master.mp4",
                      "backupUrls": ["https://sns-video.xhscdn.com/backup.mp4"]}],
            "h265": [{"masterUrl": "https://sns-video.xhscdn.com/h265.mp4", "backupUrls": []}],
        }}}
    else:
        note["video"] = None
    return "<script>window.__INITIAL_STATE__=" + json.dumps({"note": {"noteDetailMap": {NOTE_ID: {"note": note}}}}, ensure_ascii=False) + "</script>"


def test_classify_letters_keeps_one_share_and_finds_paths():
    from app import share_text

    assert len(share_text.classify_letters("第一行\n" + DOUYIN_SHARE + "\n最后")) == 1
    split = share_text.classify_letters(DOUYIN_SHARE + "\n" + XHS_SHARE)
    assert [item["url"] for item in split] == ["https://v.douyin.com/aDqmydz7iGA/", "https://xhslink.cn/o/4LXLtDW6SVI"]
    assert len(share_text.classify_letters("https://example.com/a\nagain https://example.com/a")) == 1
    quoted = share_text.classify_letters(r'"D:\My Videos\clip.mp4"')
    assert quoted[0]["kind"] == "local" and quoted[0]["local"] is True
    assert quoted[0]["source"].casefold() == str(Path(r"D:\My Videos\clip.mp4")).casefold()
    unc = share_text.classify_letters(r"\\server\share\my file.mkv")
    assert unc[0]["kind"] == "local" and unc[0]["source"].lower().startswith("\\\\server\\share")
    filed = share_text.classify_letters("file:///D:/My%20Videos/clip.mp4")
    assert filed[0]["kind"] == "local" and "My Videos" in filed[0]["source"]
    mixed = share_text.classify_letters('"D:\\My Videos\\clip.mp4"\nhttps://example.com/a')
    assert [item["kind"] for item in mixed] == ["local", "url"]
    assert share_text.classify_letters("   ") == []


def test_xiaohongshu_fetch_url_is_not_replaced_by_canonical(monkeypatch, tmp_path):
    from app.sites import resolve
    from app import desktop_sources, workbench_cache as cache

    monkeypatch.setattr(media, "DATA_DIR", tmp_path)
    cache.initialize()
    video_html = _xhs_state("video")
    image_html = (
        '<script>window.__INITIAL_STATE__={"note":{"noteDetailMap":{"'
        + NOTE_ID + '":{"note":{"noteId":"' + NOTE_ID
        + '","type":"normal","title":"图文","desc":"正文","user":{"nickname":"作者"},'
        + '"imageList":[{"urlDefault":"https://sns-img.xhscdn.com/a.jpg"}],"video":undefined}}}}}</script>'
    )
    video = resolve.parse_document(LONG_NOTE, video_html)
    assert video["canonical_url"] == BARE_NOTE
    assert video["resolved_fetch_url"] == LONG_NOTE
    assert video["resolved_fetch_url"] != video["canonical_url"]
    assert video["video_url"] == "https://sns-video.xhscdn.com/master.mp4"
    assert video["backup_urls"] == ["https://sns-video.xhscdn.com/backup.mp4"]
    assert "https://sns-video.xhscdn.com/h265.mp4" in video["media_urls"]
    assert video["body"] == "正文一段" and video["author"] == "航线"
    assert video["image_note"] is False and video["duration"] == 12.5
    image = resolve.parse_document(LONG_NOTE, image_html)
    assert image["image_note"] is True and image["video_url"] == ""
    assert image["images"] == ["https://sns-img.xhscdn.com/a.jpg"] and image["body"] == "正文"
    assert resolve.xhs_capture_ready("", [], []) is False
    assert resolve.xhs_capture_ready("<html>login</html>", [], []) is False
    assert resolve.xhs_capture_ready(video_html, [], []) is True
    assert resolve.xhs_capture_ready("", ["https://sns-video.xhscdn.com/a.mp4"], []) is True
    assert resolve.xhs_capture_ready("", [], ["https://sns-video.xhscdn.com/player.mp4"]) is True

    def fetch(target):
        if "xhslink" in target:
            return 302, LONG_NOTE, "", ""
        assert "xsec_token=abc" in target
        return 200, "", video_html, "text/html"

    landed = resolve.resolve("https://xhslink.cn/o/4LXLtDW6SVI", fetch=fetch)
    assert landed["resolved_fetch_url"] == LONG_NOTE
    assert landed["canonical_url"] == BARE_NOTE
    assert cache.identity(LONG_NOTE) == cache.identity(BARE_NOTE) == "xiaohongshu:" + NOTE_ID
    request = SimpleNamespace(source_value=LONG_NOTE)
    assert desktop_sources.ytdlp_target(LONG_NOTE, landed) == LONG_NOTE
    assert desktop_sources.download_page_url(request, {"canonical_url": BARE_NOTE, "resolved_fetch_url": LONG_NOTE}) == LONG_NOTE
    monkeypatch.setattr(desktop_sources, "public_target", lambda *args, **kwargs: None)
    monkeypatch.setattr(resolve, "resolve", lambda url, fetch=None: dict(landed, url=LONG_NOTE))
    monkeypatch.setattr(desktop_sources, "dump_online", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("yt-dlp")))
    target, resolved = desktop_sources.prepare_social(LONG_NOTE, "")
    assert target == LONG_NOTE and resolved["canonical_url"] == BARE_NOTE
    info = desktop_sources.inspect_online(LONG_NOTE, "")
    assert info["media_type"] == "video" and info["media_url"].endswith("master.mp4")
    assert info["resolved_fetch_url"] == LONG_NOTE
    monkeypatch.setattr(resolve, "resolve", lambda url, fetch=None: dict(image, url=LONG_NOTE, html=""))
    note = desktop_sources.inspect_online(LONG_NOTE, "")
    assert note["media_type"] == "note" and note["resolved_fetch_url"] == LONG_NOTE
    assert desktop_sources.refresh_reason(desktop_sources.SourceError("session_required", "尚未登录小红书")) == "login"
    assert desktop_sources.refresh_reason(desktop_sources.SourceError("unavailable", "连接超时")) == "network"
    assert desktop_sources.refresh_reason(desktop_sources.SourceError("signature_expired", "链接签名已过期")) == "signature_expired"
    assert desktop_sources.refresh_reason(desktop_sources.SourceError("no_stream", "未找到可用的视频流")) == "no_media"

