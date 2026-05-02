# -*- coding: utf-8 -*-
"""
功能:
    化学品库查询工具定义.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

from .base import GenericToolOutput, ToolCategory, ToolPermission, ToolSpec
from .registry import ToolRegistry

logger = logging.getLogger("EITHubAiAgentChemicalTools")

JsonDict = Dict[str, Any]


class SearchChemicalInput(BaseModel):
    """
    功能:
        化学品模糊搜索输入.
    参数:
        keyword: str, 名称, CAS 号等关键词.
        limit: Optional[int], 返回条数.
    """

    model_config = ConfigDict(extra="forbid")

    keyword: str = Field(description="搜索关键词, 可为名称, CAS 号等.")
    limit: Optional[int] = Field(default=10, description="返回条数, 默认 10, 上限 50.")


def _handle_search_chemical(model: BaseModel) -> JsonDict:
    """
    功能:
        在化学品库中按关键词模糊搜索.
    参数:
        model: BaseModel, SearchChemicalInput.
    返回:
        Dict[str, Any], 命中列表和数量.
    """
    from unilabos.devices.eit_chemical_manager.manager.chemical_manager import ChemicalManager

    args = model.model_dump()
    keyword = str(args.get("keyword") or "").strip()
    if keyword == "":
        raise ValueError("keyword 不能为空")
    limit_raw = args.get("limit")
    limit_int = int(limit_raw) if isinstance(limit_raw, (int, float)) is True else 10
    if limit_int <= 0:
        limit_int = 10
    if limit_int > 50:
        limit_int = 50

    manager = ChemicalManager.get_shared()
    hits = manager.search(keyword)
    rows = [hit.get("row_data") for hit in hits if isinstance(hit, dict) is True]
    truncated = rows[:limit_int]
    return {"items": truncated, "total": len(rows), "returned": len(truncated)}


def register_tools(registry: ToolRegistry) -> None:
    """
    功能:
        注册化学品工具.
    参数:
        registry: ToolRegistry, 目标注册表.
    返回:
        None.
    """
    registry.register(
        ToolSpec(
            name="search_chemical",
            description="在化学品库按关键词模糊搜索, 返回 CAS 号, 中英文名, 危险等级等核心字段.",
            input_model=SearchChemicalInput,
            output_model=GenericToolOutput,
            permission=ToolPermission.READ,
            category=ToolCategory.CHEMICAL,
            handler=_handle_search_chemical,
        )
    )
