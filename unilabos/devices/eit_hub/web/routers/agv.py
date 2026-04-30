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
from ..log_entry import level_from_record, source_from_record
from ..services.agv_context import AgvContext
from ..services.battery_sampler import BatterySamplerService
from ..services.charge_loop import ChargeLoopService
from ..services.station_map import build_map_payload, save_station_layout

logger = logging.getLogger("EITHubAgvRouter")

UI_LOGGER_NAME = "eit_hub.ui"

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


def _reload_positions(context: AgvContext) -> None:
    """
    功能:
        在执行点位相关动作前重新加载 yaml, 确保读取到最新的 arm_positions 配置.
    参数:
        context: AgvContext, AGV 上下文.
    返回:
        None.
    """
    try:
        context.get_or_create().position_manager.reload()
    except Exception as exc:
        logger.warning("点位配置 reload 失败: %s", exc)


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


def _build_arm_state(controller: Any, robot_status: Any) -> JsonDict:
    """
    功能:
        汇总机械臂当前可执行动作状态, 供前端只展示当前可执行的配对动作.
    参数:
        controller: Any, AGVController 实例.
        robot_status: Any, 已查询的底层 RobotStatus 对象, 复用避免重复 RPC.
    返回:
        Dict[str, Any], 包含 drive_ready/quick_change_locked/gripper_open.
    """
    quick_change_output = _safe_call(lambda: controller.arm.get_digital_output(1))
    gripper_output = _safe_call(lambda: controller.arm.get_digital_output(2))
    return {
        "drive_ready": _derive_drive_ready(robot_status),
        "quick_change_locked": None if _bool_or_none(quick_change_output) is None else quick_change_output is False,
        "gripper_open": _bool_or_none(gripper_output),
    }


