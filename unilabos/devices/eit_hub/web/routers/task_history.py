# -*- coding: utf-8 -*-
"""
功能:
    提供 EIT Hub 任务历史数据 Web API.
    扫描合成站任务目录, 检查核心文件和分析报告是否存在, 解析 xlsx/csv 内容预览,
    并代理分析站图集 (色谱图, 质谱峰图, 结构图) 的访问.
"""

from __future__ import annotations

import csv
import datetime as _dt
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse
from openpyxl import load_workbook
from pydantic import BaseModel

from ..excel_codec import read_reaction_template
from .synthesis import DEFAULT_HISTORY_TASKS_DIR

try:
    from unilabos.devices.eit_analysis_station.config.setting import (
        Settings as AnalysisSettings,
    )
    _ANALYSIS_DATA_DIR_DEFAULT = AnalysisSettings().data_dir
except Exception as _exc:  # 防止分析站配置加载失败影响 hub 启动
    logging.getLogger("EITHubTaskHistoryRouter").warning(
        "加载分析站配置失败, 将禁用图集端点: %s", _exc
    )
    _ANALYSIS_DATA_DIR_DEFAULT = Path(__file__).resolve().parent.parent.parent.parent / "eit_analysis_station" / "data"

logger = logging.getLogger("EITHubTaskHistoryRouter")

JsonDict = Dict[str, Any]

router = APIRouter(prefix="/api/task-history", tags=["task-history"])

# 分析站数据根, 测试可通过 monkeypatch 替换
ANALYSIS_DATA_DIR: Path = Path(_ANALYSIS_DATA_DIR_DEFAULT)

# 5 项合成任务核心文件检查规范, filename 中 {task_id} 会被替换
EXPECTED_TASK_FILES: Tuple[Tuple[str, str, str], ...] = (
    ("experiment_plan", "实验计划", "{task_id}_experiment_plan.xlsx"),
    ("task_report",     "任务报告", "{task_id}_task_report.xlsx"),
    ("gc_ms",           "GC-MS 方法配置", "gc_ms.csv"),
    ("uplc_qtof",       "UPLC-QTOF 方法配置", "uplc_qtof.csv"),
    ("hplc",            "HPLC 方法配置", "hplc.csv"),
)
ANALYSIS_REPORT_FILES: Tuple[Tuple[str, str, str], ...] = (
    ("yield_report", "产率报告", "yield_report"),
)
EXPECTED_FILE_KEYS = {
    key
    for key, _label, _name in (*EXPECTED_TASK_FILES, *ANALYSIS_REPORT_FILES)
}
XLSX_FILE_KEYS = {"experiment_plan", "task_report"}
CSV_FILE_KEYS = {"gc_ms", "uplc_qtof", "hplc"}

# 图集子目录白名单
IMAGE_GROUPS: Tuple[Tuple[str, str], ...] = (
    ("plots", "色谱图"),
    ("structures", "结构图"),
    ("ms_plots", "质谱图"),
)
IMAGE_GROUP_NAMES = {name for name, _label in IMAGE_GROUPS}
IMAGE_LAZY_GROUPS = {"ms_plots"}  # 默认懒加载, 仅返回数量
ALLOWED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

XLSX_PREVIEW_MAX_ROWS = 200
CSV_PREVIEW_MAX_ROWS = 500


class FilePresence(BaseModel):
    """
    功能:
        承载单个核心文件的检查结果.
    参数:
        key: str, 文件键.
        label: str, 中文显示名.
        filename: str, 实际文件名 (含 task_id 替换).
        exists: bool, 文件是否存在.
        size_bytes: int 或 None, 文件大小.
        mtime: str 或 None, 修改时间 (ISO 8601).
    """

    key: str
    label: str
    filename: str
    exists: bool
    size_bytes: Optional[int] = None
    mtime: Optional[str] = None


class TaskHistoryItem(BaseModel):
    """
    功能:
        承载历史任务摘要.
    """

    task_id: int
    task_name: str
    status: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    files: List[FilePresence]


class TaskHistoryListResponse(BaseModel):
    """
    功能:
        承载任务列表响应.
    """

    items: List[TaskHistoryItem]
    total: int


class SheetPreview(BaseModel):
    """
    功能:
        承载 xlsx 单个 sheet 的预览数据.
    """

    sheet_name: str
    headers: List[str]
    rows: List[List[Any]]
    truncated: bool


class XlsxPreview(BaseModel):
    """
    功能:
        承载 xlsx 多 sheet 预览.
    """

    kind: str = "xlsx"
    sheets: List[SheetPreview]


class CsvPreview(BaseModel):
    """
    功能:
        承载 csv 预览.
    """

    kind: str = "csv"
    headers: List[str]
    rows: List[List[str]]
    truncated: bool


class ImageGroupInfo(BaseModel):
    """
    功能:
        承载分析站图集分组信息.
    """

    name: str
    label: str
    count: int
    images: List[str]
    lazy: bool


class TaskHistoryDetailResponse(BaseModel):
    """
    功能:
        承载任务详情响应.
    """

    task: TaskHistoryItem
    image_groups: List[ImageGroupInfo]


class ImageListResponse(BaseModel):
    """
    功能:
        承载图集图片名称列表响应.
    """

    name: str
    label: str
    count: int
    images: List[str]


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


def _format_mtime(timestamp: float) -> str:
    """
    功能:
        将文件 mtime 浮点秒转换为本地时区 ISO 8601 字符串.
    参数:
        timestamp: float, Unix 时间戳.
    返回:
        str, ISO 8601 文本.
    """
    return _dt.datetime.fromtimestamp(timestamp).isoformat(timespec="seconds")


