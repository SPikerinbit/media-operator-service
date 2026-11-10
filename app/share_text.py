"""Pull links, authors and titles out of a pasted share blurb."""
import re

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


def parse(text):
    items = []
    cursor = 0
    for match in URL.finditer(text or ""):
        url = match.group(0).rstrip(".,;:)]}")
        segment = title_line(text[cursor:match.start()])
        cursor = match.end()
        author = ""
        found = AUTHOR.search(segment)
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
            "title": clean_title(title),
            "source_kind": info["source_kind"],
        }
        duration = share_duration(segment)
        if duration:
            item["duration"] = duration
        items.append(item)
    return items
