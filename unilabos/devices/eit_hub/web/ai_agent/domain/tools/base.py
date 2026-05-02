# -*- coding: utf-8 -*-
"""
功能:
    AI Agent 工具基础类型, 统一工具权限, 分类, 输入输出模型和协议导出.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Type

from pydantic import BaseModel, ConfigDict

logger = logging.getLogger("EITHubAiAgentToolBase")

JsonDict = Dict[str, Any]


class ToolPermission(str, Enum):
    """
    功能:
        工具权限枚举. read 自动执行, control 必须进入人工确认.
    """

    READ = "read"
    CONTROL = "control"


class ToolCategory(str, Enum):
    """
    功能:
        工具业务分类枚举, 用于工具发现, 审计和前端管理展示.
    """

    MAINTENANCE = "maintenance"
    CHEMICAL = "chemical"
    AGV = "agv"
    DEVICE = "device"
    SYNTHESIS = "synthesis"
    KNOWLEDGE = "knowledge"
    SKILL = "skill"
    INTERACTION = "interaction"


class EmptyInput(BaseModel):
    """
    功能:
        无参数工具的输入模型.
    """

    model_config = ConfigDict(extra="forbid")


class GenericToolOutput(BaseModel):
    """
    功能:
        通用工具输出模型, 允许业务工具返回任意 JSON 字段.
    """

    model_config = ConfigDict(extra="allow")


ToolHandler = Callable[[BaseModel], Any]


@dataclass(frozen=True)
class ToolSpec:
    """
    功能:
        工具元数据和执行入口. 同一份定义可导出 OpenAI tools 协议和 MCP-style 元数据.
    参数:
        name: str, 工具名, 全局唯一.
        description: str, 给模型和用户看的中文工具说明.
        input_model: Type[BaseModel], Pydantic 输入模型.
        output_model: Type[BaseModel], Pydantic 输出模型.
        permission: ToolPermission, read 或 control.
        category: ToolCategory, 业务分类.
        handler: Callable, 接收已校验输入模型并返回 dict 或 BaseModel.
    返回:
        ToolSpec, 可注册到 ToolRegistry 的工具定义.
    """

    name: str
    description: str
    input_model: Type[BaseModel]
    output_model: Type[BaseModel]
    permission: ToolPermission
    category: ToolCategory
    handler: ToolHandler

    def to_openai_tool(self) -> JsonDict:
        """
        功能:
            导出 OpenAI-compatible tools 数组元素.
        返回:
            Dict[str, Any], function tool 描述.
        """
        parameters = self.input_model.model_json_schema()
        if parameters.get("type") is None:
            parameters["type"] = "object"
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": parameters,
            },
        }

    def to_mcp_metadata(self) -> JsonDict:
        """
        功能:
            导出 MCP-style 工具元数据, 供后续 MCP server 传输层复用.
        返回:
            Dict[str, Any], 含 name, description, inputSchema, outputSchema 和权限元数据.
        """
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_model.model_json_schema(),
            "outputSchema": self.output_model.model_json_schema(),
            "_meta": {
                "permission": self.permission.value,
                "category": self.category.value,
            },
        }

    def validate_args(self, args: JsonDict) -> BaseModel:
        """
        功能:
            使用输入模型校验模型传入的工具参数.
        参数:
            args: Dict[str, Any], 原始工具参数.
        返回:
            BaseModel, 已校验的输入模型实例.
        """
        return self.input_model.model_validate(args)

    def execute(self, args: JsonDict) -> JsonDict:
        """
        功能:
            校验参数并执行工具 handler.
        参数:
            args: Dict[str, Any], 原始工具参数.
        返回:
            Dict[str, Any], JSON 可序列化工具结果.
        """
        model = self.validate_args(args)
        result = self.handler(model)
        if isinstance(result, BaseModel) is True:
            return result.model_dump(mode="json")
        if isinstance(result, dict) is True:
            return result
        return {"value": result}


def summarize_tools_for_prompt(tools: List[ToolSpec]) -> str:
    """
    功能:
        把工具列表压缩成系统提示中的工具目录, 避免把完整 schema 重复写入提示词.
    参数:
        tools: List[ToolSpec], 已注册工具.
    返回:
        str, 中文工具目录文本.
    """
    lines: List[str] = []
    for spec in tools:
        lines.append(
            f"- {spec.name}: {spec.description} "
            f"(权限: {spec.permission.value}, 分类: {spec.category.value})"
        )
    return "\n".join(lines)
