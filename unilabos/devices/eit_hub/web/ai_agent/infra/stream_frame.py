# -*- coding: utf-8 -*-
"""
功能:
    定义模型流式输出的统一事件帧. 所有 provider 客户端都转换为该结构,
    上层 runtime 不感知具体厂商协议.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

JsonDict = Dict[str, Any]


@dataclass
class StreamFrame:
    """
    功能:
        模型客户端对外 yield 的统一事件帧.
    参数:
        kind: str, 帧类型 token / phase / done / error.
        text: str 或 None, 仅 kind=token 时有效, 增量文本片段.
        phase: str 或 None, 仅 kind=phase 时有效, 取值 thinking / tool_calling, 用于前端阶段提示.
        tool_name: str 或 None, 仅 kind=phase 且 phase=tool_calling 时有效, 即将调用的工具名.
        reasoning_content: str 或 None, 仅 kind=done 时有效, 模型推理摘要或 thinking 内容.
        finish_reason: str 或 None, 仅 kind=done 时有效, 标准化结束原因.
        tool_calls: List[Dict] 或 None, 仅 kind=done 时有效, 工具调用列表.
        prompt_tokens: int 或 None, 仅 kind=done 时有效.
        completion_tokens: int 或 None, 仅 kind=done 时有效.
        error_message: str 或 None, 仅 kind=error 时有效.
    返回:
        StreamFrame, 流式事件帧实例.
    """

    kind: str
    text: Optional[str] = None
    phase: Optional[str] = None
    tool_name: Optional[str] = None
    reasoning_content: Optional[str] = None
    finish_reason: Optional[str] = None
    tool_calls: Optional[List[JsonDict]] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    error_message: Optional[str] = None
