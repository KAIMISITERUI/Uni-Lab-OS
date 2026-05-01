# -*- coding: utf-8 -*-
"""
功能:
    AI 助手模块专属依赖工厂, 提供存储, 配置和编排器单例.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from .application.orchestrator import AiAgentOrchestrator
from .domain.store import AiAgentStore
from .infra.config_store import AiAgentConfigStore
from .infra.deepseek_client import DeepseekClient, DeepseekSettings


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


def get_ai_agent_orchestrator() -> AiAgentOrchestrator:
    """
    功能:
        构造 AI 助手对话编排器. store 复用单例, deepseek 客户端每请求新建 (轻量).
    返回:
        AiAgentOrchestrator, 编排器实例.
    """
    return AiAgentOrchestrator(
        store=_get_shared_ai_agent_store(),
        deepseek=_build_deepseek_client(),
    )
