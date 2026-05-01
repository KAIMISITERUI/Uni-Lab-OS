# -*- coding: utf-8 -*-
"""
功能:
    AI 助手工具注册表. 把 LLM 可调用的函数集中收敛, 拆成 read (自动执行) 与 control (HITL).
    每个工具持有 OpenAI tools 协议的 JSON Schema (供 LLM 决策) 与 handler (实际执行).
    工具直接调用既有 store 单例 / sampler / context, 不再叠加 service 层, 保持最短路径.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from ...services.maintenance_store import MaintenanceStore

logger = logging.getLogger("EITHubAiAgentTools")

JsonDict = Dict[str, Any]
ToolHandler = Callable[[JsonDict], JsonDict]

# 工具类别常量
KIND_READ = "read"
KIND_CONTROL = "control"


@dataclass
class ToolSpec:
    """
    功能:
        工具元信息. kind 决定是否走 HITL.
    参数:
        name: str, OpenAI 协议要求的函数名.
        kind: str, read 或 control.
        description: str, 给 LLM 的中文工具说明.
        parameters: Dict, JSON Schema (类型为 object).
        handler: Callable, 接收已解析参数字典, 返回结果字典.
    """

    name: str
    kind: str
    description: str
    parameters: JsonDict
    handler: ToolHandler

    def to_openai_tool(self) -> JsonDict:
        """
        功能:
            转成 OpenAI Chat Completions 协议的 tools 列表元素.
        返回:
            Dict, OpenAI tools 数组的单个元素.
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# ---------- handler 实现 (直调既有单例, 不通过 HTTP) ----------

_maintenance_store_singleton: Optional[MaintenanceStore] = None


def _maintenance_store() -> MaintenanceStore:
    """
    功能:
        懒加载并复用 MaintenanceStore 单例, 避免每次工具调用重新打开 JSON 文件.
    返回:
        MaintenanceStore, 单例实例.
    """
    global _maintenance_store_singleton
    if _maintenance_store_singleton is None:
        _maintenance_store_singleton = MaintenanceStore()
    return _maintenance_store_singleton


def _handle_get_maintenance_overview(args: JsonDict) -> JsonDict:
    """
    功能:
        取指定日期的运维待办与逾期总览.
    参数:
        args: Dict, 含可选 date (YYYY-MM-DD).
    返回:
        Dict, 运维总览.
    """
    from datetime import date as _date

    date_text = args.get("date") or _date.today().isoformat()
    return _maintenance_store().build_overview(date_text)


def _handle_list_maintenance_records(args: JsonDict) -> JsonDict:
    """
    功能:
        查询日期范围内的运维记录.
    参数:
        args: Dict, 含可选 start_date 与 end_date.
    返回:
        Dict, 含 records 列表与 total.
    """
    from datetime import date as _date, timedelta

    start_date = args.get("start_date") or (_date.today() - timedelta(days=7)).isoformat()
    end_date = args.get("end_date") or _date.today().isoformat()
    return _maintenance_store().list_records(start_date, end_date)


def _handle_list_maintenance_events(args: JsonDict) -> JsonDict:
    """
    功能:
        列出全部运维事件配置.
    参数:
        args: Dict, 无参数, 占位.
    返回:
        Dict, 含 events 列表与 total.
    """
    events = _maintenance_store().list_events()
    return {"events": events, "total": len(events)}


