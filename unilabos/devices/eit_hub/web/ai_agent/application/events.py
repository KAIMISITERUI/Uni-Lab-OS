# -*- coding: utf-8 -*-
"""
功能:
    AI 助手流式事件结构, 负责把内部事件序列化为 SSE 文本.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict

JsonDict = Dict[str, Any]


@dataclass
class SseEvent:
    """
    功能:
        SSE 单条事件的内部结构, to_sse_text 拼成 text/event-stream 文本.
    参数:
        event: str, 事件名 token / tool_call / tool_result / pending_confirm / done / error.
        data: Dict, 事件荷载, 会被 json.dumps.
    """

    event: str
    data: JsonDict

    def to_sse_text(self) -> str:
        """
        功能:
            序列化为 SSE 协议的 event:/data: 文本块, 末尾保留空行.
        返回:
            str, 单条 SSE 事件的完整文本.
        """
        payload = json.dumps(self.data, ensure_ascii=False, default=str)
        return f"event: {self.event}\ndata: {payload}\n\n"
