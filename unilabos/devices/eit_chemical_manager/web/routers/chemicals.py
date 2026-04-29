# -*- coding: utf-8 -*-
"""
功能:
    化学品 CRUD 路由.
    路由前缀 /api/chemicals.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ...driver.exceptions import ValidationError
from ...manager.chemical_manager import ChemicalManager
from ..deps import TokenDep, get_manager
from ..schemas import (
    ChemicalIn,
    ChemicalListResponse,
    ChemicalOut,
    ChemicalStructureSearchRequest,
    ChemicalStructureSearchResponse,
    DeleteResponse,
)

logger = logging.getLogger("ChemicalsRouter")

router = APIRouter(prefix="/api/chemicals", tags=["chemicals"], dependencies=[TokenDep])


@router.get("", response_model=ChemicalListResponse)
def list_chemicals(
    manager: ChemicalManager = Depends(get_manager),
    q: Optional[str] = Query(default=None, description="按表格可见字段模糊搜索"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=500),
) -> ChemicalListResponse:
    """
    功能:
        分页列表 + 搜索. q 为空时返回全表分页, 否则调用 ChemicalManager.search.
    """
    if q is not None and q.strip() != "":
        rows = [hit["row_data"] for hit in manager.search(q)]
    else:
        rows = manager.db.iter_all()

    total = len(rows)
    start = (page - 1) * page_size
    end = start + page_size
    items = rows[start:end]
    return ChemicalListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[ChemicalOut(**row) for row in items],
    )


@router.post("/structure-search", response_model=ChemicalStructureSearchResponse)
def search_chemicals_by_structure(
    payload: ChemicalStructureSearchRequest,
    manager: ChemicalManager = Depends(get_manager),
) -> ChemicalStructureSearchResponse:
    """
    功能:
        按结构式搜索本地化学品库.
        exact 模式使用完整 InChIKey 精确比对, substructure 模式使用子结构匹配.
    参数:
        payload: ChemicalStructureSearchRequest, 查询结构, 输入格式, 匹配模式与分页参数.
        manager: ChemicalManager, 化学品管理器.
    返回:
        ChemicalStructureSearchResponse, 分页命中结果与规范化查询 SMILES.
    """
    try:
        result = manager.search_by_structure(
            structure=payload.structure,
            input_format=payload.input_format,
            match_mode=payload.match_mode,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        logger.exception("结构式搜索运行环境不可用")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    rows = list(result.get("rows") or [])
    total = len(rows)
    start = (payload.page - 1) * payload.page_size
    end = start + payload.page_size
    items = rows[start:end]
    return ChemicalStructureSearchResponse(
        total=total,
        page=payload.page,
        page_size=payload.page_size,
        items=[ChemicalOut(**row) for row in items],
        query_smiles=str(result.get("query_smiles") or ""),
    )


@router.get("/by-substance", response_model=ChemicalOut)
def get_chemical_by_substance(
    substance: str = Query(..., description="按 substance 中文名精确查询"),
    manager: ChemicalManager = Depends(get_manager),
) -> ChemicalOut:
    """
    功能:
        按 substance 中文名精确查询单条化学品记录.
    参数:
        substance: str, 中文名.
        manager: ChemicalManager, 化学品管理器.
    返回:
        ChemicalOut, 命中的化学品记录.
    """
    normalized_substance = str(substance or "").strip()
    if normalized_substance == "":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="substance 不能为空",
        )

    row = manager.db.find_by_substance_exact(normalized_substance)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"未找到化学品 substance={normalized_substance}",
        )
    return ChemicalOut(**row)


@router.get("/{row_id}", response_model=ChemicalOut)
def get_chemical(
    row_id: int,
    manager: ChemicalManager = Depends(get_manager),
) -> ChemicalOut:
    """
    功能:
        按主键查询单条化学品.
    """
    row = manager.db.get_by_id(row_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"未找到化学品 id={row_id}",
        )
    return ChemicalOut(**row)


@router.post("/{row_id}/refresh-hazard", response_model=ChemicalOut)
def refresh_chemical_hazard(
    row_id: int,
    manager: ChemicalManager = Depends(get_manager),
) -> ChemicalOut:
    """
    功能:
        按当前化学品标识刷新 PubChem GHS 危害信息.
    参数:
        row_id: int, 化学品行 id.
        manager: ChemicalManager, 化学品管理器.
    返回:
        ChemicalOut, 刷新后的化学品记录.
    """
    row = manager.refresh_hazard_for_row(row_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"未找到化学品 id={row_id}",
        )
    return ChemicalOut(**row)


@router.post(
    "",
    response_model=ChemicalOut,
    status_code=status.HTTP_201_CREATED,
)
def create_chemical(
    payload: ChemicalIn,
    manager: ChemicalManager = Depends(get_manager),
) -> ChemicalOut:
    """
    功能:
        手工新增一条化学品记录.
        UNIQUE 约束在写入路径强制 substance 唯一, 重名抛 409.
    """
    row_data = payload.model_dump(exclude_none=True)
    if not row_data.get("substance") and not row_data.get("substance_english_name"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="substance 或 substance_english_name 至少提供一个",
        )
    try:
        new_id = manager.db.insert_row(row_data)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    created = manager.db.get_by_id(new_id)
    logger.info("Web 新增化学品 id=%s, substance=%s", new_id, row_data.get("substance"))
    return ChemicalOut(**created)


@router.put("/{row_id}", response_model=ChemicalOut)
def update_chemical(
    row_id: int,
    payload: ChemicalIn,
    manager: ChemicalManager = Depends(get_manager),
) -> ChemicalOut:
    """
    功能:
        编辑指定 id 的化学品行.
    """
    if manager.db.get_by_id(row_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"未找到化学品 id={row_id}",
        )
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请求体为空, 无可更新字段",
        )
    try:
        manager.db.update_row(row_id, updates)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return ChemicalOut(**manager.db.get_by_id(row_id))


@router.delete("/{row_id}", response_model=DeleteResponse)
def delete_chemical(
    row_id: int,
    manager: ChemicalManager = Depends(get_manager),
) -> DeleteResponse:
    """
    功能:
        删除指定 id 的化学品行.
    """
    if manager.db.get_by_id(row_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"未找到化学品 id={row_id}",
        )
    deleted = manager.db.delete_row(row_id)
    logger.info("Web 删除化学品 id=%s", row_id)
    return DeleteResponse(deleted=deleted)
