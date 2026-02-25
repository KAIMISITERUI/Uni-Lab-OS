#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    将积分结果汇总为 Excel (.xlsx) 表格.
    按任务汇总, 每个任务生成一个 xlsx 文件,
    包含 TIC 峰表, FID 峰表, 样品汇总三个 Sheet.
参数:
    无.
返回:
    无.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .nist_matcher import CompoundMatch
from .peak_integrator import PeakResult

logger = logging.getLogger(__name__)


@dataclass
class SampleResult:
    """
    功能:
        存储单个样品的积分结果(TIC + FID + 化合物匹配).
    参数:
        sample_name: 样品名称.
        d_dir: .D 目录路径.
        tic_peaks: TIC 峰检测与积分结果列表.
        fid_peaks: FID 峰检测与积分结果列表.
        compound_matches: 保留时间 -> 化合物匹配结果.
        acq_time: 采集时间字符串.
    返回:
        SampleResult.
    """
    sample_name: str = ""
    d_dir: Path = field(default_factory=Path)
    tic_peaks: List[PeakResult] = field(default_factory=list)
    fid_peaks: List[PeakResult] = field(default_factory=list)
    compound_matches: Dict[float, CompoundMatch] = field(default_factory=dict)
    acq_time: str = ""


class ReportGenerator:
    """
    功能:
        将积分结果汇总为 Excel 表格.
        按任务汇总, 生成包含 TIC峰表/FID峰表/样品汇总 三个 Sheet 的 xlsx 文件.
    参数:
        无.
    返回:
        无.
    """

    # 表头样式
    _HEADER_FONT = Font(bold=True, size=11)
    _HEADER_FILL = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
    _HEADER_ALIGN = Alignment(horizontal="center", vertical="center")

    # TIC 峰表列定义
    _TIC_HEADERS = [
        "样品名", "峰号", "保留时间(min)", "峰高", "峰面积",
        "面积%", "峰起始(min)", "峰结束(min)", "峰宽(min)",
        "化合物名称", "CAS号", "匹配度",
    ]

    # FID 峰表列定义
    _FID_HEADERS = [
        "样品名", "峰号", "保留时间(min)", "峰高", "峰面积",
        "面积%", "峰起始(min)", "峰结束(min)", "峰宽(min)",
    ]

    # 样品汇总列定义
    _SUMMARY_HEADERS = [
        "样品名", "TIC峰数", "FID峰数", "TIC总面积", "FID总面积", "采集时间",
    ]

    def generate_task_report(
        self,
        task_id: str,
        sample_results: List[SampleResult],
        output_dir: Path,
    ) -> Path:
        """
        功能:
            生成任务级汇总 Excel 报告.
        参数:
            task_id: 任务 ID.
            sample_results: 各样品的积分结果列表.
            output_dir: 输出目录.
        返回:
            Path: 生成的 xlsx 文件路径.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"integration_report_{task_id}.xlsx"

        wb = openpyxl.Workbook()

        # Sheet 1: TIC 峰表
        ws_tic = wb.active
        ws_tic.title = "TIC峰表"
        self._write_tic_sheet(ws_tic, sample_results)

        # Sheet 2: FID 峰表
        ws_fid = wb.create_sheet("FID峰表")
        self._write_fid_sheet(ws_fid, sample_results)

        # Sheet 3: 样品汇总
        ws_summary = wb.create_sheet("样品汇总")
        self._write_summary_sheet(ws_summary, sample_results)

        wb.save(str(output_path))
        logger.info("积分报告已保存: %s", output_path)
        return output_path

    def _write_header(self, ws, headers: List[str]) -> None:
        """写入表头行并设置样式."""
        for col_idx, header in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.font = self._HEADER_FONT
            cell.fill = self._HEADER_FILL
            cell.alignment = self._HEADER_ALIGN

    def _auto_column_width(self, ws) -> None:
        """根据内容自动调整列宽."""
        for col_cells in ws.columns:
            max_length = 0
            col_letter = get_column_letter(col_cells[0].column)
            for cell in col_cells:
                if cell.value is not None:
                    # 中文字符按2字节计算宽度
                    val_str = str(cell.value)
                    char_len = sum(2 if ord(c) > 127 else 1 for c in val_str)
                    max_length = max(max_length, char_len)
            ws.column_dimensions[col_letter].width = min(max_length + 3, 30)

    def _write_tic_sheet(self, ws, sample_results: List[SampleResult]) -> None:
        """
        功能:
            写入 TIC 峰表 Sheet, 包含所有样品的 TIC 峰检测积分结果和化合物匹配.
        """
        self._write_header(ws, self._TIC_HEADERS)

        row = 2
        for sr in sample_results:
            for peak_num, peak in enumerate(sr.tic_peaks, start=1):
                # 按保留时间查找化合物匹配
                match = self._find_match(peak.retention_time, sr.compound_matches)

                ws.cell(row=row, column=1, value=sr.sample_name)
                ws.cell(row=row, column=2, value=peak_num)
                ws.cell(row=row, column=3, value=round(peak.retention_time, 3))
                ws.cell(row=row, column=4, value=round(peak.height, 0))
                ws.cell(row=row, column=5, value=round(peak.area, 2))
                ws.cell(row=row, column=6, value=round(peak.area_percent, 2))
                ws.cell(row=row, column=7, value=round(peak.start_time, 3))
                ws.cell(row=row, column=8, value=round(peak.end_time, 3))
                ws.cell(row=row, column=9, value=round(peak.width, 3))
                ws.cell(row=row, column=10, value=match.compound_name if match else "")
                ws.cell(row=row, column=11, value=match.cas_number if match else "")
                ws.cell(row=row, column=12, value=round(match.match_score, 1) if match else "")
                row += 1

        self._auto_column_width(ws)

    def _write_fid_sheet(self, ws, sample_results: List[SampleResult]) -> None:
        """
        功能:
            写入 FID 峰表 Sheet, 包含所有样品的 FID 峰检测积分结果.
        """
        self._write_header(ws, self._FID_HEADERS)

        row = 2
        for sr in sample_results:
            for peak_num, peak in enumerate(sr.fid_peaks, start=1):
                ws.cell(row=row, column=1, value=sr.sample_name)
                ws.cell(row=row, column=2, value=peak_num)
                ws.cell(row=row, column=3, value=round(peak.retention_time, 3))
                ws.cell(row=row, column=4, value=round(peak.height, 4))
                ws.cell(row=row, column=5, value=round(peak.area, 6))
                ws.cell(row=row, column=6, value=round(peak.area_percent, 2))
                ws.cell(row=row, column=7, value=round(peak.start_time, 3))
                ws.cell(row=row, column=8, value=round(peak.end_time, 3))
                ws.cell(row=row, column=9, value=round(peak.width, 3))
                row += 1

        self._auto_column_width(ws)

    def _write_summary_sheet(self, ws, sample_results: List[SampleResult]) -> None:
        """
        功能:
            写入样品汇总 Sheet, 每个样品一行, 包含峰数和总面积.
        """
        self._write_header(ws, self._SUMMARY_HEADERS)

        for row_idx, sr in enumerate(sample_results, start=2):
            tic_total_area = sum(p.area for p in sr.tic_peaks)
            fid_total_area = sum(p.area for p in sr.fid_peaks)

            ws.cell(row=row_idx, column=1, value=sr.sample_name)
            ws.cell(row=row_idx, column=2, value=len(sr.tic_peaks))
            ws.cell(row=row_idx, column=3, value=len(sr.fid_peaks))
            ws.cell(row=row_idx, column=4, value=round(tic_total_area, 2))
            ws.cell(row=row_idx, column=5, value=round(fid_total_area, 6))
            ws.cell(row=row_idx, column=6, value=sr.acq_time)

        self._auto_column_width(ws)

    @staticmethod
    def _find_match(
        rt: float,
        matches: Dict[float, CompoundMatch],
        tolerance: float = 0.05,
    ) -> Optional[CompoundMatch]:
        """按保留时间在匹配字典中查找最接近的化合物."""
        if not matches:
            return None
        closest_rt = min(matches.keys(), key=lambda r: abs(r - rt))
        if abs(closest_rt - rt) <= tolerance:
            return matches[closest_rt]
        return None