def _build_collision_info(robot_status: Any) -> JsonDict:
    """
    功能:
        从 Duco RobotStatus 中提取碰撞检测状态, 供前端展示告警.
    参数:
        robot_status: Any, 底层 RobotStatus 对象, 为 None 时降级为未碰撞.
    返回:
        Dict[str, Any], 包含 active (bool, 是否处于碰撞) 和 axis (Optional[int], 触发碰撞的轴号).
    """
    if robot_status is None:
        return {"active": False, "axis": None}
    collision_flag = getattr(robot_status, "collision", None)
    collision_axis = getattr(robot_status, "collisionAxis", None)
    active = collision_flag is True
    axis = collision_axis if isinstance(collision_axis, int) else None
    return {"active": active, "axis": axis}


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
        interval_minutes: int, 正常检查间隔分钟.
        retry_wait_minutes: int, 异常重试等待分钟.
        low_battery_pct: int, 低电量阈值 0-100.
        full_battery_pct: int, 满电停充阈值, 必须大于 low_battery_pct, 上限 100.
    """

    interval_minutes: int = Field(default=30, ge=1, le=180)
    retry_wait_minutes: int = Field(default=5, ge=1, le=60)
    low_battery_pct: int = Field(default=50, ge=10, le=90)
    full_battery_pct: int = Field(default=95, ge=11, le=100)


class ChargeControlDoRequest(BaseModel):
    """
    功能:
        手动设置底盘 DO7 充电控制输出请求.
    参数:
        do_status: bool, True 表示打开 DO7 停止充电, False 表示关闭 DO7 允许充电.
    """

    do_status: bool


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


class MiddleTrayRowRequest(BaseModel):
    """
    功能:
        中间托盘按行计算请求.
    参数:
        station_name: str, 工站名称.
        row_index: int, 行号, 从1开始.
    """

    station_name: str = Field(..., min_length=1)
    row_index: int = Field(..., ge=1)


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


class TestTrayActionRequest(BaseModel):
    """
    功能:
        取/放托盘测试请求.
    参数:
        tray_name: str, 目标托盘名称.
        material_type: Optional[str], 物料类型, 决定夹爪与高度偏移; 为 None 时使用默认参数.
    """

    tray_name: str = Field(..., min_length=1)
    material_type: Optional[str] = None


class TraySaveRequest(BaseModel):
    """
    功能:
        显式保存托盘点位 TCP 位姿请求.
    参数:
        tray_name: str, 托盘名称.
        pose: List[float], 6 维 TCP 位姿 [x, y, z, rx, ry, rz].
    """

    tray_name: str = Field(..., min_length=1)
    pose: List[float] = Field(..., min_length=6, max_length=6)


class StationOffsetPrepareRequest(BaseModel):
    """
    功能:
        工站整体偏差校准准备请求.
    参数:
        station: str, 选择的工站名称, 例如 "agv" 或 "synthesis_station".
        reference_tray: str, 选定的参考点位名称.
        use_loaded_tray: bool, 是否带托盘校准.
        source_tray: str, 带托盘场景的源托盘, 默认 "agv_tray_1".
        run_vision: bool, 是否先做视觉补偿 (仅非 agv 工站有效).
        move_to_point: bool, 空载场景下是否运动到参考点位.
    """

    station: str = Field(..., min_length=1)
    reference_tray: str = Field(..., min_length=1)
    use_loaded_tray: bool = False
    source_tray: str = "agv_tray_1"
    run_vision: bool = False
    move_to_point: bool = True


class StationOffsetPreviewRequest(BaseModel):
    """
    功能:
        工站整体偏差预览计算请求, 不写盘.
    参数:
        station: str, 工站名称.
        reference_tray: str, 参考点位名称.
        vision_offset: Optional[Dict[str, float]], 视觉补偿偏移, 字段 x/y/z/dx/dy/dz.
    """

    station: str = Field(..., min_length=1)
    reference_tray: str = Field(..., min_length=1)
    vision_offset: Optional[Dict[str, float]] = None


class StationOffsetApplyRequest(BaseModel):
    """
    功能:
        工站整体偏差应用请求, 写盘.
    参数:
        station: str, 工站名称.
        offset: Dict[str, float], 偏移量 x/y/z/rx/ry/rz.
    """

    station: str = Field(..., min_length=1)
    offset: Dict[str, float]


class StationOffsetCleanupRequest(BaseModel):
    """
    功能:
        工站整体偏差校准收尾请求, 仅带托盘场景需要松爪+回零.
    参数:
        reference_tray: str, 参考点位名称.
        use_loaded_tray: bool, 是否带托盘校准.
    """

    reference_tray: str = Field(..., min_length=1)
    use_loaded_tray: bool = False


class TrayPositionCreateRequest(BaseModel):
    """
    功能:
        从模板创建托盘点位请求.
    参数:
        tray_name: str, 新点位名称.
        template_tray: str, 模板点位名称, 用于继承非 pose 字段.
        pose: List[float], 6 维 TCP 位姿.
        description: Optional[str], 描述.
    """

    tray_name: str = Field(..., min_length=1)
    template_tray: str = Field(..., min_length=1)
    pose: List[float] = Field(..., min_length=6, max_length=6)
    description: Optional[str] = None


class TrayPositionUpdateRequest(BaseModel):
    """
    功能:
        更新托盘点位字段请求, 字段为 None 表示不修改.
    参数:
        pose: Optional[List[float]], 6 维 TCP 位姿.
        descend_z: Optional[float], 下探距离.
        lift_z: Optional[float], 提升距离.
        drop_z: Optional[float], 放置下落距离.
        speed: Optional[float], 速度百分比.
        acceleration: Optional[float], 加速度百分比.
        description: Optional[str], 描述.
    """

    pose: Optional[List[float]] = Field(default=None, min_length=6, max_length=6)
    descend_z: Optional[float] = None
    lift_z: Optional[float] = None
    drop_z: Optional[float] = None
    speed: Optional[float] = None
    acceleration: Optional[float] = None
    description: Optional[str] = None


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
        "charge_control": None,
        "nav_task": None,
        "slots": None,
        "gripper_state": None,
        "current_gripper": None,
        "tcp_pose": None,
        "joints": None,
        "is_moving": None,
        "arm_state": _empty_arm_state(),
        "collision": {"active": False, "axis": None},
        "charge_loop": charger.status(),
    }

    if connections.get("chassis_connected") is True:
        controller = context.get_or_create()
        result["station"] = _safe_call(controller.query_current_station)
        result["battery"] = _safe_call(lambda: controller.query_battery_status(simple=False))
        result["charge_control"] = _safe_call(controller.query_charge_control_status)
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
                # 单次查询 RobotStatus, 同时驱动 arm_state 和 collision 派生字段
                robot_status = _safe_call(controller.arm.get_robot_status)
                result["arm_state"] = _build_arm_state(controller, robot_status)
                result["collision"] = _build_collision_info(robot_status)
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


@router.post("/arm/reset-collision")
def arm_reset_collision(context: AgvContext = Depends(get_agv_context)) -> JsonDict:
    """
    功能:
        清除机械臂碰撞检测标志, 让机械臂可以接受新的运动指令. 同步执行, 不占 Job 槽.
    返回:
        Dict[str, Any], 执行结果.
    """
    _require_arm(context)
    try:
        with context.arm_lock:
            context.get_or_create().arm.reset_collision()
    except Exception as exc:
        raise _json_error(f"清除碰撞标志失败: {exc}", status.HTTP_500_INTERNAL_SERVER_ERROR) from exc
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
        _reload_positions(context)
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
        _reload_positions(context)
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


@router.put("/charging/config")
def charging_config_save(
    request: ChargingStartRequest,
    charger: ChargeLoopService = Depends(get_charge_loop_service),
) -> JsonDict:
    """
    功能:
        保存充电循环配置, 不要求 AGV 底盘已连接.
    参数:
        request: ChargingStartRequest, 配置请求.
    返回:
        Dict[str, Any], 保存后的服务状态.
    """
    try:
        return charger.save_config(
            interval_minutes=request.interval_minutes,
            retry_wait_minutes=request.retry_wait_minutes,
            low_battery_pct=request.low_battery_pct,
            full_battery_pct=request.full_battery_pct,
        )
    except ValueError as exc:
        raise _json_error(str(exc), status.HTTP_422_UNPROCESSABLE_ENTITY) from exc
    except OSError as exc:
        raise _json_error(f"保存充电参数失败: {exc}", status.HTTP_500_INTERNAL_SERVER_ERROR) from exc


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
            interval_minutes=request.interval_minutes,
            retry_wait_minutes=request.retry_wait_minutes,
            low_battery_pct=request.low_battery_pct,
            full_battery_pct=request.full_battery_pct,
        )
    except ValueError as exc:
        raise _json_error(str(exc), status.HTTP_422_UNPROCESSABLE_ENTITY) from exc
    except OSError as exc:
        raise _json_error(f"保存充电参数失败: {exc}", status.HTTP_500_INTERNAL_SERVER_ERROR) from exc
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


@router.post("/charging/do7")
def charging_do7_set(
    request: ChargeControlDoRequest,
    context: AgvContext = Depends(get_agv_context),
    charger: ChargeLoopService = Depends(get_charge_loop_service),
) -> JsonDict:
    """
    功能:
        手动设置底盘 DO7 充电控制输出. 自动充电循环运行时禁止手动切换.
    参数:
        request: ChargeControlDoRequest, DO7 输出状态请求.
    返回:
        Dict[str, Any], DO7 设置后的状态数据.
    """
    _require_chassis(context)
    charge_loop_status = charger.status()
    if charge_loop_status.get("running") is True:
        raise _json_error("充电循环运行中, 请先停止循环后再手动切换 DO7.", status.HTTP_409_CONFLICT)

    try:
        return context.get_or_create().set_charge_control_do(request.do_status)
    except ValueError as exc:
        raise _json_error(str(exc), status.HTTP_422_UNPROCESSABLE_ENTITY) from exc
    except RuntimeError as exc:
        raise _json_error(str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR) from exc
    except Exception as exc:
        logger.exception("手动设置 DO7 失败")
        raise _json_error(f"手动设置 DO7 失败: {exc}", status.HTTP_500_INTERNAL_SERVER_ERROR) from exc


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
        log(
            f"执行单次充电检查, 低电阈值={request.low_battery_pct}%, 满电阈值={request.full_battery_pct}%."
        )
        # 充电检查内部可能触发导航+回零, 持锁执行
        with context.arm_lock:
            result = context.get_or_create().auto_charge_pp5_cp6_check(
                low_battery_pct=request.low_battery_pct,
                full_battery_pct=request.full_battery_pct,
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
        _reload_positions(context)
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
        _reload_positions(context)
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
        _reload_positions(context)
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
        _reload_positions(context)
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
        带托盘校准: 根据当前 TCP 位姿计算应保存的托盘点位, 不写入配置文件.
    参数:
        request: TrayNameRequest, 托盘名称请求.
    返回:
        Dict[str, Any], 包含待保存的位姿.
    """
    _require_arm(context)
    _reload_positions(context)
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
        _reload_positions(context)
        log(f"开始带托盘校准收尾: {request.tray_name}.")
        with context.arm_lock:
            result = context.get_or_create().complete_loaded_tray_calibration(
                request.tray_name, block=True
            )
        log("收尾完成.")
        return {"ok": bool(result)}

    return _start_job(f"带托盘校准收尾 {request.tray_name}", _target)


