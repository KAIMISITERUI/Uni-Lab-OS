# coding: utf-8
"""
功能:
    Modbus RTU 纯算法单元测试.
    用用户提供的真实抓包报文校验 crc16 / build_read_input_registers /
    parse_read_input_registers 三个函数.
"""

import unittest

from unilabos.devices.eit_consumables_rack.driver.modbus_rtu import (
    ModbusError,
    build_read_input_registers,
    crc16,
    parse_read_input_registers,
)


# 用户提供的真实抓包, 十六进制转 bytes
_REQUEST_SLAVE1 = bytes.fromhex("01 04 00 00 00 06 70 08".replace(" ", ""))
_RESPONSE_EMPTY = bytes.fromhex(
    "01 04 0C 00 00 00 00 00 00 00 00 00 00 00 00 95 B7".replace(" ", "")
)
_RESPONSE_POS1 = bytes.fromhex(
    "01 04 0C 00 01 00 00 00 00 00 00 00 00 00 00 91 4B".replace(" ", "")
)


class CrcAndBuildTests(unittest.TestCase):
    """
    功能:
        校验 crc16 与 build_read_input_registers 能复现示例报文.
    """

    def test_crc16_matches_sample(self):
        """
        功能:
            对示例请求 payload 计算 CRC, 结果应等于报文末尾两字节(低位在前).

        参数:
            无.

        返回:
            无.
        """
        payload = _REQUEST_SLAVE1[:-2]
        crc = crc16(payload)
        low_byte = crc & 0xFF
        high_byte = (crc >> 8) & 0xFF
        self.assertEqual(low_byte, _REQUEST_SLAVE1[-2])
        self.assertEqual(high_byte, _REQUEST_SLAVE1[-1])

    def test_build_matches_sample(self):
        """
        功能:
            用业务参数构造请求, 结果应逐字节等于示例报文.

        参数:
            无.

        返回:
            无.
        """
        frame = build_read_input_registers(slave=1, start=0, count=6)
        self.assertEqual(frame, _REQUEST_SLAVE1)

    def test_build_rejects_invalid_slave(self):
        """
        功能:
            slave 地址越界应抛 ValueError.

        参数:
            无.

        返回:
            无.
        """
        with self.assertRaises(ValueError):
            build_read_input_registers(slave=0, start=0, count=6)
        with self.assertRaises(ValueError):
            build_read_input_registers(slave=248, start=0, count=6)


class ParseResponseTests(unittest.TestCase):
    """
    功能:
        校验 parse_read_input_registers 对真实响应帧的解析结果.
    """

    def test_parse_empty_rack(self):
        """
        功能:
            全空架响应应全部解析为 0.

        参数:
            无.

        返回:
            无.
        """
        registers = parse_read_input_registers(_RESPONSE_EMPTY, slave=1, count=6)
        self.assertEqual(registers, [0, 0, 0, 0, 0, 0])

    def test_parse_position1_occupied(self):
        """
        功能:
            1 号位有耗材时, 第一个寄存器应为 1, 其余为 0.

        参数:
            无.

        返回:
            无.
        """
        registers = parse_read_input_registers(_RESPONSE_POS1, slave=1, count=6)
        self.assertEqual(registers, [1, 0, 0, 0, 0, 0])

    def test_parse_rejects_wrong_slave(self):
        """
        功能:
            slave 期望值与帧首字节不一致时应抛 ModbusError.

        参数:
            无.

        返回:
            无.
        """
        with self.assertRaises(ModbusError):
            parse_read_input_registers(_RESPONSE_POS1, slave=2, count=6)

    def test_parse_rejects_bad_crc(self):
        """
        功能:
            篡改 CRC 字节应触发 CRC 校验失败.

        参数:
            无.

        返回:
            无.
        """
        corrupted = bytearray(_RESPONSE_EMPTY)
        corrupted[-1] ^= 0xFF
        with self.assertRaises(ModbusError):
            parse_read_input_registers(bytes(corrupted), slave=1, count=6)

    def test_parse_rejects_short_frame(self):
        """
        功能:
            帧长度不足应抛 ModbusError.

        参数:
            无.

        返回:
            无.
        """
        with self.assertRaises(ModbusError):
            parse_read_input_registers(_RESPONSE_EMPTY[:-2], slave=1, count=6)

    def test_parse_detects_exception_response(self):
        """
        功能:
            功能码高位置 1 的异常响应应抛 ModbusError.

        参数:
            无.

        返回:
            无.
        """
        head = bytes([0x01, 0x84, 0x02])                       # 异常响应: func | 0x80
        exception_frame = head + bytes([(crc16(head) & 0xFF), (crc16(head) >> 8) & 0xFF])
        with self.assertRaises(ModbusError):
            parse_read_input_registers(exception_frame, slave=1, count=6)


class CrossSlaveTests(unittest.TestCase):
    """
    功能:
        从机地址 2 ~ 5 的请求应能 build 并 self-round-trip parse.
    """

    def test_build_for_all_5_slaves(self):
        """
        功能:
            对每个从机地址构造请求再假造合法响应, parse 应 round-trip.

        参数:
            无.

        返回:
            无.
        """
        for slave in (1, 2, 3, 4, 5):
            frame = build_read_input_registers(slave=slave, start=0, count=6)
            self.assertEqual(frame[0], slave)
            self.assertEqual(frame[1], 0x04)
            # 伪造响应: 寄存器 index-th 置 1
            data = bytearray(12)
            data[2 * (slave - 1)] = 0x00
            data[2 * (slave - 1) + 1] = 0x01
            body = bytes([slave, 0x04, 0x0C]) + bytes(data)
            crc = crc16(body)
            response = body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])
            registers = parse_read_input_registers(response, slave=slave, count=6)
            expected = [0] * 6
            expected[slave - 1] = 1
            self.assertEqual(registers, expected)


if __name__ == "__main__":
    unittest.main()
