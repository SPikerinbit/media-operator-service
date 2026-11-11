from __future__ import annotations

# ruff: noqa: F821
"""Job folders, batch records, and stage progress.

Executed inside app.main so callers and tests keep patching that module.
"""

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dirs() -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    BATCHES_DIR.mkdir(parents=True, exist_ok=True)
    TRANSLATION_CONTEXTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PREVIEW_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def sanitize_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(value, (int, float)):
        return bool(value)
    return default



def job_dir(job_id: str) -> Path:
    if DESKTOP and not re.fullmatch(r"[a-zA-Z0-9_-]+", job_id):
        raise FileNotFoundError(job_id)
    return JOBS_DIR / job_id


def batch_dir(batch_id: str) -> Path:
    if DESKTOP and not re.fullmatch(r"batch_[0-9a-f]{12}", batch_id):
        raise FileNotFoundError(batch_id)
    return BATCHES_DIR / batch_id


def batch_state_path(batch_id: str) -> Path:
    return batch_dir(batch_id) / "state.json"


def state_path(job_id: str) -> Path:
    return job_dir(job_id) / "state.json"


def request_path(job_id: str) -> Path:
    return job_dir(job_id) / "request.json"


def artifact_path(job_id: str, name: str) -> Path:
    return job_dir(job_id) / name


def public_file_url(job_id: str, name: str) -> str:
    return f"{'' if DESKTOP else PUBLIC_BASE_URL}/files/{job_id}/{name}"


def public_job_url(job_id: str) -> str:
    return f"{PUBLIC_BASE_URL}/jobs/{job_id}"


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    tmp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    tmp_path.write_text(payload, encoding="utf-8")
    last_error: Exception | None = None
    for attempt in range(8):
        try:
            os.replace(tmp_path, path)
            return
        except PermissionError as error:
            last_error = error
            time.sleep(min(0.25, 0.03 * (attempt + 1)))
        except OSError as error:
            last_error = error
            time.sleep(min(0.25, 0.03 * (attempt + 1)))
    try:
        if tmp_path.exists():
            tmp_path.unlink()
    except Exception:
        pass
    if last_error is not None:
        raise last_error


def read_json(path: Path) -> Any:
    last_error: Exception | None = None
    for _ in range(5):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            last_error = error
            time.sleep(0.05)
    if last_error is not None:
        raise last_error
    return json.loads(path.read_text(encoding="utf-8"))


def clean_translation_text(value: Any, limit: int = 4000) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return text[:limit]


def normalize_saved_translation_text(value: Any) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def load_translation_context_profiles() -> list[dict[str, Any]]:
    ensure_dirs()
    if not TRANSLATION_CONTEXTS_PATH.exists():
        return []
    data = read_json(TRANSLATION_CONTEXTS_PATH)
    if isinstance(data, dict):
        data = data.get("profiles", [])
    if not isinstance(data, list):
        return []
    profiles: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            profile = TranslationContextProfile.model_validate(item)
        except Exception:
            continue
        profiles.append(profile.model_dump())
    return profiles


def save_translation_context_profiles(profiles: list[dict[str, Any]]) -> None:
    write_json(TRANSLATION_CONTEXTS_PATH, {"profiles": profiles})


def is_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except Exception:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def is_youtube_url(value: str) -> bool:
    return video_url_kind(value) == "youtube"


def video_url_kind(value: str) -> str | None:
    try:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or parsed.username is not None or parsed.port is not None:
            return None
        host = parsed.hostname or ""
    except ValueError:
        return None
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}:
        return "youtube"
    if host in {"bilibili.com", "www.bilibili.com", "m.bilibili.com", "b23.tv"}:
        return "bilibili"
    return None


def is_local_source_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except Exception:
        return False
    return parsed.path.startswith("/files/")


def source_display_title(kind: str, source: str, title: str = "") -> str:
    if kind in {"local", "subtitle"}:
        return Path(source).name
    return " ".join(title.split())[:500] if title and not is_http_url(title.strip()) else ""


def normalize_local_source_path(value: str) -> Path:
    raw = value.strip()
    if not raw:
        raise ValueError("source_value is required")
    if raw.startswith("/files/"):
        _, path = resolve_local_artifact_from_url(raw)
        return path
    parsed = urlparse(raw)
    if parsed.scheme == "file":
        raw = parsed.path or ""
        if re.match(r"^/[A-Za-z]:/", raw):
            raw = raw[1:]
    path = Path(raw)
    if not path.is_absolute():
        raise ValueError("local source must be an absolute path or /files/ resource url")
    if not path.exists():
        raise ValueError(f"local source not found: {path}")
    if not path.is_file():
        raise ValueError(f"local source is not a file: {path}")
    return path


