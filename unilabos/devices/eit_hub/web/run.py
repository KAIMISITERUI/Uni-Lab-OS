# -*- coding: utf-8 -*-
"""
功能:
    启动 EIT Hub Web 服务.
用法:
    python -m unilabos.devices.eit_hub.web.run
环境变量:
    EIT_HUB_WEB_HOST: 监听地址, 默认 0.0.0.0.
    EIT_HUB_WEB_PORT: 监听端口, 默认 8770.
"""

from __future__ import annotations

import logging
import os

import uvicorn

logger = logging.getLogger("EITHubWebRun")


def main() -> None:
    """
    功能:
        从环境变量读取监听配置并启动 uvicorn.
    返回:
        None.
    """
    host = os.getenv("EIT_HUB_WEB_HOST", "0.0.0.0")
    port = int(os.getenv("EIT_HUB_WEB_PORT", "8770"))
    logger.info("启动 EIT Hub Web 服务: %s:%d", host, port)
    uvicorn.run(
        "unilabos.devices.eit_hub.web.app:app",
        host=host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()

