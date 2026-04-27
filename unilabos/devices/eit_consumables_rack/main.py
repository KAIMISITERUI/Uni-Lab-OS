# coding: utf-8
"""
功能:
    耗材货架交互式查询工具.
    底层 ping / all / layer 走 RackClient, 高层 find / slot / available 走 RackController.
    被 eit_hub 通过 importlib.import_module("eit_consumables_rack.main").interactive() 调用.

用法:
    python -m unilabos.devices.eit_consumables_rack.main \
        [--host 192.168.1.45] [--port 6006]
"""

import argparse
import logging
import sys
from dataclasses import replace
from typing import List, Optional

from unilabos.devices.devices_logging import configure_root_logging
from unilabos.devices.eit_consumables_rack.config.settings import RackSettings
from unilabos.devices.eit_consumables_rack.controller import (
    RackController,
    SlotStatus,
    load_resource_config,
)
from unilabos.devices.eit_consumables_rack.driver.rack_client import (
    RackClient,
    RackClientError,
)


logger = logging.getLogger(__name__)

_OCCUPIED_GLYPH = "■"
_EMPTY_GLYPH = "·"
_MISSING_GLYPH = "?"

_PROMPT = "rack> "
_HELP_TEXT = (
    "可用命令:\n"
    "  all                  查询全部 5 层光电状态 (协议层)\n"
    "  layer N              查询第 N 层 (N=1~5, 协议层)\n"
    "  ping                 心跳探活\n"
    "  find <类型>          按资源类型列出全部声明盘位 (含占用状态)\n"
    "  slot <层> <位>       查询单个盘位 (层=1~5, 位=0~5)\n"
    "  available [<类型>]   列出当前实际有耗材的盘位, 可按类型过滤\n"
    "  help                 显示本帮助\n"
    "  quit / exit          退出"
)


def _parse_args() -> argparse.Namespace:
    """
    功能:
        解析命令行参数.

    参数:
        无.

    返回:
        argparse.Namespace, 包含 host / port / timeout / log_level.
    """
    default = RackSettings.from_env()
    parser = argparse.ArgumentParser(description="耗材货架交互式查询测试")
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
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别, 交互式默认 WARNING 以免干扰提示符",
    )
    return parser.parse_args()


def _format_positions(positions: Optional[List[int]], positions_per_layer: int) -> str:
    """
    功能:
        把 0/1 列表格式化为带图形的单行字符串.

    参数:
        positions: 盘位状态列表, None 表示该层查询失败.
        positions_per_layer: 盘位数量, 用于对齐缺失数据.

    返回:
        str, 盘位字符串.
    """
    if positions is None:
        return "  ".join(f"{_MISSING_GLYPH:>2s}" for _ in range(positions_per_layer))
    return "  ".join(
        f"{_OCCUPIED_GLYPH if item != 0 else _EMPTY_GLYPH:>2s}" for item in positions
    )


def _print_layers(layers: dict, positions_per_layer: int) -> None:
    """
    功能:
        以表格方式打印全部层状态.

    参数:
        layers: query_all 返回的 dict.
        positions_per_layer: 每层盘位数量.

    返回:
        无.
    """
    header_positions = "  ".join(f"{idx:>2d}" for idx in range(1, positions_per_layer + 1))
    header = f"层 | {header_positions}"
    print(header)
    print("-" * len(header))
    for layer_id in sorted(layers.keys()):
        cells = _format_positions(layers[layer_id], positions_per_layer)
        print(f"{layer_id:>2d} | {cells}")


def _handle_all(client: RackClient, settings: RackSettings) -> None:
    """
    功能:
        执行 all 命令, 打印全部层状态.

    参数:
        client: 已连接的 RackClient.
        settings: RackSettings, 用于确定盘位数量.

    返回:
        无.
    """
    layers = client.query_all()
    _print_layers(layers, settings.positions_per_layer)
    if any(value is None for value in layers.values()) is True:
        print("警告: 存在单层查询失败, ? 位置代表 RS485 通信异常")


