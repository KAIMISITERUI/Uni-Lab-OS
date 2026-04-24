# -*- coding: utf-8 -*-
"""
功能:
    读取和写入合成工站 reaction_template.xlsx, 为 Web 表格提供结构化数据.
协议:
    只修改包含 "实验编号" 表头的实验方案工作表, 保留其它工作表和工作簿结构.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.worksheet.worksheet import Worksheet

from unilabos.devices.eit_synthesis_station.utils.file_utils import safe_workbook_save

logger = logging.getLogger("EITHubExcelCodec")

JsonDict = Dict[str, Any]

DEVICES_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REACTION_TEMPLATE = (
    DEVICES_ROOT / "eit_synthesis_station" / "sheet" / "reaction_template.xlsx"
)
DEFAULT_BATCH_IN_TEMPLATE = DEVICES_ROOT / "eit_synthesis_station" / "sheet" / "batch_in_tray.xlsx"
BATCH_IN_HEADERS = ("position", "tray_type", "content", "shelf_position", "storage")
BATCH_IN_REQUIRED_HEADERS = ("position", "tray_type", "content")

PARAMETER_NAMES = (
    "实验名称",
    "实验ID",
    "反应规模(mmol)",
    "反应器类型",
    "反应时间(min/h)",
    "反应温度(°C)",
    "转速(rpm)",
    "搅拌后目标温度(°C)",
    "等待目标温度",
    "称量误差(%)",
    "最大称量误差(mg)",
    "固定加料顺序",
    "自动加磁子",
    "稀释液种类",
    "稀释量(μL)",
    "内标种类",
    "内标用量(μL/mg)",
    "加入内标后搅拌时间(min)",
    "闪滤液种类",
    "闪滤液用量(μL)",
    "取样量(μL)",
    "闪滤实验编号",
    "GC_MS",
    "UPLC_QTOF",
    "HPLC",
)

SECTION_NAMES = (
    "实验设定",
    "反应设定",
    "称量设定",
    "加料设定",
    "稀释设定",
    "内标设定",
    "闪滤设定",
    "分析方法设定",
)

SUPPORTED_EXPERIMENT_COUNTS = [12, 24, 36, 48]
YIELD_CONFIG_SHEET_NAME = "GC产率计算"
YIELD_PARAM_ROWS = (
    ("内标SMILES", "internal_standard_smiles"),
    ("内标预期RT(min)", "internal_standard_expected_rt"),
    ("产率计算方法", "yield_method"),
    ("标准曲线斜率", "curve_slope"),
    ("标准曲线截距", "curve_intercept"),
    ("响应因子", "response_factor"),
)
YIELD_PRODUCT_FIELDS = (
    ("适用实验", "applicable_experiments"),
    ("目标产物名称", "product_name"),
    ("当量(eq)", "equivalent"),
    ("SMILES", "smiles"),
    ("预期RT(min)", "expected_rt"),
)
YIELD_PRODUCT_FIELD_NAMES = tuple(field_name for _header_text, field_name in YIELD_PRODUCT_FIELDS)


def read_reaction_template(path: Path = DEFAULT_REACTION_TEMPLATE) -> JsonDict:
    """
    功能:
        读取 reaction_template.xlsx 并返回 Web 可编辑结构.
    参数:
        path: Path, 模板文件路径.
    返回:
        Dict[str, Any], 包含参数区, 表头和实验行.
    """
    template_path = Path(path)
    if template_path.exists() is False:
        raise FileNotFoundError(f"未找到任务模板文件: {template_path}")

    workbook = load_workbook(template_path, data_only=False)
    try:
        worksheet, header_row, exp_col = _select_experiment_sheet(workbook.worksheets)
        headers = _read_headers(worksheet, header_row, exp_col)
        rows = _read_experiment_rows(worksheet, header_row, exp_col, len(headers))
        param_rows = _read_param_rows(worksheet)
        gc_ms_yield = _read_gc_ms_yield_optional(workbook)
        result = {
            "path": str(template_path),
            "sheet_name": worksheet.title,
            "header_row": header_row,
            "experiment_column": exp_col,
            "has_gc_ms_yield_sheet": YIELD_CONFIG_SHEET_NAME in workbook.sheetnames,
            "supported_experiment_counts": SUPPORTED_EXPERIMENT_COUNTS,
            "param_rows": param_rows,
            "params": {
                str(item["name"]): item.get("value")
                for item in param_rows
                if item.get("type") == "parameter"
            },
            "gc_ms_yield": gc_ms_yield,
            "headers": headers,
            "rows": rows,
            "reagent_pair_count": _count_reagent_pairs(headers),
        }
        logger.debug("读取合成任务模板完成: %s", template_path)
        return result
    finally:
        workbook.close()


def write_reaction_template(payload: JsonDict, path: Path = DEFAULT_REACTION_TEMPLATE) -> JsonDict:
    """
    功能:
        将 Web 表格数据覆盖写回 reaction_template.xlsx.
    参数:
        payload: Dict[str, Any], 前端提交的模板结构.
        path: Path, 模板文件路径.
    返回:
        Dict[str, Any], 写入后重新读取的模板结构.
    """
    template_path = Path(path)
    if template_path.exists() is False:
        raise FileNotFoundError(f"未找到任务模板文件: {template_path}")

    headers = _normalize_headers(payload.get("headers"))
    rows = _normalize_rows(payload.get("rows"), len(headers))
    params = _collect_params(payload)
    workbook = load_workbook(template_path, data_only=False)
    try:
        worksheet_main, header_row, exp_col = _select_experiment_sheet(workbook.worksheets)
        _write_params(worksheet_main, params)
        _write_experiment_area(worksheet_main, header_row, exp_col, headers, rows)
        if YIELD_CONFIG_SHEET_NAME in workbook.sheetnames:
            gc_ms_yield = _normalize_gc_ms_yield(payload.get("gc_ms_yield"))
            worksheet_yield = _select_gc_ms_yield_sheet(workbook)
            _write_gc_ms_yield(worksheet_yield, gc_ms_yield)
        safe_workbook_save(workbook, template_path)
        logger.info("已保存合成任务模板: %s", template_path)
    finally:
        workbook.close()

    return read_reaction_template(template_path)


def read_batch_in_template(path: Path = DEFAULT_BATCH_IN_TEMPLATE) -> JsonDict:
    """
    功能:
        读取 batch_in_tray.xlsx 并返回 Web 可编辑的固定上料表格结构.
    参数:
        path: Path, 上料文件路径.
    返回:
        Dict[str, Any], 包含路径, 工作表名, 固定表头和上料行.
    """
    template_path = Path(path)
    if template_path.exists() is False:
        raise FileNotFoundError(f"未找到上料文件: {template_path}")

    workbook = load_workbook(template_path, data_only=False)
    try:
        worksheet, header_row, header_map = _select_batch_in_sheet(workbook)
        result = {
            "path": str(template_path),
            "sheet_name": worksheet.title,
            "headers": list(BATCH_IN_HEADERS),
            "tray_type_options": _read_batch_in_tray_type_options(workbook),
            "rows": _read_batch_in_rows(worksheet, header_row, header_map),
        }
        logger.debug("读取上料文件完成: %s", template_path)
        return result
    finally:
        workbook.close()


def write_batch_in_template(payload: JsonDict, path: Path = DEFAULT_BATCH_IN_TEMPLATE) -> JsonDict:
    """
    功能:
        将 Web 上料表格数据覆盖写回 batch_in_tray.xlsx.
    参数:
        payload: Dict[str, Any], 前端提交的上料表格结构.
        path: Path, 上料文件路径.
    返回:
        Dict[str, Any], 写入后重新读取的上料表格结构.
    """
    template_path = Path(path)
    if template_path.exists() is False:
        raise FileNotFoundError(f"未找到上料文件: {template_path}")

    _normalize_batch_in_headers(payload.get("headers"))
    rows = _normalize_rows(payload.get("rows"), len(BATCH_IN_HEADERS))

    workbook = load_workbook(template_path, data_only=False)
    try:
        worksheet, header_row, header_map = _select_batch_in_sheet(workbook)
        _write_batch_in_area(worksheet, header_row, header_map["position"], rows)
        safe_workbook_save(workbook, template_path)
        logger.info("已保存上料文件: %s", template_path)
    finally:
        workbook.close()

    return read_batch_in_template(template_path)


def _cell_text(value: Any) -> str:
    """
    功能:
        将单元格值转换为去空格文本.
    参数:
        value: Any, 单元格原始值.
    返回:
        str, 文本值.
    """
    if value is None:
        return ""
    return str(value).strip()


def _normalize_batch_in_header_text(value: Any) -> str:
    """
    功能:
        规范化上料表头文本, 用于定位固定列.
    参数:
        value: Any, 表头单元格原始值.
    返回:
        str, 去除空白和常见分隔符后的小写文本.
    """
    text = _cell_text(value)
    return (
        text.replace(" ", "")
        .replace("\n", "")
        .replace("\r", "")
        .replace("\t", "")
        .replace("_", "")
        .replace("-", "")
        .lower()
    )


def _batch_in_header_matches(normalized_text: str, expected_text: str) -> bool:
    """
    功能:
        判断上料表头是否匹配固定列名.
    参数:
        normalized_text: str, 已规范化的表头文本.
        expected_text: str, 期望列名.
    返回:
        bool, True 表示匹配.
    """
    if normalized_text == expected_text:
        return True
    if expected_text in {"content", "storage"} and normalized_text.startswith(expected_text):
        return True
    return False


def _select_batch_in_sheet(workbook: Any) -> Tuple[Worksheet, int, Dict[str, int]]:
    """
    功能:
        从上料工作簿中选择包含固定表头的工作表.
    参数:
        workbook: Any, openpyxl 工作簿对象.
    返回:
        Tuple[Worksheet, int, Dict[str, int]], 工作表, 表头行号和列映射.
    """
    candidate_sheet_names: List[str] = []
    if "batch_in_tray" in workbook.sheetnames:
        candidate_sheet_names.append("batch_in_tray")

    active_sheet_name = workbook.active.title
    if active_sheet_name not in candidate_sheet_names:
        candidate_sheet_names.append(active_sheet_name)

    for sheet_name in workbook.sheetnames:
        if sheet_name not in candidate_sheet_names:
            candidate_sheet_names.append(sheet_name)

    for sheet_name in candidate_sheet_names:
        worksheet = workbook[sheet_name]
        header_row, header_map = _find_batch_in_header_map(worksheet)
        if header_row is None or header_map is None:
            continue
        return worksheet, header_row, header_map

    raise ValueError(f"未找到可解析的上料工作表, 可用工作表: {workbook.sheetnames}")


def _find_batch_in_header_map(
    worksheet: Worksheet,
    max_scan_rows: int = 30,
    max_scan_cols: int = 30,
) -> Tuple[Optional[int], Optional[Dict[str, int]]]:
    """
    功能:
        在单个工作表中定位上料表头行和固定列映射.
    参数:
        worksheet: Worksheet, 工作表.
        max_scan_rows: int, 最大扫描行数.
        max_scan_cols: int, 最大扫描列数.
    返回:
        Tuple[Optional[int], Optional[Dict[str, int]]], 命中时返回行号和列映射.
    """
    scan_rows = min(worksheet.max_row, max_scan_rows)
    scan_cols = min(worksheet.max_column, max_scan_cols)
    expected_headers = {
        "position": "position",
        "tray_type": "traytype",
        "content": "content",
        "shelf_position": "shelfposition",
        "storage": "storage",
    }

    for row_index in range(1, scan_rows + 1):
        normalized_cells: Dict[int, str] = {}
        for col_index in range(1, scan_cols + 1):
            normalized_cells[col_index] = _normalize_batch_in_header_text(
                worksheet.cell(row_index, col_index).value
            )

        header_map: Dict[str, int] = {}
        for field_name, expected_text in expected_headers.items():
            for col_index, normalized_text in normalized_cells.items():
                if _batch_in_header_matches(normalized_text, expected_text) is False:
                    continue
                header_map[field_name] = col_index
                break

        if all(field_name in header_map for field_name in BATCH_IN_REQUIRED_HEADERS) is True:
            return row_index, header_map

    return None, None


def _select_experiment_sheet(worksheets: Iterable[Worksheet]) -> Tuple[Worksheet, int, int]:
    """
    功能:
        查找包含 "实验编号" 表头的工作表和单元格位置.
    参数:
        worksheets: Iterable[Worksheet], 工作簿内的工作表.
    返回:
        Tuple[Worksheet, int, int], 工作表, 表头行号, 实验编号列号.
    """
    for worksheet in worksheets:
        max_row = min(worksheet.max_row, 80)
        max_col = min(worksheet.max_column, 40)
        for row_index in range(1, max_row + 1):
            for col_index in range(1, max_col + 1):
                if _cell_text(worksheet.cell(row_index, col_index).value) == "实验编号":
                    return worksheet, row_index, col_index
    raise ValueError("模板中未找到 '实验编号' 表头.")


def _read_headers(worksheet: Worksheet, header_row: int, exp_col: int) -> List[str]:
    """
    功能:
        从实验编号列开始读取实验表头.
    参数:
        worksheet: Worksheet, 工作表.
        header_row: int, 表头行.
        exp_col: int, 实验编号列.
    返回:
        List[str], 表头文本列表.
    """
    raw_headers: List[str] = []
    for col_index in range(exp_col, worksheet.max_column + 1):
        raw_headers.append(_cell_text(worksheet.cell(header_row, col_index).value))

    last_non_empty = -1
    for index, header_text in enumerate(raw_headers):
        if header_text != "":
            last_non_empty = index

    if last_non_empty < 0:
        raise ValueError("模板实验表头为空.")

    return raw_headers[: last_non_empty + 1]


def _read_experiment_rows(
    worksheet: Worksheet,
    header_row: int,
    exp_col: int,
    width: int,
) -> List[List[Any]]:
    """
    功能:
        读取实验表格数据行.
    参数:
        worksheet: Worksheet, 工作表.
        header_row: int, 表头行.
        exp_col: int, 实验编号列.
        width: int, 读取列数.
    返回:
        List[List[Any]], 实验数据行.
    """
    rows: List[List[Any]] = []
    for row_index in range(header_row + 1, worksheet.max_row + 1):
        exp_no = worksheet.cell(row_index, exp_col).value
        if _cell_text(exp_no) == "":
            if len(rows) > 0:
                break
            continue

        row_values: List[Any] = []
        for offset in range(0, width):
            value = worksheet.cell(row_index, exp_col + offset).value
            if value is None:
                row_values.append("")
            else:
                row_values.append(value)
        rows.append(row_values)
    return rows


def _read_batch_in_rows(
    worksheet: Worksheet,
    header_row: int,
    header_map: Dict[str, int],
) -> List[List[Any]]:
    """
    功能:
        按固定上料列顺序读取上料数据行.
    参数:
        worksheet: Worksheet, 工作表.
        header_row: int, 表头行.
        header_map: Dict[str, int], 字段到列号的映射.
    返回:
        List[List[Any]], 上料数据行.
    """
    rows: List[List[Any]] = []
    for row_index in range(header_row + 1, worksheet.max_row + 1):
        position = worksheet.cell(row_index, header_map["position"]).value
        if _cell_text(position) == "":
            continue

        row_values: List[Any] = []
        for header_text in BATCH_IN_HEADERS:
            col_index = header_map.get(header_text)
            if col_index is None:
                row_values.append("")
                continue
            value = worksheet.cell(row_index, col_index).value
            if value is None:
                row_values.append("")
            else:
                row_values.append(value)
        rows.append(row_values)
    return rows


def _read_batch_in_tray_type_options(workbook: Any) -> List[str]:
    """
    功能:
        从上料文件隐藏校验表读取 tray_type 下拉选项.
    参数:
        workbook: Any, openpyxl 工作簿对象.
    返回:
        List[str], 托盘类型下拉选项.
    """
    if "validation_meta" not in workbook.sheetnames:
        return []

    worksheet = workbook["validation_meta"]
    options: List[str] = []
    for row_index in range(1, worksheet.max_row + 1):
        option_text = _cell_text(worksheet.cell(row_index, 1).value)
        if option_text == "":
            continue
        options.append(option_text)
    return options


def _read_param_rows(worksheet: Worksheet) -> List[JsonDict]:
    """
    功能:
        读取左侧参数区, 区分分类标题和可编辑参数.
    参数:
        worksheet: Worksheet, 工作表.
    返回:
        List[Dict[str, Any]], 参数行列表.
    """
    result: List[JsonDict] = []
    for row_index in range(1, worksheet.max_row + 1):
        name = _cell_text(worksheet.cell(row_index, 1).value)
        if name == "":
            continue
        if name.startswith("注:") or name.startswith("注："):
            continue

        value_cell = worksheet.cell(row_index, 2)
        value = "" if value_cell.value is None else value_cell.value

        if name in PARAMETER_NAMES:
            result.append(
                {
                    "name": name,
                    "value": value,
                    "row": row_index,
                    "type": "parameter",
                }
            )
            continue

        if name in SECTION_NAMES:
            result.append(
                {
                    "name": name,
                    "value": "",
                    "row": row_index,
                    "type": "section",
                }
            )
    return result


def _read_gc_ms_yield(workbook: Any) -> JsonDict:
    """
    功能:
        读取 GC产率计算 Sheet 并转换为 Web 结构.
    参数:
        workbook: Any, openpyxl 工作簿对象.
    返回:
        Dict[str, Any], GC-MS 产率配置.
    """
    worksheet = _select_gc_ms_yield_sheet(workbook)
    params = _read_sheet_kv_params(worksheet)
    products = _read_gc_ms_yield_products(worksheet)

    result = _build_default_gc_ms_yield()
    for sheet_key, field_name in YIELD_PARAM_ROWS:
        result[field_name] = params.get(sheet_key, "")
    result["yield_method"] = _normalize_yield_method(result.get("yield_method"))
    result["products"] = products
    return result


def _read_gc_ms_yield_optional(workbook: Any) -> JsonDict:
    """
    功能:
        读取 GC产率计算 Sheet, 缺失时返回空的 GC-MS 产率配置.
    参数:
        workbook: Any, openpyxl 工作簿对象.
    返回:
        Dict[str, Any], GC-MS 产率配置.
    """
    if YIELD_CONFIG_SHEET_NAME not in workbook.sheetnames:
        return _build_default_gc_ms_yield()
    return _read_gc_ms_yield(workbook)


def _select_gc_ms_yield_sheet(workbook: Any) -> Worksheet:
    """
    功能:
        读取 GC产率计算工作表.
    参数:
        workbook: Any, openpyxl 工作簿对象.
    返回:
        Worksheet, GC产率计算工作表.
    """
    if YIELD_CONFIG_SHEET_NAME not in workbook.sheetnames:
        raise ValueError(f"模板中未找到 '{YIELD_CONFIG_SHEET_NAME}' 工作表.")
    return workbook[YIELD_CONFIG_SHEET_NAME]


def _read_sheet_kv_params(worksheet: Worksheet) -> JsonDict:
    """
    功能:
        从工作表 A/B 两列读取键值区.
    参数:
        worksheet: Worksheet, 工作表.
    返回:
        Dict[str, Any], 键值字典.
    """
    params: JsonDict = {}
    header_row = _find_gc_ms_yield_header_row(worksheet)
    stop_row = header_row if header_row is not None else worksheet.max_row + 1
    for row_index in range(1, stop_row):
        key = _cell_text(worksheet.cell(row_index, 1).value)
        if key == "":
            continue
        params[key] = worksheet.cell(row_index, 2).value
    return params


def _find_gc_ms_yield_header_row(worksheet: Worksheet) -> Optional[int]:
    """
    功能:
        查找 GC产率计算产物表表头行.
    参数:
        worksheet: Worksheet, 工作表.
    返回:
        Optional[int], 表头行号.
    """
    max_scan_row = min(worksheet.max_row, 80)
    max_scan_col = min(worksheet.max_column, 20)
    for row_index in range(1, max_scan_row + 1):
        row_values = [
            _cell_text(worksheet.cell(row_index, col_index).value)
            for col_index in range(1, max_scan_col + 1)
        ]
        if "适用实验" in row_values and any("目标产物" in value for value in row_values):
            return row_index
    return None


def _build_gc_ms_yield_header_map(worksheet: Worksheet, header_row: int) -> Dict[str, int]:
    """
    功能:
        构造 GC产率计算产物表字段到列号的映射.
    参数:
        worksheet: Worksheet, 工作表.
        header_row: int, 表头行号.
    返回:
        Dict[str, int], 字段到列号的映射.
    """
    header_map: Dict[str, int] = {}
    for col_index in range(1, worksheet.max_column + 1):
        header_text = _cell_text(worksheet.cell(header_row, col_index).value)
        if header_text == "":
            continue
        if "适用实验" in header_text:
            header_map["applicable_experiments"] = col_index
            continue
        if "目标产物" in header_text:
            header_map["product_name"] = col_index
            continue
        if "当量" in header_text or "eq" in header_text.lower():
            header_map["equivalent"] = col_index
            continue
        if "SMILES" in header_text.upper():
            header_map["smiles"] = col_index
            continue
        if "RT" in header_text.upper():
            header_map["expected_rt"] = col_index
    missing_fields = [
        field_name
        for field_name in YIELD_PRODUCT_FIELD_NAMES
        if field_name not in header_map
    ]
    if len(missing_fields) > 0:
        raise ValueError(
            f"{YIELD_CONFIG_SHEET_NAME} 工作表缺少产物表头字段: {', '.join(missing_fields)}."
        )
    return header_map


def _read_gc_ms_yield_products(worksheet: Worksheet) -> List[JsonDict]:
    """
    功能:
        读取 GC产率计算产物表.
    参数:
        worksheet: Worksheet, 工作表.
    返回:
        List[Dict[str, Any]], 产物行列表.
    """
    header_row = _find_gc_ms_yield_header_row(worksheet)
    if header_row is None:
        return []
    header_map = _build_gc_ms_yield_header_map(worksheet, header_row)

    products: List[JsonDict] = []
    for row_index in range(header_row + 1, worksheet.max_row + 1):
        row_data: JsonDict = {}
        has_any_value = False
        for field_name, col_index in header_map.items():
            value = worksheet.cell(row_index, col_index).value
            row_data[field_name] = "" if value is None else value
            if _cell_text(value) != "":
                has_any_value = True
        if has_any_value is False:
            continue
        products.append(row_data)
    return products


def _build_default_gc_ms_yield() -> JsonDict:
    """
    功能:
        构造默认 GC-MS 产率配置结构.
    返回:
        Dict[str, Any], 默认结构.
    """
    return {
        "internal_standard_smiles": "",
        "internal_standard_expected_rt": "",
        "yield_method": "ECN",
        "curve_slope": "",
        "curve_intercept": "",
        "response_factor": "",
        "products": [],
    }


def _normalize_gc_ms_yield(raw_gc_ms_yield: Any) -> JsonDict:
    """
    功能:
        校验并规范化前端提交的 GC-MS 产率配置.
    参数:
        raw_gc_ms_yield: Any, 原始 GC-MS 产率配置.
    返回:
        Dict[str, Any], 规范化后的 GC-MS 产率配置.
    """
    if isinstance(raw_gc_ms_yield, dict) is False:
        raise ValueError("gc_ms_yield 必须是对象.")

    result = _build_default_gc_ms_yield()
    result["internal_standard_smiles"] = _cell_text(
        raw_gc_ms_yield.get("internal_standard_smiles")
    )
    result["internal_standard_expected_rt"] = raw_gc_ms_yield.get(
        "internal_standard_expected_rt", ""
    )
    result["yield_method"] = _normalize_yield_method(raw_gc_ms_yield.get("yield_method"))
    result["curve_slope"] = raw_gc_ms_yield.get("curve_slope", "")
    result["curve_intercept"] = raw_gc_ms_yield.get("curve_intercept", "")
    result["response_factor"] = raw_gc_ms_yield.get("response_factor", "")
    result["products"] = _normalize_gc_ms_yield_products(raw_gc_ms_yield.get("products"))

    if result["internal_standard_smiles"] == "":
        raise ValueError("GC-MS 数据分析中的内标SMILES不能为空.")

    if result["yield_method"] == "ECN":
        result["curve_slope"] = ""
        result["curve_intercept"] = ""
        result["response_factor"] = ""
    elif result["yield_method"] == "标准曲线":
        if _cell_text(result["curve_slope"]) == "":
            raise ValueError("GC-MS 数据分析选择标准曲线法时必须填写标准曲线斜率.")
        result["response_factor"] = ""
    elif result["yield_method"] == "响应因子":
        if _cell_text(result["response_factor"]) == "":
            raise ValueError("GC-MS 数据分析选择响应因子法时必须填写响应因子.")
        result["curve_slope"] = ""
        result["curve_intercept"] = ""

    return result


def _normalize_yield_method(raw_value: Any) -> str:
    """
    功能:
        规范化产率计算方法文本.
    参数:
        raw_value: Any, 原始方法值.
    返回:
        str, 规范化后的方法值.
    """
    text = _cell_text(raw_value)
    upper_text = text.upper()
    if text == "" or upper_text == "ECN":
        return "ECN"
    if text == "标准曲线" or upper_text in {"CALIBRATION", "CURVE"}:
        return "标准曲线"
    if text == "响应因子" or upper_text in {"RF", "RESPONSE_FACTOR"}:
        return "响应因子"
    raise ValueError(f"不支持的产率计算方法: {text}.")


def _normalize_gc_ms_yield_products(raw_products: Any) -> List[JsonDict]:
    """
    功能:
        校验并规范化 GC-MS 产率配置中的目标产物表.
    参数:
        raw_products: Any, 原始产物表数据.
    返回:
        List[Dict[str, Any]], 规范化后的产物列表.
    """
    if isinstance(raw_products, list) is False:
        raise ValueError("gc_ms_yield.products 必须是列表.")

    products: List[JsonDict] = []
    for row_index, raw_item in enumerate(raw_products, start=1):
        if isinstance(raw_item, dict) is False:
            raise ValueError(f"GC-MS 目标产物第 {row_index} 行必须是对象.")
        normalized_item = {
            "applicable_experiments": raw_item.get("applicable_experiments", ""),
            "product_name": raw_item.get("product_name", ""),
            "equivalent": raw_item.get("equivalent", ""),
            "smiles": raw_item.get("smiles", ""),
            "expected_rt": raw_item.get("expected_rt", ""),
        }
        non_empty_fields = [
            field_name
            for field_name, value in normalized_item.items()
            if _cell_text(value) != ""
        ]
        if len(non_empty_fields) == 0:
            continue
        if _cell_text(normalized_item["product_name"]) == "":
            raise ValueError(f"GC-MS 目标产物第 {row_index} 行缺少目标产物名称.")
        if _cell_text(normalized_item["smiles"]) == "":
            raise ValueError(f"GC-MS 目标产物第 {row_index} 行缺少 SMILES.")
        products.append(normalized_item)
    return products


def _normalize_headers(raw_headers: Any) -> List[str]:
    """
    功能:
        校验并规范化前端提交的表头.
    参数:
        raw_headers: Any, 原始表头.
    返回:
        List[str], 规范化表头.
    """
    if isinstance(raw_headers, list) is False:
        raise ValueError("headers 必须是列表.")

    headers = [_cell_text(item) for item in raw_headers]
    while len(headers) > 0 and headers[-1] == "":
        headers.pop()

    if len(headers) == 0:
        raise ValueError("headers 不能为空.")
    if headers[0] != "实验编号":
        raise ValueError("headers 第一列必须是 '实验编号'.")
    return headers


def _normalize_rows(raw_rows: Any, width: int) -> List[List[Any]]:
    """
    功能:
        校验并规范化前端提交的实验数据行.
    参数:
        raw_rows: Any, 原始行.
        width: int, 表头列数.
    返回:
        List[List[Any]], 规范化行.
    """
    if isinstance(raw_rows, list) is False:
        raise ValueError("rows 必须是列表.")

    rows: List[List[Any]] = []
    for row_index, raw_row in enumerate(raw_rows, start=1):
        if isinstance(raw_row, list) is False:
            raise ValueError(f"第 {row_index} 行必须是列表.")
        normalized = list(raw_row[:width])
        while len(normalized) < width:
            normalized.append("")
        rows.append(normalized)
    return rows


def _normalize_batch_in_headers(raw_headers: Any) -> List[str]:
    """
    功能:
        校验上料表格固定表头.
    参数:
        raw_headers: Any, 前端提交的表头.
    返回:
        List[str], 固定上料表头.
    """
    if isinstance(raw_headers, list) is False:
        raise ValueError("上料 headers 必须是列表.")

    headers = [_cell_text(item) for item in raw_headers]
    expected_headers = list(BATCH_IN_HEADERS)
    if headers != expected_headers:
        raise ValueError(f"上料 headers 必须是: {', '.join(expected_headers)}.")
    return expected_headers


def _collect_params(payload: JsonDict) -> JsonDict:
    """
    功能:
        从 payload 中收集参数键值.
    参数:
        payload: Dict[str, Any], 前端提交数据.
    返回:
        Dict[str, Any], 参数键值.
    """
    params: JsonDict = {}
    raw_params = payload.get("params")
    if isinstance(raw_params, dict):
        for key, value in raw_params.items():
            key_text = _cell_text(key)
            if key_text != "":
                params[key_text] = value

    raw_param_rows = payload.get("param_rows")
    if isinstance(raw_param_rows, list):
        for item in raw_param_rows:
            if isinstance(item, dict) is False:
                continue
            if item.get("type") != "parameter":
                continue
            name = _cell_text(item.get("name"))
            if name != "":
                params[name] = item.get("value", "")
    return params


def _write_params(worksheet: Worksheet, params: JsonDict) -> None:
    """
    功能:
        将参数写回左侧参数区.
    参数:
        worksheet: Worksheet, 工作表.
        params: Dict[str, Any], 参数键值.
    返回:
        None.
    """
    if len(params) == 0:
        return

    for row_index in range(1, worksheet.max_row + 1):
        name = _cell_text(worksheet.cell(row_index, 1).value)
        if name not in params:
            continue
        target_cell = worksheet.cell(row_index, 2)
        if isinstance(target_cell, MergedCell):
            continue
        target_cell.value = params[name]


def _write_experiment_area(
    worksheet: Worksheet,
    header_row: int,
    exp_col: int,
    headers: List[str],
    rows: List[List[Any]],
) -> None:
    """
    功能:
        覆盖写入实验表头和实验数据区.
    参数:
        worksheet: Worksheet, 工作表.
        header_row: int, 表头行.
        exp_col: int, 实验编号列.
        headers: List[str], 表头.
        rows: List[List[Any]], 实验数据行.
    返回:
        None.
    """
    clear_width = max(worksheet.max_column - exp_col + 1, len(headers) + 10)
    clear_height = max(worksheet.max_row - header_row + 1, len(rows) + 8, 56)

    for row_offset in range(0, clear_height):
        for col_offset in range(0, clear_width):
            cell = worksheet.cell(header_row + row_offset, exp_col + col_offset)
            if isinstance(cell, MergedCell):
                continue
            cell.value = None

    for col_offset, header_text in enumerate(headers):
        worksheet.cell(header_row, exp_col + col_offset, value=header_text)

    for row_offset, row_values in enumerate(rows, start=1):
        for col_offset, value in enumerate(row_values):
            worksheet.cell(header_row + row_offset, exp_col + col_offset, value=value)


def _write_batch_in_area(
    worksheet: Worksheet,
    header_row: int,
    start_col: int,
    rows: List[List[Any]],
) -> None:
    """
    功能:
        覆盖写入上料表头和数据区.
    参数:
        worksheet: Worksheet, 工作表.
        header_row: int, 表头行.
        start_col: int, 上料表起始列.
        rows: List[List[Any]], 上料数据行.
    返回:
        None.
    """
    clear_height = max(worksheet.max_row - header_row + 1, len(rows) + 8, 101)
    clear_width = len(BATCH_IN_HEADERS)

    for row_offset in range(0, clear_height):
        for col_offset in range(0, clear_width):
            cell = worksheet.cell(header_row + row_offset, start_col + col_offset)
            if isinstance(cell, MergedCell):
                continue
            cell.value = None

    for col_offset, header_text in enumerate(BATCH_IN_HEADERS):
        worksheet.cell(header_row, start_col + col_offset, value=header_text)

    for row_offset, row_values in enumerate(rows, start=1):
        for col_offset, value in enumerate(row_values):
            worksheet.cell(header_row + row_offset, start_col + col_offset, value=value)


def _write_gc_ms_yield(worksheet: Worksheet, gc_ms_yield: JsonDict) -> None:
    """
    功能:
        将 GC-MS 产率配置写回 GC产率计算工作表.
    参数:
        worksheet: Worksheet, GC产率计算工作表.
        gc_ms_yield: Dict[str, Any], 规范化后的产率配置.
    返回:
        None.
    """
    _write_gc_ms_yield_params(worksheet, gc_ms_yield)
    _write_gc_ms_yield_products(worksheet, gc_ms_yield.get("products", []))


def _write_gc_ms_yield_params(worksheet: Worksheet, gc_ms_yield: JsonDict) -> None:
    """
    功能:
        写回 GC产率计算上半区键值配置.
    参数:
        worksheet: Worksheet, GC产率计算工作表.
        gc_ms_yield: Dict[str, Any], 规范化后的产率配置.
    返回:
        None.
    """
    row_map: Dict[str, int] = {}
    for row_index in range(1, worksheet.max_row + 1):
        key_text = _cell_text(worksheet.cell(row_index, 1).value)
        if key_text != "":
            row_map[key_text] = row_index

    missing_keys = [sheet_key for sheet_key, _field_name in YIELD_PARAM_ROWS if sheet_key not in row_map]
    if len(missing_keys) > 0:
        raise ValueError(
            f"{YIELD_CONFIG_SHEET_NAME} 工作表缺少参数行: {', '.join(missing_keys)}."
        )

    for sheet_key, field_name in YIELD_PARAM_ROWS:
        row_index = row_map[sheet_key]
        value = gc_ms_yield.get(field_name, "")
        worksheet.cell(row_index, 2).value = None if _cell_text(value) == "" else value


def _write_gc_ms_yield_products(worksheet: Worksheet, products: Any) -> None:
    """
    功能:
        写回 GC产率计算下半区目标产物表.
    参数:
        worksheet: Worksheet, GC产率计算工作表.
        products: Any, 目标产物列表.
    返回:
        None.
    """
    header_row = _find_gc_ms_yield_header_row(worksheet)
    if header_row is None:
        raise ValueError(f"{YIELD_CONFIG_SHEET_NAME} 工作表缺少目标产物表头.")
    header_map = _build_gc_ms_yield_header_map(worksheet, header_row)

    min_col = min(header_map.values())
    max_col = max(header_map.values())
    clear_height = max(worksheet.max_row - header_row, len(products) + 12)
    for row_offset in range(1, clear_height + 1):
        for col_index in range(min_col, max_col + 1):
            cell = worksheet.cell(header_row + row_offset, col_index)
            if isinstance(cell, MergedCell):
                continue
            cell.value = None

    if isinstance(products, list) is False:
        raise ValueError("GC-MS 目标产物列表格式错误.")

    for row_offset, product in enumerate(products, start=1):
        if isinstance(product, dict) is False:
            raise ValueError("GC-MS 目标产物列表格式错误.")
        row_index = header_row + row_offset
        for _header_text, field_name in YIELD_PRODUCT_FIELDS:
            col_index = header_map[field_name]
            value = product.get(field_name, "")
            worksheet.cell(row_index, col_index).value = None if _cell_text(value) == "" else value


def _count_reagent_pairs(headers: List[str]) -> int:
    """
    功能:
        统计试剂/试剂量列组数量.
    参数:
        headers: List[str], 表头.
    返回:
        int, 试剂列组数.
    """
    count = 0
    for header_text in headers:
        if "试剂" in header_text and "量" not in header_text:
            count += 1
    return count
