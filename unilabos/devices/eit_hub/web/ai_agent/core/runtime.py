# -*- coding: utf-8 -*-
"""
功能:
    AI Agent 运行时入口. 负责会话消息, LangGraph checkpoint, 工具路由, 人工确认和 SSE 事件.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

from ..application.events import SseEvent
from ..domain.audit import AgentAuditStore
from ..domain.memory import AgentMemoryService
from ..domain.skills import SkillService
from ..domain.store import (
    AiAgentStore,
    ROLE_ASSISTANT,
    ROLE_TOOL,
    STATUS_COMMITTED,
    STATUS_PENDING,
    STATUS_REJECTED,
)
from ..domain.tools import ToolPermission, ToolRegistry, summarize_tools_for_prompt
from ..infra.model_provider import ModelProvider
from .graph import build_agent_graph
from .state import AgentState

logger = logging.getLogger("EITHubAiAgentRuntime")

JsonDict = Dict[str, Any]

_SYSTEM_PROMPT_TEMPLATE = """
你是 EIT 实验室 (Uni-Lab OS) 的 AI 助手, 服务于实验室自动化控制, 实验方案生成, 运维管理, 合成工站, 分析工站, AGV 运输车和化学品库.
你必须使用简体中文回答, 标点使用英文符号.
你只能调用已注册工具. read 工具可以自动执行. control 工具必须等待用户在前端确认, 你只负责给出准确参数.
不要编造设备状态, 任务历史, 化学品信息或知识库内容. 缺少事实时先调用工具或说明需要补充数据.

可用工具:
{tool_catalog}

可用 skills:
{skill_catalog}

