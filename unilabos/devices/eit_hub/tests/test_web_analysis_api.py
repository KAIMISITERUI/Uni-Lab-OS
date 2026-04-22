# -*- coding: utf-8 -*-
"""
功能:
    覆盖 EIT Hub 分析工站 Web API.
"""

from __future__ import annotations

import csv
import shutil
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from unilabos.devices.eit_hub.web.app import create_app
from unilabos.devices.eit_hub.web.deps import get_analysis_controller
from unilabos.devices.eit_hub.web.jobs import JobManager
from unilabos.devices.eit_hub.web.routers import analysis, synthesis


class FakeAnalysisController:
    """
    功能:
        提供分析工站 Web API 测试用假控制器.
    """

    def __init__(self, data_dir: Path) -> None:
        self._settings = SimpleNamespace(
            gc_ms_host="gc-host",
            gc_ms_port=5701,
            gc_ms_timeout=1.0,
            uplc_qtof_host="uplc-host",
            uplc_qtof_port=5702,
            uplc_qtof_timeout=1.0,
            hplc_host="hplc-host",
            hplc_port=5703,
            hplc_timeout=1.0,
            data_dir=data_dir,
        )
        self.calls: list[tuple[str, str]] = []

    def submit_by_csv_path(self, instrument: str, csv_file_path: str) -> Dict[str, Any]:
        """
        功能:
            记录手工 CSV 提交调用并返回成功结果.
        参数:
            instrument: str, 仪器 key.
            csv_file_path: str, CSV 文件路径.
        返回:
            Dict[str, Any], 提交结果.
        """
        self.calls.append((instrument, csv_file_path))
        return {"success": True, "return_info": f"{instrument} ok"}


class FakeZhidaClient:
    """
    功能:
        提供状态查询测试用假智达客户端.
    """

    status_by_host: Dict[str, str] = {
        "gc-host": "Idle",
        "uplc-host": "Offline",
        "hplc-host": "Error",
    }

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    def get_status(self) -> str:
        """
        功能:
            按 host 返回测试状态.
        返回:
            str, 仪器状态.
        """
        return self.status_by_host[self.host]

    def close(self) -> None:
        """
        功能:
            关闭测试连接.
        返回:
            None.
        """
        return None


@pytest.fixture()
def api_client(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, FakeAnalysisController]:
    """
    功能:
        创建隔离的 Hub TestClient 和分析工站假控制器.
    返回:
        tuple[TestClient, FakeAnalysisController], 测试客户端和假控制器.
    """
    tmp_root = Path.cwd() / "_tmp_analysis_api"
    tmp_root.mkdir(parents=True, exist_ok=True)
    case_dir = tmp_root / uuid.uuid4().hex
    case_dir.mkdir(parents=True, exist_ok=False)
    request.addfinalizer(lambda: shutil.rmtree(case_dir, ignore_errors=True))

    fake_controller = FakeAnalysisController(case_dir / "analysis_data")
    test_job_manager = JobManager()
    monkeypatch.setattr(analysis, "job_manager", test_job_manager)
    monkeypatch.setattr(synthesis, "job_manager", test_job_manager)

    app = create_app()
    app.dependency_overrides[get_analysis_controller] = lambda: fake_controller
    client = TestClient(app)
    request.addfinalizer(client.close)
    return client, fake_controller


def _sample_row(rack_code: str = "Rack 1") -> Dict[str, Any]:
    """
    功能:
        生成一行有效分析样品数据.
    参数:
        rack_code: str, RackCode 测试值.
    返回:
        Dict[str, Any], 样品行.
    """
    return {
        "SampleName": "S001",
        "AcqMethod": "method-a",
        "RackCode": rack_code,
        "VialPos": 1,
        "SmplInjVol": 1,
        "OutputFile": "S001",
    }


def _empty_row() -> Dict[str, Any]:
    """
    功能:
        生成一行全空分析样品数据.
    返回:
        Dict[str, Any], 空行.
    """
    return {
        "SampleName": "",
        "AcqMethod": "",
        "RackCode": "",
        "VialPos": "",
        "SmplInjVol": "",
        "OutputFile": "",
    }


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


