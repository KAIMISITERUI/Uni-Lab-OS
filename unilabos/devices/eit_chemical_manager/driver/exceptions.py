# -*- coding: utf-8 -*-
"""
功能:
    eit_chemical_manager 驱动的异常层级定义.
    遵循项目驱动标准: 所有异常继承自 DriverError.
"""


class DriverError(Exception):
    """功能: 化学品管理驱动所有异常的基类."""


class ConfigError(DriverError):
    """功能: 配置错误, 例如数据库路径不可写."""


class ValidationError(DriverError):
    """功能: 输入校验错误, 例如查询类型非法或行数据缺失核心字段."""


class DatabaseError(DriverError):
    """功能: SQLite 数据库操作失败."""


class LookupError(DriverError):
    """功能: 在线化学品查询失败, 例如 PubChem 或 ChemicalBook 不可达."""
