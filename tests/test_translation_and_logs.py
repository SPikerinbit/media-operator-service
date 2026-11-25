"""Tests for DeepSeek thinking-mode translation fix and curated workbench record logs."""
from __future__ import annotations

import json
import os
from types import SimpleNamespace

import httpx

os.environ["MEDIA_DESKTOP"] = "1"

from app import desktop_bilibili, knowledge, main as media
from app import workbench_inbox as inbox
from app import workbench_logs


def test_translate_disables_thinking_and_handles_400_fallback(monkeypatch):
    seen_bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen_bodies.append(body)
        if len(seen_bodies) == 1:
            assert body.get("thinking") == {"type": "disabled"}
            return httpx.Response(400, json={"error": {"message": "Unknown parameter: thinking"}})
        assert "thinking" not in body
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps({"items": [{"index": 1, "translation": "窗户里有敌人"}]})},
                    }
                ]
            },
        )

    real_client = httpx.Client
    monkeypatch.setattr(media, "TRANSLATE_PROVIDER", "deepseek")
    monkeypatch.setattr(media, "TRANSLATE_API_BASE", "https://api.deepseek.com")
    monkeypatch.setattr(media, "TRANSLATE_API_KEY", "sk-test")
    monkeypatch.setattr(media, "TRANSLATE_MODEL", "deepseek-flash")
    monkeypatch.setattr(
        media,
        "httpx",
        SimpleNamespace(
            Client=lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
            TransportError=httpx.TransportError,
            HTTPStatusError=httpx.HTTPStatusError,
        ),
    )

    out = media.translate_lines(["В окне"], "zh-CN")
    assert out == ["窗户里有敌人"]
    assert len(seen_bodies) == 2


def test_translate_retries_single_line_when_reasoning_exhausts_max_tokens(monkeypatch):
    seen_max_tokens: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen_max_tokens.append(body["max_tokens"])
        if len(seen_max_tokens) == 1:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "length",
                            "message": {"content": "", "reasoning_content": "thinking..." * 40},
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps({"items": [{"index": 1, "translation": "在窗口，完了"}]})},
                    }
                ]
            },
        )

    real_client = httpx.Client
    monkeypatch.setattr(media, "TRANSLATE_PROVIDER", "deepseek")
    monkeypatch.setattr(media, "TRANSLATE_API_BASE", "https://api.deepseek.com/chat/completions")
    monkeypatch.setattr(media, "TRANSLATE_API_KEY", "sk-test")
    monkeypatch.setattr(media, "TRANSLATE_MODEL", "deepseek-flash")
    monkeypatch.setattr(
        media,
        "httpx",
        SimpleNamespace(
            Client=lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
            TransportError=httpx.TransportError,
            HTTPStatusError=httpx.HTTPStatusError,
        ),
    )

    out = media.translate_lines(["окне В окне, пиздец"], "zh-CN")
    assert out == ["在窗口，完了"]
    assert len(seen_max_tokens) == 2
    assert seen_max_tokens[1] >= 4096 and seen_max_tokens[1] > seen_max_tokens[0]


def test_bilibili_metadata_disables_thinking_with_400_fallback(monkeypatch):
    seen_bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen_bodies.append(body)
        if len(seen_bodies) == 1:
            assert body.get("thinking") == {"type": "disabled"}
            return httpx.Response(400, text="unsupported field: thinking")
        assert "thinking" not in body
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps({"tid": 17, "title": "m0NESY 4000分 CS2 第一视角", "desc": "• CS2 对局实录", "tags": ["CS2"]})
                        },
                    }
                ]
            },
        )

    real_client = httpx.Client
    monkeypatch.setattr(media, "TRANSLATE_API_BASE", "https://api.deepseek.com")
    monkeypatch.setattr(media, "TRANSLATE_API_KEY", "sk-test")
    monkeypatch.setattr(media, "TRANSLATE_MODEL", "deepseek-flash")
    monkeypatch.setattr(
        desktop_bilibili,
        "httpx",
        SimpleNamespace(
            Client=lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
            Timeout=httpx.Timeout,
            HTTPError=httpx.HTTPError,
        ),
    )
    req = SimpleNamespace(
        original_title="m0NESY (29-12) 4000 ELO FACEIT",
        original_description="CS2 match",
        english_srt_url="",
        translate_model="deepseek-flash",
    )
    parsed = desktop_bilibili.request_metadata(req, {17: "游戏 / 单机游戏"}, ["tid", "title", "desc", "tags"])
    assert parsed["tid"] == 17 and len(seen_bodies) == 2


