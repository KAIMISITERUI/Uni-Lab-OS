#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    分析站配置模块, 统一管理仪器连接参数, 数据目录和积分参数.
参数:
    无.
返回:
    Settings 实例.
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Settings:
    """
    功能:
        存储分析站运行所需的全部配置项.
    参数:
        无.
    返回:
        Settings.
    """

    # ---------- GC_MS 设备 ----------
    gc_ms_host: str = "10.40.6.101"
    gc_ms_port: int = 5792
    gc_ms_timeout: float = 10.0

    # ---------- UPLC_QTOF 设备(预留) ----------
    uplc_qtof_host: str = "192.168.3.185"
    uplc_qtof_port: int = 5792
    uplc_qtof_timeout: float = 10.0

    # ---------- HPLC 设备(预留) ----------
    hplc_host: str = "192.168.3.186"
    hplc_port: int = 5792
    hplc_timeout: float = 10.0

    # ---------- 仪器侧数据目录 ----------
    gc_ms_data_dir: Path = field(default_factory=lambda: Path(r"\\10.37.2.2\Autolab_Database\Auto_GC_MS\data"))
    uplc_qtof_data_dir: Path = field(default_factory=lambda: Path("Z:/Auto_UPLC_QTOF/data"))
    hplc_data_dir: Path = field(default_factory=lambda: Path("Z:/Auto_HPLC/data"))

    # ---------- 合成任务目录 ----------
    synthesis_tasks_dir: Path = field(
        default_factory=lambda: Path(__file__).parent.parent.parent
        / "eit_synthesis_station"
        / "data"
        / "tasks"
    )

    # ---------- 分析站本地数据目录 ----------
    data_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent / "data")

    # ---------- 日志 ----------
    log_level: str = "INFO"

    # ---------- NIST 配置 ----------
    nist_path: Path = field(default_factory=lambda: Path(r"D:\NIST23\MSSEARCH"))
    nist_max_hits: int = 5
    nist_search_timeout: float = 120.0
    nist_avg_scans: int = 3

    # ---------- 峰检测与积分参数 ----------
    peak_smoothing_window: int = 11
    peak_prominence: float = 50000.0
    peak_min_distance: int = 5
    peak_width_rel_height: float = 0.99
    fid_peak_prominence: float = 0.5
    fid_peak_min_distance: int = 50

    # ---------- legacy 参数 ----------
    use_als_baseline: bool = True
    als_lambda: float = 1e7
    als_p: float = 0.01
    use_valley_boundary: bool = False

    # ---------- robust_v2 参数 ----------
    integration_mode: str = "robust_v2"
    baseline_method: str = "rolling_quantile"
    baseline_quantile: float = 20.0
    baseline_window_min: float = 0.9
    boundary_sigma_factor: float = 3.0
    boundary_edge_ratio: float = 0.01
    boundary_expand_factor: float = 6.0
    boundary_min_span_min: float = 0.08
    boundary_max_span_min: float = 0.80

    # ---------- 峰过滤参数 ----------
    peak_rt_min: Optional[float] = 4
    peak_rt_max: Optional[float] = 10
    tic_area_min: Optional[float] = 100000
    tic_area_max: Optional[float] = None
    fid_area_min: Optional[float] = 0.01
    fid_area_max: Optional[float] = None

    # ---------- 报告目录 ----------
    report_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent / "data")

    # ---------- 结构图缓存目录 ----------
    structure_cache_dir: Path = field(
        default_factory=lambda: Path(__file__).parent.parent / "data" / "structure_cache"
    )

    @staticmethod
    def from_env() -> "Settings":
        """
        功能:
            从环境变量读取配置, 未配置时使用默认值.
        参数:
            无.
        返回:
            Settings.
        环境变量:
            ANALYSIS_GC_MS_HOST, ANALYSIS_GC_MS_PORT, ANALYSIS_GC_MS_TIMEOUT,
            ANALYSIS_UPLC_QTOF_HOST, ANALYSIS_UPLC_QTOF_PORT, ANALYSIS_UPLC_QTOF_TIMEOUT,
            ANALYSIS_HPLC_HOST, ANALYSIS_HPLC_PORT, ANALYSIS_HPLC_TIMEOUT,
            ANALYSIS_GC_MS_DATA_DIR, ANALYSIS_UPLC_QTOF_DATA_DIR, ANALYSIS_HPLC_DATA_DIR,
            ANALYSIS_SYNTHESIS_TASKS_DIR, ANALYSIS_DATA_DIR, ANALYSIS_LOG_LEVEL,
            ANALYSIS_PEAK_SMOOTHING_WINDOW, ANALYSIS_PEAK_PROMINENCE,
            ANALYSIS_PEAK_MIN_DISTANCE, ANALYSIS_PEAK_WIDTH_REL_HEIGHT,
            ANALYSIS_FID_PEAK_PROMINENCE, ANALYSIS_FID_PEAK_MIN_DISTANCE,
            ANALYSIS_USE_ALS_BASELINE, ANALYSIS_ALS_LAMBDA, ANALYSIS_ALS_P,
            ANALYSIS_USE_VALLEY_BOUNDARY,
            ANALYSIS_INTEGRATION_MODE, ANALYSIS_BASELINE_METHOD,
            ANALYSIS_BASELINE_QUANTILE, ANALYSIS_BASELINE_WINDOW_MIN,
            ANALYSIS_BOUNDARY_SIGMA_FACTOR, ANALYSIS_BOUNDARY_EDGE_RATIO,
            ANALYSIS_BOUNDARY_EXPAND_FACTOR, ANALYSIS_BOUNDARY_MIN_SPAN_MIN,
            ANALYSIS_BOUNDARY_MAX_SPAN_MIN,
            ANALYSIS_PEAK_RT_MIN, ANALYSIS_PEAK_RT_MAX,
            ANALYSIS_TIC_AREA_MIN, ANALYSIS_TIC_AREA_MAX,
            ANALYSIS_FID_AREA_MIN, ANALYSIS_FID_AREA_MAX,
            ANALYSIS_REPORT_DIR, ANALYSIS_STRUCTURE_CACHE_DIR,
            ANALYSIS_NIST_PATH, ANALYSIS_NIST_MAX_HITS,
            ANALYSIS_NIST_SEARCH_TIMEOUT, ANALYSIS_NIST_AVG_SCANS.
        """
        defaults = Settings()

        def _str(key: str, default: str) -> str:
            return os.getenv(key, default)

        def _int(key: str, default: int) -> int:
            try:
                return int(os.getenv(key, str(default)))
            except ValueError:
                return default

        def _float(key: str, default: float) -> float:
            try:
                return float(os.getenv(key, str(default)))
            except ValueError:
                return default

        def _path(key: str, default: Path) -> Path:
            value = os.getenv(key)
            if value is None or value.strip() == "":
                return default
            return Path(value)

        def _opt_float(key: str, default: Optional[float] = None) -> Optional[float]:
            value = os.getenv(key)
            if value is None or value.strip() == "":
                return default
            try:
                return float(value)
            except ValueError:
                return default

        def _bool(key: str, default: bool) -> bool:
            value = os.getenv(key)
            if value is None or value.strip() == "":
                return default
            return value.strip().lower() in ("true", "1", "yes")

        return Settings(
            gc_ms_host=_str("ANALYSIS_GC_MS_HOST", defaults.gc_ms_host),
            gc_ms_port=_int("ANALYSIS_GC_MS_PORT", defaults.gc_ms_port),
            gc_ms_timeout=_float("ANALYSIS_GC_MS_TIMEOUT", defaults.gc_ms_timeout),
            uplc_qtof_host=_str("ANALYSIS_UPLC_QTOF_HOST", defaults.uplc_qtof_host),
            uplc_qtof_port=_int("ANALYSIS_UPLC_QTOF_PORT", defaults.uplc_qtof_port),
            uplc_qtof_timeout=_float("ANALYSIS_UPLC_QTOF_TIMEOUT", defaults.uplc_qtof_timeout),
            hplc_host=_str("ANALYSIS_HPLC_HOST", defaults.hplc_host),
            hplc_port=_int("ANALYSIS_HPLC_PORT", defaults.hplc_port),
            hplc_timeout=_float("ANALYSIS_HPLC_TIMEOUT", defaults.hplc_timeout),
            gc_ms_data_dir=_path("ANALYSIS_GC_MS_DATA_DIR", defaults.gc_ms_data_dir),
            uplc_qtof_data_dir=_path("ANALYSIS_UPLC_QTOF_DATA_DIR", defaults.uplc_qtof_data_dir),
            hplc_data_dir=_path("ANALYSIS_HPLC_DATA_DIR", defaults.hplc_data_dir),
            synthesis_tasks_dir=_path("ANALYSIS_SYNTHESIS_TASKS_DIR", defaults.synthesis_tasks_dir),
            data_dir=_path("ANALYSIS_DATA_DIR", defaults.data_dir),
            log_level=_str("ANALYSIS_LOG_LEVEL", defaults.log_level),
            peak_smoothing_window=_int("ANALYSIS_PEAK_SMOOTHING_WINDOW", defaults.peak_smoothing_window),
            peak_prominence=_float("ANALYSIS_PEAK_PROMINENCE", defaults.peak_prominence),
            peak_min_distance=_int("ANALYSIS_PEAK_MIN_DISTANCE", defaults.peak_min_distance),
            peak_width_rel_height=_float("ANALYSIS_PEAK_WIDTH_REL_HEIGHT", defaults.peak_width_rel_height),
            fid_peak_prominence=_float("ANALYSIS_FID_PEAK_PROMINENCE", defaults.fid_peak_prominence),
            fid_peak_min_distance=_int("ANALYSIS_FID_PEAK_MIN_DISTANCE", defaults.fid_peak_min_distance),
            use_als_baseline=_bool("ANALYSIS_USE_ALS_BASELINE", defaults.use_als_baseline),
            als_lambda=_float("ANALYSIS_ALS_LAMBDA", defaults.als_lambda),
            als_p=_float("ANALYSIS_ALS_P", defaults.als_p),
            use_valley_boundary=_bool("ANALYSIS_USE_VALLEY_BOUNDARY", defaults.use_valley_boundary),
            integration_mode=_str("ANALYSIS_INTEGRATION_MODE", defaults.integration_mode),
            baseline_method=_str("ANALYSIS_BASELINE_METHOD", defaults.baseline_method),
            baseline_quantile=_float("ANALYSIS_BASELINE_QUANTILE", defaults.baseline_quantile),
            baseline_window_min=_float("ANALYSIS_BASELINE_WINDOW_MIN", defaults.baseline_window_min),
            boundary_sigma_factor=_float("ANALYSIS_BOUNDARY_SIGMA_FACTOR", defaults.boundary_sigma_factor),
            boundary_edge_ratio=_float("ANALYSIS_BOUNDARY_EDGE_RATIO", defaults.boundary_edge_ratio),
            boundary_expand_factor=_float("ANALYSIS_BOUNDARY_EXPAND_FACTOR", defaults.boundary_expand_factor),
            boundary_min_span_min=_float("ANALYSIS_BOUNDARY_MIN_SPAN_MIN", defaults.boundary_min_span_min),
            boundary_max_span_min=_float("ANALYSIS_BOUNDARY_MAX_SPAN_MIN", defaults.boundary_max_span_min),
            report_dir=_path("ANALYSIS_REPORT_DIR", defaults.report_dir),
            structure_cache_dir=_path("ANALYSIS_STRUCTURE_CACHE_DIR", defaults.structure_cache_dir),
            nist_path=_path("ANALYSIS_NIST_PATH", defaults.nist_path),
            nist_max_hits=_int("ANALYSIS_NIST_MAX_HITS", defaults.nist_max_hits),
            nist_search_timeout=_float("ANALYSIS_NIST_SEARCH_TIMEOUT", defaults.nist_search_timeout),
            nist_avg_scans=_int("ANALYSIS_NIST_AVG_SCANS", defaults.nist_avg_scans),
            peak_rt_min=_opt_float("ANALYSIS_PEAK_RT_MIN", defaults.peak_rt_min),
            peak_rt_max=_opt_float("ANALYSIS_PEAK_RT_MAX", defaults.peak_rt_max),
            tic_area_min=_opt_float("ANALYSIS_TIC_AREA_MIN", defaults.tic_area_min),
            tic_area_max=_opt_float("ANALYSIS_TIC_AREA_MAX", defaults.tic_area_max),
            fid_area_min=_opt_float("ANALYSIS_FID_AREA_MIN", defaults.fid_area_min),
            fid_area_max=_opt_float("ANALYSIS_FID_AREA_MAX", defaults.fid_area_max),
        )


def configure_logging(level: str = "INFO") -> None:
    """
    功能:
        配置全局 logging.
    参数:
        level: 日志等级字符串.
    返回:
        无.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    if not root_logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)