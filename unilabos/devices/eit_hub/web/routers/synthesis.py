# -*- coding: utf-8 -*-
"""
功能:
    提供合成工站 Web API, 将页面请求转换为现有 SynthesisStationManager 调用.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field

from unilabos.devices.eit_synthesis_station.manager.station_manager import (
    SynthesisStationManager,
)

from ..deps import get_synthesis_manager
from ..excel_codec import DEFAULT_REACTION_TEMPLATE, read_reaction_template, write_reaction_template
from ..jobs import JobBusyError, job_manager

logger = logging.getLogger("EITHubSynthesisRouter")

JsonDict = Dict[str, Any]

router = APIRouter(prefix="/api/synthesis", tags=["synthesis"])


class ActionRequest(BaseModel):
    """
    功能:
        合成工站动作请求体.
    参数:
        params: Dict[str, Any], 透传给动作的参数.
    """

    params: JsonDict = Field(default_factory=dict)


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


@router.post("/actions/{action_name}")
def run_action(
    action_name: str,
    request: ActionRequest,
    manager: SynthesisStationManager = Depends(get_synthesis_manager),
) -> JsonDict:
    """
    功能:
        执行合成工站白名单动作, 实际执行放入后台任务.
    参数:
        action_name: str, 动作名称.
        request: ActionRequest, 动作参数.
    返回:
        Dict[str, Any], 后台任务 ID.
    """
    if action_name not in ACTION_LABELS:
        allowed_text = ", ".join(sorted(ACTION_LABELS.keys()))
        raise _json_error(f"不支持的合成工站动作: {action_name}. 可用动作: {allowed_text}")

    params = request.params

    def _target(log: Callable[[str], None]) -> Any:
        label = ACTION_LABELS[action_name]
        log(f"正在执行: {label}.")
        result = _execute_action(manager, action_name, params, log)
        log(f"动作完成: {label}.")
        return result

    return _start_job(ACTION_LABELS[action_name], _target)


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


def _optional_int(value: Any) -> Optional[int]:
    """
    功能:
        将可选值转换为 int.
    参数:
        value: Any, 原始值.
    返回:
        Optional[int], 转换结果.
    """
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    return int(text)


def _optional_str(value: Any) -> Optional[str]:
    """
    功能:
        将可选值转换为非空字符串.
    参数:
        value: Any, 原始值.
    返回:
        Optional[str], 转换结果.
    """
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    return text


def _float_param(params: JsonDict, key: str, default_value: float) -> float:
    """
    功能:
        从动作参数中读取浮点值.
    参数:
        params: Dict[str, Any], 参数.
        key: str, 参数名.
        default_value: float, 默认值.
    返回:
        float, 浮点值.
    """
    value = params.get(key, default_value)
    return float(value)


def _bool_param(params: JsonDict, key: str, default_value: bool) -> bool:
    """
    功能:
        从动作参数中读取布尔值.
    参数:
        params: Dict[str, Any], 参数.
        key: str, 参数名.
        default_value: bool, 默认值.
    返回:
        bool, 布尔值.
    """
    value = params.get(key, default_value)
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in ("1", "true", "yes", "y", "on", "是")


def _execute_action(
    manager: SynthesisStationManager,
    action_name: str,
    params: JsonDict,
    log: Callable[[str], None],
) -> Any:
    """
    功能:
        根据动作名称调用现有合成工站管理器方法.
    参数:
        manager: SynthesisStationManager, 合成工站管理器.
        action_name: str, 动作名称.
        params: Dict[str, Any], 动作参数.
        log: Callable, 任务日志函数.
    返回:
        Any, 动作结果.
    """
    if action_name == "sync_chemicals":
        return manager.sync_chemicals_to_station()
    if action_name == "device_init":
        return manager.device_init()
    if action_name == "batch_in_agv":
        file_path = _optional_str(params.get("file_path"))
        block = _bool_param(params, "block", True)
        return manager.batch_in_tray_with_agv_transfer(file_path=file_path, block=block)
    if action_name == "start_task":
        task_id = _optional_int(params.get("task_id"))
        return manager.start_task(
            task_id,
            check_glovebox_env=_bool_param(params, "check_glovebox_env", True),
            water_limit_ppm=_float_param(params, "water_limit_ppm", 10.0),
            oxygen_limit_ppm=_float_param(params, "oxygen_limit_ppm", 10.0),
        )
    if action_name == "wait_task":
        return manager.wait_task_with_ops(
            _optional_int(params.get("task_id")),
            poll_interval_s=_float_param(params, "poll_interval_s", 2.0),
        )
    if action_name == "batch_out_task_empty":
        return manager.batch_out_task_and_empty_trays(_optional_int(params.get("task_id")))
    if action_name == "auto_unload_to_agv":
        return manager.auto_unload_trays_to_agv(
            batch_out_file=_optional_str(params.get("batch_out_file")),
            block=_bool_param(params, "block", True),
            auto_run_analysis=_bool_param(params, "auto_run_analysis", True),
        )
    if action_name == "run_analysis":
        return manager.run_analysis(_optional_str(params.get("task_id")))
    if action_name == "poll_analysis":
        return manager.poll_analysis_run(
            task_id=_optional_str(params.get("task_id")),
            poll_interval=_float_param(params, "poll_interval", 30.0),
        )
    if action_name == "transfer_analysis_to_shelf":
        return manager.transfer_analysis_to_shelf()
    if action_name == "print_reagent_labels":
        manager.print_reagent_labels()
        return {"success": True}
    if action_name == "print_task_number_labels":
        task_id = _optional_int(params.get("task_id"))
        if task_id is None:
            raise ValueError("打印任务编号标签需要 task_id.")
        manager.print_task_number_labels(task_id)
        return {"success": True}
    if action_name == "upload_task_flow":
        log("正在同步化学品库到合成工站.")
        sync_result = manager.sync_chemicals_to_station()
        log("正在提交当前 Excel 模板.")
        task_id = manager.create_task_by_file(str(DEFAULT_REACTION_TEMPLATE))
        log("正在执行物料核算.")
        resource_result = manager.check_resource_for_task(str(DEFAULT_REACTION_TEMPLATE))
        return {
            "sync": sync_result,
            "task_id": task_id,
            "resource_check": resource_result,
        }
    raise ValueError(f"未实现的动作: {action_name}")


ACTION_LABELS: Dict[str, str] = {
    "sync_chemicals": "同步化学品库",
    "device_init": "设备初始化",
    "batch_in_agv": "AGV 上料",
    "start_task": "启动任务",
    "wait_task": "等待任务完成",
    "batch_out_task_empty": "下料任务物料和空托盘",
    "auto_unload_to_agv": "AGV 自动下料",
    "run_analysis": "提交分析任务",
    "poll_analysis": "谱图数据处理",
    "transfer_analysis_to_shelf": "分析样品转运到货架",
    "print_reagent_labels": "打印上料试剂标签",
    "print_task_number_labels": "打印任务编号标签",
    "upload_task_flow": "上传任务流程",
}

