"""Resolve public short links and read the page they land on.

Redirects and response bodies stay small. Every hop must be a public HTTP(S) host.
"""
from html import unescape
import json
import re
import threading
from urllib.parse import parse_qs, urljoin, urlsplit, unquote

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
    "抖音": (
        "douyin.com", "iesdouyin.com", "douyinvod.com", "douyincdn.com",
        "bytecdn.cn", "ibytedtos.com", "snssdk.com", "zjcdn.com",
        "amemv.com", "toutiaovod.com", "douyinpic.com", "byteimg.com",
    ),
    "小红书": ("xiaohongshu.com", "xhslink.com", "xhslink.cn", "xhscdn.com", "xhscdn.net"),
}
LOCK = threading.Lock()
ALIASES = {}
AWEME = re.compile(r'["\'](?:aweme_?id|item_?id)["\']\s*[:=]\s*["\']?(\d{6,})', re.I)
DOUYIN_ID = re.compile(r"/(?:video|share/video|note|share/note|slides|share/slides)/(\d{6,})")
DOUYIN_NOTE_PATH = re.compile(r"/(?:note|share/note|slides|share/slides)/(\d{6,})")
DOUYIN_QUERY_KEYS = ("modal_id", "item_ids", "vid", "aweme_id")
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
            link_kind = "note" if DOUYIN_NOTE_PATH.search(path) else "video"
        else:
            query = parse_qs(parsed.query)
            for key in DOUYIN_QUERY_KEYS:
                candidate = next((v.strip() for v in query.get(key, []) if re.fullmatch(r"\d{6,}", v.strip())), "")
                if candidate:
                    video_id = aweme_id = candidate
                    link_kind = "video"
                    form = key
                    break
        if not video_id and (host == "v.douyin.com" or (path.strip("/") and host.endswith("douyin.com") and "/" not in path.strip("/"))):
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


def _clean_media_url(value):
    if not isinstance(value, str):
        return ""
    url = unescape(value.replace("\\/", "/").replace("\\u002F", "/").replace("\\u0026", "&")).strip()
    if url.startswith("//"):
        url = "https:" + url
    return url if url.startswith(("http://", "https://")) else ""


def _add_unique_url(bucket, value):
    url = _clean_media_url(value)
    if url and url not in bucket:
        bucket.append(url)


def _play_addresses(window):
    """Extract ordered video play URLs from a Douyin aweme/video window, preserving CDN mirrors."""
    rated = []
    for match in re.finditer(
        r'"bitRate"\s*:\s*(\d+).{0,1600}?"playAddr"\s*:\s*\[([^\]]{1,4000})\]',
        window, re.S,
    ):
        rate = int(match.group(1))
        for src in re.finditer(r'"src"\s*:\s*"((?:https?:|//)[^"]+)"', match.group(2)):
            rated.append((rate, _clean_media_url(src.group(1))))
    for match in re.finditer(
        r'"bit_rate"\s*:\s*(\d+).{0,1600}?"url_list"\s*:\s*\[([^\]]{1,4000})\]',
        window, re.S,
    ):
        rate = int(match.group(1))
        for src in re.finditer(r'"((?:https?:|//)[^"]+)"', match.group(2)):
            rated.append((rate, _clean_media_url(src.group(1))))
    ordered = []
    for _, url in sorted(rated, key=lambda item: item[0], reverse=True):
        _add_unique_url(ordered, url)
    for pattern in (
        r'"playAddr"\s*:\s*\[([^\]]{1,4000})\]',
        r'"play_addr"\s*:\s*\{.{0,800}?"url_list"\s*:\s*\[([^\]]{1,4000})\]',
    ):
        for match in re.finditer(pattern, window, re.S):
            block = match.group(1)
            for src in re.finditer(r'"(?:src"\s*:\s*")?((?:https?:|//)[^"]+)"', block):
                _add_unique_url(ordered, src.group(1))
    for pattern in (
        r'"playAddr"\s*:\s*"((?:https?:|//)[^"]+)"',
        r'"playApi"\s*:\s*"((?:https?:|//)[^"]+)"',
    ):
        for found in re.finditer(pattern, window, re.S):
            _add_unique_url(ordered, found.group(1))
    return ordered


