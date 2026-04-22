from __future__ import annotations

import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dify_workflows" / "youtube_main_pipeline_workflow.json"
OPERATOR_BASE_URL = os.getenv("OPERATOR_BASE_URL", "http://172.17.144.1:8090").rstrip("/")
DIFY_STAGE_HOLD_SECONDS = {
    "download": 60,
    "transcribe": 60,
    "translate": 60,
    "burn": 60,
}
DIFY_STAGE_LOOP_COUNTS = {
    "download": 240,
    "transcribe": 480,
    "translate": 240,
    "burn": 360,
}


def stage_hold_seconds(stage_key: str) -> int:
    return DIFY_STAGE_HOLD_SECONDS[stage_key]


def stage_loop_count(stage_key: str) -> int:
    return DIFY_STAGE_LOOP_COUNTS[stage_key]


def node_base(
    node_id: str,
    node_type: str,
    title: str,
    x: float,
    y: float,
    width: int,
    height: int,
    data: dict,
    *,
    parent_id: str | None = None,
    z_index: int = 0,
) -> dict:
    node = {
        "id": node_id,
        "type": "custom" if node_type != "loop-start" else "custom-loop-start",
        "data": data,
        "position": {"x": x, "y": y},
        "positionAbsolute": {"x": x, "y": y},
        "sourcePosition": "right",
        "targetPosition": "left",
        "width": width,
        "height": height,
        "selected": False,
    }
    if parent_id is not None:
        node["parentId"] = parent_id
    if z_index:
        node["zIndex"] = z_index
    return node


def start_node() -> dict:
    return node_base(
        "start_node",
        "start",
        "开始",
        30,
        280,
        242,
        520,
        {
            "desc": "",
            "selected": False,
            "title": "开始",
            "type": "start",
            "variables": [
                {
                    "label": "Operator Batch ID",
                    "max_length": 128,
                    "options": [],
                    "required": False,
                    "type": "text-input",
                    "variable": "operator_batch_id",
                },
                {
                    "label": "Operator Item ID",
                    "max_length": 128,
                    "options": [],
                    "required": False,
                    "type": "text-input",
                    "variable": "operator_item_id",
                },
                {
                    "label": "来源类型",
                    "max_length": 16,
                    "options": ["youtube", "local"],
                    "required": False,
                    "type": "select",
                    "variable": "source_kind",
                },
                {
                    "label": "来源值",
                    "max_length": 2048,
                    "options": [],
                    "required": False,
                    "type": "text-input",
                    "variable": "source_value",
                },
                {
                    "label": "YouTube 链接",
                    "max_length": 2048,
                    "options": [],
                    "required": False,
                    "type": "text-input",
                    "variable": "youtube_url",
                },
                {
                    "label": "已确认素材可用",
                    "max_length": 16,
                    "options": ["true", "false"],
                    "required": True,
                    "type": "select",
                    "variable": "rights_confirmed",
                },
                {
                    "label": "目标语言",
                    "max_length": 32,
                    "options": [],
                    "required": False,
                    "type": "text-input",
                    "variable": "target_lang",
                },
                {
                    "label": "Whisper 模型",
                    "max_length": 32,
                    "options": ["tiny", "base", "small", "medium", "large-v3"],
                    "required": False,
                    "type": "select",
                    "variable": "whisper_model",
                },
                {
                    "label": "Whisper 转写模式",
                    "max_length": 32,
                    "options": ["standard", "auto_repair", "batched"],
                    "required": False,
                    "type": "select",
                    "variable": "whisper_inference_mode",
                },
                {
                    "label": "翻译模型",
                    "max_length": 64,
                    "options": ["deepseek-chat", "deepseek-reasoner"],
                    "required": False,
                    "type": "select",
                    "variable": "translate_model",
                },
                {
                    "label": "翻译上下文预设",
                    "max_length": 128,
                    "options": [],
                    "required": False,
                    "type": "text-input",
                    "variable": "translation_context_profile_id",
                },
                {
                    "label": "领域说明",
                    "max_length": 4000,
                    "options": [],
                    "required": False,
                    "type": "paragraph",
                    "variable": "translation_context_note",
                },
                {
                    "label": "术语表",
                    "max_length": 4000,
                    "options": [],
                    "required": False,
                    "type": "paragraph",
                    "variable": "translation_glossary",
                },
                {
                    "label": "领域说明 JSON",
                    "max_length": 8192,
                    "options": [],
                    "required": False,
                    "type": "paragraph",
                    "variable": "translation_context_note_json",
                },
                {
                    "label": "术语表 JSON",
                    "max_length": 8192,
                    "options": [],
                    "required": False,
                    "type": "paragraph",
                    "variable": "translation_glossary_json",
                },
                {
                    "label": "命名模式",
                    "max_length": 16,
                    "options": ["original", "sequence", "custom"],
                    "required": False,
                    "type": "select",
                    "variable": "output_name_mode",
                },
                {
                    "label": "命名前缀",
                    "max_length": 128,
                    "options": [],
                    "required": False,
                    "type": "text-input",
                    "variable": "output_name_prefix",
                },
                {
                    "label": "输出序号",
                    "max_length": 8,
                    "options": [],
                    "required": False,
                    "type": "number",
                    "variable": "output_index",
                },
                {
                    "label": "画幅",
                    "max_length": 16,
                    "options": ["source", "16:9", "9:16", "1:1"],
                    "required": False,
                    "type": "select",
                    "variable": "aspect_ratio",
                },
                {
                    "label": "下载清晰度",
                    "max_length": 16,
                    "options": ["best", "1080p", "1440p", "2160p"],
                    "required": False,
                    "type": "select",
                    "variable": "resolution",
                },
                {
                    "label": "帧率",
                    "max_length": 16,
                    "options": ["source", "30", "60"],
                    "required": False,
                    "type": "select",
                    "variable": "fps",
                },
                {
                    "label": "字幕字号",
                    "max_length": 16,
                    "options": ["auto", "small", "medium", "large"],
                    "required": False,
                    "type": "select",
                    "variable": "subtitle_font_size",
                },
                {
                    "label": "字幕颜色",
                    "max_length": 16,
                    "options": [],
                    "required": False,
                    "type": "text-input",
                    "variable": "subtitle_color",
                },
                {
                    "label": "字幕描边色",
                    "max_length": 16,
                    "options": [],
                    "required": False,
                    "type": "text-input",
                    "variable": "subtitle_outline_color",
                },
                {
                    "label": "字幕位置",
                    "max_length": 16,
                    "options": ["bottom", "middle", "top"],
                    "required": False,
                    "type": "select",
                    "variable": "subtitle_position",
                },
                {
                    "label": "字幕边距",
                    "max_length": 16,
                    "options": ["auto", "compact", "normal", "high"],
                    "required": False,
                    "type": "select",
                    "variable": "subtitle_margin",
                },
                {
                    "label": "字幕输出",
                    "max_length": 16,
                    "options": ["bilingual", "zh_only", "en_only"],
                    "required": False,
                    "type": "select",
                    "variable": "subtitle_output_mode",
                },
                {
                    "label": "字幕样式 JSON",
                    "max_length": 4096,
                    "options": [],
                    "required": False,
                    "type": "paragraph",
                    "variable": "subtitle_style",
                },
            ],
        },
    )


