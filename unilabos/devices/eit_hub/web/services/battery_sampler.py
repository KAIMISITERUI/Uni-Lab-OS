# -*- coding: utf-8 -*-
"""
功能:
    电量定时采样服务. 周期性调用 AGVController.query_battery_status(),
    将结果追加到 JSON 文件, 保留最近 MAX_RECORDS 条记录, 供前端绘制曲线.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from .agv_context import AgvContext

logger = logging.getLogger("EITHubBatterySampler")

SAMPLE_INTERVAL_SECONDS = 60
MAX_RECORDS = 24 * 60  # 每分钟 1 条, 默认保留约 24 小时


class BatterySamplerService:
    """
    功能:
        电量历史采样服务, 作为 Web 启动时的常驻后台线程.
    """

    def __init__(self, context: AgvContext, data_path: Path) -> None:
        self._context = context
        self._data_path = data_path
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    # ==================== 生命周期 ====================

    def start(self) -> None:
        """
        功能:
            启动采样线程. 重复调用保持幂等.
        返回:
            None.
        """
        with self._lock:
            if self._thread is not None and self._thread.is_alive() is True:
                return
            self._stop_event.clear()
            thread = threading.Thread(target=self._loop, name="agv-battery-sampler", daemon=True)
            self._thread = thread
            thread.start()
        logger.info("电量采样服务已启动, 间隔 %ss", SAMPLE_INTERVAL_SECONDS)

    def stop(self) -> None:
        """
        功能:
            停止采样线程.
        返回:
            None.
        """
        with self._lock:
            self._stop_event.set()
            thread = self._thread
            self._thread = None
        if thread is not None and thread.is_alive() is True:
            thread.join(timeout=3.0)
        logger.info("电量采样服务已停止.")

    # ==================== 查询 ====================

    def get_history(self, hours: float = 6.0) -> List[Dict[str, Any]]:
        """
        功能:
            读取指定小时数内的电量记录.
        参数:
            hours: float, 查询窗口小时数.
        返回:
            List[Dict], 时间升序排列的记录列表.
        """
        records = self._load_records()
        if hours <= 0 or len(records) == 0:
            return records
        cutoff = datetime.now() - timedelta(hours=hours)
        cutoff_iso = cutoff.isoformat(timespec="seconds")
        return [item for item in records if item.get("timestamp", "") >= cutoff_iso]

    def get_latest(self) -> Optional[Dict[str, Any]]:
        """
        功能:
            获取最近一次采样结果.
        返回:
            Optional[Dict], 最近一条记录或 None.
        """
        records = self._load_records()
        if len(records) == 0:
            return None
        return records[-1]

    # ==================== 内部 ====================

    def _loop(self) -> None:
        """
        功能:
            采样循环. 每次调用 query_battery_status, 若底盘未连接则跳过.
        返回:
            None.
        """
        while self._stop_event.wait(SAMPLE_INTERVAL_SECONDS) is False:
            if self._context.is_chassis_connected() is False:
                continue
            try:
                data = self._context.get_or_create().query_battery_status(simple=False)
            except Exception as exc:
                logger.debug("电量采样查询失败, 跳过本次: %s", exc)
                continue
            if data is None or isinstance(data, dict) is False:
                continue
            battery_level = data.get("battery_level")
            if battery_level is None:
                continue
            record = {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "battery_level": float(battery_level),
                "charging": bool(data.get("charging", False)),
                "voltage": data.get("voltage"),
                "current": data.get("current"),
                "temperature": data.get("temperature"),
            }
            self._append_record(record)

    def _load_records(self) -> List[Dict[str, Any]]:
        """
        功能:
            从 JSON 文件读取全部历史记录.
        返回:
            List[Dict], 记录列表. 文件不存在或解析失败时返回空列表.
        """
        if self._data_path.is_file() is False:
            return []
        try:
            payload = json.loads(self._data_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("读取电量历史文件失败: %s", exc)
            return []
        records = payload.get("records")
        if isinstance(records, list) is False:
            return []
        return records

    def _append_record(self, record: Dict[str, Any]) -> None:
        """
        功能:
            向 JSON 文件追加一条记录, 超过 MAX_RECORDS 时裁剪.
        参数:
            record: Dict, 新记录.
        返回:
            None.
        """
        with self._lock:
            records = self._load_records()
            records.append(record)
            if len(records) > MAX_RECORDS:
                records = records[-MAX_RECORDS:]
            self._data_path.parent.mkdir(parents=True, exist_ok=True)
            self._data_path.write_text(
                json.dumps({"records": records}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
