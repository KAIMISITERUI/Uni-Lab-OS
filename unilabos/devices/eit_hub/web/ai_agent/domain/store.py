# -*- coding: utf-8 -*-
"""
功能:
    AI 助手会话数据存储, 使用 stdlib sqlite3 单表反规范化设计.
    全部消息行落入同一张 ai_messages 表, 会话通过 session_id 派生; session_title 写时冗余,
    以便会话改名只需 UPDATE WHERE session_id, 列表派生只需 GROUP BY.
    Pending 控制类工具的等待状态作为消息行的 status 字段持久化, 重启不丢.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger("EITHubAiAgentStore")

JsonDict = Dict[str, Any]

AI_AGENT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "ai_agent.db"

# 消息状态常量
STATUS_COMMITTED = "committed"
STATUS_PENDING = "pending_confirm"
STATUS_REJECTED = "rejected"

# 角色常量, 与 OpenAI 协议一致
ROLE_SYSTEM = "system"
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_TOOL = "tool"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ai_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    session_title TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT,
    reasoning_content TEXT,
    tool_calls_json TEXT,
    tool_call_id TEXT,
    status TEXT NOT NULL DEFAULT 'committed',
    pending_tool_name TEXT,
    pending_tool_args_json TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_messages_session_time
    ON ai_messages (session_id, created_at);
"""


def _now_iso() -> str:
    """
    功能:
        返回当前 UTC 时间的 ISO8601 文本.
    返回:
        str, 形如 2026-05-01T12:34:56.789012+00:00 的时间戳.
    """
    return datetime.now(timezone.utc).isoformat()


def _build_title_from_text(text: str, max_len: int = 24) -> str:
    """
    功能:
        从首条用户消息内容截取会话标题.
    参数:
        text: str, 消息原文.
        max_len: int, 标题最大字符数.
    返回:
        str, 截断后的标题, 空字符串时返回固定占位文本.
    """
    cleaned = (text or "").strip().replace("\n", " ")
    if cleaned == "":
        return "新对话"
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1] + "…"


