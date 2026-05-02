# -*- coding: utf-8 -*-
"""
功能:
    Agent Skills 发现, 解析, 加载和受控脚本执行.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("EITHubAiAgentSkills")

JsonDict = Dict[str, Any]


@dataclass(frozen=True)
class SkillRecord:
    """
    功能:
        已发现的 skill 元数据.
    参数:
        name: str, skill 名称.
        description: str, skill 描述.
        skill_path: Path, SKILL.md 绝对路径.
        scope: str, project 或 user.
    """

    name: str
    description: str
    skill_path: Path
    scope: str

    @property
    def skill_dir(self) -> Path:
        """
        功能:
            返回 skill 目录路径.
        返回:
            Path, SKILL.md 所在目录.
        """
        return self.skill_path.parent

    def to_dict(self) -> JsonDict:
        """
        功能:
            转为 API 可返回的字典.
        返回:
            Dict[str, Any], skill 摘要.
        """
        return {
            "name": self.name,
            "description": self.description,
            "path": str(self.skill_path),
            "scope": self.scope,
        }


def _default_ai_agent_root() -> Path:
    """
    功能:
        解析当前 ai_agent 模块根目录.
    返回:
        Path, ai_agent 模块根目录.
    """
    return Path(__file__).resolve().parents[1]


def _parse_frontmatter(text: str) -> JsonDict:
    """
    功能:
        解析 SKILL.md 顶部 YAML 风格 frontmatter 的基础键值.
    参数:
        text: str, SKILL.md 内容.
    返回:
        Dict[str, Any], frontmatter 字典.
    """
    if text.startswith("---") is False:
        return {}
    close_index = text.find("\n---", 3)
    if close_index < 0:
        return {}
    block = text[3:close_index].strip()
    result: JsonDict = {}
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if line == "" or line.startswith("#") is True:
            continue
        if line.find(":") < 0:
            continue
        key, value = line.split(":", 1)
        cleaned_key = key.strip()
        cleaned_value = value.strip().strip("'").strip('"')
        if cleaned_key != "":
            result[cleaned_key] = cleaned_value
    return result


def _body_without_frontmatter(text: str) -> str:
    """
    功能:
        去除 SKILL.md frontmatter 并返回正文.
    参数:
        text: str, SKILL.md 内容.
    返回:
        str, markdown 正文.
    """
    if text.startswith("---") is False:
        return text.strip()
    close_index = text.find("\n---", 3)
    if close_index < 0:
        return text.strip()
    return text[close_index + 4:].strip()


class SkillService:
    """
    功能:
        Agent Skills 服务. 扫描项目级和用户级 skill 目录, 按需加载正文和资源.
    """

    def __init__(self, root_paths: Optional[List[Path]] = None) -> None:
        ai_agent_root = _default_ai_agent_root()
        if root_paths is None:
            root_paths = [
                Path.home() / ".agents" / "skills",
                ai_agent_root / "skills",
            ]
        self._root_paths = root_paths
        self._project_skill_root = (ai_agent_root / "skills").resolve()
        self._skills: Dict[str, SkillRecord] = {}
        self.refresh()

    def refresh(self) -> List[JsonDict]:
        """
        功能:
            重新扫描 skill 目录. 项目级 skill 覆盖用户级同名 skill.
        返回:
            List[Dict[str, Any]], 已发现 skill 摘要.
        """
        discovered: Dict[str, SkillRecord] = {}
        for root in self._root_paths:
            scope = "project" if root.resolve() == self._project_skill_root else "user"
            if root.is_dir() is False:
                continue
            for skill_file in root.glob("*/SKILL.md"):
                try:
                    text = skill_file.read_text(encoding="utf-8")
                except Exception as exc:
                    logger.warning("读取 skill 失败: %s, %s", skill_file, exc)
                    continue
                meta = _parse_frontmatter(text)
                name = str(meta.get("name") or skill_file.parent.name).strip()
                description = str(meta.get("description") or "").strip()
                if description == "":
                    logger.warning("跳过缺少 description 的 skill: %s", skill_file)
                    continue
                record = SkillRecord(
                    name=name,
                    description=description,
                    skill_path=skill_file.resolve(),
                    scope=scope,
                )
                if name in discovered:
                    logger.warning("skill 名称重复, 后发现者覆盖前者: %s", name)
                discovered[name] = record
        self._skills = discovered
        return self.list_skills()

    def list_skills(self) -> List[JsonDict]:
        """
        功能:
            返回当前 skill 目录.
        返回:
            List[Dict[str, Any]], skill 摘要列表.
        """
        return [record.to_dict() for record in self._skills.values()]

    def build_catalog_prompt(self) -> str:
        """
        功能:
            构造用于 system prompt 的 skill catalog.
        返回:
            str, 精简 skill 目录.
        """
        lines: List[str] = []
        for record in self._skills.values():
            lines.append(f"- {record.name}: {record.description}")
        return "\n".join(lines)

    def get(self, name: str) -> SkillRecord:
        """
        功能:
            按名称获取 skill.
        参数:
            name: str, skill 名称.
        返回:
            SkillRecord, skill 记录.
        """
        if name not in self._skills:
            raise KeyError(f"未找到 skill: {name}")
        return self._skills[name]

    def load_skill(self, name: str) -> JsonDict:
        """
        功能:
            加载指定 skill 的完整说明和资源清单.
        参数:
            name: str, skill 名称.
        返回:
            Dict[str, Any], skill 正文和资源信息.
        """
        record = self.get(name)
        text = record.skill_path.read_text(encoding="utf-8")
        body = _body_without_frontmatter(text)
        return {
            **record.to_dict(),
            "content": body,
            "resources": self._list_relative_files(record, "references"),
            "scripts": self._list_relative_files(record, "scripts"),
        }

    def read_resource(self, name: str, resource_path: str, max_chars: int = 20000) -> JsonDict:
        """
        功能:
            读取 skill references/assets 中的资源文件.
        参数:
            name: str, skill 名称.
            resource_path: str, 相对 skill 目录的资源路径.
            max_chars: int, 最大返回字符数.
        返回:
            Dict[str, Any], 资源内容.
        """
        record = self.get(name)
        target = self._resolve_inside_skill(record, resource_path)
        if target.is_file() is False:
            raise FileNotFoundError(f"skill 资源不存在: {resource_path}")
        text = target.read_text(encoding="utf-8", errors="replace")
        truncated = len(text) > max_chars
        if truncated is True:
            text = text[:max_chars]
        return {
            "skill": name,
            "path": resource_path,
            "content": text,
            "truncated": truncated,
        }

    def run_script(self, name: str, script_path: str, args: Optional[JsonDict] = None, timeout_s: float = 30.0) -> JsonDict:
        """
        功能:
            执行 skill scripts 目录下的 Python 脚本. 调用方必须先完成人工确认.
        参数:
            name: str, skill 名称.
            script_path: str, 相对 skill 目录的脚本路径.
            args: Optional[Dict[str, Any]], 通过 stdin 传入脚本的 JSON 参数.
            timeout_s: float, 超时秒.
        返回:
            Dict[str, Any], 脚本执行结果.
        """
        record = self.get(name)
        target = self._resolve_inside_skill(record, script_path)
        scripts_root = (record.skill_dir / "scripts").resolve()
        try:
            target.relative_to(scripts_root)
        except ValueError as exc:
            raise ValueError("只能执行 skill scripts 目录下的脚本") from exc
        if target.is_file() is False:
            raise FileNotFoundError(f"skill 脚本不存在: {script_path}")
        if target.suffix.lower() != ".py":
            raise ValueError("当前仅允许执行 Python skill 脚本")
        payload = json.dumps(args or {}, ensure_ascii=False)
        completed = subprocess.run(
            [sys.executable, str(target)],
            input=payload,
            text=True,
            capture_output=True,
            timeout=timeout_s,
            cwd=str(record.skill_dir),
            check=False,
        )
        return {
            "skill": name,
            "script": script_path,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }

    def _resolve_inside_skill(self, record: SkillRecord, relative_path: str) -> Path:
        """
        功能:
            解析相对路径并确保目标仍在 skill 目录内.
        参数:
            record: SkillRecord, skill 记录.
            relative_path: str, 相对路径.
        返回:
            Path, 解析后的绝对路径.
        """
        target = (record.skill_dir / relative_path).resolve()
        root = record.skill_dir.resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError("skill 资源路径不能越过 skill 目录") from exc
        return target

    def _list_relative_files(self, record: SkillRecord, folder: str) -> List[str]:
        """
        功能:
            列出 skill 下指定目录的相对文件路径.
        参数:
            record: SkillRecord, skill 记录.
            folder: str, 子目录名称.
        返回:
            List[str], 相对路径列表.
        """
        root = record.skill_dir / folder
        if root.is_dir() is False:
            return []
        files: List[str] = []
        for item in root.rglob("*"):
            if item.is_file() is True:
                files.append(str(item.relative_to(record.skill_dir)).replace("\\", "/"))
        return files
