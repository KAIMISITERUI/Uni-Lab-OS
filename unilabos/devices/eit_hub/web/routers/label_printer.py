# -*- coding: utf-8 -*-
"""
功能:
    提供 EIT Hub 标签打印机 Web API.
    负责标签规格模板的读取, 保存, 另存为, 以及按二维表格内容提交打印任务.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any, Callable, Dict, List

import yaml
from fastapi import APIRouter, Body, HTTPException, status
from pydantic import BaseModel

import unilabos.devices.eit_label_printer as label_printer_package
from unilabos.devices.eit_label_printer.driver import LabelPrintService

from ..jobs import JobBusyError, job_manager

logger = logging.getLogger("EITHubLabelPrinterRouter")

JsonDict = Dict[str, Any]

router = APIRouter(prefix="/api/label-printer", tags=["label-printer"])

PROFILE_ROOT = Path(label_printer_package.__file__).resolve().parent / "profiles"
PROFILE_SUFFIXES = {".yaml", ".yml"}
VALID_ROTATIONS = {0, 90, 180, 270}
VALID_BINARY_FLAGS = {0, 1}
VALID_DIRECTIONS = {0, 1}


class LabelProfilePayload(BaseModel):
    """
    功能:
        承载标签模板保存请求.
    参数:
        config: Dict[str, Any], 标签规格配置.
    返回:
        LabelProfilePayload.
    """

    config: JsonDict

    class Config:
        extra = "forbid"


class LabelProfileSaveAsRequest(BaseModel):
    """
    功能:
        承载标签模板另存为请求.
    参数:
        name: str, 新模板文件名, 必须为 .yaml 或 .yml.
        config: Dict[str, Any], 标签规格配置.
    返回:
        LabelProfileSaveAsRequest.
    """

    name: str
    config: JsonDict

    class Config:
        extra = "forbid"


class LabelPrintRequest(BaseModel):
    """
    功能:
        承载标签打印请求.
    参数:
        profile: str, 使用的模板文件名.
        rows: List[List[Any]], 二维表格内容, 每行对应一次标签纸打印.
    返回:
        LabelPrintRequest.
    """

    profile: str
    rows: List[List[Any]]

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


@router.get("/profiles")
def list_profiles() -> JsonDict:
    """
    功能:
        列出标签打印 profiles 目录下的 YAML 模板文件.
    返回:
        Dict[str, Any], 包含 items 列表.
    """
    profile_root = _get_profile_root()
    items: List[JsonDict] = []
    for profile_path in sorted(profile_root.iterdir(), key=lambda item: item.name.lower()):
        if profile_path.is_file() is False:
            continue
        if profile_path.suffix.lower() not in PROFILE_SUFFIXES:
            continue
        items.append(
            {
                "name": profile_path.name,
                "stem": profile_path.stem,
                "path": str(profile_path),
            }
        )
    return {"items": items}


@router.get("/profiles/{name}")
def get_profile(name: str) -> JsonDict:
    """
    功能:
        读取指定标签模板并返回结构化配置.
    参数:
        name: str, 模板文件名.
    返回:
        Dict[str, Any], 包含 name, path, config, columns.
    """
    profile_path = _resolve_existing_profile_path(name)
    return _read_profile_response(profile_path)


@router.put("/profiles/{name}")
def save_profile(name: str, payload: LabelProfilePayload = Body(...)) -> JsonDict:
    """
    功能:
        保存指定标签模板配置.
    参数:
        name: str, 模板文件名.
        payload: LabelProfilePayload, 标签配置.
    返回:
        Dict[str, Any], 保存后的模板结构.
    """
    profile_path = _resolve_existing_profile_path(name)
    config = _validate_profile_config(payload.config)
    _write_profile_config(profile_path, config)
    logger.info("标签模板已保存: %s", profile_path)
    return _read_profile_response(profile_path)


@router.post("/profiles")
def save_profile_as(payload: LabelProfileSaveAsRequest = Body(...)) -> JsonDict:
    """
    功能:
        将标签模板配置另存为新 YAML 文件.
    参数:
        payload: LabelProfileSaveAsRequest, 新文件名和配置.
    返回:
        Dict[str, Any], 新模板结构.
    """
    profile_path = _resolve_new_profile_path(payload.name)
    config = _validate_profile_config(payload.config)
    _write_profile_config(profile_path, config)
    logger.info("标签模板已另存为: %s", profile_path)
    return _read_profile_response(profile_path)


@router.post("/print")
def print_labels(request: LabelPrintRequest = Body(...)) -> JsonDict:
    """
    功能:
        创建标签打印后台任务.
    参数:
        request: LabelPrintRequest, 模板文件名和二维表格内容.
    返回:
        Dict[str, Any], 后台任务 ID.
    """
    profile_path = _resolve_existing_profile_path(request.profile)
    config = _load_profile_config(profile_path)
    columns = _read_columns(config)
    normalized_rows, skipped_rows = _normalize_print_rows(request.rows, columns)
    if len(normalized_rows) == 0:
        raise _json_error("没有可打印的标签内容.")

    def _target(log: Callable[[str], None]) -> JsonDict:
        return _run_print_job(profile_path, normalized_rows, skipped_rows, log)

    return _start_job("打印标签", _target)


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> JsonDict:
    """
    功能:
        查询标签打印后台任务状态.
    参数:
        job_id: str, 后台任务 ID.
    返回:
        Dict[str, Any], 后台任务状态.
    """
    job = job_manager.get(job_id)
    if job is None:
        raise _json_error(f"未找到后台任务: {job_id}", status.HTTP_404_NOT_FOUND)
    return job.to_dict()


def _start_job(name: str, target: Callable[[Callable[[str], None]], Any]) -> JsonDict:
    """
    功能:
        创建独占后台任务并返回任务 ID.
    参数:
        name: str, 任务名称.
        target: Callable, 任务函数.
    返回:
        Dict[str, Any], 后台任务响应.
    """
    try:
        job = job_manager.start_exclusive(name, target)
    except JobBusyError as exc:
        raise _json_error(str(exc), status.HTTP_409_CONFLICT) from exc
    return {
        "job_id": job.job_id,
        "status": "queued",
    }


def _get_profile_root() -> Path:
    """
    功能:
        返回标签模板根目录, 并确认目录存在.
    返回:
        Path, profiles 目录绝对路径.
    """
    profile_root = Path(PROFILE_ROOT).resolve()
    if profile_root.is_dir() is False:
        raise _json_error(f"标签模板目录不存在: {profile_root}", status.HTTP_500_INTERNAL_SERVER_ERROR)
    return profile_root


def _resolve_existing_profile_path(name: str) -> Path:
    """
    功能:
        将模板文件名解析为 profiles 目录内已存在的文件路径.
    参数:
        name: str, 模板文件名.
    返回:
        Path, 已存在模板路径.
    """
    profile_path = _resolve_profile_path(name)
    if profile_path.is_file() is False:
        raise _json_error(f"未找到标签模板: {name}", status.HTTP_404_NOT_FOUND)
    return profile_path


def _resolve_new_profile_path(name: str) -> Path:
    """
    功能:
        将新模板文件名解析为 profiles 目录内尚不存在的文件路径.
    参数:
        name: str, 新模板文件名.
    返回:
        Path, 新模板路径.
    """
    profile_path = _resolve_profile_path(name)
    if profile_path.exists() is True:
        raise _json_error(f"标签模板已存在: {profile_path.name}")
    return profile_path


def _resolve_profile_path(name: str) -> Path:
    """
    功能:
        校验模板文件名并限制路径只能落在 profiles 目录内.
    参数:
        name: str, 模板文件名.
    返回:
        Path, profiles 目录内的模板路径.
    """
    profile_root = _get_profile_root()
    profile_name = str(name).strip()
    if profile_name == "":
        raise _json_error("模板文件名不能为空.")
    if Path(profile_name).name != profile_name:
        raise _json_error("模板文件名不能包含路径.")
    if Path(profile_name).suffix.lower() not in PROFILE_SUFFIXES:
        raise _json_error("模板文件必须以 .yaml 或 .yml 结尾.")

    profile_path = (profile_root / profile_name).resolve()
    if profile_path.parent != profile_root:
        raise _json_error("模板路径必须位于标签模板目录内.")
    return profile_path


def _read_profile_response(profile_path: Path) -> JsonDict:
    """
    功能:
        读取模板配置并构造前端响应.
    参数:
        profile_path: Path, 模板文件路径.
    返回:
        Dict[str, Any], 模板响应结构.
    """
    config = _load_profile_config(profile_path)
    columns = _read_columns(config)
    return {
        "name": profile_path.name,
        "path": str(profile_path),
        "config": config,
        "columns": columns,
    }


def _load_profile_config(profile_path: Path) -> JsonDict:
    """
    功能:
        从 YAML 文件读取并校验标签模板配置.
    参数:
        profile_path: Path, 模板文件路径.
    返回:
        Dict[str, Any], 已校验配置.
    """
    try:
        with profile_path.open("r", encoding="utf-8") as file_obj:
            raw_config = yaml.safe_load(file_obj)
    except yaml.YAMLError as exc:
        logger.exception("读取标签模板 YAML 失败: %s", profile_path)
        raise _json_error(f"标签模板 YAML 格式错误: {exc}") from exc
    except OSError as exc:
        logger.exception("读取标签模板失败: %s", profile_path)
        raise _json_error(f"读取标签模板失败: {exc}", status.HTTP_500_INTERNAL_SERVER_ERROR) from exc
    return _validate_profile_config(raw_config)


def _write_profile_config(profile_path: Path, config: JsonDict) -> None:
    """
    功能:
        将标签模板配置写入 YAML 文件.
    参数:
        profile_path: Path, 模板文件路径.
        config: Dict[str, Any], 已校验配置.
    返回:
        None.
    """
    try:
        with profile_path.open("w", encoding="utf-8") as file_obj:
            yaml.safe_dump(config, file_obj, allow_unicode=True, sort_keys=False, default_flow_style=False)
    except OSError as exc:
        logger.exception("保存标签模板失败: %s", profile_path)
        raise _json_error(f"保存标签模板失败: {exc}", status.HTTP_500_INTERNAL_SERVER_ERROR) from exc


def _validate_profile_config(raw_config: Any) -> JsonDict:
    """
    功能:
        校验标签模板配置, 确保纸张, 字体和位置参数可用于打印.
    参数:
        raw_config: Any, 原始配置.
    返回:
        Dict[str, Any], 规范化后的配置.
    """
    if isinstance(raw_config, dict) is False:
        raise _json_error("标签模板配置必须是对象.")

    printer = _require_section(raw_config, "printer")
    paper = _require_section(raw_config, "paper")
    font = _require_section(raw_config, "font")
    position = _require_section(raw_config, "position")

    config: JsonDict = {
        "printer": {
            "ppi": _read_positive_int(printer, "ppi", "printer.ppi"),
        },
        "paper": {
            "width": _read_positive_number(paper, "width", "paper.width"),
            "height": _read_positive_number(paper, "height", "paper.height"),
            "unit": _read_unit(paper),
            "columns": _read_positive_int(paper, "columns", "paper.columns"),
            "column_gap": _read_nonnegative_number(paper, "column_gap", "paper.column_gap"),
            "margin": _read_nonnegative_number(paper, "margin", "paper.margin"),
            "gap": _read_nonnegative_number(paper, "gap", "paper.gap"),
            "gap_offset": _read_finite_number(paper, "gap_offset", "paper.gap_offset"),
            "direction": _read_allowed_int(paper, "direction", "paper.direction", VALID_DIRECTIONS),
        },
        "font": {
            "name": _read_nonempty_text(font, "name", "font.name"),
            "size": _read_positive_int(font, "size", "font.size"),
            "bold": _read_allowed_int(font, "bold", "font.bold", VALID_BINARY_FLAGS),
            "underline": _read_allowed_int(font, "underline", "font.underline", VALID_BINARY_FLAGS),
            "rotation": _read_allowed_int(font, "rotation", "font.rotation", VALID_ROTATIONS),
        },
        "position": {
            "x": _read_finite_number(position, "x", "position.x"),
            "y": _read_finite_number(position, "y", "position.y"),
        },
    }
    _validate_label_width(config["paper"])
    return config


def _require_section(config: JsonDict, section_name: str) -> JsonDict:
    """
    功能:
        从模板配置中读取必需分组.
    参数:
        config: Dict[str, Any], 模板配置.
        section_name: str, 分组名称.
    返回:
        Dict[str, Any], 分组配置.
    """
    section = config.get(section_name)
    if isinstance(section, dict) is False:
        raise _json_error(f"标签模板缺少 {section_name} 配置.")
    return section


def _read_unit(paper: JsonDict) -> str:
    """
    功能:
        读取并校验纸张单位, 当前页面固定使用 mm.
    参数:
        paper: Dict[str, Any], paper 分组.
    返回:
        str, 单位.
    """
    unit = str(paper.get("unit", "")).strip()
    if unit != "mm":
        raise _json_error("paper.unit 必须是 mm.")
    return unit


def _read_nonempty_text(section: JsonDict, key: str, label: str) -> str:
    """
    功能:
        读取非空文本字段.
    参数:
        section: Dict[str, Any], 配置分组.
        key: str, 字段名.
        label: str, 页面错误提示字段名.
    返回:
        str, 文本值.
    """
    text = str(section.get(key, "")).strip()
    if text == "":
        raise _json_error(f"{label} 不能为空.")
    return text


def _read_positive_number(section: JsonDict, key: str, label: str) -> float:
    """
    功能:
        读取正数配置字段.
    参数:
        section: Dict[str, Any], 配置分组.
        key: str, 字段名.
        label: str, 页面错误提示字段名.
    返回:
        float, 数值.
    """
    value = _read_finite_number(section, key, label)
    if value <= 0:
        raise _json_error(f"{label} 必须大于 0.")
    return value


def _read_nonnegative_number(section: JsonDict, key: str, label: str) -> float:
    """
    功能:
        读取非负数配置字段.
    参数:
        section: Dict[str, Any], 配置分组.
        key: str, 字段名.
        label: str, 页面错误提示字段名.
    返回:
        float, 数值.
    """
    value = _read_finite_number(section, key, label)
    if value < 0:
        raise _json_error(f"{label} 不能小于 0.")
    return value


def _read_finite_number(section: JsonDict, key: str, label: str) -> float:
    """
    功能:
        读取有限数字配置字段.
    参数:
        section: Dict[str, Any], 配置分组.
        key: str, 字段名.
        label: str, 页面错误提示字段名.
    返回:
        float, 数值.
    """
    if key not in section:
        raise _json_error(f"{label} 不能为空.")
    raw_value = section[key]
    if isinstance(raw_value, bool):
        raise _json_error(f"{label} 必须是数字.")
    try:
        value = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise _json_error(f"{label} 必须是数字.") from exc
    if math.isfinite(value) is False:
        raise _json_error(f"{label} 必须是有限数字.")
    return value


def _read_positive_int(section: JsonDict, key: str, label: str) -> int:
    """
    功能:
        读取正整数配置字段.
    参数:
        section: Dict[str, Any], 配置分组.
        key: str, 字段名.
        label: str, 页面错误提示字段名.
    返回:
        int, 整数值.
    """
    value = _read_int(section, key, label)
    if value <= 0:
        raise _json_error(f"{label} 必须大于 0.")
    return value


def _read_allowed_int(section: JsonDict, key: str, label: str, allowed_values: set[int]) -> int:
    """
    功能:
        读取并校验枚举整数配置字段.
    参数:
        section: Dict[str, Any], 配置分组.
        key: str, 字段名.
        label: str, 页面错误提示字段名.
        allowed_values: set[int], 允许值集合.
    返回:
        int, 整数值.
    """
    value = _read_int(section, key, label)
    if value not in allowed_values:
        allowed_text = ", ".join(str(item) for item in sorted(allowed_values))
        raise _json_error(f"{label} 必须是以下值之一: {allowed_text}.")
    return value


def _read_int(section: JsonDict, key: str, label: str) -> int:
    """
    功能:
        读取整数配置字段.
    参数:
        section: Dict[str, Any], 配置分组.
        key: str, 字段名.
        label: str, 页面错误提示字段名.
    返回:
        int, 整数值.
    """
    value = _read_finite_number(section, key, label)
    if value.is_integer() is False:
        raise _json_error(f"{label} 必须是整数.")
    return int(value)


def _validate_label_width(paper: JsonDict) -> None:
    """
    功能:
        校验纸张宽度, 边距, 列间距和列数能形成正标签宽度.
    参数:
        paper: Dict[str, Any], paper 分组.
    返回:
        None.
    """
    width = float(paper["width"])
    margin = float(paper["margin"])
    columns = int(paper["columns"])
    column_gap = float(paper["column_gap"])
    label_width = (width - margin * 2 - column_gap * (columns - 1)) / columns
    if label_width <= 0:
        raise _json_error("纸张宽度, 边距, 列间距和列数无法形成有效标签宽度.")


def _read_columns(config: JsonDict) -> int:
    """
    功能:
        从已校验配置中读取标签列数.
    参数:
        config: Dict[str, Any], 标签模板配置.
    返回:
        int, 标签列数.
    """
    paper = config["paper"]
    return int(paper["columns"])


def _normalize_print_rows(rows: List[List[Any]], columns: int) -> tuple[List[List[str]], int]:
    """
    功能:
        将前端二维表格规范化为打印行, 跳过全空行.
    参数:
        rows: List[List[Any]], 原始二维表格.
        columns: int, 模板列数.
    返回:
        tuple[List[List[str]], int], 打印行和跳过空行数.
    """
    normalized_rows: List[List[str]] = []
    skipped_rows = 0
    for raw_row in rows:
        row_values: List[str] = []
        for column_index in range(columns):
            value = raw_row[column_index] if column_index < len(raw_row) else ""
            row_values.append(_to_cell_text(value))
        if _is_empty_print_row(row_values) is True:
            skipped_rows += 1
            continue
        normalized_rows.append(row_values)
    return normalized_rows, skipped_rows


def _to_cell_text(value: Any) -> str:
    """
    功能:
        将单元格内容转换为打印文本.
    参数:
        value: Any, 单元格内容.
    返回:
        str, 去除首尾空白后的文本.
    """
    if value is None:
        return ""
    return str(value).strip()


def _is_empty_print_row(row_values: List[str]) -> bool:
    """
    功能:
        判断一行标签内容是否全空.
    参数:
        row_values: List[str], 已规范化行内容.
    返回:
        bool, True 表示全空.
    """
    for value in row_values:
        if value != "":
            return False
    return True


def _run_print_job(
    profile_path: Path,
    rows: List[List[str]],
    skipped_rows: int,
    log: Callable[[str], None],
) -> JsonDict:
    """
    功能:
        执行标签打印后台任务.
    参数:
        profile_path: Path, 模板文件路径.
        rows: List[List[str]], 已规范化打印行.
        skipped_rows: int, 已跳过空行数.
        log: Callable, 后台任务日志函数.
    返回:
        Dict[str, Any], 打印结果.
    """
    log(f"正在使用标签模板: {profile_path.name}.")
    service = LabelPrintService(config_path=str(profile_path))
    printed_rows = 0
    try:
        if service.connect() is not True:
            raise RuntimeError("标签打印机连接失败.")
        for row_index, row_values in enumerate(rows, start=1):
            log(f"正在打印第 {row_index} 行: {' | '.join(row_values)}.")
            if service.print_label(row_values) is not True:
                raise RuntimeError(f"第 {row_index} 行标签打印失败.")
            printed_rows += 1
    finally:
        service.disconnect()
    log(f"标签打印完成, 已打印 {printed_rows} 行, 跳过空行 {skipped_rows} 行.")
    return {
        "profile": profile_path.name,
        "profile_path": str(profile_path),
        "printed_rows": printed_rows,
        "skipped_rows": skipped_rows,
    }
