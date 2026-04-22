# -*- coding: utf-8 -*-
"""
功能:
    提供分析工站 Web API, 支持三台分析仪器状态查询和手工 CSV 提交.
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field

from unilabos.devices.eit_analysis_station.controller.analysis_controller import (
    AnalysisStationController,
)
from unilabos.devices.eit_analysis_station.driver.zhida_driver import ZhidaClient

from ..deps import get_analysis_controller
from ..jobs import JobBusyError, job_manager

logger = logging.getLogger("EITHubAnalysisRouter")

JsonDict = Dict[str, Any]

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

CSV_HEADERS: List[str] = [
    "SampleName",
    "AcqMethod",
    "RackCode",
    "VialPos",
    "SmplInjVol",
    "OutputFile",
]
INSTRUMENT_ORDER: List[str] = ["gc_ms", "uplc_qtof", "hplc"]
INSTRUMENT_NAMES: Dict[str, str] = {
    "gc_ms": "GC-MS",
    "uplc_qtof": "UPLC_QTOF",
    "hplc": "HPLC",
}
ALLOWED_RACK_CODES = {f"Rack {index}" for index in range(1, 7)}
OFFLINE_STATUSES = {"", "offline", "error", "unknown"}


class AnalysisSampleRow(BaseModel):
    """
    功能:
        承载分析仪器 CSV 的一行样品配置, 字段名与仪器协议列名保持一致.
    参数:
        SampleName: 样品名称.
        AcqMethod: 采集方法.
        RackCode: 样品盘编号, 仅允许 Rack 1 到 Rack 6.
        VialPos: 样品瓶位, 正整数.
        SmplInjVol: 进样量, 非负数字.
        OutputFile: 输出文件名.
    返回:
        AnalysisSampleRow.
    """

    SampleName: Optional[Any] = None
    AcqMethod: Optional[Any] = None
    RackCode: Optional[Any] = None
    VialPos: Optional[Any] = None
    SmplInjVol: Optional[Any] = None
    OutputFile: Optional[Any] = None

    class Config:
        extra = "forbid"


class AnalysisSubmitRequest(BaseModel):
    """
    功能:
        承载分析工站手工提交请求.
    参数:
        tables: Dict[str, List[AnalysisSampleRow]], 按仪器 key 组织的样品表.
    返回:
        AnalysisSubmitRequest.
    """

    tables: Dict[str, List[AnalysisSampleRow]] = Field(default_factory=dict)

    class Config:
        extra = "forbid"


def _json_error(message: str, status_code: int = status.HTTP_400_BAD_REQUEST) -> HTTPException:
    """
    功能:
        创建中文错误响应.
    参数:
        message: str, 错误信息.
        status_code: int, HTTP 状态码.
    返回:
        HTTPException, FastAPI 异常.
    """
    return HTTPException(status_code=status_code, detail=message)


def _job_response(job_id: str, run_id: str, saved_files: Dict[str, str], skipped: List[str]) -> JsonDict:
    """
    功能:
        生成分析提交后台任务响应.
    参数:
        job_id: str, 后台任务 ID.
        run_id: str, 本次手工提交运行 ID.
        saved_files: Dict[str, str], 已保存 CSV 文件.
        skipped: List[str], 无有效行而跳过的仪器.
    返回:
        Dict[str, Any], 响应体.
    """
    return {
        "job_id": job_id,
        "status": "queued",
        "run_id": run_id,
        "saved_files": saved_files,
        "skipped": skipped,
    }


@router.get("/status")
def get_analysis_status(
    controller: AnalysisStationController = Depends(get_analysis_controller),
) -> JsonDict:
    """
    功能:
        查询 GC-MS, UPLC_QTOF, HPLC 三台分析仪器当前连接状态.
    返回:
        Dict[str, Any], 包含三台仪器的状态列表.
    """
    statuses: List[JsonDict] = []
    for config in _get_device_configs(controller):
        statuses.append(_read_device_status(config))
    return {"items": statuses}


@router.post("/submit")
def submit_analysis_tables(
    payload: AnalysisSubmitRequest = Body(...),
    controller: AnalysisStationController = Depends(get_analysis_controller),
) -> JsonDict:
    """
    功能:
        校验并保存三台分析仪器的手工 CSV 表格, 再创建后台任务提交到仪器.
    参数:
        payload: AnalysisSubmitRequest, 前端传入的分析样品表.
        controller: AnalysisStationController, 分析工站控制器.
    返回:
        Dict[str, Any], 后台任务信息.
    """
    unknown_instruments = sorted(set(payload.tables.keys()) - set(INSTRUMENT_ORDER))
    if len(unknown_instruments) > 0:
        allowed_text = ", ".join(INSTRUMENT_ORDER)
        unknown_text = ", ".join(unknown_instruments)
        raise _json_error(f"分析仪器参数无效: {unknown_text}. 可选值: {allowed_text}.")

    try:
        normalized_tables, skipped = _validate_tables(payload.tables)
    except ValueError as exc:
        raise _json_error(str(exc)) from exc
    if len(normalized_tables) == 0:
        raise _json_error("至少需要填写一台分析仪器的有效样品行.")
    if job_manager.is_busy() is True:
        raise _json_error("当前已有后台任务正在运行, 请稍后再提交.", status.HTTP_409_CONFLICT)

    run_id, saved_files = _save_tables(controller, normalized_tables)

    def _target(log: Callable[[str], None]) -> JsonDict:
        return _submit_saved_files(controller, saved_files, skipped, log)

    try:
        job = job_manager.start_exclusive("提交分析任务", _target)
    except JobBusyError as exc:
        raise _json_error(str(exc), status.HTTP_409_CONFLICT) from exc

    return _job_response(job.job_id, run_id, {key: str(path) for key, path in saved_files.items()}, skipped)


def _get_device_configs(controller: AnalysisStationController) -> List[JsonDict]:
    """
    功能:
        从分析站配置汇总三台仪器连接参数.
    参数:
        controller: AnalysisStationController, 分析工站控制器.
    返回:
        List[Dict[str, Any]], 仪器配置列表.
    """
    settings = controller._settings
    return [
        {
            "instrument": "gc_ms",
            "name": INSTRUMENT_NAMES["gc_ms"],
            "host": settings.gc_ms_host,
            "port": settings.gc_ms_port,
            "timeout": settings.gc_ms_timeout,
        },
        {
            "instrument": "uplc_qtof",
            "name": INSTRUMENT_NAMES["uplc_qtof"],
            "host": settings.uplc_qtof_host,
            "port": settings.uplc_qtof_port,
            "timeout": settings.uplc_qtof_timeout,
        },
        {
            "instrument": "hplc",
            "name": INSTRUMENT_NAMES["hplc"],
            "host": settings.hplc_host,
            "port": settings.hplc_port,
            "timeout": settings.hplc_timeout,
        },
    ]


def _read_device_status(config: JsonDict) -> JsonDict:
    """
    功能:
        调用单台分析仪器的 get_status 接口并整理连接状态.
    参数:
        config: Dict[str, Any], 仪器连接配置.
    返回:
        Dict[str, Any], 仪器状态.
    """
    client = ZhidaClient(
        host=str(config["host"]),
        port=int(config["port"]),
        timeout=float(config["timeout"]),
    )
    error_message = ""
    try:
        status_text = client.get_status()
    except Exception as exc:
        logger.exception("分析仪器状态查询失败, instrument=%s", config["instrument"])
        status_text = "Error"
        error_message = str(exc)
    finally:
        client.close()

    normalized_status = str(status_text or "").strip()
    connected = normalized_status.lower() not in OFFLINE_STATUSES
    result: JsonDict = {
        "instrument": config["instrument"],
        "name": config["name"],
        "host": config["host"],
        "port": config["port"],
        "status": normalized_status,
        "connected": connected,
    }
    if error_message != "":
        result["error"] = error_message
    return result


def _validate_tables(
    tables: Dict[str, List[AnalysisSampleRow]],
) -> tuple[Dict[str, List[List[str]]], List[str]]:
    """
    功能:
        校验三台仪器样品表并转换为 CSV 行数据.
    参数:
        tables: Dict[str, List[AnalysisSampleRow]], 原始样品表.
    返回:
        tuple[Dict[str, List[List[str]]], List[str]], 有效行和跳过仪器.
    """
    normalized_tables: Dict[str, List[List[str]]] = {}
    skipped: List[str] = []

    for instrument in INSTRUMENT_ORDER:
        rows = tables.get(instrument, [])
        normalized_rows = _validate_instrument_rows(instrument, rows)
        if len(normalized_rows) == 0:
            skipped.append(instrument)
            continue
        normalized_tables[instrument] = normalized_rows

    return normalized_tables, skipped


def _validate_instrument_rows(instrument: str, rows: List[AnalysisSampleRow]) -> List[List[str]]:
    """
    功能:
        校验单台仪器样品表, 跳过全空行并拒绝不完整非空行.
    参数:
        instrument: str, 仪器 key.
        rows: List[AnalysisSampleRow], 原始样品行.
    返回:
        List[List[str]], 可写入 CSV 的有效行.
    """
    normalized_rows: List[List[str]] = []
    for row_index, row in enumerate(rows, start=1):
        if _is_empty_row(row) is True:
            continue
        normalized_rows.append(_validate_row(instrument, row_index, row))
    return normalized_rows


def _is_empty_row(row: AnalysisSampleRow) -> bool:
    """
    功能:
        判断样品行是否为全空行.
    参数:
        row: AnalysisSampleRow, 样品行.
    返回:
        bool, True 表示全空.
    """
    for header in CSV_HEADERS:
        if _is_empty_value(getattr(row, header)) is False:
            return False
    return True


def _validate_row(instrument: str, row_index: int, row: AnalysisSampleRow) -> List[str]:
    """
    功能:
        校验单行样品数据并按 CSV 表头顺序返回文本值.
    参数:
        instrument: str, 仪器 key.
        row_index: int, 行号.
        row: AnalysisSampleRow, 样品行.
    返回:
        List[str], CSV 行值.
    """
    instrument_name = INSTRUMENT_NAMES[instrument]
    raw_values: Dict[str, Any] = {}
    values: Dict[str, str] = {}
    for header in CSV_HEADERS:
        value = getattr(row, header)
        if _is_empty_value(value) is True:
            raise ValueError(f"{instrument_name} 第 {row_index} 行 {header} 不能为空.")
        raw_values[header] = value
        values[header] = _to_text(value)

    rack_code = values["RackCode"]
    if rack_code not in ALLOWED_RACK_CODES:
        raise ValueError(f"{instrument_name} 第 {row_index} 行 RackCode 无效, 仅支持 Rack 1 到 Rack 6.")

    values["VialPos"] = _normalize_positive_int(raw_values["VialPos"], instrument_name, row_index)
    values["SmplInjVol"] = _normalize_nonnegative_number(raw_values["SmplInjVol"], instrument_name, row_index)
    return [values[header] for header in CSV_HEADERS]


def _is_empty_value(value: Any) -> bool:
    """
    功能:
        判断单元格是否为空.
    参数:
        value: Any, 单元格值.
    返回:
        bool, True 表示空值.
    """
    if value is None:
        return True
    return str(value).strip() == ""


def _to_text(value: Any) -> str:
    """
    功能:
        将单元格值转换为去除首尾空格的文本.
    参数:
        value: Any, 单元格值.
    返回:
        str, 文本值.
    """
    return str(value).strip()


def _normalize_positive_int(value: Any, instrument_name: str, row_index: int) -> str:
    """
    功能:
        校验并规范化 VialPos 正整数.
    参数:
        value: Any, 原始 VialPos.
        instrument_name: str, 仪器显示名.
        row_index: int, 行号.
    返回:
        str, 规范化后的整数文本.
    """
    if isinstance(value, bool):
        raise ValueError(f"{instrument_name} 第 {row_index} 行 VialPos 必须为正整数.")
    if isinstance(value, int):
        if value <= 0:
            raise ValueError(f"{instrument_name} 第 {row_index} 行 VialPos 必须为正整数.")
        return str(value)
    if isinstance(value, float) and value.is_integer() is True:
        number = int(value)
        if number <= 0:
            raise ValueError(f"{instrument_name} 第 {row_index} 行 VialPos 必须为正整数.")
        return str(number)

    text = _to_text(value)
    if text.isdigit() is False:
        raise ValueError(f"{instrument_name} 第 {row_index} 行 VialPos 必须为正整数.")
    number = int(text)
    if number <= 0:
        raise ValueError(f"{instrument_name} 第 {row_index} 行 VialPos 必须为正整数.")
    return str(number)


def _normalize_nonnegative_number(value: Any, instrument_name: str, row_index: int) -> str:
    """
    功能:
        校验并规范化 SmplInjVol 非负数字.
    参数:
        value: Any, 原始 SmplInjVol.
        instrument_name: str, 仪器显示名.
        row_index: int, 行号.
    返回:
        str, 规范化后的数字文本.
    """
    text = _to_text(value)
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{instrument_name} 第 {row_index} 行 SmplInjVol 必须为非负数字.") from exc

    if number.is_finite() is False or number < 0:
        raise ValueError(f"{instrument_name} 第 {row_index} 行 SmplInjVol 必须为非负数字.")
    return text


def _save_tables(
    controller: AnalysisStationController,
    tables: Dict[str, List[List[str]]],
) -> tuple[str, Dict[str, Path]]:
    """
    功能:
        将有效样品表保存到分析站手工提交目录.
    参数:
        controller: AnalysisStationController, 分析工站控制器.
        tables: Dict[str, List[List[str]]], 已校验 CSV 行.
    返回:
        tuple[str, Dict[str, Path]], run_id 和保存路径.
    """
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    run_dir = controller._settings.data_dir / "web_manual" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    saved_files: Dict[str, Path] = {}

    for instrument in INSTRUMENT_ORDER:
        rows = tables.get(instrument)
        if rows is None:
            continue
        csv_path = run_dir / f"{instrument}.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as file_obj:
            writer = csv.writer(file_obj, lineterminator="\n")
            writer.writerow(CSV_HEADERS)
            writer.writerows(rows)
        logger.info("分析仪器手工 CSV 已保存: instrument=%s, path=%s", instrument, csv_path)
        saved_files[instrument] = csv_path

    return run_id, saved_files


def _submit_saved_files(
    controller: AnalysisStationController,
    saved_files: Dict[str, Path],
    skipped: List[str],
    log: Callable[[str], None],
) -> JsonDict:
    """
    功能:
        按固定顺序提交已保存 CSV 到三台分析仪器.
    参数:
        controller: AnalysisStationController, 分析工站控制器.
        saved_files: Dict[str, Path], 已保存 CSV 路径.
        skipped: List[str], 跳过仪器列表.
        log: Callable, 后台任务日志函数.
    返回:
        Dict[str, Any], 提交结果.
    """
    results: JsonDict = {}
    failed_instruments: List[str] = []

    for instrument in INSTRUMENT_ORDER:
        instrument_name = INSTRUMENT_NAMES[instrument]
        csv_path = saved_files.get(instrument)
        if csv_path is None:
            if instrument in skipped:
                log(f"{instrument_name} 未填写有效样品行, 已跳过.")
            continue

        log(f"{instrument_name} CSV 已保存: {csv_path}")
        log(f"正在提交 {instrument_name} 分析任务.")
        result = controller.submit_by_csv_path(instrument, str(csv_path))
        results[instrument] = result
        log(f"{instrument_name} 提交结果: {result}")

        if isinstance(result, dict) is False or result.get("success") is not True:
            failed_instruments.append(instrument_name)

    if len(failed_instruments) > 0:
        failed_text = ", ".join(failed_instruments)
        raise RuntimeError(f"分析任务提交失败: {failed_text}")

    return {
        "success": True,
        "results": results,
        "skipped": skipped,
    }
