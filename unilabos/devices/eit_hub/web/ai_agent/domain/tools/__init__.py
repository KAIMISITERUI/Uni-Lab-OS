# -*- coding: utf-8 -*-
"""
功能:
    AI Agent 工具包公开入口, 负责构造默认工具注册表并兼容协议导出.
"""

from __future__ import annotations

from typing import List, Optional

from ..knowledge import KnowledgeService
from ..skills import SkillService
from . import agv, chemical, device, interaction, knowledge, maintenance, skill, synthesis
from .base import JsonDict, ToolCategory, ToolPermission, ToolSpec, summarize_tools_for_prompt
from .registry import ToolRegistry

_DEFAULT_REGISTRY: Optional[ToolRegistry] = None


def build_tool_registry(
    knowledge_service: Optional[KnowledgeService] = None,
    skill_service: Optional[SkillService] = None,
) -> ToolRegistry:
    """
    功能:
        构造完整工具注册表.
    参数:
        knowledge_service: Optional[KnowledgeService], 知识库服务.
        skill_service: Optional[SkillService], skill 服务.
    返回:
        ToolRegistry, 已注册全部工具的注册表.
    """
    registry = ToolRegistry()
    if knowledge_service is None:
        knowledge_service = KnowledgeService()
    if skill_service is None:
        skill_service = SkillService()
    maintenance.register_tools(registry)
    synthesis.register_tools(registry)
    agv.register_tools(registry)
    device.register_tools(registry)
    chemical.register_tools(registry)
    interaction.register_tools(registry)
    knowledge.register_tools(registry, knowledge_service)
    skill.register_tools(registry, skill_service)
    return registry


def get_default_registry() -> ToolRegistry:
    """
    功能:
        返回进程内默认工具注册表.
    返回:
        ToolRegistry, 默认注册表.
    """
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = build_tool_registry()
    return _DEFAULT_REGISTRY


def list_tools() -> List[ToolSpec]:
    """
    功能:
        返回默认注册表中的全部工具.
    返回:
        List[ToolSpec], 工具列表.
    """
    return get_default_registry().list()


def get_tool(name: str) -> ToolSpec:
    """
    功能:
        从默认注册表按名称获取工具.
    参数:
        name: str, 工具名.
    返回:
        ToolSpec, 工具定义.
    """
    return get_default_registry().get(name)


def build_openai_tools_payload() -> List[JsonDict]:
    """
    功能:
        导出默认注册表的 OpenAI-compatible tools 数组.
    返回:
        List[Dict[str, Any]], 工具 schema 列表.
    """
    return get_default_registry().to_openai_tools()


__all__ = [
    "JsonDict",
    "ToolCategory",
    "ToolPermission",
    "ToolRegistry",
    "ToolSpec",
    "build_openai_tools_payload",
    "build_tool_registry",
    "get_default_registry",
    "get_tool",
    "list_tools",
    "summarize_tools_for_prompt",
]