def _handle_layer(client: RackClient, settings: RackSettings, raw_arg: str) -> None:
    """
    功能:
        执行 layer N 命令, 打印单层状态.

    参数:
        client: 已连接的 RackClient.
        settings: RackSettings, 提供层数范围与每层盘位数.
        raw_arg: 用户输入的层号字符串.

    返回:
        无.
    """
    try:
        layer = int(raw_arg)
    except ValueError:
        print("layer 参数必须是整数, 例如: layer 3")
        return

    positions = client.query_layer(layer)
    cells = _format_positions(positions, settings.positions_per_layer)
    print(f"第 {layer} 层 | {cells}")


def _handle_ping(client: RackClient) -> None:
    """
    功能:
        执行 ping 命令.

    参数:
        client: 已连接的 RackClient.

    返回:
        无.
    """
    alive = client.ping()
    print("ping: %s" % ("ok" if alive is True else "failed"))


def _format_slot_status(item: SlotStatus) -> str:
    """
    功能:
        把单个 SlotStatus 渲染为单行可读字符串, 同时显示位置, 资源类型与占用状态.

    参数:
        item: SlotStatus 实例.

    返回:
        str, 单行描述.
    """
    glyph = _OCCUPIED_GLYPH if item.occupied is True else _EMPTY_GLYPH
    type_text = item.resource_type if item.resource_type is not None else "(未声明)"
    description = f" - {item.description}" if item.description != "" else ""
    return (
        f"  L{item.layer} P{item.position} {glyph}  "
        f"{type_text}{description}"
    )


def _handle_find(controller: RackController, raw_arg: str) -> None:
    """
    功能:
        执行 find <类型> 命令, 列出该资源类型在 yaml 中声明的全部盘位与实时占用状态.

    参数:
        controller: 已连接的 RackController.
        raw_arg: 用户输入的资源类型字符串.

    返回:
        无.
    """
    if raw_arg == "":
        print("用法: find <资源类型>, 例如 find tube_15ml")
        return

    items = controller.find_by_type(raw_arg)
    if len(items) == 0:
        print(f"未在配置中找到资源类型: {raw_arg}")
        return

    occupied_count = sum(1 for item in items if item.occupied is True)
    print(
        f"资源 '{raw_arg}': 共 {len(items)} 个盘位, "
        f"当前占用 {occupied_count} / 空 {len(items) - occupied_count}"
    )
    for item in items:
        print(_format_slot_status(item))


def _handle_slot(controller: RackController, raw_arg: str) -> None:
    """
    功能:
        执行 slot <层> <位> 命令, 查询单个盘位的资源类型与占用状态.

    参数:
        controller: 已连接的 RackController.
        raw_arg: 用户输入的 "<层> <位>" 字符串.

    返回:
        无.
    """
    parts = raw_arg.split()
    if len(parts) != 2:
        print("用法: slot <层> <位>, 例如 slot 1 0")
        return

    try:
        layer = int(parts[0])
        position = int(parts[1])
    except ValueError:
        print("层号与位号必须是整数")
        return

    item = controller.get_slot(layer, position)
    print(_format_slot_status(item))


def _handle_available(controller: RackController, raw_arg: str) -> None:
    """
    功能:
        执行 available [<类型>] 命令, 列出当前实际有耗材的盘位, 可按资源类型过滤.

    参数:
        controller: 已连接的 RackController.
        raw_arg: 可选资源类型字符串, 空字符串表示不过滤.

    返回:
        无.
    """
    resource_type = raw_arg if raw_arg != "" else None
    items = controller.list_available(resource_type)
    if len(items) == 0:
        if resource_type is None:
            print("当前货架无任何占用盘位")
        else:
            print(f"当前没有可用的 '{resource_type}'")
        return

    if resource_type is None:
        print(f"当前占用盘位 {len(items)} 个:")
    else:
        print(f"资源 '{resource_type}' 当前可用 {len(items)} 个:")
    for item in items:
        print(_format_slot_status(item))


