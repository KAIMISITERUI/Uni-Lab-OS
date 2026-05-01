# -*- coding: utf-8 -*-
"""
功能:
    提供 EIT Hub 设备状态总览 API, 统一检查各设备 TCP 端口可联通性.
"""

from __future__ import annotations

import logging
import os
import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Tuple

from fastapi import APIRouter, Request

logger = logging.getLogger("EITHubDevicesRouter")

JsonDict = Dict[str, object]

router = APIRouter(prefix="/api/devices", tags=["devices"])

TCP_TIMEOUT_S = 1.5
DEFAULT_HUB_PORT = 8770


@dataclass(frozen=True)
class EndpointSpec:
    """
    功能:
        描述单个 TCP 端点.
    参数:
        host: str, 设备 IP 或主机名.
        port: int, TCP 端口.
    返回:
        EndpointSpec.
    """

    host: str
    port: int


@dataclass(frozen=True)
class DeviceSpec:
    """
    功能:
        描述总览页中的一台设备及其待检查端点.
    参数:
        key: str, 设备稳定标识.
        name: str, 页面展示名称.
        category: str, 设备分类.
        endpoints: Tuple[EndpointSpec, ...], 待检查 TCP 端点.
    返回:
        DeviceSpec.
    """

    key: str
    name: str
    category: str
    endpoints: Tuple[EndpointSpec, ...]


DEVICE_SPECS: Tuple[DeviceSpec, ...] = (
    DeviceSpec(
        key="agv_chassis",
        name="AGV 底盘",
        category="AGV",
        endpoints=(
            EndpointSpec(host="192.168.1.5", port=19204),
            EndpointSpec(host="192.168.1.5", port=19206),
        ),
    ),
    DeviceSpec(
        key="agv_arm",
        name="AGV 机械臂",
        category="AGV",
        endpoints=(EndpointSpec(host="192.168.1.10", port=7003),),
    ),
    DeviceSpec(
        key="consumables_rack",
        name="耗材货架",
        category="耗材",
        endpoints=(EndpointSpec(host="192.168.1.45", port=6006),),
    ),
    DeviceSpec(
        key="synthesis_station",
        name="合成工站",
        category="合成",
        endpoints=(EndpointSpec(host="10.32.2.106", port=4669),),
    ),
    DeviceSpec(
        key="gc_ms",
        name="GC-MS",
        category="分析",
        endpoints=(EndpointSpec(host="10.40.6.101", port=5792),),
    ),
    DeviceSpec(
        key="uplc_qtof",
        name="UPLC_QTOF",
        category="分析",
        endpoints=(EndpointSpec(host="10.40.0.103", port=5792),),
    ),
    DeviceSpec(
        key="hplc",
        name="HPLC",
        category="分析",
        endpoints=(EndpointSpec(host="10.40.16.204", port=5792),),
    ),
    DeviceSpec(
        key="label_printer",
        name="标签打印机",
        category="打印",
        endpoints=(EndpointSpec(host="192.168.1.20", port=9100),),
    ),
)


@router.get("/status")
def get_device_status(request: Request) -> JsonDict:
    """
    功能:
        返回 EIT Hub 和所有外部设备的 TCP 端口连通性总览.
    参数:
        request: Request, 当前 HTTP 请求, 用于展示 Hub 访问地址.
    返回:
        Dict[str, object], 包含 checked_at 和 items 的设备状态快照.
    """
    checked_at = datetime.now().isoformat(timespec="seconds")
    items: List[JsonDict] = [_build_hub_status(request)]
    items.extend(_build_external_device_statuses())
    return {
        "checked_at": checked_at,
        "items": items,
    }


