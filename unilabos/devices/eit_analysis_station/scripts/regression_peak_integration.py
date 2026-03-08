#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    对 robust_v2 积分方案执行快速回归检查.
    覆盖合成漂移基线场景和本地 725 样本目录场景.
参数:
    --data-root: 725 数据目录, 默认 eit_analysis_station/data/725.
返回:
    进程退出码, 0 表示通过, 1 表示失败.
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import List

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from unilabos.devices.eit_analysis_station.processor.data_reader import GCMSDataReader
from unilabos.devices.eit_analysis_station.processor.peak_integrator import PeakIntegrator, PeakResult

logger = logging.getLogger(__name__)


def _build_integrator(prominence: float, min_distance: int) -> PeakIntegrator:
    """
    功能:
        构造 robust_v2 积分器.
    参数:
        prominence: 峰检测 prominence.
        min_distance: 峰最小间距.
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


def _gaussian(times: np.ndarray, center: float, sigma: float, amplitude: float) -> np.ndarray:
    """
    功能:
        生成高斯峰信号.
    参数:
        times: 时间数组.
        center: 中心时间.
        sigma: 峰宽参数.
        amplitude: 峰高.
    返回:
        np.ndarray.
    """
    return amplitude * np.exp(-0.5 * ((times - center) / sigma) ** 2)


def _closest_peak(peaks: List[PeakResult], target_rt: float) -> PeakResult:
    """
    功能:
        找到最接近目标保留时间的峰.
    参数:
        peaks: 峰列表.
        target_rt: 目标保留时间.
    返回:
        PeakResult.
    """
    return min(peaks, key=lambda item: abs(item.retention_time - target_rt))


def run_synthetic_regression() -> bool:
    """
    功能:
        执行合成漂移基线回归.
    参数:
        无.
    返回:
        bool, True 表示通过.
    """
    rng = np.random.default_rng(77)
    times = np.arange(4.0, 10.0, 0.01)

    baseline = (
        2.8e4
        + 4.2e3 * np.sin((times - 4.0) * 0.9)
        + 1.5e4 * np.exp(-0.5 * ((times - 7.0) / 1.2) ** 2)
    )
    big_peak = _gaussian(times, center=6.85, sigma=0.006, amplitude=2.8e6)
    tail = np.where(times >= 6.95, 6.5e4 * np.exp(-(times - 6.95) / 0.6), 0.0)
    small_peak = _gaussian(times, center=6.98, sigma=0.012, amplitude=1.5e5)
    signal = baseline + big_peak + tail + small_peak + rng.normal(0.0, 1200.0, size=len(times))

    integrator = _build_integrator(prominence=50000.0, min_distance=5)
    peaks = integrator.integrate(times, signal)
    if len(peaks) < 2:
        logger.error("合成回归失败: 检测峰数量不足, count=%d", len(peaks))
        return False

    near_peak = _closest_peak(peaks, target_rt=6.98)
    if near_peak.width >= 0.80:
        logger.error(
            "合成回归失败: 6.98 分钟附近峰宽异常, width=%.3f min",
            near_peak.width,
        )
        return False

    logger.info("合成回归通过: near_rt=%.3f, width=%.3f", near_peak.retention_time, near_peak.width)
    return True


def run_725_regression(data_root: Path) -> bool:
    """
    功能:
        对 725 目录下可用 .D 样本执行回归检查.
    参数:
        data_root: 725 数据目录.
    返回:
        bool, True 表示通过.
    """
    if not data_root.is_dir():
        logger.warning("目录不存在, 跳过 725 回归: %s", data_root)
        return True

    d_dirs = sorted([item for item in data_root.glob("*.D") if item.is_dir()])
    if len(d_dirs) == 0:
        logger.warning("未找到 .D 样本, 跳过 725 回归: %s", data_root)
        return True

    reader = GCMSDataReader()
    integrator = _build_integrator(prominence=50000.0, min_distance=5)

    all_ok = True
    for d_dir in d_dirs:
        times, intensities = reader.read_tic(d_dir)
        peaks = integrator.integrate(times, intensities)

        filtered = [item for item in peaks if 4.0 <= item.retention_time <= 10.0]
        if len(filtered) == 0:
            logger.warning("样本 %s 在 4-10 min 未检出峰", d_dir.name)
            continue

        max_width = max(item.width for item in filtered)
        logger.info("样本 %s 峰数=%d, 最大峰宽=%.3f", d_dir.name, len(filtered), max_width)
        if max_width > 0.80:
            logger.error("样本 %s 出现异常超宽峰: %.3f min", d_dir.name, max_width)
            all_ok = False

    return all_ok


def main() -> int:
    """
    功能:
        程序入口.
    参数:
        无.
    返回:
        int, 进程退出码.
    """
    parser = argparse.ArgumentParser(description="robust_v2 积分回归检查")
    parser.add_argument(
        "--data-root",
        type=Path,
        default=PROJECT_ROOT / "eit_analysis_station" / "data" / "725",
        help="725 数据目录路径",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )

    ok_synthetic = run_synthetic_regression()
    ok_725 = run_725_regression(args.data_root)

    if ok_synthetic and ok_725:
        logger.info("回归检查全部通过.")
        return 0

    logger.error("回归检查失败.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
