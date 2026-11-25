"""Tests for local book extraction (TXT/EPUB/MOBI/AZW3/FB2/DOCX/PDF), letter path parsing, and Notes E2E."""
from __future__ import annotations

import os
from pathlib import Path
import struct
import zipfile

import pytest

os.environ["MEDIA_DESKTOP"] = "1"

from app import desktop_routes, desktop_sources, knowledge, local_books, obsidian, share_text
from app import main as media
from app import note_engine
from app import note_pages
from app import workbench_inbox as inbox


def _build_epub(
    target: Path,
    *,
    title: str = "系统思考",
    author: str = "作者甲",
    chapters: list[tuple[str, str]] | None = None,
    drm: bool = False,
    font_obfuscation: bool = False,
) -> Path:
    chapters = chapters or [
        ("OEBPS/Text/Chapter%201.xhtml", "<html><body><h1>第一章 系统结构</h1><p>反馈回路决定系统行为。</p></body></html>"),
        ("OEBPS/Text/00_chapter2.xhtml", "<html><body><h2>第二章 杠杆点</h2><p><ruby>漢<rp>(</rp><rt>かん</rt><rp>)</rp>字</ruby>与规则调整最有效。</p></body></html>"),
    ]
    manifest_items = []
    spine_refs = []
    for idx, (member, _) in enumerate(chapters, 1):
        rel = member.removeprefix("OEBPS/")
        manifest_items.append(f'<item id="ch{idx}" href="{rel}" media-type="application/xhtml+xml"/>')
        spine_refs.append(f'<itemref idref="ch{idx}"/>')
    opf = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<dc:title>{title}</dc:title>"
        f"<dc:creator>{author}</dc:creator>"
        "<dc:language>zh-CN</dc:language>"
        "</metadata>"
        f"<manifest>{''.join(manifest_items)}</manifest>"
        f"<spine>{''.join(spine_refs)}</spine>"
        "</package>"
    )
    container = (
        '<?xml version="1.0"?>'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>'
        "</container>"
    )
    with zipfile.ZipFile(target, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("OEBPS/content.opf", opf)
        for member, html_body in chapters:
            # Store unquoted name inside zip to verify percent-decoded lookup too.
            zf.writestr(member.replace("%20", " "), html_body)
        if drm:
            zf.writestr(
                "META-INF/encryption.xml",
                '<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container" '
                'xmlns:enc="http://www.w3.org/2001/04/xmlenc#">'
                '<enc:EncryptedData><enc:EncryptionMethod Algorithm="http://www.w3.org/2001/04/xmlenc#aes128-cbc"/>'
                '<enc:CipherData><enc:CipherReference URI="OEBPS/Text/Chapter 1.xhtml"/></enc:CipherData>'
                "</enc:EncryptedData></encryption>",
            )
        elif font_obfuscation:
            zf.writestr(
                "META-INF/encryption.xml",
                '<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container" '
                'xmlns:enc="http://www.w3.org/2001/04/xmlenc#">'
                '<enc:EncryptedData><enc:EncryptionMethod Algorithm="http://www.idpf.org/2008/embedding"/>'
                '<enc:CipherData><enc:CipherReference URI="OEBPS/Fonts/body.otf"/></enc:CipherData>'
                "</enc:EncryptedData></encryption>",
            )
    return target


def _build_palmdb(name: bytes, records: list[bytes]) -> bytes:
    header = bytearray(78)
    header[:len(name[:31])] = name[:31]
    header[60:64] = b"BOOK"
    header[64:68] = b"MOBI"
    struct.pack_into(">H", header, 76, len(records))
    offset = 78 + len(records) * 8 + 2
    rec_table = bytearray()
    for idx, rec in enumerate(records):
        rec_table.extend(struct.pack(">IB3s", offset, 0, idx.to_bytes(3, "big")))
        offset += len(rec)
    return bytes(header) + bytes(rec_table) + b"\x00\x00" + b"".join(records)


def _build_mobi_record0(
    *,
    compression: int,
    text_len: int,
    text_records: int,
    encryption: int = 0,
    mobi_version: int = 6,
    title: str = "",
    author: str = "",
    huff_offset: int = 0xFFFFFFFF,
    huff_count: int = 0,
    extra_data_flags: int = 0,
    fdst_index: int = 0xFFFFFFFF,
    fdst_count: int = 0,
    kf8_boundary: int | None = None,
) -> bytes:
    header_len = 232
    rec0 = bytearray(16 + header_len)
    struct.pack_into(">HHIIHH", rec0, 0, compression, 0, text_len, text_records, 4096, encryption)
    rec0[16:20] = b"MOBI"
    struct.pack_into(">I", rec0, 20, header_len)
    struct.pack_into(">I", rec0, 24, 2)  # Mobipocket book
    struct.pack_into(">I", rec0, 28, 65001)  # UTF-8
    struct.pack_into(">I", rec0, 36, mobi_version)
    struct.pack_into(">II", rec0, 112, huff_offset, huff_count)
    if mobi_version >= 8:
        struct.pack_into(">II", rec0, 192, fdst_index, fdst_count)
    struct.pack_into(">H", rec0, 242, extra_data_flags)

    exth_entries: list[tuple[int, bytes]] = []
    if title:
        exth_entries.append((503, title.encode("utf-8")))
    if author:
        exth_entries.append((100, author.encode("utf-8")))
    if kf8_boundary is not None:
        exth_entries.append((121, struct.pack(">I", kf8_boundary)))

    if exth_entries:
        struct.pack_into(">I", rec0, 128, 0x40)
        exth_body = bytearray()
        for rtype, payload in exth_entries:
            exth_body.extend(struct.pack(">II", rtype, 8 + len(payload)))
            exth_body.extend(payload)
        exth_total = 12 + len(exth_body)
        pad = (-exth_total) % 4
        exth = b"EXTH" + struct.pack(">II", exth_total + pad, len(exth_entries)) + bytes(exth_body) + (b"\x00" * pad)
        rec0.extend(exth)
    return bytes(rec0)


def _palmdoc_compress_simple(raw: bytes) -> bytes:
    """Minimal valid PalmDOC LZ77 compressor exercising literal, space+char, and back-reference ops."""
    out = bytearray()
    i = 0
    n = len(raw)
    while i < n:
        if raw[i] == 0x20 and i + 1 < n and 0x40 <= raw[i + 1] <= 0x7F:
            out.append(raw[i + 1] ^ 0x80)
            i += 2
            continue
        # Search for a short back-reference match
        best_dist = 0
        best_len = 0
        window_start = max(0, i - 2000)
        if i + 3 <= n:
            needle = raw[i:i + 3]
            pos = raw.find(needle, window_start, i)
            if pos != -1:
                dist = i - pos
                length = 3
                while length < 10 and i + length < n and raw[pos + length] == raw[i + length]:
                    length += 1
                best_dist, best_len = dist, length
        if best_len >= 3:
            pair = 0x8000 | (best_dist << 3) | (best_len - 3)
            out.append((pair >> 8) & 0xFF)
            out.append(pair & 0xFF)
            i += best_len
        elif 0x09 <= raw[i] <= 0x7F:
            out.append(raw[i])
            i += 1
        else:
            chunk = raw[i:i + 8]
            out.append(len(chunk))
            out.extend(chunk)
            i += len(chunk)
    return bytes(out)


def _build_huff_cdic_fixture(phrases: list[tuple[bytes, bool]]) -> tuple[bytes, bytes, bytes]:
    """Construct a valid 2-bit-code HUFF/CDIC table (up to 4 entries) + encoded bitstream for all entries."""
    # Fixed 2-bit codes for indices 0..3: code c in 0..3 maps to r = maxcode - c = 3 - c.
    # For 8-bit prefix x, top 2 bits = x >> 6, so term=1, codelen=2, v>>8 = 3 -> r = 3 - (x >> 6).
    dict1 = [((3 << 8) | 0x80 | 2) for _ in range(256)]
    dict2 = [0] * 64
    huff = (
        b"HUFF"
        + struct.pack(">IIIII", 24, 24, 24 + 256 * 4, 24, 24 + 256 * 4)
        + struct.pack(">256I", *dict1)
        + struct.pack(">64I", *dict2)
    )

    # CDIC: 4 phrases, bits=2
    data_area = bytearray()
    offsets = []
    table_size = len(phrases) * 2
    for content, terminal in phrases:
        offsets.append(table_size + len(data_area))
        flag = 0x8000 if terminal else 0x0000
        data_area.extend(struct.pack(">H", flag | len(content)))
        data_area.extend(content)
    cdic = b"CDIC" + struct.pack(">III", 16, len(phrases), 2) + struct.pack(f">{len(offsets)}H", *offsets) + bytes(data_area)

    # Emit sequence of indices: [3, 2] -> codes (3-3)=0 (00), (3-2)=1 (01) -> 4 bits?
    # Let's emit [3, 2, 1, 0] -> codes 00, 01, 10, 11 -> single byte 0b00011011 = 0x1B!
    encoded = bytes([0b00011011])
    return huff, cdic, encoded


def test_txt_encodings_and_paragraph_normalization(tmp_path):
    # GB18030 Chinese TXT
    gb = tmp_path / "红楼测试.txt"
    gb.write_bytes("第一回 甄士隐梦幻识通灵\r\n满纸荒唐言，一把辛酸泪。\r\n都云作者痴，谁解其中味。\r\n".encode("gb18030"))
    book_gb = local_books.extract_book(gb)
    assert book_gb["format"] == "TXT"
    assert book_gb["title"] == "红楼测试"
    assert book_gb["paragraphs"][0].startswith("第一回")
    assert any("满纸荒唐言" in p for p in book_gb["paragraphs"])

    # UTF-16 LE TXT
    u16 = tmp_path / "utf16.txt"
    u16.write_bytes("第一章 序幕\n这是 UTF-16 编码的图书正文。".encode("utf-16"))
    book_u16 = local_books.extract_book(u16)
    assert "UTF-16 编码" in " ".join(book_u16["paragraphs"])

    # Hard-wrapped English TXT (Project Gutenberg style)
    en = tmp_path / "gutenberg.txt"
    en.write_text(
        "Chapter 1\n\n"
        "This is a long sentence that was hard-\nwrapped across multiple short\nlines for old terminals.\n\n"
        "Second paragraph stays distinct\nwhile joining its own wrapped lines.\n",
        encoding="utf-8",
    )
    book_en = local_books.extract_book(en)
    assert book_en["paragraphs"][0] == "Chapter 1"
    assert "hardwrapped across multiple short lines" in book_en["paragraphs"][1]
    assert len(book_en["paragraphs"]) == 3

    # Long unbroken paragraph softly splits at sentence boundary
    long_txt = tmp_path / "long.txt"
    long_txt.write_text("这是一句用于测试切分长度的中文句子。" * 220, encoding="utf-8")
    book_long = local_books.extract_book(long_txt)
    assert len(book_long["paragraphs"]) >= 2
    assert all(len(p) <= local_books.MAX_PARAGRAPH_CHARS for p in book_long["paragraphs"])


def test_markdown_html_fb2_docx_and_pdf(tmp_path):
    md = tmp_path / "guide.md"
    md.write_text("# 原则笔记\n\n---\n\n第一条：极度求真与透明。\n\n- 保留反例\n", encoding="utf-8")
    b_md = local_books.extract_book(md)
    assert b_md["title"] == "原则笔记" and b_md["format"] == "Markdown"
    assert any("极度求真" in p for p in b_md["paragraphs"])

    html = tmp_path / "article.html"
    html.write_text(
        "<html><head><title>网页长文</title><style>body{color:red}</style></head>"
        "<body><script>evil()</script><h1>小节标题</h1>"
        "<p><ruby>東京<rp>(</rp><rt>とうきょう</rt><rp>)</rp></ruby>之旅。</p></body></html>",
        encoding="utf-8",
    )
    b_html = local_books.extract_book(html)
    assert b_html["title"] == "网页长文"
    assert "evil" not in " ".join(b_html["paragraphs"])
    assert "とうきょう" not in " ".join(b_html["paragraphs"])
    assert any("東京之旅" in p for p in b_html["paragraphs"])

    fb2 = tmp_path / "sample.fb2"
    fb2.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">'
        "<description><title-info><book-title>战争与和平</book-title>"
        "<author><first-name>列夫</first-name><last-name>托尔斯泰</last-name></author>"
        "</title-info></description>"
        "<body><section><title><p>第一卷</p></title><p>彼得堡沙龙夜谈。</p></section></body>"
        '<body name="notes"><section><p>脚注不应混入正文</p></section></body>'
        "</FictionBook>",
        encoding="utf-8",
    )
    b_fb2 = local_books.extract_book(fb2)
    assert b_fb2["title"] == "战争与和平" and b_fb2["author"] == "列夫 托尔斯泰"
    assert b_fb2["paragraphs"] == ["第一卷", "彼得堡沙龙夜谈。"]

    docx = tmp_path / "draft.docx"
    with zipfile.ZipFile(docx, "w") as zf:
        zf.writestr(
            "docProps/core.xml",
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">'
            "<dc:title>手稿标题</dc:title><dc:creator>作者乙</dc:creator></cp:coreProperties>",
        )
        zf.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
            "<w:p><w:pPr><w:pStyle w:val=\"Heading1\"/></w:pPr><w:r><w:t>第一章 引言</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>这是 Word 正文段落。</w:t></w:r></w:p>"
            "</w:body></w:document>",
        )
    b_docx = local_books.extract_book(docx)
    assert b_docx["title"] == "手稿标题" and b_docx["author"] == "作者乙"
    assert b_docx["paragraphs"] == ["第一章 引言", "这是 Word 正文段落。"]

    # Text-layer PDF, scanned blank PDF, and password-encrypted PDF
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    text_pdf = tmp_path / "paper.pdf"
    writer = PdfWriter()
    page = writer.add_blank_page(width=400, height=400)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})
    })
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 50 300 Td (Systems thinking improves decisions.) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.add_metadata({"/Title": "Systems Paper", "/Author": "Dr. Lin"})
    with text_pdf.open("wb") as fh:
        writer.write(fh)
    b_pdf = local_books.extract_book(text_pdf)
    assert b_pdf["title"] == "Systems Paper" and b_pdf["author"] == "Dr. Lin"
    assert any("Systems thinking improves decisions." in p for p in b_pdf["paragraphs"])

    blank_pdf = tmp_path / "scanned.pdf"
    w2 = PdfWriter()
    w2.add_blank_page(width=200, height=200)
    with blank_pdf.open("wb") as fh:
        w2.write(fh)
    with pytest.raises(local_books.BookError, match="扫描图片版"):
        local_books.extract_book(blank_pdf)

    enc_pdf = tmp_path / "locked.pdf"
    writer.encrypt("secret123")
    with enc_pdf.open("wb") as fh:
        writer.write(fh)
    with pytest.raises(local_books.BookError, match="密码加密"):
        local_books.extract_book(enc_pdf)


