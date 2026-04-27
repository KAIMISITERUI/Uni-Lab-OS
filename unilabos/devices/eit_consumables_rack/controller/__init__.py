# coding: utf-8
"""
功能:
    耗材货架 controller 层包入口.
    暴露资源管理控制器与盘位数据类型, 协议层 RackClient 在 driver 子包.
"""

from unilabos.devices.eit_consumables_rack.controller.rack_controller import (
    RackController,
    SlotResource,
    SlotStatus,
    load_resource_config,
)


__all__ = [
    "RackController",
    "SlotResource",
    "SlotStatus",
    "load_resource_config",
]
