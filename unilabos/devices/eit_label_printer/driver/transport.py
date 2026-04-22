# coding: utf-8
"""
功能:
    打印机通讯层抽象.
    将 "连接 + 发送 TSPL 文本指令 + 渲染 Windows 字体文字 + 触发打印 + 断开"
    五个原子操作抽象为 Transport 接口, 业务层 (print_engine) 不再直接依赖
    TSCLIB.dll 或 socket.

提供两种实现:
    DllTransport: 通过 TSCLIB.dll + Windows 打印机驱动 (USB / 驱动级网络端口).
    TcpTransport: 通过 WiFi TCP 9100 直连, 使用 PIL 在 PC 端栅格化文字后
                  以 TSPL BITMAP 指令发送, 功能与 DLL 模式视觉对齐.

依赖:
    DllTransport: ctypes (标准库), 仅 Windows 可用.
    TcpTransport: Pillow (pip install Pillow), 用于文字渲染.

协议参考:
    TSPL2 编程手册 BITMAP 指令: BITMAP x,y,width_bytes,height,mode,<data>
    - width_bytes = ceil(pixel_width / 8)
    - mode: 0=覆盖 1=OR 2=XOR
    - data: 原始字节流, 每字节 8 像素 MSB 优先, bit 0 = 打印(黑), bit 1 = 不打印(白)
    WiFi 通讯端口 9100 由 SDK FAQ 第 3.2 节明确.
"""

import ctypes
import logging
import os
import socket
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)

# 常用 Windows 字体名 → 文件名映射, 用于 PIL 加载
# PIL 不认识 "微软雅黑" 这种本地化名, 需显式给出 ttf/ttc 文件名
_WINDOWS_FONT_MAP = {
    "arial": "arial.ttf",
    "arial black": "ariblk.ttf",
    "times new roman": "times.ttf",
    "courier new": "cour.ttf",
    "verdana": "verdana.ttf",
    "tahoma": "tahoma.ttf",
    "calibri": "calibri.ttf",
    "consolas": "consola.ttf",
    "微软雅黑": "msyh.ttc",
    "微软雅黑 light": "msyhl.ttc",
    "宋体": "simsun.ttc",
    "新宋体": "simsun.ttc",
    "黑体": "simhei.ttf",
    "楷体": "simkai.ttf",
    "仿宋": "simfang.ttf",
    "等线": "deng.ttf",
}


class Transport(ABC):
    """
    功能:
        打印机通讯抽象基类. 子类负责具体通讯方式 (DLL 或 TCP socket),
        业务代码只面向此接口.

    方法语义:
        open/close 必须成对, 重入由 _opened 标志保证幂等.
        send_command 发送 ASCII TSPL 文本指令 (一行, 末尾 CRLF 由实现负责).
        render_windows_text 在指定位置用指定 Windows 字体绘制文字.
        print_label 发送 PRINT 指令触发实际出纸.
    """

    @abstractmethod
    def open(self) -> None:
        """
        功能:
            建立到打印机的连接. 无参数, 连接参数在构造时传入.
        """

    @abstractmethod
    def send_command(self, command: str) -> None:
        """
        功能:
            发送一条 ASCII TSPL 文本指令.
        参数:
            command: TSPL 指令字符串, 不含换行符, 实现负责追加 CRLF.
        """

    @abstractmethod
    def render_windows_text(
        self,
        x: int,
        y: int,
        font_height: int,
        rotation: int,
        bold: int,
        underline: int,
        font_name: str,
        text: str,
    ) -> None:
        """
        功能:
            在 (x, y) 位置用指定 Windows 字体绘制文字.
        参数:
            x/y: 文字起始点, 单位 dot.
            font_height: 字体高度, 单位 dot.
            rotation: 旋转角度, 0/90/180/270.
            bold: 粗体, 0 否 / 1 是.
            underline: 下划线, 0 否 / 1 是.
            font_name: Windows 字体名, 例如 "Arial" 或 "微软雅黑".
            text: 要绘制的文字内容.
        """

    @abstractmethod
    def print_label(self, sets: str, copies: str) -> None:
        """
        功能:
            触发打印当前缓冲区内容.
        参数:
            sets: 打印标签个数字符串.
            copies: 每个标签份数字符串.
        """

    @abstractmethod
    def close(self) -> None:
        """
        功能:
            关闭连接, 释放资源.
        """


# ═══════════════════════ DllTransport ═══════════════════════


def _load_tsclib(dll_path: str) -> ctypes.WinDLL:
    """
    功能:
        加载 TSCLIB.dll 并声明常用函数签名.
    参数:
        dll_path: DLL 文件绝对路径.
    返回:
        ctypes.WinDLL 实例.
    """
    if not os.path.exists(dll_path):
        raise FileNotFoundError(f"找不到 DLL 文件: {dll_path}")

    lib = ctypes.WinDLL(dll_path)
    wstr = ctypes.c_wchar_p
    lib.openportW.argtypes = [wstr]
    lib.openportW.restype = ctypes.c_int  # 0=失败, 非0=成功
    lib.closeport.argtypes = []
    lib.sendcommandW.argtypes = [wstr]
    lib.printlabelW.argtypes = [wstr, wstr]
    # windowsfontUnicode: 前6个int, 第7个字体名(ASCII char*), 第8个UTF-16LE内容缓冲区(void*)
    lib.windowsfontUnicode.argtypes = [
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p,
    ]
    lib.windowsfontUnicode.restype = ctypes.c_int
    logger.debug("已加载 DLL: %s", dll_path)
    return lib


