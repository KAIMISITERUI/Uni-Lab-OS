---
name: synthesis-station-control
description: Use when planning or validating EIT synthesis station operations, resource loading, tray movement, reaction workflow execution, or station state checks.
---

# 合成工站控制

功能:
    处理合成工站自动化控制相关任务时使用. 目标是把自然语言请求转为可审计, 可确认的工站动作.

原则:
1. 先读取任务历史, 工站资源和设备状态, 再规划动作.
2. 任何写入, 移动, 启动, 停止, 上料, 出料操作都必须使用 control 工具并等待人工确认.
3. 不根据记忆推断当前托盘和孔位状态, 必须调用实时工具或要求用户补充.
4. 方案中必须写明涉及的 layout_code, 托盘, 孔位, 物质, 用量和单位.
5. 如果工具参数缺失, 先向用户确认, 不生成半参数控制请求.

输出要求:
- 控制前说明动作影响.
- 控制后提示用户查看工具结果.
- 失败时保留错误原文并给出下一步排查建议.
