"""Resolve public media and keep site sessions outside persisted task data."""
from contextlib import contextmanager
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlsplit

import httpx

from app import main as media
from app.source_network import public_proxy, public_target

LOCK = threading.Lock()
PROBE_SLOTS = threading.BoundedSemaphore(3)
SESSIONS = {}
PROBES = {}
AUDIO_EXTS = {"aac", "flac", "m4a", "mp3", "oga", "ogg", "opus", "wav", "wma"}
VIDEO_EXTS = {"avi", "flv", "m4v", "mkv", "mov", "mp4", "ts", "wmv"}
SITES = (
    ("YouTube", ("youtube.com", "youtu.be")),
    ("B 站", ("bilibili.com", "b23.tv")),
    ("抖音", ("douyin.com",)),
    ("小红书", ("xiaohongshu.com", "xhslink.com", "xhslink.cn")),
    ("小宇宙", ("xiaoyuzhoufm.com",)),
)


class SourceError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def domain_matches(host, domain):
    return host == domain or host.endswith("." + domain)


def site(url):
    host = urlsplit(url).hostname or ""
    for label, domains in SITES:
        if any(domain_matches(host, domain) for domain in domains):
            return label, domains
    return host, (host,)


def prune():
    now = time.monotonic()
    for store in (SESSIONS, PROBES):
        for key, (expiry, _) in list(store.items()):
            if expiry <= now:
                store.pop(key, None)


def register_session(url, contents):
    if len(contents) > 512 * 1024:
        raise SourceError("invalid_session", "Cookie 文件过大")
    try:
        public_target(url, media.online_media_proxy(url))
        _, domains = site(url)
        content = contents.decode("utf-8-sig")
    except (OSError, ValueError) as error:
        raise SourceError("invalid_session", "无法读取本站 Cookie 文件") from error
    if not content.startswith(("# Netscape HTTP Cookie File", "# HTTP Cookie File")):
        raise SourceError("invalid_session", "请选择 Netscape 格式的 Cookie 文件")
    rows = []
    for line in content.splitlines():
        if not line or (line.startswith("#") and not line.startswith("#HttpOnly_")):
            continue
        fields = line.split("\t")
        if len(fields) != 7:
            continue
        domain = fields[0].removeprefix("#HttpOnly_").lstrip(".").lower()
        if any(domain_matches(domain, allowed) for allowed in domains):
            rows.append(line)
    if not rows:
        raise SourceError("invalid_session", "文件中没有与此站点匹配的 Cookie")
    session = secrets.token_urlsafe(24)
    with LOCK:
        prune()
        SESSIONS[session] = (time.monotonic() + 3600, (domains, "\n".join(rows)))
    return session


def session_for(url, session):
    if not session:
        return None
    with LOCK:
        prune()
        record = SESSIONS.get(session)
    if not record or record[1][0] != site(url)[1]:
        raise SourceError("session_required", "站点会话已失效，请重新选择 Cookie 文件")
    return record[1][1]


def cookies_for(url, session=""):
    if session:
        return session_for(url, session)
    from app import site_profiles

    return site_profiles.cookie_rows(url)


def clear_site_probes(label):
    with LOCK:
        for key in list(PROBES):
            if site(key[1])[0] == label:
                PROBES.pop(key, None)


def referer_for(url):
    label = site(url)[0]
    if label == "抖音":
        return "https://www.douyin.com/"
    if label == "小红书":
        return "https://www.xiaohongshu.com/"
    return ""


def forget_session(session):
    if not session:
        return
    with LOCK:
        SESSIONS.pop(session, None)
        for key in [key for key in PROBES if key[2] == session]:
            PROBES.pop(key, None)


@contextmanager
def downloader(url, cookies=None):
    public_target(url, media.online_media_proxy(url))
    with public_proxy(media.online_media_proxy) as proxy, tempfile.TemporaryDirectory(prefix="media-source-") as directory:
        flags = media.yt_dlp_network_flags(url)
        if "--proxy" in flags:
            index = flags.index("--proxy")
            del flags[index:index + 2]
        cmd = [media.YT_DLP_BIN, *flags, "--ignore-config", "--no-cache-dir", "--no-plugin-dirs",
               "--proxy", proxy, "--no-playlist", "--playlist-items", "1", "--no-mtime",
               "--socket-timeout", "60", "--retries", "3", "--extractor-retries", "3",
               "--downloader", "native"]
        ffmpeg = media.yt_dlp_ffmpeg_location()
        if ffmpeg:
            cmd += ["--ffmpeg-location", ffmpeg]
        referer = referer_for(url)
        if referer:
            cmd += ["--referer", referer]
        if cookies:
            path = Path(directory) / "session.txt"
            path.write_text("# Netscape HTTP Cookie File\n" + cookies + "\n", encoding="utf-8")
            cmd += ["--cookies", str(path)]
        yield cmd, Path(directory)


