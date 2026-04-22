# -*- coding: utf-8 -*-
"""
功能:
    化学品库 SQLite 数据库操作封装.
    提供建表, CRUD, 搜索, 完整性校验等功能.
"""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config.constants import CORE_COLUMNS, NUMERIC_COLUMNS
from ..driver.exceptions import ValidationError

logger = logging.getLogger("ChemicalDB")

# 数据库 schema 版本, 与 PRAGMA user_version 对应
_SCHEMA_VERSION = 1

# 建表 SQL
# substance 列加 UNIQUE COLLATE NOCASE 约束, 保证中文名全库唯一且大小写不敏感
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS chemicals (
    id                         INTEGER PRIMARY KEY AUTOINCREMENT,
    cas_number                 TEXT,
    chemical_id                TEXT,
    substance                  TEXT UNIQUE COLLATE NOCASE,
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
            确保数据库表与索引已创建, 并按需执行 schema 迁移.
        """
        # 先迁移旧库, 再执行 CREATE IF NOT EXISTS, 保证新库直接带约束且旧库会被重建
        self._migrate_unique_substance_v1()
        self._conn.execute(_CREATE_TABLE_SQL)
        for index_sql in _CREATE_INDEXES_SQL:
            self._conn.execute(index_sql)
        self._conn.commit()

    def _migrate_unique_substance_v1(self) -> None:
        """
        功能:
            把 chemicals 表的 substance 列升级为 UNIQUE COLLATE NOCASE 约束.
            若探测到已存在的重名记录, 直接抛 RuntimeError 要求人工清理.
            不提供自动合并或静默丢弃, 以避免业务数据丢失.
        返回:
            None.
        异常:
            RuntimeError: 旧库中存在 substance 重名, 需人工处理后再启动.
        """
        # 读当前 schema 版本, 已迁移则跳过
        cursor = self._conn.execute("PRAGMA user_version;")
        current_version = cursor.fetchone()[0]
        if int(current_version) >= _SCHEMA_VERSION:
            return

        # 表不存在表示首次初始化, 无需迁移, 直接写版本号
        cursor = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='chemicals';"
        )
        if cursor.fetchone() is None:
            self._conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION};")
            self._conn.commit()
            return

        # 若 substance 列已带 UNIQUE 约束, 仅刷新版本号
        if self._substance_column_is_unique() is True:
            self._conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION};")
            self._conn.commit()
            return

        # 探测重名, 命中即中断迁移, 等待人工清理
        cursor = self._conn.execute(
            """
            SELECT substance, COUNT(*) AS cnt FROM chemicals
            WHERE substance IS NOT NULL AND substance != ''
            GROUP BY LOWER(substance) HAVING cnt > 1
            """
        )
        duplicates = cursor.fetchall()
        if len(duplicates) > 0:
            duplicate_list = [
                f"{row['substance']}({row['cnt']} 条)" for row in duplicates
            ]
            logger.error(
                "化学品库存在 substance 重名, 需人工清理后再启动, 重名列表: %s",
                duplicate_list,
            )
            raise RuntimeError(
                "化学品库 substance 列存在重名, 迁移已中止. "
                f"请先在 Web UI 或 CLI 中清理以下条目: {duplicate_list}"
            )

        # 重建表结构以添加 UNIQUE 约束
        logger.info("开始执行化学品库 schema 迁移: 为 substance 列添加 UNIQUE 约束")
        try:
            self._conn.execute("BEGIN")
            self._conn.execute("""
                CREATE TABLE chemicals_new (
                    id                         INTEGER PRIMARY KEY AUTOINCREMENT,
                    cas_number                 TEXT,
                    chemical_id                TEXT,
                    substance                  TEXT UNIQUE COLLATE NOCASE,
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
            """)
            # 明确列出字段, 避免 SELECT * 因未来列序变化出错
            self._conn.execute("""
                INSERT INTO chemicals_new (
                    id, cas_number, chemical_id, substance, substance_english_name,
                    other_name, brand, package_size, storage_location,
                    molecular_weight, density, physical_state, physical_form,
                    active_content, smiles, extra_json, chemicalbook_record_path,
                    created_at, updated_at
                )
                SELECT
                    id, cas_number, chemical_id, substance, substance_english_name,
                    other_name, brand, package_size, storage_location,
                    molecular_weight, density, physical_state, physical_form,
                    active_content, smiles, extra_json, chemicalbook_record_path,
                    created_at, updated_at
                FROM chemicals
            """)
            self._conn.execute("DROP TABLE chemicals;")
            self._conn.execute("ALTER TABLE chemicals_new RENAME TO chemicals;")
            for index_sql in _CREATE_INDEXES_SQL:
                self._conn.execute(index_sql)
            self._conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION};")
            self._conn.commit()
        except Exception as exc:
            self._conn.rollback()
            logger.exception("化学品库 schema 迁移失败, 已回滚")
            raise RuntimeError(f"化学品库 schema 迁移失败: {exc}") from exc

        logger.info("化学品库 schema 迁移完成, substance 列已带 UNIQUE 约束")

    def _substance_column_is_unique(self) -> bool:
        """
        功能:
            判断 chemicals 表的 substance 列是否已经存在 UNIQUE 约束.
        返回:
            bool, True 表示已带 UNIQUE 约束.
        """
        cursor = self._conn.execute("PRAGMA index_list('chemicals');")
        for index_row in cursor.fetchall():
            # index_list 返回 seq, name, unique, origin, partial
            if int(index_row["unique"]) != 1:
                continue
            col_cursor = self._conn.execute(f"PRAGMA index_info('{index_row['name']}');")
            col_names = [c["name"] for c in col_cursor.fetchall()]
            if col_names == ["substance"]:
                return True
        return False

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
        异常:
            ValidationError: 违反唯一性约束, 例如 substance 重名.
        """
        values = self._prepare_insert_values(row_data)
        columns = list(values.keys())
        placeholders = ", ".join(["?"] * len(columns))
        column_names = ", ".join(columns)
        sql = f"INSERT INTO chemicals ({column_names}) VALUES ({placeholders})"
        try:
            cursor = self._conn.execute(sql, [values[col] for col in columns])
        except sqlite3.IntegrityError as exc:
            # 唯一性约束冲突, 抛 ValidationError 让上层按业务错误处理
            conflict_substance = str(values.get("substance") or "").strip()
            raise ValidationError(
                f"化学品写入失败, substance 重名或触发唯一约束: {conflict_substance}"
            ) from exc
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
        异常:
            ValidationError: 触发唯一性约束, 例如改名为已有 substance.
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
        try:
            cursor = self._conn.execute(sql, params)
        except sqlite3.IntegrityError as exc:
            conflict_substance = str(values.get("substance") or "").strip()
            raise ValidationError(
                f"化学品更新失败, substance 重名或触发唯一约束: {conflict_substance}"
            ) from exc
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

    # ===================== 合成工站专用精确查询与按名更新 =====================

    def find_by_substance_exact(self, substance: str) -> Optional[Dict[str, Any]]:
        """
        功能:
            按 substance 中文名精确匹配(依赖 COLLATE NOCASE 大小写不敏感).
            依赖表级 UNIQUE 约束保证最多命中一条.
        参数:
            substance: str, 中文名.
        返回:
            Optional[Dict[str, Any]], 命中时返回行数据, 否则 None.
        """
        normalized = str(substance or "").strip()
        if normalized == "":
            return None
        cursor = self._conn.execute(
            "SELECT * FROM chemicals WHERE substance = ? LIMIT 1",
            (normalized,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def find_many_by_substances(
        self,
        substances: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        """
        功能:
            按 substance 列表一次性查询, 返回 {substance_原样: row_data}.
            内部对输入去重(大小写不敏感). 未命中的名称不出现在返回值中, 由上层判断.
        参数:
            substances: List[str], 中文名列表.
        返回:
            Dict[str, Dict[str, Any]], 键保留调用方传入的原始字符串.
        """
        if not substances:
            return {}

        # 去重时按小写折叠, 保留首次出现的原样字符串
        seen_lower: Dict[str, str] = {}
        for name in substances:
            stripped = str(name or "").strip()
            if stripped == "":
                continue
            key_lower = stripped.lower()
            if key_lower not in seen_lower:
                seen_lower[key_lower] = stripped

        if not seen_lower:
            return {}

        # 构造 IN 子句, substance 列已带 COLLATE NOCASE, 比较自动忽略大小写
        placeholders = ", ".join(["?"] * len(seen_lower))
        sql = f"SELECT * FROM chemicals WHERE substance IN ({placeholders})"
        cursor = self._conn.execute(sql, list(seen_lower.values()))
        rows = cursor.fetchall()

        # 用查询结果的小写名映射回调用方传入的原样字符串
        result: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            row_substance = str(row["substance"] or "").strip()
            original = seen_lower.get(row_substance.lower())
            if original is None:
                continue
            result[original] = self._row_to_dict(row)
        return result

    def update_chemical_ids_batch(self, mapping: Dict[str, str]) -> int:
        """
        功能:
            单事务批量更新 chemical_id. 调用前上层需已保证所有 substance 存在.
        参数:
            mapping: Dict[str, str], {substance: chemical_id}, 值必须为非空字符串.
        返回:
            int, 实际更新行数.
        """
        if not mapping:
            return 0

        updated_count = 0
        try:
            self._conn.execute("BEGIN")
            for substance_name, chemical_id_value in mapping.items():
                cursor = self._conn.execute(
                    "UPDATE chemicals SET chemical_id = ?, updated_at = datetime('now') "
                    "WHERE substance = ?",
                    (chemical_id_value, substance_name),
                )
                if cursor.rowcount > 0:
                    updated_count += 1
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            logger.exception("批量回写 chemical_id 失败, 已回滚")
            raise

        return updated_count

    def update_by_substance(self, substance: str, updates: Dict[str, Any]) -> bool:
        """
        功能:
            按 substance 中文名定位并更新指定字段, 用于 Web UI 编辑与
            合成工站 chemical_id 回写.
        参数:
            substance: str, 中文名.
            updates: Dict[str, Any], 要更新的字段.
        返回:
            bool, True 表示命中并更新成功.
        """
        normalized = str(substance or "").strip()
        if normalized == "":
            return False
        values = self._prepare_insert_values(updates)
        if not values:
            return False

        set_parts = [f"{col} = ?" for col in values.keys()]
        set_parts.append("updated_at = datetime('now')")
        sql = (
            f"UPDATE chemicals SET {', '.join(set_parts)} "
            "WHERE substance = ?"
        )
        params = list(values.values()) + [normalized]
        cursor = self._conn.execute(sql, params)
        self._conn.commit()
        return cursor.rowcount > 0

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

    def check_integrity(self) -> Dict[str, Any]:
        """
        功能:
            检查化学品库完整性, 返回 7 类问题清单.
            每条问题项均包含完整行数据, 便于前端跳转编辑.
        返回:
            Dict[str, Any], 含以下 7 个键:
                duplicate_chinese_names: 中文名 (substance) 列内重复, 每组含 name + rows
                duplicate_english_names: 英文名 (substance_english_name) 列内重复, 同结构
                missing_physical_state: physical_state 缺失行
                missing_physical_form: physical_form 缺失行
                neat_missing_molecular_weight: physical_form='neat' 但缺 molecular_weight
                neat_liquid_missing_density: physical_form='neat' 且 physical_state='liquid' 但缺 density
                beads_solution_missing_content: physical_form ∈ {beads, solution} 但缺 active_content
        """
        # 中文名列内重复 (DB 上 substance 已有 UNIQUE COLLATE NOCASE, 通常为空; 用于发现历史脏数据)
        duplicate_chinese_names = self._collect_duplicate_name_groups("substance")
        # 英文名列内重复 (无 UNIQUE 约束, 是该检查的主要落点)
        duplicate_english_names = self._collect_duplicate_name_groups(
            "substance_english_name"
        )

        # 物态缺失
        missing_physical_state = self._collect_rows(
            "physical_state IS NULL OR physical_state = ''"
        )
        # 形态缺失
        missing_physical_form = self._collect_rows(
            "physical_form IS NULL OR physical_form = ''"
        )

        # neat 缺 molecular_weight (要求 physical_form 已填)
        neat_missing_mw = self._collect_rows(
            "physical_form = 'neat' AND molecular_weight IS NULL"
        )
        # neat 且 liquid 缺 density (要求 physical_form/state 已填)
        neat_liquid_missing_density = self._collect_rows(
            "physical_form = 'neat' AND physical_state = 'liquid' AND density IS NULL"
        )
        # beads/solution 缺 active_content
        beads_solution_missing_content = self._collect_rows(
            "physical_form IN ('beads', 'solution') "
            "AND (active_content IS NULL OR active_content = '')"
        )
        total_cursor = self._conn.execute("SELECT COUNT(*) AS total FROM chemicals")
        total_row = total_cursor.fetchone()
        total = 0
        if total_row is not None:
            total = int(total_row["total"])
        no_cas_cursor = self._conn.execute(
            "SELECT COUNT(*) AS no_cas FROM chemicals WHERE cas_number IS NULL OR cas_number = ''"
        )
        no_cas_row = no_cas_cursor.fetchone()
        no_cas = 0
        if no_cas_row is not None:
            no_cas = int(no_cas_row["no_cas"])
        return {
            "total": total,
            "no_cas": no_cas,
            "duplicate_chinese_names": duplicate_chinese_names,
            "duplicate_english_names": duplicate_english_names,
            "missing_physical_state": missing_physical_state,
            "missing_physical_form": missing_physical_form,
            "neat_missing_molecular_weight": neat_missing_mw,
            "neat_liquid_missing_density": neat_liquid_missing_density,
            "beads_solution_missing_content": beads_solution_missing_content,
        }

    def _collect_rows(self, where_clause: str) -> List[Dict[str, Any]]:
        """
        功能:
            按 where 子句拉取全部命中行, 返回 dict 列表.
        参数:
            where_clause: str, SQL WHERE 子句 (不含 WHERE 关键字).
        返回:
            List[Dict[str, Any]], 命中的行数据列表, 按 id 升序.
        """
        cursor = self._conn.execute(
            f"SELECT * FROM chemicals WHERE {where_clause} ORDER BY id ASC"
        )
        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def _collect_duplicate_name_groups(self, column: str) -> List[Dict[str, Any]]:
        """
        功能:
            在指定名称列内查找重复值, 返回每个重复值对应的全部行.
        参数:
            column: str, 'substance' 或 'substance_english_name'.
        返回:
            List[Dict[str, Any]], 每项为 {"name": str, "rows": List[Dict]}.
        """
        # 先找出现次数 >1 的名称
        cursor = self._conn.execute(
            f"SELECT {column} AS name FROM chemicals "
            f"WHERE {column} IS NOT NULL AND {column} != '' "
            f"GROUP BY {column} HAVING COUNT(*) > 1 ORDER BY {column}"
        )
        duplicate_names = [row["name"] for row in cursor.fetchall()]

        # 再为每个重复名称拉取全部行
        groups: List[Dict[str, Any]] = []
        for name in duplicate_names:
            cursor = self._conn.execute(
                f"SELECT * FROM chemicals WHERE {column} = ? ORDER BY id ASC",
                (name,),
            )
            groups.append(
                {
                    "name": name,
                    "rows": [self._row_to_dict(row) for row in cursor.fetchall()],
                }
            )
        return groups

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
