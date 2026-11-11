from __future__ import annotations

# ruff: noqa: F821
"""Subtitle translation.

Executed inside app.main so callers and tests keep patching that module.
"""

def split_srt_blocks(text: str) -> list[srt.Subtitle]:
    return list(srt.parse(text))


def build_translation_system_prompt(target_lang: str, context_note: str = "", glossary: str = "") -> str:
    parts = [
        f"Translate subtitles into concise {target_lang} output.",
        "Preserve meaning, keep one output line per input line, and do not add commentary.",
        "Use any supplied domain context or glossary only when it is relevant to the sentence.",
        "Do not force glossary entries if they conflict with the sentence meaning, and never translate or output the context itself.",
    ]
    note = clean_translation_text(context_note)
    terms = clean_translation_text(glossary)
    if note:
        parts.append(f"Domain context for reference only:\n{note}")
    if terms:
        parts.append(f"Glossary for reference only:\n{terms}")
    return "\n\n".join(parts)


def build_translation_json_system_prompt(target_lang: str, context_note: str = "", glossary: str = "") -> str:
    parts = [
        "You are a subtitle translation engine.",
        "Return json only.",
        f"Translate subtitles into concise {target_lang} output.",
        "The response must be a valid json object with this exact shape:",
        '{"items":[{"index":1,"translation":"..."},{"index":2,"translation":"..."}]}',
        "Keep one json item per input line, preserve the index, and do not add explanations, markdown, or code fences.",
        "If a source line is empty, return an empty translation string for that item.",
    ]
    note = clean_translation_text(context_note)
    terms = clean_translation_text(glossary)
    if note:
        parts.append(f"Domain context for reference only:\n{note}")
    if terms:
        parts.append(f"Glossary for reference only:\n{terms}")
    return "\n\n".join(parts)


def build_translation_json_user_prompt(texts: list[str], target_lang: str) -> str:
    example_input = "1. Which is the longest river in the world?\n2. The Nile River."
    example_output = json.dumps(
        {
            "items": [
                {"index": 1, "translation": "Which river is the longest in the world?"},
                {"index": 2, "translation": "The Nile River."},
            ]
        },
        ensure_ascii=False,
        indent=2,
    )
    input_lines = "\n".join(f"{idx + 1}. {line}" for idx, line in enumerate(texts))
    return (
        f"Translate the following subtitle lines into {target_lang} and return json only.\n\n"
        f"EXAMPLE INPUT:\n{example_input}\n\n"
        f"EXAMPLE JSON OUTPUT:\n{example_output}\n\n"
        f"INPUT:\n{input_lines}"
    )


def _extract_json_object_text(content: str) -> str:
    text = (content or "").strip()
    if not text:
        raise ValueError("empty translation content")
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    if text.startswith("{") and text.endswith("}"):
        return text
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    raise ValueError("translation content does not contain a json object")


def _normalize_translation_text(value: Any) -> str:
    text = str(value or "")
    text = text.replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _estimate_translation_max_tokens(texts: list[str]) -> int:
    char_count = sum(len(text) for text in texts)
    line_count = max(1, len(texts))
    estimate = int(char_count * 2.2) + line_count * 48 + 256
    return max(256, min(8192, estimate))


def _validate_translation_items(data: Any, texts: list[str]) -> list[str]:
    if not isinstance(data, dict):
        raise ValueError("translation payload is not a json object")
    items = data.get("items")
    if not isinstance(items, list):
        raise ValueError("translation json missing items array")

    translated: dict[int, str] = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("translation items must be json objects")
        index = item.get("index")
        if isinstance(index, str) and index.isdigit():
            index = int(index)
        if not isinstance(index, int):
            raise ValueError("translation item missing numeric index")
        if index < 1 or index > len(texts):
            raise ValueError(f"translation item index out of range: {index}")
        translation = _normalize_translation_text(item.get("translation"))
        if index in translated:
            raise ValueError(f"duplicate translation item index: {index}")
        translated[index] = translation

    if len(translated) != len(texts):
        raise ValueError(
            f"translation json returned {len(translated)} items for {len(texts)} inputs"
        )

    ordered: list[str] = []
    for idx, source_text in enumerate(texts, start=1):
        translation = translated.get(idx, "")
        if not translation:
            translation = source_text
        ordered.append(translation)
    return ordered


