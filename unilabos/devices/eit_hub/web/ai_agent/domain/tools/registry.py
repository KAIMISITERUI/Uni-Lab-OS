# -*- coding: utf-8 -*-
"""
功能:
    AI Agent 工具注册表, 负责工具发现, 重名检测, 协议导出和统一执行.
"""

from __future__ import annotations

import logging
from typing import Dict, Iterable, List

from .base import JsonDict, ToolPermission, ToolSpec

logger = logging.getLogger("EITHubAiAgentToolRegistry")


class ToolRegistry:
    """
    功能:
        线程内只读工具注册表. 启动时完成注册, 运行时仅查询和执行.
    """

    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        """
        功能:
            注册单个工具, 工具名重复时直接报错.
        参数:
            spec: ToolSpec, 工具定义.
        返回:
            None.
        """
        if spec.name in self._tools:
            raise RuntimeError(f"工具名称重复: {spec.name}")
        self._tools[spec.name] = spec
        logger.info("AI Agent 工具已注册: %s, permission=%s", spec.name, spec.permission.value)

    def register_many(self, specs: Iterable[ToolSpec]) -> None:
        """
        功能:
            批量注册工具.
        参数:
            specs: Iterable[ToolSpec], 工具定义集合.
        返回:
            None.
        """
        for spec in specs:
            self.register(spec)

    def get(self, name: str) -> ToolSpec:
        """
        功能:
            按名称获取工具定义.
        参数:
            name: str, 工具名.
        返回:
            ToolSpec, 工具定义.
        """
        if name not in self._tools:
            raise KeyError(f"未注册的工具: {name}")
        return self._tools[name]

    def list(self) -> List[ToolSpec]:
        """
        功能:
            返回全部工具定义, 保持注册顺序.
        返回:
            List[ToolSpec], 工具列表.
        """
        return list(self._tools.values())

    def list_by_permission(self, permission: ToolPermission) -> List[ToolSpec]:
        """
        功能:
            按权限过滤工具.
        参数:
            permission: ToolPermission, 目标权限.
        返回:
            List[ToolSpec], 匹配工具列表.
        """
        return [spec for spec in self._tools.values() if spec.permission == permission]

    def to_openai_tools(self) -> List[JsonDict]:
        """
        功能:
            导出 OpenAI-compatible tools 数组.
        返回:
            List[Dict[str, Any]], 工具 schema 列表.
        """
        return [spec.to_openai_tool() for spec in self._tools.values()]

    def to_mcp_tools(self) -> List[JsonDict]:
        """
        功能:
            导出 MCP-style 工具元数据列表.
        返回:
            List[Dict[str, Any]], 工具元数据列表.
        """
        return [spec.to_mcp_metadata() for spec in self._tools.values()]

    def execute(self, name: str, args: JsonDict) -> JsonDict:
        """
        功能:
            查找并执行工具.
        参数:
            name: str, 工具名.
            args: Dict[str, Any], 工具参数.
        返回:
            Dict[str, Any], 工具结果.
        """
        spec = self.get(name)
        return spec.execute(args)
