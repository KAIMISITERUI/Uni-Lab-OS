# -*- coding: utf-8 -*-
"""
功能:
    提供化学品查询结果追加入库所需的轻量工具函数.
    包括 ChemicalBook 结构化结果适配, 物态推断, 重复检查规则生成,
    以及全量 sidecar JSON 落盘.
参数:
    无.
返回:
    无.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


logger = logging.getLogger("ChemicalAppendUtils")

MODULE_ROOT = Path(__file__).resolve().parent.parent
CHEMICALBOOK_RECORD_ROOT = MODULE_ROOT / "data" / "chemicalbook_records"


def _first_non_empty(*values: Any) -> str:
    """
    功能:
        从多个候选值中返回第一个非空字符串.
    参数:
        values: 任意数量的候选值.
    返回:
        str, 第一个非空字符串. 若都为空则返回空字符串.
    """
    for value in values:
        value_text = str(value or "").strip()
        if value_text != "":
            return value_text
    return ""


def _first_non_none(*values: Any) -> Any:
    """
    功能:
        从多个候选值中返回第一个非 None 的值.
    参数:
        values: 任意数量的候选值.
    返回:
        Any, 第一个非 None 的值. 若都为空则返回 None.
    """
    for value in values:
        if value is not None:
            return value
    return None


def get_measurement_value(normalized: Optional[Dict[str, Any]], field_name: str) -> Optional[float]:
    """
    功能:
        从 ChemicalBook normalized 结果中提取数值型测量字段.
    参数:
        normalized: Optional[Dict[str, Any]], ChemicalBook normalized 字段.
        field_name: str, 目标字段名, 如 density 或 boiling_point.
    返回:
        Optional[float], 成功解析出的数值. 不存在时返回 None.
    """
    if isinstance(normalized, dict) is False:
        return None

    field_value = normalized.get(field_name)
    if isinstance(field_value, dict) is False:
        return None

    numeric_value = field_value.get("value")
    if numeric_value is None:
        return None

    try:
        return float(numeric_value)
    except (TypeError, ValueError):
        logger.warning("ChemicalBook 字段无法转换为浮点数: field=%s, value=%s", field_name, numeric_value)
        return None


def needs_legacy_chemicalbook_fallback(record: Optional[Dict[str, Any]]) -> bool:
    """
    功能:
        判断新 ChemicalBook 抓取结果是否需要旧实现兜底.
        仅关注当前入库链路依赖的中文名, 密度, 熔点三个核心字段.
    参数:
        record: Optional[Dict[str, Any]], fetch_chemicalbook_by_cas 返回结果.
    返回:
        bool, True 表示至少一个核心字段缺失, 需要旧实现回填.
    """
    if isinstance(record, dict) is False:
        return True

    normalized = record.get("normalized")
    cn_name = ""
    if isinstance(normalized, dict) is True:
        cn_name = str(normalized.get("cn_name") or "").strip()

    density_value = get_measurement_value(normalized, "density")
    melting_point_value = get_measurement_value(normalized, "melting_point")
    if cn_name == "" or density_value is None or melting_point_value is None:
        return True
    return False


def infer_physical_state(
    existing_state: Optional[str],
    melting_point: Optional[float],
    boiling_point: Optional[float],
) -> str:
    """
    功能:
        根据现有状态和温度数据推断 25 摄氏度下的物态.
    参数:
        existing_state: Optional[str], 已有物态值.
        melting_point: Optional[float], 熔点, 单位为摄氏度.
        boiling_point: Optional[float], 沸点, 单位为摄氏度.
    返回:
        str, solid, liquid, gas 或空字符串.
    """
    normalized_state = str(existing_state or "").strip().lower()
    if normalized_state != "":
        return normalized_state

    if melting_point is not None and melting_point > 25.0:
        return "solid"
    if boiling_point is not None and boiling_point <= 25.0:
        return "gas"
    if melting_point is not None or boiling_point is not None:
        return "liquid"
    return ""


def join_aliases(alias_values: Optional[Sequence[Any]]) -> str:
    """
    功能:
        将别名列表去重后拼接为适合写入 Excel 的字符串.
    参数:
        alias_values: Optional[Sequence[Any]], ChemicalBook 别名列表.
    返回:
        str, 以 ; 分隔的别名文本. 无有效别名时返回空字符串.
    """
    if isinstance(alias_values, Sequence) is False or isinstance(alias_values, (str, bytes)):
        return ""

    deduplicated_aliases: List[str] = []
    seen_aliases = set()
    for alias_value in alias_values:
        alias_text = str(alias_value or "").strip()
        if alias_text == "":
            continue
        if alias_text in seen_aliases:
            continue
        seen_aliases.add(alias_text)
        deduplicated_aliases.append(alias_text)

    return "; ".join(deduplicated_aliases)


def build_append_row_data(
    query: str,
    lookup_info: Optional[Any],
    chemicalbook_record: Optional[Dict[str, Any]],
    legacy_chemicalbook_info: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    功能:
        按约定优先级合并多源查询结果, 生成 Excel 追加行所需字段.
        Excel 主表仅保留核心字段, ChemicalBook 的全量结构化结果单独落盘 sidecar.
    参数:
        query: str, 用户输入的 CAS 或名称.
        lookup_info: Optional[Any], lookup_chemical 返回对象.
        chemicalbook_record: Optional[Dict[str, Any]], fetch_chemicalbook_by_cas 返回结果.
        legacy_chemicalbook_info: Optional[Any], 旧 _query_chemicalbook 返回对象, 仅作兜底.
    返回:
        Dict[str, Any], 追加入库所需字段映射.
    """
    normalized = {}
    if isinstance(chemicalbook_record, dict) is True and isinstance(chemicalbook_record.get("normalized"), dict) is True:
        normalized = chemicalbook_record["normalized"]

    lookup_cas = getattr(lookup_info, "cas_number", None)
    lookup_en_name = getattr(lookup_info, "substance_english_name", None)
    lookup_cn_name = getattr(lookup_info, "substance", None)
    lookup_molecular_weight = getattr(lookup_info, "molecular_weight", None)
    lookup_density = getattr(lookup_info, "density", None)
    lookup_melting_point = getattr(lookup_info, "melting_point", None)
    lookup_state = getattr(lookup_info, "physical_state", None)

    legacy_cn_name = getattr(legacy_chemicalbook_info, "substance", None)
    legacy_en_name = getattr(legacy_chemicalbook_info, "substance_english_name", None)
    legacy_density = getattr(legacy_chemicalbook_info, "density", None)
    legacy_melting_point = getattr(legacy_chemicalbook_info, "melting_point", None)

    chemicalbook_cas = ""
    if isinstance(chemicalbook_record, dict) is True:
        chemicalbook_cas = str(chemicalbook_record.get("cas") or "").strip()

    cas_number = _first_non_empty(lookup_cas, chemicalbook_cas, query)
    substance_english_name = _first_non_empty(
        lookup_en_name,
        normalized.get("en_name"),
        legacy_en_name,
    )
    substance_chinese_name = _first_non_empty(
        lookup_cn_name,
        normalized.get("cn_name"),
        legacy_cn_name,
    )
    molecular_weight = _first_non_none(
        lookup_molecular_weight,
        normalized.get("molecular_weight"),
    )
    density_value = _first_non_none(
        lookup_density,
        get_measurement_value(normalized, "density"),
        legacy_density,
    )
    melting_point_value = _first_non_none(
        lookup_melting_point,
        get_measurement_value(normalized, "melting_point"),
        legacy_melting_point,
    )
    boiling_point_value = get_measurement_value(normalized, "boiling_point")
    physical_state = infer_physical_state(
        existing_state=lookup_state,
        melting_point=melting_point_value,
        boiling_point=boiling_point_value,
    )
    other_name = join_aliases(normalized.get("aliases"))

    return {
        "cas_number": cas_number,
        "chemical_id": "",
        "substance_english_name": substance_english_name,
        "substance": substance_chinese_name,
        "substance_chinese_name": substance_chinese_name,
        "other_name": other_name,
        "brand": "",
        "package_size": "",
        "storage_location": "",
        "molecular_weight": molecular_weight,
        "density (g/mL)": density_value,
        "physical_state": physical_state,
        "physical_form": "neat",
        "active_content(mol/L or wt%)": "",
    }