def extract_error(url, diagnostic, *, has_session=False):
    from app.sites.resolve import classify

    label = site(url)[0]
    lower = diagnostic.lower()
    kind = classify(url).get("kind")
    if label == "抖音" and "http error 403" in lower and ("web detail json" in lower or kind == "short"):
        if has_session:
            return SourceError("site_blocked", "已使用本站 Cookie，抖音拒绝了详情接口，将用已登录页面重试。")
        return SourceError("session_required", "尚未登录抖音。抖音拒绝读取视频详情（403）。请在设置中登录抖音后重试。")
    if label == "小红书":
        for address in re.findall(r"Unsupported URL:\s+(https?://\S+)", diagnostic, flags=re.IGNORECASE):
            target = urlsplit(address)
            if domain_matches(target.hostname or "", "xiaohongshu.com") and target.path.rstrip("/") == "/login":
                if has_session:
                    return SourceError("session_required", "已使用本站 Cookie，小红书仍跳转到了登录页。将用已登录页面重试。")
                return SourceError("session_required", "尚未登录小红书。小红书跳转到了登录页。请在设置中登录小红书后重试。")
        if "no video formats" in lower or "no formats" in lower:
            if has_session:
                return SourceError("no_stream", "已读取小红书笔记页面，但未找到可用的视频流。将用已登录页面重试。")
            return SourceError("no_stream", "已读取小红书笔记页面，但未找到可用的视频流。可重新复制原笔记的完整分享链接。")
    if any(word in lower for word in ("cookies", "sign in", "login", "log in", "captcha")):
        return SourceError("session_required", "站点要求登录或会话验证")
    if any(word in lower for word in ("no video formats", "unsupported url", "no formats", "unable to extract")):
        return SourceError("no_stream", "此链接当前没有可读取的媒体")
    if any(word in lower for word in ("connection", "proxy", "timed out", "timeout", "unreachable")):
        return SourceError("unavailable", f"无法连接到 {label}，请检查 Windows 代理或网络后重试")
    return SourceError("unavailable", f"无法读取 {label} 的素材，请检查链接是否仍可访问")


def inspect_file(path):
    process = subprocess.run(
        [media.FFPROBE_BIN, "-v", "error", "-protocol_whitelist", "file,crypto,data",
         "-show_entries", "stream=codec_type:stream_disposition=attached_pic:format=duration,format_name",
         "-of", "json", str(path)],
        capture_output=True, timeout=18, creationflags=media.WINDOW_FLAGS,
    )
    if process.returncode:
        raise SourceError("no_stream", "文件中没有可读取的音视频流")
    data = json.loads(process.stdout)
    streams = data.get("streams", [])
    audio = any(stream.get("codec_type") == "audio" for stream in streams)
    video = any(stream.get("codec_type") == "video" and not stream.get("disposition", {}).get("attached_pic")
                for stream in streams)
    if not audio and not video:
        raise SourceError("no_stream", "文件中没有可读取的音视频流")
    return {"media_type": "video" if video else "audio", "has_audio": audio,
            "duration": seconds(data.get("format", {}).get("duration")), "audio_direct": not video}


def seconds(value):
    try:
        number = float(value)
        return number if 0 < number < 1e8 else None
    except (ValueError, TypeError):
        return None


class EpisodePage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.audio = ""
        self.title = ""
        self.capturing = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            if attrs.get("property") in {"og:audio", "og:audio:url", "og:audio:secure_url"}:
                self.audio = self.audio or attrs.get("content", "")
            elif attrs.get("property") == "og:title":
                self.title = attrs.get("content", "")
        elif tag == "script":
            self.capturing = attrs.get("id") == "__NEXT_DATA__"

    def handle_endtag(self, tag):
        if tag == "script":
            self.capturing = False

    def handle_data(self, data):
        if self.capturing:
            self.parts.append(data)


@contextmanager
def public_client(headers=None):
    with public_proxy(media.online_media_proxy) as proxy, httpx.Client(
        proxy=proxy, trust_env=False, follow_redirects=True, max_redirects=8, timeout=20, headers=headers,
    ) as client:
        yield client


def is_episode(url):
    parsed = urlsplit(url)
    return (parsed.hostname in {"www.xiaoyuzhoufm.com", "xiaoyuzhoufm.com"}
            and re.fullmatch(r"/episode/[a-f0-9]+/?", parsed.path) is not None)


def podcast_episode(url):
    if not is_episode(url):
        raise SourceError("no_stream", "请输入单集节目链接")
    page = EpisodePage()
    with public_client() as client, client.stream("GET", url) as response:
        response.raise_for_status()
        if not is_episode(str(response.url)):
            raise SourceError("no_stream", "没有找到公开节目页")
        content = bytearray()
        for chunk in response.iter_bytes():
            content.extend(chunk)
            if len(content) > 2_500_000:
                raise SourceError("no_stream", "节目页数据超出读取限制")
    page.feed(content.decode("utf-8", "replace"))
    payload = json.loads("".join(page.parts)) if page.parts else {}
    episode = payload.get("props", {}).get("pageProps", {}).get("episode", {})
    if episode.get("isPrivateMedia"):
        raise SourceError("session_required", "节目音频需要访问权限")
    address = (page.audio or (episode.get("enclosure") or {}).get("url")
               or ((episode.get("media") or {}).get("source") or {}).get("url"))
    if not address:
        raise SourceError("no_stream", "公开节目页未提供音频")
    public_target(address, media.online_media_proxy(address))
    return {"title": episode.get("title") or page.title, "duration": seconds(episode.get("duration")),
            "description": episode.get("description"), "address": address}


