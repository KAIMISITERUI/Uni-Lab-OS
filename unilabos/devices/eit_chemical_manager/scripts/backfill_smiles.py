# -*- coding: utf-8 -*-
"""
功能:
    批量通过 CAS 号补齐化学品库中缺失的 SMILES 结构式.
    遍历 chemicals 表中 smiles 为空且 cas_number 非空的记录, 调用
    driver.chemical_lookup.lookup_chemical 查询 PubChem, 将返回的 smiles
    UPDATE 回对应行. 查询不到 SMILES 的记录本次不处理.

    脚本是幂等的: WHERE 过滤会自动跳过已写入 smiles 的记录, 中断后重跑即续处理.
参数:
    --db-path: str, 可选, SQLite 数据库路径. 默认取 config.setting.Settings.from_env().db_path.
    --sleep: float, 可选, 每次 PubChem 查询之间的延时(秒), 默认 0.25.
    --limit: int, 可选, 限制本次处理的最大条数, 用于调试小样本.
返回:
    进程退出码. 正常结束返回 0.
"""

import argparse
import logging
import sqlite3
import sys
import time
from pathlib import Path
from typing import Optional

from unilabos.devices.eit_chemical_manager.config.setting import (
    Settings,
    configure_logging,
)
from unilabos.devices.eit_chemical_manager.driver.chemical_lookup import (
    lookup_chemical,
)

logger = logging.getLogger("BackfillSmiles")


# 选集 SQL: 仅挑 smiles 为空且 cas_number 非空的记录
_SELECT_SQL = """
SELECT id, cas_number, substance
FROM chemicals
WHERE (smiles IS NULL OR TRIM(smiles) = '')
  AND cas_number IS NOT NULL
  AND TRIM(cas_number) != ''
ORDER BY id
"""

# 更新 SQL: 写入 smiles 并刷新 updated_at
_UPDATE_SQL = """
UPDATE chemicals
SET smiles = ?, updated_at = datetime('now')
WHERE id = ?
"""


def _parse_args() -> argparse.Namespace:
    """
    功能:
        解析命令行参数.
    参数:
        无.
    返回:
        argparse.Namespace, 含 db_path, sleep, limit.
    """
    parser = argparse.ArgumentParser(
        description="批量通过 CAS 号补齐化学品库 SMILES 结构式",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="SQLite 数据库路径, 默认取 Settings.from_env().db_path",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.25,
        help="每次 PubChem 查询之间的延时(秒), 默认 0.25",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="仅处理前 N 条, 用于调试",
    )
    return parser.parse_args()


def _resolve_db_path(cli_db_path: Optional[str]) -> Path:
    """
    功能:
        解析实际使用的数据库路径. CLI 参数优先, 否则回退到 Settings.from_env().
    参数:
        cli_db_path: CLI 传入的路径字符串, 可能为 None.
    返回:
        Path, 指向 SQLite 数据库文件.
    """
    if cli_db_path is not None and cli_db_path.strip() != "":
        return Path(cli_db_path)
    return Settings.from_env().db_path


def backfill_smiles(db_path: Path, sleep_seconds: float, limit: Optional[int]) -> int:
    """
    功能:
        执行批量 SMILES 补齐. 每成功一条立即 COMMIT, 保证部分结果可持久化.
    参数:
        db_path: SQLite 数据库路径.
        sleep_seconds: 每次查询之间的延时(秒).
        limit: 本次处理的最大条数, None 表示不限制.
    返回:
        int, 进程退出码. 正常返回 0.
    """
    if db_path.exists() is False:
        logger.error("数据库文件不存在: %s", db_path)
        return 2

    logger.info("打开数据库: %s", db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        # 先用选集 SQL 拉出所有待处理记录 (内存占用小, chemicals 表规模有限)
        select_sql = _SELECT_SQL
        if limit is not None and limit > 0:
            select_sql = select_sql + f"\nLIMIT {int(limit)}"
        rows = conn.execute(select_sql).fetchall()
        total = len(rows)
        logger.info("待补齐记录数: %d", total)

        if total == 0:
            logger.info("没有需要补齐的记录, 脚本结束")
            return 0

        updated = 0
        skipped_no_result = 0
        started_at = time.time()

        for index, row in enumerate(rows, start=1):
            row_id = int(row["id"])
            cas = str(row["cas_number"]).strip()
            substance = row["substance"] or ""
            logger.info(
                "[%d/%d] 查询 id=%d, cas=%s, substance=%s",
                index, total, row_id, cas, substance,
            )

            # lookup_chemical 内部已吞掉所有网络/解析异常, 失败时返回 None
            info = lookup_chemical(cas)
            smiles_value = None
            if info is not None and info.smiles is not None:
                smiles_candidate = str(info.smiles).strip()
                if smiles_candidate != "":
                    smiles_value = smiles_candidate

            if smiles_value is None:
                skipped_no_result = skipped_no_result + 1
                logger.warning(
                    "跳过 id=%d, cas=%s: 未获取到有效 SMILES",
                    row_id, cas,
                )
            else:
                conn.execute(_UPDATE_SQL, (smiles_value, row_id))
                conn.commit()
                updated = updated + 1
                logger.info(
                    "已写入 id=%d, cas=%s, smiles=%s",
                    row_id, cas, smiles_value,
                )

            # 控制请求速率, 避免触发 PubChem 限流
            if index < total:
                time.sleep(sleep_seconds)

        elapsed = time.time() - started_at
        logger.info(
            "批处理结束: total=%d, updated=%d, skipped_no_result=%d, elapsed_seconds=%.2f",
            total, updated, skipped_no_result, elapsed,
        )
        return 0
    finally:
        conn.close()


def main() -> int:
    """
    功能:
        脚本入口. 解析参数, 初始化日志, 调用 backfill_smiles.
    参数:
        无.
    返回:
        int, 进程退出码.
    """
    args = _parse_args()
    configure_logging(level="INFO")

    db_path = _resolve_db_path(args.db_path)
    return backfill_smiles(
        db_path=db_path,
        sleep_seconds=float(args.sleep),
        limit=args.limit,
    )


if __name__ == "__main__":
    sys.exit(main())