class AiAgentStore:
    """
    功能:
        AI 助手会话存储. 提供会话创建, 消息追加, 历史查询, pending 状态机等能力.
    """

    def __init__(self, db_path: Path = AI_AGENT_DB_PATH) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA_SQL)
            self._ensure_schema(conn)
            conn.commit()
        logger.info("AI 助手存储已初始化: %s", self._db_path)

    @staticmethod
    def _ensure_schema(conn: sqlite3.Connection) -> None:
        """
        功能:
            补齐 ai_messages 表的增量字段, 兼容已经存在的本地 SQLite 文件.
        参数:
            conn: sqlite3.Connection, 当前数据库连接.
        返回:
            None.
        """
        rows = conn.execute("PRAGMA table_info(ai_messages)").fetchall()
        column_names = {str(row["name"]) for row in rows}
        if "reasoning_content" not in column_names:
            conn.execute("ALTER TABLE ai_messages ADD COLUMN reasoning_content TEXT")
            logger.info("AI 助手消息表已新增字段: reasoning_content")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """
        功能:
            上下文形式建立 SQLite 连接, 退出时显式关闭, 避免 Windows 上 WAL 文件锁.
        返回:
            Iterator[sqlite3.Connection], 已配置的连接对象.
        """
        conn = sqlite3.connect(self._db_path, check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()

    # ---------- 会话级操作 ----------

    @staticmethod
    def new_session_id() -> str:
        """
        功能:
            生成一个新的会话 ID.
        返回:
            str, uuid4 的 hex 表示.
        """
        return uuid.uuid4().hex

    def list_sessions(self, keyword: str = "", page: int = 1, page_size: int = 20) -> JsonDict:
        """
        功能:
            派生会话列表, 按最近一条消息时间倒序返回.
        参数:
            keyword: str, 标题模糊匹配关键词, 空字符串表示不过滤.
            page: int, 页码, 从 1 起.
            page_size: int, 每页条数.
        返回:
            Dict, 含 sessions 列表与 total 总数.
        """
        if page < 1:
            page = 1
        if page_size < 1:
            page_size = 20
        offset = (page - 1) * page_size

        keyword_clean = (keyword or "").strip()

        base_where = ""
        params: List[Any] = []
        if keyword_clean != "":
            base_where = "WHERE session_title LIKE ?"
            params.append(f"%{keyword_clean}%")

        with self._lock:
            with self._connect() as conn:
                total_row = conn.execute(
                    f"""
                    SELECT COUNT(DISTINCT session_id) AS total
                    FROM ai_messages
                    {base_where}
                    """,
                    params,
                ).fetchone()
                total = int(total_row["total"]) if total_row is not None else 0

                rows = conn.execute(
                    f"""
                    SELECT session_id,
                           MAX(session_title) AS title,
                           MIN(created_at) AS started_at,
                           MAX(created_at) AS last_at,
                           SUM(CASE WHEN role='user' THEN 1 ELSE 0 END) AS user_turns,
                           COUNT(*) AS message_count
                    FROM ai_messages
                    {base_where}
                    GROUP BY session_id
                    ORDER BY MAX(created_at) DESC
                    LIMIT ? OFFSET ?
                    """,
                    [*params, page_size, offset],
                ).fetchall()

        sessions = [
            {
                "session_id": row["session_id"],
                "title": row["title"],
                "started_at": row["started_at"],
                "last_at": row["last_at"],
                "user_turns": int(row["user_turns"] or 0),
                "message_count": int(row["message_count"] or 0),
            }
            for row in rows
        ]
        return {"sessions": sessions, "total": total, "page": page, "page_size": page_size}

    def list_messages(self, session_id: str, include_reasoning_content: bool = False) -> List[JsonDict]:
        """
        功能:
            按时间升序返回指定会话的全部消息行.
        参数:
            session_id: str, 会话 ID.
            include_reasoning_content: bool, 是否返回 DeepSeek thinking 内容, 默认不向外暴露.
        返回:
            List[Dict], 消息行字典列表, 字段与 SQLite 列对齐并把 JSON 文本字段反序列化.
        """
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM ai_messages
                    WHERE session_id = ?
                    ORDER BY created_at ASC, id ASC
                    """,
                    (session_id,),
                ).fetchall()
        return [
            self._row_to_dict(row, include_reasoning_content=include_reasoning_content)
            for row in rows
        ]

    def rename_session(self, session_id: str, new_title: str) -> int:
        """
        功能:
            修改指定会话的标题, 同步刷新该会话所有消息行的 session_title 冗余字段.
        参数:
            session_id: str, 会话 ID.
            new_title: str, 新标题, 不能为空.
        返回:
            int, 受影响的行数.
        """
        title_clean = (new_title or "").strip()
        if title_clean == "":
            raise ValueError("会话标题不能为空.")
        with self._lock:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    UPDATE ai_messages
                    SET session_title = ?
                    WHERE session_id = ?
                    """,
                    (title_clean, session_id),
                )
                conn.commit()
                rowcount = cursor.rowcount
        if rowcount == 0:
            raise KeyError(f"未找到会话: {session_id}")
        logger.info("会话已重命名: %s, 受影响 %d 行", session_id, rowcount)
        return rowcount

    def delete_session(self, session_id: str) -> int:
        """
        功能:
            删除指定会话的全部消息行.
        参数:
            session_id: str, 会话 ID.
        返回:
            int, 受影响的行数.
        """
        with self._lock:
            with self._connect() as conn:
                cursor = conn.execute(
                    "DELETE FROM ai_messages WHERE session_id = ?",
                    (session_id,),
                )
                conn.commit()
                rowcount = cursor.rowcount
        if rowcount == 0:
            raise KeyError(f"未找到会话: {session_id}")
        logger.info("会话已删除: %s, 受影响 %d 行", session_id, rowcount)
        return rowcount

    # ---------- 消息级操作 ----------

    def _resolve_session_title(self, conn: sqlite3.Connection, session_id: str, fallback_text: str) -> str:
        """
        功能:
            读取该会话已有标题, 若是首条消息则用 fallback_text 截取生成.
        参数:
            conn: sqlite3.Connection, 复用的连接.
            session_id: str, 会话 ID.
            fallback_text: str, 用于首次创建会话时生成标题的原文.
        返回:
            str, 会话标题.
        """
        row = conn.execute(
            "SELECT session_title FROM ai_messages WHERE session_id = ? LIMIT 1",
            (session_id,),
        ).fetchone()
        if row is not None:
            return str(row["session_title"])
        return _build_title_from_text(fallback_text)

    def append_user_message(self, session_id: str, content: str) -> JsonDict:
        """
        功能:
            写入一条 user 角色消息, 首次写入时自动生成会话标题.
        参数:
            session_id: str, 会话 ID.
            content: str, 用户消息原文.
        返回:
            Dict, 已落库的消息字典.
        """
        with self._lock:
            with self._connect() as conn:
                title = self._resolve_session_title(conn, session_id, content)
                created_at = _now_iso()
                cursor = conn.execute(
                    """
                    INSERT INTO ai_messages
                        (session_id, session_title, role, content, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (session_id, title, ROLE_USER, content, STATUS_COMMITTED, created_at),
                )
                conn.commit()
                message_id = int(cursor.lastrowid)
        return {
            "id": message_id,
            "session_id": session_id,
            "session_title": title,
            "role": ROLE_USER,
            "content": content,
            "status": STATUS_COMMITTED,
            "created_at": created_at,
        }

    def append_assistant_message(
        self,
        session_id: str,
        content: Optional[str],
        tool_calls: Optional[List[JsonDict]] = None,
        reasoning_content: Optional[str] = None,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
    ) -> JsonDict:
        """
        功能:
            写入一条 assistant 角色消息, 内容与工具调用至少有其一非空.
        参数:
            session_id: str, 会话 ID.
            content: str 或 None, 文本内容.
            tool_calls: List[Dict] 或 None, OpenAI 协议的 tool_calls 数组.
            reasoning_content: str 或 None, DeepSeek thinking 内容, 仅用于协议回放.
            prompt_tokens: int 或 None, 输入 token 用量.
            completion_tokens: int 或 None, 输出 token 用量.
        返回:
            Dict, 已落库的消息字典.
        """
        tool_calls_json = None
        if tool_calls is not None and len(tool_calls) > 0:
            tool_calls_json = json.dumps(tool_calls, ensure_ascii=False)

        reasoning_content_value = None
        if isinstance(reasoning_content, str) is True and reasoning_content != "":
            reasoning_content_value = reasoning_content
        with self._lock:
            with self._connect() as conn:
                title = self._resolve_session_title(conn, session_id, "")
                created_at = _now_iso()
                cursor = conn.execute(
                    """
                    INSERT INTO ai_messages
                        (session_id, session_title, role, content, reasoning_content,
                         tool_calls_json, status, prompt_tokens, completion_tokens, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        title,
                        ROLE_ASSISTANT,
                        content,
                        reasoning_content_value,
                        tool_calls_json,
                        STATUS_COMMITTED,
                        prompt_tokens,
                        completion_tokens,
                        created_at,
                    ),
                )
                conn.commit()
                message_id = int(cursor.lastrowid)
        return {
            "id": message_id,
            "session_id": session_id,
            "session_title": title,
            "role": ROLE_ASSISTANT,
            "content": content,
            "tool_calls": tool_calls,
            "status": STATUS_COMMITTED,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "created_at": created_at,
        }

    def append_tool_message(
        self,
        session_id: str,
        tool_call_id: str,
        content: str,
        status: str = STATUS_COMMITTED,
        pending_tool_name: Optional[str] = None,
        pending_tool_args: Optional[JsonDict] = None,
    ) -> JsonDict:
        """
        功能:
            写入一条 tool 角色消息, status 可为 committed (已执行) 或 pending_confirm (等待确认).
        参数:
            session_id: str, 会话 ID.
            tool_call_id: str, 对应 assistant.tool_calls[i].id.
            content: str, 工具结果或占位文案.
            status: str, 消息状态.
            pending_tool_name: str 或 None, 等待确认时记录工具名.
            pending_tool_args: Dict 或 None, 等待确认时记录工具入参.
        返回:
            Dict, 已落库的消息字典.
        """
        pending_args_json = json.dumps(pending_tool_args, ensure_ascii=False) if pending_tool_args is not None else None
        with self._lock:
            with self._connect() as conn:
                title = self._resolve_session_title(conn, session_id, "")
                created_at = _now_iso()
                cursor = conn.execute(
                    """
                    INSERT INTO ai_messages
                        (session_id, session_title, role, content, tool_call_id,
                         status, pending_tool_name, pending_tool_args_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        title,
                        ROLE_TOOL,
                        content,
                        tool_call_id,
                        status,
                        pending_tool_name,
                        pending_args_json,
                        created_at,
                    ),
                )
                conn.commit()
                message_id = int(cursor.lastrowid)
        return {
            "id": message_id,
            "session_id": session_id,
            "session_title": title,
            "role": ROLE_TOOL,
            "content": content,
            "tool_call_id": tool_call_id,
            "status": status,
            "pending_tool_name": pending_tool_name,
            "pending_tool_args": pending_tool_args,
            "created_at": created_at,
        }

    def resolve_pending_tool(
        self,
        session_id: str,
        message_id: int,
        new_status: str,
        new_content: str,
    ) -> JsonDict:
        """
        功能:
            把 pending_confirm 的 tool 消息落地为 committed 或 rejected,
            content 字段被替换为执行结果或拒绝说明.
        参数:
            session_id: str, 会话 ID.
            message_id: int, 待解决的消息行 ID.
            new_status: str, committed 或 rejected.
            new_content: str, 替换后的消息内容.
        返回:
            Dict, 更新后的消息行字典.
        """
        if new_status not in (STATUS_COMMITTED, STATUS_REJECTED):
            raise ValueError(f"未支持的状态: {new_status}")
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM ai_messages WHERE id = ? AND session_id = ?",
                    (message_id, session_id),
                ).fetchone()
                if row is None:
                    raise KeyError(f"未找到消息: {message_id}")
                if row["status"] != STATUS_PENDING:
                    raise ValueError(f"消息状态不是 pending_confirm: 当前 {row['status']}")
                conn.execute(
                    """
                    UPDATE ai_messages
                    SET status = ?, content = ?
                    WHERE id = ?
                    """,
                    (new_status, new_content, message_id),
                )
                conn.commit()
                updated = conn.execute(
                    "SELECT * FROM ai_messages WHERE id = ?",
                    (message_id,),
                ).fetchone()
        logger.info("pending tool 消息已解决: id=%s, status=%s", message_id, new_status)
        return self._row_to_dict(updated)

    def get_pending_tool(self, session_id: str, message_id: int) -> Optional[JsonDict]:
        """
        功能:
            查找指定 ID 的 pending_confirm 消息, 用于校验前端发来的确认请求合法.
        参数:
            session_id: str, 会话 ID.
            message_id: int, 消息行 ID.
        返回:
            Dict 或 None, pending 消息字典或不存在/状态不匹配时 None.
        """
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT * FROM ai_messages
                    WHERE id = ? AND session_id = ? AND status = ?
                    """,
                    (message_id, session_id, STATUS_PENDING),
                ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    # ---------- 序列化辅助 ----------

    @staticmethod
    def _row_to_dict(row: Optional[sqlite3.Row], include_reasoning_content: bool = False) -> JsonDict:
        """
        功能:
            把 sqlite3.Row 转成普通字典并反序列化 JSON 列.
        参数:
            row: sqlite3.Row 或 None.
            include_reasoning_content: bool, 是否保留 DeepSeek thinking 内容.
        返回:
            Dict, 消息行字典. row 为 None 时返回空字典.
        """
        if row is None:
            return {}
        result: JsonDict = {key: row[key] for key in row.keys()}
        if result.get("tool_calls_json"):
            try:
                result["tool_calls"] = json.loads(result["tool_calls_json"])
            except json.JSONDecodeError:
                result["tool_calls"] = None
        else:
            result["tool_calls"] = None
        if result.get("pending_tool_args_json"):
            try:
                result["pending_tool_args"] = json.loads(result["pending_tool_args_json"])
            except json.JSONDecodeError:
                result["pending_tool_args"] = None
        else:
            result["pending_tool_args"] = None
        # 不向外暴露 *_json 原始列, 避免前端重复解析.
        result.pop("tool_calls_json", None)
        result.pop("pending_tool_args_json", None)
        if include_reasoning_content is False:
            result.pop("reasoning_content", None)
        return result

    def build_openai_messages(self, session_id: str) -> List[JsonDict]:
        """
        功能:
            从 SQLite 拉取该会话所有 committed/rejected 消息, 拼装成 OpenAI Chat Completions
            兼容的 messages 数组. assistant 行的 tool_calls 与 tool 行的 tool_call_id 一一对齐.
            pending_confirm 的消息一律不进入上下文 (避免协议报错).
        参数:
            session_id: str, 会话 ID.
        返回:
            List[Dict], OpenAI messages 数组.
        """
        rows = self.list_messages(session_id, include_reasoning_content=True)
        messages: List[JsonDict] = []
        for row in rows:
            if row["status"] == STATUS_PENDING:
                continue
            role = row["role"]
            if role == ROLE_USER:
                messages.append({"role": ROLE_USER, "content": row.get("content") or ""})
            elif role == ROLE_ASSISTANT:
                msg: JsonDict = {"role": ROLE_ASSISTANT, "content": row.get("content") or ""}
                reasoning_content = row.get("reasoning_content")
                if isinstance(reasoning_content, str) is True and reasoning_content != "":
                    msg["reasoning_content"] = reasoning_content
                tool_calls = row.get("tool_calls")
                if tool_calls is not None and len(tool_calls) > 0:
                    msg["tool_calls"] = [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": tc.get("arguments_text", "{}"),
                            },
                        }
                        for tc in tool_calls
                    ]
                messages.append(msg)
            elif role == ROLE_TOOL:
                messages.append(
                    {
                        "role": ROLE_TOOL,
                        "tool_call_id": row.get("tool_call_id") or "",
                        "content": row.get("content") or "",
                    }
                )
            elif role == ROLE_SYSTEM:
                messages.append({"role": ROLE_SYSTEM, "content": row.get("content") or ""})
        return messages
