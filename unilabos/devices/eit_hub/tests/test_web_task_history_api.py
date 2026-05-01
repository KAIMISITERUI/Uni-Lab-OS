# -*- coding: utf-8 -*-
"""
功能:
    覆盖 EIT Hub 任务历史数据 Web API.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from unilabos.devices.eit_hub.web.app import create_app
from unilabos.devices.eit_hub.web.excel_codec import DEFAULT_REACTION_TEMPLATE
from unilabos.devices.eit_hub.web.routers import task_history


def _write_xlsx(path: Path, sheets: Dict[str, list]) -> None:
    """
    功能:
        写入一个含若干 sheet 的 xlsx 文件用于测试.
    参数:
        path: Path, 文件路径.
        sheets: Dict[str, list], sheet 名到行列表的映射.
    返回:
        None.
    """
    workbook = Workbook()
    workbook.remove(workbook.active)
    for sheet_name, rows in sheets.items():
        worksheet = workbook.create_sheet(title=sheet_name)
        for row in rows:
            worksheet.append(row)
    workbook.save(str(path))


def _write_task_report(path: Path) -> None:
    """
    功能:
        构造最小化但结构完整的任务报告 xlsx (5 行元信息 + 1 个步骤段含 2 实验).
    参数:
        path: Path, 输出文件路径.
    返回:
        None.
    """
    workbook = Workbook()
    workbook.remove(workbook.active)
    worksheet = workbook.create_sheet(title="托盘 W-2-5")
    rows = [
        [None] * 13,
        [None, "任务名称", "EIT-胺合成-725"],
        [None, "创建人", "admin", "创建时间", "2026-02-24T19:06:32", "任务状态", "已完成"],
        [None, "执行时长", "01:16:26", "开始时间", "2026-02-24T19:39:28", "完成时间", "2026-02-24T20:55:54"],
        [None, "托盘型号", "2 mL反应试管", "托盘条码", None, "托盘位置", "W-2-5"],
        [None] * 13,
        [None, "反应试管", "条码", "步骤1", "步骤状态", "完成时间"],
        [None, "1", None, "加磁子", "已完成", "2026-02-24T19:41:11"],
        [None, "2", None, "加磁子", "已完成", "2026-02-24T19:41:11"],
        [None, "反应试管", "条码", "步骤2", "步骤状态", "完成时间", "目标溶剂名称", "加液量(mL)", "单位"],
        [None, "1", None, "移液加液", "已完成", "2026-02-24T19:43:41", "乙腈", 1, "mL"],
        [None, "2", None, "移液加液", "已完成", "2026-02-24T19:44:03", "乙腈", 1, "mL"],
    ]
    for row in rows:
        worksheet.append(row)
    workbook.save(str(path))


def _write_integration_report(path: Path, structures_dir: Path) -> None:
    """
    功能:
        构造最小化的积分报告 xlsx (含 TIC 峰表, FID 峰表, 对照表, 样品汇总).
        TIC 化合物 1 名称单元格写入 hyperlink 指向 structures_dir 下结构图.
    参数:
        path: Path, 输出文件路径.
        structures_dir: Path, 结构图目录, hyperlink 目标的拼接基准.
    返回:
        None.
    """
    tic_headers = [
        "样品名", "峰号", "保留时间(min)", "峰高", "峰面积", "面积%",
        "峰起始(min)", "峰结束(min)", "峰宽(min)",
        "化合物1(名称)", "化合物1(匹配度)", "化合物1(分子式)", "化合物1(分子量)",
        "化合物2(名称)", "化合物2(匹配度)", "化合物2(分子式)", "化合物2(分子量)",
        "化合物3(名称)", "化合物3(匹配度)", "化合物3(分子式)", "化合物3(分子量)",
        "质谱图", "PIM预测分子量(Da)", "PIM置信指数", "SS-HM预测分子量(Da)", "SS-HM置信度",
    ]
    fid_headers = ["样品名", "峰号", "保留时间(min)", "峰高", "峰面积", "面积%", "峰起始(min)", "峰结束(min)", "峰宽(min)"]
    align_headers = [
        "样品名", "FID峰号", "FID保留时间(min)", "TIC峰号", "TIC保留时间(min)", "FID峰面积",
        "化合物1(名称)", "化合物1(匹配度)", "化合物1(分子式)", "化合物1(分子量)",
        "化合物2(名称)", "化合物2(匹配度)", "化合物2(分子式)", "化合物2(分子量)",
        "化合物3(名称)", "化合物3(匹配度)", "化合物3(分子式)", "化合物3(分子量)",
        "PIM预测分子量(Da)", "PIM置信指数", "SS-HM预测分子量(Da)", "SS-HM置信度", "质谱图",
    ]
    summary_headers = ["样品名", "TIC峰数", "FID峰数", "TIC总面积", "FID总面积", "采集时间", "TIC色谱图", "FID色谱图"]

    workbook = Workbook()
    workbook.remove(workbook.active)

    tic_ws = workbook.create_sheet(title="TIC峰表")
    tic_ws.append(tic_headers)
    tic_ws.append(["725-1", 1, 6.849, 12714845, 243540.99, 90.42, 6.819, 7.351, 0.532,
                   "1,2,4-Triisopropylbenzene", 92.1, "C15H24", 204,
                   "Benzene, 1,3,5-tris(1-methylethyl)-", 90, "C15H24", 204,
                   None, None, None, None, "查看链接", 204, 0.9481, 204, 0.9831])
    tic_ws.append(["725-1", 2, 7.653, 63083, 12858.77, 4.77, 7.592, 8.818, 1.225,
                   None, None, None, None, None, None, None, None, None, None, None, None,
                   "查看链接", 429, 0, 429, 0.5149])
    # 候选 1 名称单元格添加 hyperlink 到结构图 (模拟报告生成器行为)
    name_cell = tic_ws.cell(row=2, column=tic_headers.index("化合物1(名称)") + 1)
    name_cell.hyperlink = str(structures_dir / "100-46-9.png")

    fid_ws = workbook.create_sheet(title="FID峰表")
    fid_ws.append(fid_headers)
    fid_ws.append(["725-1", 1, 4.702, 0.8888, 0.019575, 1.67, 4.688, 4.755, 0.068])
    fid_ws.append(["725-1", 2, 6.843, 87.1354, 1.140963, 97.28, 6.821, 6.866, 0.044])

    align_ws = workbook.create_sheet(title="TIC-FID对照表")
    align_ws.append(align_headers)
    # 对照行 1: FID 峰 2 ↔ TIC 峰 1, 含候选化合物
    align_ws.append(["725-1", 2, 6.843, 1, 6.849, 1.140963,
                     "1,2,4-Triisopropylbenzene", 92.1, "C15H24", 204,
                     None, None, None, None, None, None, None, None,
                     204, 0.9481, 204, 0.9831, "查看质谱图"])
    align_name_cell = align_ws.cell(row=2, column=align_headers.index("化合物1(名称)") + 1)
    align_name_cell.hyperlink = str(structures_dir / "100-46-9.png")

    summary_ws = workbook.create_sheet(title="样品汇总")
    summary_ws.append(summary_headers)
    summary_ws.append(["725-1", 2, 2, 256399.76, 1.160538, "2026-02-24 21:17:17", "查看链接", "查看链接"])

    workbook.save(str(path))


def _write_yield_report(path: Path) -> None:
    """
    功能:
        构造最小化的产率报告 xlsx (含产率计算结果与计算参数).
    参数:
        path: Path, 输出文件路径.
    返回:
        None.
    """
    result_headers = [
        "样品名", "目标产物", "产物保留时间(min)", "产物FID面积", "产物匹配化合物",
        "内标保留时间(min)", "内标FID面积", "内标匹配化合物", "Ratio",
        "产物ECN", "内标ECN", "产率(%)", "匹配方式", "置信度",
        "NIST匹配分子量(Da)", "PIM预测分子量(Da)", "SS-HM预测分子量(Da)", "备注",
    ]
    _write_xlsx(path, {
        "产率计算结果": [
            result_headers,
            ["725-1", "酯化产物", 8.5, 12.34, "Some Compound",
             4.149, 2.301453, "Benzene, 1,2,4-trimethyl-", 5.36,
             19.93, 9, 53.5, "ECN", 0.9, 352, 352, 352,
             "命中"],
            ["725-2", "酯化产物", None, None, None,
             4.149, 2.0, "Benzene, 1,2,4-trimethyl-", None,
             19.93, 9, None, None, None, None, None, None,
             "未检测到目标峰"],
            ["725-3", "酯化产物", 8.7, 0.12, "Trace Compound",
             4.149, 2.0, "Benzene, 1,2,4-trimethyl-", 0.06,
             19.93, 9, "<1", "分子量命中", 0.7, 352, 352, 352,
             "低于 1%"],
        ],
        "计算参数": [
            ["参数", "值"],
            ["产率计算方法", "ECN"],
            ["反应规模(mmol)", 0.2],
            ["==== 内标信息 ====", None],
            ["内标 名称", "1,3,5-三异丙基苯"],
            ["内标 SMILES", "CC1=CC(C)=CC(C)=C1"],
            ["内标 分子式", "C9H12"],
            ["内标 分子量(Da)", 120.195],
            ["内标 ECN", 9],
            ["==== 目标产物 ====", None],
            ["产物1 名称", "酯化产物"],
            ["产物1 SMILES", "O=C1CC[C@@]2C"],
            ["产物1 分子式", "C23H28O3"],
            ["产物1 分子量(Da)", 352.474],
            ["产物1 ECN", 19.932],
            ["产物1 当量(eq)", 1],
        ],
    })


def _write_experiment_plan(path: Path, task_name: str) -> None:
    """
    功能:
        基于真实 reaction_template.xlsx 生成测试实验计划, 并写入指定的实验名称.
    参数:
        path: Path, 输出文件路径.
        task_name: str, 实验名称值.
    返回:
        None.
    """
    shutil.copyfile(DEFAULT_REACTION_TEMPLATE, path)
    workbook = load_workbook(path)
    try:
        for worksheet in workbook.worksheets:
            for row in worksheet.iter_rows():
                for cell in row:
                    if cell.value == "实验名称":
                        worksheet.cell(cell.row, cell.column + 1).value = task_name
                        workbook.save(str(path))
                        return
    finally:
        workbook.close()
    raise AssertionError("模板中未找到 '实验名称' 单元格")


def _write_csv(path: Path, content: str) -> None:
    """
    功能:
        写入测试 csv 文件.
    参数:
        path: Path, 文件路径.
        content: str, 文件内容.
    返回:
        None.
    """
    path.write_text(content, encoding="utf-8")


def _write_task_info(path: Path, info: Dict[str, Any]) -> None:
    """
    功能:
        写入测试 task_info.json.
    参数:
        path: Path, 文件路径.
        info: Dict[str, Any], 任务信息.
    返回:
        None.
    """
    path.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")


@pytest.fixture()
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Path, Path]:
    """
    功能:
        创建隔离的任务历史 API 测试客户端.
    参数:
        tmp_path: Path, pytest 临时目录.
        monkeypatch: pytest.MonkeyPatch, monkeypatch 工具.
    返回:
        tuple[TestClient, Path, Path], 测试客户端, 合成站任务根, 分析站数据根.
    """
    synthesis_root = tmp_path / "synthesis_tasks"
    analysis_root = tmp_path / "analysis_data"
    synthesis_root.mkdir(parents=True, exist_ok=True)
    analysis_root.mkdir(parents=True, exist_ok=True)

    # 任务 725: 合成任务核心文件中除 hplc 外全部存在
    task_725 = synthesis_root / "725"
    task_725.mkdir()
    _write_experiment_plan(task_725 / "725_experiment_plan.xlsx", "EIT-胺合成-725")
    _write_task_report(task_725 / "725_task_report.xlsx")
    _write_csv(
        task_725 / "gc_ms.csv",
        "SampleName,AcqMethod,RackCode,VialPos,SmplInjVol,OutputFile\n"
        "725-1,280_12min,Rack 6,47,1,725-1\n",
    )
    _write_csv(
        task_725 / "uplc_qtof.csv",
        "SampleName,AcqMethod,RackCode,VialPos,SmplInjVol,OutputFile\n"
        "725-1,50-100_positive_5min,Rack 1,48,2,725-1\n",
    )
    _write_task_info(
        task_725 / "task_info.json",
        {
            "task_id": "725",
            "status": "COMPLETED",
            "created_at": "2026-02-24T19:06:34",
            "started_at": "2026-02-24T19:39:23",
            "completed_at": "2026-02-24T20:55:54",
        },
    )

    # 任务 504: 仅有 experiment_plan
    task_504 = synthesis_root / "504"
    task_504.mkdir()
    _write_experiment_plan(task_504 / "504_experiment_plan.xlsx", "Test-504")
    _write_task_info(
        task_504 / "task_info.json",
        {"task_id": "504", "status": "FAILED"},
    )

    # 干扰子目录: 名称非整数
    (synthesis_root / "_archive").mkdir()

    # 分析站任务 725: plots / structures / ms_plots + 积分报告 + 产率报告
    analysis_725 = analysis_root / "725"
    (analysis_725 / "plots").mkdir(parents=True)
    (analysis_725 / "structures").mkdir(parents=True)
    (analysis_725 / "ms_plots").mkdir(parents=True)
    (analysis_725 / "plots" / "725-1_tic.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    (analysis_725 / "plots" / "725-1_fid.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    structures_dir = analysis_725 / "structures"
    (structures_dir / "100-46-9.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    (analysis_725 / "ms_plots" / "725-1_peak1_ms.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    (analysis_725 / "ms_plots" / "725-1_peak2_ms.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    # 干扰文件: 非图片后缀
    (analysis_725 / "plots" / "readme.txt").write_text("ignore", encoding="utf-8")
    _write_integration_report(analysis_725 / "725_integration_report.xlsx", structures_dir)
    _write_yield_report(analysis_725 / "725_yield_report.xlsx")

    monkeypatch.setattr(task_history, "DEFAULT_HISTORY_TASKS_DIR", synthesis_root)
    monkeypatch.setattr(task_history, "ANALYSIS_DATA_DIR", analysis_root)

    return TestClient(create_app()), synthesis_root, analysis_root


def _find_file_presence(files: list, key: str) -> Dict[str, Any]:
    """
    功能:
        在 files 列表中按 key 查找单条记录.
    参数:
        files: list, files 数组.
        key: str, 文件键.
    返回:
        Dict[str, Any], 命中记录.
    """
    for entry in files:
        if entry["key"] == key:
            return entry
    raise AssertionError(f"未找到 file_key={key}")


def test_list_returns_tasks_with_file_presences(
    api_client: tuple[TestClient, Path, Path],
) -> None:
    """
    功能:
        验证列表端点返回任务且每项包含合成任务文件与分析报告检查.
    """
    client, _synthesis_root, _analysis_root = api_client
    response = client.get("/api/task-history/list")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    task_ids = [item["task_id"] for item in body["items"]]
    assert task_ids == [725, 504]

    item_725 = body["items"][0]
    assert item_725["task_id"] == 725
    assert item_725["task_name"] == "EIT-胺合成-725"
    assert item_725["status"] == "COMPLETED"
    assert len(item_725["files"]) == 6
    keys = [entry["key"] for entry in item_725["files"]]
    assert keys == ["experiment_plan", "task_report", "gc_ms", "uplc_qtof", "hplc", "yield_report"]
    assert _find_file_presence(item_725["files"], "experiment_plan")["exists"] is True
    assert _find_file_presence(item_725["files"], "hplc")["exists"] is False
    assert _find_file_presence(item_725["files"], "yield_report")["exists"] is True


def test_list_filters_by_query(api_client: tuple[TestClient, Path, Path]) -> None:
    """
    功能:
        验证 query 参数同时支持任务 ID 与任务名称模糊匹配.
    """
    client, _synthesis_root, _analysis_root = api_client

    response_id = client.get("/api/task-history/list", params={"query": "725"})
    assert response_id.status_code == 200
    assert [item["task_id"] for item in response_id.json()["items"]] == [725]

    response_name = client.get("/api/task-history/list", params={"query": "胺合成"})
    assert response_name.status_code == 200
    assert [item["task_id"] for item in response_name.json()["items"]] == [725]

    response_empty = client.get("/api/task-history/list", params={"query": "不存在"})
    assert response_empty.status_code == 200
    assert response_empty.json()["total"] == 0


def test_hplc_always_missing(api_client: tuple[TestClient, Path, Path]) -> None:
    """
    功能:
        验证 hplc.csv 在所有任务中都标记为缺失.
    """
    client, _synthesis_root, _analysis_root = api_client
    response = client.get("/api/task-history/list")
    for item in response.json()["items"]:
        assert _find_file_presence(item["files"], "hplc")["exists"] is False


def test_yield_report_presence_marks_analysis_report(
    api_client: tuple[TestClient, Path, Path],
) -> None:
    """
    功能:
        验证任务列表会标记分析站产率报告是否存在, 用于前端筛选和卡片展示.
    """
    client, _synthesis_root, _analysis_root = api_client
    response = client.get("/api/task-history/list")
    assert response.status_code == 200
    items = {item["task_id"]: item for item in response.json()["items"]}
    assert _find_file_presence(items[725]["files"], "yield_report")["exists"] is True
    assert _find_file_presence(items[725]["files"], "yield_report")["filename"] == "725_yield_report.xlsx"
    assert _find_file_presence(items[504]["files"], "yield_report")["exists"] is False


def test_detail_includes_image_groups_and_lazy_ms_plots(
    api_client: tuple[TestClient, Path, Path],
) -> None:
    """
    功能:
        验证详情端点返回图集分组, 且 ms_plots 组默认懒加载.
    """
    client, _synthesis_root, _analysis_root = api_client
    response = client.get("/api/task-history/725")
    assert response.status_code == 200
    body = response.json()
    assert body["task"]["task_id"] == 725
    groups = {entry["name"]: entry for entry in body["image_groups"]}
    assert groups["plots"]["count"] == 2
    assert groups["plots"]["images"] == ["725-1_fid.png", "725-1_tic.png"]
    assert groups["plots"]["lazy"] is False
    assert groups["structures"]["count"] == 1
    assert groups["ms_plots"]["count"] == 2
    assert groups["ms_plots"]["lazy"] is True
    assert groups["ms_plots"]["images"] == []


def test_detail_404_for_unknown_task(api_client: tuple[TestClient, Path, Path]) -> None:
    """
    功能:
        验证不存在的任务 ID 返回 404.
    """
    client, _synthesis_root, _analysis_root = api_client
    response = client.get("/api/task-history/9999")
    assert response.status_code == 404


def test_xlsx_preview_returns_sheet_data(api_client: tuple[TestClient, Path, Path]) -> None:
    """
    功能:
        验证 xlsx 预览返回 sheet 与行内容.
    """
    client, _synthesis_root, _analysis_root = api_client
    response = client.get("/api/task-history/725/files/task_report/preview")
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "xlsx"
    assert len(body["sheets"]) == 1
    sheet = body["sheets"][0]
    assert sheet["sheet_name"] == "托盘 W-2-5"
    # 第 1 行表头 (任务名称行) 后续行为元信息, 仅验证 sheet 名与是否有数据
    assert len(sheet["rows"]) > 0


def test_csv_preview_returns_rows(api_client: tuple[TestClient, Path, Path]) -> None:
    """
    功能:
        验证 csv 预览正确解析表头与行.
    """
    client, _synthesis_root, _analysis_root = api_client
    response = client.get("/api/task-history/725/files/gc_ms/preview")
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "csv"
    assert body["headers"][0] == "SampleName"
    assert body["rows"][0][0] == "725-1"


def test_preview_404_when_file_missing(api_client: tuple[TestClient, Path, Path]) -> None:
    """
    功能:
        验证缺失文件 (例如 hplc) 预览返回 404.
    """
    client, _synthesis_root, _analysis_root = api_client
    response = client.get("/api/task-history/725/files/hplc/preview")
    assert response.status_code == 404


def test_preview_400_for_invalid_file_key(api_client: tuple[TestClient, Path, Path]) -> None:
    """
    功能:
        验证非法 file_key 返回 400.
    """
    client, _synthesis_root, _analysis_root = api_client
    response = client.get("/api/task-history/725/files/unknown/preview")
    assert response.status_code == 400


def test_download_returns_file(api_client: tuple[TestClient, Path, Path]) -> None:
    """
    功能:
        验证下载端点返回文件原始内容.
    """
    client, _synthesis_root, _analysis_root = api_client
    response = client.get("/api/task-history/725/files/gc_ms/download")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/octet-stream")
    assert b"SampleName" in response.content


def test_image_list_returns_filenames(api_client: tuple[TestClient, Path, Path]) -> None:
    """
    功能:
        验证图集列表端点返回文件名 (用于 ms_plots 懒加载).
    """
    client, _synthesis_root, _analysis_root = api_client
    response = client.get("/api/task-history/725/images/ms_plots")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert body["images"] == ["725-1_peak1_ms.png", "725-1_peak2_ms.png"]


def test_image_list_400_for_unknown_group(api_client: tuple[TestClient, Path, Path]) -> None:
    """
    功能:
        验证未知图集名称返回 400.
    """
    client, _synthesis_root, _analysis_root = api_client
    response = client.get("/api/task-history/725/images/unknown")
    assert response.status_code == 400


def test_serve_image_returns_png(api_client: tuple[TestClient, Path, Path]) -> None:
    """
    功能:
        验证图片端点返回 PNG 内容.
    """
    client, _synthesis_root, _analysis_root = api_client
    response = client.get("/api/task-history/725/images/plots/725-1_tic.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")


def test_serve_image_rejects_path_traversal(api_client: tuple[TestClient, Path, Path]) -> None:
    """
    功能:
        验证图片端点拒绝路径穿越攻击.
    """
    client, _synthesis_root, _analysis_root = api_client
    response = client.get("/api/task-history/725/images/plots/..%2F..%2Fetc%2Fpasswd")
    assert response.status_code in (403, 404)


def test_serve_image_rejects_unsupported_suffix(
    api_client: tuple[TestClient, Path, Path],
) -> None:
    """
    功能:
        验证图片端点拒绝不支持的文件后缀.
    """
    client, _synthesis_root, _analysis_root = api_client
    response = client.get("/api/task-history/725/images/plots/readme.txt")
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# 业务视图端点测试
# ---------------------------------------------------------------------------


def test_experiment_plan_endpoint(api_client: tuple[TestClient, Path, Path]) -> None:
    """
    功能:
        验证实验计划端点返回 read_reaction_template 解析结果, 含 task_id.
    """
    client, _synthesis_root, _analysis_root = api_client
    response = client.get("/api/task-history/725/experiment-plan")
    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == 725
    assert body["params"]["实验名称"] == "EIT-胺合成-725"
    assert isinstance(body["headers"], list)
    assert isinstance(body["rows"], list)


def test_experiment_plan_404_when_missing(api_client: tuple[TestClient, Path, Path]) -> None:
    """
    功能:
        验证实验计划缺失时返回 404.
    """
    client, synthesis_root, _analysis_root = api_client
    (synthesis_root / "999").mkdir()
    response = client.get("/api/task-history/999/experiment-plan")
    assert response.status_code == 404


def test_task_report_endpoint(api_client: tuple[TestClient, Path, Path]) -> None:
    """
    功能:
        验证任务报告端点返回元信息 + 实验编号 + 步骤段重组结构.
    """
    client, _synthesis_root, _analysis_root = api_client
    response = client.get("/api/task-history/725/task-report")
    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == 725
    assert body["metadata"]["task_name"] == "EIT-胺合成-725"
    assert body["metadata"]["operator"] == "admin"
    assert body["metadata"]["task_status"] == "已完成"
    assert body["metadata"]["tray_position"] == "W-2-5"
    assert body["experiments"] == [1, 2]
    assert len(body["steps"]) == 2
    step1 = body["steps"][0]
    assert step1["step_index"] == 1
    assert step1["step_label"] == "步骤1"
    assert step1["step_name"] == "加磁子"
    assert step1["extra_columns"] == []
    assert step1["experiments"]["1"]["status"] == "已完成"
    step2 = body["steps"][1]
    assert step2["step_index"] == 2
    assert step2["step_name"] == "移液加液"
    assert step2["extra_columns"] == ["目标溶剂名称", "加液量(mL)", "单位"]
    assert step2["experiments"]["1"]["extras"] == ["乙腈", 1, "mL"]


def test_task_report_404_when_missing(api_client: tuple[TestClient, Path, Path]) -> None:
    """
    功能:
        验证任务报告缺失时返回 404.
    """
    client, _synthesis_root, _analysis_root = api_client
    response = client.get("/api/task-history/504/task-report")
    assert response.status_code == 404


def test_integration_report_endpoint(api_client: tuple[TestClient, Path, Path]) -> None:
    """
    功能:
        验证积分报告端点返回样品 → 峰 → 候选化合物 + 关联图片引用.
    """
    client, _synthesis_root, _analysis_root = api_client
    response = client.get("/api/task-history/725/integration-report")
    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == 725
    samples = body["samples"]
    assert len(samples) == 1
    sample = samples[0]
    assert sample["name"] == "725-1"
    assert sample["tic_peak_count"] == 2
    assert sample["fid_peak_count"] == 2
    assert sample["tic_image"] == "725-1_tic.png"
    assert sample["fid_image"] == "725-1_fid.png"
    assert len(sample["tic_peaks"]) == 2
    peak1 = sample["tic_peaks"][0]
    assert peak1["peak_no"] == 1
    assert peak1["ms_image"] == "725-1_peak1_ms.png"
    assert len(peak1["candidates"]) == 2
    assert peak1["candidates"][0]["name"] == "1,2,4-Triisopropylbenzene"
    assert peak1["candidates"][0]["score"] == 92.1
    # hyperlink 指向已存在的 structures/100-46-9.png
    assert peak1["candidates"][0]["structure_image"] == "100-46-9.png"
    # 第二个候选无 hyperlink, 结构图为 null
    assert peak1["candidates"][1]["structure_image"] is None
    assert peak1["pim_mw"] == 204
    peak2 = sample["tic_peaks"][1]
    assert peak2["peak_no"] == 2
    assert peak2["ms_image"] == "725-1_peak2_ms.png"
    # 测试数据中 peak2 没有候选化合物 (xlsx 行设置为 None)
    assert peak2["candidates"] == []
    assert len(sample["fid_peaks"]) == 2
    # 对照表: FID 峰 2 ↔ TIC 峰 1, 一项有候选化合物
    assert len(sample["alignments"]) == 1
    align0 = sample["alignments"][0]
    assert align0["fid_peak_no"] == 2
    assert align0["tic_peak_no"] == 1
    assert align0["ms_image"] == "725-1_peak1_ms.png"
    assert len(align0["candidates"]) == 1
    assert align0["candidates"][0]["name"] == "1,2,4-Triisopropylbenzene"
    assert align0["candidates"][0]["structure_image"] == "100-46-9.png"


def test_integration_report_404_when_missing(api_client: tuple[TestClient, Path, Path]) -> None:
    """
    功能:
        验证积分报告缺失时返回 404.
    """
    client, _synthesis_root, _analysis_root = api_client
    response = client.get("/api/task-history/504/integration-report")
    assert response.status_code == 404


def test_yield_report_endpoint(api_client: tuple[TestClient, Path, Path]) -> None:
    """
    功能:
        验证产率报告端点返回配置 + 产物列表 + 样品 × 产物 矩阵.
    """
    client, _synthesis_root, _analysis_root = api_client
    response = client.get("/api/task-history/725/yield-report")
    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == 725
    config = body["config"]
    assert config["calc_method"] == "ECN"
    assert config["reaction_scale"] == 0.2
    assert config["internal_standard"]["name"] == "1,3,5-三异丙基苯"
    assert config["internal_standard"]["smiles"] == "CC1=CC(C)=CC(C)=C1"
    assert config["internal_standard"]["formula"] == "C9H12"
    assert len(config["products"]) == 1
    assert config["products"][0]["name"] == "酯化产物"
    assert config["products"][0]["smiles"] == "O=C1CC[C@@]2C"
    assert body["products"] == ["酯化产物"]
    assert len(body["samples"]) == 3
    sample1 = body["samples"][0]
    assert sample1["sample"] == "725-1"
    assert sample1["results"][0]["yield_pct"] == 53.5
    assert sample1["results"][0]["yield_display"] == "54%"
    sample2 = body["samples"][1]
    assert sample2["sample"] == "725-2"
    assert sample2["results"][0]["yield_pct"] is None
    assert sample2["results"][0]["yield_display"] == "-"
    assert "未检测到" in sample2["results"][0]["remarks"]
    sample3 = body["samples"][2]
    assert sample3["sample"] == "725-3"
    assert sample3["results"][0]["yield_pct"] is None
    assert sample3["results"][0]["yield_display"] == "<1%"


def test_yield_report_404_when_missing(api_client: tuple[TestClient, Path, Path]) -> None:
    """
    功能:
        验证产率报告缺失时返回 404.
    """
    client, _synthesis_root, _analysis_root = api_client
    response = client.get("/api/task-history/504/yield-report")
    assert response.status_code == 404