def _handle_list_recent_tasks(args: JsonDict) -> JsonDict:
    """
    功能:
        列出最近的合成任务. 通过 task_history 路由的内部扫描函数实现, 不重复磁盘读.
    参数:
        args: Dict, 含可选 query (关键词) 和可选 limit.
    返回:
        Dict, 含 items 列表与 total, items 字段裁剪到 LLM 可读的最小集合.
    """
    from ...routers.task_history import _list_task_items

    query = str(args.get("query") or "").strip()
    limit_raw = args.get("limit")
    limit_int = int(limit_raw) if isinstance(limit_raw, (int, float)) else 20
    if limit_int <= 0:
        limit_int = 20
    if limit_int > 100:
        limit_int = 100

    items = _list_task_items(query)
    truncated = items[:limit_int]
    payload_items: List[JsonDict] = [
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


def _handle_get_agv_status(args: JsonDict) -> JsonDict:
    """
    功能:
        从 AgvStatusCache 单例读取 AGV 当前状态字段, 不触发底层 IO.
    参数:
        args: Dict, 无参数.
    返回:
        Dict, AGV 状态摘要 (站点, 电量, 是否移动, TCP 位姿等).
    """
    from ...deps import get_agv_status_cache

    cache = get_agv_status_cache()
    field_max_age_s = 5.0
    return {
        "station": cache.get("station", field_max_age_s),
        "battery": cache.get("battery", field_max_age_s),
        "nav_task": cache.get("nav_task", field_max_age_s),
        "is_moving": cache.get("is_moving", field_max_age_s),
        "tcp_pose": cache.get("tcp_pose", field_max_age_s),
        "joints": cache.get("joints", field_max_age_s),
        "slots": cache.get("slots", field_max_age_s),
        "gripper_state": cache.get("gripper_state", field_max_age_s),
    }


def _handle_get_device_overview(args: JsonDict) -> JsonDict:
    """
    功能:
        返回外部设备 TCP 端口连通性总览, 直调 devices 路由的内部检查函数.
    参数:
        args: Dict, 无参数.
    返回:
        Dict, 含 items (设备状态列表).
    """
    from ...routers.devices import _build_external_device_statuses

    items = _build_external_device_statuses()
    return {"items": items, "total": len(items)}


def _handle_search_chemical(args: JsonDict) -> JsonDict:
    """
    功能:
        在化学品库中按关键词模糊搜索, 直调 ChemicalManager 单例.
    参数:
        args: Dict, 含 keyword (必填), 可选 limit.
    返回:
        Dict, 含 items 列表与 total.
    """
    from unilabos.devices.eit_chemical_manager.manager.chemical_manager import ChemicalManager

    keyword = str(args.get("keyword") or "").strip()
    if keyword == "":
        raise ValueError("keyword 不能为空")
    limit_raw = args.get("limit")
    limit_int = int(limit_raw) if isinstance(limit_raw, (int, float)) else 10
    if limit_int <= 0:
        limit_int = 10
    if limit_int > 50:
        limit_int = 50

    manager = ChemicalManager.get_shared()
    hits = manager.search(keyword)
    rows = [hit.get("row_data") for hit in hits if isinstance(hit, dict) is True]
    truncated = rows[:limit_int]
    return {"items": truncated, "total": len(rows), "returned": len(truncated)}


def _handle_submit_maintenance_records(args: JsonDict) -> JsonDict:
    """
    功能:
        批量提交运维完成记录 (控制类工具, 必须走 HITL).
    参数:
        args: Dict, 含 date, operator, items (event_id, due_date?, value_text?, note?).
    返回:
        Dict, 含 saved_count 与 records.
    """
    return _maintenance_store().save_batch_records(args)


def _handle_update_maintenance_event(args: JsonDict) -> JsonDict:
    """
    功能:
        更新单个运维事件配置 (控制类工具, 必须走 HITL).
    参数:
        args: Dict, 含 event_id 以及 station/title/start_date/interval_days/enabled/sort_order.
    返回:
        Dict, 更新后的事件.
    """
    event_id = str(args.get("event_id") or "").strip()
    if event_id == "":
        raise ValueError("event_id 不能为空")
    payload = {key: value for key, value in args.items() if key != "event_id"}
    return _maintenance_store().update_event(event_id, payload)


# ---------- 工具注册 ----------

_TOOLS: Dict[str, ToolSpec] = {}


def _register(spec: ToolSpec) -> None:
    """
    功能:
        把 ToolSpec 注册到全局表, 名称重复时报错.
    参数:
        spec: ToolSpec, 工具描述.
    返回:
        None.
    """
    if spec.name in _TOOLS:
        raise RuntimeError(f"工具名称重复: {spec.name}")
    _TOOLS[spec.name] = spec


_register(
    ToolSpec(
        name="get_maintenance_overview",
        kind=KIND_READ,
        description="查询指定日期的运维待办、逾期与完成统计. 参数 date 留空则取今天.",
        parameters={
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "目标日期, 格式 YYYY-MM-DD, 留空表示今天."}
            },
            "required": [],
        },
        handler=_handle_get_maintenance_overview,
    )
)

_register(
    ToolSpec(
        name="list_maintenance_records",
        kind=KIND_READ,
        description="按日期范围查询已提交的运维完成记录. 留空时默认查询最近 7 天.",
        parameters={
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "起始日期 YYYY-MM-DD, 留空为 7 天前."},
                "end_date": {"type": "string", "description": "结束日期 YYYY-MM-DD, 留空为今天."},
            },
            "required": [],
        },
        handler=_handle_list_maintenance_records,
    )
)

