#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    对色谱信号(TIC/FID)执行峰检测与积分, 支持 legacy 和 robust_v2 两种模式.
参数:
    无.
返回:
    无.
"""

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
from scipy import sparse
from scipy.ndimage import percentile_filter
from scipy.signal import find_peaks, peak_widths, savgol_filter
from scipy.sparse.linalg import spsolve

logger = logging.getLogger(__name__)


@dataclass
class PeakResult:
    """
    功能:
        存储单个色谱峰的检测与积分结果.
    参数:
        peak_index: 峰顶在原始数组中的索引.
        retention_time: 峰顶保留时间(min).
        height: 峰高(原始强度).
        area: 峰面积(局部基线梯形积分).
        area_percent: 面积百分比(%).
        start_time: 峰起始时间(min).
        end_time: 峰结束时间(min).
        width: 峰宽(min).
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
        执行色谱峰检测与积分.

        - legacy: 兼容历史流程(ALS/非ALS + valley/peak_widths).
        - robust_v2: 滚动分位数基线(可回退 ALS) + 噪声阈值 + 自适应限宽边界.

    参数:
        smoothing_window: Savitzky-Golay 平滑窗口(奇数).
        prominence: 峰检测最小 prominence.
        min_distance: 相邻峰最小距离(点数).
        width_rel_height: legacy 模式下 peak_widths 定界相对高度.
        use_als_baseline: legacy 模式是否启用 ALS 基线.
        als_lambda: ALS 平滑参数.
        als_p: ALS 不对称权重参数.
        use_valley_boundary: legacy 模式是否使用 valley+回落定界.
        integration_mode: 积分模式, robust_v2 或 legacy.
        baseline_method: robust_v2 基线方式, rolling_quantile 或 als.
        baseline_quantile: rolling_quantile 的分位数(0-100).
        baseline_window_min: rolling_quantile 窗口长度(min).
        boundary_sigma_factor: 边界噪声阈值倍数.
        boundary_edge_ratio: 边界峰高比例阈值.
        boundary_expand_factor: 基于半高宽扩展搜索半径系数.
        boundary_min_span_min: 边界最小半径(min).
        boundary_max_span_min: 边界最大半径(min).
    返回:
        无.
    """

    def __init__(
        self,
        smoothing_window: int = 11,
        prominence: float = 5000.0,
        min_distance: int = 5,
        width_rel_height: float = 0.95,
        use_als_baseline: bool = True,
        als_lambda: float = 1e7,
        als_p: float = 0.01,
        use_valley_boundary: bool = True,
        integration_mode: str = "robust_v2",
        baseline_method: str = "rolling_quantile",
        baseline_quantile: float = 20.0,
        baseline_window_min: float = 0.9,
        boundary_sigma_factor: float = 3.0,
        boundary_edge_ratio: float = 0.01,
        boundary_expand_factor: float = 6.0,
        boundary_min_span_min: float = 0.08,
        boundary_max_span_min: float = 0.80,
        gcpy_whittaker_lmbd: float = 10.0,
    ):
        self._smoothing_window = self._ensure_odd(max(3, int(smoothing_window)))
        self._prominence = float(prominence)
        self._min_distance = int(min_distance)
        self._width_rel_height = float(width_rel_height)

        # legacy 参数
        self._use_als_baseline = bool(use_als_baseline)
        self._als_lambda = float(als_lambda)
        self._als_p = float(als_p)
        self._use_valley_boundary = bool(use_valley_boundary)

        # robust_v2 参数
        self._integration_mode = str(integration_mode).strip().lower()
        self._baseline_method = str(baseline_method).strip().lower()
        self._baseline_quantile = float(baseline_quantile)
        self._baseline_window_min = float(baseline_window_min)
        self._boundary_sigma_factor = float(boundary_sigma_factor)
        self._boundary_edge_ratio = float(boundary_edge_ratio)
        self._boundary_expand_factor = float(boundary_expand_factor)
        self._boundary_min_span_min = float(boundary_min_span_min)
        self._boundary_max_span_min = float(boundary_max_span_min)

        # gcpy 参数
        self._gcpy_whittaker_lmbd = float(gcpy_whittaker_lmbd)

        # integrate() 完成后可读取最后一次使用的基线.
        self.last_baseline: Optional[np.ndarray] = None

    @staticmethod
    def _ensure_odd(value: int) -> int:
        """
        功能:
            将整数调整为奇数.
        参数:
            value: 输入整数.
        返回:
            int, 奇数结果.
        """
        if value % 2 == 0:
            return value + 1
        return value

    def _als_baseline(
        self,
        y: np.ndarray,
        lam: float,
        p: float,
        n_iter: int = 10,
    ) -> np.ndarray:
        """
        功能:
            ALS(Asymmetric Least Squares)基线估计.
        参数:
            y: 原始信号数组.
            lam: 平滑参数.
            p: 不对称权重.
            n_iter: 迭代次数.
        返回:
            np.ndarray, 基线数组.
        """
        n_points = len(y)
        diag_vals = np.array([1.0, -2.0, 1.0], dtype=np.float64)
        diff_matrix = sparse.diags(
            diag_vals,
            offsets=[0, -1, -2],
            shape=(n_points, n_points - 2),
            format="csc",
        )
        smooth_matrix = lam * diff_matrix.dot(diff_matrix.T)

        weights = np.ones(n_points, dtype=np.float64)
        for _ in range(n_iter):
            weight_matrix = sparse.spdiags(weights, 0, n_points, n_points, format="csc")
            system = weight_matrix + smooth_matrix
            baseline = spsolve(system, weights * y)
            weights = p * (y > baseline).astype(np.float64) + (1.0 - p) * (y <= baseline).astype(np.float64)

        return baseline

    @staticmethod
    def _median_dt(times: np.ndarray) -> float:
        """
        功能:
            估计时间轴步长中位数.
        参数:
            times: 时间数组.
        返回:
            float, 步长中位数.
        """
        diffs = np.diff(times)
        valid_diffs = diffs[diffs > 0]
        if len(valid_diffs) == 0:
            return 0.0
        return float(np.median(valid_diffs))

    def _compute_window_points(self, dt: float, duration_min: float, n_points: int) -> int:
        """
        功能:
            将分钟级窗口转换为点数窗口, 并限制为奇数合法值.
        参数:
            dt: 时间步长(min).
            duration_min: 目标窗口(min).
            n_points: 信号总点数.
        返回:
            int, 合法窗口点数.
        """
        if dt <= 0:
            base = 31
        else:
            base = int(round(duration_min / dt))

        if base < 5:
            base = 5

        base = self._ensure_odd(base)

        if base >= n_points:
            if n_points % 2 == 0:
                base = n_points - 1
            else:
                base = n_points

        if base < 3:
            base = 3

        return base

    def _rolling_quantile_baseline(self, signal: np.ndarray, times: np.ndarray) -> np.ndarray:
        """
        功能:
            使用滚动分位数估计局部基线, 并通过 SG 再平滑.
        参数:
            signal: 平滑后的信号.
            times: 时间数组.
        返回:
            np.ndarray, 基线数组.
        """
        dt = self._median_dt(times)
        window_points = self._compute_window_points(dt, self._baseline_window_min, len(signal))

        baseline_raw = percentile_filter(
            signal,
            percentile=self._baseline_quantile,
            size=window_points,
            mode="nearest",
        )

        baseline = baseline_raw
        if window_points >= 5 and window_points <= len(signal):
            poly_order = 3
            if window_points <= poly_order:
                poly_order = window_points - 1
            if poly_order >= 1:
                baseline = savgol_filter(baseline_raw, window_points, polyorder=poly_order)

        return baseline

    @staticmethod
    def _baseline_is_valid(signal: np.ndarray, baseline: np.ndarray) -> bool:
        """
        功能:
            判断基线是否可用于后续计算.
        参数:
            signal: 参考信号.
            baseline: 待校验基线.
        返回:
            bool, True 表示基线有效.
        """
        if baseline is None:
            return False

        if len(signal) != len(baseline):
            return False

        if np.any(~np.isfinite(baseline)):
            return False

        signal_span = float(np.max(signal) - np.min(signal))
        if signal_span <= 0:
            return True

        upper_limit = float(np.max(signal) + signal_span)
        lower_limit = float(np.min(signal) - signal_span)
        if np.any(baseline > upper_limit):
            return False
        if np.any(baseline < lower_limit):
            return False

        return True

    @staticmethod
    def _find_drop_index(
        signal: np.ndarray,
        start: int,
        direction: int,
        threshold: float,
        left_limit: int,
        right_limit: int,
    ) -> int:
        """
        功能:
            从峰顶向两侧搜索, 找到首次低于阈值的索引.
        参数:
            signal: 目标信号.
            start: 起始索引.
            direction: 搜索方向, -1 左, +1 右.
            threshold: 回落阈值.
            left_limit: 左边界约束.
            right_limit: 右边界约束.
        返回:
            int, 回落索引.
        """
        idx = start
        if direction < 0:
            while idx > left_limit and signal[idx] > threshold:
                idx -= 1
            return idx

        while idx < right_limit and signal[idx] > threshold:
            idx += 1
        return idx

    @staticmethod
    def _find_valley(signal: np.ndarray, start: int, end: int) -> int:
        """
        功能:
            在闭区间[start, end]寻找局部谷点.
        参数:
            signal: 目标信号.
            start: 起始索引.
            end: 结束索引.
        返回:
            int, 谷点索引.
        """
        if end < start:
            return start

        region = signal[start:end + 1]
        if len(region) == 0:
            return start

        return start + int(np.argmin(region))

    @staticmethod
    def _estimate_noise_sigma(corrected_signal: np.ndarray) -> float:
        """
        功能:
            基于 MAD 估计低信号区噪声标准差.
        参数:
            corrected_signal: 基线校正后的非负信号.
        返回:
            float, 噪声 sigma 估计.
        """
        finite_values = corrected_signal[np.isfinite(corrected_signal)]
        if len(finite_values) == 0:
            return 0.0

        quantile_threshold = float(np.percentile(finite_values, 70.0))
        lower_values = finite_values[finite_values <= quantile_threshold]
        if len(lower_values) < 10:
            lower_values = finite_values

        median_value = float(np.median(lower_values))
        mad_value = float(np.median(np.abs(lower_values - median_value)))
        sigma = 1.4826 * mad_value

        if not np.isfinite(sigma):
            return 0.0

        if sigma < 0:
            return 0.0

        return sigma

    @staticmethod
    def _integrate_with_local_baseline(times: np.ndarray, intensities: np.ndarray) -> float:
        """
        功能:
            使用峰端点线性基线进行局部积分.
        参数:
            times: 峰段时间数组(min).
            intensities: 峰段原始强度数组.
        返回:
            float, 峰面积.
        """
        if len(times) < 2:
            return 0.0

        local_baseline = np.linspace(intensities[0], intensities[-1], len(times))
        net_signal = intensities - local_baseline
        net_signal = np.maximum(net_signal, 0)
        return float(np.trapz(net_signal, times * 60.0))

    @staticmethod
    def _integrate_with_baseline_array(
        times: np.ndarray,
        intensities: np.ndarray,
        baseline: np.ndarray,
    ) -> float:
        """
        功能:
            使用给定基线数组进行逐点扣基线积分.
        参数:
            times: 峰段时间数组(min).
            intensities: 峰段原始强度数组.
            baseline: 与峰段等长的全局基线数组.
        返回:
            float, 峰面积.
        """
        if len(times) < 2:
            return 0.0

        if len(times) != len(intensities) or len(times) != len(baseline):
            return 0.0

        if np.any(~np.isfinite(intensities)) or np.any(~np.isfinite(baseline)):
            return 0.0

        net_signal = intensities - baseline
        net_signal = np.maximum(net_signal, 0.0)
        return float(np.trapz(net_signal, times * 60.0))

    def _find_legacy_boundaries(
        self,
        signal: np.ndarray,
        peak_indices: np.ndarray,
    ) -> List[Tuple[int, int]]:
        """
        功能:
            legacy 模式边界搜索, 保留历史 valley+回落逻辑.
        参数:
            signal: 检测信号.
            peak_indices: 峰索引数组.
        返回:
            List[Tuple[int, int]], 边界索引列表.
        """
        n_points = len(signal)
        n_peaks = len(peak_indices)
        boundaries: List[Tuple[int, int]] = []

        for i in range(n_peaks):
            peak_idx = int(peak_indices[i])
            peak_height = float(signal[peak_idx])
            drop_threshold = peak_height * 0.01

            if i == 0:
                valley_left = 0
                left_region = signal[0:peak_idx]
                if len(left_region) > 0:
                    valley_left = int(np.argmin(left_region))
            else:
                prev_peak = int(peak_indices[i - 1])
                middle_region = signal[prev_peak:peak_idx]
                if len(middle_region) > 0:
                    valley_left = prev_peak + int(np.argmin(middle_region))
                else:
                    valley_left = prev_peak

            if i == n_peaks - 1:
                valley_right = n_points - 1
                right_region = signal[peak_idx:n_points]
                if len(right_region) > 0:
                    valley_right = peak_idx + int(np.argmin(right_region))
            else:
                next_peak = int(peak_indices[i + 1])
                middle_region = signal[peak_idx:next_peak]
                if len(middle_region) > 0:
                    valley_right = peak_idx + int(np.argmin(middle_region))
                else:
                    valley_right = next_peak

            drop_left = self._find_drop_index(
                signal,
                peak_idx,
                direction=-1,
                threshold=drop_threshold,
                left_limit=0,
                right_limit=n_points - 1,
            )
            drop_right = self._find_drop_index(
                signal,
                peak_idx,
                direction=1,
                threshold=drop_threshold,
                left_limit=0,
                right_limit=n_points - 1,
            )

            left_idx = max(valley_left, drop_left)
            right_idx = min(valley_right, drop_right)
            boundaries.append((left_idx, right_idx))

        return boundaries

    def _find_robust_boundaries(
        self,
        times: np.ndarray,
        corrected_signal: np.ndarray,
        peak_indices: np.ndarray,
    ) -> List[Optional[Tuple[int, int]]]:
        """
        功能:
            robust_v2 边界搜索.

            规则:
            1. 以半高宽推导自适应搜索半径.
            2. 叠加相邻峰中点约束, 防止跨峰吞并.
            3. 使用 max(峰高比例阈值, 噪声阈值) 搜索回落点.
            4. 与局部 valley 合并, 选择更靠近峰顶的边界.
            5. 异常时回退到半高宽边界.

        参数:
            times: 时间数组(min).
            corrected_signal: 基线校正后的检测信号.
            peak_indices: 峰索引数组.
        返回:
            List[Optional[Tuple[int, int]]], 每个峰的边界索引, 失败项为 None.
        """
        n_points = len(corrected_signal)
        boundaries: List[Optional[Tuple[int, int]]] = []

        widths_50, _, left_ips_50, right_ips_50 = peak_widths(
            corrected_signal,
            peak_indices,
            rel_height=0.5,
        )

        dt = self._median_dt(times)
        min_span_pts = self._compute_window_points(dt, self._boundary_min_span_min, n_points)
        max_span_pts = self._compute_window_points(dt, self._boundary_max_span_min, n_points)
        if max_span_pts < min_span_pts:
            max_span_pts = min_span_pts

        noise_sigma = self._estimate_noise_sigma(corrected_signal)

        for i, peak_idx in enumerate(peak_indices):
            peak_idx = int(peak_idx)

            fallback_left = max(0, int(np.floor(left_ips_50[i])))
            fallback_right = min(n_points - 1, int(np.ceil(right_ips_50[i])))

            width_pts = float(widths_50[i])
            if not np.isfinite(width_pts):
                width_pts = float(min_span_pts)

            span_pts = int(np.ceil(width_pts * self._boundary_expand_factor))
            if span_pts < min_span_pts:
                span_pts = min_span_pts
            if span_pts > max_span_pts:
                span_pts = max_span_pts

            left_limit = max(0, peak_idx - span_pts)
            right_limit = min(n_points - 1, peak_idx + span_pts)

            if i > 0:
                midpoint_left = (int(peak_indices[i - 1]) + peak_idx) // 2
                if midpoint_left > left_limit:
                    left_limit = midpoint_left

            if i < len(peak_indices) - 1:
                midpoint_right = (peak_idx + int(peak_indices[i + 1])) // 2
                if midpoint_right < right_limit:
                    right_limit = midpoint_right

            if left_limit >= peak_idx:
                left_limit = max(0, peak_idx - 1)

            if right_limit <= peak_idx:
                right_limit = min(n_points - 1, peak_idx + 1)

            peak_height = float(corrected_signal[peak_idx])
            edge_threshold = max(
                peak_height * self._boundary_edge_ratio,
                noise_sigma * self._boundary_sigma_factor,
            )

            drop_left = self._find_drop_index(
                corrected_signal,
                peak_idx,
                direction=-1,
                threshold=edge_threshold,
                left_limit=left_limit,
                right_limit=right_limit,
            )
            drop_right = self._find_drop_index(
                corrected_signal,
                peak_idx,
                direction=1,
                threshold=edge_threshold,
                left_limit=left_limit,
                right_limit=right_limit,
            )

            valley_left = self._find_valley(corrected_signal, left_limit, peak_idx)
            valley_right = self._find_valley(corrected_signal, peak_idx, right_limit)

            left_idx = max(drop_left, valley_left)
            right_idx = min(drop_right, valley_right)

            if right_idx <= left_idx or (right_idx - left_idx) < 2:
                if fallback_right > fallback_left:
                    left_idx = fallback_left
                    right_idx = fallback_right
                    logger.warning(
                        "RT=%.3f 的边界触发回退, 使用半高宽边界.",
                        float(times[peak_idx]),
                    )
                else:
                    logger.warning(
                        "RT=%.3f 的边界无效且回退失败, 已跳过该峰.",
                        float(times[peak_idx]),
                    )
                    boundaries.append(None)
                    continue

            boundaries.append((left_idx, right_idx))

        return boundaries

    def _build_peak_result(
        self,
        times: np.ndarray,
        intensities: np.ndarray,
        peak_idx: int,
        left_idx: int,
        right_idx: int,
        area: float,
    ) -> PeakResult:
        """
        功能:
            组装单个峰结果.
        参数:
            times: 时间数组.
            intensities: 强度数组.
            peak_idx: 峰顶索引.
            left_idx: 左边界索引.
            right_idx: 右边界索引.
            area: 峰面积.
        返回:
            PeakResult.
        """
        width = 0.0
        if right_idx > left_idx:
            width = float(times[right_idx] - times[left_idx])

        return PeakResult(
            peak_index=int(peak_idx),
            retention_time=float(times[peak_idx]),
            height=float(intensities[peak_idx]),
            area=float(area),
            start_time=float(times[left_idx]),
            end_time=float(times[right_idx]),
            width=width,
        )

    @staticmethod
    def _update_area_percent(results: List[PeakResult]) -> None:
        """
        功能:
            按总面积回填 area_percent.
        参数:
            results: 峰结果列表.
        返回:
            无.
        """
        total_area = sum(item.area for item in results)
        if total_area <= 0:
            return

        for item in results:
            item.area_percent = item.area / total_area * 100.0

    def _integrate_legacy(self, times: np.ndarray, intensities: np.ndarray) -> List[PeakResult]:
        """
        功能:
            兼容历史积分流程.
        参数:
            times: 时间数组.
            intensities: 强度数组.
        返回:
            List[PeakResult], 峰列表.
        """
        if self._use_als_baseline:
            baseline = self._als_baseline(intensities.astype(np.float64), self._als_lambda, self._als_p)
            corrected_signal = np.maximum(intensities - baseline, 0)
            self.last_baseline = baseline
            signal_for_detection = corrected_signal
            logger.info("legacy 模式使用 ALS 基线.")
        else:
            corrected_signal = intensities.astype(np.float64)
            self.last_baseline = None
            signal_for_detection = corrected_signal
            logger.info("legacy 模式不使用 ALS 基线.")

        smoothed_signal = savgol_filter(signal_for_detection, self._smoothing_window, polyorder=3)
        smoothed_signal = np.maximum(smoothed_signal, 0)

        peak_indices, _ = find_peaks(
            smoothed_signal,
            prominence=self._prominence,
            distance=self._min_distance,
        )
        if len(peak_indices) == 0:
            logger.info("legacy 模式未检测到峰.")
            return []

        if self._use_valley_boundary:
            boundaries = self._find_legacy_boundaries(smoothed_signal, peak_indices)
        else:
            _, _, left_ips, right_ips = peak_widths(
                smoothed_signal,
                peak_indices,
                rel_height=self._width_rel_height,
            )
            boundaries = []
            for i in range(len(peak_indices)):
                left_idx = max(0, int(np.floor(left_ips[i])))
                right_idx = min(len(times) - 1, int(np.ceil(right_ips[i])))
                boundaries.append((left_idx, right_idx))

        results: List[PeakResult] = []
        for i, peak_idx in enumerate(peak_indices):
            left_idx, right_idx = boundaries[i]
            left_idx = max(0, left_idx)
            right_idx = min(len(times) - 1, right_idx)
            if right_idx <= left_idx:
                continue

            peak_times = times[left_idx:right_idx + 1]
            if self._use_als_baseline:
                peak_signal = corrected_signal[left_idx:right_idx + 1]
                area = 0.0
                if len(peak_times) >= 2:
                    area = float(np.trapz(peak_signal, peak_times * 60.0))
            else:
                peak_signal = intensities[left_idx:right_idx + 1]
                area = self._integrate_with_local_baseline(peak_times, peak_signal)

            results.append(
                self._build_peak_result(
                    times=times,
                    intensities=intensities,
                    peak_idx=int(peak_idx),
                    left_idx=left_idx,
                    right_idx=right_idx,
                    area=area,
                )
            )

        self._update_area_percent(results)
        logger.info("legacy 模式积分完成, 峰数量: %d", len(results))
        return results

    def _integrate_robust_v2(self, times: np.ndarray, intensities: np.ndarray) -> List[PeakResult]:
        """
        功能:
            执行 robust_v2 积分流程.
        参数:
            times: 时间数组.
            intensities: 强度数组.
        返回:
            List[PeakResult], 峰列表.
        """
        smoothed_signal = savgol_filter(intensities, self._smoothing_window, polyorder=3)

        baseline = None
        if self._baseline_method == "rolling_quantile":
            baseline = self._rolling_quantile_baseline(smoothed_signal, times)
            if not self._baseline_is_valid(smoothed_signal, baseline):
                logger.warning("滚动分位数基线异常, 自动回退 ALS 基线.")
                baseline = self._als_baseline(intensities.astype(np.float64), self._als_lambda, self._als_p)
        elif self._baseline_method == "als":
            baseline = self._als_baseline(intensities.astype(np.float64), self._als_lambda, self._als_p)
        else:
            logger.warning("未知 baseline_method=%s, 自动使用 rolling_quantile.", self._baseline_method)
            baseline = self._rolling_quantile_baseline(smoothed_signal, times)
            if not self._baseline_is_valid(smoothed_signal, baseline):
                logger.warning("滚动分位数基线异常, 自动回退 ALS 基线.")
                baseline = self._als_baseline(intensities.astype(np.float64), self._als_lambda, self._als_p)

        if not self._baseline_is_valid(smoothed_signal, baseline):
            logger.warning("基线仍异常, 强制使用 ALS 基线.")
            baseline = self._als_baseline(intensities.astype(np.float64), self._als_lambda, self._als_p)

        self.last_baseline = baseline
        corrected_signal = np.maximum(smoothed_signal - baseline, 0)
        baseline_available = baseline is not None and len(baseline) == len(intensities)

        peak_indices, _ = find_peaks(
            corrected_signal,
            prominence=self._prominence,
            distance=self._min_distance,
        )
        if len(peak_indices) == 0:
            logger.info("robust_v2 模式未检测到峰.")
            return []

        boundaries = self._find_robust_boundaries(times, corrected_signal, peak_indices)

        results: List[PeakResult] = []
        for i, peak_idx in enumerate(peak_indices):
            boundary = boundaries[i]
            if boundary is None:
                continue

            left_idx, right_idx = boundary
            left_idx = max(0, left_idx)
            right_idx = min(len(times) - 1, right_idx)
            if right_idx <= left_idx:
                logger.warning("RT=%.3f 的边界非法, 已跳过.", float(times[int(peak_idx)]))
                continue

            peak_times = times[left_idx:right_idx + 1]
            peak_intensities = intensities[left_idx:right_idx + 1]
            if baseline_available:
                peak_baseline = baseline[left_idx:right_idx + 1]
                if len(peak_baseline) == len(peak_times) and np.all(np.isfinite(peak_baseline)):
                    area = self._integrate_with_baseline_array(
                        peak_times,
                        peak_intensities,
                        peak_baseline,
                    )
                else:
                    logger.warning(
                        "RT=%.3f 的全局基线片段无效, 已回退到局部端点基线积分.",
                        float(times[int(peak_idx)]),
                    )
                    area = self._integrate_with_local_baseline(peak_times, peak_intensities)
            else:
                logger.warning(
                    "RT=%.3f 缺少可用全局基线, 已回退到局部端点基线积分.",
                    float(times[int(peak_idx)]),
                )
                area = self._integrate_with_local_baseline(peak_times, peak_intensities)

            results.append(
                self._build_peak_result(
                    times=times,
                    intensities=intensities,
                    peak_idx=int(peak_idx),
                    left_idx=left_idx,
                    right_idx=right_idx,
                    area=area,
                )
            )

        self._update_area_percent(results)
        logger.info("robust_v2 模式积分完成, 峰数量: %d", len(results))
        return results

    def _integrate_gcpy(
        self, times: np.ndarray, intensities: np.ndarray
    ) -> List[PeakResult]:
        """
        功能:
            使用 gcpy 方法执行峰检测与积分:
            1. Whittaker 平滑(gcpy.smooth)用于峰检测与边界定位.
            2. scipy.signal.find_peaks 检测峰位置.
            3. gcpy.bls.lininterp_baseline_subtract 在原始信号上全局扣除基线:
               屏蔽峰区域后对剩余点做样条插值并扣除.
            4. np.trapz 逐峰梯形积分.
        参数:
            times: 时间数组(min).
            intensities: 原始强度数组.
        返回:
            List[PeakResult], 峰积分结果列表.
        """
        from .gcpy.smooth import whittaker_smooth
        from .gcpy.bls import lininterp_baseline_subtract

        signal = intensities.astype(float)

        # Whittaker 平滑, 仅用于峰检测与边界定位, 不改变积分信号
        smoothed = whittaker_smooth(signal, self._gcpy_whittaker_lmbd)

        # 峰检测
        peak_indices, _ = find_peaks(
            smoothed,
            prominence=self._prominence,
            distance=self._min_distance,
        )
        if len(peak_indices) == 0:
            logger.info("gcpy 模式未检测到峰.")
            self.last_baseline = np.zeros_like(signal)
            return []

        # 在平滑信号上获取峰边界
        _, _, left_ips, right_ips = peak_widths(
            smoothed, peak_indices, rel_height=self._width_rel_height
        )

        # 在原始信号上做 lininterp 基线扣除, 保持与绘图坐标一致
        x_indices = np.arange(len(signal), dtype=float)
        try:
            baseline_sub = lininterp_baseline_subtract(signal, x_indices, left_ips, right_ips)
            baseline_array = signal - baseline_sub  # 纯基线数组, 供绘图备用
        except Exception as e:
            logger.warning("gcpy lininterp 基线扣除失败, 回退到不扣除基线: %s", e)
            baseline_sub = signal.copy()
            baseline_array = np.zeros_like(signal)

        self.last_baseline = baseline_array

        # 逐峰梯形积分
        raw_areas: List[float] = []
        for center, left, right in zip(peak_indices, left_ips, right_ips):
            lb = max(0, int(left))
            rb = min(len(times) - 1, int(right) + 1)
            seg_times = times[lb:rb]
            seg_signal = np.maximum(baseline_sub[lb:rb], 0.0)
            # 时间轴转换为秒后积分
            area = float(np.trapz(seg_signal, seg_times * 60.0))
            raw_areas.append(area)

        total_area = sum(raw_areas)

        results: List[PeakResult] = []
        for center, left, right, area in zip(peak_indices, left_ips, right_ips, raw_areas):
            lb = max(0, int(left))
            rb = min(len(times) - 1, int(right))
            rt = float(times[center])
            height = float(signal[center])
            area_pct = (area / total_area * 100.0) if total_area > 0 else 0.0
            start_t = float(times[lb])
            end_t = float(times[rb])
            width = end_t - start_t
            results.append(PeakResult(
                peak_index=int(center),
                retention_time=rt,
                height=height,
                area=area,
                area_percent=area_pct,
                start_time=start_t,
                end_time=end_t,
                width=width,
            ))

        logger.info("gcpy 模式积分完成, 峰数量: %d", len(results))
        return results

    def integrate(self, times: np.ndarray, intensities: np.ndarray) -> List[PeakResult]:
        """
        功能:
            根据配置执行峰检测与积分.
        参数:
            times: 时间数组(min).
            intensities: 强度数组.
        返回:
            List[PeakResult], 峰检测积分结果.
        """
        if len(times) != len(intensities):
            logger.warning("时间与强度长度不一致, 已跳过积分.")
            return []

        if len(times) < self._smoothing_window:
            logger.warning(
                "数据点数 %d 小于平滑窗口 %d, 已跳过积分.",
                len(times),
                self._smoothing_window,
            )
            return []

        mode = self._integration_mode
        if mode == "legacy":
            return self._integrate_legacy(times, intensities)

        if mode == "gcpy":
            return self._integrate_gcpy(times, intensities)

        if mode != "robust_v2":
            logger.warning("未知 integration_mode=%s, 自动使用 robust_v2.", mode)

        return self._integrate_robust_v2(times, intensities)
