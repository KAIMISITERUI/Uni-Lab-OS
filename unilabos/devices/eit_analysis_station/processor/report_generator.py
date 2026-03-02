#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    将积分结果汇总为 Excel (.xlsx) 表格.
    按任务汇总, 每个任务生成一个 xlsx 文件,
    包含 TIC 峰表, FID 峰表, TIC-FID 对照表, 样品汇总四个 Sheet.
参数:
    无.
返回:
    无.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .nist_matcher import CompoundMatch
from .peak_integrator import PeakResult

logger = logging.getLogger(__name__)


@dataclass
class PIMPrediction:
    """
    功能:
        存储单个峰的 PIM 分子量预测结果.
    参数:
        predicted_mz: 预测分子离子峰 m/z.
        predicted_mw: 预测分子量(Da).
        confidence_index: PIM 置信指数.
        status: 结果状态, 可选 ok/no_spectrum/error.
        message: 状态说明.
    返回:
        PIMPrediction.
    """
    predicted_mz: Optional[int] = None
    predicted_mw: Optional[int] = None
    confidence_index: Optional[float] = None
    status: str = ""
    message: str = ""


@dataclass
class SSHMPrediction:
    """
    功能:
        存储单个峰的 SS-HM (Simple Search Hitlist Method) 分子量预测结果.
    参数:
        predicted_mw: SS-HM 预测分子量(Da).
        confidence: 概率置信度 (0-1).
        correction: 最佳修正值 (sigma = PIM + correction).
        status: 结果状态, 可选 ok/no_spectrum/error.
        message: 状态说明.
    返回:
        SSHMPrediction.
    """
    predicted_mw: Optional[int] = None
    confidence: Optional[float] = None
    correction: Optional[int] = None
    status: str = ""
    message: str = ""


@dataclass
class iHSHMPrediction:
    """
    功能:
        存储单个峰的 iHS-HM (iterative Hybrid Search Hitlist Method) 分子量预测结果.
    参数:
        predicted_mw: iHS-HM 预测分子量(Da).
        confidence: 置信度 (Omega1 - Omega2) / 999.
        status: 结果状态, 可选 ok/no_spectrum/error.
        message: 状态说明.
    返回:
        iHSHMPrediction.
    """
    predicted_mw: Optional[int] = None
    confidence: Optional[float] = None
    status: str = ""
    message: str = ""


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
        compound_matches: 保留时间 -> 化合物匹配结果列表 (最多2个).
        acq_time: 采集时间字符串.
        nist_result_path: NIST SRCRESLT 结果文件副本路径.
        tic_plot_path: TIC 色谱图图片路径.
        fid_plot_path: FID 色谱图图片路径.
        pim_predictions: 保留时间 -> PIM 预测结果字典.
    返回:
        SampleResult.
    """
    sample_name: str = ""
    d_dir: Path = field(default_factory=Path)
    tic_peaks: List[PeakResult] = field(default_factory=list)
    fid_peaks: List[PeakResult] = field(default_factory=list)
    compound_matches: Dict[float, List[CompoundMatch]] = field(default_factory=dict)
    acq_time: str = ""
    nist_result_path: Optional[Path] = None
    tic_plot_path: Optional[Path] = None
    fid_plot_path: Optional[Path] = None
    ms_plot_paths: Dict[int, Path] = field(default_factory=dict)  # 峰号(1-based) -> 质谱图路径
    pim_predictions: Dict[float, PIMPrediction] = field(default_factory=dict)  # 保留时间 -> PIM 预测结果
    sshm_predictions: Dict[float, SSHMPrediction] = field(default_factory=dict)  # 保留时间 -> SS-HM 预测结果
    ihshm_predictions: Dict[float, iHSHMPrediction] = field(default_factory=dict)  # 保留时间 -> iHS-HM 预测结果

class ReportGenerator:
    """
    功能:
        将积分结果汇总为 Excel 表格.
        按任务汇总, 生成包含 TIC峰表/FID峰表/TIC-FID对照表/样品汇总 四个 Sheet 的 xlsx 文件.
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
        "化合物1(名称)", "化合物1(匹配度)", "化合物1(结构)", "化合物1(分子式)", "化合物1(分子量)",
        "化合物2(名称)", "化合物2(匹配度)", "化合物2(结构)", "化合物2(分子式)", "化合物2(分子量)",
        "质谱图",
        "PIM预测分子量(Da)", "PIM置信指数",
        "SS-HM预测分子量(Da)", "SS-HM置信度",
        "iHS-HM预测分子量(Da)", "iHS-HM置信度",
    ]

    # FID 峰表列定义
    _FID_HEADERS = [
        "样品名", "峰号", "保留时间(min)", "峰高", "峰面积",
        "面积%", "峰起始(min)", "峰结束(min)", "峰宽(min)",
    ]

    # 样品汇总列定义
    _SUMMARY_HEADERS = [
        "样品名", "TIC峰数", "FID峰数", "TIC总面积", "FID总面积", "采集时间",
        "TIC色谱图", "FID色谱图",
    ]

    # TIC-FID 对照表列定义
    _ALIGNMENT_HEADERS = [
        "样品名", "FID峰号", "FID保留时间(min)",
        "TIC峰号", "TIC保留时间(min)", "FID峰面积",
        "化合物1(名称)", "化合物1(匹配度)", "化合物1(分子式)", "化合物1(分子量)",
        "化合物2(名称)", "化合物2(匹配度)", "化合物2(分子式)", "化合物2(分子量)",
    ]

    def generate_task_report(
        self,
        task_id: str,
        sample_results: List[SampleResult],
        output_dir: Path,
        structure_images: Optional[Dict[str, Path]] = None,
        alignment_tolerance: float = 0.05,
        include_tic_only: bool = True,
        include_fid_only: bool = True,
    ) -> Path:
        """
        功能:
            生成任务级汇总 Excel 报告.
        参数:
            task_id: 任务 ID.
            sample_results: 各样品的积分结果列表.
            output_dir: 输出目录.
            structure_images: CAS 号 -> 结构图 PNG 路径的映射, None 表示不嵌入结构图.
            alignment_tolerance: FID 与 TIC 峰保留时间对齐容差(min).
            include_tic_only: 对照表是否输出 TIC 有峰但 FID 无峰的行.
            include_fid_only: 对照表是否输出 FID 有峰但 TIC 无峰的行.
        返回:
            Path: 生成的 xlsx 文件路径.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{task_id}_integration_report.xlsx"

        wb = openpyxl.Workbook()

        # Sheet 1: TIC 峰表
        ws_tic = wb.active
        ws_tic.title = "TIC峰表"
        self._write_tic_sheet(ws_tic, sample_results, structure_images)

        # Sheet 2: FID 峰表
        ws_fid = wb.create_sheet("FID峰表")
        self._write_fid_sheet(ws_fid, sample_results)

        # Sheet 3: TIC-FID 对照表
        ws_align = wb.create_sheet("TIC-FID对照表")
        self._write_alignment_sheet(ws_align, sample_results, alignment_tolerance,
                                    include_tic_only, include_fid_only)

        # Sheet 4: 样品汇总
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

    def _write_tic_sheet(
        self,
        ws,
        sample_results: List[SampleResult],
        structure_images: Optional[Dict[str, Path]] = None,
    ) -> None:
        """
        功能:
            写入 TIC 峰表 Sheet, 包含所有样品的 TIC 峰检测积分结果,
            Top2 化合物匹配及对应的 2D 结构图超链接.
        参数:
            ws: openpyxl Worksheet.
            sample_results: 各样品积分结果列表.
            structure_images: CAS 号 -> 结构图 PNG 路径, None 表示无结构图.
        返回:
            无.
        """
        self._write_header(ws, self._TIC_HEADERS)

        row = 2
        for sr in sample_results:
            for peak_num, peak in enumerate(sr.tic_peaks, start=1):
                # 按保留时间查找化合物匹配列表
                match_list = self._find_match_list(
                    peak.retention_time, sr.compound_matches
                )

                ws.cell(row=row, column=1, value=sr.sample_name)
                ws.cell(row=row, column=2, value=peak_num)
                ws.cell(row=row, column=3, value=round(peak.retention_time, 3))
                ws.cell(row=row, column=4, value=round(peak.height, 0))
                ws.cell(row=row, column=5, value=round(peak.area, 2))
                ws.cell(row=row, column=6, value=round(peak.area_percent, 2))
                ws.cell(row=row, column=7, value=round(peak.start_time, 3))
                ws.cell(row=row, column=8, value=round(peak.end_time, 3))
                ws.cell(row=row, column=9, value=round(peak.width, 3))

                # 填充 Top 2 化合物 (每个化合物占5列: 名称, 匹配度, 结构, 分子式, 分子量)
                for i in range(2):
                    col_name = 10 + i * 5       # 列 10, 15
                    col_score = 11 + i * 5      # 列 11, 16
                    col_struct = 12 + i * 5     # 列 12, 17
                    col_formula = 13 + i * 5    # 列 13, 18
                    col_mw = 14 + i * 5         # 列 14, 19
                    if match_list is not None and i < len(match_list):
                        m = match_list[i]
                        ws.cell(row=row, column=col_name, value=m.compound_name)
                        ws.cell(row=row, column=col_score, value=round(m.match_score, 1))

                        # 结构图超链接: 显示 CAS 号, 点击打开 PNG
                        if (
                            structure_images is not None
                            and m.cas_number
                            and m.cas_number in structure_images
                        ):
                            img_path = structure_images[m.cas_number]
                            if img_path is not None and img_path.exists():
                                cell = ws.cell(
                                    row=row, column=col_struct, value=m.cas_number
                                )
                                cell.hyperlink = str(img_path)
                                cell.font = Font(color="0563C1", underline="single")

                        # 分子式和分子量
                        ws.cell(row=row, column=col_formula, value=m.formula)
                        ws.cell(row=row, column=col_mw, value=round(m.mw, 2) if m.mw else "")
                    else:
                        ws.cell(row=row, column=col_name, value="")
                        ws.cell(row=row, column=col_score, value="")

                # 质谱图超链接 (列 20)
                if peak_num in sr.ms_plot_paths:
                    ms_path = sr.ms_plot_paths[peak_num]
                    if ms_path.exists():
                        cell = ws.cell(row=row, column=20, value="查看质谱")
                        cell.hyperlink = str(ms_path)
                        cell.font = Font(color="0563C1", underline="single")

                # PIM 预测结果 (列 21-22: 预测分子量, 置信指数)
                pim_prediction = self._find_pim_prediction(
                    peak.retention_time, sr.pim_predictions
                )
                if pim_prediction is not None:
                    if pim_prediction.predicted_mw is not None:
                        ws.cell(row=row, column=21, value=pim_prediction.predicted_mw)
                    if pim_prediction.confidence_index is not None:
                        ws.cell(row=row, column=22, value=round(pim_prediction.confidence_index, 4))

                # SS-HM 预测结果 (列 23-24: 预测分子量, 置信度)
                sshm_prediction = self._find_prediction_by_rt(
                    peak.retention_time, sr.sshm_predictions
                )
                if sshm_prediction is not None:
                    if sshm_prediction.predicted_mw is not None:
                        ws.cell(row=row, column=23, value=sshm_prediction.predicted_mw)
                    if sshm_prediction.confidence is not None:
                        ws.cell(row=row, column=24, value=round(sshm_prediction.confidence, 4))

                # iHS-HM 预测结果 (列 25-26: 预测分子量, 置信度)
                ihshm_prediction = self._find_prediction_by_rt(
                    peak.retention_time, sr.ihshm_predictions
                )
                if ihshm_prediction is not None:
                    if ihshm_prediction.predicted_mw is not None:
                        ws.cell(row=row, column=25, value=ihshm_prediction.predicted_mw)
                    if ihshm_prediction.confidence is not None:
                        ws.cell(row=row, column=26, value=round(ihshm_prediction.confidence, 6))

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
            写入样品汇总 Sheet, 每个样品一行, 包含峰数、总面积和色谱图超链接.
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

            # TIC 色谱图超链接
            if sr.tic_plot_path is not None and sr.tic_plot_path.exists():
                cell = ws.cell(row=row_idx, column=7, value="查看色谱图")
                cell.hyperlink = str(sr.tic_plot_path)
                cell.font = Font(color="0563C1", underline="single")

            # FID 色谱图超链接
            if sr.fid_plot_path is not None and sr.fid_plot_path.exists():
                cell = ws.cell(row=row_idx, column=8, value="查看色谱图")
                cell.hyperlink = str(sr.fid_plot_path)
                cell.font = Font(color="0563C1", underline="single")

        self._auto_column_width(ws)

    @staticmethod
    def _align_fid_tic_peaks(
        fid_peaks: List[PeakResult],
        tic_peaks: List[PeakResult],
        tolerance: float = 0.05,
    ) -> List[Tuple[Optional[PeakResult], Optional[int],
                     Optional[PeakResult], Optional[int]]]:
        """
        功能:
            按保留时间对齐 FID 峰和 TIC 峰.
            贪心匹配: 遍历 FID 峰, 对每个 FID 峰在未匹配的 TIC 峰中
            找保留时间最接近且在容差内的峰进行配对.
        参数:
            fid_peaks: FID 峰列表.
            tic_peaks: TIC 峰列表.
            tolerance: 保留时间容差(min), 在此范围内视为同一峰.
        返回:
            List of (fid_peak, fid_peak_num, tic_peak, tic_peak_num).
            未匹配的峰对应字段为 None.
        """
        matched_tic: set = set()  # 已匹配的 TIC 峰索引集合
        pairs: List[Tuple[Optional[PeakResult], Optional[int],
                          Optional[PeakResult], Optional[int]]] = []

        # 遍历 FID 峰, 贪心匹配最近的 TIC 峰
        for fi, fp in enumerate(fid_peaks):
            best_ti: Optional[int] = None
            best_diff = tolerance + 1.0
            for ti, tp in enumerate(tic_peaks):
                if ti in matched_tic:
                    continue
                diff = abs(fp.retention_time - tp.retention_time)
                if diff <= tolerance and diff < best_diff:
                    best_diff = diff
                    best_ti = ti
            if best_ti is not None:
                # FID-TIC 配对成功
                pairs.append((fp, fi + 1, tic_peaks[best_ti], best_ti + 1))
                matched_tic.add(best_ti)
            else:
                # FID 峰无对应 TIC 峰
                pairs.append((fp, fi + 1, None, None))

        # 收集未匹配的 TIC 峰
        for ti, tp in enumerate(tic_peaks):
            if ti not in matched_tic:
                pairs.append((None, None, tp, ti + 1))

        # 按保留时间排序 (取非 None 峰的 RT)
        pairs.sort(key=lambda x: (x[0] or x[2]).retention_time)
        return pairs

    def _write_alignment_sheet(
        self,
        ws,
        sample_results: List[SampleResult],
        tolerance: float = 0.05,
        include_tic_only: bool = True,
        include_fid_only: bool = True,
    ) -> None:
        """
        功能:
            写入 TIC-FID 对照表 Sheet, 按保留时间对齐 FID 和 TIC 峰,
            并展示 TIC 峰对应的 Top2 化合物预测结果.
        参数:
            ws: openpyxl Worksheet.
            sample_results: 各样品积分结果列表.
            tolerance: FID-TIC 峰保留时间对齐容差(min).
            include_tic_only: 是否输出 TIC 有峰但 FID 无峰的行.
            include_fid_only: 是否输出 FID 有峰但 TIC 无峰的行.
        返回:
            无.
        """
        self._write_header(ws, self._ALIGNMENT_HEADERS)

        row = 2
        for sr in sample_results:
            aligned = self._align_fid_tic_peaks(
                sr.fid_peaks, sr.tic_peaks, tolerance
            )
            for fid_peak, fid_num, tic_peak, tic_num in aligned:
                # 根据配置过滤仅单侧有峰的行
                if fid_peak is None and not include_tic_only:
                    continue
                if tic_peak is None and not include_fid_only:
                    continue

                ws.cell(row=row, column=1, value=sr.sample_name)

                # FID 峰信息
                if fid_peak is not None:
                    ws.cell(row=row, column=2, value=fid_num)
                    ws.cell(row=row, column=3,
                            value=round(fid_peak.retention_time, 3))
                    ws.cell(row=row, column=6,
                            value=round(fid_peak.area, 6))

                # TIC 峰信息
                if tic_peak is not None:
                    ws.cell(row=row, column=4, value=tic_num)
                    ws.cell(row=row, column=5,
                            value=round(tic_peak.retention_time, 3))

                    # 查找化合物匹配结果
                    match_list = self._find_match_list(
                        tic_peak.retention_time, sr.compound_matches
                    )
                    # 填充 Top2 化合物 (每个化合物占4列: 名称/匹配度/分子式/分子量)
                    for i in range(2):
                        col_name = 7 + i * 4      # 列 7, 11
                        col_score = 8 + i * 4     # 列 8, 12
                        col_formula = 9 + i * 4   # 列 9, 13
                        col_mw = 10 + i * 4       # 列 10, 14
                        if match_list is not None and i < len(match_list):
                            m = match_list[i]
                            ws.cell(row=row, column=col_name,
                                    value=m.compound_name)
                            ws.cell(row=row, column=col_score,
                                    value=round(m.match_score, 1))
                            ws.cell(row=row, column=col_formula,
                                    value=m.formula)
                            ws.cell(row=row, column=col_mw,
                                    value=round(m.mw, 2) if m.mw else "")

                row += 1

        self._auto_column_width(ws)

    @staticmethod
    def _find_match_list(
        rt: float,
        matches: Dict[float, List[CompoundMatch]],
        tolerance: float = 0.05,
    ) -> Optional[List[CompoundMatch]]:
        """按保留时间在匹配字典中查找最接近的化合物匹配列表."""
        if not matches:
            return None
        closest_rt = min(matches.keys(), key=lambda r: abs(r - rt))
        if abs(closest_rt - rt) <= tolerance:
            return matches[closest_rt]
        return None

    @staticmethod
    def _find_pim_prediction(
        rt: float,
        predictions: Dict[float, PIMPrediction],
        tolerance: float = 0.05,
    ) -> Optional[PIMPrediction]:
        """
        功能:
            按保留时间在 PIM 预测字典中查找最接近结果.
        参数:
            rt: 目标保留时间(min).
            predictions: 保留时间 -> PIM 预测结果.
            tolerance: 保留时间容差(min).
        返回:
            Optional[PIMPrediction], 容差内最近结果.
        """
        if len(predictions) == 0:
            return None
        closest_rt = min(predictions.keys(), key=lambda key_rt: abs(key_rt - rt))
        if abs(closest_rt - rt) <= tolerance:
            return predictions[closest_rt]
        return None

    @staticmethod
    def _find_prediction_by_rt(
        rt: float,
        predictions: Dict,
        tolerance: float = 0.05,
    ):
        """
        功能:
            按保留时间在预测字典中查找最接近结果 (通用版, 支持任意预测类型).
        参数:
            rt: 目标保留时间(min).
            predictions: 保留时间 -> 预测结果字典.
            tolerance: 保留时间容差(min).
        返回:
            容差内最近的预测结果, 或 None.
        """
        if len(predictions) == 0:
            return None
        closest_rt = min(predictions.keys(), key=lambda key_rt: abs(key_rt - rt))
        if abs(closest_rt - rt) <= tolerance:
            return predictions[closest_rt]
        return None


