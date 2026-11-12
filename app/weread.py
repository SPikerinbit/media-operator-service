"""WeChat Read chapter text.

Parsing is covered by tests. Fetching a live book needs a logged-in
微信读书 session from the same popup flow as the other sites, and that
path is not verified here.
"""
import re
from html import unescape

BOOK = re.compile(r"weread\.qq\.com/(?:web/)?reader/([A-Za-z0-9]+)")
TAG = re.compile(r"<[^>]+>")


class LoginRequired(RuntimeError):
    pass


def book_id(url):
    match = BOOK.search(url or "")
    if not match:
        raise ValueError("不是微信读书的阅读链接")
    return match.group(1)


def chapters_from(payload):
    rows = []
    books = payload.get("chapters")
    data = payload.get("data") if books is None else [{"updated": books}]
    if isinstance(data, dict):
        data = [data]
    for book in data or []:
        if not isinstance(book, dict):
            continue
        for chapter in book.get("updated") or book.get("chapters") or []:
            if not isinstance(chapter, dict):
                continue
            uid = chapter.get("chapterUid", chapter.get("uid"))
            if uid is None:
                continue
            rows.append({"uid": int(uid), "title": str(chapter.get("title") or "")})
    return rows


def _plain(value):
    text = unescape(TAG.sub("", str(value or "")))
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def text_from_chapter(payload):
    if isinstance(payload, str):
        return _plain(payload)
    if not isinstance(payload, dict):
        return ""
    for key in ("content", "text", "html"):
        if isinstance(payload.get(key), str) and payload[key].strip():
            return _plain(payload[key])
    parts = payload.get("paragraphs") or payload.get("contents") or []
    lines = []
    if isinstance(parts, list):
        for item in parts:
            lines.append(_plain(item.get("text") if isinstance(item, dict) else item))
    return "\n".join(line for line in lines if line)


def title_from(payload):
    data = payload.get("data")
    book = data[0] if isinstance(data, list) and data else payload
    if isinstance(book, dict):
        nested = book.get("book") if isinstance(book.get("book"), dict) else book
        return str(nested.get("title") or "")
    return ""


def assemble(chapters):
    blocks = []
    for chapter in chapters:
        body = (chapter.get("text") or "").strip()
        if not body:
            continue
        title = (chapter.get("title") or "").strip()
        blocks.append(f"{title}\n{body}" if title else body)
    return "\n\n".join(blocks)


def cookie_header(value):
    text = value or ""
    if "\t" not in text:
        return text.strip()
    pairs = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) >= 7 and parts[-2] and parts[-1]:
            pairs.append(parts[-2] + "=" + parts[-1])
    return "; ".join(pairs)


def fetch_book(url, cookie_header, client=None):
    if not (cookie_header or "").strip():
        raise LoginRequired("需要登录微信读书后才能读取章节")
    ident = book_id(url)
    import httpx

    own = client is None
    session = client or httpx.Client(timeout=20, headers={
        "User-Agent": "Mozilla/5.0",
        "Cookie": cookie_header,
        "Referer": "https://weread.qq.com/",
    })
    try:
        info = session.post("https://i.weread.qq.com/book/chapterInfos", json={"bookIds": [ident], "synckeys": [0]})
        if info.status_code in {401, 403}:
            if own:
                from app.site_profiles import invalidate
                invalidate('weread')
            raise LoginRequired("微信读书登录已失效")
        info.raise_for_status()
        payload = info.json()
        chapters = chapters_from(payload)
        if not chapters:
            raise ValueError("没有读到章节列表")
        collected = []
        for chapter in chapters[:40]:
            page = session.get(
                f"https://i.weread.qq.com/book/chapter/e/{chapter['uid']}",
                params={"bookId": ident},
            )
            if page.status_code in {401, 403}:
                if own:
                    from app.site_profiles import invalidate
                    invalidate('weread')
                raise LoginRequired("微信读书登录已失效")
            page.raise_for_status()
            body = page.json() if "json" in page.headers.get("content-type", "") else {"content": page.text}
            text = text_from_chapter(body)
            if text:
                collected.append({"title": chapter["title"], "text": text})
        joined = assemble(collected)
        if not joined:
            raise ValueError("章节正文为空")
        return {"book_id": ident, "title": title_from(payload) or ident, "text": joined}
    finally:
        if own:
            session.close()