def http_node(
    node_id: str,
    title: str,
    desc: str,
    method: str,
    url: str,
    body: str | None = None,
    x: float = 0,
    y: float = 0,
    *,
    parent_id: str | None = None,
    loop_id: str | None = None,
) -> dict:
    payload = {
        "desc": desc,
        "title": title,
        "type": "http-request",
        "method": method,
        "url": url,
        "authorization": {"type": "no-auth", "config": None},
        "headers": "",
        "params": "",
        "timeout": {"connect": 10, "read": 120, "write": 60},
        "retry_config": {
            "enabled": True,
            "max_retries": 1,
            "retry_interval": 1000,
            "exponential_backoff": {"enabled": True, "multiplier": 2, "max_interval": 10000},
        },
        "ssl_verify": True,
        "variables": [],
    }
    if loop_id is not None:
        payload["loop_id"] = loop_id
        payload["isInLoop"] = True
    if body is not None:
        payload["body"] = {"type": "json", "data": body}
    else:
        payload["body"] = {"type": "none", "data": []}
    return node_base(node_id, "http-request", title, x, y, 244, 155, payload, parent_id=parent_id, z_index=1002 if loop_id else 0)


def loop_node(
    node_id: str,
    title: str,
    desc: str,
    start_node_id: str,
    loop_vars: list[dict],
    break_selector: list[str],
    x: float,
    y: float,
    *,
    loop_count: int = 100,
    width: int = 900,
    height: int = 220,
) -> dict:
    return node_base(
        node_id,
        "loop",
        title,
        x,
        y,
        width,
        height,
        {
            "desc": desc,
            "title": title,
            "type": "loop",
            "start_node_id": start_node_id,
            "loop_count": loop_count,
            "break_conditions": [
                {
                    "id": f"{node_id}-break-succeeded",
                    "variable_selector": break_selector,
                    "comparison_operator": "is",
                    "value": "succeeded",
                    "varType": "string",
                },
                {
                    "id": f"{node_id}-break-failed",
                    "variable_selector": break_selector,
                    "comparison_operator": "is",
                    "value": "failed",
                    "varType": "string",
                },
            ],
            "logical_operator": "or",
            "loop_variables": loop_vars,
            "outputs": {},
            "selected": False,
        },
    )


def loop_start_node(node_id: str, parent_id: str, x: float, y: float) -> dict:
    return {
        "id": node_id,
        "type": "custom-loop-start",
        "parentId": parent_id,
        "data": {"desc": "", "isInLoop": True, "selected": False, "title": "", "type": "loop-start"},
        "position": {"x": x, "y": y},
        "positionAbsolute": {"x": x, "y": y},
        "sourcePosition": "right",
        "targetPosition": "left",
        "width": 44,
        "height": 48,
        "draggable": False,
        "selectable": False,
        "selected": False,
        "zIndex": 1002,
    }


