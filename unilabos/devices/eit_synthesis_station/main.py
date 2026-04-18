# -*- coding: utf-8 -*-
from .manager.station_manager import SynthesisStationManager
from .config.setting import Settings
from .config.constants import TaskStatus, StationState
from pathlib import Path
import json
import logging
import traceback

logger = logging.getLogger("InteractiveCLI")

# ===================== 模块常量 =====================

ROOT = Path(__file__).resolve().parent
DEFAULT_TASK_TPL = ROOT / "sheet" / "reaction_template.xlsx"
DEFAULT_TEMPLATE_IN = ROOT / "sheet" / "batch_in_tray.xlsx"

# 任务状态码 -> 中文名称
_TASK_STATUS_LABEL = {
    TaskStatus.UNSTARTED: "未开始",
    TaskStatus.RUNNING: "运行中",
    TaskStatus.COMPLETED: "已完成",
    TaskStatus.PAUSED: "已暂停",
    TaskStatus.FAILED: "失败",
    TaskStatus.STOPPED: "已停止",
    TaskStatus.PAUSING: "暂停中",
    TaskStatus.STOPPING: "停止中",
    TaskStatus.WAITING: "等待中",
    TaskStatus.HOLDING: "挂起",
}

# 工站状态码 -> 中文名称
_STATION_STATE_LABEL = {
    StationState.IDLE: "空闲/待机",
    StationState.RUNNING: "运行中",
    StationState.PAUSED: "已暂停",
    StationState.PAUSING: "暂停中",
    StationState.STOPPING: "停止中",
    StationState.HOLDING: "挂起/保持",
}

# 哨兵对象: 用于区分"函数正常返回None"和"异常/中断导致的失败"
_SENTINEL_FAILED = object()


# ===================== 工具函数 =====================

def _input_with_default(prompt, default=None):
    """
    功能:
        带默认值的输入提示, 用户直接回车即采用默认值
    参数:
        prompt: str, 提示文本
        default: 默认值, None 时不显示默认值
    返回:
        str, 用户输入或默认值的字符串形式
    """
    if default is not None:
        display = f"{prompt} [默认: {default}]: "
    else:
        display = f"{prompt}: "
    val = input(display).strip()
    if val == "" and default is not None:
        return str(default)
    return val


def _input_file_path(prompt, default_path):
    """
    功能:
        输入文件路径, 带默认值
    参数:
        prompt: str, 提示文本
        default_path: Path 或 str, 默认路径
    返回:
        str, 文件路径字符串
    """
    return _input_with_default(prompt, str(default_path))


def _input_task_id(allow_none=True):
    """
    功能:
        提示用户输入任务ID.
        最近任务ID仅作为提示展示, 不再作为输入默认值.
        当 allow_none 为 True 时, 直接回车表示自动选取.
        当 allow_none 为 False 时, 必须显式输入合法任务ID.
    参数:
        allow_none: bool, 是否允许留空(由系统自动选取)
    返回:
        int | None, 任务ID或None
    """
    while True:
        if allow_none is True:
            val = input("请输入任务ID(留空则自动选取): ").strip()
            if val == "" or val == "None":
                return None
        else:
            val = input("请输入任务ID: ").strip()
            if val == "" or val == "None":
                print("任务ID不能为空, 请重新输入")
                continue

        try:
            tid = int(val)
            return tid
        except ValueError:
            if allow_none is True:
                print("输入的任务ID格式不正确, 将自动选取")
                return None
            print("输入的任务ID格式不正确, 请重新输入")


def _input_positive_float(prompt):
    """
    功能:
        提示用户输入大于 0 的数值, 输入非法时循环重试.
    参数:
        prompt: str, 提示文本.
    返回:
        float, 用户输入的正数.
    """
    while True:
        val = input(f"{prompt}: ").strip()
        if val == "":
            print("输入不能为空")
            continue
        try:
            numeric_value = float(val)
        except ValueError:
            print("请输入数字")
            continue
        if numeric_value <= 0:
            print("请输入大于0的数值")
            continue
        return numeric_value


def _pause():
    """按回车键继续"""
    input("\n按回车键继续...")


