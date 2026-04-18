# -*- coding: utf-8 -*-
"""
功能:
    验证 ChemicalManager 暴露给合成工站的 Python API.
    覆盖精确查询, 批量查询, 英文名解析, storage_location 与 chemical_id
    回写, 以及 substance UNIQUE 约束的 schema 迁移行为.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict

import pytest

from unilabos.devices.eit_chemical_manager.config.setting import Settings
from unilabos.devices.eit_chemical_manager.controller.chemical_db import (
    _CREATE_INDEXES_SQL,
    _SCHEMA_VERSION,
    ChemicalDB,
)
from unilabos.devices.eit_chemical_manager.driver.exceptions import ValidationError
from unilabos.devices.eit_chemical_manager.manager.chemical_manager import (
    ChemicalManager,
)


def _make_manager(tmp_path: Path) -> ChemicalManager:
    """
    功能:
        在临时目录下构造隔离的 ChemicalManager 实例, 绕开全局单例.
    参数:
        tmp_path: Path, pytest 提供的临时目录.
    返回:
        ChemicalManager.
    """
    db_path = tmp_path / "chemical_library.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings(db_path=db_path, data_dir=data_dir)
    return ChemicalManager(settings=settings)


def _insert_sample(
    manager: ChemicalManager,
    substance: str,
    **extra: Any,
) -> int:
    """
    功能:
        通过底层 DB 写入一条最小样本行, 便于测试.
    参数:
        manager: ChemicalManager, 上下文管理器.
        substance: str, 中文名.
        extra: Any, 其他行数据.
    返回:
        int, 新行 id.
    """
    row: Dict[str, Any] = {"substance": substance}
    row.update(extra)
    return manager.db.insert_row(row)


def test_get_by_substance_returns_projected_fields(tmp_path: Path) -> None:
    """功能: 验证按中文名精确查询返回合成工站字段投影."""
    manager = _make_manager(tmp_path)
    _insert_sample(
        manager,
        substance="乙醇",
        substance_english_name="Ethanol",
        cas_number="64-17-5",
        physical_state="liquid",
        storage_location="TB-2-1",
        density=0.789,
    )

    result = manager.get_by_substance("乙醇")
    assert result["substance"] == "乙醇"
    assert result["substance_english_name"] == "Ethanol"
    assert result["physical_state"] == "liquid"
    assert result["storage_location"] == "TB-2-1"
    assert result["density"] == pytest.approx(0.789)
    # 不应泄露非投影字段
    assert "extra_json" not in result
    assert "id" not in result


def test_get_by_substance_missing_raises_key_error(tmp_path: Path) -> None:
    """功能: 查询不存在的中文名必须抛 KeyError, 不允许返回 None."""
    manager = _make_manager(tmp_path)
    with pytest.raises(KeyError):
        manager.get_by_substance("不存在的化合物")


def test_get_many_by_substances_hits_and_missing(tmp_path: Path) -> None:
    """功能: 批量查询命中完整集合返回字典, 缺失任一名称抛 KeyError 并列出."""
    manager = _make_manager(tmp_path)
    _insert_sample(manager, substance="乙醇", physical_state="liquid")
    _insert_sample(manager, substance="苯", physical_state="liquid")

    ok = manager.get_many_by_substances(["乙醇", "苯"])
    assert set(ok.keys()) == {"乙醇", "苯"}
    assert ok["乙醇"]["physical_state"] == "liquid"

    with pytest.raises(KeyError) as err_info:
        manager.get_many_by_substances(["乙醇", "甲苯"])
    assert "甲苯" in str(err_info.value)


def test_exists_true_false(tmp_path: Path) -> None:
    """功能: exists 对已录入/未录入中文名分别返回 True/False."""
    manager = _make_manager(tmp_path)
    _insert_sample(manager, substance="乙醇")

    assert manager.exists("乙醇") is True
    assert manager.exists("丙酮") is False
    assert manager.exists("") is False


def test_resolve_english_to_chinese(tmp_path: Path) -> None:
    """功能: 批量英文名映射中文名, 忽略大小写, 缺失抛 KeyError."""
    manager = _make_manager(tmp_path)
    _insert_sample(manager, substance="乙醇", substance_english_name="Ethanol")
    _insert_sample(manager, substance="苯", substance_english_name="Benzene")

    result = manager.resolve_english_to_chinese(["ethanol", "BENZENE"])
    assert result == {"ethanol": "乙醇", "BENZENE": "苯"}

    with pytest.raises(KeyError):
        manager.resolve_english_to_chinese(["ethanol", "Toluene"])


def test_list_all_for_synthesis_projection(tmp_path: Path) -> None:
    """功能: 全表列表仅返回合成工站所需字段."""
    manager = _make_manager(tmp_path)
    _insert_sample(
        manager,
        substance="乙醇",
        substance_english_name="Ethanol",
        cas_number="64-17-5",
        physical_state="liquid",
        storage_location="TB-2-1",
    )

    rows = manager.list_all_for_synthesis()
    assert len(rows) == 1
    row = rows[0]
    assert set(row.keys()) == set(ChemicalManager._SYNTHESIS_FIELDS)


def test_set_storage_location_updates_db(tmp_path: Path) -> None:
    """功能: set_storage_location 写回后再次查询可读出新值."""
    manager = _make_manager(tmp_path)
    _insert_sample(manager, substance="乙醇", storage_location="TB-2-1")

    manager.set_storage_location("乙醇", "TB-2-5")
    assert manager.get_by_substance("乙醇")["storage_location"] == "TB-2-5"

    with pytest.raises(KeyError):
        manager.set_storage_location("不存在", "TB-2-5")


def test_set_chemical_id_and_batch(tmp_path: Path) -> None:
    """功能: 单条与批量 chemical_id 回写链路正确落库, 缺失抛 KeyError."""
    manager = _make_manager(tmp_path)
    _insert_sample(manager, substance="乙醇")
    _insert_sample(manager, substance="苯")

    manager.set_chemical_id("乙醇", 1001)
    assert manager.get_by_substance("乙醇")["chemical_id"] == "1001"

    updated_count = manager.set_chemical_ids_batch({"乙醇": 2002, "苯": 3003})
    assert updated_count == 2
    assert manager.get_by_substance("乙醇")["chemical_id"] == "2002"
    assert manager.get_by_substance("苯")["chemical_id"] == "3003"

    # 任一缺失即中断, 且原值不被改动(回滚前已通过预扫描拦截, 不进入事务)
    with pytest.raises(KeyError):
        manager.set_chemical_ids_batch({"乙醇": 9999, "未知": 8888})
    assert manager.get_by_substance("乙醇")["chemical_id"] == "2002"


def test_substance_unique_constraint_on_insert(tmp_path: Path) -> None:
    """功能: 新建库默认带 UNIQUE 约束, 重复 substance 插入抛 ValidationError, 且大小写不敏感."""
    manager = _make_manager(tmp_path)
    _insert_sample(manager, substance="乙醇")

    with pytest.raises(ValidationError):
        _insert_sample(manager, substance="乙醇")

    # ASCII 大小写通过 COLLATE NOCASE 被视作重复
    _insert_sample(manager, substance="ethanol")
    with pytest.raises(ValidationError):
        _insert_sample(manager, substance="ETHANOL")


def test_migration_detects_duplicates_in_legacy_db(tmp_path: Path) -> None:
    """功能: 旧库存在 substance 重名时, 迁移必须抛 RuntimeError 且不自动合并."""
    db_path = tmp_path / "legacy.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # 手工构造一个不带 UNIQUE 约束的旧表, 并插入重名行
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE chemicals (
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
    """)
    for sql in _CREATE_INDEXES_SQL:
        conn.execute(sql)
    conn.execute("INSERT INTO chemicals (substance) VALUES ('乙醇')")
    conn.execute("INSERT INTO chemicals (substance) VALUES ('乙醇')")
    conn.execute("PRAGMA user_version = 0;")
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError) as err_info:
        ChemicalDB(db_path)
    assert "乙醇" in str(err_info.value)


def test_migration_upgrades_legacy_db(tmp_path: Path) -> None:
    """功能: 旧库无重名时, 迁移应重建表并打上 UNIQUE 约束, user_version 升到 v1."""
    db_path = tmp_path / "legacy_ok.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE chemicals (
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
    """)
    conn.execute("INSERT INTO chemicals (substance) VALUES ('乙醇')")
    conn.execute("INSERT INTO chemicals (substance) VALUES ('苯')")
    conn.execute("PRAGMA user_version = 0;")
    conn.commit()
    conn.close()

    db = ChemicalDB(db_path)
    try:
        # 迁移后 UNIQUE 约束生效
        with pytest.raises(ValidationError):
            db.insert_row({"substance": "乙醇"})

        version = db._conn.execute("PRAGMA user_version;").fetchone()[0]
        assert int(version) == _SCHEMA_VERSION
        assert db._substance_column_is_unique() is True
    finally:
        db.close()
