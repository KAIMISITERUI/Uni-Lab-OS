# -*- coding: utf-8 -*-
"""
功能:
    将 dynamic-graph 前端发起的 /synthesis-api/* 请求, 通过 SynthesisStationManager
    复用已经鉴权的会话, 反向代理到 eit_synthesis_station 设备 PC (base_url 由 setting.py 提供).
    解决前端直连设备时 405/401 (无 token) 的问题, 同时使 dev 模式与生产模式走同一条链路.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException

from unilabos.devices.eit_synthesis_station.driver.exceptions import (
    AuthorizationExpiredError,
)
from unilabos.devices.eit_synthesis_station.manager.station_manager import (
    SynthesisStationManager,
)

from ..deps import get_synthesis_manager

logger = logging.getLogger("EITHubWeb.synthesis_proxy")

# 与前端 /synthesis-api/api/* 完整对齐, dynamic-graph 内部调用形如
# axios.post('/synthesis-api/api/GetResourceInfo', { roll: 'normal' })
router = APIRouter(prefix="/synthesis-api/api", tags=["synthesis-proxy"])


def _invoke_with_relogin(
    manager: SynthesisStationManager,
    op_name: str,
    invoke,
) -> Dict[str, Any]:
    """
    功能:
        统一封装 SynthesisStationManager 的代理调用流程, 复用 GetResourceInfo 的 401 自动重登重试逻辑.
        所有 /synthesis-api/api/* 代理路由共用本函数.
    参数:
        manager: SynthesisStationManager, 由 FastAPI 依赖注入.
        op_name: str, 操作名称, 用于日志和错误信息.
        invoke: Callable[[], Dict[str, Any]], 真正调用 manager._client 方法的零参闭包.
    返回:
        Dict[str, Any], 设备返回的原始 JSON.
    """
    try:
        manager.ensure_login()
        return invoke()
    except AuthorizationExpiredError:
        # 登录失效, 重登一次再重试
        logger.warning("token 失效, 自动重新登录后重试: %s", op_name)
        manager.login()
        try:
            return invoke()
        except Exception as exc:
            logger.error("重试 %s 仍然失败: %s", op_name, exc)
            raise HTTPException(status_code=502, detail=f"代理调用 {op_name} 失败: {exc}")
    except Exception as exc:
        logger.error("代理 %s 失败: %s", op_name, exc)
        raise HTTPException(status_code=502, detail=f"代理调用 {op_name} 失败: {exc}")


@router.post("/GetResourceInfo")
def proxy_get_resource_info(
    body: Optional[Dict[str, Any]] = Body(default=None),
    manager: SynthesisStationManager = Depends(get_synthesis_manager),
) -> Dict[str, Any]:
    """
    功能:
        代理 dynamic-graph 前端的 GetResourceInfo 调用. 透传请求体到设备 /api/GetResourceInfo,
        附带 SynthesisStationManager 的鉴权头. 401 时自动重登录并重试一次.
    参数:
        body: Optional[Dict[str, Any]], 透传给设备的过滤参数, 例如 {"roll": "normal"}.
        manager: SynthesisStationManager, 由 FastAPI 依赖注入.
    返回:
        Dict[str, Any], 设备 /api/GetResourceInfo 的原始 JSON 响应,
        含 resource_list, lock_positions 等字段, 供 dynamic-graph 前端聚合渲染.
    """
    payload = body or {}
    return _invoke_with_relogin(
        manager,
        "GetResourceInfo",
        lambda: manager._client.get_resource_info(payload),
    )


@router.post("/InTray")
def proxy_in_tray(
    body: Dict[str, Any] = Body(...),
    manager: SynthesisStationManager = Depends(get_synthesis_manager),
) -> Dict[str, Any]:
    """
    功能:
        代理 dynamic-resource 前端的 InTray 调用 (单托盘录入资源).
        透传请求体到设备 /api/InTray, 复用 SynthesisStationManager 鉴权与 401 重登逻辑.
    参数:
        body: Dict[str, Any], 包含 tray_QR_code 与 resource_list 两个字段, 与 web_code 入参完全一致.
        manager: SynthesisStationManager, 由 FastAPI 依赖注入.
    返回:
        Dict[str, Any], 设备 /api/InTray 原始 JSON 响应.
    """
    tray_qr_code = body.get("tray_QR_code", "")
    resource_list = body.get("resource_list", []) or []
    if not isinstance(resource_list, list):
        raise HTTPException(status_code=400, detail="resource_list 必须为数组")
    return _invoke_with_relogin(
        manager,
        "InTray",
        lambda: manager._client.in_tray(tray_qr_code, resource_list),
    )


@router.post("/BatchInTray")
def proxy_batch_in_tray(
    body: Dict[str, Any] = Body(...),
    manager: SynthesisStationManager = Depends(get_synthesis_manager),
) -> Dict[str, Any]:
    """
    功能:
        代理 dynamic-resource 前端的 BatchInTray 调用 (批量多托盘录入资源).
        透传 resource_req_list 到设备 /api/BatchInTray.
    参数:
        body: Dict[str, Any], 必须包含 resource_req_list 列表, 每项含 tray_layout_code 与 resource_list.
        manager: SynthesisStationManager, 由 FastAPI 依赖注入.
    返回:
        Dict[str, Any], 设备 /api/BatchInTray 原始 JSON 响应.
    """
    resource_req_list = body.get("resource_req_list", []) or []
    if not isinstance(resource_req_list, list):
        raise HTTPException(status_code=400, detail="resource_req_list 必须为数组")
    return _invoke_with_relogin(
        manager,
        "BatchInTray",
        lambda: manager._client.batch_in_tray(resource_req_list),
    )
