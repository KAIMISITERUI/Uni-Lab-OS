# coding: utf-8
"""
功能:
    电脑端 RackClient 运行参数.
    支持 dataclass 直接实例化, 也支持从环境变量读取.
"""

import logging
import os
from dataclasses import dataclass


logger = logging.getLogger(__name__)


_ENV_PREFIX = "RACK_"


@dataclass
class RackSettings:
    """
    功能:
        耗材货架客户端配置.
        host/port 必须与 HaaS506-ED1 侧 firmware/board_config.py 一致.

    参数:
        host: HaaS506-ED1 在局域网内的 IP 或主机名.
        port: HaaS506-ED1 TCP Server 监听端口.
        socket_timeout_s: socket recv/send 超时.
        connect_retries: 断线重连最大次数, 0 表示不重连.
        layers: 货架层数, 与 SLAVE_ADDRS 长度一致.
        positions_per_layer: 每层盘位数量, 与 Modbus 寄存器数量一致.

    返回:
        无.
    """

    host: str = "192.168.1.45"
    port: int = 6006
    socket_timeout_s: float = 3.0
    connect_retries: int = 2
    layers: int = 5
    positions_per_layer: int = 6

    @classmethod
    def from_env(cls) -> "RackSettings":
        """
        功能:
            从 RACK_ 前缀环境变量构造配置, 缺省值来自 dataclass 默认值.

        参数:
            无.

        返回:
            RackSettings 实例.
        """
        default = cls()
        return cls(
            host=os.environ.get(f"{_ENV_PREFIX}HOST", default.host),
            port=int(os.environ.get(f"{_ENV_PREFIX}PORT", default.port)),
            socket_timeout_s=float(
                os.environ.get(f"{_ENV_PREFIX}TIMEOUT", default.socket_timeout_s)
            ),
            connect_retries=int(
                os.environ.get(f"{_ENV_PREFIX}RETRIES", default.connect_retries)
            ),
            layers=int(os.environ.get(f"{_ENV_PREFIX}LAYERS", default.layers)),
            positions_per_layer=int(
                os.environ.get(
                    f"{_ENV_PREFIX}POSITIONS", default.positions_per_layer
                )
            ),
        )


__all__ = ["RackSettings"]
