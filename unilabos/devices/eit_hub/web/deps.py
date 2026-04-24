# -*- coding: utf-8 -*-
"""
功能:
    定义 EIT Hub Web 的 FastAPI 依赖.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from unilabos.devices.eit_analysis_station.config.setting import Settings as AnalysisSettings
from unilabos.devices.eit_analysis_station.controller.analysis_controller import (
    AnalysisStationController,
)
from unilabos.devices.eit_synthesis_station.config.setting import Settings
from unilabos.devices.eit_synthesis_station.manager.station_manager import (
    SynthesisStationManager,
)

from .services.agv_context import AgvContext
from .services.battery_sampler import BatterySamplerService
from .services.charge_loop import ChargeLoopService


# AGV 电量历史数据文件, 位于 web/data 目录, 首次采样时自动创建
_AGV_DATA_DIR = Path(__file__).resolve().parent / "data"
_BATTERY_HISTORY_PATH = _AGV_DATA_DIR / "battery_history.json"


@lru_cache(maxsize=1)
def _get_shared_synthesis_manager() -> SynthesisStationManager:
    """
    功能:
        创建并缓存合成工站管理器, 避免每次请求重复初始化连接配置.
    返回:
        SynthesisStationManager, 合成工站管理器实例.
    """
    settings = Settings.from_env()
    return SynthesisStationManager(settings=settings)


def get_synthesis_manager() -> SynthesisStationManager:
    """
    功能:
        FastAPI 依赖, 返回合成工站管理器.
    返回:
        SynthesisStationManager, 合成工站管理器实例.
    """
    return _get_shared_synthesis_manager()


@lru_cache(maxsize=1)
def _get_shared_analysis_controller() -> AnalysisStationController:
    """
    功能:
        创建并缓存分析工站控制器, 避免每次请求重复初始化连接配置.
    返回:
        AnalysisStationController, 分析工站控制器实例.
    """
    settings = AnalysisSettings.from_env()
    return AnalysisStationController(settings=settings)


def get_analysis_controller() -> AnalysisStationController:
    """
    功能:
        FastAPI 依赖, 返回分析工站控制器.
    返回:
        AnalysisStationController, 分析工站控制器实例.
    """
    return _get_shared_analysis_controller()


@lru_cache(maxsize=1)
def _get_shared_agv_context() -> AgvContext:
    """
    功能:
        创建并缓存 AGV 上下文, 保证全局唯一的 AGVController 实例和连接状态.
    返回:
        AgvContext, AGV 上下文实例.
    """
    return AgvContext()


def get_agv_context() -> AgvContext:
    """
    功能:
        FastAPI 依赖, 返回 AGV 上下文.
    返回:
        AgvContext, AGV 上下文实例.
    """
    return _get_shared_agv_context()


@lru_cache(maxsize=1)
def _get_shared_battery_sampler_service() -> BatterySamplerService:
    """
    功能:
        创建并缓存电量采样服务.
    返回:
        BatterySamplerService, 采样服务实例.
    """
    return BatterySamplerService(_get_shared_agv_context(), _BATTERY_HISTORY_PATH)


def get_battery_sampler_service() -> BatterySamplerService:
    """
    功能:
        FastAPI 依赖, 返回电量采样服务.
    返回:
        BatterySamplerService, 采样服务实例.
    """
    return _get_shared_battery_sampler_service()


@lru_cache(maxsize=1)
def _get_shared_charge_loop_service() -> ChargeLoopService:
    """
    功能:
        创建并缓存充电循环服务.
    返回:
        ChargeLoopService, 充电循环服务实例.
    """
    return ChargeLoopService(_get_shared_agv_context())


def get_charge_loop_service() -> ChargeLoopService:
    """
    功能:
        FastAPI 依赖, 返回充电循环服务.
    返回:
        ChargeLoopService, 充电循环服务实例.
    """
    return _get_shared_charge_loop_service()
