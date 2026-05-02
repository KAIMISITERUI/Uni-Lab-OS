# -*- coding: utf-8 -*-
"""
功能:
    合成工站和任务历史相关工具定义.
    覆盖反应模板读写, 历史方案查询载入, 上传任务, 物料核算, 上料表读写, 试剂标签和上料表打印.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .base import EmptyInput, GenericToolOutput, ToolCategory, ToolPermission, ToolSpec
from .registry import ToolRegistry

logger = logging.getLogger("EITHubAiAgentSynthesisTools")

JsonDict = Dict[str, Any]


class ListRecentTasksInput(BaseModel):
    """
    功能:
        最近合成任务查询输入.
    参数:
        query: Optional[str], 搜索关键词.
        limit: Optional[int], 返回条数.
    """

    model_config = ConfigDict(extra="forbid")

    query: Optional[str] = Field(default=None, description="搜索关键词, 留空表示不过滤.")
    limit: Optional[int] = Field(default=20, description="返回条数, 默认 20, 上限 100.")


def _handle_list_recent_tasks(model: BaseModel) -> JsonDict:
    """
    功能:
        列出最近的合成任务, 复用 task_history 路由内部扫描函数.
    参数:
        model: BaseModel, ListRecentTasksInput.
    返回:
        Dict[str, Any], 任务列表.
    """
    from ....routers.task_history import _list_task_items

    args = model.model_dump()
    query = str(args.get("query") or "").strip()
    limit_raw = args.get("limit")
    limit_int = int(limit_raw) if isinstance(limit_raw, (int, float)) is True else 20
    if limit_int <= 0:
        limit_int = 20
    if limit_int > 100:
        limit_int = 100

    items = _list_task_items(query)
    truncated = items[:limit_int]
    payload_items = [
        {
            "task_id": item.task_id,
            "task_name": item.task_name,
            "status": item.status,
            "created_at": item.created_at,
            "started_at": item.started_at,
            "completed_at": item.completed_at,
        }
        for item in truncated
    ]
    return {"items": payload_items, "total": len(items), "returned": len(payload_items)}


def _handle_read_reaction_template(model: BaseModel) -> JsonDict:
    """
    功能:
        读取当前 reaction_template.xlsx 的完整结构, 供 AI 了解界面上已有内容.
    参数:
        model: BaseModel, 空输入.
    返回:
        Dict[str, Any], 模板结构, 包含 params, headers, rows, gc_ms_yield 等.
    """
    from ....excel_codec import DEFAULT_REACTION_TEMPLATE, read_reaction_template

    return read_reaction_template(DEFAULT_REACTION_TEMPLATE)


class ListReactionTemplateHistoryInput(BaseModel):
    """
    功能:
        历史实验模板分页查询输入.
    参数:
        query: Optional[str], 实验名称搜索关键词.
        page: Optional[int], 页码, 从 1 开始.
        page_size: Optional[int], 每页条数, 上限 100.
    """

    model_config = ConfigDict(extra="forbid")

    query: Optional[str] = Field(default=None, description="按实验名称模糊搜索, 留空返回全部.")
    page: Optional[int] = Field(default=1, description="页码, 从 1 开始.")
    page_size: Optional[int] = Field(default=10, description="每页条数, 默认 10, 上限 100.")


def _handle_list_reaction_template_history(model: BaseModel) -> JsonDict:
    """
    功能:
        列出可载入的历史实验模板摘要, 复用 routers.synthesis 的扫描函数.
    参数:
        model: BaseModel, ListReactionTemplateHistoryInput.
    返回:
        Dict[str, Any], 包含 total/page/page_size/items 的分页结果.
    """
    from ....routers.synthesis import _list_reaction_template_history

    args = model.model_dump()
    query = str(args.get("query") or "").strip()
    page_raw = args.get("page")
    page_int = int(page_raw) if isinstance(page_raw, (int, float)) is True else 1
    if page_int < 1:
        page_int = 1
    size_raw = args.get("page_size")
    size_int = int(size_raw) if isinstance(size_raw, (int, float)) is True else 10
    if size_int < 1:
        size_int = 10
    if size_int > 100:
        size_int = 100

    items = _list_reaction_template_history(query_text=query if query != "" else None)
    start = (page_int - 1) * size_int
    end = start + size_int
    return {
        "total": len(items),
        "page": page_int,
        "page_size": size_int,
        "items": items[start:end],
    }


class LoadReactionTemplateHistoryInput(BaseModel):
    """
    功能:
        载入历史实验模板的输入.
    参数:
        task_id: int, 历史任务 ID.
    """

    model_config = ConfigDict(extra="forbid")

    task_id: int = Field(description="历史任务 ID, 从 list_reaction_template_history 获取.")


def _handle_load_reaction_template_history(model: BaseModel) -> JsonDict:
    """
    功能:
        读取指定历史任务的完整模板结构, 不写入当前模板文件.
    参数:
        model: BaseModel, LoadReactionTemplateHistoryInput.
    返回:
        Dict[str, Any], 历史模板结构, 与 read_reaction_template 同形.
    """
    from ....excel_codec import read_reaction_template
    from ....routers.synthesis import _find_history_reaction_template_path

    args = model.model_dump()
    task_id = int(args["task_id"])
    history_path = _find_history_reaction_template_path(task_id)
    return read_reaction_template(history_path)


class SaveReactionTemplateInput(BaseModel):
    """
    功能:
        保存反应模板到磁盘的输入.
    参数:
        template: Dict[str, Any], 与 read_reaction_template 同形的完整 payload.
            必填顶层字段:
                params: Dict[str, Any], 25 项参数, 字段名按 PARAMETER_NAMES.
                headers: List[str], 试剂表表头.
                rows: List[List[Any]], 试剂表行数据, 行数必须是 12, 24, 36, 48 之一.
            可选顶层字段:
                gc_ms_yield: Dict[str, Any], 含 internal_standard_smiles,
                    internal_standard_expected_rt, yield_method, curve_slope,
                    curve_intercept, response_factor, products[].
    """

    model_config = ConfigDict(extra="forbid")

    template: Dict[str, Any] = Field(
        description=(
            "完整反应模板 payload. 必须包含 params(25 项参数), headers, rows, "
            "可选 gc_ms_yield. 字段含义和取值范围以 experiment-method-fill skill 的 "
            "field-spec.md 为准."
        )
    )


def _handle_save_reaction_template(model: BaseModel) -> JsonDict:
    """
    功能:
        将 AI 生成的完整模板写入磁盘, 不上传任务. 用户可在网页表格上检查修改.
    参数:
        model: BaseModel, SaveReactionTemplateInput.
    返回:
        Dict[str, Any], 写入后重新读取的模板结构, 含 sheet_name, params, reagent_pair_count.
    """
    from ....excel_codec import DEFAULT_REACTION_TEMPLATE, write_reaction_template

    args = model.model_dump()
    template = args.get("template")
    if isinstance(template, dict) is False:
        raise ValueError("template 必须是字典")

    saved = write_reaction_template(template, DEFAULT_REACTION_TEMPLATE)
    return {
        "sheet_name": saved.get("sheet_name"),
        "params": saved.get("params"),
        "reagent_pair_count": saved.get("reagent_pair_count"),
        "message": "已保存模板到网页表格, 请在任务编辑页面检查并修改.",
    }


class SubmitReactionTemplateInput(BaseModel):
    """
    功能:
        上传当前磁盘上反应模板的输入.
    参数:
        template: Optional[Dict[str, Any]], 可选完整 payload. 提供时先覆盖磁盘再上传; 留空时直接上传当前磁盘版本.
    """

    model_config = ConfigDict(extra="forbid")

    template: Optional[Dict[str, Any]] = Field(
        default=None,
        description="可选完整模板 payload. 留空使用磁盘当前版本(用户在网页修改并保存后的内容); 提供时会先覆盖磁盘再上传.",
    )


def _handle_submit_reaction_template(model: BaseModel) -> JsonDict:
    """
    功能:
        把磁盘上当前的 reaction_template.xlsx 同步到化学品库后创建合成任务.
        可选地在上传前先覆盖磁盘.
    参数:
        model: BaseModel, SubmitReactionTemplateInput.
    返回:
        Dict[str, Any], 含 task_id 和提示信息.
    """
    from ....deps import _get_shared_synthesis_manager
    from ....excel_codec import DEFAULT_REACTION_TEMPLATE, write_reaction_template

    args = model.model_dump()
    template = args.get("template")
    if template is not None:
        if isinstance(template, dict) is False:
            raise ValueError("template 必须是字典或留空")
        write_reaction_template(template, DEFAULT_REACTION_TEMPLATE)

    manager = _get_shared_synthesis_manager()
    manager.sync_chemicals_to_station()
    task_id = manager.create_task_by_file(str(DEFAULT_REACTION_TEMPLATE))
    return {
        "task_id": task_id,
        "message": "已上传任务到合成工站.",
    }


class RunResourceCheckInput(BaseModel):
    """
    功能:
        物料核算输入.
    参数:
        auto_generate_batch_file: bool, 是否同时自动修改上料表.
    """

    model_config = ConfigDict(extra="forbid")

    auto_generate_batch_file: bool = Field(
        default=True,
        description="是否在核算同时自动修改上料表, 默认 True.",
    )


def _handle_run_resource_check(model: BaseModel) -> JsonDict:
    """
    功能:
        基于当前 Excel 模板执行物料核算, 默认同步生成上料表.
    参数:
        model: BaseModel, RunResourceCheckInput.
    返回:
        Dict[str, Any], 核算结果, 由 SynthesisStationManager.check_resource_for_task 返回.
    """
    from ....deps import _get_shared_synthesis_manager
    from ....excel_codec import DEFAULT_REACTION_TEMPLATE

    args = model.model_dump()
    auto_generate = bool(args.get("auto_generate_batch_file", True))
    manager = _get_shared_synthesis_manager()
    return manager.check_resource_for_task(
        str(DEFAULT_REACTION_TEMPLATE),
        auto_generate_batch_file=auto_generate,
    )


def _handle_read_batch_in_template(model: BaseModel) -> JsonDict:
    """
    功能:
        读取当前上料表 batch_in_tray.xlsx 结构.
    参数:
        model: BaseModel, 空输入.
    返回:
        Dict[str, Any], 上料表结构, 包含 headers, rows, tray_type_options.
    """
    from ....excel_codec import DEFAULT_BATCH_IN_TEMPLATE, read_batch_in_template

    return read_batch_in_template(DEFAULT_BATCH_IN_TEMPLATE)


class SaveBatchInTemplateInput(BaseModel):
    """
    功能:
        覆盖保存上料表的输入.
    参数:
        rows: List[List[Any]], 上料表全部行, 列顺序与 BATCH_IN_HEADERS 一致.
    """

    model_config = ConfigDict(extra="forbid")

    rows: List[List[Any]] = Field(
        description="上料表行数据, 列顺序: position, tray_type, content, shelf_position, storage."
    )


def _handle_save_batch_in_template(model: BaseModel) -> JsonDict:
    """
    功能:
        将 AI 生成的上料表行数据覆盖保存到 batch_in_tray.xlsx.
    参数:
        model: BaseModel, SaveBatchInTemplateInput.
    返回:
        Dict[str, Any], 保存后重新读取的上料表结构.
    """
    from ....excel_codec import DEFAULT_BATCH_IN_TEMPLATE, write_batch_in_template

    args = model.model_dump()
    rows = args.get("rows")
    if isinstance(rows, list) is False:
        raise ValueError("rows 必须是列表")
    payload: JsonDict = {"rows": rows}
    return write_batch_in_template(payload, DEFAULT_BATCH_IN_TEMPLATE)


class PrintBatchInRequest(BaseModel):
    """
    功能:
        打印类工具的输入.
    参数:
        rows: Optional[List[List[Any]]], 留空时使用磁盘当前上料表; 提供时先覆盖再打印.
    """

    model_config = ConfigDict(extra="forbid")

    rows: Optional[List[List[Any]]] = Field(
        default=None,
        description="可选上料表行数据. 留空使用磁盘上现有上料表; 提供时会先覆盖保存再打印.",
    )


def _maybe_save_batch_in(rows: Optional[List[List[Any]]]) -> Optional[JsonDict]:
    """
    功能:
        若调用方提供 rows, 则先覆盖保存上料表, 否则直接返回 None.
    参数:
        rows: Optional[List[List[Any]]], 上料表行数据.
    返回:
        Optional[Dict[str, Any]], 保存后的上料表结构, 未保存时为 None.
    """
    if rows is None:
        return None
    from ....excel_codec import DEFAULT_BATCH_IN_TEMPLATE, write_batch_in_template

    return write_batch_in_template({"rows": rows}, DEFAULT_BATCH_IN_TEMPLATE)


def _handle_print_reagent_labels(model: BaseModel) -> JsonDict:
    """
    功能:
        打印当前上料表对应的试剂标签, 可选先覆盖保存上料表.
    参数:
        model: BaseModel, PrintBatchInRequest.
    返回:
        Dict[str, Any], 打印结果摘要.
    """
    from ....deps import _get_shared_synthesis_manager
    from ....excel_codec import DEFAULT_BATCH_IN_TEMPLATE

    args = model.model_dump()
    saved = _maybe_save_batch_in(args.get("rows"))
    manager = _get_shared_synthesis_manager()
    manager.print_reagent_labels()
    return {
        "printed": True,
        "file_path": saved.get("path", str(DEFAULT_BATCH_IN_TEMPLATE)) if saved is not None else str(DEFAULT_BATCH_IN_TEMPLATE),
        "message": "试剂标签打印任务已完成.",
    }


def _handle_print_batch_in_table(model: BaseModel) -> JsonDict:
    """
    功能:
        打印当前上料表 Excel, 可选先覆盖保存上料表.
    参数:
        model: BaseModel, PrintBatchInRequest.
    返回:
        Dict[str, Any], 打印任务结果.
    """
    from ....excel_codec import DEFAULT_BATCH_IN_TEMPLATE
    from ....excel_printing import DEFAULT_BATCH_IN_TABLE_PRINTER, print_batch_in_table

    args = model.model_dump()
    saved = _maybe_save_batch_in(args.get("rows"))
    result = print_batch_in_table(DEFAULT_BATCH_IN_TEMPLATE, DEFAULT_BATCH_IN_TABLE_PRINTER)
    if saved is not None:
        result["file_path"] = saved.get("path", result.get("file_path", str(DEFAULT_BATCH_IN_TEMPLATE)))
    elif result.get("file_path") is None:
        result["file_path"] = str(DEFAULT_BATCH_IN_TEMPLATE)
    return result


def register_tools(registry: ToolRegistry) -> None:
    """
    功能:
        注册合成工站工具.
    参数:
        registry: ToolRegistry, 目标注册表.
    返回:
        None.
    """
    registry.register(
        ToolSpec(
            name="list_recent_tasks",
            description="列出最近的合成任务. 可用 query 模糊匹配任务 ID 或名称, limit 控制条数.",
            input_model=ListRecentTasksInput,
            output_model=GenericToolOutput,
            permission=ToolPermission.READ,
            category=ToolCategory.SYNTHESIS,
            handler=_handle_list_recent_tasks,
        )
    )
    registry.register(
        ToolSpec(
            name="read_reaction_template",
            description="读取当前任务编辑界面的 reaction_template.xlsx 完整结构, 包含参数区, 试剂表和 GC 产率配置. 在写入新模板前应先调用以避免覆盖用户已填内容.",
            input_model=EmptyInput,
            output_model=GenericToolOutput,
            permission=ToolPermission.READ,
            category=ToolCategory.SYNTHESIS,
            handler=_handle_read_reaction_template,
        )
    )
    registry.register(
        ToolSpec(
            name="list_reaction_template_history",
            description="分页列出可载入的历史实验模板, 支持按实验名称模糊搜索. 用于"
            "用户希望以历史方案为底版时定位 task_id.",
            input_model=ListReactionTemplateHistoryInput,
            output_model=GenericToolOutput,
            permission=ToolPermission.READ,
            category=ToolCategory.SYNTHESIS,
            handler=_handle_list_reaction_template_history,
        )
    )
    registry.register(
        ToolSpec(
            name="load_reaction_template_history",
            description="按 task_id 读取历史实验模板的完整 payload, 仅读取不写盘. 适合作为新方案的起点.",
            input_model=LoadReactionTemplateHistoryInput,
            output_model=GenericToolOutput,
            permission=ToolPermission.READ,
            category=ToolCategory.SYNTHESIS,
            handler=_handle_load_reaction_template_history,
        )
    )
    registry.register(
        ToolSpec(
            name="save_reaction_template",
            description=(
                "把完整反应模板写入磁盘 Excel, 网页任务编辑表格会自动刷新. 不上传任务. "
                "用于让用户在网页里检查修改 AI 填好的方案. 这是控制类操作, 必须由用户确认后执行."
            ),
            input_model=SaveReactionTemplateInput,
            output_model=GenericToolOutput,
            permission=ToolPermission.CONTROL,
            category=ToolCategory.SYNTHESIS,
            handler=_handle_save_reaction_template,
        )
    )
    registry.register(
        ToolSpec(
            name="submit_reaction_template",
            description=(
                "上传磁盘当前反应模板到合成工站, 创建合成任务并返回 task_id. "
                "默认不带 template 直接上传(用户在网页修改并点击保存后的版本); "
                "若提供 template 则先覆盖磁盘再上传. 这是控制类操作, 必须由用户确认后执行."
            ),
            input_model=SubmitReactionTemplateInput,
            output_model=GenericToolOutput,
            permission=ToolPermission.CONTROL,
            category=ToolCategory.SYNTHESIS,
            handler=_handle_submit_reaction_template,
        )
    )
    registry.register(
        ToolSpec(
            name="run_resource_check",
            description=(
                "基于当前模板执行物料核算, 默认同时自动修改上料表. 这是控制类操作, "
                "必须由用户确认后执行. 应该在 save_and_submit_reaction_template 成功后再调用."
            ),
            input_model=RunResourceCheckInput,
            output_model=GenericToolOutput,
            permission=ToolPermission.CONTROL,
            category=ToolCategory.SYNTHESIS,
            handler=_handle_run_resource_check,
        )
    )
    registry.register(
        ToolSpec(
            name="read_batch_in_template",
            description="读取当前上料表 batch_in_tray.xlsx 全部行, 用于和用户确认是否需要修改.",
            input_model=EmptyInput,
            output_model=GenericToolOutput,
            permission=ToolPermission.READ,
            category=ToolCategory.SYNTHESIS,
            handler=_handle_read_batch_in_template,
        )
    )
    registry.register(
        ToolSpec(
            name="save_batch_in_template",
            description=(
                "覆盖保存上料表全部行. 这是控制类操作, 必须由用户确认后执行. "
                "rows 列顺序: position, tray_type, content, shelf_position, storage."
            ),
            input_model=SaveBatchInTemplateInput,
            output_model=GenericToolOutput,
            permission=ToolPermission.CONTROL,
            category=ToolCategory.SYNTHESIS,
            handler=_handle_save_batch_in_template,
        )
    )
    registry.register(
        ToolSpec(
            name="print_reagent_labels",
            description=(
                "打印试剂标签. 这是控制类操作, 必须由用户确认后执行. "
                "rows 留空时使用磁盘当前上料表; 提供 rows 时会先覆盖保存再打印."
            ),
            input_model=PrintBatchInRequest,
            output_model=GenericToolOutput,
            permission=ToolPermission.CONTROL,
            category=ToolCategory.SYNTHESIS,
            handler=_handle_print_reagent_labels,
        )
    )
    registry.register(
        ToolSpec(
            name="print_batch_in_table",
            description=(
                "打印上料表格. 这是控制类操作, 必须由用户确认后执行. "
                "rows 留空时使用磁盘当前上料表; 提供 rows 时会先覆盖保存再打印."
            ),
            input_model=PrintBatchInRequest,
            output_model=GenericToolOutput,
            permission=ToolPermission.CONTROL,
            category=ToolCategory.SYNTHESIS,
            handler=_handle_print_batch_in_table,
        )
    )
