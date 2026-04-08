#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    提供 AGV 工站交互式命令行入口, 将 controller 中的测试菜单独立到 main.py.
参数:
    无.
返回:
    无.
"""

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import yaml

from .config.agv_config import (
    STATION_POSITIONS,
    AGV_PP5_CP6_AUTO_CHARGE_INTERVAL_MINUTES,
    AGV_PP5_CP6_AUTO_CHARGE_LOW_BATTERY_PCT,
)
from .controller.agv_controller import AGVController
from .utils.position_manager import PositionManager

logger = logging.getLogger("AGVInteractiveCLI")


def _configure_logging() -> None:
    """
    功能:
        配置 AGV 交互入口的控制台日志格式.
    参数:
        无.
    返回:
        无.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def _report_exception(exc: Exception) -> None:
    """
    功能:
        统一记录交互过程中的异常并输出中文提示.
    参数:
        exc: 捕获到的异常对象.
    返回:
        无.
    """
    logger.exception("AGV交互操作失败")
    print(f"错误: {exc}")


def _query_current_station_display(
    controller: AGVController,
    *,
    announce: bool = False,
) -> str:
    """
    功能:
        查询当前站点并格式化成菜单展示文本.
    参数:
        controller: AGVController 实例.
        announce: 是否先打印查询提示.
    返回:
        str, 用于菜单展示的当前站点文本.
    """
    if announce is True:
        print("\n正在查询当前站点...")

    station_info = controller.query_current_station()
    if station_info is None:
        if announce is True:
            print("查询站点失败")
        return "未知"

    current_station_display = (
        f"{station_info['station_id']} - "
        f"{station_info['station_name']} "
        f"({station_info['description']})"
    )
    if announce is True:
        print(f"当前站点: {current_station_display}")
    return current_station_display


def _print_top_menu(current_station_display: str) -> None:
    """
    功能:
        打印 AGV 顶层交互菜单.
    参数:
        current_station_display: 当前站点展示文本.
    返回:
        无.
    """
    print("\n" + "=" * 60)
    print(f"当前站点: {current_station_display}")
    print("=" * 60)
    print("请选择要测试的功能:")
    print("1. 连接机械臂")
    print("2. 断开机械臂连接")
    print("3. 机械臂回零")
    print("4. 查看当前状态")
    print("5. 上电并使能")
    print("6. 下使能并下电")
    print("7. 测试取托盘")
    print("8. 测试放托盘")
    print("9. 测试快换控制")
    print("10. 测试夹爪控制")
    print("11. 查看夹爪状态")
    print("12. 查看料盘状态")
    print("13. 重新加载点位配置")
    print("14. 工站点位校准")
    print("15. 查看校准偏移值")
    print("16. AGV移动到工站")
    print("17. 查询当前站点")
    print("18. 运动到抓取点位")
    print("19. 物料适配转移")
    print("20. 更换夹爪")
    print("21. 查看物料/夹爪配置")
    print("22. 批量物料转运(含AGV移动和校准)")
    print("23. 托盘点位校准")
    print("24. 全点位测试")
    print("25. 工站整体偏差矫正")
    print("26. 查询电池电量")
    print("27. 自动充电检查(单次)")
    print("28. 启动自动充电循环")
    print("29. 批量物料转运循环测试")
    print("30. 分析站→货架样品转运")
    print("31. 查看/管理货架状态")
    print("32. PP5/CP6自动充电检查(单次)")
    print("33. 启动PP5/CP6自动充电循环")
    print("34. 工站中间托盘点位自动计算")
    print("0. 退出程序")
    print("=" * 60)


def _prompt_index_choice(prompt: str, option_count: int) -> Optional[int]:
    """
    功能:
        读取 1 基编号输入并转换为 0 基索引.
    参数:
        prompt: 输入提示文本.
        option_count: 允许选择的最大数量.
    返回:
        Optional[int], 成功时返回索引, 失败时返回 None.
    """
    choice_input = input(prompt).strip()
    if choice_input.isdigit() is False:
        print("错误: 请输入有效的数字")
        return None

    index = int(choice_input) - 1
    if index < 0 or index >= option_count:
        print(f"错误: 请输入1到{option_count}之间的数字")
        return None

    return index


def _get_filtered_tray_context(
    controller: AGVController,
) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    """
    功能:
        按当前站点筛选当前可用的托盘位置, 同时保留 AGV 自身托盘位置.
    参数:
        controller: AGVController 实例.
    返回:
        Tuple[Dict[str, Dict[str, Any]], List[str]], 托盘配置映射与筛选后的托盘名称列表.
    """
    tray_positions = controller.position_manager.get_category("tray_position")
    if not tray_positions:
        raise ValueError("未找到托盘位置配置")

    filtered_tray_list: List[str] = []
    if controller.current_station is not None and controller.current_station in STATION_POSITIONS:
        station_name = STATION_POSITIONS[controller.current_station]["name"]
        for tray_name in tray_positions.keys():
            # 同时保留当前站点托盘与 AGV 托盘, 方便做站内转运.
            if tray_name.startswith(station_name) or tray_name.startswith("agv"):
                filtered_tray_list.append(tray_name)
    else:
        for tray_name in tray_positions.keys():
            if tray_name.startswith("agv"):
                filtered_tray_list.append(tray_name)

    if len(filtered_tray_list) == 0:
        raise ValueError("当前站点没有可用的托盘位置")

    return tray_positions, filtered_tray_list


def _get_current_station_target_tray_context(
    controller: AGVController,
) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    """
    功能:
        获取当前工站下可用于带托盘校准的目标点位列表, 只保留当前工站的非AGV托盘点位.

    参数:
        controller: AGVController 实例.

    返回:
        Tuple[Dict[str, Dict[str, Any]], List[str]], 托盘配置映射与目标点位列表.
    """
    tray_positions = controller.position_manager.get_category("tray_position")
    if not tray_positions:
        raise ValueError("未找到托盘位置配置")

    if controller.current_station is None or controller.current_station not in STATION_POSITIONS:
        raise ValueError("当前工站不可用")

    station_name = STATION_POSITIONS[controller.current_station]["name"]
    target_tray_list: List[str] = []
    for tray_name in tray_positions.keys():
        if tray_name.startswith(station_name):
            target_tray_list.append(tray_name)

    if len(target_tray_list) == 0:
        raise ValueError("当前工站没有可校准的目标点位")

    return tray_positions, target_tray_list


def _extract_middle_tray_station_name(tray_name: str) -> Optional[str]:
    """
    功能:
        从工站托盘点位名称中提取工站名称.

    参数:
        tray_name: 托盘点位名称.

    返回:
        Optional[str], 成功时返回工站名称, 失败时返回None.
    """
    tray_marker = "_tray_"
    if tray_marker not in tray_name:
        return None

    station_name, index_text = tray_name.split(tray_marker, 1)
    if index_text.count("-") != 1:
        return None

    row_text, col_text = index_text.split("-", 1)
    if row_text.isdigit() is False or col_text.isdigit() is False:
        return None

    return station_name


