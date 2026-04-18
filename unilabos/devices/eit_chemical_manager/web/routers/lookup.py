# -*- coding: utf-8 -*-
"""
功能:
    在线查询 + 入库路由.
    路由前缀 /api/lookup.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from ...manager.chemical_manager import ChemicalManager
from ..deps import TokenDep, get_manager
from ..schemas import LookupRequest, LookupResponse

logger = logging.getLogger("LookupRouter")

router = APIRouter(prefix="/api/lookup", tags=["lookup"], dependencies=[TokenDep])


@router.post("", response_model=LookupResponse)
def lookup_and_append(
    payload: LookupRequest,
    manager: ChemicalManager = Depends(get_manager),
) -> LookupResponse:
    """
    功能:
        统一的在线查询入库接口. 调用 ChemicalManager.lookup_and_append.
        - 查询失败返回 success=False
        - 重复返回 duplicate=True 与已有 substance
        - 成功返回新行 id 与 row_data
    """
    try:
        result = manager.lookup_and_append(payload.query, payload.query_type)
    except Exception as exc:
        logger.exception("在线查询失败: query=%s, type=%s", payload.query, payload.query_type)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"在线查询失败: {exc}",
        ) from exc

    if result is None:
        return LookupResponse(success=False, message="未找到化合物或核心字段为空")
    if result.get("duplicate") is True:
        return LookupResponse(
            success=True,
            duplicate=True,
            duplicate_substance=result.get("duplicate_substance"),
        )
    return LookupResponse(
        success=True,
        row_id=result.get("row_id"),
        row_data=result.get("row_data"),
        chemicalbook_status=result.get("chemicalbook_status"),
        chemicalbook_record_path=result.get("chemicalbook_record_path"),
    )
