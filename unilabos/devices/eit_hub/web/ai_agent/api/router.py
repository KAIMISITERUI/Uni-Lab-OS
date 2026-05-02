# -*- coding: utf-8 -*-
"""
功能:
    EIT Hub AI 助手 Web API. 提供会话管理 (列表/详情/重命名/删除) 与
    流式对话 (StreamingResponse, text/event-stream) 端点.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Set

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
from ..infra.config_store import AiAgentConfig
from ..infra.deepseek_client import DEFAULT_BASE_URL, DEFAULT_MODEL, MODEL_OPTIONS
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


def _allowed_model_values() -> Set[str]:
    """
    功能:
        返回 UI 允许保存的 AI 助手模型 ID 集合.
    返回:
        set[str], 支持的模型 ID.
    """
    return {str(item["value"]) for item in MODEL_OPTIONS}


@router.get("/config")
def get_ai_config() -> JsonDict:
    """
    功能:
        返回 AI 助手当前配置 (UI 持久化部分 + env 默认值), API Key 仅返回脱敏预览.
        前端用此响应回显输入框, 不会拿到原始密钥.
    返回:
        Dict[str, Any], 含 ui (UI 设置) / env (环境变量) / effective (最终生效) 三段信息.
    """
    config_store = get_ai_agent_config_store()
    ui_config = config_store.load()

    env_api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    env_base_url = os.getenv("DEEPSEEK_BASE_URL", "").strip()
    env_model = os.getenv("DEEPSEEK_MODEL", "").strip()
    env_timeout_text = os.getenv("DEEPSEEK_TIMEOUT_S", "").strip()
    try:
        env_timeout: Optional[float] = float(env_timeout_text) if env_timeout_text != "" else None
    except ValueError:
        env_timeout = None

    effective_api_key = ui_config.api_key or env_api_key or ""
    effective_base_url = ui_config.base_url or env_base_url or DEFAULT_BASE_URL
    effective_model = ui_config.model or env_model or DEFAULT_MODEL
    effective_timeout = ui_config.timeout_s if ui_config.timeout_s is not None else (
        env_timeout if env_timeout is not None else 120.0
    )

    return {
        "ui": {
            "has_api_key": ui_config.api_key is not None,
            "api_key_preview": _mask_api_key(ui_config.api_key),
            "base_url": ui_config.base_url,
            "model": ui_config.model,
            "timeout_s": ui_config.timeout_s,
        },
        "env": {
            "has_api_key": env_api_key != "",
            "api_key_preview": _mask_api_key(env_api_key) if env_api_key != "" else None,
            "base_url": env_base_url or None,
            "model": env_model or None,
            "timeout_s": env_timeout,
        },
        "effective": {
            "has_api_key": effective_api_key != "",
            "api_key_preview": _mask_api_key(effective_api_key) if effective_api_key != "" else None,
            "base_url": effective_base_url,
            "model": effective_model,
            "timeout_s": effective_timeout,
            "source": {
                "api_key": "ui" if ui_config.api_key is not None else ("env" if env_api_key != "" else "none"),
                "base_url": "ui" if ui_config.base_url is not None else ("env" if env_base_url != "" else "default"),
                "model": "ui" if ui_config.model is not None else ("env" if env_model != "" else "default"),
                "timeout_s": "ui" if ui_config.timeout_s is not None else ("env" if env_timeout is not None else "default"),
            },
        },
        "defaults": {
            "base_url": DEFAULT_BASE_URL,
            "model": DEFAULT_MODEL,
            "timeout_s": 120.0,
        },
        "model_options": [dict(item) for item in MODEL_OPTIONS],
    }


@router.put("/config")
def update_ai_config(payload: AiConfigUpdatePayload = Body(...)) -> JsonDict:
    """
    功能:
        更新 UI 持久化的 AI 助手配置. None 字段保持原值, "" / 0 / 负数表示清除该字段 (回退 env).
    参数:
        payload: AiConfigUpdatePayload, 待更新的字段.
    返回:
        Dict[str, Any], 与 GET /config 同结构, 用于回显.
    """
    config_store = get_ai_agent_config_store()
    current = config_store.load()

    next_api_key = current.api_key
    if payload.api_key is not None:
        cleaned = payload.api_key.strip()
        next_api_key = cleaned if cleaned != "" else None

    next_base_url = current.base_url
    if payload.base_url is not None:
        cleaned = payload.base_url.strip()
        next_base_url = cleaned if cleaned != "" else None

    next_model = current.model
    if payload.model is not None:
        cleaned = payload.model.strip()
        if cleaned != "" and cleaned not in _allowed_model_values():
            raise _json_error("模型必须选择 deepseek-v4-flash 或 deepseek-v4-pro.")
        next_model = cleaned if cleaned != "" else None

    next_timeout = current.timeout_s
    if payload.timeout_s is not None:
        next_timeout = payload.timeout_s if payload.timeout_s > 0 else None

    config_store.save(
        AiAgentConfig(
            api_key=next_api_key,
            base_url=next_base_url,
            model=next_model,
            timeout_s=next_timeout,
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
