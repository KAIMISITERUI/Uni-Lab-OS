# -*- coding: utf-8 -*-
"""
功能:
    覆盖 EIT Hub 合成工站 Excel 编解码行为.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import openpyxl

from unilabos.devices.eit_hub.web.excel_codec import (
    read_reaction_template,
    write_reaction_template,
)


def _create_template(path: Path) -> None:
    """
    功能:
        创建测试用合成任务模板.
    参数:
        path: Path, 输出路径.
    返回:
        None.
    """
    workbook = openpyxl.Workbook()
    try:
        worksheet = workbook.active
        worksheet.title = "实验方案设定"
        worksheet["A1"] = "实验设定"
        worksheet["A2"] = "实验名称"
        worksheet["B2"] = "旧任务"
        worksheet["A3"] = "实验ID"
        worksheet["B3"] = 1
        worksheet["A4"] = "反应设定"
        worksheet["A5"] = "反应规模(mmol)"
        worksheet["B5"] = 0.2
        worksheet["A6"] = "反应器类型"
        worksheet["B6"] = "heat"
        worksheet["A7"] = "自动加磁子"
        worksheet["B7"] = "是"
        worksheet["A8"] = "分析方法设定"
        worksheet["A9"] = "GC_MS"
        worksheet["B9"] = "280_12min"
        worksheet["A10"] = "UPLC_QTOF"
        worksheet["B10"] = "Generic_5min"
        worksheet["A11"] = "HPLC"
        worksheet["C1"] = "实验编号"
        worksheet["D1"] = "试剂"
        worksheet["E1"] = "试剂量"
        worksheet["F1"] = "试剂"
        worksheet["G1"] = "试剂量"
        for index in range(1, 13):
            row_index = index + 1
            worksheet.cell(row_index, 3, index)
            worksheet.cell(row_index, 4, "乙腈")
            worksheet.cell(row_index, 5, "1mL")

        gc_sheet = workbook.create_sheet("GC产率计算")
        gc_sheet["A1"] = "内标SMILES"
        gc_sheet["B1"] = "CC"
        workbook.save(path)
    finally:
        workbook.close()


def _updated_payload() -> Dict[str, Any]:
    """
    功能:
        返回测试用 Web 模板数据.
    返回:
        Dict[str, Any], 模板 payload.
    """
    rows: List[List[Any]] = []
    for index in range(1, 13):
        rows.append([index, "对叔丁基苯甲醛", f"{index}.0eq", "乙腈", "1mL"])
    return {
        "param_rows": [
            {"name": "实验设定", "value": "", "type": "section"},
            {"name": "实验名称", "value": "Web任务", "type": "parameter"},
            {"name": "实验ID", "value": 1, "type": "parameter"},
            {"name": "反应规模(mmol)", "value": 0.5, "type": "parameter"},
            {"name": "反应器类型", "value": "heat", "type": "parameter"},
            {"name": "自动加磁子", "value": "否", "type": "parameter"},
            {"name": "分析方法设定", "value": "", "type": "section"},
            {"name": "GC_MS", "value": "280_12min(1-3)", "type": "parameter"},
            {"name": "UPLC_QTOF", "value": "Generic_5min", "type": "parameter"},
            {"name": "HPLC", "value": "", "type": "parameter"},
        ],
        "headers": ["实验编号", "试剂", "试剂量", "试剂", "试剂量"],
        "rows": rows,
    }


def test_reaction_template_read_write_round_trip(tmp_path: Path) -> None:
    """
    功能:
        验证模板读取, Web 数据写回和再次读取保持一致.
    """
    template_path = tmp_path / "reaction_template.xlsx"
    _create_template(template_path)

    original = read_reaction_template(template_path)
    assert original["params"]["实验名称"] == "旧任务"
    assert original["params"]["GC_MS"] == "280_12min"
    assert original["params"]["UPLC_QTOF"] == "Generic_5min"
    assert original["params"]["HPLC"] == ""
    param_names = [item["name"] for item in original["param_rows"]]
    assert "分析方法设定" in param_names
    assert "GC_MS" in param_names
    assert "UPLC_QTOF" in param_names
    assert "HPLC" in param_names
    assert original["headers"] == ["实验编号", "试剂", "试剂量", "试剂", "试剂量"]
    assert len(original["rows"]) == 12

    saved = write_reaction_template(_updated_payload(), template_path)

    assert saved["params"]["实验名称"] == "Web任务"
    assert saved["params"]["反应规模(mmol)"] == 0.5
    assert saved["params"]["GC_MS"] == "280_12min(1-3)"
    assert saved["params"]["UPLC_QTOF"] == "Generic_5min"
    assert saved["params"]["HPLC"] == ""
    assert saved["rows"][0] == [1, "对叔丁基苯甲醛", "1.0eq", "乙腈", "1mL"]

    workbook = openpyxl.load_workbook(template_path, data_only=False)
    try:
        assert "GC产率计算" in workbook.sheetnames
        assert workbook["GC产率计算"]["B1"].value == "CC"
        assert workbook["实验方案设定"]["B2"].value == "Web任务"
        assert workbook["实验方案设定"]["B9"].value == "280_12min(1-3)"
        assert workbook["实验方案设定"]["B10"].value == "Generic_5min"
        assert workbook["实验方案设定"]["B11"].value is None
        assert workbook["实验方案设定"]["D2"].value == "对叔丁基苯甲醛"
    finally:
        workbook.close()