def test_epub_spine_order_font_obfuscation_and_drm_guard(tmp_path):
    clean = _build_epub(tmp_path / "clean.epub", font_obfuscation=True)
    book = local_books.extract_book(clean)
    assert book["title"] == "系统思考" and book["author"] == "作者甲" and book["format"] == "EPUB"
    # Verify OPF spine order (Chapter 1 precedes 00_chapter2) and ruby stripping
    assert book["paragraphs"][0] == "第一章 系统结构"
    assert book["paragraphs"][1] == "反馈回路决定系统行为。"
    assert "かん" not in " ".join(book["paragraphs"])
    assert any("漢字与规则调整最有效" in p for p in book["paragraphs"])

    drm = _build_epub(tmp_path / "locked.epub", drm=True)
    with pytest.raises(local_books.BookError, match="DRM"):
        local_books.extract_book(drm)


def test_mobi_palmdoc_huffcdic_kf8_fdst_combo_and_drm(tmp_path):
    # 1. PalmDOC LZ77 compressed MOBI6 + trailing overlap byte
    html_bytes = "<html><body><h1>第一章</h1><p>Repeat phrase Repeat phrase in PalmDOC book.</p></body></html>".encode("utf-8")
    compressed = _palmdoc_compress_simple(html_bytes) + b"\x00"  # extra_data_flags=1 -> 1 trailing byte ((0 & 3) + 1 = 1)
    rec0 = _build_mobi_record0(
        compression=2, text_len=len(html_bytes), text_records=1,
        title="掌中图书", author="作者丙", extra_data_flags=1,
    )
    mobi_path = tmp_path / "lz77.mobi"
    mobi_path.write_bytes(_build_palmdb(b"lz77", [rec0, compressed]))
    b_lz = local_books.extract_book(mobi_path)
    assert b_lz["title"] == "掌中图书" and b_lz["author"] == "作者丙" and b_lz["format"] == "MOBI"
    assert any("Repeat phrase Repeat phrase" in p for p in b_lz["paragraphs"])

    # 2. HUFF/CDIC compressed MOBI (including a recursive non-terminal dictionary entry!)
    # 2-bit codes: 00->idx3, 01->idx2, 10->idx1, 11->idx0.
    # idx0 is non-terminal containing 1 byte 0b01011010 -> emits idx2, idx2, idx1, idx1!
    huff, cdic, encoded = _build_huff_cdic_fixture([
        (bytes([0b01011010]), False),
        (b"!</p><p>", True),
        (b"CDIC", True),
        (b"<p>Huff ", True),
    ])
    rec0_h = _build_mobi_record0(
        compression=17480, text_len=64, text_records=1,
        title="哈夫曼书", huff_offset=2, huff_count=2,
    )
    huff_path = tmp_path / "huff.mobi"
    huff_path.write_bytes(_build_palmdb(b"huff", [rec0_h, encoded, huff, cdic]))
    b_huff = local_books.extract_book(huff_path)
    assert b_huff["title"] == "哈夫曼书"
    assert b_huff["paragraphs"] == ["Huff CDIC!", "CDICCDIC!", "!"]

    # 3. KF8 / AZW3 with FDST isolating flow 0 (HTML) from flow 1 (CSS)
    flow0 = "<html><body><h1>AZW3 标题</h1><p>只有正文流应当被提取。</p></body></html>".encode("utf-8")
    flow1 = b"body { font-size: 16px; } .secret-css-noise { display: none; }"
    combined = flow0 + flow1
    fdst = b"FDST" + struct.pack(">II", 12, 2) + struct.pack(">IIII", 0, len(flow0), len(flow0), len(combined))
    rec0_kf8 = _build_mobi_record0(
        compression=1, text_len=len(combined), text_records=1,
        mobi_version=8, title="现代电子书", author="作者丁", fdst_index=2, fdst_count=2,
    )
    azw3_path = tmp_path / "modern.azw3"
    azw3_path.write_bytes(_build_palmdb(b"modern", [rec0_kf8, combined, fdst]))
    b_azw3 = local_books.extract_book(azw3_path)
    assert b_azw3["format"] == "AZW3" and b_azw3["title"] == "现代电子书"
    assert "secret-css-noise" not in " ".join(b_azw3["paragraphs"])
    assert b_azw3["paragraphs"] == ["AZW3 标题", "只有正文流应当被提取。"]

    # 4. Dual-MOBI Combo (MOBI6 header with EXTH 121 -> BOUNDARY -> KF8 section)
    m6_body = b"<html><body><p>Old MOBI6 fallback text</p></body></html>"
    rec0_m6 = _build_mobi_record0(
        compression=1, text_len=len(m6_body), text_records=1,
        mobi_version=6, title="旧版标题", kf8_boundary=2,
    )
    rec0_combo_kf8 = _build_mobi_record0(
        compression=1, text_len=len(flow0), text_records=1,
        mobi_version=8, title="新版 KF8 标题", author="双格式作者",
    )
    combo_path = tmp_path / "combo.azw"
    combo_path.write_bytes(_build_palmdb(b"combo", [rec0_m6, m6_body, b"BOUNDARY", rec0_combo_kf8, flow0]))
    b_combo = local_books.extract_book(combo_path)
    assert b_combo["title"] == "新版 KF8 标题" and b_combo["author"] == "双格式作者"
    assert "只有正文流应当被提取" in " ".join(b_combo["paragraphs"])

    # 5. DRM-encrypted MOBI and KFX rejection
    drm_rec0 = _build_mobi_record0(compression=1, text_len=10, text_records=1, encryption=2)
    drm_mobi = tmp_path / "drm.azw3"
    drm_mobi.write_bytes(_build_palmdb(b"drm", [drm_rec0, b"encrypted!"]))
    with pytest.raises(local_books.BookError, match="DRM"):
        local_books.extract_book(drm_mobi)

    kfx = tmp_path / "kindle.kfx"
    kfx.write_bytes(b"\xeaDRMION\xee" + b"\x00" * 100)
    with pytest.raises(local_books.BookError, match="KFX"):
        local_books.extract_book(kfx)


