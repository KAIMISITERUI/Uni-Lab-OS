# -*- coding: utf-8 -*-
"""
功能:
    AI Agent 新 runtime, 工具注册表, skills, memory 和 knowledge 的回归测试.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from unilabos.devices.eit_hub.web.ai_agent.core.runtime import AgentRuntime
from unilabos.devices.eit_hub.web.ai_agent.domain.audit import AgentAuditStore
from unilabos.devices.eit_hub.web.ai_agent.domain.knowledge import KnowledgeService
from unilabos.devices.eit_hub.web.ai_agent.domain.memory import AgentMemoryService
from unilabos.devices.eit_hub.web.ai_agent.domain.skills import SkillService
from unilabos.devices.eit_hub.web.ai_agent.domain.store import AiAgentStore, ROLE_TOOL, STATUS_PENDING
from unilabos.devices.eit_hub.web.ai_agent.domain.tools import ToolCategory, ToolPermission
from unilabos.devices.eit_hub.web.ai_agent.domain.tools.base import GenericToolOutput, ToolSpec
from unilabos.devices.eit_hub.web.ai_agent.domain.tools.registry import ToolRegistry
from unilabos.devices.eit_hub.web.ai_agent.infra.deepseek_client import StreamFrame

JsonDict = Dict[str, Any]


class EchoInput(BaseModel):
    """
    功能:
        测试用 echo 工具输入.
    参数:
        text: str, 回显文本.
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(description="回显文本.")


class FakeModelProvider:
    """
    功能:
        测试用模型 provider, 按轮次返回预设帧.
    """

    def __init__(self, frames_by_call: List[List[StreamFrame]]) -> None:
        self._frames_by_call = frames_by_call
        self.calls = 0

    async def stream_chat(
        self,
        messages: List[JsonDict],
        tools: Optional[List[JsonDict]] = None,
    ) -> AsyncIterator[StreamFrame]:
        """
        功能:
            返回当前轮预设帧.
        参数:
            messages: List[Dict], 模型消息.
            tools: Optional[List[Dict]], 工具 schema.
        返回:
            AsyncIterator[StreamFrame], 流式帧.
        """
        index = self.calls
        self.calls += 1
        for frame in self._frames_by_call[index]:
            yield frame


def _build_registry(executed: List[JsonDict], permission: ToolPermission) -> ToolRegistry:
    """
    功能:
        构造测试工具注册表.
    参数:
        executed: List[Dict], 记录执行参数.
        permission: ToolPermission, 工具权限.
    返回:
        ToolRegistry, 注册表.
    """

    def _handler(model: BaseModel) -> JsonDict:
        """
        功能:
            测试工具 handler.
        参数:
            model: BaseModel, EchoInput.
        返回:
            Dict[str, Any], 工具结果.
        """
        payload = model.model_dump()
        executed.append(payload)
        return {"echo": payload["text"]}

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="echo_tool",
            description="测试 echo 工具.",
            input_model=EchoInput,
            output_model=GenericToolOutput,
            permission=permission,
            category=ToolCategory.SYNTHESIS,
            handler=_handler,
        )
    )
    return registry


def _build_runtime(tmp_path: Path, provider: FakeModelProvider, registry: ToolRegistry) -> AgentRuntime:
    """
    功能:
        构造测试 runtime.
    参数:
        tmp_path: Path, 临时目录.
        provider: FakeModelProvider, 模型 provider.
        registry: ToolRegistry, 工具注册表.
    返回:
        AgentRuntime, 测试运行时.
    """
    db_path = tmp_path / "agent.db"
    return AgentRuntime(
        store=AiAgentStore(db_path),
        model_provider=provider,
        tool_registry=registry,
        memory_service=AgentMemoryService(db_path),
        skill_service=SkillService(root_paths=[tmp_path / "skills"]),
        audit_store=AgentAuditStore(db_path),
        checkpointer=None,
    )


def test_read_tool_executes_without_human_review(tmp_path: Path) -> None:
    """
    功能:
        验证 read 工具自动执行并继续模型回合.
    """
    asyncio.run(_assert_read_tool_executes_without_human_review(tmp_path))


