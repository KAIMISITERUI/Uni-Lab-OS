# 全流程 ask_user_choice 调用范例与兜底分支

所有需要用户决策的地方都用 `ask_user_choice` 工具弹窗, 不要在对话里写选择题文字. 本文给出典型场景的调用范例, 严格按这个 schema 写参数.

## 通用调用 schema

```
ask_user_choice(
  question: str,                              # 一句话清晰描述要选什么
  options: List[{label, value, description?}],# 备选项, 至少 1 项
  multi: bool,                                # True 多选, False 单选
  allow_other: bool,                          # 是否允许 Other 自定义
  allow_skip: bool,                           # 是否允许跳过(走默认或不选)
)
```

selected 字段 AI 不要填, 由前端弹窗注入. 工具返回 `{answer, is_other, skipped}`.

## 阶段 A 范例

### A1 实验数

```
ask_user_choice(
  question="本次合成需要做多少个反应?",
  options=[
    {label:"12 个", value:"12"},
    {label:"24 个", value:"24"},
    {label:"36 个", value:"36"},
    {label:"48 个", value:"48"},
  ],
  multi=False, allow_other=False, allow_skip=False,
)
```

### A2 反应类型

```
ask_user_choice(
  question="这次实验的反应类型是?",
  options=[
    {label:"Suzuki 偶联", value:"suzuki", description:"Ar-X + Ar'-B(OH)2 -> Ar-Ar'"},
    {label:"Buchwald 胺化", value:"buchwald", description:"Ar-X + HN(R)R' -> Ar-N(R)R'"},
    {label:"酯化", value:"esterification", description:"R-COOH + R'-OH -> R-COOR'"},
    {label:"酰胺缩合", value:"amide", description:"R-COOH + R'-NH2 -> R-C(=O)NH-R'"},
    {label:"还原胺化", value:"reductive_amination"},
    {label:"Sonogashira", value:"sonogashira"},
  ],
  multi=False, allow_other=True, allow_skip=False,
)
```

(其它反应类型放 product-smiles-rules.md 里, 用户选 Other 自定义时按 description 提示.)

### A3 化学品多条命中

调 `search_chemical(keyword="苯硼酸")` 拿到 N 条候选, 然后:

```
ask_user_choice(
  question='化学品库里 "苯硼酸" 有多条候选, 请选一个:',
  options=[
    {label:"苯硼酸", value:"苯硼酸", description:"CAS 98-80-6, SMILES OB(O)c1ccccc1"},
    {label:"4-甲基苯硼酸", value:"4-甲基苯硼酸", description:"CAS 5720-05-8, ..."},
  ],
  multi=False, allow_other=False, allow_skip=False,
)
```

### A4 化学品 0 命中

```
ask_user_choice(
  question='化学品库未找到 "<name>". 怎么处理?',
  options=[
    {label:"我换一个名字", value:"rename"},
    {label:"跳过该试剂", value:"skip"},
    {label:"我去化学品库新增, 完成后回来继续", value:"add_then_continue"},
  ],
  multi=False, allow_other=False, allow_skip=False,
)
```

收到 rename 后再问 "请告诉我新的名字 (用 ask_user_choice 暂不支持自由文本, 请直接在对话里告诉我)" → 等用户文字回复. 注: 自由文本输入仍走对话, 选择类才走 ask_user_choice.

### A5 内标种类(默认 1,3,5-三异丙基苯, 允许跳过)

```
ask_user_choice(
  question="内标种类? 不选则使用默认 1,3,5-三异丙基苯.",
  options=[
    {label:"使用默认 1,3,5-三异丙基苯", value:"1,3,5-三异丙基苯"},
  ],
  multi=False, allow_other=True, allow_skip=True,
)
```

注意: Other 选项需要用户输入名字后再走 search_chemical 校验.

### A6 分析仪器(多选)

```
ask_user_choice(
  question="本次实验用哪些分析仪器? (可多选)",
  options=[
    {label:"GC-MS", value:"gc_ms"},
    {label:"UPLC-QTOF", value:"uplc_qtof"},
    {label:"HPLC", value:"hplc"},
  ],
  multi=True, allow_other=False, allow_skip=False,
)
```

### A7 分析方法(对每台已选仪器)

调 `list_analysis_methods(instrument="hplc")` 拿到 methods, 然后:

```
ask_user_choice(
  question="HPLC 用哪个分析方法?",
  options=[
    {label: m, value: m} for m in methods
  ],
  multi=False, allow_other=False, allow_skip=False,
)
```

### A8 闪滤实验编号(允许跳过=测全部)

```
ask_user_choice(
  question="闪滤实验编号? 不选表示对全部样品做闪滤.",
  options=[
    {label:"全部样品", value:"all"},
  ],
  multi=False, allow_other=True, allow_skip=True,
)
```

用户选 Other 自定义时, 提示编号必须连续且数量是 6 的倍数.

## 阶段 B 范例 (网页预览, 不再 echo 表格)

调 `save_reaction_template` 后, 直接发文字消息(不要写选择题):

```
方案已写入网页. 请到 任务编辑 页面检查修改字段.
注意: 网页表格修改后需点击保存按钮才会同步到磁盘, 否则上传的还是 AI 写入的版本.
完成后回复 "确认上传".
```

不需要 ask_user_choice, 因为只等文字"确认上传"的自由输入. 收到该关键词后调 `submit_reaction_template`.

## 阶段 C 范例

### C1 是否物料核算

```
ask_user_choice(
  question="任务已上传, task_id=<id>. 是否立即执行物料核算并自动修改上料表?",
  options=[
    {label:"立即执行", value:"yes"},
    {label:"暂不核算, 我先看看任务编辑页", value:"no"},
  ],
  multi=False, allow_other=False, allow_skip=False,
)
```

## 阶段 D 范例 (上料表放置 -> 打印)

### D1 上料表生成后, 提示用户放置耗材或试剂

调 read_batch_in_template 拿到上料表后, 直接发文字提示, **不要问"是否修改"**, **不要等待额外文字确认**:

```
上料表已生成 <N> 行. 请在对应的位置放置好相应的耗材或试剂.
```

提示后立即进入 D2, 不等待用户文字回复.

### D2 试剂行检测 (决定是否要打印试剂标签)

重新调 `read_batch_in_template` 拿最新 rows. 对每行的 content 调 `search_chemical(keyword=content)`:

- 至少 1 行命中化学品库 -> 走 D3 询问是否打印试剂标签.
- 全部 0 命中(只有耗材如磁子/反应器/注射器) -> **跳过 D3**, 不调 print_reagent_labels, 也不询问. 直接进 D4 询问是否打印上料表格.

### D3 打印试剂标签 (有试剂行时才出现)

```
ask_user_choice(
  question="是否打印试剂标签?",
  options=[
    {label:"打印", value:"print"},
    {label:"跳过", value:"skip"},
  ],
  multi=False, allow_other=False, allow_skip=False,
)
```

用户选 print -> 调 print_reagent_labels (CONTROL).

### D4 打印上料表格

不再等待用户文字回复, 直接弹出选择框:

```
ask_user_choice(
  question="是否打印上料表格?",
  options=[
    {label:"打印", value:"print"},
    {label:"跳过", value:"skip"},
  ],
  multi=False, allow_other=False, allow_skip=False,
)
```

用户选 print -> 调 print_batch_in_table (CONTROL).

## 兜底分支

### F1 save_reaction_template 失败

```
保存网页失败, 错误: <message>. 重新写入还是中止?
ask_user_choice(
  question="保存到网页失败. 怎么办?",
  options=[
    {label:"重试 save", value:"retry"},
    {label:"修改方案再试", value:"revise"},
    {label:"中止流程", value:"abort"},
  ],
  multi=False, allow_other=False, allow_skip=False,
)
```

### F2 submit 失败

同 F1 模式: 重试 / 修改后重试 / 中止.

### F3 物料核算缺料

```
ask_user_choice(
  question="物料核算发现短缺试剂 <列表>. 怎么办?",
  options=[
    {label:"我去补料后重试", value:"replenish_retry"},
    {label:"调整试剂量后重新核算", value:"adjust"},
    {label:"暂时忽略, 后续手动处理", value:"ignore"},
  ],
  multi=False, allow_other=False, allow_skip=False,
)
```

### F4 打印失败

```
ask_user_choice(
  question="打印失败, 错误: <message>. 怎么办?",
  options=[
    {label:"重试", value:"retry"},
    {label:"跳过这一步", value:"skip"},
  ],
  multi=False, allow_other=False, allow_skip=False,
)
```

## 触发载入历史方案

用户主动说"用上次的方案改一改":

1. 调 `list_reaction_template_history(query=用户给的关键词)`.
2. `ask_user_choice` 让用户从候选中选 task_id:
   ```
   ask_user_choice(
     question="找到 N 个历史方案, 选一个作为底版:",
     options=[
       {label: f"task_id={item.task_id}", value: str(item.task_id), description: item.task_name + " | " + str(item.experiment_count) + "个实验"}
       for item in items
     ],
     multi=False, allow_other=False, allow_skip=False,
   )
   ```
3. 调 `load_reaction_template_history(task_id=...)` 拿到模板.
4. 把载入结果作为初始 payload, 再走阶段 A 仅询问用户希望修改的字段.
