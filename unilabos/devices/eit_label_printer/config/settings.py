# coding: utf-8
"""
功能:
    标签打印模块运行参数.
    YAML 规格文件与 TSCLIB.dll 默认均随包发布, 同时允许通过环境变量覆盖,
    便于不同部署环境 (测试机, 生产机) 切换标签规格或驱动路径.
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


@dataclass
class PrinterSettings:
    """
    功能:
        标签打印模块的运行参数.

    参数:
        config_path: 标签规格 YAML 文件绝对路径, 默认使用包内 profiles/25x10x2.yaml.
        dll_path: TSCLIB.dll 绝对路径, 默认使用包内 libs/TSCLIB.dll.
        log_level: 日志级别字符串, 例如 "INFO".

    返回:
        无.
    """

    config_path: Path = _DEFAULT_CONFIG_PATH
    dll_path: Path = _DEFAULT_DLL_PATH
    log_level: str = "INFO"

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
            LABEL_PRINTER_CONFIG_PATH, LABEL_PRINTER_DLL_PATH, LABEL_PRINTER_LOG_LEVEL.
        """
        default = cls()
        config_path_env = os.environ.get(f"{_ENV_PREFIX}CONFIG_PATH")
        dll_path_env = os.environ.get(f"{_ENV_PREFIX}DLL_PATH")
        log_level = os.environ.get(f"{_ENV_PREFIX}LOG_LEVEL", default.log_level)

        config_path = Path(config_path_env) if config_path_env else default.config_path
        dll_path = Path(dll_path_env) if dll_path_env else default.dll_path

        return cls(
            config_path=config_path,
            dll_path=dll_path,
            log_level=log_level,
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
