# -*- coding: utf-8 -*-
"""
功能:
    LangGraph 状态图定义. 节点名固定表达 AI Agent 全链路阶段.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .state import AgentState

logger = logging.getLogger("EITHubAiAgentGraph")


def _pass_node(state: AgentState) -> AgentState:
    """
    功能:
        轻量节点占位, 实际流式执行由 AgentRuntime 使用同名阶段函数完成.
    参数:
        state: AgentState, 当前状态.
    返回:
        AgentState, 原状态.
    """
    return state


def _route_after_llm(state: AgentState) -> str:
    """
    功能:
        根据 llm_step 后的状态选择工具路由或持久化.
    参数:
        state: AgentState, 当前状态.
    返回:
        str, 下一节点名称.
    """
    next_step = state.get("next_step") or "persist_memory"
    if next_step == "tool_router":
        return "tool_router"
    return "persist_memory"


def _route_after_tool(state: AgentState) -> str:
    """
    功能:
        根据工具路由结果选择人工确认, 继续 LLM 或结束.
    参数:
        state: AgentState, 当前状态.
    返回:
        str, 下一节点名称.
    """
    next_step = state.get("next_step") or "persist_memory"
    if next_step == "human_review":
        return "human_review"
    if next_step == "llm_step":
        return "llm_step"
    return "persist_memory"


def build_agent_graph(checkpointer: Optional[Any] = None):
    """
    功能:
        构造 LangGraph 状态图. 图定义是 runtime 的唯一流程蓝图.
    参数:
        checkpointer: Optional[Any], LangGraph checkpoint saver.
    返回:
        CompiledStateGraph, 已编译图.
    """
    try:
        from langgraph.graph import END, StateGraph
    except ImportError as exc:
        raise RuntimeError("未安装 LangGraph, 请先安装 langgraph 和 langgraph-checkpoint-sqlite") from exc

    graph = StateGraph(AgentState)
    graph.add_node("load_context", _pass_node)
    graph.add_node("load_skills", _pass_node)
    graph.add_node("llm_step", _pass_node)
    graph.add_node("tool_router", _pass_node)
    graph.add_node("human_review", _pass_node)
    graph.add_node("persist_memory", _pass_node)

    graph.set_entry_point("load_context")
    graph.add_edge("load_context", "load_skills")
    graph.add_edge("load_skills", "llm_step")
    graph.add_conditional_edges(
        "llm_step",
        _route_after_llm,
        {
            "tool_router": "tool_router",
            "persist_memory": "persist_memory",
        },
    )
    graph.add_conditional_edges(
        "tool_router",
        _route_after_tool,
        {
            "human_review": "human_review",
            "llm_step": "llm_step",
            "persist_memory": "persist_memory",
        },
    )
    graph.add_edge("human_review", END)
    graph.add_edge("persist_memory", END)
    if checkpointer is None:
        return graph.compile()
    return graph.compile(checkpointer=checkpointer)
