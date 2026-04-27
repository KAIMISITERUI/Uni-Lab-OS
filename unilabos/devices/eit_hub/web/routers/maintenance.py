# -*- coding: utf-8 -*-
"""
功能:
    提供 EIT Hub 运维管理 Web API.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Query, status
from pydantic import BaseModel

from ..services.maintenance_store import MaintenanceStore

JsonDict = Dict[str, Any]

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"])
_STORE = MaintenanceStore()


class MaintenanceEventPayload(BaseModel):
    """
    功能:
        承载运维事件新增或更新请求.
    参数:
        station: str, 工站名称.
        title: str, 检查内容.
        start_date: str, 开始日期, 格式为 YYYY-MM-DD.
        interval_days: int, 间隔天数.
        enabled: bool, 是否启用.
        sort_order: int 或 None, 排序值.
    返回:
        MaintenanceEventPayload.
    """

    station: str
    title: str
    start_date: str
    interval_days: int
    enabled: bool = True
    sort_order: Optional[int] = None

    class Config:
        extra = "forbid"


class MaintenanceRecordItemPayload(BaseModel):
    """
    功能:
        承载单条运维记录提交内容.
    参数:
        event_id: str, 运维事件 ID.
        due_date: str 或 None, 到期日期, 为空时使用批量提交日期.
        value_text: str 或 None, 运维信息.
        note: str 或 None, 备注.
    返回:
        MaintenanceRecordItemPayload.
    """

    event_id: str
    due_date: Optional[str] = None
    value_text: Optional[str] = ""
    note: Optional[str] = ""

    class Config:
        extra = "forbid"


class MaintenanceBatchRecordPayload(BaseModel):
    """
    功能:
        承载运维记录批量提交请求.
    参数:
        date: str, 提交日期, 格式为 YYYY-MM-DD.
        operator: str, 操作人.
        items: List[MaintenanceRecordItemPayload], 运维记录项.
    返回:
        MaintenanceBatchRecordPayload.
    """

    date: str
    operator: str
    items: List[MaintenanceRecordItemPayload]

    class Config:
        extra = "forbid"


def _json_error(message: str, status_code: int = status.HTTP_400_BAD_REQUEST) -> HTTPException:
    """
    功能:
        创建中文错误响应.
    参数:
        message: str, 错误信息.
        status_code: int, HTTP 状态码.
    返回:
        HTTPException, FastAPI 异常.
    """
    return HTTPException(status_code=status_code, detail=message)


@router.get("/overview")
def get_maintenance_overview(
    date_text: Optional[str] = Query(default=None, alias="date"),
) -> JsonDict:
    """
    功能:
        返回指定日期的运维待办, 逾期提醒和完成统计.
    参数:
        date_text: str, 目标日期, 格式为 YYYY-MM-DD.
    返回:
        Dict[str, Any], 运维提醒总览.
    """
    target_date_text = date_text if date_text is not None else date.today().isoformat()
    try:
        return _STORE.build_overview(target_date_text)
    except ValueError as exc:
        raise _json_error(str(exc)) from exc


@router.get("/events")
def list_maintenance_events() -> JsonDict:
    """
    功能:
        返回全部运维事件配置.
    返回:
        Dict[str, Any], 事件列表.
    """
    try:
        events = _STORE.list_events()
    except ValueError as exc:
        raise _json_error(str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR) from exc
    return {"events": events, "total": len(events)}


@router.post("/events")
def create_maintenance_event(payload: MaintenanceEventPayload = Body(...)) -> JsonDict:
    """
    功能:
        新增运维事件配置.
    参数:
        payload: MaintenanceEventPayload, 事件字段.
    返回:
        Dict[str, Any], 新增后的事件.
    """
    event_payload = _event_payload_dict(payload)
    try:
        event = _STORE.create_event(event_payload)
    except ValueError as exc:
        raise _json_error(str(exc)) from exc
    return event


@router.put("/events/{event_id}")
def update_maintenance_event(event_id: str, payload: MaintenanceEventPayload = Body(...)) -> JsonDict:
    """
    功能:
        更新运维事件配置.
    参数:
        event_id: str, 运维事件 ID.
        payload: MaintenanceEventPayload, 事件字段.
    返回:
        Dict[str, Any], 更新后的事件.
    """
    event_payload = _event_payload_dict(payload)
    try:
        event = _STORE.update_event(event_id, event_payload)
    except KeyError as exc:
        raise _json_error(str(exc).strip("'"), status.HTTP_404_NOT_FOUND) from exc
    except ValueError as exc:
        raise _json_error(str(exc)) from exc
    return event


@router.post("/records/batch")
def submit_maintenance_records(payload: MaintenanceBatchRecordPayload = Body(...)) -> JsonDict:
    """
    功能:
        批量提交运维完成记录.
    参数:
        payload: MaintenanceBatchRecordPayload, 批量提交内容.
    返回:
        Dict[str, Any], 保存结果.
    """
    request_payload = {
        "date": payload.date,
        "operator": payload.operator,
        "items": [_record_item_dict(item) for item in payload.items],
    }
    try:
        return _STORE.save_batch_records(request_payload)
    except KeyError as exc:
        raise _json_error(str(exc).strip("'"), status.HTTP_404_NOT_FOUND) from exc
    except ValueError as exc:
        raise _json_error(str(exc)) from exc


@router.get("/records")
def list_maintenance_records(
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
) -> JsonDict:
    """
    功能:
        查询指定日期范围内的运维记录.
    参数:
        start_date: str, 起始日期.
        end_date: str, 结束日期.
    返回:
        Dict[str, Any], 运维记录列表.
    """
    start_date_text = start_date if start_date is not None else (date.today() - timedelta(days=7)).isoformat()
    end_date_text = end_date if end_date is not None else date.today().isoformat()
    try:
        return _STORE.list_records(start_date_text, end_date_text)
    except ValueError as exc:
        raise _json_error(str(exc)) from exc


def _event_payload_dict(payload: MaintenanceEventPayload) -> JsonDict:
    """
    功能:
        将 Pydantic 事件模型转换为普通字典.
    参数:
        payload: MaintenanceEventPayload, 事件模型.
    返回:
        Dict[str, Any], 事件字段.
    """
    result: JsonDict = {
        "station": payload.station,
        "title": payload.title,
        "start_date": payload.start_date,
        "interval_days": payload.interval_days,
        "enabled": payload.enabled,
    }
    if payload.sort_order is not None:
        result["sort_order"] = payload.sort_order
    return result


def _record_item_dict(payload: MaintenanceRecordItemPayload) -> JsonDict:
    """
    功能:
        将 Pydantic 记录项模型转换为普通字典.
    参数:
        payload: MaintenanceRecordItemPayload, 记录项模型.
    返回:
        Dict[str, Any], 记录项字段.
    """
    result: JsonDict = {
        "event_id": payload.event_id,
        "value_text": payload.value_text,
        "note": payload.note,
    }
    if payload.due_date is not None:
        result["due_date"] = payload.due_date
    return result
