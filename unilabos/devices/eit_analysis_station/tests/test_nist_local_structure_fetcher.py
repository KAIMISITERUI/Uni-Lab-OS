#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    验证 NistLocalStructureFetcher 运行时映射, 本地渲染与回退行为.
参数:
    无.
返回:
    无.
"""

import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from eit_analysis_station.processor.nist_matcher import CompoundMatch
from eit_analysis_station.processor.structure_fetcher import NistLocalStructureFetcher


class TestNistLocalStructureFetcher(unittest.TestCase):
    """
    功能:
        覆盖运行时映射构建, 本地渲染, PubChem 回退与缓存复用.
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

    @staticmethod
    def _write_seed_msp(seed_msp_path: Path) -> None:
        """
        功能:
            写入最小 MSP 样例, 含 mainlib 与 replib 序号映射.
        参数:
            seed_msp_path: MSP 文件路径.
        返回:
            无.
        """
        seed_msp_path.write_text(
            "\n".join(
                [
                    "Name: Benzylamine",
                    "CASNO: 100469",
                    "ID: 5989",
                    "Comment: ; NIST MS# 414443, Seq# R22326",
                    "Num peaks: 1",
                    "91 9999",
                    "",
                    "Name: Benzene, iodo-",
                    "CASNO: 591504",
                    "ID: 87779",
                    "Comment: ; NIST MS# 39523, Seq# R39523",
                    "Num peaks: 1",
                    "204 9999",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    def test_runtime_mapping_renders_from_replib_sequence_id(self) -> None:
        """
        功能:
            验证可通过 Lib=replib + Id(Seq#) 映射到 CAS 并完成本地渲染.
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
        seed_msp_path = tmp_path / "mainlib_export.msp"
        seed_mol_dir = tmp_path / "mainlib_export.MOL"
        runtime_cache_path = tmp_path / "nist_runtime_map.pkl"
        seed_mol_dir.mkdir(parents=True, exist_ok=True)
        self._write_seed_msp(seed_msp_path)

        mol = Chem.MolFromSmiles("NCc1ccccc1")
        self.assertIsNotNone(mol)
        Chem.MolToMolFile(mol, str(seed_mol_dir / "S100469.MOL"))

        fetcher = NistLocalStructureFetcher(
            task_cache_dir=tmp_path / "task",
            seed_msp_path=seed_msp_path,
            seed_mol_dir=seed_mol_dir,
            runtime_cache_path=runtime_cache_path,
            offline_only=True,
        )

        matches = [
            CompoundMatch(
                compound_name="Benzylamine",
                cas_number="",
                library="replib",
                nist_id=22326,
            )
        ]
        result = fetcher.fetch_batch_from_matches(matches)

        self.assertIn("NIST:22326", result)
        self.assertIsNotNone(result["NIST:22326"])
        self.assertTrue(result["NIST:22326"].exists())

    def test_runtime_mapping_supports_global_nist_ms_key(self) -> None:
        """
        功能:
            验证缺少库类型时, 仍可按全局 NIST MS# 回退映射 CAS.
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
        seed_msp_path = tmp_path / "mainlib_export.msp"
        seed_mol_dir = tmp_path / "mainlib_export.MOL"
        seed_mol_dir.mkdir(parents=True, exist_ok=True)
        self._write_seed_msp(seed_msp_path)

        mol = Chem.MolFromSmiles("IC1=CC=CC=C1")
        self.assertIsNotNone(mol)
        Chem.MolToMolFile(mol, str(seed_mol_dir / "S591504.MOL"))

        fetcher = NistLocalStructureFetcher(
            task_cache_dir=tmp_path / "task",
            seed_msp_path=seed_msp_path,
            seed_mol_dir=seed_mol_dir,
            runtime_cache_path=tmp_path / "nist_runtime_map.pkl",
            offline_only=True,
        )

        matches = [
            CompoundMatch(
                compound_name="Benzene, iodo-",
                cas_number="",
                library="",
                nist_id=39523,
            )
        ]
        result = fetcher.fetch_batch_from_matches(matches)

        self.assertIn("NIST:39523", result)
        self.assertIsNotNone(result["NIST:39523"])
        self.assertTrue(result["NIST:39523"].exists())

    def test_resolve_seed_cas_skips_global_nist_ms_fallback_for_known_library(self) -> None:
        """
        功能:
            验证库类型已知但序号未命中时, 不会把 Id 误当 NIST MS# 导致错配.
        参数:
            无.
        返回:
            无.
        """
        tmp_path = self._make_tmp_dir()
        seed_msp_path = tmp_path / "mainlib_export.msp"
        seed_msp_path.write_text(
            "\n".join(
                [
                    "Name: Not iodobenzene",
                    "CASNO: 30616172",
                    "ID: 12345",
                    "Comment: ; NIST MS# 39523, Seq# M99999",
                    "Num peaks: 1",
                    "100 9999",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        fetcher = NistLocalStructureFetcher(
            task_cache_dir=tmp_path / "task",
            seed_msp_path=seed_msp_path,
            seed_mol_dir=None,
            runtime_cache_path=tmp_path / "nist_runtime_map.pkl",
            offline_only=True,
        )

        match = CompoundMatch(
            compound_name="Benzene, iodo-",
            cas_number="591-50-4",
            library="replib",
            nist_id=39523,
        )

        self.assertEqual(fetcher._resolve_seed_cas_digits(match), "591504")

    def test_pubchem_fallback_uses_mapped_cas_when_hit_cas_invalid(self) -> None:
        """
        功能:
            验证命中 CAS 无效时, 可用运行时映射 CAS 触发 PubChem 回退.
        参数:
            无.
        返回:
            无.
        """
        tmp_path = self._make_tmp_dir()
        seed_msp_path = tmp_path / "mainlib_export.msp"
        seed_mol_dir = tmp_path / "mainlib_export.MOL"
        seed_mol_dir.mkdir(parents=True, exist_ok=True)
        self._write_seed_msp(seed_msp_path)

        # 仅需文件存在以参与映射, 不要求可渲染.
        (seed_mol_dir / "S100469.MOL").write_text("MOL", encoding="utf-8")

        fake_png = tmp_path / "100-46-9.png"
        fake_png.write_bytes(b"png")

        with patch(
            "eit_analysis_station.processor.structure_fetcher.StructureFetcher.fetch_structure",
            return_value=fake_png,
        ) as fetch_mock:
            fetcher = NistLocalStructureFetcher(
                task_cache_dir=tmp_path / "task",
                seed_msp_path=seed_msp_path,
                seed_mol_dir=seed_mol_dir,
                runtime_cache_path=tmp_path / "nist_runtime_map.pkl",
                offline_only=False,
            )
            result = fetcher.fetch_batch_from_matches(
                [
                    CompoundMatch(
                        compound_name="Benzylamine",
                        cas_number="0",
                        library="replib",
                        nist_id=22326,
                    )
                ]
            )

        self.assertIn("NIST:22326", result)
        self.assertEqual(result["NIST:22326"], fake_png)
        fetch_mock.assert_called()
        first_cas = fetch_mock.call_args_list[0].args[0]
        self.assertEqual(first_cas, "100-46-9")

    def test_offline_mode_does_not_use_network_fallback(self) -> None:
        """
        功能:
            验证 offline_only=True 时不会触发 PubChem 回退.
        参数:
            无.
        返回:
            无.
        """
        tmp_path = self._make_tmp_dir()

        with patch(
            "eit_analysis_station.processor.structure_fetcher.StructureFetcher.fetch_structure",
            side_effect=AssertionError("offline_only=True 时不应触发网络回退"),
        ):
            fetcher = NistLocalStructureFetcher(
                task_cache_dir=tmp_path / "task",
                seed_msp_path=None,
                seed_mol_dir=None,
                runtime_cache_path=tmp_path / "nist_runtime_map.pkl",
                offline_only=True,
            )
            result = fetcher.fetch_batch_from_matches(
                [CompoundMatch(compound_name="Unknown", cas_number="123-45-6", nist_id=None)]
            )

        self.assertIn("CAS:123456", result)
        self.assertIsNone(result["CAS:123456"])

    def test_runtime_cache_written_and_reused(self) -> None:
        """
        功能:
            验证运行时映射缓存可写入且可复用加载.
        参数:
            无.
        返回:
            无.
        """
        tmp_path = self._make_tmp_dir()
        seed_msp_path = tmp_path / "mainlib_export.msp"
        seed_mol_dir = tmp_path / "mainlib_export.MOL"
        runtime_cache_path = tmp_path / "nist_runtime_map.pkl"
        seed_mol_dir.mkdir(parents=True, exist_ok=True)
        self._write_seed_msp(seed_msp_path)
        (seed_mol_dir / "S100469.MOL").write_text("MOL", encoding="utf-8")

        fetcher_first = NistLocalStructureFetcher(
            task_cache_dir=tmp_path / "task1",
            seed_msp_path=seed_msp_path,
            seed_mol_dir=seed_mol_dir,
            runtime_cache_path=runtime_cache_path,
            offline_only=True,
        )
        self.assertTrue(runtime_cache_path.exists())

        match = CompoundMatch(
            compound_name="Benzylamine",
            cas_number="",
            library="replib",
            nist_id=22326,
        )
        self.assertEqual(fetcher_first._resolve_seed_cas_digits(match), "100469")

        with patch.object(
            NistLocalStructureFetcher,
            "_build_runtime_mapping_from_seed",
            side_effect=AssertionError("缓存命中时不应重新构建映射"),
        ):
            fetcher_second = NistLocalStructureFetcher(
                task_cache_dir=tmp_path / "task2",
                seed_msp_path=seed_msp_path,
                seed_mol_dir=seed_mol_dir,
                runtime_cache_path=runtime_cache_path,
                offline_only=True,
            )

        self.assertEqual(fetcher_second._resolve_seed_cas_digits(match), "100469")


if __name__ == "__main__":
    unittest.main()
