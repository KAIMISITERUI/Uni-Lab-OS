# coding: utf-8
"""
功能:
    覆盖 PositionManager 按模板创建托盘点位的保存逻辑.

参数:
    无.

返回:
    无, 通过 unittest 执行断言.
"""

import os
import tempfile
import unittest

import yaml

from eit_agv.utils.position_manager import PositionManager


class TestPositionManagerTemplateSave(unittest.TestCase):
    """
    功能:
        PositionManager 模板建点测试套件.

    参数:
        无.

    返回:
        无.
    """

    def setUp(self) -> None:
        """
        功能:
            为每个测试用例准备独立的临时配置文件.

        参数:
            无.

        返回:
            无.
        """
        file_descriptor, self.config_file = tempfile.mkstemp(
            dir=os.getcwd(),
            suffix=".yaml",
        )
        os.close(file_descriptor)
        config_content = """
tray_position:
  synthesis_station_tray_1-1:
    pose:
      - 1.0
      - 2.0
      - 3.0
      - 4.0
      - 5.0
      - 6.0
    descend_z: -15
    lift_z: 10
    drop_z: 2
    speed: 0.6
    acceleration: 0.3
    blend_radius: 5
    tool: "tool_a"
    wobj: "wobj_a"
    description: "左端模板"
"""
        with open(self.config_file, "w", encoding="utf-8") as file:
            file.write(config_content)

    def tearDown(self) -> None:
        """
        功能:
            清理测试过程中创建的临时目录.

        参数:
            无.

        返回:
            无.
        """
        if os.path.exists(self.config_file):
            os.remove(self.config_file)

    def test_save_tray_position_from_template_copies_non_pose_fields(self) -> None:
        """
        功能:
            验证按模板创建新托盘点位时会继承非pose字段并落盘到 YAML.

        参数:
            无.

        返回:
            无.
        """
        manager = PositionManager(config_file=self.config_file)

        manager.save_tray_position_from_template(
            tray_name="synthesis_station_tray_1-2",
            pose=[10.0, 20.0, 30.0, 0.1, 0.2, 0.3],
            template_tray_name="synthesis_station_tray_1-1",
        )

        saved_position = manager.get_position("tray_position", "synthesis_station_tray_1-2")
        self.assertIsNotNone(saved_position)
        self.assertEqual(saved_position.pose, [10.0, 20.0, 30.0, 0.1, 0.2, 0.3])
        self.assertEqual(saved_position.descend_z, -15)
        self.assertEqual(saved_position.lift_z, 10)
        self.assertEqual(saved_position.drop_z, 2)
        self.assertEqual(saved_position.speed, 0.6)
        self.assertEqual(saved_position.acceleration, 0.3)
        self.assertEqual(saved_position.blend_radius, 5)
        self.assertEqual(saved_position.tool, "tool_a")
        self.assertEqual(saved_position.wobj, "wobj_a")
        self.assertEqual(saved_position.description, "synthesis_station_tray_1-2抓取/放置位置")

        with open(self.config_file, "r", encoding="utf-8") as file:
            saved_config = yaml.safe_load(file)

        self.assertIn("synthesis_station_tray_1-2", saved_config["tray_position"])
        self.assertEqual(
            saved_config["tray_position"]["synthesis_station_tray_1-2"]["drop_z"],
            2,
        )


if __name__ == "__main__":
    unittest.main()
