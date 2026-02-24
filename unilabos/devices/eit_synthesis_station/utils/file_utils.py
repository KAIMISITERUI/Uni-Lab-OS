# -*- coding: utf-8 -*-
"""
Excel 文件安全读写工具

在 Windows 上, Excel 打开某个 .xlsx 文件时会在同目录生成 ~$filename.xlsx 锁文件,
并持有文件独占句柄, 导致其他进程写入时抛出 PermissionError.
本模块提供带自动解锁与重试逻辑的安全写入函数, 替代裸调用的 df.to_excel / wb.save.

解锁策略(优先级从高到低):
  1. 通过 Windows COM 接口精准关闭 Excel 中的目标工作簿, 不影响其他已打开的文件
  2. COM 不可用或失败时, 通过 psutil 终止持有文件句柄的整个进程(兜底)
"""

import time
import logging
from pathlib import Path
from typing import Union

import psutil

logger = logging.getLogger("FileUtils")


def _try_close_excel_workbook(path: Path) -> bool:
    """
    功能:
        通过 Windows COM 接口连接正在运行的 Excel 实例,
        精准关闭与目标路径匹配的工作簿, 不影响同一 Excel 进程中其他已打开的文件.
        仅在 Windows + pywin32 可用时生效, 其他情况静默返回 False.
    参数:
        path: 需要关闭的工作簿的绝对路径(Path 对象)
    返回:
        bool, True 表示成功通过 COM 关闭了目标工作簿, False 表示未能通过 COM 关闭
    """
    try:
        import win32com.client  # pywin32, 仅 Windows 可用

        # 连接已运行的 Excel 实例(若 Excel 未启动会抛出 COM 错误)
        excel = win32com.client.GetActiveObject("Excel.Application")
        target = str(path).lower()

        # 遍历所有已打开的工作簿, 找到路径匹配的那一个
        for wb in excel.Workbooks:
            if wb.FullName.lower() == target:
                wb.Close(SaveChanges=False)  # 只关闭目标工作簿, 不保存(由调用方写入)
                logger.info("已通过 COM 精准关闭 Excel 工作簿: %s", path.name)
                return True

        logger.debug("COM 已连接 Excel, 但未找到工作簿: %s", path.name)
        return False
    except Exception as exc:
        # ImportError(pywin32 未安装) / COM 连接失败 / Excel 未运行 等均视为不可用
        logger.debug("COM 关闭工作簿失败, 将回退至进程终止方式 | %s", exc)
        return False


def release_file_lock(path: Union[str, Path]) -> bool:
    """
    功能:
        检测并释放 Windows 下占用指定文件的进程锁.
        优先通过 COM 接口只关闭 Excel 中的目标工作簿;
        COM 不可用时再通过 psutil 遍历进程句柄并终止占用进程.
    参数:
        path: 被锁定的目标文件路径
    返回:
        bool, True 表示成功释放了文件锁, False 表示未发现占用进程
    """
    path = Path(path).resolve()
    lock_file = path.parent / f"~${path.name}"  # Office 临时锁文件
    released = False

    # --- 策略 1: 锁文件存在时, 优先通过 COM 精准关闭目标工作簿 ---
    if lock_file.exists():
        logger.warning("检测到 Excel 锁文件, 尝试通过 COM 关闭工作簿 | 文件: %s", path.name)
        if _try_close_excel_workbook(path):
            released = True
            # COM 成功关闭工作簿后, 等待 Excel 释放文件句柄
            time.sleep(0.5)
            # 清理可能残留的锁文件
            if lock_file.exists():
                try:
                    lock_file.unlink()
                except OSError:
                    pass  # 锁文件已被 Excel 自动删除则忽略
            return released
        # COM 失败, 继续走 psutil 流程

    # --- 策略 2: 通过 psutil 扫描持有文件句柄的进程 ---
    for proc in psutil.process_iter(["pid", "name", "open_files"]):
        try:
            open_files = proc.info.get("open_files") or []
            held_paths = {Path(f.path).resolve() for f in open_files}

            if path not in held_paths and lock_file not in held_paths:
                continue

            proc_name = proc.info["name"]
            proc_pid  = proc.info["pid"]

            # 对 Excel 进程: 先尝试 COM 精准关闭工作簿, 避免误关其他文件
            if proc_name.lower() in ("excel.exe", "microsoft excel"):
                logger.warning(
                    "检测到 Excel 占用文件, 尝试 COM 精准关闭 | 文件: %s | PID=%s",
                    path.name, proc_pid,
                )
                if _try_close_excel_workbook(path):
                    released = True
                    continue  # COM 成功, 不杀进程, 继续检查下一个进程
                # COM 失败才杀进程
                logger.warning("COM 失败, 回退终止 Excel 进程 | PID=%s", proc_pid)
            else:
                logger.warning(
                    "检测到文件被进程占用, 正在终止 | 文件: %s | 进程: %s (PID=%s)",
                    path.name, proc_name, proc_pid,
                )

            # 终止整个进程(Excel COM 失败兜底, 或非 Excel 进程)
            try:
                proc.terminate()        # 先发送温和的 SIGTERM
                proc.wait(timeout=2)    # 最多等 2 秒
            except psutil.TimeoutExpired:
                proc.kill()             # 超时则强制 kill
            except psutil.AccessDenied:
                logger.warning("无权限终止进程 %s (PID=%s), 跳过", proc_name, proc_pid)
                continue
            released = True

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            # 进程在遍历期间已退出或无权查看, 直接跳过
            continue

    # 清理残留锁文件(进程退出后可能不会立即删除)
    if lock_file.exists():
        try:
            lock_file.unlink()
            logger.info("已删除残留锁文件: %s", lock_file.name)
        except OSError as exc:
            logger.warning("无法删除锁文件 %s: %s", lock_file.name, exc)

    return released