def import_local_source(job_id: str, source_value: str) -> Path:
    source_path = normalize_local_source_path(source_value)
    suffix = source_path.suffix or ".mp4"
    target_path = artifact_path(job_id, f"source{suffix}")
    if target_path.exists():
        return target_path
    shutil.copy2(source_path, target_path)
    return target_path


def parse_url_list(text_or_urls: str | list[str]) -> list[str]:
    if isinstance(text_or_urls, str):
        raw_parts = re.split(r"[\s,]+", text_or_urls)
    else:
        raw_parts = []
        for item in text_or_urls:
            raw_parts.extend(re.split(r"[\s,]+", str(item)))
    urls: list[str] = []
    seen: set[str] = set()
    for raw in raw_parts:
        url = raw.strip()
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def build_output_name(mode: OutputNameMode, prefix: str, index: int, fallback: str) -> str:
    clean_prefix = prefix.strip()
    if mode == "sequence":
        return f"{clean_prefix or 'video'}{index}"
    if mode == "custom" and clean_prefix:
        return clean_prefix if index == 1 else f"{clean_prefix}{index}"
    return fallback.strip() or "source"


def safe_download_filename(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip(" .")
    return cleaned[:120] or "final"


def bilibili_configured() -> bool:
    return bool(BILI_SESSDATA and BILI_JCT and BILI_BUVID3)


def require_bilibili_config() -> None:
    if not bilibili_configured():
        raise RuntimeError("Bilibili credential is not configured: set BILI_SESSDATA, BILI_JCT and BILI_BUVID3")


def bilibili_cookie_header() -> str:
    values = {
        "SESSDATA": BILI_SESSDATA,
        "bili_jct": BILI_JCT,
        "buvid3": BILI_BUVID3,
        "DedeUserID": BILI_DEDEUSERID,
        "ac_time_value": BILI_AC_TIME_VALUE,
    }
    return "; ".join(f"{key}={value}" for key, value in values.items() if value)


def render_bilibili_title(template: str, *, output_name: str, index: int, original_title: str, source: str) -> str:
    values = {
        "output_name": output_name or f"video{index}",
        "index": str(index),
        "original_title": original_title or output_name or f"video{index}",
        "source": source,
    }
    text = template or "{output_name}"
    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value))
    return safe_download_filename(text)[:80] or values["output_name"][:80]


def extract_bilibili_submission_ids(value: Any) -> dict[str, Any]:
    found: dict[str, Any] = {}

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, raw in item.items():
                lower = str(key).lower()
                if lower in {"bvid", "bv_id", "bv"} and raw:
                    found["bvid"] = str(raw)
                if lower in {"aid", "avid", "archive_id"} and raw:
                    try:
                        found["aid"] = int(raw)
                    except Exception:
                        found["aid"] = raw
                visit(raw)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return found


def load_state(job_id: str) -> JobState:
    path = state_path(job_id)
    if not path.exists():
        raise FileNotFoundError(job_id)
    return JobState.model_validate(read_json(path))


def save_state(state: JobState) -> JobState:
    with state_lock:
        payload = state.model_dump()
        write_json(state_path(state.job_id), payload)
        return state


def load_batch(batch_id: str) -> BatchState:
    path = batch_state_path(batch_id)
    if not path.exists():
        raise FileNotFoundError(batch_id)
    return BatchState.model_validate(read_json(path))


def save_batch(batch: BatchState) -> BatchState:
    with batch_lock:
        payload = batch.model_dump()
        write_json(batch_state_path(batch.batch_id), payload)
        return batch


def recompute_batch_counts(data: dict[str, Any]) -> None:
    items = data.get("items") or []
    statuses = [item.get("status") for item in items]
    data["queued"] = statuses.count("queued")
    data["running"] = statuses.count("running")
    data["succeeded"] = statuses.count("succeeded")
    data["failed"] = statuses.count("failed")
    if data["running"]:
        data["status"] = "running"
    elif data["queued"]:
        data["status"] = "queued"
    elif data["failed"]:
        data["status"] = "failed"
    elif statuses and all(item == "cancelled" for item in statuses):
        data["status"] = "cancelled"
    else:
        data["status"] = "succeeded"


