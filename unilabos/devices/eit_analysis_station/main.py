#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    提供分析站交互式命令行入口, 将 controller 中的测试菜单独立到 main.py.
参数:
    无.
返回:
    无.
"""

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from .config.setting import configure_logging
from .controller.analysis_controller import AnalysisStationController
from .driver.zhida_driver import ZhidaClient

logger = logging.getLogger("AnalysisInteractiveCLI")


def _print_result(result: Any) -> None:
    """
    功能:
        格式化打印执行结果, 兼容字典与普通对象.
    参数:
        result: 任意返回对象.
    返回:
        无.
    """
    if isinstance(result, dict):
        print("\n========== 执行结果 ==========")
        for key, value in result.items():
            print(f"  {key}: {value}")
        print("==============================\n")
        return

    print(result)


def _prompt_task_id() -> Optional[str]:
    """
    功能:
        读取 task_id 输入, 留空时返回 None 以便自动选取最新任务.
    参数:
        无.
    返回:
        Optional[str], task_id 字符串或 None.
    """
    task_id_input = input("请输入 task_id (留空则自动选取最新任务): ").strip()
    if task_id_input == "":
        return None
    return task_id_input


def _prompt_rack_code() -> Optional[str]:
    """
    功能:
        读取 run_analysis 交互式提交流程使用的 RackCode.
        直接回车时使用控制器默认的 Rack 6.
    参数:
        无.
    返回:
        Optional[str], None 表示沿用默认 Rack 6, 否则返回 "Rack 1" 到 "Rack 6".
    """
    rack_input = input("请输入 Rack 编号(1-6, 直接回车使用默认 Rack 6): ").strip()
    if rack_input == "":
        return None

    if rack_input not in ("1", "2", "3", "4", "5", "6"):
        raise ValueError("无效 Rack 选择, 请输入 1-6, 或直接回车使用默认 Rack 6.")

    return f"Rack {rack_input}"


def _get_analysis_device_configs(settings: Any) -> Dict[str, Dict[str, Any]]:
    """
    功能:
        汇总三台分析设备的连接配置, 供状态查询按固定顺序遍历.
    参数:
        settings: AnalysisStationController 持有的 Settings 实例.
    返回:
        Dict[str, Dict[str, Any]], key 为设备显示名, value 包含 host/port/timeout.
    """
    return {
        "GC-MS": {
            "host": settings.gc_ms_host,
            "port": settings.gc_ms_port,
            "timeout": settings.gc_ms_timeout,
        },
        "UPLC_QTOF": {
            "host": settings.uplc_qtof_host,
            "port": settings.uplc_qtof_port,
            "timeout": settings.uplc_qtof_timeout,
        },
        "HPLC": {
            "host": settings.hplc_host,
            "port": settings.hplc_port,
            "timeout": settings.hplc_timeout,
        },
    }


def _print_status_detail(
    device_name: str,
    config: Dict[str, Any],
    status_detail: Dict[str, Any],
) -> None:
    """
    功能:
        打印单台分析设备的原始状态, 仪器状态, 诊断消息与样品计数.
    参数:
        device_name: 设备显示名.
        config: 设备连接配置, 包含 host/port.
        status_detail: ZhidaClient.get_status_detail 返回的状态详情, 五键 dict.
    返回:
        无.
    """
    raw_status = status_detail["raw_status"] or "(空)"
    message = status_detail["message"] or "(无)"
    total_sample_count = status_detail["total_sample_count"]
    unrun_sample_count = status_detail["unrun_sample_count"]
    finished_sample_count = max(total_sample_count - unrun_sample_count, 0)

    print(
        "\n"
        f"  [{device_name}] {config['host']}:{config['port']}\n"
        f"    原始状态: {raw_status}\n"
        f"    仪器状态: {status_detail['instrument_status']}\n"
        f"    消息: {message}\n"
        f"    样品总数: {total_sample_count}\n"
        f"    未运行样品数: {unrun_sample_count}\n"
        f"    样品进度: {finished_sample_count}/{total_sample_count}"
    )


def _handle_all_device_status(controller: AnalysisStationController) -> None:
    """
    功能:
        依次查询 GC-MS, UPLC_QTOF, HPLC 三台分析设备的当前状态.
    参数:
        controller: AnalysisStationController 实例.
    返回:
        无.
    """
    settings = controller._settings
    device_configs = _get_analysis_device_configs(settings)

    print("\n>>> 调用三台分析设备 ZhidaClient.get_status_detail()")
    for device_name, config in device_configs.items():
        client = ZhidaClient(
            host=config["host"],
            port=config["port"],
            timeout=config["timeout"],
        )
        try:
            client.connect()
            status_detail = client.get_status_detail()
            _print_status_detail(device_name, config, status_detail)
        except Exception as exc:
            logger.exception("%s 状态查询失败", device_name)
            print(
                "\n"
                f"  [{device_name}] {config['host']}:{config['port']}\n"
                f"    操作失败: {exc}"
            )
        finally:
            client.close()


def _handle_device_query(controller: AnalysisStationController, choice: str) -> None:
    """
    功能:
        处理设备状态与方法查询分支.
    参数:
        controller: AnalysisStationController 实例.
        choice: 菜单选项, 仅支持 4 或 5.
    返回:
        无.
    """
    settings = controller._settings

    if choice == "4":
        _handle_all_device_status(controller)
        return

    client = ZhidaClient(
        host=settings.gc_ms_host,
        port=settings.gc_ms_port,
        timeout=settings.gc_ms_timeout,
    )

    try:
        client.connect()
        print("\n>>> 调用 ZhidaClient.get_methods()")
        methods = client.get_methods()
        _print_result(methods)
    except Exception as exc:
        logger.exception("分析站设备查询失败")
        print(f"\n操作失败: {exc}\n")
    finally:
        client.close()


def _handle_submit_by_csv_path(controller: AnalysisStationController) -> None:
    """
    功能:
        处理按 CSV 路径直接提交分析任务的交互流程.
    参数:
        controller: AnalysisStationController 实例.
    返回:
        无.
    """
    instrument_options = {
        "1": ("gc_ms", "GC-MS"),
        "2": ("uplc_qtof", "UPLC_QTOF"),
        "3": ("hplc", "HPLC"),
    }
    print("\n请选择仪器:")
    for option, (_, instrument_name) in instrument_options.items():
        print(f"  {option}. {instrument_name}")

    instrument_choice = input("请输入仪器编号(1/2/3): ").strip()
    if instrument_choice not in instrument_options:
        print("无效选择, 请输入 1/2/3.")
        return

    instrument = instrument_options[instrument_choice][0]
    csv_file_path = input("请输入CSV文件路径: ").strip()
    print(
        f"\n>>> 调用 submit_by_csv_path("
        f"instrument={instrument!r}, csv_file_path={csv_file_path!r})"
    )
    result = controller.submit_by_csv_path(
        instrument=instrument, csv_file_path=csv_file_path
    )
    _print_result(result)


def _handle_transfer_to_shelf() -> None:
    """
    功能:
        处理分析完成样品转运到货架的交互流程.
    参数:
        无.
    返回:
        无.
    """
    print("\n>>> 分析完成样品→货架转运")
    print("说明: 轮询智达进样设备状态, 等待空闲后将样品从分析站转运到货架空位\n")

    try:
        from eit_agv.controller.agv_controller import AGVController

        agv = AGVController(timeout=180000)

        # 先展示当前货架状态, 方便用户确认目标空位.
        agv.shelf_manager.print_status()

        print("默认源托盘: analysis_station_tray_1-2")
        source_input = input(
            "请输入源托盘(多个用逗号分隔, 直接回车使用默认): "
        ).strip()

        if source_input == "":
            source_trays = ["analysis_station_tray_1-2"]
        else:
            source_trays = [
                item.strip() for item in source_input.split(",") if item.strip() != ""
            ]

        interval_input = input("请输入轮询间隔秒数 (留空默认30): ").strip()
        try:
            interval = float(interval_input) if interval_input else 30.0
        except ValueError:
            print("无效数值, 使用默认30秒.")
            interval = 30.0

        print(f"\n源托盘: {source_trays}")
        print(f"轮询间隔: {interval} 秒")
        print("\n开始执行分析站→货架样品转运...")

        success = agv.transfer_analysis_to_shelf(
            source_trays=source_trays,
            poll_interval=interval,
        )

        _print_result(
            {
                "success": success,
                "source_trays": source_trays,
                "poll_interval": interval,
            }
        )

        if success:
            agv.shelf_manager.print_status()
    except Exception as exc:
        logger.exception("分析站到货架转运失败")
        print(f"\n操作失败: {exc}\n")


def _handle_generate_heatmap() -> None:
    """
    功能:
        处理从 Excel/CSV 文件生成产率热力图的交互流程.
    参数:
        无.
    返回:
        无.
    """
    from .processor.heatmap_plotter import HeatmapPlotter

    file_path_input = input("请输入数据文件路径(.xlsx 或 .csv): ").strip()
    if file_path_input == "":
        print("文件路径不能为空.")
        return

    output_input = input("请输入输出路径(留空则自动生成同名 .png): ").strip()
    output_path = output_input if output_input != "" else None

    try:
        plotter = HeatmapPlotter()
        result_path = plotter.plot(file_path=file_path_input, output_path=output_path)
        print(f"\n热力图已保存: {result_path}\n")
    except Exception as exc:
        logger.exception("热力图生成失败")
        print(f"\n操作失败: {exc}\n")


def interactive() -> None:
    """
    功能:
        启动分析站交互式菜单.
    参数:
        无.
    返回:
        无.
    """
    configure_logging("DEBUG")
    logger.info("初始化分析站控制器...")
    controller = AnalysisStationController()

    menu = (
        "\n===== 分析站交互式测试菜单 =====\n"
        "  1. run_analysis          - 统一分析入口(生成CSV并提交至仪器)\n"
        "  2. process_gc_ms_results - GC-MS结果处理(积分+定性+报告)\n"
        "  3. poll_analysis_run     - 轮询GC-MS分析任务状态并自动处理结果\n"
        "  4. get_status            - 获取三台分析设备当前状态\n"
        "  5. get_methods           - 获取当前Project的方法列表\n"
        "  6. calculate_yields      - 产率计算\n"
        "  7. submit_by_csv_path    - 选择仪器并按CSV路径直接提交任务\n"
        "  8. aggregate_task_data   - 实验数据归档汇总\n"
        "  9. transfer_to_shelf     - 分析完成样品→货架转运(等待空闲后自动执行)\n"
        "  10. generate_heatmap    - 从Excel/CSV生成产率热力图\n"
        "  0. 退出\n"
        "================================"
    )

    while True:
        print(menu)
        choice = input("请选择功能编号: ").strip()

        if choice == "0":
            print("已退出测试.")
            break

        if choice not in ("1", "2", "3", "4", "5", "6", "7", "8", "9", "10"):
            print("无效选择, 请输入 0-10.")
            continue

        if choice in ("4", "5"):
            _handle_device_query(controller, choice)
            continue

        if choice == "7":
            _handle_submit_by_csv_path(controller)
            continue

        if choice == "9":
            _handle_transfer_to_shelf()
            continue

        if choice == "10":
            _handle_generate_heatmap()
            continue

        task_id = _prompt_task_id()

        if choice == "1":
            try:
                rack_code = _prompt_rack_code()
            except ValueError as exc:
                print(str(exc))
                continue
            print(f"\n>>> 调用 run_analysis(task_id={task_id!r}, rack_code={rack_code!r})")
            result = controller.run_analysis(task_id=task_id, rack_code=rack_code)
            _print_result(result)

        elif choice == "2":
            print(f"\n>>> 调用 process_gc_ms_results(task_id={task_id!r})")
            result = controller.process_gc_ms_results(task_id=task_id)
            _print_result(result)

        elif choice == "3":
            interval_input = input("请输入轮询间隔秒数 (留空默认30): ").strip()
            try:
                interval = float(interval_input) if interval_input else 30.0
            except ValueError:
                print("无效数值, 使用默认30秒.")
                interval = 30.0

            print(
                f"\n>>> 调用 poll_analysis_run(task_id={task_id!r}, "
                f"poll_interval={interval})"
            )
            result = controller.poll_analysis_run(
                task_id=task_id, poll_interval=interval
            )
            _print_result(result)

        elif choice == "6":
            print(f"\n>>> 调用 calculate_yields(task_id={task_id!r})")
            result = controller.calculate_yields(task_id=task_id)
            _print_result(result)

        elif choice == "8":
            default_copy = controller._settings.archive_copy_raw_data
            hint = "Y/n" if default_copy is True else "y/N"
            copy_raw_input = input(
                f"是否复制原始数据(.D目录)? ({hint}, 留空使用配置默认值): "
            ).strip().lower()
            if copy_raw_input == "":
                copy_raw: Optional[bool] = None
            else:
                copy_raw = copy_raw_input in ("y", "yes")
            print(
                f"\n>>> 调用 aggregate_task_data("
                f"task_id={task_id!r}, copy_raw_data={copy_raw})"
            )
            result = controller.aggregate_task_data(
                task_id=task_id, copy_raw_data=copy_raw
            )
            _print_result(result)


if __name__ == "__main__":
    interactive()