def _play_address(window):
    urls = _play_addresses(window)
    return urls[0] if urls else ""


def _audio_address(window):
    rates = []
    for marker in ("bitRateAudio", "bit_rate_audio"):
        for block in re.finditer('"' + marker + '"', window):
            chunk = window[block.end():block.end() + 12000]
            for match in re.finditer(
                r'"(?:bitRate|bit_rate)"\s*:\s*(\d+).{0,1500}?"(?:src|main_url)"\s*:\s*"((?:https?:|//)[^"]+)"',
                chunk, re.S,
            ):
                rates.append((int(match.group(1)), _clean_media_url(match.group(2))))
            for match in re.finditer(r'"url_list"\s*:\s*\[\s*"((?:https?:|//)[^"]+)"', chunk):
                rates.append((0, _clean_media_url(match.group(1))))
    if not rates:
        return ""
    return max(rates, key=lambda item: item[0])[1]


def _seconds_value(number):
    seconds = number / 1000 if number >= 1000 else float(number)
    return seconds if 1 <= seconds <= 6 * 3600 else None


def _flight_blobs(raw_text):
    """Unescape RSC/Modern.js flight strings such as self.__pace_f.push([1, \"...\"])."""
    blobs = []
    text = raw_text or ""
    for match in re.finditer(r'__pace_f\.push\(\s*\[\s*\d+\s*,\s*"((?:\\.|[^"\\])*)"\s*\]\s*\)', text):
        try:
            decoded = json.loads('"' + match.group(1) + '"')
        except (ValueError, json.JSONDecodeError):
            continue
        if isinstance(decoded, str) and decoded:
            blobs.append(plain_html(decoded))
    if '\\"aweme' in text or '\\"playAddr' in text or '\\"play_addr' in text:
        unescaped = text.replace('\\\\"', '"').replace('\\"', '"').replace('\\\\/', '/')
        blobs.append(plain_html(unescaped))
    return blobs


def _aweme_id_of(obj):
    if not isinstance(obj, dict):
        return ""
    for key in ("aweme_id", "awemeId", "item_id", "itemId"):
        value = obj.get(key)
        if value is not None:
            text = str(value).strip()
            if re.fullmatch(r"\d{6,}", text):
                return text
    return ""


def _urls_from_addr_node(node):
    found = []
    if isinstance(node, str):
        _add_unique_url(found, node)
    elif isinstance(node, list):
        for item in node:
            if isinstance(item, str):
                _add_unique_url(found, item)
            elif isinstance(item, dict):
                _add_unique_url(found, item.get("src") or item.get("url") or item.get("main_url") or "")
    elif isinstance(node, dict):
        for key in ("url_list", "urlList", "playAddr", "play_addr"):
            if key in node:
                for u in _urls_from_addr_node(node[key]):
                    _add_unique_url(found, u)
        for key in ("src", "url", "main_url"):
            _add_unique_url(found, node.get(key) or "")
    return found


