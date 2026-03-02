#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    验证 UPLC_QTOF 提交流程是否按 setting 控制追加 wash_stop 停止方法.
参数:
    无.
返回:
    无.
"""

import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from eit_analysis_station.config.setting import Settings
from eit_analysis_station.controller.analysis_controller import AnalysisStationController


def _build_uplc_task_info(method: str = "uplc_method") -> dict:
    """
    功能:
        构造 UPLC_QTOF 最小任务信息, 用于提交流程单元测试.
    参数:
        method: UPLC_QTOF 方法名.
    返回:
        Dict, _do_submit_uplc_qtof 所需的最小字段集合.
    """
    return {
        "exp_count": 2,
        "uplc_qtof_method": method,
        "uplc_qtof_exp_nums": None,
    }


class TestUplcQtofAppendStopMethod(unittest.TestCase):
    """
    功能:
        覆盖 UPLC_QTOF 停止方法追加开关的核心行为.
    参数:
        无.
    返回:
        无.
    """

    def _run_submit_and_capture_csv(self, append_stop: bool) -> str:
        """
        功能:
            执行一次 UPLC_QTOF 提交流程并捕获保存前 CSV 文本.
        参数:
            append_stop: 是否开启追加 wash_stop 停止方法.
        返回:
            str, 保存阶段接收到的 CSV 内容.
        """
        settings = Settings(uplc_qtof_append_wash_stop=append_stop)
        controller = AnalysisStationController(settings=settings)
        captured_csv: dict = {}

        def _fake_save_csv(content: str, task_id: str, instrument: str):
            captured_csv["content"] = content
            self.assertEqual(task_id, "123")
            self.assertEqual(instrument, "uplc_qtof")
            return [Path("uplc_qtof.csv")]

        mock_client = Mock()
        mock_client.start_with_csv_file.return_value = {"success": True, "return_info": "ok"}

        with patch.object(controller, "_save_csv", side_effect=_fake_save_csv) as save_mock:
            with patch("eit_analysis_station.controller.analysis_controller.ZhidaClient", return_value=mock_client):
                result = controller._do_submit_uplc_qtof("123", _build_uplc_task_info())

        self.assertEqual(result["success"], True)
        save_mock.assert_called_once()
        mock_client.connect.assert_called_once()
        mock_client.close.assert_called_once()
        return captured_csv["content"]

    def test_uplc_qtof_not_append_stop_method_when_disabled(self) -> None:
        """
        功能:
            场景A, 开关关闭时 CSV 不应包含 wash_stop 行.
        参数:
            无.
        返回:
            无.
        """
        csv_content = self._run_submit_and_capture_csv(append_stop=False)
        self.assertNotIn(",wash_stop,", csv_content)

    def test_uplc_qtof_append_stop_method_when_enabled(self) -> None:
        """
        功能:
            场景B, 开关开启时 CSV 末尾应追加 wash_stop 行.
        参数:
            无.
        返回:
            无.
        """
        csv_content = self._run_submit_and_capture_csv(append_stop=True)
        self.assertIn(",wash_stop,", csv_content)
        self.assertTrue(csv_content.endswith(",wash_stop,,,,\n"))

    def test_uplc_qtof_skip_when_method_not_configured(self) -> None:
        """
        功能:
            场景C, uplc_qtof_method 为空时仍按原逻辑跳过提交.
        参数:
            无.
        返回:
            无.
        """
        controller = AnalysisStationController(settings=Settings(uplc_qtof_append_wash_stop=True))
        task_info = {"uplc_qtof_method": None}

        with patch.object(controller, "_save_csv") as save_mock:
            with patch("eit_analysis_station.controller.analysis_controller.ZhidaClient") as client_cls:
                result = controller._do_submit_uplc_qtof("123", task_info)

        self.assertEqual(result["success"], True)
        save_mock.assert_not_called()
        client_cls.assert_not_called()

    def test_settings_from_env_reads_append_stop_switch(self) -> None:
        """
        功能:
            场景D, 验证环境变量可正确驱动新增开关.
        参数:
            无.
        返回:
            无.
        """
        with patch.dict(os.environ, {"ANALYSIS_UPLC_QTOF_APPEND_WASH_STOP": "true"}, clear=False):
            settings = Settings.from_env()
        self.assertEqual(settings.uplc_qtof_append_wash_stop, True)

    def test_run_analysis_return_keys_unchanged(self) -> None:
        """
        功能:
            回归检查 run_analysis 返回键保持 gc_ms/uplc_qtof/hplc.
        参数:
            无.
        返回:
            无.
        """
        controller = AnalysisStationController(settings=Settings())
        parsed_task_info = {
            "gc_ms_method": None,
            "uplc_qtof_method": None,
            "hplc_method": None,
        }

        with patch.object(controller, "_find_task_dir", return_value=(Path("dummy"), "123")):
            with patch.object(controller, "_check_task_status", return_value=None):
                with patch.object(controller, "_parse_task_xlsx", return_value=parsed_task_info):
                    result = controller.run_analysis(task_id="123")

        self.assertEqual(set(result.keys()), {"gc_ms", "uplc_qtof", "hplc"})


if __name__ == "__main__":
    unittest.main()