def safe_excel_write(df, path: Union[str, Path], retries: int = 3, delay: float = 2.0, **kwargs) -> None:
    """
    功能:
        将 DataFrame 安全写入 Excel 文件.
        遇到 PermissionError 时自动调用 release_file_lock 解锁并重试,
        最多重试 retries 次, 仍失败则抛出带有中文提示的异常.
    参数:
        df      : pd.DataFrame, 待写入数据
        path    : str | Path, 目标 Excel 文件路径
        retries : int, 最大重试次数, 默认 3
        delay   : float, 每次重试前等待秒数, 默认 2.0
        **kwargs: 透传给 df.to_excel() 的额外参数(如 index, sheet_name 等)
    返回:
        None
    """
    path = Path(path)
    for attempt in range(1, retries + 1):
        try:
            df.to_excel(path, **kwargs)
            if attempt > 1:
                logger.info("文件写入成功(第 %d 次尝试): %s", attempt, path.name)
            return  # 写入成功, 直接返回
        except PermissionError as exc:
            logger.warning(
                "写入 Excel 权限不足(第 %d/%d 次), 尝试自动解锁 | 文件: %s | 错误: %s",
                attempt, retries, path.name, exc,
            )
            release_file_lock(path)     # 解锁占用进程
            time.sleep(delay)           # 等待 OS 释放文件句柄
            if attempt == retries:
                raise PermissionError(
                    f"写入 Excel 文件失败, 已重试 {retries} 次仍无法获得写权限: {path}\n"
                    f"请确认文件未被其他程序占用后重试."
                ) from exc


def safe_workbook_save(wb, path: Union[str, Path], retries: int = 3, delay: float = 2.0) -> None:
    """
    功能:
        将 openpyxl Workbook 安全保存到文件.
        遇到 PermissionError 时自动调用 release_file_lock 解锁并重试,
        最多重试 retries 次, 仍失败则抛出带有中文提示的异常.
    参数:
        wb      : openpyxl.Workbook, 待保存工作簿对象
        path    : str | Path, 目标文件路径
        retries : int, 最大重试次数, 默认 3
        delay   : float, 每次重试前等待秒数, 默认 2.0
    返回:
        None
    """
    path = Path(path)
    for attempt in range(1, retries + 1):
        try:
            wb.save(path)
            if attempt > 1:
                logger.info("工作簿保存成功(第 %d 次尝试): %s", attempt, path.name)
            return  # 保存成功, 直接返回
        except PermissionError as exc:
            logger.warning(
                "保存工作簿权限不足(第 %d/%d 次), 尝试自动解锁 | 文件: %s | 错误: %s",
                attempt, retries, path.name, exc,
            )
            release_file_lock(path)     # 解锁占用进程
            time.sleep(delay)           # 等待 OS 释放文件句柄
            if attempt == retries:
                raise PermissionError(
                    f"保存 Excel 文件失败, 已重试 {retries} 次仍无法获得写权限: {path}\n"
                    f"请确认文件未被其他程序占用后重试."
                ) from exc
