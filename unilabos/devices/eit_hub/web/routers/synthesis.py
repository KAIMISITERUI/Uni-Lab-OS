# -*- coding: utf-8 -*-
"""
功能:
    提供合成工站 Web API, 将页面请求转换为现有 SynthesisStationManager 调用.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from unilabos.devices.eit_synthesis_station.manager.station_manager import (
    SynthesisStationManager,
)

from ..deps import get_synthesis_manager
from ..excel_codec import (
    DEFAULT_BATCH_IN_TEMPLATE,
    DEFAULT_REACTION_TEMPLATE,
    read_batch_in_template,
    read_reaction_template,
    write_batch_in_template,
    write_reaction_template,
)
from ..excel_printing import DEFAULT_BATCH_IN_TABLE_PRINTER, print_batch_in_table
from ..jobs import JobBusyError, JobStoppedError, job_manager

logger = logging.getLogger("EITHubSynthesisRouter")

JsonDict = Dict[str, Any]

router = APIRouter(prefix="/api/synthesis", tags=["synthesis"])

W1_SHELF_POSITIONS = {"W-1-1", "W-1-3", "W-1-5", "W-1-7"}
W1_SHELF_ACTIONS = {"outside", "home"}
OUTER_DOOR_ACTIONS = {"open", "close"}
DEFAULT_HISTORY_TASKS_DIR = DEFAULT_REACTION_TEMPLATE.parent.parent / "data" / "tasks"
WORKFLOW_STEP_ORDER = (
    "batch_in",
    "resource_check",
    "start_task",
    "wait_task",
    "batch_out",
    "auto_unload",
    "submit_analysis",
    "poll_analysis",
    "calculate_yields",
)
WORKFLOW_STEP_LABELS = {
    "batch_in": "AGV上料",
    "resource_check": "物料检查",
    "start_task": "开始合成任务",
    "wait_task": "任务监控",
    "batch_out": "下料(任务物料+空托盘)",
    "auto_unload": "AGV转运",
    "submit_analysis": "运行分析任务",
    "poll_analysis": "谱图数据处理",
    "calculate_yields": "产率计算",
}
WORKFLOW_BATCH_IN_MODES = {"manual", "agv"}
WORKFLOW_PAUSABLE_TASK_STEPS = {"start_task", "wait_task"}
WORKFLOW_CANCELABLE_TASK_STEPS = {"start_task", "wait_task"}
WORKFLOW_ANALYSIS_STOP_STEPS = {"submit_analysis", "poll_analysis"}

_workflow_lock = threading.RLock()
_workflow_runs: Dict[str, "WorkflowRunState"] = {}


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


class ResourceCheckRequest(BaseModel):
    """
    功能:
        承载物料核算请求, 包含任务模板和是否自动修改上料文件.
    参数:
        template: Optional[Dict[str, Any]], 任务模板结构.
        auto_generate_batch_file: bool, 是否在核算后自动修改上料文件.
    """

    template: Optional[JsonDict] = None
    auto_generate_batch_file: bool = True


class WorkflowBatchInRequest(BaseModel):
    """
    功能:
        承载工作流上料步骤参数.
    参数:
        mode: str, 上料方式, manual 表示手动上料, agv 表示 AGV 上料.
        chamber_capacity: int, AGV 上料时过渡舱单轮最大托盘数.
    """

    mode: str = "agv"
    chamber_capacity: int = Field(default=8, ge=1)


class WorkflowWaitTaskRequest(BaseModel):
    """
    功能:
        承载工作流任务监控参数.
    参数:
        poll_interval_s: float, 合成任务状态轮询间隔秒数.
    """

    poll_interval_s: float = Field(default=2.0, gt=0)


class WorkflowStartTaskRequest(BaseModel):
    """
    功能:
        承载工作流启动任务步骤参数.
    参数:
        check_glovebox_env: bool, 启动前是否检查手套箱水氧.
        water_limit_ppm: float, 手套箱水含量上限.
        oxygen_limit_ppm: float, 手套箱氧含量上限.
    """

    check_glovebox_env: bool = True
    water_limit_ppm: float = Field(default=10.0, gt=0)
    oxygen_limit_ppm: float = Field(default=10.0, gt=0)


class WorkflowSubmitAnalysisRequest(BaseModel):
    """
    功能:
        承载工作流提交分析任务步骤参数.
    参数:
        auto_submit_after_agv: bool, 是否在 AGV 转运分析物料完成后立即提交分析任务.
    """

    auto_submit_after_agv: bool = True


class WorkflowPollAnalysisRequest(BaseModel):
    """
    功能:
        承载工作流谱图处理参数.
    参数:
        poll_interval: float, 分析任务状态轮询间隔秒数.
    """

    poll_interval: float = Field(default=30.0, gt=0)


class WorkflowStartRequest(BaseModel):
    """
    功能:
        承载合成工作流启动请求.
    参数:
        experiment_id: int, 已上传任务的实验 ID.
        experiment_name: str, 已上传任务的实验名称.
        start_step: str, 工作流开始步骤 ID.
        batch_in: WorkflowBatchInRequest, 上料步骤参数.
        start_task: WorkflowStartTaskRequest, 启动任务步骤参数.
        wait_task: WorkflowWaitTaskRequest, 任务监控参数.
        has_analysis_task: bool, 当前任务是否设置了分析任务.
        submit_analysis: WorkflowSubmitAnalysisRequest, 提交分析任务步骤参数.
        poll_analysis: WorkflowPollAnalysisRequest, 谱图处理参数.
    """

    experiment_id: int
    experiment_name: str
    start_step: str
    batch_in: WorkflowBatchInRequest = Field(default_factory=WorkflowBatchInRequest)
    start_task: WorkflowStartTaskRequest = Field(default_factory=WorkflowStartTaskRequest)
    wait_task: WorkflowWaitTaskRequest = Field(default_factory=WorkflowWaitTaskRequest)
    has_analysis_task: bool = True
    submit_analysis: WorkflowSubmitAnalysisRequest = Field(default_factory=WorkflowSubmitAnalysisRequest)
    poll_analysis: WorkflowPollAnalysisRequest = Field(default_factory=WorkflowPollAnalysisRequest)


@dataclass
class WorkflowStepState:
    """
    功能:
        保存单个工作流步骤的运行状态.
    参数:
        step_id: str, 步骤 ID.
        name: str, 步骤中文名称.
        status: str, pending/running/succeeded/failed/skipped.
        result: Any, 步骤结果.
        error: Optional[str], 步骤失败信息.
    """

    step_id: str
    name: str
    status: str = "pending"
    result: Any = None
    error: Optional[str] = None

    def to_dict(self) -> JsonDict:
        """
        功能:
            转换为可 JSON 序列化的字典.
        返回:
            Dict[str, Any], 步骤状态快照.
        """
        return {
            "id": self.step_id,
            "name": self.name,
            "status": self.status,
            "result": _workflow_to_jsonable(self.result),
            "error": self.error,
        }


@dataclass
class WorkflowRunState:
    """
    功能:
        保存工作流运行状态, 支持步骤间暂停与恢复.
    参数:
        workflow_id: str, 工作流 ID, 与后台 job_id 相同.
        experiment_id: int, 实验 ID.
        experiment_name: str, 实验名称.
        start_step: str, 开始步骤 ID.
        steps: List[WorkflowStepState], 全部步骤状态.
        logs: List[str], 工作流日志.
    """

    workflow_id: str
    experiment_id: int
    experiment_name: str
    start_step: str
    steps: List[WorkflowStepState]
    logs: List[str] = field(default_factory=list)
    current_step: Optional[str] = None
    pause_requested: bool = False
    paused: bool = False
    task_pause_sent: bool = False
    stop_requested: bool = False
    stopped: bool = False
    _condition: threading.Condition = field(default_factory=lambda: threading.Condition(threading.RLock()))

    def add_log(self, message: str) -> None:
        """
        功能:
            追加工作流日志.
        参数:
            message: str, 日志文本.
        返回:
            None.
        """
        with self._condition:
            self.logs.append(message)

    def set_current_step(self, step_id: str) -> None:
        """
        功能:
            设置当前执行步骤.
        参数:
            step_id: str, 步骤 ID.
        返回:
            None.
        """
        with self._condition:
            self.current_step = step_id

    def clear_current_step(self) -> None:
        """
        功能:
            清空当前执行步骤.
        返回:
            None.
        """
        with self._condition:
            self.current_step = None

    def update_step(self, step_id: str, status_text: str, result: Any = None, error: Optional[str] = None) -> None:
        """
        功能:
            更新指定步骤状态.
        参数:
            step_id: str, 步骤 ID.
            status_text: str, 新状态文本.
            result: Any, 步骤结果.
            error: Optional[str], 失败信息.
        返回:
            None.
        """
        with self._condition:
            for step in self.steps:
                if step.step_id == step_id:
                    step.status = status_text
                    step.result = result
                    step.error = error
                    break

    def request_pause(self) -> None:
        """
        功能:
            标记工作流需要暂停.
        返回:
            None.
        """
        with self._condition:
            if self.stop_requested is True:
                return
            self.pause_requested = True

    def request_stop(self) -> None:
        """
        功能:
            标记工作流需要停止, 并唤醒可能处于暂停等待的工作流线程.
        返回:
            None.
        """
        with self._condition:
            self.stop_requested = True
            self.pause_requested = False
            self.paused = False
            self._condition.notify_all()

    def mark_paused_immediately(self) -> None:
        """
        功能:
            当前步骤支持立即暂停时, 直接标记为暂停态.
        返回:
            None.
        """
        with self._condition:
            self.paused = True

    def raise_if_stop_requested(self) -> None:
        """
        功能:
            检查停止请求, 已请求停止时更新步骤状态并抛出停止异常.
        返回:
            None.
        """
        with self._condition:
            if self.stop_requested is False:
                return
            self._raise_stopped_locked()

    def wait_if_pause_requested(self, log_fn: Callable[[str], None]) -> None:
        """
        功能:
            在步骤边界等待恢复信号.
        参数:
            log_fn: Callable, 工作流日志函数.
        返回:
            None.
        """
        with self._condition:
            if self.stop_requested is True:
                self._raise_stopped_locked()
            if self.pause_requested is False:
                return
            self.paused = True
            log_fn("工作流已暂停, 等待恢复.")
            while self.pause_requested is True:
                if self.stop_requested is True:
                    self._raise_stopped_locked()
                self._condition.wait(timeout=1.0)
            self.paused = False
            log_fn("工作流已恢复, 继续执行后续步骤.")

    def resume(self) -> None:
        """
        功能:
            清除暂停标记并唤醒工作流线程.
        返回:
            None.
        """
        with self._condition:
            if self.stop_requested is True:
                return
            self.pause_requested = False
            self.paused = False
            self._condition.notify_all()

    def _raise_stopped_locked(self) -> None:
        """
        功能:
            在已持有条件锁时构造停止结果, 标记工作流停止并抛出停止异常.
        返回:
            None.
        """
        result = {
            "workflow_id": self.workflow_id,
            "experiment_id": self.experiment_id,
            "experiment_name": self.experiment_name,
            "current_step": self.current_step,
        }
        self._mark_stopped_locked()
        raise JobStoppedError("工作流已停止.", result=result)

    def _mark_stopped_locked(self) -> None:
        """
        功能:
            在已持有条件锁时标记工作流停止, 当前运行步骤置为 stopped, 后续 pending 步骤置为 skipped.
        返回:
            None.
        """
        self.stopped = True
        self.stop_requested = True
        self.pause_requested = False
        self.paused = False
        for step in self.steps:
            if self.current_step is not None and step.step_id == self.current_step and step.status == "running":
                step.status = "stopped"
            elif step.status == "pending":
                step.status = "skipped"
        self.current_step = None

    def to_dict(self, job_status: Optional[str] = None, job_error: Optional[str] = None, result: Any = None) -> JsonDict:
        """
        功能:
            转换为前端工作流状态结构.
        参数:
            job_status: Optional[str], 后台任务状态.
            job_error: Optional[str], 后台任务错误.
            result: Any, 后台任务结果.
        返回:
            Dict[str, Any], 工作流状态.
        """
        with self._condition:
            status_text = job_status or "queued"
            if self.stopped is True or status_text == "stopped":
                status_text = "stopped"
            elif status_text in ("queued", "running"):
                if self.stop_requested is True:
                    status_text = "stopping"
                elif self.paused is True:
                    status_text = "paused"
                elif self.pause_requested is True:
                    status_text = "pausing"
            return {
                "workflow_id": self.workflow_id,
                "job_id": self.workflow_id,
                "status": status_text,
                "current_step": self.current_step,
                "experiment_id": self.experiment_id,
                "experiment_name": self.experiment_name,
                "start_step": self.start_step,
                "steps": [step.to_dict() for step in self.steps],
                "logs": list(self.logs),
                "result": _workflow_to_jsonable(result),
                "error": job_error,
            }


class _WorkflowLogBridge(logging.Handler):
    """
    功能:
        将底层控制器日志转发到工作流日志.
    参数:
        log_fn: Callable, 工作流日志函数.
    """

    def __init__(self, log_fn: Callable[[str], None]) -> None:
        super().__init__(level=logging.INFO)
        self._log_fn = log_fn

    def emit(self, record: logging.LogRecord) -> None:
        """
        功能:
            处理一条日志记录并写入工作流日志.
        参数:
            record: logging.LogRecord, 日志记录.
        返回:
            None.
        """
        try:
            self._log_fn(record.getMessage())
        except Exception:
            self.handleError(record)


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


@router.get("/reaction-template/history")
def list_reaction_template_history(
    q: Optional[str] = Query(default=None, description="按实验名称搜索"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
) -> JsonDict:
    """
    功能:
        返回可载入的历史实验模板摘要列表.
    参数:
        q: Optional[str], 按实验名称模糊搜索.
        page: int, 页码, 从 1 开始.
        page_size: int, 每页条数.
    返回:
        Dict[str, Any], 包含历史任务摘要分页列表.
    """
    try:
        all_items = _list_reaction_template_history(query_text=q)
        start = (page - 1) * page_size
        end = start + page_size
        return {
            "total": len(all_items),
            "page": page,
            "page_size": page_size,
            "items": all_items[start:end],
        }
    except Exception as exc:
        logger.exception("读取历史实验模板列表失败")
        raise _json_error(f"读取历史实验模板列表失败: {exc}") from exc


@router.get("/reaction-template/history/{task_id}")
def get_reaction_template_history(task_id: int) -> JsonDict:
    """
    功能:
        读取指定历史任务的实验模板, 仅做读取不修改历史文件.
    参数:
        task_id: int, 历史任务 ID.
    返回:
        Dict[str, Any], 历史任务模板结构.
    """
    try:
        history_path = _find_history_reaction_template_path(task_id)
        return read_reaction_template(history_path)
    except FileNotFoundError as exc:
        raise _json_error(str(exc), status.HTTP_404_NOT_FOUND) from exc
    except Exception as exc:
        logger.exception("读取历史实验模板失败, task_id=%s", task_id)
        raise _json_error(f"读取历史实验模板失败: {exc}") from exc


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


@router.get("/batch-in-template")
def get_batch_in_template() -> JsonDict:
    """
    功能:
        读取当前合成工站上料文件.
    返回:
        Dict[str, Any], 上料表格结构.
    """
    try:
        return read_batch_in_template(DEFAULT_BATCH_IN_TEMPLATE)
    except Exception as exc:
        logger.exception("读取上料文件失败")
        raise _json_error(f"读取上料文件失败: {exc}") from exc


@router.put("/batch-in-template")
def save_batch_in_template(payload: JsonDict = Body(...)) -> JsonDict:
    """
    功能:
        将 Web 上料表格内容覆盖保存到默认 batch_in_tray.xlsx.
    参数:
        payload: Dict[str, Any], 上料表格结构.
    返回:
        Dict[str, Any], 保存后的上料表格结构.
    """
    if job_manager.is_busy() is True:
        raise _json_error("当前已有合成工站后台任务正在运行, 请稍后再保存.", status.HTTP_409_CONFLICT)
    try:
        return write_batch_in_template(payload, DEFAULT_BATCH_IN_TEMPLATE)
    except Exception as exc:
        logger.exception("保存上料文件失败")
        raise _json_error(f"保存上料文件失败: {exc}") from exc


@router.post("/batch-in-template/print-reagent-labels")
def print_batch_in_reagent_labels(
    payload: JsonDict = Body(...),
    manager: SynthesisStationManager = Depends(get_synthesis_manager),
) -> JsonDict:
    """
    功能:
        保存 Web 上料表格并创建打印试剂标签后台任务.
    参数:
        payload: Dict[str, Any], 上料表格结构.
        manager: SynthesisStationManager, 合成工站管理器.
    返回:
        Dict[str, Any], 后台任务 ID.
    """

    def _target(log: Callable[[str], None]) -> JsonDict:
        log("正在保存 Web 上料表格到本地 Excel 文件.")
        saved = write_batch_in_template(payload, DEFAULT_BATCH_IN_TEMPLATE)
        log("正在调用合成工站试剂标签打印逻辑.")
        manager.print_reagent_labels()
        log("试剂标签打印完成.")
        return {
            "file_path": saved.get("path", str(DEFAULT_BATCH_IN_TEMPLATE)),
            "printed": True,
        }

    return _start_job("打印试剂标签", _target)


@router.post("/batch-in-template/print-table")
def print_batch_in_template(
    payload: JsonDict = Body(...),
) -> JsonDict:
    """
    功能:
        保存 Web 上料表格并创建打印上料表格后台任务.
    参数:
        payload: Dict[str, Any], 上料表格结构.
    返回:
        Dict[str, Any], 后台任务 ID.
    """

    def _target(log: Callable[[str], None]) -> JsonDict:
        log("正在保存 Web 上料表格到本地 Excel 文件.")
        saved = write_batch_in_template(payload, DEFAULT_BATCH_IN_TEMPLATE)
        log(f"正在打印上料表格, 打印机={DEFAULT_BATCH_IN_TABLE_PRINTER}.")
        result = print_batch_in_table(DEFAULT_BATCH_IN_TEMPLATE, DEFAULT_BATCH_IN_TABLE_PRINTER)
        log("上料表格打印任务已提交.")
        result["file_path"] = saved.get("path", result.get("file_path", str(DEFAULT_BATCH_IN_TEMPLATE)))
        return result

    return _start_job("打印上料表格", _target)


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
        log("正在同步化学品库到工站.")
        manager.sync_chemicals_to_station()
        log("化学品库同步完成.")
        log("正在调用合成工站任务上传逻辑.")
        task_id = manager.create_task_by_file(str(DEFAULT_REACTION_TEMPLATE))
        log(f"合成任务上传完成, task_id={task_id}.")
        return {"task_id": task_id}

    return _start_job("上传任务", _target)


@router.post("/resource-check")
def check_resource(
    request: ResourceCheckRequest = Body(...),
    manager: SynthesisStationManager = Depends(get_synthesis_manager),
) -> JsonDict:
    """
    功能:
        保存 Web 表格并执行物料核算, 实际执行放入后台任务.
    参数:
        request: ResourceCheckRequest, 物料核算请求.
    返回:
        Dict[str, Any], 后台任务 ID.
    """

    def _target(log: Callable[[str], None]) -> JsonDict:
        if request.template is not None:
            log("正在保存 Web 表格到本地 Excel 模板.")
            write_reaction_template(request.template, DEFAULT_REACTION_TEMPLATE)
        if request.auto_generate_batch_file is True:
            log("正在执行物料核算, 并自动修改上料文件.")
        else:
            log("正在执行物料核算, 不自动修改上料文件.")
        result = manager.check_resource_for_task(
            str(DEFAULT_REACTION_TEMPLATE),
            auto_generate_batch_file=request.auto_generate_batch_file,
        )
        log("物料核算完成.")
        return result

    return _start_job("物料核算", _target)


@router.post("/workflow/start")
def start_workflow(
    request: WorkflowStartRequest = Body(...),
    manager: SynthesisStationManager = Depends(get_synthesis_manager),
) -> JsonDict:
    """
    功能:
        启动上传任务后的合成工作流后台任务.
    参数:
        request: WorkflowStartRequest, 工作流启动参数.
        manager: SynthesisStationManager, 合成工站管理器.
    返回:
        Dict[str, Any], 工作流 ID 和排队状态.
    """
    _validate_workflow_request(request)
    state = _create_workflow_state(request)
    ready_event = threading.Event()

    def _target(log: Callable[[str], None]) -> JsonDict:
        ready_event.wait()
        return _run_workflow_steps(state, request, manager, log)

    try:
        job = job_manager.start_exclusive("合成工作流", _target)
    except JobBusyError as exc:
        raise _json_error(str(exc), status.HTTP_409_CONFLICT) from exc

    state.workflow_id = job.job_id
    with _workflow_lock:
        _workflow_runs[job.job_id] = state
    ready_event.set()
    return {
        "workflow_id": job.job_id,
        "job_id": job.job_id,
        "status": "queued",
    }


@router.get("/workflow/{workflow_id}")
def get_workflow(workflow_id: str) -> JsonDict:
    """
    功能:
        查询合成工作流运行状态.
    参数:
        workflow_id: str, 工作流 ID.
    返回:
        Dict[str, Any], 工作流状态.
    """
    state = _get_workflow_state(workflow_id)
    job = job_manager.get(workflow_id)
    if job is None:
        raise _json_error(f"未找到工作流后台任务: {workflow_id}", status.HTTP_404_NOT_FOUND)
    return state.to_dict(job_status=job.status, job_error=job.error, result=job.result)


@router.post("/workflow/{workflow_id}/pause")
def pause_workflow(
    workflow_id: str,
    manager: SynthesisStationManager = Depends(get_synthesis_manager),
) -> JsonDict:
    """
    功能:
        请求暂停合成工作流. 对任务运行阶段尽量立即下发工站暂停.
    参数:
        workflow_id: str, 工作流 ID.
        manager: SynthesisStationManager, 合成工站管理器.
    返回:
        Dict[str, Any], 工作流状态.
    """
    state = _get_workflow_state(workflow_id)
    job = job_manager.get(workflow_id)
    if job is None:
        raise _json_error(f"未找到工作流后台任务: {workflow_id}", status.HTTP_404_NOT_FOUND)
    if job.status not in ("queued", "running"):
        return state.to_dict(job_status=job.status, job_error=job.error, result=job.result)

    state.request_pause()
    state.add_log("已收到暂停请求.")
    if state.current_step in WORKFLOW_PAUSABLE_TASK_STEPS:
        _pause_running_station_task(state, manager)
    return state.to_dict(job_status=job.status, job_error=job.error, result=job.result)


@router.post("/workflow/{workflow_id}/resume")
def resume_workflow(
    workflow_id: str,
    manager: SynthesisStationManager = Depends(get_synthesis_manager),
) -> JsonDict:
    """
    功能:
        恢复已暂停的合成工作流.
    参数:
        workflow_id: str, 工作流 ID.
        manager: SynthesisStationManager, 合成工站管理器.
    返回:
        Dict[str, Any], 工作流状态.
    """
    state = _get_workflow_state(workflow_id)
    job = job_manager.get(workflow_id)
    if job is None:
        raise _json_error(f"未找到工作流后台任务: {workflow_id}", status.HTTP_404_NOT_FOUND)
    if job.status not in ("queued", "running"):
        return state.to_dict(job_status=job.status, job_error=job.error, result=job.result)

    if state.task_pause_sent is True:
        state.add_log("正在恢复合成工站任务.")
        manager.fault_recovery(resume_task=1)
        state.task_pause_sent = False
    state.resume()
    state.add_log("已收到恢复请求.")
    return state.to_dict(job_status=job.status, job_error=job.error, result=job.result)


@router.post("/workflow/{workflow_id}/stop")
def stop_workflow(
    workflow_id: str,
    manager: SynthesisStationManager = Depends(get_synthesis_manager),
) -> JsonDict:
    """
    功能:
        停止合成工作流, 终止当前可取消操作并阻止后续步骤继续执行.
    参数:
        workflow_id: str, 工作流 ID.
        manager: SynthesisStationManager, 合成工站管理器.
    返回:
        Dict[str, Any], 工作流状态.
    """
    state = _get_workflow_state(workflow_id)
    job = job_manager.get(workflow_id)
    if job is None:
        raise _json_error(f"未找到工作流后台任务: {workflow_id}", status.HTTP_404_NOT_FOUND)
    if job.status not in ("queued", "running"):
        return state.to_dict(job_status=job.status, job_error=job.error, result=job.result)

    state.request_stop()
    state.add_log("已收到停止请求, 正在终止当前操作.")
    _terminate_current_workflow_operation(state, manager)
    return state.to_dict(job_status=job.status, job_error=job.error, result=job.result)


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


def _validate_workflow_request(request: WorkflowStartRequest) -> None:
    """
    功能:
        校验工作流启动参数.
    参数:
        request: WorkflowStartRequest, 工作流启动请求.
    返回:
        None.
    """
    if request.experiment_id <= 0:
        raise _json_error("实验ID必须大于0.")
    if str(request.experiment_name).strip() == "":
        raise _json_error("实验名称不能为空.")
    if request.start_step not in WORKFLOW_STEP_ORDER:
        allowed_text = ", ".join(WORKFLOW_STEP_ORDER)
        raise _json_error(f"工作流开始步骤无效: {request.start_step}. 可选值: {allowed_text}.")
    if request.batch_in.mode not in WORKFLOW_BATCH_IN_MODES:
        allowed_text = ", ".join(sorted(WORKFLOW_BATCH_IN_MODES))
        raise _json_error(f"上料方式无效: {request.batch_in.mode}. 可选值: {allowed_text}.")
    if request.has_analysis_task is False and request.start_step in ("submit_analysis", "poll_analysis", "calculate_yields"):
        raise _json_error("当前任务未设置分析任务, 不能从分析步骤开始.")


def _create_workflow_state(request: WorkflowStartRequest) -> WorkflowRunState:
    """
    功能:
        根据启动请求创建工作流状态对象.
    参数:
        request: WorkflowStartRequest, 工作流启动请求.
    返回:
        WorkflowRunState, 初始化后的工作流状态.
    """
    start_index = WORKFLOW_STEP_ORDER.index(request.start_step)
    steps: List[WorkflowStepState] = []
    for index, step_id in enumerate(WORKFLOW_STEP_ORDER):
        status_text = "pending"
        if index < start_index:
            status_text = "skipped"
        steps.append(
            WorkflowStepState(
                step_id=step_id,
                name=_workflow_step_label(step_id, request),
                status=status_text,
            )
        )
    return WorkflowRunState(
        workflow_id="",
        experiment_id=request.experiment_id,
        experiment_name=str(request.experiment_name).strip(),
        start_step=request.start_step,
        steps=steps,
    )


def _get_workflow_state(workflow_id: str) -> WorkflowRunState:
    """
    功能:
        读取已登记的工作流状态.
    参数:
        workflow_id: str, 工作流 ID.
    返回:
        WorkflowRunState, 工作流状态对象.
    """
    with _workflow_lock:
        state = _workflow_runs.get(workflow_id)
    if state is None:
        raise _json_error(f"未找到工作流: {workflow_id}", status.HTTP_404_NOT_FOUND)
    return state


def _run_workflow_steps(
    state: WorkflowRunState,
    request: WorkflowStartRequest,
    manager: SynthesisStationManager,
    job_log: Callable[[str], None],
) -> JsonDict:
    """
    功能:
        按工作流步骤顺序执行合成任务后流程.
    参数:
        state: WorkflowRunState, 工作流状态对象.
        request: WorkflowStartRequest, 启动参数.
        manager: SynthesisStationManager, 合成工站管理器.
        job_log: Callable, 后台任务日志函数.
    返回:
        Dict[str, Any], 工作流执行结果.
    """

    def workflow_log(message: str) -> None:
        state.add_log(message)
        job_log(message)

    start_index = WORKFLOW_STEP_ORDER.index(request.start_step)
    completed_steps: List[str] = []
    workflow_log(f"工作流开始, 实验ID={request.experiment_id}, 实验名称={request.experiment_name}.")
    bridges = _attach_workflow_loggers(workflow_log)
    try:
        for step_id in WORKFLOW_STEP_ORDER[start_index:]:
            state.raise_if_stop_requested()
            state.wait_if_pause_requested(workflow_log)
            state.raise_if_stop_requested()
            if _workflow_step_enabled(step_id, request) is False:
                state.update_step(step_id, "skipped")
                workflow_log(f"跳过步骤: {_workflow_step_label(step_id, request)}.")
                continue
            state.set_current_step(step_id)
            state.update_step(step_id, "running")
            workflow_log(f"开始步骤: {_workflow_step_label(step_id, request)}.")
            try:
                step_result = _execute_workflow_step(step_id, request, manager)
            except JobStoppedError:
                state.update_step(step_id, "stopped")
                workflow_log(f"步骤已停止: {_workflow_step_label(step_id, request)}.")
                raise
            except Exception as exc:
                state.update_step(step_id, "failed", error=str(exc))
                workflow_log(f"步骤失败: {_workflow_step_label(step_id, request)}, 错误: {exc}.")
                raise
            state.raise_if_stop_requested()
            state.update_step(step_id, "succeeded", result=step_result)
            completed_steps.append(step_id)
            workflow_log(f"步骤完成: {_workflow_step_label(step_id, request)}.")
            state.wait_if_pause_requested(workflow_log)
            state.raise_if_stop_requested()
        state.clear_current_step()
        workflow_log("工作流执行完成.")
        return {
            "workflow_id": state.workflow_id,
            "experiment_id": state.experiment_id,
            "experiment_name": state.experiment_name,
            "completed_steps": completed_steps,
        }
    finally:
        _detach_workflow_loggers(bridges)


def _execute_workflow_step(
    step_id: str,
    request: WorkflowStartRequest,
    manager: SynthesisStationManager,
) -> Any:
    """
    功能:
        执行单个工作流步骤.
    参数:
        step_id: str, 步骤 ID.
        request: WorkflowStartRequest, 工作流参数.
        manager: SynthesisStationManager, 合成工站管理器.
    返回:
        Any, 底层步骤执行结果.
    """
    if step_id == "batch_in":
        if request.batch_in.mode == "manual":
            return manager.batch_in_tray_by_file(str(DEFAULT_BATCH_IN_TEMPLATE))
        return manager.batch_in_tray_with_agv_transfer(
            str(DEFAULT_BATCH_IN_TEMPLATE),
            chamber_capacity=request.batch_in.chamber_capacity,
        )
    if step_id == "resource_check":
        return manager.check_resource_for_task(
            str(DEFAULT_REACTION_TEMPLATE),
            auto_generate_batch_file=False,
        )
    if step_id == "start_task":
        return manager.start_task(
            request.experiment_id,
            check_glovebox_env=request.start_task.check_glovebox_env,
            water_limit_ppm=request.start_task.water_limit_ppm,
            oxygen_limit_ppm=request.start_task.oxygen_limit_ppm,
        )
    if step_id == "wait_task":
        return manager.wait_task_with_ops(
            request.experiment_id,
            poll_interval_s=request.wait_task.poll_interval_s,
        )
    if step_id == "batch_out":
        return manager.batch_out_task_and_empty_trays(request.experiment_id)
    if step_id == "auto_unload":
        return manager.auto_unload_trays_to_agv(
            auto_run_analysis=(
                request.has_analysis_task is True
                and request.submit_analysis.auto_submit_after_agv is True
            ),
        )
    if step_id == "submit_analysis":
        if (
            request.submit_analysis.auto_submit_after_agv is True
            and WORKFLOW_STEP_ORDER.index(request.start_step) <= WORKFLOW_STEP_ORDER.index("auto_unload")
        ):
            return {
                "success": True,
                "submitted_in_auto_unload": True,
            }
        return manager.run_analysis(str(request.experiment_id))
    if step_id == "poll_analysis":
        return manager.poll_analysis_run(
            str(request.experiment_id),
            poll_interval=request.poll_analysis.poll_interval,
        )
    if step_id == "calculate_yields":
        return manager.calculate_yields(str(request.experiment_id))
    raise ValueError(f"未知工作流步骤: {step_id}")


def _workflow_step_enabled(step_id: str, request: WorkflowStartRequest) -> bool:
    """
    功能:
        判断工作流步骤是否需要执行.
    参数:
        step_id: str, 步骤 ID.
        request: WorkflowStartRequest, 工作流启动参数.
    返回:
        bool, True 表示执行, False 表示跳过.
    """
    if request.has_analysis_task is False and step_id in ("submit_analysis", "poll_analysis", "calculate_yields"):
        return False
    return True


def _workflow_step_label(step_id: str, request: WorkflowStartRequest) -> str:
    """
    功能:
        根据工作流参数返回步骤显示名称.
    参数:
        step_id: str, 步骤 ID.
        request: WorkflowStartRequest, 工作流启动参数.
    返回:
        str, 步骤中文名称.
    """
    if step_id == "batch_in":
        if request.batch_in.mode == "manual":
            return "手动上料"
        return "AGV上料"
    return WORKFLOW_STEP_LABELS[step_id]


def _pause_running_station_task(state: WorkflowRunState, manager: SynthesisStationManager) -> None:
    """
    功能:
        对合成任务运行或监控阶段下发工站暂停.
    参数:
        state: WorkflowRunState, 工作流状态.
        manager: SynthesisStationManager, 合成工站管理器.
    返回:
        None.
    """
    try:
        state.add_log(f"正在暂停合成工站任务, 实验ID={state.experiment_id}.")
        manager.stop_task(state.experiment_id)
        state.task_pause_sent = True
        state.mark_paused_immediately()
        state.add_log("合成工站暂停请求已下发.")
    except Exception as exc:
        logger.exception("暂停合成工站任务失败, workflow_id=%s", state.workflow_id)
        state.add_log(f"暂停合成工站任务失败: {exc}.")


def _terminate_current_workflow_operation(state: WorkflowRunState, manager: SynthesisStationManager) -> None:
    """
    功能:
        根据当前步骤下发可用的终止命令, 并让工作流线程在步骤边界停止后续操作.
    参数:
        state: WorkflowRunState, 工作流状态.
        manager: SynthesisStationManager, 合成工站管理器.
    返回:
        None.
    """
    current_step = state.current_step
    if current_step in WORKFLOW_CANCELABLE_TASK_STEPS or state.task_pause_sent is True:
        _cancel_running_station_task(state, manager)
    if current_step in WORKFLOW_ANALYSIS_STOP_STEPS:
        _abort_running_analysis(state)
    if current_step in ("batch_in", "batch_out", "auto_unload"):
        _stop_agv_arm_operation(state)


def _cancel_running_station_task(state: WorkflowRunState, manager: SynthesisStationManager) -> None:
    """
    功能:
        对合成任务运行或监控阶段下发取消任务命令.
    参数:
        state: WorkflowRunState, 工作流状态.
        manager: SynthesisStationManager, 合成工站管理器.
    返回:
        None.
    """
    try:
        state.add_log(f"正在取消合成工站任务, 实验ID={state.experiment_id}.")
        manager.cancel_task(state.experiment_id)
        state.task_pause_sent = False
        state.add_log("合成工站取消请求已下发.")
    except Exception as exc:
        logger.exception("取消合成工站任务失败, workflow_id=%s", state.workflow_id)
        state.add_log(f"取消合成工站任务失败: {exc}.")


def _abort_running_analysis(state: WorkflowRunState) -> None:
    """
    功能:
        对正在运行的智达分析任务下发终止命令.
    参数:
        state: WorkflowRunState, 工作流状态.
    返回:
        None.
    """
    client = None
    try:
        from unilabos.devices.eit_analysis_station.driver.zhida_driver import ZhidaClient

        state.add_log("正在终止分析仪器任务.")
        client = ZhidaClient()
        client.connect()
        result = client.abort()
        state.add_log(f"分析仪器终止请求已下发: {result}.")
    except Exception as exc:
        logger.exception("终止分析仪器任务失败, workflow_id=%s", state.workflow_id)
        state.add_log(f"终止分析仪器任务失败: {exc}.")
    finally:
        if client is not None:
            try:
                client.close()
            except Exception as exc:
                logger.warning("关闭分析仪器连接失败, workflow_id=%s, err=%s", state.workflow_id, exc)


def _stop_agv_arm_operation(state: WorkflowRunState) -> None:
    """
    功能:
        对 AGV 转运动作涉及的机械臂下发停止全部任务命令.
    参数:
        state: WorkflowRunState, 工作流状态.
    返回:
        None.
    """
    agv_controller = None
    try:
        from unilabos.devices.eit_agv.controller.agv_controller import AGVController

        state.add_log("正在停止 AGV 机械臂任务.")
        agv_controller = AGVController(timeout=5000)
        if agv_controller.connect() is False:
            raise RuntimeError("AGV 机械臂连接失败")
        result = agv_controller.arm.stop(block=False)
        state.add_log(f"AGV 机械臂停止请求已下发: {result}.")
    except Exception as exc:
        logger.exception("停止 AGV 机械臂任务失败, workflow_id=%s", state.workflow_id)
        state.add_log(f"停止 AGV 机械臂任务失败: {exc}.")
    finally:
        if agv_controller is not None:
            try:
                agv_controller.disconnect()
            except Exception as exc:
                logger.warning("断开 AGV 机械臂连接失败, workflow_id=%s, err=%s", state.workflow_id, exc)


def _attach_workflow_loggers(log_fn: Callable[[str], None]) -> List[tuple[logging.Logger, _WorkflowLogBridge]]:
    """
    功能:
        将底层关键 logger 桥接到工作流日志.
    参数:
        log_fn: Callable, 工作流日志函数.
    返回:
        List[tuple[logging.Logger, _WorkflowLogBridge]], 已挂载的 logger 与 handler.
    """
    logger_names = [
        "SynthesisStationManager",
        "StationManager",
        "unilabos.devices.eit_synthesis_station.controller.station_controller",
        "eit_synthesis_station.controller.station_controller",
        "unilabos.devices.eit_agv.controller.agv_controller",
        "eit_agv.controller.agv_controller",
        "unilabos.devices.eit_analysis_station.controller.analysis_controller",
        "eit_analysis_station.controller.analysis_controller",
    ]
    bridges: List[tuple[logging.Logger, _WorkflowLogBridge]] = []
    for logger_name in logger_names:
        target_logger = logging.getLogger(logger_name)
        bridge = _WorkflowLogBridge(log_fn)
        target_logger.addHandler(bridge)
        bridges.append((target_logger, bridge))
    return bridges


def _detach_workflow_loggers(bridges: List[tuple[logging.Logger, _WorkflowLogBridge]]) -> None:
    """
    功能:
        移除工作流日志桥接 handler.
    参数:
        bridges: List[tuple[logging.Logger, _WorkflowLogBridge]], 已挂载桥接列表.
    返回:
        None.
    """
    for target_logger, bridge in bridges:
        target_logger.removeHandler(bridge)


def _workflow_to_jsonable(value: Any) -> Any:
    """
    功能:
        将工作流结果转换为 JSON 兼容结构.
    参数:
        value: Any, 原始结果.
    返回:
        Any, JSON 兼容值.
    """
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return f"<bytes length={len(value)}>"
    if isinstance(value, dict):
        return {str(key): _workflow_to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_workflow_to_jsonable(item) for item in value]
    return str(value)


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


def _list_reaction_template_history(query_text: Optional[str] = None) -> List[JsonDict]:
    """
    功能:
        扫描任务目录并返回可读取的历史实验模板摘要.
    参数:
        query_text: Optional[str], 实验名称搜索关键词.
    返回:
        List[Dict[str, Any]], 历史模板摘要列表.
    """
    tasks_dir = Path(DEFAULT_HISTORY_TASKS_DIR)
    if tasks_dir.is_dir() is False:
        return []

    normalized_query = "" if query_text is None else str(query_text).strip().lower()
    task_dirs = [item for item in tasks_dir.iterdir() if item.is_dir() is True]
    task_dirs.sort(key=_history_task_sort_key, reverse=True)

    result: List[JsonDict] = []
    for task_dir in task_dirs:
        task_id_text = task_dir.name.strip()
        if task_id_text == "":
            continue

        try:
            task_id = int(task_id_text)
        except ValueError:
            continue

        try:
            template_path = _find_history_reaction_template_path(task_id)
            template = read_reaction_template(template_path)
        except FileNotFoundError:
            continue
        except Exception as exc:
            logger.warning("跳过不可读取的历史实验模板, task_id=%s, err=%s", task_id, exc)
            continue

        result.append(
            _build_history_template_summary(
                task_id=task_id,
                task_name=str(template.get("params", {}).get("实验名称", "")).strip(),
                experiment_count=len(template.get("rows", [])),
                normalized_query=normalized_query,
            )
        )

    return [item for item in result if item is not None]


def _build_history_template_summary(
    task_id: int,
    task_name: str,
    experiment_count: int,
    normalized_query: str,
) -> Optional[JsonDict]:
    """
    功能:
        构造历史实验模板摘要, 并按实验名称执行模糊筛选.
    参数:
        task_id: int, 任务 ID.
        task_name: str, 实验名称.
        experiment_count: int, 实验个数.
        normalized_query: str, 已规范化的小写搜索关键词.
    返回:
        Optional[Dict[str, Any]], 命中筛选时返回摘要, 否则返回 None.
    """
    if normalized_query != "" and normalized_query not in task_name.lower():
        return None
    return {
        "task_id": task_id,
        "task_name": task_name,
        "experiment_count": experiment_count,
    }


def _history_task_sort_key(task_dir: Path) -> tuple[int, float]:
    """
    功能:
        生成历史任务目录排序键, 优先按数字任务 ID 倒序.
    参数:
        task_dir: Path, 任务目录路径.
    返回:
        tuple[int, float], 排序键.
    """
    try:
        return int(task_dir.name), task_dir.stat().st_mtime
    except ValueError:
        return -1, task_dir.stat().st_mtime


def _find_history_reaction_template_path(task_id: int) -> Path:
    """
    功能:
        定位历史任务目录中的实验模板文件.
    参数:
        task_id: int, 任务 ID.
    返回:
        Path, 历史模板文件路径.
    """
    task_dir = Path(DEFAULT_HISTORY_TASKS_DIR) / str(task_id)
    if task_dir.is_dir() is False:
        raise FileNotFoundError(f"未找到历史任务目录: {task_dir}")

    preferred_paths = [
        task_dir / f"{task_id}_experiment_plan.xlsx",
        task_dir / f"{task_id}.xlsx",
    ]
    for path in preferred_paths:
        if path.is_file() is True:
            return path

    plan_candidates = sorted(task_dir.glob("*_experiment_plan.xlsx"))
    if len(plan_candidates) > 0:
        return plan_candidates[0]

    generic_candidates = [
        path
        for path in sorted(task_dir.glob("*.xlsx"))
        if path.name.endswith("_integration_report.xlsx") is False
        and path.name.endswith("_yield_report.xlsx") is False
        and path.name.endswith("_task_report.xlsx") is False
    ]
    if len(generic_candidates) > 0:
        return generic_candidates[0]

    raise FileNotFoundError(f"任务 {task_id} 未找到可读取的历史实验模板文件")


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