def note_info(url, resolved):
    body = resolved.get("body") or resolved.get("description") or ""
    return {
        "title": resolved.get("title") or "", "description": resolved.get("description") or body, "body": body,
        "author": resolved.get("author") or "", "platform": site(url)[0], "media_type": "note",
        "has_audio": False, "audio_direct": False, "duration": None,
        "images": list(resolved.get("images") or []), "canonical_url": resolved.get("canonical_url") or "",
        "resolved_fetch_url": resolved.get("resolved_fetch_url") or url,
        "original_url": resolved.get("original_url") or url,
    }


def refresh_reason(error):
    """Why a later retry may refresh the fetch URL: login, network, signature_expired, or no_media."""
    code = getattr(error, "code", "") or ""
    text = str(error or "")
    lowered = text.lower()
    if code in {"session_required", "site_blocked"} or "登录" in text or "login" in lowered:
        return "login"
    if code == "signature_expired" or "签名" in text or "xsec" in lowered or "signature" in lowered:
        return "signature_expired"
    if code == "unavailable" or any(word in lowered for word in ("timeout", "timed out", "proxy", "connection", "unreachable")) or any(
        word in text for word in ("网络", "超时", "代理")
    ):
        return "network"
    if code in {"no_stream", "note_only"} or "没有可读取" in text or "未找到" in text or "没有找到" in text:
        return "no_media"
    return ""


def download_page_url(request, info):
    """Page URL passed to the downloader. Identity/canonical is not a fetch URL."""
    info = info or {}
    fetch = info.get("resolved_fetch_url") or ""
    label = site(getattr(request, "source_value", "") or "")[0]
    if label == "小红书":
        return fetch or request.source_value
    if fetch:
        return fetch
    return info.get("canonical_url") or request.source_value


def ytdlp_target(url, resolved):
    from app.sites.resolve import classify

    resolved = resolved or {}
    canonical = resolved.get("canonical_url") or ""
    fetch = resolved.get("resolved_fetch_url") or ""
    label = site(url)[0]
    if label == "抖音" and classify(url).get("kind") == "short":
        if canonical and "/video/" in urlsplit(canonical).path:
            return canonical
        if fetch and "/video/" in urlsplit(fetch).path:
            return fetch
        return ""
    if label == "小红书":
        return fetch or url
    return fetch or canonical or url


def duration_matches(actual, expected):
    if not expected:
        return True
    try:
        actual_seconds = float(actual)
        expected_seconds = float(expected)
    except (TypeError, ValueError):
        return False
    if actual_seconds <= 0 or expected_seconds <= 0:
        return False
    return expected_seconds * 0.5 <= actual_seconds <= expected_seconds * 1.5


def browser_page(url):
    from app import site_profiles
    from app.sites import resolve

    if not site_profiles.can_capture(url):
        return None
    try:
        found = site_profiles.capture(url)
    except Exception:
        return None
    parsed = resolve.parse_document(found.get("url") or url, found.get("html") or "")
    parsed["sniffed"] = [] if parsed.get("platform") == "抖音" else list(found.get("media_urls") or [])
    parsed["html"] = found.get("html") or ""
    if found.get("duration") and not parsed.get("duration"):
        parsed["duration"] = found["duration"]
    if parsed.get("platform") == "抖音" and found.get("media_urls"):
        parsed["play_urls"] = list(found["media_urls"])
        parsed["video_url"] = found["media_urls"][0]
    if parsed.get("platform") == "抖音" and found.get("audio_urls"):
        parsed["audio_url"] = found["audio_urls"][0]
    elif parsed.get("audio_url") is None:
        parsed["audio_url"] = ""
    return parsed