@router.get("/calibration/middle-tray/rows")
def calibration_middle_tray_rows(
    context: AgvContext = Depends(get_agv_context),
) -> JsonDict:
    """
    功能:
        列出所有可按行自动计算中间托盘点位的行, 供前端下拉菜单使用.
    返回:
        Dict[str, Any], 包含 rows 列表.
    """
    _reload_positions(context)
    try:
        rows = context.get_or_create().list_middle_tray_calibratable_rows()
    except Exception as exc:
        logger.exception("读取中间托盘可校准行失败")
        raise _json_error(str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR) from exc
    return {"rows": rows}


@router.get("/calibration/middle-tray/preview")
def calibration_middle_tray_preview(
    station_name: str = Query(..., min_length=1),
    row_index: int = Query(..., ge=1),
    context: AgvContext = Depends(get_agv_context),
) -> JsonDict:
    """
    功能:
        按行预览中间托盘的自动计算结果.
    参数:
        station_name: str, 工站名称.
        row_index: int, 行号, 从1开始.
    返回:
        Dict[str, Any], 包含 station_name, row_index 和 rows 列表.
    """
    _reload_positions(context)
    try:
        rows = context.get_or_create().preview_middle_tray_row_updates(
            station_name,
            row_index,
        )
    except ValueError as exc:
        raise _json_error(str(exc)) from exc
    except Exception as exc:
        logger.exception("预览中间托盘失败")
        raise _json_error(str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR) from exc
    return {"station_name": station_name, "row_index": row_index, "rows": rows}