def code_node(
    node_id: str,
    title: str,
    x: float,
    y: float,
    variable_name: str,
    source_selector: list[str],
    *,
    parent_id: str | None = None,
    loop_id: str | None = None,
) -> dict:
    return node_base(
        node_id,
        "code",
        title,
        x,
        y,
        244,
        124,
        {
            "desc": "",
            "title": title,
            "type": "code",
            "variables": [{"variable": variable_name, "value_selector": source_selector}],
            "code_language": "python3",
            "code": (
                "import json\n\n"
                "def main(response_json: str) -> dict:\n"
                "    try:\n"
                "        data = json.loads(response_json or '{}')\n"
                "    except Exception:\n"
                "        data = {\n"
                "            'status': 'failed',\n"
                "            'progress': 100,\n"
                "            'result_url': '',\n"
                "            'error': {'message': 'invalid JSON response'},\n"
                "            'message': 'invalid JSON response',\n"
                "        }\n"
                "    error = data.get('error')\n"
                "    if isinstance(error, dict):\n"
                "        error_message = str(error.get('message') or error.get('detail') or '')\n"
                "    else:\n"
                "        error_message = str(error or '')\n"
                "    result_url = str(\n"
                "        data.get('result_url')\n"
                "        or data.get('source_video_url')\n"
                "        or data.get('english_srt_url')\n"
                "        or data.get('bilingual_srt_url')\n"
                "        or data.get('final_video_url')\n"
                "        or ''\n"
                "    )\n"
                "    try:\n"
                "        progress = int(data.get('progress') or 0)\n"
                "    except Exception:\n"
                "        progress = 0\n"
                "    status = str(data.get('status') or '')\n"
                "    detail = data.get('detail')\n"
                "    if not status and detail:\n"
                "        status = 'failed'\n"
                "        progress = 100\n"
                "        error_message = str(detail)\n"
                "    if not status and error_message:\n"
                "        status = 'failed'\n"
                "        progress = 100\n"
                "    return {\n"
                "        'status': status,\n"
                "        'progress': progress,\n"
                "        'result_url': result_url,\n"
                "        'error': error_message,\n"
                "        'message': str(data.get('message') or ''),\n"
                "    }\n"
            ),
            "outputs": {
                "status": {"type": "string"},
                "progress": {"type": "number"},
                "result_url": {"type": "string"},
                "error": {"type": "string"},
                "message": {"type": "string"},
            },
            "dependencies": [],
        },
        parent_id=parent_id,
        z_index=1002 if loop_id else 0,
    )


def assigner_node(
    node_id: str,
    title: str,
    loop_id: str,
    mappings: list[tuple[str, list[str], str]],
    x: float,
    y: float,
    *,
    parent_id: str | None = None,
) -> dict:
    items = []
    for target_var, source_selector, value_type in mappings:
        items.append(
            {
                "variable_selector": [loop_id, target_var],
                "input_type": "variable",
                "operation": "over-write",
                "value": source_selector,
            }
        )
    return node_base(
        node_id,
        "assigner",
        title,
        x,
        y,
        244,
        86,
        {
            "desc": "",
            "isInIteration": False,
            "isInLoop": True,
            "loop_id": loop_id,
            "selected": False,
            "title": title,
            "type": "assigner",
            "version": "2",
            "items": items,
        },
        parent_id=parent_id,
        z_index=1002,
    )


def if_else_node(node_id: str, title: str, condition_selector: list[str], fail_value: str, x: float, y: float) -> dict:
    return node_base(
        node_id,
        "if-else",
        title,
        x,
        y,
        244,
        126,
        {
            "desc": "",
            "title": title,
            "type": "if-else",
            "cases": [
                {
                    "case_id": "true",
                    "logical_operator": "and",
                    "conditions": [
                        {
                            "id": f"{node_id}-failed",
                            "variable_selector": condition_selector,
                            "comparison_operator": "is",
                            "value": fail_value,
                            "varType": "string",
                        }
                    ],
                }
            ],
            "selected": False,
        },
    )


def end_node(node_id: str, title: str, outputs: list[dict], x: float, y: float, width: int = 244, height: int = 140) -> dict:
    return node_base(
        node_id,
        "end",
        title,
        x,
        y,
        width,
        height,
        {"desc": "", "title": title, "type": "end", "outputs": outputs, "selected": False},
    )


def edge(edge_id: str, source: str, target: str, source_type: str, target_type: str, *, is_in_loop: bool = False, loop_id: str | None = None, source_handle: str = "source", target_handle: str = "target") -> dict:
    data = {
        "sourceType": source_type,
        "targetType": target_type,
        "isInIteration": False,
        "isInLoop": is_in_loop,
    }
    if loop_id:
        data["loop_id"] = loop_id
    return {
        "id": edge_id,
        "source": source,
        "sourceHandle": source_handle,
        "target": target,
        "targetHandle": target_handle,
        "type": "custom",
        "data": data,
        "zIndex": 1002 if is_in_loop else 0,
    }


