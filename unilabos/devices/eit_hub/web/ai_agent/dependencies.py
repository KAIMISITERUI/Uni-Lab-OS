# -*- coding: utf-8 -*-
"""
功能:
    AI 助手模块专属依赖工厂, 提供存储, 配置, 工具, 记忆, 知识库, skills 和运行时实例.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from .core.runtime import AgentRuntime
from .domain.audit import AgentAuditStore
from .domain.knowledge import KnowledgeService
from .domain.memory import AgentMemoryService
from .domain.skills import SkillService
from .domain.store import AiAgentStore
from .domain.tools import ToolRegistry, build_tool_registry
from .infra.config_store import AiAgentConfigStore
from .infra.checkpoint import build_checkpointer
from .infra.deepseek_client import DeepseekClient, DeepseekSettings
from .infra.model_provider import DeepSeekModelProvider


@lru_cache(maxsize=1)
def _get_shared_ai_agent_store() -> AiAgentStore:
    """
    功能:
        创建并缓存 AI 助手 SQLite 存储. 路径可由 AI_AGENT_DB_PATH 环境变量覆盖.
    返回:
        AiAgentStore, 单例实例.
    """
    db_path_text = os.getenv("AI_AGENT_DB_PATH", "").strip()
    if db_path_text != "":
        return AiAgentStore(Path(db_path_text))
    return AiAgentStore()


def get_ai_agent_store() -> AiAgentStore:
    """
    功能:
        FastAPI 依赖, 返回 AI 助手存储单例.
    返回:
        AiAgentStore, 单例实例.
    """
    return _get_shared_ai_agent_store()


@lru_cache(maxsize=1)
def _get_shared_ai_agent_config_store() -> AiAgentConfigStore:
    """
    功能:
        创建并缓存 AI 助手配置存储 (UI 持久化的 DeepSeek 接入参数).
    返回:
        AiAgentConfigStore, 单例实例.
    """
    return AiAgentConfigStore()


def get_ai_agent_config_store() -> AiAgentConfigStore:
    """
    功能:
        FastAPI 依赖, 返回 AI 助手配置存储单例.
    返回:
        AiAgentConfigStore, 单例实例.
    """
    return _get_shared_ai_agent_config_store()


@lru_cache(maxsize=1)
def _get_shared_ai_agent_memory_service() -> AgentMemoryService:
    """
    功能:
        创建并缓存 AI 助手长期记忆服务.
    返回:
        AgentMemoryService, 单例实例.
    """
    return AgentMemoryService()


def get_ai_agent_memory_service() -> AgentMemoryService:
    """
    功能:
        FastAPI 依赖, 返回长期记忆服务.
    返回:
        AgentMemoryService, 单例实例.
    """
    return _get_shared_ai_agent_memory_service()


@lru_cache(maxsize=1)
def _get_shared_ai_agent_skill_service() -> SkillService:
    """
    功能:
        创建并缓存 Agent Skills 服务.
    返回:
        SkillService, 单例实例.
    """
    return SkillService()


def get_ai_agent_skill_service() -> SkillService:
    """
    功能:
        FastAPI 依赖, 返回 Agent Skills 服务.
    返回:
        SkillService, 单例实例.
    """
    return _get_shared_ai_agent_skill_service()


@lru_cache(maxsize=1)
def _get_shared_ai_agent_knowledge_service() -> KnowledgeService:
    """
    功能:
        创建并缓存知识库服务.
    返回:
        KnowledgeService, 单例实例.
    """
    return KnowledgeService()


def get_ai_agent_knowledge_service() -> KnowledgeService:
    """
    功能:
        FastAPI 依赖, 返回知识库服务.
    返回:
        KnowledgeService, 单例实例.
    """
    return _get_shared_ai_agent_knowledge_service()


@lru_cache(maxsize=1)
def _get_shared_ai_agent_audit_store() -> AgentAuditStore:
    """
    功能:
        创建并缓存审计存储.
    返回:
        AgentAuditStore, 单例实例.
    """
    return AgentAuditStore()


def get_ai_agent_audit_store() -> AgentAuditStore:
    """
    功能:
        FastAPI 依赖, 返回审计存储.
    返回:
        AgentAuditStore, 单例实例.
    """
    return _get_shared_ai_agent_audit_store()


@lru_cache(maxsize=1)
def _get_shared_tool_registry() -> ToolRegistry:
    """
    功能:
        创建并缓存工具注册表.
    返回:
        ToolRegistry, 单例实例.
    """
    return build_tool_registry(
        knowledge_service=_get_shared_ai_agent_knowledge_service(),
        skill_service=_get_shared_ai_agent_skill_service(),
    )


def get_ai_agent_tool_registry() -> ToolRegistry:
    """
    功能:
        FastAPI 依赖, 返回工具注册表.
    返回:
        ToolRegistry, 单例实例.
    """
    return _get_shared_tool_registry()


@lru_cache(maxsize=1)
def _get_shared_ai_agent_checkpointer():
    """
    功能:
        创建并缓存 LangGraph SQLite checkpointer.
    返回:
        Any, LangGraph checkpointer.
    """
    return build_checkpointer()


def _build_deepseek_client() -> DeepseekClient:
    """
    功能:
        分层加载 DeepSeek 配置: UI store 优先, 字段缺失时回退环境变量, 然后构造客户端.
        Key 缺失时 Settings.load 抛 ValueError, 由路由层翻译为 503.
    返回:
        DeepseekClient, 客户端实例.
    """
    settings = DeepseekSettings.load(store=_get_shared_ai_agent_config_store())
    return DeepseekClient(settings)


def get_ai_agent_runtime() -> AgentRuntime:
    """
    功能:
        构造 AI 助手运行时. store, 工具, 记忆, knowledge, skills 复用单例, 模型客户端每请求新建.
    返回:
        AgentRuntime, 运行时实例.
    """
    return AgentRuntime(
        store=_get_shared_ai_agent_store(),
        model_provider=DeepSeekModelProvider(_build_deepseek_client()),
        tool_registry=_get_shared_tool_registry(),
        memory_service=_get_shared_ai_agent_memory_service(),
        skill_service=_get_shared_ai_agent_skill_service(),
        audit_store=_get_shared_ai_agent_audit_store(),
        checkpointer=_get_shared_ai_agent_checkpointer(),
    )