class DllTransport(Transport):
    """
    功能:
        通过 TSCLIB.dll + Windows 打印机驱动的通讯实现.
        依赖系统已安装 GP-1134T 驱动, 端口名必须与 Windows 设备管理器里的一致.
    参数:
        dll_path: TSCLIB.dll 绝对路径.
        printer_port: Windows 打印机名, 例如 "Gprinter GP-1134T".
    """

    def __init__(self, dll_path: str, printer_port: str):
        self._dll_path = str(dll_path)
        self._printer_port = printer_port
        self._lib: Optional[ctypes.WinDLL] = None
        self._opened = False

    def open(self) -> None:
        if self._opened:
            return
        if self._lib is None:
            self._lib = _load_tsclib(self._dll_path)
        ret = self._lib.openportW(self._printer_port)
        if ret == 0:
            raise RuntimeError(
                f"无法连接打印机, 端口/名称: '{self._printer_port}'. "
                "请检查配置中的打印机名称是否与系统中安装的名称一致"
            )
        self._opened = True
        logger.debug("DllTransport 已连接: %s", self._printer_port)

    def send_command(self, command: str) -> None:
        self._lib.sendcommandW(command)

    def render_windows_text(
        self,
        x: int,
        y: int,
        font_height: int,
        rotation: int,
        bold: int,
        underline: int,
        font_name: str,
        text: str,
    ) -> None:
        # UTF-16LE 编码后追加终止符, 使用 create_string_buffer 避免 c_char_p 遇到 \x00 截断
        raw = text.encode("utf-16-le") + b"\x00\x00"
        content_buf = ctypes.create_string_buffer(raw)
        self._lib.windowsfontUnicode(
            x,
            y,
            font_height,
            rotation,
            bold,
            underline,
            font_name.encode("ascii"),
            ctypes.cast(content_buf, ctypes.c_void_p),
        )

    def print_label(self, sets: str, copies: str) -> None:
        self._lib.printlabelW(sets, copies)

    def close(self) -> None:
        if not self._opened:
            return
        try:
            self._lib.closeport()
        finally:
            self._opened = False
            logger.debug("DllTransport 已断开")


# ═══════════════════════ TcpTransport ═══════════════════════


def _resolve_font_file(font_name: str) -> str:
    """
    功能:
        把 Windows 字体名解析为 PIL 可加载的文件名或路径.
        先查映射表, 再交给 PIL 自己搜 (PIL 会在 C:\\Windows\\Fonts 下按名查).
    参数:
        font_name: Windows 字体名.
    返回:
        str, 字体文件名或绝对路径.
    """
    key = font_name.strip().lower()
    if key in _WINDOWS_FONT_MAP:
        return _WINDOWS_FONT_MAP[key]
    # 若映射表没有, 原样返回让 PIL 尝试 (英文字体名通常 PIL 能直接搜到)
    return font_name


