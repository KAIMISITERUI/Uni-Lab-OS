# coding: utf-8
"""
功能:
    Modbus RTU 纯算法工具, 无任何 IO 依赖.
    提供 CRC16 计算, 读 Input Registers 请求帧构造, 以及响应帧解析与校验.
    电脑端客户端与单元测试共用本模块. 固件端为降低依赖另有简化实现.
"""

import logging
from typing import List


logger = logging.getLogger(__name__)

_FUNC_READ_INPUT_REGISTERS = 0x04


class ModbusError(Exception):
    """
    功能:
        Modbus 协议层异常.
        帧长度不符, 功能码异常, CRC 校验失败等均抛出此异常.
    """


def crc16(data: bytes) -> int:
    """
    功能:
        按 Modbus RTU 规约计算 CRC-16.
        多项式 0xA001, 初值 0xFFFF, 字节低位先处理.

    参数:
        data: 参与 CRC 计算的字节序列.

    返回:
        int, 16 bit CRC 值. 序列化为帧时低字节在前, 高字节在后.
    """
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if (crc & 0x0001) != 0:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc = crc >> 1
    return crc & 0xFFFF


def build_read_input_registers(slave: int, start: int, count: int) -> bytes:
    """
    功能:
        构造功能码 0x04 "Read Input Registers" 的 Modbus RTU 请求帧.

    参数:
        slave: 从机地址, 1 ~ 247.
        start: 起始寄存器地址, 0 ~ 0xFFFF.
        count: 读取寄存器数量, 1 ~ 125.

    返回:
        bytes, 完整请求帧, 末尾两字节为 CRC 低位在前.
    """
    if slave < 1 or slave > 247:
        raise ValueError("slave 地址超出范围 1 ~ 247")
    if start < 0 or start > 0xFFFF:
        raise ValueError("start 超出范围 0 ~ 0xFFFF")
    if count < 1 or count > 125:
        raise ValueError("count 超出范围 1 ~ 125")

    payload = bytes(
        [
            slave & 0xFF,
            _FUNC_READ_INPUT_REGISTERS,
            (start >> 8) & 0xFF,
            start & 0xFF,
            (count >> 8) & 0xFF,
            count & 0xFF,
        ]
    )
    crc = crc16(payload)
    return payload + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def parse_read_input_registers(frame: bytes, slave: int, count: int) -> List[int]:
    """
    功能:
        解析功能码 0x04 响应帧并返回寄存器值列表.
        校验从机地址, 功能码, 字节数以及 CRC.

    参数:
        frame: 完整响应帧, 含 CRC.
        slave: 期望的从机地址, 用于校验.
        count: 期望寄存器数量, 决定数据段长度.

    返回:
        List[int], 长度为 count 的寄存器值列表, 每项为 0 ~ 0xFFFF.
    """
    expected_length = 3 + 2 * count + 2                      # addr + func + bc + data + crc
    if len(frame) != expected_length:
        raise ModbusError(
            f"帧长度不符, 期望 {expected_length} 字节, 实际 {len(frame)} 字节"
        )

    if frame[0] != (slave & 0xFF):
        raise ModbusError(f"从机地址不符, 期望 {slave:#04x}, 实际 {frame[0]:#04x}")

    func_code = frame[1]
    if (func_code & 0x80) != 0:
        exception_code = frame[2] if len(frame) > 2 else 0
        raise ModbusError(
            f"从机返回异常响应, 功能码 {func_code:#04x}, 异常码 {exception_code:#04x}"
        )
    if func_code != _FUNC_READ_INPUT_REGISTERS:
        raise ModbusError(f"功能码不符, 期望 0x04, 实际 {func_code:#04x}")

    byte_count = frame[2]
    if byte_count != 2 * count:
        raise ModbusError(
            f"字节数不符, 期望 {2 * count}, 实际 {byte_count}"
        )

    crc_expected = crc16(frame[:-2])
    crc_received = frame[-2] | (frame[-1] << 8)              # CRC low byte first
    if crc_received != crc_expected:
        raise ModbusError(
            f"CRC 校验失败, 期望 {crc_expected:#06x}, 实际 {crc_received:#06x}"
        )

    registers: List[int] = []
    for index in range(count):
        high = frame[3 + 2 * index]
        low = frame[3 + 2 * index + 1]
        registers.append((high << 8) | low)
    return registers


__all__ = [
    "ModbusError",
    "build_read_input_registers",
    "crc16",
    "parse_read_input_registers",
]
