# coding: utf-8
"""
功能:
    电脑端 TCP 客户端. 与 HaaS506-ED1 固件 firmware/main.py 对接.
    协议: 一行一条 JSON, 以 '\\n' 作帧分隔. 发送请求后等待单行 JSON 响应.
    提供 query_all / query_layer / ping 三个业务方法, 异常统一 RackClientError.
"""

import json
import logging
import socket
from typing import Any, Dict, List, Optional

from unilabos.devices.eit_consumables_rack.config.settings import RackSettings


logger = logging.getLogger(__name__)


class RackClientError(Exception):
    """
    功能:
        耗材货架客户端异常. 连接失败, 超时, 协议错误, 单层查询失败等均上抛此异常.
    """


class RackClient:
    """
    功能:
        耗材货架 TCP 客户端.
        维持单条长连接, 按行发送 JSON 命令并读取单行 JSON 响应.
        对调用者屏蔽 socket 细节与自动重连, 暴露业务级方法.

    参数:
        settings: RackSettings 配置. 省略时使用默认值.

    返回:
        无.
    """

    def __init__(self, settings: Optional[RackSettings] = None) -> None:
        """
        功能:
            初始化客户端, 不立即建立连接.

        参数:
            settings: 可选 RackSettings; 未提供时使用默认配置.

        返回:
            无.
        """
        self._settings = settings if settings is not None else RackSettings()
        self._sock: Optional[socket.socket] = None
        self._buffer = bytearray()
        self._next_id = 1

    # --------------------------------------------------------------
    # 连接管理
    # --------------------------------------------------------------

    def connect(self) -> None:
        """
        功能:
            建立到 HaaS506-ED1 的 TCP 连接.
            若已连接则直接返回.

        参数:
            无.

        返回:
            无.
        """
        if self._sock is not None:
            return

        try:
            sock = socket.create_connection(
                (self._settings.host, self._settings.port),
                timeout=self._settings.socket_timeout_s,
            )
        except OSError as exc:
            raise RackClientError(
                f"连接 {self._settings.host}:{self._settings.port} 失败: {exc}"
            ) from exc

        sock.settimeout(self._settings.socket_timeout_s)
        self._sock = sock
        self._buffer.clear()
        logger.info(
            "已连接耗材货架网关 host=%s port=%s",
            self._settings.host,
            self._settings.port,
        )

    def close(self) -> None:
        """
        功能:
            关闭底层 socket, 重置接收缓冲.

        参数:
            无.

        返回:
            无.
        """
        if self._sock is None:
            return
        try:
            self._sock.close()
        except OSError:
            pass
        finally:
            self._sock = None
            self._buffer.clear()
            logger.info("已断开耗材货架网关")

    def __enter__(self) -> "RackClient":
        """
        功能:
            进入 with 语句时自动连接.

        参数:
            无.

        返回:
            RackClient 实例.
        """
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """
        功能:
            退出 with 语句时自动关闭连接.

        参数:
            exc_type/exc_val/exc_tb: 上下文异常信息, 仅透传不处理.

        返回:
            无.
        """
        self.close()

    # --------------------------------------------------------------
    # 业务方法
    # --------------------------------------------------------------

    def ping(self) -> bool:
        """
        功能:
            发送 ping 命令, 验证链路与固件存活.

        参数:
            无.

        返回:
            bool, True 表示固件响应 ok.
        """
        response = self._request({"cmd": "ping"})
        return bool(response.get("ok", False))

    def query_layer(self, layer: int) -> List[int]:
        """
        功能:
            查询单层占用状态.

        参数:
            layer: 层号, 1 ~ settings.layers.

        返回:
            List[int], 长度 positions_per_layer 的 0/1 列表.
            1 表示该盘位有耗材, 0 表示空.
        """
        if layer < 1 or layer > self._settings.layers:
            raise ValueError(
                f"layer 超出范围 1 ~ {self._settings.layers}: {layer}"
            )

        response = self._request({"cmd": "query_layer", "layer": layer})
        if bool(response.get("ok", False)) is False:
            raise RackClientError(
                f"查询第 {layer} 层失败: {response.get('error')}"
            )

        positions = response.get("positions")
        if isinstance(positions, list) is False:
            raise RackClientError(
                f"响应缺少 positions 字段或类型错误: {response}"
            )
        return [int(item) for item in positions]

    def query_all(self) -> Dict[int, List[int]]:
        """
        功能:
            一次性查询全部 layers 层的占用状态.
            单层查询失败时对应值为 None, 调用方可据此局部重试.

        参数:
            无.

        返回:
            Dict[int, List[int]], key 为层号 1 ~ layers.
            value 为该层 0/1 列表或 None.
        """
        response = self._request({"cmd": "query_all"})
        if bool(response.get("ok", False)) is False:
            raise RackClientError(f"查询全部层失败: {response.get('error')}")

        raw_layers = response.get("layers")
        if isinstance(raw_layers, dict) is False:
            raise RackClientError(f"响应缺少 layers 字段或类型错误: {response}")

        result: Dict[int, List[int]] = {}
        for layer in range(1, self._settings.layers + 1):
            raw_value = raw_layers.get(str(layer))
            if raw_value is None:
                result[layer] = None                               # 单层失败
                continue
            if isinstance(raw_value, list) is False:
                raise RackClientError(
                    f"第 {layer} 层 positions 类型错误: {raw_value}"
                )
            result[layer] = [int(item) for item in raw_value]
        return result

    # --------------------------------------------------------------
    # 内部实现
    # --------------------------------------------------------------

    def _request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        功能:
            发送单条 JSON 请求并读取单行 JSON 响应, 失败时按配置重试.

        参数:
            payload: 请求 dict, 本函数负责补充 id 字段.

        返回:
            Dict[str, Any], 解析后的响应体.
        """
        request_id = self._next_id
        self._next_id += 1
        payload_with_id = dict(payload)
        payload_with_id["id"] = request_id

        attempt = 0
        last_error: Optional[Exception] = None
        while attempt <= self._settings.connect_retries:
            try:
                self.connect()
                self._send_line(payload_with_id)
                response = self._recv_line()
                if response.get("id") not in (None, request_id):
                    raise RackClientError(
                        f"响应 id 不匹配, 期望 {request_id}, 实际 {response.get('id')}"
                    )
                return response
            except (OSError, RackClientError) as exc:
                last_error = exc
                logger.warning(
                    "请求失败, 尝试重连 attempt=%s err=%s", attempt, exc
                )
                self.close()
                attempt += 1

        raise RackClientError(f"请求失败, 重试耗尽: {last_error}")

    def _send_line(self, payload: Dict[str, Any]) -> None:
        """
        功能:
            把 dict 序列化为 JSON 并追加 '\\n' 通过 socket 发送.

        参数:
            payload: 请求 dict.

        返回:
            无.
        """
        if self._sock is None:
            raise RackClientError("socket 未建立")
        data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            self._sock.sendall(data)
        except OSError as exc:
            raise RackClientError(f"发送失败: {exc}") from exc

    def _recv_line(self) -> Dict[str, Any]:
        """
        功能:
            从 socket 接收数据直到读到 '\\n', 解析并返回 dict.

        参数:
            无.

        返回:
            Dict[str, Any], JSON 响应对象.
        """
        if self._sock is None:
            raise RackClientError("socket 未建立")

        while b"\n" not in self._buffer:
            try:
                chunk = self._sock.recv(1024)
            except OSError as exc:
                raise RackClientError(f"接收失败: {exc}") from exc
            if len(chunk) == 0:
                raise RackClientError("对端已关闭连接")
            self._buffer.extend(chunk)

        newline_index = self._buffer.index(b"\n")
        line = bytes(self._buffer[:newline_index])
        del self._buffer[: newline_index + 1]

        try:
            response = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RackClientError(f"响应 JSON 解析失败: {exc}") from exc

        if isinstance(response, dict) is False:
            raise RackClientError(f"响应非 JSON 对象: {response!r}")
        return response


__all__ = ["RackClient", "RackClientError"]
