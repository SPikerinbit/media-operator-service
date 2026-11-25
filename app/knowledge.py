
"""Local transcript catalog and editable, source-grounded viewpoint cards."""
from contextlib import closing, contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from pydantic import BaseModel, Field
import srt
import webvtt

from app import main as media


@contextmanager
def database():
    with closing(sqlite3.connect(media.DATA_DIR / "knowledge.sqlite3", timeout=15)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 15000")
        db.execute("PRAGMA temp_store = FILE")
        db.execute("PRAGMA cache_size = -4096")
        with db:
            yield db


def initialize():
    with database() as db:
        columns = {row["name"] for row in db.execute("PRAGMA table_info(card)")}
        if columns and "quote_translation" not in columns:
            backup = media.DATA_DIR / "knowledge.before-0.3.0.sqlite3"
            if not backup.exists():
                with closing(sqlite3.connect(backup)) as destination:
                    db.backup(destination)
            db.execute("ALTER TABLE card ADD COLUMN quote_translation TEXT NOT NULL DEFAULT ''")
        transcript_columns = {row["name"] for row in db.execute("PRAGMA table_info(transcript)")}
        if transcript_columns and "media_type" not in transcript_columns:
            backup = media.DATA_DIR / "knowledge.before-0.4.0.sqlite3"
            if not backup.exists():
                with closing(sqlite3.connect(backup)) as destination:
                    db.backup(destination)
            db.execute("ALTER TABLE transcript ADD COLUMN media_type TEXT")
            db.execute("ALTER TABLE transcript ADD COLUMN asset_type TEXT")
        transcript_columns = {row["name"] for row in db.execute("PRAGMA table_info(transcript)")}
        if transcript_columns and "note_body" not in transcript_columns:
            db.execute("ALTER TABLE transcript ADD COLUMN note_body TEXT")
            db.execute("ALTER TABLE transcript ADD COLUMN note_images TEXT")
        if transcript_columns and 'reference_kind' not in transcript_columns:
            db.execute("ALTER TABLE transcript ADD COLUMN reference_kind TEXT NOT NULL DEFAULT 'time'")
        db.executescript("""
            PRAGMA journal_mode = WAL;
            CREATE TABLE IF NOT EXISTS transcript (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                source TEXT NOT NULL,
                cache_key TEXT,
                digest TEXT NOT NULL,
                playable TEXT,
                media_type TEXT,
                asset_type TEXT,
                note_body TEXT,
                note_images TEXT,
                reference_kind TEXT NOT NULL DEFAULT 'time',
                created_at TEXT NOT NULL,
                UNIQUE(source, digest)
            );
            CREATE INDEX IF NOT EXISTS transcript_cache ON transcript(cache_key);
            CREATE TABLE IF NOT EXISTS cue (
                transcript_id INTEGER NOT NULL REFERENCES transcript(id) ON DELETE CASCADE,
                number INTEGER NOT NULL,
                start_ms INTEGER NOT NULL,
                end_ms INTEGER NOT NULL,
                text TEXT NOT NULL,
                PRIMARY KEY(transcript_id, number)
            );
            CREATE TABLE IF NOT EXISTS card (
                id INTEGER PRIMARY KEY,
                transcript_id INTEGER NOT NULL REFERENCES transcript(id) ON DELETE CASCADE,
                claim TEXT NOT NULL,
                evidence TEXT NOT NULL,
                example TEXT NOT NULL,
                quote_translation TEXT NOT NULL DEFAULT '',
                refs TEXT NOT NULL,
                origin_key TEXT NOT NULL,
                UNIQUE(transcript_id, origin_key)
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS transcript_search USING fts5(
                transcript_id UNINDEXED, text, tokenize='trigram'
            );
        """)

    from app.note_engine import initialize as initialize_notes
    initialize_notes()


def _read_cues(path: Path):
    if path.suffix.lower() == ".vtt":
        captions = webvtt.read(str(path), encoding="utf-8-sig")
        cues = [(cue.start_time.in_milliseconds(), cue.end_time.in_milliseconds(), cue.text) for cue in captions]
    else:
        subtitles = srt.parse(path.read_text(encoding="utf-8-sig"))
        cues = [
            (round(cue.start.total_seconds() * 1000), round(cue.end.total_seconds() * 1000), cue.content)
            for cue in subtitles
        ]
    clean = sorted((start, end, text.strip()) for start, end, text in cues if text.strip() and 0 <= start < end)
    if not clean:
        raise ValueError("字幕没有可用的时间戳片段")
    return clean


def load_cues(path: Path):
    try:
        return _read_cues(path)
    except (srt.SRTParseError, webvtt.errors.MalformedFileError, UnicodeError) as error:
        raise ValueError("无法读取字幕，请检查 SRT 或 VTT 格式及 UTF-8 编码") from error


def register(path, *, source_kind, source, title, playable=None, cache_key=None, media_type=None, asset_type=None,
             note_body=None, note_images=None, paragraphs=None):
    if paragraphs is not None:
        cues = [(0, 0, str(paragraph).strip()) for paragraph in paragraphs if str(paragraph or '').strip()]
        if not cues:
            raise ValueError("图书中没有可提取的正文内容")
        if note_body is None:
            note_body = "\n\n".join(text for _, _, text in cues[:12])[:4000]
    elif media_type == 'note':
        cues = [(0, 0, paragraph.strip()) for paragraph in re.split(r'\n\s*\n|\n', note_body or '') if paragraph.strip()]
    else:
        cues = load_cues(path)
    digest = hashlib.sha256(json.dumps(cues, ensure_ascii=False).encode()).hexdigest()
    images = json.dumps(note_images, ensure_ascii=False) if note_images is not None else None
    with database() as db:
        row = db.execute("""
            INSERT INTO transcript(title, source_kind, source, cache_key, digest, playable, media_type, asset_type,
                                   note_body, note_images, created_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, digest) DO UPDATE SET
                playable = coalesce(excluded.playable, transcript.playable),
                media_type = coalesce(excluded.media_type, transcript.media_type),
                asset_type = coalesce(excluded.asset_type, transcript.asset_type),
                cache_key = coalesce(excluded.cache_key, transcript.cache_key),
                note_body = coalesce(excluded.note_body, transcript.note_body),
                note_images = coalesce(excluded.note_images, transcript.note_images)
            RETURNING id
        """, (title, source_kind, source, cache_key, digest, str(playable) if playable else None,
              media_type, asset_type, note_body, images, media.now_iso())).fetchone()
        transcript_id = row["id"]
        if not db.execute("SELECT 1 FROM cue WHERE transcript_id=? LIMIT 1", (transcript_id,)).fetchone():
            db.executemany("INSERT INTO cue VALUES(?, ?, ?, ?, ?)", (
                (transcript_id, index, start, end, text) for index, (start, end, text) in enumerate(cues, 1)
            ))
            db.executemany("INSERT INTO transcript_search VALUES(?, ?)", [
                (transcript_id, title), *((transcript_id, text) for _, _, text in cues)
            ])
    if media_type == 'note':
        with database() as db:
            db.execute("UPDATE transcript SET reference_kind='paragraph' WHERE id=?", (transcript_id,))
    return transcript_id


def transcription_key(kind, source, language, model, inference):
    if kind == "local":
        path = media.normalize_local_source_path(source)
        stat = path.stat()
        identity = [str(path).casefold(), stat.st_size, stat.st_mtime_ns]
    else:
        from app.sites.resolve import identity as canonical_identity
        identity = [canonical_identity(source)]
    return json.dumps([kind, identity, language, model, inference], ensure_ascii=False)


def note_image(transcript_id, index):
    record = transcript_metadata(transcript_id)
    try:
        paths = json.loads(record.get("note_images") or "[]")
    except ValueError:
        paths = []
    if index < 1 or index > len(paths):
        raise FileNotFoundError("找不到图片")
    path = Path(paths[index - 1]).resolve()
    root = media.DATA_DIR.resolve()
    if not path.is_file() or root not in path.parents:
        raise FileNotFoundError("找不到图片")
    return path


def cached_id(cache_key):
    with database() as db:
        row = db.execute("SELECT id FROM transcript WHERE cache_key=? ORDER BY id DESC LIMIT 1", (cache_key,)).fetchone()
    return row["id"] if row else None


def list_transcripts(query=""):
    term = query.strip()
    with database() as db:
        if not term:
            rows = db.execute("SELECT id, title, source_kind, source, created_at FROM transcript ORDER BY id DESC")
        else:
            # Trigram supports both Chinese and English substrings. instr handles one- and two-character terms.
            if len(term) >= 3:
                indexed = "SELECT transcript_id FROM transcript_search WHERE transcript_search MATCH ?"
                search = '"' + term.replace('"', '""') + '"'
            else:
                indexed = "SELECT transcript_id FROM transcript_search WHERE instr(lower(text), lower(?)) > 0"
                search = term
            has_nodes = bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='note_node'").fetchone())
            node_clause = (
                """
                   OR id IN (
                       SELECT r.transcript_id FROM note_node n
                       JOIN note_run r ON n.run = r.id
                       WHERE n.status='done'
                         AND instr(lower(coalesce(n.title, '') || ' ' || coalesce(n.capsule, '')), lower(?)) > 0
                   )"""
                if has_nodes
                else ""
            )
            params = (search, term, term) if has_nodes else (search, term)
            rows = db.execute(f"""
                SELECT id, title, source_kind, source, created_at FROM transcript
                WHERE id IN ({indexed})
                   OR id IN (
                       SELECT transcript_id FROM card
                       WHERE instr(lower(coalesce(topic, '') || ' ' || claim || ' ' || evidence || ' ' || example || ' ' || quote_translation), lower(?)) > 0
                   ){node_clause}
                ORDER BY id DESC
            """, params)
        return [dict(row) for row in rows]


def transcript_metadata(transcript_id):
    with database() as db:
        row=db.execute('''SELECT id,title,source_kind,source,cache_key,digest,playable,media_type,asset_type,
            substr(note_body,1,4000) AS note_body,note_images,reference_kind,created_at FROM transcript WHERE id=?''',(transcript_id,)).fetchone()
        if row is None: raise FileNotFoundError('找不到字幕')
        cues=[dict(r) for r in db.execute('SELECT number,start_ms,end_ms,substr(text,1,600) AS text FROM cue WHERE transcript_id=? ORDER BY number LIMIT 8',(transcript_id,))]
    return dict(row,cues=cues)


def read_transcript(transcript_id, *, include_origins=False, mode=None):
    from app.note_engine import initialize as initialize_notes
    initialize_notes()
    with database() as db:
        transcript = db.execute("SELECT * FROM transcript WHERE id=?", (transcript_id,)).fetchone()
        if transcript is None:
            raise FileNotFoundError("找不到字幕")
        cues = [dict(row) for row in db.execute("""
            SELECT number, start_ms, end_ms, text FROM cue WHERE transcript_id=? ORDER BY number
        """, (transcript_id,))]
        effective_mode = mode if mode in {"curated", "comprehensive"} else None
        if effective_mode is None:
            active_row = db.execute(
                """SELECT r.mode FROM note_active a JOIN note_run r ON a.run=r.id
                   WHERE a.transcript_id=? LIMIT 1""",
                (transcript_id,),
            ).fetchone()
            if active_row and active_row["mode"] in {"curated", "comprehensive"}:
                effective_mode = active_row["mode"]
        if effective_mode in {"curated", "comprehensive"}:
            card_rows = db.execute("""
                SELECT id, topic, kind, mode, claim, evidence, example, quote_translation, refs, origin_key
                FROM card
                WHERE transcript_id=? AND active=1
                  AND (mode=? OR (note_run IS NULL AND mode IN ('', ?)))
                ORDER BY id
            """, (transcript_id, effective_mode, effective_mode))
        else:
            # Summary or legacy/manual-only view: prefer edited cards + latest viewpoint mode if multiple exist.
            vp_mode_row = db.execute(
                """SELECT mode FROM note_active_mode
                   WHERE transcript_id=? AND mode IN ('comprehensive', 'curated')
                   ORDER BY updated DESC LIMIT 1""",
                (transcript_id,),
            ).fetchone()
            if vp_mode_row:
                vp_mode = vp_mode_row["mode"]
                card_rows = db.execute("""
                    SELECT id, topic, kind, mode, claim, evidence, example, quote_translation, refs, origin_key
                    FROM card
                    WHERE transcript_id=? AND active=1
                      AND (mode=? OR edited=1 OR note_run IS NULL OR mode='')
                    ORDER BY id
                """, (transcript_id, vp_mode))
            else:
                card_rows = db.execute("""
                    SELECT id, topic, kind, mode, claim, evidence, example, quote_translation, refs, origin_key
                    FROM card WHERE transcript_id=? AND active=1 ORDER BY id
                """, (transcript_id,))
        cards = [dict(row, refs=json.loads(row["refs"])) for row in card_rows]
    if not include_origins:
        for card in cards:
            card.pop("origin_key")
    return dict(transcript, cues=cues, cards=cards)


def subtitle_file(transcript_id, path):
    with path.open('w', encoding='utf-8') as output, database() as db:
        rows = db.execute(
            'SELECT number,start_ms,end_ms,length(text) AS size FROM cue WHERE transcript_id=? ORDER BY number',
            (transcript_id,),
        ).fetchall()
        for cue in rows:
            output.write(f"{cue['number']}\n{clock(cue['start_ms']).replace('.',',')} --> {clock(cue['end_ms']).replace('.',',')}\n")
            for offset in range(0, cue['size'], 4000):
                chunk = db.execute(
                    'SELECT substr(text,?,4000) FROM cue WHERE transcript_id=? AND number=?',
                    (offset + 1, transcript_id, cue['number']),
                ).fetchone()
                if chunk and chunk[0]:
                    output.write(chunk[0])
            output.write('\n\n')
    return path


class CardText(BaseModel):
    claim: str = Field(min_length=1, max_length=4000)
    evidence: str = Field(default="", max_length=6000)
    example: str = Field(default="", max_length=6000)
    quote_translation: str = Field(default="", max_length=6000)
    topic: str = Field(default="", max_length=120)
    kind: str = Field(default="", max_length=32)
    mode: str = Field(default="", max_length=32)
    refs: list[int] | None = Field(default=None, max_length=12)


class GeneratedCard(CardText):
    refs: list[int] = Field(min_length=1, max_length=12)


class Generation(BaseModel):
    cards: list[GeneratedCard] = Field(max_length=30)


def create_card(transcript_id, edit: CardText):
    import uuid
    from app.note_engine import initialize, normalize_kind
    initialize()
    claim = edit.claim.strip()
    if not claim:
        raise ValueError("主张不能为空")
    kind = normalize_kind(edit.kind, allow_empty=True)
    mode = edit.mode if edit.mode in {"curated", "comprehensive"} else ""
    with database() as db:
        if not db.execute("SELECT 1 FROM transcript WHERE id=?", (transcript_id,)).fetchone():
            raise FileNotFoundError("找不到字幕")
        refs = [int(r) for r in (edit.refs or []) if isinstance(r, int) and r > 0][:12]
        if not refs:
            first_cue = db.execute(
                "SELECT number FROM cue WHERE transcript_id=? ORDER BY number LIMIT 1",
                (transcript_id,),
            ).fetchone()
            refs = [int(first_cue["number"])] if first_cue else []
        origin_key = f"manual-{uuid.uuid4().hex[:12]}"
        row = db.execute(
            """INSERT INTO card(transcript_id, topic, kind, mode, claim, evidence, example, quote_translation, refs, origin_key, active, edited)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1) RETURNING id""",
            (transcript_id, (edit.topic or "").strip(), kind, mode, claim, edit.evidence, edit.example,
             edit.quote_translation, json.dumps(refs), origin_key),
        ).fetchone()
        return int(row["id"])


def delete_card(transcript_id, card_id):
    from app.note_engine import initialize
    initialize()
    with database() as db:
        result = db.execute("DELETE FROM card WHERE id=? AND transcript_id=?", (card_id, transcript_id))
        if not result.rowcount:
            raise FileNotFoundError("找不到观点卡")


def update_card(transcript_id, card_id, edit):
    from app.note_engine import initialize, normalize_kind
    initialize()
    kind = normalize_kind(edit.kind, allow_empty=True) if "kind" in edit.model_fields_set else ""
    with database() as db:
        result = db.execute("""UPDATE card SET edited=1, claim=?, evidence=?, example=?,
                            quote_translation=CASE WHEN ? THEN ? ELSE quote_translation END,
                            topic=CASE WHEN ? THEN ? ELSE topic END,
                            kind=CASE WHEN ? THEN ? ELSE kind END
                            WHERE id=? AND transcript_id=?""",
                            (edit.claim.strip(), edit.evidence, edit.example,
                             "quote_translation" in edit.model_fields_set, edit.quote_translation,
                             "topic" in edit.model_fields_set, (edit.topic or "").strip(),
                             "kind" in edit.model_fields_set, kind,
                             card_id, transcript_id))
        if not result.rowcount:
            raise FileNotFoundError("找不到观点卡")


def remove_published_draft(transcript_id, card):
    with database() as db:
        result = db.execute("""
            DELETE FROM card WHERE transcript_id=? AND id=? AND origin_key=?
            AND claim=? AND evidence=? AND example=? AND json(refs)=json(?) AND quote_translation=?
        """, (transcript_id, card["id"], card["origin_key"], card["claim"],
              card["evidence"], card["example"], json.dumps(card["refs"]), card.get("quote_translation", "")))
        return bool(result.rowcount)


def cue_groups(cues):
    group = []
    size = 0
    for cue in cues:
        length = len(cue["text"]) + 32
        if group and size + length > 8000:
            yield group
            group = group[-2:]
            size = sum(len(item["text"]) + 32 for item in group)
        group.append({"id": cue["number"], "text": cue["text"]})
        size += length
    if group:
        yield group


def generate_cards(transcript_id, api_key, model, mode="curated", progress=None, *, derive_siblings=True):
    from app.note_engine import generate
    return generate(transcript_id, api_key, model, mode, progress, derive_siblings=derive_siblings)


def clock(milliseconds):
    seconds = milliseconds // 1000
    return f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}.{milliseconds % 1000:03d}"


