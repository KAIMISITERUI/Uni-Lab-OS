# -*- coding: utf-8 -*-
"""
功能:
    覆盖 EIT Hub 合成工站 Web API.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

import pytest
from fastapi.testclient import TestClient

from unilabos.devices.eit_hub.web.app import create_app
from unilabos.devices.eit_hub.web.deps import get_synthesis_manager
from unilabos.devices.eit_hub.web.jobs import JobManager
from unilabos.devices.eit_hub.web.routers import synthesis

from .test_web_excel_codec import _create_template, _updated_payload


class FakeSynthesisManager:
    """
    功能:
        提供合成工站 Web API 测试用假管理器.
    """

    def __init__(self) -> None:
        self.submitted_path: Optional[str] = None
        self.resource_check_path: Optional[str] = None
        self.entered_event: Optional[threading.Event] = None
        self.release_event: Optional[threading.Event] = None
        self.device_init_calls = 0
        self.door_ops: list[str] = []
        self.w1_calls: list[tuple[str, str]] = []

    def station_state(self) -> int:
        """功能: 返回测试工站状态."""
        return 0

    def get_glovebox_env(self) -> Dict[str, Any]:
        """功能: 返回测试手套箱环境."""
        return {"box_pressure": 12, "water_content": 1.2, "oxygen_content": 2.3}

    def list_device_status(self) -> list[Dict[str, Any]]:
        """功能: 返回测试设备状态."""
        return [{"device_name": "机械臂", "status": "AVAILABLE", "status_code": 0}]

    def get_resource_info(self) -> list[Dict[str, Any]]:
        """功能: 返回测试资源状态."""
        return [{"layout_code": "W-1-1", "count": 1, "resource_type_name": "测试托盘"}]

    def get_task_list(self, **_: Any) -> Dict[str, Any]:
        """功能: 返回测试任务列表."""
        return {"task_list": [{"task_id": 7, "task_name": "最近任务", "status": 0}]}

    def create_task_by_file(self, template_path: str) -> int:
        """
        功能:
            记录任务模板路径并返回测试任务 ID.
        """
        self.submitted_path = template_path
        if self.entered_event is not None:
            self.entered_event.set()
        if self.release_event is not None:
            self.release_event.wait(timeout=5)
        return 321

    def check_resource_for_task(
        self,
        template_path: str,
        auto_generate_batch_file: bool = True,
    ) -> Dict[str, Any]:
        """
        功能:
            记录物料核算路径并返回测试结果.
        """
        self.resource_check_path = template_path
        return {"ready": True, "auto_generate_batch_file": auto_generate_batch_file}

    def device_init(self) -> Dict[str, Any]:
        """
        功能:
            返回测试设备初始化结果.
        返回:
            Dict[str, Any], 初始化结果.
        """
        self.device_init_calls += 1
        return {"success": True}

    def open_close_door(self, op: str) -> Dict[str, Any]:
        """
        功能:
            记录过渡舱外门开关动作.
        参数:
            op: str, 开门或关门动作.
        返回:
            Dict[str, Any], 动作结果.
        """
        self.door_ops.append(op)
        return {"success": True, "op": op}

    def control_w1_shelf(self, position: str, action: str) -> Dict[str, Any]:
        """
        功能:
            记录 W1 排货架控制动作.
        参数:
            position: str, W1 排货架位置.
            action: str, 推出或复位动作.
        返回:
            Dict[str, Any], 动作结果.
        """
        self.w1_calls.append((position, action))
        return {"success": True, "position": position, "action": action}


@pytest.fixture()
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, FakeSynthesisManager, Path]:
    """
    功能:
        创建隔离的 Hub TestClient 和测试模板.
    """
    template_path = tmp_path / "reaction_template.xlsx"
    _create_template(template_path)
    fake_manager = FakeSynthesisManager()

    monkeypatch.setattr(synthesis, "DEFAULT_REACTION_TEMPLATE", template_path)
    monkeypatch.setattr(synthesis, "job_manager", JobManager())

    app = create_app()
    app.dependency_overrides[get_synthesis_manager] = lambda: fake_manager
    return TestClient(app), fake_manager, template_path


def _wait_job(client: TestClient, job_id: str, expected_status: str = "succeeded") -> Dict[str, Any]:
    """
    功能:
        轮询后台任务直到结束.
    参数:
        client: TestClient, 测试客户端.
        job_id: str, 后台任务 ID.
        expected_status: str, 期望终态.
    返回:
        Dict[str, Any], 任务状态.
    """
    deadline = time.time() + 5
    last_body: Dict[str, Any] = {}
    while time.time() < deadline:
        response = client.get(f"/api/synthesis/jobs/{job_id}")
        assert response.status_code == 200
        last_body = response.json()
        if last_body["status"] in ("succeeded", "failed"):
            assert last_body["status"] == expected_status
            return last_body
        time.sleep(0.05)
    raise AssertionError(f"后台任务未按时结束: {last_body}")


def test_dashboard_returns_station_snapshot(api_client: tuple[TestClient, FakeSynthesisManager, Path]) -> None:
    """
    功能:
        验证仪表盘返回状态, 环境, 设备, 资源和最近任务.
    """
    client, _fake_manager, _template_path = api_client
    response = client.get("/api/synthesis/dashboard")
    assert response.status_code == 200
    body = response.json()
    assert body["station_state"] == 0
    assert body["glovebox_env"]["oxygen_content"] == 2.3
    assert body["device_status"][0]["device_name"] == "机械臂"
    assert body["resources"][0]["layout_code"] == "W-1-1"
    assert body["recent_tasks"][0]["task_id"] == 7


def test_submit_saves_template_and_uses_default_path(
    api_client: tuple[TestClient, FakeSynthesisManager, Path],
) -> None:
    """
    功能:
        验证提交任务会先保存 Web 表格, 再把默认模板路径交给 create_task_by_file.
    """
    client, fake_manager, template_path = api_client
    response = client.post("/api/synthesis/reaction-template/submit", json=_updated_payload())
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    job = _wait_job(client, job_id)
    assert job["result"]["task_id"] == 321
    assert fake_manager.submitted_path == str(template_path)

    saved = client.get("/api/synthesis/reaction-template").json()
    assert saved["params"]["实验名称"] == "Web任务"


def test_resource_check_uses_default_path(
    api_client: tuple[TestClient, FakeSynthesisManager, Path],
) -> None:
    """
    功能:
        验证物料核算使用默认模板路径并开启上料文件生成.
    """
    client, fake_manager, template_path = api_client
    response = client.post("/api/synthesis/resource-check", json=_updated_payload())
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    job = _wait_job(client, job_id)
    assert job["result"]["ready"] is True
    assert job["result"]["auto_generate_batch_file"] is True
    assert fake_manager.resource_check_path == str(template_path)


def test_device_init_calls_manager(
    api_client: tuple[TestClient, FakeSynthesisManager, Path],
) -> None:
    """
    功能:
        验证设备初始化窄接口会调用底层 device_init.
    """
    client, fake_manager, _template_path = api_client
    response = client.post("/api/synthesis/device-init")
    assert response.status_code == 200
    job = _wait_job(client, response.json()["job_id"])
    assert job["result"]["success"] is True
    assert fake_manager.device_init_calls == 1


def test_open_outer_door_action_calls_manager(
    api_client: tuple[TestClient, FakeSynthesisManager, Path],
) -> None:
    """
    功能:
        验证打开过渡舱外门窄接口会调用底层 open_close_door("open").
    """
    client, fake_manager, _template_path = api_client
    response = client.post("/api/synthesis/outer-door", json={"action": "open"})
    assert response.status_code == 200
    job = _wait_job(client, response.json()["job_id"])
    assert job["result"]["op"] == "open"
    assert fake_manager.door_ops == ["open"]


def test_close_outer_door_action_calls_manager(
    api_client: tuple[TestClient, FakeSynthesisManager, Path],
) -> None:
    """
    功能:
        验证关闭过渡舱外门窄接口会调用底层 open_close_door("close").
    """
    client, fake_manager, _template_path = api_client
    response = client.post("/api/synthesis/outer-door", json={"action": "close"})
    assert response.status_code == 200
    job = _wait_job(client, response.json()["job_id"])
    assert job["result"]["op"] == "close"
    assert fake_manager.door_ops == ["close"]


def test_control_w1_shelf_action_passes_params(
    api_client: tuple[TestClient, FakeSynthesisManager, Path],
) -> None:
    """
    功能:
        验证 W1 排货架窄接口会透传位置和动作参数.
    """
    client, fake_manager, _template_path = api_client
    response = client.post(
        "/api/synthesis/w1-shelf",
        json={"position": "W-1-3", "action": "home"},
    )
    assert response.status_code == 200
    job = _wait_job(client, response.json()["job_id"])
    assert job["result"]["position"] == "W-1-3"
    assert job["result"]["action"] == "home"
    assert fake_manager.w1_calls == [("W-1-3", "home")]


def test_control_w1_shelf_rejects_invalid_params(
    api_client: tuple[TestClient, FakeSynthesisManager, Path],
) -> None:
    """
    功能:
        验证 W1 排货架控制参数非法时直接返回 400.
    """
    client, fake_manager, _template_path = api_client
    response = client.post(
        "/api/synthesis/w1-shelf",
        json={"position": "W-1-2", "action": "home"},
    )
    assert response.status_code == 400
    assert "W1 货架位置" in response.json()["detail"]
    assert fake_manager.w1_calls == []


def test_synthesis_actions_api_is_removed(
    api_client: tuple[TestClient, FakeSynthesisManager, Path],
) -> None:
    """
    功能:
        验证旧的合成工站通用动作接口已被删除.
    """
    client, _fake_manager, _template_path = api_client
    response = client.post("/api/synthesis/actions/open_outer_door", json={"params": {}})
    assert response.status_code == 404


def test_second_exclusive_job_returns_409(
    api_client: tuple[TestClient, FakeSynthesisManager, Path],
) -> None:
    """
    功能:
        验证同一时间只允许一个合成后台任务运行.
    """
    client, fake_manager, _template_path = api_client
    fake_manager.entered_event = threading.Event()
    fake_manager.release_event = threading.Event()

    first = client.post("/api/synthesis/reaction-template/submit", json=_updated_payload())
    assert first.status_code == 200
    assert fake_manager.entered_event.wait(timeout=2) is True

    second = client.post("/api/synthesis/resource-check", json=_updated_payload())
    assert second.status_code == 409

    fake_manager.release_event.set()
    _wait_job(client, first.json()["job_id"])