def _safe_run(func, *args, **kwargs):
    """
    功能:
        安全执行函数, 捕获异常并友好提示
    参数:
        func: 可调用对象
        *args, **kwargs: 透传参数
    返回:
        func 的返回值, 异常时返回 None
    """
    try:
        result = func(*args, **kwargs)
        return result
    except KeyboardInterrupt:
        print("\n操作已被用户中断")
    except Exception as exc:
        logger.debug("异常详情:\n%s", traceback.format_exc())
        print(f"\n操作失败: {exc}")
    _pause()
    return _SENTINEL_FAILED


def _print_menu(title, options):
    """
    功能:
        打印格式化菜单
    参数:
        title: str, 菜单标题
        options: list[tuple[str, str]], (编号, 描述) 列表
    返回:
        None
    """
    width = 48
    print("\n" + "=" * width)
    print(f"  {title}")
    print("=" * width)
    for num, desc in options:
        print(f"  {num}. {desc}")
    print("=" * width)


def _print_result(result):
    """
    功能:
        格式化打印 API 返回结果
    参数:
        result: 任意可 JSON 序列化的对象
    返回:
        None
    """
    if result is None:
        return
    try:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (TypeError, ValueError):
        print(result)


# ===================== 工作流执行器 =====================

def _run_workflow(steps, quick=False):
    """
    功能:
        按顺序执行工作流步骤, 每步可跳过或终止;
        quick=True 时跳过逐步确认, 直接连续执行
    参数:
        steps: list[tuple[str, callable]], (步骤名, 执行函数) 列表
        quick: bool, 是否跳过逐步确认直接执行
    返回:
        None
    """
    for i, (name, action) in enumerate(steps, 1):
        print(f"\n--- 步骤 {i}/{len(steps)}: {name} ---")
        if quick is False:
            confirm = input("继续执行? (y/n/q) [默认: y]: ").strip().lower()
            if confirm == "n":
                print(f"已跳过: {name}")
                continue
            if confirm == "q":
                print("工作流已终止")
                return
        result = _safe_run(action)
        if result is _SENTINEL_FAILED:
            if quick is True:
                # 快速模式下步骤失败或被中断, 直接终止工作流
                print("工作流已中断")
                _pause()
                return
            else:
                retry = input("该步骤可能未成功, 是否继续后续步骤? (y/n) [默认: n]: ").strip().lower()
                if retry != "y":
                    print("工作流已终止")
                    return
    print("\n工作流执行完毕!")
    _pause()


# ===================== 1. 快速工作流 =====================

def _menu_quick_workflow(manager):
    """快速工作流子菜单"""
    options = [
        ("1", "上传任务流程"),
        ("2", "agv上料+提交合成任务+分析执行流程"),
        ("3", "等待合成任务完成+分析执行流程"),
        ("4", "等待分析任务完成+回收检测样品"),
        ("0", "返回上级菜单"),
    ]

    while True:
        _print_menu("快速工作流", options)
        choice = input("请选择操作: ").strip()

        if choice == "0":
            return

        # 收集所有工作流共用的文件路径
        if choice in ("1"):
            task_tpl = _input_file_path("任务模板路径", DEFAULT_TASK_TPL)

        if choice == "1":
            # 提交任务流程
            steps = [
                ("同步化学品库到工站", lambda: manager.sync_chemicals_to_station()),
                ("上传任务到工站", lambda: manager.create_task_by_file(task_tpl)),
                ("物料核算", lambda: manager.check_resource_for_task(task_tpl)),
            ]
            _run_workflow(steps, quick=True)

        elif choice == "2":
            # AGV执行流程
            task_tpl = _input_file_path("任务模板路径", DEFAULT_TASK_TPL)
            steps = [
                ("AGV上料", lambda: manager.batch_in_tray_with_agv_transfer()),
                ("启动任务", lambda: manager.start_task()),
                ("等待任务完成", lambda: manager.wait_task_with_ops()),
                ("下料(任务物料+空托盘)", lambda: manager.batch_out_task_and_empty_trays()),
                ("AGV自动下料", lambda: manager.auto_unload_trays_to_agv()),
                ("谱图数据处理", lambda: manager.poll_analysis_run()),
                ("分析样品转运到货架", lambda: manager.transfer_analysis_to_shelf()),
            ]
            _run_workflow(steps, quick=True)

        elif choice == "3":
            # 执行流程
            tid = _input_task_id()
            tid_str = str(tid) if tid is not None else None
            steps = [
                ("等待任务完成", lambda: manager.wait_task_with_ops(task_id=tid)),
                ("下料(任务物料+空托盘)", lambda: manager.batch_out_task_and_empty_trays(task_id=tid)),
                ("AGV自动下料", lambda: manager.auto_unload_trays_to_agv()),
                ("谱图数据处理", lambda: manager.poll_analysis_run(task_id=tid_str)),
                ("分析样品转运到货架", lambda: manager.transfer_analysis_to_shelf()),
            ]
            _run_workflow(steps, quick=True)

        elif choice == "4":
            # 执行流程
            tid = _input_task_id()
            tid_str = str(tid) if tid is not None else None
            steps = [
                ("谱图数据处理", lambda: manager.poll_analysis_run(task_id=tid_str)),
                ("分析样品转运到货架", lambda: manager.transfer_analysis_to_shelf()),
            ]
            _run_workflow(steps, quick=True)

        else:
            print("无效选择, 请重新输入")


