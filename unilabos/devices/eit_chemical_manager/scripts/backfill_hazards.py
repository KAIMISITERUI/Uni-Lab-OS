# -*- coding: utf-8 -*-
"""
功能:
    批量刷新化学品库中所有化学品的 PubChem GHS 危害信息.
    脚本按行读取 chemicals 表, 使用 ChemicalManager 的危害查询逻辑选择标识符,
    并将查询结果写回 extra_json.
参数:
    --db-path: str, 可选, SQLite 数据库路径. 默认读取 Settings.from_env().db_path.
    --sleep: float, 可选, 每条 PubChem 查询后的等待秒数. 默认 0.25.
    --limit: int, 可选, 仅处理前 N 条记录.
    --only-missing: bool, 可选, 只刷新缺少 hazard_updated_at 的记录.
    --workers: int, 可选, 并发查询线程数. 写库仍然在主线程顺序执行.
返回:
    int, 进程退出码. 正常结束返回 0.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

try:
    from unilabos.devices.eit_chemical_manager.config.setting import (
        Settings,
        configure_logging,
    )
    from unilabos.devices.eit_chemical_manager.driver.pubchem_ghs import (
        lookup_pubchem_ghs,
    )
    from unilabos.devices.eit_chemical_manager.manager.chemical_manager import (
        ChemicalManager,
    )
except ImportError:
    from eit_chemical_manager.config.setting import Settings, configure_logging
    from eit_chemical_manager.driver.pubchem_ghs import lookup_pubchem_ghs
    from eit_chemical_manager.manager.chemical_manager import ChemicalManager


logger = logging.getLogger("BackfillHazards")


def _configure_stdio_encoding() -> None:
    """
    功能:
        将标准输出和标准错误配置为 UTF-8, 避免 Windows 控制台编码无法写出化学品名称.
    参数:
        无.
    返回:
        None.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure") is True:
            stream.reconfigure(encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    """
    功能:
        解析命令行参数.
    参数:
        无.
    返回:
        argparse.Namespace, 包含 db_path, sleep, limit, only_missing, workers.
    """
    parser = argparse.ArgumentParser(
        description="批量刷新化学品库 PubChem GHS 危害信息.",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="SQLite 数据库路径, 默认读取 Settings.from_env().db_path.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.25,
        help="每条 PubChem 查询后的等待秒数, 默认 0.25.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="仅处理前 N 条记录, 用于小范围验证.",
    )
    parser.add_argument(
        "--only-missing",
        action="store_true",
        help="只刷新缺少 hazard_updated_at 的记录.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="并发查询线程数, 默认 1. 写库仍然在主线程顺序执行.",
    )
    return parser.parse_args()


def _resolve_db_path(cli_db_path: Optional[str]) -> Path:
    """
    功能:
        解析实际使用的 SQLite 数据库路径.
    参数:
        cli_db_path: Optional[str], 命令行传入的数据库路径.
    返回:
        Path, SQLite 数据库路径.
    """
    if cli_db_path is not None and cli_db_path.strip() != "":
        return Path(cli_db_path)
    return Settings.from_env().db_path


def _fetch_hazard_for_row(
    *,
    row: Dict[str, Any],
    timeout_seconds: float,
    sleep_seconds: float,
) -> Tuple[int, Dict[str, Any], str]:
    """
    功能:
        为单条化学品记录查询 PubChem GHS 危害信息.
    参数:
        row: Dict[str, Any], 化学品行数据.
        timeout_seconds: float, HTTP 请求超时秒数.
        sleep_seconds: float, 查询完成后的等待秒数.
    返回:
        Tuple[int, Dict[str, Any], str], row_id, 危害字段, 错误信息.
    """
    row_id = int(row["id"])
    identifier, query_type = ChemicalManager._select_hazard_identifier(row_data=row)
    if identifier == "":
        return row_id, {}, ""

    try:
        hazard_fields = lookup_pubchem_ghs(
            identifier,
            query_type,
            timeout=timeout_seconds,
        )
    except Exception as exc:
        hazard_fields = {}
        error_text = str(exc)
    else:
        error_text = ""

    if sleep_seconds > 0:
        time.sleep(sleep_seconds)

    return row_id, hazard_fields, error_text


def _write_hazard_result(
    *,
    manager: ChemicalManager,
    row: Dict[str, Any],
    index: int,
    total: int,
    hazard_fields: Dict[str, Any],
    error_text: str,
    updated: int,
    no_data: int,
    failed: int,
) -> Tuple[int, int, int]:
    """
    功能:
        将单条危害查询结果写回数据库并更新统计值.
    参数:
        manager: ChemicalManager, 化学品管理器.
        row: Dict[str, Any], 化学品行数据.
        index: int, 当前处理序号.
        total: int, 总处理数量.
        hazard_fields: Dict[str, Any], PubChem GHS 危害字段.
        error_text: str, 查询错误信息.
        updated: int, 已更新计数.
        no_data: int, 无数据计数.
        failed: int, 失败计数.
    返回:
        Tuple[int, int, int], 更新后的 updated, no_data, failed.
    """
    row_id = int(row["id"])
    name = str(row.get("substance") or row.get("substance_english_name") or "").strip()
    cas = str(row.get("cas_number") or "").strip()
    logger.info("[%d/%d] 写入 id=%d, cas=%s, name=%s", index, total, row_id, cas, name)

    if error_text != "":
        failed = failed + 1
        logger.warning("刷新失败: id=%d, err=%s", row_id, error_text)
    elif len(hazard_fields) > 0:
        manager.db.update_row(row_id, hazard_fields)
        updated = updated + 1
        logger.info(
            "已写入危害信息: id=%d, source_cid=%s",
            row_id,
            hazard_fields.get("hazard_source_cid"),
        )
    else:
        no_data = no_data + 1
        logger.info("未检索到危害信息: id=%d", row_id)

    logger.info(
        "当前进度: total=%d, updated=%d, no_data=%d, failed=%d",
        index,
        updated,
        no_data,
        failed,
    )
    return updated, no_data, failed


def backfill_hazards(
    db_path: Path,
    sleep_seconds: float,
    limit: Optional[int],
    only_missing: bool,
    workers: int,
) -> int:
    """
    功能:
        遍历化学品库并刷新每条记录的 PubChem GHS 危害信息.
    参数:
        db_path: Path, SQLite 数据库路径.
        sleep_seconds: float, 每条查询后的等待秒数.
        limit: Optional[int], 本次处理的最大条数. None 表示不限制.
        only_missing: bool, True 表示跳过已有 hazard_updated_at 的记录.
        workers: int, 并发查询线程数. 写库仍然在主线程顺序执行.
    返回:
        int, 进程退出码. 正常结束返回 0, 数据库不存在返回 2.
    """
    if db_path.exists() is False:
        logger.error("数据库文件不存在: %s", db_path)
        return 2

    settings = Settings.from_env()
    settings.db_path = db_path
    manager = ChemicalManager(settings=settings)
    rows = manager.db.iter_all()

    if only_missing is True:
        rows = [row for row in rows if str(row.get("hazard_updated_at") or "").strip() == ""]

    if limit is not None and limit > 0:
        rows = rows[: int(limit)]

    total = len(rows)
    normalized_workers = max(1, int(workers))
    logger.info(
        "开始批量刷新危害信息: db=%s, total=%d, workers=%d",
        db_path,
        total,
        normalized_workers,
    )
    if total == 0:
        logger.info("没有需要刷新的记录.")
        manager.db.close()
        return 0

    updated = 0
    no_data = 0
    failed = 0
    started_at = time.time()
    timeout_seconds = float(settings.request_timeout_s)

    try:
        if normalized_workers == 1:
            for index, row in enumerate(rows, start=1):
                row_id, hazard_fields, error_text = _fetch_hazard_for_row(
                    row=row,
                    timeout_seconds=timeout_seconds,
                    sleep_seconds=sleep_seconds,
                )
                updated, no_data, failed = _write_hazard_result(
                    manager=manager,
                    row=row,
                    index=index,
                    total=total,
                    hazard_fields=hazard_fields,
                    error_text=error_text,
                    updated=updated,
                    no_data=no_data,
                    failed=failed,
                )
        else:
            with ThreadPoolExecutor(max_workers=normalized_workers) as executor:
                future_to_row = {
                    executor.submit(
                        _fetch_hazard_for_row,
                        row=row,
                        timeout_seconds=timeout_seconds,
                        sleep_seconds=sleep_seconds,
                    ): row
                    for row in rows
                }
                for index, future in enumerate(as_completed(future_to_row), start=1):
                    row = future_to_row[future]
                    try:
                        row_id, hazard_fields, error_text = future.result()
                    except Exception as exc:
                        row_id = int(row["id"])
                        hazard_fields = {}
                        error_text = str(exc)

                    updated, no_data, failed = _write_hazard_result(
                        manager=manager,
                        row=row,
                        index=index,
                        total=total,
                        hazard_fields=hazard_fields,
                        error_text=error_text,
                        updated=updated,
                        no_data=no_data,
                        failed=failed,
                    )

        elapsed = time.time() - started_at
        logger.info(
            "批量刷新完成: total=%d, updated=%d, no_data=%d, failed=%d, elapsed_seconds=%.2f",
            total,
            updated,
            no_data,
            failed,
            elapsed,
        )
        return 0
    finally:
        manager.db.close()


def main() -> int:
    """
    功能:
        脚本入口, 初始化日志并执行批量刷新.
    参数:
        无.
    返回:
        int, 进程退出码.
    """
    _configure_stdio_encoding()
    args = _parse_args()
    configure_logging(level="INFO")
    db_path = _resolve_db_path(args.db_path)
    return backfill_hazards(
        db_path=db_path,
        sleep_seconds=float(args.sleep),
        limit=args.limit,
        only_missing=bool(args.only_missing),
        workers=int(args.workers),
    )


if __name__ == "__main__":
    sys.exit(main())
