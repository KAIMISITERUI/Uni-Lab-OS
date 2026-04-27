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
    try:
        manager.ensure_login()
        return manager._client.get_resource_info(payload)
    except AuthorizationExpiredError:
        # 登录失效, 重登一次再重试
        logger.warning("token 失效, 自动重新登录后重试")
        manager.login()
        try:
            return manager._client.get_resource_info(payload)
        except Exception as exc:
            logger.error("重试 GetResourceInfo 仍然失败: %s", exc)
            raise HTTPException(status_code=502, detail=f"代理调用 GetResourceInfo 失败: {exc}")
    except Exception as exc:
        logger.error("代理 GetResourceInfo 失败: %s", exc)
        raise HTTPException(status_code=502, detail=f"代理调用 GetResourceInfo 失败: {exc}")
