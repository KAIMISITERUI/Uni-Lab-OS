# coding: utf-8
"""
功能:
    HaaS506-ED1 (标准 MicroPython on ESP32) 端 Modbus RTU 查询实现.
    仅依赖 machine.UART 与 time, 不依赖阿里 HaaS Python 轻应用.
    与电脑端 driver.modbus_rtu 算法等价, 独立成文件便于直接拷贝到设备根目录.
"""

import time


_FUNC_READ_INPUT_REGISTERS = 0x04


def crc16(data):
    """
    功能:
        Modbus RTU CRC-16, 多项式 0xA001, 初值 0xFFFF, 字节低位先.

    参数:
        data: bytes / bytearray.

    返回:
        int, 16 bit CRC.
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


def _build_request(slave, start, count):
    """
    功能:
        构造功能码 0x04 的请求帧.

    参数:
        slave: 从机地址.
        start: 起始寄存器地址.
        count: 寄存器数量.

    返回:
        bytes, 含 CRC 的完整请求帧.
    """
    payload = bytes(
        (
            slave & 0xFF,
            _FUNC_READ_INPUT_REGISTERS,
            (start >> 8) & 0xFF,
            start & 0xFF,
            (count >> 8) & 0xFF,
            count & 0xFF,
        )
    )
    crc = crc16(payload)
    return payload + bytes((crc & 0xFF, (crc >> 8) & 0xFF))


def _flush_rx(uart):
    """
    功能:
        清空 UART 接收缓冲中的残留字节, 防止粘包.

    参数:
        uart: machine.UART 实例.

    返回:
        无.
    """
    while uart.any() > 0:
        uart.read(uart.any())


def _read_exact(uart, size, timeout_ms):
    """
    功能:
        阻塞读取 size 字节, 超时未读满抛 OSError.
        标准 MicroPython UART.read 非阻塞, 轮询 uart.any() 累积.

    参数:
        uart: machine.UART 实例.
        size: 期望字节数.
        timeout_ms: 整体超时.

    返回:
        bytes, 长度为 size.
    """
    buffer = bytearray()
    deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
    while len(buffer) < size:
        available = uart.any()
        if available > 0:
            chunk = uart.read(min(available, size - len(buffer)))
            if chunk is not None:
                buffer.extend(chunk)
                continue
        if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
            raise OSError("RS485 读取超时")
        time.sleep_ms(2)
    return bytes(buffer)


def query_slave(uart, slave, start, count, timeout_ms):
    """
    功能:
        向单个 Modbus RTU 从机发送读 Input Registers 请求并解析响应.
        任一环节失败返回 None, 错误原因通过 print 输出到串口.

    参数:
        uart: machine.UART 实例.
        slave: 从机地址, 1 ~ 247.
        start: 起始寄存器地址.
        count: 寄存器数量.
        timeout_ms: 整体超时.

    返回:
        list[int] | None. 成功时返回寄存器数值列表, 失败返回 None.
    """
    try:
        _flush_rx(uart)
        request = _build_request(slave, start, count)
        uart.write(request)

        expected_length = 3 + 2 * count + 2
        frame = _read_exact(uart, expected_length, timeout_ms)
    except OSError as exc:
        print("从机 %s 通信失败: %s" % (slave, exc))
        return None

    if frame[0] != (slave & 0xFF):
        print("从机 %s 地址不符, 实际 0x%02X" % (slave, frame[0]))
        return None

    func_code = frame[1]
    if (func_code & 0x80) != 0:
        print(
            "从机 %s 返回异常响应, 功能码 0x%02X, 异常码 0x%02X"
            % (slave, func_code, frame[2] if len(frame) > 2 else 0)
        )
        return None
    if func_code != _FUNC_READ_INPUT_REGISTERS:
        print("从机 %s 功能码不符, 实际 0x%02X" % (slave, func_code))
        return None

    byte_count = frame[2]
    if byte_count != 2 * count:
        print("从机 %s 字节数不符, 实际 %s" % (slave, byte_count))
        return None

    crc_expected = crc16(frame[:-2])
    crc_received = frame[-2] | (frame[-1] << 8)
    if crc_received != crc_expected:
        print(
            "从机 %s CRC 校验失败, 期望 0x%04X 实际 0x%04X"
            % (slave, crc_expected, crc_received)
        )
        return None

    registers = []
    for index in range(count):
        high = frame[3 + 2 * index]
        low = frame[3 + 2 * index + 1]
        registers.append((high << 8) | low)
    return registers
