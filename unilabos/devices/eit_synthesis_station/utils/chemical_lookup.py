# -*- coding: utf-8 -*-
"""
化合物在线查询模块

功能:
    根据 CAS 号或中英文名称, 从多个在线数据源查询化合物信息,
    包括 CAS 号, 英文名, 中文名, 分子量, 密度, 熔点和物态.
    数据源优先级: PubChem > Common Chemistry > ChemicalBook.
"""

import re
import logging
import json
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger("ChemicalLookup")

# ===================== 数据模型 =====================

@dataclass
class ChemicalInfo:
    """
    功能:
        化合物在线查询结果的统一数据容器.
        各数据源写入对应字段, 后续按优先级合并.
    """
    cas_number: Optional[str] = None
    substance_english_name: Optional[str] = None
    substance: Optional[str] = None           # 中文名
    molecular_weight: Optional[float] = None
    density: Optional[float] = None           # g/mL
    melting_point: Optional[float] = None     # celsius, 用于推断 physical_state
    physical_state: Optional[str] = None      # solid / liquid

    def to_dict(self) -> Dict:
        """
        功能:
            转换为字典, 过滤 None 和 melting_point(中间字段).
        返回:
            Dict, 仅包含非 None 的字段(不含 melting_point).
        """
        result = {}
        for key, val in asdict(self).items():
            if key == "melting_point":
                continue  # 内部字段, 不对外暴露
            if val is not None:
                result[key] = val
        return result


# ===================== 常量 =====================

CAS_PATTERN = re.compile(r"^\d{2,7}-\d{2}-\d$")

# PubChem API 基地址
_PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
_PUBCHEM_VIEW_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view"

# Common Chemistry API 基地址
_COMMON_CHEM_BASE = "https://commonchemistry.cas.org/api"

# ChemicalBook URL 模板
_CHEMBOOK_CN_URL = "https://www.chemicalbook.com/CAS_{cas}.htm"
_CHEMBOOK_EN_URL = "https://www.chemicalbook.com/CASEN_{cas}.htm"

# 通用浏览器请求头, 用于绕过反爬
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
}

# 密度解析正则
_DENSITY_WITH_UNIT_RE = re.compile(
    r"(\d+\.?\d*)\s*g\s*/\s*(?:mL|cm[³3]|cu\s*cm)",
    re.IGNORECASE,
)
_DENSITY_LEADING_FLOAT_RE = re.compile(r"^(\d+\.?\d*)")
_DENSITY_RELATIVE_RE = re.compile(
    r"(?:relative\s+density|specific\s+gravity)[^:]*:\s*(\d+\.?\d*)",
    re.IGNORECASE,
)
# 比重范围, 如 "0.80872～0.81601"
_DENSITY_RANGE_RE = re.compile(
    r"(\d+\.?\d*)\s*[～~–\-]\s*(\d+\.?\d*)",
)

# 熔点解析正则
_MP_CELSIUS_RE = re.compile(r"(-?\d+\.?\d*)\s*°?\s*C(?:\b|[^a-zA-Z])", re.IGNORECASE)
_MP_FAHRENHEIT_RE = re.compile(r"(-?\d+\.?\d*)\s*°?\s*F(?:\b|[^a-zA-Z])", re.IGNORECASE)
# 范围格式: "138-140", "101-104 °C", "134-136°C"
_MP_RANGE_RE = re.compile(
    r"(-?\d+\.?\d*)\s*[～~–\-]\s*(-?\d+\.?\d*)\s*°?\s*C?",
    re.IGNORECASE,
)

# 密度过滤关键词 (出现则跳过该条目)
_DENSITY_SKIP_KEYWORDS = ["enthalpy", "latent heat"]

