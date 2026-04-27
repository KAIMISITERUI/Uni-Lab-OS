# -*- coding: utf-8 -*-
"""
功能:
    定义 EIT Hub 前端结果区使用的结构化日志条目, 以及 logging.LogRecord 到该条目的转换工具.
    设计要点:
        - 展示通道与诊断通道分离, 仅当显式调用 ui_logger 或 add_log 时才会产生 LogEntry.
        - 级别字段固定为 info / success / warning / error 四种, 直接对接前端染色逻辑.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict


VALID_LEVELS = ("info", "success", "warning", "error")


@dataclass
class LogEntry:
    """
    功能:
        前端结果区展示用的结构化日志条目.
    参数:
        ts: str, ISO 8601 秒级时间戳.
        level: str, info / success / warning / error.
        source: str, 来源标识, 一般为工作流步骤 ID 或子模块名.
        message: str, 日志正文.
    """

    ts: str
    level: str
    source: str
    message: str

    def to_dict(self) -> Dict[str, Any]:
        """
        功能:
            转换为前端可序列化字典.
        返回:
            Dict[str, Any], 含 ts / level / source / message 四个字段.
        """
        return {
            "ts": self.ts,
            "level": self.level,
            "source": self.source,
            "message": self.message,
        }


def make_entry(message: str, level: str = "info", source: str = "") -> LogEntry:
    """
    功能:
        构造一条 LogEntry, 自动打入当前秒级时间戳并校验级别.
    参数:
        message: str, 日志正文.
        level: str, 级别, 非法值会被规范为 info.
        source: str, 来源标识, 默认为空字符串.
    返回:
        LogEntry, 新建的日志条目.
    """
    normalized_level = level if level in VALID_LEVELS else "info"
    timestamp = datetime.now().isoformat(timespec="seconds")
    return LogEntry(ts=timestamp, level=normalized_level, source=source, message=message)


def level_from_record(record: logging.LogRecord) -> str:
    """
    功能:
        从 logging.LogRecord 推断 UI 级别. 调用方可通过 extra={'level_hint': 'success'} 显式声明 success.
    参数:
        record: logging.LogRecord, 原始日志记录.
    返回:
        str, info / success / warning / error 之一.
    """
    hint = getattr(record, "level_hint", None)
    if isinstance(hint, str) and hint in VALID_LEVELS:
        return hint
    if record.levelno >= logging.ERROR:
        return "error"
    if record.levelno >= logging.WARNING:
        return "warning"
    return "info"


def source_from_record(record: logging.LogRecord) -> str:
    """
    功能:
        从 logging.LogRecord 派生来源标识. 优先使用 extra['source'], 否则取 logger 名称末段.
    参数:
        record: logging.LogRecord, 原始日志记录.
    返回:
        str, 来源标识.
    """
    explicit = getattr(record, "source", None)
    if isinstance(explicit, str) and explicit != "":
        return explicit
    name = record.name or ""
    if name == "":
        return ""
    # 截取 logger 名称末段, 例如 eit_hub.ui.agv -> agv
    return name.rsplit(".", 1)[-1]
