# -*- coding: utf-8 -*-
"""
功能:
    DeepSeek Chat Completions 异步流式客户端, 兼容 OpenAI 协议.
    使用 httpx.AsyncClient.stream POST, 行级解析 SSE data: ... 行,
    把增量文本与 tool_calls delta 合并成有序事件, 上层编排器据此分发.
    DeepSeek 流式 tool_calls 的 arguments 会按 index 分多次返回, 必须按 index 累加 arguments 字符串.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional, TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from .config_store import AiAgentConfigStore

logger = logging.getLogger("EITHubDeepseekClient")

JsonDict = Dict[str, Any]

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"
MODEL_OPTIONS: List[JsonDict] = [
    {"label": "快速", "value": "deepseek-v4-flash"},
    {"label": "推理", "value": "deepseek-v4-pro"},
]


@dataclass
class DeepseekSettings:
    """
    功能:
        DeepSeek 接入参数, 支持环境变量加载.
    参数:
        api_key: str, 平台密钥.
        base_url: str, 接口前缀.
        model: str, 模型 ID.
        timeout_s: float, 请求总超时秒.
    """

    api_key: str
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout_s: float = 120.0

    @classmethod
    def load(cls, store: Optional["AiAgentConfigStore"] = None) -> "DeepseekSettings":
        """
        功能:
            分层加载配置: UI 持久化的 store 优先, 字段缺失时回退环境变量.
            合并完成后仍缺 API Key 抛 ValueError, 由路由层翻译为 503 提示用户去 UI 配置.
        参数:
            store: Optional[AiAgentConfigStore], UI 配置存储单例, None 表示仅用 env.
        返回:
            DeepseekSettings, 已校验的配置实例.
        """
        # UI 优先
        ui_api_key: Optional[str] = None
        ui_base_url: Optional[str] = None
        ui_model: Optional[str] = None
        ui_timeout: Optional[float] = None
        if store is not None:
            ui_config = store.load()
            ui_api_key = ui_config.api_key
            ui_base_url = ui_config.base_url
            ui_model = ui_config.model
            ui_timeout = ui_config.timeout_s

        # 回退 env
        env_api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        env_base_url = os.getenv("DEEPSEEK_BASE_URL", "").strip()
        env_model = os.getenv("DEEPSEEK_MODEL", "").strip()
        env_timeout_text = os.getenv("DEEPSEEK_TIMEOUT_S", "").strip()
        try:
            env_timeout = float(env_timeout_text) if env_timeout_text != "" else None
        except ValueError:
            env_timeout = None

        api_key = ui_api_key or env_api_key
        if api_key == "":
            raise ValueError("未配置 DeepSeek API Key, 请在 AI 助手页面的 [设置] 中填入或配置 DEEPSEEK_API_KEY 环境变量.")

        base_url = ui_base_url or env_base_url or DEFAULT_BASE_URL
        model = ui_model or env_model or DEFAULT_MODEL
        timeout_s = ui_timeout if ui_timeout is not None else (env_timeout if env_timeout is not None else 120.0)

        return cls(api_key=api_key, base_url=base_url.rstrip("/"), model=model, timeout_s=timeout_s)

    # 兼容老接口的别名: 现有代码若直接调 from_env 会自动走 UI 优先逻辑.
    from_env = load


@dataclass
class _ToolCallAcc:
    """
    功能:
        流式 tool_calls 的累加器, 按 index 维护 id/name/arguments_text 三个字段的拼接进度.
    """

    id: str = ""
    name: str = ""
    arguments_text: str = ""


@dataclass
class StreamFrame:
    """
    功能:
        deepseek_client 对外 yield 的统一事件帧, 上层编排器只关心这层抽象.
    参数:
        kind: str, 帧类型 token / tool_call_complete / done / error.
        text: str 或 None, 仅 kind=token 时有效, 增量文本片段.
        reasoning_content: str 或 None, 仅 kind=done 时有效, DeepSeek thinking 内容.
        finish_reason: str 或 None, 仅 kind=done 时有效, OpenAI 协议的结束原因.
        tool_calls: List[Dict] 或 None, 仅 kind=tool_call_complete 或 kind=done 时有效.
        prompt_tokens: int 或 None, 仅 kind=done 时有效.
        completion_tokens: int 或 None, 仅 kind=done 时有效.
        error_message: str 或 None, 仅 kind=error 时有效.
    """

    kind: str
    text: Optional[str] = None
    reasoning_content: Optional[str] = None
    finish_reason: Optional[str] = None
    tool_calls: Optional[List[JsonDict]] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    error_message: Optional[str] = None


class DeepseekClient:
    """
    功能:
        DeepSeek 流式聊天客户端, 单例使用. 不缓存 API Key, 每次从 settings 取.
    """

    def __init__(self, settings: DeepseekSettings) -> None:
        self._settings = settings

    async def stream_chat(
        self,
        messages: List[JsonDict],
        tools: Optional[List[JsonDict]] = None,
    ) -> AsyncIterator[StreamFrame]:
        """
        功能:
            发起一次流式 chat 请求, 异步迭代输出帧序列.
        参数:
            messages: List[Dict], OpenAI 协议的 messages 数组.
            tools: List[Dict] 或 None, 工具 JSON Schema 列表.
        返回:
            AsyncIterator[StreamFrame], 帧序列, 顺序为零或多个 token, 一个 done.
        """
        url = f"{self._settings.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._settings.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        payload: JsonDict = {
            "model": self._settings.model,
            "messages": messages,
            "stream": True,
        }
        if tools is not None and len(tools) > 0:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        tool_acc: Dict[int, _ToolCallAcc] = {}
        reasoning_content_parts: List[str] = []
        finish_reason: Optional[str] = None
        prompt_tokens: Optional[int] = None
        completion_tokens: Optional[int] = None

        try:
            async with httpx.AsyncClient(timeout=self._settings.timeout_s) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    if response.status_code >= 400:
                        body = await response.aread()
                        error_text = body.decode("utf-8", errors="replace")
                        logger.error("DeepSeek HTTP 错误: %s, %s", response.status_code, error_text)
                        yield StreamFrame(
                            kind="error",
                            error_message=f"DeepSeek 接口返回 {response.status_code}: {error_text[:300]}",
                        )
                        return

                    async for raw_line in response.aiter_lines():
                        if raw_line is None:
                            continue
                        line = raw_line.strip()
                        if line == "":
                            continue
                        if line.startswith("data:") is False:
                            continue
                        data_text = line[len("data:"):].strip()
                        if data_text == "[DONE]":
                            break
                        try:
                            chunk: JsonDict = json.loads(data_text)
                        except json.JSONDecodeError:
                            logger.warning("DeepSeek 流式片段非 JSON: %s", data_text[:120])
                            continue

                        choices = chunk.get("choices") or []
                        usage = chunk.get("usage")
                        if isinstance(usage, dict) is True:
                            prompt_tokens = int(usage.get("prompt_tokens") or prompt_tokens or 0)
                            completion_tokens = int(usage.get("completion_tokens") or completion_tokens or 0)
                        if len(choices) == 0:
                            continue

                        choice = choices[0]
                        delta = choice.get("delta") or {}

                        reasoning_delta = delta.get("reasoning_content")
                        if isinstance(reasoning_delta, str) is True and reasoning_delta != "":
                            reasoning_content_parts.append(reasoning_delta)

                        text_delta = delta.get("content")
                        if isinstance(text_delta, str) is True and text_delta != "":
                            yield StreamFrame(kind="token", text=text_delta)

                        tool_call_delta = delta.get("tool_calls")
                        if isinstance(tool_call_delta, list) is True:
                            for item in tool_call_delta:
                                if isinstance(item, dict) is False:
                                    continue
                                index = int(item.get("index", 0))
                                acc = tool_acc.setdefault(index, _ToolCallAcc())
                                call_id = item.get("id")
                                if isinstance(call_id, str) is True and call_id != "":
                                    acc.id = call_id
                                fn = item.get("function") or {}
                                name = fn.get("name")
                                if isinstance(name, str) is True and name != "":
                                    acc.name = name
                                args_chunk = fn.get("arguments")
                                if isinstance(args_chunk, str) is True:
                                    acc.arguments_text += args_chunk

                        choice_finish = choice.get("finish_reason")
                        if isinstance(choice_finish, str) is True and choice_finish != "":
                            finish_reason = choice_finish

        except httpx.HTTPError as exc:
            logger.exception("DeepSeek 请求异常")
            yield StreamFrame(kind="error", error_message=f"DeepSeek 请求失败: {exc}")
            return

        tool_calls_list: List[JsonDict] = []
        if len(tool_acc) > 0:
            ordered_keys = sorted(tool_acc.keys())
            for key in ordered_keys:
                acc = tool_acc[key]
                if acc.name == "":
                    continue
                tool_calls_list.append(
                    {
                        "id": acc.id or f"call_{key}",
                        "name": acc.name,
                        "arguments_text": acc.arguments_text or "{}",
                    }
                )

        reasoning_content = "".join(reasoning_content_parts)
        reasoning_content_value = None
        if reasoning_content != "":
            reasoning_content_value = reasoning_content

        yield StreamFrame(
            kind="done",
            reasoning_content=reasoning_content_value,
            finish_reason=finish_reason or "stop",
            tool_calls=tool_calls_list if len(tool_calls_list) > 0 else None,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