def _translate_lines_via_provider(
    texts: list[str],
    target_lang: str,
    *,
    model_name: str | None = None,
    context_note: str = "",
    glossary: str = "",
) -> list[str]:
    requested_model = (model_name or TRANSLATE_MODEL).strip()
    if not (TRANSLATE_PROVIDER and TRANSLATE_API_BASE and requested_model and TRANSLATE_API_KEY):
        raise RuntimeError(
            "translation provider is not configured "
            f"(provider={TRANSLATE_PROVIDER!r}, api_base={TRANSLATE_API_BASE!r}, "
            f"model={requested_model!r}, key_set={bool(TRANSLATE_API_KEY)})"
        )

    prompt = build_translation_json_user_prompt(texts, target_lang)
    payload = {
        "model": requested_model,
        "messages": [
            {
                "role": "system",
                "content": build_translation_json_system_prompt(target_lang, context_note, glossary),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": _estimate_translation_max_tokens(texts),
        "response_format": {"type": "json_object"},
    }
    with TRANSLATE_PROMPT_SEMAPHORE:
        with httpx.Client(timeout=120) as client:
            response = client.post(
                f"{TRANSLATE_API_BASE.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {TRANSLATE_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            choice = (data.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            content = str(message.get("content") or "").strip()
    json_text = _extract_json_object_text(content)
    parsed = json.loads(json_text)
    return _validate_translation_items(parsed, texts)


def _translate_lines_recursive(
    texts: list[str],
    target_lang: str,
    *,
    model_name: str | None = None,
    context_note: str = "",
    glossary: str = "",
) -> list[str]:
    if not texts:
        return []
    try:
        return _translate_lines_via_provider(
            texts,
            target_lang,
            model_name=model_name,
            context_note=context_note,
            glossary=glossary,
        )
    except Exception as error:
        if DESKTOP and isinstance(error, (httpx.TransportError, httpx.HTTPStatusError)):
            raise
        if len(texts) > 1:
            midpoint = max(1, len(texts) // 2)
            left = _translate_lines_recursive(
                texts[:midpoint],
                target_lang,
                model_name=model_name,
                context_note=context_note,
                glossary=glossary,
            )
            right = _translate_lines_recursive(
                texts[midpoint:],
                target_lang,
                model_name=model_name,
                context_note=context_note,
                glossary=glossary,
            )
            return left + right
        if DESKTOP:
            raise RuntimeError("DeepSeek 没有返回有效译文，请检查模型配置后重试") from error
        if ALLOW_PLACEHOLDER_ARTIFACTS:
            source = texts[0] if texts else ""
            return [f"（{target_lang}）{source}" if source else ""]
        return [texts[0]]


def translate_lines(
    texts: list[str],
    target_lang: str,
    *,
    model_name: str | None = None,
    context_note: str = "",
    glossary: str = "",
) -> list[str]:
    if not texts:
        return []

    return _translate_lines_recursive(
        texts,
        target_lang,
        model_name=model_name,
        context_note=context_note,
        glossary=glossary,
    )


def translate_srt(
    job_id: str,
    english_srt_path: Path,
    *,
    target_lang: str = DEFAULT_TARGET_LANG,
    model_name: str | None = None,
    context_note: str = "",
    glossary: str = "",
    progress_callback: Callable[[int, str, str | None], None] | None = None,
) -> Path:
    if progress_callback:
        progress_callback(8, "reading source subtitles", None)
    source_text = english_srt_path.read_text(encoding="utf-8")
    subtitles = split_srt_blocks(source_text)
    texts = [item.content for item in subtitles]
    chunk_size = 40
    chunks = [
        (index, texts[offset : offset + chunk_size])
        for index, offset in enumerate(range(0, len(texts), chunk_size))
    ]
    translated_chunks: list[list[str] | None] = [None] * len(chunks)
    completed_chunks = 0
    max_workers = min(TRANSLATE_PROMPT_CONCURRENCY, max(1, len(chunks)))

    def translate_chunk(chunk_texts: list[str]) -> list[str]:
        return _translate_lines_recursive(
            chunk_texts,
            target_lang,
            model_name=model_name,
            context_note=context_note,
            glossary=glossary,
        )

    if chunks:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_map = {
                pool.submit(translate_chunk, chunk_texts): (chunk_index, chunk_texts)
                for chunk_index, chunk_texts in chunks
            }
            for future in as_completed(future_map):
                chunk_index, chunk_texts = future_map[future]
                translated_chunks[chunk_index] = future.result()
                completed_chunks += 1
                if progress_callback:
                    start_line = chunk_index * chunk_size + 1
                    end_line = start_line + len(chunk_texts) - 1
                    progress = 12 + int(76 * completed_chunks / max(1, len(chunks)))
                    progress_callback(
                        progress,
                        f"translating subtitles {start_line}-{end_line} of {len(texts)}",
                        None,
                    )
    translated_texts = [line for chunk in translated_chunks if chunk for line in chunk]
    if progress_callback:
        progress_callback(90, "merging translated subtitles", None)
    bilingual: list[srt.Subtitle] = []
    for index, subtitle in enumerate(subtitles, start=1):
        translation = translated_texts[index - 1] if index - 1 < len(translated_texts) else ""
        content = subtitle.content.strip()
        if translation and translation != content:
            content = f"{content}\n{translation}"
        bilingual.append(
            srt.Subtitle(
                index=index,
                start=subtitle.start,
                end=subtitle.end,
                content=content,
            )
        )
    path = artifact_path(job_id, "bilingual.srt")
    path.write_text(srt.compose(bilingual), encoding="utf-8")
    if progress_callback:
        progress_callback(100, "translation file ready", None)
    return path
