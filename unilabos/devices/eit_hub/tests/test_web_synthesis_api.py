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
from unilabos.devices.eit_hub.web.excel_codec import write_reaction_template
from unilabos.devices.eit_hub.web.jobs import JobManager
from unilabos.devices.eit_hub.web.routers import synthesis

from .test_web_excel_codec import (
    _create_batch_in_template,
    _create_legacy_template_without_gc_sheet,
    _create_template,
    _updated_batch_in_payload,
    _updated_payload,
)


class FakeSynthesisManager:
    """
    功能:
        提供合成工站 Web API 测试用假管理器.
    """

    def __init__(self) -> None:
        self.submitted_path: Optional[str] = None
        self.resource_check_path: Optional[str] = None
        self.resource_check_auto_generate_batch_file: Optional[bool] = None
        self.entered_event: Optional[threading.Event] = None
        self.release_event: Optional[threading.Event] = None
        self.device_init_calls = 0
        self.door_ops: list[str] = []
        self.w1_calls: list[tuple[str, str]] = []
        self.reagent_label_print_calls = 0
        self.chemical_sync_calls = 0
        self.call_order: list[str] = []
        self.workflow_calls: list[tuple[str, Any]] = []
        self.stop_task_calls: list[int] = []
        self.cancel_task_calls: list[int] = []
        self.fault_recovery_calls: list[Dict[str, Any]] = []
        self.login_calls = 0
        self.batch_in_tray_calls: list[list[Dict[str, Any]]] = []
        self.batch_update_resource_calls: list[list[Dict[str, Any]]] = []
        self._client = self

    def ensure_login(self) -> None:
        """功能: 记录 synthesis_proxy 的登录校验调用."""
        self.call_order.append("ensure_login")

    def login(self) -> None:
        """功能: 记录 synthesis_proxy 的重登调用."""
        self.login_calls += 1

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

    def sync_chemicals_to_station(self) -> Dict[str, Any]:
        """
        功能:
            记录化学品库同步调用并返回测试结果.
        返回:
            Dict[str, Any], 同步结果.
        """
        self.chemical_sync_calls += 1
        self.call_order.append("sync_chemicals_to_station")
        return {"total": 2, "updated_rows": 2, "id_written": 2}

    def create_task_by_file(self, template_path: str) -> int:
        """
        功能:
            记录任务模板路径并返回测试任务 ID.
        """
        self.submitted_path = template_path
        self.call_order.append("create_task_by_file")
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
        self.resource_check_auto_generate_batch_file = auto_generate_batch_file
        return {
            "ready": True,
            "missing": ["乙腈:1mL"],
            "auto_generate_batch_file": auto_generate_batch_file,
        }

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

    def print_reagent_labels(self) -> None:
        """
        功能:
            记录试剂标签打印调用.
        返回:
            None.
        """
        self.reagent_label_print_calls += 1

    def batch_in_tray_by_file(self, file_path: str) -> Dict[str, Any]:
        """
        功能:
            记录手动上料调用.
        参数:
            file_path: str, 上料文件路径.
        返回:
            Dict[str, Any], 上料结果.
        """
        self.workflow_calls.append(("batch_in_manual", file_path))
        return {"success": True, "mode": "manual", "file_path": file_path}

    def batch_in_tray(self, resource_req_list: list[Dict[str, Any]]) -> Dict[str, Any]:
        """
        功能:
            记录资源面板批量上料调用.
        参数:
            resource_req_list: list[Dict[str, Any]], 批量上料请求列表.
        返回:
            Dict[str, Any], 上料结果.
        """
        self.batch_in_tray_calls.append(resource_req_list)
        return {"success": True, "mode": "resource_panel", "resource_req_list": resource_req_list}

    def batch_update_resource(self, resource_req_list: list[Dict[str, Any]]) -> Dict[str, Any]:
        """
        功能:
            记录资源面板批量编辑资源调用.
        参数:
            resource_req_list: list[Dict[str, Any]], 批量编辑资源请求列表.
        返回:
            Dict[str, Any], 编辑资源结果.
        """
        self.batch_update_resource_calls.append(resource_req_list)
        return {"success": True, "mode": "resource_panel_update", "resource_req_list": resource_req_list}

    def batch_in_tray_with_agv_transfer(
        self,
        file_path: str,
        *,
        chamber_capacity: int = 8,
    ) -> Dict[str, Any]:
        """
        功能:
            记录 AGV 上料调用.
        参数:
            file_path: str, 上料文件路径.
            chamber_capacity: int, 单轮最大托盘数.
        返回:
            Dict[str, Any], 上料结果.
        """
        self.workflow_calls.append(
            (
                "batch_in_agv",
                {
                    "file_path": file_path,
                    "chamber_capacity": chamber_capacity,
                },
            )
        )
        return {"success": True, "mode": "agv", "chamber_capacity": chamber_capacity}

    def start_task(
        self,
        task_id: int,
        *,
        check_glovebox_env: bool = True,
        water_limit_ppm: float = 10.0,
        oxygen_limit_ppm: float = 10.0,
    ) -> Dict[str, Any]:
        """
        功能:
            记录启动任务调用.
        参数:
            task_id: int, 任务 ID.
            check_glovebox_env: bool, 是否检查手套箱水氧.
            water_limit_ppm: float, 手套箱水含量上限.
            oxygen_limit_ppm: float, 手套箱氧含量上限.
        返回:
            Dict[str, Any], 启动结果.
        """
        self.workflow_calls.append(
            (
                "start_task",
                {
                    "task_id": task_id,
                    "check_glovebox_env": check_glovebox_env,
                    "water_limit_ppm": water_limit_ppm,
                    "oxygen_limit_ppm": oxygen_limit_ppm,
                },
            )
        )
        return {"success": True, "task_id": task_id}

    def wait_task_with_ops(self, task_id: int, *, poll_interval_s: float = 2.0) -> int:
        """
        功能:
            记录任务监控调用, 并按测试事件阻塞.
        参数:
            task_id: int, 任务 ID.
            poll_interval_s: float, 轮询间隔.
        返回:
            int, 完成状态码.
        """
        self.workflow_calls.append(
            (
                "wait_task",
                {
                    "task_id": task_id,
                    "poll_interval_s": poll_interval_s,
                },
            )
        )
        if self.entered_event is not None:
            self.entered_event.set()
        if self.release_event is not None:
            self.release_event.wait(timeout=5)
        return 2

    def batch_out_task_and_empty_trays(self, task_id: int) -> Dict[str, Any]:
        """
        功能:
            记录下料调用.
        参数:
            task_id: int, 任务 ID.
        返回:
            Dict[str, Any], 下料结果.
        """
        self.workflow_calls.append(("batch_out", task_id))
        return {"success": True, "task_id": task_id}

    def auto_unload_trays_to_agv(self, *, auto_run_analysis: bool = True) -> Dict[str, Any]:
        """
        功能:
            记录 AGV 自动下料调用.
        参数:
            auto_run_analysis: bool, 是否提交分析任务.
        返回:
            Dict[str, Any], 自动下料结果.
        """
        self.workflow_calls.append(("auto_unload", auto_run_analysis))
        return {"success": True, "auto_run_analysis": auto_run_analysis}

    def run_analysis(self, task_id: str) -> Dict[str, Any]:
        """
        功能:
            记录提交分析任务调用.
        参数:
            task_id: str, 任务 ID.
        返回:
            Dict[str, Any], 提交分析任务结果.
        """
        self.workflow_calls.append(("submit_analysis", task_id))
        return {"success": True, "task_id": task_id}

    def poll_analysis_run(self, task_id: str, *, poll_interval: float = 30.0) -> Dict[str, Any]:
        """
        功能:
            记录谱图数据处理调用.
        参数:
            task_id: str, 任务 ID.
            poll_interval: float, 轮询间隔.
        返回:
            Dict[str, Any], 谱图处理结果.
        """
        self.workflow_calls.append(
            (
                "poll_analysis",
                {
                    "task_id": task_id,
                    "poll_interval": poll_interval,
                },
            )
        )
        return {"success": True, "task_id": task_id}

    def calculate_yields(self, task_id: str) -> Dict[str, Any]:
        """
        功能:
            记录产率计算调用.
        参数:
            task_id: str, 任务 ID.
        返回:
            Dict[str, Any], 产率计算结果.
        """
        self.workflow_calls.append(("calculate_yields", task_id))
        return {"success": True, "task_id": task_id}

    def stop_task(self, task_id: int) -> Dict[str, Any]:
        """
        功能:
            记录暂停任务调用.
        参数:
            task_id: int, 任务 ID.
        返回:
            Dict[str, Any], 暂停结果.
        """
        self.stop_task_calls.append(task_id)
        return {"success": True, "task_id": task_id}

    def cancel_task(self, task_id: int) -> Dict[str, Any]:
        """
        功能:
            记录取消任务调用.
        参数:
            task_id: int, 任务 ID.
        返回:
            Dict[str, Any], 取消结果.
        """
        self.cancel_task_calls.append(task_id)
        return {"success": True, "task_id": task_id}

    def fault_recovery(
        self,
        *,
        resume_task: int = 1,
        recovery_type: int = 0,
    ) -> Dict[str, Any]:
        """
        功能:
            记录故障恢复调用.
        参数:
            resume_task: int, 是否恢复任务.
            recovery_type: int, 恢复类型.
        返回:
            Dict[str, Any], 恢复结果.
        """
        call = {
            "resume_task": resume_task,
            "recovery_type": recovery_type,
        }
        self.fault_recovery_calls.append(call)
        return {"success": True, **call}