@pytest.mark.skipif(os.name != "nt", reason="Windows local path classification tests")
def test_letter_path_classification_and_normalization_edge_cases(tmp_path):
    # Apostrophe inside double quotes, smart quotes, invisible LTR mark, file:// with Chinese & spaces
    apos = share_text.classify_letters('"D:\\Books\\O\'Reilly - DDIA.epub"')
    assert len(apos) == 1 and apos[0]["local"] is True and apos[0]["source"].endswith("O'Reilly - DDIA.epub")

    smart = share_text.classify_letters("“D:\\Books\\三体.azw3”")
    assert len(smart) == 1 and smart[0]["local"] is True and smart[0]["source"].endswith("三体.azw3")

    bidi = share_text.classify_letters("\u202aD:\\Books\\原则.mobi")
    assert len(bidi) == 1 and bidi[0]["local"] is True and bidi[0]["source"].endswith("原则.mobi")

    spaced_file_url = share_text.classify_letters("file:///D:/My Books/测试 书籍.txt")
    assert len(spaced_file_url) == 1 and spaced_file_url[0]["local"] is True
    assert "My Books" in spaced_file_url[0]["source"]

    # Verify normalize_local_source_path resolves real files with quotes, LTR mark, and percent-encoded file:// URL
    real_book = tmp_path / "O'Reilly 测试 图书.epub"
    _build_epub(real_book)
    from urllib.parse import quote
    file_uri = "file:///" + quote(str(real_book).replace("\\", "/"), safe=":/")
    assert media.normalize_local_source_path(f'"{real_book}"') == real_book
    assert media.normalize_local_source_path(f"\u202a{real_book}") == real_book
    assert media.normalize_local_source_path(file_uri) == real_book