# ChemicalBook 中文页属性正则 (HTML 中提取)
_CB_CN_NAME_RE = re.compile(
    r"中文名称\s*(?:</[^>]+>)?\s*(?:<[^>]+>)*\s*([^<]+)",
    re.IGNORECASE,
)
# 英文页属性正则 (方括号标记, HTML 中 [density&nbsp;] 格式)
# 匹配 [density&nbsp;] 或 [density] 后跟 <br> 再跟属性值
_CB_EN_DENSITY_RE = re.compile(
    r"\[density\s*(?:&nbsp;)*\s*\].*?<br\s*/?>.*?<br\s*/?>\s*([^<]+)",
    re.IGNORECASE | re.DOTALL,
)
_CB_EN_MP_RE = re.compile(
    r"\[Melting\s+point\s*(?:&nbsp;)*\s*\].*?<br\s*/?>.*?<br\s*/?>\s*([^<]+)",
    re.IGNORECASE | re.DOTALL,
)
_CB_EN_NAME_RE = re.compile(
    r"\[Name\s*(?:&nbsp;)*\s*\].*?<br\s*/?>.*?<br\s*/?>\s*([^<]+)",
    re.IGNORECASE | re.DOTALL,
)


# ===================== 工具函数 =====================

def is_cas_number(query: str) -> bool:
    """
    功能:
        判断输入字符串是否为合法的 CAS 号格式.
    参数:
        query: str, 用户输入的查询字符串.
    返回:
        bool, True 表示匹配 CAS 号格式.
    """
    return CAS_PATTERN.match(query.strip()) is not None


def _fahrenheit_to_celsius(f: float) -> float:
    """华氏度转摄氏度"""
    return round((f - 32) * 5 / 9, 2)


def _extract_cas_from_synonyms(synonyms: List[str]) -> Optional[str]:
    """
    功能:
        从 PubChem 同义词列表中提取 CAS 号.
        CAS 号格式: 2~7位数字-2位数字-1位数字.
    参数:
        synonyms: List[str], PubChem 返回的同义词列表.
    返回:
        Optional[str], 找到的第一个 CAS 号, 未找到返回 None.
    """
    for name in synonyms:
        name = name.strip()
        if CAS_PATTERN.match(name):
            return name
    return None


# ===================== PubChem 查询 =====================

def _pubchem_get_cid(query: str, timeout: float = 15.0) -> Optional[int]:
    """
    功能:
        通过名称或 CAS 号查询 PubChem 获取化合物 CID.
    参数:
        query: str, CAS 号或化合物名称.
        timeout: float, 请求超时秒数.
    返回:
        Optional[int], 化合物 CID, 查询失败返回 None.
    """
    url = f"{_PUBCHEM_BASE}/compound/name/{requests.utils.quote(query)}/cids/JSON"
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code != 200:
            logger.debug("PubChem CID 查询失败: status=%s, query=%s", resp.status_code, query)
            return None
        data = resp.json()
        cids = data.get("IdentifierList", {}).get("CID", [])
        if cids:
            return cids[0]
    except (requests.RequestException, json.JSONDecodeError, ValueError) as exc:
        logger.warning("PubChem CID 查询异常: %s", exc)
    return None


def _pubchem_get_properties(cid: int, timeout: float = 15.0) -> Tuple[Optional[str], Optional[float]]:
    """
    功能:
        根据 CID 获取化合物的 IUPAC 名称和分子量.
    参数:
        cid: int, PubChem CID.
        timeout: float, 请求超时秒数.
    返回:
        (iupac_name, molecular_weight), 各为 Optional.
    """
    url = f"{_PUBCHEM_BASE}/compound/cid/{cid}/property/MolecularWeight,IUPACName/JSON"
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code != 200:
            return None, None
        data = resp.json()
        props = data.get("PropertyTable", {}).get("Properties", [{}])[0]
        iupac = props.get("IUPACName")
        mw_str = props.get("MolecularWeight")
        mw = float(mw_str) if mw_str is not None else None
        return iupac, mw
    except (requests.RequestException, json.JSONDecodeError, ValueError, IndexError) as exc:
        logger.warning("PubChem 属性查询异常: %s", exc)
    return None, None


def _pubchem_get_synonyms(cid: int, timeout: float = 15.0) -> List[str]:
    """
    功能:
        根据 CID 获取化合物的所有同义词列表 (含 CAS 号).
    参数:
        cid: int, PubChem CID.
        timeout: float, 请求超时秒数.
    返回:
        List[str], 同义词列表, 查询失败返回空列表.
    """
    url = f"{_PUBCHEM_BASE}/compound/cid/{cid}/synonyms/JSON"
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code != 200:
            return []
        data = resp.json()
        tables = data.get("InformationList", {}).get("Information", [])
        if tables:
            return tables[0].get("Synonym", [])
    except (requests.RequestException, json.JSONDecodeError, ValueError) as exc:
        logger.warning("PubChem 同义词查询异常: %s", exc)
    return []