def update_batch_item(
    batch_id: str,
    item_id: str,
    *,
    status: BatchItemStatus | None = None,
    stage: str | None = None,
    progress: int | None = None,
    message: str | None = None,
    output_name: str | None = None,
    source_title: str | None = None,
    stage_jobs: dict[str, str] | None = None,
    stage_details: dict[str, dict[str, Any]] | None = None,
    active_stage_job_id: str | None = None,
    local_progress: int | None = None,
    progress_detail: str | None = None,
    log_tail: list[str] | None = None,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    clear_error: bool = False,
) -> BatchState:
    with batch_lock:
        batch = load_batch(batch_id)
        data = batch.model_dump()
        found = False
        for item in data["items"]:
            if item["item_id"] != item_id:
                continue
            found = True
            if item.get("status") == "cancelled" and status != "cancelled":
                return batch
            if status is not None:
                item["status"] = status
            if stage is not None:
                item["stage"] = stage
            if progress is not None:
                item["progress"] = progress
            if message is not None:
                item["message"] = message
            if output_name is not None:
                item["output_name"] = output_name
            if source_title is not None:
                item["source_title"] = source_title
            if stage_jobs is not None:
                item["stage_jobs"] = stage_jobs
            if stage_details is not None:
                item["stage_details"] = stage_details
            if active_stage_job_id is not None:
                item["active_stage_job_id"] = active_stage_job_id
            if local_progress is not None:
                item["local_progress"] = local_progress
            if progress_detail is not None:
                item["progress_detail"] = progress_detail
            if log_tail is not None:
                item["log_tail"] = log_tail
            if result is not None:
                item["result"] = result
            if clear_error:
                item["error"] = None
            elif error is not None:
                item["error"] = error
            item["updated_at"] = now_iso()
            break
        if not found:
            raise FileNotFoundError(item_id)
        data["updated_at"] = now_iso()
        recompute_batch_counts(data)
        updated = BatchState.model_validate(data)
        save_batch(updated)
        return updated


def clamp_percent(value: int | float | None) -> int:
    try:
        return max(0, min(100, int(float(value or 0))))
    except Exception:
        return 0


def stage_overall_progress(stage: str, local_progress: int | float | None) -> int:
    start, end = STAGE_PROGRESS_RANGES.get(stage, (0, 100))
    local = clamp_percent(local_progress)
    return max(0, min(100, int(round(start + (end - start) * local / 100))))


def stage_progress_log_path(job_id: str) -> Path:
    return job_dir(job_id) / "progress.log.txt"


def append_stage_log(job_id: str, stage: str, progress: int, message: str, raw: str | None = None) -> None:
    path = stage_progress_log_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    detail = " ".join(str(message or "").split())
    raw_text = " ".join(str(raw or "").split())
    if raw_text and raw_text != detail:
        detail = f"{detail} | {raw_text}" if detail else raw_text
    line = f"{now_iso()}\t{stage}\t{clamp_percent(progress)}\t{detail}\n"
    with path.open("a", encoding="utf-8", errors="replace") as handle:
        handle.write(line)


def read_stage_log_tail(job_id: str, limit: int = 5) -> list[str]:
    path = stage_progress_log_path(job_id)
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    return lines[-limit:]


def exception_diagnostics(error: BaseException) -> dict[str, Any]:
    message = str(error).strip()
    repr_text = repr(error)
    return {
        "type": error.__class__.__name__,
        "message": message or repr_text or error.__class__.__name__,
        "repr": repr_text,
        "args": [str(item) for item in getattr(error, "args", ())],
        "cause": repr(error.__cause__) if getattr(error, "__cause__", None) else "",
        "context": repr(error.__context__) if getattr(error, "__context__", None) else "",
    }


