#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    峰边界识别器, 提供 GC-MS 多维边界识别和 FID 局部拟合边界识别.
    通过工厂模式按检测器类型路由到具体实现.

参数:
    无.

返回:
    无.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np
from scipy import sparse
from scipy.signal import find_peaks, savgol_filter, argrelmin
from scipy.sparse.linalg import spsolve

from eit_analysis_station.processor.peak_boundary_models import (
    PeakBoundary,
    PeakBoundaryEvidence,
    PeakBoundaryQuality,
    PeakDetectionResult,
    PeakDetectionTrace,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

@dataclass
class PeakBoundaryDetectorConfig:
    """
    功能:
        峰边界识别器的全部配置参数.

    参数:
        smoothing_window: 预处理 SG 平滑窗口 (点数, 奇数).
        gcms_*: GC-MS 分支参数.
        fid_*: FID 分支参数.

    返回:
        无.
    """

    # 公共
    smoothing_window: int = 11

    # GC-MS
    gcms_seed_prominence: float = 30000.0
    gcms_seed_min_distance: int = 15
    gcms_feature_ion_min_count: int = 3
    gcms_feature_ion_max_count: int = 15
    gcms_spectral_similarity_threshold: float = 0.85
    gcms_ratio_cv_threshold: float = 0.30
    gcms_component_gap_min_scans: int = 15
    gcms_boundary_low_score_threshold: float = 0.15
    gcms_boundary_high_score_threshold: float = 0.50

    # FID
    fid_candidate_prominence: float = 0.5
    fid_candidate_min_distance: int = 50
    fid_fit_max_components: int = 4
    fid_fit_bic_improve_min: float = 2.0
    fid_boundary_rel_height: float = 0.005
    fid_boundary_abs_noise_factor: float = 3.0
    fid_baseline_method: str = "arpls"


# ---------------------------------------------------------------------------
# 输入
# ---------------------------------------------------------------------------

@dataclass
class PeakDetectionInput:
    """
    功能:
        峰边界检测的输入数据.

    参数:
        detector: 检测器类型, "fid" 或 "gcms_tic".
        times: 保留时间数组.
        signal: 信号强度数组.
        ms_matrix: GC-MS 原始强度矩阵 (n_scans, n_mz), 可选.
        mz_axis: m/z 轴 (n_mz,), 可选.

    返回:
        无.
    """

    detector: str
    times: np.ndarray
    signal: np.ndarray
    ms_matrix: Optional[np.ndarray] = None
    mz_axis: Optional[np.ndarray] = None


@dataclass
class FIDFittingWindow:
    """
    功能:
        描述 FID 单个色谱事件窗口.
        一个窗口可包含一个或多个 primary seed, 以及仅用于提示分峰的 split hint.

    参数:
        start_idx: 窗口起始全局索引, 包含该点.
        end_idx: 窗口结束全局索引, 不包含该点.
        primary_indices: 窗口内 primary seed 全局索引数组.
        split_hint_indices: 窗口内 split hint 全局索引数组.

    返回:
        无.
    """

    start_idx: int
    end_idx: int
    primary_indices: np.ndarray = field(default_factory=lambda: np.array([], dtype=int))
    split_hint_indices: np.ndarray = field(default_factory=lambda: np.array([], dtype=int))


# ---------------------------------------------------------------------------
# 抽象基类
# ---------------------------------------------------------------------------

class BasePeakBoundaryDetector(ABC):
    """
    功能:
        峰边界检测器抽象基类.

    参数:
        config: 检测器配置.

    返回:
        无.
    """

    def __init__(self, config: PeakBoundaryDetectorConfig) -> None:
        self.config = config

    @abstractmethod
    def detect(self, inp: PeakDetectionInput) -> PeakDetectionResult:
        """
        功能:
            执行峰边界检测.

        参数:
            inp: 检测输入数据.

        返回:
            PeakDetectionResult.
        """
        ...


# ---------------------------------------------------------------------------
# 公共工具函数
# ---------------------------------------------------------------------------

def _estimate_noise_std(signal: np.ndarray, window: int = 15) -> float:
    """
    功能:
        基于 SG 平滑残差的 MAD 估计噪声标准差.

    参数:
        signal: 输入信号.
        window: SG 平滑窗口.

    返回:
        float, 噪声标准差估计.
    """
    win = min(window, len(signal))
    if win % 2 == 0:
        win = max(win - 1, 3)
    smooth = savgol_filter(signal, win, min(3, win - 1))
    residual = signal - smooth
    return float(1.4826 * np.median(np.abs(residual)))


def _hampel_filter(signal: np.ndarray, half_window: int = 3, threshold: float = 3.0) -> np.ndarray:
    """
    功能:
        Hampel 滤波器去除尖峰噪声.

    参数:
        signal: 输入信号.
        half_window: 半窗口大小.
        threshold: MAD 倍数阈值.

    返回:
        np.ndarray, 去尖峰后的信号.
    """
    result = signal.copy()
    n = len(signal)
    for i in range(half_window, n - half_window):
        window = signal[i - half_window:i + half_window + 1]
        med = np.median(window)
        mad = 1.4826 * np.median(np.abs(window - med))
        if mad > 0 and abs(signal[i] - med) > threshold * mad:
            result[i] = med
    return result


def _rolling_percentile_baseline(signal: np.ndarray, times: np.ndarray,
                                  window_min: float = 0.9,
                                  quantile: float = 20.0) -> np.ndarray:
    """
    功能:
        滚动分位数基线估计.

    参数:
        signal: 输入信号.
        times: 时间轴.
        window_min: 窗口宽度 (min).
        quantile: 分位数百分比.

    返回:
        np.ndarray, 基线估计.
    """
    dt = np.median(np.diff(times)) if len(times) > 1 else 1.0
    half_win = max(1, int(window_min / dt / 2))
    n = len(signal)
    baseline = np.empty(n)
    for i in range(n):
        lo = max(0, i - half_win)
        hi = min(n, i + half_win + 1)
        baseline[i] = np.percentile(signal[lo:hi], quantile)
    return baseline


# ---------------------------------------------------------------------------
# FID 检测器
# ---------------------------------------------------------------------------

def _solve_whittaker_baseline(
    signal: np.ndarray,
    lam: float,
    weight_updater,
    weights: Optional[np.ndarray] = None,
    max_iter: int = 50,
    tol: float = 1e-6,
) -> np.ndarray:
    """
    功能:
        使用 Whittaker 惩罚项求解迭代加权基线.

    参数:
        signal: 输入信号.
        lam: 平滑惩罚系数.
        weight_updater: 根据残差更新自适应权重的函数.
        weights: 外部固定权重, 用于第二阶段抑制峰区.
        max_iter: 最大迭代次数.
        tol: 权重收敛阈值.

    返回:
        np.ndarray, 基线数组.
    """
    length = len(signal)
    if length < 3:
        return signal.astype(float, copy=True)

    diff_matrix = sparse.diags(
        diagonals=[1.0, -2.0, 1.0],
        offsets=[0, 1, 2],
        shape=(length - 2, length),
        format="csc",
    )
    penalty = float(lam) * (diff_matrix.T @ diff_matrix)

    external_weights = np.ones(length, dtype=float)
    if weights is not None:
        external_weights = np.clip(np.asarray(weights, dtype=float), 1e-6, None)

    adaptive_weights = np.ones(length, dtype=float)
    baseline = signal.astype(float, copy=True)

    for _ in range(max_iter):
        combined_weights = np.clip(external_weights * adaptive_weights, 1e-6, None)
        weight_matrix = sparse.diags(combined_weights, 0, shape=(length, length), format="csc")
        baseline = spsolve(weight_matrix + penalty, combined_weights * signal)

        residual = signal - baseline
        new_adaptive_weights = np.clip(
            np.asarray(weight_updater(residual), dtype=float),
            1e-6,
            1.0,
        )

        denominator = max(float(np.linalg.norm(adaptive_weights)), 1e-12)
        delta = float(np.linalg.norm(new_adaptive_weights - adaptive_weights)) / denominator
        adaptive_weights = new_adaptive_weights
        if delta <= tol:
            break

    return np.asarray(baseline, dtype=float)


def _asls_baseline(
    signal: np.ndarray,
    lam: float = 1e6,
    p: float = 0.01,
    weights: Optional[np.ndarray] = None,
) -> np.ndarray:
    """
    功能:
        使用 AsLS 估计基线.

    参数:
        signal: 输入信号.
        lam: 平滑惩罚系数.
        p: 正残差权重.
        weights: 外部固定权重.

    返回:
        np.ndarray, 基线数组.
    """

    def _update(residual: np.ndarray) -> np.ndarray:
        return np.where(residual > 0.0, float(p), 1.0 - float(p))

    return _solve_whittaker_baseline(
        signal=signal,
        lam=lam,
        weight_updater=_update,
        weights=weights,
        max_iter=25,
        tol=1e-6,
    )


def _arpls_baseline(
    signal: np.ndarray,
    lam: float = 1e6,
    weights: Optional[np.ndarray] = None,
) -> np.ndarray:
    """
    功能:
        使用 arPLS 估计基线.

    参数:
        signal: 输入信号.
        lam: 平滑惩罚系数.
        weights: 外部固定权重.

    返回:
        np.ndarray, 基线数组.
    """

    def _update(residual: np.ndarray) -> np.ndarray:
        negative = residual[residual < 0.0]
        if len(negative) == 0:
            return np.ones_like(residual)

        mean_negative = float(np.mean(negative))
        std_negative = float(np.std(negative))
        if std_negative <= 1e-12:
            return np.ones_like(residual)

        exponent = 2.0 * (residual - (2.0 * std_negative - mean_negative)) / std_negative
        exponent = np.clip(exponent, -60.0, 60.0)
        return 1.0 / (1.0 + np.exp(exponent))

    return _solve_whittaker_baseline(
        signal=signal,
        lam=lam,
        weight_updater=_update,
        weights=weights,
        max_iter=50,
        tol=1e-6,
    )


class FIDPeakBoundaryDetector(BasePeakBoundaryDetector):
    """
    功能:
        FID 色谱峰边界识别器.
        基线校正 -> 候选峰检测 -> 局部 EMG 拟合 -> 边界精修.

    参数:
        config: 检测器配置.

    返回:
        无.
    """

    def detect(self, inp: PeakDetectionInput) -> PeakDetectionResult:
        """
        功能:
            对 FID 信号执行峰边界检测.

        参数:
            inp: 检测输入数据.

        返回:
            PeakDetectionResult.
        """
        times = inp.times
        signal = inp.signal
        n = len(times)
        cfg = self.config

        # Step 1: 去尖峰
        cleaned = _hampel_filter(signal, half_window=3, threshold=3.0)

        # Step 2: 噪声估计
        noise_std = _estimate_noise_std(cleaned)
        if noise_std <= 0:
            noise_std = 1e-10

        # Step 3: 两阶段基线校正
        baseline = self._estimate_baseline(cleaned, noise_std, cfg)

        # 基线校正后信号
        y_bc = cleaned - baseline

        y_smooth = self._smooth_signal(y_bc, cfg.smoothing_window)

        # Step 4: primary seed 检测
        primary_candidates = self._detect_candidates(y_bc, times, noise_std, cfg)

        # Step 5: split hint 仅用于扩展窗口和提示是否尝试多组分拟合
        split_hints = self._detect_secondary_candidates(
            y_bc=y_bc,
            y_smooth=y_smooth,
            noise_std=noise_std,
            primary_candidates=primary_candidates,
            cfg=cfg,
        )

        if len(primary_candidates) == 0 and len(split_hints) == 0:
            logger.warning("FID 未检测到任何可用事件窗口")
            return PeakDetectionResult(
                detector="fid",
                peaks=[],
                trace=PeakDetectionTrace(baseline=baseline),
            )

        # Step 6: 先构建色谱事件窗口, 再由拟合结果决定是否真的分峰
        windows = self._build_fitting_windows(
            primary_candidates=primary_candidates,
            split_hints=split_hints,
            y_bc=y_bc,
            n=n,
            cfg=cfg,
            noise_std=noise_std,
        )
        boundaries = self._fit_and_refine(
            windows=windows,
            times=times,
            raw_signal=cleaned,
            y_bc=y_bc,
            y_smooth=y_smooth,
            noise_std=noise_std,
            cfg=cfg,
        )

        # 按 apex_time 排序
        boundaries.sort(key=lambda b: b.apex_time)

        # 重新编号
        for i, b in enumerate(boundaries):
            b.peak_id = i + 1

        return PeakDetectionResult(
            detector="fid",
            peaks=boundaries,
            trace=PeakDetectionTrace(baseline=baseline),
        )

    def _estimate_baseline(self, signal: np.ndarray, noise_std: float,
                            cfg: PeakBoundaryDetectorConfig) -> np.ndarray:
        """
        功能:
            两阶段基线校正: 粗校正 -> peak mask -> 加权重估.

        参数:
            signal: 去尖峰后的信号.
            noise_std: 噪声标准差.
            cfg: 配置.

        返回:
            np.ndarray, 基线数组.
        """
        baseline_func = _arpls_baseline if cfg.fid_baseline_method == "arpls" else _asls_baseline

        try:
            # 第一阶段: 粗校正
            baseline_1 = baseline_func(signal, lam=1e6)
            y_bc_1 = signal - baseline_1

            # 构建 peak mask
            peak_mask = y_bc_1 > 3.0 * noise_std

            # 第二阶段: 带权重重估
            weights = np.where(peak_mask, 0.01, 1.0)
            baseline_2 = baseline_func(signal, lam=1e6, weights=weights)
            return baseline_2
        except Exception as e:
            logger.warning("FID 基线校正失败, 回退到滚动最小值: %s", e)
            # 回退: 使用简单的滚动最小值
            from scipy.ndimage import minimum_filter1d
            win = max(51, len(signal) // 20)
            if win % 2 == 0:
                win += 1
            return minimum_filter1d(signal, size=win)

    @staticmethod
    def _has_close_seed(candidates: np.ndarray, seed_idx: int, min_dist: int) -> bool:
        """
        功能:
            判断给定种子是否与已有候选过近.

        参数:
            candidates: 已有候选峰索引.
            seed_idx: 待判断的种子索引.
            min_dist: 最小间距阈值.

        返回:
            bool, 是否存在过近候选.
        """
        if len(candidates) == 0:
            return False
        return bool(np.min(np.abs(candidates - int(seed_idx))) < int(min_dist))

    @staticmethod
    def _group_dense_seed_bands(seed_indices: List[int], min_dist: int) -> List[Tuple[int, int]]:
        """
        功能:
            将高密度二阶导种子压缩为候选带.

        参数:
            seed_indices: 二阶导种子索引列表.
            min_dist: 判定为同一候选带的最大间距.

        返回:
            List[Tuple[int, int]], 每项为候选带起止索引.
        """
        if len(seed_indices) == 0:
            return []

        bands: List[Tuple[int, int]] = []
        sorted_seeds = sorted(int(idx) for idx in seed_indices)
        band_start = sorted_seeds[0]
        band_end = sorted_seeds[0]

        for seed_idx in sorted_seeds[1:]:
            if seed_idx - band_end < int(min_dist):
                band_end = seed_idx
                continue
            bands.append((band_start, band_end))
            band_start = seed_idx
            band_end = seed_idx

        bands.append((band_start, band_end))
        return bands

    @staticmethod
    def _has_clear_valley_split(
        left_idx: int,
        right_idx: int,
        signal: np.ndarray,
        abs_threshold: float,
        rel_threshold: float = 0.72,
    ) -> bool:
        """
        功能:
            判断两个局部峰之间是否存在足够清晰的谷底分隔.

        参数:
            left_idx: 左侧峰索引.
            right_idx: 右侧峰索引.
            signal: 平滑后信号.
            abs_threshold: 谷底绝对深度阈值.
            rel_threshold: 谷底相对深度阈值.

        返回:
            bool, 是否允许拆成两个峰.
        """
        if right_idx - left_idx < 2:
            return False

        valley_idx = left_idx + int(np.argmin(signal[left_idx:right_idx + 1]))
        valley_depth = min(float(signal[left_idx]), float(signal[right_idx])) - float(signal[valley_idx])
        if valley_depth < float(abs_threshold):
            return False

        lower_peak_height = max(min(float(signal[left_idx]), float(signal[right_idx])), 1e-10)
        relative_depth = valley_depth / lower_peak_height
        return bool(relative_depth >= float(rel_threshold))

    def _extract_secondary_candidates_from_band(
        self,
        band_start: int,
        band_end: int,
        y_smooth: np.ndarray,
        primary_candidates: np.ndarray,
        noise_std: float,
        cfg: PeakBoundaryDetectorConfig,
    ) -> List[int]:
        """
        功能:
            从单个高密度二阶导候选带中提取补候选峰.

        参数:
            band_start: 候选带起点索引.
            band_end: 候选带终点索引.
            y_smooth: 平滑后信号.
            primary_candidates: 主检测候选峰.
            noise_std: 噪声标准差.
            cfg: 配置.

        返回:
            List[int], 补候选峰索引列表.
        """
        min_dist = int(cfg.fid_candidate_min_distance)
        margin = max(3, min_dist // 2)
        left = max(0, int(band_start) - margin)
        right = min(len(y_smooth) - 1, int(band_end) + margin)

        band_signal = y_smooth[left:right + 1]
        if len(band_signal) == 0:
            return []

        band_max_height = float(np.max(band_signal))
        prominence_floor = max(
            2.0 * float(noise_std),
            min(0.12, 0.20 * band_max_height),
        )
        local_peak_distance = max(3, min_dist // 3)
        local_peak_indices, _ = find_peaks(
            band_signal,
            prominence=prominence_floor,
            distance=local_peak_distance,
        )

        if len(local_peak_indices) == 0:
            dominant_peak_idx = left + int(np.argmax(band_signal))
            return [dominant_peak_idx]

        global_peak_indices = [left + int(idx) for idx in local_peak_indices]
        dominant_peak_idx = max(
            global_peak_indices,
            key=lambda idx: float(y_smooth[idx]),
        )
        dominant_peak_height = max(float(y_smooth[dominant_peak_idx]), 1e-10)
        accepted: List[int] = [dominant_peak_idx]

        for peak_idx in global_peak_indices:
            if peak_idx == dominant_peak_idx:
                continue

            peak_height = float(y_smooth[peak_idx])
            if peak_height < 0.85 * dominant_peak_height:
                continue

            previous_idx = min(accepted, key=lambda idx: abs(idx - peak_idx))
            if self._has_clear_valley_split(
                min(previous_idx, peak_idx),
                max(previous_idx, peak_idx),
                y_smooth,
                abs_threshold=max(
                    2.0 * float(noise_std),
                    0.25 * dominant_peak_height,
                ),
            ) is True:
                accepted.append(peak_idx)

        return sorted(set(accepted))

    def _suppress_secondary_candidates(
        self,
        secondary_candidates: np.ndarray,
        y_smooth: np.ndarray,
        noise_std: float,
        cfg: PeakBoundaryDetectorConfig,
    ) -> np.ndarray:
        """
        功能:
            对 FID 补种子候选峰做邻域非极大值抑制, 避免同一条拖尾被拆成串状小峰.

        参数:
            secondary_candidates: 补种子候选峰索引.
            y_smooth: 平滑后的基线校正信号.
            noise_std: 噪声标准差.
            cfg: 检测配置.

        返回:
            np.ndarray, 抑制后的补种子候选峰索引.
        """
        if len(secondary_candidates) <= 1:
            return np.array(sorted(set(int(idx) for idx in secondary_candidates)), dtype=int)

        suppress_distance = max(
            int(cfg.fid_candidate_min_distance),
            int(cfg.fid_candidate_min_distance) * 6,
        )
        strength_ratio = 0.85
        sorted_candidates = sorted(
            set(int(idx) for idx in secondary_candidates),
            key=lambda idx: float(y_smooth[idx]),
            reverse=True,
        )

        kept: List[int] = []
        for candidate_idx in sorted_candidates:
            candidate_height = float(y_smooth[candidate_idx])
            suppressed = False

            for kept_idx in kept:
                if abs(candidate_idx - kept_idx) > suppress_distance:
                    continue

                kept_height = max(float(y_smooth[kept_idx]), 1e-10)
                if candidate_height >= strength_ratio * kept_height and self._has_clear_valley_split(
                    min(candidate_idx, kept_idx),
                    max(candidate_idx, kept_idx),
                    y_smooth,
                    abs_threshold=max(
                        2.0 * float(noise_std),
                        0.25 * kept_height,
                    ),
                ) is True:
                    continue

                suppressed = True
                break

            if suppressed is False:
                kept.append(candidate_idx)

        return np.array(sorted(set(kept)), dtype=int)

    def _detect_secondary_candidates(
        self,
        y_bc: np.ndarray,
        y_smooth: np.ndarray,
        noise_std: float,
        primary_candidates: np.ndarray,
        cfg: PeakBoundaryDetectorConfig,
    ) -> np.ndarray:
        """
        功能:
            生成 FID 的二阶导补候选峰, 并压缩拖尾区域的高密度假种子.

        参数:
            y_bc: 基线校正后信号.
            y_smooth: 平滑后信号.
            noise_std: 噪声标准差.
            primary_candidates: 主检测候选峰.
            cfg: 配置.

        返回:
            np.ndarray, 补候选峰索引数组.
        """
        d2 = np.gradient(np.gradient(y_smooth))
        try:
            d2_seeds = argrelmin(d2, order=5)[0]
        except Exception:
            return np.array([], dtype=int)

        filtered_seeds: List[int] = []
        min_dist = int(cfg.fid_candidate_min_distance)
        for seed_idx in d2_seeds:
            if y_bc[seed_idx] <= 2.0 * noise_std:
                continue
            if self._has_close_seed(primary_candidates, int(seed_idx), min_dist) is True:
                continue
            filtered_seeds.append(int(seed_idx))

        if len(filtered_seeds) == 0:
            return np.array([], dtype=int)

        secondary_candidates: List[int] = []
        for band_start, band_end in self._group_dense_seed_bands(filtered_seeds, min_dist):
            secondary_candidates.extend(
                self._extract_secondary_candidates_from_band(
                    band_start=band_start,
                    band_end=band_end,
                    y_smooth=y_smooth,
                    primary_candidates=primary_candidates,
                    noise_std=noise_std,
                    cfg=cfg,
                )
            )

        if len(secondary_candidates) == 0:
            return np.array([], dtype=int)

        return self._suppress_secondary_candidates(
            secondary_candidates=np.array(sorted(set(int(idx) for idx in secondary_candidates)), dtype=int),
            y_smooth=y_smooth,
            noise_std=noise_std,
            cfg=cfg,
        )

    @staticmethod
    def _merge_candidate_indices(
        primary_candidates: np.ndarray,
        secondary_candidates: np.ndarray,
        y_smooth: np.ndarray,
        min_dist: int,
    ) -> np.ndarray:
        """
        功能:
            合并主候选峰与补候选峰, 对近邻候选执行优先级去重.

        参数:
            primary_candidates: 主检测候选峰.
            secondary_candidates: 补检测候选峰.
            y_smooth: 平滑后信号.
            min_dist: 最小间距阈值.

        返回:
            np.ndarray, 合并后的候选峰索引数组.
        """
        entries = []
        for idx in primary_candidates:
            entries.append((int(idx), 0))
        for idx in secondary_candidates:
            entries.append((int(idx), 1))

        if len(entries) == 0:
            return np.array([], dtype=int)

        entries.sort(key=lambda item: item[0])
        merged: List[Tuple[int, int]] = []

        for idx, priority in entries:
            if len(merged) == 0:
                merged.append((idx, priority))
                continue

            previous_idx, previous_priority = merged[-1]
            if idx - previous_idx >= int(min_dist):
                merged.append((idx, priority))
                continue

            if priority < previous_priority:
                merged[-1] = (idx, priority)
                continue

            if priority > previous_priority:
                continue

            if y_smooth[idx] > y_smooth[previous_idx]:
                merged[-1] = (idx, priority)

        return np.array([idx for idx, _ in merged], dtype=int)

    def _threshold_valley_boundaries(self, candidates: np.ndarray,
                                       times: np.ndarray, y_bc: np.ndarray,
                                       noise_std: float,
                                       cfg: PeakBoundaryDetectorConfig) -> List[PeakBoundary]:
        """
        功能:
            对每个候选峰基于阈值和谷值搜索边界, 稳健且不依赖 LAPACK.

        参数:
            candidates: 候选峰索引.
            times: 时间轴.
            y_bc: 基线校正信号.
            noise_std: 噪声标准差.
            cfg: 配置.

        返回:
            List[PeakBoundary].
        """
        n = len(y_bc)
        boundaries = []

        # 计算候选峰间的谷值, 用作天然分界
        valleys = []
        for i in range(len(candidates) - 1):
            seg = y_bc[candidates[i]:candidates[i + 1] + 1]
            valley_idx = candidates[i] + int(np.argmin(seg))
            valleys.append(valley_idx)

        for i, peak_idx in enumerate(candidates):
            peak_height = float(y_bc[peak_idx])
            if peak_height < noise_std * 2:
                continue

            # 搜索阈值
            threshold = max(
                cfg.fid_boundary_rel_height * peak_height,
                cfg.fid_boundary_abs_noise_factor * noise_std,
            )

            # 左边界: 搜索至阈值或谷值
            left_limit = valleys[i - 1] if i > 0 else 0
            left = peak_idx
            for j in range(peak_idx - 1, left_limit - 1, -1):
                if y_bc[j] < threshold:
                    left = j
                    break
            else:
                left = left_limit

            # 右边界: 搜索至阈值或谷值
            right_limit = valleys[i] if i < len(valleys) else n - 1
            right = peak_idx
            for j in range(peak_idx + 1, right_limit + 1):
                if y_bc[j] < threshold:
                    right = j
                    break
            else:
                right = right_limit

            # snap 到最近谷值
            left = self._snap_to_valley(y_bc, left, peak_idx, "left")
            right = self._snap_to_valley(y_bc, right, peak_idx, "right")

            # 确保有序
            left = max(0, min(left, peak_idx - 1))
            right = min(n - 1, max(right, peak_idx + 1))

            # 面积 (梯形积分)
            area = float(np.trapz(
                np.maximum(y_bc[left:right + 1], 0.0),
                times[left:right + 1],
            ))

            boundaries.append(PeakBoundary(
                peak_id=i + 1,
                detector="fid",
                start_idx=left,
                apex_idx=peak_idx,
                end_idx=right,
                start_time=float(times[left]),
                apex_time=float(times[peak_idx]),
                end_time=float(times[right]),
                height=peak_height,
                area=max(area, 0.0),
                evidence=PeakBoundaryEvidence(fit_score=0.7, area_stability=0.8),
                quality=PeakBoundaryQuality(
                    quality_score=0.7,
                    boundary_confidence=0.7,
                    split_confidence=0.0,
                    manual_review=False,
                ),
                flags=["fid_fit_ok"],
            ))

        return boundaries

    def _try_emg_refinement(self, boundaries: List[PeakBoundary],
                             candidates: np.ndarray,
                             times: np.ndarray, y_bc: np.ndarray,
                             noise_std: float,
                             cfg: PeakBoundaryDetectorConfig) -> List[PeakBoundary]:
        """
        功能:
            尝试用 EMG 拟合精修边界. 拟合失败时保留原始边界.

        参数:
            boundaries: 已有的阈值边界.
            candidates: 候选峰索引.
            times: 时间轴.
            y_bc: 基线校正信号.
            noise_std: 噪声标准差.
            cfg: 配置.

        返回:
            List[PeakBoundary], 精修后或保持原始的边界.
        """
        if len(boundaries) == 0:
            return boundaries

        # 构建拟合窗口
        windows = self._build_fitting_windows(candidates, y_bc, len(times))

        refined = []
        for w_start, w_end, peak_indices in windows:
            t_w = times[w_start:w_end]
            y_w = y_bc[w_start:w_end]

            if len(t_w) < 10:
                # 窗口太小, 保留原始边界
                for pi in peak_indices:
                    for b in boundaries:
                        if b.apex_idx == pi:
                            refined.append(b)
                continue

            try:
                emg_result = self._emg_fit_window(
                    t_w, y_w, peak_indices, w_start, times, y_bc, noise_std, cfg,
                )
                if emg_result is not None and len(emg_result) >= len(peak_indices):
                    # EMG 拟合成功且找到了足够多的组分, 使用拟合结果
                    refined.extend(emg_result)
                    continue
            except Exception:
                pass

            # EMG 失败或组分不足, 保留原始边界
            for pi in peak_indices:
                for b in boundaries:
                    if b.apex_idx == pi:
                        refined.append(b)

        # 如果精修后结果反而少于原始结果, 回退到原始边界
        if len(refined) < len(boundaries):
            return boundaries

        return refined

    @staticmethod
    def _smooth_signal(signal: np.ndarray, smoothing_window: int) -> np.ndarray:
        """
        功能:
            对 FID 基线校正信号执行统一平滑, 保证 primary seed 与 split hint 使用同一条平滑曲线.

        参数:
            signal: 基线校正后的信号.
            smoothing_window: SG 平滑窗口.

        返回:
            np.ndarray, 平滑后的信号.
        """
        win = int(smoothing_window)
        if win % 2 == 0:
            win += 1
        if win > len(signal):
            win = max(3, len(signal) if len(signal) % 2 == 1 else len(signal) - 1)
        return savgol_filter(signal, win, min(3, win - 1))

    def _detect_candidates(self, y_bc: np.ndarray, times: np.ndarray,
                            noise_std: float,
                            cfg: PeakBoundaryDetectorConfig) -> np.ndarray:
        """
        功能:
            在基线校正后的信号上检测候选峰.

        参数:
            y_bc: 基线校正后信号.
            times: 时间轴.
            noise_std: 噪声标准差.
            cfg: 配置.

        返回:
            np.ndarray, 候选峰索引.
        """
        del times

        y_smooth = self._smooth_signal(y_bc, cfg.smoothing_window)

        # FID 正式候选入口仅保留平滑信号上的真实局部极大值
        primary_candidates, _ = find_peaks(
            y_smooth,
            prominence=cfg.fid_candidate_prominence,
            distance=cfg.fid_candidate_min_distance,
        )

        return np.array(sorted(set(int(idx) for idx in primary_candidates)), dtype=int)

    def _build_fitting_windows(self, candidates: np.ndarray, y_bc: np.ndarray,
                                n: int) -> List[Tuple[int, int, np.ndarray]]:
        """
        功能:
            将候选峰合并为局部拟合窗口.

        参数:
            candidates: 候选峰索引.
            y_bc: 基线校正后信号.
            n: 信号总长度.

        返回:
            List[Tuple[int, int, np.ndarray]], 每项为 (window_start, window_end, peaks_in_window).
        """
        if len(candidates) == 0:
            return []

        # 计算相邻候选峰之间的谷值位置
        valleys = []
        for i in range(len(candidates) - 1):
            seg = y_bc[candidates[i]:candidates[i + 1] + 1]
            valley = candidates[i] + int(np.argmin(seg))
            valleys.append(valley)

        # 为每个候选峰构建独立窗口, 边界取左右谷值
        windows = []
        for i in range(len(candidates)):
            # 左边界: 上一个谷值, 或信号起点
            left = valleys[i - 1] if i > 0 else 0
            # 右边界: 下一个谷值, 或信号终点
            right = valleys[i] if i < len(valleys) else n

            # 小量扩展 (最多 20 点或窗口宽度的 10%)
            margin = min(20, max(5, (right - left) // 10))
            left = max(0, left - margin)
            right = min(n, right + margin)

            windows.append((left, right, np.array([candidates[i]])))

        # 仅合并窗口间距极小的窗口 (间距 < 10 点)
        merged = []
        for w in windows:
            if merged and w[0] - merged[-1][1] < 10:
                prev = merged[-1]
                merged[-1] = (
                    prev[0],
                    max(prev[1], w[1]),
                    np.concatenate([prev[2], w[2]]),
                )
            else:
                merged.append(w)

        return merged

    def _fit_and_refine(self, windows: List[Tuple[int, int, np.ndarray]],
                         times: np.ndarray, y_bc: np.ndarray,
                         noise_std: float,
                         cfg: PeakBoundaryDetectorConfig) -> List[PeakBoundary]:
        """
        功能:
            对每个窗口执行 EMG 拟合和边界精修.

        参数:
            windows: 拟合窗口列表.
            times: 时间轴.
            y_bc: 基线校正后信号.
            noise_std: 噪声标准差.
            cfg: 配置.

        返回:
            List[PeakBoundary].
        """
        all_peaks = []

        for w_start, w_end, peak_indices in windows:
            s = slice(w_start, w_end)
            t_w = times[s]
            y_w = y_bc[s]

            if len(t_w) < 5:
                continue

            try:
                components = self._emg_fit_window(
                    t_w, y_w, peak_indices, w_start, times, y_bc, noise_std, cfg,
                )
            except Exception as e:
                logger.debug("EMG 拟合失败, 回退非参数边界: %s", e)
                components = None

            if components is None or len(components) == 0:
                # 回退: 非参数边界
                for pi in peak_indices:
                    boundary = self._fallback_boundary(pi, times, y_bc, noise_std)
                    if boundary is not None:
                        all_peaks.append(boundary)
            else:
                all_peaks.extend(components)

        return all_peaks

    def _emg_fit_window(self, t_w: np.ndarray, y_w: np.ndarray,
                         peak_indices: np.ndarray, w_start: int,
                         times: np.ndarray, y_bc: np.ndarray,
                         noise_std: float,
                         cfg: PeakBoundaryDetectorConfig) -> Optional[List[PeakBoundary]]:
        """
        功能:
            在单个窗口内执行 EMG 拟合, 用 BIC 选择最优模型.

        参数:
            t_w: 窗口时间.
            y_w: 窗口信号.
            peak_indices: 全局候选峰索引.
            w_start: 窗口起始的全局索引.
            times: 完整时间轴.
            y_bc: 完整基线校正信号.
            noise_std: 噪声标准差.
            cfg: 配置.

        返回:
            Optional[List[PeakBoundary]], 拟合失败时返回 None.
        """
        from lmfit import Model, Parameters
        from scipy.special import erfc

        def emg(x, amp, mu, sigma, tau):
            """指数修正高斯函数."""
            z = (x - mu) / max(sigma, 1e-10) - max(sigma, 1e-10) / max(tau, 1e-10)
            prefactor = (amp * max(sigma, 1e-10) / max(tau, 1e-10)) * np.sqrt(np.pi / 2.0)
            exp_part = np.exp(
                0.5 * (max(sigma, 1e-10) / max(tau, 1e-10)) ** 2
                - (x - mu) / max(tau, 1e-10)
            )
            # 限制 z 的范围避免 erfc 溢出
            z_clipped = np.clip(z, -20.0, 20.0)
            return prefactor * exp_part * erfc(z_clipped / np.sqrt(2.0))

        def local_baseline(x, slope, intercept):
            """局部线性基线."""
            return slope * x + intercept

        # 局部索引 -> 全局索引
        local_peaks = peak_indices - w_start
        # 过滤越界的局部索引
        local_peaks = local_peaks[(local_peaks >= 0) & (local_peaks < len(t_w))]

        if len(local_peaks) == 0:
            return None

        n_data = len(t_w)
        max_k = min(len(local_peaks) + 1, cfg.fid_fit_max_components)

        best_bic = np.inf
        best_result = None
        best_k = 0
        best_params = {}

        for k in range(1, max_k + 1):
            try:
                # 构建模型
                model = Model(local_baseline, prefix="bl_")
                for i in range(k):
                    model = model + Model(emg, prefix=f"p{i}_")

                params = model.make_params()

                # 基线初始值
                params["bl_slope"].set(value=0.0, min=-1.0, max=1.0)
                params["bl_intercept"].set(value=float(np.min(y_w)), min=-abs(np.max(y_w)) * 2)

                # 每个组分的初始参数
                dt = np.median(np.diff(t_w)) if len(t_w) > 1 else 0.01
                for i in range(k):
                    if i < len(local_peaks):
                        pi = local_peaks[i]
                    else:
                        # 额外组分放在窗口中间
                        pi = len(t_w) // 2

                    mu_init = float(t_w[pi])
                    amp_init = max(float(y_w[pi]), noise_std * 3)
                    sigma_init = dt * 5.0
                    tau_init = dt * 10.0

                    params[f"p{i}_amp"].set(value=amp_init, min=noise_std * 0.5, max=amp_init * 10)
                    params[f"p{i}_mu"].set(value=mu_init, min=float(t_w[0]), max=float(t_w[-1]))
                    params[f"p{i}_sigma"].set(value=sigma_init, min=dt * 0.5, max=float(t_w[-1] - t_w[0]) / 2)
                    params[f"p{i}_tau"].set(value=tau_init, min=dt * 0.5, max=float(t_w[-1] - t_w[0]))

                result = model.fit(y_w, params, x=t_w, max_nfev=5000)

                if result.success is False:
                    continue

                n_params = result.nvarys
                chisqr = max(result.chisqr, 1e-30)
                bic = n_data * np.log(chisqr / n_data) + n_params * np.log(n_data)

                # BIC 选模: 更高 K 需明显改善
                if bic < best_bic - cfg.fid_fit_bic_improve_min:
                    best_bic = bic
                    best_result = result
                    best_k = k
                    best_params = {name: result.params[name].value for name in result.params}
                elif best_result is None:
                    best_bic = bic
                    best_result = result
                    best_k = k
                    best_params = {name: result.params[name].value for name in result.params}

            except Exception as e:
                logger.debug("K=%d EMG 拟合异常: %s", k, e)
                continue

        if best_result is None:
            return None

        # 从最优模型提取边界
        boundaries = self._extract_boundaries_from_fit(
            best_result, best_k, t_w, y_w, w_start, times, y_bc, noise_std, cfg,
        )
        return boundaries

    def _extract_boundaries_from_fit(self, result, k: int,
                                      t_w: np.ndarray, y_w: np.ndarray,
                                      w_start: int,
                                      times: np.ndarray, y_bc: np.ndarray,
                                      noise_std: float,
                                      cfg: PeakBoundaryDetectorConfig) -> List[PeakBoundary]:
        """
        功能:
            从 lmfit 拟合结果中提取各组分的峰边界.

        参数:
            result: lmfit 拟合结果.
            k: 组分数.
            t_w: 窗口时间.
            y_w: 窗口信号.
            w_start: 窗口起始全局索引.
            times: 完整时间轴.
            y_bc: 完整基线校正信号.
            noise_std: 噪声标准差.
            cfg: 配置.

        返回:
            List[PeakBoundary].
        """
        from scipy.special import erfc

        def emg_curve(x, amp, mu, sigma, tau):
            """计算单个 EMG 组分的贡献曲线."""
            sigma = max(sigma, 1e-10)
            tau = max(tau, 1e-10)
            z = (x - mu) / sigma - sigma / tau
            prefactor = (amp * sigma / tau) * np.sqrt(np.pi / 2.0)
            exp_part = np.exp(0.5 * (sigma / tau) ** 2 - (x - mu) / tau)
            z_clipped = np.clip(z, -20.0, 20.0)
            return prefactor * exp_part * erfc(z_clipped / np.sqrt(2.0))

        # 计算每个组分的贡献曲线
        component_curves = []
        for i in range(k):
            amp = result.params[f"p{i}_amp"].value
            mu = result.params[f"p{i}_mu"].value
            sigma = result.params[f"p{i}_sigma"].value
            tau = result.params[f"p{i}_tau"].value
            curve = emg_curve(t_w, amp, mu, sigma, tau)
            component_curves.append((curve, mu, amp, sigma, tau))

        # 按 mu 排序
        sorted_idx = sorted(range(k), key=lambda i: component_curves[i][1])
        component_curves = [component_curves[i] for i in sorted_idx]

        # 拟合优度
        y_var = np.var(y_w)
        fit_score = 1.0 - (result.redchi / max(y_var, 1e-30)) if y_var > 0 else 0.0
        fit_score = max(0.0, min(1.0, fit_score))

        boundaries = []
        for ci in range(k):
            curve = component_curves[ci][0]
            peak_height = float(np.max(curve))

            if peak_height < noise_std:
                continue

            # 阈值截断
            threshold = max(
                cfg.fid_boundary_rel_height * peak_height,
                cfg.fid_boundary_abs_noise_factor * noise_std,
            )

            # 在窗口内找峰顶
            apex_local = int(np.argmax(curve))

            # 左边界: 从 apex 向左找第一个低于阈值的点
            left_local = apex_local
            for j in range(apex_local - 1, -1, -1):
                if curve[j] < threshold:
                    left_local = j
                    break
            else:
                left_local = 0

            # 右边界: 从 apex 向右找第一个低于阈值的点
            right_local = apex_local
            for j in range(apex_local + 1, len(curve)):
                if curve[j] < threshold:
                    right_local = j
                    break
            else:
                right_local = len(curve) - 1

            # 重叠区处理: 与前一个组分的交叉点
            if ci > 0:
                prev_curve = component_curves[ci - 1][0]
                for j in range(apex_local, -1, -1):
                    if prev_curve[j] >= curve[j] and curve[j] > threshold:
                        left_local = j
                        break

            # 重叠区处理: 与后一个组分的交叉点
            if ci < k - 1:
                next_curve = component_curves[ci + 1][0]
                for j in range(apex_local, len(curve)):
                    if next_curve[j] >= curve[j] and curve[j] > threshold:
                        right_local = j
                        break

            # 谷值吸附: 在边界附近找 y_bc 的局部最小值
            left_local = self._snap_to_valley(y_w, left_local, apex_local, direction="left")
            right_local = self._snap_to_valley(y_w, right_local, apex_local, direction="right")

            # 确保边界有序
            if left_local >= apex_local:
                left_local = max(0, apex_local - 1)
            if right_local <= apex_local:
                right_local = min(len(t_w) - 1, apex_local + 1)

            # 转换为全局索引
            start_idx = w_start + left_local
            apex_idx = w_start + apex_local
            end_idx = w_start + right_local

            # 保证不越界
            start_idx = max(0, min(start_idx, len(times) - 1))
            apex_idx = max(0, min(apex_idx, len(times) - 1))
            end_idx = max(0, min(end_idx, len(times) - 1))

            # 计算面积 (梯形积分)
            seg_start = max(0, start_idx)
            seg_end = min(len(y_bc), end_idx + 1)
            if seg_end > seg_start + 1:
                area = float(np.trapz(
                    np.maximum(y_bc[seg_start:seg_end], 0.0),
                    times[seg_start:seg_end],
                ))
            else:
                area = 0.0

            boundaries.append(PeakBoundary(
                peak_id=0,
                detector="fid",
                start_idx=start_idx,
                apex_idx=apex_idx,
                end_idx=end_idx,
                start_time=float(times[start_idx]),
                apex_time=float(times[apex_idx]),
                end_time=float(times[end_idx]),
                height=float(y_bc[apex_idx]),
                area=max(area, 0.0),
                evidence=PeakBoundaryEvidence(
                    fit_score=fit_score,
                    area_stability=max(0.0, min(1.0, 1.0 - result.redchi / max(noise_std ** 2, 1e-30))),
                ),
                quality=PeakBoundaryQuality(
                    quality_score=fit_score,
                    boundary_confidence=fit_score,
                    split_confidence=min(1.0, fit_score) if k > 1 else 0.0,
                    manual_review=fit_score < 0.3,
                ),
                flags=["fid_fit_ok"],
            ))

        return boundaries

    @staticmethod
    def _snap_to_valley(y: np.ndarray, boundary_idx: int, apex_idx: int,
                         direction: str) -> int:
        """
        功能:
            将边界 snap 到附近的局部谷值.

        参数:
            y: 信号.
            boundary_idx: 当前边界索引.
            apex_idx: 峰顶索引.
            direction: "left" 或 "right".

        返回:
            int, snap 后的边界索引.
        """
        search_range = max(3, abs(apex_idx - boundary_idx) // 3)

        if direction == "left":
            lo = max(0, boundary_idx - search_range)
            hi = min(len(y), boundary_idx + search_range + 1)
            if hi > lo:
                seg = y[lo:hi]
                return lo + int(np.argmin(seg))
        else:
            lo = max(0, boundary_idx - search_range)
            hi = min(len(y), boundary_idx + search_range + 1)
            if hi > lo:
                seg = y[lo:hi]
                return lo + int(np.argmin(seg))

        return boundary_idx

    def _fallback_boundary(self, peak_idx: int, times: np.ndarray,
                            y_bc: np.ndarray, noise_std: float) -> Optional[PeakBoundary]:
        """
        功能:
            非参数回退: 基于峰顶 + 谷值 + 基线包络的边界估计.

        参数:
            peak_idx: 峰顶全局索引.
            times: 时间轴.
            y_bc: 基线校正信号.
            noise_std: 噪声标准差.

        返回:
            Optional[PeakBoundary], 峰高不足时返回 None.
        """
        n = len(y_bc)
        peak_height = float(y_bc[peak_idx])

        if peak_height < noise_std * 2:
            return None

        threshold = max(noise_std * 3, peak_height * 0.01)

        # 向左搜索
        left = peak_idx
        for i in range(peak_idx - 1, -1, -1):
            if y_bc[i] < threshold:
                left = i
                break
        else:
            left = 0

        # 向右搜索
        right = peak_idx
        for i in range(peak_idx + 1, n):
            if y_bc[i] < threshold:
                right = i
                break
        else:
            right = n - 1

        # 面积
        seg_start = max(0, left)
        seg_end = min(n, right + 1)
        if seg_end > seg_start + 1:
            area = float(np.trapz(
                np.maximum(y_bc[seg_start:seg_end], 0.0),
                times[seg_start:seg_end],
            ))
        else:
            area = 0.0

        return PeakBoundary(
            peak_id=0,
            detector="fid",
            start_idx=left,
            apex_idx=peak_idx,
            end_idx=right,
            start_time=float(times[left]),
            apex_time=float(times[peak_idx]),
            end_time=float(times[right]),
            height=peak_height,
            area=max(area, 0.0),
            evidence=PeakBoundaryEvidence(fit_score=0.0, area_stability=0.5),
            quality=PeakBoundaryQuality(
                quality_score=0.3,
                boundary_confidence=0.3,
                split_confidence=0.0,
                manual_review=True,
            ),
            flags=["fid_fit_fallback"],
        )


# ---------------------------------------------------------------------------
# GC-MS 检测器
# ---------------------------------------------------------------------------

    def _build_fitting_windows(
        self,
        primary_candidates: np.ndarray,
        split_hints: np.ndarray,
        y_bc: np.ndarray,
        n: int,
        cfg: PeakBoundaryDetectorConfig,
        noise_std: float,
    ) -> List[FIDFittingWindow]:
        """
        功能:
            将 FID primary seed 组织为色谱事件窗口.
            split hint 只用于扩展窗口和提示尝试分峰, 不会直接成为正式峰.

        参数:
            primary_candidates: primary seed 全局索引数组.
            split_hints: split hint 全局索引数组.
            y_bc: 基线校正后信号.
            n: 信号总长度.

        返回:
            List[FIDFittingWindow], 色谱事件窗口列表.
        """
        if len(primary_candidates) == 0 and len(split_hints) == 0:
            return []

        primary_candidates = np.array(
            sorted(set(int(idx) for idx in primary_candidates)),
            dtype=int,
        )
        split_hints = np.array(
            sorted(set(int(idx) for idx in split_hints)),
            dtype=int,
        )

        valleys = []
        for i in range(len(primary_candidates) - 1):
            seg = y_bc[primary_candidates[i]:primary_candidates[i + 1] + 1]
            valley = primary_candidates[i] + int(np.argmin(seg))
            valleys.append(valley)

        windows: List[FIDFittingWindow] = []
        for i in range(len(primary_candidates)):
            if i > 0:
                left = valleys[i - 1]
            else:
                left = self._search_window_boundary(
                    apex_idx=int(primary_candidates[i]),
                    start_limit=0,
                    end_limit=n - 1,
                    y_bc=y_bc,
                    noise_std=noise_std,
                    cfg=cfg,
                    direction="left",
                )

            if i < len(valleys):
                right = valleys[i]
            else:
                right = self._search_window_boundary(
                    apex_idx=int(primary_candidates[i]),
                    start_limit=0,
                    end_limit=n - 1,
                    y_bc=y_bc,
                    noise_std=noise_std,
                    cfg=cfg,
                    direction="right",
                )

            margin = min(20, max(5, (right - left) // 10))
            left = max(0, left - margin)
            right = min(n, right + margin + 1)

            windows.append(
                FIDFittingWindow(
                    start_idx=int(left),
                    end_idx=int(right),
                    primary_indices=np.array([primary_candidates[i]], dtype=int),
                    split_hint_indices=np.array([], dtype=int),
                )
            )

        orphan_hint_margin = max(20, int(cfg.fid_candidate_min_distance) * 2)
        for hint_idx in split_hints:
            if len(windows) == 0:
                left = max(0, int(hint_idx) - orphan_hint_margin)
                right = min(n, int(hint_idx) + orphan_hint_margin + 1)
                windows.append(
                    FIDFittingWindow(
                        start_idx=int(left),
                        end_idx=int(right),
                        primary_indices=np.array([], dtype=int),
                        split_hint_indices=np.array([int(hint_idx)], dtype=int),
                    )
                )
                continue

            nearest_window = min(
                windows,
                key=lambda item: abs(int(self._window_anchor_idx(item)) - int(hint_idx)),
            )
            nearest_distance = abs(int(self._window_anchor_idx(nearest_window)) - int(hint_idx))
            if nearest_distance > orphan_hint_margin:
                left = max(0, int(hint_idx) - orphan_hint_margin)
                right = min(n, int(hint_idx) + orphan_hint_margin + 1)
                windows.append(
                    FIDFittingWindow(
                        start_idx=int(left),
                        end_idx=int(right),
                        primary_indices=np.array([], dtype=int),
                        split_hint_indices=np.array([int(hint_idx)], dtype=int),
                    )
                )
                continue

            nearest_window.split_hint_indices = np.array(
                sorted(
                    set(
                        int(idx)
                        for idx in np.append(nearest_window.split_hint_indices, int(hint_idx))
                    )
                ),
                dtype=int,
            )
            if int(hint_idx) < nearest_window.start_idx:
                nearest_window.start_idx = int(hint_idx)
            if int(hint_idx) >= nearest_window.end_idx:
                nearest_window.end_idx = int(hint_idx) + 1

        merge_scan_gap = max(10, int(cfg.fid_candidate_min_distance) * 5)
        merged: List[FIDFittingWindow] = []
        for window in sorted(windows, key=lambda item: item.start_idx):
            if len(merged) == 0:
                merged.append(window)
                continue

            previous = merged[-1]
            apex_gap = int(self._window_anchor_idx(window)) - int(self._window_anchor_idx(previous))
            if apex_gap <= merge_scan_gap:
                previous.end_idx = max(previous.end_idx, window.end_idx)
                previous.primary_indices = np.array(
                    sorted(
                        set(
                            int(idx)
                            for idx in np.concatenate([previous.primary_indices, window.primary_indices])
                        )
                    ),
                    dtype=int,
                )
                previous.split_hint_indices = np.array(
                    sorted(
                        set(
                            int(idx)
                            for idx in np.concatenate([previous.split_hint_indices, window.split_hint_indices])
                        )
                    ),
                    dtype=int,
                )
                continue

            merged.append(window)

        return merged

    def _fit_and_refine(
        self,
        windows: List[FIDFittingWindow],
        times: np.ndarray,
        raw_signal: np.ndarray,
        y_bc: np.ndarray,
        y_smooth: np.ndarray,
        noise_std: float,
        cfg: PeakBoundaryDetectorConfig,
    ) -> List[PeakBoundary]:
        """
        功能:
            逐个色谱事件窗口执行 EMG 拟合和分峰判定.

        参数:
            windows: 色谱事件窗口列表.
            times: 完整时间轴.
            y_bc: 完整基线校正信号.
            y_smooth: 完整平滑信号.
            noise_std: 噪声标准差.
            cfg: 配置.

        返回:
            List[PeakBoundary], FID 峰边界列表.
        """
        all_peaks: List[PeakBoundary] = []

        for window in windows:
            s = slice(window.start_idx, window.end_idx)
            t_w = times[s]
            y_w = y_bc[s]
            y_smooth_w = y_smooth[s]

            if len(t_w) < 5:
                fallback_apices = self._resolve_window_peak_indices(
                    window=window,
                    y_smooth=y_smooth,
                    noise_std=noise_std,
                    cfg=cfg,
                )
                all_peaks.extend(
                    self._build_boundaries_from_signal_apices(
                        window=window,
                        apex_indices=fallback_apices,
                        times=times,
                        raw_signal=raw_signal,
                        y_bc=y_bc,
                        y_smooth=y_smooth,
                        noise_std=noise_std,
                        cfg=cfg,
                        fit_score=0.0,
                        split_confidence=0.0,
                        flags=["fid_fit_fallback"],
                        manual_review=True,
                    )
                )
                continue

            try:
                components = self._emg_fit_window(
                    t_w=t_w,
                    y_w=y_w,
                    y_smooth_w=y_smooth_w,
                    window=window,
                    times=times,
                    raw_signal=raw_signal,
                    y_bc=y_bc,
                    y_smooth=y_smooth,
                    noise_std=noise_std,
                    cfg=cfg,
                )
            except Exception as exc:
                logger.warning("FID 事件窗口 EMG 拟合失败, 回退到信号边界: %s", exc)
                components = None

            if components is None or len(components) == 0:
                fallback_apices = self._resolve_window_peak_indices(
                    window=window,
                    y_smooth=y_smooth,
                    noise_std=noise_std,
                    cfg=cfg,
                )
                components = self._build_boundaries_from_signal_apices(
                    window=window,
                    apex_indices=fallback_apices,
                    times=times,
                    raw_signal=raw_signal,
                    y_bc=y_bc,
                    y_smooth=y_smooth,
                    noise_std=noise_std,
                    cfg=cfg,
                    fit_score=0.0,
                    split_confidence=0.0,
                    flags=["fid_fit_fallback"],
                    manual_review=True,
                )

            all_peaks.extend(components)

        return all_peaks

    def _emg_fit_window(
        self,
        t_w: np.ndarray,
        y_w: np.ndarray,
        y_smooth_w: np.ndarray,
        window: FIDFittingWindow,
        times: np.ndarray,
        raw_signal: np.ndarray,
        y_bc: np.ndarray,
        y_smooth: np.ndarray,
        noise_std: float,
        cfg: PeakBoundaryDetectorConfig,
    ) -> Optional[List[PeakBoundary]]:
        """
        功能:
            对单个 FID 事件窗口执行 EMG 拟合, 再由真实局部极值与内部谷底决定是否接受分峰.

        参数:
            t_w: 窗口时间轴.
            y_w: 窗口基线校正信号.
            y_smooth_w: 窗口平滑信号.
            window: FID 事件窗口.
            times: 完整时间轴.
            y_bc: 完整基线校正信号.
            y_smooth: 完整平滑信号.
            noise_std: 噪声标准差.
            cfg: 配置.

        返回:
            Optional[List[PeakBoundary]], 拟合成功时返回峰列表, 否则返回 None.
        """
        from lmfit import Model
        from scipy.special import erfc

        def emg(x, amp, mu, sigma, tau):
            sigma = max(float(sigma), 1e-10)
            tau = max(float(tau), 1e-10)
            z = (x - mu) / sigma - sigma / tau
            prefactor = (amp * sigma / tau) * np.sqrt(np.pi / 2.0)
            exp_part = np.exp(0.5 * (sigma / tau) ** 2 - (x - mu) / tau)
            z_clipped = np.clip(z, -20.0, 20.0)
            return prefactor * exp_part * erfc(z_clipped / np.sqrt(2.0))

        def local_baseline(x, slope, intercept):
            return slope * x + intercept

        local_seed_indices = []
        for peak_idx in window.primary_indices:
            local_idx = int(peak_idx) - int(window.start_idx)
            if 0 <= local_idx < len(t_w):
                local_seed_indices.append(local_idx)
        for hint_idx in window.split_hint_indices:
            local_idx = int(hint_idx) - int(window.start_idx)
            if 0 <= local_idx < len(t_w):
                local_seed_indices.append(local_idx)

        local_seed_indices = sorted(set(int(idx) for idx in local_seed_indices))
        if len(local_seed_indices) == 0:
            return None

        seed_ranking = sorted(
            local_seed_indices,
            key=lambda idx: float(y_smooth_w[idx]),
            reverse=True,
        )
        max_k = min(len(seed_ranking), int(cfg.fid_fit_max_components))
        if max_k <= 0:
            return None

        best_bic = np.inf
        best_result = None
        best_k = 0

        for k in range(1, max_k + 1):
            try:
                chosen_seed_indices = sorted(seed_ranking[:k])
                model = Model(local_baseline, prefix="bl_")
                for component_index in range(k):
                    model = model + Model(emg, prefix=f"p{component_index}_")

                params = model.make_params()
                params["bl_slope"].set(value=0.0, min=-1.0, max=1.0)
                params["bl_intercept"].set(value=float(np.min(y_w)), min=-abs(float(np.max(y_w))) * 2.0)

                dt = float(np.median(np.diff(t_w))) if len(t_w) > 1 else 0.01
                window_span = max(float(t_w[-1] - t_w[0]), dt * 2.0)
                for component_index, seed_idx in enumerate(chosen_seed_indices):
                    mu_init = float(t_w[seed_idx])
                    amp_init = max(float(y_w[seed_idx]), noise_std * 3.0)
                    sigma_init = max(dt * 5.0, window_span / 60.0)
                    tau_init = max(dt * 10.0, window_span / 30.0)

                    params[f"p{component_index}_amp"].set(
                        value=amp_init,
                        min=noise_std * 0.5,
                        max=max(amp_init * 10.0, noise_std * 10.0),
                    )
                    params[f"p{component_index}_mu"].set(
                        value=mu_init,
                        min=float(t_w[0]),
                        max=float(t_w[-1]),
                    )
                    params[f"p{component_index}_sigma"].set(
                        value=sigma_init,
                        min=dt * 0.5,
                        max=max(window_span / 2.0, dt),
                    )
                    params[f"p{component_index}_tau"].set(
                        value=tau_init,
                        min=dt * 0.5,
                        max=max(window_span, dt),
                    )

                result = model.fit(y_w, params, x=t_w, max_nfev=5000)
                if result.success is False:
                    continue

                n_data = len(t_w)
                n_params = result.nvarys
                chisqr = max(float(result.chisqr), 1e-30)
                bic = n_data * np.log(chisqr / n_data) + n_params * np.log(n_data)

                if bic < best_bic - float(cfg.fid_fit_bic_improve_min):
                    best_bic = bic
                    best_result = result
                    best_k = k
                elif best_result is None:
                    best_bic = bic
                    best_result = result
                    best_k = k
            except Exception as exc:
                logger.debug("FID EMG 拟合候选 K=%d 失败: %s", k, exc)
                continue

        if best_result is None:
            return None

        return self._extract_boundaries_from_fit(
            result=best_result,
            k=best_k,
            t_w=t_w,
            y_w=y_w,
            y_smooth_w=y_smooth_w,
            window=window,
            times=times,
            raw_signal=raw_signal,
            y_bc=y_bc,
            y_smooth=y_smooth,
            noise_std=noise_std,
            cfg=cfg,
        )

    def _extract_boundaries_from_fit(
        self,
        result,
        k: int,
        t_w: np.ndarray,
        y_w: np.ndarray,
        y_smooth_w: np.ndarray,
        window: FIDFittingWindow,
        times: np.ndarray,
        raw_signal: np.ndarray,
        y_bc: np.ndarray,
        y_smooth: np.ndarray,
        noise_std: float,
        cfg: PeakBoundaryDetectorConfig,
    ) -> List[PeakBoundary]:
        """
        功能:
            将拟合结果映射回真实平滑信号, 再按主算法规则判断是否接受分峰.

        参数:
            result: lmfit 拟合结果.
            k: 最优组分数.
            t_w: 窗口时间轴.
            y_w: 窗口基线校正信号.
            y_smooth_w: 窗口平滑信号.
            window: FID 事件窗口.
            times: 完整时间轴.
            y_bc: 完整基线校正信号.
            y_smooth: 完整平滑信号.
            noise_std: 噪声标准差.
            cfg: 配置.

        返回:
            List[PeakBoundary], 拟合解释后的峰边界列表.
        """
        from scipy.special import erfc

        def emg_curve(x, amp, mu, sigma, tau):
            sigma = max(float(sigma), 1e-10)
            tau = max(float(tau), 1e-10)
            z = (x - mu) / sigma - sigma / tau
            prefactor = (amp * sigma / tau) * np.sqrt(np.pi / 2.0)
            exp_part = np.exp(0.5 * (sigma / tau) ** 2 - (x - mu) / tau)
            z_clipped = np.clip(z, -20.0, 20.0)
            return prefactor * exp_part * erfc(z_clipped / np.sqrt(2.0))

        component_curves = []
        for component_index in range(k):
            component_curves.append(
                emg_curve(
                    t_w,
                    result.params[f"p{component_index}_amp"].value,
                    result.params[f"p{component_index}_mu"].value,
                    result.params[f"p{component_index}_sigma"].value,
                    result.params[f"p{component_index}_tau"].value,
                )
            )

        component_curves = sorted(
            component_curves,
            key=lambda curve: int(np.argmax(curve)),
        )
        y_var = float(np.var(y_w))
        fit_score = 1.0 - (float(result.redchi) / max(y_var, 1e-30)) if y_var > 0 else 0.0
        fit_score = max(0.0, min(1.0, fit_score))

        accepted_apices = None
        if k > 1:
            accepted_apices = self._map_component_apices_to_signal_maxima(
                component_curves=component_curves,
                y_smooth_w=y_smooth_w,
                noise_std=noise_std,
                cfg=cfg,
            )
            if accepted_apices is not None:
                is_valid_split, _ = self._validate_split_apices(
                    apex_indices=accepted_apices,
                    y_smooth_w=y_smooth_w,
                    noise_std=noise_std,
                    cfg=cfg,
                )
                if is_valid_split is False:
                    accepted_apices = None

        if accepted_apices is not None and len(accepted_apices) > 1:
            global_apices = accepted_apices + int(window.start_idx)
            return self._build_boundaries_from_signal_apices(
                window=window,
                apex_indices=global_apices,
                times=times,
                raw_signal=raw_signal,
                y_bc=y_bc,
                y_smooth=y_smooth,
                noise_std=noise_std,
                cfg=cfg,
                fit_score=fit_score,
                split_confidence=fit_score,
                flags=["fid_fit_ok", "fid_split_accepted"],
                manual_review=fit_score < 0.3,
            )

        dominant_apex = np.array([int(window.start_idx) + int(np.argmax(y_smooth_w))], dtype=int)
        return self._build_boundaries_from_signal_apices(
            window=window,
            apex_indices=dominant_apex,
            times=times,
            raw_signal=raw_signal,
            y_bc=y_bc,
            y_smooth=y_smooth,
            noise_std=noise_std,
            cfg=cfg,
            fit_score=fit_score,
            split_confidence=0.0,
            flags=["fid_fit_ok"],
            manual_review=fit_score < 0.3,
        )

    @staticmethod
    def _find_real_local_maxima(y_smooth_w: np.ndarray, noise_std: float) -> np.ndarray:
        """
        功能:
            在窗口平滑信号上寻找真实局部极大值.

        参数:
            y_smooth_w: 窗口平滑信号.
            noise_std: 噪声标准差.

        返回:
            np.ndarray, 局部极大值局部索引数组.
        """
        height_floor = max(2.0 * float(noise_std), 0.0)
        maxima, _ = find_peaks(
            y_smooth_w,
            height=height_floor,
            distance=1,
        )
        if len(maxima) == 0:
            return np.array([int(np.argmax(y_smooth_w))], dtype=int)
        return np.array(sorted(set(int(idx) for idx in maxima)), dtype=int)

    def _map_component_apices_to_signal_maxima(
        self,
        component_curves: List[np.ndarray],
        y_smooth_w: np.ndarray,
        noise_std: float,
        cfg: PeakBoundaryDetectorConfig,
    ) -> Optional[np.ndarray]:
        """
        功能:
            将拟合组分 apex 映射到原始平滑信号上的真实局部极大值.

        参数:
            component_curves: 拟合得到的组分曲线列表.
            y_smooth_w: 窗口平滑信号.
            noise_std: 噪声标准差.
            cfg: 配置.

        返回:
            Optional[np.ndarray], 映射后的局部 apex 索引数组, 无法映射时返回 None.
        """
        signal_maxima = self._find_real_local_maxima(y_smooth_w, noise_std)
        if len(signal_maxima) == 0:
            return None

        max_gap = max(3, int(cfg.fid_candidate_min_distance) // 3)
        used = set()
        mapped = []

        for curve in component_curves:
            component_apex = int(np.argmax(curve))
            eligible = [
                int(idx)
                for idx in signal_maxima
                if int(idx) not in used and abs(int(idx) - component_apex) <= max_gap
            ]
            if len(eligible) == 0:
                return None

            nearest_idx = min(
                eligible,
                key=lambda idx: (abs(int(idx) - component_apex), -float(y_smooth_w[idx])),
            )
            used.add(int(nearest_idx))
            mapped.append(int(nearest_idx))

        mapped = np.array(sorted(set(int(idx) for idx in mapped)), dtype=int)
        if len(mapped) != len(component_curves):
            return None
        return mapped

    def _validate_split_apices(
        self,
        apex_indices: np.ndarray,
        y_smooth_w: np.ndarray,
        noise_std: float,
        cfg: PeakBoundaryDetectorConfig,
    ) -> Tuple[bool, List[int]]:
        """
        功能:
            校验相邻 apex 之间是否存在满足规则的真实内部谷底.

        参数:
            apex_indices: 候选局部 apex 索引数组.
            y_smooth_w: 窗口平滑信号.
            noise_std: 噪声标准差.
            cfg: 配置.

        返回:
            Tuple[bool, List[int]], 是否接受分峰, 以及内部谷底局部索引列表.
        """
        apex_indices = np.array(sorted(set(int(idx) for idx in apex_indices)), dtype=int)
        if len(apex_indices) <= 1:
            return False, []

        min_gap = max(3, int(cfg.fid_candidate_min_distance) // 3)
        valleys: List[int] = []

        for left_idx, right_idx in zip(apex_indices[:-1], apex_indices[1:]):
            if int(right_idx) - int(left_idx) < min_gap:
                return False, []
            if int(right_idx) - int(left_idx) <= 1:
                return False, []

            seg = y_smooth_w[int(left_idx) + 1:int(right_idx)]
            if len(seg) == 0:
                return False, []

            valley_idx = int(left_idx) + 1 + int(np.argmin(seg))
            valley_depth = min(
                float(y_smooth_w[int(left_idx)]),
                float(y_smooth_w[int(right_idx)]),
            ) - float(y_smooth_w[valley_idx])
            if valley_depth < 3.0 * float(noise_std):
                return False, []

            relative_threshold = 0.15 * min(
                float(y_smooth_w[int(left_idx)]),
                float(y_smooth_w[int(right_idx)]),
            )
            if valley_depth < relative_threshold:
                return False, []

            valleys.append(int(valley_idx))

        return True, valleys

    def _resolve_window_peak_indices(
        self,
        window: FIDFittingWindow,
        y_smooth: np.ndarray,
        noise_std: float,
        cfg: PeakBoundaryDetectorConfig,
    ) -> np.ndarray:
        """
        功能:
            在不给 split hint 正式峰身份的前提下, 从窗口中解析最终应保留的信号 apex.

        参数:
            window: FID 事件窗口.
            y_smooth: 完整平滑信号.
            noise_std: 噪声标准差.
            cfg: 配置.

        返回:
            np.ndarray, 应保留的全局 apex 索引数组.
        """
        window_smooth = y_smooth[window.start_idx:window.end_idx]
        if len(window_smooth) == 0:
            return np.array([], dtype=int)

        signal_maxima_local = self._find_real_local_maxima(window_smooth, noise_std)
        candidate_local_indices = []
        max_gap = max(3, int(cfg.fid_candidate_min_distance) // 3)

        for peak_idx in window.primary_indices:
            local_idx = int(peak_idx) - int(window.start_idx)
            if 0 <= local_idx < len(window_smooth):
                candidate_local_indices.append(local_idx)

        for hint_idx in window.split_hint_indices:
            hint_local = int(hint_idx) - int(window.start_idx)
            eligible = [
                int(idx)
                for idx in signal_maxima_local
                if abs(int(idx) - hint_local) <= max_gap
            ]
            if len(eligible) == 0:
                continue
            nearest_idx = min(
                eligible,
                key=lambda idx: (abs(int(idx) - hint_local), -float(window_smooth[idx])),
            )
            candidate_local_indices.append(int(nearest_idx))

        if len(candidate_local_indices) == 0:
            return np.array([int(window.start_idx) + int(np.argmax(window_smooth))], dtype=int)

        candidate_local_indices = np.array(
            sorted(set(int(idx) for idx in candidate_local_indices)),
            dtype=int,
        )

        is_valid_split, _ = self._validate_split_apices(
            apex_indices=candidate_local_indices,
            y_smooth_w=window_smooth,
            noise_std=noise_std,
            cfg=cfg,
        )
        if len(candidate_local_indices) > 1 and is_valid_split is True:
            return candidate_local_indices + int(window.start_idx)

        return np.array([int(window.start_idx) + int(np.argmax(window_smooth))], dtype=int)

    @staticmethod
    def _window_anchor_idx(window: FIDFittingWindow) -> int:
        """
        功能:
            返回窗口用于排序和距离比较的锚点索引.

        参数:
            window: FID 事件窗口.

        返回:
            int, 窗口锚点索引.
        """
        indices = []
        indices.extend(int(idx) for idx in window.primary_indices)
        indices.extend(int(idx) for idx in window.split_hint_indices)
        if len(indices) > 0:
            return min(indices)
        return int(window.start_idx)

    def _build_boundaries_from_signal_apices(
        self,
        window: FIDFittingWindow,
        apex_indices: np.ndarray,
        times: np.ndarray,
        raw_signal: np.ndarray,
        y_bc: np.ndarray,
        y_smooth: np.ndarray,
        noise_std: float,
        cfg: PeakBoundaryDetectorConfig,
        fit_score: float,
        split_confidence: float,
        flags: List[str],
        manual_review: bool,
    ) -> List[PeakBoundary]:
        """
        功能:
            依据最终接受的信号 apex 与真实谷底生成边界.

        参数:
            window: FID 事件窗口.
            apex_indices: 最终接受的全局 apex 索引数组.
            times: 完整时间轴.
            y_bc: 完整基线校正信号.
            y_smooth: 完整平滑信号.
            noise_std: 噪声标准差.
            cfg: 配置.
            fit_score: 拟合质量分数.
            split_confidence: 分峰置信度.
            flags: 边界标记列表.
            manual_review: 是否需要人工复核.

        返回:
            List[PeakBoundary], 峰边界列表.
        """
        apex_indices = np.array(sorted(set(int(idx) for idx in apex_indices)), dtype=int)
        if len(apex_indices) == 0:
            return []

        start_limit = int(window.start_idx)
        end_limit = int(window.end_idx) - 1
        if end_limit <= start_limit:
            return []

        local_apices = apex_indices - int(window.start_idx)
        if len(local_apices) > 1:
            is_valid_split, valley_local_indices = self._validate_split_apices(
                apex_indices=local_apices,
                y_smooth_w=y_smooth[window.start_idx:window.end_idx],
                noise_std=noise_std,
                cfg=cfg,
            )
            if is_valid_split is False:
                dominant_apex = np.array(
                    [int(window.start_idx) + int(np.argmax(y_smooth[window.start_idx:window.end_idx]))],
                    dtype=int,
                )
                return self._build_boundaries_from_signal_apices(
                    window=window,
                    apex_indices=dominant_apex,
                    times=times,
                    raw_signal=raw_signal,
                    y_bc=y_bc,
                    y_smooth=y_smooth,
                    noise_std=noise_std,
                    cfg=cfg,
                    fit_score=fit_score,
                    split_confidence=0.0,
                    flags=flags,
                    manual_review=manual_review,
                )
        else:
            valley_local_indices = []

        boundaries: List[PeakBoundary] = []
        left_boundary = self._search_window_boundary(
            apex_idx=int(apex_indices[0]),
            start_limit=start_limit,
            end_limit=end_limit,
            y_bc=y_bc,
            noise_std=noise_std,
            cfg=cfg,
            direction="left",
        )
        right_boundary = self._search_window_boundary(
            apex_idx=int(apex_indices[-1]),
            start_limit=start_limit,
            end_limit=end_limit,
            y_bc=y_bc,
            noise_std=noise_std,
            cfg=cfg,
            direction="right",
        )
        internal_boundaries = [int(window.start_idx) + int(idx) for idx in valley_local_indices]

        for peak_index, apex_idx in enumerate(apex_indices):
            if peak_index == 0:
                start_idx = int(left_boundary)
            else:
                start_idx = int(internal_boundaries[peak_index - 1])

            if peak_index == len(apex_indices) - 1:
                end_idx = int(right_boundary)
            else:
                end_idx = int(internal_boundaries[peak_index])

            if start_idx >= int(apex_idx):
                start_idx = max(start_limit, int(apex_idx) - 1)
            if end_idx <= int(apex_idx):
                end_idx = min(end_limit, int(apex_idx) + 1)

            segment_apex_idx = start_idx + int(np.argmax(raw_signal[start_idx:end_idx + 1]))
            area = self._calculate_boundary_area(
                start_idx=start_idx,
                end_idx=end_idx,
                times=times,
                y_bc=y_bc,
            )
            boundaries.append(
                PeakBoundary(
                    peak_id=0,
                    detector="fid",
                    start_idx=start_idx,
                    apex_idx=int(segment_apex_idx),
                    end_idx=end_idx,
                    start_time=float(times[start_idx]),
                    apex_time=float(times[int(segment_apex_idx)]),
                    end_time=float(times[end_idx]),
                    height=float(y_bc[int(segment_apex_idx)]),
                    area=max(area, 0.0),
                    evidence=PeakBoundaryEvidence(
                        fit_score=float(fit_score),
                        area_stability=max(0.0, min(1.0, float(fit_score))),
                    ),
                    quality=PeakBoundaryQuality(
                        quality_score=max(0.0, min(1.0, float(fit_score))),
                        boundary_confidence=max(0.0, min(1.0, float(fit_score))),
                        split_confidence=float(split_confidence) if len(apex_indices) > 1 else 0.0,
                        manual_review=bool(manual_review),
                    ),
                    flags=list(flags),
                )
            )

        return boundaries

    def _search_window_boundary(
        self,
        apex_idx: int,
        start_limit: int,
        end_limit: int,
        y_bc: np.ndarray,
        noise_std: float,
        cfg: PeakBoundaryDetectorConfig,
        direction: str,
    ) -> int:
        """
        功能:
            在窗口范围内基于阈值和自然谷底搜索单侧边界.

        参数:
            apex_idx: apex 全局索引.
            start_limit: 窗口起始索引.
            end_limit: 窗口结束索引, 包含该点.
            y_bc: 基线校正信号.
            noise_std: 噪声标准差.
            cfg: 配置.
            direction: left 或 right.

        返回:
            int, 单侧边界全局索引.
        """
        peak_height = max(float(y_bc[int(apex_idx)]), 0.0)
        threshold = max(
            float(cfg.fid_boundary_rel_height) * peak_height,
            float(cfg.fid_boundary_abs_noise_factor) * float(noise_std),
        )

        boundary_idx = int(apex_idx)
        if direction == "left":
            for current_idx in range(int(apex_idx) - 1, int(start_limit) - 1, -1):
                if float(y_bc[current_idx]) < threshold:
                    boundary_idx = int(current_idx)
                    break
            else:
                boundary_idx = int(start_limit)

            boundary_idx = self._snap_to_valley(y_bc, boundary_idx, int(apex_idx), "left")
            return max(int(start_limit), min(int(boundary_idx), int(apex_idx) - 1))

        for current_idx in range(int(apex_idx) + 1, int(end_limit) + 1):
            if float(y_bc[current_idx]) < threshold:
                boundary_idx = int(current_idx)
                break
        else:
            boundary_idx = int(end_limit)

        boundary_idx = self._snap_to_valley(y_bc, boundary_idx, int(apex_idx), "right")
        return min(int(end_limit), max(int(boundary_idx), int(apex_idx) + 1))

    @staticmethod
    def _calculate_boundary_area(
        start_idx: int,
        end_idx: int,
        times: np.ndarray,
        y_bc: np.ndarray,
    ) -> float:
        """
        功能:
            计算给定边界内的正向积分面积.

        参数:
            start_idx: 起始索引.
            end_idx: 结束索引, 包含该点.
            times: 时间轴.
            y_bc: 基线校正信号.

        返回:
            float, 峰面积.
        """
        seg_start = max(0, int(start_idx))
        seg_end = min(len(y_bc), int(end_idx) + 1)
        if seg_end <= seg_start + 1:
            return 0.0
        return float(
            np.trapz(
                np.maximum(y_bc[seg_start:seg_end], 0.0),
                times[seg_start:seg_end],
            )
        )

    def _fallback_boundary(
        self,
        peak_idx: int,
        times: np.ndarray,
        y_bc: np.ndarray,
        noise_std: float,
    ) -> Optional[PeakBoundary]:
        """
        功能:
            保留旧接口形状, 但内部统一复用新的单峰边界搜索逻辑.

        参数:
            peak_idx: apex 全局索引.
            times: 时间轴.
            y_bc: 基线校正信号.
            noise_std: 噪声标准差.

        返回:
            Optional[PeakBoundary], 单峰边界对象.
        """
        if int(peak_idx) < 0 or int(peak_idx) >= len(y_bc):
            return None

        if float(y_bc[int(peak_idx)]) < float(noise_std) * 2.0:
            return None

        window = FIDFittingWindow(
            start_idx=0,
            end_idx=len(y_bc),
            primary_indices=np.array([int(peak_idx)], dtype=int),
            split_hint_indices=np.array([], dtype=int),
        )
        boundaries = self._build_boundaries_from_signal_apices(
            window=window,
            apex_indices=np.array([int(peak_idx)], dtype=int),
            times=times,
            raw_signal=y_bc,
            y_bc=y_bc,
            y_smooth=y_bc,
            noise_std=noise_std,
            cfg=self.config,
            fit_score=0.0,
            split_confidence=0.0,
            flags=["fid_fit_fallback"],
            manual_review=True,
        )
        if len(boundaries) == 0:
            return None
        return boundaries[0]

class GCMSPeakBoundaryDetector(BasePeakBoundaryDetector):
    """
    功能:
        GC-MS 峰边界识别器.
        TIC 预处理 -> 候选生成 -> 特征离子筛选 -> 责任度计算 -> 边界搜索.

    参数:
        config: 检测器配置.

    返回:
        无.
    """

    def detect(self, inp: PeakDetectionInput) -> PeakDetectionResult:
        """
        功能:
            对 GC-MS 信号执行峰边界检测.

        参数:
            inp: 检测输入数据.

        返回:
            PeakDetectionResult.
        """
        times = inp.times
        signal = inp.signal
        n = len(times)
        cfg = self.config

        # Step 1: TIC 预处理
        win = cfg.smoothing_window
        if win % 2 == 0:
            win += 1
        if win > n:
            win = max(3, n if n % 2 == 1 else n - 1)

        y_smooth = savgol_filter(signal, win, min(3, win - 1))
        noise_std = _estimate_noise_std(signal)
        if noise_std <= 0:
            noise_std = 1e-10
        baseline = _rolling_percentile_baseline(signal, times)
        y_bc = signal - baseline

        # Step 2: 候选 apex 生成
        seeds, _ = find_peaks(
            y_smooth,
            prominence=cfg.gcms_seed_prominence,
            distance=cfg.gcms_seed_min_distance,
        )

        if len(seeds) == 0:
            logger.warning("GC-MS TIC 未检测到任何候选种子")
            return PeakDetectionResult(
                detector="gcms_tic",
                peaks=[],
                trace=PeakDetectionTrace(baseline=baseline),
            )

        # 判断是否有 MS 矩阵
        has_ms = (inp.ms_matrix is not None and inp.mz_axis is not None
                  and inp.ms_matrix.ndim == 2 and inp.ms_matrix.shape[0] == n)

        if has_ms is True:
            # 多维分支
            boundaries = self._multidim_detect(
                seeds, times, signal, y_bc, y_smooth, baseline, noise_std,
                inp.ms_matrix, inp.mz_axis, cfg,
            )
        else:
            # TIC-only 回退
            logger.info("GC-MS 无可用 ms_matrix, 使用 TIC-only 边界检测")
            boundaries = self._tic_only_detect(
                seeds, times, signal, y_bc, y_smooth, baseline, noise_std, cfg,
            )

        # 去重合并: 同一 RT 区域内只保留质量最高的边界
        boundaries = self._merge_overlapping_boundaries(boundaries, times)

        # 按 apex_time 排序并编号
        boundaries.sort(key=lambda b: b.apex_time)
        for i, b in enumerate(boundaries):
            b.peak_id = i + 1

        return PeakDetectionResult(
            detector="gcms_tic",
            peaks=boundaries,
            trace=PeakDetectionTrace(baseline=baseline),
        )

    @staticmethod
    def _merge_overlapping_boundaries(boundaries: List[PeakBoundary],
                                       times: np.ndarray) -> List[PeakBoundary]:
        """
        功能:
            合并 apex 接近的重复边界, 每个 RT 簇只保留质量最高的峰.

        参数:
            boundaries: 原始边界列表.
            times: 时间轴.

        返回:
            List[PeakBoundary], 去重后的边界.
        """
        if len(boundaries) <= 1:
            return boundaries

        # 按 apex_time 排序
        sorted_b = sorted(boundaries, key=lambda b: b.apex_time)

        # 估计合并容差: 时间步长的 10 倍, 至少 0.05 min
        dt = float(np.median(np.diff(times))) if len(times) > 1 else 0.01
        merge_tol = max(dt * 10, 0.05)

        # 贪心聚类: apex_time 间距 < merge_tol 的归为一簇
        clusters = [[sorted_b[0]]]
        for b in sorted_b[1:]:
            if b.apex_time - clusters[-1][-1].apex_time < merge_tol:
                clusters[-1].append(b)
            else:
                clusters.append([b])

        # 每个簇保留质量最高的
        merged = []
        for cluster in clusters:
            best = max(cluster, key=lambda b: (b.quality.quality_score, b.area))
            merged.append(best)

        return merged

    def _multidim_detect(self, seeds: np.ndarray,
                          times: np.ndarray, signal: np.ndarray,
                          y_bc: np.ndarray, y_smooth: np.ndarray,
                          baseline: np.ndarray, noise_std: float,
                          ms_matrix: np.ndarray, mz_axis: np.ndarray,
                          cfg: PeakBoundaryDetectorConfig) -> List[PeakBoundary]:
        """
        功能:
            GC-MS 多维边界检测: 特征离子 + 责任度 + 拆峰.

        参数:
            seeds: 候选种子索引.
            times: 时间轴.
            signal: 原始 TIC 信号.
            y_bc: 基线校正后信号.
            y_smooth: 平滑信号.
            baseline: 基线.
            noise_std: TIC 噪声标准差.
            ms_matrix: MS 矩阵 (n_scans, n_mz).
            mz_axis: m/z 轴.
            cfg: 配置.

        返回:
            List[PeakBoundary].
        """
        n = len(times)
        all_boundaries = []

        for seed_idx in seeds:
            seed_idx = int(seed_idx)

            # Step 3: 局部窗口
            half_window = max(15, int(0.5 / np.median(np.diff(times))))  # ~0.5 min
            w_start = max(0, seed_idx - half_window)
            w_end = min(n, seed_idx + half_window + 1)

            # Step 4: 特征离子筛选
            feature_ions = self._select_feature_ions(
                seed_idx, w_start, w_end, ms_matrix, noise_std, cfg,
            )

            if len(feature_ions) < cfg.gcms_feature_ion_min_count:
                # 回退到 TIC-only
                boundary = self._tic_only_single_peak(
                    seed_idx, times, y_bc, y_smooth, baseline, noise_std, cfg,
                )
                if boundary is not None:
                    boundary.flags = ["gcms_tic_only_fallback"]
                    all_boundaries.append(boundary)
                continue

            # Step 5: 组分拆分
            components = self._split_components(
                seed_idx, w_start, w_end, feature_ions, ms_matrix, times, cfg,
            )

            # Step 6 + 7: 对每个组分计算责任度并搜索边界
            for comp_apex, comp_ions in components:
                # 参考谱: 组分 apex 处的特征离子强度
                ref_spectrum = ms_matrix[comp_apex, comp_ions].copy()
                ref_norm = np.linalg.norm(ref_spectrum)
                if ref_norm > 0:
                    ref_spectrum_normed = ref_spectrum / ref_norm
                else:
                    ref_spectrum_normed = ref_spectrum

                # 参考离子比例
                ref_max = ref_spectrum[0] if ref_spectrum[0] > 0 else 1.0
                ref_ratios = ref_spectrum[:min(3, len(ref_spectrum))] / ref_max

                # 计算扫描级责任度
                responsibility = np.zeros(w_end - w_start)
                for t_local in range(w_end - w_start):
                    t_global = w_start + t_local
                    scan_spectrum = ms_matrix[t_global, comp_ions]

                    # 谱相似性 (余弦)
                    scan_norm = np.linalg.norm(scan_spectrum)
                    if scan_norm > 0 and ref_norm > 0:
                        spec_sim = float(np.dot(scan_spectrum / scan_norm, ref_spectrum_normed))
                    else:
                        spec_sim = 0.0

                    # 特征离子共洗脱分数
                    ion_noise = noise_std * 0.1  # MS 噪声阈值估计
                    active_count = int(np.sum(scan_spectrum > ion_noise))
                    coelution = active_count / max(len(comp_ions), 1)

                    # 主离子比例稳定性
                    scan_max = scan_spectrum[0] if scan_spectrum[0] > 0 else 1.0
                    scan_ratios = scan_spectrum[:min(3, len(scan_spectrum))] / scan_max
                    ratio_diff = np.abs(scan_ratios - ref_ratios[:len(scan_ratios)])
                    ratio_cv = float(np.mean(ratio_diff))
                    ratio_stability = max(0.0, 1.0 - ratio_cv / max(cfg.gcms_ratio_cv_threshold, 1e-10))

                    # TIC 形状
                    apex_height = max(y_smooth[comp_apex], 1e-10)
                    tic_shape = min(1.0, y_smooth[t_global] / apex_height)

                    # 基线惩罚
                    above_baseline = max(0.0, y_smooth[t_global] - baseline[t_global])
                    baseline_penalty = max(0.0, 1.0 - above_baseline / (noise_std * 3)) if noise_std > 0 else 0.0

                    # 综合责任度
                    responsibility[t_local] = (
                        0.35 * spec_sim
                        + 0.25 * coelution
                        + 0.20 * ratio_stability
                        + 0.15 * tic_shape
                        - 0.05 * baseline_penalty
                    )

                # Step 7: 双阈值边界搜索
                apex_local = comp_apex - w_start
                left_local, right_local = self._dual_threshold_search(
                    responsibility, apex_local, cfg,
                )

                start_idx = w_start + left_local
                apex_idx = comp_apex
                end_idx = w_start + right_local

                # 谷值吸附
                start_idx = self._snap_to_tic_valley(y_bc, start_idx, apex_idx, direction="left")
                end_idx = self._snap_to_tic_valley(y_bc, end_idx, apex_idx, direction="right")

                # 保证有序
                start_idx = max(0, min(start_idx, apex_idx - 1))
                end_idx = min(len(times) - 1, max(end_idx, apex_idx + 1))

                # 计算面积
                seg = y_bc[start_idx:end_idx + 1]
                area = float(np.trapz(np.maximum(seg, 0.0), times[start_idx:end_idx + 1]))

                # 质量评分
                avg_resp = float(np.mean(responsibility[left_local:right_local + 1]))
                quality_score = max(0.0, min(1.0, avg_resp))

                all_boundaries.append(PeakBoundary(
                    peak_id=0,
                    detector="gcms_tic",
                    start_idx=start_idx,
                    apex_idx=apex_idx,
                    end_idx=end_idx,
                    start_time=float(times[start_idx]),
                    apex_time=float(times[apex_idx]),
                    end_time=float(times[end_idx]),
                    height=float(y_bc[apex_idx]),
                    area=max(area, 0.0),
                    evidence=PeakBoundaryEvidence(
                        fit_score=avg_resp,
                        area_stability=0.8,
                    ),
                    quality=PeakBoundaryQuality(
                        quality_score=quality_score,
                        boundary_confidence=quality_score,
                        split_confidence=quality_score if len(components) > 1 else 0.0,
                        manual_review=quality_score < 0.3,
                    ),
                    flags=["gcms_multidim"],
                ))

        return all_boundaries

    def _select_feature_ions(self, apex_idx: int, w_start: int, w_end: int,
                              ms_matrix: np.ndarray, noise_std: float,
                              cfg: PeakBoundaryDetectorConfig) -> np.ndarray:
        """
        功能:
            以 apex 为中心筛选特征离子.

        参数:
            apex_idx: 峰顶扫描索引.
            w_start: 窗口起始.
            w_end: 窗口结束.
            ms_matrix: MS 矩阵.
            noise_std: TIC 噪声标准差.
            cfg: 配置.

        返回:
            np.ndarray, 特征离子的 m/z 索引.
        """
        n_scans, n_mz = ms_matrix.shape

        # 核心区: apex +/- 2 scans
        core_start = max(w_start, apex_idx - 2)
        core_end = min(w_end, apex_idx + 3)
        core_spectrum = ms_matrix[core_start:core_end, :].mean(axis=0)

        # 背景区: 左右各 5~15 scans
        bg_left_start = max(0, apex_idx - 15)
        bg_left_end = max(0, apex_idx - 5)
        bg_right_start = min(n_scans, apex_idx + 5)
        bg_right_end = min(n_scans, apex_idx + 15)

        bg_spectra = []
        if bg_left_end > bg_left_start:
            bg_spectra.append(ms_matrix[bg_left_start:bg_left_end, :].mean(axis=0))
        if bg_right_end > bg_right_start:
            bg_spectra.append(ms_matrix[bg_right_start:bg_right_end, :].mean(axis=0))

        if len(bg_spectra) > 0:
            bg_spectrum = np.mean(bg_spectra, axis=0)
        else:
            bg_spectrum = np.zeros(n_mz)

        # 富集度
        epsilon = max(noise_std * 0.01, 1.0)
        enrichment = (core_spectrum - bg_spectrum) / (bg_spectrum + epsilon)

        # 过滤: 核心区强度 > 噪声阈值
        ms_noise = max(np.median(core_spectrum[core_spectrum > 0]) * 0.01, 1.0) if np.any(core_spectrum > 0) else 1.0
        valid = core_spectrum > ms_noise

        # 综合评分并排序
        scores = enrichment * valid.astype(float)
        sorted_ions = np.argsort(scores)[::-1]

        # 选取 top N
        n_ions = min(cfg.gcms_feature_ion_max_count, int(np.sum(scores > 0)))
        n_ions = max(n_ions, 0)
        return sorted_ions[:n_ions]

    def _split_components(self, seed_idx: int, w_start: int, w_end: int,
                           feature_ions: np.ndarray, ms_matrix: np.ndarray,
                           times: np.ndarray,
                           cfg: PeakBoundaryDetectorConfig) -> List[Tuple[int, np.ndarray]]:
        """
        功能:
            基于特征离子 XIC apex 时间聚类拆分组分.

        参数:
            seed_idx: 种子索引.
            w_start: 窗口起始.
            w_end: 窗口结束.
            feature_ions: 特征离子索引.
            ms_matrix: MS 矩阵.
            times: 时间轴.
            cfg: 配置.

        返回:
            List[Tuple[int, np.ndarray]], 每项为 (apex_scan_idx, feature_ion_indices).
        """
        if len(feature_ions) == 0:
            return [(seed_idx, feature_ions)]

        # 每个特征离子的 XIC apex 位置
        xic_apices = []
        for mz_idx in feature_ions:
            xic = ms_matrix[w_start:w_end, mz_idx]
            local_apex = int(np.argmax(xic))
            xic_apices.append(w_start + local_apex)

        xic_apices = np.array(xic_apices)

        # 按 apex 位置排序
        sort_order = np.argsort(xic_apices)
        sorted_apices = xic_apices[sort_order]
        sorted_ions = feature_ions[sort_order]

        # gap-based 聚类
        clusters = []
        current_cluster_apices = [sorted_apices[0]]
        current_cluster_ions = [sorted_ions[0]]

        for i in range(1, len(sorted_apices)):
            gap = sorted_apices[i] - sorted_apices[i - 1]
            if gap >= cfg.gcms_component_gap_min_scans:
                # 新簇
                clusters.append((current_cluster_apices, current_cluster_ions))
                current_cluster_apices = [sorted_apices[i]]
                current_cluster_ions = [sorted_ions[i]]
            else:
                current_cluster_apices.append(sorted_apices[i])
                current_cluster_ions.append(sorted_ions[i])

        clusters.append((current_cluster_apices, current_cluster_ions))

        # 每个簇的代表 apex 和离子
        components = []
        for apices, ions in clusters:
            rep_apex = int(np.median(apices))
            components.append((rep_apex, np.array(ions)))

        return components

    def _dual_threshold_search(self, responsibility: np.ndarray, apex_local: int,
                                cfg: PeakBoundaryDetectorConfig) -> Tuple[int, int]:
        """
        功能:
            双阈值从 apex 向两侧扩展搜索边界.

        参数:
            responsibility: 责任度数组.
            apex_local: apex 在窗口内的局部索引.
            cfg: 配置.

        返回:
            Tuple[int, int], (左边界, 右边界) 局部索引.
        """
        n = len(responsibility)
        low_thr = cfg.gcms_boundary_low_score_threshold
        consecutive_limit = 3

        # 向左
        left = apex_local
        low_count = 0
        for i in range(apex_local - 1, -1, -1):
            if responsibility[i] < low_thr:
                low_count += 1
                if low_count >= consecutive_limit:
                    left = i + consecutive_limit
                    break
            else:
                low_count = 0
            left = i

        # 向右
        right = apex_local
        low_count = 0
        for i in range(apex_local + 1, n):
            if responsibility[i] < low_thr:
                low_count += 1
                if low_count >= consecutive_limit:
                    right = i - consecutive_limit
                    break
            else:
                low_count = 0
            right = i

        return max(0, left), min(n - 1, right)

    @staticmethod
    def _snap_to_tic_valley(y_bc: np.ndarray, boundary_idx: int, apex_idx: int,
                             direction: str) -> int:
        """
        功能:
            将边界 snap 到 TIC 的局部谷值.

        参数:
            y_bc: 基线校正信号.
            boundary_idx: 当前边界索引.
            apex_idx: 峰顶索引.
            direction: "left" 或 "right".

        返回:
            int, snap 后的边界索引.
        """
        search_range = max(3, abs(apex_idx - boundary_idx) // 4)
        n = len(y_bc)

        lo = max(0, boundary_idx - search_range)
        hi = min(n, boundary_idx + search_range + 1)
        if hi > lo:
            seg = y_bc[lo:hi]
            return lo + int(np.argmin(seg))
        return boundary_idx

    def _tic_only_detect(self, seeds: np.ndarray,
                          times: np.ndarray, signal: np.ndarray,
                          y_bc: np.ndarray, y_smooth: np.ndarray,
                          baseline: np.ndarray, noise_std: float,
                          cfg: PeakBoundaryDetectorConfig) -> List[PeakBoundary]:
        """
        功能:
            TIC-only 回退检测.

        参数:
            seeds: 候选种子.
            times: 时间轴.
            signal: 原始信号.
            y_bc: 基线校正信号.
            y_smooth: 平滑信号.
            baseline: 基线.
            noise_std: 噪声标准差.
            cfg: 配置.

        返回:
            List[PeakBoundary].
        """
        boundaries = []
        for seed_idx in seeds:
            boundary = self._tic_only_single_peak(
                int(seed_idx), times, y_bc, y_smooth, baseline, noise_std, cfg,
            )
            if boundary is not None:
                boundary.flags = ["gcms_tic_only_fallback"]
                boundaries.append(boundary)
        return boundaries

    def _tic_only_single_peak(self, peak_idx: int,
                               times: np.ndarray, y_bc: np.ndarray,
                               y_smooth: np.ndarray, baseline: np.ndarray,
                               noise_std: float,
                               cfg: PeakBoundaryDetectorConfig) -> Optional[PeakBoundary]:
        """
        功能:
            TIC 单维保守边界: 从 apex 向两侧搜索至基线包络或信号谷底.

        参数:
            peak_idx: 峰顶索引.
            times: 时间轴.
            y_bc: 基线校正信号.
            y_smooth: 平滑信号.
            baseline: 基线.
            noise_std: 噪声标准差.
            cfg: 配置.

        返回:
            Optional[PeakBoundary].
        """
        n = len(y_bc)
        peak_height = float(y_bc[peak_idx])

        if peak_height < noise_std * 2:
            return None

        threshold = max(noise_std * 3, peak_height * 0.01)

        # 向左搜索
        left = peak_idx
        for i in range(peak_idx - 1, max(-1, peak_idx - 200), -1):
            if i < 0:
                left = 0
                break
            if y_bc[i] < threshold:
                left = i
                break

        # 向右搜索
        right = peak_idx
        for i in range(peak_idx + 1, min(n, peak_idx + 200)):
            if y_bc[i] < threshold:
                right = i
                break

        # 谷值吸附
        left = self._snap_to_tic_valley(y_bc, left, peak_idx, "left")
        right = self._snap_to_tic_valley(y_bc, right, peak_idx, "right")

        # 确保有序
        left = max(0, min(left, peak_idx - 1))
        right = min(n - 1, max(right, peak_idx + 1))

        # 面积
        seg = y_bc[left:right + 1]
        area = float(np.trapz(np.maximum(seg, 0.0), times[left:right + 1]))

        return PeakBoundary(
            peak_id=0,
            detector="gcms_tic",
            start_idx=left,
            apex_idx=peak_idx,
            end_idx=right,
            start_time=float(times[left]),
            apex_time=float(times[peak_idx]),
            end_time=float(times[right]),
            height=peak_height,
            area=max(area, 0.0),
            evidence=PeakBoundaryEvidence(fit_score=0.5, area_stability=0.7),
            quality=PeakBoundaryQuality(
                quality_score=0.5,
                boundary_confidence=0.5,
                split_confidence=0.0,
                manual_review=False,
            ),
            flags=["gcms_tic_only_fallback"],
        )


# ---------------------------------------------------------------------------
# 工厂
# ---------------------------------------------------------------------------

class PeakBoundaryDetectorFactory:
    """
    功能:
        根据检测器类型构建对应的峰边界检测器.

    参数:
        config: 检测器配置.

    返回:
        无.
    """

    def __init__(self, config: PeakBoundaryDetectorConfig) -> None:
        self._config = config

    def build(self, detector_type: str) -> BasePeakBoundaryDetector:
        """
        功能:
            根据检测器类型路由到具体检测器.

        参数:
            detector_type: "gcms_tic" 或 "fid".

        返回:
            BasePeakBoundaryDetector 的具体子类实例.
        """
        if detector_type == "gcms_tic":
            return GCMSPeakBoundaryDetector(self._config)
        elif detector_type == "fid":
            return FIDPeakBoundaryDetector(self._config)
        else:
            raise ValueError(f"未知的检测器类型: {detector_type}")