def collect_missing_append_headers(header_map: Dict[str, int]) -> List[str]:
    """
    功能:
        检查化学品追加流程依赖的表头是否存在.
        中文名列兼容 substance 与 substance_chinese_name 两种命名.
    参数:
        header_map: Dict[str, int], Excel 表头映射.
    返回:
        List[str], 缺失的字段名列表.
    """
    missing_headers: List[str] = []
    required_headers = [
        "cas_number",
        "substance_english_name",
        "molecular_weight",
        "density (g/mL)",
        "physical_state",
        "physical_form",
    ]

    for header_name in required_headers:
        if header_name not in header_map:
            missing_headers.append(header_name)

    if "substance" not in header_map and "substance_chinese_name" not in header_map:
        missing_headers.append("substance/substance_chinese_name")

    return missing_headers


def build_duplicate_check_specs(row_data: Dict[str, Any]) -> List[Tuple[Tuple[str, ...], str, str]]:
    """
    功能:
        生成按优先级排列的重复检查规则.
        优先级固定为 CAS > 英文名 > 中文名.
    参数:
        row_data: Dict[str, Any], 准备写入 Excel 的行数据.
    返回:
        List[Tuple[Tuple[str, ...], str, str]], 每项包含候选列名集合, 目标值, 日志标签.
    """
    duplicate_specs: List[Tuple[Tuple[str, ...], str, str]] = []

    cas_number = str(row_data.get("cas_number") or "").strip()
    if cas_number != "":
        duplicate_specs.append((("cas_number",), cas_number, "CAS"))

    substance_english_name = str(row_data.get("substance_english_name") or "").strip()
    if substance_english_name != "":
        duplicate_specs.append((("substance_english_name",), substance_english_name, "英文名"))

    substance_chinese_name = str(
        row_data.get("substance")
        or row_data.get("substance_chinese_name")
        or ""
    ).strip()
    if substance_chinese_name != "":
        duplicate_specs.append((("substance", "substance_chinese_name"), substance_chinese_name, "中文名"))

    return duplicate_specs


