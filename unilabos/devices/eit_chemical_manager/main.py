# -*- coding: utf-8 -*-
"""
功能:
    eit_chemical_manager 驱动的交互式 CLI 入口.
    提供化学品库管理菜单: 搜索, 添加, 去重, 校验, 导出, 配置溶液/beads, 迁移.
"""

from .manager.chemical_manager import ChemicalManager
from .config.setting import Settings, configure_logging
import json
import logging
import traceback

logger = logging.getLogger("ChemicalManagerCLI")

# 哨兵对象: 区分"正常返回 None"和"异常/中断导致的失败"
_SENTINEL_FAILED = object()


# ===================== 工具函数 =====================

def _input_with_default(prompt, default=None):
    """
    功能:
        带默认值的输入提示, 用户直接回车即采用默认值.
    参数:
        prompt: str, 提示文本.
        default: 默认值.
    返回:
        str, 用户输入或默认值.
    """
    if default is not None:
        display = f"{prompt} [默认: {default}]: "
    else:
        display = f"{prompt}: "
    val = input(display).strip()
    if val == "" and default is not None:
        return str(default)
    return val


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
        安全执行函数, 捕获异常并友好提示.
    参数:
        func: 可调用对象.
        *args, **kwargs: 透传参数.
    返回:
        func 的返回值, 异常时返回哨兵对象.
    """
    try:
        return func(*args, **kwargs)
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
        打印格式化菜单.
    参数:
        title: str, 菜单标题.
        options: list[tuple[str, str]], (编号, 描述) 列表.
    返回:
        None.
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
        格式化打印结果.
    参数:
        result: 可 JSON 序列化的对象.
    返回:
        None.
    """
    if result is None:
        return
    if isinstance(result, dict):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result)


# ===================== 摘要展示 =====================

def _print_search_results(results):
    """
    功能:
        格式化展示化学品库查询结果列表.
    参数:
        results: list, search 返回的匹配结果列表.
    返回:
        None.
    """
    print(f"找到 {len(results)} 条匹配结果:")
    for idx, item in enumerate(results, start=1):
        row_data = item.get("row_data") or {}
        cas = str(row_data.get("cas_number") or "").strip()
        name = str(
            row_data.get("substance")
            or row_data.get("substance_english_name")
            or ""
        ).strip()
        state = str(row_data.get("physical_state") or "").strip()
        form = str(row_data.get("physical_form") or "").strip()
        row_id = item.get("row_id", "")
        print(f"  [{idx}] CAS={cas}, 名称={name}, 物态={state}, 形态={form}, id={row_id}")


def _print_chemical_append_summary(result, *, source_label="查询"):
    """
    功能:
        输出化学品追加成功结果摘要.
    参数:
        result: dict, 化学品追加结果.
        source_label: str, 成功来源标识.
    返回:
        None.
    """
    if isinstance(result, dict) is False:
        return

    row_data = result.get("row_data") or {}
    if isinstance(row_data, dict) is False:
        row_data = {}

    cas_number = str(row_data.get("cas_number") or "").strip()
    display_name = str(
        row_data.get("substance")
        or row_data.get("substance_english_name")
        or ""
    ).strip()
    row_id = result.get("row_id")
    substance = str(row_data.get("substance") or "").strip()
    physical_state = str(row_data.get("physical_state") or "").strip()
    physical_form = str(row_data.get("physical_form") or "").strip()

    print(
        f"已成功添加化合物: CAS={cas_number}, 名称={display_name}, "
        f"substance={substance}, physical_state={physical_state}, "
        f"physical_form={physical_form}, id={row_id}"
    )


def _print_prepared_chemical_summary(result):
    """
    功能:
        输出溶液或 beads 派生条目的精简摘要与配制结果.
    参数:
        result: dict, prepare_solution_or_beads 的返回结果.
    返回:
        None.
    """
    if isinstance(result, dict) is False:
        return

    base_row_data = result.get("base_row_data") or {}
    derived_row_data = result.get("derived_row_data") or {}
    recipe = result.get("recipe") or {}

    base_name = str(
        base_row_data.get("base_substance")
        or base_row_data.get("substance")
        or base_row_data.get("substance_english_name")
        or ""
    ).strip()
    derived_name = str(
        derived_row_data.get("substance")
        or derived_row_data.get("substance_english_name")
        or ""
    ).strip()
    base_created = bool(result.get("base_created"))
    derived_row_id = result.get("derived_row_id")
    instruction_text = str(recipe.get("instruction_text") or "").strip()

    base_source_text = "新补录母体" if base_created is True else "复用现有母体"
    print(f"母体条目: 名称={base_name}, 来源={base_source_text}")
    print(f"已成功添加派生条目: 名称={derived_name}, id={derived_row_id}")
    if instruction_text != "":
        print(f"配制结果: {instruction_text}")