def markdown(transcript_id):
    transcript = read_transcript(transcript_id)
    cues = {cue["number"]: cue for cue in transcript["cues"]}
    output = [f"# {transcript['title']}", ""]
    if transcript["source_kind"] in {"youtube", "bilibili", "url"}:
        output += [f"来源：{transcript['source']}", ""]
    for card in transcript["cards"]:
        title = re.sub(r"\s+", " ", card["claim"]).strip()
        output += [f"## {title}", ""]
        if card.get("quote_translation"):
            output += ["**中文译句**", "", card["quote_translation"], ""]
        for label, key in (("论据", "evidence"), ("例子", "example")):
            if card[key]:
                output += [f"**{label}**　{card[key]}", ""]
        for ref in card["refs"]:
            cue = cues[ref]
            quote = cue["text"].replace("\n", "\n> ")
            location = f"第 {cue['number']} 段" if transcript.get('reference_kind') == 'paragraph' else f"{clock(cue['start_ms'])}–{clock(cue['end_ms'])}"
            output += [f"> [{location}] {quote}", ""]
    if not transcript["cards"]:
        for cue in transcript["cues"]:
            location = f"第 {cue['number']} 段" if transcript.get('reference_kind') == 'paragraph' else clock(cue['start_ms'])
            output += [f"- {location}　{cue['text'].replace(chr(10), ' ')}"]
    return "\n".join(output) + "\n"
