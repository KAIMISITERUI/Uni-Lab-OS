# -*- coding: utf-8 -*-
"""
功能:
    AGV 充电循环常驻服务. 包装 AGVController.auto_charge_pp5_cp6_check(),
    在独立线程中周期执行, 不占用 JobManager 的独占槽位, 方便与其他 AGV 操作并发调度.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any, Dict, Optional

from .agv_context import AgvContext

logger = logging.getLogger("EITHubChargeLoop")


class ChargeLoopService:
    """
    功能:
        充电循环服务, 运行时以独立线程周期执行一次充电检查.
    """

    def __init__(self, context: AgvContext) -> None:
        self._context = context
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._running = False
        self._standby: str = "PP5"
        self._config: Dict[str, Any] = {
            "interval_minutes": 30,
            "retry_wait_minutes": 5,
            "low_battery_pct": 50,
        }
        self._last_action: Optional[Dict[str, Any]] = None

    def start(
        self,
        standby: str,
        interval_minutes: int,
        retry_wait_minutes: int,
        low_battery_pct: int,
    ) -> Dict[str, Any]:
        """
        功能:
            启动充电循环.
        参数:
            standby: str, 待命点类型, "CP6" 或 "PP5". 仅用于日志和前端展示.
            interval_minutes: int, 正常检查间隔.
            retry_wait_minutes: int, 异常/跳过时的重试等待.
            low_battery_pct: int, 低电量阈值 (0-100).
        返回:
            Dict, 启动后的服务状态.
        """
        if self._context.is_chassis_connected() is False:
            raise RuntimeError("AGV 底盘未连接, 无法启动充电循环")

        with self._lock:
            if self._running is True:
                raise RuntimeError("充电循环已在运行")
            self._standby = standby.upper() if isinstance(standby, str) else "PP5"
            self._config = {
                "interval_minutes": int(interval_minutes),
                "retry_wait_minutes": int(retry_wait_minutes),
                "low_battery_pct": int(low_battery_pct),
            }
            self._stop_event.clear()
            self._running = True
            self._last_action = {
                "at": datetime.now().isoformat(timespec="seconds"),
                "status": "started",
                "message": f"充电循环已启动, 待命点={self._standby}",
            }
            thread = threading.Thread(target=self._loop, name="agv-charge-loop", daemon=True)
            self._thread = thread
            thread.start()

        logger.info(
            "充电循环已启动, standby=%s, interval=%d min, retry=%d min, threshold=%d%%",
            self._standby,
            self._config["interval_minutes"],
            self._config["retry_wait_minutes"],
            self._config["low_battery_pct"],
        )
        return self.status()

    def stop(self) -> Dict[str, Any]:
        """
        功能:
            停止充电循环.
        返回:
            Dict, 停止后的服务状态.
        """
        with self._lock:
            self._stop_event.set()
            thread = self._thread
        if thread is not None and thread.is_alive() is True:
            thread.join(timeout=5.0)
        with self._lock:
            self._running = False
            self._thread = None
            self._last_action = {
                "at": datetime.now().isoformat(timespec="seconds"),
                "status": "stopped",
                "message": "充电循环已停止",
            }
        logger.info("充电循环已停止.")
        return self.status()

    def status(self) -> Dict[str, Any]:
        """
        功能:
            返回当前服务状态.
        返回:
            Dict, 包含 running/standby/config/last_action.
        """
        with self._lock:
            return {
                "running": self._running,
                "standby": self._standby,
                "config": dict(self._config),
                "last_action": self._last_action,
            }

    def _loop(self) -> None:
        """
        功能:
            循环执行充电检查. 每轮结束后按执行结果挑选等待时长.
            充电检查内部可能触发导航和机械臂回零, 必须持 arm_lock.
        返回:
            None.
        """
        controller = self._context.get_or_create()
        while self._stop_event.is_set() is False:
            try:
                with self._context.arm_lock:
                    result = controller.auto_charge_pp5_cp6_check(
                        low_battery_pct=self._config["low_battery_pct"]
                    )
                action = {
                    "at": datetime.now().isoformat(timespec="seconds"),
                    **(result if isinstance(result, dict) else {"status": "unknown", "raw": str(result)}),
                }
            except Exception as exc:
                logger.warning("充电循环检查失败: %s", exc)
                action = {
                    "at": datetime.now().isoformat(timespec="seconds"),
                    "status": "error",
                    "error": str(exc),
                }

            with self._lock:
                self._last_action = action

            status_value = action.get("status")
            if status_value == "success":
                wait_seconds = max(1, self._config["interval_minutes"] * 60)
            else:
                wait_seconds = max(1, self._config["retry_wait_minutes"] * 60)

            if self._stop_event.wait(wait_seconds) is True:
                break
