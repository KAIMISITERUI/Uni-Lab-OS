# -*- coding: utf-8 -*-
"""
功能:
    覆盖 EIT Hub 运维管理 Web API.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from unilabos.devices.eit_hub.web.routers import maintenance
from unilabos.devices.eit_hub.web.services.maintenance_store import MaintenanceStore


@pytest.fixture()
def api_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Tuple[TestClient, MaintenanceStore]:
    """
    功能:
        创建隔离的 Hub TestClient, 并将运维数据文件指向临时目录.
    返回:
        Tuple[TestClient, MaintenanceStore], 测试客户端和运维存储.
    """
    store = MaintenanceStore(tmp_path / "maintenance.json")
    monkeypatch.setattr(maintenance, "_STORE", store)
    app = FastAPI()
    app.include_router(maintenance.router)
    return TestClient(app), store


def _event_by_id(events: list[Dict[str, Any]], event_id: str) -> Dict[str, Any]:
    """
    功能:
        从事件列表中查找指定事件.
    参数:
        events: list[Dict[str, Any]], 事件列表.
        event_id: str, 事件 ID.
    返回:
        Dict[str, Any], 事件.
    """
    for event in events:
        if event["id"] == event_id:
            return event
    raise AssertionError(f"未找到运维事件: {event_id}")


def _due_item_by_id(items: list[Dict[str, Any]], event_id: str) -> Dict[str, Any]:
    """
    功能:
        从待办列表中查找指定事件.
    参数:
        items: list[Dict[str, Any]], 待办列表.
        event_id: str, 事件 ID.
    返回:
        Dict[str, Any], 待办项.
    """
    for item in items:
        if item["event_id"] == event_id:
            return item
    raise AssertionError(f"未找到运维待办: {event_id}")


def test_default_events_are_initialized_from_reference_table(
    api_client: Tuple[TestClient, MaintenanceStore],
) -> None:
    """
    功能:
        验证首次读取时创建 Excel 参考表对应的默认运维事件.
    """
    client, _store = api_client

    response = client.get("/api/maintenance/events")

    assert response.status_code == 200
    body = response.json()
    events = body["events"]
    assert body["total"] == 19
    assert events[0]["station"] == "合成手套箱工站"
    assert events[0]["title"] == "1. 中央氮气气压检查"
    weekly_event = _event_by_id(events, "maintenance-015")
    assert weekly_event["title"] == "10. GC-MS快速调谐, 每周一做"
    assert weekly_event["start_date"] == "2026-03-23"
    assert weekly_event["interval_days"] == 7


def test_overview_uses_custom_interval_days(
    api_client: Tuple[TestClient, MaintenanceStore],
) -> None:
    """
    功能:
        验证每日和每 7 天周期的到期计算.
    """
    client, _store = api_client

    monday_response = client.get("/api/maintenance/overview", params={"date": "2026-03-30"})
    tuesday_response = client.get("/api/maintenance/overview", params={"date": "2026-03-24"})

    assert monday_response.status_code == 200
    monday_body = monday_response.json()
    weekly_due = _due_item_by_id(monday_body["due_items"], "maintenance-015")
    assert weekly_due["due_date"] == "2026-03-30"
    assert monday_body["stats"]["due_count"] == 19

    assert tuesday_response.status_code == 200
    tuesday_body = tuesday_response.json()
    tuesday_due_ids = {item["event_id"] for item in tuesday_body["due_items"]}
    assert "maintenance-015" not in tuesday_due_ids
    overdue_weekly = _due_item_by_id(tuesday_body["overdue_items"], "maintenance-015")
    assert overdue_weekly["due_date"] == "2026-03-23"


def test_batch_records_create_and_update_one_record_per_event_date(
    api_client: Tuple[TestClient, MaintenanceStore],
) -> None:
    """
    功能:
        验证批量提交创建记录, 重复提交同一 event_id 和 due_date 时更新原记录.
    """
    client, _store = api_client
    payload = {
        "date": "2026-03-19",
        "operator": "张三",
        "items": [
            {
                "event_id": "maintenance-001",
                "due_date": "2026-03-19",
                "value_text": "气压正常",
                "note": "首次检查",
            }
        ],
    }

    create_response = client.post("/api/maintenance/records/batch", json=payload)
    payload["items"][0]["value_text"] = "气压稳定"
    update_response = client.post("/api/maintenance/records/batch", json=payload)
    records_response = client.get(
        "/api/maintenance/records",
        params={"start_date": "2026-03-19", "end_date": "2026-03-19"},
    )
    overview_response = client.get("/api/maintenance/overview", params={"date": "2026-03-19"})

    assert create_response.status_code == 200
    assert create_response.json()["saved_count"] == 1
    assert update_response.status_code == 200
    assert update_response.json()["saved_count"] == 1
    assert records_response.status_code == 200
    records_body = records_response.json()
    assert records_body["total"] == 1
    assert records_body["records"][0]["value_text"] == "气压稳定"
    overview_body = overview_response.json()
    due_ids = {item["event_id"] for item in overview_body["due_items"]}
    assert "maintenance-001" not in due_ids
    assert overview_body["stats"]["due_count"] == 18
    assert overview_body["stats"]["pending_count"] == 17
    assert overview_body["stats"]["completed_count"] == 1


def test_disabled_event_is_not_due_but_record_remains(
    api_client: Tuple[TestClient, MaintenanceStore],
) -> None:
    """
    功能:
        验证停用事件不再进入待办, 历史运维记录仍可查询.
    """
    client, _store = api_client
    submit_response = client.post(
        "/api/maintenance/records/batch",
        json={
            "date": "2026-03-19",
            "operator": "李四",
            "items": [
                {
                    "event_id": "maintenance-001",
                    "due_date": "2026-03-19",
                    "value_text": "已完成",
                    "note": "",
                }
            ],
        },
    )
    update_response = client.put(
        "/api/maintenance/events/maintenance-001",
        json={
            "station": "合成手套箱工站",
            "title": "1. 中央氮气气压检查",
            "start_date": "2026-03-19",
            "interval_days": 1,
            "enabled": False,
            "sort_order": 10,
        },
    )
    overview_response = client.get("/api/maintenance/overview", params={"date": "2026-03-20"})
    records_response = client.get(
        "/api/maintenance/records",
        params={"start_date": "2026-03-19", "end_date": "2026-03-19"},
    )

    assert submit_response.status_code == 200
    assert update_response.status_code == 200
    assert update_response.json()["enabled"] is False
    due_ids = {item["event_id"] for item in overview_response.json()["due_items"]}
    overdue_ids = {item["event_id"] for item in overview_response.json()["overdue_items"]}
    assert "maintenance-001" not in due_ids
    assert "maintenance-001" not in overdue_ids
    assert records_response.json()["total"] == 1
    assert records_response.json()["records"][0]["title_snapshot"] == "1. 中央氮气气压检查"


def test_later_record_suppresses_previous_overdue_reminder(
    api_client: Tuple[TestClient, MaintenanceStore],
) -> None:
    """
    功能:
        验证同一事件已有更新完成记录时, 不再提醒更早未完成的到期日.
    """
    client, _store = api_client

    submit_response = client.post(
        "/api/maintenance/records/batch",
        json={
            "date": "2026-03-20",
            "operator": "王五",
            "items": [
                {
                    "event_id": "maintenance-001",
                    "due_date": "2026-03-20",
                    "value_text": "今天已检查",
                }
            ],
        },
    )
    overview_response = client.get("/api/maintenance/overview", params={"date": "2026-03-20"})

    assert submit_response.status_code == 200
    assert overview_response.status_code == 200
    overdue_ids = {item["event_id"] for item in overview_response.json()["overdue_items"]}
    assert "maintenance-001" not in overdue_ids


def test_completed_today_due_item_disappears_from_todo_list(
    api_client: Tuple[TestClient, MaintenanceStore],
) -> None:
    """
    功能:
        验证当天运维记录提交后, 已完成事项不再返回到当日待办列表.
    """
    client, _store = api_client

    submit_response = client.post(
        "/api/maintenance/records/batch",
        json={
            "date": "2026-03-19",
            "operator": "赵六",
            "items": [
                {
                    "event_id": "maintenance-001",
                    "due_date": "2026-03-19",
                    "value_text": "已完成",
                }
            ],
        },
    )
    overview_response = client.get("/api/maintenance/overview", params={"date": "2026-03-19"})

    assert submit_response.status_code == 200
    assert overview_response.status_code == 200
    body = overview_response.json()
    due_ids = {item["event_id"] for item in body["due_items"]}
    assert "maintenance-001" not in due_ids
    assert body["stats"]["pending_count"] == 17
    assert body["stats"]["completed_count"] == 1


def test_invalid_batch_request_returns_chinese_error(
    api_client: Tuple[TestClient, MaintenanceStore],
) -> None:
    """
    功能:
        验证无效批量提交返回中文错误信息.
    """
    client, _store = api_client

    response = client.post(
        "/api/maintenance/records/batch",
        json={"date": "2026-03-19", "operator": "", "items": []},
    )

    assert response.status_code == 400
    assert "操作人不能为空" in response.json()["detail"]
