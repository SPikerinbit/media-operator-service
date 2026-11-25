import json
from types import SimpleNamespace

import pytest


def test_douyin_url_variants_and_cache_identity(tmp_path, monkeypatch):
    from app import desktop_sources, main as media, workbench_cache
    from app.sites import resolve

    monkeypatch.setattr(media, "DATA_DIR", tmp_path)
    workbench_cache.initialize()

    aweme = "7456789012345678901"
    variants = [
        f"https://www.douyin.com/video/{aweme}",
        f"https://www.douyin.com/discover?modal_id={aweme}&extra=1",
        f"https://www.douyin.com/user/MS4wLjABAAAAxyz?modal_id={aweme}",
        f"https://www.douyin.com/jingxuan?modal_id={aweme}",
        f"https://www.iesdouyin.com/share/video/{aweme}/?region=CN",
        f"https://www.douyin.com/note/{aweme}",
        f"https://www.douyin.com/slides/{aweme}",
    ]
    for url in variants:
        info = resolve.classify(url)
        assert info["platform"] == "抖音", url
        assert info["aweme_id"] == aweme, url
        assert desktop_sources.site(url)[0] == "抖音", url
        assert workbench_cache.identity(url) == f"douyin:{aweme}", url


def test_player_feature_skips_route_mention_and_reads_video_duration_not_music():
    from app.sites import resolve

    aweme = "7456789012345678901"
    mirror_1 = "https://v26-web.douyinvod.com/mirror-1.mp4"
    mirror_2 = "https://v3-web.douyinvod.com/mirror-2.mp4"
    html = json.dumps({
        "routeParams": {"aweme_id": aweme, "tab": "discover"},
        "recommendations": [
            {
                "aweme_id": "9999999999999999999",
                "video": {"duration": 12000, "play_addr": {"url_list": ["https://v9-web.douyinvod.com/other.mp4"]}},
            }
        ],
        "aweme_detail": {
            "aweme_id": aweme,
            "desc": "真正目标视频标题",
            "author": {"nickname": "目标作者"},
            "music": {"duration": 15},  # Seconds — MUST NOT be confused with video.duration (ms)
            "video": {
                "duration": 182400,
                "bit_rate": [
                    {"bit_rate": 800000, "is_bytevc1": 0, "play_addr": {"url_list": ["https://cdn.example/low.mp4"]}},
                    {"bit_rate": 2400000, "is_bytevc1": 0, "play_addr": {"url_list": [mirror_1, mirror_2]}},
                ],
            },
        },
    }, ensure_ascii=False)
    feature = resolve.player_feature(html, aweme)
    assert feature is not None
    assert feature["aweme_id"] == aweme
    assert feature["url"] == mirror_1
    assert mirror_1 in feature["play_urls"] and mirror_2 in feature["play_urls"]
    assert abs(feature["duration"] - 182.4) < 0.01
    assert feature["title"] == "真正目标视频标题"
    assert feature["author"] == "目标作者"


def test_player_feature_parses_rsc_flight_escaped_payload():
    from app.sites import resolve

    aweme = "7488888888888888888"
    stream = "https://v26-web.douyinvod.com/rsc-stream.mp4"
    inner = json.dumps({
        "awemeDetail": {
            "awemeId": aweme,
            "desc": "RSC 嵌套作品",
            "video": {
                "duration": 22500,
                "playAddr": [{"src": stream}],
            },
        }
    }, ensure_ascii=False)
    html = f'<script>self.__pace_f.push([1,{json.dumps(inner)}])</script>'
    feature = resolve.player_feature(html, aweme)
    assert feature is not None
    assert feature["url"] == stream
    assert abs(feature["duration"] - 22.5) < 0.01
    assert feature["title"] == "RSC 嵌套作品"


def test_douyin_api_detail_and_image_slides():
    from app.sites import resolve

    aweme = "7411111111111111111"
    api_json = json.dumps({
        "status_code": 0,
        "aweme_detail": {
            "aweme_id": aweme,
            "aweme_type": 68,
            "desc": "抖音图文干货",
            "author": {"nickname": "笔记博主"},
            "images": [
                {"url_list": ["https://p3-pc.douyinpic.com/img1.webp"]},
                {"url_list": ["https://p3-pc.douyinpic.com/img2.webp"]},
            ],
        },
    }, ensure_ascii=False)
    detail = resolve.extract_douyin_api_detail(api_json, aweme)
    assert detail is not None
    assert detail["image_note"] is True
    assert len(detail["images"]) == 2
    assert detail["title"] == "抖音图文干货"


