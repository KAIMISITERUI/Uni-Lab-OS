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


def _make_status_detail(
    raw_status: str,
    instrument_status: str,
    message: str = "",
    total_sample_count: int = 0,
    unrun_sample_count: int = 0,
) -> Dict[str, Any]:
    """
    功能:
        构造智达状态五键 dict, 与驱动 get_status_detail 保持同形.
    参数:
        raw_status/instrument_status/message/total_sample_count/unrun_sample_count: 与协议字段对应.
    返回:
        Dict[str, Any], 状态明细.
    """
    return {
        "raw_status": raw_status,
        "instrument_status": instrument_status,
        "message": message,
        "total_sample_count": total_sample_count,
        "unrun_sample_count": unrun_sample_count,
    }


class FakeZhidaClient:
    """
    功能:
        提供状态查询测试用假智达客户端.
    """

    status_detail_by_host: Dict[str, Dict[str, Any]] = {
        "gc-host": _make_status_detail(raw_status="Idle", instrument_status="Idle"),
        "uplc-host": _make_status_detail(raw_status="Offline", instrument_status="Offline"),
        "hplc-host": _make_status_detail(raw_status="Error", instrument_status="Error"),
    }
    methods_by_host: Dict[str, Dict[str, Any]] = {
        "gc-host": {"result": "OK", "message": [" gc-method-a ", "gc-method-b", ""]},
        "uplc-host": {
            "result": "OK",
            "message": "[\"280_12min.mtl\",\"300_15min.mtl\"]",
        },
        "hplc-host": {"result": "OK", "message": ["hplc-method-a"]},
    }

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    def get_status_detail(self) -> Dict[str, Any]:
        """
        功能:
            按 host 返回六键状态明细.
        返回:
            Dict[str, Any], 状态明细.
        """
        return self.status_detail_by_host[self.host]

    def get_methods(self) -> Dict[str, Any]:
        """
        功能:
            按 host 返回测试方法列表响应.
        返回:
            Dict[str, Any], get_methods 协议响应.
        """
        return self.methods_by_host[self.host]

    def close(self) -> None:
        """
        功能:
            关闭测试连接.
        返回:
            None.
        """
        return None


class FakePartialFailureZhidaClient(FakeZhidaClient):
    """
    功能:
        提供单台方法列表查询失败的测试客户端.
    """

    def get_methods(self) -> Dict[str, Any]:
        """
        功能:
            UPLC_QTOF 返回失败响应, 其它仪器沿用正常方法列表.
        返回:
            Dict[str, Any], get_methods 协议响应.
        """
        if self.host == "uplc-host":
            return {"result": "Error", "message": "Project 未打开"}
        return super().get_methods()


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
    assert items[0]["instrument_status"] == "Idle"
    assert items[0]["connected"] is True
    assert "queue_status" not in items[0]
    assert items[0]["total_sample_count"] == 0
    assert items[0]["unrun_sample_count"] == 0
    assert items[0]["message"] == ""
    assert items[1]["instrument_status"] == "Offline"
    assert items[1]["connected"] is False
    assert items[2]["instrument_status"] == "Error"
    assert items[2]["connected"] is False


def test_status_passes_run_sample_and_sample_counts(
    api_client: tuple[TestClient, FakeAnalysisController],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    功能:
        验证 RunSample 状态在线, 并透传样品计数与消息.
    """
    client, _fake_controller = api_client

    class RunSampleZhidaClient(FakeZhidaClient):
        """
        功能:
            提供 gc-host 上 RunSample 状态 fixture.
        """

        status_detail_by_host = {
            "gc-host": _make_status_detail(
                raw_status="RunSample",
                instrument_status="RunSample",
                message="sample active",
                total_sample_count=10,
                unrun_sample_count=4,
            ),
            "uplc-host": _make_status_detail(raw_status="Idle", instrument_status="Idle"),
            "hplc-host": _make_status_detail(raw_status="Idle", instrument_status="Idle"),
        }

    monkeypatch.setattr(analysis, "ZhidaClient", RunSampleZhidaClient)

    response = client.get("/api/analysis/status")

    assert response.status_code == 200
    gc_item = response.json()["items"][0]
    assert gc_item["instrument"] == "gc_ms"
    assert gc_item["raw_status"] == "RunSample"
    assert gc_item["instrument_status"] == "RunSample"
    assert "queue_status" not in gc_item
    assert gc_item["message"] == "sample active"
    assert gc_item["total_sample_count"] == 10
    assert gc_item["unrun_sample_count"] == 4
    assert gc_item["connected"] is True


def test_methods_returns_three_analysis_devices_with_parsed_methods(
    api_client: tuple[TestClient, FakeAnalysisController],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    功能:
        验证方法列表接口按固定仪器顺序返回, 并解析列表和 JSON 列表字符串.
    """
    client, _fake_controller = api_client
    monkeypatch.setattr(analysis, "ZhidaClient", FakeZhidaClient)

    response = client.get("/api/analysis/methods")

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["instrument"] for item in items] == ["gc_ms", "uplc_qtof", "hplc"]
    assert items[0]["methods"] == ["gc-method-a", "gc-method-b"]
    assert items[1]["methods"] == ["280_12min.mtl", "300_15min.mtl"]
    assert items[2]["methods"] == ["hplc-method-a"]
    assert [item["error"] for item in items] == ["", "", ""]


