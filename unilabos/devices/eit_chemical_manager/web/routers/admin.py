# -*- coding: utf-8 -*-
"""
功能:
    化学品库的运维路由: 完整性检查, 导出 CSV / XLSX, 从文件导入.
    路由前缀 /api.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ...manager.chemical_manager import ChemicalManager
from ..deps import TokenDep, get_manager
from ..schemas import ImportResponse, IntegrityReport

logger = logging.getLogger("AdminRouter")

router = APIRouter(prefix="/api", tags=["admin"], dependencies=[TokenDep])

# 与前端 ImportDialog 保持一致的受支持扩展名集合
_ALLOWED_IMPORT_SUFFIXES = {".xlsx", ".csv"}

# Excel xlsx 文件的标准 MIME, 抽成常量避免散落在多处
_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/integrity", response_model=IntegrityReport)
def get_integrity(
    manager: ChemicalManager = Depends(get_manager),
) -> IntegrityReport:
    """
    功能:
        返回化学品库完整性报告.
    """
    return IntegrityReport(**manager.check_integrity())


@router.get("/export.csv")
def export_csv(
    background_tasks: BackgroundTasks,
    manager: ChemicalManager = Depends(get_manager),
) -> FileResponse:
    """
    功能:
        导出化学品库为 CSV 文件并通过 FileResponse 返回, 临时文件在响应完成后自动清理.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="chem_export_"))
    output = tmp_dir / "chemical_library.csv"
    manager.export_to_csv(str(output))

    background_tasks.add_task(_cleanup_tmp_dir, tmp_dir)
    return FileResponse(
        path=str(output),
        media_type="text/csv",
        filename="chemical_library.csv",
    )


@router.get("/export.xlsx")
def export_xlsx(
    background_tasks: BackgroundTasks,
    manager: ChemicalManager = Depends(get_manager),
) -> FileResponse:
    """
    功能:
        导出化学品库为 xlsx 文件并通过 FileResponse 返回, 临时文件在响应完成后自动清理.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="chem_export_"))
    output = tmp_dir / "chemical_library.xlsx"
    manager.export_to_xlsx(str(output))

    background_tasks.add_task(_cleanup_tmp_dir, tmp_dir)
    return FileResponse(
        path=str(output),
        media_type=_XLSX_MEDIA_TYPE,
        filename="chemical_library.xlsx",
    )


@router.post("/import", response_model=ImportResponse)
async def import_file(
    background_tasks: BackgroundTasks,
    file: UploadFile,
    dry_run: bool = Form(default=False),
    manager: ChemicalManager = Depends(get_manager),
) -> ImportResponse:
    """
    功能:
        接收 xlsx / csv 上传, 将其中化学品追加到化学品库, 重复行自动跳过.
        仅允许 .xlsx 和 .csv 后缀, 其他类型返回 400.
    参数:
        file: UploadFile, 上传文件.
        dry_run: bool, 表单字段, True 时仅统计不写入.
    返回:
        ImportResponse, 含 migrated / skipped / failed.
    """
    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()
    if suffix not in _ALLOWED_IMPORT_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"仅支持 .xlsx 或 .csv 文件, 当前文件: {filename}",
        )

    # 保留原始后缀以便 import_to_library 按后缀分派读取器
    tmp_dir = Path(tempfile.mkdtemp(prefix="chem_import_"))
    tmp_file = tmp_dir / f"upload{suffix}"
    try:
        with open(tmp_file, "wb") as out_f:
            shutil.copyfileobj(file.file, out_f)
    finally:
        await file.close()

    try:
        stats = manager.import_to_library(str(tmp_file), dry_run=bool(dry_run))
    except ValueError as exc:
        # 表头缺失或文件格式非法, 给前端返回 400
        _cleanup_tmp_dir(tmp_dir)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        _cleanup_tmp_dir(tmp_dir)
        raise

    background_tasks.add_task(_cleanup_tmp_dir, tmp_dir)
    logger.info(
        "Web 导入完成: file=%s, dry_run=%s, migrated=%d, skipped=%d, failed=%d",
        filename,
        dry_run,
        stats["migrated"],
        stats["skipped"],
        stats["failed"],
    )
    return ImportResponse(**stats)


def _cleanup_tmp_dir(tmp_dir: Path) -> None:
    """
    功能:
        递归删除导出或导入使用的临时目录, 已删除时静默忽略.
    参数:
        tmp_dir: Path, 临时目录路径.
    返回:
        None.
    """
    try:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    except OSError as cleanup_exc:
        logger.warning("临时目录清理失败: %s, err=%s", tmp_dir, cleanup_exc)
