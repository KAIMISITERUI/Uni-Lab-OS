# -*- coding: utf-8 -*-
"""
功能:
    溶液 / beads 配置路由.
    路由前缀 /api/prepare.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from ...driver.exceptions import ValidationError
from ...manager.chemical_manager import ChemicalManager
from ..deps import TokenDep, get_manager
from ..schemas import (
    PrepareBeadsRequest,
    PrepareResponse,
    PrepareSolutionRequest,
)

logger = logging.getLogger("PrepareRouter")

router = APIRouter(prefix="/api/prepare", tags=["prepare"], dependencies=[TokenDep])


def _to_response(result) -> PrepareResponse:
    """
    功能:
        把 ChemicalManager.prepare_solution_or_beads 的返回归一为 PrepareResponse.
    """
    if result is None:
        return PrepareResponse(success=False, message="未找到母体化合物或操作未完成")
    if result.get("duplicate") is True:
        return PrepareResponse(
            success=True,
            duplicate=True,
            duplicate_substance=result.get("duplicate_substance"),
        )
    return PrepareResponse(
        success=True,
        base_row_data=result.get("base_row_data"),
        base_row_id=result.get("base_row_id"),
        base_created=result.get("base_created"),
        derived_row_data=result.get("derived_row_data"),
        derived_row_id=result.get("derived_row_id"),
        recipe=result.get("recipe"),
    )


@router.post("/solution", response_model=PrepareResponse)
def prepare_solution(
    payload: PrepareSolutionRequest,
    manager: ChemicalManager = Depends(get_manager),
) -> PrepareResponse:
    """
    功能:
        配置溶液. active_content 单位 mol/L, target_volume_ml 单位 mL.
    """
    try:
        result = manager.prepare_solution_or_beads(
            identifier=payload.identifier,
            prepared_form="solution",
            solvent_name=payload.solvent_name,
            active_content=payload.active_content,
            target_volume_ml=payload.target_volume_ml,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("配置溶液失败: %s", payload.identifier)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"配置溶液失败: {exc}",
        ) from exc

    return _to_response(result)


@router.post("/beads", response_model=PrepareResponse)
def prepare_beads(
    payload: PrepareBeadsRequest,
    manager: ChemicalManager = Depends(get_manager),
) -> PrepareResponse:
    """
    功能:
        配置 beads. active_content 单位 wt%, target_active_mmol 单位 mmol.
    """
    try:
        result = manager.prepare_solution_or_beads(
            identifier=payload.identifier,
            prepared_form="beads",
            active_content=payload.active_content,
            target_active_mmol=payload.target_active_mmol,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("配置 beads 失败: %s", payload.identifier)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"配置 beads 失败: {exc}",
        ) from exc

    return _to_response(result)
