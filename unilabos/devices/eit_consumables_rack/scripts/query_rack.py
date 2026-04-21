# coding: utf-8
"""
功能:
    耗材货架一次性查询命令行工具.
    连接 HaaS506-ED1 网关, 拉取全部层状态并打印表格.
    占用打印 ■, 空打印 ·. 退出码: 0 成功, 1 连接失败, 2 部分层查询失败.

用法:
    python -m unilabos.devices.eit_consumables_rack.scripts.query_rack \
        [--host 192.168.1.100] [--port 6006] [--timeout 3.0]
"""

import argparse
import logging
import sys
from typing import List, Optional

from unilabos.devices.devices_logging import configure_root_logging
from unilabos.devices.eit_consumables_rack.config.settings import RackSettings
from unilabos.devices.eit_consumables_rack.driver.rack_client import (
    RackClient,
    RackClientError,
)


logger = logging.getLogger(__name__)

_OCCUPIED_GLYPH = "■"
_EMPTY_GLYPH = "·"
_MISSING_GLYPH = "?"


def _parse_args() -> argparse.Namespace:
    """
    功能:
        解析命令行参数.

    参数:
        无.

    返回:
        argparse.Namespace, 包含 host/port/timeout/log_level.
    """
    default = RackSettings.from_env()
    parser = argparse.ArgumentParser(
        description="耗材货架占用状态查询工具"
    )
    parser.add_argument("--host", default=default.host, help="HaaS506-ED1 IP")
    parser.add_argument("--port", type=int, default=default.port, help="TCP 端口")
    parser.add_argument(
        "--timeout",
        type=float,
        default=default.socket_timeout_s,
        help="socket 超时(秒)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )
    return parser.parse_args()


def _render_table(layers: dict, positions_per_layer: int) -> str:
    """
    功能:
        把 query_all 返回的 dict 渲染为人类可读表格.

    参数:
        layers: Dict[int, Optional[List[int]]]; None 表示该层查询失败.
        positions_per_layer: 每层盘位数量, 用于表头对齐.

    返回:
        str, 多行表格文本.
    """
    header_positions = "  ".join(f"{idx:>2d}" for idx in range(1, positions_per_layer + 1))
    lines = [f"层 | {header_positions}"]
    lines.append("-" * len(lines[0]))
    for layer_id in sorted(layers.keys()):
        positions: Optional[List[int]] = layers[layer_id]
        if positions is None:
            cells = "  ".join(f"{_MISSING_GLYPH:>2s}" for _ in range(positions_per_layer))
        else:
            cells = "  ".join(
                f"{_OCCUPIED_GLYPH if item else _EMPTY_GLYPH:>2s}" for item in positions
            )
        lines.append(f"{layer_id:>2d} | {cells}")
    return "\n".join(lines)


def main() -> int:
    """
    功能:
        命令行入口, 查询货架并打印表格.

    参数:
        无.

    返回:
        int, 进程退出码.
    """
    args = _parse_args()
    configure_root_logging(level=args.log_level)

    settings = RackSettings(
        host=args.host,
        port=args.port,
        socket_timeout_s=args.timeout,
    )

    try:
        with RackClient(settings) as client:
            layers = client.query_all()
    except RackClientError as exc:
        logger.error("查询失败: %s", exc)
        return 1

    print(_render_table(layers, settings.positions_per_layer))

    has_failure = any(value is None for value in layers.values())
    if has_failure is True:
        logger.warning("存在单层查询失败, 请检查 RS485 链路")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
