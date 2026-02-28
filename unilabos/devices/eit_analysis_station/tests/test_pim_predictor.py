#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    PIM 预测器单元测试.
参数:
    无.
返回:
    无.
"""

import math
import unittest

import numpy as np

from eit_analysis_station.processor.molecular_mass_predictor import PIMPredictor


class TestPIMPredictor(unittest.TestCase):
    """
    功能:
        覆盖 PIM 核心路径, 归一化逻辑, 置信指数计算.
    参数:
        无.
    返回:
        无.
    """

    def setUp(self) -> None:
        self.predictor = PIMPredictor(
            ab_m=0.3,
            beta=5.0,
            epsilon_f=0.0,
        )
        self.predictor._illogical_losses = {-1, 2, 19}

    def test_md1_greater_than_two(self) -> None:
        """
        功能:
            覆盖 md1 > 2 路径, 直接返回当前高质量峰.
        """
        mz = np.array([40.0, 44.0, 50.0])
        intensity = np.array([20.0, 30.0, 100.0])
        result = self.predictor.predict(mz, intensity)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.predicted_mw, 50)

    def test_md1_equal_two_halogen_like(self) -> None:
        """
        功能:
            覆盖 md1 == 2 且 a1 < a0/2 的路径.
        """
        mz = np.array([100.0, 102.0, 104.0])
        intensity = np.array([5.0, 20.0, 100.0])
        result = self.predictor.predict(mz, intensity)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.predicted_mz, 104)

    def test_md1_equal_one_isotope_path(self) -> None:
        """
        功能:
            覆盖 md1 == 1 的同位素判定路径.
        """
        mz = np.array([100.0, 101.0, 102.0])
        intensity = np.array([5.0, 100.0, 5.0])
        result = self.predictor.predict(mz, intensity)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.predicted_mw, 101)

    def test_single_peak_and_empty_spectrum(self) -> None:
        """
        功能:
            覆盖单峰与空谱边界.
        """
        single_result = self.predictor.predict(np.array([77.0]), np.array([100.0]))
        self.assertEqual(single_result.status, "ok")
        self.assertEqual(single_result.predicted_mw, 77)

        empty_result = self.predictor.predict(np.array([]), np.array([]))
        self.assertEqual(empty_result.status, "no_spectrum")
        self.assertIsNone(empty_result.predicted_mw)

    def test_merge_duplicate_mz_take_max_intensity(self) -> None:
        """
        功能:
            验证重复 m/z 合并时取最大强度.
        """
        normalized_mz, normalized_int = self.predictor._normalize_spectrum(
            np.array([49.7, 50.2, 50.4]),
            np.array([10.0, 25.0, 15.0]),
        )
        self.assertEqual(list(normalized_mz), [50.0])
        self.assertEqual(list(normalized_int), [25.0])

    def test_confidence_formula_and_range(self) -> None:
        """
        功能:
            验证置信指数公式数值与取值范围.
        """
        mz = np.array([100.0, 101.0, 102.0])
        intensity = np.array([10.0, 30.0, 100.0])
        result = self.predictor.predict(mz, intensity)
        self.assertEqual(result.status, "ok")
        self.assertIsNotNone(result.confidence_index)
        self.assertGreaterEqual(result.confidence_index, 0.0)
        self.assertLessEqual(result.confidence_index, 2.0)

        expected_r_tau = 10.0 / 100.0
        expected_i = 2.0 - 2.0 / (1.0 + math.exp(-5.0 * expected_r_tau))
        self.assertAlmostEqual(result.confidence_index, expected_i, places=6)

    def test_confidence_returns_none_when_peak_abundance_non_positive(self) -> None:
        """
        功能:
            覆盖 pAb <= 0 时返回 None 的分支.
        """
        confidence = self.predictor._compute_confidence_index(
            gamma=100.0,
            mz_values=np.array([100.0]),
            intensities=np.array([0.0]),
        )
        self.assertIsNone(confidence)


if __name__ == "__main__":
    unittest.main()
