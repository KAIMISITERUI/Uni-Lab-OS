#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    验证 NISTMatcher 对 SRCRESLT 中 Id 字段解析行为.
参数:
    无.
返回:
    无.
"""

import unittest
from pathlib import Path
from uuid import uuid4

from eit_analysis_station.processor.nist_matcher import NISTMatcher


class TestNistMatcherParseId(unittest.TestCase):
    """
    功能:
        覆盖 SRCRESLT 解析中 nist_id 和 CAS=0 处理逻辑.
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
        case_dir = tmp_root / f"matcher_{uuid4().hex}"
        case_dir.mkdir(parents=True, exist_ok=False)
        return case_dir

    def test_parse_srcreslt_extracts_nist_id_and_handles_cas_zero(self) -> None:
        """
        功能:
            验证 Id 可解析为 nist_id, 且 CAS=0 会被清空.
        参数:
            无.
        返回:
            无.
        """
        srcreslt_text = "\n".join(
            [
                "Unknown: RT_1.000",
                "Hit 1  : <<Benzylamine>>;<<C7H9N>>; MF: 924; RMF: 928; Prob: 53.53; CAS:100-46-9; Mw: 107; Lib: <<replib>>; Id: 22326; RI: 1360891.",
                "Unknown: RT_2.000",
                "Hit 1  : <<NoCASCompound>>;<<C8H10O>>; MF: 700; RMF: 710; Prob: 5.0; CAS:0; Mw: 122; Lib: <<mainlib>>; RI: 1410000.",
            ]
        )

        tmp_dir = self._make_tmp_dir()
        src_path = tmp_dir / "SRCRESLT.TXT"
        src_path.write_text(srcreslt_text, encoding="utf-8")

        matcher = NISTMatcher(nist_path=None)
        matcher._srcreslt_path = src_path
        result = matcher._parse_srcreslt()

        self.assertIn("RT_1.000", result)
        self.assertIn("RT_2.000", result)

        hit_with_id = result["RT_1.000"][0]
        self.assertEqual(hit_with_id.nist_id, 22326)
        self.assertEqual(hit_with_id.cas_number, "100-46-9")

        hit_without_id = result["RT_2.000"][0]
        self.assertIsNone(hit_without_id.nist_id)
        self.assertEqual(hit_without_id.cas_number, "")


if __name__ == "__main__":
    unittest.main()