def _find_sections(data: dict, heading: str) -> list:
    """
    功能:
        递归搜索 PUG-View JSON 中匹配指定 heading 的 Section 节点.
    参数:
        data: dict, 当前层级的 JSON 数据.
        heading: str, 目标 Section 标题.
    返回:
        list, 匹配的 Section 列表.
    """
    results = []
    sections = data.get("Section", [])
    for sec in sections:
        if sec.get("TOCHeading", "") == heading:
            results.append(sec)
        results.extend(_find_sections(sec, heading))
    return results


def _extract_density_from_info_list(info_list: list) -> Optional[float]:
    """
    功能:
        从 PubChem Density Information 列表中提取密度值 (g/mL).
        按优先级: 结构化 Number > 带单位字符串 > 开头浮点数 > 相对密度.
    参数:
        info_list: list, PubChem PUG-View Density 的 Information 数组.
    返回:
        Optional[float], 密度值, 未提取到返回 None.
    """
    # 第一遍: 检查结构化 Number+Unit 格式
    for item in info_list:
        value = item.get("Value", {})
        if "Number" in value:
            nums = value["Number"]
            if isinstance(nums, list) and len(nums) > 0:
                val = nums[0]
                if 0.3 <= val <= 25.0:
                    return round(val, 4)

    # 第二遍: 匹配带 g/mL 或 g/cm³ 单位的字符串
    for item in info_list:
        value = item.get("Value", {})
        for swm in value.get("StringWithMarkup", []):
            text = swm.get("String", "")
            text_lower = text.lower()
            # 跳过混合描述
            if any(kw in text_lower for kw in _DENSITY_SKIP_KEYWORDS):
                continue
            # 跳过不等式
            if text.strip().startswith("<") or text.strip().startswith(">"):
                continue
            match = _DENSITY_WITH_UNIT_RE.search(text)
            if match is not None:
                return round(float(match.group(1)), 4)

    # 第三遍: 匹配字符串开头的浮点数 (范围 0.3-25.0)
    for item in info_list:
        value = item.get("Value", {})
        for swm in value.get("StringWithMarkup", []):
            text = swm.get("String", "")
            text_lower = text.lower()
            if any(kw in text_lower for kw in _DENSITY_SKIP_KEYWORDS):
                continue
            if text.strip().startswith("<") or text.strip().startswith(">"):
                continue
            # 跳过 relative density / specific gravity (留到第四遍)
            if "relative density" in text_lower or "specific gravity" in text_lower:
                continue
            match = _DENSITY_LEADING_FLOAT_RE.match(text.strip())
            if match is not None:
                val = float(match.group(1))
                if 0.3 <= val <= 25.0:
                    return round(val, 4)

    # 第四遍: 回退 - 从 "Relative density" / "Specific Gravity" 条目提取
    for item in info_list:
        value = item.get("Value", {})
        for swm in value.get("StringWithMarkup", []):
            text = swm.get("String", "")
            text_lower = text.lower()
            if "relative density" in text_lower or "specific gravity" in text_lower:
                # 尝试匹配范围 (如 "0.80872～0.81601")
                range_match = _DENSITY_RANGE_RE.search(text)
                if range_match is not None:
                    low = float(range_match.group(1))
                    high = float(range_match.group(2))
                    return round((low + high) / 2, 4)
                # 尝试匹配单个数值 (如 "Relative density (water = 1): 0.79")
                rel_match = _DENSITY_RELATIVE_RE.search(text)
                if rel_match is not None:
                    return round(float(rel_match.group(1)), 4)
                # 最后尝试提取最后一个浮点数
                all_floats = re.findall(r"(\d+\.?\d*)", text)
                if all_floats:
                    val = float(all_floats[-1])
                    if 0.3 <= val <= 25.0:
                        return round(val, 4)

    return None


