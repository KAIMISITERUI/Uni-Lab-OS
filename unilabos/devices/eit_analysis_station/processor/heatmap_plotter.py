#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    从 Excel/CSV 文件生成产率热力图.
    支持数字和特殊文本值(>99, <1, n.p., n.d., trace, Invalid, N/A, Failed)的识别.
参数:
    无.
返回:
    无.
"""

import csv
import logging
import re
from pathlib import Path
from typing import List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")  # 非交互式后端, 不依赖 GUI
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams["axes.unicode_minus"] = False  # 负号正常显示

logger = logging.getLogger(__name__)

# 显示为 0 色值的特殊文本(无产物/未检测)
_ZERO_DISPLAY_VALUES = {"n.p.", "n.d."}

# 显示为 NaN (灰色) 的特殊文本
_NAN_DISPLAY_VALUES = {"invalid", "n/a", "failed"}

# trace 的着色数值
_TRACE_COLOR_VALUE = 1.0


class HeatmapPlotter:
    """
    功能:
        从表格数据生成产率热力图.
    参数:
        dpi: 输出图片分辨率.
    返回:
        无.
    """

    def __init__(self, dpi: int = 300):
        self._dpi = dpi

    def plot(
        self,
        file_path: str,
        output_path: Optional[str] = None,
    ) -> Path:
        """
        功能:
            读取 Excel/CSV 文件并生成热力图, 保存为 PNG.
        参数:
            file_path: 输入 .xlsx 或 .csv 文件路径.
            output_path: 输出 PNG 路径, None 时自动生成同目录同名 .png.
        返回:
            Path, 保存的 PNG 文件路径.
        """
        file_path = Path(file_path)
        if file_path.is_file() is False:
            raise FileNotFoundError(f"输入文件不存在: {file_path}")

        raw_table = self._read_table(file_path)
        if len(raw_table) < 2:
            raise ValueError("表格至少需要 2 行(首行配置 + 数据行).")

        colorbar_label, vmin, vmax = self._parse_header(raw_table[0])

        data_rows = raw_table[1:]
        n_rows = len(data_rows)
        n_cols = max(len(row) for row in data_rows)

        # 构建着色数据矩阵和显示文本矩阵
        color_data = np.full((n_rows, n_cols), np.nan, dtype=float)
        display_texts: List[List[str]] = [[""] * n_cols for _ in range(n_rows)]

        for i, row in enumerate(data_rows):
            for j, cell in enumerate(row):
                color_val, display_text = self._parse_cell(cell)
                if color_val is not None:
                    color_data[i, j] = color_val
                display_texts[i][j] = display_text

        if output_path is not None:
            out = Path(output_path)
        else:
            out = file_path.with_suffix(".png")

        return self._render(
            color_data=color_data,
            display_texts=display_texts,
            colorbar_label=colorbar_label,
            vmin=vmin,
            vmax=vmax,
            output_path=out,
        )

    @staticmethod
    def _read_table(file_path: Path) -> List[List]:
        """
        功能:
            读取 Excel 或 CSV 文件为二维列表.
        参数:
            file_path: 输入文件路径, 支持 .xlsx 和 .csv.
        返回:
            List[List], 行列二维列表, 包含原始单元格值.
        """
        suffix = file_path.suffix.lower()
        if suffix == ".xlsx":
            import openpyxl

            wb = openpyxl.load_workbook(file_path, data_only=True)
            ws = wb.active
            return [[cell.value for cell in row] for row in ws.iter_rows()]
        elif suffix == ".csv":
            with open(file_path, newline="", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                return [row for row in reader]
        else:
            raise ValueError(f"不支持的文件格式: {suffix}, 仅支持 .xlsx 和 .csv.")

    @staticmethod
    def _parse_header(first_row: List) -> Tuple[str, float, float]:
        """
        功能:
            解析首行配置, 提取 colorbar 标签和值范围.
        参数:
            first_row: 表格首行列表, 第一个单元格为标签, 第二个为 "min-max" 范围.
        返回:
            Tuple[str, float, float], (colorbar_label, vmin, vmax).
        """
        if len(first_row) < 2:
            raise ValueError("首行至少需要 2 个单元格: [标签, 范围].")

        colorbar_label = str(first_row[0]).strip()
        range_str = str(first_row[1]).strip()

        match = re.match(r"^([\d.]+)\s*-\s*([\d.]+)$", range_str)
        if match is None:
            raise ValueError(f"无法解析值范围: {range_str!r}, 期望格式 'min-max'.")

        vmin = float(match.group(1))
        vmax = float(match.group(2))
        return colorbar_label, vmin, vmax

    @staticmethod
    def _parse_cell(value) -> Tuple[Optional[float], str]:
        """
        功能:
            解析单个单元格值, 返回用于着色的数值和用于文本标注的字符串.
        参数:
            value: 原始单元格值(可能是 float, int, str 或 None).
        返回:
            Tuple[Optional[float], str]:
                color_value: 着色数值, None 表示使用 NaN(灰色).
                display_text: 在单元格中显示的文本.
        """
        if value is None:
            return (None, "")

        # 已经是数值类型(openpyxl 读取结果)
        if isinstance(value, (int, float)):
            if value != value:  # NaN 检查
                return (None, "")
            if isinstance(value, float) and value == int(value):
                return (value, str(int(value)))
            return (value, str(value))

        text = str(value).strip()
        if text == "":
            return (None, "")

        # >N 模式: 显示原文, 着色为 N
        gt_match = re.match(r"^>\s*([\d.]+)$", text)
        if gt_match is not None:
            return (float(gt_match.group(1)), text)

        # <N 模式: 显示原文, 着色为 N
        lt_match = re.match(r"^<\s*([\d.]+)$", text)
        if lt_match is not None:
            return (float(lt_match.group(1)), text)

        # trace: 着色为 1
        if text.lower() == "trace":
            return (_TRACE_COLOR_VALUE, text)

        # n.p. / n.d.: 着色为 0
        if text.lower() in _ZERO_DISPLAY_VALUES:
            return (0.0, text)

        # Invalid / N/A / Failed: 着色为 NaN(灰色)
        if text.lower() in _NAN_DISPLAY_VALUES:
            return (None, text)

        # 尝试解析为数字(CSV 字符串情况)
        try:
            num = float(text)
            if num != num:  # NaN
                return (None, "")
            if num == int(num):
                return (num, str(int(num)))
            return (num, text)
        except ValueError:
            pass

        # 未知文本: 着色为 NaN, 显示原文
        return (None, text)

    def _render(
        self,
        color_data: np.ndarray,
        display_texts: List[List[str]],
        colorbar_label: str,
        vmin: float,
        vmax: float,
        output_path: Path,
    ) -> Path:
        """
        功能:
            使用 matplotlib 渲染热力图并保存.
        参数:
            color_data: 着色用二维 numpy 数组(NaN 表示灰色).
            display_texts: 与 color_data 同形状的文本标注矩阵.
            colorbar_label: colorbar 的标签文字.
            vmin: colorbar 最小值.
            vmax: colorbar 最大值.
            output_path: 输出 PNG 路径.
        返回:
            Path, 保存的 PNG 文件路径.
        """
        n_rows, n_cols = color_data.shape

        # 图片尺寸随数据量缩放
        cell_width = 1.2
        cell_height = 0.8
        fig_width = max(n_cols * cell_width + 2.0, 4.0)
        fig_height = max(n_rows * cell_height + 1.0, 3.0)
        fig, ax = plt.subplots(1, 1, figsize=(fig_width, fig_height))

        # NaN 区域用浅灰色
        cmap = plt.cm.Blues.copy()
        cmap.set_bad(color="#f0f0f0")

        masked_data = np.ma.masked_invalid(color_data)

        # y 轴坐标: vmax(顶部) 到 vmin(底部) 均匀分布
        y_edges = np.linspace(vmax, vmin, n_rows + 1)
        x_edges = np.arange(n_cols + 1)

        # 格子之间无间隙, 无边线
        im = ax.pcolormesh(
            x_edges,
            y_edges,
            masked_data,
            cmap=cmap,
            vmin=vmin,
            vmax=vmax,
            edgecolors="none",
            linewidth=0,
        )

        # 在每个单元格中标注文本
        value_range = max(vmax - vmin, 1e-9)
        for i in range(n_rows):
            y_center = (y_edges[i] + y_edges[i + 1]) / 2.0
            for j in range(n_cols):
                text = display_texts[i][j]
                if text == "":
                    continue
                x_center = j + 0.5

                # 根据颜色深浅选择文本颜色
                cell_val = color_data[i, j]
                if cell_val != cell_val:  # NaN
                    text_color = "#666666"
                elif (cell_val - vmin) / value_range > 0.6:
                    text_color = "white"
                else:
                    text_color = "black"

                ax.text(
                    x_center,
                    y_center,
                    text,
                    ha="center",
                    va="center",
                    fontsize=10,
                    fontweight="normal",
                    color=text_color,
                )

        # 右侧 colorbar, 去掉边框线
        cbar = fig.colorbar(im, ax=ax, pad=0.02)
        cbar.set_label(colorbar_label, fontsize=11)
        cbar.outline.set_visible(False)

        # 隐藏所有轴刻度, 刻度由 colorbar 承担
        ax.set_xlim(0, n_cols)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.tick_params(left=False, bottom=False, right=False, top=False)

        # 去掉外框线
        for spine in ax.spines.values():
            spine.set_visible(False)

        plt.tight_layout()

        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(str(output_path), dpi=self._dpi, bbox_inches="tight")
        plt.close(fig)

        logger.info("热力图已保存: %s", output_path)
        return output_path