def _parse_aweme_dict(obj, expected_id=""):
    if not isinstance(obj, dict):
        return None
    ident = _aweme_id_of(obj)
    if expected_id and ident != expected_id:
        return None
    if not ident:
        return None
    video = obj.get("video") if isinstance(obj.get("video"), dict) else {}
    rated = []
    for list_key in ("bit_rate", "bitRateList", "bitRate"):
        items = video.get(list_key)
        if not isinstance(items, list):
            continue
        for entry in items:
            if not isinstance(entry, dict):
                continue
            rate = entry.get("bit_rate") or entry.get("bitRate") or 0
            try:
                rate = int(rate)
            except (TypeError, ValueError):
                rate = 0
            # Prefer H.264 (is_bytevc1==0 / codec_type==0) slightly when bitrates are comparable.
            is_h264 = 1 if entry.get("is_bytevc1") in (0, False, None) and entry.get("codec_type") in (0, None, "h264") else 0
            urls = _urls_from_addr_node(entry.get("play_addr") or entry.get("playAddr"))
            for u in urls:
                if "mime_type=audio" not in u.lower():
                    rated.append((is_h264, rate, u))
    play_urls = []
    for _, _, u in sorted(rated, key=lambda item: (item[0], item[1]), reverse=True):
        _add_unique_url(play_urls, u)
    for key in ("play_addr", "playAddr", "play_addr_h264", "play_addr_265", "playApi", "download_addr"):
        for u in _urls_from_addr_node(video.get(key)):
            if "mime_type=audio" not in u.lower():
                _add_unique_url(play_urls, u)
    # Also handle non-watermark variant preference if a /playwm/ URL slipped in first.
    play_urls.sort(key=lambda u: 1 if "/playwm/" in u.lower() else 0)

    audio_rates = []
    for list_key in ("bit_rate_audio", "bitRateAudio"):
        items = video.get(list_key)
        if not isinstance(items, list):
            continue
        for entry in items:
            if not isinstance(entry, dict):
                continue
            meta = entry.get("audio_meta") if isinstance(entry.get("audio_meta"), dict) else {}
            rate = entry.get("bit_rate") or entry.get("bitRate") or meta.get("bitrate") or 0
            try:
                rate = int(rate)
            except (TypeError, ValueError):
                rate = 0
            urls = [
                *_urls_from_addr_node(entry.get("play_addr") or entry.get("playAddr")),
                *_urls_from_addr_node(meta.get("url_list")),
                *_urls_from_addr_node(meta.get("main_url")),
            ]
            for u in urls:
                audio_rates.append((rate, u))
    audio_url = max(audio_rates, key=lambda item: item[0])[1] if audio_rates else ""

    images = []
    for item in obj.get("images") or []:
        if not isinstance(item, dict) or len(images) >= 30:
            continue
        urls = (
            _urls_from_addr_node(item.get("url_list"))
            or _urls_from_addr_node(item.get("urlList"))
            or _urls_from_addr_node(item.get("download_url_list"))
        )
        if urls:
            _add_unique_url(images, urls[0])

    # Strictly read video.duration (milliseconds) — never music.duration (seconds)!
    duration = None
    raw_duration = video.get("duration")
    if raw_duration is None and not isinstance(obj.get("music"), dict):
        raw_duration = obj.get("duration")
    if raw_duration is not None:
        try:
            value = float(raw_duration)
            if value > 0:
                duration = value / 1000.0
        except (TypeError, ValueError):
            duration = None

    aweme_type = obj.get("aweme_type", obj.get("awemeType"))
    image_note = bool(images) and (not play_urls or aweme_type in {68, "68"})
    if not play_urls and not image_note:
        return None
    author_obj = obj.get("author") if isinstance(obj.get("author"), dict) else {}
    author = str(author_obj.get("nickname") or author_obj.get("nickName") or "").strip()
    title = str(obj.get("desc") or obj.get("preview_title") or obj.get("title") or "").strip()
    cover_urls = (
        _urls_from_addr_node(video.get("origin_cover"))
        or _urls_from_addr_node(video.get("cover"))
        or _urls_from_addr_node(video.get("dynamic_cover"))
    )
    return {
        "url": play_urls[0] if play_urls else "",
        "play_urls": play_urls,
        "audio_url": audio_url,
        "duration": duration,
        "aweme_id": ident,
        "title": title,
        "author": author,
        "cover": cover_urls[0] if cover_urls else "",
        "images": images,
        "image_note": image_note,
    }


def _find_aweme_in_tree(node, expected_id="", depth=0):
    if depth > 24:
        return None
    if isinstance(node, dict):
        # Prioritize explicit detail containers first.
        for key in ("aweme_detail", "awemeDetail", "videoDetail", "detail", "item_info"):
            child = node.get(key)
            if isinstance(child, dict):
                parsed = _parse_aweme_dict(child, expected_id)
                if parsed:
                    return parsed
        parsed = _parse_aweme_dict(node, expected_id)
        if parsed:
            return parsed
        for value in node.values():
            if isinstance(value, (dict, list)):
                found = _find_aweme_in_tree(value, expected_id, depth + 1)
                if found:
                    return found
    elif isinstance(node, list):
        for item in node:
            if isinstance(item, (dict, list)):
                found = _find_aweme_in_tree(item, expected_id, depth + 1)
                if found:
                    return found
    return None


