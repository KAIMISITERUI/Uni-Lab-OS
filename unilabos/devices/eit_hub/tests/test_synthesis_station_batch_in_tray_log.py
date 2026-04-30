# -*- coding: utf-8 -*-
"""
功能:
    覆盖合成工站 batch_in_tray 标准 resource_list 日志汇总.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import MagicMock

from unilabos.devices.eit_synthesis_station.config.constants import (
    ResourceCode,
    TRAY_CODE_DISPLAY_NAME,
)
from unilabos.devices.eit_synthesis_station.controller.station_controller import (
    SynthesisStationController,
)


def _build_controller() -> SynthesisStationController:
    """
    功能:
        构造可直接调用 batch_in_tray 的控制器测试实例.
    参数:
        无.
    返回:
        SynthesisStationController, 测试控制器实例.
    """
    controller = SynthesisStationController.__new__(SynthesisStationController)
    controller._logger = MagicMock()
    controller._ui_logger = MagicMock()
    controller._data_manager = MagicMock()
    controller._client = MagicMock()
    controller.wait_idle = MagicMock()
    controller._call_with_relogin = MagicMock(return_value={"success": True})
    return controller


def test_batch_in_tray_log_reads_standard_resource_list_shape() -> None:
    """
    功能:
        验证日志从 resource_list 中读取托盘本体, 孔位物质和 initial_volume.
    参数:
        无.
    返回:
        None.
    """
    controller = _build_controller()
    tray_code = int(ResourceCode.REAGENT_BOTTLE_TRAY_8ML)
    media_code = str(int(ResourceCode.REAGENT_BOTTLE_8ML))
    resource_req_list: list[Dict[str, Any]] = [
        {
            "tray_layout_code": "TB-2-1",
            "remark": "",
            "resource_list": [
                {
                    "layout_code": "TB-2-1:-1",
                    "resource_type": str(tray_code),
                },
                {
                    "layout_code": "TB-2-1:0",
                    "resource_type": media_code,
                    "substance": "水杨醛",
                    "unit": "mL",
                    "initial_volume": 8,
                },
            ],
        }
    ]

    resp = controller.batch_in_tray(resource_req_list, task_id=99)

    assert resp == {"success": True}
    controller._data_manager.save_batch_in_tray_log.assert_called_once()
    log_data = controller._data_manager.save_batch_in_tray_log.call_args.args[0]
    assert len(log_data["resources"]) == 1
    resource = log_data["resources"][0]
    assert resource["layout_code"] == "TB-2-1"
    assert resource["count"] == 1
    assert resource["resource_type"] == tray_code
    assert resource["resource_type_name"] == TRAY_CODE_DISPLAY_NAME[tray_code]
    assert resource["substance_details"] == [
        {
            "slot": 0,
            "well": "A1",
            "substance": "水杨醛",
            "value": "8mL",
        }
    ]
