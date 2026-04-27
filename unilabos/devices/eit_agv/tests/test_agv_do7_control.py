# coding: utf-8
"""
功能:
    覆盖 AGV 底盘 DO7 充电控制协议与状态解析逻辑.
参数:
    无.
返回:
    无, 通过 unittest 执行断言.
"""

import unittest
from unittest.mock import patch

from eit_agv.config.agv_config import (
    AGV_CHARGE_CONTROL_DO_ID,
    AGV_PORT_OTHER,
    REQ_CMD_ROBOT_OTHER_SET_DO,
    REQ_CMD_ROBOT_STATUS_IO,
    RSP_CMD_ROBOT_OTHER_SET_DO,
    RSP_CMD_ROBOT_STATUS_IO,
)
from eit_agv.driver.agv_driver import AGVDriver, AGVDriverConfig


_ARM_DRIVER_PATH = "eit_agv.controller.agv_controller.ArmDriver"
_POS_MGR_PATH = "eit_agv.controller.agv_controller.PositionManager"


def _make_driver() -> AGVDriver:
    """
    功能:
        创建不连接真实设备的 AGVDriver 实例.
    参数:
        无.
    返回:
        AGVDriver, 用于协议调用断言.
    """
    return AGVDriver(
        AGVDriverConfig(
            host="127.0.0.1",
            port=19204,
            port_navigation=19206,
            port_other=AGV_PORT_OTHER,
            timeout_s=0.1,
            debug_hex=False,
        )
    )


def _make_controller():
    """
    功能:
        创建 AGVController 实例, 并替换硬件相关依赖.
    参数:
        无.
    返回:
        AGVController, 用于 DO7 状态解析测试.
    """
    with patch(_ARM_DRIVER_PATH), patch(_POS_MGR_PATH):
        from eit_agv.controller.agv_controller import AGVController

        return AGVController()


class TestAgvDo7Control(unittest.TestCase):
    """
    功能:
        AGV DO7 充电控制单元测试.
    参数:
        无.
    返回:
        无.
    """

    def test_set_do7_uses_other_port_command_and_payload(self):
        """
        功能:
            验证设置 DO7 使用其他 API 端口, 命令号和 payload 正确.
        参数:
            无.
        返回:
            无.
        """
        driver = _make_driver()
        with patch.object(driver, "connect_other") as mock_connect_other, patch.object(
            driver,
            "_send_and_recv_json",
            return_value={"ret_code": 0},
        ) as mock_send:
            response = driver.set_digital_output(AGV_CHARGE_CONTROL_DO_ID, True)

        self.assertEqual(response, {"ret_code": 0})
        mock_connect_other.assert_called_once_with()
        mock_send.assert_called_once_with(
            cmd_id=REQ_CMD_ROBOT_OTHER_SET_DO,
            payload_obj={"id": AGV_CHARGE_CONTROL_DO_ID, "status": True},
            expect_cmd_id=RSP_CMD_ROBOT_OTHER_SET_DO,
            use_other_port=True,
        )

    def test_set_do7_failure_raises_clear_error(self):
        """
        功能:
            验证设置 DO7 返回非零 ret_code 时抛出明确失败信息.
        参数:
            无.
        返回:
            无.
        """
        driver = _make_driver()
        with patch.object(driver, "connect_other"), patch.object(
            driver,
            "_send_and_recv_json",
            return_value={"ret_code": 5, "err_msg": "端口拒绝"},
        ):
            with self.assertRaisesRegex(RuntimeError, "设置底盘 DO7 失败: 端口拒绝"):
                driver.set_digital_output(AGV_CHARGE_CONTROL_DO_ID, False)

    def test_query_io_status_uses_io_command(self):
        """
        功能:
            验证查询 I/O 使用 1013 请求与 11013 响应命令号.
        参数:
            无.
        返回:
            无.
        """
        driver = _make_driver()
        with patch.object(
            driver,
            "_send_and_recv_json",
            return_value={"DO": [{"id": AGV_CHARGE_CONTROL_DO_ID, "status": False}]},
        ) as mock_send:
            response = driver.query_io_status()

        self.assertEqual(response["DO"][0]["id"], AGV_CHARGE_CONTROL_DO_ID)
        mock_send.assert_called_once_with(
            cmd_id=REQ_CMD_ROBOT_STATUS_IO,
            payload_obj=None,
            expect_cmd_id=RSP_CMD_ROBOT_STATUS_IO,
        )

    def test_query_charge_control_status_parses_do7_false(self):
        """
        功能:
            验证控制器能从 DO 列表中解析 DO7 关闭状态为允许充电.
        参数:
            无.
        返回:
            无.
        """
        controller = _make_controller()
        with patch("eit_agv.controller.agv_controller.AGVDriver") as mock_driver_class:
            driver = mock_driver_class.return_value
            driver.query_io_status.return_value = {
                "DO": [
                    {"id": 1, "status": True},
                    {"id": AGV_CHARGE_CONTROL_DO_ID, "status": False, "source": "robot", "valid": True},
                ]
            }
            result = controller.query_charge_control_status()

        self.assertEqual(result["do_id"], AGV_CHARGE_CONTROL_DO_ID)
        self.assertIs(result["do_status"], False)
        self.assertIs(result["stop_charging"], False)
        self.assertIs(result["charging_enabled"], True)
        self.assertEqual(result["source"], "robot")
        self.assertIs(result["valid"], True)
        driver.connect.assert_called_once_with()
        driver.close.assert_called_once_with()

    def test_query_charge_control_status_unknown_without_do7(self):
        """
        功能:
            验证 I/O 响应缺少 DO7 时返回未知状态.
        参数:
            无.
        返回:
            无.
        """
        controller = _make_controller()
        with patch("eit_agv.controller.agv_controller.AGVDriver") as mock_driver_class:
            driver = mock_driver_class.return_value
            driver.query_io_status.return_value = {"DO": [{"id": 1, "status": True}]}
            result = controller.query_charge_control_status()

        self.assertIsNone(result["do_status"])
        self.assertIsNone(result["stop_charging"])
        self.assertIsNone(result["charging_enabled"])
        self.assertIn("未找到 DO7", result["message"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
