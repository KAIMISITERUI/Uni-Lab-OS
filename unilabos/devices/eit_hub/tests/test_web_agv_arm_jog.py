# -*- coding: utf-8 -*-
"""
功能:
    覆盖 EIT Hub 机械臂 WebSocket 端点接口.
    机械臂微调走 eit_hub 后端 WebSocket 反代 (路径 /api/agv/arm/duco-ws),
    端点接口仅返回相对路径, 由前端结合 window.location 拼成完整 URL,
    避免向浏览器暴露内网 ARM_HOST 拓扑.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from unilabos.devices.eit_hub.web.app import create_app


def test_arm_duco_ws_endpoint_returns_relative_path() -> None:
    """
    功能:
        验证 /api/agv/arm/duco-ws-endpoint 返回相对路径 ws_path,
        指向 eit_hub 后端反代路由 /api/agv/arm/duco-ws, 不再泄露 ARM_HOST.
    """
    client = TestClient(create_app())

    response = client.get("/api/agv/arm/duco-ws-endpoint")

    assert response.status_code == 200
    body = response.json()
    assert body == {"ws_path": "/api/agv/arm/duco-ws"}


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
