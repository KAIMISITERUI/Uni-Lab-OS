# -*- coding: utf-8 -*-
"""
功能:
    提供 EIT Hub 后台任务管理器, 用于承载合成工站长耗时操作.
"""

from __future__ import annotations

import logging
import threading
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from unilabos.devices.eit_hub.web.log_entry import LogEntry, make_entry

logger = logging.getLogger("EITHubJobs")

JsonDict = Dict[str, Any]
# Job 闭包接收的 log 回调签名: (message, level="info", source="").
JobLogFn = Callable[..., None]
JobCallable = Callable[[JobLogFn], Any]


class JobBusyError(RuntimeError):
    """
    功能:
        表示当前已有独占后台任务正在运行.
    """


class JobStoppedError(RuntimeError):
    """
    功能:
        表示后台任务收到停止请求并正常终止.
    参数:
        message: str, 停止原因说明.
        result: Any, 停止时需要保存的任务结果.
    """

    def __init__(self, message: str, result: Any = None) -> None:
        super().__init__(message)
        self.result = result


@dataclass
class JobRecord:
    """
    功能:
        保存后台任务的运行状态, 结构化日志和结果.
    参数:
        job_id: str, 后台任务 ID.
        name: str, 任务名称.
        status: str, queued/running/succeeded/failed/stopped.
        logs: List[LogEntry], 任务运行的结构化日志.
        result: Any, 任务结果.
        error: Optional[str], 失败信息.
    """

    job_id: str
    name: str
    status: str = "queued"
    logs: List[LogEntry] = field(default_factory=list)
    result: Any = None
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    started_at: Optional[str] = None
    finished_at: Optional[str] = None

    def add_log(self, message: str, level: str = "info", source: str = "") -> None:
        """
        功能:
            追加一条结构化任务日志.
        参数:
            message: str, 日志正文.
            level: str, info / success / warning / error.
            source: str, 来源标识.
        返回:
            None.
        """
        self.logs.append(make_entry(message, level=level, source=source))

    def to_dict(self) -> JsonDict:
        """
        功能:
            转换为可 JSON 序列化的字典.
        返回:
            Dict[str, Any], 任务状态快照.
        """
        return {
            "job_id": self.job_id,
            "name": self.name,
            "status": self.status,
            "logs": [entry.to_dict() for entry in self.logs],
            "result": _to_jsonable(self.result),
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


def _to_jsonable(value: Any) -> Any:
    """
    功能:
        将后台任务结果转换为 FastAPI 可序列化的结构.
    参数:
        value: Any, 原始结果.
    返回:
        Any, JSON 兼容值.
    """
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return f"<bytes length={len(value)}>"
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    return str(value)


class JobManager:
    """
    功能:
        管理后台任务生命周期, 并确保合成工站执行类任务同一时间只有一个运行.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: Dict[str, JobRecord] = {}
        self._active_job_id: Optional[str] = None

    def start_exclusive(self, name: str, target: JobCallable) -> JobRecord:
        """
        功能:
            创建独占后台任务, 当前已有任务运行时抛出 JobBusyError.
        参数:
            name: str, 任务名称.
            target: Callable, 接收 log 函数并返回任务结果的执行函数.
        返回:
            JobRecord, 已创建的任务记录.
        """
        with self._lock:
            if self._active_job_id is not None:
                active_job = self._jobs.get(self._active_job_id)
                if active_job is not None and active_job.status in ("queued", "running"):
                    raise JobBusyError(f"已有任务正在运行: {active_job.name}")

            job_id = uuid.uuid4().hex
            job = JobRecord(job_id=job_id, name=name)
            job.add_log("任务已进入后台队列.", level="info", source="job")
            self._jobs[job_id] = job
            self._active_job_id = job_id

        thread = threading.Thread(
            target=self._run_job,
            args=(job_id, target),
            name=f"eit-hub-job-{job_id[:8]}",
            daemon=True,
        )
        thread.start()
        logger.info("后台任务已创建, job_id=%s, name=%s", job_id, name)
        return job

    def get(self, job_id: str) -> Optional[JobRecord]:
        """
        功能:
            查询指定后台任务.
        参数:
            job_id: str, 后台任务 ID.
        返回:
            Optional[JobRecord], 未找到时返回 None.
        """
        with self._lock:
            return self._jobs.get(job_id)

    def is_busy(self) -> bool:
        """
        功能:
            判断当前是否存在排队或运行中的独占后台任务.
        返回:
            bool, True 表示当前繁忙.
        """
        with self._lock:
            if self._active_job_id is None:
                return False
            active_job = self._jobs.get(self._active_job_id)
            if active_job is None:
                return False
            return active_job.status in ("queued", "running")

    def list_recent(self, limit: int = 20) -> List[JsonDict]:
        """
        功能:
            返回最近创建的后台任务列表.
        参数:
            limit: int, 最大返回数量.
        返回:
            List[Dict[str, Any]], 任务快照列表.
        """
        with self._lock:
            jobs = list(self._jobs.values())
        jobs.sort(key=lambda item: item.created_at, reverse=True)
        return [job.to_dict() for job in jobs[:limit]]

    def _run_job(self, job_id: str, target: JobCallable) -> None:
        """
        功能:
            在线程中执行后台任务并记录状态.
        参数:
            job_id: str, 后台任务 ID.
            target: Callable, 实际任务函数.
        返回:
            None.
        """
        job = self.get(job_id)
        if job is None:
            logger.error("后台任务不存在, job_id=%s", job_id)
            return

        with self._lock:
            job.status = "running"
            job.started_at = datetime.now().isoformat(timespec="seconds")
            job.add_log("任务开始执行.", level="info", source="job")

        try:
            result = target(job.add_log)
            with self._lock:
                job.result = result
                job.status = "succeeded"
                job.finished_at = datetime.now().isoformat(timespec="seconds")
                job.add_log("任务执行成功.", level="success", source="job")
            logger.info("后台任务执行成功, job_id=%s, name=%s", job.job_id, job.name)
        except JobStoppedError as exc:
            logger.warning("后台任务已停止, job_id=%s, name=%s", job.job_id, job.name)
            with self._lock:
                job.result = exc.result
                job.status = "stopped"
                job.finished_at = datetime.now().isoformat(timespec="seconds")
                job.add_log(f"任务已停止: {exc}", level="warning", source="job")
        except Exception as exc:
            logger.exception("后台任务执行失败, job_id=%s, name=%s", job.job_id, job.name)
            with self._lock:
                job.error = str(exc)
                job.status = "failed"
                job.finished_at = datetime.now().isoformat(timespec="seconds")
                job.add_log(f"任务执行失败: {exc}", level="error", source="job")
                job.add_log(traceback.format_exc().strip(), level="error", source="job")
        finally:
            with self._lock:
                if self._active_job_id == job_id:
                    self._active_job_id = None


job_manager = JobManager()