def _dispatch(
    client: RackClient,
    controller: RackController,
    settings: RackSettings,
    line: str,
) -> bool:
    """
    功能:
        解析并执行单条用户命令.
        捕获 RackClientError / ValueError 并以可读形式输出, 避免异常冲断交互.

    参数:
        client: 已连接的 RackClient, 用于协议层 ping / all / layer.
        controller: 已加载资源配置的 RackController, 用于 find / slot / available.
        settings: RackSettings.
        line: 用户输入的一行命令(已 strip).

    返回:
        bool, False 表示用户请求退出.
    """
    if line == "":
        return True
    parts = line.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    try:
        if cmd in ("quit", "exit"):
            return False
        if cmd == "help":
            print(_HELP_TEXT)
            return True
        if cmd == "all":
            _handle_all(client, settings)
            return True
        if cmd == "layer":
            if arg == "":
                print("用法: layer N")
                return True
            _handle_layer(client, settings, arg)
            return True
        if cmd == "ping":
            _handle_ping(client)
            return True
        if cmd == "find":
            _handle_find(controller, arg)
            return True
        if cmd == "slot":
            _handle_slot(controller, arg)
            return True
        if cmd == "available":
            _handle_available(controller, arg)
            return True
        print("未知命令, 输入 help 查看帮助")
        return True
    except ValueError as exc:
        print("参数错误: %s" % exc)
        return True
    except RackClientError as exc:
        print("请求失败: %s" % exc)
        return True


def _read_line() -> Optional[str]:
    """
    功能:
        从 stdin 读取一行用户输入.
        EOF (Ctrl+Z/Ctrl+D) 或 Ctrl+C 返回 None 以触发退出.

    参数:
        无.

    返回:
        Optional[str], 用户输入去除两端空白. None 表示请求退出.
    """
    try:
        return input(_PROMPT).strip()
    except EOFError:
        print()
        return None
    except KeyboardInterrupt:
        print()
        return None


def interactive(settings: Optional[RackSettings] = None) -> None:
    """
    功能:
        启动耗材货架交互式查询循环.
        建立 TCP 长连接, 加载资源 yaml, 进入命令循环.
        被 eit_hub 通过 importlib 调用时不传 settings, 内部从环境变量加载.

    参数:
        settings: 可选 RackSettings, 省略时调用 RackSettings.from_env().

    返回:
        无.
    """
    effective = settings if settings is not None else RackSettings.from_env()

    print(f"连接 {effective.host}:{effective.port} ...")
    try:
        slot_resources = load_resource_config(
            effective.resource_config_path,
            effective.layers,
            effective.positions_per_layer,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"资源配置加载失败: {exc}")
        return

    client = RackClient(effective)
    try:
        client.connect()
    except RackClientError as exc:
        print(f"连接失败: {exc}")
        return

    controller = RackController(client, slot_resources)

    declared_count = sum(
        1 for resource in slot_resources.values() if resource.resource_type is not None
    )
    print(
        f"连接成功, 已加载资源配置 (声明 {declared_count} / 总 {len(slot_resources)} 盘位)"
    )
    print("输入 help 查看命令, quit 退出")
    try:
        while True:
            line = _read_line()
            if line is None:
                break
            keep_running = _dispatch(client, controller, effective, line)
            if keep_running is False:
                break
    finally:
        client.close()
    print("已退出")


def main() -> int:
    """
    功能:
        命令行入口. 解析参数后调用 interactive 完成交互.

    参数:
        无.

    返回:
        int, 进程退出码. 0 正常退出.
    """
    args = _parse_args()
    configure_root_logging(level=args.log_level)

    # 以 from_env 为基础, 仅按命令行覆盖通讯三项, 其余配置 (layers/positions/yaml 路径) 保留
    base = RackSettings.from_env()
    settings = replace(
        base,
        host=args.host,
        port=args.port,
        socket_timeout_s=args.timeout,
    )

    interactive(settings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
