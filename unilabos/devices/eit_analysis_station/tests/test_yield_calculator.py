#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    产率计算模块单元测试.
    覆盖 ECN 计算, 分子式推导, 实验范围解析, 峰匹配, 产率计算公式.
"""

import sys
from pathlib import Path

# 确保可以直接运行此测试脚本
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import unittest


class TestECN(unittest.TestCase):
    """ECN 计算测试."""

    def test_ethane(self):
        """乙烷 CC → ECN=2.0 (2个脂肪族碳)."""
        from eit_analysis_station.processor.yield_calculator import YieldCalculator
        ecn = YieldCalculator.calculate_ecn("CC")
        self.assertAlmostEqual(ecn, 2.0, places=2)

    def test_ethanol(self):
        """乙醇 CCO → ECN=1.5 (1个脂肪族 + 1个伯醇)."""
        from eit_analysis_station.processor.yield_calculator import YieldCalculator
        ecn = YieldCalculator.calculate_ecn("CCO")
        self.assertAlmostEqual(ecn, 1.5, places=2)

    def test_benzene(self):
        """苯 c1ccccc1 → ECN=6.0 (6个芳香族碳)."""
        from eit_analysis_station.processor.yield_calculator import YieldCalculator
        ecn = YieldCalculator.calculate_ecn("C1=CC=CC=C1")
        self.assertAlmostEqual(ecn, 6.0, places=2)

    def test_acetone(self):
        """丙酮 CC(=O)C → ECN=2.0 (2个脂肪族 + 1个羰基=0)."""
        from eit_analysis_station.processor.yield_calculator import YieldCalculator
        ecn = YieldCalculator.calculate_ecn("CC(=O)C")
        self.assertAlmostEqual(ecn, 2.0, places=2)


class TestSMILESToFormula(unittest.TestCase):
    """SMILES → 分子式测试."""

    def test_ethanol(self):
        from eit_analysis_station.processor.yield_calculator import YieldCalculator
        formula = YieldCalculator.smiles_to_formula("CCO")
        self.assertEqual(formula, "C2H6O")

    def test_benzene(self):
        from eit_analysis_station.processor.yield_calculator import YieldCalculator
        formula = YieldCalculator.smiles_to_formula("C1=CC=CC=C1")
        self.assertEqual(formula, "C6H6")

    def test_n_benzylaniline(self):
        """N-苄基苯胺: C13H13N."""
        from eit_analysis_station.processor.yield_calculator import YieldCalculator
        formula = YieldCalculator.smiles_to_formula("c1ccc(CNc2ccccc2)cc1")
        self.assertEqual(formula, "C13H13N")

    def test_triisopropylbenzene(self):
        """1,3,5-三异丙基苯: C15H24."""
        from eit_analysis_station.processor.yield_calculator import YieldCalculator
        formula = YieldCalculator.smiles_to_formula("CC(C)c1cc(C(C)C)cc(C(C)C)c1")
        self.assertEqual(formula, "C15H24")


class TestExperimentRange(unittest.TestCase):
    """适用实验范围解析测试."""

    def test_single(self):
        from eit_analysis_station.processor.yield_calculator import YieldCalculator
        self.assertEqual(YieldCalculator.parse_experiment_range("3"), [3])

    def test_range(self):
        from eit_analysis_station.processor.yield_calculator import YieldCalculator
        self.assertEqual(
            YieldCalculator.parse_experiment_range("1-6"),
            [1, 2, 3, 4, 5, 6],
        )

    def test_mixed(self):
        from eit_analysis_station.processor.yield_calculator import YieldCalculator
        self.assertEqual(
            YieldCalculator.parse_experiment_range("1-3,7,9-12"),
            [1, 2, 3, 7, 9, 10, 11, 12],
        )

    def test_all(self):
        from eit_analysis_station.processor.yield_calculator import YieldCalculator
        self.assertEqual(YieldCalculator.parse_experiment_range("all"), [])
        self.assertEqual(YieldCalculator.parse_experiment_range(""), [])

    def test_dedup(self):
        from eit_analysis_station.processor.yield_calculator import YieldCalculator
        self.assertEqual(
            YieldCalculator.parse_experiment_range("1-3,2-4"),
            [1, 2, 3, 4],
        )


class TestExtractExperimentNumber(unittest.TestCase):
    """样品名实验编号提取测试."""

    def test_normal(self):
        from eit_analysis_station.processor.yield_calculator import YieldCalculator
        self.assertEqual(YieldCalculator._extract_experiment_number("729-3"), 3)
        self.assertEqual(YieldCalculator._extract_experiment_number("729-12"), 12)

    def test_no_match(self):
        from eit_analysis_station.processor.yield_calculator import YieldCalculator
        self.assertIsNone(YieldCalculator._extract_experiment_number("sample"))


class TestPeakMatching(unittest.TestCase):
    """峰匹配测试."""

    def setUp(self):
        from eit_analysis_station.processor.yield_calculator import YieldCalculator
        self.calc = YieldCalculator(rt_tolerance=0.1)
        self.sample_rows = [
            {
                "FID保留时间(min)": 4.688,
                "FID峰面积": 48.823,
                "化合物1(分子式)": "C13H13N",
                "化合物1(名称)": "Aniline, N-benzyl-",
                "化合物2(分子式)": "",
            },
            {
                "FID保留时间(min)": 5.123,
                "FID峰面积": 12.456,
                "化合物1(分子式)": "C6H5Br",
                "化合物1(名称)": "Bromobenzene",
                "化合物2(分子式)": "",
            },
            {
                "FID保留时间(min)": 6.842,
                "FID峰面积": 79.770,
                "化合物1(分子式)": "C15H24",
                "化合物1(名称)": "1,3,5-Triisopropylbenzene",
                "化合物2(分子式)": "",
            },
        ]

    def test_rt_match(self):
        """优先按 RT 匹配."""
        row = self.calc.identify_peak(self.sample_rows, expected_rt=6.85, formula="C15H24")
        self.assertIsNotNone(row)
        self.assertAlmostEqual(row["FID保留时间(min)"], 6.842, places=2)

    def test_formula_match(self):
        """无 RT 时按分子式匹配."""
        row = self.calc.identify_peak(self.sample_rows, expected_rt=None, formula="C13H13N")
        self.assertIsNotNone(row)
        self.assertEqual(row["化合物1(名称)"], "Aniline, N-benzyl-")

    def test_no_match(self):
        """分子式不存在时返回 None."""
        row = self.calc.identify_peak(self.sample_rows, expected_rt=None, formula="C99H99")
        self.assertIsNone(row)

    def test_rt_out_of_tolerance(self):
        """RT 超出容差时返回 None."""
        row = self.calc.identify_peak(self.sample_rows, expected_rt=8.0, formula="")
        self.assertIsNone(row)


class TestYieldCalculation(unittest.TestCase):
    """产率计算公式测试."""

    def test_ecn_method(self):
        """ECN 法完整计算验证."""
        from eit_analysis_station.processor.yield_calculator import (
            YieldCalculator, YieldCalcConfig,
        )
        calc = YieldCalculator()
        config = YieldCalcConfig(
            calc_method="ECN",
            is_moles=1e-4,               # 0.1 mmol 内标
            reaction_scale_mmol=0.2,      # 0.2 mmol 反应规模
        )

        # 假设: 产物面积=50, 内标面积=100, 产物ECN=13, 内标ECN=15
        ratio, molar_ratio, n_product, yield_pct = calc._calculate_yield(
            fid_area_product=50.0,
            fid_area_is=100.0,
            ecn_product=13.0,
            ecn_is=15.0,
            config=config,
        )

        # ratio = 50/100 = 0.5
        self.assertAlmostEqual(ratio, 0.5, places=4)
        # molar_ratio = 0.5 * (15/13) = 0.5769...
        self.assertAlmostEqual(molar_ratio, 0.5 * 15.0 / 13.0, places=4)
        # n_product = molar_ratio * 1e-4
        expected_n = molar_ratio * 1e-4
        self.assertAlmostEqual(n_product, expected_n, places=8)
        # yield = n_product / (0.2/1000) * 100
        expected_yield = expected_n / (0.2 / 1000) * 100
        self.assertAlmostEqual(yield_pct, expected_yield, places=2)

    def test_response_factor_method(self):
        """响应因子法测试."""
        from eit_analysis_station.processor.yield_calculator import (
            YieldCalculator, YieldCalcConfig,
        )
        calc = YieldCalculator()
        config = YieldCalcConfig(
            calc_method="响应因子",
            response_factor=1.2,
            is_moles=1e-4,
            reaction_scale_mmol=0.2,
        )

        ratio, molar_ratio, n_product, yield_pct = calc._calculate_yield(
            fid_area_product=60.0,
            fid_area_is=100.0,
            ecn_product=0,      # 响应因子法不使用 ECN
            ecn_is=0,
            config=config,
        )

        self.assertAlmostEqual(ratio, 0.6, places=4)
        self.assertAlmostEqual(molar_ratio, 0.6 * 1.2, places=4)

    def test_zero_is_area(self):
        """内标面积为 0 时返回 None."""
        from eit_analysis_station.processor.yield_calculator import (
            YieldCalculator, YieldCalcConfig,
        )
        calc = YieldCalculator()
        config = YieldCalcConfig(calc_method="ECN", is_moles=1e-4, reaction_scale_mmol=0.2)

        result = calc._calculate_yield(50.0, 0.0, 13.0, 15.0, config)
        self.assertIsNone(result[0])  # ratio 应为 None

    def test_ecn_method_with_equivalent(self):
        """ECN 法 + 当量(eq) 计算验证: eq=1.5, reaction_scale=0.2 → 按 0.3mmol 计算."""
        from eit_analysis_station.processor.yield_calculator import (
            YieldCalculator, YieldCalcConfig,
        )
        calc = YieldCalculator()
        config = YieldCalcConfig(
            calc_method="ECN",
            is_moles=1e-4,               # 0.1 mmol 内标
            reaction_scale_mmol=0.2,      # 0.2 mmol 反应规模
        )

        ratio, molar_ratio, n_product, yield_pct = calc._calculate_yield(
            fid_area_product=50.0,
            fid_area_is=100.0,
            ecn_product=13.0,
            ecn_is=15.0,
            config=config,
            product_equivalent=1.5,       # 当量 1.5
        )

        # ratio = 50/100 = 0.5
        self.assertAlmostEqual(ratio, 0.5, places=4)
        # molar_ratio = 0.5 * (15/13)
        expected_molar = 0.5 * 15.0 / 13.0
        self.assertAlmostEqual(molar_ratio, expected_molar, places=4)
        # n_product = molar_ratio * 1e-4
        expected_n = expected_molar * 1e-4
        self.assertAlmostEqual(n_product, expected_n, places=8)
        # yield = n_product / (0.2 * 1.5 / 1000) * 100, 即按 0.3mmol 计算
        expected_yield = expected_n / (0.2 * 1.5 / 1000) * 100
        self.assertAlmostEqual(yield_pct, expected_yield, places=2)

        # 对比默认 eq=1.0 的结果, 确认 eq=1.5 产率更低
        _, _, _, yield_default = calc._calculate_yield(
            50.0, 100.0, 13.0, 15.0, config,
        )
        self.assertGreater(yield_default, yield_pct)


class TestActiveContentParsing(unittest.TestCase):
    """active_content 解析测试."""

    def test_solution_numeric(self):
        from eit_analysis_station.processor.yield_calculator import YieldCalculator
        t, v = YieldCalculator._parse_active_content(1.0, "solution")
        self.assertEqual(t, "mmol_per_ml")
        self.assertAlmostEqual(v, 1.0)

    def test_beads_wt_percent(self):
        from eit_analysis_station.processor.yield_calculator import YieldCalculator
        t, v = YieldCalculator._parse_active_content(5.0, "beads")
        self.assertEqual(t, "wt_percent")
        self.assertAlmostEqual(v, 5.0)

    def test_text_mmol(self):
        from eit_analysis_station.processor.yield_calculator import YieldCalculator
        t, v = YieldCalculator._parse_active_content("1.5 mmol/mL", "")
        self.assertEqual(t, "mmol_per_ml")
        self.assertAlmostEqual(v, 1.5)

    def test_empty(self):
        from eit_analysis_station.processor.yield_calculator import YieldCalculator
        t, v = YieldCalculator._parse_active_content(None, "")
        self.assertEqual(t, "")
        self.assertAlmostEqual(v, 0.0)


if __name__ == "__main__":
    unittest.main()
