# coding: utf-8
"""
功能:
    覆盖工站中间托盘点位自动补齐相关的控制器核心逻辑.

参数:
    无.

返回:
    无, 通过 unittest 执行断言.
"""

import unittest
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
        AGVController, 用于中间托盘点位测试的控制器实例.
    """
    with patch(_ARM_DRIVER_PATH), patch(_POS_MGR_PATH), patch(_SHELF_MANAGER_PATH):
        from eit_agv.controller.agv_controller import AGVController

        return AGVController()


class TestMiddleTrayCompletion(unittest.TestCase):
    """
    功能:
        工站中间托盘点位自动补齐控制器测试套件.

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

    def test_preview_generates_middle_points_for_row_1_to_4(self) -> None:
        """
        功能:
            验证 1-1 到 1-4 会生成 1-2 与 1-3 的预览结果.

        参数:
            无.

        返回:
            无.
        """
        self.controller.position_manager.get_category.return_value = {
            "synthesis_station_tray_1-1": {"pose": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]},
            "synthesis_station_tray_1-2": {"pose": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0]},
            "synthesis_station_tray_1-3": {"pose": [2.0, 2.0, 2.0, 2.0, 2.0, 2.0]},
            "synthesis_station_tray_1-4": {"pose": [30.0, 60.0, 90.0, 0.3, 0.6, 0.9]},
            "bad_name": {"pose": [9.0, 9.0, 9.0, 9.0, 9.0, 9.0]},
        }

        preview_items = self.controller.preview_station_middle_tray_updates("synthesis_station")

        self.assertEqual(len(preview_items), 2)
        self.assertEqual(preview_items[0]["target_tray"], "synthesis_station_tray_1-2")
        self.assertEqual(preview_items[1]["target_tray"], "synthesis_station_tray_1-3")
        self.assertAlmostEqual(preview_items[0]["ratio"], 1 / 3)
        self.assertAlmostEqual(preview_items[1]["ratio"], 2 / 3)
        self.assertEqual(preview_items[0]["new_pose"][0:3], [10.0, 20.0, 30.0])
        self.assertEqual(preview_items[1]["new_pose"][0:3], [20.0, 40.0, 60.0])

    def test_preview_generates_all_missing_points_for_row_1_to_6(self) -> None:
        """
        功能:
            验证 1-1 到 1-6 会生成 1-2 到 1-5 的所有中间点位.

        参数:
            无.

        返回:
            无.
        """
        self.controller.position_manager.get_category.return_value = {
            "shelf_tray_1-1": {"pose": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]},
            "shelf_tray_1-6": {"pose": [60.0, 120.0, 180.0, 0.6, 1.2, 1.8]},
        }

        preview_items = self.controller.preview_station_middle_tray_updates("shelf")

        self.assertEqual(
            [item["target_tray"] for item in preview_items],
            [
                "shelf_tray_1-2",
                "shelf_tray_1-3",
                "shelf_tray_1-4",
                "shelf_tray_1-5",
            ],
        )
        self.assertEqual(preview_items[2]["new_pose"][0:3], [36.0, 72.0, 108.0])

    def test_preview_uses_shortest_angle_path_across_pi(self) -> None:
        """
        功能:
            验证姿态跨越 ±π 时会按最短路径进行插值.

        参数:
            无.

        返回:
            无.
        """
        self.controller.position_manager.get_category.return_value = {
            "shelf_tray_1-1": {"pose": [0.0, 0.0, 0.0, 3.0, 3.0, 3.0]},
            "shelf_tray_1-4": {"pose": [0.0, 0.0, 0.0, -3.0, -3.0, -3.0]},
        }

        preview_items = self.controller.preview_station_middle_tray_updates("shelf")

        self.assertEqual(len(preview_items), 2)
        self.assertGreater(preview_items[0]["new_pose"][3], 3.0)
        self.assertGreater(preview_items[0]["new_pose"][4], 3.0)
        self.assertGreater(preview_items[0]["new_pose"][5], 3.0)

    def test_apply_updates_existing_and_creates_missing_middle_points(self) -> None:
        """
        功能:
            验证批量写入时会区分更新已有点位与新增缺失点位.

        参数:
            无.

        返回:
            无.
        """
        self.controller.position_manager.get_category.return_value = {
            "synthesis_station_tray_1-1": {"pose": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]},
            "synthesis_station_tray_1-4": {"pose": [40.0, 40.0, 40.0, 0.4, 0.4, 0.4]},
            "synthesis_station_tray_1-6": {"pose": [60.0, 60.0, 60.0, 0.6, 0.6, 0.6]},
        }
        self.controller.position_manager.save_tray_position = MagicMock()
        self.controller.position_manager.save_tray_position_from_template = MagicMock()

        result = self.controller.apply_station_middle_tray_updates("synthesis_station")

        self.assertEqual(result["updated_count"], 1)
        self.assertEqual(result["created_count"], 3)
        self.assertEqual(
            result["affected_trays"],
            [
                "synthesis_station_tray_1-2",
                "synthesis_station_tray_1-3",
                "synthesis_station_tray_1-4",
                "synthesis_station_tray_1-5",
            ],
        )
        save_args = self.controller.position_manager.save_tray_position.call_args.args
        self.assertEqual(save_args[0], "synthesis_station_tray_1-4")
        expected_update_pose = [36.0, 36.0, 36.0, 0.36, 0.36, 0.36]
        for axis_value, expected_axis in zip(save_args[1], expected_update_pose):
            self.assertAlmostEqual(axis_value, expected_axis)
        template_calls = self.controller.position_manager.save_tray_position_from_template.call_args_list
        self.assertEqual(len(template_calls), 3)
        self.assertEqual(template_calls[0].args[0], "synthesis_station_tray_1-2")
        self.assertEqual(template_calls[1].args[0], "synthesis_station_tray_1-3")
        self.assertEqual(template_calls[2].args[0], "synthesis_station_tray_1-5")
        self.assertEqual(template_calls[0].args[2], "synthesis_station_tray_1-1")
        self.assertEqual(template_calls[1].args[2], "synthesis_station_tray_1-1")
        self.assertEqual(template_calls[2].args[2], "synthesis_station_tray_1-1")

        expected_pose_list = [
            [12.0, 12.0, 12.0, 0.12, 0.12, 0.12],
            [24.0, 24.0, 24.0, 0.24, 0.24, 0.24],
            [48.0, 48.0, 48.0, 0.48, 0.48, 0.48],
        ]
        for call_item, expected_pose in zip(template_calls, expected_pose_list):
            for axis_value, expected_axis in zip(call_item.args[1], expected_pose):
                self.assertAlmostEqual(axis_value, expected_axis)

    def test_apply_skips_invalid_and_consecutive_rows(self) -> None:
        """
        功能:
            验证连续编号排与端点位姿非法的排会被跳过.

        参数:
            无.

        返回:
            无.
        """
        self.controller.position_manager.get_category.return_value = {
            "shelf_tray_1-1": {"pose": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]},
            "shelf_tray_1-2": {"pose": [2.0, 2.0, 2.0, 0.2, 0.2, 0.2]},
            "shelf_tray_2-1": {"pose": [0.0, 0.0, 0.0, 0.0, 0.0]},
            "shelf_tray_2-4": {"pose": [4.0, 4.0, 4.0, 0.4, 0.4, 0.4]},
        }
        self.controller.position_manager.save_tray_position = MagicMock()
        self.controller.position_manager.save_tray_position_from_template = MagicMock()

        result = self.controller.apply_station_middle_tray_updates("shelf")

        self.assertEqual(result["updated_count"], 0)
        self.assertEqual(result["created_count"], 0)
        self.assertEqual(len(result["skipped_rows"]), 2)
        self.assertEqual(result["skipped_rows"][0]["reason"], "该排没有中间编号可计算")
        self.assertIn("左端点位姿无效", result["skipped_rows"][1]["reason"])
        self.controller.position_manager.save_tray_position.assert_not_called()
        self.controller.position_manager.save_tray_position_from_template.assert_not_called()

    def test_preview_single_row_only_returns_selected_row(self) -> None:
        """
        功能:
            验证按行预览只返回指定行的中间点位.

        参数:
            无.

        返回:
            无.
        """
        self.controller.position_manager.get_category.return_value = {
            "shelf_tray_1-1": {"pose": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]},
            "shelf_tray_1-4": {"pose": [4.0, 4.0, 4.0, 0.4, 0.4, 0.4]},
            "shelf_tray_2-1": {"pose": [10.0, 10.0, 10.0, 1.0, 1.0, 1.0]},
            "shelf_tray_2-3": {"pose": [30.0, 30.0, 30.0, 3.0, 3.0, 3.0]},
        }

        preview_items = self.controller.preview_middle_tray_row_updates("shelf", 2)

        self.assertEqual(len(preview_items), 1)
        self.assertEqual(preview_items[0]["target_tray"], "shelf_tray_2-2")
        self.assertEqual(preview_items[0]["row_index"], 2)

    def test_list_calibratable_rows_excludes_rows_without_middle_points(self) -> None:
        """
        功能:
            验证可校准行列表只包含存在中间编号可计算的行.

        参数:
            无.

        返回:
            无.
        """
        self.controller.position_manager.get_category.return_value = {
            "shelf_tray_1-1": {"pose": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]},
            "shelf_tray_1-4": {"pose": [4.0, 4.0, 4.0, 0.4, 0.4, 0.4]},
            "shelf_tray_2-1": {"pose": [10.0, 10.0, 10.0, 1.0, 1.0, 1.0]},
            "shelf_tray_2-2": {"pose": [20.0, 20.0, 20.0, 2.0, 2.0, 2.0]},
        }

        row_options = self.controller.list_middle_tray_calibratable_rows()

        self.assertEqual(len(row_options), 1)
        self.assertEqual(row_options[0]["station_name"], "shelf")
        self.assertEqual(row_options[0]["row_index"], 1)
        self.assertEqual(row_options[0]["target_count"], 2)

    def test_apply_single_row_only_writes_selected_row(self) -> None:
        """
        功能:
            验证按行应用只写入指定行的中间点位.

        参数:
            无.

        返回:
            无.
        """
        self.controller.position_manager.get_category.return_value = {
            "shelf_tray_1-1": {"pose": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]},
            "shelf_tray_1-4": {"pose": [4.0, 4.0, 4.0, 0.4, 0.4, 0.4]},
            "shelf_tray_2-1": {"pose": [10.0, 10.0, 10.0, 1.0, 1.0, 1.0]},
            "shelf_tray_2-3": {"pose": [30.0, 30.0, 30.0, 3.0, 3.0, 3.0]},
        }
        self.controller.position_manager.save_tray_position = MagicMock()
        self.controller.position_manager.save_tray_position_from_template = MagicMock()

        result = self.controller.apply_middle_tray_row_updates("shelf", 2)

        self.assertEqual(result["row_index"], 2)
        self.assertEqual(result["affected_trays"], ["shelf_tray_2-2"])
        self.controller.position_manager.save_tray_position.assert_not_called()
        template_call = self.controller.position_manager.save_tray_position_from_template.call_args
        self.assertEqual(template_call.args[0], "shelf_tray_2-2")
        self.assertEqual(template_call.args[2], "shelf_tray_2-1")


if __name__ == "__main__":
    unittest.main()