def extract_douyin_api_detail(raw_text, aweme_id=""):
    """Parse an intercepted Douyin XHR/Fetch JSON payload and return the exact target aweme."""
    if not raw_text:
        return None
    try:
        payload = json.loads(raw_text)
    except (ValueError, json.JSONDecodeError):
        return None
    return _find_aweme_in_tree(payload, str(aweme_id or ""))


def _video_subobject(window):
    match = re.search(r'"video"\s*:\s*\{', window)
    if not match:
        return ""
    start = window.find("{", match.start())
    end = _brace_end(window, start)
    return window[start:end] if end else window[start:start + 40000]


def _without_music_object(window):
    match = re.search(r'"music"\s*:\s*\{', window)
    if not match:
        return window
    start = window.find("{", match.start())
    end = _brace_end(window, start)
    return (window[:match.start()] + window[end:]) if end else window


def _enclosing_objects(text, index, max_levels=3, max_span=240000):
    """Yield enclosing {...} objects around index from smallest outward, up to max_levels."""
    found = []
    pos = index
    min_pos = max(0, index - max_span)
    while pos >= min_pos and len(found) < max_levels:
        pos = text.rfind("{", min_pos, pos)
        if pos < 0:
            break
        end = _brace_end(text, pos, limit=max_span)
        if end and end > index:
            if not found or (pos < found[-1][0] and end >= found[-1][1]):
                found.append((pos, end))
    return [text[lo:hi] for lo, hi in found]


def _feature_from_window(window, target_id):
    try:
        parsed_json = json.loads(window)
    except (ValueError, json.JSONDecodeError):
        parsed_json = None
    if isinstance(parsed_json, dict):
        exact = _parse_aweme_dict(parsed_json, target_id)
        if exact:
            return exact
        nested = _find_aweme_in_tree(parsed_json, target_id)
        if nested:
            return nested
    # Reject windows that accidentally span multiple unrelated aweme objects without clean JSON boundaries.
    other_ids = set(re.findall(r'["\'](?:aweme_?id|item_?id)["\']\s*:\s*["\']?(\d{6,})["\']?', window, re.I))
    if len(other_ids) > 1:
        return None
    video_part = _video_subobject(window) or _without_music_object(window)
    play_urls = _play_addresses(_without_audio_lists(video_part))
    if not play_urls:
        return None
    duration = None
    timed = re.search(r'"duration"\s*:\s*(\d+)', video_part)
    if timed:
        duration = int(timed.group(1)) / 1000  # Aweme video.duration is milliseconds, including sub-second clips.
    audio = _audio_address(video_part) or _audio_address(window)
    return {
        "url": play_urls[0],
        "play_urls": play_urls,
        "audio_url": audio,
        "duration": duration,
        "aweme_id": target_id,
        "title": _json_string(window, "desc"),
        "author": _json_string(window, "nickname") or _json_string(window, "nickName"),
        "cover": "",
        "images": [],
        "image_note": False,
    }


def _extract_feature_from_text(source, aweme_id):
    # 1. Fast path if source itself is pure JSON (e.g., intercepted API response or unit tests).
    stripped = source.lstrip()
    if stripped.startswith("{"):
        try:
            direct = json.loads(stripped)
            found = _find_aweme_in_tree(direct, aweme_id)
            if found:
                return found
        except (ValueError, json.JSONDecodeError):
            pass
    # 2. Scan ALL occurrences of target aweme_id — never stop at the first metadata/route mention!
    pattern = re.compile(r'["\'](?:aweme_?id|item_?id)["\']\s*:\s*["\']?' + re.escape(aweme_id) + r'["\']?', re.I)
    for match in pattern.finditer(source):
        for window in _enclosing_objects(source, match.start()):
            feature = _feature_from_window(window, aweme_id)
            if feature:
                return feature
    return None


