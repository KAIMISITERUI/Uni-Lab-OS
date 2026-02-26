#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    peak_integrator 的 robust_v2 回归测试.
参数:
    无.
返回:
    无.
"""

import unittest
from pathlib import Path

import numpy as np

from eit_analysis_station.processor.data_reader import GCMSDataReader
from eit_analysis_station.processor.peak_integrator import PeakIntegrator


def _gaussian(times: np.ndarray, center: float, sigma: float, amplitude: float) -> np.ndarray:
    """
    功能:
        生成高斯峰.
    参数:
        times: 时间数组.
        center: 峰中心.
        sigma: 峰宽参数.
        amplitude: 峰高.
    返回:
        np.ndarray, 峰信号.
    """
    return amplitude * np.exp(-0.5 * ((times - center) / sigma) ** 2)


def _find_closest_peak(peaks, target_rt: float):
    """
    功能:
        从峰列表中找到最接近目标保留时间的峰.
    参数:
        peaks: PeakResult 列表.
        target_rt: 目标保留时间.
    返回:
        PeakResult.
    """
    return min(peaks, key=lambda item: abs(item.retention_time - target_rt))


def _build_integrator(prominence: float, min_distance: int) -> PeakIntegrator:
    """
    功能:
        构造 robust_v2 积分器.
    参数:
        prominence: 峰检测 prominence.
        min_distance: 峰间最小距离.
    返回:
        PeakIntegrator.
    """
    return PeakIntegrator(
        smoothing_window=11,
        prominence=prominence,
        min_distance=min_distance,
        integration_mode="robust_v2",
        baseline_method="rolling_quantile",
        baseline_quantile=20.0,
        baseline_window_min=0.9,
        boundary_sigma_factor=3.0,
        boundary_edge_ratio=0.01,
        boundary_expand_factor=6.0,
        boundary_min_span_min=0.08,
        boundary_max_span_min=0.80,
    )


class TestPeakIntegratorRobust(unittest.TestCase):
    """
    功能:
        robust_v2 的关键场景测试集.
    参数:
        无.
    返回:
        无.
    """

    def test_robust_v2_handles_drifting_baseline_narrow_peak(self) -> None:
        """
        功能:
            验证漂移基线场景下窄峰不会被积分成宽峰.
        参数:
            无.
        返回:
            无.
        """
        rng = np.random.default_rng(7)
        times = np.arange(4.0, 10.0, 0.01)

        baseline = (
            2.6e4
            + 4.5e3 * np.sin((times - 4.0) * 0.8)
            + 1.8e4 * np.exp(-0.5 * ((times - 7.1) / 1.1) ** 2)
        )
        signal = baseline + _gaussian(times, center=6.85, sigma=0.006, amplitude=2.5e6)
        signal = signal + rng.normal(0.0, 1200.0, size=len(times))

        integrator = _build_integrator(prominence=50000.0, min_distance=5)
        peaks = integrator.integrate(times, signal)

        self.assertGreaterEqual(len(peaks), 1)
        target_peak = _find_closest_peak(peaks, target_rt=6.85)
        self.assertLess(abs(target_peak.retention_time - 6.85), 0.03)
        self.assertLess(target_peak.width, 0.20)
        self.assertGreater(target_peak.start_time, 6.70)
        self.assertLess(target_peak.end_time, 6.98)

    def test_robust_v2_limits_tail_peak_boundary(self) -> None:
        """
        功能:
            验证强峰拖尾背景下边界不会扩展到分钟级宽峰.
        参数:
            无.
        返回:
            无.
        """
        rng = np.random.default_rng(19)
        times = np.arange(4.0, 10.0, 0.01)

        baseline = 3.0e4 + 3.0e3 * np.sin((times - 4.0) * 0.7)
        big_peak = _gaussian(times, center=6.85, sigma=0.006, amplitude=3.0e6)
        tail = np.where(times >= 6.95, 7.0e4 * np.exp(-(times - 6.95) / 0.6), 0.0)
        small_peak = _gaussian(times, center=6.98, sigma=0.012, amplitude=1.6e5)
        signal = baseline + big_peak + tail + small_peak + rng.normal(0.0, 1200.0, size=len(times))

        integrator = _build_integrator(prominence=50000.0, min_distance=5)
        peaks = integrator.integrate(times, signal)

        self.assertGreaterEqual(len(peaks), 2)
        tail_peak = _find_closest_peak(peaks, target_rt=6.98)
        self.assertLess(abs(tail_peak.retention_time - 6.98), 0.05)
        self.assertLess(tail_peak.width, 0.80)

    def test_robust_v2_respects_neighbor_midpoint_boundary(self) -> None:
        """
        功能:
            验证邻近双峰时边界不会越过峰间中点.
        参数:
            无.
        返回:
            无.
        """
        rng = np.random.default_rng(202)
        times = np.arange(6.2, 7.4, 0.005)

        baseline = 2.2e4 + 1500.0 * np.sin((times - 6.2) * 1.1)
        peak_1 = _gaussian(times, center=6.80, sigma=0.010, amplitude=2.2e5)
        peak_2 = _gaussian(times, center=6.86, sigma=0.010, amplitude=2.0e5)
        signal = baseline + peak_1 + peak_2 + rng.normal(0.0, 700.0, size=len(times))

        integrator = _build_integrator(prominence=20000.0, min_distance=4)
        peaks = sorted(integrator.integrate(times, signal), key=lambda item: item.retention_time)

        self.assertGreaterEqual(len(peaks), 2)
        left_peak = peaks[0]
        right_peak = peaks[1]
        midpoint_time = (left_peak.retention_time + right_peak.retention_time) / 2.0

        self.assertLessEqual(left_peak.end_time, midpoint_time + 0.01)
        self.assertGreaterEqual(right_peak.start_time, midpoint_time - 0.01)

    def test_robust_v2_stable_on_high_rate_fid_like_signal(self) -> None:
        """
        功能:
            验证高采样率 FID 类信号下参数换算稳定.
        参数:
            无.
        返回:
            无.
        """
        rng = np.random.default_rng(33)
        times = np.arange(4.0, 5.2, 1.0 / 3000.0)

        baseline = 0.20 + 0.02 * np.sin((times - 4.0) * 5.0)
        peak_a = _gaussian(times, center=4.35, sigma=0.008, amplitude=0.9)
        peak_b = _gaussian(times, center=4.90, sigma=0.010, amplitude=0.8)
        signal = baseline + peak_a + peak_b + rng.normal(0.0, 0.02, size=len(times))

        integrator = _build_integrator(prominence=0.5, min_distance=50)
        peaks = integrator.integrate(times, signal)

        self.assertGreaterEqual(len(peaks), 2)
        for item in peaks:
            self.assertLess(item.width, 0.40)

    def test_robust_v2_regression_for_725_sample_if_available(self) -> None:
        """
        功能:
            使用本地 725 样本做回归, 防止再次出现超宽误积分.
        参数:
            无.
        返回:
            无.
        """
        d_dir = Path(__file__).resolve().parents[1] / "data" / "725" / "725-1.D"
        if not d_dir.is_dir():
            self.skipTest("未找到 725-1.D 样本, 跳过回归测试.")

        times, intensities = GCMSDataReader().read_tic(d_dir)
        integrator = _build_integrator(prominence=50000.0, min_distance=5)
        peaks = integrator.integrate(times, intensities)

        near_peak = _find_closest_peak(peaks, target_rt=6.98)
        self.assertLess(abs(near_peak.retention_time - 6.98), 0.08)
        self.assertLess(near_peak.width, 0.25)


if __name__ == "__main__":
    unittest.main()