@pytest.mark.skipif(os.name != "nt", reason="Windows inbox local book end-to-end test")
def test_notes_lane_end_to_end_local_book_and_publish_rejection(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "DATA_DIR", tmp_path)
    monkeypatch.setattr(media, "JOBS_DIR", tmp_path / "jobs")
    media.JOBS_DIR.mkdir()
    monkeypatch.setattr(media, "BATCHES_DIR", tmp_path / "batches")
    media.BATCHES_DIR.mkdir()
    monkeypatch.setattr(inbox.desktop_config, "settings", lambda: {})
    knowledge.initialize()
    inbox.initialize()
    monkeypatch.setattr(inbox.POOL, "submit", lambda fn, *a: fn(*a))

    epub_file = _build_epub(tmp_path / "thinking.epub", title="系统之美", author="梅多斯")
    txt_file = tmp_path / "notes.txt"
    txt_file.write_text("第一章 开篇\n系统思考的核心是看见整体结构。\n", encoding="utf-8")

    # 1. Publish lane rejects book files cleanly without invoking ffprobe
    monkeypatch.setattr(desktop_sources, "inspect_file", lambda *a, **kw: pytest.fail("ffprobe should not run on books"))
    pub_gid = inbox.deliver(inbox.Delivery(
        request_id="pub-book-reject",
        lane="publish",
        entries=[{"id": "1", "text": f'"{epub_file}"'}, {"id": "2", "text": str(txt_file)}],
    ))["group_id"]
    pub_entries = inbox.get_delivery(pub_gid)["entries"]
    assert all(e["status"] == "rejected" and "笔记信箱" in e["message"] for e in pub_entries)

    # 2. Notes lane accepts local book without eagerly extracting it
    extract_calls = []
    real_extract = local_books.extract_book

    def spy_extract(path):
        extract_calls.append(Path(path))
        return real_extract(path)

    monkeypatch.setattr(local_books, "extract_book", spy_extract)
    notes_gid = inbox.deliver(inbox.Delivery(
        request_id="notes-book-e2e",
        lane="notes",
        entries=[{"id": "b1", "text": f"\u202a\"{epub_file}\""}],
    ))["group_id"]
    entry = inbox.get_delivery(notes_gid)["entries"][0]
    assert entry["status"] == "ready"
    assert entry["probe"]["media_type"] == "book"
    assert entry["platform"] == "本地图书 · EPUB"
    assert extract_calls == []

    # 3. Start notes with mocked DeepSeek -> full E2E through note_engine + Markdown + Obsidian
    monkeypatch.setattr(media, "TRANSLATE_API_KEY", "fixture-key")

    def fake_ask(self, operation, instruction, payload):
        if operation == "read":
            return {
                "topic": "系统结构与杠杆点",
                "capsule": "系统行为由反馈回路和规则决定，调整规则是高杠杆点。",
                "key_points": ["反馈回路主导行为", "规则调整最有效"],
                "overflow": False,
                "cards": [{
                    "kind": "judgment",
                    "topic": "系统思考",
                    "claim": "调整系统规则比微调参数更具杠杆效应",
                    "importance": 3,
                    "specificity": 3,
                    "evidence": "反馈回路决定系统行为",
                    "example": "杠杆点优先级排序",
                    "refs": [payload[0]["id"]],
                }],
            }
        if operation == "merge":
            return {"title": "系统之美总览", "capsule": "全书总览。", "highlights": ["整体结构"]}
        if operation == "merge_candidates":
            cands = payload["candidates"]
            return {"capsule": "归约概述", "keep": [{"primary": c["id"], "merged_from": [], "kind": "judgment", "topic": c["topic"], "claim": c["claim"], "evidence": c["evidence"]} for c in cands[:4]]}
        if operation == "dedup":
            return {"duplicates": []}
        raise AssertionError(operation)

    monkeypatch.setattr(note_engine.Engine, "ask", fake_ask)
    inbox.start_group(notes_gid, inbox.Start(entry_ids=[entry["id"]], revision=0, confirmed=True, notes_mode="comprehensive"))

    done = inbox.get_delivery(notes_gid)["entries"][0]
    assert done["status"] == "succeeded", done
    assert done["title"] == "系统之美" and done["author"] == "梅多斯"
    assert len(extract_calls) == 1
    tid = done["result"]["transcript_id"]
    assert not done["result"].get("english_srt_url")
    assert done["task"]["stage_details"]["download"]["status"] == "succeeded"

    doc = knowledge.read_transcript(tid)
    assert doc["source_kind"] == "book" and doc["media_type"] == "note" and doc["reference_kind"] == "paragraph"
    assert len(doc["cards"]) >= 1

    # 4. Restart / switch mode reuses already-imported transcript without re-parsing file
    inbox.start_group(notes_gid, inbox.Start(
        entry_ids=[entry["id"]], revision=0, confirmed=True,
        notes_mode="summary", restart=True, entry_revision=done["revision"],
    ))
    assert len(extract_calls) == 1

    # 5. Markdown export uses paragraph citations (no 00:00:00 timestamps)
    md_out = tmp_path / "book_notes.md"
    note_pages.markdown_to(tid, md_out, view_mode="comprehensive")
    md_text = md_out.read_text(encoding="utf-8")
    assert "第 1 段" in md_text and "00:00:00" not in md_text

    # 6. Dual Obsidian Vault publish tags platform as 本地图书
    vp_vault = tmp_path / "vp_vault"
    sum_vault = tmp_path / "sum_vault"
    (vp_vault / ".obsidian").mkdir(parents=True)
    (sum_vault / ".obsidian").mkdir(parents=True)
    vp_res = obsidian.publish(vp_vault, tid, [doc["cards"][0]["id"]])[0]
    assert vp_res["status"] == "published"
    src_note = next((vp_vault / "Media Operator" / "素材").glob("*.md")).read_text(encoding="utf-8")
    assert 'source_platform: "本地图书"' in src_note and "media-operator/source/本地图书" in src_note
    sum_res = obsidian.publish_summary(sum_vault, tid)
    assert sum_res["status"] == "published"

    # 7. Direct /desktop/knowledge/import supports local books too
    direct = desktop_routes.import_source(desktop_routes.ImportRequest(
        kind="local", source=str(txt_file), rights_confirmed=True,
    ))
    assert direct["transcript_id"] > 0