# ===================== 2. 全流程分步进行 =====================

def _menu_step_by_step(manager):
    """全流程分步进行子菜单"""
    options = [
        ("1", "同步化学品库到工站"),
        ("2", "上传任务到工站"),
        ("3", "物料核算"),
        ("4", "AGV上料"),
        ("5", "二次物料核算"),
        ("6", "启动任务"),
        ("7", "等待任务完成"),
        ("8", "下料(任务物料+空托盘)"),
        ("9", "AGV自动下料"),
        ("10", "提交分析任务"),
        ("11", "谱图数据处理"),
        ("0", "返回上级菜单"),
    ]

    while True:
        _print_menu("全流程分步进行", options)
        choice = input("请选择操作: ").strip()

        if choice == "0":
            return
        elif choice == "1":
            _safe_run(manager.sync_chemicals_to_station)
        elif choice == "2":
            task_tpl = _input_file_path("任务模板路径", DEFAULT_TASK_TPL)
            _safe_run(manager.create_task_by_file, task_tpl)
        elif choice == "3" or choice == "5":
            task_tpl = _input_file_path("任务模板路径", DEFAULT_TASK_TPL)
            _safe_run(manager.check_resource_for_task, task_tpl)
        elif choice == "4":
            _safe_run(manager.batch_in_tray_with_agv_transfer)
        elif choice == "6":
            tid = _input_task_id()
            _safe_run(manager.start_task, tid)
        elif choice == "7":
            tid = _input_task_id()
            _safe_run(manager.wait_task_with_ops, tid)
        elif choice == "8":
            tid = _input_task_id()
            _safe_run(manager.batch_out_task_and_empty_trays, tid)
        elif choice == "9":
            _safe_run(manager.auto_unload_trays_to_agv)
        elif choice == "10":
            tid = _input_task_id()
            _safe_run(manager.run_analysis, tid)
        elif choice == "11":
            tid = _input_task_id()
            _safe_run(manager.poll_analysis_run, tid)
        else:
            print("无效选择, 请重新输入")


# ===================== 3. 工站状态查询 =====================

def _menu_status_query(manager):
    """工站状态查询子菜单"""
    options = [
        ("1", "查询站内物料信息"),
        ("2", "查询设备状态"),
        ("3", "查询工站运行状态"),
        ("4", "查询手套箱环境"),
        ("0", "返回上级菜单"),
    ]

    while True:
        _print_menu("工站状态查询", options)
        choice = input("请选择操作: ").strip()

        if choice == "0":
            return
        elif choice == "1":
            result = _safe_run(manager.get_resource_info)
            _print_result(result)
            _pause()
        elif choice == "2":
            result = _safe_run(manager.list_device_status)
            _print_result(result)
            _pause()
        elif choice == "3":
            result = _safe_run(manager.station_state)
            if result is not None:
                label = _STATION_STATE_LABEL.get(result, f"未知({result})")
                print(f"工站状态: {label} (代码: {result})")
            _pause()
        elif choice == "4":
            result = _safe_run(manager.get_glovebox_env)
            _print_result(result)
            _pause()
        else:
            print("无效选择, 请重新输入")


# ===================== 4. 化学品库管理 =====================

