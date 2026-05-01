# -*- coding: utf-8 -*-
"""
功能:
    AI 助手对话编排器. 负责把 user 消息 -> DeepSeek 流式调用 -> tool_calls 处理 ->
    HITL 等待 -> 续轮 LLM 调用串成一条 SSE 事件流, 同时把所有消息行落到 SQLite.

    核心不变量:
    - assistant.tool_calls[i].id 必须与 tool 行的 tool_call_id 一一对应才能进入下一轮 LLM
    - 控制类工具不落地执行结果, 只写 pending_confirm 占位行, 由前端确认后再 resolve
    - pending_confirm 状态的行不进入 OpenAI messages 数组, 避免协议报错
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

from ..domain import tools as ai_agent_tools
from ..domain.store import (
    AiAgentStore,
    ROLE_ASSISTANT,
    ROLE_TOOL,
    STATUS_COMMITTED,
    STATUS_PENDING,
    STATUS_REJECTED,
)
from ..infra.deepseek_client import DeepseekClient
from .events import SseEvent

logger = logging.getLogger("EITHubAiAgentOrchestrator")

JsonDict = Dict[str, Any]

# 顶层 system prompt, 让模型清楚自己处于实验室运维场景
_SYSTEM_PROMPT = (
    "你是 EIT 实验室 (Uni-Lab OS) 的 AI 助手, 服务于运维管理、合成工站、分析工站、"
    "AGV 运输车、化学品库等场景. 你可以调用提供的工具读取真实数据 (运维记录、任务历史、"
    "AGV 状态、设备连通性、化学品库) 与提交少量写操作 (运维记录、运维事件配置). "
    "写操作必须由用户在前端确认后才会真正执行, 你只需要给出参数即可. "
    "回答使用简体中文, 标点符号使用英文, 必要时用 markdown 表格或列表呈现."
)


class AiAgentOrchestrator:
    """
    功能:
        对话编排器, 单例使用. 持有 store 与 deepseek 客户端, 不持有会话级状态.
    """

    def __init__(self, store: AiAgentStore, deepseek: DeepseekClient) -> None:
        self._store = store
        self._deepseek = deepseek

    async def stream_user_turn(self, session_id: str, user_text: str) -> AsyncIterator[SseEvent]:
        """
        功能:
            处理一条用户输入. 落 user 行 -> 进入 LLM 流式回合循环.
        参数:
            session_id: str, 会话 ID.
            user_text: str, 用户消息原文.
        返回:
            AsyncIterator[SseEvent], 顺序的 SSE 事件流.
        """
        if (user_text or "").strip() == "":
            yield SseEvent(event="error", data={"message": "消息内容不能为空."})
            yield SseEvent(event="done", data={"reason": "error"})
            return

        self._store.append_user_message(session_id, user_text)
        async for event in self._run_turn_loop(session_id):
            yield event

    async def stream_tool_resolution(
        self,
        session_id: str,
        message_id: int,
        action: str,
        reject_reason: str = "",
    ) -> AsyncIterator[SseEvent]:
        """
        功能:
            处理一次用户对挂起 control_tool 的确认或拒绝, 然后续接对话循环.
        参数:
            session_id: str, 会话 ID.
            message_id: int, pending_confirm 的 tool 消息行 ID.
            action: str, confirm 或 reject.
            reject_reason: str, 拒绝时的说明文本, 留空使用默认文案.
        返回:
            AsyncIterator[SseEvent], 顺序的 SSE 事件流.
        """
        pending = self._store.get_pending_tool(session_id, message_id)
        if pending is None:
            yield SseEvent(event="error", data={"message": f"未找到等待确认的工具调用: {message_id}"})
            yield SseEvent(event="done", data={"reason": "error"})
            return

        tool_name = pending.get("pending_tool_name") or ""
        tool_args = pending.get("pending_tool_args") or {}

        if action == "confirm":
            try:
                spec = ai_agent_tools.get_tool(tool_name)
                result = await asyncio.to_thread(spec.handler, tool_args)
                content = json.dumps(result, ensure_ascii=False, default=str)
                resolved = self._store.resolve_pending_tool(
                    session_id=session_id,
                    message_id=message_id,
                    new_status=STATUS_COMMITTED,
                    new_content=content,
                )
                yield SseEvent(
                    event="tool_result",
                    data={
                        "message_id": resolved["id"],
                        "tool_call_id": resolved["tool_call_id"],
                        "name": tool_name,
                        "result": result,
                    },
                )
            except Exception as exc:
                logger.exception("控制类工具执行失败: %s", tool_name)
                error_content = json.dumps(
                    {"error": str(exc), "tool": tool_name},
                    ensure_ascii=False,
                )
                self._store.resolve_pending_tool(
                    session_id=session_id,
                    message_id=message_id,
                    new_status=STATUS_COMMITTED,
                    new_content=error_content,
                )
                yield SseEvent(
                    event="tool_result",
                    data={
                        "message_id": message_id,
                        "tool_call_id": pending.get("tool_call_id"),
                        "name": tool_name,
                        "error": str(exc),
                    },
                )
        elif action == "reject":
            reason_text = (reject_reason or "").strip()
            if reason_text == "":
                reason_text = "用户拒绝执行该操作, 未提供具体原因."
            content = json.dumps(
                {"rejected": True, "reason": reason_text},
                ensure_ascii=False,
            )
            self._store.resolve_pending_tool(
                session_id=session_id,
                message_id=message_id,
                new_status=STATUS_REJECTED,
                new_content=content,
            )
            yield SseEvent(
                event="tool_result",
                data={
                    "message_id": message_id,
                    "tool_call_id": pending.get("tool_call_id"),
                    "name": tool_name,
                    "rejected": True,
                    "reason": reason_text,
                },
            )
        else:
            yield SseEvent(event="error", data={"message": f"未支持的 action: {action}"})
            yield SseEvent(event="done", data={"reason": "error"})
            return

        async for event in self._run_turn_loop(session_id):
            yield event

    # ---------- 内部循环 ----------

    async def _run_turn_loop(self, session_id: str) -> AsyncIterator[SseEvent]:
        """
        功能:
            主循环. 反复 (处理悬挂 tool_calls -> 调 LLM) 直到模型自然结束或再次挂起.
        参数:
            session_id: str, 会话 ID.
        返回:
            AsyncIterator[SseEvent], SSE 事件流.
        """
        max_loops = 8
        for _ in range(max_loops):
            pending_event = await self._process_pending_tool_calls(session_id)
            async for event in pending_event["events"]:
                yield event
            if pending_event["paused"] is True:
                yield SseEvent(event="done", data={"reason": "pending_confirm"})
                return

            llm_done = await self._stream_one_llm_round(session_id)
            for event in llm_done["pre_events"]:
                yield event
            async for event in llm_done["frame_events"]:
                yield event
            if llm_done["finished"] is True:
                yield SseEvent(
                    event="done",
                    data={"reason": llm_done.get("finish_reason") or "stop"},
                )
                return
            # 否则继续下一轮 (LLM 想调工具)
        yield SseEvent(event="error", data={"message": "对话循环超过最大轮次, 已强制终止."})
        yield SseEvent(event="done", data={"reason": "max_loops"})

    async def _process_pending_tool_calls(self, session_id: str) -> JsonDict:
        """
        功能:
            扫描最近一条 assistant.tool_calls 行, 把还未生成 tool 行的 tool_call 按顺序处理.
            读类工具立即执行并落 committed; 控制类工具落 pending_confirm 占位并暂停循环.
        参数:
            session_id: str, 会话 ID.
        返回:
            Dict, 含 events (异步迭代器) 与 paused (bool).
        """
        events: List[SseEvent] = []
        paused = False

        rows = self._store.list_messages(session_id)
        last_assistant: Optional[JsonDict] = None
        for row in reversed(rows):
            if row.get("role") == ROLE_ASSISTANT and row.get("tool_calls"):
                last_assistant = row
                break
        if last_assistant is None:
            return {"events": _aiter(events), "paused": False}

        tool_calls = last_assistant.get("tool_calls") or []
        existing_tool_call_ids = {
            row.get("tool_call_id")
            for row in rows
            if row.get("role") == ROLE_TOOL and row.get("tool_call_id")
        }

        for tc in tool_calls:
            tc_id = tc.get("id") or ""
            if tc_id == "" or tc_id in existing_tool_call_ids:
                continue

            tool_name = tc.get("name") or ""
            try:
                args_text = tc.get("arguments_text") or "{}"
                args = json.loads(args_text) if args_text.strip() != "" else {}
            except json.JSONDecodeError as exc:
                logger.warning("tool_calls.arguments 不是合法 JSON: %s, %s", tool_name, exc)
                args = {}

            try:
                spec = ai_agent_tools.get_tool(tool_name)
            except KeyError:
                error_content = json.dumps(
                    {"error": f"未注册的工具: {tool_name}"},
                    ensure_ascii=False,
                )
                self._store.append_tool_message(
                    session_id=session_id,
                    tool_call_id=tc_id,
                    content=error_content,
                    status=STATUS_COMMITTED,
                )
                events.append(
                    SseEvent(
                        event="tool_result",
                        data={
                            "tool_call_id": tc_id,
                            "name": tool_name,
                            "error": f"未注册的工具: {tool_name}",
                        },
                    )
                )
                continue

            if spec.kind == ai_agent_tools.KIND_READ:
                events.append(
                    SseEvent(
                        event="tool_call",
                        data={
                            "tool_call_id": tc_id,
                            "name": tool_name,
                            "arguments": args,
                            "kind": "read",
                        },
                    )
                )
                try:
                    result = await asyncio.to_thread(spec.handler, args)
                    content = json.dumps(result, ensure_ascii=False, default=str)
                    self._store.append_tool_message(
                        session_id=session_id,
                        tool_call_id=tc_id,
                        content=content,
                        status=STATUS_COMMITTED,
                    )
                    events.append(
                        SseEvent(
                            event="tool_result",
                            data={
                                "tool_call_id": tc_id,
                                "name": tool_name,
                                "result": result,
                            },
                        )
                    )
                except Exception as exc:
                    logger.exception("读类工具执行失败: %s", tool_name)
                    error_content = json.dumps(
                        {"error": str(exc), "tool": tool_name},
                        ensure_ascii=False,
                    )
                    self._store.append_tool_message(
                        session_id=session_id,
                        tool_call_id=tc_id,
                        content=error_content,
                        status=STATUS_COMMITTED,
                    )
                    events.append(
                        SseEvent(
                            event="tool_result",
                            data={
                                "tool_call_id": tc_id,
                                "name": tool_name,
                                "error": str(exc),
                            },
                        )
                    )
            else:
                # 控制类工具走 HITL
                placeholder = self._store.append_tool_message(
                    session_id=session_id,
                    tool_call_id=tc_id,
                    content="(等待用户确认)",
                    status=STATUS_PENDING,
                    pending_tool_name=tool_name,
                    pending_tool_args=args,
                )
                events.append(
                    SseEvent(
                        event="pending_confirm",
                        data={
                            "message_id": placeholder["id"],
                            "tool_call_id": tc_id,
                            "name": tool_name,
                            "arguments": args,
                            "description": spec.description,
                        },
                    )
                )
                paused = True
                break

        return {"events": _aiter(events), "paused": paused}

    async def _stream_one_llm_round(self, session_id: str) -> JsonDict:
        """
        功能:
            调一次 DeepSeek 流式接口. 把 token / 错误事件转成 SseEvent, 结束后落 assistant 行.
        参数:
            session_id: str, 会话 ID.
        返回:
            Dict, 含 pre_events (List), frame_events (异步迭代器), finished (bool),
            finish_reason (str 或 None). finished=False 表示需要再处理 tool_calls.
        """
        messages = self._store.build_openai_messages(session_id)
        # 顶部加 system 引导, 不落库 (引导不计入会话历史展示)
        messages_with_system = [{"role": "system", "content": _SYSTEM_PROMPT}, *messages]
        tools_payload = ai_agent_tools.build_openai_tools_payload()

        accumulated_text_parts: List[str] = []
        sse_events: List[SseEvent] = []
        finish_reason: Optional[str] = None
        prompt_tokens: Optional[int] = None
        completion_tokens: Optional[int] = None
        reasoning_content_final: Optional[str] = None
        tool_calls_final: Optional[List[JsonDict]] = None
        had_error = False

        async for frame in self._deepseek.stream_chat(messages_with_system, tools_payload):
            if frame.kind == "token":
                accumulated_text_parts.append(frame.text or "")
                sse_events.append(SseEvent(event="token", data={"text": frame.text or ""}))
            elif frame.kind == "error":
                had_error = True
                sse_events.append(
                    SseEvent(event="error", data={"message": frame.error_message or "DeepSeek 调用失败"})
                )
                break
            elif frame.kind == "done":
                finish_reason = frame.finish_reason
                prompt_tokens = frame.prompt_tokens
                completion_tokens = frame.completion_tokens
                reasoning_content_final = frame.reasoning_content
                tool_calls_final = frame.tool_calls
                break

        if had_error is True:
            return {
                "pre_events": [],
                "frame_events": _aiter(sse_events),
                "finished": True,
                "finish_reason": "error",
            }

        accumulated_text = "".join(accumulated_text_parts)
        self._store.append_assistant_message(
            session_id=session_id,
            content=accumulated_text or None,
            tool_calls=tool_calls_final,
            reasoning_content=reasoning_content_final,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

        if finish_reason == "tool_calls" and tool_calls_final:
            return {
                "pre_events": [],
                "frame_events": _aiter(sse_events),
                "finished": False,
                "finish_reason": finish_reason,
            }

        return {
            "pre_events": [],
            "frame_events": _aiter(sse_events),
            "finished": True,
            "finish_reason": finish_reason or "stop",
        }


async def _aiter(events: List[SseEvent]) -> AsyncIterator[SseEvent]:
    """
    功能:
        把同步收集好的 SseEvent 列表包装成异步迭代器, 与 _run_turn_loop 的 yield 协议对齐.
    参数:
        events: List[SseEvent], 待发送事件.
    返回:
        AsyncIterator[SseEvent], 顺序异步发出的事件流.
    """
    for event in events:
        yield event