长期记忆:
{memory_catalog}
""".strip()


class AgentRuntime:
    """
    功能:
        Agent 对外运行时. FastAPI 只调用这个类, 不直接接触模型客户端或工具实现.
    """

    def __init__(
        self,
        store: AiAgentStore,
        model_provider: ModelProvider,
        tool_registry: ToolRegistry,
        memory_service: AgentMemoryService,
        skill_service: SkillService,
        audit_store: AgentAuditStore,
        checkpointer: Optional[Any] = None,
    ) -> None:
        self._store = store
        self._model_provider = model_provider
        self._tool_registry = tool_registry
        self._memory_service = memory_service
        self._skill_service = skill_service
        self._audit_store = audit_store
        self._graph = build_agent_graph(checkpointer=checkpointer)

    async def stream_user_turn(self, session_id: str, user_text: str, user_id: str = "default") -> AsyncIterator[SseEvent]:
        """
        功能:
            处理一条用户消息, 输出 SSE 事件流.
        参数:
            session_id: str, 会话 ID.
            user_text: str, 用户消息.
            user_id: str, 用户 ID.
        返回:
            AsyncIterator[SseEvent], SSE 事件序列.
        """
        if (user_text or "").strip() == "":
            yield SseEvent(event="error", data={"message": "消息内容不能为空."})
            yield SseEvent(event="done", data={"reason": "error"})
            return

        self._store.append_user_message(session_id, user_text)
        await self._checkpoint(session_id=session_id, user_id=user_id, next_step="load_context")
        async for event in self._run_turn_loop(session_id=session_id, user_id=user_id, last_user_text=user_text):
            yield event

    async def resume_human_review(
        self,
        session_id: str,
        message_id: int,
        action: str,
        reject_reason: str = "",
        edited_arguments: Optional[JsonDict] = None,
        user_id: str = "default",
    ) -> AsyncIterator[SseEvent]:
        """
        功能:
            处理控制工具的人工确认, 拒绝或编辑后确认, 然后续接对话.
        参数:
            session_id: str, 会话 ID.
            message_id: int, pending tool 消息 ID.
            action: str, approve, reject 或 edit.
            reject_reason: str, 拒绝原因.
            edited_arguments: Optional[Dict[str, Any]], edit 决策后的新参数.
            user_id: str, 用户 ID.
        返回:
            AsyncIterator[SseEvent], SSE 事件序列.
        """
        pending = self._store.get_pending_tool(session_id, message_id)
        if pending is None:
            yield SseEvent(event="error", data={"message": f"未找到等待确认的工具调用: {message_id}"})
            yield SseEvent(event="done", data={"reason": "error"})
            return

        tool_name = str(pending.get("pending_tool_name") or "")
        tool_args = pending.get("pending_tool_args") or {}
        tool_call_id = str(pending.get("tool_call_id") or "")
        self._audit_store.resolve_human_review(
            session_id=session_id,
            message_id=message_id,
            decision=action,
            reviewer=user_id,
            reason=reject_reason,
        )

        if action == "approve" or action == "edit":
            args_to_execute = edited_arguments if action == "edit" and edited_arguments is not None else tool_args
            async for event in self._execute_confirmed_tool(
                session_id=session_id,
                message_id=message_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                tool_args=args_to_execute,
            ):
                yield event
        elif action == "reject":
            reason_text = (reject_reason or "").strip()
            if reason_text == "":
                reason_text = "用户拒绝执行该操作, 未提供具体原因."
            content = json.dumps({"rejected": True, "reason": reason_text}, ensure_ascii=False)
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
                    "tool_call_id": tool_call_id,
                    "name": tool_name,
                    "rejected": True,
                    "reason": reason_text,
                },
            )
        else:
            yield SseEvent(event="error", data={"message": f"不支持的确认动作: {action}"})
            yield SseEvent(event="done", data={"reason": "error"})
            return

        await self._checkpoint(session_id=session_id, user_id=user_id, next_step="llm_step")
        async for event in self._run_turn_loop(session_id=session_id, user_id=user_id, last_user_text=""):
            yield event

    async def _run_turn_loop(
        self,
        session_id: str,
        user_id: str,
        last_user_text: str,
    ) -> AsyncIterator[SseEvent]:
        """
        功能:
            执行工具处理和模型回合循环, 直到自然结束或等待人工确认.
        参数:
            session_id: str, 会话 ID.
            user_id: str, 用户 ID.
            last_user_text: str, 当前用户输入.
        返回:
            AsyncIterator[SseEvent], SSE 事件序列.
        """
        max_loops = 8
        last_assistant_text = ""
        for _ in range(max_loops):
            pending_result = await self._process_pending_tool_calls(session_id)
            async for event in pending_result["events"]:
                yield event
            if pending_result["paused"] is True:
                yield SseEvent(event="done", data={"reason": "pending_confirm"})
                return

            llm_done = await self._stream_one_llm_round(session_id)
            async for event in llm_done["frame_events"]:
                yield event
            assistant_text = str(llm_done.get("assistant_text") or "")
            if assistant_text != "":
                last_assistant_text = assistant_text
            if llm_done["finished"] is True:
                self._memory_service.persist_turn_memory(
                    session_id=session_id,
                    user_id=user_id,
                    user_text=last_user_text,
                    assistant_text=last_assistant_text,
                )
                await self._checkpoint(session_id=session_id, user_id=user_id, next_step="persist_memory")
                yield SseEvent(event="done", data={"reason": llm_done.get("finish_reason") or "stop"})
                return
        yield SseEvent(event="error", data={"message": "对话循环超过最大轮次, 已强制终止."})
        yield SseEvent(event="done", data={"reason": "max_loops"})

    async def _process_pending_tool_calls(self, session_id: str) -> JsonDict:
        """
        功能:
            扫描最近 assistant.tool_calls, 按 read/control 权限处理工具.
        参数:
            session_id: str, 会话 ID.
        返回:
            Dict[str, Any], 含 events 异步迭代器和 paused 标记.
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

        for tool_call in tool_calls:
            tc_id = str(tool_call.get("id") or "")
            if tc_id == "" or tc_id in existing_tool_call_ids:
                continue
            tool_name = str(tool_call.get("name") or "")
            args = _parse_tool_args(tool_name, str(tool_call.get("arguments_text") or "{}"))
            try:
                spec = self._tool_registry.get(tool_name)
            except KeyError:
                error_text = f"未注册的工具: {tool_name}"
                self._store.append_tool_message(
                    session_id=session_id,
                    tool_call_id=tc_id,
                    content=json.dumps({"error": error_text}, ensure_ascii=False),
                    status=STATUS_COMMITTED,
                    pending_tool_name=tool_name,
                )
                events.append(SseEvent(event="tool_result", data={"tool_call_id": tc_id, "name": tool_name, "error": error_text}))
                continue

            if spec.permission == ToolPermission.READ:
                events.append(
                    SseEvent(
                        event="tool_call",
                        data={"tool_call_id": tc_id, "name": tool_name, "arguments": args, "kind": "read"},
                    )
                )
                try:
                    result = await asyncio.to_thread(spec.execute, args)
                    content = json.dumps(result, ensure_ascii=False, default=str)
                    self._store.append_tool_message(
                        session_id=session_id,
                        tool_call_id=tc_id,
                        content=content,
                        status=STATUS_COMMITTED,
                        pending_tool_name=tool_name,
                        pending_tool_args=args,
                    )
                    self._audit_store.record_tool_event(
                        session_id=session_id,
                        tool_call_id=tc_id,
                        tool_name=tool_name,
                        permission=spec.permission.value,
                        arguments=args,
                        status="committed",
                        result=result,
                    )
                    events.append(SseEvent(event="tool_result", data={"tool_call_id": tc_id, "name": tool_name, "result": result}))
                except Exception as exc:
                    logger.exception("读类工具执行失败: %s", tool_name)
                    error_content = json.dumps({"error": str(exc), "tool": tool_name}, ensure_ascii=False)
                    self._store.append_tool_message(
                        session_id=session_id,
                        tool_call_id=tc_id,
                        content=error_content,
                        status=STATUS_COMMITTED,
                        pending_tool_name=tool_name,
                        pending_tool_args=args,
                    )
                    self._audit_store.record_tool_event(
                        session_id=session_id,
                        tool_call_id=tc_id,
                        tool_name=tool_name,
                        permission=spec.permission.value,
                        arguments=args,
                        status="error",
                        error_text=str(exc),
                    )
                    events.append(SseEvent(event="tool_result", data={"tool_call_id": tc_id, "name": tool_name, "error": str(exc)}))
            else:
                placeholder = self._store.append_tool_message(
                    session_id=session_id,
                    tool_call_id=tc_id,
                    content="(等待用户确认)",
                    status=STATUS_PENDING,
                    pending_tool_name=tool_name,
                    pending_tool_args=args,
                )
                self._audit_store.create_human_review(
                    session_id=session_id,
                    message_id=int(placeholder["id"]),
                    tool_call_id=tc_id,
                    tool_name=tool_name,
                    arguments=args,
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

    async def _execute_confirmed_tool(
        self,
        session_id: str,
        message_id: int,
        tool_call_id: str,
        tool_name: str,
        tool_args: JsonDict,
    ) -> AsyncIterator[SseEvent]:
        """
        功能:
            执行已经人工确认的控制工具.
        参数:
            session_id: str, 会话 ID.
            message_id: int, pending tool 消息 ID.
            tool_call_id: str, 工具调用 ID.
            tool_name: str, 工具名.
            tool_args: Dict[str, Any], 工具参数.
        返回:
            AsyncIterator[SseEvent], 工具结果事件.
        """
        try:
            spec = self._tool_registry.get(tool_name)
            result = await asyncio.to_thread(spec.execute, tool_args)
            content = json.dumps(result, ensure_ascii=False, default=str)
            resolved = self._store.resolve_pending_tool(
                session_id=session_id,
                message_id=message_id,
                new_status=STATUS_COMMITTED,
                new_content=content,
            )
            self._audit_store.record_tool_event(
                session_id=session_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                permission=spec.permission.value,
                arguments=tool_args,
                status="committed",
                result=result,
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
            error_content = json.dumps({"error": str(exc), "tool": tool_name}, ensure_ascii=False)
            self._store.resolve_pending_tool(
                session_id=session_id,
                message_id=message_id,
                new_status=STATUS_COMMITTED,
                new_content=error_content,
            )
            self._audit_store.record_tool_event(
                session_id=session_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                permission=ToolPermission.CONTROL.value,
                arguments=tool_args,
                status="error",
                error_text=str(exc),
            )
            yield SseEvent(
                event="tool_result",
                data={"message_id": message_id, "tool_call_id": tool_call_id, "name": tool_name, "error": str(exc)},
            )

    async def _stream_one_llm_round(self, session_id: str) -> JsonDict:
        """
        功能:
            调用模型完成一轮流式响应并落库 assistant 消息.
        参数:
            session_id: str, 会话 ID.
        返回:
            Dict[str, Any], 回合完成状态.
        """
        messages = self._store.build_openai_messages(session_id)
        messages_with_system = [{"role": "system", "content": self._build_system_prompt()}, *messages]
        tools_payload = self._tool_registry.to_openai_tools()

        accumulated_text_parts: List[str] = []
        sse_events: List[SseEvent] = []
        finish_reason: Optional[str] = None
        prompt_tokens: Optional[int] = None
        completion_tokens: Optional[int] = None
        reasoning_content_final: Optional[str] = None
        tool_calls_final: Optional[List[JsonDict]] = None
        had_error = False

        async for frame in self._model_provider.stream_chat(messages_with_system, tools_payload):
            if frame.kind == "token":
                accumulated_text_parts.append(frame.text or "")
                sse_events.append(SseEvent(event="token", data={"text": frame.text or ""}))
            elif frame.kind == "phase":
                # 模型流式中段的阶段提示 (thinking / tool_calling), 仅用于前端动效, 不落库.
                phase_value = frame.phase or ""
                if phase_value != "":
                    phase_data: JsonDict = {"phase": phase_value}
                    tool_name = frame.tool_name or ""
                    if tool_name != "":
                        phase_data["tool_name"] = tool_name
                        # 查询 ToolRegistry 取 read/control 用于前端区分颜色, 工具未注册时不附加.
                        try:
                            spec = self._tool_registry.get(tool_name)
                            phase_data["kind"] = spec.permission.value
                        except KeyError:
                            pass
                    sse_events.append(SseEvent(event="phase", data=phase_data))
            elif frame.kind == "error":
                had_error = True
                sse_events.append(SseEvent(event="error", data={"message": frame.error_message or "模型调用失败"}))
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
                "frame_events": _aiter(sse_events),
                "finished": True,
                "finish_reason": "error",
                "assistant_text": "".join(accumulated_text_parts),
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

        if finish_reason == "tool_calls" and tool_calls_final is not None and len(tool_calls_final) > 0:
            return {
                "frame_events": _aiter(sse_events),
                "finished": False,
                "finish_reason": finish_reason,
                "assistant_text": accumulated_text,
            }

        return {
            "frame_events": _aiter(sse_events),
            "finished": True,
            "finish_reason": finish_reason or "stop",
            "assistant_text": accumulated_text,
        }

    def _build_system_prompt(self) -> str:
        """
        功能:
            构造每轮模型调用的系统提示, 注入工具目录, skill catalog 和长期记忆摘要.
        返回:
            str, 系统提示.
        """
        tool_catalog = summarize_tools_for_prompt(self._tool_registry.list())
        skill_catalog = self._skill_service.build_catalog_prompt()
        if skill_catalog == "":
            skill_catalog = "当前未发现可用 skills."
        memories = self._memory_service.list_memories(user_id="default", limit=10)
        memory_lines = [f"- [{item.get('category')}] {item.get('content')}" for item in memories]
        memory_catalog = "\n".join(memory_lines) if len(memory_lines) > 0 else "当前没有长期记忆."
        return _SYSTEM_PROMPT_TEMPLATE.format(
            tool_catalog=tool_catalog,
            skill_catalog=skill_catalog,
            memory_catalog=memory_catalog,
        )

    async def _checkpoint(self, session_id: str, user_id: str, next_step: str) -> None:
        """
        功能:
            通过 LangGraph 写入轻量 checkpoint, 让会话具备可恢复执行锚点.
        参数:
            session_id: str, 会话 ID.
            user_id: str, 用户 ID.
            next_step: str, 当前阶段.
        返回:
            None.
        """
        state: AgentState = {
            "session_id": session_id,
            "user_id": user_id,
            "messages": self._store.build_openai_messages(session_id),
            "selected_tools": [spec.name for spec in self._tool_registry.list()],
            "loaded_skills": [],
            "retrieved_knowledge": [],
            "pending_action": None,
            "next_step": "persist_memory" if next_step != "tool_router" else next_step,
        }
        try:
            await asyncio.to_thread(
                self._graph.invoke,
                state,
                {"configurable": {"thread_id": session_id}},
            )
        except Exception as exc:
            logger.warning("写入 LangGraph checkpoint 失败: %s", exc)


def _parse_tool_args(tool_name: str, args_text: str) -> JsonDict:
    """
    功能:
        解析模型生成的工具参数 JSON.
    参数:
        tool_name: str, 工具名.
        args_text: str, JSON 文本.
    返回:
        Dict[str, Any], 参数字典.
    """
    try:
        args = json.loads(args_text) if args_text.strip() != "" else {}
    except json.JSONDecodeError as exc:
        logger.warning("工具参数不是合法 JSON: %s, %s", tool_name, exc)
        args = {}
    if isinstance(args, dict) is False:
        return {}
    return args


async def _aiter(events: List[SseEvent]) -> AsyncIterator[SseEvent]:
    """
    功能:
        把同步事件列表包装为异步迭代器.
    参数:
        events: List[SseEvent], 待发送事件.
    返回:
        AsyncIterator[SseEvent], 事件流.
    """
    for event in events:
        yield event