@router.post("/calibration/middle-tray/apply")
def calibration_middle_tray_apply(
    request: MiddleTrayRowRequest,
    context: AgvContext = Depends(get_agv_context),
) -> JsonDict:
    """
    功能:
        按行应用中间托盘计算结果到配置文件.
    参数:
        request: MiddleTrayRowRequest, 中间托盘行请求.
    返回:
        Dict[str, Any], 应用统计信息.
    """
    _reload_positions(context)
    try:
        result = context.get_or_create().apply_middle_tray_row_updates(
            request.station_name,
            request.row_index,
        )
    except ValueError as exc:
        raise _json_error(str(exc)) from exc
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
        _reload_positions(context)
        log(f"运动到抓取点位: {request.tray_name}.")
        with context.arm_lock:
            result = context.get_or_create().move_to_grasp_position(request.tray_name, block=True)
        log("运动完成.")
        return {"ok": bool(result)}

    return _start_job(f"移动到抓取点位 {request.tray_name}", _target)


@router.get("/calibration/station/offset")
def calibration_station_offset_query(
    station: str = Query(..., min_length=1),
    context: AgvContext = Depends(get_agv_context),
) -> JsonDict:
    """
    功能:
        查询指定工站当前已保存的校准偏移量, 同步接口.
    参数:
        station: str, 工站名称, 例如 "shelf" / "synthesis_station".
    返回:
        Dict[str, Any], 包含 station 与 offset (None 表示未校准).
    """
    _reload_positions(context)
    try:
        offset = context.get_or_create().position_manager.get_calibration_offset(station)
    except Exception as exc:
        logger.exception("读取工站校准偏移量失败")
        raise _json_error(str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR) from exc
    return {"station": station, "offset": offset}


@router.post("/calibration/tray/preview")
def calibration_tray_preview(
    request: TrayNameRequest,
    context: AgvContext = Depends(get_agv_context),
) -> JsonDict:
    """
    功能:
        预览空载托盘校准: 读取当前 TCP 位姿并与配置文件中的位姿对比, 不写盘.
    参数:
        request: TrayNameRequest, 托盘名称请求.
    返回:
        Dict[str, Any], 包含 original_pose/current_pose/pose_to_save/station_offset.
    """
    _require_arm(context)
    _reload_positions(context)
    try:
        with context.arm_lock:
            return context.get_or_create().compute_tray_pose_from_current_pose(request.tray_name)
    except ValueError as exc:
        raise _json_error(str(exc)) from exc
    except RuntimeError as exc:
        raise _json_error(str(exc), status.HTTP_409_CONFLICT) from exc
    except Exception as exc:
        logger.exception("预览托盘校准失败")
        raise _json_error(str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR) from exc