def _build_file_presence(task_dir: Path, task_id: int) -> List[FilePresence]:
    """
    功能:
        计算任务历史卡片需要展示和筛选的文件存在状态.
    参数:
        task_dir: Path, 任务目录.
        task_id: int, 任务 ID.
    返回:
        List[FilePresence], 合成任务文件和分析站报告检查结果.
    """
    presences: List[FilePresence] = []
    for key, label, name_pattern in EXPECTED_TASK_FILES:
        filename = name_pattern.format(task_id=task_id)
        candidate = task_dir / filename
        if candidate.is_file() is True:
            stat_result = candidate.stat()
            presences.append(
                FilePresence(
                    key=key,
                    label=label,
                    filename=filename,
                    exists=True,
                    size_bytes=int(stat_result.st_size),
                    mtime=_format_mtime(stat_result.st_mtime),
                )
            )
        else:
            presences.append(
                FilePresence(
                    key=key,
                    label=label,
                    filename=filename,
                    exists=False,
                    size_bytes=None,
                    mtime=None,
                )
            )
    for key, label, suffix in ANALYSIS_REPORT_FILES:
        filename = f"{task_id}_{suffix}.xlsx"
        candidate = _resolve_analysis_report(task_id, suffix)
        if candidate is not None:
            stat_result = candidate.stat()
            presences.append(
                FilePresence(
                    key=key,
                    label=label,
                    filename=candidate.name,
                    exists=True,
                    size_bytes=int(stat_result.st_size),
                    mtime=_format_mtime(stat_result.st_mtime),
                )
            )
        else:
            presences.append(
                FilePresence(
                    key=key,
                    label=label,
                    filename=filename,
                    exists=False,
                    size_bytes=None,
                    mtime=None,
                )
            )
    return presences


