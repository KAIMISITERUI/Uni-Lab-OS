# coding: utf-8
"""
功能:
    测试 batch_transfer_cycle_test 在循环测试中回到充电站后的等待逻辑。

参数:
    无

返回:
    无
"""

import unittest
from unittest.mock import MagicMock, call, patch


_ARM_DRIVER_PATH = "eit_agv.controller.agv_controller.ArmDriver"
_POS_MGR_PATH = "eit_agv.controller.agv_controller.PositionManager"
_SHELF_MANAGER_PATH = "eit_agv.controller.agv_controller.ShelfManager"
_SLEEP_PATH = "eit_agv.controller.agv_controller.time.sleep"


def _make_controller():
    """
    功能:
        创建屏蔽底层硬件依赖的 AGVController 测试实例。

    参数:
        无

    返回:
        AGVController, 可用于循环测试逻辑验证的控制器实例。
    """
    with patch(_ARM_DRIVER_PATH), patch(_POS_MGR_PATH), patch(_SHELF_MANAGER_PATH):
        from eit_agv.controller.agv_controller import AGVController

        return AGVController()


class TestBatchTransferCycleTest(unittest.TestCase):
    """
    功能:
        验证批量物料循环测试在回到充电站后的等待行为。

    参数:
        无

    返回:
        无
    """

    def setUp(self):
        """
        功能:
            初始化循环测试所需的控制器和模拟任务数据。

        参数:
            无

        返回:
            无
        """
        self.controller = _make_controller()
        self.controller.batch_transfer_materials = MagicMock(return_value=True)
        self.controller.go_to_charging_station = MagicMock(return_value={"ret_code": 0})
        self.transfer_tasks = [
            {
                "source_tray": "shelf_tray_1",
                "target_tray": "agv_tray_1",
                "material_type": "FLASH_FILTER_OUTER_BOTTLE_TRAY",
            }
        ]
        self.reverse_tasks = [
            {
                "source_tray": "agv_tray_1",
                "target_tray": "shelf_tray_1",
                "material_type": "FLASH_FILTER_OUTER_BOTTLE_TRAY",
            }
        ]

    @patch(_SLEEP_PATH, return_value=None)
    def test_waits_10_seconds_before_reverse_transfer(self, mock_sleep):
        """
        功能:
            验证单轮循环在第一次回到充电站后会等待 10 秒, 最终停回充电站时不会额外等待。

        参数:
            mock_sleep: time.sleep 的补丁对象。

        返回:
            无
        """
        result = self.controller.batch_transfer_cycle_test(
            self.transfer_tasks,
            cycle_count=1,
            block=True,
        )

        self.assertIs(result["success"], True)
        self.assertEqual(result["completed_cycles"], 1)
        self.assertEqual(result["total_cycles"], 1)
        self.assertIs(result["failed_at"], None)
        self.controller.batch_transfer_materials.assert_has_calls(
            [
                call(self.transfer_tasks, block=True),
                call(self.reverse_tasks, block=True),
            ]
        )
        self.assertEqual(self.controller.go_to_charging_station.call_count, 2)
        self.assertEqual(mock_sleep.call_args_list, [call(10)])

    @patch(_SLEEP_PATH, return_value=None)
    def test_waits_before_next_cycle_and_skips_extra_wait_after_last_cycle(self, mock_sleep):
        """
        功能:
            验证多轮循环时, 每次再次离开充电站前都会等待 10 秒, 最后一轮结束后不再多等一次。

        参数:
            mock_sleep: time.sleep 的补丁对象。

        返回:
            无
        """
        result = self.controller.batch_transfer_cycle_test(
            self.transfer_tasks,
            cycle_count=2,
            block=True,
        )

        self.assertIs(result["success"], True)
        self.assertEqual(result["completed_cycles"], 2)
        self.assertEqual(result["total_cycles"], 2)
        self.assertIs(result["failed_at"], None)
        self.assertEqual(self.controller.batch_transfer_materials.call_count, 4)
        self.assertEqual(self.controller.go_to_charging_station.call_count, 4)
        self.assertEqual(mock_sleep.call_args_list, [call(10), call(10), call(10)])


if __name__ == "__main__":
    unittest.main()
