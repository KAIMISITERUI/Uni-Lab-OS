# -*- coding: utf-8 -*-
"""
功能:
    提供 EIT Hub 运维管理数据存储服务.
    使用本地 JSON 保存运维事件和运维记录, 并按自定义间隔计算到期事项.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("EITHubMaintenanceStore")

JsonDict = Dict[str, Any]

MAINTENANCE_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "maintenance.json"
DEFAULT_DAILY_START_DATE = "2026-03-19"
DEFAULT_WEEKLY_MONDAY_START_DATE = "2026-03-23"

DEFAULT_EVENT_SPECS: Tuple[Tuple[str, str, str, int], ...] = (
    ("合成手套箱工站", "1. 中央氮气气压检查", DEFAULT_DAILY_START_DATE, 1),
    ("合成手套箱工站", "2. 手套箱垃圾箱清理, 超过2/3倒掉", DEFAULT_DAILY_START_DATE, 1),
    ("合成手套箱工站", "3. 手套箱水氧值检查(<0.01ppm)", DEFAULT_DAILY_START_DATE, 1),
    ("合成手套箱工站", "4. 清洗1min", DEFAULT_DAILY_START_DATE, 1),
    ("AGV", "1. 电量是否充足", DEFAULT_DAILY_START_DATE, 1),
    ("分析工站", "1. UPLC的Ar气量", DEFAULT_DAILY_START_DATE, 1),
    ("分析工站", "2. GC-MS的氮气量", DEFAULT_DAILY_START_DATE, 1),
    ("分析工站", "3. GC-MS的氦气量", DEFAULT_DAILY_START_DATE, 1),
    ("分析工站", "4. QTOF的LockSpray(B), 校正液(C), 和洗液量(甲醇), 小于1/4要补充", DEFAULT_DAILY_START_DATE, 1),
    ("分析工站", "7. UPLC的A相(水+0.1%甲酸). B相(乙腈+0.1%甲酸), 和洗液(水+0.1%甲酸), 小于1/4要补充", DEFAULT_DAILY_START_DATE, 1),
    ("分析工站", "8. 智达自动进样器的强洗(甲醇), 弱洗(甲醇:水, 1:1), 小于1/4要补充", DEFAULT_DAILY_START_DATE, 1),
    ("分析工站", "9. GC-MS洗液(乙酸乙酯), 小于1/2要补充", DEFAULT_DAILY_START_DATE, 1),
    ("分析工站", "8. 氢气发生器水位线, 小于1/2要补充", DEFAULT_DAILY_START_DATE, 1),
    ("分析工站", "9. QTOF,HPLC,UPLC三个废液桶", DEFAULT_DAILY_START_DATE, 1),
    ("分析工站", "10. GC-MS快速调谐, 每周一做", DEFAULT_WEEKLY_MONDAY_START_DATE, 7),
    ("分析工站", "11. UPLC-QTOF调谐, 每天做", DEFAULT_DAILY_START_DATE, 1),
    ("其它", "12. 实验室所有垃圾箱检查, 超过2/3倒掉", DEFAULT_DAILY_START_DATE, 1),
    ("其它", "13. 不用药品归位", DEFAULT_DAILY_START_DATE, 1),
    ("其它", "14. 备料区台面整理", DEFAULT_DAILY_START_DATE, 1),
)


class MaintenanceStore:
    """
    功能:
        管理运维事件, 运维记录和到期提醒.
    """

    def __init__(self, data_path: Path = MAINTENANCE_DATA_PATH) -> None:
        self._data_path = data_path
        self._lock = threading.Lock()

    def list_events(self) -> List[JsonDict]:
        """
        功能:
            读取全部运维事件.
        返回:
            List[Dict], 按排序字段和 ID 排列的运维事件.
        """
        with self._lock:
            payload = self._load_or_initialize()
            return self._sort_events(payload["events"])

    def create_event(self, event_payload: JsonDict) -> JsonDict:
        """
        功能:
            新增一个运维事件并保存.
        参数:
            event_payload: Dict, 已校验的事件字段.
        返回:
            Dict, 新增后的事件.
        """
        with self._lock:
            payload = self._load_or_initialize()
            now_text = _now_text()
            event = {
                "id": _new_event_id(payload["events"]),
                "station": _required_text(event_payload.get("station"), "工站名称"),
                "title": _required_text(event_payload.get("title"), "检查内容"),
                "start_date": _parse_date_text(event_payload.get("start_date"), "开始日期"),
                "interval_days": _positive_int(event_payload.get("interval_days"), "间隔天数"),
                "enabled": bool(event_payload.get("enabled", True)),
                "sort_order": _int_value(event_payload.get("sort_order", _next_sort_order(payload["events"])), "排序"),
                "created_at": now_text,
                "updated_at": now_text,
            }
            payload["events"].append(event)
            self._write_payload(payload)
        logger.info("运维事件已新增: %s", event["id"])
        return deepcopy(event)

    def update_event(self, event_id: str, event_payload: JsonDict) -> JsonDict:
        """
        功能:
            更新指定运维事件.
        参数:
            event_id: str, 运维事件 ID.
            event_payload: Dict, 已校验的事件字段.
        返回:
            Dict, 更新后的事件.
        """
        with self._lock:
            payload = self._load_or_initialize()
            event = _find_event(payload["events"], event_id)
            if event is None:
                raise KeyError(f"未找到运维事件: {event_id}")

            event["station"] = _required_text(event_payload.get("station"), "工站名称")
            event["title"] = _required_text(event_payload.get("title"), "检查内容")
            event["start_date"] = _parse_date_text(event_payload.get("start_date"), "开始日期")
            event["interval_days"] = _positive_int(event_payload.get("interval_days"), "间隔天数")
            event["enabled"] = bool(event_payload.get("enabled", True))
            event["sort_order"] = _int_value(event_payload.get("sort_order", event.get("sort_order", 0)), "排序")
            event["updated_at"] = _now_text()
            self._write_payload(payload)
        logger.info("运维事件已更新: %s", event_id)
        return deepcopy(event)

    def build_overview(self, target_date_text: str) -> JsonDict:
        """
        功能:
            构造指定日期的运维提醒总览.
        参数:
            target_date_text: str, 目标日期, 格式为 YYYY-MM-DD.
        返回:
            Dict, 包含当日事项, 逾期事项和统计信息.
        """
        target_date = _parse_date(target_date_text, "目标日期")
        with self._lock:
            payload = self._load_or_initialize()
            records_by_key = _records_by_event_due_date(payload["records"])
            due_items: List[JsonDict] = []
            overdue_items: List[JsonDict] = []
            due_count = 0
            completed_count = 0

            for event in self._sort_events(payload["events"]):
                if event.get("enabled") is not True:
                    continue
                if _is_due_on(event, target_date) is True:
                    due_count += 1
                    due_item = _build_due_item(event, target_date, records_by_key)
                    if due_item["completed"] is True:
                        completed_count += 1
                    else:
                        due_items.append(due_item)

                overdue_due_date = _latest_due_before(event, target_date)
                if overdue_due_date is None:
                    continue
                overdue_key = _record_key(str(event["id"]), overdue_due_date.isoformat())
                if overdue_key in records_by_key:
                    continue
                if _has_later_record(str(event["id"]), overdue_due_date, payload["records"]) is True:
                    continue
                overdue_items.append(_build_due_item(event, overdue_due_date, records_by_key))

        return {
            "date": target_date.isoformat(),
            "due_items": due_items,
            "overdue_items": overdue_items,
            "stats": {
                "due_count": due_count,
                "pending_count": len(due_items),
                "completed_count": completed_count,
                "overdue_count": len(overdue_items),
            },
        }

    def save_batch_records(self, submit_payload: JsonDict) -> JsonDict:
        """
        功能:
            批量保存运维完成记录, 同一 event_id 和 due_date 重复提交时更新原记录.
        参数:
            submit_payload: Dict, 包含提交日期, 操作人和记录列表.
        返回:
            Dict, 保存结果和记录列表.
        """
        submit_date_text = _parse_date_text(submit_payload.get("date"), "提交日期")
        operator = _required_text(submit_payload.get("operator"), "操作人")
        items = submit_payload.get("items")
        if isinstance(items, list) is False or len(items) == 0:
            raise ValueError("至少需要选择一条运维事项.")

        with self._lock:
            payload = self._load_or_initialize()
            records_by_key = _records_by_event_due_date(payload["records"])
            saved_records: List[JsonDict] = []
            now_text = _now_text()

            for item in items:
                if isinstance(item, dict) is False:
                    raise ValueError("运维记录项必须是对象.")
                event_id = _required_text(item.get("event_id"), "运维事件 ID")
                event = _find_event(payload["events"], event_id)
                if event is None:
                    raise KeyError(f"未找到运维事件: {event_id}")
                due_date_text = _parse_date_text(item.get("due_date", submit_date_text), "到期日期")
                due_date = _parse_date(due_date_text, "到期日期")
                if _is_due_on(event, due_date) is False:
                    raise ValueError(f"运维事项在 {due_date_text} 不到期: {event['title']}")

                key = _record_key(event_id, due_date_text)
                record = records_by_key.get(key)
                if record is None:
                    record = {
                        "record_id": uuid.uuid4().hex,
                        "event_id": event_id,
                        "due_date": due_date_text,
                        "created_at": now_text,
                    }
                    payload["records"].append(record)
                    records_by_key[key] = record

                record["station_snapshot"] = str(event["station"])
                record["title_snapshot"] = str(event["title"])
                record["operator"] = operator
                record["value_text"] = _optional_text(item.get("value_text"))
                record["note"] = _optional_text(item.get("note"))
                record["completed_at"] = now_text
                record["updated_at"] = now_text
                saved_records.append(deepcopy(record))

            self._write_payload(payload)
        logger.info("运维记录已批量保存, date=%s, count=%d", submit_date_text, len(saved_records))
        return {"saved_count": len(saved_records), "records": saved_records}

    def list_records(self, start_date_text: str, end_date_text: str) -> JsonDict:
        """
        功能:
            查询指定日期范围内的运维记录.
        参数:
            start_date_text: str, 起始日期, 格式为 YYYY-MM-DD.
            end_date_text: str, 结束日期, 格式为 YYYY-MM-DD.
        返回:
            Dict, 包含 records 列表和 total 数量.
        """
        start_date = _parse_date(start_date_text, "起始日期")
        end_date = _parse_date(end_date_text, "结束日期")
        if start_date > end_date:
            raise ValueError("起始日期不能晚于结束日期.")

        with self._lock:
            payload = self._load_or_initialize()
            records = []
            for record in payload["records"]:
                due_date = _parse_date(str(record.get("due_date", "")), "到期日期")
                if start_date <= due_date <= end_date:
                    records.append(deepcopy(record))
            records.sort(
                key=lambda item: (str(item.get("due_date", "")), str(item.get("completed_at", ""))),
                reverse=True,
            )
        return {"records": records, "total": len(records)}

    def _load_or_initialize(self) -> JsonDict:
        """
        功能:
            读取 JSON 数据文件, 不存在时创建默认数据文件.
        返回:
            Dict, 标准化后的存储数据.
        """
        if self._data_path.is_file() is False:
            payload = _default_payload()
            self._write_payload(payload)
            return payload

        try:
            payload = json.loads(self._data_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.exception("读取运维数据文件失败: %s", self._data_path)
            raise ValueError(f"读取运维数据文件失败: {exc}") from exc

        normalized = _normalize_payload(payload)
        return normalized

    def _write_payload(self, payload: JsonDict) -> None:
        """
        功能:
            将运维数据写入 JSON 文件.
        参数:
            payload: Dict, 标准化后的存储数据.
        返回:
            None.
        """
        self._data_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._data_path.with_suffix(f"{self._data_path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self._data_path)

    @staticmethod
    def _sort_events(events: List[JsonDict]) -> List[JsonDict]:
        """
        功能:
            按排序字段和 ID 返回事件副本.
        参数:
            events: List[Dict], 原始事件列表.
        返回:
            List[Dict], 排序后的事件副本.
        """
        return [
            deepcopy(event)
            for event in sorted(events, key=lambda item: (int(item.get("sort_order", 0)), str(item.get("id", ""))))
        ]


def _default_payload() -> JsonDict:
    """
    功能:
        构造默认运维事件数据.
    返回:
        Dict, 默认 JSON payload.
    """
    now_text = _now_text()
    events: List[JsonDict] = []
    for index, (station, title, start_date_text, interval_days) in enumerate(DEFAULT_EVENT_SPECS, start=1):
        events.append(
            {
                "id": f"maintenance-{index:03d}",
                "station": station,
                "title": title,
                "start_date": start_date_text,
                "interval_days": interval_days,
                "enabled": True,
                "sort_order": index * 10,
                "created_at": now_text,
                "updated_at": now_text,
            }
        )
    return {"version": 1, "events": events, "records": []}


def _normalize_payload(payload: Any) -> JsonDict:
    """
    功能:
        校验并标准化 JSON 文件结构.
    参数:
        payload: Any, 解析后的 JSON 内容.
    返回:
        Dict, 标准化后的数据.
    """
    if isinstance(payload, dict) is False:
        raise ValueError("运维数据文件格式错误, 根节点必须是对象.")
    events = payload.get("events")
    records = payload.get("records")
    if isinstance(events, list) is False:
        raise ValueError("运维数据文件格式错误, events 必须是列表.")
    if isinstance(records, list) is False:
        raise ValueError("运维数据文件格式错误, records 必须是列表.")
    return {"version": int(payload.get("version", 1)), "events": events, "records": records}


def _new_event_id(events: List[JsonDict]) -> str:
    """
    功能:
        生成不重复的运维事件 ID.
    参数:
        events: List[Dict], 现有事件列表.
    返回:
        str, 新事件 ID.
    """
    existing_ids = {str(event.get("id", "")) for event in events}
    index = len(events) + 1
    while True:
        event_id = f"maintenance-{index:03d}"
        if event_id not in existing_ids:
            return event_id
        index += 1


def _next_sort_order(events: List[JsonDict]) -> int:
    """
    功能:
        计算下一个排序值.
    参数:
        events: List[Dict], 现有事件列表.
    返回:
        int, 排序值.
    """
    if len(events) == 0:
        return 10
    return max(int(event.get("sort_order", 0)) for event in events) + 10


def _find_event(events: List[JsonDict], event_id: str) -> Optional[JsonDict]:
    """
    功能:
        按 ID 查找运维事件.
    参数:
        events: List[Dict], 事件列表.
        event_id: str, 事件 ID.
    返回:
        Optional[Dict], 找到的事件或 None.
    """
    for event in events:
        if str(event.get("id", "")) == event_id:
            return event
    return None


def _build_due_item(event: JsonDict, due_date: date, records_by_key: Dict[str, JsonDict]) -> JsonDict:
    """
    功能:
        构造前端待办事项行.
    参数:
        event: Dict, 运维事件.
        due_date: date, 到期日期.
        records_by_key: Dict[str, Dict], 记录索引.
    返回:
        Dict, 待办事项行.
    """
    event_id = str(event["id"])
    due_date_text = due_date.isoformat()
    record = records_by_key.get(_record_key(event_id, due_date_text))
    return {
        "event_id": event_id,
        "station": str(event["station"]),
        "title": str(event["title"]),
        "due_date": due_date_text,
        "start_date": str(event["start_date"]),
        "interval_days": int(event["interval_days"]),
        "completed": record is not None,
        "record": deepcopy(record) if record is not None else None,
    }


def _records_by_event_due_date(records: List[JsonDict]) -> Dict[str, JsonDict]:
    """
    功能:
        将记录按 event_id 和 due_date 建立索引.
    参数:
        records: List[Dict], 运维记录列表.
    返回:
        Dict[str, Dict], 记录索引.
    """
    result: Dict[str, JsonDict] = {}
    for record in records:
        event_id = str(record.get("event_id", ""))
        due_date_text = str(record.get("due_date", ""))
        if event_id == "" or due_date_text == "":
            continue
        result[_record_key(event_id, due_date_text)] = record
    return result


def _has_later_record(event_id: str, due_date: date, records: List[JsonDict]) -> bool:
    """
    功能:
        判断指定到期日之后是否已有同一事件的完成记录.
    参数:
        event_id: str, 运维事件 ID.
        due_date: date, 被检查的旧到期日.
        records: List[Dict], 运维记录列表.
    返回:
        bool, True 表示已有更新记录覆盖旧逾期.
    """
    for record in records:
        if str(record.get("event_id", "")) != event_id:
            continue
        record_due_date = _parse_date(str(record.get("due_date", "")), "到期日期")
        if record_due_date > due_date:
            return True
    return False


def _record_key(event_id: str, due_date_text: str) -> str:
    """
    功能:
        生成记录唯一键.
    参数:
        event_id: str, 运维事件 ID.
        due_date_text: str, 到期日期.
    返回:
        str, 唯一键.
    """
    return f"{event_id}|{due_date_text}"


def _is_due_on(event: JsonDict, target_date: date) -> bool:
    """
    功能:
        判断事件在指定日期是否到期.
    参数:
        event: Dict, 运维事件.
        target_date: date, 目标日期.
    返回:
        bool, True 表示到期.
    """
    start_date = _parse_date(str(event.get("start_date", "")), "开始日期")
    if target_date < start_date:
        return False
    interval_days = _positive_int(event.get("interval_days"), "间隔天数")
    delta_days = (target_date - start_date).days
    return delta_days % interval_days == 0


def _latest_due_before(event: JsonDict, target_date: date) -> Optional[date]:
    """
    功能:
        计算目标日期之前最近一次到期日.
    参数:
        event: Dict, 运维事件.
        target_date: date, 目标日期.
    返回:
        Optional[date], 最近到期日或 None.
    """
    start_date = _parse_date(str(event.get("start_date", "")), "开始日期")
    if target_date <= start_date:
        return None
    interval_days = _positive_int(event.get("interval_days"), "间隔天数")
    days_before = (target_date - start_date).days - 1
    periods = days_before // interval_days
    return start_date + timedelta(days=periods * interval_days)


def _parse_date_text(value: Any, label: str) -> str:
    """
    功能:
        将输入值校验为 ISO 日期文本.
    参数:
        value: Any, 输入值.
        label: str, 字段中文名.
    返回:
        str, 日期文本.
    """
    if isinstance(value, str) is False:
        raise ValueError(f"{label}必须是日期文本.")
    target_date = _parse_date(value, label)
    return target_date.isoformat()


def _parse_date(value: str, label: str) -> date:
    """
    功能:
        解析 YYYY-MM-DD 日期文本.
    参数:
        value: str, 日期文本.
        label: str, 字段中文名.
    返回:
        date, 日期对象.
    """
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label}必须是 YYYY-MM-DD 格式.") from exc


def _required_text(value: Any, label: str) -> str:
    """
    功能:
        校验必填文本字段.
    参数:
        value: Any, 输入值.
        label: str, 字段中文名.
    返回:
        str, 去除首尾空白后的文本.
    """
    if isinstance(value, str) is False:
        raise ValueError(f"{label}不能为空.")
    text = value.strip()
    if text == "":
        raise ValueError(f"{label}不能为空.")
    return text


def _optional_text(value: Any) -> str:
    """
    功能:
        将可选输入转换为文本.
    参数:
        value: Any, 输入值.
    返回:
        str, 文本.
    """
    if value is None:
        return ""
    return str(value).strip()


def _positive_int(value: Any, label: str) -> int:
    """
    功能:
        校验正整数.
    参数:
        value: Any, 输入值.
        label: str, 字段中文名.
    返回:
        int, 正整数.
    """
    int_value = _int_value(value, label)
    if int_value <= 0:
        raise ValueError(f"{label}必须大于 0.")
    return int_value


def _int_value(value: Any, label: str) -> int:
    """
    功能:
        将输入值转换为整数.
    参数:
        value: Any, 输入值.
        label: str, 字段中文名.
    返回:
        int, 整数.
    """
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}必须是整数.") from exc


def _now_text() -> str:
    """
    功能:
        返回当前本地时间文本.
    返回:
        str, ISO 8601 时间.
    """
    return datetime.now().isoformat(timespec="seconds")
