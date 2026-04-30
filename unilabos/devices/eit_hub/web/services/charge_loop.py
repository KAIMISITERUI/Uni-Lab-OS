# -*- coding: utf-8 -*-
"""
功能:
    AGV 充电循环常驻服务. 包装 AGVController.auto_charge_pp5_cp6_check(),
    在独立线程中周期执行, 不占用 JobManager 的独占槽位, 方便与其他 AGV 操作并发调度.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .agv_context import AgvContext

logger = logging.getLogger("EITHubChargeLoop")

CHARGE_LOOP_CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "charge_loop_config.json"

DEFAULT_CHARGE_LOOP_CONFIG: Dict[str, int] = {
    "interval_minutes": 30,
    "retry_wait_minutes": 5,
    "low_battery_pct": 50,
    "full_battery_pct": 95,
}


def _default_config() -> Dict[str, int]:
    """
    功能:
        返回充电循环默认配置副本, 避免调用方修改模块级默认值.
    返回:
        Dict[str, int], 默认充电循环配置.
    """
    return dict(DEFAULT_CHARGE_LOOP_CONFIG)


def _normalize_config(config: Dict[str, Any]) -> Dict[str, int]:
    """
    功能:
        将外部配置转换为整数配置并校验业务范围.
    参数:
        config: Dict[str, Any], 外部传入或文件读取的配置.
    返回:
        Dict[str, int], 已校验的充电循环配置.
    """
    try:
        interval_minutes = int(config["interval_minutes"])
        retry_wait_minutes = int(config["retry_wait_minutes"])
        low_battery_pct = int(config["low_battery_pct"])
        full_battery_pct = int(config["full_battery_pct"])
    except KeyError as exc:
        raise ValueError(f"充电循环配置缺少字段: {exc.args[0]}.") from exc
    except (TypeError, ValueError) as exc:
        raise ValueError("充电循环配置必须是整数.") from exc

    if (1 <= interval_minutes <= 180) is False:
        raise ValueError("检查间隔必须在 1 到 180 分钟之间.")
    if (1 <= retry_wait_minutes <= 60) is False:
        raise ValueError("重试等待必须在 1 到 60 分钟之间.")
    if (10 <= low_battery_pct <= 90) is False:
        raise ValueError("电量阈值必须在 10 到 90 之间.")
    # 满电阈值必须严格大于低电量阈值, 上限 100, 否则浮充逻辑无效
    if (low_battery_pct < full_battery_pct <= 100) is False:
        raise ValueError("满电阈值必须大于低电量阈值且不超过 100.")

    return {
        "interval_minutes": interval_minutes,
        "retry_wait_minutes": retry_wait_minutes,
        "low_battery_pct": low_battery_pct,
        "full_battery_pct": full_battery_pct,
    }


class ChargeLoopService:
    """
    功能:
        充电循环服务, 运行时以独立线程周期执行一次充电检查.
    """

    def __init__(self, context: AgvContext, config_path: Optional[Path] = None) -> None:
        self._context = context
        self._config_path = config_path if config_path is not None else CHARGE_LOOP_CONFIG_PATH
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._running = False
        self._config: Dict[str, Any] = self._load_config()
        self._last_action: Optional[Dict[str, Any]] = None

    def start(
        self,
        interval_minutes: int,
        retry_wait_minutes: int,
        low_battery_pct: int,
        full_battery_pct: int,
    ) -> Dict[str, Any]:
        """
        功能:
            启动充电循环.
        参数:
            interval_minutes: int, 正常检查间隔.
            retry_wait_minutes: int, 异常/跳过时的重试等待.
            low_battery_pct: int, 低电量阈值 (0-100).
            full_battery_pct: int, 满电停充阈值, 必须大于 low_battery_pct 且不超过 100.
        返回:
            Dict, 启动后的服务状态.
        """
        if self._context.is_chassis_connected() is False:
            raise RuntimeError("AGV 底盘未连接, 无法启动充电循环")

        config = _normalize_config(
            {
                "interval_minutes": interval_minutes,
                "retry_wait_minutes": retry_wait_minutes,
                "low_battery_pct": low_battery_pct,
                "full_battery_pct": full_battery_pct,
            }
        )

        with self._lock:
            if self._running is True:
                raise RuntimeError("充电循环已在运行")
            self._write_config(config)
            self._config = config
            self._stop_event.clear()
            self._running = True
            self._last_action = {
                "at": datetime.now().isoformat(timespec="seconds"),
                "status": "started",
                "message": "充电循环已启动, 固定策略=PP5待命/CP6充电",
            }
            thread = threading.Thread(target=self._loop, name="agv-charge-loop", daemon=True)
            self._thread = thread
            thread.start()

        logger.info(
            "充电循环已启动, strategy=PP5待命/CP6充电, interval=%d min, retry=%d min, low=%d%%, full=%d%%",
            self._config["interval_minutes"],
            self._config["retry_wait_minutes"],
            self._config["low_battery_pct"],
            self._config["full_battery_pct"],
        )
        return self.status()

    def save_config(
        self,
        interval_minutes: int,
        retry_wait_minutes: int,
        low_battery_pct: int,
        full_battery_pct: int,
    ) -> Dict[str, Any]:
        """
        功能:
            保存充电循环配置, 并更新当前服务内存配置.
        参数:
            interval_minutes: int, 正常检查间隔.
            retry_wait_minutes: int, 异常/跳过时的重试等待.
            low_battery_pct: int, 低电量阈值.
            full_battery_pct: int, 满电停充阈值, 必须大于 low_battery_pct 且不超过 100.
        返回:
            Dict[str, Any], 保存后的服务状态.
        """
        config = _normalize_config(
            {
                "interval_minutes": interval_minutes,
                "retry_wait_minutes": retry_wait_minutes,
                "low_battery_pct": low_battery_pct,
                "full_battery_pct": full_battery_pct,
            }
        )
        with self._lock:
            self._write_config(config)
            self._config = config
        logger.info(
            "充电循环配置已保存, interval=%d min, retry=%d min, low=%d%%, full=%d%%",
            config["interval_minutes"],
            config["retry_wait_minutes"],
            config["low_battery_pct"],
            config["full_battery_pct"],
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
            Dict, 包含 running/config/last_action.
        """
        with self._lock:
            return {
                "running": self._running,
                "config": dict(self._config),
                "last_action": self._last_action,
            }

    def _loop(self) -> None:
        """
        功能:
            循环执行充电检查. 每轮结束后按执行结果挑选等待时长.
            机械臂回零的锁保护已下沉到 _safe_navigate_to_station_detailed 内部,
            本循环不再外包 arm_lock, 避免在数分钟的 PP5/CP6 移动期间阻塞状态采样器.
        返回:
            None.
        """
        controller = self._context.get_or_create()
        while self._stop_event.is_set() is False:
            try:
                result = controller.auto_charge_pp5_cp6_check(
                    low_battery_pct=self._config["low_battery_pct"],
                    full_battery_pct=self._config["full_battery_pct"],
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

    def _load_config(self) -> Dict[str, int]:
        """
        功能:
            从持久化文件读取充电循环配置, 文件不存在时使用默认配置.
            历史文件可能缺少新增字段, 先与默认值合并再校验, 兼容向后升级.
        返回:
            Dict[str, int], 当前充电循环配置.
        """
        if self._config_path.is_file() is False:
            return _default_config()

        with self._config_path.open("r", encoding="utf-8") as file_obj:
            payload = json.load(file_obj)
        if isinstance(payload, dict) is False:
            raise ValueError("充电循环配置文件格式错误, 必须是对象.")
        # 合并默认值, 老配置缺少 full_battery_pct 等新字段时自动补全
        merged = {**_default_config(), **payload}
        return _normalize_config(merged)

    def _write_config(self, config: Dict[str, int]) -> None:
        """
        功能:
            将充电循环配置写入持久化文件.
        参数:
            config: Dict[str, int], 已校验的充电循环配置.
        返回:
            None.
        """
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._config_path.with_suffix(f"{self._config_path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(self._config_path)
