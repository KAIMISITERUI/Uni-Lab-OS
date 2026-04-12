# -*- coding: utf-8 -*-
import os
from dataclasses import dataclass
from pathlib import Path

try:
    from devices_logging import configure_root_logging
except ImportError:
    from unilabos.devices.devices_logging import configure_root_logging


# 驱动根目录, 用于默认数据/数据库路径定位
_DRIVER_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    """
    功能:
        eit_chemical_manager 驱动的运行期配置.
        化学品管理驱动不依赖远程 HTTP 服务, 主要配置均为本地路径与日志.
    参数:
        db_path: SQLite 数据库文件路径.
        data_dir: 数据根目录, 存放 ChemicalBook 缓存与 sidecar JSON.
        log_level: 日志级别字符串, 例如 "INFO".
        request_timeout_s: 在线查询 HTTP 请求默认超时(秒).
    返回:
        Settings.
    """

    db_path: Path = _DRIVER_ROOT / "data" / "chemical_library.db"
    data_dir: Path = _DRIVER_ROOT / "data"
    log_level: str = "INFO"
    request_timeout_s: float = 30.0

    @staticmethod
    def from_env() -> "Settings":
        """
        功能:
            从环境变量读取配置.
        参数:
            无.
        返回:
            Settings.
        环境变量:
            CHEM_MGR_DB_PATH, CHEM_MGR_DATA_DIR, CHEM_MGR_LOG_LEVEL,
            CHEM_MGR_REQUEST_TIMEOUT_S.
        """
        db_path_str = os.getenv("CHEM_MGR_DB_PATH")
        db_path = Path(db_path_str) if db_path_str else Settings.db_path

        data_dir_str = os.getenv("CHEM_MGR_DATA_DIR")
        data_dir = Path(data_dir_str) if data_dir_str else Settings.data_dir

        log_level = os.getenv("CHEM_MGR_LOG_LEVEL", Settings.log_level)

        timeout_str = os.getenv("CHEM_MGR_REQUEST_TIMEOUT_S", str(Settings.request_timeout_s))
        try:
            request_timeout_s = float(timeout_str)
        except ValueError:
            request_timeout_s = Settings.request_timeout_s

        return Settings(
            db_path=db_path,
            data_dir=data_dir,
            log_level=log_level,
            request_timeout_s=request_timeout_s,
        )


def configure_logging(level: str = "INFO") -> None:
    """
    功能:
        配置全局 logging, 统一输出格式.
    参数:
        level: 日志级别, 例如 "DEBUG", "INFO".
    返回:
        无.
    """
    configure_root_logging(level=level)
