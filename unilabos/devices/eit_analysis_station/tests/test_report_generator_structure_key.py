#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    验证报告结构列按结构键写入超链接与显示文本.
参数:
    无.
返回:
    无.
"""

import unittest
from pathlib import Path
from uuid import uuid4

import openpyxl

from eit_analysis_station.processor.nist_matcher import CompoundMatch
from eit_analysis_station.processor.peak_integrator import PeakResult
from eit_analysis_station.processor.report_generator import ReportGenerator, SampleResult


class TestReportGeneratorStructureKey(unittest.TestCase):
    """
    功能:
        覆盖结构列 key 匹配与显示文本规则.
    参数:
        无.
    返回:
        无.
    """

    @staticmethod
    def _make_tmp_dir() -> Path:
        """
        功能:
            在仓库可写目录创建临时测试目录.
        参数:
            无.
        返回:
            Path, 临时目录路径.
        """
        tmp_root = Path.cwd() / "eit_analysis_station" / "tests" / "_tmp"
        tmp_root.mkdir(parents=True, exist_ok=True)
        case_dir = tmp_root / f"report_{uuid4().hex}"
        case_dir.mkdir(parents=True, exist_ok=False)
        return case_dir

    @staticmethod
    def _build_sample(match: CompoundMatch) -> SampleResult:
        """
        功能:
            构造最小样品结果用于 TIC 表写入.
        参数:
            match: 化合物命中对象.
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
            compound_matches={5.000: [match]},
        )

    def test_structure_cell_uses_nist_display_when_cas_missing(self) -> None:
        """
        功能:
            验证 CAS 缺失时, 名称列显示化合物名并写入结构图超链接.
        参数:
            无.
        返回:
            无.
        """
        tmp_path = self._make_tmp_dir()
        png_path = tmp_path / "NIST_22326.png"
        png_path.write_bytes(b"png")

        match = CompoundMatch(
            compound_name="Benzylamine",
            cas_number="",
            match_score=92.0,
            nist_id=22326,
        )
        sample = self._build_sample(match)

        workbook = openpyxl.Workbook()
        ws = workbook.active

        ReportGenerator()._write_tic_sheet(
            ws,
            [sample],
            structure_images={"NIST:22326": png_path},
        )

        cell = ws.cell(row=2, column=10)
        self.assertEqual(cell.value, "Benzylamine")
        self.assertEqual(cell.hyperlink.target, str(png_path))
        workbook.close()

    def test_structure_cell_prefers_cas_display_when_cas_exists(self) -> None:
        """
        功能:
            验证存在 CAS 时, 名称列仍显示化合物名并写入结构图超链接.
        参数:
            无.
        返回:
            无.
        """
        tmp_path = self._make_tmp_dir()
        png_path = tmp_path / "NIST_22326.png"
        png_path.write_bytes(b"png")

        match = CompoundMatch(
            compound_name="Benzylamine",
            cas_number="100-46-9",
            match_score=92.0,
            nist_id=22326,
        )
        sample = self._build_sample(match)

        workbook = openpyxl.Workbook()
        ws = workbook.active

        ReportGenerator()._write_tic_sheet(
            ws,
            [sample],
            structure_images={"NIST:22326": png_path},
        )

        cell = ws.cell(row=2, column=10)
        self.assertEqual(cell.value, "Benzylamine")
        self.assertEqual(cell.hyperlink.target, str(png_path))
        workbook.close()


if __name__ == "__main__":
    unittest.main()
