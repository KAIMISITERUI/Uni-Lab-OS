# -*- coding: utf-8 -*-
"""
功能:
    将 ops_http sidecar (合成工站 PC 上独立 Python 进程, 端口 4670) 的 /api/cameras
    透传给 eit_hub 前端, 并为每路相机同时拼出子码流 (缩略图) 与主码流 (放大查看)
    的 MJPEG 直连 URL, 让前端 <img> 标签可直接拉流, 不经 eit_hub 后端转发视频.
    服务地址通过环境变量 OPS_HTTP_BASE_URL 配置, 默认 http://10.32.2.106:4670.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import requests
from fastapi import APIRouter, HTTPException

logger = logging.getLogger("EITHubCameraRouter")

# ops_http sidecar 基础地址, 与合成工站业务接口 (4669) 解耦
_DEFAULT_OPS_HTTP_BASE_URL = "http://10.32.2.106:4670"
_OPS_HTTP_BASE_URL = os.getenv("OPS_HTTP_BASE_URL", _DEFAULT_OPS_HTTP_BASE_URL).rstrip("/")
_REQUEST_TIMEOUT_S = 5.0

router = APIRouter(prefix="/api/synthesis", tags=["synthesis-camera"])


def _build_stream_urls(camera_id: str) -> Dict[str, str]:
    """
    功能:
        为单路相机同时拼出子码流与主码流的 MJPEG 直连 URL,
        前端用子码流做缩略图, 用户点击放大时切换到主码流.
    参数:
        camera_id: str, 相机标识, 例如 cam1, cam2, cam3.
    返回:
        Dict[str, str], 含 stream_url_sub 与 stream_url_main 两个字段.
    """
    base = f"{_OPS_HTTP_BASE_URL}/api/cameras/{camera_id}/stream.mjpg"
    return {
        "stream_url_sub": f"{base}?stream=sub",
        "stream_url_main": f"{base}?stream=main",
    }


def _normalize_camera_entry(entry: Any) -> Optional[Dict[str, Any]]:
    """
    功能:
        将 ops_http /api/cameras 返回的单项数据规整成前端可消费的结构,
        兼容 sidecar 直接返回字符串 id 列表与对象列表两种格式.
    参数:
        entry: Any, sidecar 原始数据, 可能为字符串或对象.
    返回:
        Optional[Dict[str, Any]], 规整后的相机记录, 若无法识别则返回 None.
    """
    if isinstance(entry, str):
        camera_id = entry.strip()
        if camera_id == "":
            return None
        return {"id": camera_id, **_build_stream_urls(camera_id)}
    if isinstance(entry, dict):
        camera_id = str(entry.get("id") or entry.get("camera_id") or "").strip()
        if camera_id == "":
            return None
        normalized: Dict[str, Any] = dict(entry)
        normalized["id"] = camera_id
        normalized.update(_build_stream_urls(camera_id))
        return normalized
    return None


@router.get("/cameras")
def list_cameras() -> List[Dict[str, Any]]:
    """
    功能:
        透传 ops_http /api/cameras 列表, 并为每路相机附上子码流与主码流
        的直连 URL, 供前端 <img> 标签直接拉取 MJPEG.
    参数:
        无.
    返回:
        List[Dict[str, Any]], 相机记录列表, 每项至少包含 id, stream_url_sub, stream_url_main.
    """
    upstream = f"{_OPS_HTTP_BASE_URL}/api/cameras"
    try:
        response = requests.get(upstream, timeout=_REQUEST_TIMEOUT_S)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        logger.warning("拉取摄像头列表失败 url=%s err=%s", upstream, exc)
        raise HTTPException(status_code=502, detail="ops_http 摄像头服务不可达")
    except ValueError as exc:
        logger.warning("摄像头列表 JSON 解析失败 url=%s err=%s", upstream, exc)
        raise HTTPException(status_code=502, detail="ops_http 摄像头服务返回数据无法解析")

    # 兼容两种返回格式: 直接列表, 或包裹在 cameras 字段下
    raw_list: List[Any]
    if isinstance(payload, list):
        raw_list = payload
    elif isinstance(payload, dict) and isinstance(payload.get("cameras"), list):
        raw_list = payload["cameras"]
    else:
        logger.warning("摄像头列表结构异常 payload=%s", payload)
        raise HTTPException(status_code=502, detail="ops_http 摄像头服务返回结构异常")

    cameras: List[Dict[str, Any]] = []
    for entry in raw_list:
        normalized = _normalize_camera_entry(entry)
        if normalized is not None:
            cameras.append(normalized)

    return cameras
