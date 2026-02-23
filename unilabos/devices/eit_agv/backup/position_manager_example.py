# coding:utf-8
"""
功能:
    机械臂坐标管理使用示例
    演示如何使用PositionManager加载和使用YAML配置的坐标数据
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from driver.arm_driver import ArmDriver
from utils.position_manager import PositionManager
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def example_basic_usage():
    """
    功能:
        基础使用示例, 演示如何加载和访问坐标数据
    """
    print("\n" + "="*60)
    print("示例1: 基础使用 - 加载和访问坐标")
    print("="*60)

    # 创建坐标管理器, 自动加载默认配置文件
    pos_mgr = PositionManager()

    # 打印配置摘要
    pos_mgr.print_summary()

    # 获取单个位置点
    tray1_pos = pos_mgr.get_position('tray_pickup', 'tray_1')
    if tray1_pos:
        print(f"\n托盘1位置信息:")
        print(f"  位姿: {tray1_pos.pose}")
        print(f"  速度: {tray1_pos.speed}%")
        print(f"  描述: {tray1_pos.description}")

        # 获取接近位姿
        approach_pose = tray1_pos.get_approach_pose()
        print(f"  接近位姿: {approach_pose}")

    # 获取安全位置
    home_pos = pos_mgr.get_position('safe_positions', 'home')
    if home_pos:
        print(f"\n初始位置信息:")
        print(f"  关节角度: {home_pos.joints}")
        print(f"  描述: {home_pos.description}")

def example_move_to_positions():
    """
    功能:
        运动控制示例, 演示如何使用坐标管理器控制机械臂运动
    """
    print("\n" + "="*60)
    print("示例2: 运动控制 - 使用配置的坐标控制机械臂")
    print("="*60)

    # 创建坐标管理器和机械臂驱动
    pos_mgr = PositionManager()
    arm = ArmDriver()

    # 连接机械臂(实际使用时取消注释)
    if not arm.connect():
        logger.error("机械臂连接失败")
        return
    # arm.power_on()
    # arm.enable()

    # 1. 移动到初始位置
    home_pos = pos_mgr.get_position('safe_positions', 'home')
    if home_pos and home_pos.has_joints():
        print(f"\n移动到初始位置: {home_pos.joints}")
        arm.move_to_joints(
            home_pos.joints,
            v=home_pos.speed,
            a=home_pos.acceleration
        )

    # # 2. 移动到托盘抓取位置(先接近, 再到达)
    # tray1_pos = pos_mgr.get_position('tray_pickup', 'tray_1')
    # if tray1_pos and tray1_pos.has_pose():
    #     # 先移动到接近位置
    #     approach_pose = tray1_pos.get_approach_pose()
    #     if approach_pose:
    #         print(f"\n移动到托盘1接近位置: {approach_pose}")
    #         # arm.move_to_pose(
    #         #     approach_pose,
    #         #     v=tray1_pos.speed,
    #         #     a=tray1_pos.acceleration
    #         # )

    #     # 再移动到抓取位置
    #     print(f"移动到托盘1抓取位置: {tray1_pos.pose}")
    #     # arm.move_to_pose(
    #     #     tray1_pos.pose,
    #     #     v=tray1_pos.speed,
    #     #     a=tray1_pos.acceleration
    #     # )

    # # 3. 移动到工作台放置位置
    # workbench_pos = pos_mgr.get_position('material_place', 'workbench_1')
    # if workbench_pos and workbench_pos.has_pose():
    #     print(f"\n移动到工作台1位置: {workbench_pos.pose}")
    #     # arm.move_to_pose(
    #     #     workbench_pos.pose,
    #     #     v=workbench_pos.speed,
    #     #     a=workbench_pos.acceleration,
    #     #     tool=workbench_pos.tool,
    #     #     wobj=workbench_pos.wobj
    #     # )

    # # 4. 返回待机位置
    # standby_pos = pos_mgr.get_position('safe_positions', 'standby')
    # if standby_pos and standby_pos.has_pose():
    #     print(f"\n返回待机位置: {standby_pos.pose}")
    #     # arm.move_to_pose(
    #     #     standby_pos.pose,
    #     #     v=standby_pos.speed,
    #     #     a=standby_pos.acceleration
    #     # )

    # # 断开连接(实际使用时取消注释)
    # # arm.disable()
    # # arm.power_off()
    # # arm.disconnect()

def example_trajectory_execution():
    """
    功能:
        轨迹执行示例, 演示如何执行多点轨迹
    """
    print("\n" + "="*60)
    print("示例3: 轨迹执行 - 执行多点路径")
    print("="*60)

    # 创建坐标管理器和机械臂驱动
    pos_mgr = PositionManager()
    arm = ArmDriver()

    # 获取托盘搬运轨迹
    traj = pos_mgr.get_trajectory('tray_transfer')
    if traj:
        print(f"\n执行轨迹: {traj.name}")
        print(f"描述: {traj.description}")
        print(f"路径点数量: {len(traj)}")

        # 遍历所有路径点
        for i, waypoint in enumerate(traj.waypoints):
            print(f"\n路径点 {i+1}/{len(traj)}: {waypoint.name}")
            print(f"  位姿: {waypoint.pose}")
            print(f"  速度: {waypoint.speed}%")
            print(f"  融合半径: {waypoint.blend_radius}m")

            # 执行运动(实际使用时取消注释)
            # arm.move_linear(
            #     waypoint.pose,
            #     v=waypoint.speed / 100.0,  # 转换为m/s
            #     a=waypoint.acceleration / 100.0,
            #     r=waypoint.blend_radius
            # )

        # 也可以通过名称访问特定路径点
        pickup_wp = traj.get_waypoint_by_name('pickup')
        if pickup_wp:
            print(f"\n抓取点位姿: {pickup_wp.pose}")

def example_tool_and_workobject():
    """
    功能:
        工具和工件坐标系示例, 演示如何设置和使用坐标系
    """
    print("\n" + "="*60)
    print("示例4: 坐标系管理 - 设置工具和工件坐标系")
    print("="*60)

    # 创建坐标管理器和机械臂驱动
    pos_mgr = PositionManager()
    arm = ArmDriver()

    # 设置工具坐标系
    gripper1 = pos_mgr.get_tool('gripper_1')
    if gripper1:
        print(f"\n设置工具坐标系: {gripper1.name}")
        print(f"  TCP偏移: {gripper1.tcp_offset}")
        print(f"  负载: {gripper1.payload}")
        print(f"  描述: {gripper1.description}")

        # 设置到机械臂(实际使用时取消注释)
        # arm.set_tool(
        #     gripper1.name,
        #     gripper1.tcp_offset,
        #     gripper1.payload,
        #     gripper1.inertia
        # )

    # 设置工件坐标系
    workbench = pos_mgr.get_workobject('workbench')
    if workbench:
        print(f"\n设置工件坐标系: {workbench.name}")
        print(f"  偏移: {workbench.offset}")
        print(f"  描述: {workbench.description}")

        # 设置到机械臂(实际使用时取消注释)
        # arm.set_workobject(workbench.name, workbench.offset)

    # 使用工具和工件坐标系进行运动
    workbench_pos = pos_mgr.get_position('material_place', 'workbench_1')
    if workbench_pos:
        print(f"\n使用工具和工件坐标系移动到工作台:")
        print(f"  工具: {workbench_pos.tool}")
        print(f"  工件坐标系: {workbench_pos.wobj}")
        # arm.move_to_pose(
        #     workbench_pos.pose,
        #     tool=workbench_pos.tool,
        #     wobj=workbench_pos.wobj
        # )

def example_global_params():
    """
    功能:
        全局参数示例, 演示如何使用全局配置参数
    """
    print("\n" + "="*60)
    print("示例5: 全局参数 - 使用全局配置")
    print("="*60)

    # 创建坐标管理器和机械臂驱动
    pos_mgr = PositionManager()
    arm = ArmDriver()

    # 获取全局参数
    default_speed = pos_mgr.get_global_param('default_speed', 30)
    default_acc = pos_mgr.get_global_param('default_acceleration', 30)
    collision_level = pos_mgr.get_global_param('collision_level', 3)
    speed_ratio = pos_mgr.get_global_param('speed_ratio', 100)

    print(f"\n全局参数:")
    print(f"  默认速度: {default_speed}%")
    print(f"  默认加速度: {default_acc}%")
    print(f"  碰撞检测等级: {collision_level}")
    print(f"  全局速度比例: {speed_ratio}%")

    # 应用全局参数(实际使用时取消注释)
    # arm.set_collision_level(collision_level)
    # arm.set_speed_ratio(speed_ratio)

def example_list_all():
    """
    功能:
        列表查询示例, 演示如何查询所有配置项
    """
    print("\n" + "="*60)
    print("示例6: 列表查询 - 查询所有配置项")
    print("="*60)

    pos_mgr = PositionManager()

    # 列出所有位置类别
    print("\n所有位置类别:")
    for category in pos_mgr.list_categories():
        print(f"  - {category}")
        # 列出该类别下的所有位置
        for pos_name in pos_mgr.list_positions(category):
            print(f"    * {pos_name}")

    # 列出所有轨迹
    print("\n所有轨迹:")
    for traj_name in pos_mgr.list_trajectories():
        print(f"  - {traj_name}")

    # 列出所有工具
    print("\n所有工具坐标系:")
    for tool_name in pos_mgr.list_tools():
        print(f"  - {tool_name}")

    # 列出所有工件坐标系
    print("\n所有工件坐标系:")
    for wobj_name in pos_mgr.list_workobjects():
        print(f"  - {wobj_name}")

def example_complete_workflow():
    """
    功能:
        完整工作流示例, 演示托盘搬运的完整流程
    """
    print("\n" + "="*60)
    print("示例7: 完整工作流 - 托盘搬运流程")
    print("="*60)

    # 初始化
    pos_mgr = PositionManager()
    arm = ArmDriver()

    print("\n=== 步骤1: 初始化机械臂 ===")
    # arm.connect()
    # arm.power_on()
    # arm.enable()

    # 设置全局参数
    collision_level = pos_mgr.get_global_param('collision_level', 3)
    speed_ratio = pos_mgr.get_global_param('speed_ratio', 80)
    print(f"设置碰撞检测等级: {collision_level}")
    print(f"设置全局速度比例: {speed_ratio}%")
    # arm.set_collision_level(collision_level)
    # arm.set_speed_ratio(speed_ratio)

    print("\n=== 步骤2: 移动到初始位置 ===")
    home_pos = pos_mgr.get_position('safe_positions', 'home')
    if home_pos:
        print(f"移动到初始位置: {home_pos.joints}")
        # arm.move_to_joints(home_pos.joints, v=home_pos.speed, a=home_pos.acceleration)

    print("\n=== 步骤3: 设置工具坐标系 ===")
    gripper = pos_mgr.get_tool('gripper_1')
    if gripper:
        print(f"设置工具: {gripper.name}")
        # arm.set_tool(gripper.name, gripper.tcp_offset, gripper.payload, gripper.inertia)

    print("\n=== 步骤4: 移动到托盘抓取位置 ===")
    tray_pos = pos_mgr.get_position('tray_pickup', 'tray_1')
    if tray_pos:
        # 先移动到接近位置
        approach_pose = tray_pos.get_approach_pose()
        if approach_pose:
            print(f"移动到接近位置: {approach_pose}")
            # arm.move_to_pose(approach_pose, v=tray_pos.speed, a=tray_pos.acceleration)

        # 直线下降到抓取位置
        print(f"直线下降到抓取位置: {tray_pos.pose}")
        # arm.move_linear(tray_pos.pose, v=0.05, a=0.3)

    print("\n=== 步骤5: 抓取托盘 ===")
    print("关闭夹爪")
    # arm.set_tool_digital_output(1, True)  # 假设IO1控制夹爪

    print("\n=== 步骤6: 提升托盘 ===")
    if tray_pos:
        lift_pose = tray_pos.get_approach_pose()
        print(f"提升到安全高度: {lift_pose}")
        # arm.move_linear(lift_pose, v=0.05, a=0.3)

    print("\n=== 步骤7: 移动到工作台 ===")
    workbench_pos = pos_mgr.get_position('material_place', 'workbench_1')
    if workbench_pos:
        # 先移动到工作台上方
        approach_pose = workbench_pos.get_approach_pose()
        if approach_pose:
            print(f"移动到工作台上方: {approach_pose}")
            # arm.move_to_pose(approach_pose, v=workbench_pos.speed, a=workbench_pos.acceleration)

        # 直线下降到放置位置
        print(f"直线下降到放置位置: {workbench_pos.pose}")
        # arm.move_linear(workbench_pos.pose, v=0.05, a=0.3)

    print("\n=== 步骤8: 放置托盘 ===")
    print("打开夹爪")
    # arm.set_tool_digital_output(1, False)

    print("\n=== 步骤9: 返回待机位置 ===")
    standby_pos = pos_mgr.get_position('safe_positions', 'standby')
    if standby_pos:
        print(f"返回待机位置: {standby_pos.pose}")
        # arm.move_to_pose(standby_pos.pose, v=standby_pos.speed, a=standby_pos.acceleration)

    print("\n=== 步骤10: 关闭机械臂 ===")
    # arm.disable()
    # arm.power_off()
    # arm.disconnect()

    print("\n托盘搬运流程完成!")

if __name__ == '__main__':
    # 运行所有示例
    # example_basic_usage()
    example_move_to_positions()
    # example_trajectory_execution()
    # example_tool_and_workobject()
    # example_global_params()
    # example_list_all()
    # example_complete_workflow()

    # print("\n" + "="*60)
    # print("所有示例运行完成!")
    # print("="*60)
