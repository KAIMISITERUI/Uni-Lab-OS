#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    对色谱信号 (TIC 或 FID) 执行峰检测与积分.
    使用 Savitzky-Golay 平滑去噪, scipy.signal.find_peaks 检测峰,
    scipy.signal.peak_widths 计算峰边界, 梯形法计算峰面积.
参数:
    无.
返回:
    无.
"""

import logging
from dataclasses import dataclass, field
from typing import List

import numpy as np
from scipy.signal import find_peaks, peak_widths, savgol_filter

logger = logging.getLogger(__name__)


@dataclass
class PeakResult:
    """
    功能:
        存储单个色谱峰的检测与积分结果.
    参数:
        peak_index: 峰顶在原始数据中的索引.
        retention_time: 保留时间 (min).
        height: 峰高 (强度值).
        area: 峰面积 (梯形积分).
        area_percent: 面积百分比 (%).
        start_time: 峰起始时间 (min).
        end_time: 峰结束时间 (min).
        width: 峰宽 (min).
    返回:
        PeakResult.
    """
    peak_index: int
    retention_time: float
    height: float
    area: float
    area_percent: float = 0.0
    start_time: float = 0.0
    end_time: float = 0.0
    width: float = 0.0


class PeakIntegrator:
    """
    功能:
        对单个色谱信号执行峰检测与积分.
        支持 TIC (高强度整数信号) 和 FID (低强度浮点信号) 两种信号类型.
    参数:
        smoothing_window: Savitzky-Golay 平滑窗口大小 (奇数).
        prominence: 峰检测最小突出度.
        min_distance: 相邻峰最小距离 (数据点数).
        width_rel_height: 峰宽计算的相对高度 (0-1, 越接近1越靠近基线).
    返回:
        无.
    """

    def __init__(
        self,
        smoothing_window: int = 11,
        prominence: float = 5000.0,
        min_distance: int = 5,
        width_rel_height: float = 0.95,
    ):
        # 确保窗口为奇数
        self._smoothing_window = smoothing_window if smoothing_window % 2 == 1 else smoothing_window + 1
        self._prominence = prominence
        self._min_distance = min_distance
        self._width_rel_height = width_rel_height

    def integrate(
        self, times: np.ndarray, intensities: np.ndarray
    ) -> List[PeakResult]:
        """
        功能:
            执行完整的峰检测与积分流程:
            1. Savitzky-Golay 平滑去噪
            2. find_peaks 检测峰
            3. peak_widths 计算峰边界
            4. 梯形积分计算峰面积
            5. 计算面积百分比
        参数:
            times: 保留时间数组, shape (n,).
            intensities: 信号强度数组, shape (n,).
        返回:
            List[PeakResult]: 检测到的峰列表, 按保留时间排序.
        """
        if len(times) < self._smoothing_window:
            logger.warning("数据点数 %d 少于平滑窗口 %d, 跳过积分",
                           len(times), self._smoothing_window)
            return []

        # 步骤1: Savitzky-Golay 平滑
        smoothed = savgol_filter(intensities, self._smoothing_window, polyorder=3)

        # 步骤2: 峰检测
        peak_indices, properties = find_peaks(
            smoothed,
            prominence=self._prominence,
            distance=self._min_distance,
        )

        if len(peak_indices) == 0:
            logger.info("未检测到峰 (prominence=%.0f)", self._prominence)
            return []

        logger.info("检测到 %d 个峰", len(peak_indices))

        # 步骤3: 计算峰宽和边界
        widths, width_heights, left_ips, right_ips = peak_widths(
            smoothed, peak_indices, rel_height=self._width_rel_height
        )

        # 步骤4: 逐峰计算面积
        results: List[PeakResult] = []
        for i, peak_idx in enumerate(peak_indices):
            # 将插值的左右边界索引转换为整数索引
            left_idx = max(0, int(np.floor(left_ips[i])))
            right_idx = min(len(times) - 1, int(np.ceil(right_ips[i])))

            # 梯形积分: 在原始信号上计算(未平滑), 时间轴做x
            peak_times = times[left_idx:right_idx + 1]
            peak_intensities = intensities[left_idx:right_idx + 1]

            # 基线估计: 使用峰左右端点连线作为基线
            if len(peak_times) >= 2:
                baseline = np.linspace(
                    peak_intensities[0], peak_intensities[-1], len(peak_times)
                )
                corrected = peak_intensities - baseline
                corrected = np.maximum(corrected, 0)  # 负值置零
                area = float(np.trapz(corrected, peak_times))
            else:
                area = 0.0

            # 峰宽: 用时间轴换算
            peak_width_min = float(times[right_idx] - times[left_idx]) if right_idx > left_idx else 0.0

            results.append(PeakResult(
                peak_index=int(peak_idx),
                retention_time=float(times[peak_idx]),
                height=float(intensities[peak_idx]),
                area=area,
                start_time=float(times[left_idx]),
                end_time=float(times[right_idx]),
                width=peak_width_min,
            ))

        # 步骤5: 计算面积百分比
        total_area = sum(p.area for p in results)
        if total_area > 0:
            for p in results:
                p.area_percent = (p.area / total_area) * 100.0

        logger.info("积分完成: %d 个峰, 总面积: %.2f", len(results), total_area)
        return results
