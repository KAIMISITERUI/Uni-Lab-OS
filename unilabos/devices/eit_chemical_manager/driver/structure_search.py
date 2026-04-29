# -*- coding: utf-8 -*-
"""
功能:
    基于 RDKit 的化学品结构搜索工具.
    支持完整结构 InChIKey 精确比对与子结构匹配, 仅依赖库内已有 smiles 字段.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from .exceptions import ValidationError

logger = logging.getLogger("ChemicalStructureSearch")


@dataclass(frozen=True)
class ParsedStructure:
    """
    功能:
        保存一次查询结构的 RDKit 解析结果.
    参数:
        molecule: RDKit Mol 对象.
        canonical_smiles: RDKit 规范化后的 isomeric SMILES.
        inchikey: RDKit 生成的完整 InChIKey.
    返回:
        ParsedStructure.
    """

    molecule: Any
    canonical_smiles: str
    inchikey: str


def _load_rdkit_modules() -> Tuple[Any, Any]:
    """
    功能:
        动态加载 RDKit Chem 与 InChI 模块, 避免导入包时强依赖 RDKit.
    参数:
        无.
    返回:
        Tuple[Any, Any], 依次为 Chem 模块与 RDKit InChI 模块.
    异常:
        RuntimeError: 当前 Python 环境未安装 RDKit 或 InChI 模块不可用.
    """
    try:
        from rdkit import Chem
        from rdkit.Chem import inchi as rdkit_inchi
    except ImportError as exc:
        raise RuntimeError("未安装 RDKit, 无法执行结构式搜索") from exc
    return Chem, rdkit_inchi


def _mol_to_inchikey(rdkit_inchi: Any, molecule: Any, source_label: str) -> str:
    """
    功能:
        将 RDKit Mol 转换为完整 InChIKey.
    参数:
        rdkit_inchi: Any, RDKit InChI 模块.
        molecule: Any, RDKit Mol 对象.
        source_label: str, 日志中使用的来源说明.
    返回:
        str, 成功时返回大写 InChIKey, 失败时返回空字符串.
    """
    try:
        inchikey = rdkit_inchi.MolToInchiKey(molecule)
    except Exception as exc:
        logger.warning("生成 InChIKey 失败: source=%s, err=%s", source_label, exc)
        return ""
    normalized = str(inchikey or "").strip().upper()
    return normalized


def _parse_structure(
    Chem: Any,
    rdkit_inchi: Any,
    structure: str,
    input_format: str,
) -> ParsedStructure:
    """
    功能:
        按指定格式解析用户绘制或输入的结构, 并生成规范 SMILES 与 InChIKey.
    参数:
        Chem: Any, RDKit Chem 模块.
        rdkit_inchi: Any, RDKit InChI 模块.
        structure: str, SMILES 或 molfile 文本.
        input_format: str, 输入格式, 支持 smiles 或 molfile.
    返回:
        ParsedStructure, 解析后的结构信息.
    异常:
        ValidationError: 输入为空, 格式非法, 或结构无法解析.
    """
    normalized_structure = str(structure or "").strip()
    if normalized_structure == "":
        raise ValidationError("结构式不能为空")

    normalized_format = str(input_format or "").strip().lower()
    if normalized_format == "smiles":
        molecule = Chem.MolFromSmiles(normalized_structure)
    elif normalized_format == "molfile":
        molecule = Chem.MolFromMolBlock(
            normalized_structure,
            sanitize=True,
            removeHs=True,
            strictParsing=False,
        )
    else:
        raise ValidationError("input_format 必须是 smiles 或 molfile")

    if molecule is None:
        raise ValidationError("结构式解析失败, 请检查绘制内容")
    if molecule.GetNumAtoms() == 0:
        raise ValidationError("结构式不能为空")

    canonical_smiles = str(
        Chem.MolToSmiles(molecule, isomericSmiles=True, canonical=True) or ""
    ).strip()
    if canonical_smiles == "":
        raise ValidationError("结构式解析失败, 未生成有效 SMILES")

    inchikey = _mol_to_inchikey(rdkit_inchi, molecule, "query")
    if inchikey == "":
        raise ValidationError("结构式解析失败, 未生成有效 InChIKey")

    return ParsedStructure(
        molecule=molecule,
        canonical_smiles=canonical_smiles,
        inchikey=inchikey,
    )


def _parse_target_smiles(Chem: Any, row: Dict[str, Any]) -> Any:
    """
    功能:
        将库内行的 smiles 字段解析为 RDKit Mol, 无效时返回 None.
    参数:
        Chem: Any, RDKit Chem 模块.
        row: Dict[str, Any], 化学品库行数据.
    返回:
        Any, RDKit Mol 对象或 None.
    """
    smiles_text = str(row.get("smiles") or "").strip()
    if smiles_text == "":
        return None

    try:
        molecule = Chem.MolFromSmiles(smiles_text)
    except Exception as exc:
        logger.warning(
            "库内 SMILES 解析异常, 跳过该行: id=%s, smiles=%s, err=%s",
            row.get("id"),
            smiles_text,
            exc,
        )
        return None

    if molecule is None:
        logger.warning(
            "库内 SMILES 无法解析, 跳过该行: id=%s, smiles=%s",
            row.get("id"),
            smiles_text,
        )
        return None
    if molecule.GetNumAtoms() == 0:
        logger.warning(
            "库内 SMILES 为空结构, 跳过该行: id=%s, smiles=%s",
            row.get("id"),
            smiles_text,
        )
        return None
    return molecule


def filter_rows_by_structure(
    rows: List[Dict[str, Any]],
    structure: str,
    input_format: str,
    match_mode: str,
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    功能:
        按结构式过滤化学品库行.
        exact 模式使用完整 InChIKey 精确比对, substructure 模式使用 RDKit 子结构匹配.
    参数:
        rows: List[Dict[str, Any]], 待搜索的化学品库行.
        structure: str, 查询结构, 支持 SMILES 或 molfile.
        input_format: str, 输入格式, 支持 smiles 或 molfile.
        match_mode: str, 匹配方式, 支持 exact 或 substructure.
    返回:
        Tuple[str, List[Dict[str, Any]]], 规范化查询 SMILES 与命中行列表.
    异常:
        ValidationError: 输入结构或匹配方式非法.
        RuntimeError: RDKit 不可用.
    """
    normalized_mode = str(match_mode or "").strip().lower()
    if normalized_mode not in {"exact", "substructure"}:
        raise ValidationError("match_mode 必须是 exact 或 substructure")

    Chem, rdkit_inchi = _load_rdkit_modules()
    query = _parse_structure(Chem, rdkit_inchi, structure, input_format)
    matches: List[Dict[str, Any]] = []

    for row in rows:
        target_molecule = _parse_target_smiles(Chem, row)
        if target_molecule is None:
            continue

        if normalized_mode == "exact":
            target_inchikey = _mol_to_inchikey(
                rdkit_inchi,
                target_molecule,
                f"row_id={row.get('id')}",
            )
            if target_inchikey == query.inchikey:
                matches.append(row)
        else:
            try:
                is_match = target_molecule.HasSubstructMatch(
                    query.molecule,
                    useChirality=True,
                )
            except Exception as exc:
                logger.warning(
                    "子结构匹配异常, 跳过该行: id=%s, err=%s",
                    row.get("id"),
                    exc,
                )
                continue
            if is_match is True:
                matches.append(row)

    return query.canonical_smiles, matches