def test_bilibili_metadata_resilient_parsing_length_retry_and_missing_title_recovery(monkeypatch):
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        data = json.loads(body["messages"][1]["content"])
        # Placeholder original_title="video1" must be cleared before sending to DeepSeek.
        assert data["source_title"] == ""
        assert body["temperature"] == 0.2
        if len(calls) == 1:
            # 1st attempt: exhausted max_tokens while thinking -> triggers length retry with 6144 max_tokens.
            return httpx.Response(200, json={
                "choices": [{"finish_reason": "length", "message": {"content": "", "reasoning_content": "thinking..." * 40}}]
            })
        if len(calls) == 2:
            # 2nd attempt: fenced JSON, string tid, list desc, comma string tags, but placeholder title "video1".
            assert body["max_tokens"] == 6144
            fenced = '```json\n{"tid": "17", "title": "video1", "desc": ["• 对局复盘", "• 关键回合"], "tags": "CS2, 第一视角，教学"}\n```'
            return httpx.Response(200, json={
                "choices": [{"finish_reason": "stop", "message": {"content": fenced}}]
            })
        # 3rd attempt: targeted retry for missing/placeholder title succeeds.
        assert data["fields_to_fill"] == ["title"]
        return httpx.Response(200, json={
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"title": "CS2 关键回合复盘与战术解析"})}}]
        })

    real_client = httpx.Client
    monkeypatch.setattr(media, "TRANSLATE_API_BASE", "https://api.deepseek.com")
    monkeypatch.setattr(media, "TRANSLATE_API_KEY", "sk-test")
    monkeypatch.setattr(media, "TRANSLATE_MODEL", "deepseek-flash")
    monkeypatch.setattr(desktop_bilibili, "posting_zones", lambda: {17: "游戏 / 单机游戏"})
    monkeypatch.setattr(
        desktop_bilibili,
        "httpx",
        SimpleNamespace(
            Client=lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
            Timeout=httpx.Timeout,
            HTTPError=httpx.HTTPError,
        ),
    )
    req = media.StageBilibiliUploadRequest(
        final_video_url="/files/j/final.mp4",
        original_source="https://youtu.be/demo1234567",
        output_name="video1",
        original_title="video1",
        original_description="CS2 tactical round breakdown",
        upload_settings=media.BilibiliUploadSettings(
            enabled=True, auto_metadata=True, tid=None, title_template="", desc="", tags=[],
        ),
    )
    effective, meta = desktop_bilibili.prepare_metadata(req)
    assert len(calls) == 3
    assert effective.tid == 17
    assert effective.title_template == "CS2 关键回合复盘与战术解析"
    assert meta["title"] == "CS2 关键回合复盘与战术解析"
    assert effective.desc == "• 对局复盘\n• 关键回合"
    assert effective.tags == ["CS2", "第一视角", "教学"]
    assert set(meta["generated_fields"]) == {"tid", "title", "desc", "tags"}


def test_bilibili_metadata_falls_back_to_real_original_title_instead_of_video1(monkeypatch):
    def fail_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server error")

    real_client = httpx.Client
    monkeypatch.setattr(media, "TRANSLATE_API_BASE", "https://api.deepseek.com")
    monkeypatch.setattr(media, "TRANSLATE_API_KEY", "sk-test")
    monkeypatch.setattr(media, "TRANSLATE_MODEL", "deepseek-flash")
    monkeypatch.setattr(desktop_bilibili, "posting_zones", lambda: {201: "知识 / 科学"})
    monkeypatch.setattr(desktop_bilibili.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        desktop_bilibili,
        "httpx",
        SimpleNamespace(
            Client=lambda **kwargs: real_client(transport=httpx.MockTransport(fail_handler), **kwargs),
            Timeout=httpx.Timeout,
            HTTPError=httpx.HTTPError,
        ),
    )
    req = media.StageBilibiliUploadRequest(
        final_video_url="/files/j/final.mp4",
        original_source="https://youtu.be/demo1234567",
        output_name="video1",
        original_title="How Distributed Consensus Actually Works",
        original_description="Raft explained",
        upload_settings=media.BilibiliUploadSettings(
            enabled=True, auto_metadata=True, tid=201, title_template="", desc="", tags=[],
        ),
    )
    effective, meta = desktop_bilibili.prepare_metadata(req)
    assert effective.title_template == "How Distributed Consensus Actually Works"
    assert meta["title"] == "How Distributed Consensus Actually Works"
    assert meta["notice"] and meta["error_detail"]


