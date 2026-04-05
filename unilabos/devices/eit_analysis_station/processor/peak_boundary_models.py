#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    峰边界识别内部数据结构, 持有质量评分、证据、告警标记,
    并提供 PeakBoundary -> PeakResult 的转换适配.

参数:
    无.

返回:
    无.
"""

import logging
from dataclasses import dataclass, field
from typing import List

import numpy as np

from eit_analysis_station.processor.peak_integrator import PeakResult

logger = logging.getLogger(__name__)


@dataclass
class PeakBoundaryEvidence:
    """
    功能:
        记录峰边界识别过程中的拟合证据.

    参数:
        fit_score: 拟合优度 (0~1), 越高越好.
        area_stability: 面积对边界微扰的稳定性 (0~1).

    返回:
        无.
    """

    fit_score: float = 0.0
    area_stability: float = 0.0


@dataclass
class PeakBoundaryQuality:
    """
    功能:
        峰边界的质量评分汇总.

    参数:
        quality_score: 综合质量分数 (0~1).
        boundary_confidence: 边界位置置信度 (0~1).
        split_confidence: 拆峰置信度 (0~1), 单峰时为 0.
        manual_review: 是否需要人工复核.

    返回:
        无.
    """

    quality_score: float = 0.0
    boundary_confidence: float = 0.0
    split_confidence: float = 0.0
    manual_review: bool = False


@dataclass
class PeakBoundary:
    """
    功能:
        单个峰的边界描述, 包含索引/时间/面积以及质量评估信息.

    参数:
        peak_id: 峰编号 (1-based).
        detector: 检测器类型, "fid" 或 "gcms_tic".
        start_idx: 起始扫描索引.
        apex_idx: 峰顶扫描索引.
        end_idx: 结束扫描索引.
        start_time: 起始保留时间 (min).
        apex_time: 峰顶保留时间 (min).
        end_time: 结束保留时间 (min).
        height: 峰高.
        area: 峰面积.
        evidence: 拟合证据.
        quality: 质量评分.
        flags: 标记列表, 如 "fid_fit_ok", "gcms_multidim" 等.

    返回:
        无.
    """

    peak_id: int
    detector: str
    start_idx: int
    apex_idx: int
    end_idx: int
    start_time: float
    apex_time: float
    end_time: float
    height: float
    area: float
    evidence: PeakBoundaryEvidence = field(default_factory=PeakBoundaryEvidence)
    quality: PeakBoundaryQuality = field(default_factory=PeakBoundaryQuality)
    flags: List[str] = field(default_factory=list)

    def to_peak_result(self) -> PeakResult:
        """
        功能:
            将内部 PeakBoundary 转换为现有 PeakResult 契约.

        参数:
            无.

        返回:
            PeakResult, area_percent 默认为 0.0, 由 PeakDetectionResult 批量补全.
        """
        return PeakResult(
            peak_index=self.apex_idx,
            retention_time=self.apex_time,
            height=self.height,
            area=self.area,
            area_percent=0.0,
            start_time=self.start_time,
            end_time=self.end_time,
            width=round(self.end_time - self.start_time, 10),
        )


@dataclass
class PeakDetectionTrace:
    """
    功能:
        检测过程的诊断跟踪信息, 包含基线等中间结果.

    参数:
        baseline: 基线数组, shape 与输入信号相同.

    返回:
        无.
    """

    baseline: np.ndarray = field(default_factory=lambda: np.array([]))


@dataclass
class PeakDetectionResult:
    """
    功能:
        峰边界检测的完整结果, 包含所有峰和诊断信息.

    参数:
        detector: 检测器类型.
        peaks: 峰边界列表.
        trace: 诊断跟踪信息.

    返回:
        无.
    """

    detector: str
    peaks: List[PeakBoundary] = field(default_factory=list)
    trace: PeakDetectionTrace = field(default_factory=PeakDetectionTrace)

    def to_peak_results(self) -> List[PeakResult]:
        """
        功能:
            批量转换为 PeakResult 并计算 area_percent.

        参数:
            无.

        返回:
            List[PeakResult], 各峰 area_percent 之和为 100.0.
        """
        results = [peak.to_peak_result() for peak in self.peaks]
        total_area = sum(r.area for r in results)
        if total_area > 0:
            for r in results:
                r.area_percent = (r.area / total_area) * 100.0
        return results