def _read_task_info(task_dir: Path) -> JsonDict:
    """
    功能:
        读取任务目录下 task_info.json, 失败时返回空字典.
    参数:
        task_dir: Path, 任务目录.
    返回:
        Dict[str, Any], 任务元信息.
    """
    info_path = task_dir / "task_info.json"
    if info_path.is_file() is False:
        return {}
    try:
        return json.loads(info_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("解析 task_info.json 失败, task_dir=%s, err=%s", task_dir, exc)
        return {}


def _read_task_name(task_dir: Path, task_id: int) -> str:
    """
    功能:
        从 experiment_plan.xlsx 解析任务名称, 失败时返回空字符串.
    参数:
        task_dir: Path, 任务目录.
        task_id: int, 任务 ID.
    返回:
        str, 任务名称.
    """
    plan_path = task_dir / f"{task_id}_experiment_plan.xlsx"
    if plan_path.is_file() is False:
        return ""
    try:
        template = read_reaction_template(plan_path)
    except Exception as exc:
        logger.debug("读取实验计划失败, task_id=%s, err=%s", task_id, exc)
        return ""
    return str(template.get("params", {}).get("实验名称", "")).strip()


def _build_task_item(task_dir: Path) -> Optional[TaskHistoryItem]:
    """
    功能:
        构造单个任务的摘要项, 任务 ID 非整数时跳过.
    参数:
        task_dir: Path, 任务目录.
    返回:
        Optional[TaskHistoryItem], 摘要项或 None.
    """
    name_text = task_dir.name.strip()
    if name_text == "":
        return None
    try:
        task_id = int(name_text)
    except ValueError:
        return None

    info = _read_task_info(task_dir)
    return TaskHistoryItem(
        task_id=task_id,
        task_name=_read_task_name(task_dir, task_id),
        status=info.get("status"),
        created_at=info.get("created_at"),
        started_at=info.get("started_at"),
        completed_at=info.get("completed_at"),
        files=_build_file_presence(task_dir, task_id),
    )


def _list_task_items(query_text: str) -> List[TaskHistoryItem]:
    """
    功能:
        扫描合成站任务目录, 返回符合搜索条件的任务摘要列表 (按 ID 倒序).
    参数:
        query_text: str, 搜索关键词, 同时匹配任务 ID 与任务名称.
    返回:
        List[TaskHistoryItem], 任务摘要列表.
    """
    tasks_dir = Path(DEFAULT_HISTORY_TASKS_DIR)
    if tasks_dir.is_dir() is False:
        return []

    normalized_query = query_text.strip().lower()
    items: List[TaskHistoryItem] = []
    for child in tasks_dir.iterdir():
        if child.is_dir() is False:
            continue
        item = _build_task_item(child)
        if item is None:
            continue
        if normalized_query != "":
            if (
                normalized_query not in str(item.task_id)
                and normalized_query not in item.task_name.lower()
            ):
                continue
        items.append(item)

    items.sort(key=lambda entry: entry.task_id, reverse=True)
    return items


def _resolve_task_dir(task_id: int) -> Path:
    """
    功能:
        定位指定任务的合成站目录, 不存在时抛 404.
    参数:
        task_id: int, 任务 ID.
    返回:
        Path, 任务目录.
    """
    task_dir = Path(DEFAULT_HISTORY_TASKS_DIR) / str(task_id)
    if task_dir.is_dir() is False:
        raise _json_error(f"未找到任务: {task_id}", status_code=status.HTTP_404_NOT_FOUND)
    return task_dir


def _resolve_file_key(file_key: str) -> Tuple[str, str]:
    """
    功能:
        校验 file_key 并返回对应的中文标签与文件名模板.
    参数:
        file_key: str, 文件键.
    返回:
        Tuple[str, str], (label, filename_pattern).
    """
    for key, label, name_pattern in EXPECTED_TASK_FILES:
        if key == file_key:
            return label, name_pattern
    raise _json_error(f"不支持的文件类型: {file_key}", status_code=status.HTTP_400_BAD_REQUEST)


def _resolve_file_path(task_id: int, file_key: str) -> Path:
    """
    功能:
        定位任务目录下指定 file_key 对应的物理文件, 不存在时抛 404.
    参数:
        task_id: int, 任务 ID.
        file_key: str, 文件键.
    返回:
        Path, 文件路径.
    """
    task_dir = _resolve_task_dir(task_id)
    _label, name_pattern = _resolve_file_key(file_key)
    file_path = task_dir / name_pattern.format(task_id=task_id)
    if file_path.is_file() is False:
        raise _json_error(
            f"任务 {task_id} 下未找到 {file_key} 文件",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return file_path


def _normalize_cell(value: Any) -> Any:
    """
    功能:
        将 openpyxl 单元格值规范化为 JSON 可序列化的形式.
    参数:
        value: Any, 原始单元格值.
    返回:
        Any, 规范化后的值.
    """
    if value is None:
        return ""
    if isinstance(value, _dt.datetime) is True:
        return value.isoformat(timespec="seconds")
    if isinstance(value, _dt.date) is True:
        return value.isoformat()
    return value


def _preview_xlsx(file_path: Path) -> XlsxPreview:
    """
    功能:
        使用 openpyxl 解析 xlsx 文件并返回前 200 行预览.
    参数:
        file_path: Path, 文件路径.
    返回:
        XlsxPreview, 多 sheet 预览.
    """
    try:
        workbook = load_workbook(file_path, read_only=True, data_only=True)
    except Exception as exc:
        logger.warning("解析 xlsx 失败: %s, err=%s", file_path, exc)
        raise _json_error(f"解析 Excel 文件失败: {exc}")

    try:
        sheets: List[SheetPreview] = []
        for worksheet in workbook.worksheets:
            iter_rows = worksheet.iter_rows(values_only=True)
            try:
                header_row = next(iter_rows)
            except StopIteration:
                sheets.append(
                    SheetPreview(sheet_name=worksheet.title, headers=[], rows=[], truncated=False)
                )
                continue

            headers = ["" if cell is None else str(cell) for cell in header_row]
            rows: List[List[Any]] = []
            truncated = False
            for index, raw_row in enumerate(iter_rows):
                if index >= XLSX_PREVIEW_MAX_ROWS:
                    truncated = True
                    break
                rows.append([_normalize_cell(cell) for cell in raw_row])
            sheets.append(
                SheetPreview(
                    sheet_name=worksheet.title,
                    headers=headers,
                    rows=rows,
                    truncated=truncated,
                )
            )
        return XlsxPreview(sheets=sheets)
    finally:
        workbook.close()


def _preview_csv(file_path: Path) -> CsvPreview:
    """
    功能:
        解析 csv 文件并返回预览数据.
    参数:
        file_path: Path, 文件路径.
    返回:
        CsvPreview, csv 预览.
    """
    try:
        text = file_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = file_path.read_text(encoding="gbk", errors="replace")
    except Exception as exc:
        logger.warning("读取 csv 失败: %s, err=%s", file_path, exc)
        raise _json_error(f"读取 CSV 文件失败: {exc}")

    reader = csv.reader(text.splitlines())
    try:
        headers = next(reader)
    except StopIteration:
        return CsvPreview(headers=[], rows=[], truncated=False)

    rows: List[List[str]] = []
    truncated = False
    for index, row in enumerate(reader):
        if index >= CSV_PREVIEW_MAX_ROWS:
            truncated = True
            break
        rows.append(list(row))
    return CsvPreview(headers=list(headers), rows=rows, truncated=truncated)


def _resolve_image_group_dir(task_id: int, group: str) -> Path:
    """
    功能:
        定位分析站任务目录下指定图集子目录的安全路径.
    参数:
        task_id: int, 任务 ID.
        group: str, 图集名称.
    返回:
        Path, 图集目录路径 (可能不存在).
    """
    if group not in IMAGE_GROUP_NAMES:
        raise _json_error(f"不支持的图集类型: {group}", status_code=status.HTTP_400_BAD_REQUEST)

    base_dir = (Path(ANALYSIS_DATA_DIR) / str(task_id) / group).resolve()
    expected_root = (Path(ANALYSIS_DATA_DIR) / str(task_id)).resolve()
    try:
        base_dir.relative_to(expected_root)
    except ValueError:
        raise _json_error("非法图集路径", status_code=status.HTTP_403_FORBIDDEN)
    return base_dir


def _list_image_files(group_dir: Path) -> List[str]:
    """
    功能:
        列出图集目录下所有受支持后缀的图片文件名 (按字典序).
    参数:
        group_dir: Path, 图集目录.
    返回:
        List[str], 图片文件名列表.
    """
    if group_dir.is_dir() is False:
        return []
    files = [
        item.name
        for item in group_dir.iterdir()
        if item.is_file() is True and item.suffix.lower() in ALLOWED_IMAGE_SUFFIXES
    ]
    files.sort()
    return files


def _build_image_groups(task_id: int, lazy_inline_count_only: bool = True) -> List[ImageGroupInfo]:
    """
    功能:
        构造任务详情中的图集分组数据, 默认对懒加载组只返回数量.
    参数:
        task_id: int, 任务 ID.
        lazy_inline_count_only: bool, 懒加载组是否仅返回 count.
    返回:
        List[ImageGroupInfo], 分组列表.
    """
    groups: List[ImageGroupInfo] = []
    for name, label in IMAGE_GROUPS:
        try:
            group_dir = _resolve_image_group_dir(task_id, name)
        except HTTPException:
            continue
        files = _list_image_files(group_dir)
        is_lazy = name in IMAGE_LAZY_GROUPS
        images: List[str] = []
        if not (is_lazy is True and lazy_inline_count_only is True):
            images = files
        groups.append(
            ImageGroupInfo(
                name=name,
                label=label,
                count=len(files),
                images=images,
                lazy=is_lazy,
            )
        )
    return groups


@router.get("/list", response_model=TaskHistoryListResponse)
def list_history(
    query: str = Query(default="", description="按任务 ID 或任务名称模糊搜索"),
) -> TaskHistoryListResponse:
    """
    功能:
        返回历史任务列表, 含合成任务文件和分析报告存在状态.
    参数:
        query: str, 模糊搜索关键词.
    返回:
        TaskHistoryListResponse, 任务列表与总数.
    """
    items = _list_task_items(query)
    return TaskHistoryListResponse(items=items, total=len(items))


@router.get("/{task_id}", response_model=TaskHistoryDetailResponse)
def get_history_detail(task_id: int) -> TaskHistoryDetailResponse:
    """
    功能:
        返回单个任务的详情, 含元数据, 文件状态及分析站图集分组.
    参数:
        task_id: int, 任务 ID.
    返回:
        TaskHistoryDetailResponse, 任务详情.
    """
    task_dir = _resolve_task_dir(task_id)
    item = _build_task_item(task_dir)
    if item is None:
        raise _json_error(f"任务目录不可识别: {task_id}", status_code=status.HTTP_404_NOT_FOUND)
    return TaskHistoryDetailResponse(
        task=item,
        image_groups=_build_image_groups(task_id, lazy_inline_count_only=True),
    )


@router.get("/{task_id}/files/{file_key}/preview")
def preview_file(task_id: int, file_key: str) -> Any:
    """
    功能:
        预览任务目录下指定 file_key 文件 (xlsx 或 csv).
    参数:
        task_id: int, 任务 ID.
        file_key: str, 文件键.
    返回:
        XlsxPreview 或 CsvPreview, 解析结果.
    """
    file_path = _resolve_file_path(task_id, file_key)
    if file_key in XLSX_FILE_KEYS:
        return _preview_xlsx(file_path)
    if file_key in CSV_FILE_KEYS:
        return _preview_csv(file_path)
    raise _json_error(f"不支持的文件类型: {file_key}")


@router.get("/{task_id}/files/{file_key}/download")
def download_file(task_id: int, file_key: str) -> FileResponse:
    """
    功能:
        下载任务目录下指定 file_key 文件原始内容.
    参数:
        task_id: int, 任务 ID.
        file_key: str, 文件键.
    返回:
        FileResponse, 文件下载响应.
    """
    file_path = _resolve_file_path(task_id, file_key)
    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type="application/octet-stream",
    )


@router.get("/{task_id}/images/{group}", response_model=ImageListResponse)
def list_images(task_id: int, group: str) -> ImageListResponse:
    """
    功能:
        列出分析站任务目录下指定图集的图片文件名.
    参数:
        task_id: int, 任务 ID.
        group: str, 图集名称.
    返回:
        ImageListResponse, 图集列表.
    """
    if group not in IMAGE_GROUP_NAMES:
        raise _json_error(f"不支持的图集类型: {group}")
    label = next((item_label for name, item_label in IMAGE_GROUPS if name == group), group)
    group_dir = _resolve_image_group_dir(task_id, group)
    files = _list_image_files(group_dir)
    return ImageListResponse(name=group, label=label, count=len(files), images=files)


@router.get("/{task_id}/images/{group}/{filename}")
def serve_image(task_id: int, group: str, filename: str) -> FileResponse:
    """
    功能:
        返回分析站任务目录下指定图集中的单张图片.
    参数:
        task_id: int, 任务 ID.
        group: str, 图集名称.
        filename: str, 图片文件名.
    返回:
        FileResponse, 图片二进制响应.
    """
    if Path(filename).name != filename:
        raise _json_error("非法文件名", status_code=status.HTTP_403_FORBIDDEN)
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_IMAGE_SUFFIXES:
        raise _json_error(f"不支持的图片类型: {suffix}")

    group_dir = _resolve_image_group_dir(task_id, group)
    candidate = (group_dir / filename).resolve()
    try:
        candidate.relative_to(group_dir.resolve())
    except ValueError:
        raise _json_error("非法图片路径", status_code=status.HTTP_403_FORBIDDEN)

    if candidate.is_file() is False:
        raise _json_error(
            f"未找到图片: {filename}", status_code=status.HTTP_404_NOT_FOUND
        )

    media_type_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    return FileResponse(path=str(candidate), media_type=media_type_map.get(suffix, "image/png"))


# ============================================================================
# 业务视图端点
#   - 实验计划: 复用 read_reaction_template, 前端只读渲染
#   - 任务报告: 解析 step-block xlsx 为 {experiments, steps[].results} 矩阵
#   - 积分报告: 解析 4-sheet xlsx 为 {samples[].peaks[].candidates}
#   - 产率报告: 解析 2-sheet xlsx 为 {config, samples[].results[]}
# ============================================================================


def _resolve_analysis_report(task_id: int, suffix: str) -> Optional[Path]:
    """
    功能:
        定位分析站任务目录下的报告文件 (积分报告或产率报告), 不存在时返回 None.
    参数:
        task_id: int, 任务 ID.
        suffix: str, 文件名后缀, 如 "integration_report" 或 "yield_report".
    返回:
        Optional[Path], 文件路径或 None.
    """
    candidates = [
        Path(ANALYSIS_DATA_DIR) / str(task_id) / f"{task_id}_{suffix}.xlsx",
        Path(DEFAULT_HISTORY_TASKS_DIR) / str(task_id) / f"{task_id}_{suffix}.xlsx",
    ]
    for candidate in candidates:
        if candidate.is_file() is True:
            return candidate
    return None


def _cell_to_value(value: Any) -> Any:
    """
    功能:
        将 openpyxl 单元格值转为 JSON 可序列化形式.
    参数:
        value: Any, 原始单元格值.
    返回:
        Any, 规范化值.
    """
    if value is None:
        return None
    if isinstance(value, _dt.datetime) is True:
        return value.isoformat(timespec="seconds")
    if isinstance(value, _dt.date) is True:
        return value.isoformat()
    return value


def _safe_str(value: Any) -> str:
    """
    功能:
        将单元格值转为去前后空白的字符串, None 返回空串.
    参数:
        value: Any, 原始值.
    返回:
        str, 规范化字符串.
    """
    if value is None:
        return ""
    return str(value).strip()


# ---------------------------------------------------------------------------
# 实验计划
# ---------------------------------------------------------------------------


@router.get("/{task_id}/experiment-plan")
def get_experiment_plan(task_id: int) -> JsonDict:
    """
    功能:
        返回任务实验计划的结构化数据, 复用 read_reaction_template 解析逻辑.
    参数:
        task_id: int, 任务 ID.
    返回:
        Dict[str, Any], 实验计划数据 (含 params, headers, rows 等).
    """
    file_path = _resolve_file_path(task_id, "experiment_plan")
    try:
        template = read_reaction_template(file_path)
    except Exception as exc:
        logger.warning("解析实验计划失败, task_id=%s, err=%s", task_id, exc)
        raise _json_error(f"解析实验计划失败: {exc}")
    template["task_id"] = task_id
    return template


# ---------------------------------------------------------------------------
# 任务报告
# ---------------------------------------------------------------------------


def _parse_task_report_metadata(rows: List[List[Any]]) -> JsonDict:
    """
    功能:
        从任务报告 xlsx 的顶部 5 行提取任务元信息.
    参数:
        rows: List[List[Any]], xlsx 工作表行二维数组.
    返回:
        Dict[str, Any], 元信息 (task_name, operator, status 等).
    """
    metadata: JsonDict = {
        "task_name": None, "operator": None, "task_status": None,
        "duration": None, "started_at": None, "completed_at": None, "created_at": None,
        "tray_model": None, "tray_barcode": None, "tray_position": None,
    }
    label_map = {
        "任务名称": "task_name",
        "创建人": "operator",
        "操作者": "operator",  # 兼容旧版本
        "创建时间": "created_at",
        "任务状态": "task_status",
        "执行时长": "duration",
        "执行时间": "duration",  # 兼容旧版本
        "开始时间": "started_at",
        "完成时间": "completed_at",
        "结束时间": "completed_at",  # 兼容旧版本
        "托盘型号": "tray_model",
        "托盘条码": "tray_barcode",
        "托盘位置": "tray_position",
    }
    # 仅在前 5 行扫描元信息, 第 6 行起进入步骤段表头
    for row in rows[:5]:
        for index, cell in enumerate(row):
            label = _safe_str(cell)
            if label == "":
                continue
            field = label_map.get(label)
            if field is None:
                continue
            value_cell = row[index + 1] if index + 1 < len(row) else None
            metadata[field] = _cell_to_value(value_cell)
    return metadata


def _parse_task_report_steps(rows: List[List[Any]]) -> List[JsonDict]:
    """
    功能:
        从任务报告 xlsx 的"步骤段"重复结构中解析出步骤列表与各实验结果.
    参数:
        rows: List[List[Any]], xlsx 工作表行二维数组.
    返回:
        List[Dict[str, Any]], 步骤列表, 每项含 step_index, step_name, extra_columns, experiments.
    """
    steps: List[JsonDict] = []
    cursor = 0
    while cursor < len(rows):
        row = rows[cursor]
        if len(row) < 5:
            cursor += 1
            continue

        # 步骤段头特征: B 列固定文案("反应试管"/"反应器") AND D 列以 "步骤" 起始
        col_b = _safe_str(row[1] if len(row) > 1 else None)
        col_d = _safe_str(row[3] if len(row) > 3 else None)
        if col_b not in ("反应试管", "反应器") or col_d.startswith("步骤") is False:
            cursor += 1
            continue

        step_label = col_d
        try:
            step_index = int(step_label.replace("步骤", "").strip())
        except ValueError:
            step_index = len(steps) + 1
        extra_headers = [_safe_str(cell) for cell in row[6:] if _safe_str(cell) != ""]

        # 紧跟其后的连续行为各实验数据 (列 B = 实验编号 1..12)
        experiments: JsonDict = {}
        step_name: str = ""
        cursor += 1
        while cursor < len(rows):
            data_row = rows[cursor]
            if len(data_row) < 5:
                break
            exp_id_text = _safe_str(data_row[1] if len(data_row) > 1 else None)
            if exp_id_text == "" or exp_id_text in ("反应试管", "反应器"):
                break
            try:
                exp_id = int(exp_id_text)
            except ValueError:
                break
            current_step_name = _safe_str(data_row[3] if len(data_row) > 3 else None)
            if step_name == "" and current_step_name != "":
                step_name = current_step_name
            extras: List[Any] = []
            for offset in range(len(extra_headers)):
                col_index = 6 + offset
                cell_value = data_row[col_index] if col_index < len(data_row) else None
                extras.append(_cell_to_value(cell_value))
            experiments[str(exp_id)] = {
                "step_name": current_step_name,
                "status": _cell_to_value(data_row[4] if len(data_row) > 4 else None),
                "completed_at": _cell_to_value(data_row[5] if len(data_row) > 5 else None),
                "extras": extras,
            }
            cursor += 1

        steps.append({
            "step_index": step_index,
            "step_label": step_label,
            "step_name": step_name,
            "extra_columns": extra_headers,
            "experiments": experiments,
        })
    return steps


@router.get("/{task_id}/task-report")
def get_task_report(task_id: int) -> JsonDict:
    """
    功能:
        解析任务报告 xlsx, 返回适合"实验 × 步骤"流水线视图的结构化数据.
    参数:
        task_id: int, 任务 ID.
    返回:
        Dict[str, Any], 含 metadata, experiments, steps.
    """
    file_path = _resolve_file_path(task_id, "task_report")
    try:
        workbook = load_workbook(file_path, read_only=True, data_only=True)
    except Exception as exc:
        logger.warning("解析任务报告失败, task_id=%s, err=%s", task_id, exc)
        raise _json_error(f"解析任务报告失败: {exc}")

    try:
        worksheet = workbook.worksheets[0]
        rows = [list(row) for row in worksheet.iter_rows(values_only=True)]
    finally:
        workbook.close()

    metadata = _parse_task_report_metadata(rows)
    steps = _parse_task_report_steps(rows)
    experiment_ids: List[int] = []
    for step in steps:
        for exp_id_text in step["experiments"].keys():
            exp_id = int(exp_id_text)
            if exp_id not in experiment_ids:
                experiment_ids.append(exp_id)
    experiment_ids.sort()
    return {
        "task_id": task_id,
        "sheet_name": worksheet.title,
        "metadata": metadata,
        "experiments": experiment_ids,
        "steps": steps,
    }


# ---------------------------------------------------------------------------
# 积分报告
# ---------------------------------------------------------------------------


def _row_to_dict(headers: List[str], row: List[Any]) -> JsonDict:
    """
    功能:
        将 xlsx 行按表头转字典 (传入的 row 可以是 cell 对象或纯值).
    参数:
        headers: List[str], 表头.
        row: List[Any], 行内容.
    返回:
        Dict[str, Any], 字段字典.
    """
    result: JsonDict = {}
    for index, header in enumerate(headers):
        if header == "":
            continue
        cell = row[index] if index < len(row) else None
        value = cell.value if hasattr(cell, "value") else cell
        result[header] = _cell_to_value(value)
    return result


def _extract_structure_filename(cell: Any, task_id: int) -> Optional[str]:
    """
    功能:
        从化合物名称单元格的 hyperlink 中提取结构图文件名 (位于分析站 structures/ 子目录).
    参数:
        cell: openpyxl 单元格对象.
        task_id: int, 任务 ID, 用于校验文件实际存在.
    返回:
        Optional[str], 文件名 (如 "100-46-9.png"), 不存在或非结构图链接时返回 None.
    """
    if not hasattr(cell, "hyperlink") or cell.hyperlink is None:
        return None
    target = cell.hyperlink.target
    if target is None or target == "":
        return None
    candidate = Path(target).name
    if candidate == "" or candidate.lower().endswith(".png") is False:
        return None
    if _check_image_exists(task_id, "structures", candidate) is False:
        return None
    return candidate


def _build_compound_candidates(
    headers: List[str],
    row_cells: List[Any],
    task_id: int,
    max_count: int = 3,
) -> List[JsonDict]:
    """
    功能:
        从积分报告一行中抽取候选化合物数组, 同时通过名称单元格 hyperlink 关联结构图.
    参数:
        headers: List[str], 表头.
        row_cells: List[Any], 行单元格对象 (非 values_only).
        task_id: int, 任务 ID, 用于结构图存在性校验.
        max_count: int, 最多候选数.
    返回:
        List[Dict[str, Any]], 候选化合物列表.
    """
    candidates: List[JsonDict] = []
    for index in range(1, max_count + 1):
        name_header = f"化合物{index}(名称)"
        if name_header not in headers:
            continue
        name_col = headers.index(name_header)
        name_cell = row_cells[name_col] if name_col < len(row_cells) else None
        if name_cell is None:
            continue
        name_value = name_cell.value if hasattr(name_cell, "value") else name_cell
        if name_value is None or _safe_str(name_value) == "":
            continue
        score_col = headers.index(f"化合物{index}(匹配度)") if f"化合物{index}(匹配度)" in headers else None
        formula_col = headers.index(f"化合物{index}(分子式)") if f"化合物{index}(分子式)" in headers else None
        mw_col = headers.index(f"化合物{index}(分子量)") if f"化合物{index}(分子量)" in headers else None

        def _val(col_index: Optional[int]) -> Any:
            if col_index is None or col_index >= len(row_cells):
                return None
            cell = row_cells[col_index]
            return _cell_to_value(cell.value if hasattr(cell, "value") else cell)

        candidates.append({
            "rank": index,
            "name": _cell_to_value(name_value),
            "score": _val(score_col),
            "formula": _val(formula_col),
            "molecular_weight": _val(mw_col),
            "structure_image": _extract_structure_filename(name_cell, task_id),
        })
    return candidates


def _check_image_exists(task_id: int, group: str, filename: str) -> bool:
    """
    功能:
        校验分析站任务目录下指定图片是否存在 (避免前端请求 404).
    参数:
        task_id: int, 任务 ID.
        group: str, 图集名称.
        filename: str, 图片文件名.
    返回:
        bool, 文件是否存在.
    """
    base = Path(ANALYSIS_DATA_DIR) / str(task_id) / group / filename
    return base.is_file()


@router.get("/{task_id}/integration-report")
def get_integration_report(task_id: int) -> JsonDict:
    """
    功能:
        解析积分报告 xlsx (位于分析站数据目录), 返回 {样品 → 峰 → 候选化合物} 结构化数据.
    参数:
        task_id: int, 任务 ID.
    返回:
        Dict[str, Any], 含 samples 列表, 每项含 TIC/FID 峰与色谱/质谱图引用.
    """
    file_path = _resolve_analysis_report(task_id, "integration_report")
    if file_path is None:
        raise _json_error(
            f"任务 {task_id} 未找到积分报告", status_code=status.HTTP_404_NOT_FOUND,
        )

    try:
        # 不使用 read_only 模式, 以便读取候选化合物名称单元格的 hyperlink (指向 structures/ 结构图)
        workbook = load_workbook(file_path, data_only=True)
    except Exception as exc:
        logger.warning("解析积分报告失败, task_id=%s, err=%s", task_id, exc)
        raise _json_error(f"解析积分报告失败: {exc}")

    sheet_map = {sheet.title: sheet for sheet in workbook.worksheets}
    try:
        tic_cell_rows = _read_sheet_cells(sheet_map.get("TIC峰表"))
        fid_cell_rows = _read_sheet_cells(sheet_map.get("FID峰表"))
        align_cell_rows = _read_sheet_cells(sheet_map.get("TIC-FID对照表"))
        summary_rows = _read_sheet_rows(sheet_map.get("样品汇总"))
    finally:
        workbook.close()

    # 样品汇总: 一行 = 一个样品
    summary_by_sample: Dict[str, JsonDict] = {}
    if summary_rows:
        summary_headers = [_safe_str(cell) for cell in summary_rows[0]]
        for row in summary_rows[1:]:
            row_dict = _row_to_dict(summary_headers, row)
            sample_name = _safe_str(row_dict.get("样品名"))
            if sample_name == "":
                continue
            summary_by_sample[sample_name] = row_dict

    # TIC 峰表: 一行 = 一个峰, 按样品聚合
    samples_order: List[str] = []
    samples_map: Dict[str, JsonDict] = {}

    def _ensure_sample(name: str) -> JsonDict:
        if name not in samples_map:
            summary = summary_by_sample.get(name, {})
            tic_filename = f"{name}_tic.png"
            fid_filename = f"{name}_fid.png"
            samples_map[name] = {
                "name": name,
                "tic_peak_count": summary.get("TIC峰数"),
                "fid_peak_count": summary.get("FID峰数"),
                "tic_total_area": summary.get("TIC总面积"),
                "fid_total_area": summary.get("FID总面积"),
                "acquired_at": summary.get("采集时间"),
                "tic_image": tic_filename if _check_image_exists(task_id, "plots", tic_filename) else None,
                "fid_image": fid_filename if _check_image_exists(task_id, "plots", fid_filename) else None,
                "tic_peaks": [],
                "fid_peaks": [],
                "alignments": [],
            }
            samples_order.append(name)
        return samples_map[name]

    if tic_cell_rows:
        tic_headers = [_safe_str(cell.value if hasattr(cell, "value") else cell) for cell in tic_cell_rows[0]]
        for row_cells in tic_cell_rows[1:]:
            row_dict = _row_to_dict(tic_headers, row_cells)
            sample_name = _safe_str(row_dict.get("样品名"))
            if sample_name == "":
                continue
            sample = _ensure_sample(sample_name)
            peak_no = row_dict.get("峰号")
            ms_filename = f"{sample_name}_peak{peak_no}_ms.png" if peak_no is not None else None
            ms_exists = ms_filename is not None and _check_image_exists(task_id, "ms_plots", ms_filename)
            sample["tic_peaks"].append({
                "peak_no": peak_no,
                "rt": row_dict.get("保留时间(min)"),
                "height": row_dict.get("峰高"),
                "area": row_dict.get("峰面积"),
                "area_pct": row_dict.get("面积%"),
                "start": row_dict.get("峰起始(min)"),
                "end": row_dict.get("峰结束(min)"),
                "width": row_dict.get("峰宽(min)"),
                "ms_image": ms_filename if ms_exists else None,
                "candidates": _build_compound_candidates(tic_headers, list(row_cells), task_id),
                "pim_mw": row_dict.get("PIM预测分子量(Da)"),
                "pim_confidence": row_dict.get("PIM置信指数"),
                "sshm_mw": row_dict.get("SS-HM预测分子量(Da)"),
                "sshm_confidence": row_dict.get("SS-HM置信度"),
            })

    if fid_cell_rows:
        fid_headers = [_safe_str(cell.value if hasattr(cell, "value") else cell) for cell in fid_cell_rows[0]]
        for row_cells in fid_cell_rows[1:]:
            row_dict = _row_to_dict(fid_headers, row_cells)
            sample_name = _safe_str(row_dict.get("样品名"))
            if sample_name == "":
                continue
            sample = _ensure_sample(sample_name)
            sample["fid_peaks"].append({
                "peak_no": row_dict.get("峰号"),
                "rt": row_dict.get("保留时间(min)"),
                "height": row_dict.get("峰高"),
                "area": row_dict.get("峰面积"),
                "area_pct": row_dict.get("面积%"),
                "start": row_dict.get("峰起始(min)"),
                "end": row_dict.get("峰结束(min)"),
                "width": row_dict.get("峰宽(min)"),
            })

    if align_cell_rows:
        align_headers = [_safe_str(cell.value if hasattr(cell, "value") else cell) for cell in align_cell_rows[0]]
        for row_cells in align_cell_rows[1:]:
            row_dict = _row_to_dict(align_headers, row_cells)
            sample_name = _safe_str(row_dict.get("样品名"))
            if sample_name == "":
                continue
            sample = _ensure_sample(sample_name)
            tic_peak_no = row_dict.get("TIC峰号")
            ms_filename = (
                f"{sample_name}_peak{tic_peak_no}_ms.png"
                if tic_peak_no is not None and _safe_str(tic_peak_no) != ""
                else None
            )
            ms_exists = ms_filename is not None and _check_image_exists(task_id, "ms_plots", ms_filename)
            sample["alignments"].append({
                "fid_peak_no": row_dict.get("FID峰号"),
                "fid_rt": row_dict.get("FID保留时间(min)"),
                "fid_area": row_dict.get("FID峰面积"),
                "tic_peak_no": tic_peak_no,
                "tic_rt": row_dict.get("TIC保留时间(min)"),
                "ms_image": ms_filename if ms_exists else None,
                "candidates": _build_compound_candidates(align_headers, list(row_cells), task_id),
                "pim_mw": row_dict.get("PIM预测分子量(Da)"),
                "pim_confidence": row_dict.get("PIM置信指数"),
                "sshm_mw": row_dict.get("SS-HM预测分子量(Da)"),
                "sshm_confidence": row_dict.get("SS-HM置信度"),
            })

    # 仅样品汇总有但无峰数据的样品也要包含 (例如 725-10)
    for sample_name in summary_by_sample.keys():
        _ensure_sample(sample_name)

    samples = [samples_map[name] for name in samples_order]
    return {
        "task_id": task_id,
        "samples": samples,
    }


def _read_sheet_cells(worksheet: Any) -> List[List[Any]]:
    """
    功能:
        以 cell 对象方式读取整张工作表 (保留 hyperlink 元数据).
    参数:
        worksheet: Worksheet 或 None.
    返回:
        List[List[Cell]], 行单元格对象数组.
    """
    if worksheet is None:
        return []
    return [list(row) for row in worksheet.iter_rows()]


def _read_sheet_rows(worksheet: Any) -> List[List[Any]]:
    """
    功能:
        读取整张工作表为二维列表, 工作表为 None 时返回空列表.
    参数:
        worksheet: Worksheet 或 None.
    返回:
        List[List[Any]], 行数据.
    """
    if worksheet is None:
        return []
    return [list(row) for row in worksheet.iter_rows(values_only=True)]


# ---------------------------------------------------------------------------
# 产率报告
# ---------------------------------------------------------------------------


def _parse_yield_config(rows: List[List[Any]]) -> JsonDict:
    """
    功能:
        从产率报告"计算参数"sheet 解析出反应配置, 包含内标信息与目标产物列表.
    参数:
        rows: List[List[Any]], 工作表行.
    返回:
        Dict[str, Any], 配置数据.
    """
    config: JsonDict = {
        "calc_method": None,
        "reaction_scale": None,
        "internal_standard": {},
        "products": [],
    }
    products_buffer: Dict[int, JsonDict] = {}

    for row in rows:
        key = _safe_str(row[0] if len(row) > 0 else None)
        value = _cell_to_value(row[1] if len(row) > 1 else None)
        if key == "":
            continue

        # 段落分隔符 (例如 "==== 内标信息 ====") 仅作可视化分组, 数据靠字段前缀识别
        if "====" in key:
            continue

        if key == "产率计算方法":
            config["calc_method"] = value
            continue
        if key == "反应规模(mmol)":
            config["reaction_scale"] = value
            continue

        if key.startswith("内标"):
            sub = key.replace("内标", "", 1).strip()
            mapping = {
                "名称": "name", "SMILES": "smiles", "分子式": "formula",
                "分子量(Da)": "molecular_weight", "标称分子量(Da)": "nominal_mw",
                "ECN": "ecn", "NIST收录": "nist_recorded", "NIST查询模式": "nist_query_mode",
                "用量(μL/mg)": "dosage", "摩尔量(mmol)": "mmol", "预期RT(min)": "expected_rt",
            }
            if sub in mapping:
                config["internal_standard"][mapping[sub]] = value
            continue

        if key.startswith("产物"):
            tokens = key.split(" ", 1)
            head = tokens[0]
            try:
                product_index = int(head.replace("产物", "").strip())
            except ValueError:
                continue
            sub = tokens[1] if len(tokens) > 1 else ""
            mapping = {
                "名称": "name", "SMILES": "smiles", "分子式": "formula",
                "分子量(Da)": "molecular_weight", "标称分子量(Da)": "nominal_mw",
                "ECN": "ecn", "NIST收录": "nist_recorded", "NIST查询模式": "nist_query_mode",
                "预期RT(min)": "expected_rt", "适用实验": "applicable_experiments",
                "当量(eq)": "equivalent",
            }
            if sub not in mapping:
                continue
            buf = products_buffer.setdefault(product_index, {"product_index": product_index})
            buf[mapping[sub]] = value

    config["products"] = [products_buffer[idx] for idx in sorted(products_buffer.keys())]
    return config


def _normalize_yield_value(value: Any) -> Tuple[Optional[float], str]:
    """
    功能:
        将产率报告中的产率值拆分为可计算数值与可显示文本.
    参数:
        value: Any, "产率(%)" 单元格原始值, 可能是数字, None 或 "<1".
    返回:
        Tuple[Optional[float], str], 第 1 项用于热力图计算, 第 2 项用于界面显示.
    """
    if value is None:
        return None, "-"
    if isinstance(value, (int, float)) is True:
        yield_pct = float(value)
        return yield_pct, f"{round(yield_pct)}%"
    if _safe_str(value) == "<1":
        return None, "<1%"
    return None, "-"


@router.get("/{task_id}/yield-report")
def get_yield_report(task_id: int) -> JsonDict:
    """
    功能:
        解析产率报告 xlsx (位于分析站数据目录), 返回 {配置, 样品 × 产物 矩阵} 结构化数据.
    参数:
        task_id: int, 任务 ID.
    返回:
        Dict[str, Any], 含 config, samples, products.
    """
    file_path = _resolve_analysis_report(task_id, "yield_report")
    if file_path is None:
        raise _json_error(
            f"任务 {task_id} 未找到产率报告", status_code=status.HTTP_404_NOT_FOUND,
        )

    try:
        workbook = load_workbook(file_path, read_only=True, data_only=True)
    except Exception as exc:
        logger.warning("解析产率报告失败, task_id=%s, err=%s", task_id, exc)
        raise _json_error(f"解析产率报告失败: {exc}")

    sheet_map = {sheet.title: sheet for sheet in workbook.worksheets}
    try:
        result_rows = _read_sheet_rows(sheet_map.get("产率计算结果"))
        config_rows = _read_sheet_rows(sheet_map.get("计算参数"))
    finally:
        workbook.close()

    config = _parse_yield_config(config_rows)

    samples_order: List[str] = []
    samples_map: Dict[str, JsonDict] = {}
    products_seen: List[str] = []

    if result_rows:
        result_headers = [_safe_str(cell) for cell in result_rows[0]]
        for row in result_rows[1:]:
            row_dict = _row_to_dict(result_headers, row)
            sample_name = _safe_str(row_dict.get("样品名"))
            if sample_name == "":
                continue
            product_name = _safe_str(row_dict.get("目标产物")) or "未命名产物"
            if product_name not in products_seen:
                products_seen.append(product_name)
            yield_pct, yield_display = _normalize_yield_value(row_dict.get("产率(%)"))
            entry = {
                "product_name": product_name,
                "product_rt": row_dict.get("产物保留时间(min)"),
                "product_area": row_dict.get("产物FID面积"),
                "product_match": row_dict.get("产物匹配化合物"),
                "internal_rt": row_dict.get("内标保留时间(min)"),
                "internal_area": row_dict.get("内标FID面积"),
                "internal_match": row_dict.get("内标匹配化合物"),
                "ratio": row_dict.get("Ratio"),
                "product_ecn": row_dict.get("产物ECN"),
                "internal_ecn": row_dict.get("内标ECN"),
                "yield_pct": yield_pct,
                "yield_display": yield_display,
                "match_method": row_dict.get("匹配方式"),
                "confidence": row_dict.get("置信度"),
                "nist_mw": row_dict.get("NIST匹配分子量(Da)"),
                "pim_mw": row_dict.get("PIM预测分子量(Da)"),
                "sshm_mw": row_dict.get("SS-HM预测分子量(Da)"),
                "remarks": row_dict.get("备注"),
            }
            if sample_name not in samples_map:
                samples_map[sample_name] = {"sample": sample_name, "results": []}
                samples_order.append(sample_name)
            samples_map[sample_name]["results"].append(entry)

    samples = [samples_map[name] for name in samples_order]
    return {
        "task_id": task_id,
        "config": config,
        "products": products_seen,
        "samples": samples,
    }
