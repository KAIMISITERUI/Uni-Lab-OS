# EIT Hub AI Agent 开发教程

本文档面向需要扩展 `eit_hub.web.ai_agent` 的开发者, 说明如何新增工具, 理解长期记忆, 创建和导入知识库, 以及设计和导入 skills.

当前 AI Agent 的核心边界如下:

- `core/runtime.py`: Agent 对外运行时入口, 负责 SSE, 工具路由, 人工确认, 记忆持久化.
- `domain/tools/`: 工具定义目录, 每个领域一个模块.
- `domain/memory.py`: 长期记忆 CRUD 和回合记忆提取.
- `domain/knowledge.py`: 知识库摄取和检索.
- `domain/skills.py`: skills 发现, 解析, 加载, 资源读取和脚本执行.
- `infra/model_provider.py`: 模型 provider 抽象, 当前实现保留 DeepSeek 接入.

## 1. 如何给 Agent 增加新的工具

### 1.1 工具运行模型

所有工具都必须注册为 `ToolSpec`, 由 `ToolRegistry` 统一管理. Agent 不直接扫描函数, 只认识注册表里的工具.

`ToolSpec` 的固定字段如下:

- `name`: 工具名, 全局唯一.
- `description`: 给模型和前端看的中文说明.
- `input_model`: Pydantic 输入模型, 用于校验模型生成的参数.
- `output_model`: Pydantic 输出模型.
- `permission`: `read` 或 `control`.
- `category`: 工具领域分类.
- `handler`: 真正执行业务动作的函数.

权限非常关键:

- `ToolPermission.READ`: 只读工具, runtime 会自动执行.
- `ToolPermission.CONTROL`: 控制类工具, runtime 会先写入 pending tool message 和 `human_reviews`, 前端确认后才执行.

因此, 新增设备控制, 合成工站动作, AGV 移动, 机械臂动作, 物料转移等工具时, 必须使用 `ToolPermission.CONTROL`. 不要在 prompt 或 handler 外层自己做人工确认, 统一交给 runtime.

### 1.2 选择工具文件

优先把工具放进已有领域模块:

- `domain/tools/maintenance.py`: 运维和系统管理.
- `domain/tools/chemical.py`: 化学品, 安全, 库存.
- `domain/tools/agv.py`: AGV 状态, 导航, 搬运.
- `domain/tools/device.py`: 设备状态和设备操作.
- `domain/tools/synthesis.py`: 合成工站, 合成任务, 方案执行.
- `domain/tools/knowledge.py`: 知识库访问.
- `domain/tools/skill.py`: skills 加载和资源访问.

如果确实需要新增领域, 要同步修改:

1. `domain/tools/base.py` 中的 `ToolCategory`.
2. 新建 `domain/tools/<domain>.py`.
3. 在 `domain/tools/__init__.py` import 新模块并调用 `register_tools(registry)`.

### 1.3 新增 read 工具示例

下面以新增一个 AGV 只读工具为例. 这个工具只读取缓存, 不触发设备 IO 或运动, 所以权限是 `READ`.

```python
# eit_hub/web/ai_agent/domain/tools/agv.py

class GetAgvBatteryInput(BaseModel):
    """
    功能:
        AGV 电量查询输入.
    参数:
        include_station: bool, 是否同时返回当前位置.
    """

    model_config = ConfigDict(extra="forbid")

    include_station: bool = Field(default=False, description="是否同时返回当前位置.")


def _handle_get_agv_battery(model: BaseModel) -> JsonDict:
    """
    功能:
        从 AGV 状态缓存读取电量, 不触发底层设备 IO.
    参数:
        model: BaseModel, GetAgvBatteryInput.
    返回:
        Dict[str, Any], AGV 电量信息.
    """
    from ....deps import get_agv_status_cache

    args = model.model_dump()
    cache = get_agv_status_cache()
    result: JsonDict = {
        "battery": cache.get("battery", 5.0),
    }
    if args.get("include_station") is True:
        result["station"] = cache.get("station", 5.0)
    return result
```

然后在同一个文件的 `register_tools(registry)` 中注册:

```python
registry.register(
    ToolSpec(
        name="get_agv_battery",
        description="读取 AGV 当前电量, 可选返回当前位置.",
        input_model=GetAgvBatteryInput,
        output_model=GenericToolOutput,
        permission=ToolPermission.READ,
        category=ToolCategory.AGV,
        handler=_handle_get_agv_battery,
    )
)
```

### 1.4 新增 control 工具示例

