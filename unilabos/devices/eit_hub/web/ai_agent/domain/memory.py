# -*- coding: utf-8 -*-
"""
功能:
    AI Agent 长期记忆存储与检索.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from .store import AI_AGENT_DB_PATH

logger = logging.getLogger("EITHubAiAgentMemory")

JsonDict = Dict[str, Any]

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS agent_memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    user_id TEXT,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_accessed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_agent_memories_user_category
    ON agent_memories (user_id, category);
CREATE INDEX IF NOT EXISTS idx_agent_memories_session
    ON agent_memories (session_id);
"""


def _now_iso() -> str:
    """
    功能:
        返回当前 UTC ISO8601 时间.
    返回:
        str, 时间戳.
    """
    return datetime.now(timezone.utc).isoformat()


class AgentMemoryService:
    """
    功能:
        长期记忆服务. 记忆独立于对话消息, 可跨会话检索.
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

    def add_memory(
        self,
        content: str,
        category: str = "fact",
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        metadata: Optional[JsonDict] = None,
    ) -> JsonDict:
        """
        功能:
            写入一条长期记忆.
        参数:
            content: str, 记忆内容.
            category: str, 记忆分类.
            session_id: Optional[str], 来源会话.
            user_id: Optional[str], 用户 ID.
            metadata: Optional[Dict[str, Any]], 附加元数据.
        返回:
            Dict[str, Any], 新增记忆行.
        """
        cleaned = (content or "").strip()
        if cleaned == "":
            raise ValueError("记忆内容不能为空")
        now = _now_iso()
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
        with self._lock:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO agent_memories
                        (session_id, user_id, category, content, metadata_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (session_id, user_id, category, cleaned, metadata_json, now, now),
                )
                conn.commit()
                memory_id = int(cursor.lastrowid)
                row = conn.execute("SELECT * FROM agent_memories WHERE id = ?", (memory_id,)).fetchone()
        logger.info("AI Agent 长期记忆已写入: id=%s, category=%s", memory_id, category)
        return self._row_to_dict(row)

    def list_memories(
        self,
        keyword: str = "",
        user_id: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 100,
    ) -> List[JsonDict]:
        """
        功能:
            查询长期记忆.
        参数:
            keyword: str, 内容关键词.
            user_id: Optional[str], 用户 ID.
            category: Optional[str], 分类.
            limit: int, 最大条数.
        返回:
            List[Dict[str, Any]], 记忆列表.
        """
        if limit <= 0:
            limit = 100
        if limit > 500:
            limit = 500
        where_parts: List[str] = []
        params: List[Any] = []
        keyword_clean = (keyword or "").strip()
        if keyword_clean != "":
            where_parts.append("content LIKE ?")
            params.append(f"%{keyword_clean}%")
        if user_id is not None and user_id != "":
            where_parts.append("user_id = ?")
            params.append(user_id)
        if category is not None and category != "":
            where_parts.append("category = ?")
            params.append(category)
        where_sql = ""
        if len(where_parts) > 0:
            where_sql = "WHERE " + " AND ".join(where_parts)
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    f"""
                    SELECT * FROM agent_memories
                    {where_sql}
                    ORDER BY updated_at DESC, id DESC
                    LIMIT ?
                    """,
                    [*params, limit],
                ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def delete_memory(self, memory_id: int) -> int:
        """
        功能:
            删除指定长期记忆.
        参数:
            memory_id: int, 记忆 ID.
        返回:
            int, 受影响行数.
        """
        with self._lock:
            with self._connect() as conn:
                cursor = conn.execute("DELETE FROM agent_memories WHERE id = ?", (memory_id,))
                conn.commit()
                rowcount = int(cursor.rowcount)
        if rowcount == 0:
            raise KeyError(f"未找到长期记忆: {memory_id}")
        logger.info("AI Agent 长期记忆已删除: id=%s", memory_id)
        return rowcount

    def persist_turn_memory(self, session_id: str, user_text: str, assistant_text: str, user_id: str = "default") -> List[JsonDict]:
        """
        功能:
            从当前对话轮次提取显式长期记忆. 仅保存用户明确要求记住的信息.
        参数:
            session_id: str, 会话 ID.
            user_text: str, 用户输入.
            assistant_text: str, 助手回答.
            user_id: str, 用户 ID.
        返回:
            List[Dict[str, Any]], 新写入的记忆.
        """
        text = (user_text or "").strip()
        markers = ("记住", "请记住", "以后", "长期", "偏好")
        should_save = any(marker in text for marker in markers)
        if should_save is False:
            return []
        content = text
        return [
            self.add_memory(
                content=content,
                category="user_preference",
                session_id=session_id,
                user_id=user_id,
                metadata={"source": "explicit_user_turn", "assistant_preview": assistant_text[:200]},
            )
        ]

    @staticmethod
    def _row_to_dict(row: Optional[sqlite3.Row]) -> JsonDict:
        """
        功能:
            将 SQLite 行转为字典并反序列化 metadata_json.
        参数:
            row: Optional[sqlite3.Row], 数据库行.
        返回:
            Dict[str, Any], 记忆字典.
        """
        if row is None:
            return {}
        result: JsonDict = {key: row[key] for key in row.keys()}
        metadata_text = result.pop("metadata_json", None)
        try:
            result["metadata"] = json.loads(metadata_text or "{}")
        except json.JSONDecodeError:
            result["metadata"] = {}
        return result