@pytest.fixture()
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, FakeSynthesisManager, Path]:
    """
    功能:
        创建隔离的 Hub TestClient 和测试模板.
    """
    template_path = tmp_path / "reaction_template.xlsx"
    batch_in_path = tmp_path / "batch_in_tray.xlsx"
    history_tasks_dir = tmp_path / "tasks"
    _create_template(template_path)
    _create_batch_in_template(batch_in_path)
    history_tasks_dir.mkdir(parents=True, exist_ok=True)
    fake_manager = FakeSynthesisManager()

    monkeypatch.setattr(synthesis, "DEFAULT_REACTION_TEMPLATE", template_path)
    monkeypatch.setattr(synthesis, "DEFAULT_BATCH_IN_TEMPLATE", batch_in_path)
    monkeypatch.setattr(synthesis, "DEFAULT_HISTORY_TASKS_DIR", history_tasks_dir)
    monkeypatch.setattr(synthesis, "job_manager", JobManager())
    synthesis._workflow_runs.clear()

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
        if last_body["status"] in ("succeeded", "failed", "stopped"):
            assert last_body["status"] == expected_status
            return last_body
        time.sleep(0.05)
    raise AssertionError(f"后台任务未按时结束: {last_body}")


def _workflow_payload(**updates: Any) -> Dict[str, Any]:
    """
    功能:
        构造合成工作流测试 payload.
    参数:
        **updates: Any, 需要覆盖的字段.
    返回:
        Dict[str, Any], 工作流启动请求.
    """
    payload: Dict[str, Any] = {
        "experiment_id": 321,
        "experiment_name": "Web任务",
        "start_step": "batch_in",
        "batch_in": {
            "mode": "agv",
            "chamber_capacity": 8,
        },
        "start_task": {
            "check_glovebox_env": True,
            "water_limit_ppm": 10,
            "oxygen_limit_ppm": 10,
        },
        "wait_task": {
            "poll_interval_s": 2,
        },
        "has_analysis_task": True,
        "submit_analysis": {
            "auto_submit_after_agv": True,
        },
        "poll_analysis": {
            "poll_interval": 30,
        },
    }
    payload.update(updates)
    return payload


