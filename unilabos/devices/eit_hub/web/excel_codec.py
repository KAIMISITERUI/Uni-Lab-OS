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
        result = {
            "path": str(template_path),
            "sheet_name": worksheet.title,
            "header_row": header_row,
            "experiment_column": exp_col,
            "supported_experiment_counts": SUPPORTED_EXPERIMENT_COUNTS,
            "param_rows": param_rows,
            "params": {
                str(item["name"]): item.get("value")
                for item in param_rows
                if item.get("type") == "parameter"
            },
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
        worksheet, header_row, exp_col = _select_experiment_sheet(workbook.worksheets)
        _write_params(worksheet, params)
        _write_experiment_area(worksheet, header_row, exp_col, headers, rows)
        safe_workbook_save(workbook, template_path)
        logger.info("已保存合成任务模板: %s", template_path)
    finally:
        workbook.close()

    return read_reaction_template(template_path)


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

