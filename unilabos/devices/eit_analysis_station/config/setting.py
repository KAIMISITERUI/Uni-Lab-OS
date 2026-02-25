#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    分析站配置模块, 统一管理三台仪器(GC_MS/UPLC_QTOF/HPLC)的连接参数、
    数据保存路径以及合成任务文件路径.
参数:
    无(通过 dataclass 默认值或环境变量配置).
返回:
    Settings 实例.
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    """
    功能:
        统一存放分析站驱动的基础配置, 包含三台仪器的 IP/端口/超时时间、
        仪器侧数据保存路径、合成任务目录以及本站数据存储根目录.
    参数:
        gc_ms_host: GC_MS 设备 IP 地址.
        gc_ms_port: GC_MS 通信端口, 默认 5792.
        gc_ms_timeout: GC_MS 连接/接收超时时间(秒).
        uplc_qtof_host: UPLC_QTOF 设备 IP 地址(预留).
        uplc_qtof_port: UPLC_QTOF 通信端口(预留).
        uplc_qtof_timeout: UPLC_QTOF 超时时间(秒)(预留).
        hplc_host: HPLC 设备 IP 地址(预留).
        hplc_port: HPLC 通信端口(预留).
        hplc_timeout: HPLC 超时时间(秒)(预留).
        gc_ms_data_dir: GC_MS 仪器侧数据保存目录.
        uplc_qtof_data_dir: UPLC_QTOF 仪器侧数据保存目录.
        hplc_data_dir: HPLC 仪器侧数据保存目录.
        synthesis_tasks_dir: 合成任务文件夹根路径(含 task_info.json 和 xlsx).
        data_dir: 分析站本地数据存储根目录(生成的 CSV 保存于此).
        log_level: 日志级别字符串, 例如 "INFO".
    返回:
        Settings.
    """

    # ---------- GC_MS 设备 ----------
    gc_ms_host: str = "10.40.6.101"
    gc_ms_port: int = 5792
    gc_ms_timeout: float = 10.0

    # ---------- UPLC_QTOF 设备（预留，后续接入） ----------
    uplc_qtof_host: str = "192.168.3.185"
    uplc_qtof_port: int = 5792
    uplc_qtof_timeout: float = 10.0

    # ---------- HPLC 设备（预留，后续接入） ----------
    hplc_host: str = "192.168.3.186"
    hplc_port: int = 5792
    hplc_timeout: float = 10.0

    # ---------- 仪器侧数据保存路径（通过网络共享访问） ----------
    gc_ms_data_dir: Path = field(default_factory=lambda: Path(r"\\10.37.2.2\Autolab_Database\Auto_GC_MS\data"))
    uplc_qtof_data_dir: Path = field(default_factory=lambda: Path("Z:/Auto_UPLC_QTOF/data"))
    hplc_data_dir: Path = field(default_factory=lambda: Path("Z:/Auto_HPLC/data"))

    # ---------- 合成任务目录（eit_synthesis_station/data/tasks） ----------
    synthesis_tasks_dir: Path = field(
        default_factory=lambda: Path(__file__).parent.parent.parent
        / "eit_synthesis_station"
        / "data"
        / "tasks"
    )

    # ---------- 分析站本地数据存储根目录 ----------
    data_dir: Path = field(
        default_factory=lambda: Path(__file__).parent.parent / "data"
    )

    log_level: str = "INFO"

    # ---------- NIST MS Search 配置 ----------
    nist_path: Path = field(default_factory=lambda: Path(r"D:\NIST23\MSSEARCH"))
    nist_max_hits: int = 5               # 每个质谱返回的最大匹配数
    nist_search_timeout: float = 120.0   # NIST 搜索等待超时(秒)

    # ---------- 峰检测与积分参数 ----------
    peak_smoothing_window: int = 11        # Savitzky-Golay 平滑窗口 (奇数)
    peak_prominence: float = 5000.0        # TIC 峰检测最小 prominence
    peak_min_distance: int = 5             # 相邻峰最小距离 (数据点数)
    peak_width_rel_height: float = 0.95    # 峰宽计算的相对高度 (0-1)
    fid_peak_prominence: float = 0.5       # FID 峰检测最小 prominence (FID 信号较小)
    fid_peak_min_distance: int = 50        # FID 相邻峰最小距离 (FID 采样率更高)

    # ---------- 积分报告输出目录 ----------
    report_dir: Path = field(
        default_factory=lambda: Path(__file__).parent.parent / "data"
    )

    @staticmethod
    def from_env() -> "Settings":
        """
        功能:
            从环境变量读取配置, 便于部署与 CI.
        参数:
            无.
        返回:
            Settings.
        环境变量:
            ANALYSIS_GC_MS_HOST, ANALYSIS_GC_MS_PORT, ANALYSIS_GC_MS_TIMEOUT,
            ANALYSIS_UPLC_QTOF_HOST, ANALYSIS_UPLC_QTOF_PORT, ANALYSIS_UPLC_QTOF_TIMEOUT,
            ANALYSIS_HPLC_HOST, ANALYSIS_HPLC_PORT, ANALYSIS_HPLC_TIMEOUT,
            ANALYSIS_GC_MS_DATA_DIR, ANALYSIS_UPLC_QTOF_DATA_DIR, ANALYSIS_HPLC_DATA_DIR,
            ANALYSIS_SYNTHESIS_TASKS_DIR, ANALYSIS_DATA_DIR, ANALYSIS_LOG_LEVEL.
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
            val = os.getenv(key)
            return Path(val) if val else default

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
            report_dir=_path("ANALYSIS_REPORT_DIR", defaults.report_dir),
            nist_path=_path("ANALYSIS_NIST_PATH", defaults.nist_path),
            nist_max_hits=_int("ANALYSIS_NIST_MAX_HITS", defaults.nist_max_hits),
            nist_search_timeout=_float("ANALYSIS_NIST_SEARCH_TIMEOUT", defaults.nist_search_timeout),
        )


def configure_logging(level: str = "INFO") -> None:
    """
    功能:
        配置全局 logging, 统一输出格式.
    参数:
        level: 日志级别, 例如 "DEBUG", "INFO".
    返回:
        无.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(numeric_level)

    if not root.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        root.addHandler(handler)
