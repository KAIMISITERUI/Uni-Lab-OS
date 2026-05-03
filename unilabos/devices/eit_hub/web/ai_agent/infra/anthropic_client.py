# -*- coding: utf-8 -*-
"""
功能:
    Anthropic Messages API 异步流式客户端. 负责把 EIT Hub 内部的
    OpenAI-compatible messages/tools 转换为 Claude 协议, 再转换回统一 StreamFrame.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from .config_store import AiAgentConfigStore, resolve_provider_credentials
from .model_catalog import PROVIDER_ANTHROPIC
from .stream_frame import StreamFrame

logger = logging.getLogger("EITHubAnthropicClient")

JsonDict = Dict[str, Any]

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 8192


@dataclass
class AnthropicSettings:
    """
    功能:
        Anthropic provider 运行时配置.
    参数:
        api_key: str, Anthropic API Key.
        base_url: str, 接口前缀.
        model: str, 模型 ID.
        timeout_s: float, 请求总超时秒.
        max_tokens: int, 单轮最大输出 token 数 (开启 thinking 时会按 budget 自动抬高).
        thinking_budget: Optional[int], thinking.budget_tokens; None 表不开 thinking.
    """

    api_key: str
    base_url: str
    model: str
    timeout_s: float = 120.0
    max_tokens: int = DEFAULT_MAX_TOKENS
    thinking_budget: Optional[int] = None

    @classmethod
    def load(
        cls,
        model: str,
        thinking_budget: Optional[int] = None,
        store: Optional[AiAgentConfigStore] = None,
    ) -> "AnthropicSettings":
        """
        功能:
            分层加载 Anthropic provider 凭证, 并把当前选中的 model / thinking_budget 绑定到 settings.
            thinking_budget 非 None 时, max_tokens 自动抬到 budget + 4096 以满足 Anthropic 的硬约束.
        参数:
            model: str, 当前 base_model 决定的实际 API 模型名.
            thinking_budget: Optional[int], 当前 thinking_level 决定的 budget_tokens, 无则 None.
            store: Optional[AiAgentConfigStore], UI 凭证存储.
        返回:
            AnthropicSettings, 已校验的运行时配置.
        """
        config = store.load() if store is not None else None
        creds = resolve_provider_credentials(PROVIDER_ANTHROPIC, config)
        if creds.api_key == "":
            raise ValueError(
                f"未配置 {creds.provider_label} API Key, "
                f"请在 AI 助手页面的 [设置] 中填入或配置 {creds.api_key_env} 环境变量."
            )
        # 开思考时 max_tokens 必须 > budget_tokens, 抬到 budget + 4096 给最终回答留余量.
        if thinking_budget is not None:
            max_tokens = max(DEFAULT_MAX_TOKENS, int(thinking_budget) + 4096)
        else:
            max_tokens = DEFAULT_MAX_TOKENS
        return cls(
            api_key=creds.api_key,
            base_url=creds.base_url.rstrip("/"),
            model=model,
            timeout_s=creds.timeout_s,
            max_tokens=max_tokens,
            thinking_budget=thinking_budget,
        )


@dataclass
class _AnthropicToolAcc:
    """
    功能:
        Anthropic 流式 tool_use 累加器.
    参数:
        id: str, tool_use block ID.
        name: str, 工具名称.
        arguments_text: str, input_json_delta 拼接结果.
    """

    id: str
    name: str
    arguments_text: str = ""


class AnthropicClient:
    """
    功能:
        Anthropic Messages API 流式聊天客户端.
    """

    def __init__(self, settings: AnthropicSettings) -> None:
        self._settings = settings

    async def stream_chat(
        self,
        messages: List[JsonDict],
        tools: Optional[List[JsonDict]] = None,
    ) -> AsyncIterator[StreamFrame]:
        """
        功能:
            发起一次 Anthropic Messages API 流式请求.
        参数:
            messages: List[Dict], OpenAI-compatible messages.
            tools: Optional[List[Dict]], OpenAI-compatible tools.
        返回:
            AsyncIterator[StreamFrame], 流式帧序列.
        """
        system_text, claude_messages = _convert_messages(messages)
        payload: JsonDict = {
            "model": self._settings.model,
            "max_tokens": self._settings.max_tokens,
            "messages": claude_messages,
            "stream": True,
        }
        if self._settings.thinking_budget is not None:
            # Anthropic extended thinking, 由 budget_tokens 决定上游思考预算.
            payload["thinking"] = {
                "type": "enabled",
                "budget_tokens": int(self._settings.thinking_budget),
            }
        if system_text != "":
            payload["system"] = system_text
        claude_tools = _convert_tools(tools)
        if len(claude_tools) > 0:
            payload["tools"] = claude_tools

        headers = {
            "x-api-key": self._settings.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
            "accept": "text/event-stream",
        }
        url = f"{self._settings.base_url}/v1/messages"

        tool_acc: Dict[int, _AnthropicToolAcc] = {}
        # Claude thinking 流入帧, done 帧时拼成 reasoning_content 供前端展示.
        thinking_parts: List[str] = []
        prompt_tokens: Optional[int] = None
        completion_tokens: Optional[int] = None
        finish_reason: Optional[str] = None

        try:
            async with httpx.AsyncClient(timeout=self._settings.timeout_s) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    if response.status_code >= 400:
                        body = await response.aread()
                        error_text = body.decode("utf-8", errors="replace")
                        logger.error("Anthropic HTTP 错误: %s, %s", response.status_code, error_text)
                        yield StreamFrame(
                            kind="error",
                            error_message=f"Anthropic 接口返回 {response.status_code}: {error_text[:300]}",
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
                        try:
                            event_data: JsonDict = json.loads(data_text)
                        except json.JSONDecodeError:
                            logger.warning("Anthropic 流式片段非 JSON: %s", data_text[:120])
                            continue

                        # 单条 Anthropic 事件可能映射出多帧 (例如 tool_use 块开始时同时
                        # 产出 phase=tool_calling 帧并写入累加器), 故返回列表统一处理.
                        for frame in self._handle_stream_event(event_data, tool_acc, thinking_parts):
                            yield frame

                        event_type = str(event_data.get("type") or "")
                        if event_type == "message_start":
                            usage = (event_data.get("message") or {}).get("usage") or {}
                            prompt_tokens = _optional_int(usage.get("input_tokens"), prompt_tokens)
                            completion_tokens = _optional_int(usage.get("output_tokens"), completion_tokens)
                        elif event_type == "message_delta":
                            delta = event_data.get("delta") or {}
                            stop_reason = delta.get("stop_reason")
                            if isinstance(stop_reason, str) is True and stop_reason != "":
                                finish_reason = _map_stop_reason(stop_reason)
                            usage = event_data.get("usage") or {}
                            completion_tokens = _optional_int(usage.get("output_tokens"), completion_tokens)
                        elif event_type == "error":
                            error = event_data.get("error") or {}
                            message = str(error.get("message") or "Anthropic 请求失败")
                            yield StreamFrame(kind="error", error_message=message)
                            return

        except httpx.HTTPError as exc:
            logger.exception("Anthropic 请求异常")
            yield StreamFrame(kind="error", error_message=f"Anthropic 请求失败: {exc}")
            return

        yield StreamFrame(
            kind="done",
            finish_reason=finish_reason or "stop",
            tool_calls=_build_tool_calls(tool_acc),
            reasoning_content=_join_or_none(thinking_parts),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    def _handle_stream_event(
        self,
        event_data: JsonDict,
        tool_acc: Dict[int, _AnthropicToolAcc],
        thinking_parts: List[str],
    ) -> List[StreamFrame]:
        """
        功能:
            处理 Anthropic 单个流式事件, 文本事件立即转换为 token 帧.
            content_block_start 中 thinking / tool_use 块开始时, 额外 yield 一帧 phase 用于前端阶段提示.
            extended thinking 的 thinking_delta 累加到 thinking_parts, 由调用方在 done 帧填到 reasoning_content.
        参数:
            event_data: Dict[str, Any], SSE data JSON.
            tool_acc: Dict[int, _AnthropicToolAcc], 工具调用累加器.
            thinking_parts: List[str], thinking_delta 文本累加列表.
        返回:
            List[StreamFrame], 单事件可能产生 0 / 1 / 2 个帧 (phase + token/error 等).
        """
        event_type = str(event_data.get("type") or "")
        if event_type == "content_block_start":
            block = event_data.get("content_block") or {}
            block_type = str(block.get("type") or "")
            if block_type == "tool_use":
                index = int(event_data.get("index") or 0)
                tool_input = block.get("input")
                arguments_text = ""
                if isinstance(tool_input, dict) is True and len(tool_input) > 0:
                    arguments_text = json.dumps(tool_input, ensure_ascii=False)
                tool_name = str(block.get("name") or "")
                tool_acc[index] = _AnthropicToolAcc(
                    id=str(block.get("id") or f"toolu_{index}"),
                    name=tool_name,
                    arguments_text=arguments_text,
                )
                # 模型决定调用工具, 立即提示前端进入 "正在调用 {tool_name}" 阶段.
                return [StreamFrame(kind="phase", phase="tool_calling", tool_name=tool_name or None)]
            if block_type == "thinking":
                # extended thinking 块开始, 提示前端进入 "正在思考" 阶段.
                return [StreamFrame(kind="phase", phase="thinking")]
            return []

        if event_type != "content_block_delta":
            return []

        index = int(event_data.get("index") or 0)
        delta = event_data.get("delta") or {}
        delta_type = str(delta.get("type") or "")
        if delta_type == "text_delta":
            text = delta.get("text")
            if isinstance(text, str) is True and text != "":
                return [StreamFrame(kind="token", text=text)]
        elif delta_type == "thinking_delta":
            text = delta.get("thinking")
            if isinstance(text, str) is True and text != "":
                thinking_parts.append(text)
        elif delta_type == "input_json_delta":
            partial_json = delta.get("partial_json")
            if isinstance(partial_json, str) is True:
                acc = tool_acc.get(index)
                if acc is not None:
                    acc.arguments_text += partial_json
        return []


def _join_or_none(parts: List[str]) -> Optional[str]:
    """
    功能:
        拼接文本片段, 空结果返回 None.
    参数:
        parts: List[str], 文本片段.
    返回:
        Optional[str], 拼接结果或 None.
    """
    text = "".join(parts)
    if text == "":
        return None
    return text


def _convert_tools(tools: Optional[List[JsonDict]]) -> List[JsonDict]:
    """
    功能:
        将 OpenAI tools 数组转换为 Anthropic tools 数组.
    参数:
        tools: Optional[List[Dict]], OpenAI-compatible tools.
    返回:
        List[Dict], Anthropic tools.
    """
    if tools is None:
        return []
    result: List[JsonDict] = []
    for tool in tools:
        if isinstance(tool, dict) is False:
            continue
        function = tool.get("function") or {}
        name = function.get("name")
        if isinstance(name, str) is False or name == "":
            continue
        input_schema = function.get("parameters")
        if isinstance(input_schema, dict) is False:
            input_schema = {"type": "object", "properties": {}, "additionalProperties": False}
        result.append(
            {
                "name": name,
                "description": str(function.get("description") or ""),
                "input_schema": input_schema,
            }
        )
    return result


def _convert_messages(messages: List[JsonDict]) -> tuple[str, List[JsonDict]]:
    """
    功能:
        将 OpenAI-compatible messages 转换为 Anthropic system + messages.
    参数:
        messages: List[Dict], OpenAI-compatible messages.
    返回:
        tuple[str, List[Dict]], system 文本和 Anthropic messages.
    """
    system_parts: List[str] = []
    converted: List[JsonDict] = []
    pending_tool_results: List[JsonDict] = []

    def _flush_tool_results() -> None:
        if len(pending_tool_results) == 0:
            return
        converted.append({"role": "user", "content": list(pending_tool_results)})
        pending_tool_results.clear()

    for message in messages:
        role = str(message.get("role") or "")
        if role == "system":
            content = str(message.get("content") or "")
            if content != "":
                system_parts.append(content)
            continue

        if role == "tool":
            pending_tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": str(message.get("tool_call_id") or ""),
                    "content": str(message.get("content") or ""),
                }
            )
            continue

        _flush_tool_results()
        if role == "user":
            converted.append({"role": "user", "content": str(message.get("content") or "")})
        elif role == "assistant":
            converted.append({"role": "assistant", "content": _assistant_content_blocks(message)})

    _flush_tool_results()
    return "\n\n".join(system_parts), converted


def _assistant_content_blocks(message: JsonDict) -> List[JsonDict]:
    """
    功能:
        将 assistant 文本和 OpenAI tool_calls 转换为 Claude content blocks.
    参数:
        message: Dict[str, Any], OpenAI-compatible assistant message.
    返回:
        List[Dict], Claude assistant content blocks.
    """
    blocks: List[JsonDict] = []
    content = str(message.get("content") or "")
    if content != "":
        blocks.append({"type": "text", "text": content})
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list) is True:
        for tool_call in tool_calls:
            if isinstance(tool_call, dict) is False:
                continue
            function = tool_call.get("function") or {}
            name = str(function.get("name") or tool_call.get("name") or "")
            if name == "":
                continue
            arguments_text = str(function.get("arguments") or tool_call.get("arguments_text") or "{}")
            blocks.append(
                {
                    "type": "tool_use",
                    "id": str(tool_call.get("id") or ""),
                    "name": name,
                    "input": _parse_json_object(arguments_text),
                }
            )
    if len(blocks) == 0:
        blocks.append({"type": "text", "text": ""})
    return blocks


def _parse_json_object(text: str) -> JsonDict:
    """
    功能:
        将工具参数 JSON 文本解析为对象, 非对象返回空对象.
    参数:
        text: str, JSON 文本.
    返回:
        Dict[str, Any], 解析后的对象.
    """
    try:
        value = json.loads(text) if text.strip() != "" else {}
    except json.JSONDecodeError:
        return {}
    if isinstance(value, dict) is False:
        return {}
    return value


def _build_tool_calls(tool_acc: Dict[int, _AnthropicToolAcc]) -> Optional[List[JsonDict]]:
    """
    功能:
        将 Anthropic tool_use 累加器转换为 runtime 统一结构.
    参数:
        tool_acc: Dict[int, _AnthropicToolAcc], 工具调用累加器.
    返回:
        Optional[List[Dict]], 工具调用列表.
    """
    result: List[JsonDict] = []
    for key in sorted(tool_acc.keys()):
        acc = tool_acc[key]
        if acc.name == "":
            continue
        result.append(
            {
                "id": acc.id or f"toolu_{key}",
                "name": acc.name,
                "arguments_text": acc.arguments_text or "{}",
            }
        )
    if len(result) == 0:
        return None
    return result


def _map_stop_reason(stop_reason: str) -> str:
    """
    功能:
        将 Anthropic stop_reason 映射为 runtime 使用的结束原因.
    参数:
        stop_reason: str, Anthropic 结束原因.
    返回:
        str, 标准化结束原因.
    """
    if stop_reason == "tool_use":
        return "tool_calls"
    if stop_reason == "end_turn":
        return "stop"
    if stop_reason == "max_tokens":
        return "length"
    return stop_reason


def _optional_int(value: Any, fallback: Optional[int]) -> Optional[int]:
    """
    功能:
        将任意值规整为 int, 失败时返回 fallback.
    参数:
        value: Any, 原始值.
        fallback: Optional[int], 失败时返回值.
    返回:
        Optional[int], 整数或 fallback.
    """
    if value is None:
        return fallback
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback
