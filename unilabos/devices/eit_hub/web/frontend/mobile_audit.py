"""
功能:
    使用 Playwright 在 iPhone 14 Pro (393x852) 视口下逐路由访问 eit_hub 前端,
    截图保存, 收集 console errors / 主要元素是否渲染, 用于手机端响应式适配的回归审查.

参数:
    无 (顶部常量定义路由列表与视口尺寸)

返回:
    无 (写入截图到 mobile-audit/<route_slug>.png, 打印审查报告)
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, ConsoleMessage, Page


BASE_URL = os.environ.get("EIT_HUB_BASE", "http://127.0.0.1:5174")

# 移动端代表机型
DEVICES = [
    {"name": "iphone-14-pro", "width": 393, "height": 852, "deviceScaleFactor": 3},
    {"name": "iphone-se", "width": 375, "height": 667, "deviceScaleFactor": 2},
]

# 全部业务路由 + 描述
ROUTES = [
    ("/devices", "设备总览"),
    ("/synthesis", "合成工站"),
    ("/synthesis/cameras", "现场监控"),
    ("/analysis", "分析工站"),
    ("/agv", "AGV 运输车"),
    ("/agv/positions", "AGV 点位"),
    ("/agv/shelf", "AGV 货架"),
    ("/chemicals", "化学品库"),
    ("/synthesis-task-editor", "任务编辑"),
    ("/synthesis-workflow", "工作流"),
    ("/task-history", "任务历史"),
    ("/maintenance", "运维管理"),
    ("/ai-agent-history", "AI 助手"),
    ("/label-printer", "标签打印机"),
]

OUTPUT_DIR = Path(__file__).parent / "mobile-audit"
OUTPUT_DIR.mkdir(exist_ok=True)


def slug(path: str) -> str:
    "把路径转为可安全做文件名的 slug"
    return path.strip("/").replace("/", "_") or "root"


def audit_one_route(page: Page, route: str, label: str, device_name: str) -> dict:
    "访问 route, 等渲染, 截屏, 收集 console errors 与关键 DOM 检查"
    console_msgs: list[dict] = []
    page_errors: list[str] = []

    def on_console(msg: ConsoleMessage) -> None:
        if msg.type in ("error", "warning"):
            try:
                console_msgs.append({"type": msg.type, "text": msg.text})
            except Exception:
                pass

    def on_pageerror(err) -> None:
        page_errors.append(str(err))

    page.on("console", on_console)
    page.on("pageerror", on_pageerror)

    url = f"{BASE_URL}{route}"
    error_text = ""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=15_000)
        # 给 KeepAlive + 路由切换 + 异步组件 一点时间
        page.wait_for_timeout(1500)
    except Exception as e:
        error_text = str(e)

    # 关键 DOM 检查
    checks: dict[str, bool] = {}
    try:
        # mobile-topbar 应可见
        checks["has_mobile_topbar"] = page.locator(".mobile-topbar").count() > 0
        # 内容区应有内容
        checks["has_content"] = page.locator(".content-scroll").count() > 0
        # 不应该出现 fatal "Failed to fetch module" 错误覆盖整页
        checks["no_vite_overlay"] = page.locator("vite-error-overlay").count() == 0
        # 检查桌面 sidebar 是否被隐藏 (移动端不应可见)
        sidebar = page.locator(".app-shell > aside.sidebar")
        if sidebar.count() > 0:
            checks["sidebar_hidden_on_mobile"] = not sidebar.first.is_visible()
        else:
            # v-if 分支让桌面 sidebar 在 mobile 下不渲染, 也算通过
            checks["sidebar_hidden_on_mobile"] = True
    except Exception as e:
        checks["dom_query_error"] = False
        error_text += f" | dom_query_error: {e}"

    # 截屏
    screenshot_name = f"{device_name}_{slug(route)}.png"
    screenshot_path = OUTPUT_DIR / screenshot_name
    try:
        page.screenshot(path=str(screenshot_path), full_page=True)
    except Exception as e:
        error_text += f" | screenshot_error: {e}"

    page.remove_listener("console", on_console)
    page.remove_listener("pageerror", on_pageerror)

    return {
        "route": route,
        "label": label,
        "device": device_name,
        "url": url,
        "screenshot": str(screenshot_path.relative_to(OUTPUT_DIR.parent)),
        "checks": checks,
        "console_errors": [m for m in console_msgs if m["type"] == "error"][:10],
        "console_warnings": [m for m in console_msgs if m["type"] == "warning"][:5],
        "page_errors": page_errors[:10],
        "navigation_error": error_text,
    }


def audit_drawer_and_ai(page: Page, device_name: str) -> dict:
    "在 /chemicals 路由验证汉堡抽屉与 AI 助手浮窗的显示与关闭行为"
    page.goto(f"{BASE_URL}/chemicals", wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_timeout(1200)

    # ----- 抽屉测试 -----
    drawer_check = {"opened": False, "closed_after_nav": False, "screenshot": None, "error": ""}
    try:
        page.locator(".mobile-topbar-btn-menu").first.click(timeout=3_000)
        page.wait_for_timeout(700)
        # 抽屉是 teleport 到 body, 用 body 全局命中
        drawer = page.locator(".el-drawer")
        if drawer.count() > 0 and drawer.first.is_visible():
            drawer_check["opened"] = True
        screenshot_path = OUTPUT_DIR / f"{device_name}_drawer.png"
        page.screenshot(path=str(screenshot_path), full_page=False)
        drawer_check["screenshot"] = str(screenshot_path.relative_to(OUTPUT_DIR.parent))
        # 点击抽屉内的"AI 助手" 链接, 验证路由跳转 + 抽屉自动关闭
        page.locator(".el-drawer .nav-link").filter(has_text="AI 助手").first.click(timeout=3_000)
        page.wait_for_timeout(800)
        if drawer.count() == 0 or drawer.first.is_visible() is False:
            drawer_check["closed_after_nav"] = True
    except Exception as e:
        drawer_check["error"] = str(e)

    # ----- AI 浮窗测试 -----
    page.goto(f"{BASE_URL}/chemicals", wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_timeout(1000)

    ai_check = {"sheet_visible": False, "closed_via_topbar": False, "screenshot": None, "error": ""}
    try:
        ai_topbar_btn = page.locator(".mobile-topbar-btn[aria-label='AI 助手']")
        ai_topbar_btn.click(timeout=3_000)
        page.wait_for_timeout(800)
        sheet = page.locator(".ai-launcher-mobile .ai-drawer")
        if sheet.count() > 0 and sheet.first.is_visible():
            ai_check["sheet_visible"] = True
        screenshot_path = OUTPUT_DIR / f"{device_name}_ai_sheet.png"
        page.screenshot(path=str(screenshot_path), full_page=False)
        ai_check["screenshot"] = str(screenshot_path.relative_to(OUTPUT_DIR.parent))
        # 再次点击 mobile-topbar AI 按钮验证可关闭 (此前的关键 bug)
        ai_topbar_btn.click(timeout=3_000)
        page.wait_for_timeout(600)
        if sheet.count() == 0 or sheet.first.is_visible() is False:
            ai_check["closed_via_topbar"] = True
    except Exception as e:
        ai_check["error"] = str(e)

    return {"drawer": drawer_check, "ai_sheet": ai_check}


def main():
    overall_results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for device in DEVICES:
            ctx = browser.new_context(
                viewport={"width": device["width"], "height": device["height"]},
                device_scale_factor=device["deviceScaleFactor"],
                is_mobile=True,
                has_touch=True,
                user_agent=(
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
                ),
            )
            page = ctx.new_page()
            for route, label in ROUTES:
                t0 = time.time()
                res = audit_one_route(page, route, label, device["name"])
                res["elapsed_s"] = round(time.time() - t0, 2)
                overall_results.append(res)
                print(f"[{device['name']}] {route} ({label}) — checks: {res['checks']} errors: {len(res['console_errors'])}")

            interaction = audit_drawer_and_ai(page, device["name"])
            overall_results.append({"device": device["name"], "interaction": interaction})
            print(f"[{device['name']}] interaction: {interaction}")
            ctx.close()
        browser.close()

    summary_path = OUTPUT_DIR / "summary.json"
    summary_path.write_text(json.dumps(overall_results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSummary written to {summary_path}")
    print(f"Screenshots in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
