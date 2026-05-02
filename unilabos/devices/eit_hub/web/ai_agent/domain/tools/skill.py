# -*- coding: utf-8 -*-
"""
功能:
    Agent Skills 工具定义.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

from ..skills import SkillService
from .base import EmptyInput, GenericToolOutput, ToolCategory, ToolPermission, ToolSpec
from .registry import ToolRegistry

logger = logging.getLogger("EITHubAiAgentSkillTools")

JsonDict = Dict[str, Any]


class LoadSkillInput(BaseModel):
    """
    功能:
        加载 skill 输入.
    参数:
        name: str, skill 名称.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="skill 名称.")


class ReadSkillResourceInput(BaseModel):
    """
    功能:
        读取 skill 资源输入.
    参数:
        name: str, skill 名称.
        resource_path: str, 相对 skill 目录的资源路径.
        max_chars: Optional[int], 最大字符数.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="skill 名称.")
    resource_path: str = Field(description="相对 skill 目录的资源路径.")
    max_chars: Optional[int] = Field(default=20000, description="最大返回字符数.")


class RunSkillScriptInput(BaseModel):
    """
    功能:
        执行 skill 脚本输入.
    参数:
        name: str, skill 名称.
        script_path: str, 相对 skill 目录的脚本路径.
        args: Optional[Dict[str, Any]], 传入脚本的 JSON 参数.
        timeout_s: Optional[float], 超时秒.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="skill 名称.")
    script_path: str = Field(description="相对 skill 目录的脚本路径.")
    args: Optional[JsonDict] = Field(default=None, description="传入脚本的 JSON 参数.")
    timeout_s: Optional[float] = Field(default=30.0, description="超时秒.")


def register_tools(registry: ToolRegistry, skill_service: SkillService) -> None:
    """
    功能:
        注册 Agent Skills 工具.
    参数:
        registry: ToolRegistry, 目标注册表.
        skill_service: SkillService, skill 服务.
    返回:
        None.
    """

    def _handle_list_skills(model: BaseModel):
        """
        功能:
            列出可用 skills.
        参数:
            model: BaseModel, 空输入.
        返回:
            Dict[str, Any], skill 列表.
        """
        items = skill_service.list_skills()
        return {"items": items, "total": len(items)}

    def _handle_load_skill(model: BaseModel):
        """
        功能:
            加载指定 skill 的完整说明.
        参数:
            model: BaseModel, LoadSkillInput.
        返回:
            Dict[str, Any], skill 内容.
        """
        args = model.model_dump()
        return skill_service.load_skill(str(args.get("name") or ""))

    def _handle_read_skill_resource(model: BaseModel):
        """
        功能:
            读取 skill 资源.
        参数:
            model: BaseModel, ReadSkillResourceInput.
        返回:
            Dict[str, Any], 资源内容.
        """
        args = model.model_dump()
        return skill_service.read_resource(
            name=str(args.get("name") or ""),
            resource_path=str(args.get("resource_path") or ""),
            max_chars=int(args.get("max_chars") or 20000),
        )

    def _handle_run_skill_script(model: BaseModel):
        """
        功能:
            执行 skill 脚本.
        参数:
            model: BaseModel, RunSkillScriptInput.
        返回:
            Dict[str, Any], 脚本执行结果.
        """
        args = model.model_dump()
        return skill_service.run_script(
            name=str(args.get("name") or ""),
            script_path=str(args.get("script_path") or ""),
            args=args.get("args") or {},
            timeout_s=float(args.get("timeout_s") or 30.0),
        )

    registry.register_many(
        [
            ToolSpec(
                name="list_skills",
                description="列出当前 Agent 可用的 skills 目录.",
                input_model=EmptyInput,
                output_model=GenericToolOutput,
                permission=ToolPermission.READ,
                category=ToolCategory.SKILL,
                handler=_handle_list_skills,
            ),
            ToolSpec(
                name="load_skill",
                description="当用户任务匹配某个 skill 描述时, 加载该 skill 的完整说明和资源清单.",
                input_model=LoadSkillInput,
                output_model=GenericToolOutput,
                permission=ToolPermission.READ,
                category=ToolCategory.SKILL,
                handler=_handle_load_skill,
            ),
            ToolSpec(
                name="read_skill_resource",
                description="读取已加载 skill 的 references 或 assets 资源文件.",
                input_model=ReadSkillResourceInput,
                output_model=GenericToolOutput,
                permission=ToolPermission.READ,
                category=ToolCategory.SKILL,
                handler=_handle_read_skill_resource,
            ),
            ToolSpec(
                name="run_skill_script",
                description="执行 skill scripts 目录下的白名单 Python 脚本. 这是控制类操作, 必须由用户确认后执行.",
                input_model=RunSkillScriptInput,
                output_model=GenericToolOutput,
                permission=ToolPermission.CONTROL,
                category=ToolCategory.SKILL,
                handler=_handle_run_skill_script,
            ),
        ]
    )