def _menu_chemical_library(manager):
    """
    功能:
        工站化学品 CSV 导入导出菜单.
        本地化学品库管理已提升为 eit_hub 一级菜单 4, 不再在此处提供入口.
    参数:
        manager: SynthesisStationManager 实例.
    返回:
        None.
    """
    options = [
        ("1", "同步化学品库到工站 (并回写 chemical_id)"),
        ("0", "返回上级菜单"),
    ]

    while True:
        _print_menu("化学品库管理", options)
        choice = input("请选择操作: ").strip()

        if choice == "0":
            return
        elif choice == "1":
            _safe_run(manager.sync_chemicals_to_station)
        else:
            print("无效选择, 请重新输入")



# ===================== 5. 任务管理 =====================

def _show_all_tasks(manager):
    """
    功能:
        格式化显示所有任务列表
    参数:
        manager: SynthesisStationManager 实例
    返回:
        None
    """
    resp = manager.get_all_tasks()
    # 兼容多种返回结构
    task_list = resp
    if isinstance(resp, dict):
        task_list = resp.get("task_list") or resp.get("result", {}).get("task_list", [])
    if not task_list:
        print("暂无任务")
        return

    print(f"\n{'任务ID':<10} {'任务名称':<30} {'状态':<10}")
    print("-" * 55)
    for task in task_list:
        tid = task.get("task_id", "?")
        name = task.get("task_name", "未知")
        status_code = task.get("status", -1)
        status_text = _TASK_STATUS_LABEL.get(status_code, f"未知({status_code})")
        print(f"{tid:<10} {name:<30} {status_text:<10}")

    print(f"\n共 {len(task_list)} 个任务")


def _menu_task_management(manager):
    """任务管理子菜单"""
    options = [
        ("1", "查看所有任务"),
        ("2", "查看任务详情"),
        ("3", "停止任务"),
        ("4", "取消任务"),
        ("5", "删除任务"),
        ("6", "导出任务报告"),
        ("0", "返回上级菜单"),
    ]

    while True:
        _print_menu("任务管理", options)
        choice = input("请选择操作: ").strip()

        if choice == "0":
            return
        elif choice == "1":
            _safe_run(_show_all_tasks, manager)
        elif choice == "2":
            tid = _input_task_id(allow_none=False)
            if tid is not None:
                result = _safe_run(manager.get_task_info, tid)
                _print_result(result)
                _pause()
        elif choice == "3":
            tid = _input_task_id(allow_none=False)
            if tid is not None:
                _safe_run(manager.stop_task, tid)
        elif choice == "4":
            tid = _input_task_id(allow_none=False)
            if tid is not None:
                _safe_run(manager.cancel_task, tid)
        elif choice == "5":
            tid = _input_task_id(allow_none=False)
            if tid is not None:
                confirm = input(f"确认删除任务 {tid}? (y/n) [默认: n]: ").strip().lower()
                if confirm == "y":
                    _safe_run(manager.delete_task, tid)
                else:
                    print("已取消删除")
        elif choice == "6":
            tid = _input_task_id(allow_none=False)
            if tid is not None:
                _safe_run(manager.export_task_report, tid)
        else:
            print("无效选择, 请重新输入")


# ===================== 6. 上料操作 =====================

def _menu_load(manager):
    """上料操作子菜单"""
    options = [
        ("1", "手动上料"),
        ("2", "AGV上料"),
        ("0", "返回上级菜单"),
    ]

    while True:
        _print_menu("上料操作", options)
        choice = input("请选择操作: ").strip()

        if choice == "0":
            return
        elif choice == "1":
            template_in = _input_file_path("上料文件路径", DEFAULT_TEMPLATE_IN)
            _safe_run(manager.batch_in_tray_by_file, template_in)
        elif choice == "2":
            _safe_run(manager.batch_in_tray_with_agv_transfer)
        else:
            print("无效选择, 请重新输入")


# ===================== 7. 下料操作 =====================

