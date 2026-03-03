#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    验证 NistLocalStructureFetcher 本地索引读取与离线行为.
参数:
    无.
返回:
    无.
"""

import json
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from eit_analysis_station.processor.nist_matcher import CompoundMatch
from eit_analysis_station.processor.structure_fetcher import NistLocalStructureFetcher


class TestNistLocalStructureFetcher(unittest.TestCase):
    """
    功能:
        覆盖本地索引命中, CAS 回退命中, 离线不触网.
    参数:
        无.
    返回:
        无.
    """

    @staticmethod
    def _make_tmp_dir() -> Path:
        """
        功能:
            在仓库可写目录创建临时测试目录.
        参数:
            无.
        返回:
            Path, 临时目录路径.
        """
        tmp_root = Path.cwd() / "eit_analysis_station" / "tests" / "_tmp"
        tmp_root.mkdir(parents=True, exist_ok=True)
        case_dir = tmp_root / f"fetcher_{uuid4().hex}"
        case_dir.mkdir(parents=True, exist_ok=False)
        return case_dir

    def test_fetch_batch_prefers_nist_id_and_falls_back_to_cas(self) -> None:
        """
        功能:
            验证 nist_id 优先命中, 无 nist_id 时使用 CAS 键命中.
        参数:
            无.
        返回:
            无.
        """
        tmp_path = self._make_tmp_dir()
        index_dir = tmp_path / "index"
        task_cache_dir = tmp_path / "task"
        png_dir = index_dir / "png"
        png_dir.mkdir(parents=True, exist_ok=True)

        nist_png = png_dir / "N22326.png"
        cas_png = png_dir / "S100618.png"
        nist_png.write_bytes(b"nist")
        cas_png.write_bytes(b"cas")

        payload = {
            "version": 1,
            "by_nist_id": {"22326": "png/N22326.png"},
            "by_cas_digits": {"100618": "png/S100618.png"},
        }
        (index_dir / "index.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        fetcher = NistLocalStructureFetcher(
            task_cache_dir=task_cache_dir,
            index_dir=index_dir,
            offline_only=True,
        )

        matches = [
            CompoundMatch(compound_name="Benzylamine", cas_number="100-46-9", nist_id=22326),
            CompoundMatch(compound_name="N-Methylaniline", cas_number="100-61-8", nist_id=None),
        ]
        result = fetcher.fetch_batch_from_matches(matches)

        self.assertIn("NIST:22326", result)
        self.assertIn("CAS:100618", result)
        self.assertIsNotNone(result["NIST:22326"])
        self.assertIsNotNone(result["CAS:100618"])
        self.assertTrue(result["NIST:22326"].exists())
        self.assertTrue(result["CAS:100618"].exists())

    def test_offline_mode_does_not_use_legacy_network_fallback(self) -> None:
        """
        功能:
            验证 offline_only=True 时不会调用历史 PubChem 回退链路.
        参数:
            无.
        返回:
            无.
        """
        tmp_path = self._make_tmp_dir()
        index_dir = tmp_path / "index"
        index_dir.mkdir(parents=True, exist_ok=True)
        (index_dir / "index.json").write_text(
            json.dumps({"version": 1, "by_nist_id": {}, "by_cas_digits": {}}),
            encoding="utf-8",
        )

        with patch(
            "eit_analysis_station.processor.structure_fetcher.StructureFetcher.fetch_structure",
            side_effect=AssertionError("offline_only=True 时不应触发网络回退"),
        ):
            fetcher = NistLocalStructureFetcher(
                task_cache_dir=tmp_path / "task",
                index_dir=index_dir,
                offline_only=True,
            )
            result = fetcher.fetch_batch_from_matches(
                [CompoundMatch(compound_name="Unknown", cas_number="123-45-6", nist_id=None)]
            )

        self.assertIn("CAS:123456", result)
        self.assertIsNone(result["CAS:123456"])

    def test_on_demand_render_from_seed_mol(self) -> None:
        """
        功能:
            验证索引缺失时可按命中结果从 seed MOL 目录按需生成结构图.
        参数:
            无.
        返回:
            无.
        """
        try:
            from rdkit import Chem
        except ImportError:
            self.skipTest("未安装 RDKit, 跳过按需渲染测试")

        tmp_path = self._make_tmp_dir()
        seed_mol_dir = tmp_path / "mainlib_export.MOL"
        seed_mol_dir.mkdir(parents=True, exist_ok=True)

        mol = Chem.MolFromSmiles("c1ccccc1N")
        self.assertIsNotNone(mol)
        Chem.MolToMolFile(mol, str(seed_mol_dir / "N22326.MOL"))

        fetcher = NistLocalStructureFetcher(
            task_cache_dir=tmp_path / "task",
            index_dir=tmp_path / "index",
            seed_mol_dir=seed_mol_dir,
            offline_only=True,
        )

        result = fetcher.fetch_batch_from_matches(
            [CompoundMatch(compound_name="Benzylamine", cas_number="", nist_id=22326)]
        )

        self.assertIn("NIST:22326", result)
        self.assertIsNotNone(result["NIST:22326"])
        self.assertTrue(result["NIST:22326"].exists())


if __name__ == "__main__":
    unittest.main()

