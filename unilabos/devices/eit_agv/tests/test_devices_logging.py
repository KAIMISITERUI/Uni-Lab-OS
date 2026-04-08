# coding: utf-8
"""
功能:
    验证 devices_logging 共享彩色日志模块及四个模块入口的接入行为.
参数:
    无.
返回:
    无, 通过 unittest 执行断言.
"""

import io
import logging
import os
import shutil
import tempfile
import unittest
import uuid
from unittest.mock import patch

from devices_logging import ColorFormatter, configure_root_logging


_AGV_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data",
)


class _FakeTtyStream(io.StringIO):
    """
    功能:
        模拟支持 TTY 的文本输出流.
    参数:
        无.
    返回:
        无.
    """

    def isatty(self) -> bool:
        """
        功能:
            返回 True, 表示支持彩色终端.
        参数:
            无.
        返回:
            bool, 固定 True.
        """
        return True


class _FakePipeStream(io.StringIO):
    """
    功能:
        模拟非 TTY 的文本输出流.
    参数:
        无.
    返回:
        无.
    """

    def isatty(self) -> bool:
        """
        功能:
            返回 False, 表示不应启用彩色终端.
        参数:
            无.
        返回:
            bool, 固定 False.
        """
        return False


class _RootLoggingTestCase(unittest.TestCase):
    """
    功能:
        提供 root logger 清理逻辑, 避免测试间互相污染.
    参数:
        无.
    返回:
        无.
    """

    def _clear_root_handlers(self) -> None:
        """
        功能:
            清空 root logger 的 handler.
        参数:
            无.
        返回:
            无.
        """
        root_logger = logging.getLogger()
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                continue

    def tearDown(self) -> None:
        """
        功能:
            每个测试结束后清空 root logger 的 handler.
        参数:
            无.
        返回:
            无.
        """
        self._clear_root_handlers()


class TestColorFormatter(_RootLoggingTestCase):
    """
    功能:
        验证 ColorFormatter 的基础行为.
    参数:
        无.
    返回:
        无.
    """

    def test_color_formatter_applies_color_for_info(self) -> None:
        """
        功能:
            验证启用颜色时 INFO 等级会带 ANSI 颜色码.
        参数:
            无.
        返回:
            无.
        """
        formatter = ColorFormatter(use_color=True)
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="消息",
            args=(),
            exc_info=None,
        )

        formatted = formatter.format(record)

        self.assertIn("[INFO]", formatted)
        self.assertIn("\x1b[", formatted)

    def test_color_formatter_keeps_plain_text_when_disabled(self) -> None:
        """
        功能:
            验证禁用颜色时输出保持纯文本.
        参数:
            无.
        返回:
            无.
        """
        formatter = ColorFormatter(use_color=False)
        record = logging.LogRecord(
            name="test",
            level=logging.WARNING,
            pathname=__file__,
            lineno=1,
            msg="消息",
            args=(),
            exc_info=None,
        )

        formatted = formatter.format(record)

        self.assertIn("[WARNING]", formatted)
        self.assertNotIn("\x1b[", formatted)


class TestConfigureRootLogging(_RootLoggingTestCase):
    """
    功能:
        验证共享 root logger 配置行为.
    参数:
        无.
    返回:
        无.
    """

    def test_non_tty_stream_does_not_emit_ansi(self) -> None:
        """
        功能:
            验证非 TTY 输出流不会写入 ANSI 颜色码.
        参数:
            无.
        返回:
            无.
        """
        stream = _FakePipeStream()

        configure_root_logging(level="INFO", stream=stream)
        logging.getLogger("test_non_tty").info("普通日志")

        output = stream.getvalue()
        self.assertIn("[INFO]", output)
        self.assertNotIn("\x1b[", output)
        self.assertEqual(len(logging.getLogger().handlers), 1)

    def test_file_handler_never_emits_ansi(self) -> None:
        """
        功能:
            验证文件日志始终保持纯文本.
        参数:
            无.
        返回:
            无.
        """
        stream = _FakeTtyStream()

        temp_dir = os.path.join(_AGV_DATA_DIR, f"devices_logging_{uuid.uuid4().hex}")
        os.makedirs(temp_dir, exist_ok=True)
        try:
            log_file = os.path.join(temp_dir, "test.log")
            configure_root_logging(level="INFO", log_file=log_file, stream=stream)
            logging.getLogger("test_file").error("文件日志测试")

            for handler in logging.getLogger().handlers:
                handler.flush()

            console_output = stream.getvalue()
            self.assertIn("\x1b[", console_output)

            with open(log_file, "r", encoding="utf-8") as file_obj:
                file_output = file_obj.read()

            self.assertIn("[ERROR]", file_output)
            self.assertNotIn("\x1b[", file_output)
        finally:
            self._clear_root_handlers()
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_reconfigure_root_logging_does_not_duplicate_handlers(self) -> None:
        """
        功能:
            验证重复配置 root logger 时不会重复挂载 handler.
        参数:
            无.
        返回:
            无.
        """
        stream = _FakePipeStream()

        configure_root_logging(level="INFO", stream=stream)
        configure_root_logging(level="DEBUG", stream=stream)
        logging.getLogger("test_reconfigure").info("仅输出一次")

        self.assertEqual(len(logging.getLogger().handlers), 1)
        self.assertEqual(stream.getvalue().count("仅输出一次"), 1)