async def _assert_read_tool_executes_without_human_review(tmp_path: Path) -> None:
    """
    功能:
        执行 read 工具自动执行断言.
    """
    executed: List[JsonDict] = []
    provider = FakeModelProvider(
        [
            [
                StreamFrame(
                    kind="done",
                    finish_reason="tool_calls",
                    tool_calls=[
                        {
                            "id": "call_1",
                            "name": "echo_tool",
                            "arguments_text": '{"text": "abc"}',
                        }
                    ],
                )
            ],
            [
                StreamFrame(kind="token", text="完成"),
                StreamFrame(kind="done", finish_reason="stop"),
            ],
        ]
    )
    runtime = _build_runtime(tmp_path, provider, _build_registry(executed, ToolPermission.READ))

    events = [event async for event in runtime.stream_user_turn("s1", "查一下")]

    assert executed == [{"text": "abc"}]
    assert [event.event for event in events].count("tool_result") == 1
    assert events[-1].event == "done"


def test_control_tool_waits_for_approval(tmp_path: Path) -> None:
    """
    功能:
        验证 control 工具必须等待人工确认, approve 后才执行.
    """
    asyncio.run(_assert_control_tool_waits_for_approval(tmp_path))


async def _assert_control_tool_waits_for_approval(tmp_path: Path) -> None:
    """
    功能:
        执行 control 工具人工确认断言.
    """
    executed: List[JsonDict] = []
    provider = FakeModelProvider(
        [
            [
                StreamFrame(
                    kind="done",
                    finish_reason="tool_calls",
                    tool_calls=[
                        {
                            "id": "call_1",
                            "name": "echo_tool",
                            "arguments_text": '{"text": "danger"}',
                        }
                    ],
                )
            ],
            [
                StreamFrame(kind="token", text="已执行"),
                StreamFrame(kind="done", finish_reason="stop"),
            ],
        ]
    )
    runtime = _build_runtime(tmp_path, provider, _build_registry(executed, ToolPermission.CONTROL))

    first_events = [event async for event in runtime.stream_user_turn("s1", "执行")]
    assert executed == []
    assert first_events[-1].data["reason"] == "pending_confirm"

    store = runtime._store
    messages = store.list_messages("s1")
    pending = [row for row in messages if row["role"] == ROLE_TOOL and row["status"] == STATUS_PENDING][0]

    second_events = [
        event
        async for event in runtime.resume_human_review(
            session_id="s1",
            message_id=int(pending["id"]),
            action="approve",
        )
    ]

    assert executed == [{"text": "danger"}]
    assert [event.event for event in second_events].count("tool_result") == 1
    assert second_events[-1].event == "done"


def test_memory_service_persists_explicit_memory(tmp_path: Path) -> None:
    """
    功能:
        验证长期记忆写入, 查询和删除.
    """
    service = AgentMemoryService(tmp_path / "agent.db")
    rows = service.persist_turn_memory(
        session_id="s1",
        user_id="u1",
        user_text="请记住, 我偏好先做安全检查.",
        assistant_text="好的.",
    )
    assert len(rows) == 1
    listed = service.list_memories(keyword="安全", user_id="u1")
    assert len(listed) == 1
    affected = service.delete_memory(int(listed[0]["id"]))
    assert affected == 1


def test_skill_service_loads_skill(tmp_path: Path) -> None:
    """
    功能:
        验证 Agent Skills 发现和正文加载.
    """
    skill_dir = tmp_path / "skills" / "experiment-plan-generation"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: experiment-plan-generation\ndescription: 生成实验方案时使用.\n---\n# 步骤\n保持安全检查.",
        encoding="utf-8",
    )
    service = SkillService(root_paths=[tmp_path / "skills"])
    skills = service.list_skills()
    assert skills[0]["name"] == "experiment-plan-generation"
    loaded = service.load_skill("experiment-plan-generation")
    assert "保持安全检查" in loaded["content"]


def test_knowledge_service_ingest_and_search(tmp_path: Path) -> None:
    """
    功能:
        验证知识库摄取和 Qdrant 检索入口.
    """
    doc = tmp_path / "sop.md"
    doc.write_text("泵启动前需要检查阀门状态和管路连接.", encoding="utf-8")
    service = KnowledgeService(storage_path=tmp_path / "qdrant")

    ingest = service.ingest_path(str(doc))
    result = service.search("泵启动前检查什么", limit=3)

    assert ingest["chunks"] == 1
    assert result["total"] >= 1
    assert "阀门" in str(result["items"][0]["text"])
