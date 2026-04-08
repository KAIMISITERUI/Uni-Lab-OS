# coding: utf-8
"""
功能:
    覆盖带托盘点位校准相关的控制器核心流程.

参数:
    无.

返回:
    无, 通过 unittest 执行断言.
"""

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
        AGVController, 用于带托盘点位校准测试的控制器实例.
    """
    with patch(_ARM_DRIVER_PATH), patch(_POS_MGR_PATH), patch(_SHELF_MANAGER_PATH):
        from eit_agv.controller.agv_controller import AGVController

        return AGVController()


class TestLoadedTrayCalibration(unittest.TestCase):
    """
    功能:
        带托盘点位校准控制器测试套件.

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

    def test_prepare_calibration_uses_fixed_agv_source_and_transition_helper(self) -> None:
        """
        功能:
            验证带托盘点位校准准备阶段固定从 agv_tray_1 夹取, 再复用过渡位运动 helper.

        参数:
            无.

        返回:
            无.
        """
        tray_position = SimpleNamespace(
            pose=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            speed=0.6,
            acceleration=0.3,
            lift_z=20,
        )
        station_offset = {"x": 1.0, "y": 2.0, "z": 3.0, "dx": 0.1, "dy": 0.2, "dz": 0.3}

        with patch.object(self.controller, "pick_tray", return_value=True) as mock_pick, patch.object(
            self.controller,
            "_get_tray_position_context",
            return_value=(tray_position, station_offset),
        ) as mock_context, patch.object(
            self.controller,
            "_move_to_put_transition_pose",
            return_value=True,
        ) as mock_transition:
            result = self.controller.prepare_loaded_tray_calibration(
                "synthesis_station_tray_1-1",
                block=True,
            )

        self.assertIs(result, True)
        mock_pick.assert_called_once_with("agv_tray_1", block=True)
        mock_context.assert_called_once_with("synthesis_station_tray_1-1")
        mock_transition.assert_called_once_with(
            tray_position,
            station_offset=station_offset,
            transition_z_offset=0,
            block=True,
        )

    def test_get_calibrated_pose_subtracts_station_offset(self) -> None:
        """
        功能:
            验证非 AGV 点位保存姿态时会减去工站校准偏移.

        参数:
            无.

        返回:
            无.
        """
        current_pose = [100.0, 200.0, 300.0, 1.1, 1.2, 1.3]
        self.controller.position_manager.get_calibration_offset.return_value = {
            "x": 10.0,
            "y": 20.0,
            "z": 30.0,
            "dx": 0.1,
            "dy": 0.2,
            "dz": 0.3,
        }

        with patch.object(
            self.controller,
            "_get_station_name_from_tray",
            return_value="synthesis_station",
        ):
            pose_to_save = self.controller.get_calibrated_tray_pose_from_current_pose(
                "synthesis_station_tray_1-1",
                current_pose=current_pose,
            )

        self.assertEqual(
            pose_to_save,
            [90.0, 180.0, 270.0, 1.0, 1.0, 1.0],
        )

    def test_complete_calibration_reuses_finish_helper(self) -> None:
        """
        功能:
            验证带托盘点位校准收尾会复用松爪, 提升和回零 helper.

        参数:
            无.

        返回:
            无.
        """
        tray_position = SimpleNamespace(
            pose=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            speed=0.6,
            acceleration=0.3,
            lift_z=20,
        )

        with patch.object(
            self.controller,
            "_get_tray_position_context",
            return_value=(tray_position, None),
        ) as mock_context, patch.object(
            self.controller,
            "_finish_put_tray_from_current_pose",
            return_value=True,
        ) as mock_finish:
            result = self.controller.complete_loaded_tray_calibration(
                "synthesis_station_tray_1-1",
                block=True,
            )

        self.assertIs(result, True)
        mock_context.assert_called_once_with("synthesis_station_tray_1-1")
        mock_finish.assert_called_once_with(
            tray_position,
            lift_z=None,
            block=True,
        )

    def test_prepare_failure_before_manual_stage_does_not_cleanup_or_save(self) -> None:
        """
        功能:
            验证人工调整前准备失败时, 不会触发收尾 helper, 也不会保存配置.

        参数:
            无.

        返回:
            无.
        """
        tray_position = SimpleNamespace(
            pose=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            speed=0.6,
            acceleration=0.3,
            lift_z=20,
        )
        self.controller.position_manager.save_tray_position = MagicMock()

        with patch.object(self.controller, "pick_tray", return_value=True), patch.object(
            self.controller,
            "_get_tray_position_context",
            return_value=(tray_position, None),
        ), patch.object(
            self.controller,
            "_move_to_put_transition_pose",
            return_value=False,
        ), patch.object(
            self.controller,
            "_finish_put_tray_from_current_pose",
            return_value=True,
        ) as mock_finish:
            result = self.controller.prepare_loaded_tray_calibration(
                "synthesis_station_tray_1-1",
                block=True,
            )

        self.assertIs(result, False)
        mock_finish.assert_not_called()
        self.controller.position_manager.save_tray_position.assert_not_called()


if __name__ == "__main__":
    unittest.main()
