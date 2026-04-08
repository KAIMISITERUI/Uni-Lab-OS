# coding: utf-8
"""
功能:
    覆盖 auto_charge_pp5_cp6_check 的核心回归场景, 验证PP5/CP6待命充电切换逻辑与详细故障诊断.
参数:
    无.
返回:
    无, 通过 unittest 执行断言.
"""

import unittest
from unittest.mock import patch


_ARM_DRIVER_PATH = "eit_agv.controller.agv_controller.ArmDriver"
_POS_MGR_PATH = "eit_agv.controller.agv_controller.PositionManager"


def _make_controller():
    """
    功能:
        创建 AGVController 实例, 并替换硬件相关依赖, 避免连接真实设备.
    参数:
        无.
    返回:
        AGVController, 可用于PP5/CP6自动充电逻辑测试的控制器实例.
    """
    with patch(_ARM_DRIVER_PATH), patch(_POS_MGR_PATH):
        from eit_agv.controller.agv_controller import AGVController

        return AGVController()


def _ok(data):
    """
    功能:
        构造统一成功响应.
    参数:
        data: 成功数据.
    返回:
        Dict, 详细 helper 成功返回.
    """
    return {
        "ok": True,
        "data": data,
        "failure": None,
    }


def _failure(
    error_category: str,
    error_stage: str,
    error_source: str,
    error_reason: str,
    message: str,
):
    """
    功能:
        构造统一失败响应.
    参数:
        error_category: 错误分类.
        error_stage: 错误阶段.
        error_source: 错误来源.
        error_reason: 错误原因.
        message: 错误消息.
    返回:
        Dict, 详细 helper 失败返回.
    """
    return {
        "ok": False,
        "data": None,
        "failure": {
            "error_category": error_category,
            "error_stage": error_stage,
            "error_source": error_source,
            "error_reason": error_reason,
            "message": message,
            "host": "192.168.1.5" if error_source != "arm_rpc" else "192.168.1.10",
            "port": 19204 if error_source == "agv_query_port" else 19206 if error_source == "agv_navigation_port" else 7003,
        },
    }


