#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    基于 GC-FID 积分报告和实验方案, 计算各样品的产率.
    支持 ECN 法, 标准曲线法和响应因子法三种计算方式.
    从 chemical_list.xlsx 自动推算内标摩尔量, 无需手动输入浓度.
参数:
    无.
返回:
    无.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import openpyxl
import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from pysmiles.read_smiles import read_smiles

from .ecn import smiles2carbontypes, ecn_dct, class_dct

logger = logging.getLogger(__name__)
YIELD_CONFIG_SHEET_NAME = "GC产率计算"


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class TargetProduct:
    """
    功能:
        存储单个目标产物的配置信息.
    参数:
        name: 目标产物名称.
        smiles: SMILES 字符串.
        formula: 分子式 (从 SMILES 自动推导).
        ecn: 有效碳数 (从 SMILES 自动计算).
        expected_rt: 预期保留时间(min), None 表示使用分子式匹配.
        applicable_experiments: 适用实验编号列表, 如 [1,2,3].
        equivalent: 目标产物当量(eq), 默认1.0. 理论产物量 = 反应规模 * equivalent.
    返回:
        TargetProduct.
    """
    name: str = ""
    smiles: str = ""
    formula: str = ""
    ecn: float = 0.0
    expected_rt: Optional[float] = None
    applicable_experiments: List[int] = field(default_factory=list)
    equivalent: float = 1.0


@dataclass
class YieldCalcConfig:
    """
    功能:
        存储产率计算的完整配置, 从实验方案和 chemical_list 共同构建.
    参数:
        is_name: 内标名称 (从原参数 Sheet 的 "内标种类" 读取).
        is_smiles: 内标 SMILES (从 "GC产率计算" Sheet 读取).
        is_formula: 内标分子式 (自动推导).
        is_ecn: 内标 ECN (自动计算).
        is_expected_rt: 内标预期保留时间(min), 可选.
        is_amount: 内标用量原始值 (μL 或 mg).
        is_moles: 内标实际加入摩尔量(mol), 从 chemical_list 推算.
        reaction_scale_mmol: 反应规模(mmol).
        calc_method: 产率计算方法, "ECN" / "标准曲线" / "响应因子".
        curve_slope: 标准曲线斜率.
        curve_intercept: 标准曲线截距.
        response_factor: 响应因子.
        products: 目标产物列表, 各自有适用实验范围.
    返回:
        YieldCalcConfig.
    """
    # 内标信息
    is_name: str = ""
    is_smiles: str = ""
    is_formula: str = ""
    is_ecn: float = 0.0
    is_expected_rt: Optional[float] = None
    is_amount: float = 0.0
    is_moles: float = 0.0
    # 反应信息
    reaction_scale_mmol: float = 0.0
    # 计算方法
    calc_method: str = "ECN"
    curve_slope: Optional[float] = None
    curve_intercept: Optional[float] = None
    response_factor: Optional[float] = None
    # 目标产物
    products: List[TargetProduct] = field(default_factory=list)


@dataclass
class SampleYieldResult:
    """
    功能:
        存储单个 (样品 x 产物) 组合的产率计算结果.
    参数:
        sample_name: 样品名, 如 "729-1".
        product_name: 目标产物名称.
        product_fid_rt: 产物 FID 保留时间(min).
        product_fid_area: 产物 FID 峰面积.
        product_match_compound: 匹配到的 NIST 化合物名.
        is_fid_rt: 内标 FID 保留时间(min).
        is_fid_area: 内标 FID 峰面积.
        is_match_compound: 内标匹配到的 NIST 化合物名.
        area_ratio: FID 面积比 (产物/内标).
        ecn_product: 产物 ECN.
        ecn_is: 内标 ECN.
        molar_ratio: 摩尔比 (产物/内标).
        n_product_mol: 产物物质的量(mol).
        yield_percent: 产率(%).
        match_method: 峰匹配方式, "rt" 或 "formula".
        warnings: 警告信息列表.
    返回:
        SampleYieldResult.
    """
    sample_name: str = ""
    product_name: str = ""
    # 产物峰
    product_fid_rt: Optional[float] = None
    product_fid_area: Optional[float] = None
    product_match_compound: str = ""
    # 内标峰
    is_fid_rt: Optional[float] = None
    is_fid_area: Optional[float] = None
    is_match_compound: str = ""
    # 计算结果
    area_ratio: Optional[float] = None
    ecn_product: Optional[float] = None
    ecn_is: Optional[float] = None
    molar_ratio: Optional[float] = None
    n_product_mol: Optional[float] = None
    yield_percent: Optional[float] = None
    match_method: str = ""
    warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 核心类
# ---------------------------------------------------------------------------