# ===================== 子菜单 =====================

def _menu_search_chemical(mgr):
    """查询化学品库子菜单"""
    query_type_options = [
        ("1", "CAS 号"),
        ("2", "名称"),
        ("3", "SMILES 结构式"),
        ("0", "返回"),
    ]
    _print_menu("查询类型", query_type_options)
    sub_choice = input("请选择查询类型: ").strip()

    query_type_map = {"1": "cas", "2": "name", "3": "smiles"}
    prompt_map = {
        "1": "请输入 CAS 号: ",
        "2": "请输入化学品名称 (中文或英文): ",
        "3": "请输入 SMILES 结构式: ",
    }

    if sub_choice not in query_type_map:
        return

    query = input(prompt_map[sub_choice]).strip()
    if query == "":
        print("输入不能为空")
        _pause()
        return

    query_type = query_type_map[sub_choice]
    results = _safe_run(mgr.search, query, query_type)

    if results is None:
        results = []

    if len(results) > 0:
        _print_search_results(results)
    else:
        print("未找到匹配的化学品")
        add_choice = input("是否在线查询并添加? (y/n): ").strip().lower()
        if add_choice == "y":
            add_result = _safe_run(mgr.lookup_and_append, query, query_type)
            if add_result is None:
                print("在线查询未找到化合物信息")
            elif add_result.get("duplicate") is True:
                print(f"该化合物已存在于化学品库, 名称: {add_result.get('duplicate_substance', '')}")
            else:
                _print_chemical_append_summary(add_result, source_label="在线查询")
    _pause()


def _menu_add_chemical(mgr):
    """在线查询并添加化学品子菜单"""
    query_type_options = [
        ("1", "CAS 号"),
        ("2", "名称"),
        ("3", "SMILES 结构式"),
        ("0", "返回"),
    ]
    _print_menu("查询类型", query_type_options)
    sub_choice = input("请选择查询类型: ").strip()

    query_type_map = {"1": "cas", "2": "name", "3": "smiles"}
    prompt_map = {
        "1": "请输入 CAS 号: ",
        "2": "请输入化学品名称 (中文或英文): ",
        "3": "请输入 SMILES 结构式: ",
    }

    if sub_choice not in query_type_map:
        return

    query = input(prompt_map[sub_choice]).strip()
    if query == "":
        print("输入不能为空")
        _pause()
        return

    query_type = query_type_map[sub_choice]
    result = _safe_run(mgr.lookup_and_append, query, query_type)
    if result is None:
        print("未查询到化合物信息, 请检查后重试")
    elif result.get("duplicate") is True:
        print(f"该化合物已存在于化学品库, 名称: {result.get('duplicate_substance', '')}")
    else:
        _print_chemical_append_summary(result, source_label="在线查询")
    _pause()


