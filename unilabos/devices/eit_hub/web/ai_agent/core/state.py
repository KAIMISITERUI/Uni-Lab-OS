# -*- coding: utf-8 -*-
"""
功能:
    LangGraph AgentState 类型定义.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict

JsonDict = Dict[str, Any]


class PendingAction(TypedDict, total=False):
    """
    功能:
        等待人工确认的控制工具动作.
    """

    message_id: int
    tool_call_id: str
    name: str
    arguments: JsonDict
    description: str


class AgentState(TypedDict, total=False):
    """
    功能:
        Agent 主状态. LangGraph 节点只读写这个状态对象.
    """

    session_id: str
    user_id: str
    messages: List[JsonDict]
    selected_tools: List[str]
    loaded_skills: List[JsonDict]
    retrieved_knowledge: List[JsonDict]
    pending_action: Optional[PendingAction]
    last_user_text: str
    assistant_text: str
    next_step: str
