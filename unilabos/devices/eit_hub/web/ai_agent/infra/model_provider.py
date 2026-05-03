# -*- coding: utf-8 -*-
"""
功能:
    模型调用抽象层. 业务 runtime 只依赖 ModelProvider, 不直接依赖具体厂商客户端.
"""

from __future__ import annotations

from typing import AsyncIterator, List, Optional, Protocol

from .stream_frame import StreamFrame

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


class StreamingClient(Protocol):
    """
    功能:
        具备 stream_chat 能力的底层模型客户端协议.
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


class ClientModelProvider:
    """
    功能:
        通用模型 provider, 包装任意返回 StreamFrame 的底层客户端.
    """

    def __init__(self, client: StreamingClient) -> None:
        self._client = client

    async def stream_chat(
        self,
        messages: List[JsonDict],
        tools: Optional[List[JsonDict]] = None,
    ) -> AsyncIterator[StreamFrame]:
        """
        功能:
            调用底层模型客户端的流式接口.
        参数:
            messages: List[Dict], 模型消息.
            tools: Optional[List[Dict]], 工具 schema.
        返回:
            AsyncIterator[StreamFrame], 流式帧.
        """
        async for frame in self._client.stream_chat(messages, tools):
            yield frame


DeepSeekModelProvider = ClientModelProvider