def safe_json_payload(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return str(value)
    if isinstance(value, BaseException):
        return exception_diagnostics(value)
    if isinstance(value, dict):
        return {str(key): safe_json_payload(item, depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [safe_json_payload(item, depth + 1) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def bilibili_event_message(data: Any, fallback: str = "uploading video") -> str:
    if not isinstance(data, dict):
        return fallback
    name = str(data.get("name") or data.get("event") or data.get("msg") or data.get("message") or fallback)
    event_data = data.get("data")
    err: Any = None
    if isinstance(event_data, list) and event_data:
        first = event_data[0]
        if isinstance(first, dict):
            err = first.get("err")
    elif isinstance(event_data, dict):
        err = event_data.get("err")
    if err:
        if isinstance(err, dict):
            err_text = str(err.get("message") or err.get("repr") or err.get("type") or err)
        else:
            err_text = str(err)
        if err_text:
            return f"{name}: {err_text}"
    return name


def bilibili_upload_line_candidates(preferred: str) -> list[str]:
    valid = {"auto", "QN", "BDA2", "WS"}
    candidates: list[str] = []
    for raw in [preferred, *BILI_UPLOAD_FALLBACK_LINES]:
        candidate = (raw or "").strip()
        candidate = "auto" if candidate.lower() == "auto" else candidate.upper()
        if candidate in valid and candidate not in candidates:
            candidates.append(candidate)
    return candidates or ["auto"]


def sync_stage_to_batch(
    job_id: str,
    stage: str,
    *,
    status: Literal["queued", "running", "succeeded", "failed"],
    progress: int,
    message: str,
    error: dict[str, Any] | None = None,
    force: bool = False,
) -> None:
    try:
        state = load_state(job_id)
    except Exception:
        return
    request_payload = state.request or {}
    batch_id = str(request_payload.get("operator_batch_id") or "").strip()
    item_id = str(request_payload.get("operator_item_id") or "").strip()
    if not batch_id or not item_id:
        return

    sync_key = f"{batch_id}:{item_id}:{stage}"
    now_monotonic = time.monotonic()
    if not force:
        with stage_sync_lock:
            last = stage_sync_times.get(sync_key, 0.0)
            if now_monotonic - last < BATCH_STAGE_SYNC_THROTTLE_SECONDS:
                return
            stage_sync_times[sync_key] = now_monotonic
    else:
        with stage_sync_lock:
            stage_sync_times[sync_key] = now_monotonic

    try:
        batch = load_batch(batch_id)
    except Exception:
        return
    current = next((entry for entry in batch.items if entry.item_id == item_id), None)
    if current is None:
        return

    local_progress = clamp_percent(progress)
    stage_jobs = dict(current.stage_jobs or {})
    stage_jobs[stage] = job_id
    stage_details = dict(current.stage_details or {})
    stage_details[stage] = {
        "job_id": job_id,
        "label": STAGE_LABELS.get(stage, stage),
        "status": status,
        "progress": local_progress,
        "message": message,
        "updated_at": now_iso(),
    }
    log_tail = read_stage_log_tail(job_id)
    is_terminal_upload_success = not DESKTOP and stage == "bilibili_upload" and status == "succeeded"
    batch_status: BatchItemStatus = "failed" if status == "failed" else ("succeeded" if is_terminal_upload_success else "running")
    batch_stage = "done" if is_terminal_upload_success else stage
    batch_progress = 100 if is_terminal_upload_success else stage_overall_progress(stage, local_progress)
    if DESKTOP and current.planned_stages and stage in current.planned_stages:
        batch_progress = min(99, round(100 * (
            current.planned_stages.index(stage) + local_progress / 100
        ) / len(current.planned_stages)))
    if DESKTOP and batch.request.get('notes_auto'):
        ranges = {'download': (0, 15), 'transcribe': (15, 60), 'translate': (60, 80)}
        lower, upper = ranges.get(stage, (0, 80))
        batch_progress = max(current.progress, min(99, round(lower + (upper-lower)*local_progress/100)))
    batch_message = "completed" if is_terminal_upload_success else message
    batch_result = state.result if is_terminal_upload_success else None
    update_batch_item(
        batch_id,
        item_id,
        status=batch_status,
        stage=batch_stage,
        progress=batch_progress,
        message=batch_message,
        stage_jobs=stage_jobs,
        stage_details=stage_details,
        active_stage_job_id=job_id,
        local_progress=local_progress,
        progress_detail=f"{STAGE_LABELS.get(stage, stage)} {local_progress}% · {message}",
        log_tail=log_tail,
        result=batch_result,
        error=error,
        clear_error=status in {"queued", "running", "succeeded"},
    )


def report_stage_progress(
    job_id: str,
    stage: str,
    progress: int,
    message: str,
    *,
    status: Literal["queued", "running", "succeeded", "failed"] | None = None,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    raw: str | None = None,
    force: bool = False,
) -> JobState:
    state = update_state(
        job_id,
        status=status,
        stage=stage,
        progress=clamp_percent(progress),
        message=message,
        result=result,
        error=error,
    )
    append_stage_log(job_id, stage, clamp_percent(progress), message, raw)
    sync_stage_to_batch(
        job_id,
        stage,
        status=state.status,
        progress=state.progress,
        message=message,
        error=error,
        force=force or status in {"queued", "succeeded", "failed"},
    )
    return state


def create_job(request: VideoJobRequest) -> JobState:
    ensure_dirs()
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    now = now_iso()
    folder = job_dir(job_id)
    folder.mkdir(parents=True, exist_ok=True)
    payload = request.model_dump()
    payload["rights_confirmed"] = bool(request.rights_confirmed)
    payload["need_bilingual_srt"] = bool(request.need_bilingual_srt)
    payload["need_burn_subtitle"] = bool(request.need_burn_subtitle)
    state = JobState(
        job_id=job_id,
        status="queued",
        stage="queued",
        progress=0,
        message="queued",
        request=payload,
        created_at=now,
        updated_at=now,
    )
    write_json(request_path(job_id), payload)
    save_state(state)
    report_stage_progress(job_id, "queued", 0, "queued", status="queued", force=True)
    return state


def create_stage_job(stage: str, request_payload: dict[str, Any]) -> JobState:
    ensure_dirs()
    job_id = f"stage_{stage}_{uuid.uuid4().hex[:12]}"
    now = now_iso()
    folder = job_dir(job_id)
    folder.mkdir(parents=True, exist_ok=True)
    payload = dict(request_payload)
    payload["stage"] = stage
    state = JobState(
        job_id=job_id,
        status="queued",
        stage=stage,
        progress=0,
        message="queued",
        request=payload,
        created_at=now,
        updated_at=now,
    )
    write_json(request_path(job_id), payload)
    save_state(state)
    return state


def create_batch(request: BatchCreateRequest, plans: dict | None = None) -> BatchState:
    ensure_dirs()
    sources = list(request.sources or [])
    if not sources and request.youtube_urls:
        sources = [SourceInput(source_kind="youtube", source_value=url) for url in parse_url_list(request.youtube_urls)]
    if not sources:
        raise ValueError("at least one source is required")
    if not request.rights_confirmed:
        raise PermissionError("rights_confirmed must be true")

    batch_id = f"batch_{uuid.uuid4().hex[:12]}"
    now = now_iso()
    folder = batch_dir(batch_id)
    folder.mkdir(parents=True, exist_ok=True)
    request_payload = request.model_dump()
    request_payload["sources"] = [source.model_dump() for source in sources]
    request_payload["youtube_urls"] = [source.source_value for source in sources if source.source_kind == "youtube"]
    request_payload["batch_concurrency"] = min(
        int(request.batch_concurrency or BATCH_WORKER_CONCURRENCY),
        BATCH_WORKER_MAX_CONCURRENCY,
    )
    items = [
        BatchItemState(
            item_id=f"item_{uuid.uuid4().hex[:12]}",
            index=index,
            client_row_id=source.client_row_id,
            youtube_url=source.source_value,
            source_kind=source.source_kind,
            source_value=source.source_value,
            source_title=source_display_title(source.source_kind, source.source_value, source.source_title),
            **((plans or {}).get(source.client_row_id) or {}),
            output_name=build_output_name(
                request.output_name_mode,
                request.output_name_prefix,
                index,
                f"source{index}",
            ),
            created_at=now,
            updated_at=now,
        )
        for index, source in enumerate(sources, start=1)
    ]
    batch = BatchState(
        batch_id=batch_id,
        status="queued",
        total=len(items),
        queued=len(items),
        request=request_payload,
        items=items,
        created_at=now,
        updated_at=now,
    )
    save_batch(batch)
    return batch


def update_state(
    job_id: str,
    *,
    status: Literal["queued", "running", "succeeded", "failed"] | None = None,
    stage: str | None = None,
    progress: int | None = None,
    message: str | None = None,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> JobState:
    state = load_state(job_id)
    data = state.model_dump()
    if status is not None:
        data["status"] = status
    if stage is not None:
        data["stage"] = stage
    if progress is not None:
        data["progress"] = progress
    if message is not None:
        data["message"] = message
    if result is not None:
        data["result"] = result
    if error is not None:
        data["error"] = error
    data["updated_at"] = now_iso()
    updated = JobState.model_validate(data)
    save_state(updated)
    return updated


def wait_for_state_change(job_id: str, *, hold_seconds: int = 0) -> JobState:
    state = load_state(job_id)
    if hold_seconds <= 0 or state.status in {"succeeded", "failed"}:
        return state

    deadline = time.monotonic() + hold_seconds

    while time.monotonic() < deadline:
        current = load_state(job_id)
        if current.status in {"succeeded", "failed"}:
            return current

        sleep_for = min(0.25, max(0.05, deadline - time.monotonic()))
        time.sleep(sleep_for)

    return load_state(job_id)
