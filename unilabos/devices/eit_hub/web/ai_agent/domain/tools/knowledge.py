# -*- coding: utf-8 -*-
"""
功能:
    知识库检索工具定义.
"""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from ..knowledge import KnowledgeService
from .base import GenericToolOutput, ToolCategory, ToolPermission, ToolSpec
from .registry import ToolRegistry

logger = logging.getLogger("EITHubAiAgentKnowledgeTools")


class QueryKnowledgeBaseInput(BaseModel):
    """
    功能:
        知识库检索输入.
    参数:
        query: str, 检索问题.
        limit: Optional[int], 返回条数.
        collection: Optional[str], Qdrant collection 名称.
    """

    model_config = ConfigDict(extra="forbid")

    query: str = Field(description="检索问题.")
    limit: Optional[int] = Field(default=5, description="返回条数, 默认 5, 上限 20.")
    collection: Optional[str] = Field(default=None, description="Qdrant collection 名称, 留空使用默认知识库.")


def register_tools(registry: ToolRegistry, knowledge_service: KnowledgeService) -> None:
    """
    功能:
        注册知识库工具.
    参数:
        registry: ToolRegistry, 目标注册表.
        knowledge_service: KnowledgeService, 知识库服务.
    返回:
        None.
    """

    def _handle_query_knowledge_base(model: BaseModel):
        """
        功能:
            查询知识库.
        参数:
            model: BaseModel, QueryKnowledgeBaseInput.
        返回:
            Dict[str, Any], 检索结果.
        """
        args = model.model_dump()
        return knowledge_service.search(
            query=str(args.get("query") or ""),
            limit=int(args.get("limit") or 5),
            collection_name=args.get("collection"),
        )

    registry.register(
        ToolSpec(
            name="query_knowledge_base",
            description="检索 EIT Hub 知识库中的 SOP, 设备手册, 实验历史摘要和项目文档.",
            input_model=QueryKnowledgeBaseInput,
            output_model=GenericToolOutput,
            permission=ToolPermission.READ,
            category=ToolCategory.KNOWLEDGE,
            handler=_handle_query_knowledge_base,
        )
    )
