# -*- coding: utf-8 -*-
"""
功能:
    覆盖 EIT Hub AGV 地图布局与物料转移点位 API.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

from unilabos.devices.eit_hub.web import deps
from unilabos.devices.eit_hub.web.app import create_app
from unilabos.devices.eit_hub.web.services.charge_loop import (
    DEFAULT_CHARGE_LOOP_CONFIG,
    ChargeLoopService,
)
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


class FakeChargeController:
    """
    功能:
        提供充电循环服务测试所需的最小控制器.
    """

    def auto_charge_pp5_cp6_check(
        self,
        low_battery_pct: int = 50,
        full_battery_pct: int = 95,
    ) -> Dict[str, Any]:
        """
        功能:
            返回一次成功的充电检查结果.
        参数:
            low_battery_pct: int, 低电量阈值.
            full_battery_pct: int, 满电停充阈值.
        返回:
            Dict[str, Any], 充电检查结果.
        """
        return {
            "status": "success",
            "low_battery_pct": low_battery_pct,
            "full_battery_pct": full_battery_pct,
        }


class FakeChargeContext:
    """
    功能:
        提供充电循环服务测试所需的最小上下文.
    """

    def __init__(self, chassis_connected: bool = True) -> None:
        self.chassis_connected = chassis_connected
        self.arm_lock = threading.Lock()
        self.controller = FakeChargeController()

    def is_chassis_connected(self) -> bool:
        """
        功能:
            返回底盘连接状态.
        返回:
            bool, True 表示已连接.
        """
        return self.chassis_connected

    def get_or_create(self) -> FakeChargeController:
        """
        功能:
            返回测试控制器.
        返回:
            FakeChargeController, 测试控制器.
        """
        return self.controller


class FakeChargeLoopApiService:
    """
    功能:
        提供充电管理 API 测试所需的最小服务.
    """

    def __init__(self) -> None:
        self.running = False
        self.config = dict(DEFAULT_CHARGE_LOOP_CONFIG)
        self.last_action = None

    def status(self) -> Dict[str, Any]:
        """
        功能:
            返回充电循环状态.
        返回:
            Dict[str, Any], 服务状态.
        """
        return {"running": self.running, "config": dict(self.config), "last_action": self.last_action}

    def save_config(
        self,
        interval_minutes: int,
        retry_wait_minutes: int,
        low_battery_pct: int,
        full_battery_pct: int,
    ) -> Dict[str, Any]:
        """
        功能:
            保存测试充电配置.
        参数:
            interval_minutes: int, 检查间隔.
            retry_wait_minutes: int, 重试等待.
            low_battery_pct: int, 电量阈值.
            full_battery_pct: int, 满电停充阈值.
        返回:
            Dict[str, Any], 保存后的服务状态.
        """
        self.config = {
            "interval_minutes": interval_minutes,
            "retry_wait_minutes": retry_wait_minutes,
            "low_battery_pct": low_battery_pct,
            "full_battery_pct": full_battery_pct,
        }
        return self.status()

    def start(
        self,
        interval_minutes: int,
        retry_wait_minutes: int,
        low_battery_pct: int,
        full_battery_pct: int,
    ) -> Dict[str, Any]:
        """
        功能:
            启动测试充电循环并保存配置.
        参数:
            interval_minutes: int, 检查间隔.
            retry_wait_minutes: int, 重试等待.
            low_battery_pct: int, 电量阈值.
            full_battery_pct: int, 满电停充阈值.
        返回:
            Dict[str, Any], 启动后的服务状态.
        """
        self.save_config(interval_minutes, retry_wait_minutes, low_battery_pct, full_battery_pct)
        self.running = True
        return self.status()

    def stop(self) -> Dict[str, Any]:
        """
        功能:
            停止测试充电循环.
        返回:
            Dict[str, Any], 停止后的服务状态.
        """
        self.running = False
        return self.status()


class FakeConnectedAgvContext:
    """
    功能:
        提供充电启动 API 测试所需的已连接底盘上下文.
    """

    def is_chassis_connected(self) -> bool:
        """
        功能:
            返回底盘连接状态.
        返回:
            bool, True 表示已连接.
        """
        return True


class FakeManualChargeController:
    """
    功能:
        提供 DO7 手动控制 API 测试所需的最小控制器.
    """

    def __init__(self) -> None:
        self.set_calls: List[bool] = []

    def set_charge_control_do(self, do_status: bool) -> Dict[str, Any]:
        """
        功能:
            记录 DO7 手动设置调用并返回状态数据.
        参数:
            do_status: bool, DO7 输出状态.
        返回:
            Dict[str, Any], DO7 状态数据.
        """
        self.set_calls.append(do_status)
        return {
            "do_id": 7,
            "do_status": do_status,
            "stop_charging": do_status,
            "charging_enabled": do_status is False,
            "source": "agv_other_port",
            "valid": True,
            "message": "DO7 打开, 停止充电" if do_status is True else "DO7 关闭, 允许充电",
        }


class FakeManualChargeContext:
    """
    功能:
        提供 DO7 手动控制 API 测试所需的 AGV 上下文.
    """

    def __init__(self, chassis_connected: bool = True) -> None:
        self.chassis_connected = chassis_connected
        self.controller = FakeManualChargeController()

    def is_chassis_connected(self) -> bool:
        """
        功能:
            返回底盘连接状态.
        返回:
            bool, True 表示已连接.
        """
        return self.chassis_connected

    def get_or_create(self) -> FakeManualChargeController:
        """
        功能:
            返回测试控制器.
        返回:
            FakeManualChargeController, 测试控制器.
        """
        return self.controller


class FakeManualChargeLoopApiService:
    """
    功能:
        提供 DO7 手动控制 API 测试所需的充电循环状态.
    """

    def __init__(self, running: bool = False) -> None:
        self.running = running

    def status(self) -> Dict[str, Any]:
        """
        功能:
            返回充电循环运行状态.
        返回:
            Dict[str, Any], 服务状态.
        """
        return {"running": self.running, "config": dict(DEFAULT_CHARGE_LOOP_CONFIG), "last_action": None}


class FakeNavigationController:
    """
    功能:
        提供导航控制 API 测试所需的最小控制器.
    """

    def __init__(self) -> None:
        self.calls: List[str] = []

    def pause_navigation(self) -> Dict[str, Any]:
        """
        功能:
            记录暂停导航调用并返回测试响应.
        返回:
            Dict[str, Any], 测试响应.
        """
        self.calls.append("pause")
        return {"ret_code": 0}

    def resume_navigation(self) -> Dict[str, Any]:
        """
        功能:
            记录继续导航调用并返回测试响应.
        返回:
            Dict[str, Any], 测试响应.
        """
        self.calls.append("resume")
        return {"ret_code": 0}

    def cancel_navigation(self) -> Dict[str, Any]:
        """
        功能:
            记录取消导航调用并返回测试响应.
        返回:
            Dict[str, Any], 测试响应.
        """
        self.calls.append("cancel")
        return {"ret_code": 0}


class FakeNavigationContext:
    """
    功能:
        提供导航控制 API 测试所需的 AGV 上下文.
    """

    def __init__(self, chassis_connected: bool = True) -> None:
        self.chassis_connected = chassis_connected
        self.controller = FakeNavigationController()

    def is_chassis_connected(self) -> bool:
        """
        功能:
            返回底盘连接状态.
        返回:
            bool, True 表示已连接.
        """
        return self.chassis_connected

    def get_or_create(self) -> FakeNavigationController:
        """
        功能:
            返回测试控制器.
        返回:
            FakeNavigationController, 测试控制器.
        """
        return self.controller


class FakeTraySavePositionManager:
    """
    功能:
        提供托盘校准保存接口测试所需的位置管理器.
    """

    def __init__(self) -> None:
        self.reload_count = 0

    def reload(self) -> None:
        """
        功能:
            记录配置重载次数.
        返回:
            None.
        """
        self.reload_count += 1


class FakeTraySaveController:
    """
    功能:
        提供托盘校准保存接口测试所需的控制器.
    """

    def __init__(self) -> None:
        self.position_manager = FakeTraySavePositionManager()
        self.saved_calls: List[Dict[str, Any]] = []

    def save_calibrated_tray_position(self, tray_name: str, pose: List[float]) -> bool:
        """
        功能:
            记录托盘点位保存调用.
        参数:
            tray_name: str, 托盘点位名称.
            pose: List[float], 待保存 TCP 位姿.
        返回:
            bool, True 表示保存成功.
        """
        self.saved_calls.append({"tray_name": tray_name, "pose": pose})
        return True


class FakeTraySaveContext:
    """
    功能:
        提供托盘校准保存接口测试所需的 AGV 上下文.
    """

    def __init__(self) -> None:
        self.controller = FakeTraySaveController()

    def get_or_create(self) -> FakeTraySaveController:
        """
        功能:
            返回测试控制器.
        返回:
            FakeTraySaveController, 测试控制器.
        """
        return self.controller


class FakeMiddleTrayPositionManager:
    """
    功能:
        提供中间托盘按行计算 API 测试所需的位置管理器.
    """

    def __init__(self) -> None:
        self.reload_count = 0

    def reload(self) -> None:
        """
        功能:
            记录配置重载次数.
        返回:
            None.
        """
        self.reload_count += 1


class FakeMiddleTrayController:
    """
    功能:
        提供中间托盘按行计算 API 测试所需的控制器.
    """

    def __init__(self) -> None:
        self.position_manager = FakeMiddleTrayPositionManager()
        self.preview_calls: List[Dict[str, Any]] = []
        self.apply_calls: List[Dict[str, Any]] = []

    def list_middle_tray_calibratable_rows(self) -> List[Dict[str, Any]]:
        """
        功能:
            返回测试用可校准行选项.
        返回:
            List[Dict[str, Any]], 可校准行列表.
        """
        return [
            {
                "station_name": "shelf",
                "row_index": 1,
                "left_tray": "shelf_tray_1-1",
                "right_tray": "shelf_tray_1-4",
                "target_count": 2,
                "update_count": 0,
                "create_count": 2,
                "label": "shelf 第1行: shelf_tray_1-1 -> shelf_tray_1-4, 2个中间点位",
            }
        ]

    def preview_middle_tray_row_updates(self, station_name: str, row_index: int) -> List[Dict[str, Any]]:
        """
        功能:
            记录按行预览调用并返回测试预览结果.
        参数:
            station_name: str, 工站名称.
            row_index: int, 行号.
        返回:
            List[Dict[str, Any]], 预览行.
        """
        self.preview_calls.append({"station_name": station_name, "row_index": row_index})
        return [
            {
                "row_index": row_index,
                "target_tray": f"{station_name}_tray_{row_index}-2",
                "left_tray": f"{station_name}_tray_{row_index}-1",
                "right_tray": f"{station_name}_tray_{row_index}-4",
                "target_col": 2,
                "ratio": 1 / 3,
                "old_pose": None,
                "new_pose": [1.0, 2.0, 3.0, 0.1, 0.2, 0.3],
                "exists": False,
            }
        ]

    def apply_middle_tray_row_updates(self, station_name: str, row_index: int) -> Dict[str, Any]:
        """
        功能:
            记录按行应用调用并返回测试写入结果.
        参数:
            station_name: str, 工站名称.
            row_index: int, 行号.
        返回:
            Dict[str, Any], 写入统计.
        """
        self.apply_calls.append({"station_name": station_name, "row_index": row_index})
        return {
            "station_name": station_name,
            "row_index": row_index,
            "updated_count": 0,
            "created_count": 1,
            "affected_trays": [f"{station_name}_tray_{row_index}-2"],
            "skipped_rows": [],
        }


class FakeMiddleTrayContext:
    """
    功能:
        提供中间托盘按行计算 API 测试所需的 AGV 上下文.
    """

    def __init__(self) -> None:
        self.controller = FakeMiddleTrayController()

    def get_or_create(self) -> FakeMiddleTrayController:
        """
        功能:
            返回测试控制器.
        返回:
            FakeMiddleTrayController, 测试控制器.
        """
        return self.controller


def _charging_api_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    charger: FakeChargeLoopApiService,
    context: Any = None,
) -> TestClient:
    """
    功能:
        创建隔离的充电管理 API 测试客户端.
    参数:
        monkeypatch: pytest.MonkeyPatch, 测试猴子补丁工具.
        tmp_path: Path, pytest 临时目录.
        charger: FakeChargeLoopApiService, 测试充电服务.
        context: Any, 可选 AGV 上下文.
    返回:
        TestClient, 测试客户端.
    """
    monkeypatch.setattr(station_map, "MAP_LAYOUT_PATH", tmp_path / "agv_station_layout.json")
    app = create_app()
    app.dependency_overrides[deps.get_charge_loop_service] = lambda: charger
    if context is not None:
        app.dependency_overrides[deps.get_agv_context] = lambda: context
    return TestClient(app)


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


def test_charge_loop_service_returns_default_config_without_saved_file(tmp_path: Path) -> None:
    """
    功能:
        验证充电循环服务在无配置文件时返回默认配置.
    """
    config_path = tmp_path / "charge_loop_config.json"
    service = ChargeLoopService(FakeChargeContext(), config_path=config_path)

    body = service.status()

    assert body["config"] == DEFAULT_CHARGE_LOOP_CONFIG
    assert config_path.is_file() is False


def test_charge_loop_service_save_config_persists_file(tmp_path: Path) -> None:
    """
    功能:
        验证充电循环服务保存配置后写入文件.
    """
    config_path = tmp_path / "charge_loop_config.json"
    service = ChargeLoopService(FakeChargeContext(), config_path=config_path)

    body = service.save_config(
        interval_minutes=12,
        retry_wait_minutes=6,
        low_battery_pct=55,
        full_battery_pct=90,
    )

    saved_config = json.loads(config_path.read_text(encoding="utf-8"))
    assert body["config"] == {
        "interval_minutes": 12,
        "retry_wait_minutes": 6,
        "low_battery_pct": 55,
        "full_battery_pct": 90,
    }
    assert saved_config == body["config"]


def test_charge_loop_service_loads_saved_config_after_restart(tmp_path: Path) -> None:
    """
    功能:
        验证重新创建充电循环服务后读取已保存配置.
    """
    config_path = tmp_path / "charge_loop_config.json"
    service = ChargeLoopService(FakeChargeContext(), config_path=config_path)
    service.save_config(
        interval_minutes=18,
        retry_wait_minutes=8,
        low_battery_pct=60,
        full_battery_pct=92,
    )

    restarted_service = ChargeLoopService(FakeChargeContext(), config_path=config_path)

    assert restarted_service.status()["config"] == {
        "interval_minutes": 18,
        "retry_wait_minutes": 8,
        "low_battery_pct": 60,
        "full_battery_pct": 92,
    }


def test_charge_loop_service_start_persists_submitted_config(tmp_path: Path) -> None:
    """
    功能:
        验证启动充电循环时保存提交的配置.
    """
    config_path = tmp_path / "charge_loop_config.json"
    service = ChargeLoopService(FakeChargeContext(), config_path=config_path)

    try:
        body = service.start(
            interval_minutes=9,
            retry_wait_minutes=4,
            low_battery_pct=65,
            full_battery_pct=88,
        )
        saved_config = json.loads(config_path.read_text(encoding="utf-8"))
    finally:
        service.stop()

    assert body["running"] is True
    assert body["config"] == {
        "interval_minutes": 9,
        "retry_wait_minutes": 4,
        "low_battery_pct": 65,
        "full_battery_pct": 88,
    }
    assert saved_config == body["config"]


def test_charging_config_api_save_updates_status(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    功能:
        验证 /api/agv/charging/config 保存后状态接口返回新配置.
    """
    charger = FakeChargeLoopApiService()
    client = _charging_api_client(monkeypatch, tmp_path, charger)

    save_response = client.put(
        "/api/agv/charging/config",
        json={
            "interval_minutes": 15,
            "retry_wait_minutes": 7,
            "low_battery_pct": 58,
            "full_battery_pct": 93,
        },
    )
    status_response = client.get("/api/agv/charging/status")

    assert save_response.status_code == 200
    assert save_response.json()["config"] == {
        "interval_minutes": 15,
        "retry_wait_minutes": 7,
        "low_battery_pct": 58,
        "full_battery_pct": 93,
    }
    assert status_response.status_code == 200
    assert status_response.json()["config"] == save_response.json()["config"]


