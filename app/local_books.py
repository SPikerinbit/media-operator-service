"""Pure-Python, MIT-clean local e-book and document extractor for the Notes lane.

Supports:
- Plain text & Markdown: .txt, .md, .markdown
- Web / HTML documents: .html, .htm, .xhtml
- EPUB 2 & EPUB 3: .epub (ZIP + OPF manifest/spine + DRM check)
- Kindle / Mobipocket: .mobi, .azw3, .azw, .kf8, .prc
  (PalmDB + PalmDOC LZ77 + HUFF/CDIC + EXTH metadata + Dual-MOBI + KF8 FDST + DRM check)
- FictionBook 2: .fb2
- Word manuscripts: .docx
- Text-layer PDF: .pdf (via pypdf, with encrypted & scanned-image detection)
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
import posixpath
import re
import struct
from typing import Any
from urllib.parse import unquote
import xml.etree.ElementTree as ET
import zipfile

from bs4 import BeautifulSoup
from charset_normalizer import from_bytes as detect_charset

MAX_BOOK_FILE_BYTES = 250 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 250 * 1024 * 1024
MAX_ZIP_ENTRIES = 10_000
MAX_BOOK_CHARS = 20_000_000
MAX_PARAGRAPH_CHARS = 2400
MAX_HUFF_DEPTH = 64

BOOK_FORMATS: dict[str, str] = {
    ".txt": "TXT",
    ".md": "Markdown",
    ".markdown": "Markdown",
    ".html": "HTML",
    ".htm": "HTML",
    ".xhtml": "HTML",
    ".epub": "EPUB",
    ".mobi": "MOBI",
    ".azw3": "AZW3",
    ".azw": "AZW",
    ".kf8": "AZW3",
    ".prc": "PRC",
    ".fb2": "FB2",
    ".docx": "DOCX",
    ".pdf": "PDF",
    ".kfx": "KFX",
}

FONT_OBFUSCATION_ALGORITHMS = {
    "http://www.idpf.org/2008/embedding",
    "http://ns.adobe.com/pdf/enc#rc",
}

_CHAPTER_HEADING_RE = re.compile(
    r"^(?:"
    r"第[零一二三四五六七八九十百千万两0-9]{1,8}[章节回卷部篇集幕节讲课](?:[\s：:·\-—].*)?|"
    r"(?:chapter|part|book|section|prologue|epilogue|preface|introduction|appendix)\b.*|"
    r"(?:序言|前言|引言|导言|楔子|尾声|后记|跋|番外|附录|目录)(?:[\s：:·\-—].*)?|"
    r"#{1,6}\s+\S.*"
    r")$",
    re.IGNORECASE,
)
_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?；;.]\s*")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HTML_BLOCK_TAGS = {
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "blockquote", "li", "pre", "dt", "dd", "figcaption", "tr",
}
_HTML_CONTAINER_TAGS = {
    "div", "section", "article", "main", "header", "footer", "aside", "body", "td", "th",
}


class BookError(ValueError):
    """User-facing error raised when a local book cannot be extracted."""


def is_book_path(value: str | Path | None) -> bool:
    if not value:
        return False
    suffix = Path(str(value)).suffix.lower()
    return suffix in BOOK_FORMATS


def book_format(value: str | Path) -> str:
    return BOOK_FORMATS.get(Path(str(value)).suffix.lower(), "图书")


def probe_book(path: Path) -> dict[str, Any]:
    """Fast extension-based classification for inbox receipt (never reads book contents)."""
    fmt = book_format(path)
    return {
        "title": path.stem or path.name,
        "platform": f"本地图书 · {fmt}",
        "media_type": "book",
        "book_format": fmt,
        "has_audio": False,
        "audio_direct": False,
        "duration": None,
    }


def _clean_text(value: str) -> str:
    text = _CONTROL_CHARS_RE.sub("", value or "")
    text = text.replace("\u00a0", " ").replace("\u3000", " ")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _decode_bytes(raw: bytes, preferred_encoding: str = "") -> str:
    if not raw:
        return ""
    if raw.startswith(b"\xef\xbb\xbf"):
        return _clean_text(raw.decode("utf-8-sig", errors="replace"))
    if raw.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        try:
            return _clean_text(raw.decode("utf-32"))
        except UnicodeDecodeError:
            pass
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return _clean_text(raw.decode("utf-16"))
        except UnicodeDecodeError:
            pass

    if preferred_encoding:
        normalized = preferred_encoding.strip().lower().replace("_", "-")
        if normalized in {"gb2312", "gbk", "cp936"}:
            normalized = "gb18030"
        try:
            return _clean_text(raw.decode(normalized))
        except (LookupError, UnicodeDecodeError):
            pass

    try:
        return _clean_text(raw.decode("utf-8"))
    except UnicodeDecodeError:
        pass

    sample = raw[:262_144]
    detected = detect_charset(sample).best()
    if detected and detected.encoding:
        enc = detected.encoding.lower().replace("_", "-")
        if enc in {"gb2312", "gbk", "cp936"}:
            enc = "gb18030"
        try:
            return _clean_text(raw.decode(enc))
        except (LookupError, UnicodeDecodeError):
            pass

    for fallback in ("gb18030", "big5", "cp1252"):
        try:
            return _clean_text(raw.decode(fallback))
        except UnicodeDecodeError:
            continue
    return _clean_text(raw.decode("utf-8", errors="replace"))


def _join_wrapped_lines(lines: list[str]) -> str:
    out: list[str] = []
    for raw in lines:
        part = " ".join(raw.split())
        if not part:
            continue
        if not out:
            out.append(part)
            continue
        prev = out[-1]
        # Avoid inserting a space between adjacent CJK characters when unwrapping.
        if prev and part and ord(prev[-1]) >= 0x2E80 and ord(part[0]) >= 0x2E80:
            out.append(part)
        elif prev.endswith("-") and len(prev) >= 2 and prev[-2].isascii() and part[0].isascii():
            out[-1] = prev[:-1]
            out.append(part)
        else:
            out.append(" " + part)
    return "".join(out)


def _split_long_paragraph(text: str, max_chars: int = MAX_PARAGRAPH_CHARS) -> list[str]:
    clean = text.strip()
    if len(clean) <= max_chars:
        return [clean] if clean else []
    chunks: list[str] = []
    start = 0
    total = len(clean)
    while start < total:
        end = min(total, start + max_chars)
        if end < total:
            window = clean[start:end]
            matches = list(_SENTENCE_SPLIT_RE.finditer(window))
            cut = None
            for m in reversed(matches):
                if m.end() >= max_chars // 2:
                    cut = start + m.end()
                    break
            if cut is None:
                space = window.rfind(" ")
                if space >= max_chars // 2:
                    cut = start + space + 1
            if cut is not None and cut > start:
                end = cut
        piece = clean[start:end].strip()
        if piece:
            chunks.append(piece)
        start = end
    return chunks


def _normalize_paragraphs(raw_paragraphs: list[str]) -> list[str]:
    result: list[str] = []
    total_chars = 0
    for item in raw_paragraphs:
        compact = re.sub(r"[ \t]+", " ", (item or "").strip())
        compact = re.sub(r"\n{3,}", "\n\n", compact).strip()
        if not compact:
            continue
        for piece in _split_long_paragraph(compact):
            if total_chars + len(piece) > MAX_BOOK_CHARS:
                remaining = MAX_BOOK_CHARS - total_chars
                if remaining > 0:
                    result.append(piece[:remaining].strip())
                return result
            result.append(piece)
            total_chars += len(piece)
    return result


def _split_plain_paragraphs(text: str, *, markdown: bool = False) -> tuple[list[str], int]:
    lines = text.split("\n")
    non_empty = [ln.strip() for ln in lines if ln.strip()]
    if not non_empty:
        return [], 0

    blank_lines = sum(1 for ln in lines if not ln.strip())
    short_lines = sum(1 for ln in non_empty if len(ln) <= 90)
    # Hard-wrapped books (e.g. Project Gutenberg / Markdown) have many blank lines
    # separating multi-line wrapped blocks.
    use_blank_blocks = blank_lines >= max(2, len(non_empty) // 10) and (short_lines / len(non_empty)) >= 0.55

    raw_paragraphs: list[str] = []
    chapters = 0

    def clean_md_line(line: str) -> tuple[str, bool]:
        if not markdown:
            return line, bool(_CHAPTER_HEADING_RE.match(line))
        if re.fullmatch(r"[-*_]{3,}", line):
            return "", False
        heading = re.match(r"^(#{1,6})\s+(.+?)(?:\s+#+)?$", line)
        if heading:
            return heading.group(2).strip(), True
        line = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", line)
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
        return line.strip(), bool(_CHAPTER_HEADING_RE.match(line))

    if use_blank_blocks:
        buf: list[str] = []

        def flush() -> None:
            if buf:
                joined = _join_wrapped_lines(buf)
                if joined:
                    raw_paragraphs.append(joined)
                buf.clear()

        for raw_line in lines:
            stripped = raw_line.strip()
            if not stripped:
                flush()
                continue
            cleaned, is_heading = clean_md_line(stripped)
            if not cleaned:
                flush()
                continue
            if is_heading:
                flush()
                chapters += 1
                raw_paragraphs.append(cleaned)
                continue
            if markdown and re.match(r"^(?:[-*+]\s+|\d+\.\s+|>\s+)", stripped):
                flush()
                raw_paragraphs.append(re.sub(r"^>\s*", "", cleaned).strip())
                continue
            buf.append(cleaned)
        flush()
    else:
        for raw_line in lines:
            stripped = raw_line.strip()
            if not stripped:
                continue
            cleaned, is_heading = clean_md_line(stripped)
            if not cleaned:
                continue
            if is_heading:
                chapters += 1
            raw_paragraphs.append(cleaned)

    return _normalize_paragraphs(raw_paragraphs), chapters


def _make_soup(html_text: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html_text, "lxml")
    except Exception:
        return BeautifulSoup(html_text, "html.parser")


def _html_to_paragraphs(html_text: str) -> tuple[list[str], str]:
    soup = _make_soup(html_text)
    title_tag = soup.find("title")
    doc_title = " ".join(title_tag.get_text(" ", strip=True).split()) if title_tag else ""

    for bad in soup.find_all(["script", "style", "noscript", "svg", "head", "rt", "rp"]):
        bad.decompose()

    root = soup.body if soup.body is not None else soup
    paragraphs: list[str] = []

    def has_block_descendant(tag: Any) -> bool:
        for child in tag.find_all(recursive=False):
            name = getattr(child, "name", None)
            if not name:
                continue
            lname = name.lower()
            if lname in _HTML_BLOCK_TAGS or lname in _HTML_CONTAINER_TAGS or has_block_descendant(child):
                return True
        return False

    def extract_text(node: Any) -> str:
        # Replace <br> with newlines inside a block so poem/verse/dialog splits stay legible.
        parts: list[str] = []
        for desc in node.descendants:
            name = getattr(desc, "name", None)
            if name and name.lower() == "br":
                parts.append("\n")
            elif name is None:
                text = str(desc)
                if text:
                    parts.append(text)
        joined = "".join(parts)
        lines = [" ".join(ln.split()) for ln in joined.split("\n")]
        return "\n".join(ln for ln in lines if ln)

    def walk(node: Any) -> None:
        inline_buf: list[str] = []

        def flush_inline() -> None:
            if not inline_buf:
                return
            joined = " ".join("".join(inline_buf).split()).strip()
            inline_buf.clear()
            if joined:
                paragraphs.append(joined)

        for child in node.children:
            name = getattr(child, "name", None)
            if name is None:
                text = str(child)
                if text and text.strip():
                    inline_buf.append(text)
                continue
            lname = name.lower()
            if lname in {"script", "style", "noscript", "svg", "head", "rt", "rp"}:
                continue
            if lname == "br":
                flush_inline()
                continue
            if lname in _HTML_BLOCK_TAGS:
                flush_inline()
                if lname in {"blockquote", "li", "tr"} and has_block_descendant(child):
                    walk(child)
                else:
                    text = extract_text(child)
                    if text:
                        for sub in text.split("\n"):
                            if sub.strip():
                                paragraphs.append(sub.strip())
                continue
            if lname in _HTML_CONTAINER_TAGS:
                flush_inline()
                if has_block_descendant(child):
                    walk(child)
                else:
                    text = extract_text(child)
                    if text:
                        for sub in text.split("\n"):
                            if sub.strip():
                                paragraphs.append(sub.strip())
                continue
            # Inline tag (span, a, em, strong, ruby, etc.)
            text = extract_text(child)
            if text:
                inline_buf.append(" " + text + " ")
        flush_inline()

    walk(root)
    if not paragraphs:
        fallback = root.get_text("\n", strip=True)
        paragraphs = [ln.strip() for ln in fallback.splitlines() if ln.strip()]
    return paragraphs, doc_title


def _parse_xml_safe(raw: bytes) -> ET.Element:
    try:
        from lxml import etree as lxml_etree

        parser = lxml_etree.XMLParser(resolve_entities=False, no_network=True, recover=True)
        parsed = lxml_etree.fromstring(raw, parser=parser)
        if parsed is None:
            raise ValueError("empty xml")
        return ET.fromstring(lxml_etree.tostring(parsed, encoding="utf-8"))
    except Exception:
        return ET.fromstring(raw)


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1].lower()
    if ":" in tag:
        return tag.rsplit(":", 1)[1].lower()
    return tag.lower()


def _extract_txt(path: Path, *, markdown: bool = False) -> dict[str, Any]:
    raw = path.read_bytes()
    text = _decode_bytes(raw)
    paragraphs, chapters = _split_plain_paragraphs(text, markdown=markdown)
    title = path.stem or path.name
    if markdown and paragraphs:
        first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
        m = re.match(r"^#\s+(.+?)(?:\s+#+)?$", first_line)
        if m and 1 <= len(m.group(1).strip()) <= 120:
            title = m.group(1).strip()
    return {
        "title": title,
        "author": "",
        "format": "Markdown" if markdown else "TXT",
        "language": "",
        "paragraphs": paragraphs,
        "chapters": max(1, chapters) if paragraphs else 0,
    }


def _extract_html_file(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    html_text = _decode_bytes(raw)
    paragraphs, doc_title = _html_to_paragraphs(html_text)
    paragraphs = _normalize_paragraphs(paragraphs)
    return {
        "title": doc_title[:160] if doc_title else (path.stem or path.name),
        "author": "",
        "format": "HTML",
        "language": "",
        "paragraphs": paragraphs,
        "chapters": 1 if paragraphs else 0,
    }


def _check_zip_safety(zf: zipfile.ZipFile) -> None:
    infos = zf.infolist()
    if len(infos) > MAX_ZIP_ENTRIES:
        raise BookError("压缩图书包内条目过多，超过安全限制")
    total_uncompressed = sum(max(0, info.file_size) for info in infos)
    if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
        raise BookError("电子书解压后体积超过 250 MB 安全限制")


def _extract_epub(path: Path) -> dict[str, Any]:
    try:
        zf = zipfile.ZipFile(path, "r")
    except zipfile.BadZipFile as error:
        raise BookError("EPUB 文件已损坏或不是有效的 EPUB 压缩包") from error

    with zf:
        _check_zip_safety(zf)
        names = zf.namelist()
        lower_map = {name.lower(): name for name in names}

        def read_member(member_path: str) -> bytes | None:
            normalized = posixpath.normpath(member_path).lstrip("/")
            if normalized.startswith(".."):
                return None
            if normalized in zf.NameToInfo:
                return zf.read(normalized)
            unquoted = unquote(normalized)
            if unquoted in zf.NameToInfo:
                return zf.read(unquoted)
            found = lower_map.get(normalized.lower()) or lower_map.get(unquoted.lower())
            return zf.read(found) if found else None

        # Check DRM in META-INF/encryption.xml (allow standard font obfuscation).
        enc_bytes = read_member("META-INF/encryption.xml")
        if enc_bytes:
            try:
                enc_root = _parse_xml_safe(enc_bytes)
                for elem in enc_root.iter():
                    if _local_name(elem.tag) == "encrypteddata":
                        algo = ""
                        uri = ""
                        for child in elem.iter():
                            cname = _local_name(child.tag)
                            if cname == "encryptionmethod":
                                algo = (child.attrib.get("Algorithm") or "").strip().lower()
                            elif cname == "cipherreference":
                                uri = (child.attrib.get("URI") or "").strip().lower()
                        if algo and algo not in FONT_OBFUSCATION_ALGORITHMS:
                            if not uri.endswith((".ttf", ".otf", ".woff", ".woff2")):
                                raise BookError("该 EPUB 文件受 DRM 加密保护，无法直接读取正文")
            except BookError:
                raise
            except Exception:
                pass

        opf_path = ""
        container_bytes = read_member("META-INF/container.xml")
        if container_bytes:
            try:
                container = _parse_xml_safe(container_bytes)
                for elem in container.iter():
                    if _local_name(elem.tag) == "rootfile" and elem.attrib.get("full-path"):
                        opf_path = elem.attrib["full-path"].strip()
                        break
            except Exception:
                pass
        if not opf_path:
            opf_path = next((n for n in names if n.lower().endswith(".opf")), "")

        title = ""
        authors: list[str] = []
        language = ""
        ordered_files: list[str] = []

        if opf_path:
            opf_bytes = read_member(opf_path)
            if opf_bytes:
                try:
                    opf_root = _parse_xml_safe(opf_bytes)
                    opf_dir = posixpath.dirname(opf_path)
                    manifest: dict[str, tuple[str, str, str]] = {}
                    spine_ids: list[str] = []
                    for elem in opf_root.iter():
                        lname = _local_name(elem.tag)
                        if lname == "title" and not title:
                            txt = " ".join((elem.text or "").split()).strip()
                            if txt:
                                title = txt
                        elif lname == "creator":
                            txt = " ".join((elem.text or "").split()).strip()
                            if txt and txt not in authors:
                                authors.append(txt)
                        elif lname == "language" and not language:
                            language = (elem.text or "").strip()[:16]
                        elif lname == "item":
                            ident = elem.attrib.get("id")
                            href = elem.attrib.get("href")
                            if ident and href:
                                resolved = posixpath.normpath(posixpath.join(opf_dir, href)) if opf_dir else posixpath.normpath(href)
                                manifest[ident] = (
                                    resolved,
                                    (elem.attrib.get("media-type") or "").lower(),
                                    (elem.attrib.get("properties") or "").lower(),
                                )
                        elif lname == "itemref":
                            idref = elem.attrib.get("idref")
                            if idref:
                                spine_ids.append(idref)

                    content_candidates: list[tuple[str, bool]] = []
                    for idref in spine_ids:
                        entry = manifest.get(idref)
                        if not entry:
                            continue
                        href, mtype, props = entry
                        is_html = (
                            "html" in mtype
                            or "xml" in mtype
                            or href.lower().endswith((".xhtml", ".html", ".htm"))
                        )
                        if is_html:
                            is_nav = "nav" in props.split()
                            content_candidates.append((href, is_nav))

                    non_nav = [href for href, is_nav in content_candidates if not is_nav]
                    ordered_files = non_nav if non_nav else [href for href, _ in content_candidates]
                except Exception:
                    ordered_files = []

        if not ordered_files:
            ordered_files = sorted(
                n for n in names
                if n.lower().endswith((".xhtml", ".html", ".htm"))
                and not n.lower().startswith("meta-inf/")
            )

        all_paragraphs: list[str] = []
        chapters = 0
        for member in ordered_files:
            data = read_member(member)
            if not data:
                continue
            html_text = _decode_bytes(data)
            chapter_paras, _ = _html_to_paragraphs(html_text)
            if chapter_paras:
                chapters += 1
                all_paragraphs.extend(chapter_paras)

        paragraphs = _normalize_paragraphs(all_paragraphs)
        return {
            "title": (title or path.stem or path.name)[:160],
            "author": " / ".join(authors)[:160],
            "format": "EPUB",
            "language": language,
            "paragraphs": paragraphs,
            "chapters": chapters,
        }


def _decompress_palmdoc(data: bytes) -> bytes:
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        c = data[i]
        i += 1
        if 1 <= c <= 8:
            out.extend(data[i:i + c])
            i += c
        elif c <= 0x7F:
            out.append(c)
        elif c >= 0xC0:
            out.append(0x20)
            out.append(c ^ 0x80)
        else:
            if i >= n:
                break
            pair = (c << 8) | data[i]
            i += 1
            dist = (pair >> 3) & 0x07FF
            length = (pair & 0x07) + 3
            if dist == 0 or dist > len(out):
                continue
            for _ in range(length):
                out.append(out[-dist])
    return bytes(out)


class _HuffCdicDecoder:
    """Pure-Python HUFF/CDIC decompressor for MOBI / KF8 (AZW3)."""

    def __init__(self, huff_record: bytes, cdic_records: list[bytes]):
        if len(huff_record) < 24 or huff_record[:4] != b"HUFF":
            raise BookError("电子书 HUFF 压缩头无效")
        off1, off2 = struct.unpack_from(">II", huff_record, 8)
        if off1 + 256 * 4 > len(huff_record) or off2 + 64 * 4 > len(huff_record):
            raise BookError("电子书 HUFF 表长度不足")

        dict1_raw = struct.unpack_from(">256I", huff_record, off1)
        self.dict1: list[tuple[int, bool, int]] = []
        for v in dict1_raw:
            codelen = v & 0x1F
            term = bool(v & 0x80)
            maxcode = (((v >> 8) + 1) << (32 - codelen)) - 1 if codelen > 0 else 0
            self.dict1.append((codelen, term, maxcode))

        dict2_raw = struct.unpack_from(">64I", huff_record, off2)
        self.mincode: list[int] = [0] * 33
        self.maxcode: list[int] = [0] * 33
        for k in range(1, 33):
            raw_min = dict2_raw[2 * (k - 1)]
            raw_max = dict2_raw[2 * (k - 1) + 1]
            self.mincode[k] = raw_min << (32 - k)
            self.maxcode[k] = ((raw_max + 1) << (32 - k)) - 1

        self.dictionary: list[tuple[bytes, bool]] = []
        for rec in cdic_records:
            if len(rec) < 16 or rec[:4] != b"CDIC":
                continue
            phrases, bits = struct.unpack_from(">II", rec, 8)
            count = min(1 << bits, max(0, phrases - len(self.dictionary)))
            if 16 + count * 2 > len(rec):
                count = max(0, (len(rec) - 16) // 2)
            offsets = struct.unpack_from(f">{count}H", rec, 16)
            for off in offsets:
                pos = 16 + off
                if pos + 2 > len(rec):
                    self.dictionary.append((b"", True))
                    continue
                blen = struct.unpack_from(">H", rec, pos)[0]
                slice_len = blen & 0x7FFF
                terminal = bool(blen & 0x8000)
                self.dictionary.append((rec[pos + 2:pos + 2 + slice_len], terminal))

    def unpack(self, data: bytes, depth: int = 0) -> bytes:
        if depth > MAX_HUFF_DEPTH:
            raise BookError("电子书 HUFF/CDIC 解压嵌套层数异常")
        total_bits = len(data) * 8
        padded = data + b"\x00" * 8
        bit_pos = 0
        out = bytearray()

        while bit_pos < total_bits:
            byte_idx = bit_pos >> 3
            shift = bit_pos & 7
            chunk = struct.unpack_from(">Q", padded, byte_idx)[0]
            val32 = (chunk >> (32 - shift)) & 0xFFFFFFFF

            codelen, term, maxcode = self.dict1[val32 >> 24]
            if not term:
                if codelen <= 0:
                    codelen = 1
                while codelen < 32 and val32 < self.mincode[codelen]:
                    codelen += 1
                maxcode = self.maxcode[codelen]
            if codelen <= 0 or bit_pos + codelen > total_bits:
                break
            bit_pos += codelen
            index = (maxcode - val32) >> (32 - codelen)
            if not (0 <= index < len(self.dictionary)):
                break
            entry_bytes, terminal = self.dictionary[index]
            if not terminal:
                entry_bytes = self.unpack(entry_bytes, depth + 1)
                self.dictionary[index] = (entry_bytes, True)
            out.extend(entry_bytes)
            if len(out) > MAX_UNCOMPRESSED_BYTES:
                raise BookError("电子书解压体积超出安全限制")
        return bytes(out)


def _strip_mobi_trailing(record: bytes, extra_data_flags: int) -> bytes:
    if not extra_data_flags or not record:
        return record
    end = len(record)
    flags = extra_data_flags >> 1
    while flags:
        if flags & 1:
            bitpos = 0
            size = 0
            pos = end
            while pos > 0 and bitpos < 28:
                pos -= 1
                v = record[pos]
                size |= (v & 0x7F) << bitpos
                bitpos += 7
                if v & 0x80:
                    break
            if size <= 0 or size > end:
                break
            end -= size
        flags >>= 1
    if (extra_data_flags & 1) and end > 0:
        overlap = (record[end - 1] & 0x03) + 1
        if overlap <= end:
            end -= overlap
    return record[:end]


def _parse_exth(header_rec: bytes, exth_offset: int) -> dict[int, list[bytes]]:
    result: dict[int, list[bytes]] = {}
    if exth_offset + 12 > len(header_rec) or header_rec[exth_offset:exth_offset + 4] != b"EXTH":
        return result
    _, record_count = struct.unpack_from(">II", header_rec, exth_offset + 4)
    pos = exth_offset + 12
    for _ in range(min(record_count, 512)):
        if pos + 8 > len(header_rec):
            break
        rec_type, rec_len = struct.unpack_from(">II", header_rec, pos)
        if rec_len < 8 or pos + rec_len > len(header_rec):
            break
        payload = header_rec[pos + 8:pos + rec_len]
        result.setdefault(rec_type, []).append(payload)
        pos += rec_len
    return result


def _read_mobi_section(
    records: list[bytes],
    base_index: int,
    fallback_title: str,
) -> tuple[bytes, dict[str, Any]]:
    rec0 = records[base_index]
    if len(rec0) < 16:
        raise BookError("电子书头部记录长度不足")

    compression, _, _text_len, text_record_count, _rec_size, encryption_type = struct.unpack_from(">HHIIHH", rec0, 0)
    if encryption_type != 0:
        raise BookError("该电子书受 Kindle/Mobipocket DRM 加密保护，无法直接读取正文")

    encoding_name = "utf-8"
    mobi_version = 0
    full_name = ""
    huff_offset = 0xFFFFFFFF
    huff_count = 0
    extra_data_flags = 0
    fdst_index = 0xFFFFFFFF
    fdst_count = 0
    exth: dict[int, list[bytes]] = {}

    if len(rec0) >= 24 and rec0[16:20] == b"MOBI":
        header_len = struct.unpack_from(">I", rec0, 20)[0]
        if len(rec0) >= 32:
            codepage = struct.unpack_from(">I", rec0, 28)[0]
            encoding_name = "utf-8" if codepage == 65001 else "cp1252" if codepage == 1252 else ""
        if len(rec0) >= 40:
            mobi_version = struct.unpack_from(">I", rec0, 36)[0]
        if len(rec0) >= 92:
            name_off, name_len = struct.unpack_from(">II", rec0, 84)
            if 0 < name_len < 4096 and name_off + name_len <= len(rec0):
                full_name = _decode_bytes(rec0[name_off:name_off + name_len], encoding_name).strip()
        if len(rec0) >= 120:
            huff_offset, huff_count = struct.unpack_from(">II", rec0, 112)
        if len(rec0) >= 132:
            exth_flags = struct.unpack_from(">I", rec0, 128)[0]
            if exth_flags & 0x40:
                exth = _parse_exth(rec0, 16 + header_len)
        if mobi_version >= 8 and len(rec0) >= 200:
            fdst_index, fdst_count = struct.unpack_from(">II", rec0, 192)
        if header_len >= 228 and len(rec0) >= 244:
            extra_data_flags = struct.unpack_from(">H", rec0, 242)[0]

    huff_decoder: _HuffCdicDecoder | None = None
    if compression == 17480:
        if huff_offset == 0xFFFFFFFF or huff_count < 2:
            raise BookError("电子书缺少 HUFF/CDIC 解压字典")
        huff_rec_idx = base_index + huff_offset
        if huff_rec_idx + huff_count > len(records):
            huff_rec_idx = huff_offset
        if huff_rec_idx + huff_count > len(records):
            raise BookError("电子书 HUFF/CDIC 记录索引越界")
        huff_decoder = _HuffCdicDecoder(
            records[huff_rec_idx],
            records[huff_rec_idx + 1:huff_rec_idx + huff_count],
        )
    elif compression not in {1, 2}:
        raise BookError(f"不支持的 MOBI/AZW3 压缩算法（编码 {compression}）")

    raw_chunks = bytearray()
    first_text = base_index + 1
    last_text = min(len(records), first_text + text_record_count)
    for idx in range(first_text, last_text):
        part = _strip_mobi_trailing(records[idx], extra_data_flags)
        if compression == 1:
            decoded = part
        elif compression == 2:
            decoded = _decompress_palmdoc(part)
        else:
            assert huff_decoder is not None
            decoded = huff_decoder.unpack(part)
        raw_chunks.extend(decoded)
        if len(raw_chunks) > MAX_UNCOMPRESSED_BYTES:
            raise BookError("电子书解压体积超出安全限制")

    raw_bytes = bytes(raw_chunks)

    # For KF8 (AZW3), slice flow 0 using the FDST flow table so CSS/SVG/JS flows are excluded.
    if mobi_version >= 8 and fdst_index not in {0, 0xFFFFFFFF} and fdst_count >= 1:
        fdst_pos = base_index + fdst_index
        if fdst_pos >= len(records):
            fdst_pos = fdst_index
        if 0 <= fdst_pos < len(records):
            fdst_rec = records[fdst_pos]
            if len(fdst_rec) >= 20 and fdst_rec[:4] == b"FDST":
                sec_start, num_flows = struct.unpack_from(">II", fdst_rec, 4)
                if num_flows >= 1 and sec_start + 8 <= len(fdst_rec):
                    flow0_start, flow0_end = struct.unpack_from(">II", fdst_rec, sec_start)
                    if 0 <= flow0_start < flow0_end <= len(raw_bytes):
                        raw_bytes = raw_bytes[flow0_start:flow0_end]

    title_bytes = (exth.get(503) or [b""])[0]
    title = _decode_bytes(title_bytes, encoding_name).strip() if title_bytes else ""
    title = title or full_name or fallback_title
    authors = [
        _decode_bytes(a, encoding_name).strip()
        for a in exth.get(100, [])
        if _decode_bytes(a, encoding_name).strip()
    ]
    lang_bytes = (exth.get(524) or [b""])[0]
    language = _decode_bytes(lang_bytes, encoding_name).strip()[:16] if lang_bytes else ""

    kf8_boundary = None
    if 121 in exth and len(exth[121][0]) == 4:
        boundary_val = struct.unpack_from(">I", exth[121][0], 0)[0]
        if 0 < boundary_val < len(records) and boundary_val != 0xFFFFFFFF:
            kf8_boundary = boundary_val

    return raw_bytes, {
        "title": title[:160],
        "author": " / ".join(dict.fromkeys(authors))[:160],
        "language": language,
        "encoding": encoding_name,
        "mobi_version": mobi_version,
        "kf8_boundary": kf8_boundary,
    }


def _extract_mobi(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if len(data) < 80:
        raise BookError("电子书文件过小或已损坏")
    if data[:8] == b"\xeaDRMION\xee" or data[:4] == b"CONT":
        raise BookError("该文件为 Kindle KFX 专有格式或受 DRM 保护，请先转换为 EPUB / AZW3 / TXT 后导入")
    if data.startswith(b"%PDF-"):
        return _extract_pdf_bytes(data, path.stem or path.name)

    palm_title = _decode_bytes(data[:32].split(b"\x00", 1)[0]).replace("_", " ").strip()
    num_records = struct.unpack_from(">H", data, 76)[0]
    if num_records < 2 or 78 + num_records * 8 > len(data):
        raise BookError("MOBI/AZW3 文件头无效或已损坏")

    offsets = [struct.unpack_from(">I", data, 78 + i * 8)[0] for i in range(num_records)]
    records: list[bytes] = []
    for i, start in enumerate(offsets):
        end = offsets[i + 1] if i + 1 < num_records else len(data)
        if start > len(data) or end < start:
            records.append(b"")
        else:
            records.append(data[start:min(end, len(data))])

    # Check Print Replica container (Kindle AZW4 wrapping a PDF).
    for probe_idx in (1, 2):
        if probe_idx < len(records) and records[probe_idx].startswith(b"%PDF-"):
            return _extract_pdf_bytes(records[probe_idx], palm_title or path.stem or path.name)

    raw_bytes, meta = _read_mobi_section(records, 0, palm_title or path.stem or path.name)

    # Dual-MOBI combo file: try the KF8 section (richer structure) and fall back to MOBI6 if needed.
    boundary = meta.get("kf8_boundary")
    if boundary is not None and boundary != 0 and meta.get("mobi_version", 0) < 8:
        kf8_base = boundary
        if kf8_base < len(records) and records[kf8_base] == b"BOUNDARY":
            kf8_base += 1
        if kf8_base < len(records):
            try:
                kf8_bytes, kf8_meta = _read_mobi_section(records, kf8_base, meta["title"])
                if kf8_bytes.strip():
                    raw_bytes = kf8_bytes
                    for key in ("title", "author", "language", "encoding", "mobi_version"):
                        if kf8_meta.get(key):
                            meta[key] = kf8_meta[key]
            except BookError:
                raise
            except Exception:
                pass

    if raw_bytes.startswith(b"%PDF-"):
        return _extract_pdf_bytes(raw_bytes, meta["title"] or path.stem or path.name)

    decoded = _decode_bytes(raw_bytes, meta.get("encoding") or "")
    # Strip Kindle-specific pseudo tags that don't carry prose.
    decoded = re.sub(r"</?mbp:[^>]*>", "\n", decoded, flags=re.IGNORECASE)
    decoded = re.sub(r"<guide\b[^>]*>.*?</guide>", "", decoded, flags=re.IGNORECASE | re.DOTALL)

    if "<" in decoded and ">" in decoded and re.search(r"<(?:p|div|h[1-6]|body|html|br)\b", decoded, re.IGNORECASE):
        paragraphs, _ = _html_to_paragraphs(decoded)
        paragraphs = _normalize_paragraphs(paragraphs)
        chapters = sum(1 for p in paragraphs if _CHAPTER_HEADING_RE.match(p))
    else:
        paragraphs, chapters = _split_plain_paragraphs(decoded)

    fmt = "AZW3" if meta.get("mobi_version", 0) >= 8 or path.suffix.lower() in {".azw3", ".kf8"} else book_format(path)
    return {
        "title": meta["title"] or path.stem or path.name,
        "author": meta["author"],
        "format": fmt,
        "language": meta["language"],
        "paragraphs": paragraphs,
        "chapters": max(1, chapters) if paragraphs else 0,
    }


def _extract_fb2(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    try:
        root = _parse_xml_safe(raw)
    except Exception as error:
        raise BookError("FB2 文件 XML 结构已损坏") from error

    title = ""
    authors: list[str] = []
    language = ""
    paragraphs: list[str] = []
    chapters = 0

    for elem in root.iter():
        lname = _local_name(elem.tag)
        if lname == "book-title" and not title:
            title = " ".join("".join(elem.itertext()).split()).strip()
        elif lname == "author":
            parts = []
            for child in elem:
                if _local_name(child.tag) in {"first-name", "middle-name", "last-name", "nickname"}:
                    val = " ".join((child.text or "").split()).strip()
                    if val:
                        parts.append(val)
            name = " ".join(parts).strip()
            if name and name not in authors:
                authors.append(name)
        elif lname == "lang" and not language:
            language = (elem.text or "").strip()[:16]

    def walk_fb2(node: ET.Element) -> None:
        nonlocal chapters
        for child in node:
            lname = _local_name(child.tag)
            if lname == "title":
                txt = " ".join("".join(child.itertext()).split()).strip()
                if txt:
                    chapters += 1
                    paragraphs.append(txt)
            elif lname in {"p", "v", "subtitle", "text-author"}:
                txt = " ".join("".join(child.itertext()).split()).strip()
                if txt:
                    paragraphs.append(txt)
            else:
                walk_fb2(child)

    for elem in root:
        if _local_name(elem.tag) != "body":
            continue
        if (elem.attrib.get("name") or "").lower() == "notes":
            continue
        walk_fb2(elem)

    paragraphs = _normalize_paragraphs(paragraphs)
    return {
        "title": (title or path.stem or path.name)[:160],
        "author": " / ".join(authors)[:160],
        "format": "FB2",
        "language": language,
        "paragraphs": paragraphs,
        "chapters": max(1, chapters) if paragraphs else 0,
    }


def _extract_docx(path: Path) -> dict[str, Any]:
    try:
        zf = zipfile.ZipFile(path, "r")
    except zipfile.BadZipFile as error:
        raise BookError("DOCX 文件已损坏或不是有效的 Word 文档") from error

    with zf:
        _check_zip_safety(zf)
        if "word/document.xml" not in zf.NameToInfo:
            raise BookError("DOCX 文档缺少正文内容（word/document.xml）")
        title = ""
        author = ""
        if "docProps/core.xml" in zf.NameToInfo:
            try:
                core = _parse_xml_safe(zf.read("docProps/core.xml"))
                for elem in core.iter():
                    lname = _local_name(elem.tag)
                    if lname == "title" and not title:
                        title = " ".join((elem.text or "").split()).strip()
                    elif lname == "creator" and not author:
                        author = " ".join((elem.text or "").split()).strip()
            except Exception:
                pass

        doc = _parse_xml_safe(zf.read("word/document.xml"))
        paragraphs: list[str] = []
        chapters = 0
        for elem in doc.iter():
            if _local_name(elem.tag) != "p":
                continue
            is_heading = False
            chunks: list[str] = []
            for sub in elem.iter():
                sname = _local_name(sub.tag)
                if sname == "pstyle":
                    val = next((v for k, v in sub.attrib.items() if _local_name(k) == "val"), "")
                    if "heading" in val.lower() or "标题" in val:
                        is_heading = True
                elif sname == "t" and sub.text:
                    chunks.append(sub.text)
                elif sname == "tab":
                    chunks.append(" ")
                elif sname in {"br", "cr"}:
                    chunks.append("\n")
            text = "".join(chunks).strip()
            if text:
                if is_heading:
                    chapters += 1
                for part in text.splitlines():
                    if part.strip():
                        paragraphs.append(part.strip())

        paragraphs = _normalize_paragraphs(paragraphs)
        return {
            "title": (title or path.stem or path.name)[:160],
            "author": author[:160],
            "format": "DOCX",
            "language": "",
            "paragraphs": paragraphs,
            "chapters": max(1, chapters) if paragraphs else 0,
        }


def _extract_pdf_bytes(raw: bytes, fallback_title: str) -> dict[str, Any]:
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise BookError("当前运行环境未安装 PDF 解析组件（pypdf）") from error

    try:
        reader = PdfReader(BytesIO(raw))
    except Exception as error:
        raise BookError("PDF 文件已损坏或无法读取") from error

    if reader.is_encrypted:
        try:
            unlocked = reader.decrypt("")
        except Exception:
            unlocked = 0
        if not unlocked:
            raise BookError("该 PDF 受密码加密保护，无法直接读取正文")

    meta = reader.metadata or {}
    title = str(meta.get("/Title") or "").strip() if hasattr(meta, "get") else ""
    author = str(meta.get("/Author") or "").strip() if hasattr(meta, "get") else ""

    page_blocks: list[str] = []
    for page in reader.pages:
        try:
            page_text = _clean_text(page.extract_text() or "")
        except Exception:
            continue
        if page_text.strip():
            page_blocks.append(page_text.strip())

    if not page_blocks:
        raise BookError("该 PDF 为扫描图片版（无文本层），暂不支持直接提取文字")

    joined = "\n\n".join(page_blocks)
    paragraphs, chapters = _split_plain_paragraphs(joined)
    if not paragraphs:
        raise BookError("该 PDF 未提取到有效正文内容")

    return {
        "title": (title or fallback_title)[:160],
        "author": author[:160],
        "format": "PDF",
        "language": "",
        "paragraphs": paragraphs,
        "chapters": max(len(reader.pages), chapters),
    }


def _extract_pdf(path: Path) -> dict[str, Any]:
    return _extract_pdf_bytes(path.read_bytes(), path.stem or path.name)


def extract_book(path: str | Path) -> dict[str, Any]:
    """Extract normalized title, author, format, and ordered paragraphs from a local book file."""
    file_path = Path(path)
    if not file_path.exists():
        raise BookError("找不到这个图书文件，请确认文件未被移动或删除")
    if not file_path.is_file():
        raise BookError("请选择图书文件，不能是文件夹")
    size = file_path.stat().st_size
    if size <= 0:
        raise BookError("图书文件为空，没有可读取的正文")
    if size > MAX_BOOK_FILE_BYTES:
        raise BookError("图书文件超过 250 MB 限制，暂不支持直接解析")

    suffix = file_path.suffix.lower()
    if suffix == ".kfx":
        raise BookError("Kindle KFX 专有格式暂不支持直接解析，请先转换为 EPUB / AZW3 / TXT 后导入")
    if suffix == ".txt":
        book = _extract_txt(file_path, markdown=False)
    elif suffix in {".md", ".markdown"}:
        book = _extract_txt(file_path, markdown=True)
    elif suffix in {".html", ".htm", ".xhtml"}:
        book = _extract_html_file(file_path)
    elif suffix == ".epub":
        book = _extract_epub(file_path)
    elif suffix in {".mobi", ".azw3", ".azw", ".kf8", ".prc"}:
        book = _extract_mobi(file_path)
    elif suffix == ".fb2":
        book = _extract_fb2(file_path)
    elif suffix == ".docx":
        book = _extract_docx(file_path)
    elif suffix == ".pdf":
        book = _extract_pdf(file_path)
    else:
        raise BookError(f"暂不支持的图书格式：{suffix or '未知'}")

    paragraphs = [p for p in (book.get("paragraphs") or []) if p and p.strip()]
    if not paragraphs:
        raise BookError("未能从该图书文件中提取到正文内容")

    char_count = sum(len(p) for p in paragraphs)
    excerpt = "\n\n".join(paragraphs[:12])[:4000]
    return {
        "title": (book.get("title") or file_path.stem or file_path.name).strip()[:160],
        "author": (book.get("author") or "").strip()[:160],
        "format": book.get("format") or book_format(file_path),
        "language": (book.get("language") or "").strip()[:16],
        "paragraphs": paragraphs,
        "excerpt": excerpt,
        "chapters": int(book.get("chapters") or 0),
        "char_count": char_count,
    }