def build_stage(
    *,
    stage_key: str,
    stage_title: str,
    submit_url: str,
    submit_body: str,
    poll_url: str,
    fail_end_title: str,
    fail_end_x: float,
    stage_y: float,
    loop_count: int = 100,
    next_submit_id: str | None = None,
    next_submit_title: str | None = None,
    next_submit_url: str | None = None,
    next_submit_body: str | None = None,
    is_final: bool = False,
    final_end_title: str | None = None,
    final_end_x: float | None = None,
) -> tuple[list[dict], list[dict], str]:
    submit_id = f"{stage_key}_submit"
    loop_id = f"{stage_key}_loop"
    loop_start_id = f"{stage_key}_loop_start"
    poll_id = f"{stage_key}_poll"
    parse_id = f"{stage_key}_parse"
    sync_id = f"{stage_key}_sync"
    if_id = f"{stage_key}_check_failed"
    fail_end_id = f"{stage_key}_failed_end"

    nodes = [
        http_node(submit_id, f"提交{stage_title}", f"阶段 1：提交{stage_title}任务", "post", submit_url, submit_body, 330, stage_y),
        loop_node(
            loop_id,
            f"{stage_title}轮询",
            f"轮询{stage_title}进度",
            loop_start_id,
            [
                {
                    "label": "job_id",
                    "var_type": "string",
                    "value_type": "variable",
                    "value": [submit_id, "body"],
                },
                {
                    "label": "status",
                    "var_type": "string",
                    "value_type": "constant",
                    "value": "",
                },
                {
                    "label": "progress",
                    "var_type": "number",
                    "value_type": "constant",
                    "value": 0,
                },
                {
                    "label": "result_url",
                    "var_type": "string",
                    "value_type": "constant",
                    "value": "",
                },
                {
                    "label": "error",
                    "var_type": "string",
                    "value_type": "constant",
                    "value": "",
                },
                {
                    "label": "message",
                    "var_type": "string",
                    "value_type": "constant",
                    "value": "",
                },
            ],
            [loop_id, "status"],
            660,
            stage_y - 80,
            loop_count=loop_count,
            width=920,
            height=220,
        ),
        loop_start_node(loop_start_id, loop_id, 60, 90),
        http_node(
            poll_id,
            f"查询{stage_title}状态",
            f"轮询{stage_title}状态",
            "get",
            poll_url,
            None,
            150,
            80,
        ),
        code_node(parse_id, f"解析{stage_title}状态", 430, 74, "response_json", [poll_id, "body"]),
        assigner_node(
            sync_id,
            f"同步{stage_title}状态",
            loop_id,
            [
                ("status", [parse_id, "status"], "string"),
                ("progress", [parse_id, "progress"], "number"),
                ("result_url", [parse_id, "result_url"], "string"),
                ("error", [parse_id, "error"], "string"),
                ("message", [parse_id, "message"], "string"),
            ],
            680,
            72,
        ),
        if_else_node(if_id, f"{stage_title}是否完成", [loop_id, "status"], "succeeded", 1620, stage_y + 14),
        end_node(
            fail_end_id,
            fail_end_title,
            [
                {"value_selector": [loop_id, "status"], "value_type": "string", "variable": "status"},
                {"value_selector": [loop_id, "progress"], "value_type": "number", "variable": "progress"},
                {"value_selector": [loop_id, "result_url"], "value_type": "string", "variable": "result_url"},
                {"value_selector": [loop_id, "error"], "value_type": "string", "variable": "error_message"},
                {"value_selector": [loop_id, "job_id"], "value_type": "string", "variable": "stage_job_id"},
            ],
            fail_end_x,
            stage_y + 180,
        ),
    ]

    if is_final:
        nodes.append(
            end_node(
                "final_end",
                final_end_title or "结束",
                [
                    {"value_selector": ["download_loop", "result_url"], "value_type": "string", "variable": "source_video_url"},
                    {"value_selector": ["transcribe_loop", "result_url"], "value_type": "string", "variable": "english_srt_url"},
                    {"value_selector": ["translate_loop", "result_url"], "value_type": "string", "variable": "bilingual_srt_url"},
                    {"value_selector": ["burn_loop", "result_url"], "value_type": "string", "variable": "final_video_url"},
                    {"value_selector": ["download_loop", "job_id"], "value_type": "string", "variable": "download_job_id"},
                    {"value_selector": ["transcribe_loop", "job_id"], "value_type": "string", "variable": "transcribe_job_id"},
                    {"value_selector": ["translate_loop", "job_id"], "value_type": "string", "variable": "translate_job_id"},
                    {"value_selector": ["burn_loop", "job_id"], "value_type": "string", "variable": "burn_job_id"},
                    {"value_selector": ["download_loop", "progress"], "value_type": "number", "variable": "download_progress"},
                    {"value_selector": ["transcribe_loop", "progress"], "value_type": "number", "variable": "transcribe_progress"},
                    {"value_selector": ["translate_loop", "progress"], "value_type": "number", "variable": "translate_progress"},
                    {"value_selector": ["burn_loop", "progress"], "value_type": "number", "variable": "burn_progress"},
                    {"value_selector": ["burn_loop", "status"], "value_type": "string", "variable": "status"},
                    {"value_selector": ["burn_loop", "error"], "value_type": "string", "variable": "error_message"},
                ],
                final_end_x or 2400,
                stage_y + 180,
                width=280,
                height=190,
            )
        )
    else:
        nodes.append(
            http_node(
                next_submit_id,
                f"提交{next_submit_title}",
                f"阶段 1：提交{next_submit_title}任务",
                "post",
                next_submit_url or "",
                next_submit_body,
                1900,
                stage_y,
            )
        )

    edges = [
        edge(f"{submit_id}-to-{loop_id}", submit_id, loop_id, "http-request", "loop"),
        edge(f"{loop_id}-to-{if_id}", loop_id, if_id, "loop", "if-else"),
        edge(f"{if_id}-true-{fail_end_id}", if_id, fail_end_id, "if-else", "end", source_handle="true"),
    ]
    if is_final:
        edges.append(edge(f"{if_id}-true-final_end", if_id, "final_end", "if-else", "end", source_handle="true"))
        edges.append(edge(f"{if_id}-false-{fail_end_id}", if_id, fail_end_id, "if-else", "end", source_handle="false"))
    else:
        edges.append(edge(f"{if_id}-true-{next_submit_id}", if_id, next_submit_id, "if-else", "http-request", source_handle="true"))
        edges.append(edge(f"{if_id}-false-{fail_end_id}", if_id, fail_end_id, "if-else", "end", source_handle="false"))

    loop_edges = [
        edge(f"{loop_start_id}-to-{poll_id}", loop_start_id, poll_id, "loop-start", "http-request", is_in_loop=True, loop_id=loop_id),
        edge(f"{poll_id}-to-{parse_id}", poll_id, parse_id, "http-request", "code", is_in_loop=True, loop_id=loop_id),
        edge(f"{parse_id}-to-{sync_id}", parse_id, sync_id, "code", "assigner", is_in_loop=True, loop_id=loop_id),
    ]

    if is_final:
        return nodes, edges + loop_edges, submit_id

    return nodes, edges + loop_edges, submit_id


