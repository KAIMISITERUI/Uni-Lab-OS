#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    验证 process_gc_ms_results 的 SS-HM/iHS-HM 搜索开关.
参数:
    无.
返回:
    无.
"""

import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

from eit_analysis_station.config.setting import Settings
from eit_analysis_station.controller.analysis_controller import AnalysisStationController
from eit_analysis_station.processor.peak_integrator import PeakResult
from eit_analysis_station.processor.report_generator import SampleResult


class TestAnalysisControllerSshmSwitch(unittest.TestCase):
    """
    功能:
        覆盖 SS-HM/iHS-HM 搜索开关的环境变量读取和流程分支.
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
        case_dir = tmp_root / f"sshm_switch_{uuid4().hex}"
        case_dir.mkdir(parents=True, exist_ok=False)
        return case_dir

    def test_settings_from_env_reads_gc_ms_sshm_and_ihshm_switch(self) -> None:
        """
        功能:
            验证环境变量可分别驱动 SS-HM 和 iHS-HM 开关.
        参数:
            无.
        返回:
            无.
        """
        with patch.dict(
            os.environ,
            {
                "ANALYSIS_PROCESS_GC_MS_ENABLE_SSHM_SEARCH": "false",
                "ANALYSIS_PROCESS_GC_MS_ENABLE_IHSHM_SEARCH": "true",
            },
            clear=False,
        ):
            settings = Settings.from_env()
        self.assertEqual(settings.process_gc_ms_enable_sshm_search, False)
        self.assertEqual(settings.process_gc_ms_enable_ihshm_search, True)

    def test_settings_from_env_reads_plot_ppi(self) -> None:
        """
        功能:
            验证环境变量可读取色谱图、质谱图和结构图 PPI 配置.
        参数:
            无.
        返回:
            无.
        """
        with patch.dict(
            os.environ,
            {
                "ANALYSIS_CHROMATOGRAM_PLOT_PPI": "220",
                "ANALYSIS_MS_SPECTRUM_PLOT_PPI": "330",
                "ANALYSIS_STRUCTURE_IMAGE_PPI": "440",
            },
            clear=False,
        ):
            settings = Settings.from_env()

        self.assertEqual(settings.chromatogram_plot_ppi, 220)
        self.assertEqual(settings.ms_spectrum_plot_ppi, 330)
        self.assertEqual(settings.structure_image_ppi, 440)

    def test_process_gc_ms_results_skip_mspepsearch_when_both_switch_disabled(self) -> None:
        """
        功能:
            验证 SS-HM/iHS-HM 全部关闭时 process_gc_ms_results 不初始化 MSPepSearchPredictor.
        参数:
            无.
        返回:
            无.
        """
        tmp_path = self._make_tmp_dir()
        settings = Settings(
            mspepsearch_enable=True,
            process_gc_ms_enable_sshm_search=False,
            process_gc_ms_enable_ihshm_search=False,
            report_dir=tmp_path / "report",
            synthesis_tasks_dir=tmp_path / "tasks",
            nist_structure_runtime_cache_path=tmp_path / "runtime_map.pkl",
            structure_offline_only=True,
        )
        controller = AnalysisStationController(settings=settings)

        sample_result = SampleResult(sample_name="sample-1", compound_matches={})
        fake_report_generator = Mock()
        fake_report_generator.generate_task_report.return_value = tmp_path / "report.xlsx"

        with patch.object(controller, "_find_task_dir", return_value=(tmp_path / "task_dir", "123")):
            with patch.object(controller, "_enumerate_d_dirs", return_value=[tmp_path / "sample-1.D"]):
                with patch.object(controller, "_process_single_sample", return_value=sample_result):
                    with patch.object(controller, "_try_auto_yield_calculation", return_value=None):
                        with patch("eit_analysis_station.controller.analysis_controller.NISTMatcher", return_value=Mock()):
                            with patch(
                                "eit_analysis_station.controller.analysis_controller.ReportGenerator",
                                return_value=fake_report_generator,
                            ):
                                with patch(
                                    "eit_analysis_station.controller.analysis_controller.MSPepSearchPredictor",
                                ) as mspep_cls:
                                    result = controller.process_gc_ms_results(task_id="123")

        self.assertEqual(result["success"], True)
        mspep_cls.assert_not_called()

    def test_process_gc_ms_results_init_mspepsearch_when_any_switch_enabled(self) -> None:
        """
        功能:
            验证只开启其中一个开关时 process_gc_ms_results 仍初始化 MSPepSearchPredictor.
        参数:
            无.
        返回:
            无.
        """
        tmp_path = self._make_tmp_dir()
        settings = Settings(
            mspepsearch_enable=True,
            process_gc_ms_enable_sshm_search=False,
            process_gc_ms_enable_ihshm_search=True,
            report_dir=tmp_path / "report",
            synthesis_tasks_dir=tmp_path / "tasks",
            nist_structure_runtime_cache_path=tmp_path / "runtime_map.pkl",
            structure_offline_only=True,
        )
        controller = AnalysisStationController(settings=settings)

        sample_result = SampleResult(sample_name="sample-1", compound_matches={})
        fake_report_generator = Mock()
        fake_report_generator.generate_task_report.return_value = tmp_path / "report.xlsx"

        fake_mspepsearch_instance = Mock()
        fake_mspepsearch_instance.available = True

        with patch.object(controller, "_find_task_dir", return_value=(tmp_path / "task_dir", "123")):
            with patch.object(controller, "_enumerate_d_dirs", return_value=[tmp_path / "sample-1.D"]):
                with patch.object(controller, "_process_single_sample", return_value=sample_result):
                    with patch.object(controller, "_try_auto_yield_calculation", return_value=None):
                        with patch("eit_analysis_station.controller.analysis_controller.NISTMatcher", return_value=Mock()):
                            with patch(
                                "eit_analysis_station.controller.analysis_controller.NistLibraryReader",
                                return_value=Mock(),
                            ):
                                with patch(
                                    "eit_analysis_station.controller.analysis_controller.ReportGenerator",
                                    return_value=fake_report_generator,
                                ):
                                    with patch(
                                        "eit_analysis_station.controller.analysis_controller.MSPepSearchPredictor",
                                        return_value=fake_mspepsearch_instance,
                                    ) as mspep_cls:
                                        result = controller.process_gc_ms_results(task_id="123")

        self.assertEqual(result["success"], True)
        mspep_cls.assert_called_once()

    def test_process_single_sample_passes_plot_ppi_to_plotter(self) -> None:
        """
        功能:
            验证 _process_single_sample 初始化 ChromatogramPlotter 时透传 PPI 参数.
        参数:
            无.
        返回:
            无.
        """
        tmp_path = self._make_tmp_dir()
        settings = Settings(
            pim_enable=False,
            chromatogram_plot_ppi=220,
            ms_spectrum_plot_ppi=330,
        )
        controller = AnalysisStationController(settings=settings)

        fake_reader = Mock()
        fake_reader.read_sample_info.return_value = {"sample_name": "sample-1", "acq_time": ""}
        fake_reader.read_tic.return_value = ([4.8, 5.0, 5.2], [100.0, 200.0, 80.0])
        fake_reader.read_fid.return_value = ([4.8, 5.0, 5.2], [10.0, 20.0, 8.0])
        fake_reader.read_ms_spectra_at_peak.return_value = ([43.0, 58.0], [120.0, 80.0])

        tic_peak = PeakResult(
            peak_index=1,
            retention_time=5.0,
            height=200.0,
            area=20000.0,
            area_percent=100.0,
            start_time=4.9,
            end_time=5.1,
            width=0.2,
        )
        fid_peak = PeakResult(
            peak_index=1,
            retention_time=5.01,
            height=20.0,
            area=30.0,
            area_percent=100.0,
            start_time=4.95,
            end_time=5.08,
            width=0.13,
        )

        tic_integrator = Mock()
        tic_integrator.integrate.return_value = [tic_peak]
        tic_integrator.last_baseline = None

        fid_integrator = Mock()
        fid_integrator.integrate.return_value = [fid_peak]
        fid_integrator.last_baseline = None

        nist = Mock()
        nist.nist_available = False
        nist.match_from_qual_results.return_value = {}

        fake_plotter = Mock()
        fake_plotter.plot_chromatogram.side_effect = [tmp_path / "tic.png", tmp_path / "fid.png"]
        fake_plotter.plot_ms_spectrum.return_value = tmp_path / "ms.png"

        with patch("eit_analysis_station.controller.analysis_controller.GCMSDataReader", return_value=fake_reader):
            with patch(
                "eit_analysis_station.controller.analysis_controller.PeakIntegrator",
                side_effect=[tic_integrator, fid_integrator],
            ):
                with patch(
                    "eit_analysis_station.controller.analysis_controller.ChromatogramPlotter",
                    return_value=fake_plotter,
                ) as plotter_cls:
                    controller._process_single_sample(
                        d_dir=Path("sample-1.D"),
                        nist=nist,
                        report_dir=tmp_path,
                        mspepsearch_predictor=None,
                    )

        plotter_cls.assert_called_once_with(chromatogram_ppi=220, ms_spectrum_ppi=330)
        fake_plotter.plot_ms_spectrum.assert_called_once()

    def _run_single_sample_with_switch(
        self, enable_sshm_search: bool, enable_ihshm_search: bool
    ) -> Mock:
        """
        功能:
            执行一次 _process_single_sample 并返回 mspepsearch_predictor mock, 用于断言调用行为.
        参数:
            enable_sshm_search: 是否开启 SS-HM 搜索.
            enable_ihshm_search: 是否开启 iHS-HM 搜索.
        返回:
            Mock, 传入 _process_single_sample 的 mspepsearch_predictor.
        """
        settings = Settings(
            pim_enable=False,
            process_gc_ms_enable_sshm_search=enable_sshm_search,
            process_gc_ms_enable_ihshm_search=enable_ihshm_search,
        )
        controller = AnalysisStationController(settings=settings)

        fake_reader = Mock()
        fake_reader.read_sample_info.return_value = {"sample_name": "sample-1", "acq_time": ""}
        fake_reader.read_tic.return_value = ([4.8, 5.0, 5.2], [100.0, 200.0, 80.0])
        fake_reader.read_fid.return_value = ([4.8, 5.0, 5.2], [10.0, 20.0, 8.0])
        fake_reader.read_ms_spectra_at_peak.return_value = ([43.0, 58.0], [120.0, 80.0])

        tic_peak = PeakResult(
            peak_index=1,
            retention_time=5.0,
            height=200.0,
            area=20000.0,
            area_percent=100.0,
            start_time=4.9,
            end_time=5.1,
            width=0.2,
        )
        tic_integrator = Mock()
        tic_integrator.integrate.return_value = [tic_peak]
        tic_integrator.last_baseline = None

        fid_integrator = Mock()
        fid_integrator.integrate.return_value = []
        fid_integrator.last_baseline = None

        nist = Mock()
        nist.nist_available = False
        nist.match_from_qual_results.return_value = {}

        mspepsearch_predictor = Mock()
        mspepsearch_predictor.available = True
        mspepsearch_predictor.predict_sshm.return_value = Mock()
        mspepsearch_predictor.predict_ihshm.return_value = Mock()

        with patch("eit_analysis_station.controller.analysis_controller.GCMSDataReader", return_value=fake_reader):
            with patch(
                "eit_analysis_station.controller.analysis_controller.PeakIntegrator",
                side_effect=[tic_integrator, fid_integrator],
            ):
                controller._process_single_sample(
                    d_dir=Path("sample-1.D"),
                    nist=nist,
                    report_dir=None,
                    mspepsearch_predictor=mspepsearch_predictor,
                )

        return mspepsearch_predictor

    def test_process_single_sample_only_ihshm_enabled(self) -> None:
        """
        功能:
            验证只开启 iHS-HM 时, 不调用 predict_sshm, 仅调用 predict_ihshm.
        参数:
            无.
        返回:
            无.
        """
        mspepsearch_predictor = self._run_single_sample_with_switch(
            enable_sshm_search=False,
            enable_ihshm_search=True,
        )
        mspepsearch_predictor.predict_sshm.assert_not_called()
        mspepsearch_predictor.predict_ihshm.assert_called_once()

    def test_process_single_sample_only_sshm_enabled(self) -> None:
        """
        功能:
            验证只开启 SS-HM 时, 调用 predict_sshm, 不调用 predict_ihshm.
        参数:
            无.
        返回:
            无.
        """
        mspepsearch_predictor = self._run_single_sample_with_switch(
            enable_sshm_search=True,
            enable_ihshm_search=False,
        )
        mspepsearch_predictor.predict_sshm.assert_called_once()
        mspepsearch_predictor.predict_ihshm.assert_not_called()


if __name__ == "__main__":
    unittest.main()
