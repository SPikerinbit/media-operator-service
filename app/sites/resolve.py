"""Resolve public short links and read the page they land on.

Redirects and response bodies stay small. Every hop must be a public HTTP(S) host.
"""
from html import unescape
import json
import re
import threading
from urllib.parse import urljoin, urlsplit, unquote

import httpx

from app.source_network import public_proxy, public_target

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)
MAX_REDIRECTS = 5
MAX_BYTES = 1_500_000
REDIRECTS = {301, 302, 303, 307, 308}
SITES = (
    ("YouTube", "youtube", ("youtube.com", "youtu.be")),
    ("B 站", "bilibili", ("bilibili.com", "b23.tv")),
    ("抖音", "url", ("douyin.com", "iesdouyin.com")),
    ("小红书", "url", ("xiaohongshu.com", "xhslink.com", "xhslink.cn")),
    ("小宇宙", "url", ("xiaoyuzhoufm.com",)),
)
CDN = {
    "抖音": ("douyin.com", "iesdouyin.com", "douyinvod.com", "bytecdn.cn", "ibytedtos.com", "snssdk.com"),
    "小红书": ("xiaohongshu.com", "xhslink.com", "xhslink.cn", "xhscdn.com", "xhscdn.net"),
}
LOCK = threading.Lock()
ALIASES = {}
AWEME = re.compile(r'["\']aweme_id["\']\s*[:=]\s*["\'](\d{6,})')
DOUYIN_ID = re.compile(r"/(?:video|share/video|note)/(\d{6,})")
NOTE_ID = re.compile(r'["\']noteId["\']\s*[:=]\s*["\']([0-9a-fA-F]{16,32})')
XHS_ID = re.compile(r"/(?:explore|discovery/item)/([0-9a-fA-F]{16,32})")
VIDEO_URL = re.compile(r"https://[^\"'\s\\<>]+?\.mp4[^\"'\s\\<>]*", re.I)
IMAGE_URL = re.compile(r"https://[^\"'\s\\<>]+?\.(?:jpe?g|png|webp)[^\"'\s\\<>]*", re.I)
META = re.compile(r"<meta\b[^>]*>", re.I)
ATTR = r"{name}\s*=\s*([\"'])(.*?)\1"


class ResolveError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def domain_matches(host, domain):
    host = (host or "").lower().rstrip(".")
    domain = domain.lower().rstrip(".")
    return host == domain or host.endswith("." + domain)


def platform_of(url):
    host = (urlsplit(url).hostname or "").lower()
    for label, kind, domains in SITES:
        if any(domain_matches(host, domain) for domain in domains):
            return label, kind, domains
    return host, "url", (host,)


def host_allowed(url, names):
    host = (urlsplit(url).hostname or "").lower()
    return any(domain_matches(host, name) for name in names)


def classify(url):
    text = (url or "").strip()
    label, kind, _ = platform_of(text)
    parsed = urlsplit(text)
    host = (parsed.hostname or "").lower()
    path = parsed.path or "/"
    video_id = ""
    aweme_id = ""
    note_id = ""
    form = ""
    link_kind = "link"
    if label == "抖音":
        found = DOUYIN_ID.search(path)
        if found:
            video_id = aweme_id = found.group(1)
            link_kind = "video"
        elif host == "v.douyin.com" or path.strip("/") and host.endswith("douyin.com") and "/" not in path.strip("/"):
            link_kind = "short"
        if host == "v.douyin.com":
            link_kind = "video" if video_id else "short"
    elif label == "小红书":
        found = XHS_ID.search(path)
        if found:
            note_id = found.group(1)
            link_kind = "note"
        elif host.startswith("xhslink."):
            link_kind = "short"
            if path.startswith("/o/"):
                form = "/o/"
    return {
        "url": text, "platform": label, "source_kind": kind, "kind": link_kind, "form": form,
        "video_id": video_id, "aweme_id": aweme_id, "note_id": note_id,
    }


def _attr(tag, name):
    match = re.search(ATTR.format(name=name), tag, re.I | re.S)
    return unescape(match.group(2)).strip() if match else ""


def meta_map(html):
    found = {}
    for match in META.finditer(html or ""):
        tag = match.group(0)
        key = (_attr(tag, "property") or _attr(tag, "name")).lower()
        value = _attr(tag, "content")
        if key and value:
            found.setdefault(key, value)
    return found