def _extract_melting_point_from_info_list(info_list: list) -> Optional[float]:
    """
    功能:
        从 PubChem Melting Point Information 列表中提取熔点 (celsius).
        按优先级: 结构化 Number > °C 字符串 > °F 字符串(转换) > 无单位范围.
    参数:
        info_list: list, PubChem PUG-View Melting Point 的 Information 数组.
    返回:
        Optional[float], 熔点值(celsius), 未提取到返回 None.
    """
    # 第一遍: 检查结构化 Number+Unit 格式
    for item in info_list:
        value = item.get("Value", {})
        if "Number" in value and "Unit" in value:
            nums = value["Number"]
            unit = value.get("Unit", "")
            if isinstance(nums, list) and len(nums) > 0:
                temp = nums[0]
                if "F" in unit and "C" not in unit:
                    temp = _fahrenheit_to_celsius(temp)
                return round(temp, 2)

    # 收集各类匹配结果
    celsius_values = []
    fahrenheit_values = []
    range_values = []

    for item in info_list:
        value = item.get("Value", {})
        for swm in value.get("StringWithMarkup", []):
            text = swm.get("String", "")

            # 尝试匹配范围 + °C (如 "134-136°C", "101-104 °C(lit.)")
            range_c_match = re.search(
                r"(-?\d+\.?\d*)\s*[～~–\-]\s*(-?\d+\.?\d*)\s*°?\s*C",
                text, re.IGNORECASE,
            )
            if range_c_match is not None:
                low = float(range_c_match.group(1))
                high = float(range_c_match.group(2))
                celsius_values.append(round((low + high) / 2, 2))
                continue

            # 尝试匹配单个 °C 值 (如 "-114.14 °C", "135 °C")
            c_match = re.search(r"(-?\d+\.?\d*)\s*°\s*C", text)
            if c_match is not None:
                celsius_values.append(float(c_match.group(1)))
                continue

            # 尝试匹配 °F 值 (如 "-173.4 °F")
            f_match = re.search(r"(-?\d+\.?\d*)\s*°\s*F", text)
            if f_match is not None:
                f_val = float(f_match.group(1))
                fahrenheit_values.append(_fahrenheit_to_celsius(f_val))
                continue

            # 尝试匹配无单位范围 (如 "138-140"), 假设为 °C
            range_match = re.match(
                r"\s*(-?\d+\.?\d*)\s*[～~–\-]\s*(-?\d+\.?\d*)\s*$",
                text.strip(),
            )
            if range_match is not None:
                low = float(range_match.group(1))
                high = float(range_match.group(2))
                range_values.append(round((low + high) / 2, 2))

    # 按优先级返回: °C > °F > 无单位范围
    if celsius_values:
        return celsius_values[0]
    if fahrenheit_values:
        return fahrenheit_values[0]
    if range_values:
        return range_values[0]
    return None


def _pubchem_get_experimental(cid: int, timeout: float = 15.0) -> Tuple[Optional[float], Optional[float]]:
    """
    功能:
        通过 PUG-View API 获取化合物的实验密度和熔点.
    参数:
        cid: int, PubChem CID.
        timeout: float, 请求超时秒数.
    返回:
        (density, melting_point), 各为 Optional[float].
    """
    url = (
        f"{_PUBCHEM_VIEW_BASE}/data/compound/{cid}/JSON"
        f"?heading=Experimental+Properties"
    )
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code != 200:
            logger.debug("PubChem PUG-View 查询失败: status=%s, cid=%s", resp.status_code, cid)
            return None, None
        data = resp.json()
        record = data.get("Record", {})

        density = None
        melting_point = None

        # 在返回的嵌套 Section 中搜索 Density 和 Melting Point
        density_sections = _find_sections(record, "Density")
        for sec in density_sections:
            info_list = sec.get("Information", [])
            density = _extract_density_from_info_list(info_list)
            if density is not None:
                break

        mp_sections = _find_sections(record, "Melting Point")
        for sec in mp_sections:
            info_list = sec.get("Information", [])
            melting_point = _extract_melting_point_from_info_list(info_list)
            if melting_point is not None:
                break

        return density, melting_point

    except (requests.RequestException, json.JSONDecodeError, ValueError) as exc:
        logger.warning("PubChem PUG-View 查询异常: %s", exc)
    return None, None