下面以新增一个 AGV 移动工具为例. 这个工具会触发实际运动, 所以必须是 `CONTROL`.

```python
class MoveAgvToStationInput(BaseModel):
    """
    功能:
        AGV 移动到目标站点的输入.
    参数:
        station: str, 目标站点名称.
        reason: str, 本次移动原因, 用于确认卡片和审计.
    """

    model_config = ConfigDict(extra="forbid")

    station: str = Field(description="目标站点名称.")
    reason: str = Field(description="本次移动原因.")


def _handle_move_agv_to_station(model: BaseModel) -> JsonDict:
    """
    功能:
        执行 AGV 移动命令. 该函数只会在用户确认后被 runtime 调用.
    参数:
        model: BaseModel, MoveAgvToStationInput.
    返回:
        Dict[str, Any], 调度结果.
    """
    args = model.model_dump()
    station = str(args.get("station") or "").strip()
    if station == "":
        raise ValueError("目标站点不能为空")

    # 在这里调用真实 AGV 调度服务.
    return {
        "accepted": True,
        "station": station,
        "reason": args.get("reason"),
    }
```

注册时使用 `ToolPermission.CONTROL`:

```python
registry.register(
    ToolSpec(
        name="move_agv_to_station",
        description="控制 AGV 移动到指定站点. 这是控制类操作, 必须由用户确认后执行.",
        input_model=MoveAgvToStationInput,
        output_model=GenericToolOutput,
        permission=ToolPermission.CONTROL,
        category=ToolCategory.AGV,
        handler=_handle_move_agv_to_station,
    )
)
```

模型调用该工具后, runtime 的行为是:

1. 解析工具参数.
2. 发现工具权限是 `control`.
3. 写入一条状态为 `pending` 的 tool message.
4. 写入 `human_reviews` 审计记录.
5. 通过 SSE 返回 `pending_confirm` 事件.
6. 用户在前端选择 `approve`, `reject`, 或 `edit`.
7. `approve` 和 `edit` 后执行 handler.
8. `reject` 后把拒绝原因作为工具结果写回模型上下文, 让模型重新规划.

### 1.5 工具开发原则

- handler 只做业务调用, 不处理 prompt, session, SSE, memory.
- 输入参数必须由 Pydantic model 表达, 并设置 `ConfigDict(extra="forbid")`.
- 工具名使用小写加下划线, 例如 `get_agv_status`.
- `description` 要明确说明动作边界, 尤其是 control 工具.
- 只读工具不能产生设备动作, 文件写入, 状态变更或任务提交.
- 控制工具不要自己绕过确认流程, runtime 会统一处理.
- 工具结果必须是 JSON 可序列化对象, 推荐返回 `dict`.
- 工具内部错误直接抛异常, runtime 会记录 `tool_events` 并把错误写回工具消息.

### 1.6 验证工具

列出当前工具:

```powershell
& C:\ProgramData\miniforge3\envs\unilab\python.exe -c "from eit_hub.web.ai_agent.domain.tools import build_tool_registry; registry = build_tool_registry(); [print(spec.name, spec.permission.value, spec.category.value) for spec in registry.list()]"
```

运行现有回归测试:

```powershell
& C:\ProgramData\miniforge3\envs\unilab\python.exe -m pytest eit_hub\tests\test_ai_agent_refactor.py -q
```

启动后也可以通过管理接口查看:

```text
GET /api/ai-agent/tools
```

## 2. 长期记忆是如何管理的

### 2.1 长期记忆和消息历史的区别

消息历史是当前会话的逐条对话记录, 用于还原聊天上下文. 长期记忆是跨会话保存的结构化事实, 偏好, 约束或经验, 用于让 Agent 在未来回合中记得重要信息.

当前长期记忆由 `domain/memory.py` 的 `AgentMemoryService` 管理, 存储在 SQLite 的 `agent_memories` 表中.

表字段包括:

- `id`: 记忆 ID.
- `session_id`: 来源会话 ID.
- `user_id`: 用户 ID.
- `category`: 记忆分类.
- `content`: 记忆正文.
- `metadata_json`: 附加元数据.
- `created_at`: 创建时间.
- `updated_at`: 更新时间.
- `last_accessed_at`: 最近访问时间, 当前预留.

工具执行和人工确认不是长期记忆, 它们分别写入:

- `tool_events`: 工具调用审计.
- `human_reviews`: 控制工具人工确认审计.

### 2.2 记忆何时写入

每轮对话结束时, runtime 会调用:

```python
self._memory_service.persist_turn_memory(
    session_id=session_id,
    user_id=user_id,
    user_text=last_user_text,
    assistant_text=last_assistant_text,
)
```

当前实现采用保守策略: 只保存用户明确要求记住的信息. `persist_turn_memory()` 会检查用户输入中是否包含这些标记:

- `记住`
- `请记住`
- `以后`
- `长期`
- `偏好`

命中后会写入一条 `category="user_preference"` 的记忆, metadata 中记录来源和助手回答预览.

这意味着普通聊天, 工具结果, 设备状态不会自动进入长期记忆. 这样可以避免把临时状态误保存成长期事实.

### 2.3 记忆如何进入模型上下文

每次模型调用前, runtime 会构造 system prompt. `_build_system_prompt()` 会读取:

```python
memories = self._memory_service.list_memories(user_id="default", limit=10)
```

然后以精简列表注入到 `长期记忆` 区域. 因此, 长期记忆不是整库塞入 prompt, 而是取当前用户最近的少量记忆.

### 2.4 手动管理记忆

Python 中写入一条记忆:

```python
from eit_hub.web.ai_agent.domain.memory import AgentMemoryService

service = AgentMemoryService()
service.add_memory(
    content="用户偏好实验方案输出为表格加步骤清单.",
    category="user_preference",
    session_id="manual",
    user_id="default",
    metadata={"source": "manual"},
)
```

查询记忆:

```python
items = service.list_memories(keyword="表格", user_id="default", limit=20)
```

删除记忆:

```python
service.delete_memory(memory_id=1)
```

HTTP 管理接口:

```text
GET /api/ai-agent/memories?keyword=表格&category=user_preference&limit=20
DELETE /api/ai-agent/memories/{memory_id}
```

### 2.5 什么时候应该写入长期记忆

适合写入:

- 用户长期偏好, 例如输出格式, 语言习惯, 审批偏好.
- 实验约束, 例如某项目禁止使用某类溶剂.
- 设备经验, 例如某设备在特定参数下容易失败.
- 失败教训, 例如某流程需要先预热再进样.
- 稳定事实, 例如某项目的目标材料体系.

不适合写入:

- 当前一次性设备状态.
- 某次工具返回的临时数值.
- 没有用户确认的模型推断.
- 敏感信息, 除非业务明确允许保存.

如果后续要增强自动记忆提取, 修改点是 `AgentMemoryService.persist_turn_memory()`. 推荐仍保持保守原则: 只有明确长期有效的信息才写入.

## 3. 知识库应该如何创建和导入

### 3.1 知识库职责

知识库负责保存可检索文档, 例如 SOP, 设备手册, 项目文档, 实验历史摘要. Agent 不能直接把整库塞入 prompt, 只能通过工具 `query_knowledge_base` 检索.

当前实现位于 `domain/knowledge.py`:

- 向量库: Qdrant 本地持久化.
- 默认 collection: `eit_hub_knowledge`.
- 默认存储路径: `AI_AGENT_DB_PATH.parent / "knowledge_qdrant"`.
- 默认向量维度: `384`.
- embedding: 本地确定性特征哈希, 不依赖外部 embedding API.
- chunk: 默认每块 `1200` 字符, overlap `200` 字符.

### 3.2 准备知识源

建议按来源类型整理目录:

```text
knowledge_sources/
├── sop/
│   ├── synthesis_station_startup.md
│   └── solvent_handling.md
├── manuals/
│   ├── agv_manual.pdf
│   └── balance_manual.pdf
├── project_docs/
│   └── perovskite_project_notes.md
└── experiment_history/
    └── 2026-04-summary.md
```

当前轻量读取器会直接读取这些文本类型:

- `.md`
- `.txt`
- `.py`
- `.json`
- `.yml`
- `.yaml`
- `.csv`
- `.log`

其他类型会尝试使用 LlamaIndex `SimpleDirectoryReader`, 例如 PDF 或 doc 类文件. 如果某类文件读取失败, 优先把原文转换成 `.md` 或 `.txt`, 再导入.

### 3.3 通过 Python 导入

```python
from eit_hub.web.ai_agent.domain.knowledge import KnowledgeService

service = KnowledgeService()
result = service.ingest_path(
    path_text=r"D:\Uni-Lab-OS\unilabos\devices\knowledge_sources\sop",
)
print(result)
```

导入到自定义 collection:

```python
result = service.ingest_path(
    path_text=r"D:\Uni-Lab-OS\unilabos\devices\knowledge_sources\manuals",
    collection_name="device_manuals",
)
```

