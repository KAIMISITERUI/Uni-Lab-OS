# -*- coding: utf-8 -*-
"""
功能:
    覆盖 EIT Hub 标签打印机 Web API.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml
from fastapi.testclient import TestClient

from unilabos.devices.eit_hub.web.app import create_app
from unilabos.devices.eit_hub.web.jobs import JobManager
from unilabos.devices.eit_hub.web.routers import label_printer


class FakeLabelPrintService:
    """
    功能:
        提供标签打印 API 测试用假打印服务.
    """

    instances: List["FakeLabelPrintService"] = []

    def __init__(self, config_path: str) -> None:
        """
        功能:
            记录构造参数并准备调用记录.
        参数:
            config_path: str, 标签模板路径.
        返回:
            None.
        """
        self.config_path = config_path
        self.connected = False
        self.disconnected = False
        self.printed_rows: List[List[str]] = []
        FakeLabelPrintService.instances.append(self)

    def connect(self) -> bool:
        """
        功能:
            模拟打印机连接成功.
        返回:
            bool, 始终返回 True.
        """
        self.connected = True
        return True

    def print_label(self, row_values: List[str]) -> bool:
        """
        功能:
            记录单行标签打印内容.
        参数:
            row_values: List[str], 单行标签内容.
        返回:
            bool, 始终返回 True.
        """
        self.printed_rows.append(list(row_values))
        return True

    def disconnect(self) -> None:
        """
        功能:
            记录断开连接.
        返回:
            None.
        """
        self.disconnected = True


@pytest.fixture()
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Path]:
    """
    功能:
        创建隔离的标签打印机 API 测试客户端.
    参数:
        tmp_path: Path, pytest 临时目录.
        monkeypatch: pytest.MonkeyPatch, monkeypatch 工具.
    返回:
        tuple[TestClient, Path], 测试客户端和 profiles 目录.
    """
    profile_root = tmp_path / "profiles"
    profile_root.mkdir(parents=True, exist_ok=True)
    _write_profile(profile_root / "25x10x2.yaml", _sample_config(columns=2))
    _write_profile(profile_root / "single.yml", _sample_config(columns=1))
    (profile_root / "readme.txt").write_text("ignore", encoding="utf-8")

    FakeLabelPrintService.instances = []
    monkeypatch.setattr(label_printer, "PROFILE_ROOT", profile_root)
    monkeypatch.setattr(label_printer, "job_manager", JobManager())
    monkeypatch.setattr(label_printer, "LabelPrintService", FakeLabelPrintService)

    return TestClient(create_app()), profile_root


def _sample_config(
    columns: int = 2,
    width: float = 56,
    margin: float = 1.3,
    column_gap: float = 3,
) -> Dict[str, Any]:
    """
    功能:
        构造测试用标签模板配置.
    参数:
        columns: int, 标签列数.
        width: float, 纸张宽度.
        margin: float, 左右边距.
        column_gap: float, 列间距.
    返回:
        Dict[str, Any], 标签模板配置.
    """
    return {
        "printer": {
            "ppi": 300,
        },
        "paper": {
            "width": width,
            "height": 10,
            "unit": "mm",
            "columns": columns,
            "column_gap": column_gap,
            "margin": margin,
            "gap": 2,
            "gap_offset": 0,
            "direction": 1,
        },
        "font": {
            "name": "微软雅黑",
            "size": 60,
            "bold": 0,
            "underline": 0,
            "rotation": 0,
        },
        "position": {
            "x": 0.5,
            "y": 1.5,
        },
    }


def _write_profile(path: Path, config: Dict[str, Any]) -> None:
    """
    功能:
        写入测试 YAML 模板.
    参数:
        path: Path, 模板路径.
        config: Dict[str, Any], 模板配置.
    返回:
        None.
    """
    path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")


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
        response = client.get(f"/api/label-printer/jobs/{job_id}")
        assert response.status_code == 200
        last_body = response.json()
        if last_body["status"] in ("succeeded", "failed"):
            assert last_body["status"] == expected_status
            return last_body
        time.sleep(0.05)
    raise AssertionError(f"后台任务未按时结束: {last_body}")


def test_profiles_list_only_returns_yaml_files(api_client: tuple[TestClient, Path]) -> None:
    """
    功能:
        验证模板列表只返回 YAML 文件.
    """
    client, _profile_root = api_client

    response = client.get("/api/label-printer/profiles")

    assert response.status_code == 200
    body = response.json()
    assert [item["name"] for item in body["items"]] == ["25x10x2.yaml", "single.yml"]


def test_get_profile_returns_config_and_columns(api_client: tuple[TestClient, Path]) -> None:
    """
    功能:
        验证读取模板会返回配置和列数.
    """
    client, _profile_root = api_client

    response = client.get("/api/label-printer/profiles/25x10x2.yaml")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "25x10x2.yaml"
    assert body["columns"] == 2
    assert body["config"]["paper"]["columns"] == 2


def test_save_profile_writes_yaml(api_client: tuple[TestClient, Path]) -> None:
    """
    功能:
        验证保存模板会写回 YAML 文件.
    """
    client, profile_root = api_client
    payload = {"config": _sample_config(columns=3, width=70)}

    response = client.put("/api/label-printer/profiles/25x10x2.yaml", json=payload)

    assert response.status_code == 200
    assert response.json()["columns"] == 3
    saved_config = yaml.safe_load((profile_root / "25x10x2.yaml").read_text(encoding="utf-8"))
    assert saved_config["paper"]["columns"] == 3
    assert saved_config["paper"]["width"] == 70.0


def test_save_profile_rejects_invalid_label_width(api_client: tuple[TestClient, Path]) -> None:
    """
    功能:
        验证无效标签宽度会返回 400.
    """
    client, _profile_root = api_client
    payload = {
        "config": _sample_config(columns=3, width=5, margin=2, column_gap=2),
    }

    response = client.put("/api/label-printer/profiles/25x10x2.yaml", json=payload)

    assert response.status_code == 400
    assert "有效标签宽度" in response.json()["detail"]


def test_save_profile_as_creates_new_file_and_rejects_duplicate(
    api_client: tuple[TestClient, Path],
) -> None:
    """
    功能:
        验证另存为会创建新模板, 同名模板会被拒绝.
    """
    client, profile_root = api_client
    payload = {
        "name": "new_profile.yaml",
        "config": _sample_config(columns=1),
    }

    response = client.post("/api/label-printer/profiles", json=payload)

    assert response.status_code == 200
    assert response.json()["name"] == "new_profile.yaml"
    assert (profile_root / "new_profile.yaml").is_file() is True

    duplicate_response = client.post("/api/label-printer/profiles", json=payload)
    assert duplicate_response.status_code == 400
    assert "已存在" in duplicate_response.json()["detail"]


def test_print_labels_skips_empty_rows_and_preserves_columns(
    api_client: tuple[TestClient, Path],
) -> None:
    """
    功能:
        验证打印接口跳过全空行并按模板列数保留二维行结构.
    """
    client, profile_root = api_client
    response = client.post(
        "/api/label-printer/print",
        json={
            "profile": "25x10x2.yaml",
            "rows": [
                ["A", "B"],
                ["", ""],
                ["C"],
                ["D", "E", "F"],
            ],
        },
    )

    assert response.status_code == 200
    job = _wait_job(client, response.json()["job_id"])
    assert job["name"] == "打印标签"
    assert job["result"]["printed_rows"] == 3
    assert job["result"]["skipped_rows"] == 1

    assert len(FakeLabelPrintService.instances) == 1
    service = FakeLabelPrintService.instances[0]
    assert service.connected is True
    assert service.disconnected is True
    assert service.config_path == str(profile_root / "25x10x2.yaml")
    assert service.printed_rows == [
        ["A", "B"],
        ["C", ""],
        ["D", "E"],
    ]
