from __future__ import annotations

import argparse
import json
from pathlib import Path

import os

# Keep handles alive for transitive CUDA DLL loading on Windows.
_cuda_dll_handles = []
if os.name == "nt" and os.getenv("MEDIA_GPU_DLL_DIR"):
    _cuda_dll_handles.append(os.add_dll_directory(os.environ["MEDIA_GPU_DLL_DIR"]))

from faster_whisper import BatchedInferencePipeline, WhisperModel

from app.main import (
    artifact_path,
    decode_audio_for_whisper,
    job_dir,
    resolve_whisper_model_ref,
    whisper_model_status,
    DESKTOP,
    resolve_whisper_runtime,
    build_timing_diagnostics,
    subtitles_from_aligned_words,
    subtitles_from_segments,
    WHISPER_BATCH_SIZE,
    WHISPER_BATCHED_INFERENCE,
    WHISPER_BEAM_SIZE,
    WHISPER_BEST_OF,
    WHISPER_COMPRESSION_RATIO_THRESHOLD,
    WHISPER_CONDITION_ON_PREVIOUS_TEXT,
    WHISPER_LOG_PROB_THRESHOLD,
    WHISPER_NO_SPEECH_THRESHOLD,
    WHISPER_VAD_ENABLED,
    WHISPER_VAD_PADDING_MS,
    WHISPER_WORD_TIMESTAMPS,
    write_transcription_artifacts,
)


