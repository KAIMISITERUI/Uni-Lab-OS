#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    根据 CAS 号获取化合物 2D 结构图 (PNG).
    三级查找策略:
    1. 任务级本地缓存 (report_dir/structures/).
    2. 全局缓存 (structure_cache_dir/), 跨任务共享.
    3. PubChem REST API 在线下载 (兜底).
参数:
    无.
返回:
    无.
"""

import logging
import re
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 无效 CAS 号模式, 跳过查询
_INVALID_CAS_PATTERNS = {"", "0-00-0", "---", "N/A", "n/a"}


def _sanitize_cas(cas_number: str) -> str:
    """将 CAS 号转为合法文件名, 如 '74-95-3' -> '74-95-3'."""
    return re.sub(r'[^\d\-]', '_', cas_number.strip())


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

        # 确保缓存目录存在
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

        # 第一级: 任务缓存
        task_path = self._task_cache_dir / filename
        if task_path.exists():
            return task_path

        # 第二级: 全局缓存 (命中后复制到任务缓存)
        if self._global_cache_dir is not None:
            global_path = self._global_cache_dir / filename
            if global_path.exists():
                shutil.copy2(str(global_path), str(task_path))
                logger.debug("从全局缓存复制结构图: %s -> %s", global_path, task_path)
                return task_path

        # 第三级: PubChem 在线下载
        png_data = self._download_from_pubchem(cas_number)
        if png_data is None:
            return None

        # 写入任务缓存
        task_path.write_bytes(png_data)
        logger.info("结构图已下载并缓存: %s (%s)", cas_number, task_path)

        # 同步写入全局缓存
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
        # 去重并过滤无效值
        unique_cas = set()
        for cas in cas_numbers:
            if cas.strip() not in _INVALID_CAS_PATTERNS:
                unique_cas.add(cas.strip())

        results: Dict[str, Optional[Path]] = {}
        download_count = 0

        for cas in unique_cas:
            # 先检查本地是否已有 (不计入下载)
            sanitized = _sanitize_cas(cas)
            task_path = self._task_cache_dir / f"{sanitized}.png"
            needs_download = not task_path.exists()

            if needs_download and self._global_cache_dir is not None:
                global_path = self._global_cache_dir / f"{sanitized}.png"
                needs_download = not global_path.exists()

            # 在线下载前加间隔, 避免触发 PubChem 速率限制
            if needs_download and download_count > 0:
                time.sleep(self._request_interval)

            path = self.fetch_structure(cas)
            results[cas] = path

            if needs_download and path is not None:
                download_count += 1

        # 统计日志
        success_count = sum(1 for v in results.values() if v is not None)
        logger.info(
            "批量结构图获取完成: %d/%d 成功 (其中在线下载 %d 个)",
            success_count, len(unique_cas), download_count,
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

        # 步骤1: CAS -> CID
        cid_url = self._PUBCHEM_CID_URL.format(cas=cas_number)
        try:
            resp = requests.get(cid_url, timeout=self._timeout)
            if resp.status_code != 200:
                logger.debug("PubChem CID 查询失败: CAS=%s, HTTP %d", cas_number, resp.status_code)
                return None
            cid = resp.text.strip().splitlines()[0].strip()
        except Exception as e:
            logger.debug("PubChem CID 查询异常: CAS=%s, %s", cas_number, e)
            return None

        # 步骤2: CID -> PNG
        png_url = self._PUBCHEM_PNG_URL.format(cid=cid)
        params = {"image_size": f"{self._image_size}x{self._image_size}"}
        try:
            resp = requests.get(png_url, params=params, timeout=self._timeout)
            if resp.status_code != 200:
                logger.debug("PubChem PNG 下载失败: CID=%s, HTTP %d", cid, resp.status_code)
                return None
            return resp.content
        except Exception as e:
            logger.debug("PubChem PNG 下载异常: CID=%s, %s", cid, e)
            return None
