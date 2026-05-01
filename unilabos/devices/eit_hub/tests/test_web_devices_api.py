# -*- coding: utf-8 -*-
"""
功能:
    覆盖 EIT Hub 设备状态总览 API.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

import pytest
from fastapi.testclient import TestClient

from unilabos.devices.eit_hub.web.app import create_app
from unilabos.devices.eit_hub.web.routers import devices


@pytest.fixture()
def api_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """
    功能:
        创建隔离的 Hub TestClient, 并固定 Hub 本机 IPv4 地址.
    返回:
        TestClient, 测试客户端.
    """
    monkeypatch.setattr(devices, "_list_local_ipv4_addresses", lambda: ["10.1.1.20"])
    client = TestClient(create_app())
    return client


def _fake_endpoint_check(endpoint: devices.EndpointSpec, _timeout_s: float) -> Dict[str, Any]:
    """
    功能:
        按端点返回确定的 TCP 检查结果, 避免测试访问真实设备.
    参数:
        endpoint: EndpointSpec, 待检查端点.
        _timeout_s: float, 超时秒数, 测试中不使用.
    返回:
        Dict[str, Any], 端点检查结果.
    """
    online_endpoints = {
        ("192.168.1.5", 19204),
        ("192.168.1.10", 7003),
        ("192.168.1.45", 6006),
        ("10.32.2.106", 4669),
        ("10.40.6.101", 5792),
        ("10.40.0.103", 5792),
        ("10.40.16.204", 5792),
    }
    endpoint_key: Tuple[str, int] = (endpoint.host, endpoint.port)
    reachable = endpoint_key in online_endpoints
    if reachable is True:
        return {
            "host": endpoint.host,
            "port": endpoint.port,
            "reachable": True,
            "latency_ms": 12.3,
            "error": "",
        }
    return {
        "host": endpoint.host,
        "port": endpoint.port,
        "reachable": False,
        "latency_ms": None,
        "error": "连接失败: mock offline",
    }


def _find_item(items: list[Dict[str, Any]], key: str) -> Dict[str, Any]:
    """
    功能:
        从设备列表中查找指定 key 的设备状态.
    参数:
        items: list[Dict[str, Any]], 设备状态列表.
        key: str, 设备 key.
    返回:
        Dict[str, Any], 设备状态.
    """
    for item in items:
        if item["key"] == key:
            return item
    raise AssertionError(f"未找到设备状态: {key}")


def test_device_status_returns_all_configured_devices(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    功能:
        验证设备总览接口返回完整设备清单和指定 IP 端口.
    """
    monkeypatch.setattr(devices, "_check_endpoint", _fake_endpoint_check)

    response = api_client.get("/api/devices/status")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["checked_at"], str) is True
    items = body["items"]
    assert [item["key"] for item in items] == [
        "eit_hub",
        "agv_chassis",
        "agv_arm",
        "consumables_rack",
        "synthesis_station",
        "gc_ms",
        "uplc_qtof",
        "hplc",
        "label_printer",
    ]

    hub = items[0]
    assert hub["status"] == "在线"
    assert hub["reachable"] is True
    assert "10.1.1.20:8770" in hub["address"]

    uplc_qtof = _find_item(items, "uplc_qtof")
    assert uplc_qtof["address"] == "10.40.0.103:5792"
    assert uplc_qtof["endpoints"][0]["host"] == "10.40.0.103"
    assert uplc_qtof["endpoints"][0]["port"] == 5792

    hplc = _find_item(items, "hplc")
    assert hplc["address"] == "10.40.16.204:5792"
    assert hplc["endpoints"][0]["port"] == 5792


def test_device_status_summarizes_online_partial_and_offline_devices(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    功能:
        验证单端口和多端口设备的在线, 部分在线, 离线汇总规则.
    """
    monkeypatch.setattr(devices, "_check_endpoint", _fake_endpoint_check)

    response = api_client.get("/api/devices/status")

    assert response.status_code == 200
    items = response.json()["items"]

    agv_chassis = _find_item(items, "agv_chassis")
    assert agv_chassis["status"] == "部分在线"
    assert agv_chassis["reachable"] is True
    assert agv_chassis["summary"] == "1/2 端口在线"
    assert [endpoint["reachable"] for endpoint in agv_chassis["endpoints"]] == [True, False]

    agv_arm = _find_item(items, "agv_arm")
    assert agv_arm["status"] == "在线"
    assert agv_arm["reachable"] is True
    assert agv_arm["summary"] == "1/1 端口在线"

    label_printer = _find_item(items, "label_printer")
    assert label_printer["status"] == "离线"
    assert label_printer["reachable"] is False
    assert label_printer["summary"] == "0/1 端口在线"