@router.post("/calibration/tray/save")
def calibration_tray_save(
    request: TraySaveRequest,
    context: AgvContext = Depends(get_agv_context),
) -> JsonDict:
    """
    功能:
        显式保存托盘点位 TCP 位姿到配置文件.
    参数:
        request: TraySaveRequest, 包含托盘名称与待写入的位姿.
    返回:
        Dict[str, Any], 包含 tray_name 与 ok.
    """
    _reload_positions(context)
    try:
        ok = context.get_or_create().save_calibrated_tray_position(request.tray_name, request.pose)
    except Exception as exc:
        logger.exception("保存托盘校准位姿失败")
        raise _json_error(str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR) from exc
    if ok is False:
        raise _json_error("保存托盘位姿失败.")
    return {"tray_name": request.tray_name, "ok": True}


@router.post("/calibration/station-offset/prepare")
def calibration_station_offset_prepare(
    request: StationOffsetPrepareRequest,
    context: AgvContext = Depends(get_agv_context),
) -> JsonDict:
    """
    功能:
        工站整体偏差校准准备阶段 (Job 任务): 视觉补偿 + 取托盘 + 运动到参考点过渡位.
    参数:
        request: StationOffsetPrepareRequest, 准备请求.
    返回:
        Dict[str, Any], Job ID. 任务结果含 vision_offset (供后续 preview 使用).
    """
    _require_arm(context)
    if request.run_vision is True:
        _require_chassis(context)

    def _target(log: Callable[[str], None]) -> Any:
        _reload_positions(context)
        controller = context.get_or_create()
        vision_offset: Optional[Dict[str, float]] = None
        with context.arm_lock:
            if request.run_vision is True:
                log(f"执行 {request.station} 工站视觉补偿校准.")
                vision_offset = controller.calibrate_station(block=True)
                if vision_offset is None:
                    raise RuntimeError("视觉补偿校准失败")
                log(f"视觉补偿完成, 偏移量={vision_offset}.")

            if request.use_loaded_tray is True:
                log(f"带托盘准备: {request.source_tray} -> {request.reference_tray} 过渡位.")
                ok = controller.prepare_loaded_tray_calibration(
                    request.reference_tray,
                    source_tray_name=request.source_tray,
                    block=True,
                )
                if ok is False:
                    raise RuntimeError("带托盘准备失败")
            elif request.move_to_point is True:
                log(f"运动到参考点位: {request.reference_tray}.")
                ok = controller.move_to_grasp_position(request.reference_tray, block=True)
                if ok is False:
                    raise RuntimeError("运动到参考点位失败")
            else:
                log("跳过运动, 用户将手动到达参考点.")

        log("准备阶段完成, 请使用机械臂微调到精确位置.")
        return {"vision_offset": vision_offset, "use_loaded_tray": request.use_loaded_tray}

    return _start_job(f"工站整体偏差准备 {request.station}", _target)


@router.post("/calibration/station-offset/preview")
def calibration_station_offset_preview(
    request: StationOffsetPreviewRequest,
    context: AgvContext = Depends(get_agv_context),
) -> JsonDict:
    """
    功能:
        计算工站整体偏差 (同步), 不写盘. 前置: 已通过 prepare 让用户微调到位.
    参数:
        request: StationOffsetPreviewRequest, 预览请求.
    返回:
        Dict[str, Any], 包含 original_pose/current_pose/expected_pose/offset/affected_trays.
    """
    _require_arm(context)
    _reload_positions(context)
    try:
        with context.arm_lock:
            return context.get_or_create().compute_station_offset_from_current_pose(
                request.station,
                request.reference_tray,
                vision_offset=request.vision_offset,
            )
    except ValueError as exc:
        raise _json_error(str(exc)) from exc
    except RuntimeError as exc:
        raise _json_error(str(exc), status.HTTP_409_CONFLICT) from exc
    except Exception as exc:
        logger.exception("预览工站整体偏差失败")
        raise _json_error(str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR) from exc


@router.post("/calibration/station-offset/apply")
def calibration_station_offset_apply(
    request: StationOffsetApplyRequest,
    context: AgvContext = Depends(get_agv_context),
) -> JsonDict:
    """
    功能:
        将偏移量应用到工站所有点位并写盘 (同步).
    参数:
        request: StationOffsetApplyRequest, 应用请求.
    返回:
        Dict[str, Any], 包含 station/success_count/fail_count/affected_trays.
    """
    required_keys = {"x", "y", "z", "rx", "ry", "rz"}
    if required_keys.issubset(request.offset.keys()) is False:
        raise _json_error("offset 必须包含 x/y/z/rx/ry/rz 六个字段.")
    _reload_positions(context)
    try:
        return context.get_or_create().apply_station_offset(request.station, request.offset)
    except ValueError as exc:
        raise _json_error(str(exc)) from exc
    except Exception as exc:
        logger.exception("应用工站整体偏差失败")
        raise _json_error(str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR) from exc