def progress(percent: int, message: str) -> None:
    print(f"WHISPER_PROGRESS\t{max(0, min(100, int(percent)))}\t{message}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--language", default="en")
    parser.add_argument("--model", default="small")
    parser.add_argument("--inference-mode", default="standard", choices=["standard", "batched", "auto_repair"])
    args = parser.parse_args()

    job_dir(args.job_id).mkdir(parents=True, exist_ok=True)
    runtime = resolve_whisper_runtime(args.model)
    model_ref = resolve_whisper_model_ref(args.model)
    if DESKTOP:
        status = whisper_model_status(args.model)
        if status["available"]:
            model_ref = status["path"]
        else:
            from faster_whisper.utils import download_model
            progress(5, f"正在下载 Whisper {args.model}，首次转录需要联网")
            model_ref = download_model(args.model)
    progress(5, f"loading faster-whisper model {args.model}")
    model = WhisperModel(
        model_ref,
        device=str(runtime["device"]),
        device_index=int(runtime["device_index"]),
        compute_type=str(runtime["compute_type"]),
        cpu_threads=int(runtime["cpu_threads"]),
        num_workers=int(runtime["num_workers"]),
    )
    progress(18, "decoding audio for whisper")
    audio, _sample_rate = decode_audio_for_whisper(Path(args.source))
    progress(28, "audio decoded")
    effective_vad = WHISPER_VAD_ENABLED and args.inference_mode != "standard"
    kwargs = {
        "language": None if args.language == "auto" else args.language,
        "word_timestamps": WHISPER_WORD_TIMESTAMPS,
        "vad_filter": effective_vad,
        "beam_size": WHISPER_BEAM_SIZE,
        "best_of": WHISPER_BEST_OF,
        "temperature": 0.0,
        "condition_on_previous_text": WHISPER_CONDITION_ON_PREVIOUS_TEXT,
        "compression_ratio_threshold": WHISPER_COMPRESSION_RATIO_THRESHOLD,
        "log_prob_threshold": WHISPER_LOG_PROB_THRESHOLD,
        "no_speech_threshold": WHISPER_NO_SPEECH_THRESHOLD,
        "without_timestamps": False,
    }
    if effective_vad:
        kwargs["vad_parameters"] = {
            "min_silence_duration_ms": 500,
            "speech_pad_ms": WHISPER_VAD_PADDING_MS,
        }

    def collect_transcription(segments_iter, info):
        segments: list[dict] = []
        words: list[dict] = []
        duration = 0.0
        last_progress = 35
        for segment in segments_iter:
            if not duration:
                duration = float(getattr(info, "duration", 0.0) or 0.0)
            segment_words: list[dict] = []
            for word in getattr(segment, "words", None) or []:
                item = {
                    "start": float(word.start) if word.start is not None else float(segment.start),
                    "end": float(word.end) if word.end is not None else float(segment.end),
                    "word": str(word.word or "").strip(),
                    "probability": float(getattr(word, "probability", 0.0) or 0.0),
                }
                if item["word"]:
                    segment_words.append(item)
                    words.append(item)
            segments.append(
                {
                    "start": float(segment.start),
                    "end": float(segment.end),
                    "text": str(segment.text or "").strip(),
                    "words": segment_words,
                }
            )
            if duration > 0:
                current = min(92, max(35, int(35 + (float(segment.end) / duration) * 55)))
                if current >= last_progress + 2:
                    progress(current, f"transcribed {float(segment.end):.1f}s / {duration:.1f}s")
                    last_progress = current
        return segments, words

    def run_standard_transcription():
        progress(35, "starting standard transcription")
        segments_iter, info = model.transcribe(audio, **kwargs)
        return (*collect_transcription(segments_iter, info), info)

    def run_batched_transcription():
        if not WHISPER_BATCHED_INFERENCE:
            raise RuntimeError("batched inference disabled")
        progress(35, f"starting batched transcription batch_size={WHISPER_BATCH_SIZE}")
        batched_model = BatchedInferencePipeline(model)
        segments_iter, info = batched_model.transcribe(audio, batch_size=WHISPER_BATCH_SIZE, **kwargs)
        return (*collect_transcription(segments_iter, info), info)

    def count_suspicious_gaps(candidate_segments: list[dict], candidate_words: list[dict], info) -> tuple[int, float]:
        subtitles = subtitles_from_aligned_words(candidate_words) if candidate_words else subtitles_from_segments(candidate_segments)
        diagnostics = build_timing_diagnostics(
            subtitles,
            words=candidate_words,
            language=str(getattr(info, "language", args.language) or args.language),
            model_name=args.model,
        )
        return int(diagnostics.get("suspicious_gap_count") or 0), float(diagnostics.get("max_gap_seconds") or 0.0)

    transcribe_mode = "standard"
    fallback_error = ""
    repair_reason = ""
    try:
        if args.inference_mode == "standard":
            segments, words, info = run_standard_transcription()
        else:
            segments, words, info = run_batched_transcription()
            transcribe_mode = "batched"
            if args.inference_mode == "auto_repair":
                gap_count, max_gap = count_suspicious_gaps(segments, words, info)
                progress(93, f"detected {gap_count} suspicious gaps, max gap {max_gap:.1f}s")
                if gap_count:
                    repair_reason = f"batched output had {gap_count} suspicious gaps; reran standard transcription"
                    progress(94, "suspicious gaps detected, rerunning standard transcription")
                    segments, words, info = run_standard_transcription()
                    transcribe_mode = "auto_repair_standard"
    except Exception as exc:
        if args.inference_mode in {"batched", "auto_repair"}:
            fallback_error = str(exc)
            progress(36, "batched transcription failed, falling back to standard")
            segments, words, info = run_standard_transcription()
        else:
            raise
    progress(95, "writing subtitle artifacts")
    srt_path, diagnostics_path = write_transcription_artifacts(
        args.job_id,
        segments=segments,
        words=words,
        language=str(getattr(info, "language", args.language) or args.language),
        model_name=args.model,
    )
    try:
        diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
        gap_count = int(diagnostics.get("suspicious_gap_count") or 0)
        max_gap = float(diagnostics.get("max_gap_seconds") or 0.0)
        if gap_count:
            progress(96, f"detected {gap_count} suspicious gaps, max gap {max_gap:.1f}s")
    except Exception:
        pass
    artifact_path(args.job_id, "transcribe_runtime.json").write_text(
        json.dumps(
            {
                "language": str(getattr(info, "language", args.language) or args.language),
                "language_probability": float(getattr(info, "language_probability", 0.0) or 0.0),
                "duration": float(getattr(info, "duration", 0.0) or 0.0),
                "word_timestamps": WHISPER_WORD_TIMESTAMPS,
                "vad_enabled": effective_vad,
                "batched_inference": WHISPER_BATCHED_INFERENCE,
                "requested_inference_mode": args.inference_mode,
                "actual_mode": transcribe_mode,
                "batch_size": WHISPER_BATCH_SIZE,
                "beam_size": WHISPER_BEAM_SIZE,
                "best_of": WHISPER_BEST_OF,
                "condition_on_previous_text": WHISPER_CONDITION_ON_PREVIOUS_TEXT,
                "compression_ratio_threshold": WHISPER_COMPRESSION_RATIO_THRESHOLD,
                "log_prob_threshold": WHISPER_LOG_PROB_THRESHOLD,
                "no_speech_threshold": WHISPER_NO_SPEECH_THRESHOLD,
                "device": str(runtime["device"]),
                "compute_type": str(runtime["compute_type"]),
                "fallback_error": fallback_error,
                "repair_reason": repair_reason,
                "srt": str(srt_path.name),
                "diagnostics": str(diagnostics_path.name),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    progress(100, "transcription artifacts ready")


if __name__ == "__main__":
    main()
