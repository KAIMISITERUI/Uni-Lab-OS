# -*- coding: utf-8 -*-
"""
功能:
    eit_chemical_manager 驱动的交互式入口.
    interactive() 直接启动 Web GUI (FastAPI + Vue), 浏览器中完成化学品库管理.
"""

import logging
import os
import threading
import webbrowser
from pathlib import Path

from .config.setting import Settings, configure_logging

logger = logging.getLogger("ChemicalManagerCLI")


def launch_web_gui() -> None:
    """
    功能:
        启动 Web GUI (FastAPI + Vue), 自动打开浏览器, 阻塞直到 Ctrl+C 退出.
        前端构建产物缺失时给出提示并返回, 不强制启动空壳.
    返回:
        None.
    """
    import uvicorn

    web_dir = Path(__file__).resolve().parent / "web"
    dist_dir = web_dir / "frontend" / "dist"
    index_html = dist_dir / "index.html"

    if not index_html.is_file():
        print("未找到前端构建产物, 请先在 frontend 目录执行 npm install && npm run build")
        print(f"  期望路径: {index_html}")
        return

    host = os.getenv("CHEM_MGR_WEB_HOST", "127.0.0.1")
    port = int(os.getenv("CHEM_MGR_WEB_PORT", "8765"))
    open_url = (
        f"http://127.0.0.1:{port}/"
        if host in ("0.0.0.0", "127.0.0.1")
        else f"http://{host}:{port}/"
    )

    print(f"\n启动 Web GUI: {open_url}")
    print("CHEM_MGR_WEB_TOKEN 未设置时为开放访问, 设置后请用页面右上角'访问令牌'输入")
    print("按 Ctrl+C 停止服务并返回上级菜单\n")

    # 服务进入监听后再触发浏览器, 避免点开后页面 connection refused
    threading.Timer(1.5, webbrowser.open, args=(open_url,)).start()

    try:
        uvicorn.run(
            "unilabos.devices.eit_chemical_manager.web.app:app",
            host=host,
            port=port,
            log_level="info",
        )
    except KeyboardInterrupt:
        print("\nWeb GUI 已停止")


def interactive() -> None:
    """
    功能:
        驱动的交互式入口, 直接启动 Web GUI.
        保留函数名以与 eit_hub._run_station_menu 的调用协议兼容.
    返回:
        None.
    """
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    launch_web_gui()
