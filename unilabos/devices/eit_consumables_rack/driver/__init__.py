# coding: utf-8
"""
功能:
    电脑端驱动包.
    对外暴露 RackClient 与 Modbus 协议解析工具, 便于上层业务直接调用.
"""

from unilabos.devices.eit_consumables_rack.driver.modbus_rtu import (
    ModbusError,
    build_read_input_registers,
    crc16,
    parse_read_input_registers,
)
from unilabos.devices.eit_consumables_rack.driver.rack_client import (
    RackClient,
    RackClientError,
)

__all__ = [
    "ModbusError",
    "RackClient",
    "RackClientError",
    "build_read_input_registers",
    "crc16",
    "parse_read_input_registers",
]
