# -*- coding: utf-8 -*-
"""
功能:
    验证标签打印作业的会话生命周期.
    确保单次作业结束后立即关闭通讯, 不会等到脚本退出时才提交打印任务.
    同时验证 LabelPrintService 根据 settings.transport 分派出正确的 Transport 实现.
"""

import unittest
from unittest.mock import MagicMock, call, patch

from unilabos.devices.eit_label_printer.config.settings import PrinterSettings
from unilabos.devices.eit_label_printer.driver.label_print_service import LabelPrintService
from unilabos.devices.eit_label_printer.driver.print_engine import execute_print_job
from unilabos.devices.eit_label_printer.driver.transport import (
    DllTransport,
    TcpTransport,
    Transport,
)


SAMPLE_CONFIG = {
    "printer": {
        "ppi": 300,
    },
    "paper": {
        "width": 56,
        "height": 10,
        "unit": "mm",
        "columns": 2,
        "column_gap": 3,
        "margin": 1.8,
        "gap": 0,
        "gap_offset": 0,
        "direction": 1,
    },
    "font": {
        "name": "Arial",
        "size": 60,
        "bold": 0,
        "underline": 0,
        "rotation": 0,
    },
    "position": {
        "x": 10,
        "y": 30,
    },
}


class FakeTransport(Transport):
    """
    功能:
        用于测试的 Transport 桩对象.
        记录 open/send_command/render_windows_text/print_label/close 的调用次数,
        避免依赖真实硬件或 DLL.
    """

    # 类层面声明实现, 同时用 MagicMock 工厂赋给每个实例 (避免共享状态)
    def open(self): ...
    def send_command(self, command): ...
    def render_windows_text(self, x, y, font_height, rotation, bold, underline, font_name, text): ...
    def print_label(self, sets, copies): ...
    def close(self): ...

    def __init__(self):
        self.open = MagicMock()
        self.send_command = MagicMock()
        self.render_windows_text = MagicMock()
        self.print_label = MagicMock()
        self.close = MagicMock()


class TestPrintJobSession(unittest.TestCase):
    """
    功能:
        验证底层打印作业会在单次调用内完成提交.
    """

    def test_execute_print_job_closes_transport_after_print(self):
        """
        功能:
            验证单次打印完成后会立即关闭通讯.
        """
        transport = FakeTransport()

        execute_print_job(transport, SAMPLE_CONFIG, ["123", "456"])

        self.assertEqual(transport.open.call_count, 1)
        self.assertEqual(transport.print_label.call_count, 1)
        self.assertEqual(transport.close.call_count, 1)

    @patch(
        "unilabos.devices.eit_label_printer.driver.print_engine.print_text",
        side_effect=RuntimeError("boom"),
    )
    def test_execute_print_job_closes_transport_when_print_failed(self, mock_print_text):
        """
        功能:
            验证打印异常时仍会关闭通讯, 避免下次作业继续挂起.
        """
        transport = FakeTransport()

        with self.assertRaises(RuntimeError):
            execute_print_job(transport, SAMPLE_CONFIG, ["123", "456"])

        mock_print_text.assert_called_once_with(transport, SAMPLE_CONFIG, ["123", "456"])
        self.assertEqual(transport.open.call_count, 1)
        self.assertEqual(transport.close.call_count, 1)


class TestLabelPrintServiceJobs(unittest.TestCase):
    """
    功能:
        验证服务层按单次作业提交打印任务.
    """

    @patch(
        "unilabos.devices.eit_label_printer.driver.label_print_service.load_config",
        return_value=SAMPLE_CONFIG,
    )
    @patch(
        "unilabos.devices.eit_label_printer.driver.label_print_service.check_printer_ready"
    )
    @patch(
        "unilabos.devices.eit_label_printer.driver.label_print_service.execute_print_job"
    )
    def test_print_label_uses_independent_job_per_copy(
        self,
        mock_execute_print_job,
        mock_check_printer_ready,
        mock_load_config,
    ):
        """
        功能:
            验证服务层每份标签都会单独提交一次打印作业.
        """
        transport = FakeTransport()
        settings = PrinterSettings()
        service = LabelPrintService(settings=settings, config_path="dummy.yaml", transport=transport)

        result = service.print_label(["123", "456"], copies=2)

        self.assertTrue(result)
        mock_load_config.assert_called_once_with("dummy.yaml")
        mock_check_printer_ready.assert_called_once_with(transport, SAMPLE_CONFIG)
        self.assertEqual(mock_execute_print_job.call_count, 2)
        mock_execute_print_job.assert_has_calls(
            [
                call(transport, SAMPLE_CONFIG, ["123", "456"]),
                call(transport, SAMPLE_CONFIG, ["123", "456"]),
            ]
        )


class TestTransportSelection(unittest.TestCase):
    """
    功能:
        验证 LabelPrintService 根据 settings.transport 构造正确的 Transport 子类.
    """

    @patch(
        "unilabos.devices.eit_label_printer.driver.label_print_service.load_config",
        return_value=SAMPLE_CONFIG,
    )
    def test_wifi_settings_produce_tcp_transport(self, _mock_load_config):
        """
        功能:
            settings.transport == "wifi" 时私有方法应返回 TcpTransport.
        """
        settings = PrinterSettings(
            transport="wifi",
            wifi_host="10.0.0.1",
            wifi_port=9100,
            wifi_timeout=2.0,
        )
        service = LabelPrintService(settings=settings, config_path="dummy.yaml")

        transport = LabelPrintService._make_transport(settings)
        self.assertIsInstance(transport, TcpTransport)

    @patch(
        "unilabos.devices.eit_label_printer.driver.label_print_service.load_config",
        return_value=SAMPLE_CONFIG,
    )
    def test_dll_settings_produce_dll_transport(self, _mock_load_config):
        """
        功能:
            settings.transport == "dll" 时私有方法应返回 DllTransport.
            不触发 DLL 加载, 仅验证类型.
        """
        settings = PrinterSettings(
            transport="dll",
            dll_printer_port="FakePrinter",
        )
        service = LabelPrintService(settings=settings, config_path="dummy.yaml")

        transport = LabelPrintService._make_transport(settings)
        self.assertIsInstance(transport, DllTransport)

    def test_unknown_transport_raises_value_error(self):
        """
        功能:
            settings 构造阶段就应拦截未知 transport, 不降级到默认值.
        """
        with self.assertRaises(ValueError):
            PrinterSettings(transport="bogus")


if __name__ == "__main__":
    unittest.main(verbosity=2)
