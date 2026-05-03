# -*- coding: utf-8 -*-
"""
功能:
    AI Agent 新 runtime, 工具注册表, skills, memory 和 knowledge 的回归测试.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest
from pydantic import BaseModel, ConfigDict, Field

from unilabos.devices.eit_hub.web.ai_agent.api import router as ai_router
from unilabos.devices.eit_hub.web.ai_agent.api.schemas import AiConfigUpdatePayload
from unilabos.devices.eit_hub.web.ai_agent.core.runtime import AgentRuntime
from unilabos.devices.eit_hub.web.ai_agent.domain.audit import AgentAuditStore
from unilabos.devices.eit_hub.web.ai_agent.domain.knowledge import KnowledgeService
from unilabos.devices.eit_hub.web.ai_agent.domain.memory import AgentMemoryService
from unilabos.devices.eit_hub.web.ai_agent.domain.skills import SkillService
from unilabos.devices.eit_hub.web.ai_agent.domain.store import AiAgentStore, ROLE_TOOL, STATUS_PENDING
from unilabos.devices.eit_hub.web.ai_agent.domain.tools import ToolCategory, ToolPermission
from unilabos.devices.eit_hub.web.ai_agent.domain.tools.base import GenericToolOutput, ToolSpec
from unilabos.devices.eit_hub.web.ai_agent.domain.tools.registry import ToolRegistry
from unilabos.devices.eit_hub.web.ai_agent.infra import anthropic_client, openai_compatible_client
from unilabos.devices.eit_hub.web.ai_agent.infra.anthropic_client import AnthropicClient, AnthropicSettings
from unilabos.devices.eit_hub.web.ai_agent.infra.config_store import (
    AiAgentConfig,
    AiAgentConfigStore,
    AiProviderConfig,
    resolve_active_selection,
    resolve_provider_credentials,
)
from unilabos.devices.eit_hub.web.ai_agent.infra.openai_compatible_client import (
    OpenAICompatibleClient,
    OpenAICompatibleSettings,
)
from unilabos.devices.eit_hub.web.ai_agent.infra.stream_frame import StreamFrame

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


def _patch_httpx_async_client(monkeypatch: pytest.MonkeyPatch, module: Any, lines: List[str]) -> None:
    """
    功能:
        用固定 SSE 行替换模块内 httpx.AsyncClient, 避免测试访问真实网络.
    参数:
        monkeypatch: pytest.MonkeyPatch, monkeypatch 工具.
        module: Any, 需要替换 httpx.AsyncClient 的模块.
        lines: List[str], aiter_lines 返回的行序列.
    返回:
        None.
    """

    class _FakeResponse:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def aread(self) -> bytes:
            return b""

        async def aiter_lines(self):
            for line in lines:
                yield line

    class _FakeClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, method: str, url: str, headers: JsonDict, json: JsonDict):
            self.method = method
            self.url = url
            self.headers = headers
            self.payload = json
            return _FakeResponse()

    monkeypatch.setattr(module.httpx, "AsyncClient", _FakeClient)


def test_provider_config_resolves_ui_env_and_rejects_invalid_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    功能:
        验证 base_model / thinking_level 选择, provider 凭证的 UI/env/default 优先级和模型白名单.
    """
    store = AiAgentConfigStore(tmp_path / "ai_agent_config.json")
    store.save(
        AiAgentConfig(
            active_base_model_id="gpt-5.5",
            active_thinking_level_id="high",
            providers={"openai": AiProviderConfig(timeout_s=66.0)},
        )
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-openai")

    loaded = store.load()
    selection = resolve_active_selection(loaded)
    assert selection.base_model.id == "gpt-5.5"
    assert selection.thinking_level is not None
    assert selection.thinking_level.id == "high"
    assert selection.base_model_source == "ui"
    assert selection.thinking_level_source == "ui"
    resolved = resolve_provider_credentials("openai", loaded)
    assert resolved.api_key == "sk-env-openai"
    assert resolved.timeout_s == 66.0
    assert resolved.source["api_key"] == "env"
    assert resolved.source["timeout_s"] == "ui"

    monkeypatch.setattr(ai_router, "get_ai_agent_config_store", lambda: store)
    with pytest.raises(Exception) as excinfo:
        ai_router.update_ai_config(AiConfigUpdatePayload(active_base_model_id="bad-model"))
    assert getattr(excinfo.value, "status_code", None) == 400


def test_openai_compatible_stream_merges_text_and_tool_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    功能:
        验证 OpenAI-compatible 流式响应会合并文本和 tool_calls 参数片段.
    """
    asyncio.run(_assert_openai_compatible_stream_merges_text_and_tool_calls(monkeypatch))


async def _assert_openai_compatible_stream_merges_text_and_tool_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    功能:
        执行 OpenAI-compatible 流式解析断言.
    """
    chunks = [
        {
            "choices": [
                {
                    "delta": {
                        "content": "你好",
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "echo_tool", "arguments": "{\"text\""},
                            }
                        ],
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"arguments": ": \"abc\"}"},
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3},
        },
    ]
    lines = [f"data: {json.dumps(chunk, ensure_ascii=False)}" for chunk in chunks]
    lines.append("data: [DONE]")
    _patch_httpx_async_client(monkeypatch, openai_compatible_client, lines)

    client = OpenAICompatibleClient(
        OpenAICompatibleSettings(
            provider_id="openai",
            provider_label="OpenAI",
            api_key="sk-test",
            base_url="https://example.test/v1",
            model="gpt-5.5",
            timeout_s=30.0,
        )
    )
    frames = [frame async for frame in client.stream_chat([{"role": "user", "content": "hi"}], [])]

    assert frames[0].kind == "token"
    assert frames[0].text == "你好"
    assert frames[-1].kind == "done"
    assert frames[-1].finish_reason == "tool_calls"
    assert frames[-1].tool_calls == [
        {"id": "call_1", "name": "echo_tool", "arguments_text": "{\"text\": \"abc\"}"}
    ]
    assert frames[-1].prompt_tokens == 10
    assert frames[-1].completion_tokens == 3


