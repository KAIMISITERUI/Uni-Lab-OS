# -*- coding: utf-8 -*-
"""
功能:
    LangGraph SQLite checkpoint 配置.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ..domain.store import AI_AGENT_DB_PATH


def build_checkpointer(db_path: Path = AI_AGENT_DB_PATH) -> Any:
    """
    功能:
        构造 LangGraph SQLite checkpointer.
    参数:
        db_path: Path, AI Agent 数据库路径.
    返回:
        Any, LangGraph SqliteSaver.
    """
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError as exc:
        raise RuntimeError("未安装 LangGraph SQLite checkpoint 依赖") from exc
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver
