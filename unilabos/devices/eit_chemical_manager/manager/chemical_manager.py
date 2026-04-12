# -*- coding: utf-8 -*-
"""
功能:
    化学品管理器, 提供化学品库的统一对外公共 API.
    包含在线查询, 入库, 搜索, 去重, 导出, 溶液/beads 配置等全部功能.
"""

import csv
import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config.setting import Settings
from ..controller.chemical_db import ChemicalDB
from ..controller.append_utils import (
    build_append_row_data,
    build_append_row_data_for_smiles,
    build_prepared_chemical_row_data,
    save_chemicalbook_record,
)
from ..driver.exceptions import ValidationError

logger = logging.getLogger("ChemicalManager")


class ChemicalManager:
    """
    功能:
        化学品管理高层 API, 封装 ChemicalDB 与在线查询逻辑.
        通过 get_shared() 获取全局共享实例.
    参数:
        settings: Optional[Settings], 驱动配置.
    """

    _shared_instance: Optional["ChemicalManager"] = None
    _shared_lock = threading.Lock()

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings or Settings.from_env()
        self._db = ChemicalDB(self._settings.db_path)

    @classmethod
    def get_shared(cls, settings: Optional[Settings] = None) -> "ChemicalManager":
        """
        功能:
            获取全局共享实例, 线程安全.
        参数:
            settings: Optional[Settings], 首次创建时使用的配置.
        返回:
            ChemicalManager.
        """
        if cls._shared_instance is None:
            with cls._shared_lock:
                if cls._shared_instance is None:
                    cls._shared_instance = cls(settings)
        return cls._shared_instance

    @property
    def db(self) -> ChemicalDB:
        """
        功能:
            访问底层 ChemicalDB 实例.
        返回:
            ChemicalDB.
        """
        return self._db

    # ===================== 搜索 =====================

    _VALID_QUERY_TYPES = {"cas", "name", "smiles"}

    def search(
        self,
        query: str,
        query_type: str,
    ) -> List[Dict[str, Any]]:
        """
        功能:
            在化学品库中按 CAS / 名称 / SMILES 查询已有药品.
            SMILES 先在线解析为 CAS 再查库.
        参数:
            query: str, 查询字符串.
            query_type: str, 查询类型, 支持 "cas" / "name" / "smiles".
        返回:
            List[Dict[str, Any]], 匹配行列表, 每项包含 row_id 和 row_data.
        """
        from ..driver.chemical_lookup import _contains_cjk, lookup_chemical_by_smiles

        normalized_query = str(query or "").strip()
        if normalized_query == "":
            return []

        if query_type not in self._VALID_QUERY_TYPES:
            logger.warning("化学品库查询不支持的类型: %s", query_type)
            return []

        # SMILES 需先在线解析
        if query_type == "smiles":
            info = lookup_chemical_by_smiles(normalized_query)
            if info is None:
                logger.warning("SMILES 解析失败, 无法在库中查询: %s", normalized_query)
                return []
            resolved_cas = str(info.cas_number or "").strip()
            resolved_en_name = str(info.substance_english_name or "").strip()
            if resolved_cas != "":
                rows = self._db.search_by_cas(resolved_cas)
            elif resolved_en_name != "":
                rows = self._db.search_by_name(resolved_en_name, is_cjk=False)
            else:
                return []
            return [{"row_id": r["id"], "row_data": r} for r in rows]

        if query_type == "cas":
            rows = self._db.search_by_cas(normalized_query)
            return [{"row_id": r["id"], "row_data": r} for r in rows]

        # 名称查询, 自动检测中英文
        is_cjk = _contains_cjk(normalized_query)
        rows = self._db.search_by_name(normalized_query, is_cjk=is_cjk)
        return [{"row_id": r["id"], "row_data": r} for r in rows]

    # ===================== 在线查询并入库 =====================

    def lookup_and_append(
        self,
        query: str,
        query_type: str,
    ) -> Optional[Dict[str, Any]]:
        """
        功能:
            统一化学品在线查询并追加到化学品库的入口.
            根据 query_type 路由到对应查询逻辑, 查询完成后补充 ChemicalBook
            数据并追加到数据库. 重复时返回已有条目信息.
        参数:
            query: str, 查询字符串 (CAS / 名称 / SMILES).
            query_type: str, 查询类型, 支持 "cas" / "name" / "smiles".
        返回:
            Optional[Dict[str, Any]], 成功返回包含 row_data, row_id 等的结果字典.
            重复时返回 duplicate 标记. 查询失败时返回 None.
        """
        from ..driver.chemical_lookup import is_cas_number, lookup_chemical_unified

        normalized_query = str(query or "").strip()
        if normalized_query == "":
            logger.warning("化学品追加失败, 查询参数为空")
            return None

        if query_type not in self._VALID_QUERY_TYPES:
            logger.warning("不支持的查询类型: %s", query_type)
            return None

        info = lookup_chemical_unified(normalized_query, query_type)

        # 提取 CAS
        resolved_cas = ""
        if info is not None and str(info.cas_number or "").strip() != "":
            resolved_cas = str(info.cas_number).strip()
        elif query_type == "cas" and is_cas_number(normalized_query) is True:
            resolved_cas = normalized_query

        # 补充 ChemicalBook 数据
        chemicalbook_record, chemicalbook_status, chemicalbook_record_path = (
            self._fetch_chemicalbook_artifacts(resolved_cas)
        )

        if info is None and chemicalbook_record is None:
            logger.warning("在线查询未找到化合物: query=%s, type=%s", normalized_query, query_type)
            return None

        # 构建行数据
        if query_type == "smiles":
            row_data = build_append_row_data_for_smiles(
                lookup_info=info,
                chemicalbook_record=chemicalbook_record,
            )
        else:
            row_data = build_append_row_data(
                query=resolved_cas,
                lookup_info=info,
                chemicalbook_record=chemicalbook_record,
            )

        if self._has_core_value(row_data) is False:
            logger.warning("化学品追加失败, 未获取到可用核心字段: query=%s, type=%s", normalized_query, query_type)
            return None

        # 写入 chemicalbook_record_path
        if chemicalbook_record_path != "":
            row_data["chemicalbook_record_path"] = chemicalbook_record_path

        new_id, duplicate_substance = self._db.insert_with_duplicate_check(row_data)
        if new_id is None:
            if duplicate_substance != "":
                return {"duplicate": True, "duplicate_substance": duplicate_substance}
            return None

        summary_text = self._format_row_summary(row_data)
        logger.info(
            "已追加化合物到数据库: query=%s, type=%s, CAS=%s, 英文名=%s, %s, id=%d",
            normalized_query,
            query_type,
            row_data.get("cas_number"),
            row_data.get("substance_english_name"),
            summary_text,
            new_id,
        )

        return {
            "row_data": row_data,
            "row_id": new_id,
            "chemicalbook_status": chemicalbook_status,
            "chemicalbook_record_path": chemicalbook_record_path,
        }

    # ===================== 溶液/beads 配置 =====================

    def prepare_solution_or_beads(
        self,
        identifier: str,
        prepared_form: str,
        *,
        solvent_name: str = "",
        active_content: Any,
        target_volume_ml: Optional[Any] = None,
        target_active_mmol: Optional[Any] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        功能:
            根据 CAS 或 SMILES 解析母体化合物, 按指定形态生成溶液或 beads 条目并追加到化学品库.
        参数:
            identifier: str, 母体化合物 CAS 或 SMILES.
            prepared_form: str, 派生形态, 支持 solution 或 beads.
            solvent_name: str, solution 使用的溶剂名称.
            active_content: Any, solution 时表示 mol/L, beads 时表示 wt%.
            target_volume_ml: Optional[Any], solution 目标定容体积, 单位 mL.
            target_active_mmol: Optional[Any], beads 目标活性摩尔数, 单位 mmol.
        返回:
            Optional[Dict[str, Any]], 成功返回母体信息, 派生条目信息与配制结果摘要.
        异常:
            ValidationError: 形态或数值参数非法时抛出.
        """
        normalized_form = str(prepared_form or "").strip().lower()
        if normalized_form not in {"solution", "beads"}:
            raise ValidationError("派生形态仅支持 solution 或 beads")

        base_result = self._resolve_prepared_base(identifier)
        if base_result is None:
            logger.warning("未找到可用于配置的母体化合物: %s", identifier)
            return None

        base_row_data = dict(base_result.get("row_data") or {})
        if base_row_data.get("base_substance") in (None, ""):
            base_row_data["base_substance"] = (
                base_row_data.get("substance")
                or base_row_data.get("substance_english_name")
                or ""
            )

        normalized_active_content = self._parse_positive_float(active_content, "活性含量")
        if normalized_form == "solution":
            normalized_target_volume_ml = self._parse_positive_float(target_volume_ml, "目标定容体积")
            derived_row_data = build_prepared_chemical_row_data(
                base_row_data=base_row_data,
                prepared_form="solution",
                active_content=normalized_active_content,
                solvent_name=solvent_name,
            )
            recipe = self._build_solution_recipe(
                base_row_data=base_row_data,
                concentration_mol_l=normalized_active_content,
                target_volume_ml=normalized_target_volume_ml,
                solvent_name=solvent_name,
            )
        else:
            normalized_target_active_mmol = self._parse_positive_float(target_active_mmol, "目标活性 mmol")
            derived_row_data = build_prepared_chemical_row_data(
                base_row_data=base_row_data,
                prepared_form="beads",
                active_content=normalized_active_content,
            )
            recipe = self._build_beads_recipe(
                base_row_data=base_row_data,
                wt_percent=normalized_active_content,
                target_active_mmol=normalized_target_active_mmol,
            )

        new_id, duplicate_substance = self._db.insert_with_duplicate_check(derived_row_data)
        if new_id is None:
            logger.warning(
                "派生条目已存在, 跳过添加: identifier=%s, substance=%s",
                identifier,
                derived_row_data.get("substance"),
            )
            if duplicate_substance != "":
                return {"duplicate": True, "duplicate_substance": duplicate_substance}
            return None

        summary_text = self._format_row_summary(derived_row_data)
        logger.info(
            "已完成溶液或 beads 配置: identifier=%s, 母体新建=%s, %s, id=%d",
            identifier,
            base_result.get("base_created"),
            summary_text,
            new_id,
        )

        return {
            "base_row_data": base_row_data,
            "base_row_id": base_result.get("row_id"),
            "base_created": bool(base_result.get("base_created")),
            "derived_row_data": derived_row_data,
            "derived_row_id": new_id,
            "recipe": recipe,
            "chemicalbook_status": base_result.get("chemicalbook_status", ""),
            "chemicalbook_record_path": base_result.get("chemicalbook_record_path", ""),
        }

    # ===================== 导出 =====================

    def export_to_csv(self, output_path: str) -> int:
        """
        功能:
            将化学品库导出为 CSV 文件.
        参数:
            output_path: str, 输出文件路径.
        返回:
            int, 导出的行数.
        """
        rows = self._db.iter_all()
        if len(rows) == 0:
            logger.warning("化学品库为空, 无数据可导出")
            return 0

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        # 使用第一行的 key 作为 CSV 表头
        fieldnames = list(rows[0].keys())
        with open(output, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

        logger.info("化学品库已导出到 CSV: path=%s, 行数=%d", output_path, len(rows))
        return len(rows)

    def deduplicate(self) -> int:
        """
        功能:
            按 CAS 号对化学品库去重.
        返回:
            int, 删除的重复行数.
        """
        return self._db.deduplicate()

    def check_integrity(self) -> Dict[str, Any]:
        """
        功能:
            检查化学品库完整性.
        返回:
            Dict[str, Any], 完整性检查结果.
        """
        return self._db.check_integrity()

    # ===================== 私有方法 =====================

    def _resolve_prepared_base(
        self,
        identifier: str,
    ) -> Optional[Dict[str, Any]]:
        """
        功能:
            为溶液或 beads 配置流程解析母体化合物, 不存在时自动补录 neat 条目.
        参数:
            identifier: str, CAS 或 SMILES.
        返回:
            Optional[Dict[str, Any]], 成功时返回母体行数据与来源信息.
        """
        from ..driver.chemical_lookup import is_cas_number, lookup_chemical_by_smiles

        normalized_identifier = str(identifier or "").strip()
        if normalized_identifier == "":
            raise ValidationError("CAS 或 SMILES 不能为空")

        if is_cas_number(normalized_identifier) is True:
            existing = self._db.find_existing(cas_number=normalized_identifier)
            if existing is not None:
                return {
                    "row_data": existing,
                    "row_id": existing.get("id"),
                    "base_created": False,
                    "chemicalbook_status": "",
                    "chemicalbook_record_path": "",
                }

            append_result = self.lookup_and_append(normalized_identifier, "cas")
            if append_result is None or append_result.get("duplicate") is True:
                return None
            append_result["base_created"] = True
            return append_result

        lookup_info = lookup_chemical_by_smiles(normalized_identifier)
        if lookup_info is None:
            return None

        existing = self._db.find_existing(
            cas_number=str(getattr(lookup_info, "cas_number", "") or "").strip(),
            substance_english_name=str(getattr(lookup_info, "substance_english_name", "") or "").strip(),
            substance=str(getattr(lookup_info, "substance", "") or "").strip(),
        )
        if existing is not None:
            return {
                "row_data": existing,
                "row_id": existing.get("id"),
                "base_created": False,
                "chemicalbook_status": "",
                "chemicalbook_record_path": "",
            }

        append_result = self.lookup_and_append(normalized_identifier, "smiles")
        if append_result is None or append_result.get("duplicate") is True:
            return None
        append_result["base_created"] = True
        return append_result

    def _fetch_chemicalbook_artifacts(
        self,
        resolved_cas: str,
    ) -> tuple:
        """
        功能:
            根据已解析的 CAS 获取 ChemicalBook 结构化结果及 sidecar 路径.
        参数:
            resolved_cas: str, 已解析出的 CAS 号.
        返回:
            Tuple[Optional[Dict], str, str], 依次为
            chemicalbook_record, chemicalbook_status, chemicalbook_record_path.
        """
        from ..driver.chemicalbook_scraper import fetch_chemicalbook_by_cas

        normalized_cas = str(resolved_cas or "").strip()
        if normalized_cas == "":
            return None, "", ""

        chemicalbook_record = None
        chemicalbook_status = ""
        chemicalbook_record_path = ""
        try:
            chemicalbook_record = fetch_chemicalbook_by_cas(normalized_cas)
            chemicalbook_status = str(chemicalbook_record.get("status") or "")
        except Exception as exc:
            logger.warning("ChemicalBook 结构化抓取异常: CAS=%s, err=%s", normalized_cas, exc)

        if chemicalbook_record is not None:
            try:
                chemicalbook_record_path = save_chemicalbook_record(chemicalbook_record)
            except OSError as exc:
                logger.warning("ChemicalBook sidecar 保存失败: CAS=%s, err=%s", normalized_cas, exc)
                chemicalbook_record_path = ""

        return chemicalbook_record, chemicalbook_status, chemicalbook_record_path

    @staticmethod
    def _has_core_value(row_data: Dict[str, Any]) -> bool:
        """
        功能:
            判断行数据是否至少包含一个可识别化合物的核心字段.
        参数:
            row_data: Dict[str, Any], 行数据.
        返回:
            bool, True 表示至少包含 CAS, 英文名, 中文名中的一个.
        """
        return any([
            str(row_data.get("cas_number") or "").strip() != "",
            str(row_data.get("substance_english_name") or "").strip() != "",
            str(row_data.get("substance") or "").strip() != "",
        ])

    @staticmethod
    def _format_row_summary(row_data: Dict[str, Any]) -> str:
        """
        功能:
            提取关键字段, 生成日志摘要文本.
        参数:
            row_data: Dict[str, Any], 行数据.
        返回:
            str, 摘要文本.
        """
        substance = str(row_data.get("substance") or "").strip()
        physical_state = str(row_data.get("physical_state") or "").strip()
        physical_form = str(row_data.get("physical_form") or "").strip()
        return (
            f"substance={substance}, "
            f"physical_state={physical_state}, "
            f"physical_form={physical_form}"
        )

    @staticmethod
    def _parse_positive_float(value: Any, field_name: str) -> float:
        """
        功能:
            将输入值解析为大于 0 的浮点数.
        参数:
            value: Any, 待解析的数值.
            field_name: str, 字段中文名, 用于异常提示.
        返回:
            float, 解析后的正数.
        异常:
            ValidationError: 字段为空, 非数字或不大于 0 时抛出.
        """
        text_value = str(value or "").strip()
        if text_value == "":
            raise ValidationError(f"{field_name}不能为空")
        try:
            numeric_value = float(text_value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"{field_name}必须为数字") from exc
        if numeric_value <= 0:
            raise ValidationError(f"{field_name}必须大于0")
        return numeric_value

    @staticmethod
    def _format_preparation_number(value: float) -> str:
        """
        功能:
            将配液或称量结果格式化为紧凑展示文本.
        参数:
            value: float, 原始数值.
        返回:
            str, 去除多余尾零后的文本.
        """
        return format(float(value), ".6g")

    def _build_solution_recipe(
        self,
        base_row_data: Dict[str, Any],
        concentration_mol_l: float,
        target_volume_ml: float,
        solvent_name: str,
    ) -> Dict[str, Any]:
        """
        功能:
            根据母体化合物信息生成溶液配置结果.
        参数:
            base_row_data: Dict[str, Any], 母体化合物行数据.
            concentration_mol_l: float, 目标浓度, 单位 mol/L.
            target_volume_ml: float, 目标定容体积, 单位 mL.
            solvent_name: str, 溶剂名称.
        返回:
            Dict[str, Any], 包含质量, 体积与展示文案的结果字典.
        异常:
            ValidationError: 缺少分子量时抛出.
        """
        molecular_weight = self._parse_positive_float(
            base_row_data.get("molecular_weight"),
            "母体化合物分子量",
        )
        normalized_solvent_name = str(solvent_name or "").strip()
        if normalized_solvent_name == "":
            raise ValidationError("溶剂名称不能为空")

        solute_moles = concentration_mol_l * target_volume_ml / 1000.0
        solute_mass_g = solute_moles * molecular_weight
        instruction_text = (
            f"称取/加入溶质 {self._format_preparation_number(solute_mass_g)} g, "
            f"用 {normalized_solvent_name} 溶解后定容至 "
            f"{self._format_preparation_number(target_volume_ml)} mL"
        )

        solute_volume_ml = None
        density_text = str(base_row_data.get("density (g/mL)") or base_row_data.get("density") or "").strip()
        physical_state = str(base_row_data.get("physical_state") or "").strip().lower()
        if physical_state == "liquid" and density_text != "":
            try:
                density_value = self._parse_positive_float(density_text, "母体化合物密度")
                solute_volume_ml = solute_mass_g / density_value
            except ValidationError:
                logger.warning("母体液体密度无效, 跳过溶质量取体积估算: density=%s", density_text)

        return {
            "prepared_form": "solution",
            "solute_moles": solute_moles,
            "solute_mass_g": solute_mass_g,
            "solute_volume_ml": solute_volume_ml,
            "target_volume_ml": target_volume_ml,
            "active_content": concentration_mol_l,
            "solvent_name": normalized_solvent_name,
            "instruction_text": instruction_text,
        }

    def _build_beads_recipe(
        self,
        base_row_data: Dict[str, Any],
        wt_percent: float,
        target_active_mmol: float,
    ) -> Dict[str, Any]:
        """
        功能:
            根据母体化合物信息生成 beads 称量结果.
        参数:
            base_row_data: Dict[str, Any], 母体化合物行数据.
            wt_percent: float, 有效成分质量分数.
            target_active_mmol: float, 目标活性摩尔数, 单位 mmol.
        返回:
            Dict[str, Any], 包含 beads 质量与展示文案的结果字典.
        异常:
            ValidationError: 缺少分子量时抛出.
        """
        molecular_weight = self._parse_positive_float(
            base_row_data.get("molecular_weight"),
            "母体化合物分子量",
        )
        active_mass_g = target_active_mmol / 1000.0 * molecular_weight
        beads_mass_g = active_mass_g / (wt_percent / 100.0)
        instruction_text = (
            f"称取 beads {self._format_preparation_number(beads_mass_g)} g, "
            f"其中有效成分约为 {self._format_preparation_number(target_active_mmol)} mmol"
        )
        return {
            "prepared_form": "beads",
            "active_mass_g": active_mass_g,
            "beads_mass_g": beads_mass_g,
            "target_active_mmol": target_active_mmol,
            "active_content": wt_percent,
            "instruction_text": instruction_text,
        }