def prepare_social(url, cookies):
    from app.sites import resolve

    label = site(url)[0]
    if label not in {"抖音", "小红书"}:
        return url, {}
    browser = browser_page(url) if label == "抖音" and resolve.classify(url).get("kind") == "short" else None
    try:
        resolved = browser or resolve.resolve(url, fetch=lambda target: resolve.fetch_public(
            target, cookies=cookies or "", referer=referer_for(url),
        ))
    except Exception:
        if not browser:
            return url, {}
        resolved = browser
    if browser and resolved is not browser:
        for key in ("canonical_url", "aweme_id", "video_id", "title", "author", "description", "duration"):
            if browser.get(key) and not resolved.get(key):
                resolved[key] = browser[key]
    if label == "抖音":
        chosen = []
        for item in [resolved.get("video_url"), *(resolved.get("play_urls") or [])]:
            if item and item not in chosen:
                chosen.append(item)
        resolved["play_urls"] = chosen
        resolved["video_url"] = chosen[0] if chosen else ""
    else:
        play = resolve.rank_media_urls(
            [*(resolved.get("media_urls") or []), *((browser or {}).get("sniffed") or []), resolved.get("video_url") or ""],
            resolved.get("aweme_id") or resolved.get("video_id") or "",
        )
        if play:
            resolved["play_urls"] = play
            resolved["video_url"] = play[0]
    if label != "抖音" and not resolved.get("duration"):
        resolved["duration"] = resolve.page_duration(resolved.get("html") or (browser or {}).get("html") or "")
    resolved["page_notes"] = resolve.page_notes(
        resolved.get("html") or (browser or {}).get("html") or "",
        resolved.get("url") or resolved.get("canonical_url") or url,
    )
    notes = resolved.setdefault("page_notes", {})
    if resolved.get("duration"):
        notes["video_duration"] = resolved["duration"]
    notes["media_count"] = len(resolved.get("play_urls") or [])
    resolved.pop("html", None)
    resolved.pop("sniffed", None)
    canonical = resolved.get("canonical_url") or ""
    if canonical:
        try:
            public_target(canonical, media.online_media_proxy(canonical))
        except ValueError:
            canonical = ""
            resolved["canonical_url"] = ""
    if canonical:
        resolve.remember(url, canonical)
        resolve.remember(canonical, canonical)
    elif label != "小红书":
        resolved["canonical_url"] = ""
        canonical = "" if label == "抖音" and resolve.classify(url).get("kind") == "short" else url
    fetch = resolved.get("resolved_fetch_url") or resolved.get("url") or url
    if label == "抖音" and resolve.classify(url).get("kind") == "short":
        fetch = canonical if canonical and "/video/" in urlsplit(canonical).path else ""
        resolved["resolved_fetch_url"] = fetch
        target = fetch or url
    elif label == "小红书":
        candidates = [resolved.get("resolved_fetch_url") or "", resolved.get("url") or "", url]
        with_query = [item for item in candidates if item and urlsplit(item).query]
        fetch = with_query[0] if with_query else (next((item for item in candidates if item), url))
        resolved["resolved_fetch_url"] = fetch
        resolved["original_url"] = resolved.get("original_url") or url
        if canonical and fetch:
            resolve.remember(fetch, canonical)
        target = fetch
    else:
        resolved["resolved_fetch_url"] = fetch
        target = fetch or canonical or url
    if resolved.get("login_wall") and not cookies:
        raise SourceError("session_required", f"尚未登录{label}。请在设置中登录{label}后重试。")
    return target, resolved


def apply_resolved(info, resolved):
    if not resolved:
        return info
    if resolved.get("title") and not info.get("title"):
        info["title"] = resolved["title"]
    if resolved.get("author"):
        info["author"] = resolved["author"]
    if resolved.get("description") and not info.get("description"):
        info["description"] = resolved["description"]
    if resolved.get("canonical_url"):
        info["canonical_url"] = resolved["canonical_url"]
    for key in ("resolved_fetch_url", "original_url"):
        if resolved.get(key):
            info[key] = resolved[key]
    if resolved.get("body"):
        info["body"] = resolved["body"]
    return info


def _page_opened(url, cookies, error):
    from app import site_profiles

    return bool(cookies and site_profiles.can_capture(url) and error.code in {"site_blocked", "session_required", "no_stream"}
                and site(url)[0] in {"抖音", "小红书"})


def should_recover(url, error, cookies):
    if site(url)[0] not in {"抖音", "小红书"}:
        return False
    if error.code == "no_stream":
        return True
    return error.code in {"site_blocked", "session_required"} and bool(cookies)


def load_page(url, cookies):
    from app import site_profiles
    from app.sites import resolve

    if site_profiles.can_capture(url):
        try:
            return site_profiles.capture(url)
        except Exception:
            pass
    resolved = resolve.resolve(url, fetch=lambda target: resolve.fetch_public(
        target, cookies=cookies or "", referer=referer_for(url),
    ))
    return {"url": resolved.get("url") or url, "html": resolved.get("html") or "", "media_urls": [], "webview": False}


def recover_page(url, cookies, error, page=None):
    from app.sites.resolve import parse_document, rank_media_urls

    if not should_recover(url, error, cookies):
        return None
    loaded = page or {}
    if not loaded.get("play_urls") and not loaded.get("html") and not loaded.get("media_urls"):
        try:
            loaded = load_page(url, cookies)
        except Exception:
            return None
        parsed = parse_document(loaded.get("url") or url, loaded.get("html") or "")
        parsed["play_urls"] = rank_media_urls(
            [*(parsed.get("media_urls") or []), *(loaded.get("media_urls") or [])],
            parsed.get("aweme_id") or "",
        )
        loaded = parsed
    parsed = loaded
    media_urls = rank_media_urls(
        list(parsed.get("play_urls") or parsed.get("media_urls") or []),
        parsed.get("aweme_id") or parsed.get("video_id") or "",
    )
    if parsed.get("video_url") and parsed["video_url"] not in media_urls:
        media_urls.insert(0, parsed["video_url"])
        media_urls = rank_media_urls(media_urls, parsed.get("aweme_id") or "")
    image_note = parsed.get("image_note") or (parsed.get("webview") and parsed.get("images") and not media_urls)
    if site(url)[0] == "小红书" and image_note and not media_urls:
        return note_info(url, parsed)
    if not media_urls:
        return None
    return apply_resolved({
        "title": parsed.get("title"), "description": parsed.get("description"), "author": parsed.get("author") or "",
        "platform": site(url)[0], "media_type": "video", "audio_direct": False, "has_audio": True,
        "duration": parsed.get("duration"), "media_url": media_urls[0], "play_urls": media_urls,
        "page_fallback": True, "canonical_url": parsed.get("canonical_url") or "",
    }, parsed)