@router.post("/calibration/station-offset/cleanup")
def calibration_station_offset_cleanup(
    request: StationOffsetCleanupRequest,
    context: AgvContext = Depends(get_agv_context),
) -> JsonDict:
    """
    功能:
        工站整体偏差校准收尾 (Job 任务). 带托盘场景下走 complete_loaded_tray_calibration.
    参数:
        request: StationOffsetCleanupRequest, 收尾请求.
    返回:
        Dict[str, Any], Job ID 或同步 ok.
    """
    if request.use_loaded_tray is False:
        return {"ok": True, "skipped": True}

    _require_arm(context)

    def _target(log: Callable[[str], None]) -> Any:
        _reload_positions(context)
        log(f"带托盘收尾: {request.reference_tray}.")
        with context.arm_lock:
            ok = context.get_or_create().complete_loaded_tray_calibration(
                request.reference_tray, block=True
            )
        if ok is False:
            raise RuntimeError("带托盘收尾失败, 请人工处理.")
        log("收尾完成.")
        return {"ok": True}

    return _start_job(f"工站整体偏差收尾 {request.reference_tray}", _target)


# ==================== 分节 E2: 取放托盘测试 ====================


@router.post("/test/pick-tray")
def test_pick_tray(
    request: TestTrayActionRequest,
    context: AgvContext = Depends(get_agv_context),
) -> JsonDict:
    """
    功能:
        测试取托盘 (Job 任务), 复刻 main 菜单第 7 项.
    参数:
        request: TestTrayActionRequest, 含托盘名称与可选物料类型.
    返回:
        Dict[str, Any], Job ID.
    """
    _require_arm(context)

    def _target(log: Callable[[str], None]) -> Any:
        _reload_positions(context)
        log(f"测试取托盘: {request.tray_name}, material_type={request.material_type}.")
        with context.arm_lock:
            ok = context.get_or_create().pick_tray_with_material(
                request.tray_name,
                material_type=request.material_type,
                block=True,
            )
        log(f"取托盘结果: {'成功' if ok else '失败'}.")
        return {"ok": bool(ok)}

    return _start_job(f"测试取托盘 {request.tray_name}", _target)


@router.post("/test/put-tray")
def test_put_tray(
    request: TestTrayActionRequest,
    context: AgvContext = Depends(get_agv_context),
) -> JsonDict:
    """
    功能:
        测试放托盘 (Job 任务), 复刻 main 菜单第 8 项.
    参数:
        request: TestTrayActionRequest, 含托盘名称与可选物料类型.
    返回:
        Dict[str, Any], Job ID.
    """
    _require_arm(context)

    def _target(log: Callable[[str], None]) -> Any:
        _reload_positions(context)
        log(f"测试放托盘: {request.tray_name}, material_type={request.material_type}.")
        with context.arm_lock:
            ok = context.get_or_create().put_tray_with_material(
                request.tray_name,
                material_type=request.material_type,
                block=True,
            )
        log(f"放托盘结果: {'成功' if ok else '失败'}.")
        return {"ok": bool(ok)}

    return _start_job(f"测试放托盘 {request.tray_name}", _target)


# ==================== 分节 E3: 批量测试 ====================


class _JobLogBridge(logging.Handler):
    """
    功能:
        将 eit_hub.ui 命名空间下的日志记录实时转发到 Job 日志缓冲, 供前端 JobPanel 流式显示.
        绑定 logger 应统一为 eit_hub.ui, 控制器关键事件需通过 ui_logger 写入才会进入展示通道.
    参数:
        log_fn: Job target 闭包提供的 log 回调, 接受 (message, level, source) 关键字参数.
    """

    def __init__(self, log_fn: Callable[..., None]) -> None:
        super().__init__(level=logging.INFO)
        self._log_fn = log_fn

    def emit(self, record: logging.LogRecord) -> None:
        """
        功能:
            处理一条日志记录, 解析级别和来源后写入 Job 日志.
        参数:
            record: logging.LogRecord, 日志记录.
        返回:
            None.
        """
        try:
            self._log_fn(
                record.getMessage(),
                level=level_from_record(record),
                source=source_from_record(record),
            )
        except Exception:
            self.handleError(record)


class TestAllPositionsRequest(BaseModel):
    """
    功能:
        全点位测试请求体.
    参数:
        material_type: str, 托盘物料类型, 决定夹爪与高度偏移.
    """

    material_type: str = Field(..., description="托盘物料类型名称")


