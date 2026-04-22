# -*- coding: utf-8 -*-
"""
功能:
    定义 EIT Hub Web 的 FastAPI 依赖.
"""

from __future__ import annotations

from functools import lru_cache

from unilabos.devices.eit_analysis_station.config.setting import Settings as AnalysisSettings
from unilabos.devices.eit_analysis_station.controller.analysis_controller import (
    AnalysisStationController,
)
from unilabos.devices.eit_synthesis_station.config.setting import Settings
from unilabos.devices.eit_synthesis_station.manager.station_manager import (
    SynthesisStationManager,
)


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