def _get_middle_tray_station_preview_context(
    controller: AGVController,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    功能:
        获取所有可自动计算中间托盘点位的工站预览结果.

    参数:
        controller: AGVController 实例.

    返回:
        Dict[str, List[Dict[str, Any]]], 键为工站名称, 值为对应预览列表.
    """
    tray_positions = controller.position_manager.get_category("tray_position")
    if tray_positions is None or len(tray_positions) == 0:
        raise ValueError("未找到托盘位置配置")

    station_preview_map: Dict[str, List[Dict[str, Any]]] = {}
    seen_station_names = set()

    for tray_name in sorted(tray_positions.keys()):
        station_name = _extract_middle_tray_station_name(tray_name)
        if station_name is None:
            continue
        if station_name in seen_station_names:
            continue

        seen_station_names.add(station_name)
        preview_items = controller.preview_station_middle_tray_updates(station_name)
        if len(preview_items) > 0:
            station_preview_map[station_name] = preview_items

    if len(station_preview_map) == 0:
        raise ValueError("当前没有可自动计算中间托盘点位的工站")

    return station_preview_map


def _print_middle_tray_update_preview(preview_items: List[Dict[str, Any]]) -> None:
    """
    功能:
        按排展示工站中间托盘点位自动计算预览.

    参数:
        preview_items: 预览结果列表.

    返回:
        无.
    """
    current_row_index = None

    for preview_item in preview_items:
        row_index = preview_item["row_index"]
        if row_index != current_row_index:
            current_row_index = row_index
            print(f"\n第{row_index}排, 端点范围: {preview_item['left_tray']} -> {preview_item['right_tray']}")

        action_text = "更新" if preview_item["exists"] is True else "新增"
        old_pose = preview_item["old_pose"]
        old_pose_text = old_pose if old_pose is not None else "无"
        print(
            f"  - {preview_item['target_tray']} [{action_text}], "
            f"比例={preview_item['ratio']:.3f}"
        )
        print(f"      原位姿: {old_pose_text}")
        print(f"      新位姿: {preview_item['new_pose']}")


def _print_tray_list(
    tray_positions: Dict[str, Dict[str, Any]],
    tray_list: List[str],
    *,
    title: str = "可用的托盘位置:",
) -> None:
    """
    功能:
        按统一格式打印托盘列表.
    参数:
        tray_positions: 托盘配置映射.
        tray_list: 需要展示的托盘名称列表.
        title: 列表标题.
    返回:
        无.
    """
    print(title)
    for idx, tray_name in enumerate(tray_list, 1):
        tray_config = tray_positions[tray_name]
        description = tray_config.get("description", "无描述")
        print(f"  {idx}. {tray_name} - {description}")


def _handle_quick_change_menu(controller: AGVController) -> None:
    """
    功能:
        处理快换控制子菜单.
    参数:
        controller: AGVController 实例.
    返回:
        无.
    """
    print("\n--- 测试快换控制 ---")
    print("1. 松开快换")
    print("2. 夹紧快换")
    sub_choice = input("请选择操作 (1-2): ").strip()

    if controller._ensure_connected() is False:
        print("机械臂未连接")
        return

    if sub_choice == "1":
        print("正在松开快换...")
        result = controller.arm.release_quick_change(block=True)
        print(f"松开快换结果: {result}")
        return

    if sub_choice == "2":
        print("正在夹紧快换...")
        result = controller.arm.lock_quick_change(block=True)
        print(f"夹紧快换结果: {result}")
        return

    print("无效的选项")


def _handle_gripper_menu(controller: AGVController) -> None:
    """
    功能:
        处理夹爪控制子菜单.
    参数:
        controller: AGVController 实例.
    返回:
        无.
    """
    print("\n--- 测试夹爪控制 ---")
    print("1. 张开夹爪")
    print("2. 闭合夹爪")
    sub_choice = input("请选择操作 (1-2): ").strip()

    if controller._ensure_connected() is False:
        print("机械臂未连接")
        return

    if sub_choice == "1":
        print("正在张开夹爪...")
        result = controller.arm.open_gripper(block=True)
        print(f"张开夹爪结果: {result}")
        time.sleep(1)
        if controller.arm.is_gripper_opened():
            print("夹爪已张开到位")
        else:
            print("警告: 夹爪未张开到位")
        return

    if sub_choice == "2":
        print("正在闭合夹爪...")
        result = controller.arm.close_gripper(block=True)
        print(f"闭合夹爪结果: {result}")
        time.sleep(1)
        if controller.arm.is_gripper_gripped():
            print("夹爪已夹紧到位(夹到物料)")
        elif controller.arm.is_gripper_empty():
            print("夹爪空夹(未夹到物料)")
        else:
            print("警告: 夹爪状态未知")
        return

    print("无效的选项")


def _handle_slot_status_menu(controller: AGVController) -> None:
    """
    功能:
        处理料盘状态查询子菜单.
    参数:
        controller: AGVController 实例.
    返回:
        无.
    """
    print("\n--- 料盘状态 ---")
    print("1. 查看所有料位状态")
    print("2. 查看指定快换料位")
    print("3. 查看指定托盘料位")
    sub_choice = input("请选择操作 (1-3): ").strip()

    if controller._ensure_connected() is False:
        print("机械臂未连接")
        return

    if sub_choice == "1":
        status = controller.arm.get_all_slots_status()
        print("\n快换料位状态 (bg1-bg3):")
        for idx, has_material in enumerate(status["quick_change"], 1):
            print(f"  bg{idx}: {'有料' if has_material else '无料'}")
        print("\n托盘料位状态 (bg4-bg7):")
        for idx, has_material in enumerate(status["tray"], 4):
            print(f"  bg{idx}: {'有料' if has_material else '无料'}")
        return

    if sub_choice == "2":
        slot_num_input = input("请输入快换料位编号 (1-3): ").strip()
        if slot_num_input.isdigit() is False:
            print("错误: 请输入有效的数字")
            return
        slot_num = int(slot_num_input)
        has_material = controller.arm.check_quick_change_slot(slot_num)
        print(f"快换料位bg{slot_num}: {'有料' if has_material else '无料'}")
        return

    if sub_choice == "3":
        slot_num_input = input("请输入托盘料位编号 (1-4, 对应bg4-bg7): ").strip()
        if slot_num_input.isdigit() is False:
            print("错误: 请输入有效的数字")
            return
        slot_num = int(slot_num_input)
        has_material = controller.arm.check_tray_slot(slot_num)
        print(f"托盘料位bg{slot_num + 3}: {'有料' if has_material else '无料'}")
        return

    print("无效的选项")


def _build_transfer_tasks(
    controller: AGVController,
    task_count: int,
    *,
    pair_text: str,
) -> Optional[List[Dict[str, Optional[str]]]]:
    """
    功能:
        交互式构建批量转运任务列表.
    参数:
        controller: AGVController 实例.
        task_count: 需要配置的任务数量.
        pair_text: 摘要展示时使用的箭头文本.
    返回:
        Optional[List[Dict[str, Optional[str]]]], 成功返回任务列表, 取消或失败返回 None.
    """
    tray_positions = controller.position_manager.get_category("tray_position")
    if not tray_positions:
        print("错误: 未找到托盘位置配置")
        return None

    materials = controller.position_manager.list_materials()
    tray_list = list(tray_positions.keys())
    transfer_tasks: List[Dict[str, Optional[str]]] = []

    for task_index in range(task_count):
        print(f"\n{'=' * 60}")
        print(f"配置任务 {task_index + 1}/{task_count}")
        print(f"{'=' * 60}")
        _print_tray_list(tray_positions, tray_list)

        source_index = _prompt_index_choice(
            f"\n请选择源托盘位置 (1-{len(tray_list)}): ",
            len(tray_list),
        )
        if source_index is None:
            return None
        source_tray = tray_list[source_index]

        target_index = _prompt_index_choice(
            f"请选择目标托盘位置 (1-{len(tray_list)}): ",
            len(tray_list),
        )
        if target_index is None:
            return None
        target_tray = tray_list[target_index]

        selected_material: Optional[str] = None
        if materials:
            print("\n可用的物料类型:")
            for idx, material_name in enumerate(materials, 1):
                material = controller.position_manager.get_material(material_name)
                print(
                    f"  {idx}. {material_name} - "
                    f"{material.description} (夹爪: {material.gripper})"
                )

            material_choice = input(
                f"请选择物料类型 (1-{len(materials)}, 直接回车跳过): "
            ).strip()
            if material_choice != "":
                if material_choice.isdigit() is False:
                    print("错误: 请输入有效的数字")
                    return None
                material_index = int(material_choice) - 1
                if material_index < 0 or material_index >= len(materials):
                    print(f"错误: 请输入1到{len(materials)}之间的数字")
                    return None
                selected_material = materials[material_index]

        task = {
            "source_tray": source_tray,
            "target_tray": target_tray,
            "material_type": selected_material,
        }
        transfer_tasks.append(task)

        print(f"\n任务{task_index + 1}已配置: {source_tray} {pair_text} {target_tray}")
        if selected_material:
            print(f"  物料类型: {selected_material}")

    return transfer_tasks


def _print_transfer_task_summary(
    transfer_tasks: List[Dict[str, Optional[str]]],
    *,
    title: str,
    pair_text: str,
) -> None:
    """
    功能:
        打印批量转运任务摘要.
    参数:
        transfer_tasks: 任务列表.
        title: 摘要标题.
        pair_text: 摘要展示时使用的箭头文本.
    返回:
        无.
    """
    print(f"\n{'=' * 60}")
    print(title)
    print(f"{'=' * 60}")
    for idx, task in enumerate(transfer_tasks, 1):
        print(f"任务{idx}: {task['source_tray']} {pair_text} {task['target_tray']}")
        if task["material_type"]:
            print(f"       物料类型: {task['material_type']}")


def _handle_shelf_management_menu(controller: AGVController) -> None:
    """
    功能:
        处理货架状态查看与管理子菜单.
    参数:
        controller: AGVController 实例.
    返回:
        无.
    """
    print("\n--- 查看/管理货架状态 ---")

    while True:
        print("\n  1. 查看当前状态")
        print("  2. 手动清除槽位")
        print("  3. 重置全部槽位")
        print("  0. 返回上级菜单")

        sub_choice = input("请选择操作: ").strip()

        if sub_choice == "0":
            return

        if sub_choice == "1":
            controller.shelf_manager.print_status()
            continue

        if sub_choice == "2":
            controller.shelf_manager.print_status()
            status = controller.shelf_manager.get_all_status()
            occupied = [
                slot_name
                for slot_name in status["slots"]
                if status["slots"][slot_name] is not None
            ]

            if len(occupied) == 0:
                print("所有槽位均为空, 无需清除")
                continue

            print("\n有物料的槽位:")
            for idx, slot_name in enumerate(occupied, 1):
                slot_info = status["slots"][slot_name]
                print(f"  {idx}. {slot_name} - {slot_info.get('material_type', '未知')}")

            slot_index = _prompt_index_choice(
                f"请选择要清除的槽位 (1-{len(occupied)}): ",
                len(occupied),
            )
            if slot_index is None:
                continue

            slot_name = occupied[slot_index]
            confirm = input(f"确认清除槽位 {slot_name}? (y/n): ").strip().lower()
            if confirm == "y":
                result = controller.shelf_manager.remove_material(slot_name)
                print(f"清除结果: {'成功' if result else '失败'}")
            else:
                print("已取消")
            continue

        if sub_choice == "3":
            confirm = input("确认重置全部槽位? 此操作不可恢复 (y/n): ").strip().lower()
            if confirm == "y":
                controller.shelf_manager.reset_all()
                print("已重置全部槽位")
            else:
                print("已取消")
            continue

        print("无效选择")


def _handle_choice_1_to_12(
    controller: AGVController,
    choice: str,
) -> bool:
    """
    功能:
        处理 1-12 的基础连接, 状态查询和托盘测试菜单动作.
    参数:
        controller: AGVController 实例.
        choice: 顶层菜单选项.
    返回:
        bool, True 表示已处理, False 表示交给其他分组处理.
    """
    if choice == "1":
        print("\n--- 连接机械臂 ---")
        result = controller.connect()
        print(f"连接结果: {'成功' if result else '失败'}")
        return True

    if choice == "2":
        print("\n--- 断开机械臂连接 ---")
        result = controller.disconnect()
        print(f"断开结果: {'成功' if result else '失败'}")
        return True

    if choice == "3":
        print("\n--- 机械臂回零 ---")
        try:
            controller.position_manager.reload()
            logger.info("点位配置已重新加载")
            result = controller.arm_go_home(block=True)
            print(f"回零结果: {result}")
        except Exception as exc:
            _report_exception(exc)
        return True

    if choice == "4":
        print("\n--- 当前状态 ---")
        try:
            if controller._ensure_connected() is False:
                print("机械臂未连接")
                return True

            state = controller.arm.get_robot_state()
            print(f"机器人状态: {state}")

            joints = controller.arm.get_joints_position()
            print(f"当前关节角度: {joints}")

            pose = controller.arm.get_tcp_pose()
            print(f"当前TCP位姿: {pose}")

            if controller.current_station is not None:
                print(f"当前所在工站: {controller.current_station}")
                if controller.current_station in STATION_POSITIONS:
                    station_info = STATION_POSITIONS[controller.current_station]
                    station_name = station_info["name"]
                    offset = controller.position_manager.get_calibration_offset(station_name)
                    if offset is not None:
                        original_pose = [
                            pose[0] - offset["x"],
                            pose[1] - offset["y"],
                            pose[2] - offset["z"],
                            pose[3] - offset["dx"],
                            pose[4] - offset["dy"],
                            pose[5] - offset["dz"],
                        ]
                        print(f"原始TCP姿态(用于新点位存储): {original_pose}")
                    else:
                        print(f"工站 {station_name} 尚未校准, 无法计算原始TCP姿态")
            else:
                print("当前所在工站: 未设置")

            is_moving = controller.arm.is_moving()
            print(f"是否在运动: {is_moving}")
        except Exception as exc:
            _report_exception(exc)
        return True

    if choice == "5":
        print("\n--- 上电并使能 ---")
        try:
            if controller._ensure_connected() is False:
                print("机械臂连接失败")
                return True

            print("正在上电...")
            result = controller.arm.power_on(block=True)
            print(f"上电结果: {result}")

            print("正在使能...")
            result = controller.arm.enable(block=True)
            print(f"使能结果: {result}")
        except Exception as exc:
            _report_exception(exc)
        return True

    if choice == "6":
        print("\n--- 下使能并下电 ---")
        try:
            if controller._ensure_connected() is False:
                print("机械臂未连接")
                return True

            print("正在下使能...")
            result = controller.arm.disable(block=True)
            print(f"下使能结果: {result}")

            print("正在下电...")
            result = controller.arm.power_off(block=True)
            print(f"下电结果: {result}")
        except Exception as exc:
            _report_exception(exc)
        return True

    if choice == "7":
        print("\n--- 测试取托盘 ---")
        try:
            tray_positions, tray_list = _get_filtered_tray_context(controller)
            _print_tray_list(tray_positions, tray_list)
            tray_index = _prompt_index_choice(
                f"请输入托盘编号 (1-{len(tray_list)}): ",
                len(tray_list),
            )
            if tray_index is None:
                return True

            selected_tray = tray_list[tray_index]
            controller.position_manager.reload()
            logger.info("点位配置已重新加载")
            print(f"\n开始执行取托盘流程: {selected_tray}")
            result = controller.pick_tray(selected_tray, block=True)
            print(f"取托盘结果: {'成功' if result else '失败'}")
        except Exception as exc:
            _report_exception(exc)
        return True

    if choice == "8":
        print("\n--- 测试放托盘 ---")
        try:
            tray_positions, tray_list = _get_filtered_tray_context(controller)
            _print_tray_list(tray_positions, tray_list)
            tray_index = _prompt_index_choice(
                f"请输入托盘编号 (1-{len(tray_list)}): ",
                len(tray_list),
            )
            if tray_index is None:
                return True

            selected_tray = tray_list[tray_index]
            controller.position_manager.reload()
            logger.info("点位配置已重新加载")
            print(f"\n开始执行放托盘流程: {selected_tray}")
            result = controller.put_tray(selected_tray, block=True)
            print(f"放托盘结果: {'成功' if result else '失败'}")
        except Exception as exc:
            _report_exception(exc)
        return True

    if choice == "9":
        try:
            _handle_quick_change_menu(controller)
        except Exception as exc:
            _report_exception(exc)
        return True

    if choice == "10":
        try:
            _handle_gripper_menu(controller)
        except Exception as exc:
            _report_exception(exc)
        return True

    if choice == "11":
        print("\n--- 夹爪状态 ---")
        try:
            if controller._ensure_connected() is False:
                print("机械臂未连接")
                return True

            state = controller.arm.get_gripper_state()
            print(f"夹爪状态: {state}")

            is_opened = controller.arm.is_gripper_opened()
            print(f"是否张开到位: {is_opened}")

            is_gripped = controller.arm.is_gripper_gripped()
            print(f"是否夹紧到位(有物料): {is_gripped}")
        except Exception as exc:
            _report_exception(exc)
        return True

    if choice == "12":
        try:
            _handle_slot_status_menu(controller)
        except Exception as exc:
            _report_exception(exc)
        return True

    return False


def _handle_choice_13_to_24(
    controller: AGVController,
    choice: str,
    current_station_display: str,
) -> Tuple[bool, str]:
    """
    功能:
        处理 13-24 与 34-35 的点位, 导航, 转运和测试相关菜单动作.
    参数:
        controller: AGVController 实例.
        choice: 顶层菜单选项.
        current_station_display: 当前站点展示文本.
    返回:
        Tuple[bool, str], 是否已处理及最新站点展示文本.
    """
    if choice == "13":
        print("\n--- 重新加载点位配置 ---")
        try:
            controller.position_manager = PositionManager()
            print("点位配置已重新加载")

            print("\n已加载的配置类别:")
            for category in ["safe_positions", "tray_position"]:
                positions = controller.position_manager.get_category(category)
                if positions:
                    print(f"\n{category}:")
                    for name in positions.keys():
                        print(f"  - {name}")
                else:
                    print(f"\n{category}: 无配置")
        except Exception as exc:
            _report_exception(exc)
        return True, current_station_display

    if choice == "14":
        print("\n--- 工站点位校准 ---")
        print("说明: 将自动查询当前站点并执行校准")
        print("支持的工站: shelf(货架), synthesis_station(合成站), analysis_station(分析站)")
        print(f"当前站点: {current_station_display}")
        try:
            print("\n警告: 校准程序将运行机械臂, 请确保周围安全!")
            print("提示: 请确保AGV已移动到需要校准的工站")
            confirm = input("确认执行校准? (y/n): ").strip().lower()
            if confirm != "y":
                print("已取消校准")
                return True, current_station_display

            controller.position_manager.reload()
            logger.info("点位配置已重新加载")
            result = controller.calibrate_station(block=True)
            if result is not None:
                print("\n校准成功! 偏移值:")
                print(
                    f"  位置偏移: x={result['x']:.6f}, "
                    f"y={result['y']:.6f}, z={result['z']:.6f}"
                )
                print(
                    f"  姿态偏移: dx={result['dx']:.6f}, "
                    f"dy={result['dy']:.6f}, dz={result['dz']:.6f}"
                )
                print("偏移值已保存到配置文件")
            else:
                print("校准失败")
        except Exception as exc:
            _report_exception(exc)
        return True, current_station_display

    if choice == "15":
        print("\n--- 查看校准偏移值 ---")
        print("支持的工站:")
        print("1. shelf (货架)")
        print("2. synthesis_station (合成站)")
        print("3. analysis_station (分析站)")
        print("4. 查看所有工站")

        station_choice = input("请选择工站 (1-4): ").strip()
        try:
            if station_choice == "4":
                print("\n所有工站校准偏移值:")
                for station_name in ["shelf", "synthesis_station", "analysis_station"]:
                    offset = controller.position_manager.get_calibration_offset(station_name)
                    if offset is not None:
                        print(f"\n{station_name}:")
                        print(
                            f"  位置偏移: x={offset['x']:.6f}, "
                            f"y={offset['y']:.6f}, z={offset['z']:.6f}"
                        )
                        print(
                            f"  姿态偏移: dx={offset['dx']:.6f}, "
                            f"dy={offset['dy']:.6f}, dz={offset['dz']:.6f}"
                        )
                    else:
                        print(f"\n{station_name}: 未校准")
            else:
                station_map = {
                    "1": "shelf",
                    "2": "synthesis_station",
                    "3": "analysis_station",
                }
                if station_choice not in station_map:
                    print("错误: 无效的工站选择")
                    return True, current_station_display

                station_name = station_map[station_choice]
                offset = controller.position_manager.get_calibration_offset(station_name)
                if offset is not None:
                    print(f"\n{station_name} 工站校准偏移值:")
                    print(
                        f"  位置偏移: x={offset['x']:.6f}, "
                        f"y={offset['y']:.6f}, z={offset['z']:.6f}"
                    )
                    print(
                        f"  姿态偏移: dx={offset['dx']:.6f}, "
                        f"dy={offset['dy']:.6f}, dz={offset['dz']:.6f}"
                    )
                else:
                    print(f"{station_name} 工站尚未校准")
        except Exception as exc:
            _report_exception(exc)
        return True, current_station_display

    if choice == "16":
        print("\n--- AGV移动到工站 ---")
        try:
            print("可用的工站:")
            station_list = list(STATION_POSITIONS.keys())
            for idx, station_id in enumerate(station_list, 1):
                station_info = STATION_POSITIONS[station_id]
                print(f"  {idx}. {station_id} - {station_info['description']}")

            station_index = _prompt_index_choice(
                f"请输入工站编号 (1-{len(station_list)}): ",
                len(station_list),
            )
            if station_index is None:
                return True, current_station_display

            selected_station = station_list[station_index]
            station_info = STATION_POSITIONS[selected_station]
            print(f"\n开始移动到工站: {selected_station} ({station_info['description']})")

            result = controller.safe_navigate_to_station(selected_station)
            if result is not None:
                print("导航指令发送成功")
                print(f"响应信息: {result}")
                print(f"当前工站已设置为: {selected_station}")
                current_station_display = (
                    f"{selected_station} - {station_info['name']} "
                    f"({station_info['description']})"
                )
            else:
                print("导航失败, 请查看日志获取详细信息")
        except Exception as exc:
            _report_exception(exc)
        return True, current_station_display

    if choice == "17":
        print("\n--- 查询当前站点 ---")
        try:
            station_info = controller.query_current_station()
            if station_info is not None:
                print(f"站点ID: {station_info['station_id']}")
                print(f"站点名称: {station_info['station_name']}")
                print(f"站点描述: {station_info['description']}")
                current_station_display = (
                    f"{station_info['station_id']} - {station_info['station_name']} "
                    f"({station_info['description']})"
                )
            else:
                print("查询站点失败")
        except Exception as exc:
            _report_exception(exc)
        return True, current_station_display

    if choice == "18":
        print("\n--- 显示当前站点和AGV上的位置 ---")
        try:
            tray_positions, tray_list = _get_filtered_tray_context(controller)
            _print_tray_list(
                tray_positions,
                tray_list,
                title="\n当前站点和AGV上的托盘位置:",
            )
            tray_index = _prompt_index_choice(
                f"请输入托盘编号 (1-{len(tray_list)}): ",
                len(tray_list),
            )
            if tray_index is None:
                return True, current_station_display

            selected_tray = tray_list[tray_index]
            controller.position_manager.reload()
            logger.info("点位配置已重新加载")
            print(f"\n开始执行运动到抓取点位流程: {selected_tray}")
            result = controller.move_to_grasp_position(selected_tray, block=True)
            print(f"运动到抓取点位结果: {'成功' if result else '失败'}")
        except Exception as exc:
            _report_exception(exc)
        return True, current_station_display

    if choice == "19":
        print("\n--- 物料适配转移 ---")
        try:
            materials = controller.position_manager.list_materials()
            if not materials:
                print("错误: 未找到物料类型配置")
                return True, current_station_display

            print("可用的物料类型:")
            for idx, material_name in enumerate(materials, 1):
                material = controller.position_manager.get_material(material_name)
                print(
                    f"  {idx}. {material_name} - "
                    f"{material.description} (夹爪: {material.gripper})"
                )

            material_choice = input(
                f"请选择物料类型 (1-{len(materials)}, 直接回车跳过): "
            ).strip()
            selected_material = None
            if material_choice != "":
                if material_choice.isdigit() is False:
                    print("错误: 请输入有效的数字")
                    return True, current_station_display
                material_index = int(material_choice) - 1
                if material_index < 0 or material_index >= len(materials):
                    print(f"错误: 请输入1到{len(materials)}之间的数字")
                    return True, current_station_display
                selected_material = materials[material_index]

            tray_positions, tray_list = _get_filtered_tray_context(controller)
            _print_tray_list(tray_positions, tray_list, title="\n可用的托盘位置:")

            source_index = _prompt_index_choice(
                f"请选择源托盘 (1-{len(tray_list)}): ",
                len(tray_list),
            )
            if source_index is None:
                return True, current_station_display
            source_tray = tray_list[source_index]

            target_index = _prompt_index_choice(
                f"请选择目标托盘 (1-{len(tray_list)}): ",
                len(tray_list),
            )
            if target_index is None:
                return True, current_station_display
            target_tray = tray_list[target_index]

            print(f"\n开始物料转移: {source_tray} -> {target_tray}")
            if selected_material is not None:
                print(f"物料类型: {selected_material}")
            controller.position_manager.reload()
            logger.info("点位配置已重新加载")
            result = controller.transfer_material(
                source_tray,
                target_tray,
                selected_material,
                block=True,
            )
            print(f"物料转移结果: {'成功' if result else '失败'}")
        except Exception as exc:
            _report_exception(exc)
        return True, current_station_display

    if choice == "20":
        print("\n--- 更换夹爪 ---")
        try:
            current_gripper = controller.get_current_gripper()
            print(f"当前夹爪: {current_gripper if current_gripper else '无'}")

            grippers = controller.position_manager.list_grippers()
            if not grippers:
                print("错误: 未找到夹爪配置")
                return True, current_station_display

            print("\n可用的夹爪:")
            for idx, gripper_name in enumerate(grippers, 1):
                gripper = controller.position_manager.get_gripper(gripper_name)
                print(f"  {idx}. {gripper_name} - {gripper.description} (料位: {gripper.slot})")

            gripper_index = _prompt_index_choice(
                f"请选择目标夹爪 (1-{len(grippers)}): ",
                len(grippers),
            )
            if gripper_index is None:
                return True, current_station_display

            target_gripper = grippers[gripper_index]
            print(f"\n将更换夹爪: {current_gripper if current_gripper else '无'} -> {target_gripper}")
            confirm = input("确认执行? (y/n): ").strip().lower()
            if confirm != "y":
                print("已取消")
                return True, current_station_display

            controller.position_manager.reload()
            logger.info("点位配置已重新加载")
            result = controller.change_gripper(target_gripper, block=True)
            print(f"更换夹爪结果: {'成功' if result else '失败'}")
        except Exception as exc:
            _report_exception(exc)
        return True, current_station_display

    if choice == "21":
        print("\n--- 物料/夹爪配置 ---")
        try:
            grippers = controller.position_manager.list_grippers()
            print("\n夹爪配置:")
            if grippers:
                for gripper_name in grippers:
                    gripper = controller.position_manager.get_gripper(gripper_name)
                    print(f"  - {gripper_name}: {gripper.description} (料位: {gripper.slot})")
            else:
                print("  无夹爪配置")

            materials = controller.position_manager.list_materials()
            print("\n物料类型配置:")
            if materials:
                for material_name in materials:
                    material = controller.position_manager.get_material(material_name)
                    print(f"  - {material_name}: {material.description}")
                    print(f"      夹爪: {material.gripper}")
                    print(
                        f"      下探偏移: {material.descend_z_offset}mm, "
                        f"提升偏移: {material.lift_z_offset}mm"
                    )
            else:
                print("  无物料类型配置")

            current_gripper = controller.get_current_gripper()
            print(f"\n当前安装的夹爪: {current_gripper if current_gripper else '无'}")
        except Exception as exc:
            _report_exception(exc)
        return True, current_station_display

    if choice == "22":
        print("\n--- 批量物料转运(含AGV移动和校准) ---")
        print("说明: 支持一次转运最多4个物料, AGV会自动移动到各站点并进行点位校准")
        try:
            task_count_input = input("请输入要转运的物料数量 (1-4): ").strip()
            if task_count_input.isdigit() is False:
                print("错误: 请输入有效的数字")
                return True, current_station_display

            task_count = int(task_count_input)
            if task_count < 1 or task_count > 4:
                print("错误: 任务数量必须在1-4之间")
                return True, current_station_display

            transfer_tasks = _build_transfer_tasks(controller, task_count, pair_text="->")
            if transfer_tasks is None:
                print("\n任务配置未完成, 已取消")
                return True, current_station_display

            _print_transfer_task_summary(
                transfer_tasks,
                title="任务摘要:",
                pair_text="->",
            )
            print("\n警告: 此操作将控制AGV移动并执行物料转运, 请确保周围安全!")
            confirm = input("确认执行批量转运? (y/n): ").strip().lower()
            if confirm != "y":
                print("已取消")
                return True, current_station_display

            print("\n开始执行批量物料转运...")
            controller.position_manager.reload()
            logger.info("点位配置已重新加载")
            result = controller.batch_transfer_materials(transfer_tasks, block=True)
            if result:
                print(f"\n{'=' * 60}")
                print("批量物料转运成功!")
                print(f"{'=' * 60}")
            else:
                print("\n批量物料转运失败, 请查看日志获取详细信息")
        except Exception as exc:
            _report_exception(exc)
        return True, current_station_display

    if choice == "23":
        print("\n--- 托盘点位校准 ---")
        print("说明: 支持空载校准和带托盘校准")
        print("      空载时, 运动到抓取点位, 手动矫正后确认, 保存当前TCP位姿到配置文件")
        print("      带托盘时, 固定从 agv_tray_1 夹取托盘, 运动到目标点前过渡位后暂停")
        try:
            loaded_confirm = input("是否夹托盘校准? (y/n): ").strip().lower()
            use_loaded_tray = loaded_confirm == "y"

            if use_loaded_tray is True:
                if controller.current_station is None:
                    print("提示: 当前工站未知, 正在查询当前工站...")
                    station_info = controller.query_current_station()
                    if station_info is None:
                        print("错误: 查询当前工站失败, 无法执行带托盘点位校准")
                        return True, current_station_display

                    controller.current_station = station_info["station_id"]
                    current_station_display = (
                        f"{station_info['station_id']} - "
                        f"{station_info['station_name']} "
                        f"({station_info['description']})"
                    )
                    print(f"当前工站: {current_station_display}")

                tray_positions, tray_list = _get_current_station_target_tray_context(controller)
                _print_tray_list(
                    tray_positions,
                    tray_list,
                    title="\n当前工站可校准的目标点位:",
                )
                tray_index = _prompt_index_choice(
                    f"请选择目标点位 (1-{len(tray_list)}): ",
                    len(tray_list),
                )
            else:
                tray_positions, tray_list = _get_filtered_tray_context(controller)
                _print_tray_list(tray_positions, tray_list, title="\n可用的托盘位置:")
                tray_index = _prompt_index_choice(
                    f"请输入托盘编号 (1-{len(tray_list)}): ",
                    len(tray_list),
                )

            if tray_index is None:
                return True, current_station_display

            selected_tray = tray_list[tray_index]
            print(f"\n开始执行托盘点位校准: {selected_tray}")
            if use_loaded_tray is True:
                print("说明: 程序将先从 agv_tray_1 夹取托盘, 再运动到目标点前过渡位")
                print("警告: 机械臂将执行夹取和运动动作, 请确认周围安全")
            else:
                print("警告: 机械臂将运动到抓取点位, 请确保周围安全!")

            confirm = input("确认执行? (y/n): ").strip().lower()
            if confirm != "y":
                print("已取消")
                return True, current_station_display

            controller.position_manager.reload()
            logger.info("点位配置已重新加载")

            if use_loaded_tray is True:
                print("\n步骤1: 从 agv_tray_1 夹取托盘并运动到目标点前过渡位...")
                result = controller.prepare_loaded_tray_calibration(
                    selected_tray,
                    source_tray_name="agv_tray_1",
                    block=True,
                )
                if result is False:
                    print("错误: 人工调整前流程失败, 当前可能仍保持夹持状态, 请人工处理")
                    return True, current_station_display

                print("已到达目标点前过渡位")
                print("\n步骤2: 请通过控制器手动将托盘移动到目标点位")
                print("      调整完成后按回车记录当前点位...")
                input()

                save_succeeded = False
                try:
                    print("\n步骤3: 获取当前TCP位姿...")
                    current_pose = controller.arm.get_tcp_pose()
                    print(f"当前TCP位姿: {current_pose}")

                    pose_to_save = controller.get_calibrated_tray_pose_from_current_pose(
                        selected_tray,
                        current_pose=current_pose,
                    )
                    if pose_to_save is None:
                        print("错误: 计算待保存点位失败")
                    else:
                        original_tray_position = controller.position_manager.get_position(
                            "tray_position",
                            selected_tray,
                        )
                        if original_tray_position is not None and original_tray_position.pose is not None:
                            print(f"\n原先存储的TCP位姿: {original_tray_position.pose}")
                        else:
                            print("\n原先存储的TCP位姿: 无")
                        print(f"将要保存的TCP位姿: {pose_to_save}")

                        save_confirm = input("确认保存到配置文件? (y/n): ").strip().lower()
                        if save_confirm == "y":
                            save_succeeded = controller.save_calibrated_tray_position(
                                selected_tray,
                                pose_to_save,
                            )
                            if save_succeeded:
                                print(f"\n托盘位置 {selected_tray} 已成功保存到配置文件")
                            else:
                                print("错误: 保存配置文件失败")
                        else:
                            print("已取消保存, 将继续执行松爪和收尾动作")
                finally:
                    print("\n步骤4: 松开夹爪并执行收尾动作...")
                    cleanup_result = controller.complete_loaded_tray_calibration(
                        selected_tray,
                        block=True,
                    )
                    if cleanup_result:
                        print("收尾动作完成")
                    else:
                        print("错误: 松爪或回零失败, 请人工处理")

                if save_succeeded:
                    print("带托盘点位校准完成")
                return True, current_station_display

            print("\n步骤1: 运动到抓取点位...")
            result = controller.move_to_grasp_position(selected_tray, block=True)
            if result is False:
                print("运动到抓取点位失败")
                return True, current_station_display

            print("已到达抓取点位")
            print("\n步骤2: 请手动矫正机械臂位置")
            print("提示: 可以使用示教器或其他方式调整机械臂位置")
            print("      矫正完成后, 按回车键继续...")
            input()

            print("\n步骤3: 获取当前TCP位姿...")
            current_pose = controller.arm.get_tcp_pose()
            print(f"当前TCP位姿: {current_pose}")

            if selected_tray.startswith("agv"):
                pose_to_save = current_pose
                print("\nAGV点位, 将直接保存当前TCP位姿")
            else:
                matched_station = None
                with open(controller.position_manager.config_file, "r", encoding="utf-8") as file:
                    config = yaml.safe_load(file)

                if config is not None and "station_calibration" in config:
                    for station_name in config["station_calibration"].keys():
                        if selected_tray.startswith(station_name):
                            matched_station = station_name
                            break

                if matched_station is not None:
                    station_offset = controller.position_manager.get_calibration_offset(matched_station)
                    if station_offset is not None:
                        pose_to_save = [
                            current_pose[0] - station_offset["x"],
                            current_pose[1] - station_offset["y"],
                            current_pose[2] - station_offset["z"],
                            current_pose[3] - station_offset["dx"],
                            current_pose[4] - station_offset["dy"],
                            current_pose[5] - station_offset["dz"],
                        ]
                        print(f"\n非AGV点位, 匹配站点: {matched_station}")
                        print(
                            f"站点偏移量: x={station_offset['x']:.3f}, "
                            f"y={station_offset['y']:.3f}, z={station_offset['z']:.3f}"
                        )
                        print(f"原始TCP位姿(减去偏移量后): {pose_to_save}")
                    else:
                        pose_to_save = current_pose
                        print(f"\n警告: 站点 {matched_station} 未校准, 将直接保存当前TCP位姿")
                else:
                    pose_to_save = current_pose
                    print(f"\n警告: 托盘 {selected_tray} 未匹配到任何站点, 将直接保存当前TCP位姿")

            original_tray_position = controller.position_manager.get_position("tray_position", selected_tray)
            if original_tray_position is not None and original_tray_position.pose is not None:
                print(f"\n原先存储的TCP位姿: {original_tray_position.pose}")
            else:
                print("\n原先存储的TCP位姿: 无")
            print(f"将要保存的TCP位姿: {pose_to_save}")

            save_confirm = input("确认保存到配置文件? (y/n): ").strip().lower()
            if save_confirm != "y":
                print("已取消保存")
                return True, current_station_display

            controller.position_manager.save_tray_position(selected_tray, pose_to_save)
            print(f"\n托盘位置 {selected_tray} 已成功保存到配置文件!")
        except Exception as exc:
            _report_exception(exc)
        return True, current_station_display

    if choice == "24":
        print("\n--- 全点位测试 ---")
        print("说明: 从agv_tray_1取托盘依次放到当前站点的每个点位再取回, 测试所有点位的准确性")
        print("流程: 1.提示用户在agv_tray_1放置托盘 -> 2.选择托盘种类 -> 3.点位校准 -> 4.逐点位测试")
        print(f"当前站点: {current_station_display}")
        try:
            if controller.current_station is None:
                print("\n警告: 未设置当前站点, 请先查询或移动到目标站点")
                query_confirm = input("是否先查询当前站点? (y/n): ").strip().lower()
                if query_confirm == "y":
                    station_info = controller.query_current_station()
                    if station_info is not None:
                        current_station_display = (
                            f"{station_info['station_id']} - {station_info['station_name']} "
                            f"({station_info['description']})"
                        )
                        print(f"当前站点: {current_station_display}")
                    else:
                        print("查询站点失败, 无法继续")
                        return True, current_station_display
                else:
                    print("已取消")
                    return True, current_station_display

            materials = controller.position_manager.list_materials()
            if not materials:
                print("错误: 未找到物料类型配置")
                return True, current_station_display

            print("\n请选择托盘种类:")
            for idx, material_name in enumerate(materials, 1):
                material = controller.position_manager.get_material(material_name)
                print(
                    f"  {idx}. {material_name} - "
                    f"{material.description} (夹爪: {material.gripper})"
                )

            material_index = _prompt_index_choice(
                f"请选择托盘种类 (1-{len(materials)}): ",
                len(materials),
            )
            if material_index is None:
                return True, current_station_display

            selected_material = materials[material_index]
            material_config = controller.position_manager.get_material(selected_material)
            print(f"\n已选择托盘种类: {selected_material} - {material_config.description}")

            tray_positions = controller.position_manager.get_category("tray_position")
            test_positions: List[str] = []
            if controller.current_station is not None and controller.current_station in STATION_POSITIONS:
                station_name = STATION_POSITIONS[controller.current_station]["name"]
                for tray_name in tray_positions.keys():
                    if tray_name.startswith(station_name):
                        test_positions.append(tray_name)

            if len(test_positions) == 0:
                print("错误: 当前站点没有可测试的点位")
                return True, current_station_display

            print(f"\n待测试点位 ({len(test_positions)} 个):")
            for idx, position_name in enumerate(test_positions, 1):
                tray_config = tray_positions[position_name]
                description = tray_config.get("description", "无描述")
                print(f"  {idx}. {position_name} - {description}")

            print("\n" + "=" * 60)
            print("请在 agv_tray_1 位置放置托盘!")
            print("=" * 60)
            print(f"托盘种类: {selected_material} - {material_config.description}")
            print("\n警告: 此操作将控制机械臂进行全点位测试, 请确保周围安全!")
            confirm = input("托盘已放置好, 确认开始测试? (y/n): ").strip().lower()
            if confirm != "y":
                print("已取消")
                return True, current_station_display

            print("\n开始执行全点位测试...")
            controller.position_manager.reload()
            logger.info("点位配置已重新加载")
            results = controller.test_all_positions(selected_material, block=True)
            print("\n" + "=" * 60)
            print("全点位测试结果汇总")
            print("=" * 60)
            print(f"成功: {len(results['success'])} 个点位")
            for position_name in results["success"]:
                print(f"  [OK] {position_name}")
            print(f"失败: {len(results['failed'])} 个点位")
            for position_name in results["failed"]:
                print(f"  [FAIL] {position_name}")
            print(f"跳过: {len(results['skipped'])} 个点位")
            for position_name in results["skipped"]:
                print(f"  [SKIP] {position_name}")

            total_count = (
                len(results["success"])
                + len(results["failed"])
                + len(results["skipped"])
            )
            if total_count > 0:
                success_rate = len(results["success"]) / total_count * 100
                print(f"\n测试通过率: {success_rate:.1f}%")
        except Exception as exc:
            _report_exception(exc)
        return True, current_station_display

    if choice == "34":
        print("\n--- 工站中间托盘点位自动计算 ---")
        print("说明: 按每一排现有最左和最右编号自动等分中间托盘点位")
        print("说明: 已有中间点位会重算覆盖, 缺失点位会自动新增")
        try:
            controller.position_manager.reload()
            logger.info("点位配置已重新加载")

            station_preview_map = _get_middle_tray_station_preview_context(controller)
            station_list = sorted(station_preview_map.keys())

            print("\n可自动计算的工站:")
            for idx, station_name in enumerate(station_list, 1):
                preview_items = station_preview_map[station_name]
                row_count = len({item["row_index"] for item in preview_items})
                print(
                    f"  {idx}. {station_name} - "
                    f"{row_count}排, {len(preview_items)}个中间点位"
                )

            station_index = _prompt_index_choice(
                f"请选择工站 (1-{len(station_list)}): ",
                len(station_list),
            )
            if station_index is None:
                return True, current_station_display

            selected_station = station_list[station_index]
            preview_items = controller.preview_station_middle_tray_updates(selected_station)
            if len(preview_items) == 0:
                print("错误: 当前工站没有可自动计算的中间点位")
                return True, current_station_display

            print(f"\n工站 {selected_station} 的自动计算预览:")
            _print_middle_tray_update_preview(preview_items)

            print("\n警告: 此操作会修改配置文件中的托盘点位数据")
            confirm = input("确认写入配置文件? (y/n): ").strip().lower()
            if confirm != "y":
                print("已取消")
                return True, current_station_display

            result = controller.apply_station_middle_tray_updates(selected_station)
            updated_count = result["updated_count"]
            created_count = result["created_count"]
            total_count = updated_count + created_count

            if total_count == 0:
                print("没有需要写入的中间点位")
            else:
                print("\n自动计算完成!")
                print(f"工站: {result['station_name']}")
                print(f"更新点位: {updated_count}")
                print(f"新增点位: {created_count}")
                print("影响点位:")
                for tray_name in result["affected_trays"]:
                    print(f"  - {tray_name}")

            skipped_rows = result["skipped_rows"]
            if len(skipped_rows) > 0:
                print("\n跳过的排:")
                for skipped_row in skipped_rows:
                    print(f"  - 第{skipped_row['row_index']}排: {skipped_row['reason']}")
        except Exception as exc:
            _report_exception(exc)
        return True, current_station_display

    return False, current_station_display


def _handle_choice_25_to_33(
    controller: AGVController,
    choice: str,
    current_station_display: str,
) -> Tuple[bool, str]:
    """
    功能:
        处理 25-33 的校正, 充电, 循环测试和货架相关菜单动作.
    参数:
        controller: AGVController 实例.
        choice: 顶层菜单选项.
        current_station_display: 当前站点展示文本.
    返回:
        Tuple[bool, str], 是否已处理及最新站点展示文本.
    """
    if choice == "25":
        print("\n--- 工站整体偏差矫正 ---")
        print("说明: 通过选择参考点位计算偏移量并应用到工站所有点位")
        print("流程:")
        print("  1. 选择要校准的工站(agv或当前所在工站)")
        print("  2. 如果不是agv, 可选择先进行视觉补偿")
        print("  3. 选择一个参考点位")
        print("  4. 可选择运动到该点位")
        print("  5. 手动微调机械臂位置后按回车确认")
        print("  6. 计算偏移量并可选择应用到工站所有点位")
        print(f"当前站点: {current_station_display}")
        try:
            print("\n警告: 此操作可能会修改配置文件中的点位数据!")
            confirm = input("确认开始工站偏差矫正? (y/n): ").strip().lower()
            if confirm != "y":
                print("已取消")
                return True, current_station_display

            controller.position_manager.reload()
            logger.info("点位配置已重新加载")
            result = controller.calibrate_station_offset(block=True)
            if result is not None:
                print("\n工站偏差矫正完成!")
                print(
                    f"计算得到的偏移量: dx={result['x']:.3f}, "
                    f"dy={result['y']:.3f}, dz={result['z']:.3f}"
                )
            else:
                print("工站偏差矫正失败或已取消")
        except Exception as exc:
            _report_exception(exc)
        return True, current_station_display

    if choice == "26":
        print("\n--- 查询电池电量 ---")
        try:
            battery_info = controller.query_battery_status(simple=True)
            if battery_info is not None:
                battery_level = battery_info.get("battery_level")
                print(f"电池电量: {battery_level * 100:.1f}%")
                if battery_level < 0.3:
                    print("警告: 电池电量过低, 建议立即充电!")
                elif battery_level < 0.5:
                    print("提示: 电池电量较低, 建议充电")
                else:
                    print("电池电量充足")
            else:
                print("查询电池电量失败")
        except Exception as exc:
            _report_exception(exc)
        return True, current_station_display

    if choice == "27":
        print("\n--- 自动充电检查 ---")
        print("说明: 执行一次充电检查")
        print("  - 如果不在CP6, 则跳过本次检查")
        print("  - 如果在CP6, 先查询电池电量")
        print("  - 如果电量低于50%, 先确认是否已在充电")
        print("  - 仅在未充电时执行充电循环(CP6->PP5->CP6)")
        try:
            result = controller.auto_charge_check()
            print("\n充电检查结果:")
            print(f"  状态: {result.get('status')}")
            print(f"  动作: {result.get('action')}")
            print(f"  消息: {result.get('message')}")
            if "battery_level" in result:
                battery_level = result.get("battery_level")
                print(f"  电池电量: {battery_level * 100:.1f}%")
        except Exception as exc:
            _report_exception(exc)
        return True, current_station_display

    if choice == "28":
        print("\n--- 启动自动充电循环 ---")
        print("说明: 启动自动充电循环, 每隔指定时间执行一次充电检查")
        print("提示: 按Ctrl+C可以中断循环")
        try:
            interval_input = input("请输入检查间隔时间(小时, 默认1): ").strip()
            interval_hours = 1 if interval_input == "" else float(interval_input)
            if interval_hours <= 0:
                print("错误: 间隔时间必须大于0")
                return True, current_station_display

            print(f"\n启动自动充电循环, 检查间隔: {interval_hours}小时")
            print("按Ctrl+C可以中断循环\n")
            controller.auto_charge_loop(interval_hours=interval_hours)
        except KeyboardInterrupt:
            print("\n用户中断自动充电循环")
        except ValueError:
            print("错误: 请输入有效的数字")
        except Exception as exc:
            _report_exception(exc)
        return True, current_station_display

    if choice == "29":
        print("\n--- 批量物料转运循环测试 ---")
        print("说明: 执行正向转运->充电站->反向转运->充电站的循环测试")
        print("      支持一次转运最多4个物料, AGV会自动移动到各站点并进行点位校准")
        try:
            cycle_input = input("请输入循环次数 (默认1): ").strip()
            if cycle_input == "":
                cycle_count = 1
            else:
                if cycle_input.isdigit() is False:
                    print("错误: 请输入有效的数字")
                    return True, current_station_display
                cycle_count = int(cycle_input)
                if cycle_count < 1:
                    print("错误: 循环次数必须大于0")
                    return True, current_station_display

            task_count_input = input("请输入要转运的物料数量 (1-4): ").strip()
            if task_count_input.isdigit() is False:
                print("错误: 请输入有效的数字")
                return True, current_station_display

            task_count = int(task_count_input)
            if task_count < 1 or task_count > 4:
                print("错误: 任务数量必须在1-4之间")
                return True, current_station_display

            transfer_tasks = _build_transfer_tasks(controller, task_count, pair_text="<->")
            if transfer_tasks is None:
                print("\n任务配置未完成, 已取消")
                return True, current_station_display

            print(f"\n{'=' * 60}")
            print("循环测试摘要:")
            print(f"{'=' * 60}")
            print(f"循环次数: {cycle_count}")
            print("转运任务:")
            for idx, task in enumerate(transfer_tasks, 1):
                print(f"  任务{idx}: {task['source_tray']} <-> {task['target_tray']}")
                if task["material_type"]:
                    print(f"         物料类型: {task['material_type']}")

            print(f"\n警告: 此操作将控制AGV移动并执行{cycle_count}轮循环测试, 请确保周围安全!")
            confirm = input("确认执行循环测试? (y/n): ").strip().lower()
            if confirm != "y":
                print("已取消")
                return True, current_station_display

            print("\n开始执行批量物料转运循环测试...")
            controller.position_manager.reload()
            logger.info("点位配置已重新加载")
            result = controller.batch_transfer_cycle_test(
                transfer_tasks,
                cycle_count=cycle_count,
                block=True,
            )
            print(f"\n{'=' * 60}")
            print("循环测试结果:")
            print(f"{'=' * 60}")
            print(f"测试状态: {'成功' if result['success'] else '失败'}")
            print(f"完成循环: {result['completed_cycles']}/{result['total_cycles']}")
            if result["failed_at"]:
                print(f"失败阶段: {result['failed_at']}")
            print(f"{'=' * 60}")

            if result["success"]:
                print("\n批量物料转运循环测试全部完成!")
            else:
                print("\n批量物料转运循环测试失败, 请查看日志获取详细信息")
        except Exception as exc:
            _report_exception(exc)
        return True, current_station_display

    if choice == "30":
        print("\n--- 分析站→货架样品转运 ---")
        print("说明: 轮询智达进样设备状态, 等待空闲后将样品从分析站转运到货架空位")
        try:
            controller.shelf_manager.print_status()
            print("\n默认源托盘: analysis_station_tray_1-2")
            source_input = input(
                "请输入源托盘(多个用逗号分隔, 直接回车使用默认): "
            ).strip()
            if source_input == "":
                source_trays = ["analysis_station_tray_1-2"]
            else:
                source_trays = [item.strip() for item in source_input.split(",") if item.strip() != ""]
            print(f"源托盘: {source_trays}")

            interval_input = input("请输入轮询间隔秒数 (默认30): ").strip()
            try:
                poll_interval = float(interval_input) if interval_input != "" else 30.0
            except ValueError:
                print("无效数值, 使用默认30秒")
                poll_interval = 30.0

            print("\n将执行以下操作:")
            print(f"  源托盘: {source_trays}")
            print(f"  轮询间隔: {poll_interval} 秒")
            confirm = input("确认执行? (y/n): ").strip().lower()
            if confirm != "y":
                print("已取消")
                return True, current_station_display

            print("\n开始执行分析站→货架样品转运...")
            controller.position_manager.reload()
            logger.info("点位配置已重新加载")
            result = controller.transfer_analysis_to_shelf(
                source_trays=source_trays,
                poll_interval=poll_interval,
            )
            if result:
                print("\n分析站→货架样品转运成功!")
                controller.shelf_manager.print_status()
            else:
                print("\n分析站→货架样品转运失败, 请查看日志获取详细信息")
        except Exception as exc:
            _report_exception(exc)
        return True, current_station_display

    if choice == "31":
        try:
            _handle_shelf_management_menu(controller)
        except Exception as exc:
            _report_exception(exc)
        return True, current_station_display

    if choice == "32":
        print("\n--- PP5/CP6自动充电检查 ---")
        print("说明: 执行一次PP5/CP6待命充电检查")
        print("  - 如果在PP5且电量低于阈值, 则进入CP6充电")
        print("  - 如果在CP6且电量高于90%, 则返回PP5待命")
        print("  - 如果在PP5且电量不低于阈值, 则继续在PP5待命")
        print("  - 如果在CP6且电量不高于90%, 则继续在CP6待命")
        print("  - 如果不在PP5或CP6, 则视为工作途中并跳过本次检查")
        try:
            result = controller.auto_charge_pp5_cp6_check()
            print("\n充电检查结果:")
            print(f"  状态: {result.get('status')}")
            print(f"  动作: {result.get('action')}")
            print(f"  消息: {result.get('message')}")
            if "current_station" in result:
                print(f"  当前站点: {result.get('current_station')}")
            if "battery_level" in result:
                battery_level = result.get("battery_level")
                print(f"  电池电量: {battery_level * 100:.1f}%")
        except Exception as exc:
            _report_exception(exc)
        return True, current_station_display

    if choice == "33":
        print("\n--- 启动PP5/CP6自动充电循环 ---")
        print("说明: 启动PP5/CP6待命充电循环监控")
        print("提示: 按Ctrl+C可以中断循环")
        try:
            interval_input = input(
                f"请输入检查间隔时间(分钟, 默认{AGV_PP5_CP6_AUTO_CHARGE_INTERVAL_MINUTES}): "
            ).strip()
            retry_input = input("请输入重试间隔时间(分钟, 默认5): ").strip()
            low_battery_input = input(
                f"请输入低电量阈值(百分比, 默认{AGV_PP5_CP6_AUTO_CHARGE_LOW_BATTERY_PCT}): "
            ).strip()

            interval_minutes = (
                AGV_PP5_CP6_AUTO_CHARGE_INTERVAL_MINUTES
                if interval_input == ""
                else float(interval_input)
            )
            retry_wait_minutes = 5 if retry_input == "" else float(retry_input)
            low_battery_pct = (
                AGV_PP5_CP6_AUTO_CHARGE_LOW_BATTERY_PCT
                if low_battery_input == ""
                else int(low_battery_input)
            )

            if interval_minutes <= 0:
                print("错误: 检查间隔时间必须大于0")
                return True, current_station_display
            if retry_wait_minutes <= 0:
                print("错误: 重试间隔时间必须大于0")
                return True, current_station_display
            if low_battery_pct <= 0 or low_battery_pct >= 100:
                print("错误: 低电量阈值必须在1~99之间")
                return True, current_station_display

            print(
                f"\n启动PP5/CP6自动充电循环, 检查间隔: {interval_minutes}分钟, "
                f"重试间隔: {retry_wait_minutes}分钟, 低电量阈值: {low_battery_pct}%"
            )
            print("按Ctrl+C可以中断循环\n")
            controller.auto_charge_pp5_cp6_loop(
                interval_minutes=interval_minutes,
                retry_wait_minutes=retry_wait_minutes,
                low_battery_pct=low_battery_pct,
            )
        except KeyboardInterrupt:
            print("\n用户中断PP5/CP6自动充电循环")
        except ValueError:
            print("错误: 请输入有效的数字")
        except Exception as exc:
            _report_exception(exc)
        return True, current_station_display

    return False, current_station_display


def interactive() -> None:
    """
    功能:
        启动 AGV 交互式菜单.
    参数:
        无.
    返回:
        无.
    """
    _configure_logging()

    print("=" * 60)
    print("AGV控制器交互式测试程序")
    print("=" * 60)

    controller = AGVController(timeout=180000)
    current_station_display = _query_current_station_display(controller, announce=True)

    while True:
        _print_top_menu(current_station_display)
        choice = input("请输入选项 (0-34): ").strip()

        if choice == "0":
            print("\n正在退出...")
            if getattr(controller.arm, "is_connected", False):
                controller.disconnect()
            break

        handled = _handle_choice_1_to_12(controller, choice)
        if handled:
            continue

        handled, current_station_display = _handle_choice_13_to_24(
            controller,
            choice,
            current_station_display,
        )
        if handled:
            continue

        handled, current_station_display = _handle_choice_25_to_33(
            controller,
            choice,
            current_station_display,
        )
        if handled:
            continue

        print("无效的选项, 请重新输入")

    print("\n程序已退出")


if __name__ == "__main__":
    interactive()
