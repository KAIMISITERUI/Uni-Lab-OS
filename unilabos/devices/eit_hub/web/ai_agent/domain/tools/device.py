# -*- coding: utf-8 -*-
"""
功能:
    设备状态读取工具定义.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Literal

from pydantic import BaseModel, ConfigDict, Field

from .base import EmptyInput, GenericToolOutput, ToolCategory, ToolPermission, ToolSpec
from .registry import ToolRegistry

logger = logging.getLogger("EITHubAiAgentDeviceTools")

JsonDict = Dict[str, Any]


def _handle_get_device_overview(model: BaseModel) -> JsonDict:
    """
    功能:
        返回外部设备 TCP 端口连通性总览.
    参数:
        model: BaseModel, 空输入.
    返回:
        Dict[str, Any], 设备状态列表.
    """
    from ....routers.devices import _build_external_device_statuses

    items = _build_external_device_statuses()
    return {"items": items, "total": len(items)}


class ListAnalysisMethodsInput(BaseModel):
    """
    功能:
        分析仪器方法列表查询输入.
    参数:
        instrument: Literal["gc_ms","uplc_qtof","hplc","all"], 仪器选择, 默认 all.
    """

    model_config = ConfigDict(extra="forbid")

    instrument: Literal["gc_ms", "uplc_qtof", "hplc", "all"] = Field(
        default="all",
        description="目标仪器, 可选 gc_ms, uplc_qtof, hplc, all. all 同时返回三台仪器方法.",
    )


def _handle_list_analysis_methods(model: BaseModel) -> JsonDict:
    """
    功能:
        从分析工站三台仪器(GC_MS, UPLC_QTOF, HPLC)读取当前 Project 的采集方法列表,
        供 AI 校验用户给定的分析方法名是否在仪器下拉中.
    参数:
        model: BaseModel, ListAnalysisMethodsInput.
    返回:
        Dict[str, Any], 包含 items 列表, 每项含 instrument, name, methods, error.
    """
    from ....deps import _get_shared_analysis_controller
    from ....routers.analysis import _get_device_configs, _read_device_methods

    args = model.model_dump()
    target = str(args.get("instrument") or "all").strip().lower()
    controller = _get_shared_analysis_controller()
    configs = _get_device_configs(controller)
    if target != "all":
        configs = [config for config in configs if config["instrument"] == target]
        if len(configs) == 0:
            raise ValueError(f"未找到分析仪器: {target}")

    items = [_read_device_methods(config) for config in configs]
    return {"items": items, "total": len(items)}


def register_tools(registry: ToolRegistry) -> None:
    """
    功能:
        注册设备工具.
    参数:
        registry: ToolRegistry, 目标注册表.
    返回:
        None.
    """
    registry.register(
        ToolSpec(
            name="get_device_overview",
            description="检查所有外部设备的 TCP 端口连通性, 用于排查设备网络问题.",
            input_model=EmptyInput,
            output_model=GenericToolOutput,
            permission=ToolPermission.READ,
            category=ToolCategory.DEVICE,
            handler=_handle_get_device_overview,
        )
    )
    registry.register(
        ToolSpec(
            name="list_analysis_methods",
            description=(
                "列出 GC_MS, UPLC_QTOF, HPLC 三台分析仪器当前可用的采集方法名称, "
                "用于校验用户填写的分析方法名是否在仪器下拉中. instrument 默认 all 返回三台."
            ),
            input_model=ListAnalysisMethodsInput,
            output_model=GenericToolOutput,
            permission=ToolPermission.READ,
            category=ToolCategory.DEVICE,
            handler=_handle_list_analysis_methods,
        )
    )