def test_status_returns_three_analysis_devices(
    api_client: tuple[TestClient, FakeAnalysisController],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    功能:
        验证状态接口返回三台分析设备并正确映射在线状态.
    """
    client, _fake_controller = api_client
    monkeypatch.setattr(analysis, "ZhidaClient", FakeZhidaClient)

    response = client.get("/api/analysis/status")

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["instrument"] for item in items] == ["gc_ms", "uplc_qtof", "hplc"]
    assert items[0]["status"] == "Idle"
    assert items[0]["connected"] is True
    assert items[1]["status"] == "Offline"
    assert items[1]["connected"] is False
    assert items[2]["status"] == "Error"
    assert items[2]["connected"] is False


def test_submit_rejects_invalid_rack_code(
    api_client: tuple[TestClient, FakeAnalysisController],
) -> None:
    """
    功能:
        验证 RackCode 只接受 Rack 1 到 Rack 6.
    """
    client, _fake_controller = api_client
    response = client.post(
        "/api/analysis/submit",
        json={"tables": {"gc_ms": [_sample_row("Rack 7")]}},
    )

    assert response.status_code == 400
    assert "RackCode 无效" in response.json()["detail"]


def test_submit_skips_empty_rows_and_rejects_incomplete_rows(
    api_client: tuple[TestClient, FakeAnalysisController],
) -> None:
    """
    功能:
        验证全空行跳过, 非空不完整行返回中文错误.
    """
    client, _fake_controller = api_client
    empty_response = client.post(
        "/api/analysis/submit",
        json={"tables": {"gc_ms": [_empty_row()]}},
    )
    assert empty_response.status_code == 400
    assert "至少需要填写" in empty_response.json()["detail"]

    incomplete_row = _sample_row()
    incomplete_row["AcqMethod"] = ""
    incomplete_response = client.post(
        "/api/analysis/submit",
        json={"tables": {"gc_ms": [_empty_row(), incomplete_row]}},
    )
    assert incomplete_response.status_code == 400
    assert "AcqMethod 不能为空" in incomplete_response.json()["detail"]


def test_submit_saves_csv_with_fixed_header(
    api_client: tuple[TestClient, FakeAnalysisController],
) -> None:
    """
    功能:
        验证手工提交会按固定表头保存 CSV 并提交有效仪器.
    """
    client, fake_controller = api_client
    response = client.post(
        "/api/analysis/submit",
        json={"tables": {"gc_ms": [_sample_row()], "uplc_qtof": [_empty_row()]}},
    )

    assert response.status_code == 200
    body = response.json()
    job = _wait_job(client, body["job_id"])
    assert job["result"]["success"] is True

    csv_path = Path(body["saved_files"]["gc_ms"])
    with csv_path.open("r", encoding="utf-8", newline="") as file_obj:
        rows = list(csv.reader(file_obj))

    assert rows[0] == analysis.CSV_HEADERS
    assert rows[1] == ["S001", "method-a", "Rack 1", "1", "1", "S001"]
    assert fake_controller.calls == [("gc_ms", str(csv_path))]


def test_submit_uses_fixed_instrument_order(
    api_client: tuple[TestClient, FakeAnalysisController],
) -> None:
    """
    功能:
        验证三台仪器按 gc_ms, uplc_qtof, hplc 固定顺序提交.
    """
    client, fake_controller = api_client
    response = client.post(
        "/api/analysis/submit",
        json={
            "tables": {
                "hplc": [_sample_row("Rack 3")],
                "gc_ms": [_sample_row("Rack 1")],
                "uplc_qtof": [_sample_row("Rack 2")],
            }
        },
    )

    assert response.status_code == 200
    _wait_job(client, response.json()["job_id"])
    assert [instrument for instrument, _path in fake_controller.calls] == ["gc_ms", "uplc_qtof", "hplc"]
