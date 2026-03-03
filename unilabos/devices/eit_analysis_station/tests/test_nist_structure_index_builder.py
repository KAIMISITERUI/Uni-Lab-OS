#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    验证 NIST 本地结构索引构建脚本行为.
参数:
    无.
返回:
    无.
"""

import json
import unittest
from pathlib import Path
from uuid import uuid4

from eit_analysis_station.scripts.build_nist_structure_index import build_nist_structure_index


class TestNistStructureIndexBuilder(unittest.TestCase):
    """
    功能:
        覆盖最小样例下的 index.json 构建与键映射.
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
        case_dir = tmp_root / f"index_{uuid4().hex}"
        case_dir.mkdir(parents=True, exist_ok=False)
        return case_dir

    def test_build_index_with_minimal_seed_files(self) -> None:
        """
        功能:
            使用最小 MSP + MOL 样例验证 NIST 和 CAS 双键可查.
        参数:
            无.
        返回:
            无.
        """
        try:
            from rdkit import Chem
        except ImportError as exc:
            self.skipTest(f"RDKit 不可用, 跳过: {exc}")

        tmp_path = self._make_tmp_dir()
        seed_msp = tmp_path / "mainlib_export.msp"
        seed_mol_dir = tmp_path / "mainlib_export.MOL"
        index_dir = tmp_path / "index"
        seed_mol_dir.mkdir(parents=True, exist_ok=True)

        # 构造最小 MSP 记录.
        seed_msp.write_text(
            "\n".join(
                [
                    "Name: Benzylamine",
                    "CASNO: 100469",
                    "ID: 123",
                    "Comment: ; NIST MS# 22326, Seq# M1",
                    "Num peaks: 1",
                    "91 9999",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        # 写入对应 NIST 命名 MOL 文件.
        mol = Chem.MolFromSmiles("NCc1ccccc1")
        Chem.MolToMolFile(mol, str(seed_mol_dir / "N22326.MOL"))

        stats = build_nist_structure_index(
            seed_msp=seed_msp,
            seed_mol_dir=seed_mol_dir,
            index_dir=index_dir,
            image_size=160,
        )

        self.assertEqual(stats["total_records"], 1)
        self.assertEqual(stats["render_failed_records"], 0)

        index_path = index_dir / "index.json"
        self.assertTrue(index_path.exists())

        payload = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertIn("22326", payload["by_nist_id"])
        self.assertIn("100469", payload["by_cas_digits"])

        nist_png = index_dir / payload["by_nist_id"]["22326"]
        cas_png = index_dir / payload["by_cas_digits"]["100469"]
        self.assertTrue(nist_png.exists())
        self.assertTrue(cas_png.exists())


if __name__ == "__main__":
    unittest.main()

