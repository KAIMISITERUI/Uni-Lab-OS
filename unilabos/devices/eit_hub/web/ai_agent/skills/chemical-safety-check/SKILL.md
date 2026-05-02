---
name: chemical-safety-check
description: Use when checking reagent hazards, compatibility, storage constraints, PPE, waste handling, or safety notes before laboratory automation.
---

# 化学安全检查

功能:
    在实验方案, 上料, 转运或反应执行前检查化学安全风险.

步骤:
1. 先查询化学品库, 获取 CAS, 名称, 物态, 危险等级和 GHS 信息.
2. 对缺失的化学品信息, 明确提示需要补充或录入.
3. 检查挥发性, 腐蚀性, 易燃性, 毒性, 水氧敏感性和废液分类.
4. 检查自动化设备是否适合处理该物质, 包括泵, 阀, 管路, 容器和通风条件.
5. 对高风险物质, 在方案中加入人工复核节点.

输出要求:
- 使用表格列出风险项, 依据, 建议.
- 不用模糊措辞替代事实.
- 没有数据时说明没有数据, 不给出伪安全结论.