def player_feature(text, aweme_id=""):
    raw = text or ""
    plain = decode_page(raw)
    candidates = [plain, *_flight_blobs(raw)]
    aweme_id = str(aweme_id or "").strip()
    if not aweme_id:
        found = DOUYIN_ID.search(plain)
        aweme_id = found.group(1) if found else ""
    if not aweme_id:
        q = re.search(r'(?:modal_id|item_ids|aweme_id)=(\d{6,})', plain)
        aweme_id = q.group(1) if q else ""
    if not aweme_id:
        # Look for explicit detail container first.
        for blob in candidates:
            for marker in ('"aweme_detail"', '"awemeDetail"', '"videoDetail"'):
                pos = blob.find(marker)
                if pos >= 0:
                    brace = blob.find("{", pos + len(marker))
                    end = _brace_end(blob, brace) if brace >= 0 else None
                    if end:
                        try:
                            detail_obj = json.loads(blob[brace:end])
                            parsed = _find_aweme_in_tree(detail_obj, "")
                            if parsed:
                                return parsed
                        except (ValueError, json.JSONDecodeError):
                            pass
        all_ids = set()
        for blob in candidates:
            all_ids.update(re.findall(r'["\'](?:aweme_?id|item_?id)["\']\s*:\s*["\']?(\d{6,})["\']?', blob, re.I))
        aweme_id = next(iter(all_ids)) if len(all_ids) == 1 else ""
    if not aweme_id:
        return None
    for blob in candidates:
        feature = _extract_feature_from_text(blob, aweme_id)
        if feature:
            return feature
    return None


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
    feature = None
    if info["platform"] == "抖音":
        feature = player_feature(html or text, aweme_id or video_id)
        if feature and feature.get("aweme_id") and not aweme_id:
            aweme_id = video_id = feature["aweme_id"]
        media_urls = list(feature.get("play_urls") or []) if feature else []
        if not media_urls and feature and feature.get("url"):
            media_urls = [feature["url"]]
        video_url = media_urls[0] if media_urls else ""
        duration = feature.get("duration") if feature else None
        audio_url = feature.get("audio_url") if feature else ""
        if feature:
            if feature.get("title") and not title:
                title = feature["title"]
            if feature.get("title") and not body:
                body = feature["title"]
            if feature.get("author") and not author:
                author = feature["author"]
    else:
        media_urls = rank_media_urls(collect_media_urls(text), aweme_id or video_id)
        video_url = media_urls[0] if media_urls else ""
        duration = page_duration(text)
        audio_url = ""
    images = list(feature.get("images") or []) if (info["platform"] == "抖音" and feature and feature.get("images")) else _images(text, info["platform"])
    compact = re.sub(r"\s+", "", text)
    image_note = (
        (info["platform"] == "抖音" and bool(feature and feature.get("image_note") and not video_url))
        or (
            info["platform"] == "小红书" and not video_url and (
                '"type":"normal"' in compact or '"notetype":"normal"' in compact.lower()
            ) and '"type":"video"' not in compact
        )
    )
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
        prefix = "note" if image_note else "video"
        canonical = f"https://www.douyin.com/{prefix}/{video_id or aweme_id}"
    elif info["platform"] == "小红书" and note_id:
        canonical = f"https://www.xiaohongshu.com/explore/{note_id}"
    path = (urlsplit(url).path or "/").rstrip("/") or "/"
    host = (urlsplit(url).hostname or "").lower()
    login_wall = path == "/login" and (info["platform"] in {"抖音", "小红书"} or "xiaohongshu" in host or "douyin" in host)
    lowered_text = text.lower()
    captcha_wall = (
        info["platform"] == "抖音"
        and not video_url
        and not image_note
        and any(marker in lowered_text for marker in ("captcha_verify", "verifycenter", "ttwid-verify", "请完成下列验证", "验证码中间页"))
    )
    return {
        "url": url, "platform": info["platform"], "source_kind": info["source_kind"], "kind": info["kind"],
        "form": info["form"], "video_id": video_id, "aweme_id": aweme_id or video_id, "note_id": note_id,
        "title": title.strip(), "author": author.strip(), "description": description.strip(), "body": body.strip(),
        "images": images, "video_url": video_url, "media_urls": media_urls, "backup_urls": backups,
        "duration": duration, "audio_url": audio_url, "image_note": image_note, "canonical_url": canonical,
        "original_url": url, "resolved_fetch_url": url, "login_wall": login_wall, "captcha_wall": captcha_wall,
        "thumbnail": (feature.get("cover") if feature else "") or meta.get("og:image") or "",
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