class TcpTransport(Transport):
    """
    功能:
        通过 WiFi TCP 9100 直连打印机的通讯实现.
        TSPL 文本指令以 GB18030 编码发送 (兼容中文); Windows 字体文字在 PC 端
        用 PIL 栅格化为 1-bit 位图, 再以 TSPL BITMAP 指令发送, 视觉效果与
        DLL 模式的 windowsfontUnicode 等价.
    参数:
        host: 打印机 IP 地址.
        port: TCP 端口, 佳博 GP-1134T 固定 9100.
        timeout: 连接和读写超时 (秒).
    """

    def __init__(self, host: str, port: int = 9100, timeout: float = 5.0):
        self._host = host
        self._port = port
        self._timeout = timeout
        self._sock: Optional[socket.socket] = None

    def open(self) -> None:
        if self._sock is not None:
            return
        self._sock = socket.create_connection(
            (self._host, self._port), timeout=self._timeout
        )
        # 发送时也应用超时, 避免某些固件不关闭 socket 导致卡住
        self._sock.settimeout(self._timeout)
        logger.debug("TcpTransport 已连接: %s:%d", self._host, self._port)

    def send_command(self, command: str) -> None:
        # TSPL 指令按 GB18030 编码发送 (见 FAQ 4.3 节), 行尾 CRLF
        payload = (command + "\r\n").encode("gb18030")
        self._sock.sendall(payload)

    def render_windows_text(
        self,
        x: int,
        y: int,
        font_height: int,
        rotation: int,
        bold: int,
        underline: int,
        font_name: str,
        text: str,
    ) -> None:
        # 延迟 import, 避免 DLL 用户被强制装 Pillow
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError as exc:
            raise RuntimeError(
                "WiFi 模式需要 Pillow, 请 pip install Pillow"
            ) from exc

        font_file = _resolve_font_file(font_name)
        try:
            # 粗体通过 freetype index 或加粗处理实现, 这里用 PIL 自带加粗近似
            font = ImageFont.truetype(font_file, font_height)
        except (OSError, IOError) as exc:
            raise RuntimeError(
                f"无法加载字体 '{font_name}' (尝试文件 '{font_file}'): {exc}"
            ) from exc

        # 先测量文字的渲染包围盒, 据此创建最小位图
        # textbbox 返回 (left, top, right, bottom), 其中 top 可能为负 (超出基线上方)
        tmp_img = Image.new("1", (1, 1), 1)
        tmp_draw = ImageDraw.Draw(tmp_img)
        bbox = tmp_draw.textbbox((0, 0), text, font=font, stroke_width=1 if bold else 0)
        text_w = max(1, bbox[2] - bbox[0])
        text_h = max(1, bbox[3] - bbox[1])

        # 关键: 宽度向上对齐到 8 的倍数, 避免 PIL mode "1" tobytes 行尾 padding bit 的歧义
        # PIL padding 默认 bit=0, 而 TSPL BITMAP 中 bit 0 = 打印黑点 → 非对齐时每行末尾出现黑色竖线
        img_w = ((text_w + 7) // 8) * 8
        img_h = text_h

        # 绘制到 1-bit 位图: 1=白底(不打印), 0=黑字(打印), 多出的对齐列天然为白色
        img = Image.new("1", (img_w, img_h), 1)
        draw = ImageDraw.Draw(img)
        # 消除 bbox 起点偏移, 把文字原点拉到 (0,0)
        draw.text(
            (-bbox[0], -bbox[1]),
            text,
            font=font,
            fill=0,
            stroke_width=1 if bold else 0,
            stroke_fill=0,
        )

        if underline:
            # 下划线: 在基线下 1/10 字高处画一条, 粗 max(1, h/20)
            underline_y = img_h - max(1, img_h // 10)
            draw.line(
                [(0, underline_y), (text_w - 1, underline_y)],
                fill=0,
                width=max(1, img_h // 20),
            )

        if rotation:
            # PIL 旋转: expand=True 保留完整内容, fillcolor=1 用白色填新增区域
            img = img.rotate(-rotation, expand=True, fillcolor=1)
            rot_w, rot_h = img.size
            # 旋转后宽度可能再次不是 8 的倍数, 右侧用白色 padding 对齐
            aligned_w = ((rot_w + 7) // 8) * 8
            if aligned_w != rot_w:
                padded = Image.new("1", (aligned_w, rot_h), 1)
                padded.paste(img, (0, 0))
                img = padded
            img_w, img_h = img.size

        # 发送 TSPL BITMAP 指令 + 原始字节流
        # img_w 此时必然是 8 的倍数, width_bytes 精确等于每行实际数据字节数
        width_bytes = img_w // 8
        data = img.tobytes()
        expected = width_bytes * img_h
        if len(data) != expected:
            raise RuntimeError(
                f"BITMAP 数据长度异常: 期望 {expected}, 实际 {len(data)}"
            )

        header = f"BITMAP {x},{y},{width_bytes},{img_h},0,".encode("ascii")
        self._sock.sendall(header + data + b"\r\n")

    def print_label(self, sets: str, copies: str) -> None:
        payload = f"PRINT {sets},{copies}\r\n".encode("ascii")
        self._sock.sendall(payload)

    def close(self) -> None:
        """
        功能:
            优雅关闭与打印机的 TCP 连接. 先 shutdown(SHUT_WR) 发送 FIN, 再等对端主动
            关闭或超时, 最后释放 socket.
        原理:
            GP-1134T 的 WiFi 模块 (HI-LINK 类) 内部是 WiFi 网关 + UART 桥接, 从 TCP 收
            到的字节会缓存后再串行发给打印机主控. 若在 BITMAP 数据尚未完全写入 UART 时
            就直接 close(), WiFi 模块会丢弃 buffer 里未发出的尾部字节, 下一次连接发送的
            首包会接到上一次被截断的位置, 形成画面错位 / 环绕 / 乱码.
            shutdown + recv-until-EOF 是 TCP 优雅关闭的标准流程, 能让 WiFi 模块把
            buffer flush 完再关连接, 彻底消除截断.
        """
        if self._sock is None:
            return
        try:
            try:
                self._sock.shutdown(socket.SHUT_WR)
            except OSError:
                # 对端可能已先关闭, 这一步失败不影响后续 recv+close
                pass
            # 读到 EOF (对端 FIN) 或超时. 超时仅作为 flush 上限, 不影响正确性
            self._sock.settimeout(self._timeout)
            try:
                while True:
                    if not self._sock.recv(4096):
                        break
            except OSError:
                # 超时或其它读错误均视为 flush 完成, 继续 close
                pass
            self._sock.close()
        finally:
            self._sock = None
            logger.debug("TcpTransport 已断开")


__all__ = ["Transport", "DllTransport", "TcpTransport"]
