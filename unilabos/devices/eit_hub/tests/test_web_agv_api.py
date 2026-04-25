# -*- coding: utf-8 -*-
"""
功能:
    覆盖 EIT Hub AGV 地图布局与物料转移点位 API.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

from unilabos.devices.eit_hub.web.app import create_app
from unilabos.devices.eit_hub.web.services import station_map


@pytest.fixture()
def api_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    """
    功能:
        创建隔离的 Hub TestClient, 并将 AGV 地图布局文件指向临时目录.
    参数:
        monkeypatch: pytest.MonkeyPatch, 测试猴子补丁工具.
        tmp_path: Path, pytest 临时目录.
    返回:
        TestClient, 测试客户端.
    """
    monkeypatch.setattr(station_map, "MAP_LAYOUT_PATH", tmp_path / "agv_station_layout.json")
    return TestClient(create_app())


def _station_by_id(stations: List[Dict[str, Any]], station_id: str) -> Dict[str, Any]:
    """
    功能:
        从地图工站列表中查找指定工站.
    参数:
        stations: List[Dict[str, Any]], 地图工站列表.
        station_id: str, 工站 ID.
    返回:
        Dict[str, Any], 工站地图项.
    """
    for station in stations:
        if station["id"] == station_id:
            return station
    raise AssertionError(f"未找到工站: {station_id}")


def test_agv_map_returns_default_layout_without_saved_file(api_client: TestClient) -> None:
    """
    功能:
        验证 /api/agv/map 在无保存文件时返回默认工站布局.
    """
    response = api_client.get("/api/agv/map")

    assert response.status_code == 200
    body = response.json()
    lm1 = _station_by_id(body["stations"], "LM1")
    assert lm1["x"] == 30.0
    assert lm1["y"] == 20.0
    assert lm1["label"] == "合成工站"
    assert body["current_station_id"] is None


def test_agv_map_layout_save_persists_coordinates(api_client: TestClient) -> None:
    """
    功能:
        验证 /api/agv/map/layout 保存后, 后续 /api/agv/map 返回新坐标.
    """
    save_response = api_client.post(
        "/api/agv/map/layout",
        json={
            "stations": [
                {"id": "LM1", "x": 18.5, "y": 42.0},
                {"id": "CP6", "x": 88.0, "y": 82.5},
            ]
        },
    )

    assert save_response.status_code == 200
    saved_body = save_response.json()
    assert _station_by_id(saved_body["stations"], "LM1")["x"] == 18.5

    reload_response = api_client.get("/api/agv/map")
    assert reload_response.status_code == 200
    body = reload_response.json()
    lm1 = _station_by_id(body["stations"], "LM1")
    cp6 = _station_by_id(body["stations"], "CP6")
    assert lm1["x"] == 18.5
    assert lm1["y"] == 42.0
    assert cp6["x"] == 88.0
    assert cp6["y"] == 82.5


def test_agv_map_layout_rejects_out_of_range_coordinate(api_client: TestClient) -> None:
    """
    功能:
        验证 /api/agv/map/layout 拒绝超出 0 到 100 范围的坐标.
    """
    response = api_client.post(
        "/api/agv/map/layout",
        json={"stations": [{"id": "LM1", "x": 120.0, "y": 42.0}]},
    )

    assert response.status_code == 422


def test_tray_options_include_current_station_and_agv_points(api_client: TestClient) -> None:
    """
    功能:
        验证 /api/agv/tray-options 按当前工站返回本站点位与 AGV 点位.
    """
    response = api_client.get("/api/agv/tray-options", params={"station_id": "LM1"})

    assert response.status_code == 200
    body = response.json()
    option_names = [item["name"] for item in body["options"]]
    assert body["station_id"] == "LM1"
    assert "agv_tray_1" in option_names
    assert "synthesis_station_tray_1-1" in option_names
    assert "analysis_station_tray_1-1" not in option_names
    assert "shelf_tray_1-1" not in option_names


def test_tray_options_use_agv_points_for_unknown_station(api_client: TestClient) -> None:
    """
    功能:
        验证未识别当前工站时只返回 AGV 自身点位.
    """
    response = api_client.get("/api/agv/tray-options", params={"station_id": "UNKNOWN"})

    assert response.status_code == 200
    body = response.json()
    option_names = [item["name"] for item in body["options"]]
    assert len(option_names) > 0
    assert all(name.startswith("agv") for name in option_names) is True