def test_charging_config_api_rejects_invalid_value(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    功能:
        验证 /api/agv/charging/config 拒绝超出范围的参数.
    """
    charger = FakeChargeLoopApiService()
    client = _charging_api_client(monkeypatch, tmp_path, charger)

    response = client.put(
        "/api/agv/charging/config",
        json={
            "interval_minutes": 0,
            "retry_wait_minutes": 7,
            "low_battery_pct": 58,
            "full_battery_pct": 93,
        },
    )

    assert response.status_code == 422
    assert charger.config == DEFAULT_CHARGE_LOOP_CONFIG


def test_charging_start_api_uses_submitted_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    功能:
        验证 /api/agv/charging/start 使用并保存提交的配置.
    """
    charger = FakeChargeLoopApiService()
    client = _charging_api_client(monkeypatch, tmp_path, charger, context=FakeConnectedAgvContext())

    response = client.post(
        "/api/agv/charging/start",
        json={
            "interval_minutes": 20,
            "retry_wait_minutes": 9,
            "low_battery_pct": 70,
            "full_battery_pct": 96,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["running"] is True
    assert body["config"] == {
        "interval_minutes": 20,
        "retry_wait_minutes": 9,
        "low_battery_pct": 70,
        "full_battery_pct": 96,
    }
    assert charger.config == body["config"]


def test_charging_do7_api_sets_manual_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    功能:
        验证 /api/agv/charging/do7 按物理 DO7 电平语义调用控制器并返回状态.
    """
    charger = FakeManualChargeLoopApiService(running=False)
    context = FakeManualChargeContext(chassis_connected=True)
    client = _charging_api_client(monkeypatch, tmp_path, charger, context=context)

    open_response = client.post("/api/agv/charging/do7", json={"do_status": True})
    close_response = client.post("/api/agv/charging/do7", json={"do_status": False})

    assert open_response.status_code == 200
    assert open_response.json()["do_status"] is True
    assert open_response.json()["charging_enabled"] is False
    assert close_response.status_code == 200
    assert close_response.json()["do_status"] is False
    assert close_response.json()["charging_enabled"] is True
    assert context.controller.set_calls == [True, False]


def test_charging_do7_api_rejects_when_loop_running(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    功能:
        验证充电循环运行时 /api/agv/charging/do7 返回 409 且不写 DO7.
    """
    charger = FakeManualChargeLoopApiService(running=True)
    context = FakeManualChargeContext(chassis_connected=True)
    client = _charging_api_client(monkeypatch, tmp_path, charger, context=context)

    response = client.post("/api/agv/charging/do7", json={"do_status": True})

    assert response.status_code == 409
    assert "请先停止循环" in response.json()["detail"]
    assert context.controller.set_calls == []


def test_navigation_control_api_calls_controller(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    功能:
        验证暂停, 继续, 取消导航 API 调用对应控制器方法并返回动作名称.
    """
    charger = FakeManualChargeLoopApiService(running=False)
    context = FakeNavigationContext(chassis_connected=True)
    client = _charging_api_client(monkeypatch, tmp_path, charger, context=context)

    pause_response = client.post("/api/agv/navigation/pause")
    resume_response = client.post("/api/agv/navigation/resume")
    cancel_response = client.post("/api/agv/navigation/cancel")

    assert pause_response.status_code == 200
    assert pause_response.json()["ok"] is True
    assert pause_response.json()["action"] == "pause"
    assert resume_response.status_code == 200
    assert resume_response.json()["action"] == "resume"
    assert cancel_response.status_code == 200
    assert cancel_response.json()["action"] == "cancel"
    assert context.controller.calls == ["pause", "resume", "cancel"]


def test_navigation_control_api_rejects_without_chassis(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    功能:
        验证底盘未连接时导航控制 API 返回 409 且不调用控制器.
    """
    charger = FakeManualChargeLoopApiService(running=False)
    context = FakeNavigationContext(chassis_connected=False)
    client = _charging_api_client(monkeypatch, tmp_path, charger, context=context)

    response = client.post("/api/agv/navigation/cancel")

    assert response.status_code == 409
    assert "AGV 底盘未连接" in response.json()["detail"]
    assert context.controller.calls == []


def test_agv_status_returns_charge_control(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    功能:
        验证 /api/agv/status 返回 DO7 充电控制状态字段.
    """

    class FakeController:
        """
        功能:
            提供 AGV 状态接口测试所需的最小控制器.
        """

        def query_current_station(self) -> Dict[str, Any]:
            return {"station_id": "CP6", "station_name": "charging_station", "description": "充电站位置"}

        def query_battery_status(self, simple: bool = False) -> Dict[str, Any]:
            return {"battery_level": 0.6, "charging": True, "ret_code": 0}

        def query_charge_control_status(self) -> Dict[str, Any]:
            return {
                "do_id": 7,
                "do_status": False,
                "stop_charging": False,
                "charging_enabled": True,
                "source": "robot",
                "valid": True,
                "message": "DO7 关闭, 允许充电",
            }

        def query_nav_task_status(self) -> Dict[str, Any]:
            return {"task_status": 0, "task_status_name": "NONE"}

    class FakeContext:
        """
        功能:
            提供 AGV 状态接口测试所需的最小上下文.
        """

        def __init__(self) -> None:
            self.controller = FakeController()

        def status_snapshot(self) -> Dict[str, bool]:
            return {"chassis_connected": True, "arm_connected": False}

        def get_or_create(self) -> FakeController:
            return self.controller

    class FakeSampler:
        """
        功能:
            提供最近电量采样测试数据.
        """

        def get_latest(self) -> Dict[str, Any]:
            return {"timestamp": "2026-04-27T00:00:00", "battery_level": 0.6, "charging": True}

    class FakeCharger:
        """
        功能:
            提供充电循环服务测试状态.
        """

        def status(self) -> Dict[str, Any]:
            return {"running": False, "config": {}, "last_action": None}

    monkeypatch.setattr(station_map, "MAP_LAYOUT_PATH", tmp_path / "agv_station_layout.json")
    app = create_app()
    app.dependency_overrides[deps.get_agv_context] = lambda: FakeContext()
    app.dependency_overrides[deps.get_battery_sampler_service] = lambda: FakeSampler()
    app.dependency_overrides[deps.get_charge_loop_service] = lambda: FakeCharger()
    client = TestClient(app)

    response = client.get("/api/agv/status")

    assert response.status_code == 200
    body = response.json()
    assert body["battery"]["charging"] is True
    assert body["charge_control"]["do_id"] == 7
    assert body["charge_control"]["do_status"] is False
    assert body["charge_control"]["charging_enabled"] is True


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


def test_tray_calibration_save_calls_controller_after_reload() -> None:
    """
    功能:
        验证 /api/agv/calibration/tray/save 会先重载点位配置, 再调用控制器保存校准位姿.
    """
    context = FakeTraySaveContext()
    app = create_app()
    app.dependency_overrides[deps.get_agv_context] = lambda: context
    client = TestClient(app)
    pose = [1.0, 2.0, 3.0, 0.1, 0.2, 0.3]

    response = client.post(
        "/api/agv/calibration/tray/save",
        json={"tray_name": "synthesis_station_tray_1-1", "pose": pose},
    )

    assert response.status_code == 200
    assert response.json() == {"tray_name": "synthesis_station_tray_1-1", "ok": True}
    assert context.controller.position_manager.reload_count == 1
    assert context.controller.saved_calls == [
        {"tray_name": "synthesis_station_tray_1-1", "pose": pose}
    ]


def test_middle_tray_rows_api_returns_calibratable_rows() -> None:
    """
    功能:
        验证 /api/agv/calibration/middle-tray/rows 返回所有可校准行.
    """
    context = FakeMiddleTrayContext()
    app = create_app()
    app.dependency_overrides[deps.get_agv_context] = lambda: context
    client = TestClient(app)

    response = client.get("/api/agv/calibration/middle-tray/rows")

    assert response.status_code == 200
    body = response.json()
    assert body["rows"][0]["station_name"] == "shelf"
    assert body["rows"][0]["row_index"] == 1
    assert context.controller.position_manager.reload_count == 1


def test_middle_tray_preview_api_uses_station_and_row() -> None:
    """
    功能:
        验证中间托盘预览接口按工站和行号调用控制器.
    """
    context = FakeMiddleTrayContext()
    app = create_app()
    app.dependency_overrides[deps.get_agv_context] = lambda: context
    client = TestClient(app)

    response = client.get(
        "/api/agv/calibration/middle-tray/preview",
        params={"station_name": "shelf", "row_index": 2},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["station_name"] == "shelf"
    assert body["row_index"] == 2
    assert body["rows"][0]["target_tray"] == "shelf_tray_2-2"
    assert context.controller.preview_calls == [{"station_name": "shelf", "row_index": 2}]


def test_middle_tray_apply_api_uses_station_and_row() -> None:
    """
    功能:
        验证中间托盘应用接口按工站和行号调用控制器.
    """
    context = FakeMiddleTrayContext()
    app = create_app()
    app.dependency_overrides[deps.get_agv_context] = lambda: context
    client = TestClient(app)

    response = client.post(
        "/api/agv/calibration/middle-tray/apply",
        json={"station_name": "shelf", "row_index": 2},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["station_name"] == "shelf"
    assert body["row_index"] == 2
    assert body["created_count"] == 1
    assert context.controller.apply_calls == [{"station_name": "shelf", "row_index": 2}]
