# -*- coding: utf-8 -*-
"""
功能:
    管理 AGVController 全局单例, 以及底盘和机械臂的连接状态.
    所有需要访问 AGV 的 Web 服务都通过这里获取 controller 实例.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

from unilabos.devices.eit_agv.controller.agv_controller import AGVController

logger = logging.getLogger("EITHubAgvContext")


class AgvContext:
    """
    功能:
        AGVController 全局单例容器.
        提供连接/断开底盘与机械臂, 查询连接状态等功能.
    """

    def __init__(self) -> None:
        self._controller: Optional[AGVController] = None
        self._lock = threading.RLock()
        self._chassis_connected = False
        self._arm_connected = False
        # 机械臂 Thrift 连接非线程安全, 必须序列化所有对 arm 的调用
        self.arm_lock = threading.RLock()

    def get_or_create(self) -> AGVController:
        """
        功能:
            懒加载 AGVController 实例, 全局单例.
        返回:
            AGVController, 主控实例.
        """
        with self._lock:
            if self._controller is None:
                logger.info("首次创建 AGVController 实例.")
                self._controller = AGVController(timeout=180000)
            return self._controller

    def connect_chassis(self) -> bool:
        """
        功能:
            以一次实际查询作为底盘连通性探测. AGVController 内部采用短连接模式,
            每次查询/导航都会新建 AGVDriver 并在完成后关闭, 不存在持久连接.
            这里以 query_current_station 成功作为底盘可用的判据. 已标记连接时直接返回, 保持幂等.
        返回:
            bool, True 表示探测成功并将底盘标记为已连接.
        """
        with self._lock:
            if self._chassis_connected is True:
                return True
        controller = self.get_or_create()
        try:
            station = controller.query_current_station()
        except Exception as exc:
            logger.exception("AGV 底盘连通性探测失败")
            with self._lock:
                self._chassis_connected = False
            raise exc
        if station is None:
            with self._lock:
                self._chassis_connected = False
            raise RuntimeError("AGV 底盘未响应当前站点查询")
        with self._lock:
            self._chassis_connected = True
        logger.info("AGV 底盘探测成功, 标记为已连接.")
        return True

    def disconnect_chassis(self) -> bool:
        """
        功能:
            清除底盘连接标记. AGVController 内部的 AGVDriver 为短连接, 无需显式关闭.
        返回:
            bool, True 表示已清除标记.
        """
        with self._lock:
            self._chassis_connected = False
        logger.info("AGV 底盘连接标记已清除.")
        return True

    def connect_arm(self) -> bool:
        """
        功能:
            连接机械臂. 已连接时直接返回成功, 避免底层 Thrift open 抛 "already open".
        返回:
            bool, True 表示连接成功或已处于连接状态.
        """
        controller = self.get_or_create()
        with self.arm_lock:
            # 幂等: 底层已打开 socket 时直接刷新标记并返回
            if self._arm_connected is True or getattr(controller.arm, "is_connected", False) is True:
                with self._lock:
                    self._arm_connected = True
                return True
            result = controller.arm.connect()
            with self._lock:
                self._arm_connected = bool(result)
            if result is False:
                raise RuntimeError(controller.arm.last_error_message or "机械臂连接失败")
        return True

    def disconnect_arm(self) -> bool:
        """
        功能:
            断开机械臂连接.
        返回:
            bool, True 表示已断开.
        """
        controller = self.get_or_create()
        with self.arm_lock:
            try:
                controller.arm.disconnect()
            except Exception as exc:
                logger.warning("断开机械臂时抛出异常: %s", exc)
            with self._lock:
                self._arm_connected = False
        return True

    def is_chassis_connected(self) -> bool:
        """
        功能:
            查询底盘连接标记.
        返回:
            bool, 连接状态.
        """
        with self._lock:
            return self._chassis_connected

    def is_arm_connected(self) -> bool:
        """
        功能:
            查询机械臂连接标记.
        返回:
            bool, 连接状态.
        """
        with self._lock:
            return self._arm_connected

    def status_snapshot(self) -> Dict[str, Any]:
        """
        功能:
            返回连接状态快照, 不触发任何 IO.
        返回:
            Dict, 包含 chassis 和 arm 的连接布尔标记.
        """
        with self._lock:
            return {
                "chassis_connected": self._chassis_connected,
                "arm_connected": self._arm_connected,
            }