def get_excel_write_value(row_data: Dict[str, Any], column_name: str) -> Any:
    """
    功能:
        根据目标表头名称, 返回适合写入 Excel 的字段值.
        该函数负责 substance 与 substance_chinese_name 两种列名的兼容.
    参数:
        row_data: Dict[str, Any], 追加行字段映射.
        column_name: str, Excel 表头列名.
    返回:
        Any, 对应列应写入的值.
    """
    if column_name == "substance":
        return row_data.get("substance") or row_data.get("substance_chinese_name")
    if column_name == "substance_chinese_name":
        return row_data.get("substance_chinese_name") or row_data.get("substance")
    return row_data.get(column_name)


def save_chemicalbook_record(
    record: Optional[Dict[str, Any]],
    output_root: Optional[Path] = None,
) -> str:
    """
    功能:
        将 ChemicalBook 全量结构化结果保存为 sidecar JSON 文件.
    参数:
        record: Optional[Dict[str, Any]], fetch_chemicalbook_by_cas 返回结果.
        output_root: Optional[Path], 自定义输出目录. None 时使用默认目录.
    返回:
        str, 保存后的 JSON 文件路径. 无法保存时返回空字符串.
    """
    if isinstance(record, dict) is False:
        return ""

    cas_number = str(record.get("cas") or "").strip()
    if cas_number == "":
        return ""

    target_root = output_root or CHEMICALBOOK_RECORD_ROOT
    target_root.mkdir(parents=True, exist_ok=True)
    output_path = target_root / f"{cas_number}.json"
    output_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(output_path)