class BatchTransferTaskItem(BaseModel):
    """
    功能:
        批量物料转运循环测试中的单条任务.
    参数:
        source_tray: str, 源托盘点位名称.
        target_tray: str, 目标托盘点位名称.
        material_type: str, 物料类型名称, 决定夹爪与高度偏移.
    """

    source_tray: str = Field(..., description="源托盘点位名称")
    target_tray: str = Field(..., description="目标托盘点位名称")
    material_type: str = Field(..., description="物料类型名称")


class BatchTransferCycleRequest(BaseModel):
    """
    功能:
        批量物料转运循环测试请求体.
    参数:
        cycle_count: int, 循环轮数, 至少 1.
        transfer_tasks: List[BatchTransferTaskItem], 转运任务, 1-4 个.
    """

    cycle_count: int = Field(..., ge=1, description="循环轮数")
    transfer_tasks: List[BatchTransferTaskItem] = Field(
        ..., min_length=1, max_length=4, description="转运任务列表(1-4个)",
    )


@router.post("/test/all-positions")
def test_all_positions(
    request: TestAllPositionsRequest,
    context: AgvContext = Depends(get_agv_context),
) -> JsonDict:
    """
    功能:
        全点位测试 (Job 任务). 从 agv_tray_1 取托盘依次放到当前工站每个点位再取回, 验证点位准确性.
    参数:
        request: TestAllPositionsRequest, 含物料类型.
    返回:
        Dict[str, Any], Job ID 响应.
    """
    _require_arm(context)

    def _target(log: Callable[[str], None]) -> Any:
        _reload_positions(context)
        controller = context.get_or_create()
        # 全点位测试只覆盖当前工站, 未识别工站时直接终止
        if controller.current_station is None:
            raise RuntimeError("未识别当前工站, 请先校准或移动到目标工站.")
        log(f"开始全点位测试, 物料类型: {request.material_type}, 当前工站: {controller.current_station}.")
        # 仅订阅 eit_hub.ui 命名空间, 控制器需通过 ui_logger 写入才会进入 Job 日志
        target_logger = logging.getLogger(UI_LOGGER_NAME)
        bridge = _JobLogBridge(log)
        target_logger.addHandler(bridge)
        try:
            with context.arm_lock:
                results = controller.test_all_positions(
                    request.material_type,
                    block=True,
                )
        finally:
            target_logger.removeHandler(bridge)
        success_count = len(results.get("success", []))
        failed_count = len(results.get("failed", []))
        skipped_count = len(results.get("skipped", []))
        log(
            f"全点位测试结束, 成功 {success_count} 个, 失败 {failed_count} 个, 跳过 {skipped_count} 个.",
        )
        return results

    return _start_job(f"全点位测试 {request.material_type}", _target)


@router.post("/test/batch-transfer-cycle")
def test_batch_transfer_cycle(
    request: BatchTransferCycleRequest,
    context: AgvContext = Depends(get_agv_context),
) -> JsonDict:
    """
    功能:
        批量物料转运循环测试 (Job 任务). 1-4 个任务, 每轮执行 正向转运 -> 充电过渡点 -> 反向转运 -> 充电过渡点.
    参数:
        request: BatchTransferCycleRequest, 含循环轮数与任务列表.
    返回:
        Dict[str, Any], Job ID 响应.
    """
    _require_chassis(context)
    _require_arm(context)

    # pydantic 列表转控制器期望的 dict 列表
    transfer_tasks: List[Dict[str, str]] = [
        {
            "source_tray": item.source_tray,
            "target_tray": item.target_tray,
            "material_type": item.material_type,
        }
        for item in request.transfer_tasks
    ]
    cycle_count = request.cycle_count

    def _target(log: Callable[[str], None]) -> Any:
        _reload_positions(context)
        controller = context.get_or_create()
        log(f"开始批量物料转运循环测试, 共 {cycle_count} 轮, {len(transfer_tasks)} 个任务.")
        for index, task in enumerate(transfer_tasks, 1):
            log(
                f"任务 {index}: {task['source_tray']} <-> {task['target_tray']}, "
                f"物料类型 {task['material_type']}.",
            )
        # 仅订阅 eit_hub.ui 命名空间, 控制器需通过 ui_logger 写入才会进入 Job 日志
        target_logger = logging.getLogger(UI_LOGGER_NAME)
        bridge = _JobLogBridge(log)
        target_logger.addHandler(bridge)
        try:
            with context.arm_lock:
                result = controller.batch_transfer_cycle_test(
                    transfer_tasks,
                    cycle_count=cycle_count,
                    block=True,
                )
        finally:
            target_logger.removeHandler(bridge)
        log(
            f"循环测试结束, 完成 {result.get('completed_cycles', 0)}/"
            f"{result.get('total_cycles', cycle_count)} 轮, "
            f"状态: {'成功' if result.get('success') else '失败'}.",
        )
        return result

    return _start_job(f"批量物料转运循环测试 x{cycle_count}", _target)