### 3.4 通过 HTTP 导入

```text
POST /api/ai-agent/knowledge/ingest
Content-Type: application/json

{
  "path": "D:\\Uni-Lab-OS\\unilabos\\devices\\knowledge_sources\\sop",
  "collection": null
}
```

返回示例:

```json
{
  "collection": "eit_hub_knowledge",
  "source": "D:\\Uni-Lab-OS\\unilabos\\devices\\knowledge_sources\\sop",
  "chunks": 18
}
```

### 3.5 检索知识库

Python 检索:

```python
result = service.search(
    query="合成工站启动前需要检查什么?",
    limit=5,
)
```

HTTP 检索:

```text
GET /api/ai-agent/knowledge/search?query=合成工站启动前需要检查什么&limit=5
```

Agent 内部检索:

```text
query_knowledge_base
```

模型只会看到检索返回的 chunks, 每条结果包含:

- `score`: 相似度分数.
- `source_path`: 来源文件.
- `chunk_index`: chunk 序号.
- `text`: chunk 文本.

回答涉及知识库内容时, 应该引用 `source_path` 或说明来源, 方便追溯.

### 3.6 知识库维护建议

- SOP 和设备手册优先导入结构清晰的 Markdown.
- 一个文档只表达一个主题, 文件名要能看出来源.
- 实验历史不要直接导入所有原始日志, 优先导入人工或程序生成的摘要.
- 重要安全规范应该同时进入知识库和相关 skill 的 references, 知识库负责事实检索, skill 负责流程执行方式.
- 文档更新后重新调用 `ingest_path()`, 相同 `source_path + chunk_index` 会生成稳定 point ID 并覆盖旧内容.

## 4. Skills 应该如何设计和导入

### 4.1 Skills 的作用

工具解决的是"能做什么动作", 知识库解决的是"查什么事实", skills 解决的是"遇到某类任务时应该如何思考和执行".

适合做成 skill 的内容:

- 实验方案生成规范.
- 合成工站操作流程.
- AGV 转运流程.
- 化学安全检查流程.
- 某类项目的固定实验设计模板.
- 需要按需读取的领域 references.
- 需要人工确认后执行的白名单脚本.

不适合放进 skill 的内容:

- 会频繁变动的设备实时状态.
- 大量原始 SOP 全文.
- 一次性聊天结论.
- 需要直接被模型随时检索的大型资料库. 这类内容应进入知识库.

### 4.2 Skills 放在哪里

项目级 skills 放在:

```text
eit_hub/web/ai_agent/skills/
```

用户级 skills 放在:

```text
~/.agents/skills/
```

`SkillService` 默认扫描顺序是:

1. `~/.agents/skills`
2. `eit_hub/web/ai_agent/skills`

如果同名, 项目级 skill 会覆盖用户级 skill.

当前项目级 skills:

- `agv-transfer`
- `chemical-safety-check`
- `experiment-plan-generation`
- `synthesis-station-control`

### 4.3 Skill 目录结构

推荐结构:

```text
skill-name/
├── SKILL.md
├── references/
│   └── domain-guide.md
├── scripts/
│   └── validate_plan.py
└── assets/
    └── template.json
```

只有 `SKILL.md` 是必需的. 其他目录按需创建.

- `references/`: 供 Agent 按需读取的详细规范, 表结构, 模板说明.
- `scripts/`: 可执行 Python 脚本. 当前 runtime 只允许执行 `scripts/` 下的 `.py` 文件.
- `assets/`: 模板, 示例文件, 静态资源. 可通过 `read_skill_resource` 读取.

### 4.4 SKILL.md 写法

`SKILL.md` 必须包含 frontmatter:

```markdown
---
name: agv-transfer
description: Use when planning AGV material transfer, station-to-station movement, arm or gripper actions, or AGV status diagnostics in EIT Hub.
---

# AGV Transfer

## Workflow

1. Check current AGV status with `get_agv_status`.
2. Confirm source station, target station, payload, and slot constraints.
3. For movement or gripper actions, use control tools and wait for user confirmation.
4. After execution, summarize status, risk, and next step.
```

frontmatter 原则:

- `name` 必须和目录名一致.
- `description` 是触发入口, 要写清楚什么任务应该使用这个 skill.
- description 不要只写"AGV skill", 要写具体场景.
- 当前解析器只依赖基础 `name` 和 `description`, 不要把关键触发条件藏在正文里.

正文原则:

