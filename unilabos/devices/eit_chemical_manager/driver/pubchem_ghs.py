# -*- coding: utf-8 -*-
"""
功能:
    从 PubChem PUG-View 获取并解析 GHS 危害分类信息.
    输出字段用于化合物库内部安全提醒, 不替代正式 SDS.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests


logger = logging.getLogger("PubChemGHS")

_PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
_PUBCHEM_VIEW_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view"
_PUBCHEM_COMPOUND_BASE = "https://pubchem.ncbi.nlm.nih.gov/compound"

_H_STATEMENT_RE = re.compile(
    r"^(H\d{3}[A-Za-z]?)\s*(?:\(([^)]*)\))?\s*:\s*(.*?)(?:\s*\[([^\]]+)\])?$"
)
_P_CODE_RE = re.compile(r"P\d{3}(?:\+P?\d{3})*")
_GHS_CODE_RE = re.compile(r"(GHS\d{2})", re.IGNORECASE)


def lookup_pubchem_ghs(
    query: str,
    query_type: str,
    *,
    timeout: float = 15.0,
) -> Dict[str, Any]:
    """
    功能:
        按 CAS, 名称或 SMILES 查询 PubChem CID, 并返回规范化 GHS 危害字段.
    参数:
        query: str, 查询字符串.
        query_type: str, 查询类型, 支持 cas, name, smiles.
        timeout: float, HTTP 请求超时秒数.
    返回:
        Dict[str, Any], 可直接写入化学品行 extra_json 的危害字段. 未命中时返回空字典.
    """
    normalized_query = str(query or "").strip()
    normalized_type = str(query_type or "").strip().lower()
    if normalized_query == "":
        return {}

    cid = _resolve_pubchem_cid(normalized_query, normalized_type, timeout=timeout)
    if cid is None:
        logger.info("PubChem GHS 未解析到 CID: query=%s, type=%s", normalized_query, normalized_type)
        return {}

    return lookup_pubchem_ghs_by_cid(cid, timeout=timeout)


def lookup_pubchem_ghs_by_cid(
    cid: int,
    *,
    timeout: float = 15.0,
) -> Dict[str, Any]:
    """
    功能:
        按 PubChem CID 获取 GHS Classification 章节并解析为危害字段.
    参数:
        cid: int, PubChem CID.
        timeout: float, HTTP 请求超时秒数.
    返回:
        Dict[str, Any], 可直接写入化学品行 extra_json 的危害字段. 未命中时返回空字典.
    """
    if isinstance(cid, int) is False or cid <= 0:
        logger.warning("PubChem GHS CID 无效: %s", cid)
        return {}

    url = f"{_PUBCHEM_VIEW_BASE}/data/compound/{cid}/JSON?heading=GHS+Classification"
    try:
        response = requests.get(url, timeout=timeout)
        if response.status_code != 200:
            logger.info("PubChem GHS 查询失败: status=%s, cid=%s", response.status_code, cid)
            return {}
        payload = response.json()
    except (requests.RequestException, json.JSONDecodeError, ValueError) as exc:
        logger.warning("PubChem GHS 查询异常: cid=%s, err=%s", cid, exc)
        return {}

    return parse_pubchem_ghs_payload(payload, cid=cid)


def parse_pubchem_ghs_payload(payload: Dict[str, Any], *, cid: int) -> Dict[str, Any]:
    """
    功能:
        解析 PubChem PUG-View JSON 中的 GHS Classification 信息.
    参数:
        payload: Dict[str, Any], PUG-View 返回的 JSON 字典.
        cid: int, PubChem CID.
    返回:
        Dict[str, Any], 包含信号词, 图标, H 语句, P 语句和来源信息.
    """
    record = payload.get("Record") if isinstance(payload, dict) is True else None
    if isinstance(record, dict) is False:
        return {}

    section = _find_section(record, "GHS Classification")
    if section is None:
        return {}

    pictograms: List[str] = []
    signals: List[str] = []
    hazard_statements: List[Dict[str, str]] = []
    precautionary_codes: List[str] = []
    summaries: List[str] = []

    for item in section.get("Information", []) or []:
        if isinstance(item, dict) is False:
            continue

        item_name = str(item.get("Name") or "").strip()
        value = item.get("Value")
        strings = _extract_value_strings(value)

        if item_name == "Pictogram(s)":
            pictograms = _extend_unique(pictograms, _extract_pictogram_codes(value))
        elif item_name == "Signal":
            signals = _extend_unique(signals, [text for text in strings if text.strip() != ""])
        elif item_name == "GHS Hazard Statements":
            hazard_statements = _merge_hazard_statements(hazard_statements, strings)
        elif item_name == "Precautionary Statement Codes":
            precautionary_codes = _extend_unique(precautionary_codes, _extract_precautionary_codes(strings))
        elif item_name == "ECHA C&L Notifications Summary":
            summaries = _extend_unique(summaries, [text for text in strings if text.strip() != ""])

    if len(pictograms) == 0 and len(signals) == 0 and len(hazard_statements) == 0:
        return {}

    hazard_signal = _select_signal(signals)
    now_text = datetime.now(timezone.utc).isoformat(timespec="seconds")

    return {
        "hazard_signal": hazard_signal,
        "hazard_pictograms": pictograms,
        "hazard_statements": hazard_statements,
        "precautionary_codes": precautionary_codes,
        "hazard_source": "PubChem PUG-View",
        "hazard_source_cid": cid,
        "hazard_source_url": f"{_PUBCHEM_COMPOUND_BASE}/{cid}#section=GHS-Classification",
        "hazard_updated_at": now_text,
        "hazard_echa_summary": summaries,
    }


def _resolve_pubchem_cid(
    query: str,
    query_type: str,
    *,
    timeout: float,
) -> Optional[int]:
    """
    功能:
        按查询类型解析 PubChem CID.
    参数:
        query: str, 查询字符串.
        query_type: str, 查询类型.
        timeout: float, HTTP 请求超时秒数.
    返回:
        Optional[int], PubChem CID. 未命中返回 None.
    """
    if query_type == "smiles":
        return _pubchem_get_cid_by_smiles(query, timeout=timeout)
    return _pubchem_get_cid_by_name(query, timeout=timeout)


def _pubchem_get_cid_by_name(query: str, *, timeout: float) -> Optional[int]:
    """
    功能:
        通过 PubChem name 接口按 CAS 或名称解析 CID.
    参数:
        query: str, CAS 或英文名称.
        timeout: float, HTTP 请求超时秒数.
    返回:
        Optional[int], PubChem CID.
    """
    url = f"{_PUBCHEM_BASE}/compound/name/{requests.utils.quote(query)}/cids/JSON"
    try:
        response = requests.get(url, timeout=timeout)
        if response.status_code != 200:
            return None
        payload = response.json()
    except (requests.RequestException, json.JSONDecodeError, ValueError):
        return None

    cids = payload.get("IdentifierList", {}).get("CID", [])
    if isinstance(cids, list) is True and len(cids) > 0 and isinstance(cids[0], int) is True:
        return cids[0]
    return None


def _pubchem_get_cid_by_smiles(smiles: str, *, timeout: float) -> Optional[int]:
    """
    功能:
        通过 PubChem smiles 接口解析 CID.
    参数:
        smiles: str, SMILES 字符串.
        timeout: float, HTTP 请求超时秒数.
    返回:
        Optional[int], PubChem CID.
    """
    url = f"{_PUBCHEM_BASE}/compound/smiles/cids/JSON"
    try:
        response = requests.post(url, data={"smiles": smiles}, timeout=timeout)
        if response.status_code != 200:
            return None
        payload = response.json()
    except (requests.RequestException, json.JSONDecodeError, ValueError):
        return None

    cids = payload.get("IdentifierList", {}).get("CID", [])
    if isinstance(cids, list) is True and len(cids) > 0 and isinstance(cids[0], int) is True:
        return cids[0]
    return None


def _find_section(node: Dict[str, Any], heading: str) -> Optional[Dict[str, Any]]:
    """
    功能:
        在 PUG-View Section 树中递归查找指定标题.
    参数:
        node: Dict[str, Any], 当前节点.
        heading: str, 目标 TOCHeading.
    返回:
        Optional[Dict[str, Any]], 命中的 Section.
    """
    if str(node.get("TOCHeading") or "") == heading:
        return node

    for child in node.get("Section", []) or []:
        if isinstance(child, dict) is False:
            continue
        found = _find_section(child, heading)
        if found is not None:
            return found
    return None


def _extract_value_strings(value: Any) -> List[str]:
    """
    功能:
        从 PUG-View Value 字段中抽取 StringWithMarkup 文本.
    参数:
        value: Any, PUG-View Value 字段.
    返回:
        List[str], 文本列表.
    """
    if isinstance(value, dict) is False:
        return []

    result: List[str] = []
    for item in value.get("StringWithMarkup", []) or []:
        if isinstance(item, dict) is False:
            continue
        text = str(item.get("String") or "").strip()
        if text != "":
            result.append(text)
    return result


def _extract_pictogram_codes(value: Any) -> List[str]:
    """
    功能:
        从 Pictogram(s) 的 Markup URL 或文本中抽取 GHS 图标编码.
    参数:
        value: Any, PUG-View Value 字段.
    返回:
        List[str], 如 GHS02, GHS08.
    """
    codes: List[str] = []
    if isinstance(value, dict) is False:
        return codes

    for item in value.get("StringWithMarkup", []) or []:
        if isinstance(item, dict) is False:
            continue
        text = str(item.get("String") or "")
        codes = _extend_unique(codes, _extract_ghs_codes_from_text(text))
        for markup in item.get("Markup", []) or []:
            if isinstance(markup, dict) is False:
                continue
            markup_text = " ".join([
                str(markup.get("URL") or ""),
                str(markup.get("Extra") or ""),
            ])
            codes = _extend_unique(codes, _extract_ghs_codes_from_text(markup_text))
    return codes


def _extract_ghs_codes_from_text(text: str) -> List[str]:
    """
    功能:
        从任意文本中抽取 GHS 图标编码.
    参数:
        text: str, 原始文本.
    返回:
        List[str], GHS 图标编码列表.
    """
    result: List[str] = []
    for match in _GHS_CODE_RE.findall(text):
        result = _extend_unique(result, [match.upper()])
    return result


def _merge_hazard_statements(
    existing: List[Dict[str, str]],
    raw_lines: List[str],
) -> List[Dict[str, str]]:
    """
    功能:
        解析并合并 H 语句, 同一 H code 优先保留百分比更高或更完整的记录.
    参数:
        existing: List[Dict[str, str]], 已有 H 语句.
        raw_lines: List[str], 原始 H 语句文本.
    返回:
        List[Dict[str, str]], 合并后的 H 语句.
    """
    by_code: Dict[str, Dict[str, str]] = {item["code"]: item for item in existing if "code" in item}
    order = [item["code"] for item in existing if "code" in item]

    for raw_line in raw_lines:
        parsed = _parse_hazard_statement(raw_line)
        if parsed is None:
            continue
        code = parsed["code"]
        if code not in by_code:
            by_code[code] = parsed
            order.append(code)
            continue
        if _statement_rank(parsed) > _statement_rank(by_code[code]):
            by_code[code] = parsed

    return [by_code[code] for code in order]


def _parse_hazard_statement(raw_text: str) -> Optional[Dict[str, str]]:
    """
    功能:
        将单条 PubChem H 语句解析为结构化字段.
    参数:
        raw_text: str, 例如 H350 (100%): May cause cancer [Danger Carcinogenicity].
    返回:
        Optional[Dict[str, str]], 解析结果. 不符合格式时返回 None.
    """
    text = str(raw_text or "").strip()
    match = _H_STATEMENT_RE.match(text)
    if match is None:
        return None

    code, ratio, statement, category = match.groups()
    return {
        "code": code,
        "ratio": str(ratio or "").strip(),
        "statement": str(statement or "").strip(),
        "category": str(category or "").strip(),
        "raw": text,
    }


def _statement_rank(statement: Dict[str, str]) -> Tuple[int, int]:
    """
    功能:
        给 H 语句排序用的轻量权重, 优先保留含 100% 和分类信息的记录.
    参数:
        statement: Dict[str, str], H 语句结构.
    返回:
        Tuple[int, int], 排序权重.
    """
    ratio = str(statement.get("ratio") or "")
    category = str(statement.get("category") or "")
    ratio_rank = 1 if "100" in ratio else 0
    category_rank = 1 if category != "" else 0
    return ratio_rank, category_rank


def _extract_precautionary_codes(lines: List[str]) -> List[str]:
    """
    功能:
        从 P 语句文本中抽取 P code.
    参数:
        lines: List[str], 原始文本列表.
    返回:
        List[str], 去重后的 P code.
    """
    result: List[str] = []
    for line in lines:
        for code in _P_CODE_RE.findall(line):
            result = _extend_unique(result, [code])
    return result


def _select_signal(signals: List[str]) -> str:
    """
    功能:
        从多个来源的 Signal 中选择最强信号词.
    参数:
        signals: List[str], Signal 文本列表.
    返回:
        str, Danger, Warning 或空字符串.
    """
    normalized = [str(signal or "").strip() for signal in signals]
    if "Danger" in normalized:
        return "Danger"
    if "Warning" in normalized:
        return "Warning"
    if len(normalized) > 0:
        return normalized[0]
    return ""


def _extend_unique(values: List[Any], additions: List[Any]) -> List[Any]:
    """
    功能:
        按出现顺序追加去重值.
    参数:
        values: List[Any], 原始列表.
        additions: List[Any], 待追加列表.
    返回:
        List[Any], 去重后的新列表.
    """
    result = list(values)
    for item in additions:
        if item in result:
            continue
        result.append(item)
    return result
