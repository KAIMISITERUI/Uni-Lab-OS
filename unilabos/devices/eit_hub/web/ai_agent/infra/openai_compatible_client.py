# -*- coding: utf-8 -*-
"""
功能:
    OpenAI-compatible Chat Completions 异步流式客户端.
    DeepSeek 和 OpenAI 都通过该客户端接入, 上层只接收统一 StreamFrame.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from .config_store import AiAgentConfigStore, resolve_provider_credentials
from .model_catalog import PROVIDER_DEEPSEEK, PROVIDER_OPENAI
from .stream_frame import StreamFrame

logger = logging.getLogger("EITHubOpenAICompatibleClient")

JsonDict = Dict[str, Any]


@dataclass
class OpenAICompatibleSettings:
    """
    功能:
        OpenAI-compatible provider 运行时配置.
    参数:
        provider_id: str, provider ID.
        provider_label: str, provider 展示名称.
        api_key: str, API Key.
        base_url: str, 接口前缀.
        model: str, 模型 ID.
        timeout_s: float, 请求总超时秒.
        reasoning_effort: Optional[str], 思考深度档位 (low/medium/high/xhigh), None 表不带.
    """

    provider_id: str
    provider_label: str
    api_key: str
    base_url: str
    model: str
    timeout_s: float = 120.0
    reasoning_effort: Optional[str] = None

    @classmethod
    def load(
        cls,
        provider_id: str,
        model: str,
        reasoning_effort: Optional[str] = None,
        store: Optional[AiAgentConfigStore] = None,
    ) -> "OpenAICompatibleSettings":
        """
        功能:
            分层加载 OpenAI-compatible provider 凭证, 并把当前选中的 model / 思考档位绑定到 settings.
        参数:
            provider_id: str, provider ID, 仅支持 deepseek 或 openai.
            model: str, 当前 base_model 决定的实际 API 模型名.
            reasoning_effort: Optional[str], 当前 thinking_level 决定的 reasoning_effort, 无则 None.
            store: Optional[AiAgentConfigStore], UI 凭证存储.
        返回:
            OpenAICompatibleSettings, 已校验的运行时配置.
        """
        if provider_id not in (PROVIDER_DEEPSEEK, PROVIDER_OPENAI):
            raise ValueError(f"OpenAI-compatible 客户端不支持 provider: {provider_id}")
        config = store.load() if store is not None else None
        creds = resolve_provider_credentials(provider_id, config)
        if creds.api_key == "":
            raise ValueError(
                f"未配置 {creds.provider_label} API Key, "
                f"请在 AI 助手页面的 [设置] 中填入或配置 {creds.api_key_env} 环境变量."
            )
        return cls(
            provider_id=creds.provider_id,
            provider_label=creds.provider_label,
            api_key=creds.api_key,
            base_url=creds.base_url.rstrip("/"),
            model=model,
            timeout_s=creds.timeout_s,
            reasoning_effort=reasoning_effort,
        )


@dataclass
class _ToolCallAcc:
    """
    功能:
        流式 tool_calls 的累加器, 按 index 维护 id/name/arguments_text 三个字段的拼接进度.
    """

    id: str = ""
    name: str = ""
    arguments_text: str = ""


class OpenAICompatibleClient:
    """
    功能:
        OpenAI-compatible 流式聊天客户端. 每次请求使用构造时传入的 settings.
    """

    def __init__(self, settings: OpenAICompatibleSettings) -> None:
        self._settings = settings

    async def stream_chat(
        self,
        messages: List[JsonDict],
        tools: Optional[List[JsonDict]] = None,
    ) -> AsyncIterator[StreamFrame]:
        """
        功能:
            发起一次流式 chat/completions 请求.
        参数:
            messages: List[Dict], OpenAI 协议 messages 数组.
            tools: Optional[List[Dict]], OpenAI tools 数组.
        返回:
            AsyncIterator[StreamFrame], 流式帧序列.
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
        if self._settings.reasoning_effort is not None:
            # 透传给 gateway / 上游, 触发上游模型的思考档位 (low/medium/high/xhigh).
            payload["reasoning_effort"] = self._settings.reasoning_effort
        if tools is not None and len(tools) > 0:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        tool_acc: Dict[int, _ToolCallAcc] = {}
        reasoning_content_parts: List[str] = []
        finish_reason: Optional[str] = None
        prompt_tokens: Optional[int] = None
        completion_tokens: Optional[int] = None
        # 仅在首次出现 reasoning / tool_calls delta 时各发一次 phase 帧, 避免冗余事件.
        phase_thinking_emitted = False
        phase_tool_calling_emitted = False

        try:
            async with httpx.AsyncClient(timeout=self._settings.timeout_s) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    if response.status_code >= 400:
                        body = await response.aread()
                        error_text = body.decode("utf-8", errors="replace")
                        logger.error(
                            "%s HTTP 错误: %s, %s",
                            self._settings.provider_label,
                            response.status_code,
                            error_text,
                        )
                        yield StreamFrame(
                            kind="error",
                            error_message=(
                                f"{self._settings.provider_label} 接口返回 "
                                f"{response.status_code}: {error_text[:300]}"
                            ),
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
                            logger.warning("%s 流式片段非 JSON: %s", self._settings.provider_label, data_text[:120])
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
                            if phase_thinking_emitted is False:
                                # 首个 reasoning_content 增量, 通知前端进入 "正在思考" 阶段.
                                yield StreamFrame(kind="phase", phase="thinking")
                                phase_thinking_emitted = True
                            reasoning_content_parts.append(reasoning_delta)

                        text_delta = delta.get("content")
                        if isinstance(text_delta, str) is True and text_delta != "":
                            yield StreamFrame(kind="token", text=text_delta)

                        tool_calls_delta = delta.get("tool_calls")
                        # 先 accumulate, 再判断是否应当发 phase.
                        # 这样能尽量在 tool_acc 已经拿到 name 时一并把工具名带给前端,
                        # 避免先发一个空 name 的 phase 再补发.
                        self._accumulate_tool_call_delta(tool_acc, tool_calls_delta)
                        if (
                            isinstance(tool_calls_delta, list) is True
                            and len(tool_calls_delta) > 0
                            and phase_tool_calling_emitted is False
                        ):
                            # 取已 accumulate 的首个非空工具名一同发出, 没有则发 None 由前端兜底为 "正在调用工具".
                            first_tool_name = ""
                            for key in sorted(tool_acc.keys()):
                                candidate = tool_acc[key].name
                                if candidate != "":
                                    first_tool_name = candidate
                                    break
                            yield StreamFrame(
                                kind="phase",
                                phase="tool_calling",
                                tool_name=first_tool_name or None,
                            )
                            phase_tool_calling_emitted = True

                        choice_finish = choice.get("finish_reason")
                        if isinstance(choice_finish, str) is True and choice_finish != "":
                            finish_reason = choice_finish

        except httpx.HTTPError as exc:
            logger.exception("%s 请求异常", self._settings.provider_label)
            yield StreamFrame(kind="error", error_message=f"{self._settings.provider_label} 请求失败: {exc}")
            return

        yield StreamFrame(
            kind="done",
            reasoning_content=_join_or_none(reasoning_content_parts),
            finish_reason=finish_reason or "stop",
            tool_calls=_build_tool_calls(tool_acc),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    def _accumulate_tool_call_delta(self, tool_acc: Dict[int, _ToolCallAcc], tool_call_delta: Any) -> None:
        """
        功能:
            合并 OpenAI-compatible 流式 tool_calls delta.
        参数:
            tool_acc: Dict[int, _ToolCallAcc], 累加器.
            tool_call_delta: Any, delta.tool_calls 原始值.
        返回:
            None.
        """
        if isinstance(tool_call_delta, list) is False:
            return
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


def _build_tool_calls(tool_acc: Dict[int, _ToolCallAcc]) -> Optional[List[JsonDict]]:
    """
    功能:
        将工具调用累加器转换为 runtime 统一结构.
    参数:
        tool_acc: Dict[int, _ToolCallAcc], 工具调用累加器.
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
                "id": acc.id or f"call_{key}",
                "name": acc.name,
                "arguments_text": acc.arguments_text or "{}",
            }
        )
    if len(result) == 0:
        return None
    return result