def _menu_unload(manager):
    """下料操作子菜单"""
    options = [
        ("1", "下料(任务物料+空托盘)"),
        ("2", "下料(仅任务托盘)"),
        ("3", "下料(任务+化学品托盘)"),
        ("4", "下料(仅空托盘)"),
        ("5", "AGV自动下料"),
        ("6", "手动下料(指定layout)"),
        ("0", "返回上级菜单"),
    ]

    while True:
        _print_menu("下料操作", options)
        choice = input("请选择操作: ").strip()

        if choice == "0":
            return
        elif choice == "1":
            tid = _input_task_id()
            _safe_run(manager.batch_out_task_and_empty_trays, tid)
        elif choice == "2":
            tid = _input_task_id()
            _safe_run(manager.batch_out_task_trays, tid)
        elif choice == "3":
            tid = _input_task_id()
            _safe_run(manager.batch_out_task_and_chemical_trays, tid)
        elif choice == "4":
            _safe_run(manager.batch_out_empty_trays)
        elif choice == "5":
            _safe_run(manager.auto_unload_trays_to_agv)
        elif choice == "6":
            # 手动下料: 逐条输入 layout_code 和 dst_layout_code
            layout_list = []
            print("请逐条输入下料位置对(输入空行结束):")
            while True:
                src = input("  layout_code (源位置, 如 T-1-2): ").strip()
                if src == "":
                    break
                dst = input("  dst_layout_code (目标位置, 如 TB-2-2): ").strip()
                if dst == "":
                    break
                layout_list.append({"layout_code": src, "dst_layout_code": dst})
            if layout_list:
                print(f"将下料 {len(layout_list)} 个位置:")
                for item in layout_list:
                    print(f"  {item['layout_code']} -> {item['dst_layout_code']}")
                confirm = input("确认执行? (y/n) [默认: y]: ").strip().lower()
                if confirm != "n":
                    _safe_run(manager.batch_out_tray, layout_list)
            else:
                print("未输入任何下料位置, 已取消")
        else:
            print("无效选择, 请重新输入")


# ===================== 8. 分析操作 =====================

def _menu_analysis(manager):
    """分析操作子菜单"""
    options = [
        ("1", "提交分析任务"),
        ("2", "谱图数据处理"),
        ("0", "返回上级菜单"),
    ]

    while True:
        _print_menu("分析操作", options)
        choice = input("请选择操作: ").strip()

        if choice == "0":
            return
        elif choice == "1":
            tid = _input_task_id()
            _safe_run(manager.run_analysis, tid)
        elif choice == "2":
            tid = _input_task_id()
            _safe_run(manager.poll_analysis_run, tid)
        else:
            print("无效选择, 请重新输入")


# ===================== 9. 其它操作 =====================

def _menu_other(manager):
    """其它操作子菜单"""
    options = [
        ("1", "设备初始化"),
        ("2", "控制过渡舱门"),
        ("3", "控制W1货架"),
        ("4", "异常通知监控"),
        ("5", "整理W/T货架托盘"),
        ("0", "返回上级菜单"),
    ]

    while True:
        _print_menu("其它操作", options)
        choice = input("请选择操作: ").strip()

        if choice == "0":
            return
        elif choice == "1":
            _safe_run(manager.device_init)
        elif choice == "2":
            print("  1. 打开过渡舱门")
            print("  2. 关闭过渡舱门")
            op_choice = input("请选择: ").strip()
            if op_choice == "1":
                _safe_run(manager.open_close_door, "open")
            elif op_choice == "2":
                _safe_run(manager.open_close_door, "close")
            else:
                print("无效选择")
        elif choice == "3":
            print("货架位置:")
            print("  1. W-1-1 (控制 W-1-1 和 W-1-2)")
            print("  2. W-1-3 (控制 W-1-3 和 W-1-4)")
            print("  3. W-1-5 (控制 W-1-5 和 W-1-6)")
            print("  4. W-1-7 (控制 W-1-7 和 W-1-8)")
            pos_choice = input("请选择货架位置: ").strip()
            pos_map = {"1": "W-1-1", "2": "W-1-3", "3": "W-1-5", "4": "W-1-7"}
            position = pos_map.get(pos_choice)
            if position is None:
                print("无效选择")
                continue

            print("动作类型:")
            print("  1. 推出 (outside)")
            print("  2. 复位 (home)")
            act_choice = input("请选择动作: ").strip()
            act_map = {"1": "outside", "2": "home"}
            action = act_map.get(act_choice)
            if action is None:
                print("无效选择")
                continue

            _safe_run(manager.control_w1_shelf, position, action)
        elif choice == "4":
            _menu_notification(manager)
        elif choice == "5":
            task_id = _input_task_id(allow_none=False)
            if task_id is not None:
                result = _safe_run(manager.arrange_w_t_trays_for_task, task_id)
                if result is not _SENTINEL_FAILED:
                    # _print_result(result)
                    _pause()
        else:
            print("无效选择, 请重新输入")