class TestLoggingIntegration(_RootLoggingTestCase):
    """
    功能:
        验证各模块入口接入共享彩色日志配置.
    参数:
        无.
    返回:
        无.
    """

    def test_synthesis_configure_logging_installs_color_formatter(self) -> None:
        """
        功能:
            验证合成站 configure_logging 使用共享 ColorFormatter.
        参数:
            无.
        返回:
            无.
        """
        from eit_synthesis_station.config.setting import configure_logging

        configure_logging("INFO")

        root_logger = logging.getLogger()
        self.assertEqual(len(root_logger.handlers), 1)
        self.assertIsInstance(root_logger.handlers[0].formatter, ColorFormatter)

    def test_analysis_configure_logging_installs_color_formatter(self) -> None:
        """
        功能:
            验证分析站 configure_logging 使用共享 ColorFormatter.
        参数:
            无.
        返回:
            无.
        """
        from eit_analysis_station.config.setting import configure_logging

        configure_logging("INFO")

        root_logger = logging.getLogger()
        self.assertEqual(len(root_logger.handlers), 1)
        self.assertIsInstance(root_logger.handlers[0].formatter, ColorFormatter)

    def test_agv_monitor_setup_logging_installs_console_and_file_handlers(self) -> None:
        """
        功能:
            验证 AGV 监控入口同时安装彩色控制台 handler 和纯文本文件 handler.
        参数:
            无.
        返回:
            无.
        """
        from eit_agv.controller.auto_charge_pp5_cp6_monitor import _setup_logging

        temp_dir = os.path.join(_AGV_DATA_DIR, f"devices_logging_monitor_{uuid.uuid4().hex}")
        os.makedirs(temp_dir, exist_ok=True)
        try:
            _setup_logging(temp_dir)

            root_logger = logging.getLogger()
            file_handlers = [handler for handler in root_logger.handlers if isinstance(handler, logging.FileHandler)]
            console_handlers = [
                handler for handler in root_logger.handlers
                if isinstance(handler, logging.StreamHandler) and isinstance(handler, logging.FileHandler) is False
            ]

            self.assertEqual(len(file_handlers), 1)
            self.assertEqual(len(console_handlers), 1)
            self.assertIsInstance(console_handlers[0].formatter, ColorFormatter)

            logging.getLogger("test_agv_monitor").warning("监控日志测试")
            for handler in root_logger.handlers:
                handler.flush()

            with open(os.path.join(temp_dir, "auto_charge_pp5_cp6_monitor.log"), "r", encoding="utf-8") as file_obj:
                file_output = file_obj.read()

            self.assertIn("[WARNING]", file_output)
            self.assertNotIn("\x1b[", file_output)
        finally:
            self._clear_root_handlers()
            shutil.rmtree(temp_dir, ignore_errors=True)

    @patch("builtins.input", side_effect=["0"])
    def test_hub_interactive_configures_logging_before_menu(self, mock_input) -> None:
        """
        功能:
            验证 Hub 交互入口启动时会显式初始化统一日志配置.
        参数:
            mock_input: 模拟用户立即退出.
        返回:
            无.
        """
        from eit_hub.main import interactive

        interactive()

        root_logger = logging.getLogger()
        self.assertGreaterEqual(len(root_logger.handlers), 1)
        self.assertIsInstance(root_logger.handlers[0].formatter, ColorFormatter)


if __name__ == "__main__":
    unittest.main(verbosity=2)
