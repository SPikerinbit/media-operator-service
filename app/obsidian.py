"""One-way publication of multi-level summaries and viewpoint cards into Obsidian vaults."""
import hashlib
import html
import json
import os
from pathlib import Path, PureWindowsPath
import re
import tempfile
import threading
import time
from urllib.parse import parse_qs, quote, urlsplit

from app import knowledge

FOLDER = "Media Operator"
LOCK = threading.Lock()
ID_PATTERN = re.compile(r"[a-f0-9]{64}")

KIND_META = {
    "judgment": ("important", "核心判断"),
    "statement": ("note", "核心陈述"),
    "fact": ("info", "启发性事实"),
    "story": ("example", "典故 / 故事"),
    "method": ("tip", "方法 / 框架"),
}
TIER_LABELS = {
    "curated": "核心观点",
    "comprehensive": "大多数观点",
    "manual": "手动笔记",
}


def vault_root(value):
    path = Path(value)
    if not path.is_absolute() or not path.is_dir() or not (path / ".obsidian").is_dir():
        raise ValueError("请选择已有的 Obsidian Vault 根目录（包含 .obsidian 文件夹）")
    return path.resolve(strict=True)


def _inside(vault, relative):
    path = vault / relative
    if not path.resolve().is_relative_to(vault):
        raise ValueError("发布目录指向了 Vault 之外")
    return path


def _digest(*values):
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode("utf-8")).hexdigest()


def _plain(value):
    return re.sub(r"([\\\x60*_{}\[\]<>|#!~])", r"\\\1", html.escape(value or "", quote=False))


def _heading(value):
    return _plain(" ".join((value or "").split()))


def _table_cell(value, limit=80):
    compact = " ".join((value or "").split())
    if len(compact) > limit:
        compact = compact[:limit - 1].rstrip() + "…"
    return _plain(compact).replace("|", "\\|")


def _tag_slug(value):
    clean = re.sub(r"[^\w\u3400-\u9fff-]+", "-", (value or "").strip().lower()).strip("-")
    return clean[:28]


def _mermaid_label(value, limit=24):
    clean = re.sub(r'["\'`\[\](){}<>;|#\r\n]+', " ", value or "")
    clean = " ".join(clean.split())
    if len(clean) > limit:
        clean = clean[:limit - 1].rstrip() + "…"
    return clean or "节点"


def _prefix(text, depth=1):
    lead = "> " * depth
    blank = ("> " * depth).rstrip()
    return "\n".join((lead + line) if line else blank for line in text.splitlines())


def _callout(kind, title, body, *, fold=None, depth=1):
    marker = fold if fold in {"+", "-"} else ""
    lead = "> " * depth
    header = f"{lead}[!{kind}]{marker} {title}".rstrip()
    if not body:
        return header + "\n"
    return header + "\n" + _prefix(body.rstrip("\n"), depth) + "\n"


def _youtube_url(doc):
    if doc["source_kind"] != "youtube":
        return ""
    parts = urlsplit(doc["source"])
    if parts.hostname == "youtu.be":
        video_id = parts.path.strip("/").split("/")[0]
    elif parts.hostname in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
        video_id = parse_qs(parts.query).get("v", [""])[0]
        if not video_id and parts.path.startswith(("/shorts/", "/live/", "/embed/")):
            video_id = parts.path.split("/")[2]
    else:
        return ""
    if re.fullmatch(r"[a-zA-Z0-9_-]{11}", video_id):
        return f"https://www.youtube.com/watch?v={video_id}"
    return ""


def _bilibili_url(doc):
    if doc["source_kind"] != "bilibili":
        return ""
    parts = urlsplit(doc["source"])
    if parts.hostname in {"bilibili.com", "www.bilibili.com", "m.bilibili.com"}:
        video = re.fullmatch(r"/video/(BV[0-9A-Za-z]+|av[0-9]+)/?", parts.path)
        if video:
            page = parse_qs(parts.query).get("p", ["1"])[0]
            if not re.fullmatch(r"[1-9][0-9]{0,5}", page):
                page = "1"
            return f"https://www.bilibili.com/video/{video[1]}/?p={page}"
    if parts.hostname == "b23.tv" and re.fullmatch(r"/[0-9A-Za-z]+/?", parts.path):
        return "https://b23.tv" + parts.path
    return ""


