# -*- coding: utf-8 -*-
"""
功能:
    化学品库 SQLite 数据库操作封装.
    提供建表, CRUD, 搜索, 去重, 完整性校验等功能.
"""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config.constants import CORE_COLUMNS, NUMERIC_COLUMNS

logger = logging.getLogger("ChemicalDB")

# 建表 SQL
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS chemicals (
    id                         INTEGER PRIMARY KEY AUTOINCREMENT,
    cas_number                 TEXT,
    chemical_id                TEXT,
    substance                  TEXT,
    substance_english_name     TEXT,
    other_name                 TEXT,
    brand                      TEXT,
    package_size               TEXT,
    storage_location           TEXT,
    molecular_weight           REAL,
    density                    REAL,
    physical_state             TEXT,
    physical_form              TEXT,
    active_content             TEXT,
    smiles                     TEXT,
    extra_json                 TEXT,
    chemicalbook_record_path   TEXT,
    created_at                 TEXT DEFAULT (datetime('now')),
    updated_at                 TEXT DEFAULT (datetime('now'))
);
"""

_CREATE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_cas    ON chemicals(cas_number);",
    "CREATE INDEX IF NOT EXISTS idx_en     ON chemicals(substance_english_name);",
    "CREATE INDEX IF NOT EXISTS idx_cn     ON chemicals(substance);",
    "CREATE INDEX IF NOT EXISTS idx_form   ON chemicals(physical_form);",
]

# 可写入数据库的列名集合 (不含 id, created_at, updated_at)
_WRITABLE_COLUMNS = set(CORE_COLUMNS) | {"extra_json"}


class ChemicalDB:
    """
    功能:
        化学品库 SQLite 数据库的低层封装.
        管理连接, schema, 以及所有 CRUD 与查询操作.
    参数:
        db_path: Path, SQLite 数据库文件路径.
    """

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """
        功能:
            确保数据库表与索引已创建.
        """
        self._conn.execute(_CREATE_TABLE_SQL)
        for index_sql in _CREATE_INDEXES_SQL:
            self._conn.execute(index_sql)
        self._conn.commit()

    def close(self) -> None:
        """
        功能:
            关闭数据库连接.
        """
        self._conn.close()

    # ===================== 行数据序列化 =====================

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        """
        功能:
            将 sqlite3.Row 转换为普通字典.
        参数:
            row: sqlite3.Row, 数据库查询结果行.
        返回:
            Dict[str, Any], 字段字典.
        """
        result = dict(row)
        # 展开 extra_json
        extra_json_str = result.pop("extra_json", None)
        if extra_json_str is not None and extra_json_str != "":
            try:
                extra = json.loads(extra_json_str)
                if isinstance(extra, dict):
                    result.update(extra)
            except (json.JSONDecodeError, TypeError):
                pass
        return result

    @staticmethod
    def _prepare_insert_values(row_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        功能:
            将外部行数据字典拆分为核心列值与 extra_json, 用于 INSERT.
        参数:
            row_data: Dict[str, Any], 外部传入的行数据.
        返回:
            Dict[str, Any], 可直接用于 SQL 参数绑定的字典.
        """
        values: Dict[str, Any] = {}
        extras: Dict[str, Any] = {}

        for key, val in row_data.items():
            if key in ("id", "created_at", "updated_at", "extra_json", "base_substance"):
                continue
            if key in _WRITABLE_COLUMNS:
                # 数值列做类型转换
                if key in NUMERIC_COLUMNS and val is not None:
                    try:
                        val = float(val)
                    except (TypeError, ValueError):
                        val = None
                values[key] = val
            else:
                # 非核心列放入 extra_json
                if val is not None and str(val).strip() != "":
                    extras[key] = val

        if len(extras) > 0:
            values["extra_json"] = json.dumps(extras, ensure_ascii=False)
        return values

    # ===================== CRUD =====================

    def insert_row(self, row_data: Dict[str, Any]) -> int:
        """
        功能:
            向 chemicals 表插入一行数据.
        参数:
            row_data: Dict[str, Any], 行数据.
        返回:
            int, 新行 id.
        """
        values = self._prepare_insert_values(row_data)
        columns = list(values.keys())
        placeholders = ", ".join(["?"] * len(columns))
        column_names = ", ".join(columns)
        sql = f"INSERT INTO chemicals ({column_names}) VALUES ({placeholders})"
        cursor = self._conn.execute(sql, [values[col] for col in columns])
        self._conn.commit()
        return cursor.lastrowid

    def get_by_id(self, row_id: int) -> Optional[Dict[str, Any]]:
        """
        功能:
            按主键查询单行.
        参数:
            row_id: int, 行 id.
        返回:
            Optional[Dict[str, Any]], 行数据, 不存在返回 None.
        """
        cursor = self._conn.execute("SELECT * FROM chemicals WHERE id = ?", (row_id,))
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def update_row(self, row_id: int, updates: Dict[str, Any]) -> bool:
        """
        功能:
            更新指定行的字段.
        参数:
            row_id: int, 目标行 id.
            updates: Dict[str, Any], 要更新的字段.
        返回:
            bool, True 表示更新成功.
        """
        values = self._prepare_insert_values(updates)
        values["updated_at"] = "datetime('now')"
        set_parts = []
        params = []
        for col, val in values.items():
            if col == "updated_at":
                set_parts.append("updated_at = datetime('now')")
            else:
                set_parts.append(f"{col} = ?")
                params.append(val)
        params.append(row_id)
        sql = f"UPDATE chemicals SET {', '.join(set_parts)} WHERE id = ?"
        cursor = self._conn.execute(sql, params)
        self._conn.commit()
        return cursor.rowcount > 0

    def delete_row(self, row_id: int) -> bool:
        """
        功能:
            删除指定行.
        参数:
            row_id: int, 行 id.
        返回:
            bool, True 表示删除成功.
        """
        cursor = self._conn.execute("DELETE FROM chemicals WHERE id = ?", (row_id,))
        self._conn.commit()
        return cursor.rowcount > 0

    # ===================== 搜索 =====================

    def search_by_cas(self, cas: str) -> List[Dict[str, Any]]:
        """
        功能:
            按 CAS 号精确匹配.
        参数:
            cas: str, CAS 号.
        返回:
            List[Dict[str, Any]], 匹配行列表.
        """
        cursor = self._conn.execute(
            "SELECT * FROM chemicals WHERE cas_number = ?",
            (cas,),
        )
        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def search_by_name(self, name: str, is_cjk: bool) -> List[Dict[str, Any]]:
        """
        功能:
            按名称模糊匹配.
            中文名匹配 substance 列, 英文名匹配 substance_english_name 列(忽略大小写).
        参数:
            name: str, 查询名称.
            is_cjk: bool, True 表示中文名称.
        返回:
            List[Dict[str, Any]], 匹配行列表.
        """
        pattern = f"%{name}%"
        if is_cjk is True:
            cursor = self._conn.execute(
                "SELECT * FROM chemicals WHERE substance LIKE ?",
                (pattern,),
            )
        else:
            cursor = self._conn.execute(
                "SELECT * FROM chemicals WHERE LOWER(substance_english_name) LIKE LOWER(?)",
                (pattern,),
            )
        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def find_existing(
        self,
        *,
        cas_number: str = "",
        substance_english_name: str = "",
        substance: str = "",
    ) -> Optional[Dict[str, Any]]:
        """
        功能:
            按 CAS, 英文名, 中文名顺序查找已有条目, 优先返回 neat 行.
        参数:
            cas_number: str, 候选 CAS 号.
            substance_english_name: str, 候选英文名.
            substance: str, 候选中文名.
        返回:
            Optional[Dict[str, Any]], 匹配行数据, 不存在返回 None.
        """
        # 按 CAS -> 英文名 -> 中文名顺序尝试, 每次优先取 neat 行
        conditions = []
        if cas_number.strip() != "":
            conditions.append(("cas_number = ?", cas_number.strip()))
        if substance_english_name.strip() != "":
            conditions.append(("substance_english_name = ?", substance_english_name.strip()))
        if substance.strip() != "":
            conditions.append(("substance = ?", substance.strip()))

        for where_clause, param in conditions:
            cursor = self._conn.execute(
                f"SELECT * FROM chemicals WHERE {where_clause} "
                "ORDER BY (CASE WHEN physical_form = 'neat' THEN 0 ELSE 1 END) ASC, id ASC LIMIT 1",
                (param,),
            )
            row = cursor.fetchone()
            if row is not None:
                return self._row_to_dict(row)

        return None

    def find_duplicate(self, row_data: Dict[str, Any]) -> Optional[Tuple[str, str, int]]:
        """
        功能:
            按约定优先级检测重复化合物.
            neat 条目按 CAS > 英文名 > 中文名检查.
            solution / beads 仅按中文名(含展示名)检查.
        参数:
            row_data: Dict[str, Any], 准备写入的行数据.
        返回:
            Optional[Tuple[str, str, int]], 命中时返回 (标签, 目标值, 行id), 否则 None.
        """
        from .append_utils import build_duplicate_check_specs

        duplicate_specs = build_duplicate_check_specs(row_data)
        for candidate_columns, target_value, label_text in duplicate_specs:
            # 选择第一个在表中存在的候选列
            for col_name in candidate_columns:
                cursor = self._conn.execute(
                    f"SELECT id, substance FROM chemicals WHERE {col_name} = ? LIMIT 1",
                    (target_value,),
                )
                match = cursor.fetchone()
                if match is not None:
                    return label_text, target_value, match["id"]
        return None

    # ===================== 批量操作 =====================

    def iter_all(self) -> List[Dict[str, Any]]:
        """
        功能:
            返回全部化学品记录.
        返回:
            List[Dict[str, Any]], 所有行数据列表.
        """
        cursor = self._conn.execute("SELECT * FROM chemicals ORDER BY id ASC")
        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def count(self) -> int:
        """
        功能:
            返回表中总行数.
        返回:
            int, 行数.
        """
        cursor = self._conn.execute("SELECT COUNT(*) FROM chemicals")
        return cursor.fetchone()[0]

    def deduplicate(self) -> int:
        """
        功能:
            按 CAS 号去重, 保留每组中 id 最小的行.
            仅对 CAS 非空的行去重.
        返回:
            int, 删除的重复行数.
        """
        cursor = self._conn.execute(
            """
            DELETE FROM chemicals
            WHERE id NOT IN (
                SELECT MIN(id) FROM chemicals
                WHERE cas_number IS NOT NULL AND cas_number != ''
                GROUP BY cas_number
            )
            AND cas_number IS NOT NULL AND cas_number != ''
            """
        )
        deleted = cursor.rowcount
        self._conn.commit()
        if deleted > 0:
            logger.info("化学品库去重完成, 删除 %d 条重复记录", deleted)
        return deleted

    def check_integrity(self) -> Dict[str, Any]:
        """
        功能:
            检查化学品库完整性, 返回统计与问题列表.
        返回:
            Dict[str, Any], 包含 total, no_cas, no_name, duplicated_cas 统计.
        """
        total = self.count()

        cursor = self._conn.execute(
            "SELECT COUNT(*) FROM chemicals WHERE (cas_number IS NULL OR cas_number = '')"
        )
        no_cas = cursor.fetchone()[0]

        cursor = self._conn.execute(
            "SELECT COUNT(*) FROM chemicals WHERE "
            "(substance IS NULL OR substance = '') AND "
            "(substance_english_name IS NULL OR substance_english_name = '')"
        )
        no_name = cursor.fetchone()[0]

        cursor = self._conn.execute(
            "SELECT cas_number, COUNT(*) as cnt FROM chemicals "
            "WHERE cas_number IS NOT NULL AND cas_number != '' "
            "GROUP BY cas_number HAVING cnt > 1"
        )
        duplicated_cas = [dict(row) for row in cursor.fetchall()]

        return {
            "total": total,
            "no_cas": no_cas,
            "no_name": no_name,
            "duplicated_cas": duplicated_cas,
        }

    # ===================== 带重复检查的插入 =====================

    def insert_with_duplicate_check(
        self,
        row_data: Dict[str, Any],
    ) -> Tuple[Optional[int], str]:
        """
        功能:
            插入一行化学品数据, 先检查重复.
        参数:
            row_data: Dict[str, Any], 行数据.
        返回:
            Tuple[Optional[int], str], 成功返回 (新行id, ""),
            重复返回 (None, 已有行的 substance 名称).
        """
        dup = self.find_duplicate(row_data)
        if dup is not None:
            label_text, target_value, existing_id = dup
            existing = self.get_by_id(existing_id)
            existing_substance = str(
                (existing or {}).get("substance")
                or (existing or {}).get("substance_english_name")
                or ""
            ).strip()
            logger.warning(
                "化合物已存在, %s=%s, id=%d, 跳过添加",
                label_text, target_value, existing_id,
            )
            return None, existing_substance

        new_id = self.insert_row(row_data)
        return new_id, ""
