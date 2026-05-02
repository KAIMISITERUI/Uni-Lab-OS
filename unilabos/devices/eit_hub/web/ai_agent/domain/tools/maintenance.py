# -*- coding: utf-8 -*-
"""
功能:
    运维管理工具定义, 包含运维概览, 记录查询和运维写操作.
"""

from __future__ import annotations

import logging
from datetime import date as _date
from datetime import timedelta
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from ....services.maintenance_store import MaintenanceStore
from .base import GenericToolOutput, ToolCategory, ToolPermission, ToolSpec
from .registry import ToolRegistry

logger = logging.getLogger("EITHubAiAgentMaintenanceTools")

JsonDict = Dict[str, Any]

_maintenance_store_singleton: Optional[MaintenanceStore] = None


def _maintenance_store() -> MaintenanceStore:
    """
    功能:
        懒加载并复用 MaintenanceStore 单例.
    返回:
        MaintenanceStore, 运维存储实例.
    """
    global _maintenance_store_singleton
    if _maintenance_store_singleton is None:
        _maintenance_store_singleton = MaintenanceStore()
    return _maintenance_store_singleton


class MaintenanceOverviewInput(BaseModel):
    """
    功能:
        运维概览查询输入.
    参数:
        date: Optional[str], 目标日期, 格式 YYYY-MM-DD.
    """

    model_config = ConfigDict(extra="forbid")

    date: Optional[str] = Field(default=None, description="目标日期, 格式 YYYY-MM-DD, 留空表示今天.")


class MaintenanceRecordsInput(BaseModel):
    """
    功能:
        运维记录查询输入.
    参数:
        start_date: Optional[str], 起始日期.
        end_date: Optional[str], 结束日期.
    """

    model_config = ConfigDict(extra="forbid")

    start_date: Optional[str] = Field(default=None, description="起始日期 YYYY-MM-DD, 留空为 7 天前.")
    end_date: Optional[str] = Field(default=None, description="结束日期 YYYY-MM-DD, 留空为今天.")


class MaintenanceRecordItem(BaseModel):
    """
    功能:
        运维记录提交项.
    参数:
        event_id: str, 运维事件 ID.
        due_date: Optional[str], 到期日期.
        value_text: Optional[str], 运维信息说明.
        note: Optional[str], 备注.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(description="运维事件 ID.")
    due_date: Optional[str] = Field(default=None, description="到期日期 YYYY-MM-DD, 留空使用提交日期.")
    value_text: Optional[str] = Field(default=None, description="运维信息说明.")
    note: Optional[str] = Field(default=None, description="备注.")


class SubmitMaintenanceRecordsInput(BaseModel):
    """
    功能:
        批量提交运维记录输入.
    参数:
        date: str, 提交日期.
        operator: str, 操作人.
        items: List[MaintenanceRecordItem], 运维事项列表.
    """

    model_config = ConfigDict(extra="forbid")

    date: str = Field(description="提交日期 YYYY-MM-DD.")
    operator: str = Field(description="操作人姓名.")
    items: List[MaintenanceRecordItem] = Field(description="运维事项列表, 至少 1 条.")


class UpdateMaintenanceEventInput(BaseModel):
    """
    功能:
        更新运维事件配置输入.
    参数:
        event_id: str, 运维事件 ID.
        station: str, 工站名称.
        title: str, 检查内容标题.
        start_date: str, 开始日期.
        interval_days: int, 间隔天数.
        enabled: Optional[bool], 是否启用.
        sort_order: Optional[int], 排序值.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(description="运维事件 ID.")
    station: str = Field(description="工站名称.")
    title: str = Field(description="检查内容标题.")
    start_date: str = Field(description="开始日期 YYYY-MM-DD.")
    interval_days: int = Field(description="间隔天数, 必须为正整数.")
    enabled: Optional[bool] = Field(default=None, description="是否启用.")
    sort_order: Optional[int] = Field(default=None, description="排序值.")


def _handle_get_maintenance_overview(model: BaseModel) -> JsonDict:
    """
    功能:
        查询指定日期的运维待办, 逾期与完成统计.
    参数:
        model: BaseModel, MaintenanceOverviewInput.
    返回:
        Dict[str, Any], 运维概览.
    """
    args = model.model_dump()
    date_text = args.get("date") or _date.today().isoformat()
    return _maintenance_store().build_overview(str(date_text))