def _query_pubchem(query: str, timeout: float = 15.0) -> Optional[ChemicalInfo]:
    """
    功能:
        通过 PubChem 查询化合物完整信息.
        依次获取 CID, 属性, 同义词(含 CAS), 实验数据(密度/熔点).
    参数:
        query: str, CAS 号或化合物名称.
        timeout: float, 单次请求超时秒数.
    返回:
        Optional[ChemicalInfo], 查询成功返回填充后的对象, 失败返回 None.
    """
    logger.info("开始 PubChem 查询: %s", query)

    cid = _pubchem_get_cid(query, timeout)
    if cid is None:
        logger.info("PubChem 未找到化合物: %s", query)
        return None

    logger.debug("PubChem 找到 CID=%s, 开始获取详细信息", cid)
    info = ChemicalInfo()

    # 获取基础属性 (IUPAC名, 分子量)
    iupac, mw = _pubchem_get_properties(cid, timeout)
    info.substance_english_name = iupac
    info.molecular_weight = mw

    # 获取同义词 (提取 CAS 号)
    synonyms = _pubchem_get_synonyms(cid, timeout)
    info.cas_number = _extract_cas_from_synonyms(synonyms)

    # 获取实验密度和熔点
    density, mp = _pubchem_get_experimental(cid, timeout)
    info.density = density
    info.melting_point = mp

    logger.info(
        "PubChem 查询完成: CAS=%s, 名称=%s, MW=%s, 密度=%s, 熔点=%s",
        info.cas_number, info.substance_english_name,
        info.molecular_weight, info.density, info.melting_point,
    )
    return info


# ===================== Common Chemistry 查询 =====================