- 只写执行该任务必要的流程.
- 不要把大型 SOP 全文塞进 `SKILL.md`.
- 长内容放到 `references/`, 并在正文中说明何时读取.
- 对脆弱流程给出明确步骤, 对开放任务给出判断原则.
- 控制设备前必须说明需要调用 control 工具并等待人工确认.

### 4.5 渐进式加载机制

runtime 每轮只把 skill catalog 注入 system prompt:

```text
- skill-name: description
```

模型需要某个 skill 时, 会调用:

- `list_skills`: 列出可用 skills.
- `load_skill`: 加载 `SKILL.md` 正文和资源清单.
- `read_skill_resource`: 读取 `references/` 或 `assets/` 下的具体文件.
- `run_skill_script`: 执行 `scripts/` 下的 Python 脚本.

其中 `run_skill_script` 是 `control` 工具, 必须进入人工确认. 这保证脚本不会被模型静默执行.

### 4.6 新增一个 skill

假设要新增一个 `uv-vis-analysis` skill:

```text
eit_hub/web/ai_agent/skills/uv-vis-analysis/
├── SKILL.md
└── references/
    └── peak-rules.md
```

`SKILL.md`:

```markdown
---
name: uv-vis-analysis
description: Use when generating or reviewing UV-Vis analysis workflows, absorbance peak interpretation, baseline checks, dilution planning, or report structure for EIT Hub experiments.
---

# UV-Vis Analysis

## Workflow

1. Clarify sample, solvent, wavelength range, dilution factor, and blank.
2. Check whether the task needs historical methods or instrument SOP. If yes, query the knowledge base.
3. For peak interpretation rules, read `references/peak-rules.md`.
4. Return a concise method, expected outputs, and risk notes.
```

`references/peak-rules.md`:

```markdown
# Peak Rules

- Check baseline drift before comparing peak intensity.
- Compare peaks only when solvent, cuvette path length, and dilution factor are known.
- Flag saturated absorbance values before drawing conclusions.
```

刷新 skills:

```text
GET /api/ai-agent/skills?refresh=true
```

也可以用 Python 验证:

```powershell
& C:\ProgramData\miniforge3\envs\unilab\python.exe -c "from eit_hub.web.ai_agent.domain.skills import SkillService; service = SkillService(); [print(item['name'], item['path']) for item in service.list_skills()]"
```

### 4.7 Skill 脚本设计

只有在需要确定性校验, 格式转换, 参数计算, 或反复执行同一逻辑时, 才添加 `scripts/`.

脚本规则:

- 放在 `skill-name/scripts/`.
- 当前只支持 `.py`.
- 参数通过 stdin 传入 JSON.
- 输出写到 stdout.
- 不要直接控制设备, 除非该脚本本身就是经过人工确认的控制动作.
- 脚本执行会走 `run_skill_script`, 即 control 工具, 前端必须确认.

脚本示例:

```python
# scripts/validate_plan.py

import json
import sys


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    steps = payload.get("steps") or []
    issues = []
    if isinstance(steps, list) is False:
        issues.append("steps 必须是列表")
    print(json.dumps({"ok": len(issues) == 0, "issues": issues}, ensure_ascii=False))


if __name__ == "__main__":
    main()
```

### 4.8 Skill 和知识库如何分工

一个实用判断:

- 信息需要被检索, 来源很多, 内容较大: 放知识库.
- 信息是流程, 策略, 操作顺序, 输出规范: 放 skill.
- 信息是可执行能力: 放工具.
- 信息是跨会话偏好或经验: 放长期记忆.

例如:

- 合成工站 SOP 全文: 知识库.
- 合成工站执行前检查流程: `synthesis-station-control` skill.
- 查询合成工站当前状态: read 工具.
- 启动合成任务: control 工具.
- 用户偏好"方案要先给风险表": 长期记忆.

## 最小开发闭环

每次扩展 AI Agent 后, 建议按这个顺序验证:

1. 新增或修改代码.
2. 用 `build_tool_registry()` 或 `SkillService()` 做本地发现检查.
3. 运行回归测试.
4. 通过管理接口查看工具, memories, skills 或 knowledge.
5. 用一次真实前端对话验证 SSE, 工具调用, 人工确认和最终回答.

常用命令:

```powershell
& C:\ProgramData\miniforge3\envs\unilab\python.exe -m compileall eit_hub\web\ai_agent
& C:\ProgramData\miniforge3\envs\unilab\python.exe -m pytest eit_hub\tests\test_ai_agent_refactor.py -q
```

