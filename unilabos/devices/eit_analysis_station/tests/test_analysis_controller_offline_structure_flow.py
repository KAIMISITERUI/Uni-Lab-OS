#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    验证 process_gc_ms_results 使用离线结构链路.
参数:
    无.
返回:
    无.
"""

import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

from eit_analysis_station.config.setting import Settings
from eit_analysis_station.controller.analysis_controller import AnalysisStationController
from eit_analysis_station.processor.nist_matcher import CompoundMatch
from eit_analysis_station.processor.report_generator import SampleResult


class TestAnalysisControllerOfflineStructureFlow(unittest.TestCase):
    """
    功能:
        覆盖离线结构获取链路调用, 并确认不走 CAS 批量下载接口.
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
        case_dir = tmp_root / f"ctrl_{uuid4().hex}"
        case_dir.mkdir(parents=True, exist_ok=False)
        return case_dir

    def test_process_gc_ms_results_uses_fetch_batch_from_matches(self) -> None:
        """
        功能:
            验证 process_gc_ms_results 会调用 fetch_batch_from_matches.
        参数:
            无.
        返回:
            无.
        """
        tmp_path = self._make_tmp_dir()
        settings = Settings(
            mspepsearch_enable=False,
            report_dir=tmp_path / "report",
            synthesis_tasks_dir=tmp_path / "tasks",
            nist_structure_runtime_cache_path=tmp_path / "runtime_map.pkl",
            structure_offline_only=True,
        )
        controller = AnalysisStationController(settings=settings)

        sample_result = SampleResult(
            sample_name="sample-1",
            compound_matches={
                5.0: [
                    CompoundMatch(
                        compound_name="Benzylamine",
                        cas_number="100-46-9",
                        nist_id=22326,
                    )
                ]
            },
        )

        fake_png = tmp_path / "NIST_22326.png"
        fake_png.parent.mkdir(parents=True, exist_ok=True)
        fake_png.write_bytes(b"png")

        fake_fetcher = Mock()
        fake_fetcher.fetch_batch_from_matches.return_value = {"NIST:22326": fake_png}

        fake_report_generator = Mock()
        fake_report_generator.generate_task_report.return_value = tmp_path / "report.xlsx"

        with patch.object(controller, "_find_task_dir", return_value=(tmp_path / "task_dir", "123")):
            with patch.object(controller, "_enumerate_d_dirs", return_value=[tmp_path / "sample-1.D"]):
                with patch.object(controller, "_process_single_sample", return_value=sample_result):
                    with patch.object(controller, "_try_auto_yield_calculation", return_value=None):
                        with patch("eit_analysis_station.controller.analysis_controller.NISTMatcher", return_value=Mock()):
                            with patch(
                                "eit_analysis_station.controller.analysis_controller.NistLocalStructureFetcher",
                                return_value=fake_fetcher,
                            ):
                                with patch(
                                    "eit_analysis_station.processor.structure_fetcher.StructureFetcher.fetch_batch",
                                    side_effect=AssertionError("不应调用旧 CAS 批量下载链路"),
                                ):
                                    with patch(
                                        "eit_analysis_station.controller.analysis_controller.ReportGenerator",
                                        return_value=fake_report_generator,
                                    ):
                                        result = controller.process_gc_ms_results(task_id="123")

        self.assertEqual(result["success"], True)
        fake_fetcher.fetch_batch_from_matches.assert_called_once()


if __name__ == "__main__":
    unittest.main()

