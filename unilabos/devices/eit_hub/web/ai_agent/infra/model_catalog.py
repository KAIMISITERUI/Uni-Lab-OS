# -*- coding: utf-8 -*-
"""
功能:
    集中维护 AI 助手支持的 provider 凭证 schema, 以及下拉里 base_model + thinking_level 的两段式档位.
    base_model 决定 provider 与 API 模型名, thinking_level 决定 reasoning_effort / thinking budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

JsonDict = Dict[str, Any]

PROVIDER_DEEPSEEK = "deepseek"
PROVIDER_OPENAI = "openai"
PROVIDER_ANTHROPIC = "anthropic"
DEFAULT_PROVIDER = PROVIDER_DEEPSEEK


@dataclass(frozen=True)
class ProviderCatalog:
    """
    功能:
        描述单个 provider 的凭证 schema 和默认值.
    参数:
        provider_id: str, provider 唯一 ID.
        label: str, 前端展示名称.
        default_base_url: str, 默认接口前缀.
        api_key_env: str, API Key 环境变量名.
        base_url_env: str, Base URL 环境变量名.
        timeout_env: str, 超时环境变量名.
    """

    provider_id: str
    label: str
    default_base_url: str
    api_key_env: str
    base_url_env: str
    timeout_env: str


@dataclass(frozen=True)
class ThinkingLevel:
    """
    功能:
        一档右按钮档位, 同一个 base_model 可挂多档. 可承载思考深度参数,
        也可承载"切换 API 模型名"的场景 (如 DeepSeek 快速/推理实际是两个不同模型).
    参数:
        id: str, 档位 ID, 在所属 base_model 内唯一.
        label: str, 前端展示文本, 自带语境 (如 "快速" / "深思考" / "思考 high").
        reasoning_effort: Optional[str], OpenAI 兼容协议的 reasoning_effort 字段, None 表不带.
        thinking_budget: Optional[int], Anthropic thinking.budget_tokens, None 表不带.
        model_override: Optional[str], 当该档需要切换实际 API 模型名时填; None 表沿用 base_model.model.
    """

    id: str
    label: str
    reasoning_effort: Optional[str] = None
    thinking_budget: Optional[int] = None
    model_override: Optional[str] = None


@dataclass(frozen=True)
class BaseModel:
    """
    功能:
        下拉左按钮的一项, 携带 provider 归属与默认 API 模型名.
    参数:
        id: str, base_model_id, 全局唯一.
        label: str, 前端展示文本.
        provider_id: str, 归属 provider, 用于解析 api_key/base_url.
        model: str, 下发到 API 的默认 model 字段; thinking_level.model_override 非 None 时被覆盖.
        thinking_levels: List[ThinkingLevel], 右按钮可选档位; 空列表表示该模型无右按钮.
        default_level_id: Optional[str], 无明确选择时的默认档位; thinking_levels 为空时该字段为 None.
    """

    id: str
    label: str
    provider_id: str
    model: str
    thinking_levels: Tuple[ThinkingLevel, ...]
    default_level_id: Optional[str]


PROVIDER_CATALOG: Dict[str, ProviderCatalog] = {
    PROVIDER_DEEPSEEK: ProviderCatalog(
        provider_id=PROVIDER_DEEPSEEK,
        label="DeepSeek",
        default_base_url="https://api.deepseek.com",
        api_key_env="DEEPSEEK_API_KEY",
        base_url_env="DEEPSEEK_BASE_URL",
        timeout_env="DEEPSEEK_TIMEOUT_S",
    ),
    PROVIDER_OPENAI: ProviderCatalog(
        provider_id=PROVIDER_OPENAI,
        label="OpenAI",
        default_base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        base_url_env="OPENAI_BASE_URL",
        timeout_env="OPENAI_TIMEOUT_S",
    ),
    PROVIDER_ANTHROPIC: ProviderCatalog(
        provider_id=PROVIDER_ANTHROPIC,
        label="Anthropic",
        default_base_url="https://api.anthropic.com",
        api_key_env="ANTHROPIC_API_KEY",
        base_url_env="ANTHROPIC_BASE_URL",
        timeout_env="ANTHROPIC_TIMEOUT_S",
    ),
}

PROVIDER_OPTIONS: List[JsonDict] = [
    {"label": catalog.label, "value": catalog.provider_id}
    for catalog in PROVIDER_CATALOG.values()
]


# DeepSeek v4 的两档实际是两个不同模型, 通过 model_override 切换 API 模型名.
_DEEPSEEK_LEVELS: Tuple[ThinkingLevel, ...] = (
    ThinkingLevel(id="fast", label="快速", model_override="deepseek-v4-flash"),
    ThinkingLevel(id="reason", label="推理", model_override="deepseek-v4-pro"),
)

# OpenAI 系列的 4 档思考深度, 通过 reasoning_effort 字段下发到 gateway/上游.
_OPENAI_THINKING_LEVELS: Tuple[ThinkingLevel, ...] = (
    ThinkingLevel(id="low", label="思考 low", reasoning_effort="low"),
    ThinkingLevel(id="medium", label="思考 medium", reasoning_effort="medium"),
    ThinkingLevel(id="high", label="思考 high", reasoning_effort="high"),
    ThinkingLevel(id="xhigh", label="思考 xhigh", reasoning_effort="xhigh"),
)

# Anthropic 系列的 2 档思考深度, 通过 thinking.budget_tokens 字段下发.
_ANTHROPIC_THINKING_LEVELS: Tuple[ThinkingLevel, ...] = (
    ThinkingLevel(id="shallow", label="浅思考", thinking_budget=4000),
    ThinkingLevel(id="deep", label="深思考", thinking_budget=16000),
)


ALL_BASE_MODELS: Tuple[BaseModel, ...] = (
    BaseModel(
        id="deepseek-v4",
        label="DeepSeek v4",
        provider_id=PROVIDER_DEEPSEEK,
        model="deepseek-v4-flash",
        thinking_levels=_DEEPSEEK_LEVELS,
        default_level_id="fast",
    ),
    BaseModel(
        id="gpt-5.4",
        label="GPT-5.4",
        provider_id=PROVIDER_OPENAI,
        model="gpt-5.4",
        thinking_levels=_OPENAI_THINKING_LEVELS,
        default_level_id="medium",
    ),
    BaseModel(
        id="gpt-5.5",
        label="GPT-5.5",
        provider_id=PROVIDER_OPENAI,
        model="gpt-5.5",
        thinking_levels=_OPENAI_THINKING_LEVELS,
        default_level_id="medium",
    ),
    BaseModel(
        id="claude-sonnet",
        label="Claude Sonnet 4.6",
        provider_id=PROVIDER_ANTHROPIC,
        model="claude-sonnet-4-6",
        thinking_levels=_ANTHROPIC_THINKING_LEVELS,
        default_level_id="shallow",
    ),
    BaseModel(
        id="claude-opus",
        label="Claude Opus 4.7",
        provider_id=PROVIDER_ANTHROPIC,
        model="claude-opus-4-7",
        thinking_levels=_ANTHROPIC_THINKING_LEVELS,
        default_level_id="shallow",
    ),
)

BASE_MODEL_INDEX: Dict[str, BaseModel] = {bm.id: bm for bm in ALL_BASE_MODELS}


def get_provider_catalog(provider_id: str) -> ProviderCatalog:
    """
    功能:
        获取 provider 凭证 schema, 不存在时抛出 ValueError.
    参数:
        provider_id: str, provider ID.
    返回:
        ProviderCatalog, provider 凭证 schema.
    """
    if provider_id not in PROVIDER_CATALOG:
        raise ValueError(f"不支持的模型 provider: {provider_id}")
    return PROVIDER_CATALOG[provider_id]


def allowed_provider_values() -> set[str]:
    """
    功能:
        返回支持的 provider ID 集合.
    返回:
        set[str], provider ID 集合.
    """
    return set(PROVIDER_CATALOG.keys())


def get_base_model(base_model_id: str) -> BaseModel:
    """
    功能:
        根据 base_model_id 取出 BaseModel, 不存在时抛 ValueError.
    参数:
        base_model_id: str, base_model ID.
    返回:
        BaseModel, base_model 配置.
    """
    if base_model_id not in BASE_MODEL_INDEX:
        raise ValueError(f"不支持的 base_model: {base_model_id}")
    return BASE_MODEL_INDEX[base_model_id]


def get_thinking_level(base_model: BaseModel, level_id: Optional[str]) -> Optional[ThinkingLevel]:
    """
    功能:
        在指定 base_model 上解析 thinking_level. level_id 为 None / 空 / 非法时退到 default_level_id.
        若 base_model 无思考维 (thinking_levels 为空), 始终返回 None.
    参数:
        base_model: BaseModel, base_model 配置.
        level_id: Optional[str], 待解析的档位 ID.
    返回:
        Optional[ThinkingLevel], 解析后的档位; base_model 无思考维时为 None.
    """
    if len(base_model.thinking_levels) == 0:
        return None
    target_id = level_id if level_id is not None and level_id != "" else base_model.default_level_id
    for level in base_model.thinking_levels:
        if level.id == target_id:
            return level
    # level_id 不在合法集合时, 退到 default_level_id (default 必然存在).
    for level in base_model.thinking_levels:
        if level.id == base_model.default_level_id:
            return level
    return base_model.thinking_levels[0]


def default_base_model_id() -> str:
    """
    功能:
        catalog 兜底默认 base_model_id, 用于 UI 与 env 都未指定时.
    返回:
        str, ALL_BASE_MODELS 第一项的 ID.
    """
    return ALL_BASE_MODELS[0].id


def serialize_base_model(base_model: BaseModel) -> JsonDict:
    """
    功能:
        把 BaseModel 序列化为 GET /config 响应里的 dict.
    参数:
        base_model: BaseModel, base_model 配置.
    返回:
        Dict[str, Any], 含 id/label/provider_id/thinking_levels/default_level_id 的字典.
    """
    return {
        "id": base_model.id,
        "label": base_model.label,
        "provider_id": base_model.provider_id,
        "thinking_levels": [
            {"id": level.id, "label": level.label}
            for level in base_model.thinking_levels
        ],
        "default_level_id": base_model.default_level_id,
    }