def _json_string(html, name):
    match = re.search(r'["\']' + re.escape(name) + r'["\']\s*:\s*"((?:\\.|[^"\\])*)"', html)
    if not match:
        return ""
    try:
        return bytes(match.group(1), "utf-8").decode("unicode_escape")
    except UnicodeError:
        return match.group(1)


def _images(html, platform):
    if platform != "小红书":
        return []
    found = []
    for match in IMAGE_URL.finditer(html):
        address = unescape(match.group(0).replace("\\/", "/"))
        if host_allowed(address, CDN["小红书"]) and address not in found:
            found.append(address)
        if len(found) >= 20:
            break
    return found


def plain_html(html):
    return unescape((html or "").replace("\\/", "/").replace("\\u002F", "/").replace("\\u0026", "&"))


def decode_page(text):
    plain = plain_html(text)
    for _ in range(2):
        if "%" not in plain:
            break
        decoded = unquote(plain)
        if decoded == plain:
            break
        plain = plain_html(decoded)
    return plain


def page_notes(text, url=""):
    raw = text or ""
    decoded = decode_page(raw)
    return {
        "render_data": "RENDER_DATA" in raw or "RENDER_DATA" in decoded,
        "play_addr": "play_addr" in decoded or "playAddr" in decoded,
        "page": url or "",
    }


def format_notes(notes):
    notes = notes or {}
    text = "RENDER_DATA={render}，解码后play_addr={play}，页面={page}".format(
        render="有" if notes.get("render_data") else "无",
        play="有" if notes.get("play_addr") else "无",
        page=notes.get("page") or "未知",
    )
    if notes.get("video_duration"):
        text += f"，播放器时长={notes['video_duration']}"
    if notes.get("media_count") is not None:
        text += f"，候选={notes['media_count']}"
    return text


