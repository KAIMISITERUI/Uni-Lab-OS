# coding: utf-8
"""
功能:
    HaaS506-ED1 (标准 MicroPython on ESP32) 固件入口.
    拷贝到设备根目录 /main.py 上电自动执行.
    1. 连接 WiFi, 设置静态 IP, 打印局域网地址.
    2. 初始化 RS485 UART (UART2, TX=GPIO18, RX=GPIO17).
    3. 起 TCP Server 监听 TCP_LISTEN_PORT, 单连接循环接收 JSON 命令.
    4. 按命令查询 Modbus 并回写 JSON 响应, 每条命令用 '\\n' 分帧.
"""

import network
import socket
import time
import ujson
from machine import Pin, UART

import board_config as cfg
import rs485_modbus


_GLYPH_NEWLINE = b"\n"


def _connect_wifi():
    """
    功能:
        连接 WiFi 直至拿到 IP 或超时. 超时抛出 OSError.
        连接成功后强制覆盖为静态 IP.

    参数:
        无.

    返回:
        network.WLAN 实例, 已连接.
    """
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected() is False:
        print("连接 WiFi SSID=%s" % cfg.WIFI_SSID)
        wlan.connect(cfg.WIFI_SSID, cfg.WIFI_PASSWORD)
        deadline = time.ticks_add(time.ticks_ms(), cfg.WIFI_CONNECT_TIMEOUT_S * 1000)
        while wlan.isconnected() is False:
            if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                raise OSError("WiFi 连接超时")
            time.sleep_ms(200)
    wlan.ifconfig(cfg.WIFI_STATIC_IPCONFIG)              # 覆盖 DHCP, 锁定静态 IP
    print("WiFi 已连接 IP=%s" % wlan.ifconfig()[0])
    return wlan


def _ensure_wifi(wlan):
    """
    功能:
        若 WiFi 掉线则重连, 并重新应用静态 IP.

    参数:
        wlan: network.WLAN 实例.

    返回:
        无.
    """
    if wlan.isconnected() is True:
        return
    print("WiFi 掉线, 重连中")
    try:
        wlan.connect(cfg.WIFI_SSID, cfg.WIFI_PASSWORD)
        time.sleep(cfg.WIFI_RETRY_INTERVAL_S)
        if wlan.isconnected() is True:
            wlan.ifconfig(cfg.WIFI_STATIC_IPCONFIG)
            print("WiFi 已重连 IP=%s" % wlan.ifconfig()[0])
    except Exception as exc:
        print("WiFi 重连异常: %s" % exc)


def _open_uart():
    """
    功能:
        打开 RS485 UART (UART2, TX=18, RX=17).

    参数:
        无.

    返回:
        machine.UART 实例.
    """
    uart = UART(
        cfg.UART_ID,
        baudrate=cfg.UART_BAUDRATE,
        tx=cfg.UART_TX_PIN,
        rx=cfg.UART_RX_PIN,
    )
    print(
        "RS485 UART 已打开 id=%d tx=%d rx=%d baud=%d"
        % (cfg.UART_ID, cfg.UART_TX_PIN, cfg.UART_RX_PIN, cfg.UART_BAUDRATE)
    )
    return uart


def _query_layer(uart, layer):
    """
    功能:
        查询指定层, 返回 0/1 列表或 None.

    参数:
        uart: machine.UART 实例.
        layer: 层号, 1 基.

    返回:
        list[int] | None.
    """
    index = layer - 1
    if index < 0 or index >= len(cfg.SLAVE_ADDRS):
        return None
    slave = cfg.SLAVE_ADDRS[index]
    registers = rs485_modbus.query_slave(
        uart, slave, cfg.REG_START, cfg.REG_COUNT, cfg.PER_SLAVE_TIMEOUT_MS
    )
    if registers is None:
        return None
    return [1 if value != 0 else 0 for value in registers]


def _handle_query_all(uart, request_id):
    """
    功能:
        依次查询全部从机, 任一层失败对应字段置 null, 不中断整体查询.

    参数:
        uart: machine.UART 实例.
        request_id: 请求 id, 透传到响应.

    返回:
        dict, 响应对象.
    """
    layers = {}
    any_failed = False
    for layer in range(1, len(cfg.SLAVE_ADDRS) + 1):
        positions = _query_layer(uart, layer)
        if positions is None:
            any_failed = True
        layers[str(layer)] = positions
        time.sleep_ms(cfg.INTER_FRAME_GAP_MS)                # RTU 帧间隔
    response = {
        "ok": True,
        "cmd": "query_all",
        "id": request_id,
        "ts_ms": time.ticks_ms(),
        "layers": layers,
    }
    if any_failed is True:
        response["partial"] = True
    return response


