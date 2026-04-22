# -*- coding: utf-8 -*-
"""
功能:
    TSC 标签打印服务类. 封装 print_engine.py 的核心功能为可复用接口.
    支持中文, 自动缩放字号, 自动居中对齐, 兼容单列和多列标签纸.
    通讯方式 (DLL / WiFi TCP) 由 PrinterSettings 决定, 业务层无感知.

用法:
    from unilabos.devices.eit_label_printer.config import PrinterSettings
    from unilabos.devices.eit_label_printer.driver import LabelPrintService

    settings = PrinterSettings.from_env()        # 默认走 wifi
    svc = LabelPrintService(settings=settings)
    svc.connect()
    svc.print_batch(["试剂A", "试剂B", "试剂C"])
    svc.disconnect()
"""

import logging
from typing import List, Optional

try:
    from ..config.settings import PrinterSettings
except ImportError:
    # 允许作为独立包被直接运行 (非 unilabos 部署环境)
    from eit_label_printer.config.settings import PrinterSettings

from .print_engine import (
    load_config,
    check_printer_ready,
    execute_print_job,
)
from .transport import DllTransport, TcpTransport, Transport

logger = logging.getLogger(__name__)


class LabelPrintService:
    """
    功能:
        TSC/TSPL 标签打印服务.
        根据 PrinterSettings.transport 自动构造 DllTransport 或 TcpTransport,
        业务代码只调用 print_label / print_batch, 不关心底层通讯.
    参数:
        settings: PrinterSettings, 包含通讯参数和 YAML/DLL 路径.
                  不传则通过 PrinterSettings.from_env() 构造 (读取环境变量).
        config_path: 可选, 覆盖 settings.config_path. 便于显式指定不同规格 YAML.
        transport: 可选, 外部注入的 Transport 实例, 跳过自动构造. 主要用于单元测试.
    """

    def __init__(
        self,
        settings: Optional[PrinterSettings] = None,
        config_path: Optional[str] = None,
        transport: Optional[Transport] = None,
    ):
        self._settings = settings if settings is not None else PrinterSettings.from_env()
        # 显式 config_path 优先级高于 settings
        yaml_path = config_path if config_path is not None else str(self._settings.config_path)
        self._config_path = yaml_path
        self._config = load_config(yaml_path)
        self._transport = transport
        self._connected = False

    # ──────────────────── 连接管理 ────────────────────

    def connect(self) -> bool:
        """
        功能:
            根据 settings 构造 Transport 并预检打印机可用性.
            预检结束后立即关闭通讯, 避免长期占用同一个会话.
        返回:
            bool, 连接成功返回 True.
        """
        if self._connected:
            return True
        try:
            if self._transport is None:
                self._transport = self._make_transport(self._settings)
            check_printer_ready(self._transport, self._config)
            self._connected = True
            logger.debug("标签打印服务已就绪 (transport=%s)", self._settings.transport)
            return True
        except Exception as exc:
            logger.error("标签打印服务连接失败: %s", exc)
            self._transport = None
            self._connected = False
            return False

    def disconnect(self) -> None:
        """
        功能:
            释放打印服务资源.
        """
        if self._transport is not None:
            try:
                self._transport.close()
            except Exception as exc:
                logger.warning("关闭 transport 时异常: %s", exc)
        self._transport = None
        self._connected = False
        logger.debug("标签打印服务已断开")

    @property
    def connected(self) -> bool:
        """返回当前连接状态."""
        return self._connected

    @property
    def columns(self) -> int:
        """返回配置中的标签列数."""
        return self._config.get("paper", {}).get("columns", 1)

    # ──────────────────── 打印方法 ────────────────────

    def print_label(self, texts: List[str], copies: int = 1) -> bool:
        """
        功能:
            打印一张标签纸(一行), 每列分别渲染对应文字.
            自动计算字号和居中位置.
        参数:
            texts: List[str], 每列的文字内容. 长度应 <= 列数, 不足的列留空.
            copies: int, 打印份数, 默认 1.
        返回:
            bool, 打印指令发送成功返回 True.
        """
        if not self._connected:
            if not self.connect():
                return False
        try:
            for _ in range(copies):
                execute_print_job(self._transport, self._config, texts)
            return True
        except Exception as exc:
            logger.error("标签打印失败: %s", exc)
            return False

    def print_batch(self, text_list: List[str], copies_each: int = 1) -> bool:
        """
        功能:
            批量打印多张标签. 将 text_list 按列数自动分组,
            每组占一行标签纸, 最后不足一组的也打印.
        参数:
            text_list: List[str], 所有要打印的文字内容(扁平列表).
            copies_each: int, 每张标签的打印份数.
        返回:
            bool, 全部打印成功返回 True.
        """
        if not text_list:
            logger.warning("没有需要打印的内容")
            return True

        if not self._connected:
            if not self.connect():
                return False

        cols = self.columns
        total = len(text_list)
        success = True

        try:
            # 按列数分组
            for batch_start in range(0, total, cols):
                batch = text_list[batch_start:batch_start + cols]
                if not self.print_label(batch, copies=copies_each):
                    success = False
                    break

            if success:
                logger.debug("批量打印完成: 共 %d 张标签", total)
        except Exception as exc:
            logger.error("批量打印失败: %s", exc)
            success = False

        return success

    # ──────────────────── 内部方法 ────────────────────

    @staticmethod
    def _make_transport(settings: PrinterSettings) -> Transport:
        """
        功能:
            根据 settings.transport 构造对应 Transport.
            未知取值抛 ValueError, 不降级.
        参数:
            settings: PrinterSettings.
        返回:
            Transport 子类实例.
        """
        mode = settings.transport
        if mode == "dll":
            return DllTransport(str(settings.dll_path), settings.dll_printer_port)
        if mode == "wifi":
            return TcpTransport(
                settings.wifi_host, settings.wifi_port, settings.wifi_timeout
            )
        raise ValueError(f"未知 transport 取值: '{mode}', 仅支持 'dll' 或 'wifi'")
