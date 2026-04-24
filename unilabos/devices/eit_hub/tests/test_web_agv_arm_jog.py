# -*- coding: utf-8 -*-
"""
功能:
    覆盖 EIT Hub 机械臂 WebSocket 端点接口.
    机械臂微调已改为前端直连 Duco 原生 WebSocket (复刻官方 movement 控制语义),
    后端仅提供 ws_url 查询端点, 业务路由不再参与 jog 指令中继.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from unilabos.devices.eit_agv.config.arm_config import ARM_HOST
from unilabos.devices.eit_hub.web.app import create_app


def test_arm_duco_ws_endpoint_returns_configured_host() -> None:
    """
    功能:
        验证 /api/agv/arm/duco-ws-endpoint 返回 ws_url, 主机与 ARM_HOST 一致, 端口固定 7000.
    """
    client = TestClient(create_app())

    response = client.get("/api/agv/arm/duco-ws-endpoint")

    assert response.status_code == 200
    body = response.json()
    assert body["ws_url"] == f"ws://{ARM_HOST}:7000"


def test_arm_jog_legacy_routes_are_removed() -> None:
    """
    功能:
        验证旧的机械臂点动 HTTP 路由已全部移除, 前端不再依赖后端中继.
        GET 会被 SPA fallback 拦截后抛 404, POST 因无对应方法获得 405,
        两种状态码都代表"路由已移除, 请求无法抵达 jog 处理器".
    """
    client = TestClient(create_app())

    start_response = client.post("/api/agv/arm/jog/start", json={"direction": "x+"})
    stop_response = client.post("/api/agv/arm/jog/stop")
    state_response = client.get("/api/agv/arm/jog/state")

    assert start_response.status_code in (404, 405)
    assert stop_response.status_code in (404, 405)
    assert state_response.status_code == 404
