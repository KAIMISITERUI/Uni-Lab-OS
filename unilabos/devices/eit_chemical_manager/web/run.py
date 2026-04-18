# -*- coding: utf-8 -*-
"""
功能:
    eit_chemical_manager Web 服务的 uvicorn 启动入口.
用法:
    python -m unilabos.devices.eit_chemical_manager.web.run
环境变量:
    CHEM_MGR_WEB_HOST: 监听地址, 默认 0.0.0.0
    CHEM_MGR_WEB_PORT: 监听端口, 默认 8765
    CHEM_MGR_WEB_TOKEN: 鉴权 token, 设置后 X-API-Token 必须匹配
"""

from __future__ import annotations

import logging
import os

import uvicorn

logger = logging.getLogger("ChemicalManagerWebRun")


def main() -> None:
    """
    功能:
        从环境变量读取监听配置并启动 uvicorn.
    返回:
        None.
    """
    host = os.getenv("CHEM_MGR_WEB_HOST", "0.0.0.0")
    port = int(os.getenv("CHEM_MGR_WEB_PORT", "8765"))
    logger.info("启动化学品库 Web 服务: %s:%d", host, port)
    uvicorn.run(
        "unilabos.devices.eit_chemical_manager.web.app:app",
        host=host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
