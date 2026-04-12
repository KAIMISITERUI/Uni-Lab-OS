# -*- coding: utf-8 -*-
"""
功能:
    管理 ChemicalBook 缓存, 原始 HTML 与结构化记录的数据目录.
"""

import logging
from pathlib import Path


logger = logging.getLogger("ChemicalBookStorage")

# 数据根目录指向 eit_chemical_manager/data/
_DRIVER_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = _DRIVER_ROOT / "data"
CHEMICALBOOK_CACHE_ROOT = DATA_ROOT / "chemicalbook_cache"
CHEMICALBOOK_RAW_ROOT = DATA_ROOT / "chemicalbook_raw"
CHEMICALBOOK_RECORD_ROOT = DATA_ROOT / "chemicalbook_records"

_DIRS_ENSURED = False


def ensure_chemicalbook_data_layout() -> None:
    """
    功能:
        确保 ChemicalBook 数据子目录存在, 不存在则创建.
    参数:
        无.
    返回:
        无.
    """
    global _DIRS_ENSURED

    if _DIRS_ENSURED is True:
        return

    for target_root in (
        CHEMICALBOOK_CACHE_ROOT,
        CHEMICALBOOK_RAW_ROOT,
        CHEMICALBOOK_RECORD_ROOT,
    ):
        target_root.mkdir(parents=True, exist_ok=True)

    _DIRS_ENSURED = True
