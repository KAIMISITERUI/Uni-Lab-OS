# coding: utf-8
"""
功能:
    覆盖工站整体偏差矫正中带托盘校准相关的控制器流程.

参数:
    无.

返回:
    无, 通过 unittest 执行断言.
"""

import io
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


_ARM_DRIVER_PATH = "eit_agv.controller.agv_controller.ArmDriver"
_POS_MGR_PATH = "eit_agv.controller.agv_controller.PositionManager"
_SHELF_MANAGER_PATH = "eit_agv.controller.agv_controller.ShelfManager"


def _make_controller():
    """
    功能:
        创建 AGVController 实例, 并替换硬件相关依赖, 避免连接真实设备.

    参数:
        无.

    返回:
        AGVController, 用于工站整体偏差矫正测试的控制器实例.
    """
    with patch(_ARM_DRIVER_PATH), patch(_POS_MGR_PATH), patch(_SHELF_MANAGER_PATH):
        from eit_agv.controller.agv_controller import AGVController

        return AGVController()


class TestStationOffsetCalibration(unittest.TestCase):
    """
    功能:
        工站整体偏差矫正控制器测试套件.

    参数:
        无.

    返回:
        无.
    """

    def setUp(self) -> None:
        """
        功能:
            为每个测试用例准备独立的控制器实例.

        参数:
            无.

        返回:
            无.
        """
        self.controller = _make_controller()

    def _assert_offset_equal(self, actual: dict, expected: dict) -> None:
        """
        功能:
            逐项比较偏移量结果, 避免浮点尾差导致断言失败.

        参数:
            actual: 实际返回的偏移量字典.
            expected: 期望偏移量字典.

        返回:
            无.
        """
        self.assertEqual(set(actual.keys()), set(expected.keys()))
        for key, expected_value in expected.items():
            self.assertAlmostEqual(actual[key], expected_value)

    def test_loaded_station_offset_calibration_reuses_prepare_and_cleanup(self) -> None:
        """
        功能:
            验证带托盘工站整体偏差矫正会复用准备与收尾 helper, 且取消应用时仍会收尾.

        参数:
            无.

        返回:
            无.
        """
        self.controller.position_manager.get_category.return_value = {
            "synthesis_station_tray_1-1": {"description": "参考点位"},
        }
        self.controller.position_manager.get_position.return_value = SimpleNamespace(
            pose=[1.0, 2.0, 3.0, 0.1, 0.2, 0.3]
        )
        self.controller.arm.get_tcp_pose.return_value = [11.0, 22.0, 33.0, 0.4, 0.5, 0.6]

        with patch.object(
            self.controller,
            "query_current_station",
            return_value={
                "station_id": "LM1",
                "station_name": "synthesis_station",
                "description": "合成工站位置",
            },
        ), patch.object(self.controller, "_ensure_connected", return_value=True), patch.object(
            self.controller,
            "prepare_loaded_tray_calibration",
            return_value=True,
        ) as mock_prepare, patch.object(
            self.controller,
            "complete_loaded_tray_calibration",
            return_value=True,
        ) as mock_cleanup, patch.object(
            self.controller,
            "move_to_grasp_position",
            return_value=True,
        ) as mock_move, patch(
            "builtins.input",
            side_effect=["2", "n", "1", "y", "", "n"],
        ), patch("sys.stdout", new=io.StringIO()):
            result = self.controller.calibrate_station_offset(block=True)

        self._assert_offset_equal(
            result,
            {"x": 10.0, "y": 20.0, "z": 30.0, "rx": 0.3, "ry": 0.3, "rz": 0.3},
        )
        mock_prepare.assert_called_once_with(
            "synthesis_station_tray_1-1",
            source_tray_name="agv_tray_1",
            block=True,
        )
        mock_cleanup.assert_called_once_with(
            "synthesis_station_tray_1-1",
            block=True,
        )
        mock_move.assert_not_called()
        self.controller.position_manager.save_tray_position.assert_not_called()

    def test_loaded_station_offset_calibration_uses_vision_offset(self) -> None:
        """
        功能:
            验证非AGV工站带托盘校准时, 偏移量计算会基于原始位姿叠加视觉偏移.

        参数:
            无.

        返回:
            无.
        """
        self.controller.position_manager.get_category.return_value = {
            "synthesis_station_tray_1-1": {"description": "参考点位"},
        }
        self.controller.position_manager.get_position.return_value = SimpleNamespace(
            pose=[10.0, 20.0, 30.0, 1.0, 1.1, 1.2]
        )
        self.controller.arm.get_tcp_pose.return_value = [16.0, 28.0, 42.0, 1.5, 1.8, 2.1]
        self.controller.calibrate_station = MagicMock(
            return_value={"x": 1.0, "y": 2.0, "z": 3.0, "dx": 0.1, "dy": 0.2, "dz": 0.3}
        )

        with patch.object(
            self.controller,
            "query_current_station",
            return_value={
                "station_id": "LM1",
                "station_name": "synthesis_station",
                "description": "合成工站位置",
            },
        ), patch.object(self.controller, "_ensure_connected", return_value=True), patch.object(
            self.controller,
            "prepare_loaded_tray_calibration",
            return_value=True,
        ), patch.object(
            self.controller,
            "complete_loaded_tray_calibration",
            return_value=True,
        ), patch(
            "builtins.input",
            side_effect=["2", "y", "1", "y", "", "n"],
        ), patch("sys.stdout", new=io.StringIO()):
            result = self.controller.calibrate_station_offset(block=True)

        self._assert_offset_equal(
            result,
            {"x": 5.0, "y": 6.0, "z": 9.0, "rx": 0.4, "ry": 0.5, "rz": 0.6},
        )
        self.controller.calibrate_station.assert_called_once_with(block=True)

    def test_loaded_station_offset_calibration_allows_agv_tray_reference(self) -> None:
        """
        功能:
            验证 AGV 工站在带托盘模式下允许选择 agv_tray_1 作为参考点位.

        参数:
            无.

        返回:
            无.
        """
        self.controller.position_manager.get_category.return_value = {
            "agv_tray_1": {"description": "AGV托盘位"},
        }
        self.controller.position_manager.get_position.return_value = SimpleNamespace(
            pose=[100.0, 200.0, 300.0, 1.0, 2.0, 3.0]
        )
        self.controller.arm.get_tcp_pose.return_value = [101.0, 202.0, 303.0, 1.1, 2.2, 3.3]

        with patch.object(
            self.controller,
            "query_current_station",
            return_value=None,
        ), patch.object(self.controller, "_ensure_connected", return_value=True), patch.object(
            self.controller,
            "prepare_loaded_tray_calibration",
            return_value=True,
        ) as mock_prepare, patch.object(
            self.controller,
            "complete_loaded_tray_calibration",
            return_value=True,
        ) as mock_cleanup, patch(
            "builtins.input",
            side_effect=["1", "1", "y", "", "n"],
        ), patch("sys.stdout", new=io.StringIO()):
            result = self.controller.calibrate_station_offset(block=True)

        self._assert_offset_equal(
            result,
            {"x": 1.0, "y": 2.0, "z": 3.0, "rx": 0.1, "ry": 0.2, "rz": 0.3},
        )
        mock_prepare.assert_called_once_with(
            "agv_tray_1",
            source_tray_name="agv_tray_1",
            block=True,
        )
        mock_cleanup.assert_called_once_with(
            "agv_tray_1",
            block=True,
        )


if __name__ == "__main__":
    unittest.main()
