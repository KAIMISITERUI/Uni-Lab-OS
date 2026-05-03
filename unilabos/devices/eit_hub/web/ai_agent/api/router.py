# -*- coding: utf-8 -*-
"""
功能:
    EIT Hub AI 助手 Web API. 提供会话管理 (列表/详情/重命名/删除) 与
    流式对话 (StreamingResponse, text/event-stream) 端点.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from ..dependencies import (
    get_ai_agent_config_store,
    get_ai_agent_knowledge_service,
    get_ai_agent_memory_service,
    get_ai_agent_runtime,
    get_ai_agent_skill_service,
    get_ai_agent_store,
    get_ai_agent_tool_registry,
)
from ..domain.store import AiAgentStore
from ..infra.config_store import (
    AiAgentConfig,
    AiProviderConfig,
    load_env_provider_config,
    resolve_active_selection,
    resolve_provider_credentials,
)
from ..infra.model_catalog import (
    ALL_BASE_MODELS,
    BASE_MODEL_INDEX,
    PROVIDER_CATALOG,
    PROVIDER_OPTIONS,
    allowed_provider_values,
    get_base_model,
    get_provider_catalog,
    serialize_base_model,
)
from .schemas import (
    AiConfigUpdatePayload,
    CreateSessionResponse,
    KnowledgeIngestPayload,
    RenameSessionPayload,
    SendMessagePayload,
    ToolConfirmPayload,
)

logger = logging.getLogger("EITHubAiAgentRouter")

JsonDict = Dict[str, Any]

router = APIRouter(prefix="/api/ai-agent", tags=["ai-agent"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _json_error(message: str, status_code: int = status.HTTP_400_BAD_REQUEST) -> HTTPException:
    """
    功能:
        创建中文错误响应.
    参数:
        message: str, 错误信息.
        status_code: int, HTTP 状态码.
    返回:
        HTTPException, FastAPI 异常.
    """
    return HTTPException(status_code=status_code, detail=message)


def _mask_api_key(api_key: Optional[str]) -> Optional[str]:
    """
    功能:
        把 API Key 脱敏成前 4 后 4 字符, 短于 12 位时仅显示星号长度, 不返回完整密钥.
    参数:
        api_key: Optional[str], 原始密钥.
    返回:
        Optional[str], 脱敏后的预览, 未设置时为 None.
    """
    if api_key is None or api_key == "":
        return None
    text = api_key
    if len(text) <= 8:
        return "*" * len(text)
    return f"{text[:4]}{'*' * (len(text) - 8)}{text[-4:]}"


def _mask_provider_credentials(config: AiProviderConfig) -> JsonDict:
    """
    功能:
        将 provider 凭证转换为可回显结构, API Key 仅返回脱敏预览.
    参数:
        config: AiProviderConfig, provider 凭证 UI 配置.
    返回:
        Dict[str, Any], 可回显配置.
    """
    return {
        "has_api_key": config.api_key is not None,
        "api_key_preview": _mask_api_key(config.api_key),
        "base_url": config.base_url,
        "timeout_s": config.timeout_s,
    }


def _provider_config_payload(provider_id: str, ui_config: AiAgentConfig) -> JsonDict:
    """
    功能:
        构造单个 provider 的凭证 UI/env/effective/defaults 回显结构.
    参数:
        provider_id: str, provider ID.
        ui_config: AiAgentConfig, UI 持久化配置.
    返回:
        Dict[str, Any], provider 凭证回显.
    """
    catalog = get_provider_catalog(provider_id)
    env_config = load_env_provider_config(provider_id)
    effective = resolve_provider_credentials(provider_id, ui_config)
    return {
        "label": catalog.label,
        "ui": _mask_provider_credentials(ui_config.get_provider_config(provider_id)),
        "env": _mask_provider_credentials(env_config),
        "effective": {
            "has_api_key": effective.api_key != "",
            "api_key_preview": _mask_api_key(effective.api_key) if effective.api_key != "" else None,
            "base_url": effective.base_url,
            "timeout_s": effective.timeout_s,
            "source": dict(effective.source),
        },
        "defaults": {
            "base_url": catalog.default_base_url,
            "timeout_s": 120.0,
        },
    }


@router.get("/config")
def get_ai_config() -> JsonDict:
    """
    功能:
        返回 AI 助手当前两段式选择 + 各 provider 凭证回显. API Key 仅返回脱敏预览.
        前端据此渲染下拉选项与设置弹窗, 不会拿到原始密钥.
    返回:
        Dict[str, Any], 含 active_base_model_id / active_thinking_level_id / base_models / providers.
    """
    config_store = get_ai_agent_config_store()
    ui_config = config_store.load()
    selection = resolve_active_selection(ui_config)
    providers = {
        provider_id: _provider_config_payload(provider_id, ui_config)
        for provider_id in PROVIDER_CATALOG.keys()
    }
    return {
        "active_base_model_id": selection.base_model.id,
        "active_thinking_level_id": selection.thinking_level.id if selection.thinking_level is not None else None,
        "active_source": {
            "base_model": selection.base_model_source,
            "thinking_level": selection.thinking_level_source,
        },
        "base_models": [serialize_base_model(bm) for bm in ALL_BASE_MODELS],
        "provider_options": [dict(item) for item in PROVIDER_OPTIONS],
        "providers": providers,
    }


def _normalize_credential_text(value: Optional[str]) -> Optional[str]:
    """
    功能:
        把凭证字段规整为非空字符串或 None, 空白值统一返回 None (表示清除该字段).
    参数:
        value: Optional[str], 原始字符串.
    返回:
        Optional[str], 非空文本或 None.
    """
    if value is None:
        return None
    text = value.strip()
    if text == "":
        return None
    return text


@router.put("/config")
def update_ai_config(payload: AiConfigUpdatePayload = Body(...)) -> JsonDict:
    """
    功能:
        更新 UI 持久化的 AI 助手配置. 缺省字段保持原值, null / "" / 0 / 负数表示清除该字段 (回退 env).
    参数:
        payload: AiConfigUpdatePayload, 待更新的字段, 含 active_base_model_id / active_thinking_level_id / providers.
    返回:
        Dict[str, Any], 与 GET /config 同结构, 用于回显.
    """
    config_store = get_ai_agent_config_store()
    current = config_store.load()

    fields_set = payload.model_fields_set

    # 解析下次的 active_base_model_id (用于校验 thinking_level_id 与新 base_model 的合法性).
    next_base_model_id = current.active_base_model_id
    if "active_base_model_id" in fields_set:
        cleaned = (payload.active_base_model_id or "").strip()
        if cleaned != "" and cleaned not in BASE_MODEL_INDEX:
            allowed = ", ".join(sorted(BASE_MODEL_INDEX.keys()))
            raise _json_error(f"base_model 必须选择: {allowed}.")
        next_base_model_id = cleaned if cleaned != "" else None

    # 解析下次的 active_thinking_level_id, 校验是否在新 base_model 的 thinking_levels 内.
    level_explicitly_set = "active_thinking_level_id" in fields_set
    base_model_changed = (
        "active_base_model_id" in fields_set
        and next_base_model_id != current.active_base_model_id
    )
    if level_explicitly_set is True:
        cleaned = (payload.active_thinking_level_id or "").strip()
        next_level_id = cleaned if cleaned != "" else None
    elif base_model_changed is True:
        # base_model 切换且未显式指定档位时, 清空旧档位让其退到新 base_model 的 default.
        next_level_id = None
    else:
        next_level_id = current.active_thinking_level_id

    if next_level_id is not None:
        # 校验时以"最终生效的 base_model"为准: UI -> env -> default.
        effective_bm_id = next_base_model_id
        if effective_bm_id is None:
            effective_bm_id = resolve_active_selection(
                AiAgentConfig(
                    active_base_model_id=None,
                    active_thinking_level_id=None,
                    providers=current.providers,
                )
            ).base_model.id
        base_model = get_base_model(effective_bm_id)
        valid_ids = {level.id for level in base_model.thinking_levels}
        if len(valid_ids) == 0:
            # 该 base_model 无思考维, level_id 必须清除.
            next_level_id = None
        elif next_level_id not in valid_ids:
            if level_explicitly_set is True:
                allowed = ", ".join(sorted(valid_ids))
                raise _json_error(f"{base_model.label} 的思考档位必须选择: {allowed}.")
            # 不是显式设的, 静默退到默认.
            next_level_id = None

    # 合并 providers 凭证更新.
    provider_configs = dict(current.providers)
    if "providers" in fields_set and payload.providers is not None:
        for provider_id, update in payload.providers.items():
            if provider_id not in allowed_provider_values():
                allowed = ", ".join(sorted(allowed_provider_values()))
                raise _json_error(f"provider 必须选择: {allowed}.")
            update_fields = update.model_fields_set
            base_creds = current.get_provider_config(provider_id)
            next_api_key = base_creds.api_key
            if "api_key" in update_fields:
                next_api_key = _normalize_credential_text(update.api_key)
            next_base_url = base_creds.base_url
            if "base_url" in update_fields:
                next_base_url = _normalize_credential_text(update.base_url)
            next_timeout = base_creds.timeout_s
            if "timeout_s" in update_fields:
                next_timeout = (
                    update.timeout_s
                    if update.timeout_s is not None and update.timeout_s > 0
                    else None
                )
            provider_configs[provider_id] = AiProviderConfig(
                api_key=next_api_key,
                base_url=next_base_url,
                timeout_s=next_timeout,
            )

    config_store.save(
        AiAgentConfig(
            active_base_model_id=next_base_model_id,
            active_thinking_level_id=next_level_id,
            providers=provider_configs,
        )
    )
    return get_ai_config()


@router.post("/sessions", response_model=CreateSessionResponse)
def create_session() -> CreateSessionResponse:
    """
    功能:
        生成一个新的会话 ID. 数据库不会立刻新增行, 直到首条消息发出.
    返回:
        CreateSessionResponse, 含 session_id.
    """
    return CreateSessionResponse(session_id=AiAgentStore.new_session_id())


@router.get("/sessions")
def list_sessions(
    keyword: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> JsonDict:
    """
    功能:
        派生会话列表, 按最近一条消息时间倒序返回.
    参数:
        keyword: str, 标题模糊匹配关键词.
        page: int, 页码.
        page_size: int, 每页条数.
    返回:
        Dict[str, Any], 含 sessions/total/page/page_size.
    """
    store = get_ai_agent_store()
    return store.list_sessions(keyword=keyword, page=page, page_size=page_size)


@router.get("/sessions/{session_id}/messages")
def list_session_messages(session_id: str) -> JsonDict:
    """
    功能:
        返回指定会话的全部消息, 按时间升序.
    参数:
        session_id: str, 会话 ID.
    返回:
        Dict[str, Any], 含 messages 列表与 total.
    """
    store = get_ai_agent_store()
    messages: List[JsonDict] = store.list_messages(session_id)
    return {"messages": messages, "total": len(messages)}


@router.put("/sessions/{session_id}/title")
def rename_session(session_id: str, payload: RenameSessionPayload = Body(...)) -> JsonDict:
    """
    功能:
        修改会话标题, 同步刷新该会话所有消息行的 session_title 冗余字段.
    参数:
        session_id: str, 会话 ID.
        payload: RenameSessionPayload, 含新标题.
    返回:
        Dict[str, Any], 含 affected (受影响行数).
    """
    store = get_ai_agent_store()
    try:
        affected = store.rename_session(session_id, payload.title)
    except KeyError as exc:
        raise _json_error(str(exc), status.HTTP_404_NOT_FOUND) from exc
    except ValueError as exc:
        raise _json_error(str(exc)) from exc
    return {"affected": affected, "title": payload.title.strip()}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str) -> JsonDict:
    """
    功能:
        删除会话的全部消息行.
    参数:
        session_id: str, 会话 ID.
    返回:
        Dict[str, Any], 含 affected (受影响行数).
    """
    store = get_ai_agent_store()
    try:
        affected = store.delete_session(session_id)
    except KeyError as exc:
        raise _json_error(str(exc), status.HTTP_404_NOT_FOUND) from exc
    return {"affected": affected}


@router.get("/tools")
def list_tools() -> JsonDict:
    """
    功能:
        返回 AI Agent 当前注册工具目录, 同时包含 OpenAI-compatible 和 MCP-style 元数据.
    返回:
        Dict[str, Any], 工具列表.
    """
    registry = get_ai_agent_tool_registry()
    items = registry.to_mcp_tools()
    return {"items": items, "total": len(items)}


@router.get("/memories")
def list_memories(
    keyword: str = Query(default=""),
    category: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> JsonDict:
    """
    功能:
        查询 AI Agent 长期记忆.
    参数:
        keyword: str, 内容关键词.
        category: Optional[str], 记忆分类.
        limit: int, 最大条数.
    返回:
        Dict[str, Any], 记忆列表.
    """
    service = get_ai_agent_memory_service()
    items = service.list_memories(keyword=keyword, category=category, limit=limit)
    return {"items": items, "total": len(items)}


@router.delete("/memories/{memory_id}")
def delete_memory(memory_id: int) -> JsonDict:
    """
    功能:
        删除指定长期记忆.
    参数:
        memory_id: int, 记忆 ID.
    返回:
        Dict[str, Any], 删除结果.
    """
    service = get_ai_agent_memory_service()
    try:
        affected = service.delete_memory(memory_id)
    except KeyError as exc:
        raise _json_error(str(exc), status.HTTP_404_NOT_FOUND) from exc
    return {"affected": affected}


@router.get("/skills")
def list_skills(refresh: bool = Query(default=False)) -> JsonDict:
    """
    功能:
        返回 Agent Skills 目录.
    参数:
        refresh: bool, 是否重新扫描 skill 目录.
    返回:
        Dict[str, Any], skill 列表.
    """
    service = get_ai_agent_skill_service()
    items = service.refresh() if refresh is True else service.list_skills()
    return {"items": items, "total": len(items)}


@router.post("/knowledge/ingest")
def ingest_knowledge(payload: KnowledgeIngestPayload = Body(...)) -> JsonDict:
    """
    功能:
        摄取本地文件或目录到知识库.
    参数:
        payload: KnowledgeIngestPayload, 含路径和 collection.
    返回:
        Dict[str, Any], 入库统计.
    """
    service = get_ai_agent_knowledge_service()
    try:
        return service.ingest_path(payload.path, collection_name=payload.collection)
    except Exception as exc:
        logger.exception("知识库摄取失败")
        raise _json_error(str(exc)) from exc


@router.get("/knowledge/search")
def search_knowledge(
    query: str = Query(...),
    limit: int = Query(default=5, ge=1, le=20),
    collection: Optional[str] = Query(default=None),
) -> JsonDict:
    """
    功能:
        检索知识库.
    参数:
        query: str, 检索问题.
        limit: int, 返回条数.
        collection: Optional[str], collection 名称.
    返回:
        Dict[str, Any], 检索结果.
    """
    service = get_ai_agent_knowledge_service()
    try:
        return service.search(query=query, limit=limit, collection_name=collection)
    except Exception as exc:
        logger.exception("知识库检索失败")
        raise _json_error(str(exc)) from exc


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: str,
    payload: SendMessagePayload = Body(...),
) -> StreamingResponse:
    """
    功能:
        提交一条用户消息, 返回 SSE 流式回包. 内部串起 LLM + 工具调用 + HITL 全过程.
    参数:
        session_id: str, 会话 ID.
        payload: SendMessagePayload, 用户消息.
    返回:
        StreamingResponse, 媒体类型 text/event-stream.
    """
    try:
        runtime = get_ai_agent_runtime()
    except ValueError as exc:
        raise _json_error(str(exc), status.HTTP_503_SERVICE_UNAVAILABLE) from exc
    except RuntimeError as exc:
        raise _json_error(str(exc), status.HTTP_503_SERVICE_UNAVAILABLE) from exc

    async def _generate():
        async for event in runtime.stream_user_turn(session_id, payload.content):
            yield event.to_sse_text()

    return StreamingResponse(_generate(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.post("/sessions/{session_id}/tool-confirm")
async def confirm_tool(
    session_id: str,
    payload: ToolConfirmPayload = Body(...),
) -> StreamingResponse:
    """
    功能:
        对挂起的控制类工具进行确认或拒绝, 续接对话的 SSE 流.
    参数:
        session_id: str, 会话 ID.
        payload: ToolConfirmPayload, 含 message_id, action, reject_reason.
    返回:
        StreamingResponse, 媒体类型 text/event-stream.
    """
    if payload.action not in ("approve", "reject", "edit"):
        raise _json_error(f"action 必须是 approve, reject 或 edit, 当前: {payload.action}")

    try:
        runtime = get_ai_agent_runtime()
    except ValueError as exc:
        raise _json_error(str(exc), status.HTTP_503_SERVICE_UNAVAILABLE) from exc
    except RuntimeError as exc:
        raise _json_error(str(exc), status.HTTP_503_SERVICE_UNAVAILABLE) from exc

    async def _generate():
        async for event in runtime.resume_human_review(
            session_id=session_id,
            message_id=payload.message_id,
            action=payload.action,
            reject_reason=payload.reject_reason or "",
            edited_arguments=payload.edited_arguments,
        ):
            yield event.to_sse_text()

    return StreamingResponse(_generate(), media_type="text/event-stream", headers=_SSE_HEADERS)
