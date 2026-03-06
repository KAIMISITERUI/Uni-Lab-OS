import logging
import threading
import time
from typing import Any, Dict, List, Optional

from .email_channel import EmailChannel
from .formatter import NoticeFormatter
from .notification_settings import NotificationSettings


class NotificationMonitor:
    """
    功能:
        后台守护线程, 周期性轮询 Notice API, 检测新的故障/告警通知并发送邮件.
        通过 threading.Event 控制优雅退出, 支持去重与速率限制.
    参数:
        controller: SynthesisStationController 实例, 用于调用 notice() 方法.
        settings: NotificationSettings, 通知配置.
    """

    def __init__(self, controller: Any, settings: NotificationSettings):
        self._controller = controller
        self._settings = settings
        self._logger = logging.getLogger(self.__class__.__name__)

        # 邮件渠道
        self._email_channel = EmailChannel(settings)

        # 线程控制
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # 去重: {notice_id: 首次处理的时间戳}
        self._processed_ids: Dict[int, float] = {}

        # 速率限制: 记录每次发送通知的时间戳
        self._send_timestamps: List[float] = []

        # 统计信息
        self._total_processed: int = 0
        self._last_poll_time: Optional[float] = None

    def start(self) -> None:
        """
        功能:
            启动后台轮询守护线程. 如果已在运行则跳过.
        参数:
            无.
        返回:
            无.
        """
        if self._thread is not None and self._thread.is_alive():
            self._logger.warning("通知监控已在运行, 跳过重复启动")
            return

        if not self._email_channel.is_available():
            self._logger.warning("邮件渠道未配置完整, 通知监控启动但无法发送邮件")

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="NotificationMonitor",
            daemon=True,  # 跟随主进程退出
        )
        self._thread.start()
        self._logger.info(
            "异常通知监控已启动, 轮询间隔=%.1fs, 监控类型=%s",
            self._settings.poll_interval_s,
            self._settings.notice_types,
        )

    def stop(self) -> None:
        """
        功能:
            通知守护线程优雅退出, 最多等待 5 秒.
        参数:
            无.
        返回:
            无.
        """
        if self._thread is None or not self._thread.is_alive():
            self._logger.info("通知监控未在运行")
            return

        self._stop_event.set()
        self._thread.join(timeout=5.0)
        if self._thread.is_alive():
            self._logger.warning("通知监控线程未在超时内退出")
        else:
            self._logger.info("异常通知监控已停止")
        self._thread = None

    @property
    def is_running(self) -> bool:
        """
        功能:
            返回监控线程是否正在运行.
        参数:
            无.
        返回:
            bool.
        """
        return self._thread is not None and self._thread.is_alive()

    @property
    def status_info(self) -> Dict[str, Any]:
        """
        功能:
            返回监控器的当前状态信息, 用于 CLI 状态查询.
        参数:
            无.
        返回:
            Dict, 包含 running, total_processed, last_poll_time, processed_ids_count.
        """
        return {
            "running": self.is_running,
            "total_processed": self._total_processed,
            "last_poll_time": self._last_poll_time,
            "processed_ids_count": len(self._processed_ids),
            "email_available": self._email_channel.is_available(),
        }

    def _poll_loop(self) -> None:
        """
        功能:
            主轮询循环: 周期性获取通知 -> 过滤新通知 -> 发送邮件.
            使用 _stop_event.wait() 替代 time.sleep(), 确保可快速响应停止信号.
        参数:
            无.
        返回:
            无.
        """
        self._logger.info("通知监控轮询循环已启动")

        while not self._stop_event.is_set():
            try:
                self._last_poll_time = time.time()

                # 获取通知
                notices = self._fetch_notices()
                if notices:
                    # 过滤出未处理的新通知
                    new_notices = self._filter_new(notices)
                    if new_notices:
                        self._send_email(new_notices)

                # 定期清理过期的已处理记录
                self._cleanup_processed_ids()

            except Exception as e:
                # 捕获所有异常, 确保循环不中断
                self._logger.error("通知监控轮询异常, 将在下一周期重试: %s", e)

            # 等待下一轮, 可被 stop() 信号快速唤醒
            self._stop_event.wait(timeout=self._settings.poll_interval_s)

        self._logger.info("通知监控轮询循环已退出")

    def _fetch_notices(self) -> List[Dict[str, Any]]:
        """
        功能:
            调用 controller.notice() 获取指定类型的通知列表.
            复用 controller 层的 _call_with_relogin 机制处理 401.
        参数:
            无.
        返回:
            List[Dict], 通知列表. 获取失败返回空列表.
        """
        try:
            resp = self._controller.notice(types=self._settings.notice_types)
            notice_list = resp.get("list", [])
            if not isinstance(notice_list, list):
                return []
            return notice_list
        except Exception as e:
            self._logger.warning("获取通知列表失败: %s", e)
            return []

    def _filter_new(self, notices: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        功能:
            过滤出未处理的新通知:
            - 跳过已处理的 id (在冷却期内)
            - 跳过状态为 FIXED(3) 的通知
        参数:
            notices: List[Dict], 从 Notice API 获取的原始通知列表.
        返回:
            List[Dict], 需要发送通知的新条目.
        """
        now = time.time()
        new_notices = []

        for notice in notices:
            notice_id = notice.get("id")
            if notice_id is None:
                continue

            # 跳过已恢复的通知
            status = notice.get("status")
            if status == 3:
                continue

            # 检查去重冷却
            last_time = self._processed_ids.get(notice_id)
            if last_time is not None:
                elapsed = now - last_time
                if elapsed < self._settings.cooldown_s:
                    # 仍在冷却期内, 跳过
                    continue

            new_notices.append(notice)

        return new_notices

    def _send_email(self, notices: List[Dict[str, Any]]) -> None:
        """
        功能:
            格式化通知内容并通过邮件渠道发送. 发送成功后记录已处理 id.
        参数:
            notices: List[Dict], 需要发送的通知列表.
        返回:
            无.
        """
        # 检查速率限制
        if not self._check_rate_limit():
            self._logger.warning(
                "已达到每小时最大通知数(%d), 暂停发送",
                self._settings.max_notifications_per_hour,
            )
            return

        # 格式化邮件
        subject, html_body = NoticeFormatter.format_email(notices)

        # 发送
        success = self._email_channel.send(subject, html_body)

        now = time.time()
        if success:
            # 记录已处理的通知 id
            for notice in notices:
                notice_id = notice.get("id")
                if notice_id is not None:
                    self._processed_ids[notice_id] = now
            self._total_processed += len(notices)
            self._send_timestamps.append(now)
            self._logger.info("已发送 %d 条异常通知邮件", len(notices))
        else:
            self._logger.error("异常通知邮件发送失败, 将在下一轮重试")

    def _check_rate_limit(self) -> bool:
        """
        功能:
            检查是否超过每小时最大通知数.
        参数:
            无.
        返回:
            bool, True 表示未超限可继续发送, False 表示已超限.
        """
        now = time.time()
        one_hour_ago = now - 3600.0

        # 清理一小时前的记录
        self._send_timestamps = [ts for ts in self._send_timestamps if ts > one_hour_ago]

        return len(self._send_timestamps) < self._settings.max_notifications_per_hour

    def _cleanup_processed_ids(self) -> None:
        """
        功能:
            清理超过 24 小时的已处理通知记录, 防止内存无限增长.
        参数:
            无.
        返回:
            无.
        """
        now = time.time()
        expire_threshold = 86400.0  # 24 小时

        expired_ids = [
            nid for nid, ts in self._processed_ids.items()
            if now - ts > expire_threshold
        ]
        for nid in expired_ids:
            del self._processed_ids[nid]

        if expired_ids:
            self._logger.debug("已清理 %d 条过期的通知处理记录", len(expired_ids))