def build_workflow() -> dict:
    nodes = [start_node()]
    edges = []

    download_submit = http_node(
        "download_submit",
        "提交下载",
        "阶段 1：提交下载任务",
        "post",
        f"{OPERATOR_BASE_URL}/stage-jobs/download",
        "{\"source_kind\":\"{{#start_node.source_kind#}}\",\"source_value\":\"{{#start_node.source_value#}}\",\"youtube_url\":\"{{#start_node.youtube_url#}}\",\"rights_confirmed\":{{#start_node.rights_confirmed#}},\"resolution\":\"{{#start_node.resolution#}}\",\"fps\":\"{{#start_node.fps#}}\",\"operator_batch_id\":\"{{#start_node.operator_batch_id#}}\",\"operator_item_id\":\"{{#start_node.operator_item_id#}}\"}",
        330,
        280,
    )
    nodes.append(download_submit)
    nodes.append(
        loop_node(
            "download_loop",
            "下载轮询",
            "轮询下载进度",
            "download_loop_start",
            [
                {"label": "job_id", "var_type": "string", "value_type": "variable", "value": ["download_submit", "body"]},
                {"label": "status", "var_type": "string", "value_type": "constant", "value": ""},
                {"label": "progress", "var_type": "number", "value_type": "constant", "value": 0},
                {"label": "result_url", "var_type": "string", "value_type": "constant", "value": ""},
                {"label": "error", "var_type": "string", "value_type": "constant", "value": ""},
                {"label": "message", "var_type": "string", "value_type": "constant", "value": ""},
            ],
            ["download_loop", "status"],
            660,
            200,
            loop_count=stage_loop_count("download"),
            width=920,
            height=220,
        )
    )
    nodes.append(loop_start_node("download_loop_start", "download_loop", 60, 90))
    nodes.append(
        http_node(
            "download_poll",
            "查询下载状态",
            "轮询下载状态",
            "get",
            f"{OPERATOR_BASE_URL}/stage-jobs/{{{{#download_loop.job_id#}}}}?hold_seconds={stage_hold_seconds('download')}",
            None,
            150,
            80,
            parent_id="download_loop",
            loop_id="download_loop",
        )
    )
    nodes.append(
        code_node(
            "download_parse",
            "解析下载状态",
            430,
            74,
            "response_json",
            ["download_poll", "body"],
            parent_id="download_loop",
            loop_id="download_loop",
        )
    )
    nodes.append(
        assigner_node(
            "download_sync",
            "同步下载状态",
            "download_loop",
            [
                ("status", ["download_parse", "status"], "string"),
                ("progress", ["download_parse", "progress"], "number"),
                ("result_url", ["download_parse", "result_url"], "string"),
                ("error", ["download_parse", "error"], "string"),
                ("message", ["download_parse", "message"], "string"),
            ],
            680,
            72,
            parent_id="download_loop",
        )
    )
    nodes.append(if_else_node("download_check_failed", "下载是否完成", ["download_loop", "status"], "succeeded", 1620, 280))
    nodes.append(
        end_node(
            "download_failed_end",
            "下载失败",
            [
                {"value_selector": ["download_loop", "status"], "value_type": "string", "variable": "status"},
                {"value_selector": ["download_loop", "progress"], "value_type": "number", "variable": "progress"},
                {"value_selector": ["download_loop", "result_url"], "value_type": "string", "variable": "result_url"},
                {"value_selector": ["download_loop", "error"], "value_type": "string", "variable": "error_message"},
                {"value_selector": ["download_loop", "job_id"], "value_type": "string", "variable": "stage_job_id"},
            ],
            1900,
            460,
        )
    )

    nodes.append(
        http_node(
            "transcribe_submit",
            "提交转写",
            "阶段 2：提交英文转写任务",
            "post",
            f"{OPERATOR_BASE_URL}/stage-jobs/transcribe",
            "{\"source_video_url\":\"{{#download_loop.result_url#}}\",\"language\":\"en\",\"whisper_model\":\"{{#start_node.whisper_model#}}\",\"whisper_inference_mode\":\"{{#start_node.whisper_inference_mode#}}\",\"title\":\"{{#start_node.youtube_url#}}\",\"operator_batch_id\":\"{{#start_node.operator_batch_id#}}\",\"operator_item_id\":\"{{#start_node.operator_item_id#}}\"}",
            1900,
            280,
        )
    )
    nodes.append(
        loop_node(
            "transcribe_loop",
            "转写轮询",
            "轮询转写进度",
            "transcribe_loop_start",
            [
                {"label": "job_id", "var_type": "string", "value_type": "variable", "value": ["transcribe_submit", "body"]},
                {"label": "status", "var_type": "string", "value_type": "constant", "value": ""},
                {"label": "progress", "var_type": "number", "value_type": "constant", "value": 0},
                {"label": "result_url", "var_type": "string", "value_type": "constant", "value": ""},
                {"label": "error", "var_type": "string", "value_type": "constant", "value": ""},
                {"label": "message", "var_type": "string", "value_type": "constant", "value": ""},
            ],
            ["transcribe_loop", "status"],
            2230,
            200,
            loop_count=stage_loop_count("transcribe"),
            width=920,
            height=220,
        )
    )
    nodes.append(loop_start_node("transcribe_loop_start", "transcribe_loop", 60, 90))
    nodes.append(
        http_node(
            "transcribe_poll",
            "查询转写状态",
            "轮询转写状态",
            "get",
            f"{OPERATOR_BASE_URL}/stage-jobs/{{{{#transcribe_loop.job_id#}}}}?hold_seconds={stage_hold_seconds('transcribe')}",
            None,
            150,
            80,
            parent_id="transcribe_loop",
            loop_id="transcribe_loop",
        )
    )
    nodes.append(
        code_node(
            "transcribe_parse",
            "解析转写状态",
            430,
            74,
            "response_json",
            ["transcribe_poll", "body"],
            parent_id="transcribe_loop",
            loop_id="transcribe_loop",
        )
    )
    nodes.append(
        assigner_node(
            "transcribe_sync",
            "同步转写状态",
            "transcribe_loop",
            [
                ("status", ["transcribe_parse", "status"], "string"),
                ("progress", ["transcribe_parse", "progress"], "number"),
                ("result_url", ["transcribe_parse", "result_url"], "string"),
                ("error", ["transcribe_parse", "error"], "string"),
                ("message", ["transcribe_parse", "message"], "string"),
            ],
            680,
            72,
            parent_id="transcribe_loop",
        )
    )
    nodes.append(if_else_node("transcribe_check_failed", "转写是否完成", ["transcribe_loop", "status"], "succeeded", 3520, 280))
    nodes.append(
        end_node(
            "transcribe_failed_end",
            "转写失败",
            [
                {"value_selector": ["transcribe_loop", "status"], "value_type": "string", "variable": "status"},
                {"value_selector": ["transcribe_loop", "progress"], "value_type": "number", "variable": "progress"},
                {"value_selector": ["transcribe_loop", "result_url"], "value_type": "string", "variable": "result_url"},
                {"value_selector": ["transcribe_loop", "error"], "value_type": "string", "variable": "error_message"},
                {"value_selector": ["transcribe_loop", "job_id"], "value_type": "string", "variable": "stage_job_id"},
            ],
            3820,
            460,
        )
    )

    nodes.append(
        http_node(
            "translate_submit",
            "提交翻译",
            "阶段 3：提交双语翻译任务",
            "post",
            f"{OPERATOR_BASE_URL}/stage-jobs/translate",
            "{\"english_srt_url\":\"{{#transcribe_loop.result_url#}}\",\"target_lang\":\"{{#start_node.target_lang#}}\",\"translate_model\":\"{{#start_node.translate_model#}}\",\"subtitle_output_mode\":\"{{#start_node.subtitle_output_mode#}}\",\"translation_context_profile_id\":\"{{#start_node.translation_context_profile_id#}}\",\"translation_context_note\":{{#start_node.translation_context_note_json#}},\"translation_glossary\":{{#start_node.translation_glossary_json#}},\"operator_batch_id\":\"{{#start_node.operator_batch_id#}}\",\"operator_item_id\":\"{{#start_node.operator_item_id#}}\"}",
            3820,
            280,
        )
    )
    nodes.append(
        loop_node(
            "translate_loop",
            "翻译轮询",
            "轮询翻译进度",
            "translate_loop_start",
            [
                {"label": "job_id", "var_type": "string", "value_type": "variable", "value": ["translate_submit", "body"]},
                {"label": "status", "var_type": "string", "value_type": "constant", "value": ""},
                {"label": "progress", "var_type": "number", "value_type": "constant", "value": 0},
                {"label": "result_url", "var_type": "string", "value_type": "constant", "value": ""},
                {"label": "error", "var_type": "string", "value_type": "constant", "value": ""},
                {"label": "message", "var_type": "string", "value_type": "constant", "value": ""},
            ],
            ["translate_loop", "status"],
            4150,
            200,
            loop_count=stage_loop_count("translate"),
            width=920,
            height=220,
        )
    )
    nodes.append(loop_start_node("translate_loop_start", "translate_loop", 60, 90))
    nodes.append(
        http_node(
            "translate_poll",
            "查询翻译状态",
            "轮询翻译状态",
            "get",
            f"{OPERATOR_BASE_URL}/stage-jobs/{{{{#translate_loop.job_id#}}}}?hold_seconds={stage_hold_seconds('translate')}",
            None,
            150,
            80,
            parent_id="translate_loop",
            loop_id="translate_loop",
        )
    )
    nodes.append(
        code_node(
            "translate_parse",
            "解析翻译状态",
            430,
            74,
            "response_json",
            ["translate_poll", "body"],
            parent_id="translate_loop",
            loop_id="translate_loop",
        )
    )
    nodes.append(
        assigner_node(
            "translate_sync",
            "同步翻译状态",
            "translate_loop",
            [
                ("status", ["translate_parse", "status"], "string"),
                ("progress", ["translate_parse", "progress"], "number"),
                ("result_url", ["translate_parse", "result_url"], "string"),
                ("error", ["translate_parse", "error"], "string"),
                ("message", ["translate_parse", "message"], "string"),
            ],
            680,
            72,
            parent_id="translate_loop",
        )
    )
    nodes.append(if_else_node("translate_check_failed", "翻译是否完成", ["translate_loop", "status"], "succeeded", 5440, 280))
    nodes.append(
        end_node(
            "translate_failed_end",
            "翻译失败",
            [
                {"value_selector": ["translate_loop", "status"], "value_type": "string", "variable": "status"},
                {"value_selector": ["translate_loop", "progress"], "value_type": "number", "variable": "progress"},
                {"value_selector": ["translate_loop", "result_url"], "value_type": "string", "variable": "result_url"},
                {"value_selector": ["translate_loop", "error"], "value_type": "string", "variable": "error_message"},
                {"value_selector": ["translate_loop", "job_id"], "value_type": "string", "variable": "stage_job_id"},
            ],
            5740,
            460,
        )
    )

    nodes.append(
        http_node(
            "burn_submit",
            "提交烧录",
            "阶段 4：提交字幕烧录任务",
            "post",
            f"{OPERATOR_BASE_URL}/stage-jobs/burn",
            "{\"source_video_url\":\"{{#download_loop.result_url#}}\",\"english_srt_url\":\"{{#transcribe_loop.result_url#}}\",\"bilingual_srt_url\":\"{{#translate_loop.result_url#}}\",\"aspect_ratio\":\"{{#start_node.aspect_ratio#}}\",\"subtitle_font_size\":\"{{#start_node.subtitle_font_size#}}\",\"subtitle_color\":\"{{#start_node.subtitle_color#}}\",\"subtitle_outline_color\":\"{{#start_node.subtitle_outline_color#}}\",\"subtitle_position\":\"{{#start_node.subtitle_position#}}\",\"subtitle_margin\":\"{{#start_node.subtitle_margin#}}\",\"subtitle_output_mode\":\"{{#start_node.subtitle_output_mode#}}\",\"subtitle_style\":{{#start_node.subtitle_style#}},\"output_name\":\"{{#start_node.output_name_prefix#}}{{#start_node.output_index#}}\",\"operator_batch_id\":\"{{#start_node.operator_batch_id#}}\",\"operator_item_id\":\"{{#start_node.operator_item_id#}}\"}",
            5740,
            280,
        )
    )
    nodes.append(
        loop_node(
            "burn_loop",
            "烧录轮询",
            "轮询烧录进度",
            "burn_loop_start",
            [
                {"label": "job_id", "var_type": "string", "value_type": "variable", "value": ["burn_submit", "body"]},
                {"label": "status", "var_type": "string", "value_type": "constant", "value": ""},
                {"label": "progress", "var_type": "number", "value_type": "constant", "value": 0},
                {"label": "result_url", "var_type": "string", "value_type": "constant", "value": ""},
                {"label": "error", "var_type": "string", "value_type": "constant", "value": ""},
                {"label": "message", "var_type": "string", "value_type": "constant", "value": ""},
            ],
            ["burn_loop", "status"],
            6070,
            200,
            loop_count=stage_loop_count("burn"),
            width=920,
            height=220,
        )
    )
    nodes.append(loop_start_node("burn_loop_start", "burn_loop", 60, 90))
    nodes.append(
        http_node(
            "burn_poll",
            "查询烧录状态",
            "轮询烧录状态",
            "get",
            f"{OPERATOR_BASE_URL}/stage-jobs/{{{{#burn_loop.job_id#}}}}?hold_seconds={stage_hold_seconds('burn')}",
            None,
            150,
            80,
            parent_id="burn_loop",
            loop_id="burn_loop",
        )
    )
    nodes.append(
        code_node(
            "burn_parse",
            "解析烧录状态",
            430,
            74,
            "response_json",
            ["burn_poll", "body"],
            parent_id="burn_loop",
            loop_id="burn_loop",
        )
    )
    nodes.append(
        assigner_node(
            "burn_sync",
            "同步烧录状态",
            "burn_loop",
            [
                ("status", ["burn_parse", "status"], "string"),
                ("progress", ["burn_parse", "progress"], "number"),
                ("result_url", ["burn_parse", "result_url"], "string"),
                ("error", ["burn_parse", "error"], "string"),
                ("message", ["burn_parse", "message"], "string"),
            ],
            680,
            72,
            parent_id="burn_loop",
        )
    )
    nodes.append(if_else_node("burn_check_failed", "烧录是否完成", ["burn_loop", "status"], "succeeded", 7360, 280))
    nodes.append(
        end_node(
            "burn_failed_end",
            "烧录失败",
            [
                {"value_selector": ["burn_loop", "status"], "value_type": "string", "variable": "status"},
                {"value_selector": ["burn_loop", "progress"], "value_type": "number", "variable": "progress"},
                {"value_selector": ["burn_loop", "result_url"], "value_type": "string", "variable": "result_url"},
                {"value_selector": ["burn_loop", "error"], "value_type": "string", "variable": "error_message"},
                {"value_selector": ["burn_loop", "job_id"], "value_type": "string", "variable": "stage_job_id"},
            ],
            7660,
            460,
        )
    )
    nodes.append(
        end_node(
            "final_end",
            "结束",
            [
                {"value_selector": ["download_loop", "result_url"], "value_type": "string", "variable": "source_video_url"},
                {"value_selector": ["transcribe_loop", "result_url"], "value_type": "string", "variable": "english_srt_url"},
                {"value_selector": ["translate_loop", "result_url"], "value_type": "string", "variable": "bilingual_srt_url"},
                {"value_selector": ["burn_loop", "result_url"], "value_type": "string", "variable": "final_video_url"},
                {"value_selector": ["download_loop", "job_id"], "value_type": "string", "variable": "download_job_id"},
                {"value_selector": ["transcribe_loop", "job_id"], "value_type": "string", "variable": "transcribe_job_id"},
                {"value_selector": ["translate_loop", "job_id"], "value_type": "string", "variable": "translate_job_id"},
                {"value_selector": ["burn_loop", "job_id"], "value_type": "string", "variable": "burn_job_id"},
                {"value_selector": ["download_loop", "progress"], "value_type": "number", "variable": "download_progress"},
                {"value_selector": ["transcribe_loop", "progress"], "value_type": "number", "variable": "transcribe_progress"},
                {"value_selector": ["translate_loop", "progress"], "value_type": "number", "variable": "translate_progress"},
                {"value_selector": ["burn_loop", "progress"], "value_type": "number", "variable": "burn_progress"},
                {"value_selector": ["burn_loop", "status"], "value_type": "string", "variable": "status"},
                {"value_selector": ["burn_loop", "error"], "value_type": "string", "variable": "error_message"},
            ],
            7960,
            260,
            width=280,
            height=190,
        )
    )

    edges.extend(
        [
            edge("start-download_submit", "start_node", "download_submit", "start", "http-request"),
            edge("download_submit-download_loop", "download_submit", "download_loop", "http-request", "loop"),
            edge("download_loop-download_check_failed", "download_loop", "download_check_failed", "loop", "if-else"),
            edge("download_check_failed-true-transcribe_submit", "download_check_failed", "transcribe_submit", "if-else", "http-request", source_handle="true"),
            edge("download_check_failed-false-download_failed_end", "download_check_failed", "download_failed_end", "if-else", "end", source_handle="false"),
            edge("transcribe_submit-transcribe_loop", "transcribe_submit", "transcribe_loop", "http-request", "loop"),
            edge("transcribe_loop-transcribe_check_failed", "transcribe_loop", "transcribe_check_failed", "loop", "if-else"),
            edge("transcribe_check_failed-true-translate_submit", "transcribe_check_failed", "translate_submit", "if-else", "http-request", source_handle="true"),
            edge("transcribe_check_failed-false-transcribe_failed_end", "transcribe_check_failed", "transcribe_failed_end", "if-else", "end", source_handle="false"),
            edge("translate_submit-translate_loop", "translate_submit", "translate_loop", "http-request", "loop"),
            edge("translate_loop-translate_check_failed", "translate_loop", "translate_check_failed", "loop", "if-else"),
            edge("translate_check_failed-true-burn_submit", "translate_check_failed", "burn_submit", "if-else", "http-request", source_handle="true"),
            edge("translate_check_failed-false-translate_failed_end", "translate_check_failed", "translate_failed_end", "if-else", "end", source_handle="false"),
            edge("burn_submit-burn_loop", "burn_submit", "burn_loop", "http-request", "loop"),
            edge("burn_loop-burn_check_failed", "burn_loop", "burn_check_failed", "loop", "if-else"),
            edge("burn_check_failed-true-final_end", "burn_check_failed", "final_end", "if-else", "end", source_handle="true"),
            edge("burn_check_failed-false-burn_failed_end", "burn_check_failed", "burn_failed_end", "if-else", "end", source_handle="false"),
            edge("download_loop_start-download_poll", "download_loop_start", "download_poll", "loop-start", "http-request", is_in_loop=True, loop_id="download_loop"),
            edge("download_poll-download_parse", "download_poll", "download_parse", "http-request", "code", is_in_loop=True, loop_id="download_loop"),
            edge("download_parse-download_sync", "download_parse", "download_sync", "code", "assigner", is_in_loop=True, loop_id="download_loop"),
            edge("transcribe_loop_start-transcribe_poll", "transcribe_loop_start", "transcribe_poll", "loop-start", "http-request", is_in_loop=True, loop_id="transcribe_loop"),
            edge("transcribe_poll-transcribe_parse", "transcribe_poll", "transcribe_parse", "http-request", "code", is_in_loop=True, loop_id="transcribe_loop"),
            edge("transcribe_parse-transcribe_sync", "transcribe_parse", "transcribe_sync", "code", "assigner", is_in_loop=True, loop_id="transcribe_loop"),
            edge("translate_loop_start-translate_poll", "translate_loop_start", "translate_poll", "loop-start", "http-request", is_in_loop=True, loop_id="translate_loop"),
            edge("translate_poll-translate_parse", "translate_poll", "translate_parse", "http-request", "code", is_in_loop=True, loop_id="translate_loop"),
            edge("translate_parse-translate_sync", "translate_parse", "translate_sync", "code", "assigner", is_in_loop=True, loop_id="translate_loop"),
            edge("burn_loop_start-burn_poll", "burn_loop_start", "burn_poll", "loop-start", "http-request", is_in_loop=True, loop_id="burn_loop"),
            edge("burn_poll-burn_parse", "burn_poll", "burn_parse", "http-request", "code", is_in_loop=True, loop_id="burn_loop"),
            edge("burn_parse-burn_sync", "burn_parse", "burn_sync", "code", "assigner", is_in_loop=True, loop_id="burn_loop"),
        ]
    )

    return {
        "nodes": nodes,
        "edges": edges,
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }


