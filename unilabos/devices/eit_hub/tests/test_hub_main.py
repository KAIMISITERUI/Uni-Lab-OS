"""
功能:
    覆盖 EIT Hub 顶层 CLI 入口的菜单分发行为.
参数:
    无.
返回:
    无.
"""

import io
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from eit_hub import main as hub_main


class TestHubMain(unittest.TestCase):
    """
    功能:
        验证 hub 顶层菜单可正确进入三个工站的交互入口.
    参数:
        无.
    返回:
        无.
    """

    def test_interactive_dispatches_all_station_menus(self) -> None:
        """
        功能:
            验证合成站, 分析站和 AGV 菜单都能被依次调起并返回顶层.
        参数:
            无.
        返回:
            无.
        """
        with patch("eit_hub.main._run_station_menu") as run_station_menu:
            with patch("builtins.input", side_effect=["1", "2", "3", "0"]):
                with patch("sys.stdout", new=io.StringIO()):
                    hub_main.interactive()

        self.assertEqual(run_station_menu.call_count, 3)
        self.assertEqual(
            run_station_menu.call_args_list,
            [
                unittest.mock.call("eit_synthesis_station.main", "合成工站"),
                unittest.mock.call("eit_analysis_station.main", "分析工站"),
                unittest.mock.call("eit_agv.main", "AGV 工站"),
            ],
        )

    def test_run_station_menu_calls_imported_interactive(self) -> None:
        """
        功能:
            验证延迟加载工站模块后会调用其中的 interactive 入口.
        参数:
            无.
        返回:
            无.
        """
        station_entry = MagicMock()
        station_module = SimpleNamespace(interactive=station_entry)

        with patch("eit_hub.main.importlib.import_module", return_value=station_module) as import_module:
            hub_main._run_station_menu("eit_agv.main", "AGV 工站")

        import_module.assert_called_once_with("eit_agv.main")
        station_entry.assert_called_once_with()

    def test_interactive_handles_invalid_choice_and_exit(self) -> None:
        """
        功能:
            验证 hub 顶层菜单在无效输入后仍可正常退出.
        参数:
            无.
        返回:
            无.
        """
        output = io.StringIO()

        with patch("builtins.input", side_effect=["9", "0"]):
            with patch("sys.stdout", new=output):
                hub_main.interactive()

        self.assertIn("无效选择", output.getvalue())


if __name__ == "__main__":
    unittest.main()
