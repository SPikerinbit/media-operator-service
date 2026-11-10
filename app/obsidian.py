"""One-way publication of selected draft cards into an existing Obsidian vault."""
import hashlib
import html
import json
import os
from pathlib import Path, PureWindowsPath
import re
import tempfile
import threading
from urllib.parse import parse_qs, quote, urlsplit

from app import knowledge

FOLDER = "Media Operator"
LOCK = threading.Lock()
ID_PATTERN = re.compile(r"[a-f0-9]{64}")


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
    return re.sub(r"([\\\x60*_{}\[\]<>|#!~])", r"\\\1", html.escape(value, quote=False))


def _heading(value):
    return _plain(" ".join(value.split()))


def _metadata(note_id, title, kind, snapshot):
    return (
        f"---\nmedia_operator_id: {json.dumps(note_id)}\n"
        f"media_operator_snapshot: {json.dumps(snapshot)}\n"
        f"media_operator_type: {kind}\n"
        f"title: {json.dumps(title, ensure_ascii=False)}\n"
        f"tags:\n  - media-operator/{kind}\n---\n\n"
    )


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


def _source_text(doc, source_id):
    youtube = _youtube_url(doc)
    bilibili = _bilibili_url(doc)
    source = (f"[YouTube]({youtube})" if youtube else f"[B 站]({bilibili})" if bilibili
              else _heading(PureWindowsPath(doc["source"]).name))
    return (
        _metadata(source_id, doc["title"], "source", source_id)
        + f"# {_heading(doc['title'])}\n\n来源：{source}\n\n"
        + "在 Obsidian 的反向链接中查看这份素材的观点笔记。\n"
    )


def _card_text(doc, card, note_id, snapshot, source_path):
    source = source_path.with_suffix("").as_posix()
    source_link = quote(source, safe="/")
    youtube = _youtube_url(doc)
    bilibili = _bilibili_url(doc)
    sections = [
        _metadata(note_id, card["claim"], "viewpoint", snapshot),
        f"# {_heading(card['claim'])}\n\n",
        f"素材：[来源笔记]({source_link})\n\n",
    ]
    for label, key in (("论据", "evidence"), ("例子", "example")):
        if card[key].strip():
            sections.append(f"## {label}\n\n{_plain(card[key])}\n\n")
    sections.append("## 原话与时间戳\n\n")
    cues = {cue["number"]: cue for cue in doc["cues"]}
    for ref in card["refs"]:
        cue = cues[ref]
        stamp = f"{knowledge.clock(cue['start_ms'])}–{knowledge.clock(cue['end_ms'])}"
        if youtube:
            stamp = f"[{stamp}]({youtube}&t={cue['start_ms'] // 1000}s)"
        elif bilibili.startswith("https://www.bilibili.com/"):
            stamp = f"[{stamp}]({bilibili}&t={cue['start_ms'] // 1000})"
        text = "\n> ".join(_plain(cue["text"]).splitlines())
        sections.append(f"> {stamp}\n> {text}\n\n")
    return "".join(sections)


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
            file.write(text)
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


def _ensure_source(vault, doc, source_id):
    record = _receipt(vault, source_id)
    if record:
        found = _existing_note(vault, record, source_id, scan=True)
        if not found:
            raise ValueError("找不到此前发布的素材笔记，请在 Obsidian 中恢复该笔记")
        return found.relative_to(vault)
    path = Path(FOLDER, "素材", f"素材-{source_id[:20]}.md")
    _create(vault, path, _source_text(doc, source_id), source_id, source_id)
    return path


def _publish_card(vault, doc, card, source_id, new_version):
    primary_id = _digest("card", source_id, card["origin_key"])
    snapshot = _digest(card["claim"], card["evidence"], card["example"], card["refs"])
    record = _receipt(vault, primary_id)
    note_id = primary_id
    if record and new_version and record["snapshot"] != snapshot:
        note_id = _digest("version", primary_id, snapshot)
        record = _receipt(vault, note_id)
    status = "already_published" if record else "published"
    if record is None:
        source_path = _ensure_source(vault, doc, source_id)
        path = Path(FOLDER, "观点", f"观点-{note_id[:20]}.md")
        record = _create(vault, path, _card_text(doc, card, note_id, snapshot, source_path), note_id, snapshot)
    # A retry after interruption may already have a receipt. Clean only the exact recorded draft.
    cleared = bool(
        record["snapshot"] == snapshot
        and _existing_note(vault, record, note_id, scan=True)
        and knowledge.remove_published_draft(doc["id"], card)
    )
    return {"card_id": card["id"], "title": card["claim"], "status": status,
            "publication_id": note_id, "cleared": cleared}


def publish(vault, transcript_id, card_ids, new_version=False):
    with LOCK:
        doc = knowledge.read_transcript(transcript_id, include_origins=True)
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


def note_uri(vault, note_id):
    record = _receipt(vault, note_id)
    path = _existing_note(vault, record, note_id, scan=True) if record else None
    if not path:
        raise FileNotFoundError(f"找不到笔记。可在 Obsidian 搜索发布 ID {note_id}")
    return "obsidian://open?path=" + quote(str(path), safe="")