def _handle_query_layer(uart, request_id, layer):
    """
    功能:
        查询单层.

    参数:
        uart: machine.UART 实例.
        request_id: 请求 id.
        layer: 层号.

    返回:
        dict, 响应对象.
    """
    if isinstance(layer, int) is False:
        return {
            "ok": False,
            "cmd": "query_layer",
            "id": request_id,
            "error": "layer 字段必须是整数",
        }
    if layer < 1 or layer > len(cfg.SLAVE_ADDRS):
        return {
            "ok": False,
            "cmd": "query_layer",
            "id": request_id,
            "error": "layer 超出范围",
        }
    positions = _query_layer(uart, layer)
    if positions is None:
        return {
            "ok": False,
            "cmd": "query_layer",
            "id": request_id,
            "error": "slave %d timeout" % cfg.SLAVE_ADDRS[layer - 1],
        }
    return {
        "ok": True,
        "cmd": "query_layer",
        "id": request_id,
        "ts_ms": time.ticks_ms(),
        "layer": layer,
        "positions": positions,
    }


def _dispatch(uart, request):
    """
    功能:
        根据 cmd 字段分发到具体处理函数.

    参数:
        uart: machine.UART 实例.
        request: 解析后的 dict.

    返回:
        dict, 响应对象.
    """
    cmd = request.get("cmd")
    request_id = request.get("id")
    if cmd == "ping":
        return {"ok": True, "cmd": "ping", "id": request_id, "ts_ms": time.ticks_ms()}
    if cmd == "query_all":
        return _handle_query_all(uart, request_id)
    if cmd == "query_layer":
        return _handle_query_layer(uart, request_id, request.get("layer"))
    return {
        "ok": False,
        "cmd": cmd,
        "id": request_id,
        "error": "unknown cmd",
    }


def _serve_client(conn, uart, led_run):
    """
    功能:
        处理单个 TCP 客户端的请求循环, 按 '\\n' 分帧读命令.

    参数:
        conn: 已接受的客户端 socket.
        uart: machine.UART 实例.
        led_run: 运行指示 LED Pin, 每处理一条命令翻转一次.

    返回:
        无.
    """
    buffer = bytearray()
    while True:
        try:
            chunk = conn.recv(cfg.TCP_RECV_CHUNK)
        except OSError as exc:
            print("客户端读取异常, 断开: %s" % exc)
            return
        if chunk is None or len(chunk) == 0:
            print("客户端已关闭")
            return
        buffer.extend(chunk)

        while True:
            nl_index = buffer.find(_GLYPH_NEWLINE)
            if nl_index < 0:
                break
            line = bytes(buffer[:nl_index])
            buffer = bytearray(buffer[nl_index + 1:])        # MicroPython bytearray 不支持 del, 重建后重绑
            if len(line) == 0:
                continue
            try:
                request = ujson.loads(line)
            except Exception as exc:
                print("JSON 解析失败: %s" % exc)
                response = {"ok": False, "error": "bad_json"}
            else:
                if isinstance(request, dict) is False:
                    response = {"ok": False, "error": "bad_json"}
                else:
                    response = _dispatch(uart, request)
            led_run.value(led_run.value() ^ 1)               # 心跳闪烁
            try:
                conn.sendall((ujson.dumps(response) + "\n").encode("utf-8"))
            except OSError as exc:
                print("响应发送失败, 断开: %s" % exc)
                return


def _run_server(wlan, uart, led_wifi, led_run):
    """
    功能:
        建立 TCP Server 并持续接受客户端.
        客户端断开后回到 accept, 不退出进程.

    参数:
        wlan: network.WLAN 实例, 用于掉线检测.
        uart: machine.UART 实例.
        led_wifi: WiFi 指示 LED Pin.
        led_run: 运行指示 LED Pin.

    返回:
        无.
    """
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((cfg.TCP_LISTEN_HOST, cfg.TCP_LISTEN_PORT))
    server.listen(cfg.TCP_BACKLOG)
    print("TCP 监听 %s:%d" % (cfg.TCP_LISTEN_HOST or "0.0.0.0", cfg.TCP_LISTEN_PORT))

    while True:
        _ensure_wifi(wlan)
        led_wifi.value(1 if wlan.isconnected() is True else 0)
        try:
            conn, addr = server.accept()
        except OSError as exc:
            print("accept 异常: %s" % exc)
            time.sleep_ms(200)
            continue
        print("客户端接入 %s" % str(addr))
        try:
            _serve_client(conn, uart, led_run)
        finally:
            try:
                conn.close()
            except OSError:
                pass


def main():
    """
    功能:
        固件入口, 组装 WiFi + UART + TCP Server 并进入主循环.

    参数:
        无.

    返回:
        无.
    """
    led_wifi = Pin(cfg.LED_WIFI_PIN, Pin.OUT)
    led_run = Pin(cfg.LED_RUN_PIN, Pin.OUT)
    led_wifi.value(0)
    led_run.value(0)

    wlan = _connect_wifi()
    led_wifi.value(1)
    uart = _open_uart()
    _run_server(wlan, uart, led_wifi, led_run)


if __name__ == "__main__":
    main()
