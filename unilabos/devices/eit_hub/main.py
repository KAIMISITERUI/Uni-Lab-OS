#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    提供 EIT 多工站总控交互入口, 统一分发到合成站, 分析站和 AGV 菜单.
参数:
    无.
返回:
    无.
"""

import importlib
import logging

try:
    from devices_logging import configure_root_logging
except ImportError:
    from unilabos.devices.devices_logging import configure_root_logging

logger = logging.getLogger("EITHubInteractiveCLI")


def _run_station_menu(module_name: str, station_label: str) -> None:
    """
    功能:
        按需加载指定工站的 interactive 入口并执行.
    参数:
        module_name: 工站 main 模块路径.
        station_label: 工站中文名称, 用于提示和日志.
    返回:
        无.
    """
    try:
        module = importlib.import_module(module_name)
        module.interactive()
    except Exception as exc:
        logger.exception("进入%s菜单失败", station_label)
        print(f"\n进入{station_label}菜单失败: {exc}\n")


def interactive() -> None:
    """
    功能:
        启动 EIT Hub 顶层交互菜单.
    参数:
        无.
    返回:
        无.
    """
    configure_root_logging(level="INFO")

    while True:
        print("\n================================================")
        print("EIT 多工站总控交互台")
        print("================================================")
        print("1. 合成工站")
        print("2. 分析工站")
        print("3. AGV 工站")
        print("4. 化学品库管理")
        print("0. 退出")
        print("================================================")

        choice = input("请选择操作: ").strip()

        if choice == "0":
            print("已退出总控交互台.")
            break
        if choice == "1":
            _run_station_menu("eit_synthesis_station.main", "合成工站")
            continue
        if choice == "2":
            _run_station_menu("eit_analysis_station.main", "分析工站")
            continue
        if choice == "3":
            _run_station_menu("eit_agv.main", "AGV 工站")
            continue
        if choice == "4":
            _run_station_menu("eit_chemical_manager.main", "化学品库")
            continue

        print("无效选择, 请重新输入")


if __name__ == "__main__":
    interactive()
