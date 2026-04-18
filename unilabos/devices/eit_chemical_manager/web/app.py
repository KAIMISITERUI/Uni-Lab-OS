# -*- coding: utf-8 -*-
"""
功能:
    eit_chemical_manager Web 服务的 FastAPI 应用装配.
    挂载 CRUD / 在线查询 / 配置 / 运维路由, 配置 CORS, 并预留前端静态资源挂载点.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .routers import admin, chemicals, lookup, prepare

logger = logging.getLogger("ChemicalManagerWeb")

# 前端静态资源目录, 由 Vite 构建产物 dist 提供; 不存在时跳过挂载
_FRONTEND_DIST = Path(__file__).resolve().parent / "frontend" / "dist"

# index.html 必须始终重新校验, 否则浏览器拿到旧 entry 后会去引用已被新构建删除的 hash chunk
# hash 化的 assets/*.js / *.css 文件名变化, 浏览器自然走 200 拉新, 不需要 no-cache
_INDEX_HTML_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


def create_app() -> FastAPI:
    """
    功能:
        构造 FastAPI 实例, 挂载路由与中间件.
    返回:
        FastAPI.
    """
    app = FastAPI(
        title="eit_chemical_manager Web API",
        description="化学品库的 REST API, 用于 Web UI 与外部脚本访问",
        version="1.0.0",
    )

    # CORS 放开本地开发常用源, 生产可通过反向代理收紧
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 路由注册
    app.include_router(chemicals.router)
    app.include_router(lookup.router)
    app.include_router(prepare.router)
    app.include_router(admin.router)

    @app.get("/api/health", tags=["health"])
    def health() -> dict:
        """功能: 健康探针."""
        return {"status": "ok"}

    # 前端静态资源挂载, dist 不存在时不挂(开发期前端用 vite dev server)
    if _FRONTEND_DIST.is_dir():
        # 把构建产物中的 assets 子目录挂到 /assets, 让 index.html 里的 <script src="/assets/..."> 命中
        assets_dir = _FRONTEND_DIST / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend-assets")

        index_file = _FRONTEND_DIST / "index.html"

        # SPA catch-all: 任意非 /api 路径返回 index.html, 让 vue-router 接管客户端路由
        @app.get("/{full_path:path}", include_in_schema=False)
        def spa_fallback(full_path: str) -> FileResponse:
            """功能: SPA 路由 fallback, 静态文件存在时直接返回, 否则回到 index.html.
            index.html 始终下发 no-cache 头, 防止前端构建升级后浏览器引用已删 chunk.
            """
            candidate = _FRONTEND_DIST / full_path
            if full_path != "" and candidate.is_file():
                if candidate.name == "index.html":
                    return FileResponse(str(candidate), headers=_INDEX_HTML_HEADERS)
                return FileResponse(str(candidate))
            if not index_file.is_file():
                raise HTTPException(status_code=404, detail="前端入口不存在")
            return FileResponse(str(index_file), headers=_INDEX_HTML_HEADERS)

        logger.info("已挂载前端静态资源目录: %s", _FRONTEND_DIST)
    else:
        logger.info("未发现前端构建产物, 跳过静态资源挂载: %s", _FRONTEND_DIST)

    return app


app = create_app()