def _query_common_chemistry(query: str, timeout: float = 10.0) -> Optional[ChemicalInfo]:
    """
    功能:
        通过 CAS Common Chemistry API 查询化合物基础信息.
        先搜索获取 CAS RN, 再获取详情 (名称, 分子量).
    参数:
        query: str, CAS 号或化合物名称.
        timeout: float, 请求超时秒数.
    返回:
        Optional[ChemicalInfo], 仅包含 cas_number, substance_english_name, molecular_weight.
    """
    logger.info("开始 Common Chemistry 查询: %s", query)
    headers = {**_BROWSER_HEADERS, "Accept": "application/json"}

    # 第一步: 搜索获取 CAS RN
    search_url = f"{_COMMON_CHEM_BASE}/search?q={requests.utils.quote(query)}"
    try:
        resp = requests.get(search_url, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            logger.debug("Common Chemistry 搜索失败: status=%s", resp.status_code)
            return None
        data = resp.json()
        results = data.get("results", [])
        if not results:
            logger.info("Common Chemistry 未找到化合物: %s", query)
            return None
        cas_rn = results[0].get("rn", "")
        if not cas_rn:
            return None
    except (requests.RequestException, json.JSONDecodeError, ValueError) as exc:
        logger.warning("Common Chemistry 搜索异常: %s", exc)
        return None

    # 第二步: 获取详细信息
    detail_url = f"{_COMMON_CHEM_BASE}/detail?cas_rn={cas_rn}"
    try:
        resp = requests.get(detail_url, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            # 至少返回搜索到的 CAS 号
            info = ChemicalInfo(cas_number=cas_rn)
            return info
        data = resp.json()

        info = ChemicalInfo()
        info.cas_number = data.get("rn", cas_rn)
        info.substance_english_name = data.get("name")
        mw_str = data.get("molecularMass")
        if mw_str is not None:
            try:
                info.molecular_weight = float(mw_str)
            except (ValueError, TypeError):
                pass

        logger.info(
            "Common Chemistry 查询完成: CAS=%s, 名称=%s, MW=%s",
            info.cas_number, info.substance_english_name, info.molecular_weight,
        )
        return info

    except (requests.RequestException, json.JSONDecodeError, ValueError) as exc:
        logger.warning("Common Chemistry 详情查询异常: %s", exc)
        # 至少返回搜索到的 CAS 号
        return ChemicalInfo(cas_number=cas_rn)


# ===================== ChemicalBook 查询 =====================

def _fetch_chemicalbook_page(url: str, timeout: float = 10.0) -> Optional[str]:
    """
    功能:
        获取 ChemicalBook 页面 HTML 内容.
        先用 requests + 浏览器请求头尝试, 失败则尝试 playwright.
    参数:
        url: str, 目标页面 URL.
        timeout: float, requests 超时秒数.
    返回:
        Optional[str], 页面 HTML 文本, 获取失败返回 None.
    """
    # 策略 1: requests + 浏览器请求头
    try:
        resp = requests.get(url, headers=_BROWSER_HEADERS, timeout=timeout)
        if resp.status_code == 200:
            resp.encoding = resp.apparent_encoding
            return resp.text
        logger.debug("ChemicalBook requests 请求失败: status=%s, url=%s", resp.status_code, url)
    except requests.RequestException as exc:
        logger.debug("ChemicalBook requests 异常: %s", exc)

    # 策略 2: playwright 无头浏览器 (按需动态导入)
    try:
        from playwright.sync_api import sync_playwright
        logger.info("requests 获取 ChemicalBook 失败, 尝试 playwright: %s", url)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            html = page.content()
            browser.close()
            if html:
                return html
    except ImportError:
        logger.warning(
            "playwright 未安装, 无法通过无头浏览器获取 ChemicalBook 中文页. "
            "如需中文名功能, 请运行: pip install playwright && playwright install chromium"
        )
    except Exception as exc:
        logger.warning("playwright 获取 ChemicalBook 页面失败: %s", exc)

    return None


def _parse_chemicalbook_cn_name(html: str) -> Optional[str]:
    """
    功能:
        从 ChemicalBook 中文页 HTML 中提取化合物中文名称.
    参数:
        html: str, 页面 HTML 文本.
    返回:
        Optional[str], 中文名称, 未提取到返回 None.
    """
    # 多种可能的 HTML 结构
    patterns = [
        # 模式1: <td>中文名称</td><td>xxx</td>
        re.compile(r"中文名称\s*</\s*td>\s*<td[^>]*>\s*([^<]+)", re.IGNORECASE),
        # 模式2: 中文名称：xxx 或 中文名称:xxx
        re.compile(r"中文名称\s*[：:]\s*([^\n<]+)", re.IGNORECASE),
        # 模式3: <span>中文名称</span> ... <span>xxx</span>
        re.compile(r"中文名称\s*</\s*span>\s*(?:</[^>]+>\s*)*<[^>]+>\s*([^<]+)", re.IGNORECASE),
        # 模式4: <span>中文名称</span> xxx
        re.compile(r"中文名称\s*</\s*span>\s*([^<\n]+)", re.IGNORECASE),
        # 模式4: 中文名: xxx
        re.compile(r"中文名\s*[：:]\s*([^\n<]+)", re.IGNORECASE),
    ]
    for pattern in patterns:
        match = pattern.search(html)
        if match is not None:
            name = match.group(1).strip()
            # 确认包含中文字符
            if re.search(r"[\u4e00-\u9fff]", name):
                return name
    return None


def _parse_chemicalbook_en_density(html: str) -> Optional[float]:
    """
    功能:
        从 ChemicalBook 英文页 HTML 中提取密度值.
    参数:
        html: str, 英文页 HTML 文本.
    返回:
        Optional[float], 密度值 (g/mL), 未提取到返回 None.
    """
    match = _CB_EN_DENSITY_RE.search(html)
    if match is None:
        return None
    text = match.group(1).strip()

    # 先匹配带单位的值 (如 "0.789 g/mL at 20 °C")
    unit_match = _DENSITY_WITH_UNIT_RE.search(text)
    if unit_match is not None:
        return round(float(unit_match.group(1)), 4)

    # 再匹配开头的浮点数
    leading_match = _DENSITY_LEADING_FLOAT_RE.match(text)
    if leading_match is not None:
        val = float(leading_match.group(1))
        if 0.3 <= val <= 25.0:
            return round(val, 4)

    return None


def _parse_chemicalbook_en_melting_point(html: str) -> Optional[float]:
    """
    功能:
        从 ChemicalBook 英文页 HTML 中提取熔点值.
    参数:
        html: str, 英文页 HTML 文本.
    返回:
        Optional[float], 熔点值 (celsius), 未提取到返回 None.
    """
    match = _CB_EN_MP_RE.search(html)
    if match is None:
        return None
    text = match.group(1).strip()

    # 先匹配范围 + °C (如 "134-136°C")
    range_c = re.search(r"(-?\d+\.?\d*)\s*[～~–\-]\s*(-?\d+\.?\d*)\s*°?\s*C", text, re.IGNORECASE)
    if range_c is not None:
        low = float(range_c.group(1))
        high = float(range_c.group(2))
        return round((low + high) / 2, 2)

    # 匹配单个 °C 值 (如 "-114°C")
    c_match = re.search(r"(-?\d+\.?\d*)\s*°?\s*C", text, re.IGNORECASE)
    if c_match is not None:
        return float(c_match.group(1))

    # 匹配 °F 值并转换
    f_match = re.search(r"(-?\d+\.?\d*)\s*°?\s*F", text, re.IGNORECASE)
    if f_match is not None:
        return _fahrenheit_to_celsius(float(f_match.group(1)))

    return None


def _query_chemicalbook(cas: str, timeout: float = 10.0) -> Optional[ChemicalInfo]:
    """
    功能:
        通过 ChemicalBook 查询化合物信息.
        中文页获取中文名, 英文页获取密度和熔点.
    参数:
        cas: str, CAS 号 (如 "64-17-5").
        timeout: float, requests 超时秒数.
    返回:
        Optional[ChemicalInfo], 查询到的化合物信息.
    """
    if not cas:
        return None

    logger.info("开始 ChemicalBook 查询: CAS=%s", cas)
    info = ChemicalInfo()

    # 获取中文页 (提取中文名)
    cn_url = _CHEMBOOK_CN_URL.format(cas=cas)
    cn_html = _fetch_chemicalbook_page(cn_url, timeout)
    if cn_html is not None:
        info.substance = _parse_chemicalbook_cn_name(cn_html)
        if info.substance is not None:
            logger.info("ChemicalBook 中文名: %s", info.substance)
        else:
            logger.debug("ChemicalBook 中文页未能提取中文名")
    else:
        logger.debug("ChemicalBook 中文页获取失败")

    # 获取英文页 (提取密度和熔点)
    en_url = _CHEMBOOK_EN_URL.format(cas=cas)
    en_html = _fetch_chemicalbook_page(en_url, timeout)
    if en_html is not None:
        info.density = _parse_chemicalbook_en_density(en_html)
        info.melting_point = _parse_chemicalbook_en_melting_point(en_html)

        # 尝试从英文页提取英文名
        name_match = _CB_EN_NAME_RE.search(en_html)
        if name_match is not None:
            en_name = name_match.group(1).strip().split("\n")[0].strip()
            if en_name:
                info.substance_english_name = en_name

        logger.info(
            "ChemicalBook 英文页: 密度=%s, 熔点=%s",
            info.density, info.melting_point,
        )
    else:
        logger.debug("ChemicalBook 英文页获取失败")

    # 判断是否获取到任何有效数据
    has_data = any([
        info.substance, info.density, info.melting_point, info.substance_english_name,
    ])
    return info if has_data else None


# ===================== 合并与物态判断 =====================

def _merge_results(
    pubchem: Optional[ChemicalInfo],
    common_chem: Optional[ChemicalInfo],
    chemicalbook: Optional[ChemicalInfo],
) -> ChemicalInfo:
    """
    功能:
        按优先级合并多个数据源的查询结果.
        通用规则: 每个字段取第一个非 None 值.
        特殊规则: 中文名(substance) 优先取 ChemicalBook 结果.
    参数:
        pubchem: Optional[ChemicalInfo], PubChem 查询结果.
        common_chem: Optional[ChemicalInfo], Common Chemistry 查询结果.
        chemicalbook: Optional[ChemicalInfo], ChemicalBook 查询结果.
    返回:
        ChemicalInfo, 合并后的结果.
    """
    merged = ChemicalInfo()

    # 中文名优先取 ChemicalBook (唯一可靠中文源)
    if chemicalbook is not None and chemicalbook.substance is not None:
        merged.substance = chemicalbook.substance

    # 其余字段按 [common_chem, pubchem, chemicalbook] 的顺序 (CAS 号以 CAS 官方为准)
    # cas_number: Common Chemistry > PubChem > ChemicalBook
    sources_for_cas = [common_chem, pubchem, chemicalbook]
    # substance_english_name: PubChem > Common Chemistry > ChemicalBook
    sources_for_en_name = [pubchem, common_chem, chemicalbook]
    # molecular_weight: PubChem > Common Chemistry
    sources_for_mw = [pubchem, common_chem]
    # density: PubChem > ChemicalBook
    sources_for_density = [pubchem, chemicalbook]
    # melting_point: PubChem > ChemicalBook
    sources_for_mp = [pubchem, chemicalbook]

    for src in sources_for_cas:
        if src is not None and src.cas_number is not None and merged.cas_number is None:
            merged.cas_number = src.cas_number

    for src in sources_for_en_name:
        if src is not None and src.substance_english_name is not None and merged.substance_english_name is None:
            merged.substance_english_name = src.substance_english_name

    for src in sources_for_mw:
        if src is not None and src.molecular_weight is not None and merged.molecular_weight is None:
            merged.molecular_weight = src.molecular_weight

    for src in sources_for_density:
        if src is not None and src.density is not None and merged.density is None:
            merged.density = src.density

    for src in sources_for_mp:
        if src is not None and src.melting_point is not None and merged.melting_point is None:
            merged.melting_point = src.melting_point

    return merged


def _determine_physical_state(melting_point: Optional[float]) -> str:
    """
    功能:
        根据熔点推断物质的物态.
    参数:
        melting_point: Optional[float], 熔点 (celsius).
    返回:
        str, "solid" / "liquid" / "".
    """
    if melting_point is None:
        return ""
    if melting_point > 25.0:
        return "solid"
    return "liquid"


# ===================== 对外统一入口 =====================

def lookup_chemical(query: str) -> Optional[ChemicalInfo]:
    """
    功能:
        对外统一入口. 根据输入判断 CAS 号或名称, 依次查询多个数据源,
        按优先级合并结果并推断物态.
    参数:
        query: str, CAS 号或化合物中英文名称.
    返回:
        Optional[ChemicalInfo], 合并后的化合物信息, 所有源都查询失败则返回 None.
    """
    query = query.strip()
    if not query:
        logger.warning("查询字符串为空")
        return None

    is_cas = is_cas_number(query)
    logger.info("开始化合物查询: query=%s, 类型=%s", query, "CAS号" if is_cas else "名称")

    # 查询各数据源 (各自独立, 互不影响)
    pubchem_result = None
    common_chem_result = None
    chemicalbook_result = None

    # 源 1: PubChem
    try:
        pubchem_result = _query_pubchem(query)
    except Exception as exc:
        logger.warning("PubChem 查询意外异常: %s", exc)

    # 源 2: Common Chemistry
    try:
        common_chem_result = _query_common_chemistry(query)
    except Exception as exc:
        logger.warning("Common Chemistry 查询意外异常: %s", exc)

    # 确定用于 ChemicalBook 查询的 CAS 号
    cas_for_chembook = None
    if is_cas:
        cas_for_chembook = query
    else:
        # 从其他源的结果中获取 CAS 号
        if common_chem_result is not None and common_chem_result.cas_number is not None:
            cas_for_chembook = common_chem_result.cas_number
        elif pubchem_result is not None and pubchem_result.cas_number is not None:
            cas_for_chembook = pubchem_result.cas_number

    # 源 3: ChemicalBook (需要 CAS 号)
    if cas_for_chembook is not None:
        try:
            chemicalbook_result = _query_chemicalbook(cas_for_chembook)
        except Exception as exc:
            logger.warning("ChemicalBook 查询意外异常: %s", exc)
    else:
        logger.info("未获取到 CAS 号, 跳过 ChemicalBook 查询")

    # 检查是否所有源都失败
    if pubchem_result is None and common_chem_result is None and chemicalbook_result is None:
        logger.warning("所有数据源均未查询到化合物: %s", query)
        return None

    # 合并结果
    merged = _merge_results(pubchem_result, common_chem_result, chemicalbook_result)

    # 推断物态
    merged.physical_state = _determine_physical_state(merged.melting_point)

    logger.info(
        "化合物查询完成: CAS=%s, 英文名=%s, 中文名=%s, MW=%s, "
        "密度=%s, 熔点=%s, 物态=%s",
        merged.cas_number, merged.substance_english_name, merged.substance,
        merged.molecular_weight, merged.density, merged.melting_point,
        merged.physical_state,
    )
    return merged
