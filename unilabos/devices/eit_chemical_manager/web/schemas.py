# -*- coding: utf-8 -*-
"""
功能:
    Web API 的 Pydantic 请求/响应模型定义.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ChemicalIn(BaseModel):
    """
    功能:
        新增/更新化学品的入参模型.
        额外字段会透传进 extra_json, 保持与底层 ChemicalDB 写入接口一致.
    """

    model_config = ConfigDict(extra="allow")

    cas_number: Optional[str] = None
    chemical_id: Optional[str] = None
    substance: Optional[str] = None
    substance_english_name: Optional[str] = None
    other_name: Optional[str] = None
    brand: Optional[str] = None
    package_size: Optional[str] = None
    storage_location: Optional[str] = None
    molecular_weight: Optional[float] = None
    density: Optional[float] = None
    physical_state: Optional[str] = None
    physical_form: Optional[str] = None
    active_content: Optional[str] = None
    smiles: Optional[str] = None
    chemicalbook_record_path: Optional[str] = None


class ChemicalOut(BaseModel):
    """
    功能:
        化学品行数据响应模型. extra_json 已被底层展开, 因此使用 extra="allow"
        承接所有字段, 避免对 schema 演进过敏.
    """

    model_config = ConfigDict(extra="allow")

    id: int
    substance: Optional[str] = None
    cas_number: Optional[str] = None
    chemical_id: Optional[str] = None
    substance_english_name: Optional[str] = None
    physical_state: Optional[str] = None
    physical_form: Optional[str] = None
    storage_location: Optional[str] = None
    density: Optional[float] = None
    molecular_weight: Optional[float] = None
    active_content: Optional[str] = None
    smiles: Optional[str] = None
    brand: Optional[str] = None
    package_size: Optional[str] = None
    other_name: Optional[str] = None
    chemicalbook_record_path: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ChemicalListResponse(BaseModel):
    """功能: 列表查询响应, 含分页元信息."""

    total: int
    page: int
    page_size: int
    items: List[ChemicalOut]


class DuplicateNameGroup(BaseModel):
    """
    功能:
        同名行分组, 一组对应一个重复的名称值与命中该名称的全部行.
    """

    name: str
    rows: List[ChemicalOut]


class IntegrityReport(BaseModel):
    """
    功能:
        check_integrity 的响应模型, 含 7 类问题清单.
        每条问题项均为完整 ChemicalOut, 便于前端跳转编辑.
    """

    duplicate_chinese_names: List[DuplicateNameGroup]
    duplicate_english_names: List[DuplicateNameGroup]
    missing_physical_state: List[ChemicalOut]
    missing_physical_form: List[ChemicalOut]
    neat_missing_molecular_weight: List[ChemicalOut]
    neat_liquid_missing_density: List[ChemicalOut]
    beads_solution_missing_content: List[ChemicalOut]


class LookupRequest(BaseModel):
    """
    功能:
        在线查询入库请求.
    """

    query: str = Field(..., description="CAS / 名称 / SMILES")
    query_type: Literal["cas", "name", "smiles"]


class LookupResponse(BaseModel):
    """
    功能:
        lookup_and_append 的统一响应. 命中重复时 duplicate=True 且 duplicate_substance 给出已有名称.
    """

    success: bool
    duplicate: bool = False
    duplicate_substance: Optional[str] = None
    row_id: Optional[int] = None
    row_data: Optional[Dict[str, Any]] = None
    chemicalbook_status: Optional[str] = None
    chemicalbook_record_path: Optional[str] = None
    message: Optional[str] = None


class PrepareSolutionRequest(BaseModel):
    """功能: 配置溶液请求. active_content 为 mol/L."""

    identifier: str = Field(..., description="母体 CAS 或 SMILES")
    solvent_name: str
    active_content: float = Field(..., gt=0, description="目标摩尔浓度, mol/L")
    target_volume_ml: float = Field(..., gt=0, description="目标定容体积, mL")


class PrepareBeadsRequest(BaseModel):
    """功能: 配置 beads 请求. active_content 为 wt%."""

    identifier: str = Field(..., description="母体 CAS 或 SMILES")
    active_content: float = Field(..., gt=0, description="活性含量, wt%")
    target_active_mmol: float = Field(..., gt=0, description="目标活性 mmol")


class PrepareResponse(BaseModel):
    """功能: prepare_solution_or_beads 的响应."""

    success: bool
    duplicate: bool = False
    duplicate_substance: Optional[str] = None
    base_row_data: Optional[Dict[str, Any]] = None
    base_row_id: Optional[int] = None
    base_created: Optional[bool] = None
    derived_row_data: Optional[Dict[str, Any]] = None
    derived_row_id: Optional[int] = None
    recipe: Optional[Dict[str, Any]] = None
    message: Optional[str] = None


class DeleteResponse(BaseModel):
    """功能: 删除操作响应."""

    deleted: bool


class ImportResponse(BaseModel):
    """
    功能:
        从 xlsx / csv 文件导入化学品的响应, 三项计数与 import_to_library 一致.
    """

    migrated: int
    skipped: int
    failed: int