def dump_online(url, cookies):
    with downloader(url, cookies) as (cmd, _):
        result = subprocess.run([*cmd, "--skip-download", "--dump-single-json", "--", url],
                                capture_output=True, encoding="utf-8", errors="replace", timeout=120,
                                creationflags=media.WINDOW_FLAGS)
    if result.returncode:
        error = extract_error(url, result.stderr, has_session=bool(cookies))
        error.diagnostic = result.stderr or ""
        raise error
    data = json.loads(result.stdout)
    if data.get("_type") in {"playlist", "multi_video"} or "entries" in data or data.get("is_live"):
        raise SourceError("multiple_media", "请选择单条视频、单集节目或直播回放")
    formats = data.get("formats") or [data]
    audio = any(fmt.get("acodec") not in {None, "", "none"} for fmt in formats)
    video = any(fmt.get("vcodec") not in {None, "", "none"} or fmt.get("height") for fmt in formats)
    direct = any(fmt.get("vcodec") == "none" and fmt.get("acodec") != "none" for fmt in formats)
    ext = str(data.get("ext") or "").lower()
    audio_type = not video and (audio or ext in AUDIO_EXTS)
    media_type = "audio" if audio_type else "video" if video or ext in VIDEO_EXTS else "unknown"
    if not any(fmt.get("url") for fmt in formats):
        raise SourceError("no_stream", "此链接当前没有可读取的媒体")
    return {"title": data.get("title"), "description": data.get("description"), "thumbnail": data.get("thumbnail"),
            "duration": seconds(data.get("duration")), "media_type": media_type,
            "audio_direct": direct or audio_type, "has_audio": audio or audio_type or not all(
                fmt.get("acodec") == "none" for fmt in formats)}


def resolve_notes(resolved):
    from app.sites.resolve import format_notes

    text = format_notes((resolved or {}).get("page_notes"))
    try:
        from app import site_profiles
        folder = site_profiles.profile_dir("douyin")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "last-page.txt").write_text(text + "\n", encoding="utf-8")
    except Exception:
        pass
    return text


def inspect_online(url, cookies):
    target, resolved = prepare_social(url, cookies)
    if site(url)[0] == "抖音" and resolved.get("play_urls"):
        info = {
            "title": resolved.get("title"), "description": resolved.get("description"),
            "platform": "抖音", "media_type": "video", "audio_direct": False, "has_audio": True,
            "duration": resolved.get("duration"), "media_url": resolved.get("video_url") or resolved["play_urls"][0],
            "play_urls": resolved["play_urls"], "page_fallback": True,
            "canonical_url": resolved.get("canonical_url") or "", "page_notes": resolved.get("page_notes"),
            "share_duration": resolved.get("share_duration"),
            "resolved_fetch_url": resolved.get("resolved_fetch_url") or url,
            "original_url": resolved.get("original_url") or url,
        }
        return info
    if site(url)[0] == "小红书" and resolved.get("image_note") and not resolved.get("play_urls"):
        return note_info(url, resolved)
    if site(url)[0] == "小红书" and resolved.get("play_urls"):
        return apply_resolved({
            "title": resolved.get("title"), "description": resolved.get("description"),
            "platform": "小红书", "media_type": "video", "audio_direct": False, "has_audio": True,
            "duration": resolved.get("duration"), "media_url": resolved.get("video_url") or resolved["play_urls"][0],
            "play_urls": resolved["play_urls"], "backup_urls": list(resolved.get("backup_urls") or []),
            "page_fallback": True, "canonical_url": resolved.get("canonical_url") or "",
            "resolved_fetch_url": resolved.get("resolved_fetch_url") or url,
            "original_url": resolved.get("original_url") or url,
            "page_notes": resolved.get("page_notes"),
        }, resolved)
    play = ytdlp_target(url, resolved)
    try:
        if not play:
            raise SourceError("no_stream", "短链尚未解析成正式视频页")
        info = dump_online(play, cookies)
    except SourceError as error:
        if resolved.get("image_note") and error.code == "no_stream":
            return note_info(url, resolved)
        recovered = recover_page(play or target or url, cookies, error, page=resolved)
        if recovered:
            if not recovered.get("duration"):
                recovered["duration"] = resolved.get("duration")
            return recovered
        if _page_opened(url, cookies, error):
            notes = resolve_notes(resolved)
            raise SourceError(error.code, f"已打开登录后的{site(url)[0]}页面，但仍没有找到可下载的视频。{notes}") from None
        raise
    info = apply_resolved(info, resolved)
    if resolved.get("play_urls"):
        info["play_urls"] = resolved["play_urls"]
    if resolved.get("duration") and not info.get("duration"):
        info["duration"] = resolved["duration"]
    return info


