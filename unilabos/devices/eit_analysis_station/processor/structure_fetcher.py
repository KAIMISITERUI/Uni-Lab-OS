#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    提供化合物结构图获取能力.
    1. NistLocalStructureFetcher: 基于 NIST 本地索引的离线结构获取, 优先按 NIST Id 查找.
    2. StructureFetcher: 历史 CAS -> PubChem 结构下载链路, 仅作为回滚兜底保留.
参数:
    无.
返回:
    无.
"""

import json
import logging
import re
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional

from .nist_matcher import CompoundMatch

logger = logging.getLogger(__name__)

# 无效 CAS 号模式, 跳过查询.
_INVALID_CAS_PATTERNS = {"", "0", "0-00-0", "---", "N/A", "n/a"}


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
    if cas_digits:
        return f"CAS:{cas_digits}"

    return None


class NistLocalStructureFetcher:
    """
    功能:
        从本地结构索引加载 NIST 结构图并返回任务可用路径.
        索引文件约定:
        1. index_dir/index.json.
        2. 支持 by_nist_id 和 by_cas_digits 两类映射.
        3. 映射值可为绝对路径或相对 index_dir 的路径.
    参数:
        task_cache_dir: 任务级结构图缓存目录.
        index_dir: 结构索引目录, 内含 index.json.
        seed_mol_dir: NIST 导出的 MOL 目录, 用于按需渲染结构图.
        offline_only: 是否严格离线, True 时禁止回退 PubChem.
        global_cache_dir: 历史链路全局缓存目录, 仅 offline_only=False 时用于回退.
        image_size: 回退 PubChem 下载尺寸.
        timeout: 回退 PubChem 超时.
        request_interval: 回退 PubChem 请求间隔.
    返回:
        无.
    """

    _INDEX_FILE_NAME = "index.json"

    def __init__(
        self,
        task_cache_dir: Path,
        index_dir: Path,
        seed_mol_dir: Optional[Path] = None,
        offline_only: bool = True,
        global_cache_dir: Optional[Path] = None,
        image_size: int = 200,
        timeout: float = 10.0,
        request_interval: float = 0.2,
    ) -> None:
        self._task_cache_dir = Path(task_cache_dir)
        self._index_dir = Path(index_dir)
        self._index_path = self._index_dir / self._INDEX_FILE_NAME
        self._seed_mol_dir = Path(seed_mol_dir) if seed_mol_dir is not None else None
        self._offline_only = offline_only
        self._image_size = image_size

        self._task_cache_dir.mkdir(parents=True, exist_ok=True)

        self._by_nist_id: Dict[str, Path] = {}
        self._by_cas_digits: Dict[str, Path] = {}
        self._load_index()

        if self._seed_mol_dir is not None:
            if self._seed_mol_dir.is_dir() is True:
                logger.info("已启用按需结构图渲染, MOL 目录: %s", self._seed_mol_dir)
            else:
                logger.warning("MOL 目录不存在, 按需结构图渲染不可用: %s", self._seed_mol_dir)

        self._fallback_fetcher: Optional[StructureFetcher] = None
        if self._offline_only is False:
            self._fallback_fetcher = StructureFetcher(
                task_cache_dir=self._task_cache_dir,
                global_cache_dir=global_cache_dir,
                image_size=image_size,
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
            优先按 NIST:<id> 查找, 失败时按 CAS:<digits> 回退.
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

            local_path = self._find_local_path_for_match(match)
            if local_path is not None:
                results[key] = local_path
                continue

            on_demand_path = self._render_from_seed_mol(match, key)
            if on_demand_path is not None:
                results[key] = on_demand_path
                continue

            logger.warning(
                "结构未索引, key=%s, 化合物=%s, CAS=%s, NIST#=%s",
                key,
                match.compound_name or "(未知)",
                match.cas_number or "(空)",
                match.nist_id,
            )

            fallback_path = self._fetch_with_legacy_fallback(match)
            results[key] = fallback_path

        success_count = sum(1 for path in results.values() if path is not None)
        logger.info("本地结构图匹配完成: %d/%d 成功", success_count, len(results))
        return results

    def _load_index(self) -> None:
        """
        功能:
            读取 index.json 并加载 NIST 与 CAS 双索引.
        参数:
            无.
        返回:
            无.
        """
        if self._index_path.exists() is False:
            logger.info("本地结构索引不存在, 将在命中时按需渲染: %s", self._index_path)
            return

        try:
            payload = json.loads(self._index_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("读取本地结构索引失败: %s, 错误: %s", self._index_path, exc)
            return

        by_nist_id = payload.get("by_nist_id", {})
        by_cas_digits = payload.get("by_cas_digits", {})

        if isinstance(by_nist_id, dict):
            for key, value in by_nist_id.items():
                self._by_nist_id[str(key)] = self._resolve_index_png_path(value)

        if isinstance(by_cas_digits, dict):
            for key, value in by_cas_digits.items():
                self._by_cas_digits[str(key)] = self._resolve_index_png_path(value)

        logger.info(
            "已加载本地结构索引: NIST键=%d, CAS键=%d, 索引=%s",
            len(self._by_nist_id),
            len(self._by_cas_digits),
            self._index_path,
        )

    def _resolve_index_png_path(self, raw_path: str) -> Path:
        """
        功能:
            将索引中的路径值转换为绝对路径.
        参数:
            raw_path: index.json 中记录的路径.
        返回:
            Path, 解析后的路径对象.
        """
        path = Path(str(raw_path))
        if path.is_absolute():
            return path
        return self._index_dir / path

    def _find_local_path_for_match(self, match: CompoundMatch) -> Optional[Path]:
        """
        功能:
            在本地索引中按命中结果查找结构图并复制到任务缓存.
        参数:
            match: 单个化合物命中.
        返回:
            Optional[Path], 任务缓存中的结构图路径.
        """
        candidates: List[tuple[str, Path]] = []

        if match.nist_id is not None and match.nist_id > 0:
            nist_key = str(match.nist_id)
            if nist_key in self._by_nist_id:
                candidates.append((f"NIST:{match.nist_id}", self._by_nist_id[nist_key]))

        cas_digits = _normalize_cas_digits(match.cas_number)
        if cas_digits and cas_digits in self._by_cas_digits:
            candidates.append((f"CAS:{cas_digits}", self._by_cas_digits[cas_digits]))

        for structure_key, index_png_path in candidates:
            if index_png_path.exists() is False:
                logger.warning(
                    "结构索引命中但文件不存在, key=%s, 路径=%s",
                    structure_key,
                    index_png_path,
                )
                continue
            return self._copy_to_task_cache(index_png_path, structure_key)

        return None

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

        mol_path = self._find_seed_mol_path(match)
        if mol_path is None:
            return None

        target_path = self._task_cache_dir / f"{structure_key.replace(':', '_')}.png"
        if target_path.exists() is True:
            return target_path

        return self._render_mol_to_png(mol_path, target_path, structure_key)

    def _find_seed_mol_path(self, match: CompoundMatch) -> Optional[Path]:
        """
        功能:
            在种子 MOL 目录中按命中信息定位结构文件.
            规则:
            1. N<nist_id>.MOL.
            2. S<cas_digits>.MOL.
        参数:
            match: 单个化合物命中.
        返回:
            Optional[Path], 命中的 MOL 路径.
        """
        if self._seed_mol_dir is None:
            return None

        candidates: List[str] = []

        if match.nist_id is not None and match.nist_id > 0:
            candidates.append(f"N{match.nist_id}.MOL")

        cas_digits = _normalize_cas_digits(match.cas_number)
        if cas_digits:
            candidates.append(f"S{cas_digits}.MOL")

        for filename in candidates:
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
            image.save(str(target_path))
            logger.info("按需生成结构图成功, key=%s, 来源=%s", structure_key, mol_path.name)
            return target_path
        except Exception as exc:
            logger.warning("按需渲染结构图异常, key=%s, MOL=%s, 错误=%s", structure_key, mol_path, exc)
            return None

    def _copy_to_task_cache(self, source_path: Path, structure_key: str) -> Path:
        """
        功能:
            将索引中的图片复制到任务缓存目录并返回任务路径.
        参数:
            source_path: 索引图片源路径.
            structure_key: 结构键, 用于生成缓存文件名.
        返回:
            Path, 任务缓存路径.
        """
        safe_name = structure_key.replace(":", "_")
        suffix = source_path.suffix if source_path.suffix else ".png"
        target_path = self._task_cache_dir / f"{safe_name}{suffix}"

        if target_path.exists() is True:
            return target_path

        try:
            shutil.copy2(str(source_path), str(target_path))
            return target_path
        except Exception as exc:
            logger.warning(
                "复制结构图到任务缓存失败, 将回退使用索引路径: %s -> %s, 错误: %s",
                source_path,
                target_path,
                exc,
            )
            return source_path

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

        if match.cas_number.strip() in _INVALID_CAS_PATTERNS:
            return None

        logger.info(
            "本地索引未命中, 回退历史结构链路: 化合物=%s, CAS=%s",
            match.compound_name or "(未知)",
            match.cas_number,
        )
        return self._fallback_fetcher.fetch_structure(match.cas_number)


class StructureFetcher:
    """
    功能:
        根据 CAS 号获取化合物 2D 结构图 PNG 文件.
        优先从本地缓存读取, 未命中时通过 PubChem REST API 在线下载.
    参数:
        task_cache_dir: 任务级缓存目录 (如 report_dir/task_id/structures/).
        global_cache_dir: 全局缓存目录, 跨任务共享. None 表示不使用全局缓存.
        image_size: PubChem 下载图片尺寸 (正方形边长, 像素).
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
        timeout: float = 10.0,
        request_interval: float = 0.2,
    ) -> None:
        self._task_cache_dir = task_cache_dir
        self._global_cache_dir = global_cache_dir
        self._image_size = image_size
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
