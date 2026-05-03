---
name: experiment-method-fill
description: Use when the user wants to fill an EIT Hub synthesis task editor from natural language, including experiment settings, reagent table, GC-MS yield analysis, then run resource check, optionally edit the charging table, and print reagent labels and the charging table.
---

# 实验方法自动化填写

功能:
    把用户的自然语言转换成完整反应模板 payload, 写入网页表格让用户检查修改, 然后串接 上传任务 / 物料核算 / 上料表确认 / 试剂标签和上料表打印 全流程. 关键约束在 references 中, 必须先读再填.

## 必读引用

1. `references/field-spec.md`: 25 项参数 + GC 产率配置的中文名, 取值范围, 默认值, 单位换算和必查库标注. **生成 payload 前必读**.
2. `references/product-smiles-rules.md`: 反应类型 -> 产物结构推断指引. 写入数据分析前必读.
3. `references/workflow.md`: 各阶段问询脚本和兜底分支, 含 ask_user_choice 调用范例.

通过 `read_skill_resource` 读取上述文件, 不要凭记忆作业.

## 核心交互原则

**所有需要用户做选择的地方一律用 `ask_user_choice` 工具弹窗**, 不要在对话里写选择题文字. 用户已明确给出且符合规则的字段直接采用, 不要重复弹窗确认. ask_user_choice 支持 单选 / 多选 / 跳过 / Other 自定义, options 必须是 `[{label, value, description?}]` 结构.

**最终方案预览改为在网页表格上预览**, 不要在对话框 echo 完整表格让用户口头同意. 流程:
1. AI 收集完所有字段 → 调 `save_reaction_template` 写入 Excel → 网页表格自动刷新.
2. AI 提示用户在网页里检查/修改, **特别提醒"修改后需点击网页保存按钮才会同步到磁盘"**.
3. 用户在对话回 "确认上传" / "OK" 等明确同意词 → AI 调 `submit_reaction_template`(不带 template) 上传磁盘当前版本.

## 流程总览

阶段 A: 解析与校验

1. 调 `read_reaction_template` 看当前界面状态, 避免覆盖用户已填项.
2. 解析用户需求, 缺失字段优先用 `ask_user_choice` 弹窗询问, 不要在对话里手写选择题. 默认值表里的字段允许直接用默认值, 不必每个都问.
3. 试剂表: 如果用户已明确实验数且属于 12/24/36/48, 直接采用该行数, 不要再弹实验数量选择. 只有实验数缺失, 模糊或不在允许值中时, 才用 `ask_user_choice` 单选询问实验数. 一般反应体系都需要反应溶剂, 反应溶剂应作为试剂表中的一项填写. 如果用户没有说明反应溶剂, 必须用 `ask_user_choice` 提醒并询问是否添加, 不要把反应溶剂填到稀释液字段. 如果反应溶剂需要写入但现有试剂列已满, 必须在 headers 末尾自动追加一组 `试剂`, `试剂量`, 并给每一行 rows 同步追加溶剂名和用量. 不要输出列满后要求用户自行补表的提示.
4. 化学品中文名(内标, 稀释液, 闪滤液, 试剂表每行 reagent)必须先调 `search_chemical(keyword=...)` 查库. 稀释液特指反应结束后加入的液体, 不是反应溶剂:
   - 命中多条 -> 用 `ask_user_choice` 让用户从匹配项中选(options 是 `[{label: 中文名, value: 中文名, description: CAS号+SMILES}]`).
   - 0 命中 -> `ask_user_choice` 询问处理方式: 跳过该试剂 / 让我换名字 / 我去化学品库新增, 不要硬填.
5. 分析仪器: 用户明确说 GC 或 GC-MS 时直接映射为 `GC_MS`, 明确说 UPLC 或 UPLC-QTOF 时直接映射为 `UPLC_QTOF`, 明确说 HPLC 时直接映射为 `HPLC`; 已明确且映射唯一时不要再弹分析仪器多选. 只有分析仪器缺失或表述模糊时, 才用 `ask_user_choice(multi=True)` 让用户多选 GC_MS / UPLC_QTOF / HPLC. 然后**对每台已选仪器**再调 `list_analysis_methods(instrument=...)` + `ask_user_choice` 让用户从下拉中单选方法名.
6. 数据分析中目标产物 SMILES 由你按 `product-smiles-rules.md` 推断, 当量默认 1, 名称按反应类型(酯化产物/缩合产物/偶联产物等), 预期 RT 默认空.