# ===================== 10. 异常通知监控 =====================

def _menu_notification(manager):
    """异常通知监控子菜单"""
    import datetime as _dt

    options = [
        ("1", "启动通知监控"),
        ("2", "停止通知监控"),
        ("3", "查看监控状态"),
        ("0", "返回上级菜单"),
    ]

    while True:
        _print_menu("异常通知监控", options)
        choice = input("请选择操作: ").strip()

        if choice == "0":
            return
        elif choice == "1":
            _safe_run(manager.start_notification_monitor)
        elif choice == "2":
            _safe_run(manager.stop_notification_monitor)
        elif choice == "3":
            status = _safe_run(manager.notification_monitor_status)
            if status is not None:
                running_text = "运行中" if status.get("running") else "已停止"
                email_text = "可用" if status.get("email_available") else "未配置"
                last_poll = status.get("last_poll_time")
                if last_poll is not None:
                    last_poll_text = _dt.datetime.fromtimestamp(last_poll).strftime("%Y-%m-%d %H:%M:%S")
                else:
                    last_poll_text = "无"

                print(f"\n  监控状态: {running_text}")
                print(f"  邮件渠道: {email_text}")
                print(f"  已处理通知数: {status.get('total_processed', 0)}")
                print(f"  去重记录数: {status.get('processed_ids_count', 0)}")
                print(f"  上次轮询: {last_poll_text}")
            _pause()
        else:
            print("无效选择, 请重新输入")


# ===================== 10. 标签打印 =====================

def _menu_label_print(manager):
    """标签打印子菜单"""
    options = [
        ("1", "打印上料试剂标签"),
        ("2", "打印任务编号标签"),
        ("3", "交互式自由打印"),
        ("0", "返回上级菜单"),
    ]

    while True:
        _print_menu("标签打印", options)
        choice = input("请选择操作: ").strip()

        if choice == "0":
            return
        elif choice == "1":
            # 从 batch_in_tray.xlsx 提取试剂名并打印
            _safe_run(manager.print_reagent_labels)
        elif choice == "2":
            # 输入任务ID, 打印反应管+样品编号标签
            tid = _input_task_id(allow_none=False)
            if tid is not None:
                _safe_run(manager.print_task_number_labels, tid)
        elif choice == "3":
            # 交互式自由打印 (复用 print_text.py 的 main 函数)
            try:
                from .printer.print_text import main as _print_text_main
                _print_text_main()
            except Exception as exc:
                logger.error("交互式打印启动失败: %s", exc)
                print(f"启动失败: {exc}")
            _pause()
        else:
            print("无效选择, 请重新输入")


# ===================== 主入口 =====================

def interactive():
    """
    功能:
        启动交互式命令行菜单, 作为 main.py 的默认入口
    参数:
        无
    返回:
        无
    """
    settings = Settings.from_env()
    manager = SynthesisStationManager(settings)

    print("\n正在连接合成工站...")
    print(f"  地址: {settings.base_url}")
    print(f"  用户: {settings.username}")

    top_menu = [
        ("1", "快速工作流"),
        ("2", "全流程分步进行"),
        ("3", "工站状态查询"),
        ("4", "化学品库管理"),
        ("5", "任务管理"),
        ("6", "上料操作"),
        ("7", "下料操作"),
        ("8", "分析操作"),
        ("9", "其它操作"),
        ("10", "标签打印"),
        ("0", "退出"),
    ]

    dispatch = {
        "1": _menu_quick_workflow,
        "2": _menu_step_by_step,
        "3": _menu_status_query,
        "4": _menu_chemical_library,
        "5": _menu_task_management,
        "6": _menu_load,
        "7": _menu_unload,
        "8": _menu_analysis,
        "9": _menu_other,
        "10": _menu_label_print,
    }

    while True:
        _print_menu("EIT 合成工站 交互控制台", top_menu)
        choice = input("请选择操作: ").strip()

        if choice == "0" or choice.lower() == "q":
            break

        handler = dispatch.get(choice)
        if handler is None:
            print("无效选择, 请重新输入")
            continue

        handler(manager)


if __name__ == "__main__":
    interactive()
