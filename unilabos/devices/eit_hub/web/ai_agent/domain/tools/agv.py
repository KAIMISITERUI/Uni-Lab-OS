# -*- coding: utf-8 -*-
"""
功能:
    AGV 状态读取工具定义.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from pydantic import BaseModel

from .base import EmptyInput, GenericToolOutput, ToolCategory, ToolPermission, ToolSpec
from .registry import ToolRegistry

logger = logging.getLogger("EITHubAiAgentAgvTools")

JsonDict = Dict[str, Any]


def _handle_get_agv_status(model: BaseModel) -> JsonDict:
    """
    功能:
        从 AgvStatusCache 单例读取 AGV 当前状态字段, 不触发底层 IO.
    参数:
        model: BaseModel, 空输入.
    返回:
        Dict[str, Any], AGV 状态摘要.
    """
    from ....deps import get_agv_status_cache

    cache = get_agv_status_cache()
    field_max_age_s = 5.0
    return {
        "station": cache.get("station", field_max_age_s),
        "battery": cache.get("battery", field_max_age_s),
        "nav_task": cache.get("nav_task", field_max_age_s),
        "is_moving": cache.get("is_moving", field_max_age_s),
        "tcp_pose": cache.get("tcp_pose", field_max_age_s),
        "joints": cache.get("joints", field_max_age_s),
        "slots": cache.get("slots", field_max_age_s),
        "gripper_state": cache.get("gripper_state", field_max_age_s),
    }


def register_tools(registry: ToolRegistry) -> None:
    """
    功能:
        注册 AGV 工具.
    参数:
        registry: ToolRegistry, 目标注册表.
    返回:
        None.
    """
    registry.register(
        ToolSpec(
            name="get_agv_status",
            description="获取 AGV 当前位置, 电量, 导航任务, 机械臂关节, 夹爪等实时状态字段.",
            input_model=EmptyInput,
            output_model=GenericToolOutput,
            permission=ToolPermission.READ,
            category=ToolCategory.AGV,
            handler=_handle_get_agv_status,
        )
    )
