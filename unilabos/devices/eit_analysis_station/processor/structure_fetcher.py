#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    提供化合物结构图获取能力.
    1. NistLocalStructureFetcher: 运行时解析 NIST MSP 构建本地映射, 优先离线生成结构图.
    2. StructureFetcher: 历史 CAS -> PubChem 结构下载链路, 仅作为回滚兜底保留.
参数:
    无.
返回:
    无.
"""

import logging
import pickle
import re
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .nist_matcher import CompoundMatch

logger = logging.getLogger(__name__)

# 无效 CAS 号模式, 跳过查询.
_INVALID_CAS_PATTERNS = {"", "0", "0-00-0", "---", "N/A", "n/a"}
_MSP_SEQ_REGEX = re.compile(r"NIST\s+MS#\s*(\d+).*?Seq#\s*([MR])\s*(\d+)", re.IGNORECASE)
_RUNTIME_CACHE_VERSION = 2


def _normalize_cas_digits(cas_number: str) -> str:
    """
    功能:
        将 CAS 字符串标准化为纯数字形式, 用于索引键匹配.
    参数:
        cas_number: 原始 CAS 字符串.
    返回:
        str, 仅保留数字的 CAS 字符串.
    """
    return re.sub(r"\D", "", cas_number.strip())


def _sanitize_cas(cas_number: str) -> str:
    """将 CAS 号转为合法文件名, 如 '74-95-3' -> '74-95-3'."""
    return re.sub(r"[^\d\-]", "_", cas_number.strip())


def build_structure_key(nist_id: Optional[int], cas_number: str) -> Optional[str]:
    """
    功能:
        生成结构图索引键.
        1. 有效 nist_id 时返回 NIST:<id>.
        2. 否则按 CAS 纯数字返回 CAS:<digits>.
    参数:
        nist_id: NIST 命中 Id.
        cas_number: CAS 号.
    返回:
        Optional[str], 结构图索引键.
    """
    if nist_id is not None and nist_id > 0:
        return f"NIST:{nist_id}"

    cas_digits = _normalize_cas_digits(cas_number)
    if cas_digits != "":
        return f"CAS:{cas_digits}"

    return None


class NistLocalStructureFetcher:
    """
    功能:
        运行时解析 NIST 导出的 MSP 与 MOL 目录, 并按命中结果获取结构图.
        优先级:
        1. 任务缓存目录中已存在结构图.
        2. 运行时映射命中后按需渲染 S<cas_digits>.MOL.
        3. 非严格离线时回退 PubChem.
    参数:
        task_cache_dir: 任务级结构图缓存目录.
        seed_msp_path: NIST 导出的 MSP 文件路径, 用于运行时构建映射.
        seed_mol_dir: NIST 导出的 MOL 目录, 用于按需渲染结构图.
        runtime_cache_path: 运行时映射缓存文件路径.
        offline_only: 是否严格离线, True 时禁止回退 PubChem.
        global_cache_dir: 历史链路全局缓存目录, 仅 offline_only=False 时用于回退.
        image_size: 回退 PubChem 下载尺寸.
        image_ppi: 结构图写盘分辨率, 仅本地渲染路径生效.
        timeout: 回退 PubChem 超时.
        request_interval: 回退 PubChem 请求间隔.
    返回:
        无.
    """

    def __init__(
        self,
        task_cache_dir: Path,
        seed_msp_path: Optional[Path] = None,
        seed_mol_dir: Optional[Path] = None,
        runtime_cache_path: Optional[Path] = None,
        offline_only: bool = False,
        global_cache_dir: Optional[Path] = None,
        image_size: int = 200,
        image_ppi: int = 150,
        timeout: float = 10.0,
        request_interval: float = 0.2,
    ) -> None:
        self._task_cache_dir = Path(task_cache_dir)
        self._seed_msp_path = Path(seed_msp_path) if seed_msp_path is not None else None
        self._seed_mol_dir = Path(seed_mol_dir) if seed_mol_dir is not None else None
        self._runtime_cache_path = (
            Path(runtime_cache_path) if runtime_cache_path is not None else None
        )
        self._offline_only = offline_only
        self._image_size = image_size
        self._image_ppi = image_ppi

        self._task_cache_dir.mkdir(parents=True, exist_ok=True)

        self._by_nist_ms: Dict[str, str] = {}
        self._by_seq_mainlib: Dict[str, str] = {}
        self._by_seq_replib: Dict[str, str] = {}
        self._load_runtime_mapping()

        self._fallback_fetcher: Optional[StructureFetcher] = None
        if self._offline_only is False:
            self._fallback_fetcher = StructureFetcher(
                task_cache_dir=self._task_cache_dir,
                global_cache_dir=global_cache_dir,
                image_size=image_size,
                image_ppi=image_ppi,
                timeout=timeout,
                request_interval=request_interval,
            )

    def fetch_batch_from_matches(
        self,
        matches: List[CompoundMatch],
    ) -> Dict[str, Optional[Path]]:
        """
        功能:
            批量按命中结果获取结构图.
            优先使用本地缓存和本地 MOL, 失败后回退 PubChem.
        参数:
            matches: 化合物命中列表.
        返回:
            Dict[str, Optional[Path]], 结构键到结构图路径映射.
        """
        results: Dict[str, Optional[Path]] = {}

        for match in matches:
            key = build_structure_key(match.nist_id, match.cas_number)
            if key is None:
                logger.debug(
                    "命中项缺少结构定位键, 化合物=%s, CAS=%s, NIST#=%s",
                    match.compound_name or "(未知)",
                    match.cas_number or "(空)",
                    match.nist_id,
                )
                continue

            if key in results:
                continue

            cached_path = self._get_task_cache_path(key)
            if cached_path is not None:
                results[key] = cached_path
                continue

            on_demand_path = self._render_from_seed_mol(match, key)
            if on_demand_path is not None:
                results[key] = on_demand_path
                continue

            logger.warning(
                "结构未命中本地映射, key=%s, 化合物=%s, CAS=%s, NIST#=%s, Lib=%s",
                key,
                match.compound_name or "(未知)",
                match.cas_number or "(空)",
                match.nist_id,
                match.library or "(空)",
            )

            fallback_path = self._fetch_with_legacy_fallback(match)
            results[key] = fallback_path

        success_count = sum(1 for path in results.values() if path is not None)
        logger.info("结构图匹配完成: %d/%d 成功", success_count, len(results))
        return results

    def _get_task_cache_path(self, structure_key: str) -> Optional[Path]:
        """
        功能:
            返回任务缓存中已存在的结构图路径.
        参数:
            structure_key: 结构键.
        返回:
            Optional[Path], 命中时返回路径.
        """
        target_path = self._task_cache_dir / f"{structure_key.replace(':', '_')}.png"
        if target_path.exists() is True:
            return target_path
        return None

    def _load_runtime_mapping(self) -> None:
        """
        功能:
            加载运行时结构映射.
            优先尝试缓存, 缓存无效时重新解析 MSP.
        参数:
            无.
        返回:
            无.
        """
        if self._seed_mol_dir is not None:
            if self._seed_mol_dir.is_dir() is True:
                logger.info("已启用按需结构图渲染, MOL 目录: %s", self._seed_mol_dir)
            else:
                logger.warning("MOL 目录不存在, 按需结构图渲染不可用: %s", self._seed_mol_dir)

        if self._seed_msp_path is None:
            logger.info("未配置 seed MSP, 将仅依赖命中 CAS 与 PubChem 回退.")
            return

        if self._seed_msp_path.exists() is False:
            logger.warning("seed MSP 不存在, 运行时映射不可用: %s", self._seed_msp_path)
            return

        if self._seed_mol_dir is None:
            logger.info("未配置 seed MOL 目录, 运行时映射将仅用于 PubChem 回退 CAS.")
        elif self._seed_mol_dir.is_dir() is False:
            logger.warning("seed MOL 目录不存在, 运行时映射将仅用于 PubChem 回退 CAS: %s", self._seed_mol_dir)

        if self._runtime_cache_path is not None:
            if self._try_load_runtime_cache() is True:
                return

        by_nist_ms, by_seq_mainlib, by_seq_replib = self._build_runtime_mapping_from_seed()
        self._by_nist_ms = by_nist_ms
        self._by_seq_mainlib = by_seq_mainlib
        self._by_seq_replib = by_seq_replib

        if self._runtime_cache_path is not None:
            self._save_runtime_cache()

        logger.info(
            "运行时结构映射构建完成: NIST键=%d, mainlib序号键=%d, replib序号键=%d",
            len(self._by_nist_ms),
            len(self._by_seq_mainlib),
            len(self._by_seq_replib),
        )

    def _build_runtime_mapping_from_seed(self) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, str]]:
        """
        功能:
            从 seed MSP 与 seed MOL 构建运行时映射.
        参数:
            无.
        返回:
            Tuple[Dict[str, str], Dict[str, str], Dict[str, str]]:
                by_nist_ms, by_seq_mainlib, by_seq_replib.
        """
        by_nist_ms: Dict[str, str] = {}
        by_seq_mainlib: Dict[str, str] = {}
        by_seq_replib: Dict[str, str] = {}

        if self._seed_msp_path is None:
            return by_nist_ms, by_seq_mainlib, by_seq_replib
        if self._seed_msp_path.exists() is False:
            return by_nist_ms, by_seq_mainlib, by_seq_replib

        available_cas_digits = self._scan_seed_mol_cas_digits()

        current_cas_digits = ""
        with self._seed_msp_path.open("r", encoding="utf-8", errors="replace") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if line == "":
                    current_cas_digits = ""
                    continue

                if line.startswith("CASNO:"):
                    cas_raw = line.split(":", 1)[1]
                    current_cas_digits = _normalize_cas_digits(cas_raw)
                    continue

                if line.startswith("Comment:") is False:
                    continue
                if current_cas_digits == "":
                    continue
                match = _MSP_SEQ_REGEX.search(line)
                if match is None:
                    continue

                nist_ms = str(int(match.group(1)))
                seq_prefix = match.group(2).upper()
                seq_id = str(int(match.group(3)))

                if nist_ms not in by_nist_ms:
                    by_nist_ms[nist_ms] = current_cas_digits

                if seq_prefix == "M":
                    if seq_id not in by_seq_mainlib:
                        by_seq_mainlib[seq_id] = current_cas_digits
                elif seq_prefix == "R":
                    if seq_id not in by_seq_replib:
                        by_seq_replib[seq_id] = current_cas_digits

        if len(available_cas_digits) > 0:
            logger.info(
                "运行时映射包含未落地 MOL 的 CAS, 后续将按需回退: 映射CAS=%d, 可渲染CAS=%d",
                len(set(by_nist_ms.values()) | set(by_seq_mainlib.values()) | set(by_seq_replib.values())),
                len(available_cas_digits),
            )

        return by_nist_ms, by_seq_mainlib, by_seq_replib

    def _scan_seed_mol_cas_digits(self) -> Set[str]:
        """
        功能:
            扫描 seed MOL 目录中的 S<cas_digits>.MOL 文件.
        参数:
            无.
        返回:
            Set[str], 可用于渲染的 CAS 数字集合.
        """
        if self._seed_mol_dir is None:
            return set()
        if self._seed_mol_dir.is_dir() is False:
            return set()

        cas_digits_set: Set[str] = set()
        for mol_path in self._seed_mol_dir.iterdir():
            if mol_path.is_file() is False:
                continue
            if mol_path.suffix.lower() != ".mol":
                continue

            filename = mol_path.name
            upper_name = filename.upper()
            if upper_name.startswith("S") is False:
                continue
            if upper_name.endswith(".MOL") is False:
                continue

            cas_digits = filename[1:-4]
            if cas_digits.isdigit() is False:
                continue
            cas_digits_set.add(cas_digits)

        logger.info("seed MOL 扫描完成: S键=%d, 目录=%s", len(cas_digits_set), self._seed_mol_dir)
        return cas_digits_set

    def _try_load_runtime_cache(self) -> bool:
        """
        功能:
            尝试从运行时缓存文件加载映射.
        参数:
            无.
        返回:
            bool, 缓存加载是否成功.
        """
        if self._runtime_cache_path is None:
            return False
        if self._runtime_cache_path.exists() is False:
            return False

        try:
            with self._runtime_cache_path.open("rb") as handle:
                payload = pickle.load(handle)
        except Exception as exc:
            logger.warning("读取运行时映射缓存失败: %s, 错误=%s", self._runtime_cache_path, exc)
            return False

        if self._is_runtime_cache_valid(payload) is False:
            logger.info("运行时映射缓存已失效, 将重新构建: %s", self._runtime_cache_path)
            return False

        self._by_nist_ms = self._sanitize_mapping_dict(payload.get("by_nist_ms"))
        self._by_seq_mainlib = self._sanitize_mapping_dict(payload.get("by_seq_mainlib"))
        self._by_seq_replib = self._sanitize_mapping_dict(payload.get("by_seq_replib"))

        logger.info(
            "已加载运行时结构映射缓存: NIST键=%d, mainlib序号键=%d, replib序号键=%d, 缓存=%s",
            len(self._by_nist_ms),
            len(self._by_seq_mainlib),
            len(self._by_seq_replib),
            self._runtime_cache_path,
        )
        return True

    def _is_runtime_cache_valid(self, payload: object) -> bool:
        """
        功能:
            校验运行时缓存是否与当前 seed 文件一致.
        参数:
            payload: 缓存反序列化对象.
        返回:
            bool, 缓存是否可用.
        """
        if isinstance(payload, dict) is False:
            return False
        if payload.get("version") != _RUNTIME_CACHE_VERSION:
            return False
        if self._seed_msp_path is None:
            return False

        seed_msp = payload.get("seed_msp_path")
        seed_mol_dir = payload.get("seed_mol_dir")
        if seed_msp != str(self._seed_msp_path):
            return False
        if seed_mol_dir != str(self._seed_mol_dir):
            return False

        msp_stat = self._seed_msp_path.stat()
        if payload.get("seed_msp_size") != msp_stat.st_size:
            return False
        if payload.get("seed_msp_mtime") != msp_stat.st_mtime:
            return False
        return True

    @staticmethod
    def _sanitize_mapping_dict(raw_mapping: object) -> Dict[str, str]:
        """
        功能:
            将缓存中的映射对象标准化为字符串字典.
        参数:
            raw_mapping: 原始映射对象.
        返回:
            Dict[str, str], 过滤后的映射.
        """
        if isinstance(raw_mapping, dict) is False:
            return {}

        normalized: Dict[str, str] = {}
        for key, value in raw_mapping.items():
            normalized_key = str(key).strip()
            normalized_value = str(value).strip()
            if normalized_key == "":
                continue
            if normalized_value == "":
                continue
            normalized[normalized_key] = normalized_value
        return normalized

    def _save_runtime_cache(self) -> None:
        """
        功能:
            将当前运行时映射写入缓存文件.
        参数:
            无.
        返回:
            无.
        """
        if self._runtime_cache_path is None:
            return
        if self._seed_msp_path is None:
            return

        try:
            self._runtime_cache_path.parent.mkdir(parents=True, exist_ok=True)
            msp_stat = self._seed_msp_path.stat()
            payload = {
                "version": _RUNTIME_CACHE_VERSION,
                "seed_msp_path": str(self._seed_msp_path),
                "seed_mol_dir": str(self._seed_mol_dir),
                "seed_msp_size": msp_stat.st_size,
                "seed_msp_mtime": msp_stat.st_mtime,
                "by_nist_ms": self._by_nist_ms,
                "by_seq_mainlib": self._by_seq_mainlib,
                "by_seq_replib": self._by_seq_replib,
            }
            with self._runtime_cache_path.open("wb") as handle:
                pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
            logger.info("运行时结构映射缓存已写入: %s", self._runtime_cache_path)
        except Exception as exc:
            logger.warning("写入运行时结构映射缓存失败: %s, 错误=%s", self._runtime_cache_path, exc)

    def _render_from_seed_mol(
        self,
        match: CompoundMatch,
        structure_key: str,
    ) -> Optional[Path]:
        """
        功能:
            在运行时按命中结果直接查找 MOL 并渲染结构图.
        参数:
            match: 单个化合物命中.
            structure_key: 结构键.
        返回:
            Optional[Path], 渲染成功返回任务缓存路径.
        """
        if self._seed_mol_dir is None:
            return None

        if self._seed_mol_dir.is_dir() is False:
            return None

        cas_digits = self._resolve_seed_cas_digits(match)
        if cas_digits == "":
            return None

        mol_path = self._find_seed_mol_path_by_cas(cas_digits)
        if mol_path is None:
            return None

        target_path = self._task_cache_dir / f"{structure_key.replace(':', '_')}.png"
        if target_path.exists() is True:
            return target_path

        return self._render_mol_to_png(mol_path, target_path, structure_key)

    def _resolve_seed_cas_digits(self, match: CompoundMatch) -> str:
        """
        功能:
            根据命中结果推导用于本地渲染的 CAS 数字键.
            优先级:
            1. library + Id(Seq#) 映射.
            2. 当库类型未知时, 按 NIST MS# 映射.
            3. 命中项自带 CAS.
        参数:
            match: 单个化合物命中.
        返回:
            str, CAS 数字键. 空字符串表示不可定位.
        """
        if match.nist_id is not None and match.nist_id > 0:
            seq_cas_digits = self._resolve_cas_by_seq(match.library, match.nist_id)
            if seq_cas_digits != "":
                return seq_cas_digits

            normalized_library = self._normalize_library_name(match.library)
            if normalized_library == "":
                # 库未知时, 允许把 Id 视为 NIST MS# 进行兜底映射.
                nist_ms_key = str(match.nist_id)
                if nist_ms_key in self._by_nist_ms:
                    return self._by_nist_ms[nist_ms_key]
            else:
                logger.debug(
                    "库序号映射缺失, 跳过 NIST MS# 兜底避免错配: 化合物=%s, Lib=%s, Id=%s",
                    match.compound_name or "(未知)",
                    match.library or "(空)",
                    match.nist_id,
                )

        return _normalize_cas_digits(match.cas_number)

    def _resolve_cas_by_seq(self, library_name: str, sequence_id: int) -> str:
        """
        功能:
            按库类型与序号查找 CAS 数字键.
        参数:
            library_name: 命中来源库名称.
            sequence_id: 命中 Id(Seq#).
        返回:
            str, CAS 数字键. 未命中返回空字符串.
        """
        normalized_library = self._normalize_library_name(library_name)
        sequence_key = str(sequence_id)

        if normalized_library == "mainlib":
            return self._by_seq_mainlib.get(sequence_key, "")
        if normalized_library == "replib":
            return self._by_seq_replib.get(sequence_key, "")
        return ""

    @staticmethod
    def _normalize_library_name(library_name: str) -> str:
        """
        功能:
            归一化库名称, 用于匹配 mainlib/replib.
        参数:
            library_name: 原始库名称.
        返回:
            str, 归一化后库标识.
        """
        normalized = str(library_name).strip().lower()
        if "mainlib" in normalized:
            return "mainlib"
        if "replib" in normalized:
            return "replib"
        return ""

    def _find_seed_mol_path_by_cas(self, cas_digits: str) -> Optional[Path]:
        """
        功能:
            按 CAS 数字键定位 seed MOL 文件路径.
        参数:
            cas_digits: CAS 纯数字键.
        返回:
            Optional[Path], 命中则返回路径.
        """
        if self._seed_mol_dir is None:
            return None
        if cas_digits == "":
            return None

        filename = f"S{cas_digits}.MOL"
        direct_path = self._seed_mol_dir / filename
        if direct_path.exists() is True:
            return direct_path

        lower_path = self._seed_mol_dir / filename.lower()
        if lower_path.exists() is True:
            return lower_path
        return None

    def _render_mol_to_png(
        self,
        mol_path: Path,
        target_path: Path,
        structure_key: str,
    ) -> Optional[Path]:
        """
        功能:
            将 MOL 文件渲染为 PNG 并写入任务缓存目录.
        参数:
            mol_path: MOL 文件路径.
            target_path: 目标 PNG 路径.
            structure_key: 结构键, 用于日志追踪.
        返回:
            Optional[Path], 渲染成功返回目标路径.
        """
        try:
            from rdkit import Chem
            from rdkit.Chem import Draw
        except ImportError:
            logger.warning("未安装 RDKit, 无法按需生成结构图.")
            return None

        try:
            mol = Chem.MolFromMolFile(str(mol_path), sanitize=True, removeHs=False)
            if mol is None:
                mol = Chem.MolFromMolFile(str(mol_path), sanitize=False, removeHs=False)
            if mol is None:
                logger.warning("按需渲染失败, MOL 解析失败: %s", mol_path)
                return None

            target_path.parent.mkdir(parents=True, exist_ok=True)
            image = Draw.MolToImage(mol, size=(self._image_size, self._image_size))
            image.save(str(target_path), dpi=(self._image_ppi, self._image_ppi))
            logger.info("按需生成结构图成功, key=%s, 来源=%s", structure_key, mol_path.name)
            return target_path
        except Exception as exc:
            logger.warning("按需渲染结构图异常, key=%s, MOL=%s, 错误=%s", structure_key, mol_path, exc)
            return None

    @staticmethod
    def _format_cas_digits(cas_digits: str) -> str:
        """
        功能:
            将纯数字 CAS 转换为带连字符格式.
        参数:
            cas_digits: CAS 纯数字字符串.
        返回:
            str, 规范化 CAS 字符串. 不可格式化时返回空字符串.
        """
        if cas_digits.isdigit() is False:
            return ""
        if len(cas_digits) < 3:
            return ""

        left_part = cas_digits[:-3]
        middle_part = cas_digits[-3:-1]
        right_part = cas_digits[-1]
        if left_part == "":
            return ""
        return f"{left_part}-{middle_part}-{right_part}"

    def _resolve_fallback_cas_candidates(self, match: CompoundMatch) -> List[str]:
        """
        功能:
            组装 PubChem 回退时的 CAS 候选列表.
        参数:
            match: 单个化合物命中.
        返回:
            List[str], 候选 CAS 列表.
        """
        candidates: List[str] = []

        original_cas = match.cas_number.strip()
        if original_cas not in _INVALID_CAS_PATTERNS and original_cas != "":
            candidates.append(original_cas)

        mapped_cas_digits = self._resolve_seed_cas_digits(match)
        if mapped_cas_digits != "":
            mapped_cas = self._format_cas_digits(mapped_cas_digits)
            if mapped_cas and mapped_cas not in candidates:
                candidates.append(mapped_cas)
            if mapped_cas_digits not in candidates:
                candidates.append(mapped_cas_digits)

        return candidates

    def _fetch_with_legacy_fallback(self, match: CompoundMatch) -> Optional[Path]:
        """
        功能:
            在非严格离线模式下回退到历史 CAS -> PubChem 链路.
        参数:
            match: 单个化合物命中.
        返回:
            Optional[Path], 回退链路得到的结构图路径.
        """
        if self._offline_only is True:
            return None

        if self._fallback_fetcher is None:
            return None

        cas_candidates = self._resolve_fallback_cas_candidates(match)
        if len(cas_candidates) == 0:
            logger.info(
                "本地结构未命中且无可用 CAS, 跳过 PubChem 回退: 化合物=%s, NIST#=%s, Lib=%s",
                match.compound_name or "(未知)",
                match.nist_id,
                match.library or "(空)",
            )
            return None

        for cas_number in cas_candidates:
            logger.info(
                "本地结构未命中, 回退 PubChem: 化合物=%s, CAS=%s, NIST#=%s, Lib=%s",
                match.compound_name or "(未知)",
                cas_number,
                match.nist_id,
                match.library or "(空)",
            )
            fetched_path = self._fallback_fetcher.fetch_structure(cas_number)
            if fetched_path is not None:
                return fetched_path
        return None


class StructureFetcher:
    """
    功能:
        根据 CAS 号获取化合物 2D 结构图 PNG 文件.
        优先从本地缓存读取, 未命中时通过 PubChem REST API 在线下载.
    参数:
        task_cache_dir: 任务级缓存目录 (如 report_dir/task_id/structures/).
        global_cache_dir: 全局缓存目录, 跨任务共享. None 表示不使用全局缓存.
        image_size: PubChem 下载图片尺寸 (正方形边长, 像素).
        image_ppi: 结构图写盘分辨率, 仅本地渲染路径生效.
        timeout: 单次 HTTP 请求超时时间 (秒).
        request_interval: 连续请求间的最小间隔 (秒), 遵守 PubChem 速率限制.
    返回:
        无.
    """

    _PUBCHEM_CID_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{cas}/cids/TXT"
    _PUBCHEM_PNG_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/PNG"

    def __init__(
        self,
        task_cache_dir: Path,
        global_cache_dir: Optional[Path] = None,
        image_size: int = 200,
        image_ppi: int = 150,
        timeout: float = 10.0,
        request_interval: float = 0.2,
    ) -> None:
        self._task_cache_dir = task_cache_dir
        self._global_cache_dir = global_cache_dir
        self._image_size = image_size
        self._image_ppi = image_ppi
        self._timeout = timeout
        self._request_interval = request_interval

        # 确保缓存目录存在.
        self._task_cache_dir.mkdir(parents=True, exist_ok=True)
        if self._global_cache_dir is not None:
            self._global_cache_dir.mkdir(parents=True, exist_ok=True)

    def fetch_structure(self, cas_number: str) -> Optional[Path]:
        """
        功能:
            根据 CAS 号获取化合物结构图 PNG 文件路径.
            查找顺序: 任务缓存 -> 全局缓存 -> PubChem 在线下载.
        参数:
            cas_number: CAS 注册号, 如 "74-95-3".
        返回:
            Optional[Path]: PNG 文件路径 (位于任务缓存目录), 失败返回 None.
        """
        if cas_number.strip() in _INVALID_CAS_PATTERNS:
            return None

        sanitized = _sanitize_cas(cas_number)
        filename = f"{sanitized}.png"

        # 第一级: 任务缓存.
        task_path = self._task_cache_dir / filename
        if task_path.exists():
            return task_path

        # 第二级: 全局缓存 (命中后复制到任务缓存).
        if self._global_cache_dir is not None:
            global_path = self._global_cache_dir / filename
            if global_path.exists():
                shutil.copy2(str(global_path), str(task_path))
                logger.debug("从全局缓存复制结构图: %s -> %s", global_path, task_path)
                return task_path

        # 第三级: PubChem 在线下载.
        png_data = self._download_from_pubchem(cas_number)
        if png_data is None:
            return None

        # 写入任务缓存.
        task_path.write_bytes(png_data)
        logger.info("结构图已下载并缓存: %s (%s)", cas_number, task_path)

        # 同步写入全局缓存.
        if self._global_cache_dir is not None:
            global_path = self._global_cache_dir / filename
            global_path.write_bytes(png_data)

        return task_path

    def fetch_batch(self, cas_numbers: List[str]) -> Dict[str, Optional[Path]]:
        """
        功能:
            批量获取多个 CAS 号的结构图, 自动去重, 过滤无效 CAS.
        参数:
            cas_numbers: CAS 号列表.
        返回:
            Dict[str, Optional[Path]]: CAS 号 -> PNG 文件路径映射.
        """
        # 去重并过滤无效值.
        unique_cas = set()
        for cas in cas_numbers:
            if cas.strip() not in _INVALID_CAS_PATTERNS:
                unique_cas.add(cas.strip())

        results: Dict[str, Optional[Path]] = {}
        download_count = 0

        for cas in unique_cas:
            # 先检查本地是否已有 (不计入下载).
            sanitized = _sanitize_cas(cas)
            task_path = self._task_cache_dir / f"{sanitized}.png"
            needs_download = not task_path.exists()

            if needs_download and self._global_cache_dir is not None:
                global_path = self._global_cache_dir / f"{sanitized}.png"
                needs_download = not global_path.exists()

            # 在线下载前加间隔, 避免触发 PubChem 速率限制.
            if needs_download and download_count > 0:
                time.sleep(self._request_interval)

            path = self.fetch_structure(cas)
            results[cas] = path

            if needs_download and path is not None:
                download_count += 1

        # 统计日志.
        success_count = sum(1 for v in results.values() if v is not None)
        logger.info(
            "批量结构图获取完成: %d/%d 成功 (其中在线下载 %d 个)",
            success_count,
            len(unique_cas),
            download_count,
        )
        return results

    def _download_from_pubchem(self, cas_number: str) -> Optional[bytes]:
        """
        功能:
            通过 PubChem REST API 下载化合物 2D 结构图 PNG.
            两步: 先由 CAS 号查 CID, 再由 CID 下载 PNG.
        参数:
            cas_number: CAS 注册号.
        返回:
            Optional[bytes]: PNG 图片二进制数据, 失败返回 None.
        """
        try:
            import requests
        except ImportError:
            logger.warning("requests 库未安装, 无法从 PubChem 下载结构图")
            return None

        # 步骤1: CAS -> CID.
        cid_url = self._PUBCHEM_CID_URL.format(cas=cas_number)
        try:
            resp = requests.get(cid_url, timeout=self._timeout)
            if resp.status_code != 200:
                logger.debug("PubChem CID 查询失败: CAS=%s, HTTP %d", cas_number, resp.status_code)
                return None
            cid = resp.text.strip().splitlines()[0].strip()
        except Exception as exc:
            logger.debug("PubChem CID 查询异常: CAS=%s, %s", cas_number, exc)
            return None

        # 步骤2: CID -> PNG.
        png_url = self._PUBCHEM_PNG_URL.format(cid=cid)
        params = {"image_size": f"{self._image_size}x{self._image_size}"}
        try:
            resp = requests.get(png_url, params=params, timeout=self._timeout)
            if resp.status_code != 200:
                logger.debug("PubChem PNG 下载失败: CID=%s, HTTP %d", cid, resp.status_code)
                return None
            return resp.content
        except Exception as exc:
            logger.debug("PubChem PNG 下载异常: CID=%s, %s", cid, exc)
            return None
