# Dify workflow import notes

This folder contains the workflow definitions for the YouTube media pipeline.
The current entrypoint is the visual main pipeline:

- `youtube_main_pipeline_workflow.json`

The older submit/query split files are kept only for reference and rollback:

- `youtube_submit_workflow.json`
- `youtube_query_workflow.json`

They are designed for the same Dify environment described in the desktop manual:

- Dify is running in the WSL Docker stack.
- The local media service is exposed on `http://127.0.0.1:8090` for host access.
- Dify HTTP Request nodes call `http://172.18.0.1:8090` from Docker.

## Workflow split

### Main pipeline workflow

This is the upgraded visual pipeline for media processing and progress
inspection:

- submit download -> poll download -> submit transcribe -> poll transcribe
  -> submit translate -> poll translate -> submit burn -> poll burn

Input:

- `youtube_url`
- `rights_confirmed`
- `target_lang`
- `whisper_model`
- `translate_model`

Output:

- `source_video_url`
- `english_srt_url`
- `bilingual_srt_url`
- `final_video_url`
- `download_progress`
- `transcribe_progress`
- `translate_progress`
- `burn_progress`

Notes:

- Dify only orchestrates and polls. Heavy processing still runs in external
  operator APIs under `/stage-jobs/*`.
- Each loop stage surfaces a status, progress, result URL, and error message
  so the canvas and run log show per-step progress.
- The workflow trusts `rights_confirmed` as a user attestation flag. It does
  not try to infer copyright or authorization automatically.
- `whisper_model` is passed to the transcription stage so you can switch
  `small`/`medium`/`large-v3` without changing operator code.
- `translate_model` is passed to the translation stage so you can switch
  DeepSeek models from the Dify run panel while keeping the API key server-side.

## Assumption

The service trusts `rights_confirmed` as a user-attestation flag.