def test_synthesis_proxy_batch_in_tray_uses_controller(
    api_client: tuple[TestClient, FakeSynthesisManager, Path],
) -> None:
    """
    功能:
        验证资源面板 BatchInTray 代理进入控制器 batch_in_tray, 不绕过到 _client.
    参数:
        api_client: tuple[TestClient, FakeSynthesisManager, Path], 测试客户端与假管理器.
    返回:
        None.
    """
    client, fake_manager, _template_path = api_client
    resource_req_list = [
        {
            "tray_layout_code": "TB-2-1",
            "remark": "",
            "resource_list": [
                {"layout_code": "TB-2-1:-1", "resource_type": "201000502"},
                {
                    "layout_code": "TB-2-1:0",
                    "resource_type": "220000005",
                    "substance": "水杨醛",
                    "unit": "mL",
                    "initial_volume": 8,
                },
            ],
        }
    ]

    response = client.post(
        "/synthesis-api/api/BatchInTray",
        json={"resource_req_list": resource_req_list},
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "resource_panel"
    assert fake_manager.batch_in_tray_calls == [resource_req_list]
    assert "ensure_login" in fake_manager.call_order


def test_synthesis_proxy_batch_update_resource_uses_device_client(
    api_client: tuple[TestClient, FakeSynthesisManager, Path],
) -> None:
    """
    功能:
        验证资源面板 BatchUpdateResource 代理透传 resource_req_list 到设备客户端.
    参数:
        api_client: tuple[TestClient, FakeSynthesisManager, Path], 测试客户端与假管理器.
    返回:
        None.
    """
    client, fake_manager, _template_path = api_client
    resource_req_list = [
        {
            "tray_layout_code": "W-4-1",
            "remark": "",
            "resource_list": [
                {
                    "layout_code": "W-4-1:-1",
                    "slot_index": -1,
                    "with_cap": False,
                    "resource_type": "201000600",
                },
                {
                    "layout_code": "W-4-1:1",
                    "resource_type": "201000816",
                    "substance": "碳酸铯",
                    "chemical_id": 385,
                    "unit": "mg",
                    "cur_weight": 328.7,
                    "with_cap": False,
                    "with_magneton": False,
                    "content": "",
                },
            ],
        }
    ]

    response = client.post(
        "/synthesis-api/api/BatchUpdateResource",
        json={"resource_req_list": resource_req_list},
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "resource_panel_update"
    assert fake_manager.batch_update_resource_calls == [resource_req_list]
    assert "ensure_login" in fake_manager.call_order


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


def test_reaction_template_history_returns_summary_and_loads_read_only_copy(
    api_client: tuple[TestClient, FakeSynthesisManager, Path],
) -> None:
    """
    功能:
        验证历史实验模板列表与载入接口只读取历史文件, 不修改历史 xlsx 中的实验ID.
    """
    client, _fake_manager, template_path = api_client
    history_tasks_dir = synthesis.DEFAULT_HISTORY_TASKS_DIR

    history_task_dir = history_tasks_dir / "901"
    history_task_dir.mkdir(parents=True, exist_ok=True)
    history_template_path = history_task_dir / "901_experiment_plan.xlsx"
    _create_template(history_template_path)

    history_task_dir_2 = history_tasks_dir / "900"
    history_task_dir_2.mkdir(parents=True, exist_ok=True)
    history_template_path_2 = history_task_dir_2 / "900_experiment_plan.xlsx"
    _create_template(history_template_path_2)

    history_task_dir_3 = history_tasks_dir / "899"
    history_task_dir_3.mkdir(parents=True, exist_ok=True)
    history_template_path_3 = history_task_dir_3 / "899_experiment_plan.xlsx"
    _create_legacy_template_without_gc_sheet(history_template_path_3)

    (history_tasks_dir / "898").mkdir(parents=True, exist_ok=True)

    payload = _updated_payload()
    payload["param_rows"][1]["value"] = "历史任务A"
    payload["param_rows"][2]["value"] = 901
    payload["params"] = {
        "实验名称": "历史任务A",
        "实验ID": 901,
    }
    payload["rows"] = payload["rows"] + [
        [13, "对叔丁基苯甲醛", "13.0eq", "乙腈", "1mL"],
        [14, "对叔丁基苯甲醛", "14.0eq", "乙腈", "1mL"],
    ]
    write_reaction_template(payload, history_template_path)

    payload_2 = _updated_payload()
    payload_2["param_rows"][1]["value"] = "第二个历史任务"
    payload_2["param_rows"][2]["value"] = 900
    payload_2["params"] = {
        "实验名称": "第二个历史任务",
        "实验ID": 900,
    }
    write_reaction_template(payload_2, history_template_path_2)

    list_response = client.get(
        "/api/synthesis/reaction-template/history",
        params={"page": 1, "page_size": 10},
    )
    assert list_response.status_code == 200
    list_body = list_response.json()
    items = list_body["items"]
    assert list_body["total"] == 3
    assert list_body["page"] == 1
    assert list_body["page_size"] == 10
    assert items[0]["task_id"] == 901
    assert items[0]["task_name"] == "历史任务A"
    assert items[0]["experiment_count"] == 14
    assert any(item["task_id"] == 899 for item in items)

    search_response = client.get(
        "/api/synthesis/reaction-template/history",
        params={"q": "第二个", "page": 1, "page_size": 10},
    )
    assert search_response.status_code == 200
    search_body = search_response.json()
    assert search_body["total"] == 1
    assert search_body["items"][0]["task_id"] == 900

    load_response = client.get("/api/synthesis/reaction-template/history/901")
    assert load_response.status_code == 200
    body = load_response.json()
    assert body["params"]["实验名称"] == "历史任务A"
    assert body["params"]["实验ID"] == 901
    assert body["has_gc_ms_yield_sheet"] is True
    assert len(body["rows"]) == 14

    legacy_load_response = client.get("/api/synthesis/reaction-template/history/899")
    assert legacy_load_response.status_code == 200
    legacy_body = legacy_load_response.json()
    assert legacy_body["has_gc_ms_yield_sheet"] is False
    assert legacy_body["gc_ms_yield"]["internal_standard_smiles"] == ""
    assert legacy_body["gc_ms_yield"]["products"] == []

    reloaded_history = write_reaction_template(_updated_payload(), template_path)
    assert reloaded_history["params"]["实验名称"] == "Web任务"

    history_template_after = client.get("/api/synthesis/reaction-template/history/901")
    assert history_template_after.status_code == 200
    assert history_template_after.json()["params"]["实验ID"] == 901


def test_submit_saves_template_and_uses_default_path(
    api_client: tuple[TestClient, FakeSynthesisManager, Path],
) -> None:
    """
    功能:
        验证上传任务会先保存 Web 表格, 同步化学品库, 再把默认模板路径交给 create_task_by_file.
    """
    client, fake_manager, template_path = api_client
    response = client.post("/api/synthesis/reaction-template/submit", json=_updated_payload())
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    job = _wait_job(client, job_id)
    assert job["name"] == "上传任务"
    assert job["result"]["task_id"] == 321
    assert fake_manager.submitted_path == str(template_path)
    assert fake_manager.chemical_sync_calls == 1
    assert fake_manager.call_order == ["sync_chemicals_to_station", "create_task_by_file"]

    saved = client.get("/api/synthesis/reaction-template").json()
    assert saved["params"]["实验名称"] == "Web任务"
    assert saved["gc_ms_yield"]["yield_method"] == "标准曲线"
    assert len(saved["gc_ms_yield"]["products"]) == 2


def test_sync_chemicals_to_station_endpoint_starts_job(
    api_client: tuple[TestClient, FakeSynthesisManager, Path],
) -> None:
    """
    功能:
        验证化学品库对齐接口创建后台任务并调用合成工站同步逻辑.
    """
    client, fake_manager, _template_path = api_client

    response = client.post("/api/synthesis/chemicals/sync-to-station")

    assert response.status_code == 200
    job = _wait_job(client, response.json()["job_id"])
    assert job["name"] == "对齐合成工站化学品库"
    assert job["result"] == {"total": 2, "updated_rows": 2, "id_written": 2}
    assert fake_manager.chemical_sync_calls == 1
    assert fake_manager.call_order == ["sync_chemicals_to_station"]


def test_resource_check_uses_default_path(
    api_client: tuple[TestClient, FakeSynthesisManager, Path],
) -> None:
    """
    功能:
        验证物料核算使用默认模板路径并开启上料文件生成.
    """
    client, fake_manager, template_path = api_client
    response = client.post(
        "/api/synthesis/resource-check",
        json={"template": _updated_payload(), "auto_generate_batch_file": True},
    )
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    job = _wait_job(client, job_id)
    assert job["result"]["ready"] is True
    assert job["result"]["missing"] == ["乙腈:1mL"]
    assert job["result"]["auto_generate_batch_file"] is True
    assert fake_manager.resource_check_auto_generate_batch_file is True
    assert fake_manager.resource_check_path == str(template_path)
    saved = client.get("/api/synthesis/reaction-template").json()
    assert saved["gc_ms_yield"]["internal_standard_smiles"] == "CC(C)C1=CC(C(C)C)=CC(C(C)C)=C1"


def test_resource_check_can_disable_batch_file_generation(
    api_client: tuple[TestClient, FakeSynthesisManager, Path],
) -> None:
    """
    功能:
        验证物料核算可以关闭自动修改上料文件选项.
    """
    client, fake_manager, template_path = api_client
    response = client.post(
        "/api/synthesis/resource-check",
        json={"template": _updated_payload(), "auto_generate_batch_file": False},
    )
    assert response.status_code == 200

    job = _wait_job(client, response.json()["job_id"])
    assert job["result"]["auto_generate_batch_file"] is False
    assert fake_manager.resource_check_auto_generate_batch_file is False
    assert fake_manager.resource_check_path == str(template_path)


def test_batch_in_template_api_reads_and_writes(
    api_client: tuple[TestClient, FakeSynthesisManager, Path],
) -> None:
    """
    功能:
        验证上料文件接口可以读取并保存固定上料表格.
    """
    client, _fake_manager, _template_path = api_client

    original = client.get("/api/synthesis/batch-in-template")
    assert original.status_code == 200
    assert original.json()["headers"] == ["position", "tray_type", "content", "shelf_position", "storage"]

    response = client.put("/api/synthesis/batch-in-template", json=_updated_batch_in_payload())
    assert response.status_code == 200
    assert response.json()["rows"] == _updated_batch_in_payload()["rows"]

    saved = client.get("/api/synthesis/batch-in-template")
    assert saved.status_code == 200
    assert saved.json()["rows"] == _updated_batch_in_payload()["rows"]


def test_print_reagent_labels_saves_batch_in_payload_first(
    api_client: tuple[TestClient, FakeSynthesisManager, Path],
) -> None:
    """
    功能:
        验证打印试剂标签会先保存 Web 上料表格, 再调用合成工站打印函数.
    """
    client, fake_manager, _template_path = api_client
    response = client.post(
        "/api/synthesis/batch-in-template/print-reagent-labels",
        json=_updated_batch_in_payload(),
    )
    assert response.status_code == 200

    job = _wait_job(client, response.json()["job_id"])
    assert job["name"] == "打印试剂标签"
    assert job["result"]["printed"] is True
    assert fake_manager.reagent_label_print_calls == 1

    saved = client.get("/api/synthesis/batch-in-template")
    assert saved.status_code == 200
    assert saved.json()["rows"] == _updated_batch_in_payload()["rows"]


def test_print_batch_in_table_saves_payload_and_uses_hp_printer(
    api_client: tuple[TestClient, FakeSynthesisManager, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    功能:
        验证打印上料表格会保存 payload, 并固定使用 HP 打印机.
    """
    client, _fake_manager, _template_path = api_client
    calls: list[tuple[Path, str]] = []

    def _fake_print_batch_in_table(path: Path, printer_name: str) -> Dict[str, str]:
        """
        功能:
            记录打印调用, 避免测试触发真实打印.
        参数:
            path: Path, 上料文件路径.
            printer_name: str, 打印机名称.
        返回:
            Dict[str, str], 打印结果.
        """
        calls.append((Path(path), printer_name))
        return {"printer_name": printer_name, "file_path": str(path)}

    monkeypatch.setattr(synthesis, "print_batch_in_table", _fake_print_batch_in_table)

    response = client.post(
        "/api/synthesis/batch-in-template/print-table",
        json=_updated_batch_in_payload(),
    )
    assert response.status_code == 200

    job = _wait_job(client, response.json()["job_id"])
    assert job["name"] == "打印上料表格"
    assert job["result"]["printer_name"] == "HP Laser MFP 1136-1139 1188"
    assert len(calls) == 1
    assert calls[0][0] == synthesis.DEFAULT_BATCH_IN_TEMPLATE
    assert calls[0][1] == "HP Laser MFP 1136-1139 1188"

    saved = client.get("/api/synthesis/batch-in-template")
    assert saved.status_code == 200
    assert saved.json()["rows"] == _updated_batch_in_payload()["rows"]


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


def test_workflow_runs_from_selected_start_step(
    api_client: tuple[TestClient, FakeSynthesisManager, Path],
) -> None:
    """
    功能:
        验证工作流可以从指定起点开始, 并按实验 ID 继续执行后续步骤.
    """
    client, fake_manager, _template_path = api_client
    response = client.post(
        "/api/synthesis/workflow/start",
        json=_workflow_payload(start_step="start_task"),
    )
    assert response.status_code == 200

    workflow_id = response.json()["workflow_id"]
    job = _wait_job(client, workflow_id)
    assert job["name"] == "合成工作流"

    status_response = client.get(f"/api/synthesis/workflow/{workflow_id}")
    assert status_response.status_code == 200
    body = status_response.json()
    assert body["status"] == "succeeded"
    assert body["experiment_id"] == 321
    assert [step["status"] for step in body["steps"][:2]] == ["skipped", "skipped"]
    assert fake_manager.workflow_calls == [
        (
            "start_task",
            {
                "task_id": 321,
                "check_glovebox_env": True,
                "water_limit_ppm": 10.0,
                "oxygen_limit_ppm": 10.0,
            },
        ),
        ("wait_task", {"task_id": 321, "poll_interval_s": 2.0}),
        ("batch_out", 321),
        ("auto_unload", True),
        ("poll_analysis", {"task_id": "321", "poll_interval": 30.0}),
        ("calculate_yields", "321"),
    ]


def test_workflow_manual_batch_in_uses_batch_file(
    api_client: tuple[TestClient, FakeSynthesisManager, Path],
) -> None:
    """
    功能:
        验证工作流手动上料模式调用 batch_in_tray_by_file.
    """
    client, fake_manager, batch_template_path = api_client
    response = client.post(
        "/api/synthesis/workflow/start",
        json=_workflow_payload(batch_in={"mode": "manual", "chamber_capacity": 8}),
    )
    assert response.status_code == 200

    _wait_job(client, response.json()["workflow_id"])
    assert fake_manager.workflow_calls[0] == ("batch_in_manual", str(synthesis.DEFAULT_BATCH_IN_TEMPLATE))
    assert synthesis.DEFAULT_BATCH_IN_TEMPLATE == batch_template_path.parent / "batch_in_tray.xlsx"


def test_workflow_agv_batch_in_passes_capacity(
    api_client: tuple[TestClient, FakeSynthesisManager, Path],
) -> None:
    """
    功能:
        验证工作流 AGV 上料模式透传过渡舱容量参数.
    """
    client, fake_manager, _template_path = api_client
    response = client.post(
        "/api/synthesis/workflow/start",
        json=_workflow_payload(batch_in={"mode": "agv", "chamber_capacity": 4}),
    )
    assert response.status_code == 200

    _wait_job(client, response.json()["workflow_id"])
    assert fake_manager.workflow_calls[0] == (
        "batch_in_agv",
        {
            "file_path": str(synthesis.DEFAULT_BATCH_IN_TEMPLATE),
            "chamber_capacity": 4,
        },
    )


def test_workflow_resource_check_uses_secondary_check_without_batch_generation(
    api_client: tuple[TestClient, FakeSynthesisManager, Path],
) -> None:
    """
    功能:
        验证工作流物料检查固定使用二次物料核算且不自动改写上料文件.
    """
    client, fake_manager, template_path = api_client
    response = client.post(
        "/api/synthesis/workflow/start",
        json=_workflow_payload(start_step="resource_check"),
    )
    assert response.status_code == 200

    _wait_job(client, response.json()["workflow_id"])
    assert fake_manager.resource_check_path == str(template_path)
    assert fake_manager.resource_check_auto_generate_batch_file is False


def test_workflow_submit_analysis_can_run_after_agv_step(
    api_client: tuple[TestClient, FakeSynthesisManager, Path],
) -> None:
    """
    功能:
        验证关闭 AGV 转运后立即提交时, 工作流会在提交分析任务步骤单独提交.
    """
    client, fake_manager, _template_path = api_client
    response = client.post(
        "/api/synthesis/workflow/start",
        json=_workflow_payload(
            start_step="auto_unload",
            submit_analysis={"auto_submit_after_agv": False},
        ),
    )
    assert response.status_code == 200

    _wait_job(client, response.json()["workflow_id"])
    assert fake_manager.workflow_calls == [
        ("auto_unload", False),
        ("submit_analysis", "321"),
        ("poll_analysis", {"task_id": "321", "poll_interval": 30.0}),
        ("calculate_yields", "321"),
    ]


def test_workflow_skips_analysis_steps_when_task_has_no_analysis(
    api_client: tuple[TestClient, FakeSynthesisManager, Path],
) -> None:
    """
    功能:
        验证任务未设置分析方法时, 工作流不会提交分析任务或执行谱图处理.
    """
    client, fake_manager, _template_path = api_client
    response = client.post(
        "/api/synthesis/workflow/start",
        json=_workflow_payload(start_step="auto_unload", has_analysis_task=False),
    )
    assert response.status_code == 200

    workflow_id = response.json()["workflow_id"]
    _wait_job(client, workflow_id)
    status_response = client.get(f"/api/synthesis/workflow/{workflow_id}")
    assert status_response.status_code == 200
    body = status_response.json()
    statuses = {step["id"]: step["status"] for step in body["steps"]}
    assert statuses["submit_analysis"] == "skipped"
    assert statuses["poll_analysis"] == "skipped"
    assert statuses["calculate_yields"] == "skipped"
    assert fake_manager.workflow_calls == [("auto_unload", False)]


def test_workflow_submit_analysis_start_step_submits_directly(
    api_client: tuple[TestClient, FakeSynthesisManager, Path],
) -> None:
    """
    功能:
        验证从提交分析任务步骤开始时不会误认为已在 AGV 转运阶段提交.
    """
    client, fake_manager, _template_path = api_client
    response = client.post(
        "/api/synthesis/workflow/start",
        json=_workflow_payload(start_step="submit_analysis"),
    )
    assert response.status_code == 200

    _wait_job(client, response.json()["workflow_id"])
    assert fake_manager.workflow_calls == [
        ("submit_analysis", "321"),
        ("poll_analysis", {"task_id": "321", "poll_interval": 30.0}),
        ("calculate_yields", "321"),
    ]


def test_workflow_pause_and_resume_calls_station_controls(
    api_client: tuple[TestClient, FakeSynthesisManager, Path],
) -> None:
    """
    功能:
        验证任务监控阶段暂停会调用 stop_task, 恢复会调用 fault_recovery.
    """
    client, fake_manager, _template_path = api_client
    fake_manager.entered_event = threading.Event()
    fake_manager.release_event = threading.Event()

    response = client.post(
        "/api/synthesis/workflow/start",
        json=_workflow_payload(start_step="wait_task"),
    )
    assert response.status_code == 200
    workflow_id = response.json()["workflow_id"]
    assert fake_manager.entered_event.wait(timeout=2) is True

    pause_response = client.post(f"/api/synthesis/workflow/{workflow_id}/pause")
    assert pause_response.status_code == 200
    assert fake_manager.stop_task_calls == [321]

    resume_response = client.post(f"/api/synthesis/workflow/{workflow_id}/resume")
    assert resume_response.status_code == 200
    assert fake_manager.fault_recovery_calls == [{"resume_task": 1, "recovery_type": 0}]

    fake_manager.release_event.set()
    _wait_job(client, workflow_id)


def test_workflow_stop_cancels_station_task_and_skips_remaining_steps(
    api_client: tuple[TestClient, FakeSynthesisManager, Path],
) -> None:
    """
    功能:
        验证工作流停止会取消当前合成任务, 并且不继续执行后续步骤.
    """
    client, fake_manager, _template_path = api_client
    fake_manager.entered_event = threading.Event()
    fake_manager.release_event = threading.Event()

    response = client.post(
        "/api/synthesis/workflow/start",
        json=_workflow_payload(start_step="wait_task"),
    )
    assert response.status_code == 200
    workflow_id = response.json()["workflow_id"]
    assert fake_manager.entered_event.wait(timeout=2) is True

    stop_response = client.post(f"/api/synthesis/workflow/{workflow_id}/stop")
    assert stop_response.status_code == 200
    stop_body = stop_response.json()
    assert stop_body["status"] == "stopping"
    assert fake_manager.cancel_task_calls == [321]

    fake_manager.release_event.set()
    job = _wait_job(client, workflow_id, expected_status="stopped")
    assert job["status"] == "stopped"

    status_response = client.get(f"/api/synthesis/workflow/{workflow_id}")
    assert status_response.status_code == 200
    body = status_response.json()
    assert body["status"] == "stopped"
    statuses = {step["id"]: step["status"] for step in body["steps"]}
    assert statuses["wait_task"] == "stopped"
    assert statuses["batch_out"] == "skipped"
    assert statuses["auto_unload"] == "skipped"
    assert fake_manager.workflow_calls == [
        ("wait_task", {"task_id": 321, "poll_interval_s": 2.0}),
    ]


def test_workflow_start_returns_409_when_job_busy(
    api_client: tuple[TestClient, FakeSynthesisManager, Path],
) -> None:
    """
    功能:
        验证已有后台任务运行时工作流启动返回 409.
    """
    client, fake_manager, _template_path = api_client
    fake_manager.entered_event = threading.Event()
    fake_manager.release_event = threading.Event()

    first = client.post("/api/synthesis/reaction-template/submit", json=_updated_payload())
    assert first.status_code == 200
    assert fake_manager.entered_event.wait(timeout=2) is True

    second = client.post("/api/synthesis/workflow/start", json=_workflow_payload())
    assert second.status_code == 409

    fake_manager.release_event.set()
    _wait_job(client, first.json()["job_id"])


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

    second = client.post(
        "/api/synthesis/resource-check",
        json={"template": _updated_payload(), "auto_generate_batch_file": True},
    )
    assert second.status_code == 409

    fake_manager.release_event.set()
    _wait_job(client, first.json()["job_id"])


def test_sync_chemicals_to_station_returns_409_when_job_busy(
    api_client: tuple[TestClient, FakeSynthesisManager, Path],
) -> None:
    """
    功能:
        验证已有独占后台任务运行时, 化学品库对齐接口返回 409.
    """
    client, fake_manager, _template_path = api_client
    fake_manager.entered_event = threading.Event()
    fake_manager.release_event = threading.Event()

    first = client.post("/api/synthesis/reaction-template/submit", json=_updated_payload())
    assert first.status_code == 200
    assert fake_manager.entered_event.wait(timeout=2) is True

    second = client.post("/api/synthesis/chemicals/sync-to-station")
    assert second.status_code == 409
    assert fake_manager.chemical_sync_calls == 1

    fake_manager.release_event.set()
    _wait_job(client, first.json()["job_id"])
