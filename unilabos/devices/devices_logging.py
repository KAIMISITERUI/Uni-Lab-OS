# coding: utf-8
"""
功能:
    为 devices 下多个模块提供统一的显式彩色日志配置能力.
    控制台日志使用 colorama 对等级字段着色, 文件日志保持纯文本.
"""

import logging
import os
import sys
from typing import Optional, TextIO

from colorama import Fore, Style, just_fix_windows_console


DEFAULT_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_HANDLER_MARK = "_devices_logging_managed"
_CONSOLE_HANDLER_NAME = "devices_console_handler"
_FILE_HANDLER_NAME = "devices_file_handler"


class ColorFormatter(logging.Formatter):
    """
    功能:
        仅对日志等级字段应用颜色的 formatter.

    参数:
        fmt: 日志格式字符串.
        datefmt: 时间格式字符串.
        use_color: 是否启用颜色输出.

    返回:
        无.
    """

    LEVEL_COLORS = {
        logging.DEBUG: Fore.CYAN,
        logging.INFO: Fore.GREEN,
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Fore.LIGHTRED_EX,
    }

    def __init__(
        self,
        fmt: str = DEFAULT_LOG_FORMAT,
        datefmt: str = DEFAULT_DATE_FORMAT,
        use_color: bool = True,
    ) -> None:
        """
        功能:
            初始化彩色日志 formatter.

        参数:
            fmt: 日志格式.
            datefmt: 时间格式.
            use_color: 是否启用颜色.

        返回:
            无.
        """
        super().__init__(fmt=fmt, datefmt=datefmt)
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        """
        功能:
            对格式化后的日志等级字段应用颜色.

        参数:
            record: 日志记录对象.

        返回:
            str, 格式化后的日志文本.
        """
        formatted = super().format(record)

        if self.use_color is False:
            return formatted

        level_segment = f"[{record.levelname}]"
        level_color = self.LEVEL_COLORS.get(record.levelno, "")
        if level_color == "":
            return formatted

        colored_segment = f"{level_color}{level_segment}{Style.RESET_ALL}"
        return formatted.replace(level_segment, colored_segment, 1)


def _resolve_log_level(level: Optional[str], default_level: int) -> int:
    """
    功能:
        将字符串日志等级解析为 logging 数值等级.

    参数:
        level: 可选字符串等级.
        default_level: 默认数值等级.

    返回:
        int, logging 数值等级.
    """
    if level is None:
        return default_level

    numeric_level = getattr(logging, str(level).upper(), None)
    if isinstance(numeric_level, int):
        return numeric_level
    return default_level


def _should_use_color(stream: TextIO) -> bool:
    """
    功能:
        判断指定输出流是否适合启用 ANSI 颜色.

    参数:
        stream: 输出流对象.

    返回:
        bool, True 表示启用颜色.
    """
    isatty_func = getattr(stream, "isatty", None)
    if callable(isatty_func) is False:
        return False

    try:
        return bool(isatty_func())
    except Exception:
        return False


def _close_and_remove_all_handlers(root_logger: logging.Logger) -> None:
    """
    功能:
        关闭并移除 root logger 上的所有 handler.

    参数:
        root_logger: 根日志对象.

    返回:
        无.
    """
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            continue


def configure_root_logging(
    level: str = "INFO",
    *,
    log_file: Optional[str] = None,
    console_level: Optional[str] = None,
    file_level: str = "DEBUG",
    stream: TextIO = sys.stdout,
) -> None:
    """
    功能:
        配置统一的 root logging.
        控制台日志显式彩色输出到 stdout, 文件日志保持纯文本.

    参数:
        level: 默认日志等级.
        log_file: 可选日志文件路径.
        console_level: 控制台日志等级, 未提供时沿用 level.
        file_level: 文件日志等级.
        stream: 控制台输出流, 默认 sys.stdout.

    返回:
        无.
    """
    just_fix_windows_console()

    default_level = _resolve_log_level(level, logging.INFO)
    console_numeric_level = _resolve_log_level(console_level, default_level)
    file_numeric_level = _resolve_log_level(file_level, logging.DEBUG)

    root_logger = logging.getLogger()
    _close_and_remove_all_handlers(root_logger)

    root_level_candidates = [console_numeric_level]
    if log_file is not None:
        root_level_candidates.append(file_numeric_level)
    root_logger.setLevel(min(root_level_candidates))

    console_handler = logging.StreamHandler(stream)
    console_handler.set_name(_CONSOLE_HANDLER_NAME)
    setattr(console_handler, _HANDLER_MARK, True)
    console_handler.setLevel(console_numeric_level)
    console_handler.setFormatter(
        ColorFormatter(
            fmt=DEFAULT_LOG_FORMAT,
            datefmt=DEFAULT_DATE_FORMAT,
            use_color=_should_use_color(stream),
        )
    )
    root_logger.addHandler(console_handler)

    if log_file is not None:
        log_dir = os.path.dirname(os.path.abspath(log_file))
        if log_dir != "":
            os.makedirs(log_dir, exist_ok=True)

        file_handler = logging.FileHandler(log_file, encoding="utf-8", mode="a")
        file_handler.set_name(_FILE_HANDLER_NAME)
        setattr(file_handler, _HANDLER_MARK, True)
        file_handler.setLevel(file_numeric_level)
        file_handler.setFormatter(
            logging.Formatter(
                fmt=DEFAULT_LOG_FORMAT,
                datefmt=DEFAULT_DATE_FORMAT,
            )
        )
        root_logger.addHandler(file_handler)


__all__ = [
    "ColorFormatter",
    "DEFAULT_DATE_FORMAT",
    "DEFAULT_LOG_FORMAT",
    "configure_root_logging",
]