阶段 B: 写入网页, 用户网页修改

7. 调 `save_reaction_template(template=完整 payload)` (CONTROL). 用户确认后 Excel 写入完成, 网页表格自动刷新.
8. 主动告知用户:
   ```
   方案已写入网页. 请到任务编辑页面检查修改字段.
   注意: 网页表格修改后需点击保存按钮, 否则上传的还是 AI 写入的版本.
   完成后回复 确认上传.
   ```
9. 等用户在对话里回复 "确认上传" / "OK" / "可以" / "上传任务" 等明确同意词. 不要催促, 不要在对话里 echo 表格.

阶段 C: 上传与核算

**硬性分工**: 用户在网页改完模板回复任意确认词("确认上传" / "OK" / "可以" / "上传任务" / "进行物料核算" / "上传并核算" 等同义) 时, 一律调 `submit_reaction_template()` (无参), 禁止再调 `save_reaction_template`. `save_reaction_template` 只在阶段 B 第 7 步首次写入或用户要求"重新覆盖磁盘"时使用, 且必须带完整 `template` payload. 不允许用 `save_reaction_template({})` 来"保留磁盘内容".

10. 用户确认 → 调 `submit_reaction_template()` (CONTROL, 不带 template). 拿到 task_id 后用 `ask_user_choice` 询问是否进行物料核算.
11. 用户同意核算 → 调 `run_resource_check(auto_generate_batch_file=True)` (CONTROL). 上料表自动刷新到网页.

阶段 D: 上料表放置与打印

12. 调 `read_batch_in_template` 拿到上料表. 直接发文字提示用户按上料表位置放置耗材或试剂, 不要问"是否修改", 不要等待额外文字确认:
    ```
    上料表已生成. 请在对应的位置放置好相应的耗材或试剂.
    ```
13. 立即重新调 `read_batch_in_template` 拿最新 rows, 判断是否有**试剂行**:
    - 对每行的 content 调 `search_chemical(keyword=content)`, 命中即试剂行.
    - 至少 1 行命中 -> 用 `ask_user_choice` 询问是否打印试剂标签, 用户同意 -> 调 `print_reagent_labels` (CONTROL).
    - 全部 0 命中(只有耗材) -> 跳过试剂标签步骤, 不调用 print_reagent_labels, 也不询问.
14. 用 `ask_user_choice` 直接弹出是否打印上料表格 -> 用户同意 -> 调 `print_batch_in_table` (CONTROL).

阶段 E: 收尾

15. 输出最终摘要: task_id, 物料核算结论, 试剂标签打印状态(打印 / 跳过(无试剂行) / 跳过(用户拒绝) / 失败), 上料表打印状态. 流程结束.

## 工具清单

只读: `read_reaction_template`, `list_reaction_template_history`, `load_reaction_template_history`, `read_batch_in_template`, `search_chemical`, `list_analysis_methods`, `list_recent_tasks`.

控制(每个都需用户确认): `ask_user_choice`, `save_reaction_template`, `submit_reaction_template`, `run_resource_check`, `save_batch_in_template`, `print_reagent_labels`, `print_batch_in_table`.

## 硬性原则

- 不绕过校验: 化学品名先查后写, 分析方法名先查后选.
- 不替用户决策: 默认值表中没有且用户未明确给出的字段, 必须用 ask_user_choice 询问; 用户已明确且合法的字段直接采用, 不重复确认.
- 不省略网页预览: save_reaction_template 后必须等用户在网页改完并回复确认上传, 才能 submit.
- 不合并控制: save / submit / run_resource_check / save_batch_in_template / print_reagent_labels / print_batch_in_table 各自独立确认.
- 不在对话里写选择题文字: 一律用 ask_user_choice 弹窗.
- 输出统一中文, 标点用英文符号.
