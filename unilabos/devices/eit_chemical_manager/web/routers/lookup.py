# -*- coding: utf-8 -*-
"""
功能:
    在线查询预览路由. 只查询不写库, 由前端新增对话框在用户确认后走标准
    POST /api/chemicals 完成入库. 路由前缀 /api/lookup.
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
def lookup_preview(
    payload: LookupRequest,
    manager: ChemicalManager = Depends(get_manager),
) -> LookupResponse:
    """
    功能:
        在线查询预览接口. 调用 ChemicalManager.lookup_preview,
        仅返回候选行数据, 不执行数据库写入.
        - 查询失败或核心字段缺失返回 success=False
        - 成功返回 row_data 与 ChemicalBook 相关字段
    """
    try:
        result = manager.lookup_preview(payload.query, payload.query_type)
    except Exception as exc:
        logger.exception("在线查询失败: query=%s, type=%s", payload.query, payload.query_type)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"在线查询失败: {exc}",
        ) from exc

    if result is None:
        return LookupResponse(success=False, message="未找到化合物或核心字段为空")
    return LookupResponse(
        success=True,
        row_data=result.get("row_data"),
        chemicalbook_status=result.get("chemicalbook_status"),
        chemicalbook_record_path=result.get("chemicalbook_record_path"),
    )
