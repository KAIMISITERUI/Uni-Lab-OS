"""
功能:
    覆盖 AGV 独立 CLI 入口的菜单分发行为.
参数:
    无.
返回:
    无.
"""

import io
import unittest
from unittest.mock import MagicMock, patch

from eit_agv import main as agv_main
from eit_agv.config.agv_config import STATION_POSITIONS


class TestAgvMain(unittest.TestCase):
    """
    功能:
        验证 AGV main.py 能正确分发交互菜单到对应控制器方法.
    参数:
        无.
    返回:
        无.
    """

    @staticmethod
    def _make_controller() -> MagicMock:
        """
        功能:
            创建带基础属性的 AGV 控制器 mock.
        参数:
            无.
        返回:
            MagicMock, 供交互菜单测试使用的控制器 mock.
        """
        controller = MagicMock()
        controller.current_station = "LM1"
        controller.query_current_station.return_value = {
            "station_id": "LM1",
            "station_name": "synthesis_station",
            "description": "合成工站位置",
        }
        controller._ensure_connected.return_value = True
        controller.arm = MagicMock()
        controller.arm.is_connected = False
        controller.position_manager = MagicMock()
        return controller

    def test_interactive_dispatches_connect(self) -> None:
        """
        功能:
            验证选择连接机械臂时会调用 controller.connect.
        参数:
            无.
        返回:
            无.
        """
        controller = self._make_controller()
        controller.connect.return_value = True

        with patch("eit_agv.main.AGVController", return_value=controller):
            with patch("builtins.input", side_effect=["1", "0"]):
                with patch("sys.stdout", new=io.StringIO()):
                    agv_main.interactive()

        controller.connect.assert_called_once_with()

    def test_interactive_dispatches_quick_change_submenu(self) -> None:
        """
        功能:
            验证快换子菜单会分发到松开快换动作.
        参数:
            无.
        返回:
            无.
        """
        controller = self._make_controller()
        controller.arm.release_quick_change.return_value = True

        with patch("eit_agv.main.AGVController", return_value=controller):
            with patch("builtins.input", side_effect=["9", "1", "0"]):
                with patch("sys.stdout", new=io.StringIO()):
                    agv_main.interactive()

        controller.arm.release_quick_change.assert_called_once_with(block=True)

    def test_interactive_dispatches_station_navigation(self) -> None:
        """
        功能:
            验证工站导航菜单会调用安全导航接口.
        参数:
            无.
        返回:
            无.
        """
        controller = self._make_controller()
        controller.safe_navigate_to_station.return_value = {"ret_code": 0}
        expected_station = next(iter(STATION_POSITIONS))

        with patch("eit_agv.main.AGVController", return_value=controller):
            with patch("builtins.input", side_effect=["16", "1", "0"]):
                with patch("sys.stdout", new=io.StringIO()):
                    agv_main.interactive()

        controller.safe_navigate_to_station.assert_called_once_with(expected_station)

    def test_interactive_handles_invalid_choice_and_exit(self) -> None:
        """
        功能:
            验证无效输入会给出提示且程序可继续退出.
        参数:
            无.
        返回:
            无.
        """
        controller = self._make_controller()
        output = io.StringIO()

        with patch("eit_agv.main.AGVController", return_value=controller):
            with patch("builtins.input", side_effect=["99", "0"]):
                with patch("sys.stdout", new=output):
                    agv_main.interactive()

        self.assertIn("无效的选项", output.getvalue())


    def test_interactive_menu_updates_tray_calibration_entries(self) -> None:
        """
        功能:
            验证顶层菜单移除独立带托盘入口, 并将输入范围调整为0-34.

        参数:
            无.

        返回:
            无.
        """
        controller = self._make_controller()
        output = io.StringIO()
        input_mock = MagicMock(side_effect=["0"])

        with patch("eit_agv.main.AGVController", return_value=controller):
            with patch("builtins.input", input_mock):
                with patch("sys.stdout", new=output):
                    agv_main.interactive()

        self.assertNotIn("34. 带托盘点位校准", output.getvalue())
        self.assertIn("34. 工站中间托盘点位自动计算", output.getvalue())
        self.assertTrue(
            any(call.args == ("请输入选项 (0-34): ",) for call in input_mock.call_args_list)
        )

    def test_interactive_dispatches_loaded_tray_calibration_from_choice_23(self) -> None:
        """
        功能:
            验证 23 号入口选择带托盘后, 会按原固定流程调用控制器方法.

        参数:
            无.

        返回:
            无.
        """
        controller = self._make_controller()
        controller.position_manager.get_category.return_value = {
            "synthesis_station_tray_1-1": {"description": "目标位"},
        }
        controller.position_manager.get_position.return_value = MagicMock(
            pose=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        )
        controller.prepare_loaded_tray_calibration.return_value = True
        controller.arm.get_tcp_pose.return_value = [10.0, 20.0, 30.0, 0.1, 0.2, 0.3]
        controller.get_calibrated_tray_pose_from_current_pose.return_value = [
            11.0,
            21.0,
            31.0,
            0.11,
            0.21,
            0.31,
        ]
        controller.save_calibrated_tray_position.return_value = True
        controller.complete_loaded_tray_calibration.return_value = True

        with patch("eit_agv.main.AGVController", return_value=controller):
            with patch("builtins.input", side_effect=["23", "y", "1", "y", "", "y", "0"]):
                with patch("sys.stdout", new=io.StringIO()):
                    agv_main.interactive()

        controller.prepare_loaded_tray_calibration.assert_called_once_with(
            "synthesis_station_tray_1-1",
            source_tray_name="agv_tray_1",
            block=True,
        )
        controller.get_calibrated_tray_pose_from_current_pose.assert_called_once_with(
            "synthesis_station_tray_1-1",
            current_pose=[10.0, 20.0, 30.0, 0.1, 0.2, 0.3],
        )
        controller.save_calibrated_tray_position.assert_called_once_with(
            "synthesis_station_tray_1-1",
            [11.0, 21.0, 31.0, 0.11, 0.21, 0.31],
        )
        controller.complete_loaded_tray_calibration.assert_called_once_with(
            "synthesis_station_tray_1-1",
            block=True,
        )

    def test_interactive_dispatches_unloaded_tray_calibration_from_choice_23(self) -> None:
        """
        功能:
            验证 23 号入口选择不夹托盘时, 仍走原空载托盘点位校准流程.

        参数:
            无.

        返回:
            无.
        """
        controller = self._make_controller()
        controller.position_manager.get_category.return_value = {
            "agv_tray_1": {"description": "AGV托盘位"},
        }
        controller.position_manager.get_position.return_value = MagicMock(
            pose=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        )
        controller.move_to_grasp_position.return_value = True
        controller.arm.get_tcp_pose.return_value = [10.0, 20.0, 30.0, 0.1, 0.2, 0.3]

        with patch("eit_agv.main.AGVController", return_value=controller):
            with patch("builtins.input", side_effect=["23", "n", "1", "y", "", "y", "0"]):
                with patch("sys.stdout", new=io.StringIO()):
                    agv_main.interactive()

        controller.move_to_grasp_position.assert_called_once_with("agv_tray_1", block=True)
        controller.prepare_loaded_tray_calibration.assert_not_called()
        controller.position_manager.save_tray_position.assert_called_once_with(
            "agv_tray_1",
            [10.0, 20.0, 30.0, 0.1, 0.2, 0.3],
        )

    def test_loaded_tray_calibration_cancel_save_still_cleans_up(self) -> None:
        """
        功能:
            验证 23 号入口选择带托盘且取消保存时, 仍会执行松爪和回零收尾动作.

        参数:
            无.

        返回:
            无.
        """
        controller = self._make_controller()
        controller.position_manager.get_category.return_value = {
            "synthesis_station_tray_1-1": {"description": "目标位"},
        }
        controller.position_manager.get_position.return_value = MagicMock(
            pose=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        )
        controller.prepare_loaded_tray_calibration.return_value = True
        controller.arm.get_tcp_pose.return_value = [10.0, 20.0, 30.0, 0.1, 0.2, 0.3]
        controller.get_calibrated_tray_pose_from_current_pose.return_value = [
            11.0,
            21.0,
            31.0,
            0.11,
            0.21,
            0.31,
        ]
        controller.complete_loaded_tray_calibration.return_value = True

        with patch("eit_agv.main.AGVController", return_value=controller):
            with patch("builtins.input", side_effect=["23", "y", "1", "y", "", "n", "0"]):
                with patch("sys.stdout", new=io.StringIO()):
                    agv_main.interactive()

        controller.save_calibrated_tray_position.assert_not_called()
        controller.complete_loaded_tray_calibration.assert_called_once_with(
            "synthesis_station_tray_1-1",
            block=True,
        )

    def test_loaded_tray_calibration_query_station_failure_skips_prepare(self) -> None:
        """
        功能:
            验证 23 号入口选择带托盘且当前工站未知时, 查询失败会直接退出.

        参数:
            无.

        返回:
            无.
        """
        controller = self._make_controller()
        controller.current_station = None
        controller.query_current_station.return_value = None
        output = io.StringIO()

        with patch("eit_agv.main.AGVController", return_value=controller):
            with patch("builtins.input", side_effect=["23", "y", "0"]):
                with patch("sys.stdout", new=output):
                    agv_main.interactive()

        controller.prepare_loaded_tray_calibration.assert_not_called()
        self.assertIn("查询当前工站失败", output.getvalue())

    def test_loaded_tray_calibration_without_station_targets_skips_prepare(self) -> None:
        """
        功能:
            验证 23 号入口选择带托盘且当前工站无非AGV目标点位时, 新流程会直接退出.

        参数:
            无.

        返回:
            无.
        """
        controller = self._make_controller()
        controller.position_manager.get_category.return_value = {
            "agv_tray_1": {"description": "AGV托盘位"},
        }
        output = io.StringIO()

        with patch("eit_agv.main.AGVController", return_value=controller):
            with patch("builtins.input", side_effect=["23", "y", "0"]):
                with patch("sys.stdout", new=output):
                    agv_main.interactive()

        controller.prepare_loaded_tray_calibration.assert_not_called()
        self.assertIn("当前工站没有可校准的目标点位", output.getvalue())

    def test_interactive_dispatches_middle_tray_auto_completion(self) -> None:
        """
        功能:
            验证 34 号入口会预览并调用工站中间托盘点位批量写入.

        参数:
            无.

        返回:
            无.
        """
        controller = self._make_controller()
        controller.position_manager.get_category.return_value = {
            "analysis_station_tray_1-1": {"description": "分析站端点"},
            "analysis_station_tray_1-2": {"description": "分析站端点"},
            "synthesis_station_tray_1-1": {"description": "左端点"},
            "synthesis_station_tray_1-4": {"description": "右端点"},
        }

        preview_result = [
            {
                "row_index": 1,
                "left_tray": "synthesis_station_tray_1-1",
                "right_tray": "synthesis_station_tray_1-4",
                "target_tray": "synthesis_station_tray_1-2",
                "target_col": 2,
                "ratio": 1 / 3,
                "exists": False,
                "old_pose": None,
                "new_pose": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            },
            {
                "row_index": 1,
                "left_tray": "synthesis_station_tray_1-1",
                "right_tray": "synthesis_station_tray_1-4",
                "target_tray": "synthesis_station_tray_1-3",
                "target_col": 3,
                "ratio": 2 / 3,
                "exists": True,
                "old_pose": [7.0, 8.0, 9.0, 1.0, 2.0, 3.0],
                "new_pose": [10.0, 11.0, 12.0, 4.0, 5.0, 6.0],
            },
        ]

        def _preview_side_effect(station_name: str):
            if station_name == "synthesis_station":
                return preview_result
            return []

        controller.preview_station_middle_tray_updates.side_effect = _preview_side_effect
        controller.apply_station_middle_tray_updates.return_value = {
            "station_name": "synthesis_station",
            "updated_count": 1,
            "created_count": 1,
            "skipped_rows": [],
            "affected_trays": [
                "synthesis_station_tray_1-2",
                "synthesis_station_tray_1-3",
            ],
        }

        with patch("eit_agv.main.AGVController", return_value=controller):
            with patch("builtins.input", side_effect=["34", "1", "y", "0"]):
                with patch("sys.stdout", new=io.StringIO()):
                    agv_main.interactive()

        controller.apply_station_middle_tray_updates.assert_called_once_with("synthesis_station")

    def test_middle_tray_auto_completion_cancel_does_not_apply(self) -> None:
        """
        功能:
            验证 34 号入口取消保存时不会写入配置文件.

        参数:
            无.

        返回:
            无.
        """
        controller = self._make_controller()
        controller.position_manager.get_category.return_value = {
            "synthesis_station_tray_1-1": {"description": "左端点"},
            "synthesis_station_tray_1-4": {"description": "右端点"},
        }
        controller.preview_station_middle_tray_updates.return_value = [
            {
                "row_index": 1,
                "left_tray": "synthesis_station_tray_1-1",
                "right_tray": "synthesis_station_tray_1-4",
                "target_tray": "synthesis_station_tray_1-2",
                "target_col": 2,
                "ratio": 1 / 3,
                "exists": False,
                "old_pose": None,
                "new_pose": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            },
        ]

        with patch("eit_agv.main.AGVController", return_value=controller):
            with patch("builtins.input", side_effect=["34", "1", "n", "0"]):
                with patch("sys.stdout", new=io.StringIO()):
                    agv_main.interactive()

        controller.apply_station_middle_tray_updates.assert_not_called()


if __name__ == "__main__":
    unittest.main()
