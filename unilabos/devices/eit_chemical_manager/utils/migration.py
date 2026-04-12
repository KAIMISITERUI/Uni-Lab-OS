# -*- coding: utf-8 -*-
"""
功能:
    将 chemical_list.xlsx 一次性迁移到 SQLite 数据库.
    支持命令行调用: python -m eit_chemical_manager.utils.migration <excel_path> [--db <db_path>]
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config.constants import CORE_COLUMNS, NUMERIC_COLUMNS
from ..config.setting import Settings, configure_logging
from ..controller.chemical_db import ChemicalDB

logger = logging.getLogger("ChemicalMigration")


def _build_header_map(worksheet: Any) -> Dict[str, int]:
    """
    功能:
        从 Excel 工作表首行构建表头名到列号映射.
    参数:
        worksheet: openpyxl 工作表对象.
    返回:
        Dict[str, int], 表头名 -> 列号.
    """
    header_map: Dict[str, int] = {}
    for col_idx in range(1, worksheet.max_column + 1):
        header_val = worksheet.cell(row=1, column=col_idx).value
        if header_val is None:
            continue
        header_map[str(header_val).strip()] = col_idx
    return header_map


def _extract_row(
    worksheet: Any,
    header_map: Dict[str, int],
    row_index: int,
) -> Dict[str, Any]:
    """
    功能:
        从工作表中提取单行数据为字典.
    参数:
        worksheet: openpyxl 工作表对象.
        header_map: Dict[str, int], 表头映射.
        row_index: int, 行号.
    返回:
        Dict[str, Any], 字段字典.
    """
    row_data: Dict[str, Any] = {}
    for column_name, column_index in header_map.items():
        val = worksheet.cell(row=row_index, column=column_index).value
        if val is not None:
            row_data[column_name] = val
    return row_data


def _normalize_row(row_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    功能:
        标准化行数据: 统一中文名字段, 转换数值类型.
    参数:
        row_data: Dict[str, Any], 原始行数据.
    返回:
        Dict[str, Any], 标准化后的行数据.
    """
    result = dict(row_data)

    # substance / substance_chinese_name 统一
    substance = str(result.get("substance") or "").strip()
    chinese_name = str(result.get("substance_chinese_name") or "").strip()
    if substance == "" and chinese_name != "":
        result["substance"] = chinese_name
    if "substance_chinese_name" in result:
        del result["substance_chinese_name"]

    # density (g/mL) 列名适配
    if "density (g/mL)" in result:
        result["density"] = result.pop("density (g/mL)")

    # active_content(mol/L or wt%) 列名适配
    if "active_content(mol/L or wt%)" in result:
        result["active_content"] = result.pop("active_content(mol/L or wt%)")

    # 数值列转换
    for col in NUMERIC_COLUMNS:
        if col in result and result[col] is not None:
            try:
                result[col] = float(result[col])
            except (TypeError, ValueError):
                result[col] = None

    # 字符串列去空格
    for key, val in result.items():
        if isinstance(val, str):
            result[key] = val.strip()

    return result


def migrate_excel_to_sqlite(
    excel_path: str,
    db_path: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, int]:
    """
    功能:
        将 chemical_list.xlsx 迁移到 SQLite 数据库.
        成功后将 xlsx 重命名为 .migrated.<timestamp> 后缀.
    参数:
        excel_path: str, Excel 文件路径.
        db_path: Optional[str], SQLite 文件路径, None 时使用默认路径.
        dry_run: bool, True 时仅校验不写入.
    返回:
        Dict[str, int], 包含 migrated, skipped, failed 统计.
    """
    import openpyxl

    excel = Path(excel_path)
    if excel.exists() is False:
        raise FileNotFoundError(f"Excel 文件不存在: {excel}")

    settings = Settings.from_env()
    target_db_path = Path(db_path) if db_path is not None else settings.db_path

    logger.info("开始迁移: %s -> %s (dry_run=%s)", excel, target_db_path, dry_run)

    wb = openpyxl.load_workbook(str(excel), data_only=True)
    ws = wb.active
    header_map = _build_header_map(ws)

    if len(header_map) == 0:
        wb.close()
        raise ValueError("Excel 首行无表头, 无法迁移")

    stats = {"migrated": 0, "skipped": 0, "failed": 0}

    if dry_run is True:
        for row_idx in range(2, ws.max_row + 1):
            raw = _extract_row(ws, header_map, row_idx)
            if len(raw) == 0:
                continue
            stats["migrated"] += 1
        wb.close()
        logger.info("dry_run 完成, 预计迁移 %d 行", stats["migrated"])
        return stats

    db = ChemicalDB(target_db_path)
    try:
        for row_idx in range(2, ws.max_row + 1):
            raw = _extract_row(ws, header_map, row_idx)
            if len(raw) == 0:
                continue

            normalized = _normalize_row(raw)

            # 检查是否有核心标识字段
            has_id = any([
                str(normalized.get("cas_number") or "").strip() != "",
                str(normalized.get("substance_english_name") or "").strip() != "",
                str(normalized.get("substance") or "").strip() != "",
            ])
            if has_id is False:
                logger.warning("跳过无标识字段的行: row=%d", row_idx)
                stats["skipped"] += 1
                continue

            # 重复检查
            dup = db.find_duplicate(normalized)
            if dup is not None:
                label, val, existing_id = dup
                logger.debug("跳过重复行: row=%d, %s=%s, existing_id=%d", row_idx, label, val, existing_id)
                stats["skipped"] += 1
                continue

            try:
                db.insert_row(normalized)
                stats["migrated"] += 1
            except Exception as exc:
                logger.error("插入失败: row=%d, err=%s", row_idx, exc)
                stats["failed"] += 1
    finally:
        db.close()
        wb.close()

    logger.info(
        "迁移完成: migrated=%d, skipped=%d, failed=%d",
        stats["migrated"], stats["skipped"], stats["failed"],
    )

    # 重命名源文件
    if stats["failed"] == 0 and stats["migrated"] > 0:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{excel.name}.migrated.{timestamp}"
        backup_path = excel.parent / backup_name
        try:
            excel.rename(backup_path)
            logger.info("源文件已重命名: %s -> %s", excel, backup_path)
        except OSError as exc:
            logger.warning("源文件重命名失败: %s, err=%s", excel, exc)

    return stats


def main(argv: Optional[list] = None) -> int:
    """
    功能:
        命令行入口.
    参数:
        argv: Optional[list], 命令行参数.
    返回:
        int, 进程退出码.
    """
    parser = argparse.ArgumentParser(description="将 chemical_list.xlsx 迁移到 SQLite")
    parser.add_argument("excel_path", help="Excel 文件路径")
    parser.add_argument("--db", help="SQLite 数据库路径, 默认使用驱动配置")
    parser.add_argument("--dry-run", action="store_true", help="仅校验不写入")
    parser.add_argument("--log-level", default="INFO", help="日志级别")
    args = parser.parse_args(argv)

    configure_logging(args.log_level)

    try:
        stats = migrate_excel_to_sqlite(
            excel_path=args.excel_path,
            db_path=args.db,
            dry_run=args.dry_run,
        )
        print(f"迁移结果: 成功={stats['migrated']}, 跳过={stats['skipped']}, 失败={stats['failed']}")
        return 0 if stats["failed"] == 0 else 1
    except Exception as exc:
        logger.error("迁移失败: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
