# -*- coding: utf-8 -*-
"""
功能:
    AI 助手功能模块公开入口, 只向外暴露 FastAPI router.
"""

from .api.router import router

__all__ = ["router"]