def _source_url(doc):
    youtube = _youtube_url(doc)
    if youtube:
        return youtube
    bilibili = _bilibili_url(doc)
    if bilibili:
        return bilibili
    if doc["source_kind"] == "url" and urlsplit(doc["source"]).scheme in {"http", "https"}:
        return quote(doc["source"], safe=":/?&=%#@+;")
    return ""


def _platform_label(doc):
    kind = doc.get("source_kind") or ""
    if kind == "youtube":
        return "YouTube"
    if kind == "bilibili":
        return "B 站"
    if kind == "subtitle":
        return "字幕文件"
    if kind == "book":
        return "本地图书"
    if kind == "local":
        return "本地媒体"
    host = (urlsplit(doc.get("source") or "").hostname or "").lower()
    if "weread.qq.com" in host:
        return "微信读书"
    if "xiaohongshu.com" in host or "xhslink.com" in host:
        return "小红书"
    if "douyin.com" in host:
        return "抖音"
    return "在线素材"


def _created_date(doc):
    raw = str(doc.get("created_at") or "").strip()
    match = re.match(r"(\d{4}-\d{2}-\d{2})", raw)
    return match.group(1) if match else time.strftime("%Y-%m-%d")


def _deep_link(doc, start_ms, label):
    if start_ms is None or doc.get("reference_kind") == "paragraph":
        return label
    sec = max(0, int(start_ms) // 1000)
    youtube = _youtube_url(doc)
    if youtube:
        return f"[{label}]({youtube}&t={sec}s)"
    bilibili = _bilibili_url(doc)
    if bilibili.startswith("https://www.bilibili.com/"):
        return f"[{label}]({bilibili}&t={sec})"
    return label


def _metadata(note_id, title, kind, snapshot, *, extra=None, tags=None):
    lines = [
        "---",
        f"media_operator_id: {json.dumps(note_id)}",
        f"media_operator_snapshot: {json.dumps(snapshot)}",
        f"media_operator_type: {kind}",
        f"title: {json.dumps(title, ensure_ascii=False)}",
    ]
    for key, value in (extra or {}).items():
        if value is None or value == "":
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            lines.append(f"{key}: {value}")
        else:
            lines.append(f"{key}: {json.dumps(str(value), ensure_ascii=False)}")
    all_tags = [f"media-operator/{kind}"]
    for tag in (tags or []):
        if tag and tag not in all_tags:
            all_tags.append(tag)
    lines.append("tags:")
    for tag in all_tags:
        lines.append(f"  - {tag}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def _source_text(doc, source_id, *, vault_role="viewpoint"):
    youtube = _youtube_url(doc)
    bilibili = _bilibili_url(doc)
    online = doc["source"] if doc["source_kind"] == "url" and urlsplit(doc["source"]).scheme in {"http", "https"} else ""
    source = (
        f"[YouTube]({youtube})" if youtube
        else f"[B 站]({bilibili})" if bilibili
        else f"[原始素材]({quote(online, safe=':/?&=%#@+;')})" if online
        else _heading(PureWindowsPath(doc["source"]).name)
    )
    platform = _platform_label(doc)
    url = _source_url(doc)
    role_hint = "在 Obsidian 的反向链接中查看这份素材的多层级摘要笔记。" if vault_role == "summary" else "在 Obsidian 的反向链接中查看这份素材的观点笔记。"
    meta = _metadata(
        source_id,
        doc["title"],
        "source",
        source_id,
        extra={
            "source_platform": platform,
            "source_url": url,
            "vault_role": vault_role,
            "created": _created_date(doc),
        },
        tags=[f"media-operator/source/{_tag_slug(platform)}"] if _tag_slug(platform) else [],
    )
    archive_body = f"- **来源**：{source}\n- **平台**：{_plain(platform)}\n- **收录日期**：{_created_date(doc)}"
    return (
        meta
        + f"# {_heading(doc['title'])}\n\n"
        + _callout("info", "素材档案", archive_body, fold="+")
        + "\n"
        + role_hint
        + "\n"
    )


def _card_text(doc, card, note_id, snapshot, source_path):
    source = source_path.with_suffix("").as_posix()
    source_link = quote(source, safe="/")
    youtube = _youtube_url(doc)
    bilibili = _bilibili_url(doc)
    raw_kind = (card.get("kind") or "").strip()
    callout_type, kind_label = KIND_META.get(raw_kind, ("note", "核心陈述"))
    tier = (card.get("mode") or "").strip() or ("manual" if not card.get("note_run") else "")
    tier_label = TIER_LABELS.get(tier, "")
    topic = (card.get("topic") or "").strip()
    platform = _platform_label(doc)

    tags = []
    if raw_kind and raw_kind in KIND_META:
        tags.append(f"media-operator/kind/{raw_kind}")
    if tier in TIER_LABELS:
        tags.append(f"media-operator/tier/{tier}")
    topic_slug = _tag_slug(topic)
    if topic_slug:
        tags.append(f"media-operator/topic/{topic_slug}")

    meta = _metadata(
        note_id,
        card["claim"],
        "viewpoint",
        snapshot,
        extra={
            "media_operator_kind": raw_kind or "statement",
            "media_operator_tier": tier,
            "topic": topic,
            "source_title": doc["title"],
            "source_platform": platform,
            "created": _created_date(doc),
        },
        tags=tags,
    )
    callout_title = f"{kind_label} · {_heading(topic)}" if topic else kind_label
    meta_bits = [f"素材：[来源笔记]({source_link})"]
    if tier_label:
        meta_bits.append(f"档位：{tier_label}")
    if topic:
        meta_bits.append(f"主题：{_plain(topic)}")

    sections = [
        meta,
        f"# {_heading(card['claim'])}\n\n",
        " · ".join(meta_bits) + "\n\n",
        _callout(callout_type, callout_title, _plain(card["claim"]), fold="+"),
        "\n",
    ]
    if card.get("quote_translation"):
        sections.append("## 中文译句\n\n")
        sections.append(_callout("quote", "中文译句", _plain(card["quote_translation"]), fold="+"))
        sections.append("\n")
    for label, key in (("论据", "evidence"), ("例子", "example")):
        if (card.get(key) or "").strip():
            sections.append(f"## {label}\n\n{_plain(card[key])}\n\n")
    sections.append("## 原话与位置\n\n")
    yield "".join(sections)

    from app.note_pages import references, source_page
    after = 0
    quote_idx = 0
    while True:
        page = references(doc["id"], card["id"], after)
        for ref in page["items"]:
            quote_idx += 1
            stamp = f"{knowledge.clock(ref['start_ms'])}–{knowledge.clock(ref['end_ms'])}"
            if doc.get("reference_kind") == "paragraph":
                stamp = f"第 {ref['cue']} 段 · {ref['lo']}–{ref['hi']}"
            elif youtube:
                stamp = f"[{stamp}]({youtube}&t={ref['start_ms'] // 1000}s)"
            elif bilibili.startswith("https://www.bilibili.com/"):
                stamp = f"[{stamp}]({bilibili}&t={ref['start_ms'] // 1000})"
            fold = "+" if quote_idx == 1 else "-"
            yield f"> [!quote]{fold} {stamp}\n> "
            for offset in range(ref["lo"], ref["hi"], 4000):
                text = source_page(doc["id"], ref["cue"], offset)["text"][:min(4000, ref["hi"] - offset)]
                yield _plain(text).replace("\n", "\n> ")
            yield "\n\n"
        if page["next"] is None:
            break
        after = page["next"]


def _count_descendants(node):
    children = node.get("children") or []
    if not children:
        return 0, len(node.get("viewpoints") or [])
    sub_nodes = len(children)
    vps = 0
    for child in children:
        sn, sv = _count_descendants(child)
        sub_nodes += sn
        vps += sv
    return sub_nodes, vps


def _node_span_label(doc, node):
    if doc.get("reference_kind") == "paragraph":
        if node.get("start_cue") and node.get("end_cue"):
            if node["start_cue"] == node["end_cue"]:
                return f"第 {node['start_cue']} 段"
            return f"第 {node['start_cue']}–{node['end_cue']} 段"
        return ""
    if node.get("start_ms") is not None and node.get("end_ms") is not None:
        return f"{knowledge.clock(node['start_ms'])}–{knowledge.clock(node['end_ms'])}"
    if node.get("start_cue") and node.get("end_cue"):
        return f"#{node['start_cue']}–#{node['end_cue']}"
    return ""


def _summary_mermaid(doc, tree):
    top_nodes = tree.get("nodes") or []
    if len(top_nodes) < 2:
        return ""
    lines = ["```mermaid", "flowchart LR", f'  R["{_mermaid_label(doc["title"], 22)}"]']
    sub_budget = 24
    for idx, top in enumerate(top_nodes, 1):
        tid = f"N{idx}"
        lines.append(f'  R --> {tid}["{idx}. {_mermaid_label(top["title"], 20)}"]')
        children = top.get("children") or []
        if children and sub_budget > 0:
            take = min(len(children), max(1, sub_budget // max(1, len(top_nodes) - idx + 1)))
            for sub_idx, child in enumerate(children[:take], 1):
                cid = f"N{idx}_{sub_idx}"
                lines.append(f'  {tid} --> {cid}["{idx}.{sub_idx} {_mermaid_label(child["title"], 18)}"]')
                sub_budget -= 1
            if len(children) > take:
                lines.append(f'  {tid} --> {tid}_more["…其余 {len(children) - take} 节"]')
    lines.append("```")
    return "\n".join(lines)


def _summary_node_chunks(doc, node, prefix, heading_level):
    from app.note_pages import candidate_references, source_page

    hashes = "#" * min(6, max(2, heading_level))
    heading_text = f"{prefix}. {_heading(node['title'])}" if "." not in prefix else f"{prefix} {_heading(node['title'])}"
    span = _node_span_label(doc, node)
    parts = [f"{hashes} {heading_text}\n\n"]
    if span:
        if doc.get("reference_kind") == "paragraph":
            parts.append(f"§ `{span}`\n\n")
        else:
            jump = _deep_link(doc, node.get("start_ms"), "跳转原位置")
            jump_bit = f" · {jump}" if jump != "跳转原位置" else ""
            parts.append(f"⏱ `{span}`{jump_bit}\n\n")
    if node.get("summary"):
        parts.append(f"{_plain(node['summary'])}\n\n")
    highlights = [h for h in (node.get("highlights") or []) if h and h.strip()]
    if highlights:
        parts.append("\n".join(f"- {_plain(h)}" for h in highlights) + "\n\n")
    yield "".join(parts)

    for idx, child in enumerate(node.get("children") or [], 1):
        yield from _summary_node_chunks(doc, child, f"{prefix}.{idx}", heading_level + 1)

    viewpoints = node.get("viewpoints") or []
    if viewpoints:
        yield f"> [!tip]- 底层具象观点与故事（{len(viewpoints)} 条）\n>\n"
        youtube = _youtube_url(doc)
        bilibili = _bilibili_url(doc)
        for vp in viewpoints:
            raw_kind = vp.get("kind") or "statement"
            callout_type, kind_label = KIND_META.get(raw_kind, ("note", "核心陈述"))
            vp_title = f"{kind_label} · {_heading(vp['claim'])}"
            body_lines = []
            if vp.get("quote_translation"):
                body_lines.append(f"- **中文译句**：{_plain(vp['quote_translation'])}")
            if vp.get("evidence"):
                body_lines.append(f"- **论据**：{_plain(vp['evidence'])}")
            if vp.get("example"):
                body_lines.append(f"- **例子**：{_plain(vp['example'])}")
            yield _callout(callout_type, vp_title, "\n".join(body_lines), fold="+", depth=2)

            after = 0
            has_ref = False
            while True:
                page = candidate_references(doc["id"], vp["id"], after)
                for ref in page["items"]:
                    if not has_ref:
                        yield "> >\n"
                        has_ref = True
                    stamp = f"{knowledge.clock(ref['start_ms'])}–{knowledge.clock(ref['end_ms'])}"
                    if doc.get("reference_kind") == "paragraph":
                        stamp = f"第 {ref['cue']} 段 · {ref['lo']}–{ref['hi']}"
                    elif youtube:
                        stamp = f"[{stamp}]({youtube}&t={ref['start_ms'] // 1000}s)"
                    elif bilibili.startswith("https://www.bilibili.com/"):
                        stamp = f"[{stamp}]({bilibili}&t={ref['start_ms'] // 1000})"
                    yield f"> > > [!quote]- 原文溯源 · {stamp}\n> > > "
                    for offset in range(ref["lo"], ref["hi"], 4000):
                        text = source_page(doc["id"], ref["cue"], offset)["text"][:min(4000, ref["hi"] - offset)]
                        yield _plain(text).replace("\n", "\n> > > ")
                    yield "\n"
                if page["next"] is None:
                    break
                after = page["next"]
            yield ">\n"
        yield "\n"


def _summary_text(doc, tree, note_id, snapshot, source_path):
    source = source_path.with_suffix("").as_posix()
    source_link = quote(source, safe="/")
    plan = tree.get("plan") or {}
    platform = _platform_label(doc)
    top_nodes = tree.get("nodes") or []
    summary_layers = int(plan.get("summary_layers") or 1)
    leaf_count = int(plan.get("leaf_count") or len(top_nodes))
    vp_count = int(plan.get("viewpoint_count") or 0)

    tags = []
    plat_slug = _tag_slug(platform)
    if plat_slug:
        tags.append(f"media-operator/source/{plat_slug}")
    for top in top_nodes[:5]:
        ts = _tag_slug(top.get("title") or "")
        if ts:
            tags.append(f"media-operator/topic/{ts}")

    meta = _metadata(
        note_id,
        doc["title"],
        "summary",
        snapshot,
        extra={
            "source_platform": platform,
            "source_url": _source_url(doc),
            "summary_layers": summary_layers,
            "summary_nodes": leaf_count,
            "viewpoint_count": vp_count,
            "created": _created_date(doc),
        },
        tags=tags,
    )
    stats = f"`{summary_layers} 层压缩 · {len(top_nodes)} 主题 · {leaf_count} 小节 · {vp_count} 观点`"
    header = [
        meta,
        f"# {_heading(doc['title'])}\n\n",
        f"素材：[来源笔记]({source_link}) · 结构：{stats}\n\n",
    ]

    overview = tree.get("overview")
    if overview and overview.get("summary"):
        ov_body = _plain(overview["summary"])
        ov_hl = [h for h in (overview.get("highlights") or []) if h and h.strip()]
        if ov_hl:
            ov_body += "\n\n" + "\n".join(f"- {_plain(h)}" for h in ov_hl)
        header.append(_callout("abstract", "全篇总览", ov_body, fold="+"))
        header.append("\n")

    if len(top_nodes) >= 2:
        table_lines = [
            "| # | 主题 | 位置 | 核心概览 | 细化 |",
            "|---|---|---|---|---|",
        ]
        for idx, top in enumerate(top_nodes, 1):
            heading_anchor = f"{idx}. {_heading(top['title'])}"
            link = f"[[#{heading_anchor}\\|{_table_cell(top['title'], 28)}]]"
            span = _node_span_label(doc, top)
            span_cell = f"`{span}`" if span else "—"
            sub_nodes, vps = _count_descendants(top)
            detail_parts = []
            if sub_nodes:
                detail_parts.append(f"{sub_nodes} 子节")
            if vps:
                detail_parts.append(f"{vps} 观点")
            detail_cell = " · ".join(detail_parts) or "叶节"
            table_lines.append(f"| {idx} | {link} | {span_cell} | {_table_cell(top.get('summary') or '', 52)} | {detail_cell} |")
        header.append("\n".join(table_lines) + "\n\n")

        mermaid = _summary_mermaid(doc, tree)
        if mermaid:
            header.append(_callout("map", "结构脉络图（点击展开）", mermaid, fold="-"))
            header.append("\n")

    yield "".join(header)
    for idx, top in enumerate(top_nodes, 1):
        yield from _summary_node_chunks(doc, top, str(idx), 2)


def _receipt_path(vault, note_id):
    if not ID_PATTERN.fullmatch(note_id):
        raise ValueError("发布 ID 无效")
    return _inside(vault, Path(FOLDER, ".publication", f"{note_id}.json"))


def _receipt(vault, note_id):
    file = _receipt_path(vault, note_id)
    if not file.is_file():
        return None
    try:
        value = json.loads(file.read_text(encoding="utf-8"))
        if not isinstance(value["snapshot"], str) or not isinstance(value["path"], str):
            raise ValueError
    except (ValueError, TypeError, KeyError) as error:
        raise ValueError("Vault 发布记录损坏，请先检查发布目录") from error
    return value


def _markers(path):
    try:
        with path.open(encoding="utf-8-sig") as file:
            prefix = file.read(24000)
    except (FileNotFoundError, UnicodeError, PermissionError):
        return {}
    if not prefix.startswith("---\n"):
        return {}
    front = prefix.split("\n---", 1)
    if len(front) < 2:
        return {}
    return dict(re.findall(r'(?m)^(media_operator_(?:id|snapshot)):\s*"?([a-f0-9]{64})"?[ \t]*$', front[0]))


def _existing_note(vault, record, note_id, *, scan=False):
    relative = Path(record["path"])
    candidate = _inside(vault, relative)
    if candidate.suffix.lower() == ".md" and _markers(candidate).get("media_operator_id") == note_id:
        return candidate
    if scan:
        for folder, dirs, files in os.walk(vault):
            parent = Path(folder)
            dirs[:] = [name for name in dirs if not name.startswith(".")
                       and not (parent / name).is_symlink() and not (parent / name).is_junction()]
            for name in files:
                if name.lower().endswith(".md"):
                    file = parent / name
                    if file.resolve().is_relative_to(vault) and _markers(file).get("media_operator_id") == note_id:
                        return file
    return None


def _write_new(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=path.parent,
                                     prefix=".media-operator-", suffix=".tmp", delete=False) as file:
        temporary = Path(file.name)
        try:
            if isinstance(text, str):
                file.write(text)
            else:
                file.writelines(text)
            file.flush()
            os.fsync(file.fileno())
        except BaseException:
            file.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        if os.name == "nt":
            temporary.rename(path)  # A Windows rename fails if the destination exists.
        else:
            os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _create(vault, path, text, note_id, snapshot):
    target = _inside(vault, path)
    try:
        _write_new(target, text)
    except FileExistsError:
        marker = _markers(target)
        if marker != {"media_operator_id": note_id, "media_operator_snapshot": snapshot}:
            raise ValueError("同名笔记已存在，原笔记已保留") from None
    record = {"path": path.as_posix(), "snapshot": snapshot}
    try:
        _write_new(_receipt_path(vault, note_id), json.dumps(record, ensure_ascii=False) + "\n")
    except FileExistsError:
        if _receipt(vault, note_id) != record:
            raise ValueError("发布记录发生冲突，原笔记已保留") from None
    return record


def _ensure_source(vault, doc, source_id, *, vault_role="viewpoint"):
    record = _receipt(vault, source_id)
    if record:
        found = _existing_note(vault, record, source_id, scan=True)
        if not found:
            raise ValueError("找不到此前发布的素材笔记，请在 Obsidian 中恢复该笔记")
        return found.relative_to(vault)
    path = Path(FOLDER, "素材", f"素材-{source_id[:20]}.md")
    _create(vault, path, _source_text(doc, source_id, vault_role=vault_role), source_id, source_id)
    return path


def _publish_card(vault, doc, card, source_id, new_version):
    primary_id = _digest("card", source_id, card["origin_key"])
    snapshot = _digest(card["claim"], card["evidence"], card["example"], card["refs"])
    if card.get("quote_translation"):
        snapshot = _digest("translated-quote-v2", snapshot, card["quote_translation"])
    if card.get("kind") or card.get("topic"):
        snapshot = _digest("typed-v3", snapshot, card.get("kind") or "", card.get("topic") or "")
    record = _receipt(vault, primary_id)
    note_id = primary_id
    if record and new_version and record["snapshot"] != snapshot:
        note_id = _digest("version", primary_id, snapshot)
        record = _receipt(vault, note_id)
    status = "already_published" if record else "published"
    if record is None:
        source_path = _ensure_source(vault, doc, source_id, vault_role="viewpoint")
        path = Path(FOLDER, "观点", f"观点-{note_id[:20]}.md")
        record = _create(vault, path, _card_text(doc, card, note_id, snapshot, source_path), note_id, snapshot)
    # A retry after interruption may already have a receipt. Clean only the exact recorded draft.
    cleared = bool(
        record["snapshot"] == snapshot
        and _existing_note(vault, record, note_id, scan=True)
        and knowledge.remove_published_draft(doc["id"], card)
    )
    return {"card_id": card["id"], "title": card["claim"], "status": status,
            "publication_id": note_id, "cleared": cleared, "vault_kind": "viewpoint"}


def publish(vault, transcript_id, card_ids, new_version=False):
    with LOCK:
        from app.note_engine import metadata
        doc = metadata(transcript_id)
        with knowledge.database() as db:
            selected = list(dict.fromkeys(card_ids))
            if len(selected) > 300:
                raise ValueError("每批最多发布300张卡")
            doc["cards"] = [dict(row, refs=json.loads(row["refs"])) for row in db.execute(
                "SELECT * FROM card WHERE transcript_id=? AND id IN (" + ",".join("?" for _ in selected) + ")",
                [transcript_id, *selected],
            )]
        source_id = _digest("source", doc["source_kind"], doc["source"], doc["digest"])
        cards = {card["id"]: card for card in doc["cards"]}
        results = []
        for card_id in dict.fromkeys(card_ids):
            card = cards.get(card_id)
            if card is None:
                results.append({"card_id": card_id, "status": "failed", "message": "草稿已变化，请刷新后重试"})
                continue
            try:
                results.append(_publish_card(vault, doc, card, source_id, new_version))
            except (OSError, ValueError, knowledge.sqlite3.Error) as error:
                message = str(error) if isinstance(error, ValueError) else "无法完成本地发布。请检查 Vault 写入权限和磁盘空间。"
                results.append({"card_id": card_id, "title": card["claim"], "status": "failed", "message": message})
        return results


def publish_summary(vault, transcript_id, run_id=None, new_version=False):
    """Publish the full multi-level summary tree as a single rich Obsidian document into the Summary Vault."""
    with LOCK:
        from app.note_engine import metadata
        from app.note_pages import summary_tree

        doc = metadata(transcript_id)
        tree = summary_tree(transcript_id, run_id=run_id)
        if not tree or not tree.get("nodes"):
            raise ValueError("当前素材尚未生成多层级摘要，请先整理摘要后再发布")
        source_id = _digest("source", doc["source_kind"], doc["source"], doc["digest"])
        primary_id = _digest("summary-tree", source_id)
        snapshot = _digest("summary-tree-v1", tree["overview"], tree["nodes"])

        record = _receipt(vault, primary_id)
        note_id = primary_id
        if record and new_version and record["snapshot"] != snapshot:
            note_id = _digest("version", primary_id, snapshot)
            record = _receipt(vault, note_id)

        status = "already_published" if record else "published"
        if record is None:
            source_path = _ensure_source(vault, doc, source_id, vault_role="summary")
            path = Path(FOLDER, "摘要", f"摘要-{note_id[:20]}.md")
            record = _create(vault, path, _summary_text(doc, tree, note_id, snapshot, source_path), note_id, snapshot)

        same_snapshot = record["snapshot"] == snapshot
        return {
            "transcript_id": transcript_id,
            "title": doc["title"],
            "status": status,
            "publication_id": note_id,
            "path": record["path"],
            "unchanged": same_snapshot,
            "vault_kind": "summary",
            "message": (
                "已写入摘要 Obsidian 库" if status == "published"
                else "摘要库中已是最新版本" if same_snapshot
                else "摘要库已有旧版本，已保留原笔记；可点击「另存一篇」"
            ),
        }


def note_uri(vault, note_id):
    record = _receipt(vault, note_id)
    path = _existing_note(vault, record, note_id, scan=True) if record else None
    if not path:
        raise FileNotFoundError(f"找不到笔记。可在 Obsidian 搜索发布 ID {note_id}")
    return "obsidian://open?path=" + quote(str(path), safe="")


def note_uri_any(vaults, note_id):
    """Locate a published note across one or both configured vaults."""
    last_error = None
    seen = set()
    for vault in vaults:
        if not vault:
            continue
        key = str(vault)
        if key in seen:
            continue
        seen.add(key)
        try:
            return note_uri(vault, note_id)
        except (OSError, ValueError) as error:
            last_error = error
    raise FileNotFoundError(f"找不到笔记。可在 Obsidian 搜索发布 ID {note_id}") from last_error