class YieldCalculator:
    """
    功能:
        基于 GC-FID 积分报告和实验方案计算各样品的产率.
        支持 ECN 法, 标准曲线法和响应因子法.
    参数:
        rt_tolerance: 保留时间匹配容差(min), 默认 0.1.
    返回:
        无.
    """

    # 报告表头样式
    _HEADER_FONT = Font(bold=True, size=11)
    _HEADER_FILL = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
    _HEADER_ALIGN = Alignment(horizontal="center", vertical="center")

    # 产率结果表头
    _YIELD_HEADERS = [
        "样品名", "目标产物", "产物保留时间(min)", "产物FID面积",
        "产物匹配化合物", "内标保留时间(min)", "内标FID面积",
        "内标匹配化合物", "Ratio", "产物ECN", "内标ECN",
        "产率(%)", "匹配方式", "备注",
    ]

    def __init__(self, rt_tolerance: float = 0.1) -> None:
        self._rt_tolerance = rt_tolerance

    # ------------------------------------------------------------------
    # 静态/辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_ecn(smiles: str) -> float:
        """
        功能:
            根据 SMILES 计算化合物的有效碳数(ECN).
        参数:
            smiles: 化合物 SMILES 字符串.
        返回:
            float: ECN 值.
        """
        ecn = 0.0
        for ary, typ in smiles2carbontypes(smiles):
            if typ == 'alcohol':
                # 醇类需要区分伯/仲/叔
                key = (ary + ' ' + typ) if ary else typ
                ecn += ecn_dct[key]
            else:
                ecn += ecn_dct[class_dct[typ]]
        return ecn

    @staticmethod
    def smiles_to_formula(smiles: str) -> str:
        """
        功能:
            从 SMILES 推导分子式, 使用 Hill 排序 (C, H 在前, 其余按字母序).
        参数:
            smiles: 化合物 SMILES 字符串.
        返回:
            str: 分子式, 如 "C13H13N".
        """
        graph = read_smiles(smiles, explicit_hydrogen=True)
        atom_counts: Dict[str, int] = {}
        for node in graph.nodes:
            elem = graph.nodes[node].get('element', '')
            if elem:
                atom_counts[elem] = atom_counts.get(elem, 0) + 1

        # Hill 排序: C 在前, H 次之, 其余按字母序
        parts = []
        for elem in ['C', 'H']:
            if elem in atom_counts:
                count = atom_counts.pop(elem)
                parts.append(elem + (str(count) if count > 1 else ""))
        for elem in sorted(atom_counts.keys()):
            count = atom_counts[elem]
            parts.append(elem + (str(count) if count > 1 else ""))
        return "".join(parts)

    @staticmethod
    def parse_experiment_range(range_str: str) -> List[int]:
        """
        功能:
            解析 "适用实验" 字段, 支持单个编号/范围/逗号分隔/混合格式.
            "all" 或空字符串返回空列表, 表示适用于所有实验.
        参数:
            range_str: 适用实验字符串, 如 "1-6,9" 或 "all".
        返回:
            List[int]: 实验编号列表, 空列表表示全部适用.
        """
        text = str(range_str).strip().lower()
        if text == "" or text == "all":
            return []

        result = []
        for part in text.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                bounds = part.split("-", 1)
                try:
                    start = int(bounds[0].strip())
                    end = int(bounds[1].strip())
                    result.extend(range(start, end + 1))
                except ValueError:
                    logger.warning("无法解析实验范围: '%s'", part)
            else:
                try:
                    result.append(int(part))
                except ValueError:
                    logger.warning("无法解析实验编号: '%s'", part)
        return sorted(set(result))

    @staticmethod
    def _extract_experiment_number(sample_name: str) -> Optional[int]:
        """
        功能:
            从样品名提取实验编号, 如 "729-3" → 3.
        参数:
            sample_name: 样品名字符串.
        返回:
            Optional[int]: 实验编号, 提取失败返回 None.
        """
        match = re.search(r"-(\d+)$", sample_name.strip())
        if match is not None:
            return int(match.group(1))
        return None

    # ------------------------------------------------------------------
    # 内标摩尔量推算
    # ------------------------------------------------------------------

    def _calculate_is_moles(
        self, is_name: str, is_amount: float, chemical_list_path: Path
    ) -> float:
        """
        功能:
            从 chemical_list.xlsx 查询内标的物化属性,
            根据 physical_state / physical_form / active_content 推算实际加入摩尔量.
        参数:
            is_name: 内标种类名称 (含括号描述).
            is_amount: 内标用量(μL 或 mg).
            chemical_list_path: chemical_list.xlsx 文件路径.
        返回:
            float: 内标摩尔量(mol).
        """
        # 读取化学品库
        chem_df = pd.read_excel(chemical_list_path)
        chem_df.columns = [str(c).strip().lower() for c in chem_df.columns]

        def _pick(row, *keys, default=None):
            for k in keys:
                if k in row and pd.notna(row[k]):
                    return row[k]
            return default

        # 在化学品库中精确匹配内标名称
        chem_info = None
        for _, r in chem_df.iterrows():
            row = {k: r.get(k) for k in chem_df.columns}
            name = str(_pick(row, "substance", "name", "chemical_name", default="") or "").strip()
            if name == is_name:
                chem_info = {
                    "molecular_weight": _pick(row, "molecular_weight", "mw"),
                    "physical_state": str(_pick(row, "physical_state", "state", default="") or "").strip().lower(),
                    "density": _pick(row, "density (g/ml)", "density(g/ml)", "density_g_ml", "density", default=None),
                    "physical_form": str(_pick(row, "physical_form", default="") or "").strip().lower(),
                    "active_content": _pick(
                        row, "active_content",
                        "active_content(mmol/ml or wt%)",
                        "active_content(mol/l or wt%)",
                        default=""
                    ),
                }
                break

        if chem_info is None:
            logger.error("在 chemical_list.xlsx 中未找到内标: '%s' (精确匹配)", is_name)
            raise ValueError(f"在 chemical_list.xlsx 中未找到内标: '{is_name}' (需精确匹配)")

        mw = chem_info["molecular_weight"]
        state = chem_info["physical_state"]
        form = chem_info["physical_form"]
        density = chem_info["density"]
        active_content = chem_info["active_content"]

        if mw is None or float(mw) <= 0:
            raise ValueError(f"内标 '{is_name}' 缺少有效分子量")

        mw = float(mw)

        # 纯物质 (neat)
        if form == "neat" or form == "":
            if state == "liquid":
                # 用量单位为 μL, 需要密度
                if density is None or float(density) <= 0:
                    raise ValueError(f"液体内标 '{is_name}' 缺少密度")
                mass_g = is_amount / 1000.0 * float(density)
                n_mol = mass_g / mw
            else:
                # 固体, 用量单位为 mg
                n_mol = is_amount / 1000.0 / mw
            logger.info("内标(纯物质) '%s': %.4f mol", is_name, n_mol)
            return n_mol

        # 溶液 (solution)
        if form == "solution":
            content_type, content_value = self._parse_active_content(active_content, form)
            if content_type == "mmol_per_ml":
                # content_value 为 mmol/mL, is_amount 为 μL
                n_mol = content_value * (is_amount / 1000.0) / 1000.0
            elif content_type == "wt_percent":
                if density is None or float(density) <= 0:
                    raise ValueError(f"溶液内标 '{is_name}' 按 wt% 换算需要密度")
                mass_total_g = is_amount / 1000.0 * float(density)
                mass_active_g = mass_total_g * content_value / 100.0
                n_mol = mass_active_g / mw
            else:
                raise ValueError(f"溶液内标 '{is_name}' 的 active_content 无法解析")
            logger.info("内标(溶液) '%s': %.6f mol", is_name, n_mol)
            return n_mol

        # 负载型 (beads)
        if form == "beads":
            content_type, content_value = self._parse_active_content(active_content, form)
            if content_type == "wt_percent":
                # is_amount 为 mg
                mass_active_mg = is_amount * content_value / 100.0
                n_mol = mass_active_mg / 1000.0 / mw
            else:
                raise ValueError(f"负载型内标 '{is_name}' 的 active_content 应为 wt%")
            logger.info("内标(负载型) '%s': %.6f mol", is_name, n_mol)
            return n_mol

        raise ValueError(f"内标 '{is_name}' 的 physical_form '{form}' 未支持")

    @staticmethod
    def _parse_active_content(value: Any, physical_form: str) -> Tuple[str, float]:
        """
        功能:
            解析 active_content 字段, 结合 physical_form 区分 mmol/mL 与 wt%.
            逻辑与 station_controller._parse_active_content 一致.
        参数:
            value: active_content 原始值.
            physical_form: 物理形态 (solution/beads 等).
        返回:
            Tuple[str, float]: (类型标记, 数值), 无法解析返回 ("", 0.0).
        """
        form = (physical_form or "").lower().strip()
        if value is None:
            return "", 0.0
        text_raw = str(value).strip()
        if text_raw == "":
            return "", 0.0

        try:
            num_val = float(value)
        except (ValueError, TypeError):
            text_norm = text_raw.lower()
            numbers = re.findall(r"[0-9]+(?:\.[0-9]+)?", text_norm)
            num_val = float(numbers[0]) if len(numbers) > 0 else 0.0

        # 按 physical_form 优先判断
        if form == "solution":
            return "mmol_per_ml", num_val
        if form == "beads":
            return "wt_percent", num_val

        # 按文本关键词判断
        text = text_raw.lower()
        if "mmol/ml" in text or "mmol per ml" in text or "mmolml" in text:
            return "mmol_per_ml", num_val
        if "wt%" in text or "wt percent" in text or "wt" in text:
            return "wt_percent", num_val
        if num_val > 0:
            return "mmol_per_ml", num_val
        return "", 0.0

    # ------------------------------------------------------------------
    # 配置解析
    # ------------------------------------------------------------------

    def parse_yield_config(
        self, plan_path: Path, chemical_list_path: Path
    ) -> YieldCalcConfig:
        """
        功能:
            从实验方案 xlsx 解析产率计算配置:
            1. 读原参数 Sheet: 反应规模(mmol), 内标种类, 内标用量(μL/mg).
            2. 读 "GC产率计算" Sheet: 内标SMILES, 目标产物列表, 计算方法.
            3. 查 chemical_list.xlsx, 推算内标摩尔量.
            4. 自动计算各化合物的分子式和 ECN.
        参数:
            plan_path: 实验方案 xlsx 文件路径.
            chemical_list_path: chemical_list.xlsx 文件路径.
        返回:
            YieldCalcConfig: 产率计算配置.
        """
        wb = openpyxl.load_workbook(str(plan_path), data_only=True)

        # ---------- 1. 从原参数 Sheet 读取已有字段 ----------
        ws_main = wb.worksheets[0]
        params = self._read_kv_params(ws_main)

        reaction_scale = self._parse_float(params.get("反应规模(mmol)", 0))
        is_name = str(params.get("内标种类", "")).strip()
        is_amount = self._parse_float(params.get("内标用量(μL/mg)", 0))
        # 兼容可能的其他格式
        if is_amount == 0:
            is_amount = self._parse_float(params.get("内标用量(ul/mg)", 0))
            if is_amount == 0:
                is_amount = self._parse_float(params.get("内标用量", 0))

        # ---------- 2. 读 "GC产率计算" Sheet ----------
        if YIELD_CONFIG_SHEET_NAME not in wb.sheetnames:
            raise ValueError(f"实验方案中未找到 '{YIELD_CONFIG_SHEET_NAME}' Sheet")
        ws_yield = wb[YIELD_CONFIG_SHEET_NAME]

        yield_params = self._read_kv_params(ws_yield)

        is_smiles = str(yield_params.get("内标SMILES", "")).strip()
        is_expected_rt = self._parse_opt_float(yield_params.get("内标预期RT(min)"))
        calc_method = str(yield_params.get("产率计算方法", "ECN")).strip()
        curve_slope = self._parse_opt_float(yield_params.get("标准曲线斜率"))
        curve_intercept = self._parse_opt_float(yield_params.get("标准曲线截距"))
        response_factor = self._parse_opt_float(yield_params.get("响应因子"))

        if not is_smiles:
            raise ValueError(f"{YIELD_CONFIG_SHEET_NAME} Sheet 中未填写 '内标SMILES'")

        # ---------- 3. 读目标产物列表 ----------
        products = self._read_product_table(ws_yield)

        if len(products) == 0:
            raise ValueError(f"{YIELD_CONFIG_SHEET_NAME} Sheet 中未找到目标产物列表")

        # ---------- 4. 计算分子式和 ECN ----------
        is_formula = self.smiles_to_formula(is_smiles)
        is_ecn = self.calculate_ecn(is_smiles)
        logger.info("内标 '%s': 分子式=%s, ECN=%.2f", is_name, is_formula, is_ecn)

        for p in products:
            p.formula = self.smiles_to_formula(p.smiles)
            p.ecn = self.calculate_ecn(p.smiles)
            logger.info("产物 '%s': 分子式=%s, ECN=%.2f", p.name, p.formula, p.ecn)

        # ---------- 5. 推算内标摩尔量 ----------
        is_moles = self._calculate_is_moles(is_name, is_amount, chemical_list_path)

        wb.close()

        return YieldCalcConfig(
            is_name=is_name,
            is_smiles=is_smiles,
            is_formula=is_formula,
            is_ecn=is_ecn,
            is_expected_rt=is_expected_rt,
            is_amount=is_amount,
            is_moles=is_moles,
            reaction_scale_mmol=reaction_scale,
            calc_method=calc_method,
            curve_slope=curve_slope,
            curve_intercept=curve_intercept,
            response_factor=response_factor,
            products=products,
        )

    def _read_kv_params(self, ws) -> Dict[str, Any]:
        """
        功能:
            从 worksheet 的 A/B 列读取 key-value 参数.
            遇到空行或表格表头行时停止 (表头行特征: A 列为 "适用实验" 等).
        参数:
            ws: openpyxl Worksheet.
        返回:
            Dict[str, Any]: 参数字典.
        """
        params: Dict[str, Any] = {}
        # 已知的产物表表头关键词, 遇到则停止 KV 读取
        table_header_keywords = {"适用实验", "目标产物名称", "目标产物"}
        for row in ws.iter_rows(min_row=1, max_col=2, values_only=True):
            key = str(row[0] or "").strip()
            if not key:
                continue
            if key in table_header_keywords:
                break
            value = row[1]
            if value is not None:
                params[key] = value
        return params

    def _read_product_table(self, ws) -> List[TargetProduct]:
        """
        功能:
            从 "GC产率计算" Sheet 中读取目标产物列表.
            查找表头行 (含 "适用实验" / "目标产物名称"), 然后逐行读取数据.
        参数:
            ws: openpyxl Worksheet ("GC产率计算" Sheet).
        返回:
            List[TargetProduct]: 目标产物列表.
        """
        products = []
        header_row = None
        col_map: Dict[str, int] = {}

        # 定位表头行
        for row_idx, row in enumerate(ws.iter_rows(min_row=1, values_only=False), start=1):
            values = [str(cell.value or "").strip() for cell in row]
            # 检测是否为产物表头行
            lower_values = [v.lower() for v in values]
            if any("适用实验" in v for v in values) or any("目标产物" in v for v in values):
                header_row = row_idx
                for col_idx, val in enumerate(values):
                    if val:
                        col_map[val] = col_idx
                break

        if header_row is None:
            return products

        # 从表头行下一行开始读取数据
        for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
            values = [v for v in row]
            # 跳过空行
            if all(v is None or str(v).strip() == "" for v in values):
                continue

            def _get(header_name: str, default=""):
                for name, idx in col_map.items():
                    if header_name in name:
                        if idx < len(values) and values[idx] is not None:
                            return values[idx]
                return default

            product_name = str(_get("目标产物名称", _get("目标产物"))).strip()
            smiles = str(_get("SMILES")).strip()
            rt_val = _get("预期RT", _get("RT"))
            range_str = str(_get("适用实验")).strip()
            eq_val = _get("当量", _get("eq", 1.0))

            if not product_name or not smiles:
                continue

            expected_rt = self._parse_opt_float(rt_val)
            applicable = self.parse_experiment_range(range_str)
            equivalent = self._parse_float(eq_val, default=1.0)

            products.append(TargetProduct(
                name=product_name,
                smiles=smiles,
                expected_rt=expected_rt,
                applicable_experiments=applicable,
                equivalent=equivalent,
            ))

        return products

    # ------------------------------------------------------------------
    # 数据加载
    # ------------------------------------------------------------------

    def load_alignment_data(self, report_path: Path) -> Dict[str, List[Dict]]:
        """
        功能:
            从积分报告的 "TIC-FID对照表" Sheet 读取对齐数据, 按样品名分组.
        参数:
            report_path: 积分报告 xlsx 文件路径.
        返回:
            Dict[str, List[Dict]]: 样品名 → 对齐行字典列表.
        """
        wb = openpyxl.load_workbook(str(report_path), data_only=True)
        if "TIC-FID对照表" not in wb.sheetnames:
            wb.close()
            raise ValueError("积分报告中未找到 'TIC-FID对照表' Sheet")

        ws = wb["TIC-FID对照表"]

        # 读表头
        headers = []
        for cell in ws[1]:
            headers.append(str(cell.value or "").strip())

        # 按行读取数据
        data: Dict[str, List[Dict]] = {}
        for row in ws.iter_rows(min_row=2, values_only=True):
            row_dict: Dict[str, Any] = {}
            for i, val in enumerate(row):
                if i < len(headers):
                    row_dict[headers[i]] = val

            sample_name = str(row_dict.get("样品名", "")).strip()
            if not sample_name:
                continue

            if sample_name not in data:
                data[sample_name] = []
            data[sample_name].append(row_dict)

        wb.close()
        return data

    # ------------------------------------------------------------------
    # 峰匹配
    # ------------------------------------------------------------------

    def identify_peak(
        self,
        sample_rows: List[Dict],
        expected_rt: Optional[float],
        formula: str,
    ) -> Optional[Dict]:
        """
        功能:
            在单个样品的 TIC-FID 对照表行中查找目标峰.
            有预期 RT 时优先按 RT 匹配, 否则按分子式匹配.
        参数:
            sample_rows: 该样品的对照表数据行列表.
            expected_rt: 预期保留时间(min), None 表示用分子式匹配.
            formula: 目标化合物分子式.
        返回:
            Optional[Dict]: 匹配的行字典, None 表示未找到.
        """
        # 优先: 保留时间匹配
        if expected_rt is not None:
            result = self._match_by_rt(sample_rows, expected_rt)
            if result is not None:
                return result

        # 备选: 分子式匹配
        if formula:
            result = self._match_by_formula(sample_rows, formula)
            if result is not None:
                return result

        return None

    def _match_by_rt(
        self, sample_rows: List[Dict], expected_rt: float
    ) -> Optional[Dict]:
        """
        功能:
            按保留时间匹配, 在容差范围内找最接近的 FID 峰.
        参数:
            sample_rows: 对照表数据行列表.
            expected_rt: 预期保留时间(min).
        返回:
            Optional[Dict]: 匹配的行, None 表示无匹配.
        """
        best_row = None
        best_diff = self._rt_tolerance + 1.0

        for row in sample_rows:
            # 优先用 FID 保留时间
            fid_rt = self._parse_opt_float(row.get("FID保留时间(min)"))
            if fid_rt is None:
                # 退而用 TIC 保留时间
                fid_rt = self._parse_opt_float(row.get("TIC保留时间(min)"))
            if fid_rt is None:
                continue

            diff = abs(fid_rt - expected_rt)
            if diff <= self._rt_tolerance and diff < best_diff:
                best_diff = diff
                best_row = row

        return best_row

    def _match_by_formula(
        self, sample_rows: List[Dict], formula: str
    ) -> Optional[Dict]:
        """
        功能:
            按分子式匹配, 在 NIST 化合物分子式列中做精确匹配.
            检查化合物1和化合物2的分子式.
        参数:
            sample_rows: 对照表数据行列表.
            formula: 目标化合物分子式.
        返回:
            Optional[Dict]: 匹配的行, None 表示无匹配.
        """
        target = formula.strip()
        for row in sample_rows:
            # 检查化合物1和化合物2的分子式
            for suffix in ["化合物1(分子式)", "化合物2(分子式)"]:
                val = str(row.get(suffix, "")).strip()
                if val and val == target:
                    return row
        return None

    # ------------------------------------------------------------------
    # 产率计算
    # ------------------------------------------------------------------

    def _calculate_yield(
        self,
        fid_area_product: float,
        fid_area_is: float,
        ecn_product: float,
        ecn_is: float,
        config: YieldCalcConfig,
        product_equivalent: float = 1.0,
    ) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
        """
        功能:
            根据计算方法分发到 ECN/标准曲线/响应因子法, 计算产率.
        参数:
            fid_area_product: 产物 FID 峰面积.
            fid_area_is: 内标 FID 峰面积.
            ecn_product: 产物 ECN.
            ecn_is: 内标 ECN.
            config: 产率计算配置.
            product_equivalent: 目标产物当量(eq), 理论产物量 = 反应规模 * equivalent.
        返回:
            Tuple: (area_ratio, molar_ratio, n_product_mol, yield_percent).
                   任何环节失败返回 None.
        """
        if fid_area_is <= 0:
            logger.warning("内标 FID 面积 <= 0, 无法计算面积比")
            return (None, None, None, None)

        ratio = fid_area_product / fid_area_is

        method = config.calc_method.strip().upper()

        # ECN 法
        if method == "ECN":
            if ecn_product <= 0:
                logger.warning("产物 ECN <= 0, 无法计算摩尔比")
                return (ratio, None, None, None)
            molar_ratio = ratio * (ecn_is / ecn_product)

        # 标准曲线法
        elif method in ("标准曲线", "CALIBRATION", "CURVE"):
            if config.curve_slope is None or config.curve_slope == 0:
                logger.warning("标准曲线斜率无效, 无法计算")
                return (ratio, None, None, None)
            intercept = config.curve_intercept if config.curve_intercept is not None else 0.0
            molar_ratio = (ratio - intercept) / config.curve_slope

        # 响应因子法
        elif method in ("响应因子", "RF", "RESPONSE_FACTOR"):
            if config.response_factor is None or config.response_factor == 0:
                logger.warning("响应因子无效, 无法计算")
                return (ratio, None, None, None)
            molar_ratio = ratio * config.response_factor

        else:
            logger.warning("未知计算方法: '%s'", config.calc_method)
            return (ratio, None, None, None)

        # 计算产物物质的量
        if config.is_moles <= 0:
            logger.warning("内标摩尔量 <= 0, 无法计算产物物质的量")
            return (ratio, molar_ratio, None, None)

        n_product = molar_ratio * config.is_moles

        # 计算产率
        if config.reaction_scale_mmol <= 0:
            logger.warning("反应规模 <= 0, 无法计算产率")
            return (ratio, molar_ratio, n_product, None)

        n_theoretical = (config.reaction_scale_mmol * product_equivalent) / 1000.0  # mmol * eq → mol
        yield_percent = (n_product / n_theoretical) * 100.0

        return (ratio, molar_ratio, n_product, yield_percent)

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------

    def process_task(
        self,
        plan_path: Path,
        report_path: Path,
        chemical_list_path: Path,
    ) -> Tuple[YieldCalcConfig, List[SampleYieldResult]]:
        """
        功能:
            产率计算完整流程:
            1. 从实验方案和 chemical_list 解析配置.
            2. 从积分报告加载 TIC-FID 对照表数据.
            3. 逐 (样品 x 产物) 计算产率.
        参数:
            plan_path: 实验方案 xlsx 路径.
            report_path: 积分报告 xlsx 路径.
            chemical_list_path: chemical_list.xlsx 路径.
        返回:
            Tuple[YieldCalcConfig, List[SampleYieldResult]]:
                配置和所有样品的计算结果列表.
        """
        # 1. 解析配置
        config = self.parse_yield_config(plan_path, chemical_list_path)
        logger.info(
            "产率计算配置: 方法=%s, 内标=%s(%.6f mol), 反应规模=%.2f mmol, 产物数=%d",
            config.calc_method, config.is_name, config.is_moles,
            config.reaction_scale_mmol, len(config.products),
        )

        # 2. 加载对齐数据
        alignment_data = self.load_alignment_data(report_path)
        logger.info("加载了 %d 个样品的 TIC-FID 对照数据", len(alignment_data))

        # 3. 逐样品计算
        results: List[SampleYieldResult] = []
        for sample_name in sorted(alignment_data.keys()):
            sample_rows = alignment_data[sample_name]
            exp_num = self._extract_experiment_number(sample_name)

            # 查找内标峰 (所有样品共用)
            is_row = self.identify_peak(
                sample_rows, config.is_expected_rt, config.is_formula
            )

            is_fid_rt = None
            is_fid_area = None
            is_match_compound = ""
            is_match_method = ""

            if is_row is not None:
                is_fid_rt = self._parse_opt_float(is_row.get("FID保留时间(min)"))
                is_fid_area = self._parse_opt_float(is_row.get("FID峰面积"))
                is_match_compound = str(is_row.get("化合物1(名称)", "")).strip()
                is_match_method = "rt" if config.is_expected_rt is not None else "formula"

            # 筛选适用于该实验的目标产物
            for product in config.products:
                # 适用实验为空 = 全部适用
                if (
                    len(product.applicable_experiments) > 0
                    and exp_num is not None
                    and exp_num not in product.applicable_experiments
                ):
                    continue

                result = SampleYieldResult(
                    sample_name=sample_name,
                    product_name=product.name,
                    is_fid_rt=is_fid_rt,
                    is_fid_area=is_fid_area,
                    is_match_compound=is_match_compound,
                    ecn_product=product.ecn,
                    ecn_is=config.is_ecn,
                )

                # 内标未找到
                if is_row is None:
                    result.warnings.append("未检测到内标")
                    results.append(result)
                    continue

                if is_fid_area is None or is_fid_area <= 0:
                    result.warnings.append("内标FID面积无效")
                    results.append(result)
                    continue

                # 查找产物峰
                prod_row = self.identify_peak(
                    sample_rows, product.expected_rt, product.formula
                )

                if prod_row is None:
                    result.warnings.append("未检测到目标产物")
                    results.append(result)
                    continue

                result.product_fid_rt = self._parse_opt_float(
                    prod_row.get("FID保留时间(min)")
                )
                result.product_fid_area = self._parse_opt_float(
                    prod_row.get("FID峰面积")
                )
                result.product_match_compound = str(
                    prod_row.get("化合物1(名称)", "")
                ).strip()
                result.match_method = (
                    "rt" if product.expected_rt is not None else "formula"
                )

                if result.product_fid_area is None or result.product_fid_area <= 0:
                    result.warnings.append("产物FID面积无效")
                    results.append(result)
                    continue

                # 计算产率
                ratio, molar_ratio, n_product, yield_pct = self._calculate_yield(
                    result.product_fid_area, is_fid_area,
                    product.ecn, config.is_ecn, config,
                    product_equivalent=product.equivalent,
                )

                result.area_ratio = ratio
                result.molar_ratio = molar_ratio
                result.n_product_mol = n_product
                result.yield_percent = yield_pct

                results.append(result)

        logger.info("产率计算完成, 共 %d 条结果", len(results))
        return config, results

    # ------------------------------------------------------------------
    # 报告生成
    # ------------------------------------------------------------------

    def generate_yield_report(
        self,
        task_id: str,
        config: YieldCalcConfig,
        results: List[SampleYieldResult],
        output_dir: Path,
    ) -> Path:
        """
        功能:
            生成产率报告 Excel 文件, 包含 "产率计算结果" 和 "计算参数" 两个 Sheet.
        参数:
            task_id: 任务 ID.
            config: 产率计算配置.
            results: 各样品计算结果列表.
            output_dir: 输出目录.
        返回:
            Path: 生成的 xlsx 文件路径.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{task_id}_yield_report.xlsx"

        wb = openpyxl.Workbook()

        # Sheet 1: 产率计算结果
        ws_result = wb.active
        ws_result.title = "产率计算结果"
        self._write_yield_sheet(ws_result, results)

        # Sheet 2: 计算参数
        ws_params = wb.create_sheet("计算参数")
        self._write_params_sheet(ws_params, config)

        wb.save(str(output_path))
        logger.info("产率报告已保存: %s", output_path)
        return output_path

    def _write_yield_sheet(
        self, ws, results: List[SampleYieldResult]
    ) -> None:
        """写入产率计算结果 Sheet."""
        self._write_header(ws, self._YIELD_HEADERS)

        for row_idx, r in enumerate(results, start=2):
            ws.cell(row=row_idx, column=1, value=r.sample_name)
            ws.cell(row=row_idx, column=2, value=r.product_name)
            ws.cell(row=row_idx, column=3,
                    value=round(r.product_fid_rt, 3) if r.product_fid_rt is not None else "")
            ws.cell(row=row_idx, column=4,
                    value=round(r.product_fid_area, 6) if r.product_fid_area is not None else "")
            ws.cell(row=row_idx, column=5, value=r.product_match_compound)
            ws.cell(row=row_idx, column=6,
                    value=round(r.is_fid_rt, 3) if r.is_fid_rt is not None else "")
            ws.cell(row=row_idx, column=7,
                    value=round(r.is_fid_area, 6) if r.is_fid_area is not None else "")
            ws.cell(row=row_idx, column=8, value=r.is_match_compound)
            ws.cell(row=row_idx, column=9,
                    value=round(r.area_ratio, 4) if r.area_ratio is not None else "")
            ws.cell(row=row_idx, column=10,
                    value=round(r.ecn_product, 2) if r.ecn_product is not None else "")
            ws.cell(row=row_idx, column=11,
                    value=round(r.ecn_is, 2) if r.ecn_is is not None else "")
            if r.yield_percent is not None:
                yield_display = "<1" if r.yield_percent < 1 else round(r.yield_percent)
            else:
                yield_display = ""
            ws.cell(row=row_idx, column=12, value=yield_display)
            ws.cell(row=row_idx, column=13, value=r.match_method)
            ws.cell(row=row_idx, column=14, value="; ".join(r.warnings) if r.warnings else "")

        self._auto_column_width(ws)

    def _write_params_sheet(self, ws, config: YieldCalcConfig) -> None:
        """写入计算参数 Sheet, 记录本次计算的完整配置."""
        self._write_header(ws, ["参数", "值"])

        rows = [
            ("产率计算方法", config.calc_method),
            ("反应规模(mmol)", config.reaction_scale_mmol),
            ("", ""),
            ("── 内标信息 ──", ""),
            ("内标名称", config.is_name),
            ("内标SMILES", config.is_smiles),
            ("内标分子式", config.is_formula),
            ("内标ECN", round(config.is_ecn, 4)),
            ("内标用量(μL/mg)", config.is_amount),
            ("内标摩尔量(mmol)", round(config.is_moles * 1000, 6)),
            ("内标预期RT(min)", config.is_expected_rt if config.is_expected_rt is not None else ""),
            ("", ""),
        ]

        # 标准曲线/响应因子参数
        if config.curve_slope is not None:
            rows.append(("标准曲线斜率", config.curve_slope))
        if config.curve_intercept is not None:
            rows.append(("标准曲线截距", config.curve_intercept))
        if config.response_factor is not None:
            rows.append(("响应因子", config.response_factor))

        rows.append(("", ""))
        rows.append(("── 目标产物 ──", ""))

        for i, p in enumerate(config.products, start=1):
            exp_str = (
                ",".join(str(e) for e in p.applicable_experiments)
                if p.applicable_experiments else "all"
            )
            rows.append((f"产物{i} 名称", p.name))
            rows.append((f"产物{i} SMILES", p.smiles))
            rows.append((f"产物{i} 分子式", p.formula))
            rows.append((f"产物{i} ECN", round(p.ecn, 4)))
            rows.append((f"产物{i} 预期RT(min)", p.expected_rt if p.expected_rt is not None else ""))
            rows.append((f"产物{i} 适用实验", exp_str))
            rows.append((f"产物{i} 当量(eq)", p.equivalent))
            rows.append(("", ""))

        left_align = Alignment(horizontal="left", vertical="center")
        center_align = Alignment(horizontal="center", vertical="center")
        for row_idx, (key, value) in enumerate(rows, start=2):
            cell_key = ws.cell(row=row_idx, column=1, value=key)
            cell_val = ws.cell(row=row_idx, column=2, value=value)
            cell_key.alignment = left_align
            cell_val.alignment = center_align

        self._auto_column_width(ws)

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    def _write_header(self, ws, headers: List[str]) -> None:
        """写入表头行并设置样式."""
        for col_idx, header in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.font = self._HEADER_FONT
            cell.fill = self._HEADER_FILL
            cell.alignment = self._HEADER_ALIGN

    @staticmethod
    def _auto_column_width(ws) -> None:
        """根据内容自动调整列宽."""
        for col_cells in ws.columns:
            max_length = 0
            col_letter = get_column_letter(col_cells[0].column)
            for cell in col_cells:
                if cell.value is not None:
                    val_str = str(cell.value)
                    char_len = sum(2 if ord(c) > 127 else 1 for c in val_str)
                    max_length = max(max_length, char_len)
            ws.column_dimensions[col_letter].width = min(max_length + 3, 30)

    @staticmethod
    def _parse_float(value: Any, default: float = 0.0) -> float:
        """安全解析浮点数."""
        if value is None:
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            text = str(value).strip()
            numbers = re.findall(r"[0-9]+(?:\.[0-9]+)?", text)
            if numbers:
                return float(numbers[0])
            return default

    @staticmethod
    def _parse_opt_float(value: Any) -> Optional[float]:
        """安全解析可选浮点数, 无效返回 None."""
        if value is None:
            return None
        try:
            result = float(value)
            return result
        except (ValueError, TypeError):
            text = str(value).strip()
            if text == "":
                return None
            numbers = re.findall(r"[0-9]+(?:\.[0-9]+)?", text)
            if numbers:
                return float(numbers[0])
            return None

