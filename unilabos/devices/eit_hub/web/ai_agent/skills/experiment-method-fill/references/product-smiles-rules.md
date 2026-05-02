# 目标产物 SMILES 推断指引

数据分析中"目标产物"的 SMILES 由模型推断. 默认当量 1, 名称按反应类型, 预期 RT 默认空.

## 推断流程

1. 从用户描述识别反应类型(关键词命中). 若无法识别 -> 直接问用户.
2. 找到反应物 SMILES(应已通过 search_chemical 校验, 取返回值的 smiles 字段).
3. 按下表的"产物结构改写规则"推出每行实验对应的产物 SMILES.
4. 把 (实验编号区间, 反应类型, 反应物 SMILES, 推断产物 SMILES, 名称, 当量) 在阶段 B 预览表格中一并显示给用户.

## 反应类型与产物结构改写

| 反应类型 | 关键词命中 | 产物结构改写规则 | 产物名称 |
|---|---|---|---|
| 酯化 | 酯化, esterification | 羧酸 R-COOH + 醇 R'-OH -> R-C(=O)O-R' (失水) | 酯化产物 |
| 酰胺缩合 | 酰胺, 缩合, amide coupling, HATU, EDC | 羧酸 R-COOH + 胺 R'-NH2 -> R-C(=O)NH-R' | 缩合产物 |
| Suzuki 偶联 | Suzuki, 硼酸 + 卤代芳烃 | Ar-X + Ar'-B(OH)2 -> Ar-Ar' (X = Br/I/Cl 替换为 Ar') | Suzuki 产物 |
| Buchwald 胺化 | Buchwald, 胺化, C-N | Ar-X + HN(R)R' -> Ar-N(R)R' | Buchwald 产物 |
| Sonogashira | Sonogashira, 炔 | Ar-X + HC≡C-R -> Ar-C≡C-R | Sonogashira 产物 |
| Negishi | Negishi, 锌 | Ar-X + R-ZnX -> Ar-R | Negishi 产物 |
| Heck | Heck | Ar-X + CH2=CHR -> Ar-CH=CHR | Heck 产物 |
| 还原胺化 | 还原胺化, reductive amination | R-CHO + R'-NH2 + 还原剂 -> R-CH2-NH-R' | 还原胺化产物 |
| Wittig | Wittig, 内鎓盐 | R-CHO + Ph3P=CHR' -> R-CH=CH-R' | Wittig 产物 |
| Click 反应 | 点击, click, CuAAC | 叠氮 + 末端炔 -> 1,4-二取代三氮唑 | Click 产物 |
| SN2 取代 | 取代, SN2 | R-X + Nu^- -> R-Nu | 取代产物 |
| 还原 | 还原, NaBH4, LiAlH4 | R-C=O -> R-CH-OH; R-CN -> R-CH2-NH2 | 还原产物 |
| 氧化 | 氧化, MnO2, IBX | R-CH2OH -> R-CHO; R-CH(OH)R' -> R-C(=O)R' | 氧化产物 |
| 卤化 | 溴代, NBS, 氯代 | Ar-H -> Ar-Br/Ar-Cl(选择性参考催化剂) | 卤化产物 |

未列出的反应类型 -> 不要硬猜, 直接问用户产物结构.

## 输出形式 (阶段 B 预览表)

```
| 实验编号 | 反应类型 | 反应物 1 SMILES | 反应物 2 SMILES | 产物 SMILES | 产物名称 | 当量 |
|---|---|---|---|---|---|---|
| 1-12 | Suzuki 偶联 | Brc1ccccc1 | OB(O)c1ccccc1 | c1ccc(-c2ccccc2)cc1 | Suzuki 产物 | 1 |
```

不要为每行单独问用户 SMILES, 整体 payload 在阶段 B 由用户一次性确认.

## 写入 payload 时

- gc_ms_yield.products 按试剂表实验区间分段, 每段一项.
- applicable_experiments 用编号串, 例如 "1-12", "1,2,3,4,5,6". 留空表示全部实验.
- expected_rt 默认空, 用户后续可手动补.