def _build_external_device_statuses() -> List[JsonDict]:
    """
    功能:
        并发检查外部设备端点并汇总为设备状态列表.
    返回:
        List[Dict[str, object]], 外部设备状态列表.
    """
    endpoint_jobs: List[Tuple[DeviceSpec, EndpointSpec]] = []
    for spec in DEVICE_SPECS:
        for endpoint in spec.endpoints:
            endpoint_jobs.append((spec, endpoint))

    results_by_device: Dict[str, List[JsonDict]] = {
        spec.key: [] for spec in DEVICE_SPECS
    }
    if len(endpoint_jobs) == 0:
        return [_summarize_device(spec, []) for spec in DEVICE_SPECS]

    max_workers = min(16, len(endpoint_jobs))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(_check_endpoint, endpoint, TCP_TIMEOUT_S): (spec, endpoint)
            for spec, endpoint in endpoint_jobs
        }
        for future in as_completed(future_map):
            spec, endpoint = future_map[future]
            try:
                endpoint_status = future.result()
            except Exception as exc:
                logger.exception(
                    "设备端口检查任务异常, device=%s, host=%s, port=%d",
                    spec.key,
                    endpoint.host,
                    endpoint.port,
                )
                endpoint_status = _endpoint_error(endpoint, f"检查异常: {exc}")
            results_by_device[spec.key].append(endpoint_status)

    # 按配置顺序恢复端点顺序, 避免并发返回顺序影响页面展示.
    device_items: List[JsonDict] = []
    for spec in DEVICE_SPECS:
        status_map = {
            (str(item["host"]), int(item["port"])): item
            for item in results_by_device[spec.key]
        }
        ordered_statuses = []
        for endpoint in spec.endpoints:
            key = (endpoint.host, endpoint.port)
            if key in status_map:
                ordered_statuses.append(status_map[key])
            else:
                ordered_statuses.append(_endpoint_error(endpoint, "检查结果缺失."))
        device_items.append(_summarize_device(spec, ordered_statuses))
    return device_items


def _check_endpoint(endpoint: EndpointSpec, timeout_s: float) -> JsonDict:
    """
    功能:
        检查单个 TCP 端点是否可以建立连接.
    参数:
        endpoint: EndpointSpec, 待检查端点.
        timeout_s: float, 连接超时时间, 单位秒.
    返回:
        Dict[str, object], 端点连通性状态.
    """
    started_at = time.perf_counter()
    try:
        with socket.create_connection((endpoint.host, endpoint.port), timeout=timeout_s):
            latency_ms = round((time.perf_counter() - started_at) * 1000, 1)
            return {
                "host": endpoint.host,
                "port": endpoint.port,
                "reachable": True,
                "latency_ms": latency_ms,
                "error": "",
            }
    except OSError as exc:
        logger.info(
            "设备端口不可联通, host=%s, port=%d, error=%s",
            endpoint.host,
            endpoint.port,
            exc,
        )
        return _endpoint_error(endpoint, f"连接失败: {exc}")


def _endpoint_error(endpoint: EndpointSpec, error: str) -> JsonDict:
    """
    功能:
        生成端点不可联通状态.
    参数:
        endpoint: EndpointSpec, 待检查端点.
        error: str, 错误说明.
    返回:
        Dict[str, object], 端点状态.
    """
    return {
        "host": endpoint.host,
        "port": endpoint.port,
        "reachable": False,
        "latency_ms": None,
        "error": error,
    }


def _summarize_device(spec: DeviceSpec, endpoints: List[JsonDict]) -> JsonDict:
    """
    功能:
        汇总单台设备所有端点的在线状态.
    参数:
        spec: DeviceSpec, 设备配置.
        endpoints: List[Dict[str, object]], 端点检查结果.
    返回:
        Dict[str, object], 设备汇总状态.
    """
    total_count = len(endpoints)
    online_count = 0
    for endpoint in endpoints:
        if endpoint["reachable"] is True:
            online_count += 1

    if total_count > 0 and online_count == total_count:
        status = "在线"
    elif online_count > 0:
        status = "部分在线"
    else:
        status = "离线"

    return {
        "key": spec.key,
        "name": spec.name,
        "category": spec.category,
        "address": _format_endpoint_addresses(endpoints),
        "reachable": online_count > 0,
        "status": status,
        "summary": f"{online_count}/{total_count} 端口在线",
        "endpoints": endpoints,
    }