def probe(source, kind, session="", *, refresh=False):
    key = (kind, source, session)
    with LOCK:
        prune()
        entry = PROBES.get(key)
    if entry and not refresh:
        return entry[1]
    try:
        with PROBE_SLOTS:
            if kind == "local":
                path = media.normalize_local_source_path(source)
                info = {"title": path.name, "platform": "本地文件", **inspect_file(path)}
            else:
                label, _ = site(source)
                cookie = cookies_for(source, session)
                try:
                    info = inspect_online(source, cookie)
                except (SourceError, OSError, subprocess.SubprocessError) as error:
                    if not is_episode(source) or getattr(error, "code", "") == "multiple_media":
                        raise
                    episode = podcast_episode(source)
                    info = {key: episode.get(key) for key in ("title", "duration", "description")}
                    info.update(media_type="audio", audio_direct=True, has_audio=True, podcast_fallback=True)
                if is_episode(source) and not info.get("duration"):
                    try:
                        info["duration"] = podcast_episode(source)["duration"]
                    except (ValueError, httpx.HTTPError, OSError):
                        pass
                info["platform"] = label
        with LOCK:
            PROBES[key] = (time.monotonic() + 600, info)
        return info
    except SourceError:
        raise
    except (ValueError, OSError, httpx.HTTPError, subprocess.SubprocessError) as error:
        message = str(error) if type(error) is ValueError and str(error).startswith(("请输入", "链接必须")) else "读取素材失败，请检查链接、文件或网络后重试"
        raise SourceError("unavailable", message) from error


def download_episode(url, folder, progress):
    episode = podcast_episode(url)
    partial = folder / "episode.part"
    try:
        with public_client() as client, client.stream("GET", episode["address"]) as response:
            response.raise_for_status()
            if not response.headers.get("Content-Type", "").lower().startswith(("audio/", "application/octet-stream")):
                raise SourceError("no_stream", "节目地址没有返回音频")
            total = int(response.headers.get("Content-Length") or 0)
            size = 0
            with partial.open("wb") as handle:
                for chunk in response.iter_bytes(65536):
                    handle.write(chunk)
                    size += len(chunk)
                    if total:
                        progress(min(94, int(size * 94 / total)), "正在下载节目音频")
        if inspect_file(partial)["media_type"] != "audio":
            raise SourceError("no_stream", "节目地址没有返回可用的音频")
        suffix = Path(urlsplit(episode["address"]).path).suffix.lower()
        target = folder / ("source" + (suffix if suffix.lstrip(".") in AUDIO_EXTS else ".m4a"))
        partial.replace(target)
        return target, episode
    except (httpx.HTTPError, OSError, subprocess.SubprocessError) as error:
        raise SourceError("unavailable", "节目音频下载失败，请检查网络后重试") from error
    finally:
        partial.unlink(missing_ok=True)


def download_thumbnail(url, path):
    try:
        with public_client() as client, client.stream("GET", url) as response:
            response.raise_for_status()
            if response.headers.get("content-type", "").split(";")[0].lower() not in {
                "image/jpeg", "image/png", "image/webp", "image/avif",
            }:
                raise ValueError("素材封面格式不可用")
            image = bytearray()
            for chunk in response.iter_bytes(65536):
                image.extend(chunk)
                if len(image) > 10 * 1024 * 1024:
                    raise ValueError("素材封面过大")
        path.write_bytes(image)
        return path
    except (httpx.HTTPError, ValueError, OSError) as error:
        raise SourceError("no_thumbnail", "暂时无法获取来源封面") from error


def save_note(folder, info, progress):
    progress(8, "正在保存图文笔记")
    saved = []
    referer = referer_for(info.get("canonical_url") or "https://www.xiaohongshu.com/")
    for index, address in enumerate(info.get("images") or [], 1):
        if not str(address).startswith(("http://", "https://")) or len(saved) >= 20:
            continue
        try:
            public_target(address, media.online_media_proxy(address))
            name = download_bytes(address, folder / f"note-{index}", referer, "", 15 * 1024 * 1024)
        except (ValueError, OSError, httpx.HTTPError, SourceError):
            continue
        if name:
            saved.append(name)
        progress(min(90, 8 + index * 4), "正在保存笔记图片")
    body = info.get("body") or info.get("description") or ""
    payload = {
        "title": info.get("title") or "", "author": info.get("author") or "", "body": body,
        "images": saved, "canonical_url": info.get("canonical_url") or "",
    }
    (folder / "note.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    text = re.sub(r"\s+", " ", body).strip().replace("-->", "—")[:4000] or info.get("title") or "图文笔记"
    srt = folder / "note.srt"
    srt.write_text(f"1\n00:00:00,000 --> 00:00:01,000\n{text}\n\n", encoding="utf-8")
    progress(96, "图文笔记已保存")
    stored = {**info, "body": body, "image_names": saved, "media_type": "note"}
    return srt, stored, {"media_type": "note", "has_audio": False, "duration": None, "audio_direct": False}


def download_bytes(url, stem, referer, cookies, limit):
    from app.sites.resolve import cookie_header

    headers = {"User-Agent": "Mozilla/5.0"}
    if referer:
        headers["Referer"] = referer
    header = cookie_header(cookies, url)
    if header:
        headers["Cookie"] = header
    types = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif",
             "video/mp4": ".mp4", "audio/mp4": ".m4a", "audio/mpeg": ".mp3"}
    with public_client(headers) as client, client.stream("GET", url) as response:
        response.raise_for_status()
        kind = response.headers.get("content-type", "").split(";")[0].strip().lower()
        suffix = types.get(kind) or Path(urlsplit(url).path).suffix.lower()
        if suffix not in types.values() and suffix.lstrip(".") not in (
            AUDIO_EXTS | VIDEO_EXTS | {"jpg", "jpeg", "png", "webp", "gif"}
        ):
            raise SourceError("no_stream", "页面返回的地址不是可保存的媒体")
        target = stem.with_suffix(suffix if suffix.startswith(".") else f".{suffix}")
        size = 0
        try:
            with target.open("wb") as handle:
                for chunk in response.iter_bytes(65536):
                    size += len(chunk)
                    if size > limit:
                        raise SourceError("no_stream", "媒体文件超出读取限制")
                    handle.write(chunk)
        except Exception:
            target.unlink(missing_ok=True)
            raise
    return target.name


