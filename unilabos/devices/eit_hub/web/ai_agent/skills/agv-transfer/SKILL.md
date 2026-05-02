---
name: agv-transfer
description: Use when planning AGV material transfer, station-to-station movement, arm/gripper actions, or AGV status diagnostics in EIT Hub.
---

# AGV 转运

功能:
    处理 AGV 转运, 机械臂抓取, 夹爪状态和站点移动相关请求时使用.

流程:
1. 先调用 AGV 状态工具读取站点, 电量, 导航任务, TCP 位姿, 关节和夹爪状态.
2. 明确来源工站, 目标工站, 物料类型, 托盘或容器编号.
3. 检查 AGV 是否移动中, 电量是否足够, 夹爪是否处于期望状态.
4. 对任何导航, 抓取, 放置, 机械臂 jog 类动作, 必须走 control 工具确认.
5. 如果当前状态与用户描述冲突, 以实时状态为准并要求用户确认.

输出要求:
- 给出转运前检查项.
- 给出动作序列和每一步的前置条件.
- 不隐藏设备异常.