def test_anthropic_message_conversion_and_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    功能:
        验证 Anthropic 消息转换和流式 tool_use 解析.
    """
    asyncio.run(_assert_anthropic_message_conversion_and_stream(monkeypatch))


async def _assert_anthropic_message_conversion_and_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    功能:
        执行 Anthropic 协议转换和流式解析断言.
    """
    system_text, claude_messages = anthropic_client._convert_messages(
        [
            {"role": "system", "content": "系统提示"},
            {"role": "user", "content": "查一下"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "echo_tool", "arguments": "{\"text\": \"abc\"}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "{\"echo\": \"abc\"}"},
        ]
    )
    assert system_text == "系统提示"
    assert claude_messages[1]["content"][0]["type"] == "tool_use"
    assert claude_messages[2]["content"][0]["type"] == "tool_result"

    events = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 11, "output_tokens": 1}}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "收到"}},
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {"type": "tool_use", "id": "toolu_1", "name": "echo_tool", "input": {}},
        },
        {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": "{\"text\""}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": ": \"abc\"}"}},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 5}},
        {"type": "message_stop"},
    ]
    lines = [f"data: {json.dumps(event, ensure_ascii=False)}" for event in events]
    _patch_httpx_async_client(monkeypatch, anthropic_client, lines)

    client = AnthropicClient(
        AnthropicSettings(
            api_key="sk-ant-test",
            base_url="https://api.anthropic.test",
            model="claude-opus-4-7",
            timeout_s=30.0,
        )
    )
    frames = [frame async for frame in client.stream_chat([{"role": "user", "content": "hi"}], [])]

    assert frames[0].kind == "token"
    assert frames[0].text == "收到"
    assert frames[-1].kind == "done"
    assert frames[-1].finish_reason == "tool_calls"
    assert frames[-1].tool_calls == [
        {"id": "toolu_1", "name": "echo_tool", "arguments_text": "{\"text\": \"abc\"}"}
    ]
    assert frames[-1].prompt_tokens == 11
    assert frames[-1].completion_tokens == 5


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