def download_direct(url, folder, cookies, progress, referer):
    public_target(url, media.online_media_proxy(url))
    progress(12, "正在从登录页面下载")
    if ".m3u8" in urlsplit(url).path.lower():
        target = folder / "source.mp4"
        header = ""
        if referer:
            header += f"Referer: {referer}\r\n"
        from app.sites.resolve import cookie_header
        cookie = cookie_header(cookies, url)
        if cookie:
            header += f"Cookie: {cookie}\r\n"
        command = [media.FFMPEG_BIN, "-y", "-protocol_whitelist", "file,crypto,data,http,https,tcp,tls"]
        if header:
            command += ["-headers", header]
        command += ["-i", url, "-c", "copy", str(target)]
        media.run_command(command, log_dir=folder)
        return target
    name = download_bytes(url, folder / "source", referer, cookies or "", 2 * 1024 * 1024 * 1024)
    progress(94, "正在从登录页面下载")
    return folder / name


def keep_ytdlp_log(folder, text=""):
    path = folder / "yt-dlp.err.log"
    if path.exists() and path.stat().st_size:
        return path
    out = folder / "yt-dlp.out.log"
    if out.exists() and out.stat().st_size:
        path.write_text(out.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        return path
    if text:
        path.write_text(text, encoding="utf-8")
    return path


def finish_media(path, info, actual, request, folder, cookies="", referer=""):
    if request.audio_only and actual.get("media_type") == "video":
        if not actual.get("has_audio"):
            audio_url = (info or {}).get("audio_url") or ""
            if not audio_url:
                raise SourceError("no_stream", "这条视频只有画面，没有音轨，无法听写。")
            saved = download_bytes(audio_url, folder / "audio", referer, cookies or "", 2 * 1024 * 1024 * 1024)
            audio = folder / saved
            heard = inspect_file(audio)
            if not heard.get("has_audio"):
                raise SourceError("no_stream", "这条视频只有画面，没有音轨，无法听写。")
            return audio, info, heard
        if not request.allow_muxed_audio and not actual.get("audio_direct"):
            raise SourceError("muxed_audio", "此来源只有合流，请允许下载并提取音轨")
        audio = folder / "audio.m4a"
        media.run_command([media.FFMPEG_BIN, "-y", "-protocol_whitelist", "file,crypto,data",
                           "-i", str(path), "-vn", "-c:a", "aac", str(audio)], log_dir=folder)
        return audio, info, inspect_file(audio)
    return path, info, actual


def try_ytdlp(url, folder, cookies, selector, progress):
    with downloader(url, cookies) as (cmd, _temporary):
        def report(line):
            match = re.search(r"\[download\]\s+(\d+(?:\.\d+)?)%", line)
            if match:
                progress(min(94, int(float(match[1]) * .94)), "正在下载素材")

        media.run_command_streaming(
            [*cmd, "--newline", "--merge-output-format", "mp4", "-f", selector,
             "-o", str(folder / "source.%(ext)s"), "--", url],
            log_dir=folder, log_name="yt-dlp", on_stdout_line=report, on_stderr_line=report,
        )


def take_download(folder, request):
    for path in sorted(folder.glob("source.*"), key=lambda item: item.stat().st_size, reverse=True):
        if path.suffix.lower() in {".part", ".ytdl", ".jsonl", ".json", ".log"}:
            continue
        if path.name.startswith("yt-dlp"):
            continue
        try:
            actual = inspect_file(path)
        except SourceError:
            continue
        if request.audio_only and not actual["has_audio"] or not request.audio_only and actual["media_type"] != "video":
            continue
        return path, actual
    return None, None


def download_candidates(urls, folder, cookies, progress, referer, expected, request, info):
    last = SourceError("no_stream", "下载到的不是正片")
    for address in urls:
        try:
            path = download_direct(address, folder, cookies, progress, referer)
            actual = inspect_file(path)
        except SourceError as error:
            last = error
            continue
        if duration_matches(actual.get("duration"), expected):
            return finish_media(path, info, actual, request, folder, cookies, referer)
        path.unlink(missing_ok=True)
        last = SourceError("no_stream", "下载到的不是正片")
    raise last


def download_douyin(job_id, request, info, cookies, progress):
    folder = media.job_dir(job_id)
    folder.mkdir(parents=True, exist_ok=True)
    _target, resolved = prepare_social(request.source_value, cookies)
    info = apply_resolved(dict(info), resolved)
    if resolved.get("audio_url"):
        info["audio_url"] = resolved["audio_url"]
    player = resolved.get("duration") or info.get("duration")
    share = info.get("share_duration") or resolved.get("share_duration")
    expected = player if player and player >= 30 else (share or player)
    info["duration"] = expected or info.get("duration")
    urls = [item for item in [resolved.get("video_url"), *(resolved.get("play_urls") or [])] if item]
    if not urls:
        raise SourceError("no_stream", "没有从已登录播放器读到这条视频的播放地址。" + resolve_notes(resolved))
    return download_candidates(
        urls, folder, cookies, progress, referer_for(resolved.get("canonical_url") or request.source_value),
        expected, request, info,
    )


def download(job_id, request, info, cookies, progress):
    folder = media.job_dir(job_id)
    if request.source_kind == "local":
        path = media.import_local_source(job_id, request.source_value)
        return path, info, inspect_file(path)
    if info.get("media_type") == "note":
        return save_note(folder, info, progress)
    if site(request.source_value)[0] == "抖音":
        return download_douyin(job_id, request, info, cookies, progress)
    if info.get("page_fallback") and (info.get("play_urls") or info.get("media_url")):
        addresses = [item for item in (info.get("play_urls") or []) if item]
        if info.get("media_url") and info["media_url"] not in addresses:
            addresses.insert(0, info["media_url"])
        referer = referer_for(info.get("resolved_fetch_url") or info.get("canonical_url") or request.source_value)
        if len(addresses) == 1:
            path = download_direct(addresses[0], folder, cookies, progress, referer)
            return path, info, inspect_file(path)
        return download_candidates(addresses, folder, cookies, progress, referer, None, request, info)
    url = download_page_url(request, info)
    try:
        public_target(url, media.online_media_proxy(url))
    except ValueError:
        url = request.source_value
    audio_only = request.audio_only
    if audio_only and not info.get("audio_direct") and not request.allow_muxed_audio and info["media_type"] == "video":
        raise SourceError("muxed_audio", "来源只提供合流，请允许下载并提取音轨")
    selector = ("bestaudio/best" if request.allow_muxed_audio or info["media_type"] != "video" else "bestaudio") \
        if audio_only else media.build_yt_dlp_format_selector(request.resolution, request.fps)
    if info.get("podcast_fallback"):
        path, episode = download_episode(url, folder, progress)
        return path, {**info, **episode}, inspect_file(path)
    try:
        with downloader(url, cookies) as (cmd, temporary):
            def report(line):
                match = re.search(r"\[download\]\s+(\d+(?:\.\d+)?)%", line)
                if match:
                    progress(min(94, int(float(match[1]) * .94)), "正在下载素材")
            media.run_command_streaming(
                [*cmd, "--newline", "--merge-output-format", "mp4", "-f", selector,
                 "-o", str(folder / "source.%(ext)s"), "--", url],
                log_dir=folder, log_name="yt-dlp", on_stdout_line=report, on_stderr_line=report,
            )
    except RuntimeError as error:
        keep_ytdlp_log(folder, str(error))
        mapped = extract_error(url, str(error), has_session=bool(cookies))
        if is_episode(url):
            path, episode = download_episode(request.source_value, folder, progress)
            return path, {**info, **episode}, inspect_file(path)
        recovered = recover_page(url, cookies, mapped)
        if recovered and recovered.get("media_type") == "note":
            return save_note(folder, recovered, progress)
        if recovered and recovered.get("media_url"):
            path = download_direct(recovered["media_url"], folder, cookies, progress, referer_for(url))
            return path, {**info, **recovered}, inspect_file(path)
        if _page_opened(url, cookies, mapped):
            raise SourceError(mapped.code, f"已打开登录后的{site(url)[0]}页面，但仍没有找到可下载的视频。{resolve_notes(info)}") from None
        raise mapped from None
    for path in sorted(folder.glob("source.*"), key=lambda path: path.stat().st_size, reverse=True):
        if path.suffix.lower() in {".part", ".ytdl", ".jsonl", ".json"}:
            continue
        try:
            actual = inspect_file(path)
        except SourceError:
            continue
        if audio_only and not actual["has_audio"] or not audio_only and actual["media_type"] != "video":
            continue
        if audio_only and actual["media_type"] == "video":
            if not request.allow_muxed_audio:
                raise SourceError("muxed_audio", "此来源只有合流，请允许下载并提取音轨")
            audio = folder / "audio.m4a"
            media.run_command([media.FFMPEG_BIN, "-y", "-protocol_whitelist", "file,crypto,data",
                               "-i", str(path), "-vn", "-c:a", "aac", str(audio)], log_dir=folder)
            return audio, info, inspect_file(audio)
        return path, info, actual
    raise SourceError("no_stream", "下载结束，但没有找到所需的音视频流")