def _handle_list_maintenance_records(model: BaseModel) -> JsonDict:
    """
    功能:
        查询日期范围内的运维记录.
    参数:
        model: BaseModel, MaintenanceRecordsInput.
    返回:
        Dict[str, Any], 记录列表和总数.
    """
    args = model.model_dump()
    start_date = args.get("start_date") or (_date.today() - timedelta(days=7)).isoformat()
    end_date = args.get("end_date") or _date.today().isoformat()
    return _maintenance_store().list_records(str(start_date), str(end_date))


def _handle_list_maintenance_events(model: BaseModel) -> JsonDict:
    """
    功能:
        列出全部运维事件配置.
    参数:
        model: BaseModel, 空输入.
    返回:
        Dict[str, Any], 运维事件列表.
    """
    events = _maintenance_store().list_events()
    return {"events": events, "total": len(events)}


def _handle_submit_maintenance_records(model: BaseModel) -> JsonDict:
    """
    功能:
        批量提交运维完成记录.
    参数:
        model: BaseModel, SubmitMaintenanceRecordsInput.
    返回:
        Dict[str, Any], 保存结果.
    """
    return _maintenance_store().save_batch_records(model.model_dump(exclude_none=True))


def _handle_update_maintenance_event(model: BaseModel) -> JsonDict:
    """
    功能:
        更新单个运维事件配置.
    参数:
        model: BaseModel, UpdateMaintenanceEventInput.
    返回:
        Dict[str, Any], 更新后的事件.
    """
    args = model.model_dump(exclude_none=True)
    event_id = str(args.get("event_id") or "").strip()
    if event_id == "":
        raise ValueError("event_id 不能为空")
    payload = {key: value for key, value in args.items() if key != "event_id"}
    return _maintenance_store().update_event(event_id, payload)


def register_tools(registry: ToolRegistry) -> None:
    """
    功能:
        注册运维工具.
    参数:
        registry: ToolRegistry, 目标注册表.
    返回:
        None.
    """
    from .base import EmptyInput

    registry.register_many(
        [
            ToolSpec(
                name="get_maintenance_overview",
                description="查询指定日期的运维待办, 逾期与完成统计. 参数 date 留空则取今天.",
                input_model=MaintenanceOverviewInput,
                output_model=GenericToolOutput,
                permission=ToolPermission.READ,
                category=ToolCategory.MAINTENANCE,
                handler=_handle_get_maintenance_overview,
            ),
            ToolSpec(
                name="list_maintenance_records",
                description="按日期范围查询已提交的运维完成记录. 留空时默认查询最近 7 天.",
                input_model=MaintenanceRecordsInput,
                output_model=GenericToolOutput,
                permission=ToolPermission.READ,
                category=ToolCategory.MAINTENANCE,
                handler=_handle_list_maintenance_records,
            ),
            ToolSpec(
                name="list_maintenance_events",
                description="列出全部运维事件配置, 即定期检查清单.",
                input_model=EmptyInput,
                output_model=GenericToolOutput,
                permission=ToolPermission.READ,
                category=ToolCategory.MAINTENANCE,
                handler=_handle_list_maintenance_events,
            ),
            ToolSpec(
                name="submit_maintenance_records",
                description="批量提交运维完成记录. 这是写操作, 必须由用户确认后执行.",
                input_model=SubmitMaintenanceRecordsInput,
                output_model=GenericToolOutput,
                permission=ToolPermission.CONTROL,
                category=ToolCategory.MAINTENANCE,
                handler=_handle_submit_maintenance_records,
            ),
            ToolSpec(
                name="update_maintenance_event",
                description="更新单个运维事件配置. 这是写操作, 必须由用户确认后执行.",
                input_model=UpdateMaintenanceEventInput,
                output_model=GenericToolOutput,
                permission=ToolPermission.CONTROL,
                category=ToolCategory.MAINTENANCE,
                handler=_handle_update_maintenance_event,
            ),
        ]
    )
