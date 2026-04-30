# -*- coding: utf-8 -*-
"""
功能:
    AGV 状态字段的后台采样线程. ChassisSampler 周期 5s 采样底盘字段,
    ArmSampler 周期 2s 采样机械臂字段. 采样成功写入 AgvStatusCache,
    连续 N 次成功/失败用于自动翻转 AgvContext 的连接标记, 替代一次性探针.

    采样器是 AgvContext 内部连接探针的唯一来源, 同时也是 AgvStatusCache 的唯一写入者.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, List, Optional

from .agv_context import AgvContext
from .agv_status_cache import AgvStatusCache

logger = logging.getLogger("EITHubAgvStatusSampler")

CHASSIS_SAMPLE_INTERVAL_S = 5.0
ARM_SAMPLE_INTERVAL_S = 2.0
ARM_LOCK_ACQUIRE_TIMEOUT_S = 1.0
# 连续成功/失败次数达到此阈值才翻转连接标记, 抑制单次抖动
HEALTH_FLIP_THRESHOLD = 3


class _BaseSampler:
    """
    功能:
        采样线程基类. 子类只需实现 _sample_once 与 _on_health_flip.
    """

    name: str = "base-sampler"
    interval_s: float = 5.0

    def __init__(self, context: AgvContext, cache: AgvStatusCache) -> None:
        self._context = context
        self._cache = cache
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lifecycle_lock = threading.Lock()
        # 连续成功/失败计数, 用于驱动连接标记翻转
        self._consecutive_success = 0
        self._consecutive_failure = 0

    def start(self) -> None:
        """
        功能:
            启动采样线程, 重复调用幂等.
        返回:
            None.
        """
        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive() is True:
                return
            self._stop_event.clear()
            self._consecutive_success = 0
            self._consecutive_failure = 0
            thread = threading.Thread(target=self._loop, name=self.name, daemon=True)
            self._thread = thread
            thread.start()
        logger.info("%s 已启动, 间隔 %.1fs", self.name, self.interval_s)

    def stop(self) -> None:
        """
        功能:
            停止采样线程并等待退出.
        返回:
            None.
        """
        with self._lifecycle_lock:
            self._stop_event.set()
            thread = self._thread
            self._thread = None
        if thread is not None and thread.is_alive() is True:
            thread.join(timeout=3.0)
        logger.info("%s 已停止.", self.name)

    def _loop(self) -> None:
        """
        功能:
            周期采样主循环. wait 在被 set 时立即返回 True 以便快速退出.
        返回:
            None.
        """
        while self._stop_event.wait(self.interval_s) is False:
            try:
                outcome = self._sample_once()
            except Exception as exc:
                # 采样过程的兜底异常处理, 单周期失败不应崩溃整个线程
                logger.warning("%s 单周期采样异常: %s", self.name, exc)
                outcome = "failure"
            self._update_health(outcome)

    def _update_health(self, outcome: str) -> None:
        """
        功能:
            根据本轮采样的整体结果更新连续计数, 并在阈值触发时翻转连接标记.
        参数:
            outcome: str, 取值为 "success" / "failure" / "skip"
                "success" 全部底层调用成功, 计入连续成功
                "failure" 至少一次底层调用失败, 计入连续失败
                "skip" 当前周期未实际尝试 (例如机械臂锁被 Job 占用), 不影响计数
        返回:
            None.
        """
        if outcome == "skip":
            return
        if outcome == "success":
            self._consecutive_success += 1
            self._consecutive_failure = 0
            if self._consecutive_success >= HEALTH_FLIP_THRESHOLD:
                self._on_health_flip(True)
        else:
            self._consecutive_failure += 1
            self._consecutive_success = 0
            if self._consecutive_failure >= HEALTH_FLIP_THRESHOLD:
                self._on_health_flip(False)

    def _sample_once(self) -> str:
        """子类实现, 执行一轮采样并返回 outcome."""
        raise NotImplementedError

    def _on_health_flip(self, healthy: bool) -> None:
        """子类实现, 翻转 AgvContext 连接标记."""
        raise NotImplementedError

    def _run_field(self, field: str, fn: Callable[[], Any]) -> bool:
        """
        功能:
            执行单个字段查询, 成功写 cache 并返回 True, 失败写日志并返回 False.
            字段间互不影响, 一个失败不会让其他字段被丢弃.
        参数:
            field: str, 字段名, 同时是 cache 键.
            fn: Callable, 实际查询逻辑.
        返回:
            bool, 成功为 True.
        """
        try:
            value = fn()
        except Exception as exc:
            logger.debug("%s 字段 %s 查询失败: %s", self.name, field, exc)
            return False
        self._cache.set(field, value)
        return True


class ChassisSampler(_BaseSampler):
    """
    功能:
        底盘字段采样器, 周期 5s. 采样 station/battery/charge_control/nav_task,
        连续 3 次全部成功翻 chassis_connected=True, 连续 3 次全部失败翻 False.
    """

    name = "agv-chassis-sampler"
    interval_s = CHASSIS_SAMPLE_INTERVAL_S

    def _sample_once(self) -> str:
        """
        功能:
            一轮底盘采样. 直接复用 AGVController 现有查询方法, 不新建调用入口.
        返回:
            str, "success" 表示 4 个字段全部成功, "failure" 表示至少一个失败.
        """
        controller = self._context.get_or_create()
        results: List[bool] = [
            self._run_field("station", controller.query_current_station),
            self._run_field("battery", lambda: controller.query_battery_status(simple=False)),
            self._run_field("charge_control", controller.query_charge_control_status),
            self._run_field("nav_task", controller.query_nav_task_status),
        ]
        if all(results) is True:
            return "success"
        return "failure"

    def _on_health_flip(self, healthy: bool) -> None:
        """
        功能:
            翻转底盘连接标记. 由 AgvContext 暴露的私有 setter 完成实际写入.
        参数:
            healthy: bool, True 表示连续多周期采样均成功.
        返回:
            None.
        """
        if self._context.is_chassis_connected() == healthy:
            return
        self._context._set_chassis_connected(healthy)
        logger.info("底盘连接标记自动翻转为 %s (连续阈值=%d)", healthy, HEALTH_FLIP_THRESHOLD)


class ArmSampler(_BaseSampler):
    """
    功能:
        机械臂字段采样器, 周期 2s. Thrift 非线程安全, 必须先抢 arm_lock.
        Job 线程占锁时, 本周期跳过, 字段 ts 不更新, 由 cache TTL 自动过期降级.
    """

    name = "agv-arm-sampler"
    interval_s = ARM_SAMPLE_INTERVAL_S

    def _sample_once(self) -> str:
        """
        功能:
            一轮机械臂采样. 锁超时不计失败 (是 Job 占用而非底层故障).
        返回:
            str, "success" / "failure" / "skip".
        """
        controller = self._context.get_or_create()
        if self._context.arm_lock.acquire(timeout=ARM_LOCK_ACQUIRE_TIMEOUT_S) is False:
            # 锁被 Job 长动作占用, 本轮跳过, 不影响健康计数
            logger.debug("%s 等锁超时, 本轮跳过", self.name)
            return "skip"
        try:
            arm = controller.arm
            results: List[bool] = [
                self._run_field("slots", arm.get_all_slots_status),
                self._run_field("gripper_state", arm.get_gripper_state),
                self._run_field("current_gripper", arm.get_current_gripper),
                self._run_field("tcp_pose", arm.get_tcp_pose),
                self._run_field("joints", arm.get_joints_position),
                self._run_field("is_moving", arm.is_moving),
                self._run_field("robot_status", arm.get_robot_status),
                # DO1 用于快换锁状态, DO2 用于夹爪开合状态, 同样作为机械臂字段一并采样
                self._run_field("digital_output_1", lambda: arm.get_digital_output(1)),
                self._run_field("digital_output_2", lambda: arm.get_digital_output(2)),
            ]
        finally:
            self._context.arm_lock.release()
        if all(results) is True:
            return "success"
        return "failure"

    def _on_health_flip(self, healthy: bool) -> None:
        """
        功能:
            翻转机械臂连接标记.
        参数:
            healthy: bool.
        返回:
            None.
        """
        if self._context.is_arm_connected() == healthy:
            return
        self._context._set_arm_connected(healthy)
        logger.info("机械臂连接标记自动翻转为 %s (连续阈值=%d)", healthy, HEALTH_FLIP_THRESHOLD)