def _brace_end(text, start, limit=200000):
    if start >= len(text) or text[start] != "{":
        return None
    depth = 0
    quote = ""
    escaped = False
    for index in range(start, min(len(text), start + limit)):
        char = text[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in {'"', "'"}:
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    return None


def _object_around(text, index):
    best = None
    for pos in range(index, max(-1, index - 30000), -1):
        if text[pos] != "{":
            continue
        end = _brace_end(text, pos)
        if not end or end <= index:
            continue
        if best is None or end - pos < best[1] - best[0]:
            best = (pos, end)
    if not best:
        return text[max(0, index - 4000):min(len(text), index + 12000)]
    return text[best[0]:best[1]]


def _bracket_end(text, start):
    if start < 0 or start >= len(text) or text[start] != "[":
        return None
    depth = 0
    quote = ""
    escaped = False
    for index in range(start, min(len(text), start + 200000)):
        char = text[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in {'"', "'"}:
            quote = char
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return index + 1
    return None


def _without_audio_lists(window):
    cleaned = window
    for marker in ("bitRateAudio", "bit_rate_audio"):
        while True:
            found = re.search('"' + marker + r'"\s*:\s*\[', cleaned)
            if not found:
                break
            bracket = cleaned.find("[", found.start())
            end = _bracket_end(cleaned, bracket)
            if not end:
                break
            cleaned = cleaned[:found.start()] + cleaned[end:]
    return cleaned


def _play_address(window):
    rates = []
    for match in re.finditer(
        r'"bitRate"\s*:\s*(\d+).{0,1200}?"playAddr"\s*:\s*\[?\s*\{?\s*"src"\s*:\s*"(https:[^"]+)"',
        window, re.S,
    ):
        rates.append((int(match.group(1)), match.group(2)))
    for match in re.finditer(
        r'"bit_rate"\s*:\s*(\d+).{0,1200}?"url_list"\s*:\s*\[\s*"(https:[^"]+)"',
        window, re.S,
    ):
        rates.append((int(match.group(1)), match.group(2)))
    if rates:
        return max(rates)[1]
    for pattern in (
        r'"playAddr"\s*:\s*\[\s*\{\s*"src"\s*:\s*"(https:[^"]+)"',
        r'"playAddr"\s*:\s*"(https:[^"]+)"',
        r'"playApi"\s*:\s*"(https:[^"]+)"',
        r'"play_addr"\s*:\s*\{.{0,600}?"url_list"\s*:\s*\[\s*"(https:[^"]+)"',
    ):
        found = re.search(pattern, window, re.S)
        if found:
            return found.group(1)
    return ""


def _audio_address(window):
    rates = []
    for marker in ("bitRateAudio", "bit_rate_audio"):
        for block in re.finditer('"' + marker + '"', window):
            chunk = window[block.end():block.end() + 12000]
            for match in re.finditer(
                r'"(?:bitRate|bit_rate)"\s*:\s*(\d+).{0,1500}?"(?:src|main_url)"\s*:\s*"(https:[^"]+)"',
                chunk, re.S,
            ):
                rates.append((int(match.group(1)), match.group(2)))
            for match in re.finditer(r'"url_list"\s*:\s*\[\s*"(https:[^"]+)"', chunk):
                rates.append((0, match.group(1)))
    if not rates:
        return ""
    return max(rates)[1]


def _seconds_value(number):
    seconds = number / 1000 if number >= 1000 else float(number)
    return seconds if 1 <= seconds <= 6 * 3600 else None


def player_feature(text, aweme_id=""):
    plain = decode_page(text)
    aweme_id = str(aweme_id or "")
    if not aweme_id:
        found = DOUYIN_ID.search(plain)
        aweme_id = found.group(1) if found else ""
    if not aweme_id:
        ident = re.search(r'["\']aweme_?id["\']\s*:\s*["\'](\d{6,})["\']', plain, re.I)
        aweme_id = ident.group(1) if ident and len(set(re.findall(
            r'["\']aweme_?id["\']\s*:\s*["\'](\d{6,})["\']', plain, re.I))) == 1 else ""
    if not aweme_id:
        return None
    located = re.search(r'["\']aweme_?id["\']\s*:\s*["\']' + re.escape(aweme_id) + r'["\']', plain, re.I)
    if not located:
        return None
    window = _object_around(plain, located.start())
    address = unescape(_play_address(_without_audio_lists(window)).replace("\\/", "/").replace("\\u0026", "&"))
    if not address.startswith("http"):
        return None
    duration = None
    timed = re.search(r'"duration"\s*:\s*(\d+)', window)
    if timed:
        duration = _seconds_value(int(timed.group(1)))
    audio = unescape(_audio_address(window).replace("\\/", "/").replace("\\u0026", "&"))
    if not audio.startswith("http"):
        audio = ""
    return {"url": address, "audio_url": audio, "duration": duration, "aweme_id": aweme_id}


def order_player_urls(feature_url="", src="", entries=None):
    ranked = []

    def add(url, first=False):
        if not isinstance(url, str) or not url.startswith("http") or url in ranked:
            return
        if first:
            ranked.insert(0, url)
        else:
            ranked.append(url)

    add(feature_url)
    for name in entries or []:
        if isinstance(name, str) and ("aweme/v1/play" in name or "mime_type=video" in name):
            add(name)
    add(src)
    for name in entries or []:
        add(name)
    return ranked


def page_duration(html):
    found = []
    for match in re.finditer(r'"duration"\s*:\s*(\d+)', plain_html(html)):
        number = int(match.group(1))
        seconds = number / 1000 if number >= 1000 else float(number)
        if 1 <= seconds <= 6 * 3600:
            found.append(seconds)
    return max(found) if found else None


def collect_media_urls(html):
    text = plain_html(html)
    found = []

    def add(url):
        address = unescape(url).strip().rstrip("\\")
        if address.startswith("http") and address not in found and len(found) < 40:
            found.append(address)

    for block in re.finditer(r'"play_addr"\s*:\s*\{.{0,500}?"url_list"\s*:\s*\[(.*?)\]', text, re.S):
        for item in re.finditer(r"https://[^\"'\s]+", block.group(1)):
            add(item.group(0))
    for match in re.finditer(r"https://[^\"'\s<>]+?/aweme/v1/play[^\"'\s<>]*", text, re.I):
        add(match.group(0))
    for match in VIDEO_URL.finditer(text):
        add(match.group(0))
    return found


def _assigned_json(text, marker):
    index = (text or "").find(marker)
    if index < 0:
        return None
    rest = text[index + len(marker):].lstrip()
    if rest.startswith("="):
        rest = rest[1:].lstrip()
    if rest.startswith("JSON.parse"):
        open_paren = rest.find("(")
        rest = rest[open_paren + 1:].lstrip()
        quote = rest[:1]
        if quote in {'"', "'"}:
            end = 1
            escaped = False
            while end < len(rest):
                char = rest[end]
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    break
                end += 1
            try:
                rest = json.loads(rest[:end + 1])
            except (json.JSONDecodeError, ValueError):
                return None
            if isinstance(rest, str):
                rest = rest.lstrip()
            else:
                return rest if isinstance(rest, dict) else None
    if not isinstance(rest, str):
        return rest if isinstance(rest, dict) else None
    start = rest.find("{")
    if start < 0:
        return None
    end = _brace_end(rest, start, 600000)
    if not end:
        return None
    blob = re.sub(r"\bundefined\b", "null", rest[start:end])
    try:
        value = json.loads(blob)
    except json.JSONDecodeError:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None


def _note_body(entry):
    if not isinstance(entry, dict):
        return None
    note = entry.get("note")
    if isinstance(note, dict):
        return note
    if any(key in entry for key in ("noteId", "desc", "imageList", "title")):
        return entry
    return None


def _note_entry(note_map, note_id):
    if not isinstance(note_map, dict) or not note_map:
        return None
    wanted = (note_id or "").casefold()
    if wanted:
        for key, value in note_map.items():
            if str(key).casefold() == wanted:
                return value
        for value in note_map.values():
            note = _note_body(value)
            ident = str((note or {}).get("noteId") or (note or {}).get("note_id") or "")
            if ident.casefold() == wanted:
                return value
        return None
    if len(note_map) == 1:
        return next(iter(note_map.values()))
    return None


def _http_url(value):
    if not isinstance(value, str):
        return ""
    address = unescape(value.replace("\\/", "/").replace("\\u0026", "&")).strip()
    return address if address.startswith("http") else ""


def xhs_note(html, note_id=""):
    """Read one note from ``note.noteDetailMap`` without treating the bare explore URL as the fetch URL."""
    state = _assigned_json(decode_page(html or ""), "__INITIAL_STATE__")
    if not isinstance(state, dict):
        return None
    note_map = ((state.get("note") or {}).get("noteDetailMap") or {})
    note = _note_body(_note_entry(note_map, note_id))
    if not note:
        return None
    streams = []
    backups = []
    media = ((note.get("video") or {}).get("media") or {})
    groups = media.get("stream") or {}
    if isinstance(groups, dict):
        ordered = []
        for codec in ("h264", "h265", "av1", "h266"):
            if codec in groups:
                ordered.append(groups[codec])
        for value in groups.values():
            if value not in ordered:
                ordered.append(value)
        for group in ordered:
            items = group if isinstance(group, list) else [group]
            for item in items:
                if not isinstance(item, dict):
                    continue
                master = _http_url(item.get("masterUrl") or item.get("master_url"))
                if master and master not in streams:
                    streams.append(master)
                extras = item.get("backupUrls") or item.get("backup_urls") or []
                if isinstance(extras, str):
                    extras = [extras]
                for extra in extras:
                    address = _http_url(extra)
                    if address and address not in backups and address not in streams:
                        backups.append(address)
                if len(streams) >= 12:
                    break
    images = []
    for image in note.get("imageList") or []:
        if not isinstance(image, dict) or len(images) >= 20:
            break
        for key in ("urlDefault", "url", "urlPre"):
            address = _http_url(image.get(key))
            if address and address not in images and (host_allowed(address, CDN["小红书"]) or "xhscdn" in address):
                images.append(address)
        for info in image.get("infoList") or []:
            if isinstance(info, dict):
                address = _http_url(info.get("url"))
                if address and address not in images and (host_allowed(address, CDN["小红书"]) or "xhscdn" in address):
                    images.append(address)
    duration = None
    for value in (
        ((note.get("video") or {}).get("capa") or {}).get("duration"),
        (((note.get("video") or {}).get("media") or {}).get("video") or {}).get("duration"),
    ):
        try:
            duration = _seconds_value(float(value))
        except (TypeError, ValueError):
            duration = None
        if duration:
            break
    user = note.get("user") or {}
    author = ""
    if isinstance(user, dict):
        author = str(user.get("nickname") or user.get("nickName") or "").strip()
    kind = str(note.get("type") or "").lower()
    image_note = (not streams) and (kind in {"normal", "image"} or (bool(images) and kind != "video"))
    return {
        "note_id": str(note.get("noteId") or note.get("note_id") or note_id or ""),
        "title": str(note.get("title") or "").strip(),
        "author": author,
        "body": str(note.get("desc") or note.get("description") or "").strip(),
        "streams": streams,
        "backups": backups,
        "images": images,
        "duration": duration,
        "image_note": image_note,
    }


def xhs_capture_ready(html, media_urls=None, video_urls=None):
    """A logged-in Xiaohongshu page is ready only after note data, a video element, or a media response."""
    detail = xhs_note(html or "", "")
    if detail and (detail["streams"] or detail["backups"] or detail["images"] or detail["body"]):
        return True
    for group in (media_urls, video_urls):
        for address in group or []:
            if isinstance(address, str) and address.startswith("http"):
                return True
    return False


def rank_media_urls(urls, aweme_id=""):
    def score(url):
        lowered = url.lower()
        value = 0
        if aweme_id and aweme_id in url:
            value += 100
        if "/aweme/v1/play" in lowered:
            value += 40
        return value

    ordered = []
    for url in urls or []:
        if url and url not in ordered:
            ordered.append(url)
    return [url for _, url in sorted(enumerate(ordered), key=lambda item: (-score(item[1]), item[0]))]


def _video_url(html, aweme_id=""):
    ranked = rank_media_urls(collect_media_urls(html), aweme_id)
    return ranked[0] if ranked else ""


def parse_document(url, html):
    text = unescape((html or "").replace("\\/", "/").replace("\\u002F", "/"))
    info = classify(url)
    meta = meta_map(text)
    video_id = info["video_id"] or (AWEME.search(text).group(1) if AWEME.search(text) else "")
    if not video_id:
        found = DOUYIN_ID.search(text)
        video_id = found.group(1) if found and info["platform"] == "抖音" else ""
    aweme_id = info["aweme_id"] or (AWEME.search(text).group(1) if AWEME.search(text) else "") or video_id
    note_id = info["note_id"]
    if not note_id and info["platform"] == "小红书":
        found = NOTE_ID.search(text) or XHS_ID.search(text)
        note_id = found.group(1) if found else ""
    title = meta.get("og:title") or meta.get("twitter:title") or ""
    description = meta.get("og:description") or meta.get("description") or ""
    author = meta.get("article:author") or meta.get("author") or _json_string(text, "nickname") or _json_string(text, "nickName")
    body = _json_string(text, "desc") or description
    duration = None
    if info["platform"] == "抖音":
        feature = player_feature(text, aweme_id or video_id)
        media_urls = [feature["url"]] if feature and feature.get("url") else []
        video_url = media_urls[0] if media_urls else ""
        duration = feature.get("duration") if feature else None
        audio_url = feature.get("audio_url") if feature else ""
    else:
        media_urls = rank_media_urls(collect_media_urls(text), aweme_id or video_id)
        video_url = media_urls[0] if media_urls else ""
        duration = page_duration(text)
        audio_url = ""
    images = _images(text, info["platform"])
    compact = re.sub(r"\s+", "", text)
    image_note = info["platform"] == "小红书" and not video_url and (
        '"type":"normal"' in compact or '"notetype":"normal"' in compact.lower()
    ) and '"type":"video"' not in compact
    backups = []
    detail = xhs_note(text, note_id) if info["platform"] == "小红书" else None
    if detail:
        if detail.get("note_id"):
            note_id = detail["note_id"]
        if detail.get("title"):
            title = detail["title"]
        if detail.get("author"):
            author = detail["author"]
        if detail.get("body"):
            body = detail["body"]
            description = description or detail["body"]
        if detail.get("images"):
            images = detail["images"]
        if detail.get("duration"):
            duration = detail["duration"]
        if detail.get("streams"):
            media_urls = []
            for address in [*detail["streams"], *(detail.get("backups") or [])]:
                if address not in media_urls:
                    media_urls.append(address)
            video_url = media_urls[0]
            backups = list(detail.get("backups") or [])
        image_note = bool(detail.get("image_note"))
        if image_note and not detail.get("streams"):
            video_url = ""
            media_urls = []
    canonical = ""
    if info["platform"] == "抖音" and (video_id or aweme_id):
        canonical = f"https://www.douyin.com/video/{video_id or aweme_id}"
    elif info["platform"] == "小红书" and note_id:
        canonical = f"https://www.xiaohongshu.com/explore/{note_id}"
    path = (urlsplit(url).path or "/").rstrip("/") or "/"
    host = (urlsplit(url).hostname or "").lower()
    login_wall = path == "/login" and (info["platform"] in {"抖音", "小红书"} or "xiaohongshu" in host or "douyin" in host)
    return {
        "url": url, "platform": info["platform"], "source_kind": info["source_kind"], "kind": info["kind"],
        "form": info["form"], "video_id": video_id, "aweme_id": aweme_id or video_id, "note_id": note_id,
        "title": title.strip(), "author": author.strip(), "description": description.strip(), "body": body.strip(),
        "images": images, "video_url": video_url, "media_urls": media_urls, "backup_urls": backups,
        "duration": duration, "audio_url": audio_url, "image_note": image_note, "canonical_url": canonical,
        "original_url": url, "resolved_fetch_url": url, "login_wall": login_wall,
    }


def remember(url, canonical):
    raw = (url or "").strip()
    target = (canonical or "").strip()
    if not raw or not target:
        return
    with LOCK:
        ALIASES[raw] = target
        ALIASES[target] = target


def identity(source):
    raw = (source or "").strip()
    with LOCK:
        return ALIASES.get(raw, raw)


def cookie_header(cookies, url):
    host = (urlsplit(url).hostname or "").lower()
    pairs = []
    for line in (cookies or "").splitlines():
        if not line or (line.startswith("#") and not line.startswith("#HttpOnly_")):
            continue
        fields = line.split("\t")
        if len(fields) != 7:
            continue
        domain = fields[0].removeprefix("#HttpOnly_").lstrip(".").lower()
        if host == domain or host.endswith("." + domain):
            name, value = fields[5], fields[6]
            if name and "\r" not in value and "\n" not in value:
                pairs.append(f"{name}={value}")
    return "; ".join(pairs)


def fetch_public(url, headers=None, cookies="", referer=""):
    from app import main as media

    extra = {"User-Agent": MOBILE_UA, "Accept": "text/html,application/xhtml+xml", "Accept-Language": "zh-CN,zh;q=0.9"}
    label = platform_of(url)[0]
    same_site = label in CDN and host_allowed(url, CDN[label])
    if referer and (same_site or platform_of(referer)[0] == label):
        extra["Referer"] = referer
    header = cookie_header(cookies, url)
    if header:
        extra["Cookie"] = header
    if headers:
        extra.update({key: value for key, value in headers.items() if key.lower() != "cookie"})
    with public_proxy(media.online_media_proxy) as proxy, httpx.Client(
        proxy=proxy, trust_env=False, follow_redirects=False, timeout=20, headers=extra,
    ) as client, client.stream("GET", url) as response:
        location = response.headers.get("location", "")
        if response.status_code in REDIRECTS:
            return response.status_code, location, "", response.headers.get("content-type", "")
        chunks = []
        size = 0
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > MAX_BYTES:
                break
            chunks.append(chunk)
        body = b"".join(chunks).decode("utf-8", "replace")
        return response.status_code, "", body, response.headers.get("content-type", "")


def resolve(url, fetch=None):
    fetch = fetch or (lambda target: fetch_public(target, cookies="", referer=""))
    current = (url or "").strip()
    body = ""
    final = current
    status = 0
    for _ in range(MAX_REDIRECTS + 1):
        try:
            from app import main as media
            public_target(current, media.online_media_proxy(current))
        except ValueError as error:
            raise ResolveError("unavailable", str(error)) from error
        status, location, body, _ = fetch(current)
        if status in REDIRECTS and location:
            current = urljoin(current, location)
            continue
        final = current
        break
    else:
        raise ResolveError("unavailable", "短链跳转次数过多")
    if status >= 400 and not body:
        raise ResolveError("unavailable", f"短链返回 {status}")
    parsed = parse_document(final, body)
    parsed["url"] = final
    parsed["html"] = body
    parsed["status"] = status
    parsed["original_url"] = url
    fetch = final
    if parsed.get("platform") == "小红书":
        requested = urlsplit(url)
        landed = urlsplit(final)
        # A share query that actually opened the note must not be replaced by a bare explore URL.
        if requested.query and XHS_ID.search(requested.path or "") and not landed.query:
            fetch = url
        elif landed.query:
            fetch = final
        elif requested.query:
            fetch = url
    parsed["resolved_fetch_url"] = fetch
    if not parsed.get("canonical_url"):
        parsed["canonical_url"] = "" if classify(final)["kind"] == "short" else final
    if parsed.get("canonical_url"):
        remember(url, parsed["canonical_url"])
        remember(final, parsed["canonical_url"])
        if fetch and fetch not in {url, final}:
            remember(fetch, parsed["canonical_url"])
    return parsed
