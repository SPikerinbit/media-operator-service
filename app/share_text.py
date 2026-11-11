"""Classify pasted letters. Python is the source of truth for the workbench.

`classify_letters` is the shared classifier. A later UI can mirror it:
one http(s) link, even across lines, stays one letter; distinct links and
local paths become separate letters.
"""
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from app.sites.resolve import classify

URL = re.compile(r"https?://[^\s<>\"'，。；！？、）】》]+", re.I)
AUTHOR = re.compile(r"【\s*(.+?)\s*的作品】")
PREFIX = re.compile(r"^(?:\d+(?:\.\d+)?\s+)?(?:复制打开(?:抖音|小红书)[，,]?\s*(?:看看)?)")
TRAILING_DOTS = re.compile(r"(?:\.{3,}|…{1,}|。{2,})$")
SHARE_CLOCK = re.compile(r"^(\d{1,3})\.(\d{2})(?:\s|$)")


def share_duration(text):
    match = SHARE_CLOCK.match((text or "").lstrip())
    if not match:
        return None
    minutes, seconds = int(match.group(1)), int(match.group(2))
    if seconds >= 60:
        return None
    total = minutes * 60 + seconds
    return total if 0 < total <= 6 * 3600 else None


def clean_title(value):
    text = re.sub(r"\s+", " ", value or "").strip(" \t\r\n-—:：")
    text = PREFIX.sub("", text).strip()
    return TRAILING_DOTS.sub("……", text).strip()


def title_line(prefix):
    lines = [line.strip() for line in (prefix or "").splitlines() if line.strip()]
    return lines[-1] if lines else ""


FILE_URL = re.compile(r"file://[^\s<>\"']+", re.I)
QUOTED_PATH = re.compile(
    r"""(?P<quote>["'])(?P<body>(?:[A-Za-z]:[\\/]|\\\\)[^"']+)(?P=quote)"""
)
LINE_PATH = re.compile(
    r"(?m)^[ \t]*(?P<body>(?:[A-Za-z]:[\\/]|\\\\)[^\r\n]*\S)[ \t]*$"
)


def _url_item(segment, url):
    author = ""
    found = AUTHOR.search(segment or "")
    if found:
        author = found.group(1).strip()
        title = segment[found.end():]
    else:
        title = segment
    info = classify(url)
    item = {
        "url": url,
        "platform": info["platform"],
        "author": author,
        "title": clean_title(title_line(title) or title),
        "source_kind": info["source_kind"],
    }
    duration = share_duration(segment)
    if duration:
        item["duration"] = duration
    return item


def parse(text):
    items = []
    cursor = 0
    for match in URL.finditer(text or ""):
        url = match.group(0).rstrip(".,;:)]}")
        segment = title_line(text[cursor:match.start()])
        cursor = match.end()
        items.append(_url_item(segment, url))
    return items


def _file_url_path(url):
    parts = urlsplit(url)
    path = unquote(parts.path or "")
    host = (parts.netloc or "").lower()
    if host and host not in {"localhost"}:
        suffix = path.replace("/", "\\").lstrip("\\")
        return "\\\\" + parts.netloc + "\\" + suffix
    if path.startswith("/") and len(path) >= 3 and path[2] == ":":
        path = path[1:]
    return str(Path(path.replace("/", "\\")))


def _normalize_path(value):
    text = (value or "").strip().strip('"').strip("'")
    if text.lower().startswith("file:"):
        return _file_url_path(text)
    return str(Path(text))


class _Span:
    def __init__(self, start, end, kind, source, raw):
        self.start = start
        self.end = end
        self.kind = kind
        self.source = source
        self.raw = raw


def _overlaps(span, others):
    return any(not (span.end <= item.start or span.start >= item.end) for item in others)


def _spans(text):
    found = []
    for match in FILE_URL.finditer(text):
        raw = match.group(0)
        found.append(_Span(match.start(), match.end(), "local", _file_url_path(raw), raw))
    for match in QUOTED_PATH.finditer(text):
        body = match.group("body")
        found.append(_Span(match.start(), match.end(), "local", _normalize_path(body), match.group(0)))
    for match in URL.finditer(text):
        url = match.group(0).rstrip(".,;:)]}")
        end = match.start() + len(url)
        found.append(_Span(match.start(), end, "url", url, url))
    for match in LINE_PATH.finditer(text):
        body = match.group("body").strip()
        if "://" in body:
            continue
        span = _Span(match.start("body"), match.end("body"), "local", _normalize_path(body), body)
        if _overlaps(span, found):
            continue
        found.append(span)
    found.sort(key=lambda item: (item.start, 0 if item.kind == "local" else 1))
    kept = []
    for span in found:
        if _overlaps(span, kept):
            continue
        kept.append(span)
    return kept


def _local_item(span):
    source = span.source
    return {
        "kind": "local",
        "local": True,
        "text": span.raw.strip(),
        "source": source,
        "url": source,
        "platform": "本地文件",
        "author": "",
        "title": Path(source).name,
        "source_kind": "local",
    }


def _attach_url(segment, url):
    parsed = [item for item in parse(segment) if item["url"] == url]
    found = parsed[0] if parsed else _url_item("", url)
    return {**found, "kind": "url", "local": False, "text": (segment or "").strip() or url, "source": found["url"]}


def classify_letters(text):
    """Split pasted text into letters.

    Examples:
    - one share blurb with a single http(s) link, including extra lines, is one item
    - two different links are two items
    - ``"D:\\My Videos\\clip.mp4"``, ``\\\\server\\share\\clip.mp4`` and ``file:///D:/a.mp4`` are local items
    """
    raw = text or ""
    if not raw.strip():
        return []
    spans = _spans(raw)
    urls = [span for span in spans if span.kind == "url"]
    locals_ = [span for span in spans if span.kind == "local"]
    distinct = list(dict.fromkeys(span.source for span in urls))
    if len(distinct) == 1 and not locals_:
        return [_attach_url(raw.strip(), distinct[0])]
    if not spans:
        return []
    if not locals_ and len(distinct) > 1:
        items = []
        seen = set()
        chosen = []
        for span in urls:
            if span.source in seen:
                continue
            seen.add(span.source)
            chosen.append(span)
        start = 0
        for index, span in enumerate(chosen):
            end = len(raw) if index == len(chosen) - 1 else span.end
            items.append(_attach_url(raw[start:end], span.source))
            start = span.end
        return items
    items = []
    seen = set()
    for span in spans:
        key = ("local" if span.kind == "local" else "url") + ":" + span.source.casefold()
        if key in seen:
            continue
        seen.add(key)
        if span.kind == "local":
            items.append(_local_item(span))
            continue
        window_start = raw.rfind("\n", 0, span.start) + 1
        items.append(_attach_url(raw[window_start:span.end], span.source))
    return items