def build_export() -> dict:
    return {
        "app": {
            "description": "媒体工作流主流水线：提交下载、轮询下载、转写、翻译、烧录，全程可视化进度。",
            "icon": "🤖",
            "icon_background": "#FFEAD5",
            "mode": "workflow",
            "name": "媒体工作流-主流水线",
            "use_icon_as_answer_icon": False,
        },
        "dependencies": [],
        "kind": "app",
        "version": "0.3.1",
        "workflow": {
            "conversation_variables": [],
            "environment_variables": [],
            "features": {
                "file_upload": {
                    "allowed_file_extensions": [".JPG", ".JPEG", ".PNG", ".GIF", ".WEBP", ".SVG"],
                    "allowed_file_types": ["image"],
                    "allowed_file_upload_methods": ["local_file", "remote_url"],
                    "enabled": False,
                    "fileUploadConfig": {
                        "audio_file_size_limit": 50,
                        "batch_count_limit": 5,
                        "file_size_limit": 15,
                        "image_file_size_limit": 10,
                        "video_file_size_limit": 100,
                        "workflow_file_upload_limit": 10,
                    },
                    "image": {"enabled": False, "number_limits": 3, "transfer_methods": ["local_file", "remote_url"]},
                    "number_limits": 3,
                },
                "opening_statement": "",
                "retriever_resource": {"enabled": True},
                "sensitive_word_avoidance": {"enabled": False},
                "speech_to_text": {"enabled": False},
                "suggested_questions": [],
                "suggested_questions_after_answer": {"enabled": False},
                "text_to_speech": {"enabled": False, "language": "", "voice": ""},
            },
            "graph": build_workflow(),
        },
    }


def main() -> None:
    export = build_export()
    OUT.write_text(json.dumps(export["workflow"]["graph"], ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