def test_curated_publish_log_folds_download_burn_and_upload_noise(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "DATA_DIR", tmp_path)
    monkeypatch.setattr(media, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(media, "BATCHES_DIR", tmp_path / "batches")
    media.JOBS_DIR.mkdir()
    media.BATCHES_DIR.mkdir()
    knowledge.initialize()

    dl_job = "stage_download_test01"
    (media.JOBS_DIR / dl_job).mkdir()
    dl_lines = ["2026-11-25T01:00:00+00:00\tdownload\t1\t正在导入素材"]
    dl_lines += [f"2026-11-25T01:01:{i % 60:02d}+00:00\tdownload\t{min(94, i)}\t正在下载素材" for i in range(1, 201)]
    dl_lines.append("2026-11-25T01:04:00+00:00\tdownload\t100\t素材已导入")
    media.stage_progress_log_path(dl_job).write_text("\n".join(dl_lines) + "\n", encoding="utf-8")
    (media.JOBS_DIR / dl_job / "yt-dlp.out.log").write_text(
        "\n".join(f"[download]  {i / 2:.1f}% of 100MiB at 1MiB/s ETA 00:10" for i in range(1, 201)) + "\n",
        encoding="utf-8",
    )
    (media.JOBS_DIR / dl_job / "yt-dlp.err.log").write_text(
        "WARNING: \x1b[31mdeno warning\x1b[0m sessionid=secret123\n",
        encoding="utf-8",
    )

    tl_job = "stage_translate_test01"
    (media.JOBS_DIR / tl_job).mkdir()
    err_json = json.dumps({
        "stage": "translate",
        "type": "RuntimeError",
        "message": "DeepSeek 没有返回有效译文，请检查模型配置后重试",
        "cause": "ValueError(\"empty translation content (finish_reason='length', reasoning_len=1000)\")",
    }, ensure_ascii=False)
    media.stage_progress_log_path(tl_job).write_text(
        "\n".join([
            "2026-11-25T01:04:01+00:00\ttranslate\t5\tstarting translation with deepseek-flash",
            "2026-11-25T01:04:02+00:00\ttranslate\t8\treading source subtitles",
            f"2026-11-25T01:05:00+00:00\ttranslate\t100\tDeepSeek 没有返回有效译文，请检查模型配置后重试 | {err_json}",
        ]) + "\n",
        encoding="utf-8",
    )

    burn_job = "stage_burn_test01"
    (media.JOBS_DIR / burn_job).mkdir()
    burn_lines = [
        "2026-11-25T01:05:01+00:00\tburn\t5\tstarting subtitle burn",
        "2026-11-25T01:05:02+00:00\tburn\t10\tNVIDIA NVENC 编码",
    ]
    burn_lines += [f"2026-11-25T01:05:{(i % 50) + 3:02d}+00:00\tburn\t{min(95, 10 + i)}\trendered {i:.1f}s / 120.0s | out_time_ms={i * 1000000}" for i in range(1, 121)]
    burn_lines.append("2026-11-25T01:05:55+00:00\tburn\t100\tsubtitle burn completed")
    media.stage_progress_log_path(burn_job).write_text("\n".join(burn_lines) + "\n", encoding="utf-8")

    entry = {
        "id": "pub-1",
        "lane": "publish",
        "status": "failed",
        "stage": "translate",
        "message": "DeepSeek 没有返回有效译文，请检查模型配置后重试",
        "task": {
            "status": "failed",
            "stage": "translate",
            "stage_jobs": {"download": dl_job, "translate": tl_job, "burn": burn_job},
            "stage_details": {
                "download": {"status": "succeeded", "progress": 100, "message": "素材已导入"},
                "translate": {"status": "failed", "progress": 100, "message": "DeepSeek 没有返回有效译文，请检查模型配置后重试"},
                "burn": {"status": "succeeded", "progress": 100, "message": "subtitle burn completed"},
            },
        },
        "result": {},
    }

    curated = workbench_logs.build_entry_log(entry, scrub=inbox.scrub_log)
    assert curated["raw_total"] > 500
    assert curated["total"] < 15
    assert curated["folded_count"] > 500
    assert [s["stage"] for s in curated["stages"]] == ["download", "translate", "burn"]
    dl_stage, tl_stage, burn_stage = curated["stages"]
    assert len(dl_stage["events"]) == 2
    assert dl_stage["duration_label"] == "4 分"
    assert any(ev["level"] == "error" and "DeepSeek" in ev["text"] for ev in tl_stage["events"])
    assert any("长度上限" in ev["text"] for ev in tl_stage["events"])
    assert all("{" not in line and "\x1b" not in line and "secret123" not in line for line in curated["lines"])
    assert len(burn_stage["events"]) == 4

    raw_page = workbench_logs.build_entry_log(entry, raw=True, offset=0, limit=50, scrub=inbox.scrub_log)
    assert raw_page["raw"] is True
    assert raw_page["total"] == curated["raw_total"]
    raw_all = workbench_logs.raw_log_lines(entry, inbox.scrub_log)
    assert all("secret123" not in line and "\x1b" not in line for line in raw_all)


def test_curated_notes_log_includes_reused_skipped_and_note_run_extract(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "DATA_DIR", tmp_path)
    monkeypatch.setattr(media, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(media, "BATCHES_DIR", tmp_path / "batches")
    media.JOBS_DIR.mkdir()
    media.BATCHES_DIR.mkdir()
    knowledge.initialize()
    from app import note_engine
    note_engine.initialize()

    srt_file = tmp_path / "sample.srt"
    srt_file.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello world\n", encoding="utf-8")
    tid = knowledge.register(srt_file, source_kind="url", source="https://example.com/n", title="测试笔记")
    with knowledge.database() as db:
        db.execute(
            """INSERT INTO note_run(id, transcript_id, mode, status, phase, input_tokens, output_tokens,
               version, updated, detected_language, translation_strategy, saved_tokens, model)
               VALUES('run-1', ?, 'curated', 'succeeded', 'done', 1200, 450, 'v', 1.0, 'foreign', 'cited_only', 300, 'deepseek-flash')""",
            (tid,),
        )
        db.execute(
            "INSERT INTO note_node(run, key, level, position, cue, status) VALUES('run-1', 'k1', 0, 1, 1, 'done')"
        )

    entry = {
        "id": "note-1",
        "lane": "notes",
        "status": "succeeded",
        "stage": "done",
        "execution_mode": "curated",
        "message": "已完成",
        "result": {"transcript_id": tid, "note_notice": "已生成 5 条观点"},
        "reuse": [{"stage": "download", "origin_lane": "publish"}],
        "task": {
            "status": "succeeded",
            "stage": "done",
            "stage_jobs": {},
            "stage_details": {
                "download": {"status": "succeeded", "progress": 100, "reused": True, "origin_lane": "publish"},
                "translate": {"status": "succeeded", "progress": 100, "skipped": True, "message": "跨语精选并仅译引用原句"},
                "extract": {"status": "succeeded", "progress": 100, "message": "已生成 5 条观点"},
            },
        },
    }

    curated = workbench_logs.build_entry_log(entry, scrub=inbox.scrub_log)
    stages_by_key = {s["stage"]: s for s in curated["stages"]}
    assert set(stages_by_key) == {"download", "translate", "extract"}
    assert stages_by_key["download"]["status"] == "reused"
    assert stages_by_key["translate"]["status"] == "skipped"
    extract_text = " ".join(ev["text"] for ev in stages_by_key["extract"]["events"])
    assert "精华观点" in extract_text and "deepseek-flash" in extract_text
    assert "1/1" in extract_text and "1,650 token" in extract_text and "已生成 5 条观点" in extract_text
