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


if __name__ == "__main__":
    unittest.main()
