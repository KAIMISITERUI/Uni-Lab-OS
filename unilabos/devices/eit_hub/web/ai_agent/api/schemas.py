# -*- coding: utf-8 -*-
"""
功能:
    AI 助手 Web API 的请求与响应模型.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class CreateSessionResponse(BaseModel):
    """
    功能:
        新建会话响应, 仅返回 session_id, 真正落库发生在首条消息时.
    参数:
        session_id: str, 新生成的会话 ID.
    """

    session_id: str


class RenameSessionPayload(BaseModel):
    """
    功能:
        会话重命名请求.
    参数:
        title: str, 新标题, 不能为空.
    """

    title: str

    class Config:
        extra = "forbid"


class SendMessagePayload(BaseModel):
    """
    功能:
        发送用户消息请求.
    参数:
        content: str, 消息原文.
    """

    content: str

    class Config:
        extra = "forbid"


class AiConfigUpdatePayload(BaseModel):
    """
    功能:
        更新 AI 助手 DeepSeek 接入配置. 字段为 None 表示不修改, 空字符串表示清除该字段 (回退 env).
    参数:
        api_key: Optional[str], API Key, None 不修改, "" 清除.
        base_url: Optional[str], 接口前缀, None 不修改, "" 清除.
        model: Optional[str], 模型 ID, None 不修改, "" 清除.
        timeout_s: Optional[float], 超时秒, None 不修改, 0 或负数清除.
    """

    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    timeout_s: Optional[float] = None

    class Config:
        extra = "forbid"


class ToolConfirmPayload(BaseModel):
    """
    功能:
        对挂起 control_tool 的确认/拒绝请求.
    参数:
        message_id: int, 待解决的 tool 消息行 ID.
        action: str, confirm 或 reject.
        reject_reason: str 或 None, 拒绝时的说明.
    """

    message_id: int
    action: str
    reject_reason: Optional[str] = ""

    class Config:
        extra = "forbid"
