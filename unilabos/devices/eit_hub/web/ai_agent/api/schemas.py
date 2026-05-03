# -*- coding: utf-8 -*-
"""
功能:
    AI 助手 Web API 的请求与响应模型.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict


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

    model_config = ConfigDict(extra="forbid")

    title: str


class SendMessagePayload(BaseModel):
    """
    功能:
        发送用户消息请求.
    参数:
        content: str, 消息原文.
    """

    model_config = ConfigDict(extra="forbid")

    content: str


class AiProviderCredentialsUpdate(BaseModel):
    """
    功能:
        单个 provider 凭证的更新片段. 字段缺省表示不修改, null 或空字符串清除该字段 (回退 env / 默认).
    参数:
        api_key: Optional[str], API Key, 缺省不修改, null 或 "" 清除.
        base_url: Optional[str], 接口前缀, 缺省不修改, null 或 "" 清除.
        timeout_s: Optional[float], 超时秒, 缺省不修改, null / 0 / 负数清除.
    """

    model_config = ConfigDict(extra="forbid")

    api_key: Optional[str] = None
    base_url: Optional[str] = None
    timeout_s: Optional[float] = None


class AiConfigUpdatePayload(BaseModel):
    """
    功能:
        更新 AI 助手下拉两段式选择和各 provider 凭证. 字段缺省表示不修改.
    参数:
        active_base_model_id: Optional[str], 下拉左按钮选中的 base_model ID, 缺省不修改, null 或 "" 清除 (回退 env / 默认).
        active_thinking_level_id: Optional[str], 下拉右按钮选中的 thinking_level ID, 缺省不修改, null 或 "" 清除 (回退 base_model 默认档).
        providers: Optional[Dict[str, AiProviderCredentialsUpdate]], 各 provider 的凭证更新片段; 缺省不修改, key 必须是已登记 provider ID.
    """

    model_config = ConfigDict(extra="forbid")

    active_base_model_id: Optional[str] = None
    active_thinking_level_id: Optional[str] = None
    providers: Optional[Dict[str, AiProviderCredentialsUpdate]] = None


class ToolConfirmPayload(BaseModel):
    """
    功能:
        对挂起 control 工具的确认, 拒绝或编辑后确认请求.
    参数:
        message_id: int, 待解决的 tool 消息行 ID.
        action: str, approve, reject 或 edit.
        reject_reason: str 或 None, 拒绝时的说明.
        edited_arguments: Dict 或 None, edit 时的新工具参数.
    """

    model_config = ConfigDict(extra="forbid")

    message_id: int
    action: str
    reject_reason: Optional[str] = ""
    edited_arguments: Optional[Dict[str, Any]] = None


class KnowledgeIngestPayload(BaseModel):
    """
    功能:
        知识库摄取请求.
    参数:
        path: str, 本地文件或目录路径.
        collection: str 或 None, Qdrant collection 名称.
    """

    model_config = ConfigDict(extra="forbid")

    path: str
    collection: Optional[str] = None