def _build_hub_status(request: Request) -> JsonDict:
    """
    功能:
        生成 EIT Hub 自身状态, 以当前 API 可响应作为在线依据.
    参数:
        request: Request, 当前 HTTP 请求.
    返回:
        Dict[str, object], Hub 自身状态.
    """
    port = _read_hub_port()
    request_host = request.url.hostname
    if request_host is None:
        request_host = ""
    local_hosts = _list_local_ipv4_addresses()
    endpoint_hosts = _merge_hosts([request_host], local_hosts)
    if len(endpoint_hosts) == 0:
        endpoint_hosts = ["127.0.0.1"]

    endpoints: List[JsonDict] = []
    for host in endpoint_hosts:
        endpoints.append(
            {
                "host": host,
                "port": port,
                "reachable": True,
                "latency_ms": 0.0,
                "error": "",
            }
        )

    return {
        "key": "eit_hub",
        "name": "EIT Hub",
        "category": "Hub",
        "address": _format_hub_address(request_host, local_hosts, port),
        "reachable": True,
        "status": "在线",
        "summary": "当前服务可访问",
        "endpoints": endpoints,
    }


def _read_hub_port() -> int:
    """
    功能:
        从 EIT_HUB_WEB_PORT 环境变量读取 Hub Web 监听端口.
    返回:
        int, Hub Web 监听端口.
    """
    raw_port = os.getenv("EIT_HUB_WEB_PORT", str(DEFAULT_HUB_PORT))
    try:
        return int(raw_port)
    except ValueError:
        logger.warning("EIT_HUB_WEB_PORT 配置无效, 使用默认端口: %s", DEFAULT_HUB_PORT)
        return DEFAULT_HUB_PORT


def _list_local_ipv4_addresses() -> List[str]:
    """
    功能:
        查询本机非回环 IPv4 地址列表.
    返回:
        List[str], 本机 IPv4 地址列表.
    """
    try:
        host_name = socket.gethostname()
        records = socket.getaddrinfo(
            host_name,
            None,
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
        )
    except OSError:
        logger.exception("获取本机 IPv4 地址失败")
        return []

    addresses: List[str] = []
    seen = set()
    for record in records:
        sockaddr = record[4]
        if len(sockaddr) == 0:
            continue
        host = str(sockaddr[0])
        if _is_non_loopback_ipv4(host) is False:
            continue
        if host in seen:
            continue
        seen.add(host)
        addresses.append(host)
    return addresses


def _is_non_loopback_ipv4(host: str) -> bool:
    """
    功能:
        判断地址是否为可展示的非回环 IPv4.
    参数:
        host: str, 待判断地址.
    返回:
        bool, True 表示可展示.
    """
    if host == "":
        return False
    if host == "0.0.0.0":
        return False
    if host.startswith("127.") is True:
        return False
    return True


def _merge_hosts(primary_hosts: List[str], secondary_hosts: List[str]) -> List[str]:
    """
    功能:
        合并主机地址并去重, 保持原始顺序.
    参数:
        primary_hosts: List[str], 优先展示的主机地址.
        secondary_hosts: List[str], 补充展示的主机地址.
    返回:
        List[str], 去重后的主机地址.
    """
    result: List[str] = []
    seen = set()
    for host in primary_hosts + secondary_hosts:
        if host == "":
            continue
        if host in seen:
            continue
        seen.add(host)
        result.append(host)
    return result


def _format_hub_address(request_host: str, local_hosts: List[str], port: int) -> str:
    """
    功能:
        格式化 Hub 当前访问地址和本机 IPv4 地址.
    参数:
        request_host: str, 当前请求访问的主机名.
        local_hosts: List[str], 本机非回环 IPv4 地址.
        port: int, Hub Web 监听端口.
    返回:
        str, 页面展示地址.
    """
    parts: List[str] = []
    if request_host != "":
        parts.append(f"当前访问: {request_host}:{port}")
    if len(local_hosts) > 0:
        local_text = ", ".join(f"{host}:{port}" for host in local_hosts)
        parts.append(f"本机 IPv4: {local_text}")
    if len(parts) == 0:
        return f"127.0.0.1:{port}"
    return "; ".join(parts)


def _format_endpoint_addresses(endpoints: List[JsonDict]) -> str:
    """
    功能:
        格式化设备端点地址列表.
    参数:
        endpoints: List[Dict[str, object]], 端点检查结果.
    返回:
        str, 页面展示地址.
    """
    addresses: List[str] = []
    for endpoint in endpoints:
        addresses.append(f"{endpoint['host']}:{endpoint['port']}")
    return ", ".join(addresses)
