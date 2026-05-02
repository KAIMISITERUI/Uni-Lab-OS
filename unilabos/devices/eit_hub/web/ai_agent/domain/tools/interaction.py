# -*- coding: utf-8 -*-
"""
功能:
    与用户交互的工具定义. 当前包含 ask_user_choice, 通过 pending_confirm 弹窗向用户提结构化问题.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .base import GenericToolOutput, ToolCategory, ToolPermission, ToolSpec
from .registry import ToolRegistry

logger = logging.getLogger("EITHubAiAgentInteractionTools")

JsonDict = Dict[str, Any]


class ChoiceOption(BaseModel):
    """
    功能:
        单个备选项的结构化定义.
    参数:
        label: str, 给用户看的简短标题.
        value: str, 提交回 AI 的稳定标识.
        description: Optional[str], 说明文字, 显示在 label 下方.
    """

    model_config = ConfigDict(extra="forbid")

    label: str = Field(description="给用户看的简短标题.")
    value: str = Field(description="提交回 AI 的稳定标识.")
    description: Optional[str] = Field(default=None, description="可选说明文字.")


class AskUserChoiceInput(BaseModel):
    """
    功能:
        ask_user_choice 工具输入.
    参数:
        question: str, 提问主体.
        options: List[ChoiceOption], 备选项列表, 至少 1 项.
        multi: bool, True 多选, False 单选, 默认 False.
        allow_other: bool, 是否允许填 Other 自定义文本, 默认 True.
        allow_skip: bool, 是否允许跳过不选, 默认 False.
        selected: Optional[Any], 用户答案. AI 不要填; 由前端在 edit 阶段注入.
    """

    model_config = ConfigDict(extra="forbid")

    question: str = Field(description="提问主体, 一句话明确告诉用户要选什么.")
    options: List[ChoiceOption] = Field(description="备选项列表, 至少 1 项.")
    multi: bool = Field(default=False, description="True 多选(返回 List[str]), False 单选(返回 str).")
    allow_other: bool = Field(default=True, description="是否允许用户填 Other 自定义答案.")
    allow_skip: bool = Field(default=False, description="是否允许用户跳过不选.")
    selected: Optional[Any] = Field(
        default=None,
        description="用户答案. AI 不要填. 单选: str; 多选: List[str]; 跳过: null 或 []; Other: 任意字符串.",
    )


def _handle_ask_user_choice(model: BaseModel) -> JsonDict:
    """
    功能:
        校验前端在确认时注入的用户答案, 把答案返回给模型.
        AI 调用时不会填 selected, runtime 在 pending_confirm 后等待前端 edit 注入答案.
    参数:
        model: BaseModel, AskUserChoiceInput.
    返回:
        Dict[str, Any], 含 answer 用户答案, is_other 是否自定义答案, skipped 是否跳过.
    """
    args = model.model_dump()
    multi = bool(args.get("multi", False))
    allow_skip = bool(args.get("allow_skip", False))
    options = args.get("options") or []
    option_values = {str(option.get("value")) for option in options}
    selected = args.get("selected")

    if multi is True:
        # 多选: 期望 List[str]; null 或 [] 表示跳过
        if selected is None:
            selected_list: List[str] = []
        elif isinstance(selected, list) is True:
            selected_list = [str(item) for item in selected]
        else:
            raise ValueError("multi=True 时 selected 必须是字符串数组或 null")
        if len(selected_list) == 0 and allow_skip is False:
            raise ValueError("必须至少选择一项, 不允许跳过")
        is_other_list = [value not in option_values for value in selected_list]
        return {
            "answer": selected_list,
            "is_other": is_other_list,
            "skipped": len(selected_list) == 0,
        }

    # 单选: 期望 str; null 表示跳过
    if selected is None or (isinstance(selected, str) is True and selected.strip() == ""):
        if allow_skip is False:
            raise ValueError("必须选择一项, 不允许跳过")
        return {"answer": None, "is_other": False, "skipped": True}
    if isinstance(selected, str) is False:
        raise ValueError("multi=False 时 selected 必须是字符串或 null")
    is_other = selected not in option_values
    return {"answer": selected, "is_other": is_other, "skipped": False}


def register_tools(registry: ToolRegistry) -> None:
    """
    功能:
        注册交互工具.
    参数:
        registry: ToolRegistry, 目标注册表.
    返回:
        None.
    """
    registry.register(
        ToolSpec(
            name="ask_user_choice",
            description=(
                "向用户弹窗提一个选择题, 收到用户答复后再继续. 支持单选/多选/可跳过/可填 Other. "
                "AI 调用时只填 question, options(label+value+可选 description), multi, allow_other, "
                "allow_skip; 不要填 selected. 用户在前端弹窗选择/输入 Other 后, 答案会通过 edit 注入. "
                "适用于 字段缺失需用户决策, 或在化学品库/方法列表的多个候选中要用户挑选."
            ),
            input_model=AskUserChoiceInput,
            output_model=GenericToolOutput,
            permission=ToolPermission.CONTROL,
            category=ToolCategory.INTERACTION,
            handler=_handle_ask_user_choice,
        )
    )
