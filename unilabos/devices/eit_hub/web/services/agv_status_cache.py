# -*- coding: utf-8 -*-
"""
功能:
    AGV 实时状态字段的内存缓存. 由后台采样线程写入, 由 /agv/status 路由读取.
    每个字段附带写入时间戳, 读取时按 max_age_s 判断新鲜度, 过期返回 None.
    彻底分离前端轮询与底层 IO, 避免锁竞争和短连接抖动直接影响展示层.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional, Tuple


class AgvStatusCache:
    """
    功能:
        线程安全的字段级状态缓存. value 与写入时刻一同保存,
        读取时如已超出 max_age_s 则返回 None, 强制保证 "最近 N 秒内的真实值".
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # 字段名 -> (value, monotonic_ts)
        self._store: Dict[str, Tuple[Any, float]] = {}

    def set(self, field: str, value: Any) -> None:
        """
        功能:
            写入字段并打上当前单调时钟时间戳.
        参数:
            field: str, 字段名.
            value: Any, 字段值.
        返回:
            None.
        """
        with self._lock:
            self._store[field] = (value, time.monotonic())

    def get(self, field: str, max_age_s: float) -> Optional[Any]:
        """
        功能:
            读取字段. 如未写入过或写入时间距今超过 max_age_s, 一律返回 None.
        参数:
            field: str, 字段名.
            max_age_s: float, 允许的最大新鲜度秒数.
        返回:
            Any 或 None, 命中且未过期返回原值, 否则返回 None.
        """
        with self._lock:
            entry = self._store.get(field)
        if entry is None:
            return None
        value, ts = entry
        if time.monotonic() - ts > max_age_s:
            return None
        return value

    def invalidate(self, field: Optional[str] = None) -> None:
        """
        功能:
            清除单个字段或全部字段, 用于断开连接时立即让缓存过期.
        参数:
            field: 可选 str, None 表示清除全部.
        返回:
            None.
        """
        with self._lock:
            if field is None:
                self._store.clear()
            else:
                self._store.pop(field, None)
