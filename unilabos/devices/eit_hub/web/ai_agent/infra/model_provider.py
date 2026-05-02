# -*- coding: utf-8 -*-
"""
功能:
    模型调用抽象层. 业务 runtime 只依赖 ModelProvider, 不直接依赖 DeepSeek 客户端.
"""

from __future__ import annotations

from typing import AsyncIterator, List, Optional, Protocol

from .deepseek_client import DeepseekClient, StreamFrame

JsonDict = dict[str, object]


class ModelProvider(Protocol):
    """
    功能:
        流式模型 provider 协议.
    """

    async def stream_chat(
        self,
        messages: List[JsonDict],
        tools: Optional[List[JsonDict]] = None,
    ) -> AsyncIterator[StreamFrame]:
        """
        功能:
            发起一次流式聊天请求.
        参数:
            messages: List[Dict], 模型消息.
            tools: Optional[List[Dict]], 工具 schema.
        返回:
            AsyncIterator[StreamFrame], 流式帧.
        """
        ...


class DeepSeekModelProvider:
    """
    功能:
        DeepSeek 模型 provider, 复用现有 OpenAI-compatible DeepseekClient.
    """

    def __init__(self, client: DeepseekClient) -> None:
        self._client = client

    async def stream_chat(
        self,
        messages: List[JsonDict],
        tools: Optional[List[JsonDict]] = None,
    ) -> AsyncIterator[StreamFrame]:
        """
        功能:
            调用 DeepSeek 流式接口.
        参数:
            messages: List[Dict], OpenAI-compatible messages.
            tools: Optional[List[Dict]], OpenAI-compatible tools.
        返回:
            AsyncIterator[StreamFrame], 流式帧.
        """
        async for frame in self._client.stream_chat(messages, tools):
            yield frame