# ==================== 分节 E4: 物料与点位管理 ====================


@router.get("/materials")
def list_materials(context: AgvContext = Depends(get_agv_context)) -> JsonDict:
    """
    功能:
        列出物料类型选项, 用于取放测试下拉.
    返回:
        Dict[str, Any], 包含 materials 列表, 元素含 name/gripper/description.
    """
    _reload_positions(context)
    try:
        materials = context.get_or_create().position_manager.materials
    except Exception as exc:
        logger.exception("读取物料配置失败")
        raise _json_error(str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR) from exc

    items: List[JsonDict] = []
    for name, data in materials.items():
        items.append({
            "name": name,
            "gripper": getattr(data, "gripper", ""),
            "description": getattr(data, "description", ""),
        })
    return {"materials": items}


@router.get("/positions/tray")
def list_tray_positions(context: AgvContext = Depends(get_agv_context)) -> JsonDict:
    """
    功能:
        列出全部托盘点位的完整字段, 供前端点位管理页渲染表格.
    返回:
        Dict[str, Any], 包含 positions 列表.
    """
    _reload_positions(context)
    try:
        positions = context.get_or_create().position_manager.list_tray_positions()
    except Exception as exc:
        logger.exception("读取托盘点位列表失败")
        raise _json_error(str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR) from exc
    return {"positions": positions}


@router.put("/positions/tray/{tray_name}")
def update_tray_position(
    tray_name: str,
    request: TrayPositionUpdateRequest,
    context: AgvContext = Depends(get_agv_context),
) -> JsonDict:
    """
    功能:
        更新托盘点位字段, 字段为 None 表示不修改.
    参数:
        tray_name: str, 待更新的托盘名称.
        request: TrayPositionUpdateRequest, 待更新字段.
    返回:
        Dict[str, Any], 包含 tray_name 与 ok.
    """
    fields = request.model_dump(exclude_none=True)
    if len(fields) == 0:
        raise _json_error("至少提供一个待更新字段.")
    _reload_positions(context)
    try:
        context.get_or_create().position_manager.update_tray_fields(tray_name, fields)
    except ValueError as exc:
        raise _json_error(str(exc), status.HTTP_404_NOT_FOUND) from exc
    except Exception as exc:
        logger.exception("更新托盘点位失败")
        raise _json_error(str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR) from exc
    return {"tray_name": tray_name, "ok": True}


@router.post("/positions/tray")
def create_tray_position(
    request: TrayPositionCreateRequest,
    context: AgvContext = Depends(get_agv_context),
) -> JsonDict:
    """
    功能:
        基于模板创建新托盘点位.
    参数:
        request: TrayPositionCreateRequest, 创建请求.
    返回:
        Dict[str, Any], 包含 tray_name 与 ok.
    """
    _reload_positions(context)
    try:
        context.get_or_create().position_manager.save_tray_position_from_template(
            request.tray_name,
            request.pose,
            request.template_tray,
            description=request.description,
        )
    except ValueError as exc:
        raise _json_error(str(exc)) from exc
    except Exception as exc:
        logger.exception("创建托盘点位失败")
        raise _json_error(str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR) from exc
    return {"tray_name": request.tray_name, "ok": True}


@router.delete("/positions/tray/{tray_name}")
def delete_tray_position(
    tray_name: str,
    context: AgvContext = Depends(get_agv_context),
) -> JsonDict:
    """
    功能:
        删除指定托盘点位.
    参数:
        tray_name: str, 待删除的托盘名称.
    返回:
        Dict[str, Any], 包含 tray_name 与 ok.
    """
    _reload_positions(context)
    try:
        context.get_or_create().position_manager.delete_tray_position(tray_name)
    except ValueError as exc:
        raise _json_error(str(exc), status.HTTP_404_NOT_FOUND) from exc
    except Exception as exc:
        logger.exception("删除托盘点位失败")
        raise _json_error(str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR) from exc
    return {"tray_name": tray_name, "ok": True}


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