_register(
    ToolSpec(
        name="list_maintenance_events",
        kind=KIND_READ,
        description="列出全部运维事件配置 (即定期检查清单).",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=_handle_list_maintenance_events,
    )
)

_register(
    ToolSpec(
        name="list_recent_tasks",
        kind=KIND_READ,
        description="列出最近的合成任务. 可用 query 模糊匹配任务 ID 或名称, limit 控制条数 (1-100).",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词, 留空表示不过滤."},
                "limit": {"type": "integer", "description": "返回条数, 默认 20, 上限 100."},
            },
            "required": [],
        },
        handler=_handle_list_recent_tasks,
    )
)

_register(
    ToolSpec(
        name="get_agv_status",
        kind=KIND_READ,
        description="获取 AGV 当前位置、电量、导航任务、机械臂关节、夹爪等实时状态字段.",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=_handle_get_agv_status,
    )
)

_register(
    ToolSpec(
        name="get_device_overview",
        kind=KIND_READ,
        description="检查所有外部设备的 TCP 端口连通性, 用于排查设备网络问题.",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=_handle_get_device_overview,
    )
)

_register(
    ToolSpec(
        name="search_chemical",
        kind=KIND_READ,
        description="在化学品库按关键词模糊搜索, 返回 CAS 号、中英文名、危险等级等核心字段.",
        parameters={
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "搜索关键词, 可为名称、CAS 号等."},
                "limit": {"type": "integer", "description": "返回条数, 默认 10, 上限 50."},
            },
            "required": ["keyword"],
        },
        handler=_handle_search_chemical,
    )
)

_register(
    ToolSpec(
        name="submit_maintenance_records",
        kind=KIND_CONTROL,
        description=(
            "批量提交运维完成记录 (写操作, 必须由用户确认). 参数包含提交日期、操作人姓名、"
            "以及若干运维事项 (含 event_id, 可选 due_date / value_text / note)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "提交日期 YYYY-MM-DD."},
                "operator": {"type": "string", "description": "操作人姓名."},
                "items": {
                    "type": "array",
                    "description": "运维事项列表, 至少 1 条.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "event_id": {"type": "string", "description": "运维事件 ID."},
                            "due_date": {
                                "type": "string",
                                "description": "到期日期 YYYY-MM-DD, 缺省时使用提交日期.",
                            },
                            "value_text": {"type": "string", "description": "运维信息说明 (可空)."},
                            "note": {"type": "string", "description": "备注 (可空)."},
                        },
                        "required": ["event_id"],
                    },
                },
            },
            "required": ["date", "operator", "items"],
        },
        handler=_handle_submit_maintenance_records,
    )
)

_register(
    ToolSpec(
        name="update_maintenance_event",
        kind=KIND_CONTROL,
        description=(
            "更新单个运维事件配置 (写操作, 必须由用户确认). 参数包含事件 ID 与全部需更新字段, "
            "字段语义与新建运维事件一致."
        ),
        parameters={
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "运维事件 ID."},
                "station": {"type": "string", "description": "工站名称."},
                "title": {"type": "string", "description": "检查内容标题."},
                "start_date": {"type": "string", "description": "开始日期 YYYY-MM-DD."},
                "interval_days": {"type": "integer", "description": "间隔天数, 必须为正整数."},
                "enabled": {"type": "boolean", "description": "是否启用."},
                "sort_order": {"type": "integer", "description": "排序值."},
            },
            "required": ["event_id", "station", "title", "start_date", "interval_days"],
        },
        handler=_handle_update_maintenance_event,
    )
)


def list_tools() -> List[ToolSpec]:
    """
    功能:
        返回全部已注册工具的列表, 顺序与注册顺序一致.
    返回:
        List[ToolSpec], 工具列表.
    """
    return list(_TOOLS.values())


def get_tool(name: str) -> ToolSpec:
    """
    功能:
        按名称查找工具, 不存在时抛 KeyError.
    参数:
        name: str, 工具名称.
    返回:
        ToolSpec, 工具描述.
    """
    if name not in _TOOLS:
        raise KeyError(f"未注册的工具: {name}")
    return _TOOLS[name]


def build_openai_tools_payload() -> List[JsonDict]:
    """
    功能:
        组装 OpenAI tools 数组, 直接拼接到 chat completions 请求.
    返回:
        List[Dict], 全部工具 spec 的 OpenAI 格式.
    """
    return [spec.to_openai_tool() for spec in _TOOLS.values()]
