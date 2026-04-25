# -*- coding: utf-8 -*-
"""
功能:
    提供 AGV 工站 Web API, 将前端请求转换为 AGVController 调用.
    包含连接/状态/导航/微调/充电/校准/货架六大分节.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from unilabos.devices.eit_agv.config.agv_config import STATION_POSITIONS
from unilabos.devices.eit_agv.utils.position_manager import PositionManager

from ..deps import (
    get_agv_context,
    get_battery_sampler_service,
    get_charge_loop_service,
)
from ..jobs import JobBusyError, job_manager
from ..services.agv_context import AgvContext
from ..services.battery_sampler import BatterySamplerService
from ..services.charge_loop import ChargeLoopService
from ..services.station_map import build_map_payload, save_station_layout

logger = logging.getLogger("EITHubAgvRouter")

JsonDict = Dict[str, Any]

router = APIRouter(prefix="/api/agv", tags=["agv"])


# ==================== 通用工具 ====================


def _job_response(job_id: str) -> JsonDict:
    """
    功能:
        生成后台任务创建响应.
    参数:
        job_id: str, 后台任务 ID.
    返回:
        Dict[str, Any], 响应体.
    """
    return {"job_id": job_id, "status": "queued"}


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


def _require_chassis(context: AgvContext) -> None:
    """
    功能:
        校验 AGV 底盘已连接, 未连接时抛出 409.
    参数:
        context: AgvContext, AGV 上下文.
    返回:
        None.
    """
    if context.is_chassis_connected() is False:
        raise _json_error("AGV 底盘未连接, 请先点击连接底盘按钮.", status.HTTP_409_CONFLICT)


def _require_arm(context: AgvContext) -> None:
    """
    功能:
        校验机械臂已连接, 未连接时抛出 409.
    参数:
        context: AgvContext, AGV 上下文.
    返回:
        None.
    """
    if context.is_arm_connected() is False:
        raise _json_error("机械臂未连接, 请先点击连接机械臂按钮.", status.HTTP_409_CONFLICT)


def _safe_call(loader: Callable[[], Any]) -> Any:
    """
    功能:
        执行数据查询并捕获异常, 失败时返回 None 便于仪表盘降级展示.
    参数:
        loader: Callable, 数据读取函数.
    返回:
        Any, 成功返回数据, 失败返回 None.
    """
    try:
        return loader()
    except Exception as exc:
        logger.debug("AGV 状态查询失败, 字段降级为 None: %s", exc)
        return None


def _empty_arm_state() -> JsonDict:
    """
    功能:
        生成机械臂可执行动作判断的空状态.
    返回:
        Dict[str, Any], 包含 drive_ready/quick_change_locked/gripper_open.
    """
    return {
        "drive_ready": None,
        "quick_change_locked": None,
        "gripper_open": None,
    }


def _bool_or_none(value: Any) -> Optional[bool]:
    """
    功能:
        将底层布尔值统一转换为 Optional[bool].
    参数:
        value: Any, 底层接口返回值.
    返回:
        Optional[bool], 可判断时返回 bool, 否则返回 None.
    """
    if isinstance(value, bool) is False:
        return None
    return value


def _derive_drive_ready(robot_status: Any) -> Optional[bool]:
    """
    功能:
        从 Duco RobotStatus 中判断机械臂驱动是否就绪.
    参数:
        robot_status: Any, 底层 RobotStatus 对象.
    返回:
        Optional[bool], True 表示所有从站就绪, False 表示存在未就绪, None 表示无法判断.
    """
    slave_ready = getattr(robot_status, "slaveReady", None)
    if isinstance(slave_ready, list) is False:
        return None
    if len(slave_ready) == 0:
        return None
    for ready in slave_ready:
        if ready is not True:
            return False
    return True


def _build_arm_state(controller: Any) -> JsonDict:
    """
    功能:
        汇总机械臂当前可执行动作状态, 供前端只展示当前可执行的配对动作.
    参数:
        controller: Any, AGVController 实例.
    返回:
        Dict[str, Any], 包含 drive_ready/quick_change_locked/gripper_open.
    """
    quick_change_output = _safe_call(lambda: controller.arm.get_digital_output(1))
    gripper_output = _safe_call(lambda: controller.arm.get_digital_output(2))
    return {
        "drive_ready": _derive_drive_ready(_safe_call(controller.arm.get_robot_status)),
        "quick_change_locked": None if _bool_or_none(quick_change_output) is None else quick_change_output is False,
        "gripper_open": _bool_or_none(gripper_output),
    }


def _add_current_station(payload: JsonDict, context: AgvContext) -> JsonDict:
    """
    功能:
        给地图 payload 添加当前 AGV 工站 ID.
    参数:
        payload: Dict[str, Any], 地图响应体.
        context: AgvContext, AGV 上下文.
    返回:
        Dict[str, Any], 带 current_station_id 的地图响应体.
    """
    current_station_id: Optional[str] = None
    if context.is_chassis_connected() is True:
        station = _safe_call(context.get_or_create().query_current_station)
        if isinstance(station, dict) is True:
            current_station_id = station.get("station_id")
    payload["current_station_id"] = current_station_id
    return payload


def _build_tray_options(station_id: Optional[str]) -> List[JsonDict]:
    """
    功能:
        按当前工站筛选可用于物料转移的托盘点位, 同时保留 AGV 自身点位.
    参数:
        station_id: Optional[str], 当前工站 ID.
    返回:
        List[Dict[str, Any]], 可选点位列表.
    """
    tray_positions = PositionManager().get_category("tray_position")
    if tray_positions is None:
        raise ValueError("未找到托盘位置配置.")

    normalized_station_id = station_id.strip().upper() if station_id is not None else None
    station_name = None
    if normalized_station_id is not None and (normalized_station_id in STATION_POSITIONS) is True:
        station_name = STATION_POSITIONS[normalized_station_id]["name"]

    options: List[JsonDict] = []
    for tray_name, tray_meta in tray_positions.items():
        is_agv_tray = tray_name.startswith("agv")
        is_current_station_tray = station_name is not None and tray_name.startswith(station_name)
        if is_agv_tray is False and is_current_station_tray is False:
            continue
        options.append(
            {
                "name": tray_name,
                "label": tray_name,
                "description": tray_meta.get("description", ""),
                "station_id": normalized_station_id if is_current_station_tray is True else None,
                "station_name": station_name if is_current_station_tray is True else None,
            }
        )

    if len(options) == 0:
        raise ValueError("当前工站没有可用的托盘位置.")
    return options


# ==================== 请求模型 ====================


class NavigateRequest(BaseModel):
    """
    功能:
        AGV 导航请求.
    参数:
        station_id: str, 目标工站 ID, 例如 "LM1".
    """

    station_id: str = Field(..., min_length=1)


class MapLayoutStationItem(BaseModel):
    """
    功能:
        工站地图坐标保存项.
    参数:
        id: str, 工站 ID.
        x: float, 横向百分比坐标, 范围 0 到 100.
        y: float, 纵向百分比坐标, 范围 0 到 100.
    """

    id: str = Field(..., min_length=1)
    x: float = Field(..., ge=0.0, le=100.0)
    y: float = Field(..., ge=0.0, le=100.0)


class MapLayoutSaveRequest(BaseModel):
    """
    功能:
        工站地图布局保存请求.
    参数:
        stations: List[MapLayoutStationItem], 工站坐标列表.
    """

    stations: List[MapLayoutStationItem]


class TransferRequest(BaseModel):
    """
    功能:
        单次物料转移请求.
    参数:
        source_tray: str, 源托盘名称.
        target_tray: str, 目标托盘名称.
        material_type: Optional[str], 物料类型, 用于自适应 Z 偏移.
    """

    source_tray: str = Field(..., min_length=1)
    target_tray: str = Field(..., min_length=1)
    material_type: Optional[str] = None


class BatchTransferTaskItem(BaseModel):
    """
    功能:
        批量物料转运中的单项任务.
    参数:
        source_tray: str, 源托盘名称.
        target_tray: str, 目标托盘名称.
        material_type: Optional[str], 物料类型.
    """

    source_tray: str
    target_tray: str
    material_type: Optional[str] = None


class BatchTransferRequest(BaseModel):
    """
    功能:
        批量物料转运请求.
    参数:
        tasks: List[BatchTransferTaskItem], 批量任务列表.
    """

    tasks: List[BatchTransferTaskItem]


class QuickChangeRequest(BaseModel):
    """
    功能:
        快换控制请求.
    参数:
        action: str, 动作, "lock" 或 "release".
    """

    action: str


class GripperRequest(BaseModel):
    """
    功能:
        夹爪控制请求.
    参数:
        action: str, 动作, "open" 或 "close".
    """

    action: str


class ChargingStartRequest(BaseModel):
    """
    功能:
        启动充电循环请求.
    参数:
        standby: str, 待命点, "CP6" 或 "PP5".
        interval_minutes: int, 正常检查间隔分钟.
        retry_wait_minutes: int, 异常重试等待分钟.
        low_battery_pct: int, 低电量阈值 0-100.
    """

    standby: str = "PP5"
    interval_minutes: int = 30
    retry_wait_minutes: int = 5
    low_battery_pct: int = 50


class TrayNameRequest(BaseModel):
    """
    功能:
        仅包含托盘名称的请求.
    参数:
        tray_name: str, 托盘名称.
    """

    tray_name: str = Field(..., min_length=1)


class LoadedTrayPrepareRequest(BaseModel):
    """
    功能:
        带托盘校准准备请求.
    参数:
        target_tray: str, 目标托盘名称.
        source_tray: str, 源托盘名称.
    """

    target_tray: str = Field(..., min_length=1)
    source_tray: str = "agv_tray_1"


class StationNameRequest(BaseModel):
    """
    功能:
        工站名称请求.
    参数:
        station_name: str, 工站名称.
    """

    station_name: str = Field(..., min_length=1)


class ShelfSlotRequest(BaseModel):
    """
    功能:
        货架槽位操作请求.
    参数:
        slot_name: str, 槽位名称, 例如 "shelf_tray_1-1".
    """

    slot_name: str = Field(..., min_length=1)


class ShelfPlaceRequest(BaseModel):
    """
    功能:
        在货架槽位手动登记物料的请求.
    参数:
        slot_name: str, 槽位名称.
        material_type: str, 物料类型.
        source: str, 来源.
        description: str, 描述.
    """

    slot_name: str = Field(..., min_length=1)
    material_type: str = Field(..., min_length=1)
    source: str = ""
    description: str = ""


class ShelfResetRequest(BaseModel):
    """
    功能:
        清空货架确认请求.
    参数:
        confirm: bool, 必须为 True 才执行.
    """

    confirm: bool = False


# ==================== 分节 A: 基础状态与连接 ====================


@router.get("/status")
def get_status(
    context: AgvContext = Depends(get_agv_context),
    sampler: BatterySamplerService = Depends(get_battery_sampler_service),
    charger: ChargeLoopService = Depends(get_charge_loop_service),
) -> JsonDict:
    """
    功能:
        返回 AGV 综合状态快照. 底盘或机械臂未连接时, 对应字段以 None 降级.
    返回:
        Dict[str, Any], 包含 connections/station/battery/nav_task/slots/gripper/poses 等.
    """
    connections = context.status_snapshot()
    result: JsonDict = {
        "connections": connections,
        "station": None,
        "battery": None,
        "battery_latest": sampler.get_latest(),
        "nav_task": None,
        "slots": None,
        "gripper_state": None,
        "current_gripper": None,
        "tcp_pose": None,
        "joints": None,
        "is_moving": None,
        "arm_state": _empty_arm_state(),
        "charge_loop": charger.status(),
    }

    if connections.get("chassis_connected") is True:
        controller = context.get_or_create()
        result["station"] = _safe_call(controller.query_current_station)
        result["battery"] = _safe_call(lambda: controller.query_battery_status(simple=False))
        result["nav_task"] = _safe_call(controller.query_nav_task_status)

    if connections.get("arm_connected") is True:
        controller = context.get_or_create()
        # 机械臂 Thrift 非线程安全, 获取锁后再串行查询, 避免与 Job 线程冲突
        if context.arm_lock.acquire(timeout=0.5) is True:
            try:
                result["slots"] = _safe_call(controller.arm.get_all_slots_status)
                result["gripper_state"] = _safe_call(controller.arm.get_gripper_state)
                result["current_gripper"] = _safe_call(controller.arm.get_current_gripper)
                result["tcp_pose"] = _safe_call(controller.arm.get_tcp_pose)
                result["joints"] = _safe_call(controller.arm.get_joints_position)
                result["is_moving"] = _safe_call(controller.arm.is_moving)
                result["arm_state"] = _build_arm_state(controller)
            finally:
                context.arm_lock.release()
        # 锁超时则跳过, 本轮保留上次值为 None, 下一轮轮询继续尝试

    return result


@router.get("/map")
def get_station_map(context: AgvContext = Depends(get_agv_context)) -> JsonDict:
    """
    功能:
        返回 AGV 工站地图布局和当前站点.
    返回:
        Dict[str, Any], 包含 stations 列表和 current_station_id.
    """
    payload = build_map_payload()
    return _add_current_station(payload, context)


@router.post("/map/layout")
def save_station_map_layout(
    request: MapLayoutSaveRequest,
    context: AgvContext = Depends(get_agv_context),
) -> JsonDict:
    """
    功能:
        保存 AGV 工站地图相对布局坐标.
    参数:
        request: MapLayoutSaveRequest, 工站地图布局保存请求.
        context: AgvContext, AGV 上下文.
    返回:
        Dict[str, Any], 更新后的地图 payload.
    """
    try:
        payload = save_station_layout([item.model_dump() for item in request.stations])
    except ValueError as exc:
        raise _json_error(str(exc)) from exc
    return _add_current_station(payload, context)


@router.post("/chassis/connect")
def connect_chassis(context: AgvContext = Depends(get_agv_context)) -> JsonDict:
    """
    功能:
        连接 AGV 底盘查询端口与导航端口.
    返回:
        Dict[str, Any], 包含 chassis_connected 状态.
    """
    try:
        context.connect_chassis()
    except Exception as exc:
        raise _json_error(f"AGV 底盘连接失败: {exc}", status.HTTP_500_INTERNAL_SERVER_ERROR) from exc
    return context.status_snapshot()


@router.post("/chassis/disconnect")
def disconnect_chassis(context: AgvContext = Depends(get_agv_context)) -> JsonDict:
    """
    功能:
        断开 AGV 底盘连接.
    返回:
        Dict[str, Any], 连接状态.
    """
    context.disconnect_chassis()
    return context.status_snapshot()


@router.post("/arm/connect")
def connect_arm(context: AgvContext = Depends(get_agv_context)) -> JsonDict:
    """
    功能:
        连接机械臂.
    返回:
        Dict[str, Any], 连接状态.
    """
    try:
        context.connect_arm()
    except Exception as exc:
        raise _json_error(f"机械臂连接失败: {exc}", status.HTTP_500_INTERNAL_SERVER_ERROR) from exc
    return context.status_snapshot()


@router.post("/arm/disconnect")
def disconnect_arm(context: AgvContext = Depends(get_agv_context)) -> JsonDict:
    """
    功能:
        断开机械臂连接.
    返回:
        Dict[str, Any], 连接状态.
    """
    context.disconnect_arm()
    return context.status_snapshot()


@router.post("/arm/power-on")
def arm_power_on(context: AgvContext = Depends(get_agv_context)) -> JsonDict:
    """
    功能:
        机械臂上电并上使能 (Job 任务).
    返回:
        Dict[str, Any], Job ID.
    """
    _require_arm(context)

    def _target(log: Callable[[str], None]) -> Any:
        log("开始机械臂上电.")
        controller = context.get_or_create()
        with context.arm_lock:
            controller.arm.power_on(block=True)
            log("上电完成, 准备上使能.")
            controller.arm.enable(block=True)
        log("使能完成.")
        return {"ok": True}

    return _start_job("机械臂上电", _target)


@router.post("/arm/power-off")
def arm_power_off(context: AgvContext = Depends(get_agv_context)) -> JsonDict:
    """
    功能:
        机械臂下使能并下电 (Job 任务).
    返回:
        Dict[str, Any], Job ID.
    """
    _require_arm(context)

    def _target(log: Callable[[str], None]) -> Any:
        log("开始机械臂下使能.")
        controller = context.get_or_create()
        with context.arm_lock:
            controller.arm.disable(block=True)
            log("下使能完成, 准备下电.")
            controller.arm.power_off(block=True)
        log("下电完成.")
        return {"ok": True}

    return _start_job("机械臂下电", _target)


@router.post("/arm/home")
def arm_home(context: AgvContext = Depends(get_agv_context)) -> JsonDict:
    """
    功能:
        机械臂回零 (Job 任务).
    返回:
        Dict[str, Any], Job ID.
    """
    _require_arm(context)

    def _target(log: Callable[[str], None]) -> Any:
        log("开始机械臂回零.")
        with context.arm_lock:
            result = context.get_or_create().arm_go_home(block=True)
        log(f"回零完成, 结果={result}.")
        return {"ok": bool(result)}

    return _start_job("机械臂回零", _target)


@router.post("/arm/stop")
def arm_stop(context: AgvContext = Depends(get_agv_context)) -> JsonDict:
    """
    功能:
        立即停止机械臂当前运动. 同步执行, 不占 Job 槽.
    返回:
        Dict[str, Any], 执行结果.
    """
    _require_arm(context)
    # 立即停止是紧急操作, 不等锁; 底层 Thrift stop 会打断正在进行的运动
    try:
        context.get_or_create().arm.stop(block=False)
    except Exception as exc:
        raise _json_error(f"停止机械臂失败: {exc}", status.HTTP_500_INTERNAL_SERVER_ERROR) from exc
    return {"ok": True}


@router.post("/arm/quick-change")
def arm_quick_change(
    request: QuickChangeRequest,
    context: AgvContext = Depends(get_agv_context),
) -> JsonDict:
    """
    功能:
        快换动作控制 (Job 任务).
    参数:
        request: QuickChangeRequest, 快换请求.
    返回:
        Dict[str, Any], Job ID.
    """
    _require_arm(context)
    action = request.action.lower().strip()
    if action not in ("lock", "release"):
        raise _json_error("快换动作必须是 lock 或 release.")

    label = "夹紧快换" if action == "lock" else "松开快换"

    def _target(log: Callable[[str], None]) -> Any:
        log(f"执行: {label}.")
        arm = context.get_or_create().arm
        with context.arm_lock:
            if action == "lock":
                arm.lock_quick_change(block=True)
            else:
                arm.release_quick_change(block=True)
        log("快换动作完成.")
        return {"ok": True}

    return _start_job(label, _target)


@router.post("/arm/gripper")
def arm_gripper(
    request: GripperRequest,
    context: AgvContext = Depends(get_agv_context),
) -> JsonDict:
    """
    功能:
        夹爪动作控制 (Job 任务).
    参数:
        request: GripperRequest, 夹爪请求.
    返回:
        Dict[str, Any], Job ID.
    """
    _require_arm(context)
    action = request.action.lower().strip()
    if action not in ("open", "close"):
        raise _json_error("夹爪动作必须是 open 或 close.")

    label = "张开夹爪" if action == "open" else "闭合夹爪"

    def _target(log: Callable[[str], None]) -> Any:
        log(f"执行: {label}.")
        arm = context.get_or_create().arm
        with context.arm_lock:
            if action == "open":
                arm.open_gripper(block=True)
            else:
                arm.close_gripper(block=True)
        log("夹爪动作完成.")
        return {"ok": True}

    return _start_job(label, _target)


# ==================== 分节 B: 导航与转运 ====================


@router.get("/tray-options")
def get_tray_options(
    station_id: Optional[str] = Query(default=None),
) -> JsonDict:
    """
    功能:
        返回当前工站可用于物料转移的托盘点位选项.
    参数:
        station_id: Optional[str], 当前工站 ID, 未识别时只返回 AGV 自身点位.
    返回:
        Dict[str, Any], 包含 station_id 与 options.
    """
    normalized_station_id = station_id.strip().upper() if station_id is not None else None
    try:
        options = _build_tray_options(normalized_station_id)
    except ValueError as exc:
        raise _json_error(str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR) from exc
    return {"station_id": normalized_station_id, "options": options}


@router.post("/navigate")
def navigate(
    request: NavigateRequest,
    context: AgvContext = Depends(get_agv_context),
) -> JsonDict:
    """
    功能:
        AGV 安全导航到目标工站 (先回零机械臂, 然后发送导航指令, Job 任务).
    参数:
        request: NavigateRequest, 导航请求.
    返回:
        Dict[str, Any], Job ID.
    """
    _require_chassis(context)
    station_id = request.station_id.strip().upper()

    def _target(log: Callable[[str], None]) -> Any:
        log(f"准备导航到工站 {station_id}.")
        # 导航内部包含机械臂回零, 必须持有 arm_lock 避免与状态查询冲突
        with context.arm_lock:
            result = context.get_or_create().safe_navigate_to_station(station_id)
        log(f"导航任务完成, 结果={result}.")
        return {"result": result}

    return _start_job(f"AGV 导航到 {station_id}", _target)


@router.post("/transfer")
def transfer(
    request: TransferRequest,
    context: AgvContext = Depends(get_agv_context),
) -> JsonDict:
    """
    功能:
        单次物料转移 (取-放, Job 任务).
    参数:
        request: TransferRequest, 转移请求.
    返回:
        Dict[str, Any], Job ID.
    """
    _require_arm(context)

    def _target(log: Callable[[str], None]) -> Any:
        log(f"开始转移物料: {request.source_tray} → {request.target_tray}.")
        with context.arm_lock:
            result = context.get_or_create().transfer_material(
                request.source_tray,
                request.target_tray,
                material_type=request.material_type,
                block=True,
            )
        log(f"转移完成, result={result}.")
        return {"ok": bool(result)}

    return _start_job("单次物料转移", _target)


@router.post("/batch-transfer")
def batch_transfer(
    request: BatchTransferRequest,
    context: AgvContext = Depends(get_agv_context),
) -> JsonDict:
    """
    功能:
        批量物料转运 (包含 AGV 导航, Job 任务).
    参数:
        request: BatchTransferRequest, 批量转运请求.
    返回:
        Dict[str, Any], Job ID.
    """
    _require_chassis(context)
    _require_arm(context)
    if len(request.tasks) == 0:
        raise _json_error("批量转运任务列表为空.")

    tasks_payload = [item.model_dump() for item in request.tasks]

    def _target(log: Callable[[str], None]) -> Any:
        log(f"开始批量转运, 任务数={len(tasks_payload)}.")
        with context.arm_lock:
            result = context.get_or_create().batch_transfer_materials(tasks_payload, block=True)
        log(f"批量转运完成, result={result}.")
        return {"ok": bool(result)}

    return _start_job("批量物料转运", _target)


# ==================== 分节 C: 机械臂 WebSocket 端点 ====================


@router.get("/arm/duco-ws-endpoint")
def arm_duco_ws_endpoint() -> JsonDict:
    """
    功能:
        返回 Duco 机械臂原生 WebSocket 控制端点, 供前端直接建立连接
        复刻官方 movement 页面的 moveJog/stopManualMove 控制语义.
        端口 7000 是 Duco Web UI + WebSocket 的共用端口, 与 Thrift 的 7003 不同.
    返回:
        Dict[str, Any], 含 ws_url 字段, 形如 "ws://192.168.1.10:7000".
    """
    from unilabos.devices.eit_agv.config.arm_config import ARM_HOST

    return {"ws_url": f"ws://{ARM_HOST}:7000"}


# ==================== 分节 D: 充电管理 ====================


@router.get("/charging/status")
def charging_status(
    charger: ChargeLoopService = Depends(get_charge_loop_service),
) -> JsonDict:
    """
    功能:
        返回充电循环服务状态.
    返回:
        Dict[str, Any], 服务状态.
    """
    return charger.status()


@router.post("/charging/start")
def charging_start(
    request: ChargingStartRequest,
    context: AgvContext = Depends(get_agv_context),
    charger: ChargeLoopService = Depends(get_charge_loop_service),
) -> JsonDict:
    """
    功能:
        启动充电循环.
    参数:
        request: ChargingStartRequest, 启动请求.
    返回:
        Dict[str, Any], 启动后的服务状态.
    """
    _require_chassis(context)
    try:
        return charger.start(
            standby=request.standby,
            interval_minutes=request.interval_minutes,
            retry_wait_minutes=request.retry_wait_minutes,
            low_battery_pct=request.low_battery_pct,
        )
    except RuntimeError as exc:
        raise _json_error(str(exc), status.HTTP_409_CONFLICT) from exc


@router.post("/charging/stop")
def charging_stop(
    charger: ChargeLoopService = Depends(get_charge_loop_service),
) -> JsonDict:
    """
    功能:
        停止充电循环.
    返回:
        Dict[str, Any], 停止后的服务状态.
    """
    return charger.stop()


@router.post("/charging/check-once")
def charging_check_once(
    request: ChargingStartRequest = Body(default_factory=ChargingStartRequest),
    context: AgvContext = Depends(get_agv_context),
) -> JsonDict:
    """
    功能:
        手动执行一次充电检查 (Job 任务), 不启动循环.
    参数:
        request: ChargingStartRequest, 复用启动结构, 仅使用 low_battery_pct.
    返回:
        Dict[str, Any], Job ID.
    """
    _require_chassis(context)

    def _target(log: Callable[[str], None]) -> Any:
        log(f"执行单次充电检查, 阈值={request.low_battery_pct}%.")
        # 充电检查内部可能触发导航+回零, 持锁执行
        with context.arm_lock:
            result = context.get_or_create().auto_charge_pp5_cp6_check(
                low_battery_pct=request.low_battery_pct
            )
        log(f"检查完成, 结果={result}.")
        return result

    return _start_job("单次充电检查", _target)


@router.get("/battery/history")
def battery_history(
    hours: float = Query(default=6.0, ge=0.0, le=168.0),
    sampler: BatterySamplerService = Depends(get_battery_sampler_service),
) -> JsonDict:
    """
    功能:
        返回指定小时数内的电量历史采样.
    参数:
        hours: float, 查询窗口小时数, 默认 6.
    返回:
        Dict[str, Any], 包含 hours 和 records 列表.
    """
    records = sampler.get_history(hours=hours)
    return {"hours": hours, "records": records}


# ==================== 分节 E: 校准 ====================


@router.post("/calibration/station")
def calibration_station(context: AgvContext = Depends(get_agv_context)) -> JsonDict:
    """
    功能:
        执行工站点位校准 (Job 任务). 校准过程会调用机械臂的 run_program 运行示教,
        然后读取系统变量计算偏移并保存.
    返回:
        Dict[str, Any], Job ID.
    """
    _require_chassis(context)
    _require_arm(context)

    def _target(log: Callable[[str], None]) -> Any:
        log("开始工站点位校准.")
        with context.arm_lock:
            result = context.get_or_create().calibrate_station(block=True)
        log(f"工站点位校准完成, 结果={result}.")
        return result

    return _start_job("工站点位校准", _target)


@router.post("/calibration/tray")
def calibration_tray(
    request: TrayNameRequest,
    context: AgvContext = Depends(get_agv_context),
) -> JsonDict:
    """
    功能:
        执行托盘点位校准 (Job 任务).
    参数:
        request: TrayNameRequest, 托盘名称请求.
    返回:
        Dict[str, Any], Job ID.
    """
    _require_arm(context)

    def _target(log: Callable[[str], None]) -> Any:
        log(f"开始托盘点位校准: {request.tray_name}.")
        with context.arm_lock:
            result = context.get_or_create().calibrate_tray_position(request.tray_name, block=True)
        log(f"托盘校准完成, 结果={result}.")
        return {"ok": bool(result)}

    return _start_job(f"托盘点位校准 {request.tray_name}", _target)


@router.post("/calibration/station-offset")
def calibration_station_offset(context: AgvContext = Depends(get_agv_context)) -> JsonDict:
    """
    功能:
        执行工站整体偏差矫正 (Job 任务).
    返回:
        Dict[str, Any], Job ID.
    """
    _require_chassis(context)
    _require_arm(context)

    def _target(log: Callable[[str], None]) -> Any:
        log("开始工站整体偏差矫正.")
        with context.arm_lock:
            result = context.get_or_create().calibrate_station_offset(block=True)
        log(f"矫正完成, 结果={result}.")
        return result

    return _start_job("工站整体偏差矫正", _target)


@router.post("/calibration/loaded-tray/prepare")
def calibration_loaded_tray_prepare(
    request: LoadedTrayPrepareRequest,
    context: AgvContext = Depends(get_agv_context),
) -> JsonDict:
    """
    功能:
        带托盘校准准备流程: 从源托盘取托盘 → 运动到目标托盘过渡点.
    参数:
        request: LoadedTrayPrepareRequest, 准备请求.
    返回:
        Dict[str, Any], Job ID.
    """
    _require_arm(context)

    def _target(log: Callable[[str], None]) -> Any:
        log(f"开始带托盘校准准备: source={request.source_tray}, target={request.target_tray}.")
        with context.arm_lock:
            result = context.get_or_create().prepare_loaded_tray_calibration(
                request.target_tray, source_tray_name=request.source_tray, block=True
            )
        log("准备完成, 请手动调整机械臂至目标托盘位置, 完成后点击记录位姿.")
        return {"ok": bool(result)}

    return _start_job("带托盘校准准备", _target)


@router.post("/calibration/loaded-tray/record")
def calibration_loaded_tray_record(
    request: TrayNameRequest,
    context: AgvContext = Depends(get_agv_context),
) -> JsonDict:
    """
    功能:
        带托盘校准: 根据当前 TCP 位姿计算并保存托盘点位.
    参数:
        request: TrayNameRequest, 托盘名称请求.
    返回:
        Dict[str, Any], 包含保存的位姿.
    """
    _require_arm(context)
    try:
        with context.arm_lock:
            pose = context.get_or_create().get_calibrated_tray_pose_from_current_pose(request.tray_name)
    except Exception as exc:
        logger.exception("记录带托盘校准位姿失败")
        raise _json_error(str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR) from exc
    return {"tray_name": request.tray_name, "pose": pose}


@router.post("/calibration/loaded-tray/complete")
def calibration_loaded_tray_complete(
    request: TrayNameRequest,
    context: AgvContext = Depends(get_agv_context),
) -> JsonDict:
    """
    功能:
        带托盘校准收尾: 松开夹爪 → 回零 → 回到 safe 点.
    参数:
        request: TrayNameRequest, 托盘名称请求.
    返回:
        Dict[str, Any], Job ID.
    """
    _require_arm(context)

    def _target(log: Callable[[str], None]) -> Any:
        log(f"开始带托盘校准收尾: {request.tray_name}.")
        with context.arm_lock:
            result = context.get_or_create().complete_loaded_tray_calibration(
                request.tray_name, block=True
            )
        log("收尾完成.")
        return {"ok": bool(result)}

    return _start_job(f"带托盘校准收尾 {request.tray_name}", _target)


@router.get("/calibration/middle-tray/preview")
def calibration_middle_tray_preview(
    station: str = Query(..., min_length=1),
    context: AgvContext = Depends(get_agv_context),
) -> JsonDict:
    """
    功能:
        预览工站中间托盘的自动计算结果.
    参数:
        station: str, 工站名称.
    返回:
        Dict[str, Any], 包含 station_name 和 rows 列表.
    """
    try:
        rows = context.get_or_create().preview_station_middle_tray_updates(station)
    except Exception as exc:
        logger.exception("预览中间托盘失败")
        raise _json_error(str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR) from exc
    return {"station_name": station, "rows": rows}


@router.post("/calibration/middle-tray/apply")
def calibration_middle_tray_apply(
    request: StationNameRequest,
    context: AgvContext = Depends(get_agv_context),
) -> JsonDict:
    """
    功能:
        应用中间托盘计算结果到配置文件.
    参数:
        request: StationNameRequest, 工站名称请求.
    返回:
        Dict[str, Any], 应用统计信息.
    """
    try:
        result = context.get_or_create().apply_station_middle_tray_updates(request.station_name)
    except Exception as exc:
        logger.exception("应用中间托盘失败")
        raise _json_error(str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR) from exc
    return result


@router.post("/calibration/move-to-grasp")
def calibration_move_to_grasp(
    request: TrayNameRequest,
    context: AgvContext = Depends(get_agv_context),
) -> JsonDict:
    """
    功能:
        运动机械臂到指定托盘抓取点位 (Job 任务). 通常作为校准前置步骤.
    参数:
        request: TrayNameRequest, 托盘名称请求.
    返回:
        Dict[str, Any], Job ID.
    """
    _require_arm(context)

    def _target(log: Callable[[str], None]) -> Any:
        log(f"运动到抓取点位: {request.tray_name}.")
        with context.arm_lock:
            result = context.get_or_create().move_to_grasp_position(request.tray_name, block=True)
        log("运动完成.")
        return {"ok": bool(result)}

    return _start_job(f"移动到抓取点位 {request.tray_name}", _target)


# ==================== 分节 F: 货架 ====================


@router.get("/shelf/status")
def shelf_status(context: AgvContext = Depends(get_agv_context)) -> JsonDict:
    """
    功能:
        返回 12 个货架槽位的完整状态.
    返回:
        Dict[str, Any], 包含 last_updated 和 slots.
    """
    try:
        return context.get_or_create().shelf_manager.get_all_status()
    except Exception as exc:
        logger.exception("读取货架状态失败")
        raise _json_error(str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR) from exc


@router.post("/shelf/remove")
def shelf_remove(
    request: ShelfSlotRequest,
    context: AgvContext = Depends(get_agv_context),
) -> JsonDict:
    """
    功能:
        清空指定槽位.
    参数:
        request: ShelfSlotRequest, 槽位请求.
    返回:
        Dict[str, Any], 操作结果.
    """
    ok = context.get_or_create().shelf_manager.remove_material(request.slot_name)
    if ok is False:
        raise _json_error(f"槽位 {request.slot_name} 不存在或已为空.")
    return {"ok": True}


@router.post("/shelf/reset-all")
def shelf_reset_all(
    request: ShelfResetRequest,
    context: AgvContext = Depends(get_agv_context),
) -> JsonDict:
    """
    功能:
        清空全部货架槽位, 需要 confirm=true.
    参数:
        request: ShelfResetRequest, 确认请求.
    返回:
        Dict[str, Any], 操作结果.
    """
    if request.confirm is not True:
        raise _json_error("请传入 confirm=true 以确认清空全部货架.")
    context.get_or_create().shelf_manager.reset_all()
    return {"ok": True}


@router.post("/shelf/place")
def shelf_place(
    request: ShelfPlaceRequest,
    context: AgvContext = Depends(get_agv_context),
) -> JsonDict:
    """
    功能:
        手动在指定槽位登记物料.
    参数:
        request: ShelfPlaceRequest, 登记请求.
    返回:
        Dict[str, Any], 操作结果.
    """
    ok = context.get_or_create().shelf_manager.place_material(
        request.slot_name,
        request.material_type,
        request.source,
        description=request.description,
    )
    if ok is False:
        raise _json_error(f"槽位 {request.slot_name} 登记失败 (不存在或已被占用).")
    return {"ok": True}


# ==================== 分节 G: 任务轮询 ====================


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> JsonDict:
    """
    功能:
        查询后台任务状态. 复用全局 job_manager.
    参数:
        job_id: str, 后台任务 ID.
    返回:
        Dict[str, Any], 任务状态.
    """
    job = job_manager.get(job_id)
    if job is None:
        raise _json_error(f"未找到后台任务: {job_id}", status.HTTP_404_NOT_FOUND)
    return job.to_dict()