def test_methods_keeps_other_devices_when_one_device_fails(
    api_client: tuple[TestClient, FakeAnalysisController],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    功能:
        验证单台仪器方法查询失败时返回该仪器错误, 其它仪器方法列表不受影响.
    """
    client, _fake_controller = api_client
    monkeypatch.setattr(analysis, "ZhidaClient", FakePartialFailureZhidaClient)

    response = client.get("/api/analysis/methods")

    assert response.status_code == 200
    items = response.json()["items"]
    assert items[0]["methods"] == ["gc-method-a", "gc-method-b"]
    assert items[0]["error"] == ""
    assert items[1]["methods"] == []
    assert items[1]["error"] != ""
    assert items[2]["methods"] == ["hplc-method-a"]
    assert items[2]["error"] == ""


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


def test_submit_accepts_auto_wash_stop_rows_with_zero_injection(
    api_client: tuple[TestClient, FakeAnalysisController],
) -> None:
    """
    功能:
        验证前端追加的冲柱和停机行允许 0 进样量, 并按固定表头保存到 CSV.
    """
    client, fake_controller = api_client
    uplc_sample = _sample_row("Rack 2")
    uplc_sample["VialPos"] = 8
    hplc_sample = _sample_row("Rack 3")
    hplc_sample["VialPos"] = 9
    response = client.post(
        "/api/analysis/submit",
        json={
            "tables": {
                "uplc_qtof": [
                    uplc_sample,
                    {
                        "SampleName": "wash_stop",
                        "AcqMethod": "wash_stop",
                        "RackCode": "Rack 2",
                        "VialPos": 8,
                        "SmplInjVol": 0,
                        "OutputFile": "wash_stop",
                    },
                ],
                "hplc": [
                    hplc_sample,
                    {
                        "SampleName": "wash",
                        "AcqMethod": "wash",
                        "RackCode": "Rack 3",
                        "VialPos": 9,
                        "SmplInjVol": 0,
                        "OutputFile": "wash",
                    },
                    {
                        "SampleName": "stop",
                        "AcqMethod": "stop",
                        "RackCode": "Rack 3",
                        "VialPos": 9,
                        "SmplInjVol": 0,
                        "OutputFile": "stop",
                    },
                ],
            }
        },
    )

    assert response.status_code == 200
    body = response.json()
    _wait_job(client, body["job_id"])

    uplc_csv_path = Path(body["saved_files"]["uplc_qtof"])
    with uplc_csv_path.open("r", encoding="utf-8", newline="") as file_obj:
        uplc_rows = list(csv.reader(file_obj))
    hplc_csv_path = Path(body["saved_files"]["hplc"])
    with hplc_csv_path.open("r", encoding="utf-8", newline="") as file_obj:
        hplc_rows = list(csv.reader(file_obj))

    assert uplc_rows[0] == analysis.CSV_HEADERS
    assert uplc_rows[-1] == ["wash_stop", "wash_stop", "Rack 2", "8", "0", "wash_stop"]
    assert hplc_rows[0] == analysis.CSV_HEADERS
    assert hplc_rows[-2] == ["wash", "wash", "Rack 3", "9", "0", "wash"]
    assert hplc_rows[-1] == ["stop", "stop", "Rack 3", "9", "0", "stop"]
    assert [instrument for instrument, _path in fake_controller.calls] == ["uplc_qtof", "hplc"]


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
