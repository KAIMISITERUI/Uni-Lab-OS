# -*- coding: utf-8 -*-
"""
功能:
    EIT Hub Web 服务装配, 提供统一工站入口和化学品库 API 集成.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from unilabos.devices.eit_chemical_manager.web.routers import (
    admin as chemical_admin,
    chemicals as chemical_chemicals,
    lookup as chemical_lookup,
    prepare as chemical_prepare,
)

from .routers import analysis, devices, synthesis

logger = logging.getLogger("EITHubWeb")

_FRONTEND_DIST = Path(__file__).resolve().parent / "frontend" / "dist"
_INDEX_HTML_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


def create_app() -> FastAPI:
    """
    功能:
        构造 EIT Hub FastAPI 应用, 注册路由与静态前端.
    返回:
        FastAPI, Web 应用.
    """
    app = FastAPI(
        title="EIT Hub Web API",
        description="EIT Hub 统一工站 Web API.",
        version="1.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(synthesis.router)
    app.include_router(analysis.router)
    app.include_router(devices.router)
    app.include_router(chemical_chemicals.router)
    app.include_router(chemical_lookup.router)
    app.include_router(chemical_prepare.router)
    app.include_router(chemical_admin.router)

    @app.get("/api/health", tags=["health"])
    def health() -> dict:
        """
        功能:
            返回 Hub Web 健康状态.
        返回:
            dict, 健康状态.
        """
        return {"status": "ok", "service": "eit_hub"}

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    """
    功能:
        挂载 Vite 构建产物, 未构建时仅提供 API.
    参数:
        app: FastAPI, Web 应用.
    返回:
        None.
    """
    if _FRONTEND_DIST.is_dir() is False:
        logger.info("未发现 EIT Hub 前端构建产物, 跳过静态资源挂载: %s", _FRONTEND_DIST)
        return

    assets_dir = _FRONTEND_DIST / "assets"
    if assets_dir.is_dir() is True:
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="hub-assets")

    index_file = _FRONTEND_DIST / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str) -> FileResponse:
        """
        功能:
            返回前端静态资源或 SPA 入口.
        参数:
            full_path: str, 请求路径.
        返回:
            FileResponse, 静态文件响应.
        """
        if full_path.startswith("api/") is True:
            raise HTTPException(status_code=404, detail=f"未找到 API 路径: /{full_path}")

        candidate = _FRONTEND_DIST / full_path
        if full_path != "" and candidate.is_file():
            if candidate.name == "index.html":
                return FileResponse(str(candidate), headers=_INDEX_HTML_HEADERS)
            return FileResponse(str(candidate))

        if index_file.is_file() is False:
            raise HTTPException(status_code=404, detail="前端入口不存在.")
        return FileResponse(str(index_file), headers=_INDEX_HTML_HEADERS)

    logger.info("已挂载 EIT Hub 前端静态资源目录: %s", _FRONTEND_DIST)


app = create_app()
