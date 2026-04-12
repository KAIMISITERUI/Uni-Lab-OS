# -*- coding: utf-8 -*-
"""
功能:
    eit_chemical_manager 驱动使用的常量与枚举定义.
"""

from enum import Enum


# SQLite 表 chemicals 的核心列清单, 与历史 Excel 列名保持一致
CORE_COLUMNS = (
    "cas_number",
    "chemical_id",
    "substance",
    "substance_english_name",
    "other_name",
    "brand",
    "package_size",
    "storage_location",
    "molecular_weight",
    "density",
    "physical_state",
    "physical_form",
    "active_content",
    "smiles",
    "chemicalbook_record_path",
)


# 数值类型的核心列, 迁移与插入时需要进行 float 转换
NUMERIC_COLUMNS = ("molecular_weight", "density")


class QueryType(str, Enum):
    """
    功能:
        化学品查询类型枚举.
    """

    CAS = "cas"
    NAME = "name"
    SMILES = "smiles"


class PhysicalForm(str, Enum):
    """
    功能:
        化学品物理形态枚举.
        neat 为原态, solution 为溶液, beads 为珠料.
    """

    NEAT = "neat"
    SOLUTION = "solution"
    BEADS = "beads"


class PhysicalState(str, Enum):
    """
    功能:
        化学品物态枚举.
    """

    SOLID = "solid"
    LIQUID = "liquid"
    GAS = "gas"
