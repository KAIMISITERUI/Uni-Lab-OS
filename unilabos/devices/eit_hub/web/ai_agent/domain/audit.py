# -*- coding: utf-8 -*-
"""
功能:
    AI Agent 工具调用和人工确认审计存储.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from .store import AI_AGENT_DB_PATH

logger = logging.getLogger("EITHubAiAgentAudit")

JsonDict = Dict[str, Any]

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tool_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    tool_call_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    permission TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    result_json TEXT,
    status TEXT NOT NULL,
    error_text TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tool_events_session
    ON tool_events (session_id, created_at);

CREATE TABLE IF NOT EXISTS human_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    message_id INTEGER NOT NULL,
    tool_call_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    decision TEXT,
    reviewer TEXT,
    reason TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_human_reviews_session
    ON human_reviews (session_id, created_at);
"""


def _now_iso() -> str:
    """
    功能:
        返回当前 UTC ISO8601 时间.
    返回:
        str, 时间戳.
    """
    return datetime.now(timezone.utc).isoformat()


class AgentAuditStore:
    """
    功能:
        工具执行和人工确认审计存储.
    """

    def __init__(self, db_path: Path = AI_AGENT_DB_PATH) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA_SQL)
            conn.commit()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """
        功能:
            创建 SQLite 连接.
        返回:
            Iterator[sqlite3.Connection], 数据库连接.
        """
        conn = sqlite3.connect(self._db_path, check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def record_tool_event(
        self,
        session_id: str,
        tool_call_id: str,
        tool_name: str,
        permission: str,
        arguments: JsonDict,
        status: str,
        result: Optional[JsonDict] = None,
        error_text: Optional[str] = None,
    ) -> JsonDict:
        """
        功能:
            记录一次工具调用事件.
        参数:
            session_id: str, 会话 ID.
            tool_call_id: str, 工具调用 ID.
            tool_name: str, 工具名.
            permission: str, 工具权限.
            arguments: Dict[str, Any], 工具参数.
            status: str, 执行状态.
            result: Optional[Dict[str, Any]], 工具结果.
            error_text: Optional[str], 错误文本.
        返回:
            Dict[str, Any], 审计记录.
        """
        created_at = _now_iso()
        with self._lock:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO tool_events
                        (session_id, tool_call_id, tool_name, permission, arguments_json,
                         result_json, status, error_text, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        tool_call_id,
                        tool_name,
                        permission,
                        json.dumps(arguments, ensure_ascii=False),
                        json.dumps(result, ensure_ascii=False) if result is not None else None,
                        status,
                        error_text,
                        created_at,
                    ),
                )
                conn.commit()
                row = conn.execute("SELECT * FROM tool_events WHERE id = ?", (int(cursor.lastrowid),)).fetchone()
        return self._row_to_dict(row)

    def create_human_review(
        self,
        session_id: str,
        message_id: int,
        tool_call_id: str,
        tool_name: str,
        arguments: JsonDict,
    ) -> JsonDict:
        """
        功能:
            记录一个等待人工确认的控制工具请求.
        参数:
            session_id: str, 会话 ID.
            message_id: int, pending tool 消息 ID.
            tool_call_id: str, 工具调用 ID.
            tool_name: str, 工具名.
            arguments: Dict[str, Any], 工具参数.
        返回:
            Dict[str, Any], 审计记录.
        """
        created_at = _now_iso()
        with self._lock:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO human_reviews
                        (session_id, message_id, tool_call_id, tool_name, arguments_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        message_id,
                        tool_call_id,
                        tool_name,
                        json.dumps(arguments, ensure_ascii=False),
                        created_at,
                    ),
                )
                conn.commit()
                row = conn.execute("SELECT * FROM human_reviews WHERE id = ?", (int(cursor.lastrowid),)).fetchone()
        return self._row_to_dict(row)

    def resolve_human_review(
        self,
        session_id: str,
        message_id: int,
        decision: str,
        reviewer: str = "user",
        reason: str = "",
    ) -> int:
        """
        功能:
            更新人工确认决策.
        参数:
            session_id: str, 会话 ID.
            message_id: int, pending tool 消息 ID.
            decision: str, approve, reject 或 edit.
            reviewer: str, 审核人.
            reason: str, 原因.
        返回:
            int, 受影响行数.
        """
        with self._lock:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    UPDATE human_reviews
                    SET decision = ?, reviewer = ?, reason = ?, resolved_at = ?
                    WHERE session_id = ? AND message_id = ? AND resolved_at IS NULL
                    """,
                    (decision, reviewer, reason, _now_iso(), session_id, message_id),
                )
                conn.commit()
                rowcount = int(cursor.rowcount)
        return rowcount

    @staticmethod
    def _row_to_dict(row: Optional[sqlite3.Row]) -> JsonDict:
        """
        功能:
            将 SQLite 行转为字典并反序列化 JSON 字段.
        参数:
            row: Optional[sqlite3.Row], 数据库行.
        返回:
            Dict[str, Any], 审计记录.
        """
        if row is None:
            return {}
        result: JsonDict = {key: row[key] for key in row.keys()}
        for key in ("arguments_json", "result_json"):
            value = result.pop(key, None)
            try:
                result[key.replace("_json", "")] = json.loads(value or "{}")
            except json.JSONDecodeError:
                result[key.replace("_json", "")] = {}
        return result
