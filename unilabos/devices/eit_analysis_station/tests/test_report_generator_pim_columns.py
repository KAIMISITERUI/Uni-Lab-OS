#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    验证 TIC 峰表中的 PIM 预测列写入行为.
参数:
    无.
返回:
    无.
"""

import unittest
from pathlib import Path

import openpyxl

from eit_analysis_station.processor.peak_integrator import PeakResult
from eit_analysis_station.processor.report_generator import (
    PIMPrediction,
    ReportGenerator,
    SampleResult,
)


class TestReportGeneratorPIMColumns(unittest.TestCase):
    """
    功能:
        覆盖 PIM 列头与结果写入.
    参数:
        无.
    返回:
        无.
    """

    @staticmethod
    def _build_sample_ok() -> SampleResult:
        """
        功能:
            构建包含 ok 状态 PIM 预测的样品对象.
        参数:
            无.
        返回:
            SampleResult.
        """
        return SampleResult(
            sample_name="sample-1",
            d_dir=Path("sample-1.D"),
            tic_peaks=[
                PeakResult(
                    peak_index=1,
                    retention_time=5.000,
                    height=1000.0,
                    area=5000.0,
                    area_percent=100.0,
                    start_time=4.900,
                    end_time=5.100,
                    width=0.200,
                )
            ],
            pim_predictions={
                5.001: PIMPrediction(
                    predicted_mz=180,
                    predicted_mw=180,
                    confidence_index=1.23456,
                    status="ok",
                    message="PIM 预测成功",
                )
            },
        )

    @staticmethod
    def _build_sample_error() -> SampleResult:
        """
        功能:
            构建包含 error 状态 PIM 预测的样品对象.
        参数:
            无.
        返回:
            SampleResult.
        """
        return SampleResult(
            sample_name="sample-2",
            d_dir=Path("sample-2.D"),
            tic_peaks=[
                PeakResult(
                    peak_index=1,
                    retention_time=6.200,
                    height=800.0,
                    area=3200.0,
                    area_percent=100.0,
                    start_time=6.100,
                    end_time=6.300,
                    width=0.200,
                )
            ],
            pim_predictions={
                6.210: PIMPrediction(
                    predicted_mz=None,
                    predicted_mw=None,
                    confidence_index=None,
                    status="error",
                    message="PIM 置信指数计算失败",
                )
            },
        )

    def test_tic_sheet_contains_pim_headers_and_ok_values(self) -> None:
        """
        功能:
            验证列头存在且 ok 状态可写入数值.
        """
        workbook = openpyxl.Workbook()
        ws = workbook.active

        ReportGenerator()._write_tic_sheet(ws, [self._build_sample_ok()])

        self.assertEqual(ws.cell(row=1, column=21).value, "PIM预测分子离子峰(m/z)")
        self.assertEqual(ws.cell(row=1, column=22).value, "PIM预测分子量(Da)")
        self.assertEqual(ws.cell(row=1, column=23).value, "PIM置信指数")
        self.assertEqual(ws.cell(row=1, column=24).value, "PIM状态")

        self.assertEqual(ws.cell(row=2, column=21).value, 180)
        self.assertEqual(ws.cell(row=2, column=22).value, 180)
        self.assertAlmostEqual(ws.cell(row=2, column=23).value, 1.2346, places=4)
        self.assertEqual(ws.cell(row=2, column=24).value, "ok: PIM 预测成功")

        workbook.close()

    def test_tic_sheet_writes_error_status_without_numeric_values(self) -> None:
        """
        功能:
            验证 error/no_spectrum 状态下仅输出状态说明.
        """
        workbook = openpyxl.Workbook()
        ws = workbook.active

        ReportGenerator()._write_tic_sheet(ws, [self._build_sample_error()])

        self.assertIsNone(ws.cell(row=2, column=21).value)
        self.assertIsNone(ws.cell(row=2, column=22).value)
        self.assertIsNone(ws.cell(row=2, column=23).value)
        self.assertEqual(ws.cell(row=2, column=24).value, "error: PIM 置信指数计算失败")

        workbook.close()


if __name__ == "__main__":
    unittest.main()
