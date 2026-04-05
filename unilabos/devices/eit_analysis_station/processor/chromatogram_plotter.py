#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    生成色谱图 (TIC / FID) 的积分结果可视化图.
    标注峰区域, 保留时间, 峰面积, 化合物名称等.
参数:
    无.
返回:
    无.
"""

import logging
import textwrap
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")  # 非交互式后端, 不依赖 GUI
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams["axes.unicode_minus"] = False  # 负号正常显示

from .nist_matcher import CompoundMatch
from .peak_integrator import PeakResult

logger = logging.getLogger(__name__)

# 峰区域填充色板
_PEAK_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
]


class ChromatogramPlotter:
    """
    功能:
        绘制色谱图并标注积分峰, 支持 TIC 和 FID.
    参数:
        chromatogram_ppi: TIC/FID 色谱图导出分辨率.
        ms_spectrum_ppi: 质谱图导出分辨率.
        figsize: 图片尺寸 (宽, 高) 英寸.
    返回:
        无.
    """

    def __init__(
        self,
        chromatogram_ppi: int = 150,
        ms_spectrum_ppi: int = 150,
        figsize: tuple = (14, 6),
    ):
        self._chromatogram_ppi = chromatogram_ppi
        self._ms_spectrum_ppi = ms_spectrum_ppi
        self._figsize = figsize

    def plot_chromatogram(
        self,
        times: np.ndarray,
        intensities: np.ndarray,
        peaks: List[PeakResult],
        compound_matches: Optional[Dict[float, List[CompoundMatch]]] = None,
        title: str = "",
        ylabel: str = "Intensity",
        output_path: Optional[Path] = None,
        rt_min: Optional[float] = None,
        rt_max: Optional[float] = None,
        y_range_min: float = 0,
        baseline: Optional[np.ndarray] = None,
        fill_baseline_mode: str = "local",
    ) -> Path:
        """
        功能:
            绘制色谱图, 标注每个峰的积分区域, 保留时间和峰面积.
            TIC 图额外标注化合物名称 (通过 compound_matches 参数).
            密集峰自动调整标注位置避免遮挡.
        参数:
            times: 保留时间数组 (min).
            intensities: 信号强度数组.
            peaks: 峰检测积分结果列表.
            compound_matches: 保留时间 -> 化合物匹配列表, None 表示不标注化合物名.
            title: 图片标题.
            ylabel: Y 轴标签.
            output_path: 输出图片路径.
            rt_min: X 轴最小保留时间 (min), None 使用数据范围.
            rt_max: X 轴最大保留时间 (min), None 使用数据范围.
            y_range_min: Y 轴最小显示范围, 确保小信号图不会过于压缩.
            baseline: 全局基线数组, 与 times/intensities 等长. 提供时用于峰区域填充,
                      None 时回退到峰端点连线基线.
            fill_baseline_mode: 填充基线模式, local 表示局部端点连线, global 表示优先使用传入 baseline.
        返回:
            Path: 保存的图片路径.
        """
        fig, ax = plt.subplots(1, 1, figsize=self._figsize)
        global_baseline_valid = (
            fill_baseline_mode == "global"
            and baseline is not None
            and len(baseline) == len(times)
        )
        if fill_baseline_mode == "global" and not global_baseline_valid:
            logger.warning("全局基线填充不可用, 自动回退到局部基线填充.")

        # 绘制色谱基线
        ax.plot(times, intensities, color="black", linewidth=0.6, label="Signal")

        for i, peak in enumerate(peaks):
            color = _PEAK_COLORS[i % len(_PEAK_COLORS)]

            # 填充峰区域: 从基线到信号, 与积分计算一致
            mask = (times >= peak.start_time) & (times <= peak.end_time)
            if mask.any():
                peak_times = times[mask]
                peak_intensities = intensities[mask]
                if global_baseline_valid:
                    peak_baseline = np.minimum(baseline[mask], peak_intensities)
                else:
                    # 默认使用局部端点连线, 与积分算法保持一致.
                    peak_baseline = np.linspace(
                        peak_intensities[0],
                        peak_intensities[-1],
                        len(peak_times),
                    )
                ax.fill_between(
                    peak_times, peak_baseline, peak_intensities,
                    alpha=0.3, color=color,
                )

        # X 轴范围: 受 rt_min / rt_max 控制
        x_lo = rt_min if rt_min is not None else float(times[0])
        x_hi = rt_max if rt_max is not None else float(times[-1])
        ax.set_xlim(x_lo, x_hi)

        # Y 轴范围: 基于可见区域内信号最大值, 留上方余量给标注
        visible_mask = (times >= x_lo) & (times <= x_hi)
        if visible_mask.any():
            y_max = float(intensities[visible_mask].max())
            # 确保最小显示范围
            y_max = max(y_max, y_range_min)
            # 留 30% 上方空间给标注文字
            ax.set_ylim(bottom=0, top=y_max * 1.30)

        # 标注峰: 按峰高降序排列, 高峰优先占据正上方位置
        sorted_peaks = sorted(enumerate(peaks), key=lambda x: x[1].height, reverse=True)
        annotations = self._annotate_peaks(
            ax, fig, sorted_peaks, compound_matches, x_lo, x_hi,
        )

        ax.set_xlabel("Retention Time (min)")
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.ticklabel_format(axis="y", style="sci", scilimits=(0, 0))

        plt.tight_layout()

        if output_path is None:
            output_path = Path("chromatogram.png")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(str(output_path), dpi=self._chromatogram_ppi, bbox_inches="tight")
        plt.close(fig)

        logger.info("色谱图已保存: %s", output_path)
        return output_path

    def _annotate_peaks(
        self,
        ax: plt.Axes,
        fig: plt.Figure,
        sorted_peaks: List[Tuple[int, PeakResult]],
        compound_matches: Optional[Dict[float, List[CompoundMatch]]],
        x_lo: float,
        x_hi: float,
    ) -> None:
        """
        功能:
            为所有峰添加标注 (RT + 面积 + 化合物名), 自动调整偏移避免遮挡.
            使用 display 坐标检测文字碰撞, 密集区域交替左右偏移.
        参数:
            ax: matplotlib 坐标轴.
            fig: matplotlib 图形 (用于坐标变换).
            sorted_peaks: 按峰高降序排列的 (原始索引, PeakResult) 列表.
            compound_matches: 化合物匹配字典.
            x_lo: X 轴显示下限.
            x_hi: X 轴显示上限.
        返回:
            无.
        """
        # 收集所有标注信息
        label_items = []
        for _, peak in sorted_peaks:
            # 跳过不在显示范围内的峰
            if peak.retention_time < x_lo or peak.retention_time > x_hi:
                continue

            # 构建标注文本: RT + 面积
            area_str = self._format_area(peak.area)
            label_text = f"RT {peak.retention_time:.2f}\nArea: {area_str}"

            # TIC 图标注化合物名称 (显示全名)
            if compound_matches is not None:
                match_list = self._find_match(peak.retention_time, compound_matches)
                if match_list is not None and len(match_list) > 0:
                    name = self._wrap_compound_name(match_list[0].compound_name)
                    label_text += f"\n{name}"

            label_items.append((peak, label_text))

        # 第一遍: 绘制所有标注, 默认正上方
        fig.canvas.draw()  # 需要先渲染才能获取 display bbox
        placed_bboxes = []  # 已放置标注的 display 坐标 bbox 列表
        signal_display_points = self._collect_signal_display_points(ax, x_lo, x_hi)

        for peak, label_text in label_items:
            # 计算偏移: 检查是否与已有标注重叠
            offset_x, offset_y, horizontal_align = self._compute_offset(
                ax=ax,
                fig=fig,
                peak=peak,
                placed_bboxes=placed_bboxes,
                label_text=label_text,
                signal_display_points=signal_display_points,
            )

            # 引线样式: 标签紧贴峰顶用实线, 较远时用虚线降低视觉噪声
            if offset_y <= 32:
                arrow_props = dict(arrowstyle="-", color="gray", lw=0.5)
            else:
                arrow_props = dict(
                    arrowstyle="-", color="gray", lw=0.4,
                    linestyle=(0, (3, 3)),
                )

            ann = ax.annotate(
                label_text,
                xy=(peak.retention_time, peak.height),
                xytext=(offset_x, offset_y),
                textcoords="offset points",
                ha=horizontal_align, va="bottom",
                fontsize=6,
                arrowprops=arrow_props,
            )

            # 记录已放置标注的 bbox
            fig.canvas.draw()
            bbox = ann.get_window_extent(renderer=fig.canvas.get_renderer())
            placed_bboxes.append(bbox)

    def _compute_offset(
        self,
        ax: plt.Axes,
        fig: plt.Figure,
        peak: PeakResult,
        placed_bboxes: list,
        label_text: str,
        signal_display_points: np.ndarray,
    ) -> Tuple[float, float, str]:
        """
        功能:
            计算标注的 y_offset 偏移量 (单位: points).
            标签始终居中于峰正上方, 仅通过逐步上移避免与已有标注和曲线重叠.
        参数:
            ax: 坐标轴.
            fig: 图形.
            peak: 当前峰.
            placed_bboxes: 已放置标注的 display bbox 列表.
            label_text: 标注文本.
            signal_display_points: 色谱曲线的 display 坐标数组.
        返回:
            Tuple[float, float, str]: (x_offset, y_offset, ha) 偏移量与对齐方式.
        """
        renderer = fig.canvas.get_renderer()
        # 标签始终居中于峰正上方, 仅通过上移避免重叠
        base_y = 14
        y_step = 18
        max_levels = 8

        for level in range(max_levels):
            offset_y = base_y + level * y_step
            bbox = self._measure_annotation_bbox(
                ax=ax, fig=fig, renderer=renderer,
                peak=peak, label_text=label_text,
                offset_x=0, offset_y=offset_y,
                horizontal_align="center",
            )
            overlaps_label = self._has_overlap(bbox, placed_bboxes)
            # 局部碰撞检测: 仅避让标签水平邻域内的曲线
            local_x_margin = bbox.width * 0.5
            overlaps_signal = self._bbox_overlaps_signal(
                bbox, signal_display_points, local_x_margin=local_x_margin,
            )

            if overlaps_label is False and overlaps_signal is False:
                return (0, offset_y, "center")

        # 所有候选位置均有重叠, 使用最高位置
        return (0, base_y + (max_levels - 1) * y_step, "center")

    @staticmethod
    def _collect_signal_display_points(
        ax: plt.Axes,
        x_lo: float,
        x_hi: float,
    ) -> np.ndarray:
        """
        功能:
            提取可见 chromatogram 曲线的 display 坐标, 用于标签避让.

        参数:
            ax: matplotlib 坐标轴.
            x_lo: 可见区间下界.
            x_hi: 可见区间上界.

        返回:
            np.ndarray, shape=(n_points, 2) 的 display 坐标数组.
        """
        if len(ax.lines) == 0:
            return np.empty((0, 2), dtype=float)

        signal_line = ax.lines[0]
        x_data = np.asarray(signal_line.get_xdata(), dtype=float)
        y_data = np.asarray(signal_line.get_ydata(), dtype=float)
        visible_mask = (x_data >= float(x_lo)) & (x_data <= float(x_hi))
        if bool(np.any(visible_mask)) is False:
            return np.empty((0, 2), dtype=float)

        visible_xy = np.column_stack([x_data[visible_mask], y_data[visible_mask]])
        return ax.transData.transform(visible_xy)

    def _measure_annotation_bbox(
        self,
        ax: plt.Axes,
        fig: plt.Figure,
        renderer,
        peak: PeakResult,
        label_text: str,
        offset_x: float,
        offset_y: float,
        horizontal_align: str,
    ):
        """
        功能:
            测量候选标注位置对应的 display bbox.

        参数:
            ax: matplotlib 坐标轴.
            fig: matplotlib 图形.
            renderer: 当前 renderer.
            peak: 当前峰.
            label_text: 标注文本.
            offset_x: X 偏移.
            offset_y: Y 偏移.
            horizontal_align: 水平对齐方式.

        返回:
            Bbox, 候选位置的 display bbox.
        """
        tmp = ax.annotate(
            label_text,
            xy=(peak.retention_time, peak.height),
            xytext=(offset_x, offset_y),
            textcoords="offset points",
            ha=horizontal_align,
            va="bottom",
            fontsize=6,
        )
        fig.canvas.draw()
        bbox = tmp.get_window_extent(renderer)
        tmp.remove()
        return bbox

    @staticmethod
    def _bbox_overlaps_signal(
        bbox,
        signal_display_points: np.ndarray,
        padding: float = 2.0,
        local_x_margin: float = 0.0,
    ) -> bool:
        """
        功能:
            判断标注 bbox 是否压到 chromatogram 曲线.
            当 local_x_margin > 0 时, 仅检测标签水平邻域内的曲线点,
            避免远处高峰曲线干扰小峰标签定位.

        参数:
            bbox: 标注 display bbox.
            signal_display_points: chromatogram 的 display 坐标数组.
            padding: 额外间距 (display pixels).
            local_x_margin: 局部 X 范围余量 (display pixels), 0 表示全局检测.

        返回:
            bool: True 表示 bbox 覆盖到曲线.
        """
        if len(signal_display_points) == 0:
            return False

        # 局部化: 仅保留标签水平邻域内的曲线点
        points = signal_display_points
        if local_x_margin > 0:
            x_mask = (
                (points[:, 0] >= bbox.x0 - local_x_margin)
                & (points[:, 0] <= bbox.x1 + local_x_margin)
            )
            points = points[x_mask]
            if len(points) == 0:
                return False

        expanded = bbox.expanded(
            1 + padding / max(bbox.width, 1),
            1 + padding / max(bbox.height, 1),
        )
        inside_mask = (
            (points[:, 0] >= expanded.x0)
            & (points[:, 0] <= expanded.x1)
            & (points[:, 1] >= expanded.y0)
            & (points[:, 1] <= expanded.y1)
        )
        return bool(np.any(inside_mask))

    @staticmethod
    def _has_overlap(bbox, placed_bboxes: list, padding: float = 2.0) -> bool:
        """
        功能:
            检查 bbox 是否与已放置的任一标注 bbox 重叠.
        参数:
            bbox: 待检测的 display 坐标 bbox.
            placed_bboxes: 已放置标注的 bbox 列表.
            padding: 额外间距 (display pixels).
        返回:
            bool: True 表示有重叠.
        """
        expanded = bbox.expanded(
            1 + padding / max(bbox.width, 1),
            1 + padding / max(bbox.height, 1),
        )
        for existing in placed_bboxes:
            if expanded.overlaps(existing):
                return True
        return False

    @staticmethod
    def _format_area(area: float) -> str:
        """
        功能:
            将峰面积格式化为紧凑的科学计数法字符串.
        参数:
            area: 峰面积.
        返回:
            str: 格式化字符串, 如 "1.23e6", "456".
        """
        if abs(area) >= 1e6:
            return f"{area:.2e}"
        elif abs(area) >= 1000:
            return f"{area:.0f}"
        elif abs(area) >= 1:
            return f"{area:.2f}"
        else:
            return f"{area:.4f}"

    @staticmethod
    def _wrap_compound_name(name: str, max_line_length: int = 22) -> str:
        """
        功能:
            对过长化合物名称自动换行, 减少峰标注的横向占位.
        参数:
            name: 原始化合物名称.
            max_line_length: 单行最大字符数.
        返回:
            str, 插入换行后的化合物名称.
        """
        normalized_name = " ".join(str(name).split())
        if len(normalized_name) <= max_line_length:
            return normalized_name

        # 优先按空格和连字符断行, 实在过长时再切分连续长串.
        return textwrap.fill(
            normalized_name,
            width=max_line_length,
            break_long_words=True,
            break_on_hyphens=True,
        )

    def plot_ms_spectrum(
        self,
        mz: np.ndarray,
        intensities: np.ndarray,
        title: str = "",
        output_path: Optional[Path] = None,
        top_n_labels: int = 10,
    ) -> Path:
        """
        功能:
            绘制单个峰的质谱棒状图 (m/z vs relative intensity).
            自动标注强度最高的 top_n_labels 个离子的 m/z 值.
        参数:
            mz: m/z 数组.
            intensities: 强度数组.
            title: 图片标题.
            output_path: 输出图片路径, None 使用默认路径.
            top_n_labels: 标注 m/z 值的最强峰数量.
        返回:
            Path: 保存的图片路径.
        """
        fig, ax = plt.subplots(1, 1, figsize=(12, 5))

        # 归一化为相对强度 (%)
        max_intensity = intensities.max() if len(intensities) > 0 else 1.0
        if max_intensity == 0:
            max_intensity = 1.0
        rel_intensities = intensities / max_intensity * 100.0

        # 棒状图绘制
        ax.vlines(mz, 0, rel_intensities, colors="#1f77b4", linewidth=0.8)

        # 标注最强的 top_n_labels 个峰的 m/z 值
        if len(mz) > 0:
            n = min(top_n_labels, len(mz))
            top_indices = np.argsort(rel_intensities)[-n:]
            for idx in top_indices:
                ax.annotate(
                    f"{mz[idx]:.1f}",
                    xy=(mz[idx], rel_intensities[idx]),
                    xytext=(0, 4),
                    textcoords="offset points",
                    ha="center", va="bottom",
                    fontsize=7,
                    color="#333333",
                )

        ax.set_xlabel("m/z")
        ax.set_ylabel("Relative Intensity (%)")
        ax.set_title(title)
        ax.set_ylim(bottom=0, top=110)

        # X 轴留边距
        if len(mz) > 0:
            margin = (mz.max() - mz.min()) * 0.05
            ax.set_xlim(mz.min() - max(margin, 5), mz.max() + max(margin, 5))

        plt.tight_layout()

        if output_path is None:
            output_path = Path("ms_spectrum.png")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(str(output_path), dpi=self._ms_spectrum_ppi, bbox_inches="tight")
        plt.close(fig)

        logger.info("质谱图已保存: %s", output_path)
        return output_path

    @staticmethod
    def _find_match(
        rt: float,
        matches: Dict[float, List[CompoundMatch]],
        tolerance: float = 0.05,
    ) -> Optional[List[CompoundMatch]]:
        """按保留时间查找最接近的化合物匹配."""
        if not matches:
            return None
        closest_rt = min(matches.keys(), key=lambda r: abs(r - rt))
        if abs(closest_rt - rt) <= tolerance:
            return matches[closest_rt]
        return None
