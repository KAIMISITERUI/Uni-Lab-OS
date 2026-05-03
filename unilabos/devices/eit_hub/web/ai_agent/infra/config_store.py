# -*- coding: utf-8 -*-
"""
功能:
    AI 助手配置的持久化存储, 使用本地 JSON.
    顶层字段 active_base_model_id / active_thinking_level_id 决定下拉两段式选择;
    providers 仅保存各 provider 的凭证 (api_key/base_url/timeout_s), 不再存模型名.
    UI 字段优先于环境变量; 字段为 None / 空字符串视为未设置, 回退 env / 默认.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .model_catalog import (
    BASE_MODEL_INDEX,
    BaseModel,
    PROVIDER_CATALOG,
    ThinkingLevel,
    allowed_provider_values,
    default_base_model_id,
    get_base_model,
    get_provider_catalog,
    get_thinking_level,
)

logger = logging.getLogger("EITHubAiAgentConfigStore")

JsonDict = Dict[str, Any]

AI_AGENT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "data" / "ai_agent_config.json"

ENV_BASE_MODEL = "AI_AGENT_BASE_MODEL"
ENV_THINKING_LEVEL = "AI_AGENT_THINKING_LEVEL"


@dataclass
class AiProviderConfig:
    """
    功能:
        单个模型 provider 的凭证 UI 持久化配置, 全部字段可选, None 表示回退 env / 默认值.
    参数:
        api_key: Optional[str], provider API Key.
        base_url: Optional[str], 接口前缀.
        timeout_s: Optional[float], 请求超时秒.
    """

    api_key: Optional[str] = None
    base_url: Optional[str] = None
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
        if self.timeout_s is not None:
            result["timeout_s"] = self.timeout_s
        return result


@dataclass
class AiAgentConfig:
    """
    功能:
        AI 助手运行时配置. active_base_model_id / active_thinking_level_id 由下拉左右两按钮决定;
        providers 保存各 provider 的凭证 UI 覆盖.
    参数:
        active_base_model_id: Optional[str], UI 指定的 base_model ID, None 表示回退 env / 默认.
        active_thinking_level_id: Optional[str], UI 指定的思考档位 ID, None 表示回退 base_model 默认档.
        providers: Dict[str, AiProviderConfig], provider 凭证映射.
    """

    active_base_model_id: Optional[str] = None
    active_thinking_level_id: Optional[str] = None
    providers: Dict[str, AiProviderConfig] = field(default_factory=dict)

    def get_provider_config(self, provider_id: str) -> AiProviderConfig:
        """
        功能:
            获取指定 provider 的凭证 UI 配置, 缺失时返回空配置.
        参数:
            provider_id: str, provider ID.
        返回:
            AiProviderConfig, provider 凭证 UI 配置.
        """
        config = self.providers.get(provider_id)
        if config is None:
            return AiProviderConfig()
        return config

    def to_persisted_dict(self) -> JsonDict:
        """
        功能:
            转成 JSON 可序列化字典, 跳过未设置字段.
        返回:
            Dict[str, Any], 持久化配置.
        """
        result: JsonDict = {}
        if self.active_base_model_id is not None:
            result["active_base_model_id"] = self.active_base_model_id
        if self.active_thinking_level_id is not None:
            result["active_thinking_level_id"] = self.active_thinking_level_id
        provider_payload: JsonDict = {}
        for provider_id, provider_config in self.providers.items():
            if provider_id not in PROVIDER_CATALOG:
                continue
            item = provider_config.to_persisted_dict()
            if len(item) > 0:
                provider_payload[provider_id] = item
        if len(provider_payload) > 0:
            result["providers"] = provider_payload
        return result


@dataclass
class ProviderCredentials:
    """
    功能:
        合并 UI / env / 默认值后的 provider 凭证.
    参数:
        provider_id: str, provider ID.
        provider_label: str, provider 展示名称.
        api_key: str, 合并后的 API Key, 未设置时为空字符串.
        base_url: str, 合并后的接口前缀.
        timeout_s: float, 合并后的超时秒.
        source: Dict[str, str], 每个字段来源 ui/env/default/none.
        api_key_env: str, API Key 环境变量名.
    """

    provider_id: str
    provider_label: str
    api_key: str
    base_url: str
    timeout_s: float
    source: Dict[str, str]
    api_key_env: str


@dataclass
class ActiveSelection:
    """
    功能:
        当前生效的下拉两段式选择, 已经把 base_model 和 thinking_level 解析到对象.
    参数:
        base_model: BaseModel, 当前 base_model.
        thinking_level: Optional[ThinkingLevel], 当前 thinking_level; base_model 无思考维时为 None.
        base_model_source: str, base_model 来源 ui/env/default.
        thinking_level_source: str, thinking_level 来源 ui/default; base_model 无思考维时为 default.
    """

    base_model: BaseModel
    thinking_level: Optional[ThinkingLevel]
    base_model_source: str
    thinking_level_source: str


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


def _normalize_base_model_id(value: Any) -> Optional[str]:
    """
    功能:
        规整 base_model_id, 仅接受已登记 ID.
    参数:
        value: Any, 原始值.
    返回:
        Optional[str], 合法 base_model_id 或 None.
    """
    text = _normalize_optional_text(value)
    if text is None:
        return None
    if text not in BASE_MODEL_INDEX:
        return None
    return text


def _normalize_thinking_level_id(value: Any) -> Optional[str]:
    """
    功能:
        规整 thinking_level_id 字段为非空字符串或 None, 不在此处校验是否合法 (校验在 resolve 阶段).
    参数:
        value: Any, 原始值.
    返回:
        Optional[str], 非空文本或 None.
    """
    return _normalize_optional_text(value)


def _provider_from_payload(payload: Any) -> AiProviderConfig:
    """
    功能:
        从 JSON 对象规整单个 provider 凭证配置, 忽略多余字段.
    参数:
        payload: Any, provider 凭证原始 JSON.
    返回:
        AiProviderConfig, 已规整凭证.
    """
    if isinstance(payload, dict) is False:
        return AiProviderConfig()
    return AiProviderConfig(
        api_key=_normalize_optional_text(payload.get("api_key")),
        base_url=_normalize_optional_text(payload.get("base_url")),
        timeout_s=_normalize_optional_float(payload.get("timeout_s")),
    )


def load_env_provider_config(provider_id: str) -> AiProviderConfig:
    """
    功能:
        从环境变量加载指定 provider 的凭证.
    参数:
        provider_id: str, provider ID.
    返回:
        AiProviderConfig, env 配置.
    """
    catalog = get_provider_catalog(provider_id)
    timeout_text = os.getenv(catalog.timeout_env, "").strip()
    return AiProviderConfig(
        api_key=_normalize_optional_text(os.getenv(catalog.api_key_env, "")),
        base_url=_normalize_optional_text(os.getenv(catalog.base_url_env, "")),
        timeout_s=_normalize_optional_float(timeout_text),
    )


def resolve_active_selection(config: Optional[AiAgentConfig]) -> ActiveSelection:
    """
    功能:
        按 UI / env / 默认值的优先级解析当前生效的两段式选择, 并把 base_model_id / thinking_level_id
        校验后转成对象.
    参数:
        config: Optional[AiAgentConfig], UI 持久化配置.
    返回:
        ActiveSelection, 含 base_model / thinking_level / 来源标记.
    """
    base_model_id: Optional[str] = None
    base_model_source = "default"
    if config is not None and config.active_base_model_id is not None:
        base_model_id = config.active_base_model_id
        base_model_source = "ui"
    if base_model_id is None:
        env_base_model = _normalize_base_model_id(os.getenv(ENV_BASE_MODEL, ""))
        if env_base_model is not None:
            base_model_id = env_base_model
            base_model_source = "env"
    if base_model_id is None:
        base_model_id = default_base_model_id()
        base_model_source = "default"
    base_model = get_base_model(base_model_id)

    level_id: Optional[str] = None
    level_source = "default"
    if config is not None and config.active_thinking_level_id is not None:
        level_id = config.active_thinking_level_id
        level_source = "ui"
    if level_id is None:
        env_level = _normalize_thinking_level_id(os.getenv(ENV_THINKING_LEVEL, ""))
        if env_level is not None:
            level_id = env_level
            level_source = "env"
    thinking_level = get_thinking_level(base_model, level_id)
    if thinking_level is None or (
        level_id is not None and thinking_level.id != level_id
    ):
        # level_id 不合法或 base_model 没有思考维, 视为退到 default.
        level_source = "default"

    return ActiveSelection(
        base_model=base_model,
        thinking_level=thinking_level,
        base_model_source=base_model_source,
        thinking_level_source=level_source,
    )


def resolve_provider_credentials(
    provider_id: str,
    config: Optional[AiAgentConfig],
) -> ProviderCredentials:
    """
    功能:
        合并指定 provider 的 UI 凭证, env 凭证和默认值.
    参数:
        provider_id: str, provider ID.
        config: Optional[AiAgentConfig], UI 配置.
    返回:
        ProviderCredentials, 合并后的运行时凭证.
    """
    catalog = get_provider_catalog(provider_id)
    ui_config = config.get_provider_config(provider_id) if config is not None else AiProviderConfig()
    env_config = load_env_provider_config(provider_id)

    api_key = ui_config.api_key or env_config.api_key or ""
    base_url = ui_config.base_url or env_config.base_url or catalog.default_base_url
    timeout_s = ui_config.timeout_s if ui_config.timeout_s is not None else (
        env_config.timeout_s if env_config.timeout_s is not None else 120.0
    )

    return ProviderCredentials(
        provider_id=provider_id,
        provider_label=catalog.label,
        api_key=api_key,
        base_url=base_url,
        timeout_s=timeout_s,
        source={
            "api_key": "ui" if ui_config.api_key is not None else ("env" if env_config.api_key is not None else "none"),
            "base_url": "ui" if ui_config.base_url is not None else ("env" if env_config.base_url is not None else "default"),
            "timeout_s": "ui" if ui_config.timeout_s is not None else (
                "env" if env_config.timeout_s is not None else "default"
            ),
        },
        api_key_env=catalog.api_key_env,
    )


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

        providers_payload = payload.get("providers")
        providers: Dict[str, AiProviderConfig] = {}
        if isinstance(providers_payload, dict) is True:
            for provider_id in PROVIDER_CATALOG.keys():
                provider_config = _provider_from_payload(providers_payload.get(provider_id))
                if len(provider_config.to_persisted_dict()) > 0:
                    providers[provider_id] = provider_config

        return AiAgentConfig(
            active_base_model_id=_normalize_base_model_id(payload.get("active_base_model_id")),
            active_thinking_level_id=_normalize_thinking_level_id(payload.get("active_thinking_level_id")),
            providers=providers,
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
        # 不打 API Key 内容, 避免日志泄露; 仅打字段名变更.
        logger.info("AI 助手配置已保存, 字段: %s", sorted(payload.keys()))
        return self.load()