def _menu_prepare_solution_or_beads(mgr):
    """配置溶液或 beads 并添加到化学品库子菜单"""
    # 第1步: 选择查询类型
    query_type_options = [
        ("1", "CAS号"),
        ("2", "名称"),
        ("3", "SMILES结构式"),
        ("0", "返回"),
    ]
    _print_menu("选择查询类型", query_type_options)
    type_choice = input("请选择查询类型: ").strip()

    query_type_map = {"1": "cas", "2": "name", "3": "smiles"}
    prompt_map = {
        "1": "请输入CAS号: ",
        "2": "请输入化学品名称(中文或英文): ",
        "3": "请输入SMILES结构式: ",
    }

    if type_choice not in query_type_map:
        return

    # 第2步: 输入查询内容
    query = input(prompt_map[type_choice]).strip()
    if query == "":
        print("输入不能为空")
        _pause()
        return

    query_type = query_type_map[type_choice]

    # 第3步: 查询化学品库
    results = _safe_run(mgr.search, query, query_type)
    if results is None:
        results = []

    identifier = None

    if len(results) > 0:
        # 展示结果, 用户选择母体
        _print_search_results(results)
        select_input = input("请输入编号选择母体(0返回): ").strip()
        if select_input == "0" or select_input == "":
            return
        try:
            select_idx = int(select_input) - 1
        except ValueError:
            print("请输入数字")
            _pause()
            return
        if select_idx < 0 or select_idx >= len(results):
            print("编号超出范围")
            _pause()
            return

        selected_row_data = results[select_idx].get("row_data") or {}
        identifier = str(selected_row_data.get("cas_number") or "").strip()
        if identifier == "":
            print("所选条目缺少CAS号, 无法用于配置溶液或beads")
            _pause()
            return
    else:
        # 未找到, 询问是否在线添加
        print("未在化学品库中找到匹配的化学品")
        print("  1. 在线查询并添加母体")
        print("  2. 返回")
        add_choice = input("请选择: ").strip()
        if add_choice != "1":
            return

        add_result = _safe_run(mgr.lookup_and_append, query, query_type)
        if add_result is None:
            print("在线查询未找到化合物信息")
            _pause()
            return
        if add_result.get("duplicate") is True:
            print(f"该化合物已存在于化学品库, 名称: {add_result.get('duplicate_substance', '')}")
            _pause()
            return

        _print_chemical_append_summary(add_result, source_label="在线查询")
        row_data = add_result.get("row_data") or {}
        identifier = str(row_data.get("cas_number") or "").strip()
        if identifier == "":
            print("添加的条目缺少CAS号, 无法继续配置")
            _pause()
            return

    # 选择派生形态
    form_options = [
        ("1", "溶液(solution)"),
        ("2", "Beads"),
        ("0", "返回"),
    ]
    _print_menu("选择派生形态", form_options)
    form_choice = input("请选择派生形态: ").strip()

    form_map = {"1": "solution", "2": "beads"}
    prepared_form = form_map.get(form_choice)
    if prepared_form is None:
        return

    # 输入参数并执行
    if prepared_form == "solution":
        solvent_name = input("请输入溶剂名称: ").strip()
        concentration_mol_l = _input_positive_float("请输入目标浓度(mol/L)")
        target_volume_ml = _input_positive_float("请输入目标定容体积(mL)")
        result = _safe_run(
            mgr.prepare_solution_or_beads,
            identifier,
            prepared_form,
            solvent_name=solvent_name,
            active_content=concentration_mol_l,
            target_volume_ml=target_volume_ml,
        )
    else:
        wt_percent = _input_positive_float("请输入载量(wt%)")
        target_active_mmol = _input_positive_float("请输入目标活性(mmol)")
        result = _safe_run(
            mgr.prepare_solution_or_beads,
            identifier,
            prepared_form,
            active_content=wt_percent,
            target_active_mmol=target_active_mmol,
        )

    if result is None:
        print("未完成派生条目添加, 请检查输入或确认该条目是否已存在")
    elif result.get("duplicate") is True:
        print(f"该化合物已存在于化学品库, 名称: {result.get('duplicate_substance', '')}")
    else:
        _print_prepared_chemical_summary(result)
    _pause()


def _menu_migrate_excel(mgr):
    """从 Excel 迁移到 SQLite 子菜单"""
    from .utils.migration import migrate_excel_to_sqlite

    excel_path = _input_with_default("Excel 文件路径", "chemical_list.xlsx")
    dry_run_input = input("是否仅预览不写入? (y/n) [默认: n]: ").strip().lower()
    dry_run = dry_run_input == "y"

    result = _safe_run(migrate_excel_to_sqlite, excel_path, dry_run=dry_run)
    if result is not None and result is not _SENTINEL_FAILED:
        print(f"迁移结果: 成功={result['migrated']}, 跳过={result['skipped']}, 失败={result['failed']}")
    _pause()


# ===================== 主菜单 =====================

def chemical_library_menu(synthesis_manager=None):
    """
    功能:
        化学品库管理主菜单.
        可独立运行或从 eit_synthesis_station 菜单调用.
    参数:
        synthesis_manager: 可选, 合成工位管理器实例 (兼容旧调用).
    返回:
        None.
    """
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    mgr = ChemicalManager.get_shared(settings)

    options = [
        ("1", "导出化学品到CSV"),
        ("2", "化学品库去重"),
        ("3", "化学品库数据校验"),
        ("4", "查询化学品库"),
        ("5", "在线查询并添加化学品"),
        ("6", "配置溶液或beads并添加到化学品库"),
        ("7", "从Excel迁移化学品库到SQLite"),
        ("0", "返回上级菜单"),
    ]

    while True:
        _print_menu("化学品库管理", options)
        choice = input("请选择操作: ").strip()

        if choice == "0":
            return
        elif choice == "1":
            path = _input_with_default("导出文件路径", "chemicals_list_export.csv")
            _safe_run(mgr.export_to_csv, path)
        elif choice == "2":
            result = _safe_run(mgr.deduplicate)
            if result is not None and result is not _SENTINEL_FAILED:
                print(f"去重完成, 删除 {result} 条重复记录")
            _pause()
        elif choice == "3":
            result = _safe_run(mgr.check_integrity)
            _print_result(result)
            _pause()
        elif choice == "4":
            _menu_search_chemical(mgr)
        elif choice == "5":
            _menu_add_chemical(mgr)
        elif choice == "6":
            _menu_prepare_solution_or_beads(mgr)
        elif choice == "7":
            _menu_migrate_excel(mgr)
        else:
            print("无效选择, 请重新输入")


def interactive():
    """
    功能:
        驱动的交互式 CLI 入口.
    """
    chemical_library_menu()
