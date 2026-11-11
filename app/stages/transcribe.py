from __future__ import annotations

# ruff: noqa: F821
"""Subtitle timing and Whisper transcription.

Executed inside app.main so callers and tests keep patching that module.
"""

def format_srt_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis >= 1000:
        secs += 1
        millis -= 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def placeholder_srt(job_id: str, title: str, source_hint: str) -> Path:
    content = "\n".join(
        [
            "1",
            "00:00:00,000 --> 00:00:04,000",
            f"Placeholder transcript for {source_hint}",
            "",
        ]
    )
    path = artifact_path(job_id, "english.srt")
    path.write_text(content, encoding="utf-8")
    return path


def write_transcription_artifacts(
    job_id: str,
    *,
    segments: list[dict[str, Any]],
    words: list[dict[str, Any]],
    language: str,
    model_name: str,
) -> tuple[Path, Path]:
    raw_segments_path = artifact_path(job_id, "raw_segments.json")
    aligned_words_path = artifact_path(job_id, "aligned_words.json")
    diagnostics_path = artifact_path(job_id, "timing_diagnostics.json")
    raw_segments_path.write_text(json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8")
    aligned_words_path.write_text(json.dumps(words, ensure_ascii=False, indent=2), encoding="utf-8")
    subtitles = subtitles_from_aligned_words(words) if words else subtitles_from_segments(segments)
    if DESKTOP and language in {"zh", "yue", "ja"}:
        cjk = r"぀-ヿ㐀-鿿"
        for subtitle in subtitles:
            subtitle.content = re.sub(rf"(?<=[{cjk}]) +(?=[{cjk}])", "", subtitle.content)
    segmentation_stats = getattr(subtitles_from_aligned_words, "last_stats", {}) if words else {}
    srt_path = artifact_path(job_id, "english.srt")
    srt_path.write_text(srt.compose(subtitles), encoding="utf-8")
    diagnostics = build_timing_diagnostics(
        subtitles,
        words=words,
        language=language,
        model_name=model_name,
    )
    diagnostics["segmentation"] = segmentation_stats
    diagnostics_path.write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8")
    return srt_path, diagnostics_path


def normalize_word_text(value: Any) -> str:
    return str(value or "").strip()


def word_start(word: dict[str, Any]) -> float:
    return max(0.0, float(word.get("start") or 0.0))


def word_end(word: dict[str, Any]) -> float:
    start = word_start(word)
    raw_end = word.get("end")
    if raw_end is None:
        return start
    return max(start, float(raw_end))


def subtitles_from_segments(segments: list[dict[str, Any]]) -> list[srt.Subtitle]:
    subtitles: list[srt.Subtitle] = []
    for index, segment in enumerate(segments, start=1):
        start = max(0.0, float(segment.get("start") or 0.0))
        end = max(start + 0.25, float(segment.get("end") or start + 0.25))
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        subtitles.append(
            srt.Subtitle(
                index=len(subtitles) + 1,
                start=timedelta(seconds=start),
                end=timedelta(seconds=end),
                content=text,
            )
        )
    return normalize_subtitle_timing(subtitles)


def subtitles_from_aligned_words(words: list[dict[str, Any]]) -> list[srt.Subtitle]:
    clean_words = [word for word in words if normalize_word_text(word.get("word"))]
    subtitles: list[srt.Subtitle] = []
    current: list[dict[str, Any]] = []
    subtitles_from_aligned_words.last_stats = {}

    def flush() -> None:
        nonlocal current
        if not current:
            return
        text = " ".join(normalize_word_text(item.get("word")) for item in current).strip()
        if not text:
            current = []
            return
        start = word_start(current[0])
        end = word_end(current[-1]) + SUBTITLE_TAIL_PADDING_MS / 1000
        end = max(start + SUBTITLE_MIN_DURATION_MS / 1000, end)
        subtitles.append(
            srt.Subtitle(
                index=len(subtitles) + 1,
                start=timedelta(seconds=start),
                end=timedelta(seconds=end),
                content=text,
            )
        )
        current = []

    for word in clean_words:
        if not current:
            current.append(word)
            continue
        previous = current[-1]
        gap_ms = max(0.0, (word_start(word) - word_end(previous)) * 1000)
        candidate_text = " ".join(normalize_word_text(item.get("word")) for item in [*current, word]).strip()
        candidate_duration_ms = max(1.0, (word_end(word) - word_start(current[0])) * 1000)
        too_long = candidate_duration_ms > SUBTITLE_MAX_DURATION_MS
        too_wide = len(candidate_text) > SUBTITLE_MAX_CHARS
        too_sparse = gap_ms > SUBTITLE_MAX_GAP_MS
        ends_sentence = normalize_word_text(previous.get("word")).endswith((".", "?", "!", "。", "？", "！"))
        if too_long or too_wide or too_sparse or (ends_sentence and candidate_duration_ms > 1200):
            flush()
        current.append(word)
    flush()
    before_coherence_count = len(subtitles)
    coherence_result = merge_coherent_subtitles(subtitles)
    normalized = normalize_subtitle_timing(coherence_result["subtitles"])
    second_pass_result = merge_coherent_subtitles(normalized)
    if second_pass_result["coherence_merged_count"]:
        normalized = normalize_subtitle_timing(second_pass_result["subtitles"])
    subtitles_from_aligned_words.last_stats = {
        "segmentation_before_count": before_coherence_count,
        "segmentation_after_count": len(normalized),
        "coherence_merged_count": coherence_result["coherence_merged_count"] + second_pass_result["coherence_merged_count"],
        "orphan_merged_count": coherence_result["orphan_merged_count"] + second_pass_result["orphan_merged_count"],
        "coherence_second_pass_merged_count": second_pass_result["coherence_merged_count"],
        "merge_settings": {
            "enabled": SUBTITLE_COHERENCE_MERGE,
            "max_chars": SUBTITLE_COHERENCE_MAX_CHARS,
            "max_duration_ms": SUBTITLE_COHERENCE_MAX_DURATION_MS,
            "max_gap_ms": SUBTITLE_COHERENCE_MAX_GAP_MS,
            "orphan_max_chars": SUBTITLE_ORPHAN_MAX_CHARS,
        },
    }
    return normalized


def subtitle_has_sentence_end(subtitle: srt.Subtitle) -> bool:
    return subtitle.content.strip().endswith((".", "?", "!", "。", "？", "！"))


def subtitle_looks_like_orphan(subtitle: srt.Subtitle) -> bool:
    text = subtitle.content.strip()
    if len(text) <= SUBTITLE_ORPHAN_MAX_CHARS:
        return True
    tokens = re.findall(r"[A-Za-z']+", text)
    return len(tokens) <= 3 and len(text) <= SUBTITLE_ORPHAN_MAX_CHARS + 8


def can_merge_subtitle_pair(left: srt.Subtitle, right: srt.Subtitle) -> tuple[bool, bool]:
    if not SUBTITLE_COHERENCE_MERGE:
        return False, False
    left_text = left.content.strip()
    right_text = right.content.strip()
    if not left_text or not right_text:
        return False, False
    if is_pure_vocal_filler(left_text) or is_pure_vocal_filler(right_text):
        return False, False
    gap_ms = (right.start - left.end).total_seconds() * 1000
    if gap_ms < -20 or gap_ms > SUBTITLE_COHERENCE_MAX_GAP_MS:
        return False, False
    combined = f"{left_text} {right_text}".strip()
    duration = max(0.001, (right.end - left.start).total_seconds())
    if len(combined) > SUBTITLE_COHERENCE_MAX_CHARS:
        return False, False
    if duration * 1000 > SUBTITLE_COHERENCE_MAX_DURATION_MS:
        return False, False
    if len(combined) / duration > SUBTITLE_MAX_CPS:
        return False, False
    orphan = subtitle_looks_like_orphan(right)
    continuation = not subtitle_has_sentence_end(left)
    return orphan or continuation, orphan


def merge_coherent_subtitles(subtitles: list[srt.Subtitle]) -> dict[str, Any]:
    if not SUBTITLE_COHERENCE_MERGE or len(subtitles) < 2:
        return {
            "subtitles": subtitles,
            "coherence_merged_count": 0,
            "orphan_merged_count": 0,
        }
    merged: list[srt.Subtitle] = []
    coherence_merged_count = 0
    orphan_merged_count = 0
    for subtitle in subtitles:
        if not merged:
            merged.append(subtitle)
            continue
        previous = merged[-1]
        should_merge, orphan = can_merge_subtitle_pair(previous, subtitle)
        if should_merge:
            merged[-1] = srt.Subtitle(
                index=previous.index,
                start=previous.start,
                end=subtitle.end,
                content=f"{previous.content.strip()} {subtitle.content.strip()}".strip(),
            )
            coherence_merged_count += 1
            if orphan:
                orphan_merged_count += 1
            continue
        merged.append(subtitle)
    for index, subtitle in enumerate(merged, start=1):
        subtitle.index = index
    return {
        "subtitles": merged,
        "coherence_merged_count": coherence_merged_count,
        "orphan_merged_count": orphan_merged_count,
    }


def normalize_subtitle_timing(subtitles: list[srt.Subtitle]) -> list[srt.Subtitle]:
    source_subtitles = sorted(subtitles, key=lambda item: (item.start, item.end))
    source_subtitles = handle_repeated_subtitle_runs(source_subtitles)
    ordered = merge_short_subtitles(source_subtitles)
    normalized: list[srt.Subtitle] = []
    for subtitle in ordered:
        start_seconds = max(0.0, subtitle.start.total_seconds())
        min_read_seconds = min(SUBTITLE_MAX_DURATION_MS / 1000, max(SUBTITLE_MIN_DURATION_MS / 1000, len(subtitle.content) / SUBTITLE_MAX_CPS))
        end_seconds = max(start_seconds + min_read_seconds, subtitle.end.total_seconds())
        if normalized:
            previous_end = normalized[-1].end.total_seconds()
            if start_seconds < previous_end + 0.02:
                start_seconds = previous_end + 0.02
            if end_seconds <= start_seconds:
                end_seconds = start_seconds + SUBTITLE_MIN_DURATION_MS / 1000
        normalized.append(
            srt.Subtitle(
                index=len(normalized) + 1,
                start=timedelta(seconds=start_seconds),
                end=timedelta(seconds=end_seconds),
                content=subtitle.content,
            )
        )
    for index, subtitle in enumerate(normalized, start=1):
        subtitle.index = index
    return normalized


def handle_repeated_subtitle_runs(subtitles: list[srt.Subtitle]) -> list[srt.Subtitle]:
    if SUBTITLE_REPEAT_HANDLING == "keep":
        return subtitles

    handled: list[srt.Subtitle] = []
    index = 0
    while index < len(subtitles):
        current = subtitles[index]
        if not is_repeated_subtitle_candidate(current):
            handled.append(current)
            index += 1
            continue

        run_start = index
        index += 1
        while index < len(subtitles) and is_repeated_subtitle_candidate(subtitles[index]):
            index += 1
        repeated_run = subtitles[run_start:index]
        span_ms = (repeated_run[-1].end - repeated_run[0].start).total_seconds() * 1000
        should_handle_run = (
            len(repeated_run) >= SUBTITLE_REPEAT_MIN_BLOCKS
            and span_ms >= SUBTITLE_REPEAT_MIN_SPAN_MS
        ) or any(is_long_vocal_filler(subtitle) for subtitle in repeated_run)
        if not should_handle_run:
            handled.extend(repeated_run)
            continue
        if SUBTITLE_REPEAT_HANDLING == "drop":
            continue
        end = min(
            repeated_run[-1].end,
            repeated_run[0].start + timedelta(milliseconds=SUBTITLE_MAX_DURATION_MS),
        )
        handled.append(
            srt.Subtitle(
                index=len(handled) + 1,
                start=repeated_run[0].start,
                end=end,
                content=SUBTITLE_REPEAT_COMPRESS_TEXT,
            )
        )

    for output_index, subtitle in enumerate(handled, start=1):
        subtitle.index = output_index
    return handled


def is_repeated_subtitle_candidate(subtitle: srt.Subtitle) -> bool:
    return is_repeated_hallucination(subtitle.content) or is_long_vocal_filler(subtitle)


def is_long_vocal_filler(subtitle: srt.Subtitle) -> bool:
    duration_ms = (subtitle.end - subtitle.start).total_seconds() * 1000
    return duration_ms >= SUBTITLE_REPEAT_MIN_SPAN_MS and is_pure_vocal_filler(subtitle.content)


def is_pure_vocal_filler(text: str) -> bool:
    tokens = re.findall(r"[A-Za-z']+", text.lower())
    if not tokens:
        return False
    filler_tokens = {"ha", "haha", "cha", "chacha", "ja", "jaja"}
    return all(token.strip("'") in filler_tokens for token in tokens)


def is_repeated_hallucination(text: str) -> bool:
    tokens = re.findall(r"[A-Za-z']+", text.lower())
    if len(tokens) < SUBTITLE_REPEAT_TOKEN_LIMIT:
        return False
    counts: dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    repeated = max(counts.values(), default=0)
    return repeated >= SUBTITLE_REPEAT_TOKEN_LIMIT and repeated / max(1, len(tokens)) >= 0.75


def merge_short_subtitles(subtitles: list[srt.Subtitle]) -> list[srt.Subtitle]:
    merged: list[srt.Subtitle] = []
    index = 0
    while index < len(subtitles):
        current = subtitles[index]
        text = current.content.strip()
        if (
            not is_pure_vocal_filler(text)
            and len(text) <= SUBTITLE_MERGE_SHORT_CHARS
            and index + 1 < len(subtitles)
            and not is_pure_vocal_filler(subtitles[index + 1].content)
            and (subtitles[index + 1].start - current.end).total_seconds() * 1000 <= SUBTITLE_MAX_GAP_MS
        ):
            next_item = subtitles[index + 1]
            combined = f"{text} {next_item.content.strip()}".strip()
            if len(combined) <= SUBTITLE_MAX_CHARS:
                merged.append(
                    srt.Subtitle(
                        index=len(merged) + 1,
                        start=current.start,
                        end=next_item.end,
                        content=combined,
                    )
                )
                index += 2
                continue
        if merged and len(text) <= SUBTITLE_MERGE_SHORT_CHARS and not is_pure_vocal_filler(text):
            previous = merged[-1]
            gap_ms = (current.start - previous.end).total_seconds() * 1000
            combined = f"{previous.content.strip()} {text}".strip()
            if (
                gap_ms <= SUBTITLE_MAX_GAP_MS
                and len(combined) <= SUBTITLE_MAX_CHARS
                and not is_pure_vocal_filler(previous.content)
            ):
                merged[-1] = srt.Subtitle(
                    index=previous.index,
                    start=previous.start,
                    end=current.end,
                    content=combined,
                )
                index += 1
                continue
        merged.append(
            srt.Subtitle(
                index=len(merged) + 1,
                start=current.start,
                end=current.end,
                content=current.content,
            )
        )
        index += 1
    return merged


def subtitle_gap_diagnostics(subtitles: list[srt.Subtitle], threshold_seconds: float | None = None) -> list[dict[str, Any]]:
    threshold = WHISPER_GAP_THRESHOLD_SECONDS if threshold_seconds is None else threshold_seconds
    gaps: list[dict[str, Any]] = []
    ordered = sorted(subtitles, key=lambda item: item.start)
    for left, right in zip(ordered, ordered[1:]):
        gap = (right.start - left.end).total_seconds()
        if gap <= threshold:
            continue
        gaps.append(
            {
                "after_index": left.index,
                "before_index": right.index,
                "start": left.end.total_seconds(),
                "end": right.start.total_seconds(),
                "duration": gap,
                "left_text": left.content,
                "right_text": right.content,
                "suspicious": True,
            }
        )
    return gaps


def build_timing_diagnostics(
    subtitles: list[srt.Subtitle],
    *,
    words: list[dict[str, Any]],
    language: str,
    model_name: str,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for subtitle in subtitles:
        duration = max(0.001, (subtitle.end - subtitle.start).total_seconds())
        chars = len(subtitle.content)
        cps = chars / duration
        items.append(
            {
                "index": subtitle.index,
                "start": subtitle.start.total_seconds(),
                "end": subtitle.end.total_seconds(),
                "duration": duration,
                "chars": chars,
                "cps": cps,
                "too_fast": cps > SUBTITLE_MAX_CPS,
                "too_long": duration * 1000 > SUBTITLE_MAX_DURATION_MS,
                "repeated_like": is_repeated_hallucination(subtitle.content),
                "text": subtitle.content,
            }
        )
    gaps = subtitle_gap_diagnostics(subtitles)
    return {
        "language": language,
        "model": model_name,
        "word_timestamps": bool(words),
        "word_count": len(words),
        "subtitle_count": len(subtitles),
        "gap_threshold_seconds": WHISPER_GAP_THRESHOLD_SECONDS,
        "suspicious_gap_count": len(gaps),
        "max_gap_seconds": max((gap["duration"] for gap in gaps), default=0.0),
        "settings": {
            "tail_padding_ms": SUBTITLE_TAIL_PADDING_MS,
            "max_duration_ms": SUBTITLE_MAX_DURATION_MS,
            "max_gap_ms": SUBTITLE_MAX_GAP_MS,
            "max_chars": SUBTITLE_MAX_CHARS,
                "max_cps": SUBTITLE_MAX_CPS,
                "min_duration_ms": SUBTITLE_MIN_DURATION_MS,
                "merge_short_chars": SUBTITLE_MERGE_SHORT_CHARS,
                "coherence_merge": SUBTITLE_COHERENCE_MERGE,
                "coherence_max_chars": SUBTITLE_COHERENCE_MAX_CHARS,
                "coherence_max_duration_ms": SUBTITLE_COHERENCE_MAX_DURATION_MS,
                "coherence_max_gap_ms": SUBTITLE_COHERENCE_MAX_GAP_MS,
                "orphan_max_chars": SUBTITLE_ORPHAN_MAX_CHARS,
                "repeat_token_limit": SUBTITLE_REPEAT_TOKEN_LIMIT,
                "drop_repeated_hallucinations": SUBTITLE_DROP_REPEATED_HALLUCINATIONS,
            "repeat_handling": SUBTITLE_REPEAT_HANDLING,
            "repeat_compress_text": SUBTITLE_REPEAT_COMPRESS_TEXT,
            "repeat_min_span_ms": SUBTITLE_REPEAT_MIN_SPAN_MS,
            "repeat_min_blocks": SUBTITLE_REPEAT_MIN_BLOCKS,
        },
        "gaps": gaps,
        "items": items,
    }


def decode_audio_for_whisper(source_path: Path) -> tuple[np.ndarray, int]:
    temp_wav: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
            temp_wav = Path(temp_file.name)
        cmd = [
            FFMPEG_BIN,
            "-y",
            "-i",
            str(source_path),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-vn",
            "-f",
            "wav",
            str(temp_wav),
        ]
        run_command(cmd)
        with wave.open(str(temp_wav), "rb") as wav_file:
            sample_rate = wav_file.getframerate()
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            frames = wav_file.readframes(wav_file.getnframes())
        if channels != 1:
            raise RuntimeError(f"unexpected channel count in extracted audio: {channels}")
        if sample_width == 2:
            audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        elif sample_width == 4:
            audio = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
        else:
            raise RuntimeError(f"unsupported sample width in extracted audio: {sample_width}")
        return audio, sample_rate
    finally:
        if temp_wav is not None:
            try:
                temp_wav.unlink(missing_ok=True)
            except Exception:
                pass


def detect_cuda_runtime() -> dict[str, Any]:
    diagnostics: dict[str, Any] = {
        "available": False,
        "device_count": 0,
        "supported_compute_types": [],
        "error": None,
    }
    try:
        import ctranslate2  # type: ignore
    except Exception as exc:
        diagnostics["error"] = str(exc)
        return diagnostics

    try:
        diagnostics["device_count"] = int(ctranslate2.get_cuda_device_count())
        if diagnostics["device_count"] > 0:
            diagnostics["available"] = True
            diagnostics["supported_compute_types"] = list(ctranslate2.get_supported_compute_types("cuda"))
    except Exception as exc:
        diagnostics["error"] = str(exc)
    return diagnostics


def resolve_whisper_runtime(model_name: str) -> dict[str, Any]:
    backend = WHISPER_BACKEND or "auto"
    if backend not in {"auto", "cli", "faster-whisper"}:
        raise ValueError(f"unsupported WHISPER_BACKEND: {backend}")

    cuda_info = detect_cuda_runtime()
    requested_device = WHISPER_DEVICE or "auto"
    if requested_device == "cuda" and not cuda_info.get("available"):
        raise RuntimeError("WHISPER_DEVICE=cuda requested but CUDA runtime is not available")
    device = requested_device
    if device == "auto":
        device = "cuda" if cuda_info.get("available") else "cpu"
    compute_type = WHISPER_COMPUTE_TYPE or ("float16" if device == "cuda" else "int8")

    return {
        "backend": backend,
        "model_name": model_name,
        "device": device,
        "device_index": WHISPER_DEVICE_INDEX,
        "compute_type": compute_type,
        "cpu_threads": WHISPER_CPU_THREADS,
        "num_workers": WHISPER_NUM_WORKERS,
        "cuda": cuda_info,
    }


def resolve_whisper_model_ref(model_name: str) -> str:
    requested = model_name.strip() or DEFAULT_WHISPER_MODEL
    local_candidates = [
        DATA_DIR / "models" / f"faster-whisper-{requested}",
        DATA_DIR / "models" / requested,
    ]
    for candidate in local_candidates:
        if (candidate / "model.bin").exists():
            return str(candidate)
    return requested


def whisper_model_status(model_name: str) -> dict[str, Any]:
    requested = model_name.strip() or DEFAULT_WHISPER_MODEL
    if DESKTOP:
        from app.desktop_models import status
        return status(DATA_DIR, requested)
    local_candidates = [
        DATA_DIR / "models" / f"faster-whisper-{requested}",
        DATA_DIR / "models" / requested,
    ]
    local_path = next((candidate for candidate in local_candidates if (candidate / "model.bin").is_file()), None)
    return {
        "name": requested,
        "available": local_path is not None,
        "path": str(local_path) if local_path else None,
        "preferred_path": str(local_candidates[0]),
    }


def transcribe_video(
    job_id: str,
    source_path: Path,
    *,
    language: str = "en",
    model_name: str | None = None,
    inference_mode: str | None = None,
    progress_callback: Callable[[int, str, str | None], None] | None = None,
) -> Path:
    whisper_cli = WHISPER_BIN or shutil.which("whisper") or ""
    requested_model = (model_name or WHISPER_MODEL).strip() or DEFAULT_WHISPER_MODEL
    mode = (inference_mode or WHISPER_INFERENCE_MODE).strip() or WHISPER_INFERENCE_MODE
    if DESKTOP and not whisper_model_status(requested_model)["available"]:
        raise RuntimeError(f"本地 Whisper {requested_model} 未准备好，请在「设置 → 本地资源与环境」下载模型后重试。")
    runtime = {"backend": "faster-whisper"} if DESKTOP else resolve_whisper_runtime(requested_model)

    if runtime["backend"] == "cli":
        if not whisper_cli:
            raise RuntimeError("WHISPER_BACKEND=cli but whisper CLI is not installed")
        output_dir = job_dir(job_id) / "transcript"
        output_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            whisper_cli,
            str(source_path),
            "--model",
            requested_model,
            "--language",
            language,
            "--output_format",
            "srt",
            "--output_dir",
            str(output_dir),
        ]
        run_command(cmd, log_dir=job_dir(job_id), log_name="whisper-cli")
        produced = list(output_dir.glob("*.srt"))
        if not produced:
            raise RuntimeError("whisper finished but no .srt file was produced")
        return produced[0]

    try:
        job_dir(job_id).mkdir(parents=True, exist_ok=True)
        worker_exe = Path(sys.executable).with_name("MediaWhisper.exe")
        worker = [str(worker_exe)] if DESKTOP and getattr(sys, "frozen", False) else [
            WHISPER_WORKER_PYTHON or sys.executable, "-m", "app.whisper_worker"
        ]
        cmd = [
            *worker,
            "--job-id",
            job_id,
            "--source",
            str(source_path),
            "--language",
            language,
            "--model",
            requested_model,
            "--inference-mode",
            mode,
        ]
        def handle_whisper_line(line: str) -> None:
            if not progress_callback:
                return
            if not line.startswith("WHISPER_PROGRESS\t"):
                return
            parts = line.split("\t", 2)
            if len(parts) < 3:
                return
            progress_callback(clamp_percent(parts[1]), parts[2].strip(), line)

        if DESKTOP:
            from app.desktop_config import worker_environment
            env = worker_environment()
            if mode == "gpu_only" and env["WHISPER_DEVICE"] != "cuda":
                raise RuntimeError("严格 GPU 模式需要可用且已启用的 NVIDIA 转录环境。请到设置检测。")
        else:
            env = None
        try:
            run_command_streaming(
                cmd, cwd=ROOT_DIR, log_dir=job_dir(job_id), log_name="whisper",
                on_stdout_line=handle_whisper_line, on_stderr_line=handle_whisper_line, env=env,
            )
        except RuntimeError:
            if mode == "gpu_only" or not env or env.get("WHISPER_DEVICE") != "cuda":
                raise
            if progress_callback:
                progress_callback(5, "GPU 转录失败，改用 CPU 重试", None)
            env["WHISPER_DEVICE"] = "cpu"
            env["WHISPER_COMPUTE_TYPE"] = ""
            env.pop("MEDIA_GPU_DLL_DIR", None)
            run_command_streaming(
                cmd, cwd=ROOT_DIR, log_dir=job_dir(job_id), log_name="whisper-cpu",
                on_stdout_line=handle_whisper_line, on_stderr_line=handle_whisper_line, env=env,
            )
        path = artifact_path(job_id, "english.srt")
        if not path.exists():
            raise RuntimeError("faster-whisper worker finished but no english.srt was produced")
        return path
    except Exception as exc:
        if DESKTOP:
            if mode == "gpu_only":
                raise RuntimeError("严格 GPU 转录失败，任务已停止。请检查 NVIDIA 环境和显存，详情见本地 Whisper 日志。") from exc
            raise RuntimeError("Whisper 转录失败。请在设置中检查本地模型和运行环境，详情见本地 Whisper 日志。") from exc
        if runtime["backend"] == "auto" and whisper_cli:
            output_dir = job_dir(job_id) / "transcript"
            output_dir.mkdir(parents=True, exist_ok=True)
            cmd = [
                whisper_cli,
                str(source_path),
                "--model",
                requested_model,
                "--language",
                language,
                "--output_format",
                "srt",
                "--output_dir",
                str(output_dir),
            ]
            run_command(cmd, log_dir=job_dir(job_id), log_name="whisper-cli")
            produced = list(output_dir.glob("*.srt"))
            if not produced:
                raise RuntimeError("whisper finished but no .srt file was produced")
            return produced[0]
        if ALLOW_PLACEHOLDER_ARTIFACTS:
            return placeholder_srt(job_id, source_path.stem, source_path.name)
        raise RuntimeError(
            f"no usable whisper backend available for model={requested_model}: {exc}"
        ) from exc
