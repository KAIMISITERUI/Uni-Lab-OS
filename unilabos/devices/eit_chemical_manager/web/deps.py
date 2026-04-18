# -*- coding: utf-8 -*-
"""
功能:
    FastAPI 依赖注入与鉴权工具.
    - get_manager: 注入 ChemicalManager 单例
    - require_token: 校验 X-API-Token 请求头
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import Depends, Header, HTTPException, status

from ..manager.chemical_manager import ChemicalManager

# 鉴权 token 来自环境变量, 未设置时表示开放访问(本地调试)
_TOKEN_ENV_VAR = "CHEM_MGR_WEB_TOKEN"


def get_manager() -> ChemicalManager:
    """
    功能:
        FastAPI 依赖, 返回全局共享的 ChemicalManager 实例.
    返回:
        ChemicalManager.
    """
    return ChemicalManager.get_shared()


def require_token(
    x_api_token: Optional[str] = Header(default=None, alias="X-API-Token"),
) -> None:
    """
    功能:
        校验请求头中的 X-API-Token. 环境变量 CHEM_MGR_WEB_TOKEN 未设置时跳过校验,
        允许本地调试. 设置后必须严格匹配, 否则返回 401.
    参数:
        x_api_token: Optional[str], 请求头.
    异常:
        HTTPException(401): token 缺失或不匹配.
    """
    expected = os.getenv(_TOKEN_ENV_VAR, "").strip()
    if expected == "":
        return
    if x_api_token is None or x_api_token.strip() != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-API-Token 校验失败",
        )


# 共享依赖, 路由在 dependencies 列表中复用
TokenDep = Depends(require_token)
