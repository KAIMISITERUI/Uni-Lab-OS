# coding: utf-8
"""
功能:
    标签打印模块运行参数.
    YAML 规格文件与 TSCLIB.dll 默认均随包发布, 同时允许通过环境变量覆盖,
    便于不同部署环境 (测试机, 生产机) 切换标签规格或驱动路径.
    通讯层参数 (传输方式, USB 打印机名, WiFi IP/端口/超时) 也集中在此,
    职责: settings 管 "打哪儿/怎么打", YAML 管 "打什么规格".
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path

try:
    from devices_logging import configure_root_logging
except ImportError:
    from unilabos.devices.devices_logging import configure_root_logging


logger = logging.getLogger(__name__)


_ENV_PREFIX = "LABEL_PRINTER_"
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CONFIG_PATH = _PACKAGE_ROOT / "profiles" / "25x10x2.yaml"
_DEFAULT_DLL_PATH = _PACKAGE_ROOT / "libs" / "TSCLIB.dll"

# 合法的 transport 取值, 未列入的一律拒绝, 不降级
_VALID_TRANSPORTS = ("wifi", "dll")


@dataclass
class PrinterSettings:
    """
    功能:
        标签打印模块的运行参数.
        包含通讯层配置 (transport/host/port/timeout) 和资源路径 (YAML/DLL).

    参数:
        config_path: 标签规格 YAML 文件绝对路径, 默认使用包内 profiles/25x10x2.yaml.
        dll_path: TSCLIB.dll 绝对路径, 默认使用包内 libs/TSCLIB.dll.
        log_level: 日志级别字符串, 例如 "INFO".
        transport: 传输方式, "wifi" 走 TCP 9100 直连, "dll" 走 TSCLIB + Windows 驱动.
        dll_printer_port: DLL 模式使用的 Windows 打印机名, 必须与系统中安装的名字一致.
        wifi_host: WiFi 模式使用的打印机 IP 地址.
        wifi_port: WiFi 模式使用的 TCP 端口, 佳博 GP-1134T 固定为 9100.
        wifi_timeout: WiFi 模式 socket 连接和读写超时 (秒).

    返回:
        无.
    """

    config_path: Path = _DEFAULT_CONFIG_PATH
    dll_path: Path = _DEFAULT_DLL_PATH
    log_level: str = "INFO"

    # 通讯层参数
    transport: str = "wifi"
    dll_printer_port: str = "Gprinter GP-1134T"
    wifi_host: str = "192.168.1.20"
    wifi_port: int = 9100
    wifi_timeout: float = 5.0

    def __post_init__(self) -> None:
        """
        功能:
            校验 transport 字段必须是合法取值, 未知值立即抛异常, 避免运行时才暴露.
        """
        if self.transport not in _VALID_TRANSPORTS:
            raise ValueError(
                f"未知 transport 取值: '{self.transport}', 可选 {_VALID_TRANSPORTS}"
            )

    @classmethod
    def from_env(cls) -> "PrinterSettings":
        """
        功能:
            从 LABEL_PRINTER_ 前缀环境变量构造配置, 缺省值来自 dataclass 默认值.

        参数:
            无.

        返回:
            PrinterSettings 实例.

        环境变量:
            LABEL_PRINTER_CONFIG_PATH, LABEL_PRINTER_DLL_PATH, LABEL_PRINTER_LOG_LEVEL,
            LABEL_PRINTER_TRANSPORT, LABEL_PRINTER_DLL_PRINTER_PORT,
            LABEL_PRINTER_WIFI_HOST, LABEL_PRINTER_WIFI_PORT, LABEL_PRINTER_WIFI_TIMEOUT.
        """
        default = cls()

        # 路径与日志
        config_path_env = os.environ.get(f"{_ENV_PREFIX}CONFIG_PATH")
        dll_path_env = os.environ.get(f"{_ENV_PREFIX}DLL_PATH")
        log_level = os.environ.get(f"{_ENV_PREFIX}LOG_LEVEL", default.log_level)
        config_path = Path(config_path_env) if config_path_env else default.config_path
        dll_path = Path(dll_path_env) if dll_path_env else default.dll_path

        # 通讯层
        transport = os.environ.get(f"{_ENV_PREFIX}TRANSPORT", default.transport)
        dll_printer_port = os.environ.get(
            f"{_ENV_PREFIX}DLL_PRINTER_PORT", default.dll_printer_port
        )
        wifi_host = os.environ.get(f"{_ENV_PREFIX}WIFI_HOST", default.wifi_host)
        wifi_port_env = os.environ.get(f"{_ENV_PREFIX}WIFI_PORT")
        wifi_timeout_env = os.environ.get(f"{_ENV_PREFIX}WIFI_TIMEOUT")
        wifi_port = int(wifi_port_env) if wifi_port_env else default.wifi_port
        wifi_timeout = (
            float(wifi_timeout_env) if wifi_timeout_env else default.wifi_timeout
        )

        return cls(
            config_path=config_path,
            dll_path=dll_path,
            log_level=log_level,
            transport=transport,
            dll_printer_port=dll_printer_port,
            wifi_host=wifi_host,
            wifi_port=wifi_port,
            wifi_timeout=wifi_timeout,
        )


def configure_logging(level: str = "INFO") -> None:
    """
    功能:
        统一初始化根 logger, 与其它 eit_* 模块保持一致.

    参数:
        level: 日志级别字符串, 例如 "DEBUG", "INFO".

    返回:
        无.
    """
    configure_root_logging(level=level)


__all__ = ["PrinterSettings", "configure_logging"]
