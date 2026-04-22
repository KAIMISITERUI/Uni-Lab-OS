# -*- coding: utf-8 -*-
"""
功能:
    验证 TcpTransport 发送到打印机的字节流符合 TSPL 规范.
    使用 socketserver 在本地 127.0.0.1 起一个 mock 打印机, 捕获所有入站字节,
    再对 TSPL 指令头和 BITMAP 数据做精确断言. 不依赖真实硬件.
"""

import socket
import socketserver
import threading
import unittest

from unilabos.devices.eit_label_printer.driver.transport import TcpTransport


class _CaptureHandler(socketserver.BaseRequestHandler):
    """
    功能:
        TCPServer 的连接处理器, 把所有接收到的字节写入 server.received.
    """

    def handle(self):
        while True:
            chunk = self.request.recv(65536)
            if not chunk:
                break
            self.server.received += chunk


class _CaptureTCPServer(socketserver.TCPServer):
    """
    功能:
        带 received 缓冲区的 TCPServer. 允许地址重用, 避免端口 TIME_WAIT 干扰测试.
    """

    allow_reuse_address = True

    def __init__(self, addr, handler_cls):
        super().__init__(addr, handler_cls)
        self.received = b""


def _start_mock_printer():
    """
    功能:
        在 127.0.0.1 随机端口启动一个 mock TCP 打印机, 返回 (server, port, thread).
    返回:
        tuple(server, port, serve_thread).
    """
    server = _CaptureTCPServer(("127.0.0.1", 0), _CaptureHandler)
    _, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port, thread


def _wait_connection_closed(server, timeout=2.0):
    """
    功能:
        等待 mock 服务器收到 socket 关闭, 确保 received 缓冲区已完整.
        没有公开接口, 这里用反复 poll received 不再增长作为 proxy.
    参数:
        server: _CaptureTCPServer 实例.
        timeout: 最长等待秒数.
    """
    import time

    last_len = -1
    deadline = time.time() + timeout
    stable_rounds = 0
    while time.time() < deadline:
        curr = len(server.received)
        if curr == last_len:
            stable_rounds += 1
            if stable_rounds >= 3:
                return
        else:
            stable_rounds = 0
            last_len = curr
        time.sleep(0.05)


class TestTcpTransportByteStream(unittest.TestCase):
    """
    功能:
        验证 TcpTransport 各方法发送的字节流精确符合 TSPL 规范.
    """

    def setUp(self):
        self.server, self.port, self.thread = _start_mock_printer()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_send_command_encodes_gb18030_with_crlf(self):
        """
        功能:
            send_command 应以 GB18030 编码, 行尾 CRLF.
        """
        t = TcpTransport("127.0.0.1", self.port, timeout=2.0)
        t.open()
        t.send_command("SIZE 56 mm, 10 mm")
        t.send_command("中文测试")  # 确认 GB18030 编码路径
        t.close()
        _wait_connection_closed(self.server)

        self.assertIn(b"SIZE 56 mm, 10 mm\r\n", self.server.received)
        # "中文测试" 的 GB18030 编码固定
        self.assertIn("中文测试".encode("gb18030") + b"\r\n", self.server.received)

    def test_print_label_sends_print_command(self):
        """
        功能:
            print_label 应发送 PRINT <sets>,<copies>\\r\\n.
        """
        t = TcpTransport("127.0.0.1", self.port, timeout=2.0)
        t.open()
        t.print_label("1", "1")
        t.close()
        _wait_connection_closed(self.server)

        self.assertIn(b"PRINT 1,1\r\n", self.server.received)

    def test_render_windows_text_sends_bitmap_header_and_exact_data(self):
        """
        功能:
            render_windows_text 应发送 BITMAP 指令头, 紧跟正好 wb*h 字节的位图数据, 末尾 CRLF.
            不校验位图内容 (依赖 PIL/字体), 只校验协议格式.
        """
        try:
            from PIL import ImageFont  # noqa: F401
        except ImportError:
            self.skipTest("本机未安装 Pillow, 跳过 BITMAP 字节流测试")

        t = TcpTransport("127.0.0.1", self.port, timeout=2.0)
        t.open()
        t.render_windows_text(
            x=10, y=20, font_height=24, rotation=0, bold=0, underline=0,
            font_name="Arial", text="AB",
        )
        t.close()
        _wait_connection_closed(self.server)

        received = self.server.received
        # 指令头格式: BITMAP x,y,wb,h,0,
        self.assertIn(b"BITMAP 10,20,", received)
        # 解析出 wb 和 h, 验证后续字节数
        idx = received.index(b"BITMAP ")
        header_end = received.index(b",", idx + len(b"BITMAP 10,20,"))
        # 5 个逗号后紧跟数据, 末尾 \r\n
        # 精确解析 header: BITMAP X,Y,WB,H,MODE,<data>\r\n
        header_line_end = received.index(b",", header_end + 1)  # 第 4 个逗号(h 后)
        mode_comma = received.index(b",", header_line_end + 1)  # 第 5 个逗号(mode 后)
        header_text = received[idx:mode_comma + 1].decode("ascii")
        parts = header_text[len("BITMAP "):-1].split(",")  # 去掉 "BITMAP " 前缀和末尾 ","
        self.assertEqual(len(parts), 5)
        x, y, wb, h, mode = (int(p) for p in parts)
        self.assertEqual((x, y, mode), (10, 20, 0))
        self.assertGreater(wb, 0)
        self.assertGreater(h, 0)

        data_start = mode_comma + 1
        data_end = data_start + wb * h
        self.assertEqual(received[data_end:data_end + 2], b"\r\n",
                         f"位图数据后必须紧跟 CRLF, 实际 {received[data_end:data_end + 4]!r}")


class TestTcpTransportLifecycle(unittest.TestCase):
    """
    功能:
        验证 TcpTransport 的连接生命周期行为 (幂等 open/close, 重复 close 不抛).
    """

    def setUp(self):
        self.server, self.port, self.thread = _start_mock_printer()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_open_is_idempotent(self):
        """
        功能:
            重复 open 不应建立新连接, 不抛异常.
        """
        t = TcpTransport("127.0.0.1", self.port, timeout=2.0)
        t.open()
        first_sock = t._sock  # 访问内部字段是测试合理行为
        t.open()
        self.assertIs(t._sock, first_sock)
        t.close()

    def test_close_is_idempotent(self):
        """
        功能:
            重复 close 不抛异常.
        """
        t = TcpTransport("127.0.0.1", self.port, timeout=2.0)
        t.open()
        t.close()
        t.close()  # 再次 close 应 silently 返回
        self.assertIsNone(t._sock)

    def test_connect_refused_raises_oserror(self):
        """
        功能:
            连不上时应直接向上抛 OSError, 不静默吞错 (第一性原理, 不兜底).
        """
        t = TcpTransport("127.0.0.1", 1, timeout=0.5)  # 端口 1 肯定连不上
        with self.assertRaises(OSError):
            t.open()


if __name__ == "__main__":
    unittest.main(verbosity=2)
