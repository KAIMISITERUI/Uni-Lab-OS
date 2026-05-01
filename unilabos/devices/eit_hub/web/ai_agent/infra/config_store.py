# -*- coding: utf-8 -*-
"""
功能:
    AI 助手 DeepSeek 接入配置的持久化存储, 使用本地 JSON.
    UI 写入的字段优先于环境变量; 字段为 None / 空字符串视为未设置, 回退 env.
    单独文件不与 ai_agent.db 混用, 避免误删历史时丢配置.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("EITHubAiAgentConfigStore")

JsonDict = Dict[str, Any]

AI_AGENT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "data" / "ai_agent_config.json"


@dataclass
class AiAgentConfig:
    """
    功能:
        AI 助手运行时配置, 全部字段可选 (None 表示未在 UI 设置, 走 env).
    参数:
        api_key: str 或 None, DeepSeek API Key.
        base_url: str 或 None, 接口前缀.
        model: str 或 None, 模型 ID.
        timeout_s: float 或 None, 请求超时秒.
    """

    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    timeout_s: Optional[float] = None

    def to_persisted_dict(self) -> JsonDict:
        """
        功能:
            转成 JSON 可序列化字典, 跳过 None 字段以便 UI 可清除单项.
        返回:
            Dict[str, Any], 仅含已设置的字段.
        """
        result: JsonDict = {}
        if self.api_key is not None:
            result["api_key"] = self.api_key
        if self.base_url is not None:
            result["base_url"] = self.base_url
        if self.model is not None:
            result["model"] = self.model
        if self.timeout_s is not None:
            result["timeout_s"] = self.timeout_s
        return result


def _normalize_optional_text(value: Any) -> Optional[str]:
    """
    功能:
        把任意 JSON 字段规整为非空字符串或 None, 空白值统一返回 None.
    参数:
        value: Any, 任意来源值.
    返回:
        Optional[str], 非空文本或 None.
    """
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    return text


def _normalize_optional_float(value: Any) -> Optional[float]:
    """
    功能:
        把任意 JSON 字段规整为正浮点数或 None, 非法值返回 None.
    参数:
        value: Any, 任意来源值.
    返回:
        Optional[float], 正数或 None.
    """
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result <= 0:
        return None
    return result


class AiAgentConfigStore:
    """
    功能:
        线程安全的 AI 助手配置存储. 所有读写都加锁, 写时原子替换文件.
    """

    def __init__(self, data_path: Path = AI_AGENT_CONFIG_PATH) -> None:
        self._data_path = data_path
        self._lock = threading.Lock()
        self._data_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> AiAgentConfig:
        """
        功能:
            从 JSON 文件加载配置, 文件不存在或格式异常时返回空配置.
        返回:
            AiAgentConfig, 已规整的配置实例.
        """
        with self._lock:
            if self._data_path.is_file() is False:
                return AiAgentConfig()
            try:
                payload = json.loads(self._data_path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("读取 AI 助手配置失败, 使用空配置: %s", exc)
                return AiAgentConfig()
        if isinstance(payload, dict) is False:
            return AiAgentConfig()
        return AiAgentConfig(
            api_key=_normalize_optional_text(payload.get("api_key")),
            base_url=_normalize_optional_text(payload.get("base_url")),
            model=_normalize_optional_text(payload.get("model")),
            timeout_s=_normalize_optional_float(payload.get("timeout_s")),
        )

    def save(self, config: AiAgentConfig) -> AiAgentConfig:
        """
        功能:
            把配置写入 JSON 文件 (原子替换), 字段为 None 不写入.
        参数:
            config: AiAgentConfig, 需要持久化的配置.
        返回:
            AiAgentConfig, 写入后再次规整加载的配置, 用于回显.
        """
        payload = config.to_persisted_dict()
        with self._lock:
            temp_path = self._data_path.with_suffix(f"{self._data_path.suffix}.tmp")
            temp_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temp_path.replace(self._data_path)
        # 不打 API Key 内容, 避免日志泄露; 仅打字段名变更
        logger.info("AI 助手配置已保存, 字段: %s", sorted(payload.keys()))
        return self.load()