class TestAutoChargePp5Cp6CheckRegression(unittest.TestCase):
    """
    功能:
        PP5/CP6自动充电检查回归测试套件.
    参数:
        无.
    返回:
        无.
    """

    def setUp(self):
        """
        功能:
            为每个测试用例创建独立的控制器实例.
        参数:
            无.
        返回:
            无.
        """
        self.controller = _make_controller()

    def test_nav_busy_skips_check(self):
        """
        功能:
            验证导航忙碌时直接跳过PP5/CP6充电检查.
        参数:
            无.
        返回:
            无.
        """
        with patch.object(
            self.controller,
            "_query_nav_task_status_detailed",
            return_value=_ok({"task_status": 2, "task_status_name": "RUNNING"}),
        ), patch.object(
            self.controller,
            "_query_current_station_detailed",
        ) as mock_query_station, patch.object(
            self.controller,
            "_query_battery_status_detailed",
        ) as mock_query_battery:
            result = self.controller.auto_charge_pp5_cp6_check()

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["action"], "skipped_busy_nav")
        mock_query_station.assert_not_called()
        mock_query_battery.assert_not_called()

    def test_nav_status_query_failure_returns_skipped_with_diagnostics(self):
        """
        功能:
            验证导航状态查询失败时返回 skipped_nav_status_unavailable, 并携带详细诊断信息.
        参数:
            无.
        返回:
            无.
        """
        with patch.object(
            self.controller,
            "_query_nav_task_status_detailed",
            return_value=_failure(
                error_category="agv_query",
                error_stage="nav_guard",
                error_source="agv_query_port",
                error_reason="timeout",
                message="查询导航任务状态失败",
            ),
        ):
            result = self.controller.auto_charge_pp5_cp6_check()

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["action"], "skipped_nav_status_unavailable")
        self.assertEqual(result["error_category"], "agv_query")
        self.assertEqual(result["error_reason"], "timeout")
        self.assertEqual(result["error_stage"], "nav_guard")
        self.assertEqual(result["error_source"], "agv_query_port")
        self.assertIsNotNone(result["diagnostics"]["failure"])

    def test_station_query_failure_returns_error(self):
        """
        功能:
            验证站点查询失败时返回 query_location 错误.
        参数:
            无.
        返回:
            无.
        """
        with patch.object(
            self.controller,
            "_query_nav_task_status_detailed",
            return_value=_ok({"task_status": 0, "task_status_name": "NONE"}),
        ), patch.object(
            self.controller,
            "_query_current_station_detailed",
            return_value=_failure(
                error_category="agv_query",
                error_stage="query_current_station",
                error_source="agv_query_port",
                error_reason="connection_refused",
                message="查询当前位置失败",
            ),
        ):
            result = self.controller.auto_charge_pp5_cp6_check()

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["action"], "query_location")
        self.assertEqual(result["error_stage"], "query_current_station")

    def test_battery_query_failure_returns_error(self):
        """
        功能:
            验证电量查询失败时返回 query_battery 错误.
        参数:
            无.
        返回:
            无.
        """
        with patch.object(
            self.controller,
            "_query_nav_task_status_detailed",
            return_value=_ok({"task_status": 0, "task_status_name": "NONE"}),
        ), patch.object(
            self.controller,
            "_query_current_station_detailed",
            return_value=_ok({"station_id": "PP5", "station_name": "charging_transition_point"}),
        ), patch.object(
            self.controller,
            "_query_battery_status_detailed",
            return_value=_failure(
                error_category="agv_query",
                error_stage="query_battery_simple",
                error_source="agv_query_port",
                error_reason="timeout",
                message="查询电池电量失败",
            ),
        ):
            result = self.controller.auto_charge_pp5_cp6_check()

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["action"], "query_battery")
        self.assertEqual(result["current_station"], "PP5")

    def test_pp5_low_battery_moves_to_cp6(self):
        """
        功能:
            验证AGV在PP5且电量低于阈值时, 会移动到CP6充电.
        参数:
            无.
        返回:
            无.
        """
        with patch.object(
            self.controller,
            "_query_nav_task_status_detailed",
            return_value=_ok({"task_status": 0, "task_status_name": "NONE"}),
        ), patch.object(
            self.controller,
            "_query_current_station_detailed",
            return_value=_ok({"station_id": "PP5", "station_name": "charging_transition_point"}),
        ), patch.object(
            self.controller,
            "_query_battery_status_detailed",
            return_value=_ok({"battery_level": 0.45, "ret_code": 0}),
        ) as mock_query_battery, patch.object(
            self.controller,
            "_safe_navigate_to_station_detailed",
            return_value=_ok({"home_result": 0, "navigation_result": {"task_status": 4}}),
        ) as mock_safe_nav:
            result = self.controller.auto_charge_pp5_cp6_check()

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["action"], "pp5_to_cp6_for_charge")
        self.assertAlmostEqual(result["battery_level"], 0.45)
        mock_query_battery.assert_called_once_with(simple=True, error_stage="query_battery_simple")
        mock_safe_nav.assert_called_once_with(station_id="CP6", stage_prefix="pp5_to_cp6")

    def test_pp5_threshold_battery_stays_put(self):
        """
        功能:
            验证AGV在PP5且电量等于阈值时, 继续在PP5待命.
        参数:
            无.
        返回:
            无.
        """
        with patch.object(
            self.controller,
            "_query_nav_task_status_detailed",
            return_value=_ok({"task_status": 0, "task_status_name": "NONE"}),
        ), patch.object(
            self.controller,
            "_query_current_station_detailed",
            return_value=_ok({"station_id": "PP5", "station_name": "charging_transition_point"}),
        ), patch.object(
            self.controller,
            "_query_battery_status_detailed",
            return_value=_ok({"battery_level": 0.5, "ret_code": 0}),
        ), patch.object(
            self.controller,
            "_safe_navigate_to_station_detailed",
        ) as mock_safe_nav:
            result = self.controller.auto_charge_pp5_cp6_check(low_battery_pct=50)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["action"], "standby_at_pp5")
        mock_safe_nav.assert_not_called()

    def test_cp6_high_battery_moves_to_pp5(self):
        """
        功能:
            验证AGV在CP6且电量高于90%时, 会返回PP5待命.
        参数:
            无.
        返回:
            无.
        """
        with patch.object(
            self.controller,
            "_query_nav_task_status_detailed",
            return_value=_ok({"task_status": 0, "task_status_name": "NONE"}),
        ), patch.object(
            self.controller,
            "_query_current_station_detailed",
            return_value=_ok({"station_id": "CP6", "station_name": "charging_station"}),
        ), patch.object(
            self.controller,
            "_query_battery_status_detailed",
            return_value=_ok({"battery_level": 0.91, "ret_code": 0}),
        ), patch.object(
            self.controller,
            "_safe_navigate_to_station_detailed",
            return_value=_ok({"home_result": 0, "navigation_result": {"task_status": 4}}),
        ) as mock_safe_nav:
            result = self.controller.auto_charge_pp5_cp6_check()

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["action"], "cp6_to_pp5_after_charge")
        mock_safe_nav.assert_called_once_with(station_id="PP5", stage_prefix="cp6_to_pp5")

    def test_cp6_threshold_battery_stays_put(self):
        """
        功能:
            验证AGV在CP6且电量等于90%时, 继续在CP6待命.
        参数:
            无.
        返回:
            无.
        """
        with patch.object(
            self.controller,
            "_query_nav_task_status_detailed",
            return_value=_ok({"task_status": 0, "task_status_name": "NONE"}),
        ), patch.object(
            self.controller,
            "_query_current_station_detailed",
            return_value=_ok({"station_id": "CP6", "station_name": "charging_station"}),
        ), patch.object(
            self.controller,
            "_query_battery_status_detailed",
            return_value=_ok({"battery_level": 0.9, "ret_code": 0}),
        ):
            result = self.controller.auto_charge_pp5_cp6_check()

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["action"], "standby_at_cp6")

    def test_non_pp5_cp6_station_skips_check(self):
        """
        功能:
            验证AGV不在PP5或CP6时, 视为工作途中并跳过检查.
        参数:
            无.
        返回:
            无.
        """
        with patch.object(
            self.controller,
            "_query_nav_task_status_detailed",
            return_value=_ok({"task_status": 0, "task_status_name": "NONE"}),
        ), patch.object(
            self.controller,
            "_query_current_station_detailed",
            return_value=_ok({"station_id": "LM1", "station_name": "synthesis_station"}),
        ), patch.object(
            self.controller,
            "_query_battery_status_detailed",
            return_value=_ok({"battery_level": 0.7, "ret_code": 0}),
        ):
            result = self.controller.auto_charge_pp5_cp6_check()

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["action"], "working_in_progress")
        self.assertEqual(result["current_station"], "LM1")

    def test_pp5_low_battery_move_to_cp6_failure_is_arm_connection(self):
        """
        功能:
            验证AGV在PP5且低电量时, 如果机械臂连接失败导致进站失败, 会返回 arm_connection 诊断.
        参数:
            无.
        返回:
            无.
        """
        with patch.object(
            self.controller,
            "_query_nav_task_status_detailed",
            return_value=_ok({"task_status": 0, "task_status_name": "NONE"}),
        ), patch.object(
            self.controller,
            "_query_current_station_detailed",
            return_value=_ok({"station_id": "PP5", "station_name": "charging_transition_point"}),
        ), patch.object(
            self.controller,
            "_query_battery_status_detailed",
            return_value=_ok({"battery_level": 0.2, "ret_code": 0}),
        ), patch.object(
            self.controller,
            "_safe_navigate_to_station_detailed",
            return_value=_failure(
                error_category="arm_connection",
                error_stage="pp5_to_cp6.arm_home",
                error_source="arm_rpc",
                error_reason="timeout",
                message="机械臂连接失败, 无法执行回零动作",
            ),
        ):
            result = self.controller.auto_charge_pp5_cp6_check()

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["action"], "move_to_cp6")
        self.assertEqual(result["error_category"], "arm_connection")
        self.assertEqual(result["error_stage"], "pp5_to_cp6.arm_home")

    def test_cp6_high_battery_move_to_pp5_failure_is_agv_navigation(self):
        """
        功能:
            验证AGV在CP6且高电量时, 如果导航失败导致返回PP5失败, 会返回 agv_navigation 诊断.
        参数:
            无.
        返回:
            无.
        """
        with patch.object(
            self.controller,
            "_query_nav_task_status_detailed",
            return_value=_ok({"task_status": 0, "task_status_name": "NONE"}),
        ), patch.object(
            self.controller,
            "_query_current_station_detailed",
            return_value=_ok({"station_id": "CP6", "station_name": "charging_station"}),
        ), patch.object(
            self.controller,
            "_query_battery_status_detailed",
            return_value=_ok({"battery_level": 0.95, "ret_code": 0}),
        ), patch.object(
            self.controller,
            "_safe_navigate_to_station_detailed",
            return_value=_failure(
                error_category="agv_navigation",
                error_stage="cp6_to_pp5.navigate",
                error_source="agv_navigation_port",
                error_reason="connection_refused",
                message="AGV导航到PP5失败",
            ),
        ):
            result = self.controller.auto_charge_pp5_cp6_check()

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["action"], "move_to_pp5")
        self.assertEqual(result["error_category"], "agv_navigation")
        self.assertEqual(result["error_stage"], "cp6_to_pp5.navigate")

    def test_cp6_redock_return_to_cp6_failure_has_precise_stage(self):
        """
        功能:
            验证CP6重对接循环中, 返回CP6阶段失败时会带上 cp6_redock.return_to_cp6 精确阶段信息.
        参数:
            无.
        返回:
            无.
        """
        with patch.object(
            self.controller,
            "_query_nav_task_status_detailed",
            side_effect=[
                _ok({"task_status": 0, "task_status_name": "NONE"}),
                _ok({"task_status": 0, "task_status_name": "NONE"}),
            ],
        ), patch.object(
            self.controller,
            "_query_current_station_detailed",
            return_value=_ok({"station_id": "CP6", "station_name": "charging_station"}),
        ), patch.object(
            self.controller,
            "_query_battery_status_detailed",
            side_effect=[
                _ok({"battery_level": 0.45, "ret_code": 0}),
                _ok({"battery_level": 0.45, "charging": False, "ret_code": 0}),
            ],
        ), patch.object(
            self.controller,
            "_safe_navigate_to_station_detailed",
            side_effect=[
                _ok({"home_result": 0, "navigation_result": {"task_status": 4}}),
                _failure(
                    error_category="agv_navigation",
                    error_stage="cp6_redock.return_to_cp6.navigate",
                    error_source="agv_navigation_port",
                    error_reason="connection_reset",
                    message="AGV导航到CP6失败",
                ),
            ],
        ):
            result = self.controller.auto_charge_pp5_cp6_check()

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["action"], "charge_cycle_return_to_cp6")
        self.assertEqual(result["error_stage"], "cp6_redock.return_to_cp6.navigate")

    def test_exception_keeps_step_trace(self):
        """
        功能:
            验证发生顶层异常时, diagnostics.step_trace 仍保留已执行步骤.
        参数:
            无.
        返回:
            无.
        """
        with patch.object(
            self.controller,
            "_query_nav_task_status_detailed",
            return_value=_ok({"task_status": 0, "task_status_name": "NONE"}),
        ), patch.object(
            self.controller,
            "_query_current_station_detailed",
            side_effect=RuntimeError("boom"),
        ):
            result = self.controller.auto_charge_pp5_cp6_check()

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["action"], "exception")
        step_trace = result["diagnostics"]["step_trace"]
        self.assertTrue(any(item["stage"] == "nav_guard" for item in step_trace))
        self.assertTrue(any(item["stage"] == "exception" for item in step_trace))


if __name__ == "__main__":
    unittest.main(verbosity=2)