def test_douyin_share_prefix_not_misread_as_duration_and_short_clip_succeeds(monkeypatch, tmp_path):
    from app import desktop_sources, main as media, share_text

    monkeypatch.setattr(media, "DATA_DIR", tmp_path)
    monkeypatch.setattr(media, "JOBS_DIR", tmp_path / "jobs")
    parsed = share_text.parse("4.35 复制打开抖音，看看【作者的作品】短片测试 https://v.douyin.com/shortClip/")
    assert len(parsed) == 1
    assert "duration" not in parsed[0]

    mirror_bad = "https://v26-web.douyinvod.com/bad-403.mp4"
    mirror_ok = "https://v3-web.douyinvod.com/good-18s.mp4"
    monkeypatch.setattr(desktop_sources, "prepare_social", lambda url, cookies: (
        "https://www.douyin.com/video/7400000000000000001",
        {
            "aweme_id": "7400000000000000001",
            "canonical_url": "https://www.douyin.com/video/7400000000000000001",
            "duration": 18.0,
            "video_url": mirror_bad,
            "play_urls": [mirror_bad, mirror_ok],
        },
    ))
    tried = []

    def fake_direct(url, folder, cookies, progress, referer):
        tried.append(url)
        if url == mirror_bad:
            raise desktop_sources.SourceError("unavailable", "CDN 403")
        out = folder / "source.mp4"
        out.write_bytes(b"ok-18s")
        return out

    monkeypatch.setattr(desktop_sources, "download_direct", fake_direct)
    monkeypatch.setattr(desktop_sources, "inspect_file", lambda path: {
        "media_type": "video", "has_audio": True, "audio_direct": False, "duration": 18.2,
    })
    request = media.StageDownloadRequest(
        source_kind="url", source_value="https://v.douyin.com/shortClip/", rights_confirmed=True, managed=True,
    )
    _path, info, actual = desktop_sources.download(
        "stage_download_short_douyin", request, {"media_type": "video"}, "", lambda *_: None,
    )
    assert tried == [mirror_bad, mirror_ok]
    assert actual["duration"] == 18.2
    assert info["aweme_id"] == "7400000000000000001"


def test_douyin_dash_video_only_muxes_audio_for_publish(monkeypatch, tmp_path):
    from app import desktop_sources, main as media

    calls = []

    def fake_download_bytes(url, stem, referer, cookies, limit):
        out = stem.with_suffix(".m4a")
        out.write_bytes(b"audio")
        return out.name

    def fake_run_command(cmd, **kwargs):
        calls.append(cmd)
        tmp_path.joinpath("source-muxed.mp4").write_bytes(b"muxed")

    monkeypatch.setattr(desktop_sources, "download_bytes", fake_download_bytes)
    monkeypatch.setattr(media, "run_command", fake_run_command)
    monkeypatch.setattr(desktop_sources, "inspect_file", lambda path: {
        "media_type": "video", "has_audio": True, "audio_direct": False, "duration": 60.0,
    })
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video-only")
    req = SimpleNamespace(audio_only=False, allow_muxed_audio=True)
    path, _, actual = desktop_sources.finish_media(
        video, {"audio_url": "https://v26-web.douyinvod.com/audio.m4a"},
        {"media_type": "video", "has_audio": False, "audio_direct": False, "duration": 60.0},
        req, tmp_path,
    )
    assert path.name == "source-muxed.mp4"
    assert actual["has_audio"] is True
    assert calls and "-c" in calls[0]


def test_fake_ip_resolves_via_doh_or_gives_actionable_error(monkeypatch):
    from app import source_network

    monkeypatch.setattr(
        source_network.socket, "getaddrinfo",
        lambda host, port, type=None: [(2, 1, 6, "", ("198.18.1.107", port))],
    )
    monkeypatch.setattr(source_network, "direct_dns", lambda host, period: ("111.13.100.91",))
    _, _, ips = source_network.public_target("https://v.douyin.com/aDqmydz7iGA/", upstream=None)
    assert ips == ("111.13.100.91",)

    monkeypatch.setattr(source_network, "direct_dns", lambda host, period: (_ for _ in ()).throw(ValueError("offline")))
    with pytest.raises(ValueError, match="198.18"):
        source_network.public_target("https://v.douyin.com/aDqmydz7iGA/", upstream=None)
