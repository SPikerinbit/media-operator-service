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
               "--socket-timeout", "15", "--retries", "1", "--extractor-retries", "1",
               "--downloader", "native"]
        ffmpeg = media.yt_dlp_ffmpeg_location()
        if ffmpeg:
            cmd += ["--ffmpeg-location", ffmpeg]
        if cookies:
            path = Path(directory) / "session.txt"
            path.write_text("# Netscape HTTP Cookie File\n" + cookies + "\n", encoding="utf-8")
            cmd += ["--cookies", str(path)]
        yield cmd, Path(directory)


def extract_error(url, diagnostic, *, has_session=False):
    label = site(url)[0]
    lower = diagnostic.lower()
    if label == "抖音" and "http error 403" in lower and "web detail json" in lower:
        if has_session:
            return SourceError("site_blocked", "已使用本站 Cookie，抖音仍拒绝读取视频详情（403）。可重新解析、更换链接，或从队列顶部添加本地视频。")
        return SourceError("session_required", "抖音拒绝读取视频详情（403）。可在浏览器确认视频能播放后，选择本站 Cookie 重试。")
    if label == "小红书":
        for address in re.findall(r"Unsupported URL:\s+(https?://\S+)", diagnostic, flags=re.IGNORECASE):
            target = urlsplit(address)
            if domain_matches(target.hostname or "", "xiaohongshu.com") and target.path.rstrip("/") == "/login":
                return SourceError("session_required", "小红书跳转到了登录页。请在浏览器登录并确认笔记可播放，再选择本站 Cookie 重试。")
        if "no video formats" in lower or "no formats" in lower:
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
def public_client():
    with public_proxy(media.online_media_proxy) as proxy, httpx.Client(
        proxy=proxy, trust_env=False, follow_redirects=True, max_redirects=8, timeout=20,
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


def inspect_online(url, cookies):
    with downloader(url, cookies) as (cmd, _):
        result = subprocess.run([*cmd, "--skip-download", "--dump-single-json", "--", url],
                                capture_output=True, encoding="utf-8", errors="replace", timeout=50,
                                creationflags=media.WINDOW_FLAGS)
    if result.returncode:
        raise extract_error(url, result.stderr, has_session=bool(cookies))
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
                cookie = session_for(source, session)
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


def download(job_id, request, info, cookies, progress):
    folder = media.job_dir(job_id)
    if request.source_kind == "local":
        path = media.import_local_source(job_id, request.source_value)
        return path, info, inspect_file(path)
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
                log_dir=temporary, on_stdout_line=report, on_stderr_line=report,
            )
    except RuntimeError as error:
        if not is_episode(url):
            raise extract_error(url, str(error), has_session=bool(cookies)) from None
        path, episode = download_episode(url, folder, progress)
        return path, {**info, **episode}, inspect_file(path)
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
