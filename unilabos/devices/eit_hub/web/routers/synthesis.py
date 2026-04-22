# -*- coding: utf-8 -*-
"""
功能:
    提供合成工站 Web API, 将页面请求转换为现有 SynthesisStationManager 调用.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel

from unilabos.devices.eit_synthesis_station.manager.station_manager import (
    SynthesisStationManager,
)

from ..deps import get_synthesis_manager
from ..excel_codec import DEFAULT_REACTION_TEMPLATE, read_reaction_template, write_reaction_template
from ..jobs import JobBusyError, job_manager

logger = logging.getLogger("EITHubSynthesisRouter")

JsonDict = Dict[str, Any]

router = APIRouter(prefix="/api/synthesis", tags=["synthesis"])

W1_SHELF_POSITIONS = {"W-1-1", "W-1-3", "W-1-5", "W-1-7"}
W1_SHELF_ACTIONS = {"outside", "home"}
OUTER_DOOR_ACTIONS = {"open", "close"}


class OuterDoorRequest(BaseModel):
    """
    功能:
        承载过渡舱外门控制请求.
    参数:
        action: str, 外门动作, 仅允许 open 或 close.
    """

    action: str


class W1ShelfRequest(BaseModel):
    """
    功能:
        承载 W1 排货架控制请求.
    参数:
        position: str, W1 排货架位置.
        action: str, W1 排货架动作, 仅允许 outside 或 home.
    """

    position: str
    action: str


def _job_response(job_id: str) -> JsonDict:
    """
    功能:
        生成后台任务创建响应.
    参数:
        job_id: str, 后台任务 ID.
    返回:
        Dict[str, Any], 响应体.
    """
    return {
        "job_id": job_id,
        "status": "queued",
    }


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


@router.get("/dashboard")
def dashboard(
    manager: SynthesisStationManager = Depends(get_synthesis_manager),
) -> JsonDict:
    """
    功能:
        返回合成工站总览数据, 包括工站状态, 环境, 设备, 资源和最近任务.
    返回:
        Dict[str, Any], 仪表盘快照.
    """
    result: JsonDict = {
        "station_state": None,
        "glovebox_env": None,
        "device_status": [],
        "resources": [],
        "recent_tasks": [],
        "errors": {},
    }

    _fill_dashboard_section(result, "station_state", lambda: manager.station_state())
    _fill_dashboard_section(result, "glovebox_env", lambda: manager.get_glovebox_env())
    _fill_dashboard_section(result, "device_status", lambda: manager.list_device_status())
    _fill_dashboard_section(result, "resources", lambda: manager.get_resource_info())
    _fill_dashboard_section(result, "recent_tasks", lambda: _load_recent_tasks(manager))

    result["jobs"] = job_manager.list_recent(limit=10)
    return result


@router.get("/reaction-template")
def get_reaction_template() -> JsonDict:
    """
    功能:
        读取当前合成任务 Excel 模板.
    返回:
        Dict[str, Any], 模板结构.
    """
    return read_reaction_template(DEFAULT_REACTION_TEMPLATE)


@router.put("/reaction-template")
def save_reaction_template(payload: JsonDict = Body(...)) -> JsonDict:
    """
    功能:
        将 Web 表格内容覆盖保存到默认 reaction_template.xlsx.
    参数:
        payload: Dict[str, Any], 模板结构.
    返回:
        Dict[str, Any], 保存后的模板结构.
    """
    if job_manager.is_busy() is True:
        raise _json_error("当前已有合成工站后台任务正在运行, 请稍后再保存.", status.HTTP_409_CONFLICT)
    try:
        return write_reaction_template(payload, DEFAULT_REACTION_TEMPLATE)
    except Exception as exc:
        logger.exception("保存合成任务模板失败")
        raise _json_error(f"保存模板失败: {exc}") from exc


@router.post("/reaction-template/submit")
def submit_reaction_template(
    payload: Optional[JsonDict] = Body(default=None),
    manager: SynthesisStationManager = Depends(get_synthesis_manager),
) -> JsonDict:
    """
    功能:
        保存 Web 表格并创建合成任务, 实际执行放入后台任务.
    参数:
        payload: Optional[Dict[str, Any]], 模板结构, 为空时使用磁盘现有模板.
    返回:
        Dict[str, Any], 后台任务 ID.
    """

    def _target(log: Callable[[str], None]) -> JsonDict:
        if payload is not None:
            log("正在保存 Web 表格到本地 Excel 模板.")
            write_reaction_template(payload, DEFAULT_REACTION_TEMPLATE)
        log("正在调用合成工站任务提交逻辑.")
        task_id = manager.create_task_by_file(str(DEFAULT_REACTION_TEMPLATE))
        log(f"合成任务提交完成, task_id={task_id}.")
        return {"task_id": task_id}

    return _start_job("提交合成任务", _target)


@router.post("/resource-check")
def check_resource(
    payload: Optional[JsonDict] = Body(default=None),
    manager: SynthesisStationManager = Depends(get_synthesis_manager),
) -> JsonDict:
    """
    功能:
        保存 Web 表格并执行物料核算, 实际执行放入后台任务.
    参数:
        payload: Optional[Dict[str, Any]], 模板结构, 为空时使用磁盘现有模板.
    返回:
        Dict[str, Any], 后台任务 ID.
    """

    def _target(log: Callable[[str], None]) -> JsonDict:
        if payload is not None:
            log("正在保存 Web 表格到本地 Excel 模板.")
            write_reaction_template(payload, DEFAULT_REACTION_TEMPLATE)
        log("正在执行物料核算, 并按现有逻辑生成上料文件.")
        result = manager.check_resource_for_task(
            str(DEFAULT_REACTION_TEMPLATE),
            auto_generate_batch_file=True,
        )
        log("物料核算完成.")
        return result

    return _start_job("物料核算", _target)


@router.post("/device-init")
def device_init(
    manager: SynthesisStationManager = Depends(get_synthesis_manager),
) -> JsonDict:
    """
    功能:
        创建设备初始化后台任务并调用合成工站设备初始化逻辑.
    参数:
        manager: SynthesisStationManager, 合成工站管理器.
    返回:
        Dict[str, Any], 后台任务 ID.
    """

    def _target(log: Callable[[str], None]) -> Any:
        log("正在执行设备初始化.")
        result = manager.device_init()
        log("设备初始化完成.")
        return result

    return _start_job("设备初始化", _target)


@router.post("/outer-door")
def control_outer_door(
    request: OuterDoorRequest,
    manager: SynthesisStationManager = Depends(get_synthesis_manager),
) -> JsonDict:
    """
    功能:
        创建过渡舱外门控制后台任务.
    参数:
        request: OuterDoorRequest, 外门控制请求.
        manager: SynthesisStationManager, 合成工站管理器.
    返回:
        Dict[str, Any], 后台任务 ID.
    """
    try:
        action = _read_outer_door_action(request.action)
    except ValueError as exc:
        raise _json_error(str(exc)) from exc

    label = "打开过渡舱外门" if action == "open" else "关闭过渡舱外门"

    def _target(log: Callable[[str], None]) -> Any:
        log(f"正在执行: {label}.")
        result = manager.open_close_door(action)
        log(f"动作完成: {label}.")
        return result

    return _start_job(label, _target)


@router.post("/w1-shelf")
def control_w1_shelf(
    request: W1ShelfRequest,
    manager: SynthesisStationManager = Depends(get_synthesis_manager),
) -> JsonDict:
    """
    功能:
        创建 W1 排货架控制后台任务.
    参数:
        request: W1ShelfRequest, W1 排货架控制请求.
        manager: SynthesisStationManager, 合成工站管理器.
    返回:
        Dict[str, Any], 后台任务 ID.
    """
    try:
        position, action = _read_w1_shelf_params(request.position, request.action)
    except ValueError as exc:
        raise _json_error(str(exc)) from exc

    def _target(log: Callable[[str], None]) -> Any:
        log(f"正在控制 W1 排货架, 位置={position}, 动作={action}.")
        result = manager.control_w1_shelf(position, action)
        log("W1 排货架控制完成.")
        return result

    return _start_job("控制 W1 排货架", _target)


@router.post("/actions/{action_name}", include_in_schema=False)
def removed_action_endpoint(action_name: str) -> JsonDict:
    """
    功能:
        明确拒绝旧的合成工站通用动作接口.
    参数:
        action_name: str, 旧动作名称.
    返回:
        Dict[str, Any], 该路径始终返回 404.
    """
    raise _json_error(f"合成工站通用动作接口已删除: {action_name}.", status.HTTP_404_NOT_FOUND)


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> JsonDict:
    """
    功能:
        查询后台任务状态.
    参数:
        job_id: str, 后台任务 ID.
    返回:
        Dict[str, Any], 任务状态.
    """
    job = job_manager.get(job_id)
    if job is None:
        raise _json_error(f"未找到后台任务: {job_id}", status.HTTP_404_NOT_FOUND)
    return job.to_dict()


def _start_job(name: str, target: Callable[[Callable[[str], None]], Any]) -> JsonDict:
    """
    功能:
        创建后台任务并统一处理繁忙状态.
    参数:
        name: str, 任务名称.
        target: Callable, 任务函数.
    返回:
        Dict[str, Any], 后台任务响应.
    """
    try:
        job = job_manager.start_exclusive(name, target)
    except JobBusyError as exc:
        raise _json_error(str(exc), status.HTTP_409_CONFLICT) from exc
    return _job_response(job.job_id)


def _fill_dashboard_section(
    result: JsonDict,
    key: str,
    loader: Callable[[], Any],
) -> None:
    """
    功能:
        读取仪表盘某个分区, 失败时记录 errors 字段.
    参数:
        result: Dict[str, Any], 仪表盘结果.
        key: str, 分区字段名.
        loader: Callable, 数据读取函数.
    返回:
        None.
    """
    try:
        result[key] = loader()
    except Exception as exc:
        logger.warning("读取合成工站仪表盘分区失败, key=%s, err=%s", key, exc)
        errors = result.get("errors")
        if isinstance(errors, dict):
            errors[key] = str(exc)


def _load_recent_tasks(manager: SynthesisStationManager) -> List[JsonDict]:
    """
    功能:
        读取最近任务列表, 优先使用分页接口.
    参数:
        manager: SynthesisStationManager, 合成工站管理器.
    返回:
        List[Dict[str, Any]], 最近任务列表.
    """
    response = manager.get_task_list(sort="desc", offset=0, limit=20)
    task_list = response.get("task_list")
    if isinstance(task_list, list):
        return task_list
    for outer_key in ("result", "data"):
        outer = response.get(outer_key)
        if isinstance(outer, dict):
            nested = outer.get("task_list")
            if isinstance(nested, list):
                return nested
    return []


def _read_outer_door_action(value: Any) -> str:
    """
    功能:
        读取并校验过渡舱外门动作.
    参数:
        value: Any, 外门动作原始值.
    返回:
        str, 校验后的外门动作.
    """
    if value is None:
        action = ""
    else:
        action = str(value).strip()
    if action not in OUTER_DOOR_ACTIONS:
        allowed_text = ", ".join(sorted(OUTER_DOOR_ACTIONS))
        raise ValueError(f"过渡舱外门动作必须是以下之一: {allowed_text}.")
    return action


def _read_w1_shelf_params(position_value: Any, action_value: Any) -> tuple[str, str]:
    """
    功能:
        读取并校验 W1 排货架控制参数.
    参数:
        position_value: Any, W1 排货架位置原始值.
        action_value: Any, W1 排货架动作原始值.
    返回:
        tuple[str, str], 位置和动作.
    """
    if position_value is None:
        position = ""
    else:
        position = str(position_value).strip()
    if action_value is None:
        action = ""
    else:
        action = str(action_value).strip()
    if position not in W1_SHELF_POSITIONS:
        allowed_text = ", ".join(sorted(W1_SHELF_POSITIONS))
        raise ValueError(f"W1 货架位置必须是以下之一: {allowed_text}.")
    if action not in W1_SHELF_ACTIONS:
        allowed_text = ", ".join(sorted(W1_SHELF_ACTIONS))
        raise ValueError(f"W1 货架动作必须是以下之一: {allowed_text}.")
    return position, action
