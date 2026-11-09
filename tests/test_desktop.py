
"""Windows desktop integration tests. Media binaries are optional for the unit tests."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
import time

from fastapi.testclient import TestClient
import httpx
import pytest

if os.name != "nt":
    pytest.skip("Windows desktop tests", allow_module_level=True)

os.environ["MEDIA_DESKTOP"] = "1"

from app import desktop, desktop_routes, desktop_jobs, knowledge
from app import main as media

ORIGIN = "http://127.0.0.1:9810"


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


def wait_batch(client, batch_id):
    for _ in range(200):
        data = client.get(f"/ui/batches/{batch_id}").json()
        if data["status"] in {"failed", "succeeded"}:
            return data
        time.sleep(0.05)
    pytest.fail("batch did not settle")


def test_resume_and_bilibili_confirmation(desktop_app, monkeypatch):
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
        "subtitle_output_mode": "en_only", "rights_confirmed": True, "bilibili_upload": {"enabled": True},
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

