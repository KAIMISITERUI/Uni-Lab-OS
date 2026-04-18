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
    DeleteResponse,
)

logger = logging.getLogger("ChemicalsRouter")

router = APIRouter(prefix="/api/chemicals", tags=["chemicals"], dependencies=[TokenDep])


@router.get("", response_model=ChemicalListResponse)
def list_chemicals(
    manager: ChemicalManager = Depends(get_manager),
    q: Optional[str] = Query(default=None, description="按 CAS / 名称 / SMILES 搜索"),
    query_type: Optional[str] = Query(
        default=None, description="搜索类型, 支持 cas/name/smiles, 缺省时按名称搜索"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=500),
) -> ChemicalListResponse:
    """
    功能:
        分页列表 + 搜索. q 为空时返回全表分页, 否则调用 ChemicalManager.search.
    """
    if q is not None and q.strip() != "":
        effective_type = (query_type or "name").strip().lower()
        if effective_type not in {"cas", "name", "smiles"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="query_type 必须是 cas / name / smiles 之一",
            )
        rows = [hit["row_data"] for hit in manager.search(q, effective_type)]
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
