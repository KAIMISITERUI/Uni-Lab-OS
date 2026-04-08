# coding:utf-8
"""
功能:
    AGV控制器模块, 封装AGV机械臂的高级控制功能
    提供基于配置文件的坐标管理和运动控制
"""

import logging
import math
import time
import threading
from typing import Dict, List, Optional, Tuple
from ..driver.arm_driver import ArmDriver
from ..driver.agv_driver import AGVDriver, AGVDriverConfig
from ..utils.position_manager import PositionManager
from ..config.agv_config import (
    STATION_POSITIONS,
    AGV_HOST,
    AGV_PORT,
    AGV_PORT_NAVIGATION,
    AGV_TIMEOUT,
    TASK_STATUS_MAP,
    AGV_QUERY_MAX_RETRIES,
    AGV_QUERY_RETRY_DELAY,
    AGV_PP5_CP6_AUTO_CHARGE_INTERVAL_MINUTES,
    AGV_PP5_CP6_AUTO_CHARGE_LOW_BATTERY_PCT,
)
from ..config.arm_config import ENABLE_GRIP_DETECTION
from ..data.shelf_manager import ShelfManager

logger = logging.getLogger(__name__)


class AGVController:
    """
    功能:
        AGV控制器类, 提供机械臂的高级控制接口
        所有动作方法会自动检查并连接机械臂
    """

    def __init__(self, ip=None, port=None, timeout=180000):
        """
        功能:
            初始化AGV控制器
        参数:
            ip: 机械臂IP地址, 默认使用配置文件中的值
            port: 机械臂端口, 默认使用配置文件中的值
            timeout: socket超时时间, 单位毫秒, 默认180000ms(180秒)
        """
        self.arm = ArmDriver(ip, port, timeout)
        self.position_manager = PositionManager()
        self.current_station = None  # 当前所在工站
        self.shelf_manager = ShelfManager()  # 货架物料状态管理器

        logger.info("AGV控制器初始化完成")

    def _ensure_connected(self):
        """
        功能:
            确保机械臂已连接, 如果未连接则自动连接
        返回:
            bool, True表示已连接, False表示连接失败
        """
        if self.arm.is_connected:
            return True

        logger.info("机械臂未连接, 正在自动连接...")
        return self.arm.connect()

    def connect(self):
        """
        功能:
            连接机械臂
        返回:
            bool, True表示连接成功, False表示连接失败
        """
        return self.arm.connect()

    def disconnect(self):
        """
        功能:
            断开机械臂连接
        返回:
            bool, True表示断开成功, False表示断开失败
        """
        return self.arm.disconnect()

    def arm_go_home(self, block=True, home_name=None):
        """
        功能:
            控制机械臂回零位置, 根据当前姿态选择最接近的home坐标或使用指定的home位置
            根据当前Y坐标判断返回路径: Y > 450先回Y轴, Y <= 450先回Z轴
        参数:
            block: 是否阻塞执行, True表示等待运动完成, False表示立即返回
            home_name: 指定的home位置名称, 如"home_1", 如果为None则自动选择最接近的home
        返回:
            阻塞执行时返回任务结束状态, 非阻塞执行时返回任务ID
        """
        # 自动连接机械臂
        if not self._ensure_connected():
            logger.error("机械臂连接失败, 无法执行回零动作")
            return None

        # 获取当前位姿和关节角度
        current_pose = self.arm.get_tcp_pose()
        current_y = current_pose[1]
        current_joints = self.arm.get_joints_position()
        current_joint6 = current_joints[5]  # 第6个关节(索引为5)

        logger.debug(f"当前位姿: {current_pose}")
        logger.debug(f"当前Y坐标: {current_y}mm, 当前关节6: {current_joint6:.4f}")

        # 获取所有safe_positions中的home坐标
        if 'safe_positions' not in self.position_manager.positions:
            logger.error("未找到安全位置配置(safe_positions)")
            return None

        safe_positions = self.position_manager.positions['safe_positions']
        if len(safe_positions) == 0:
            logger.error("安全位置配置为空")
            return None

        # 如果指定了home_name, 直接使用指定的home位置
        if home_name is not None:
            if home_name not in safe_positions:
                logger.error(f"未找到指定的home位置: {home_name}")
                return None
            selected_home_name = home_name
            selected_home_position = safe_positions[home_name]
            logger.debug(f"使用指定的home位置: {selected_home_name}")
        else:
            # 筛选出所有home开头的位置
            home_positions = {name: pos for name, pos in safe_positions.items() if name.startswith('home')}

            if len(home_positions) == 0:
                logger.error("未找到任何home位置配置")
                return None

            # 计算与当前关节6最接近的home坐标
            min_distance = float('inf')
            selected_home_name = None
            selected_home_position = None

            for home_name_iter, home_pos in home_positions.items():
                if not home_pos.has_joints():
                    logger.warning(f"{home_name_iter}缺少关节数据, 跳过")
                    continue

                # 计算关节6的差异(绝对值)
                home_joint6 = home_pos.joints[5]
                distance = abs(current_joint6 - home_joint6)

                logger.debug(f"{home_name_iter}: joint6={home_joint6:.4f}, 关节6差异={distance:.4f}")

                if distance < min_distance:
                    min_distance = distance
                    selected_home_name = home_name_iter
                    selected_home_position = home_pos

            if selected_home_position is None:
                logger.error("未找到合适的home位置")
                return None

            logger.debug(f"选择最接近的home位置: {selected_home_name}, 关节6差异={min_distance:.4f}")

        safe_position = selected_home_position
        speed = safe_position.speed
        acceleration = safe_position.acceleration

        try:
            # 根据当前Y坐标判断返回路径
            if current_y > 450:
                # Y > 450, 机械臂伸出车体, 先将Y轴向安全姿态运动250mm
                logger.debug("Y > 450, 机械臂伸出车体, 先将Y轴向安全姿态运动250mm")

                # 步骤1: Y轴向安全姿态方向移动250mm
                pose_step1 = [
                    current_pose[0],
                    current_pose[1] - 250,  # Y轴向安全姿态方向移动250mm
                    current_pose[2],
                    current_pose[3],
                    current_pose[4],
                    current_pose[5]
                ]
                result = self.arm.move_linear(
                    pose=pose_step1,
                    v=speed * 0.5,
                    a=acceleration,
                    block=block
                )
                logger.debug(f"Y轴向安全姿态运动250mm完成: {result}")
            else:
                # Y <= 450, 车内坐标, 先回Z到home点
                logger.debug("Y <= 450, 车内坐标, 先回Z到home点")

                # 步骤1: 先运动Z到home的Z值
                pose_step1 = [
                    current_pose[0],
                    current_pose[1],
                    safe_position.pose[2],  # 使用home的Z值
                    current_pose[3],
                    current_pose[4],
                    current_pose[5]
                ]
                result = self.arm.move_linear(
                    pose=pose_step1,
                    v=speed,
                    a=acceleration,
                    block=block
                )
                logger.debug(f"Z轴运动到home完成: {result}")

                # 步骤2: 调整姿态到安全姿态 (使用关节运动避免多圈问题)
                current_pose = self.arm.get_tcp_pose()
                target_pose_for_orientation = [
                    current_pose[0] / 1000.0,  # 转换为m
                    current_pose[1] / 1000.0,
                    current_pose[2] / 1000.0,
                    safe_position.pose[3],
                    safe_position.pose[4],
                    safe_position.pose[5]
                ]
                # 使用逆运动学计算目标关节角度
                current_joints = self.arm.get_joints_position()
                target_joints = self.arm.calculate_inverse_kinematics(
                    pose=target_pose_for_orientation,
                    q_near=current_joints  # 使用当前关节角度作为参考, 确保选解合理
                )
                # 使用关节运动 (move_to_joints会自动调整j6角度到合理范围)
                result = self.arm.move_to_joints(
                    joints_list=target_joints,
                    v=speed,
                    a=acceleration,
                    block=block
                )
                logger.debug(f"姿态调整完成(关节运动): {result}")

            # 步骤3: 运动到home位置(只使用关节运动)
            logger.debug(f"运动到home位置: {selected_home_name}")
            result = self.arm.move_to_joints(
                joints_list=safe_position.joints,
                v=speed,
                a=acceleration,
                block=block
            )

            if block:
                logger.debug(f"机械臂回零完成, 结果: {result}")
            else:
                logger.debug(f"机械臂回零指令已发送, 任务ID: {result}")

            return result

        except Exception as e:
            logger.error(f"机械臂回零失败: {e}")
            return None

    def _get_station_name_from_tray(self, tray_name):
        """
        功能:
            根据托盘点位名称推断所属工站名称.

        参数:
            tray_name: 托盘点位名称.

        返回:
            str或None, 匹配到的工站名称, 未匹配时返回None.
        """
        station_id = self._get_station_from_tray(tray_name)
        if station_id is None:
            return None

        station_info = STATION_POSITIONS.get(station_id)
        if station_info is None:
            logger.warning(f"工站ID不存在配置: {station_id}")
            return None

        return station_info["name"]

    def _parse_middle_tray_name(self, tray_name: str) -> Optional[Dict[str, object]]:
        """
        功能:
            解析形如 station_tray_row-col 的托盘点位名称.

        参数:
            tray_name: 托盘点位名称.

        返回:
            Dict[str, object]或None, 成功时返回工站名、排号和列号, 失败时返回None.
        """
        tray_marker = "_tray_"
        if tray_marker not in tray_name:
            return None

        station_name, index_text = tray_name.split(tray_marker, 1)
        if index_text.count("-") != 1:
            return None

        row_text, col_text = index_text.split("-", 1)
        if row_text.isdigit() is False or col_text.isdigit() is False:
            return None

        return {
            "station_name": station_name,
            "row_index": int(row_text),
            "col_index": int(col_text),
        }

    def _is_valid_middle_tray_pose(self, pose: Optional[List[float]]) -> bool:
        """
        功能:
            判断托盘位姿是否满足中间点位计算要求.

        参数:
            pose: 待校验的位姿列表.

        返回:
            bool, True表示位姿合法, False表示不合法.
        """
        if pose is None:
            return False

        if len(pose) != 6:
            return False

        for axis_value in pose:
            if isinstance(axis_value, (int, float)) is False:
                return False

        return True

    def _calculate_shortest_angle_delta(self, start_angle: float, end_angle: float) -> float:
        """
        功能:
            计算两个姿态角之间的最短角度差.

        参数:
            start_angle: 起始角度, 单位rad.
            end_angle: 结束角度, 单位rad.

        返回:
            float, 最短路径角度差, 单位rad.
        """
        angle_delta = end_angle - start_angle
        normalized_delta = (angle_delta + math.pi) % (2 * math.pi) - math.pi

        if normalized_delta == -math.pi and angle_delta > 0:
            return math.pi

        return normalized_delta

    def _interpolate_middle_tray_pose(
        self,
        left_pose: List[float],
        right_pose: List[float],
        ratio: float,
    ) -> List[float]:
        """
        功能:
            根据左右端点位姿插值计算中间托盘位姿.

        参数:
            left_pose: 左端点位姿[x, y, z, rx, ry, rz].
            right_pose: 右端点位姿[x, y, z, rx, ry, rz].
            ratio: 目标点在左右端点之间的比例, 取值范围[0, 1].

        返回:
            List[float], 插值得到的目标位姿.
        """
        new_pose: List[float] = []

        for axis_index in range(3):
            interpolated_value = left_pose[axis_index] + (
                right_pose[axis_index] - left_pose[axis_index]
            ) * ratio
            new_pose.append(float(interpolated_value))

        for axis_index in range(3, 6):
            shortest_delta = self._calculate_shortest_angle_delta(
                left_pose[axis_index],
                right_pose[axis_index],
            )
            interpolated_value = left_pose[axis_index] + shortest_delta * ratio
            new_pose.append(float(interpolated_value))

        return new_pose

    def _collect_station_middle_tray_updates(
        self,
        station_name: str,
    ) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
        """
        功能:
            收集指定工站的中间托盘点位预览结果与跳过信息.

        参数:
            station_name: 工站名称, 如 shelf 或 synthesis_station.

        返回:
            Tuple[List[Dict[str, object]], List[Dict[str, object]]], 第1项为可更新点位列表, 第2项为跳过排信息.
        """
        tray_positions = self.position_manager.get_category("tray_position")
        if tray_positions is None or len(tray_positions) == 0:
            logger.warning("未找到托盘位置配置, 无法计算工站中间点位: %s", station_name)
            return [], [{"row_index": None, "reason": "未找到托盘位置配置"}]

        row_position_map: Dict[int, Dict[int, Dict[str, object]]] = {}
        for tray_name, tray_config in tray_positions.items():
            parsed_result = self._parse_middle_tray_name(tray_name)
            if parsed_result is None:
                continue

            if parsed_result["station_name"] != station_name:
                continue

            row_index = parsed_result["row_index"]
            col_index = parsed_result["col_index"]

            if row_index not in row_position_map:
                row_position_map[row_index] = {}

            row_position_map[row_index][col_index] = {
                "tray_name": tray_name,
                "config": tray_config,
            }

        if len(row_position_map) == 0:
            logger.info("工站 %s 没有符合命名规则的托盘点位", station_name)
            return [], []

        preview_items: List[Dict[str, object]] = []
        skipped_rows: List[Dict[str, object]] = []

        for row_index in sorted(row_position_map.keys()):
            col_position_map = row_position_map[row_index]
            sorted_col_indexes = sorted(col_position_map.keys())

            if len(sorted_col_indexes) < 2:
                skipped_rows.append({
                    "row_index": row_index,
                    "reason": "该排有效端点数量不足2个",
                })
                continue

            left_col = sorted_col_indexes[0]
            right_col = sorted_col_indexes[-1]
            if right_col - left_col < 2:
                skipped_rows.append({
                    "row_index": row_index,
                    "reason": "该排没有中间编号可计算",
                })
                continue

            left_entry = col_position_map[left_col]
            right_entry = col_position_map[right_col]
            left_pose = left_entry["config"].get("pose")
            right_pose = right_entry["config"].get("pose")
            if self._is_valid_middle_tray_pose(left_pose) is False:
                skipped_rows.append({
                    "row_index": row_index,
                    "reason": f"左端点位姿无效: {left_entry['tray_name']}",
                })
                continue
            if self._is_valid_middle_tray_pose(right_pose) is False:
                skipped_rows.append({
                    "row_index": row_index,
                    "reason": f"右端点位姿无效: {right_entry['tray_name']}",
                })
                continue

            span = right_col - left_col
            for target_col in range(left_col + 1, right_col):
                ratio = (target_col - left_col) / span
                target_tray_name = f"{station_name}_tray_{row_index}-{target_col}"
                existing_entry = col_position_map.get(target_col)
                exists = existing_entry is not None
                old_pose = None
                if existing_entry is not None:
                    old_pose = existing_entry["config"].get("pose")

                preview_items.append({
                    "row_index": row_index,
                    "left_tray": left_entry["tray_name"],
                    "right_tray": right_entry["tray_name"],
                    "target_tray": target_tray_name,
                    "target_col": target_col,
                    "ratio": ratio,
                    "exists": exists,
                    "old_pose": old_pose,
                    "new_pose": self._interpolate_middle_tray_pose(left_pose, right_pose, ratio),
                })

        return preview_items, skipped_rows

    def preview_station_middle_tray_updates(self, station_name: str) -> List[Dict[str, object]]:
        """
        功能:
            预览指定工站的中间托盘点位自动计算结果.

        参数:
            station_name: 工站名称, 如 shelf 或 synthesis_station.

        返回:
            List[Dict[str, object]], 中间点位预览结果列表.
        """
        preview_items, skipped_rows = self._collect_station_middle_tray_updates(station_name)
        if len(preview_items) == 0:
            logger.info("工站 %s 没有可自动计算的中间托盘点位", station_name)

        for skipped_row in skipped_rows:
            logger.info(
                "工站 %s 第%s排跳过: %s",
                station_name,
                skipped_row["row_index"],
                skipped_row["reason"],
            )

        return preview_items

    def apply_station_middle_tray_updates(self, station_name: str) -> Dict[str, object]:
        """
        功能:
            将指定工站的中间托盘点位自动计算结果写入配置文件.

        参数:
            station_name: 工站名称, 如 shelf 或 synthesis_station.

        返回:
            Dict[str, object], 包含更新汇总信息.
        """
        preview_items, skipped_rows = self._collect_station_middle_tray_updates(station_name)
        result_summary = {
            "station_name": station_name,
            "updated_count": 0,
            "created_count": 0,
            "skipped_rows": skipped_rows,
            "affected_trays": [],
        }

        if len(preview_items) == 0:
            logger.info("工站 %s 没有需要写入的中间托盘点位", station_name)
            return result_summary

        for preview_item in preview_items:
            target_tray = preview_item["target_tray"]
            new_pose = preview_item["new_pose"]
            if preview_item["exists"] is True:
                self.position_manager.save_tray_position(target_tray, new_pose)
                result_summary["updated_count"] += 1
            else:
                self.position_manager.save_tray_position_from_template(
                    target_tray,
                    new_pose,
                    preview_item["left_tray"],
                )
                result_summary["created_count"] += 1

            result_summary["affected_trays"].append(target_tray)

        logger.info(
            "工站 %s 中间托盘点位写入完成, 更新%d个, 新增%d个",
            station_name,
            result_summary["updated_count"],
            result_summary["created_count"],
        )
        return result_summary

    def _get_tray_position_context(self, tray_name):
        """
        功能:
            获取托盘点位配置和对应工站校准偏移.

        参数:
            tray_name: 托盘点位名称.

        返回:
            tuple, 第1项为点位配置, 第2项为工站偏移字典或None.
        """
        tray_position = self.position_manager.get_position('tray_position', tray_name)
        if tray_position is None:
            logger.error(f"未找到托盘位置配置: tray_position.{tray_name}")
            return None, None

        station_offset = None
        if tray_name.startswith('agv') is False:
            station_name = self._get_station_name_from_tray(tray_name)
            if station_name is None:
                logger.debug(f"托盘 {tray_name} 未匹配到工站偏移配置, 使用原始坐标")
                return tray_position, None

            station_offset = self.position_manager.get_calibration_offset(station_name)
            if station_offset is None:
                logger.debug(f"工站 {station_name} 未配置校准偏移, 使用原始坐标")
            else:
                logger.debug(
                    "托盘 %s 使用工站 %s 偏移: x=%.6f, y=%.6f, z=%.6f, dx=%.6f, dy=%.6f, dz=%.6f",
                    tray_name,
                    station_name,
                    station_offset['x'],
                    station_offset['y'],
                    station_offset['z'],
                    station_offset['dx'],
                    station_offset['dy'],
                    station_offset['dz'],
                )

        return tray_position, station_offset

    def _build_transition_pose(self, tray_position, station_offset=None, transition_z_offset=0):
        """
        功能:
            生成托盘点位对应的过渡位姿.

        参数:
            tray_position: 托盘点位配置对象.
            station_offset: 工站校准偏移, 为None表示不应用偏移.
            transition_z_offset: 过渡位Z轴附加偏移, 单位mm.

        返回:
            list, 过渡位姿[x, y, z, rx, ry, rz].
        """
        grasp_pose = tray_position.pose.copy()
        config_descend_z = tray_position.descend_z if hasattr(tray_position, 'descend_z') else -32
        transition_pose = grasp_pose.copy()
        transition_pose[2] = grasp_pose[2] - config_descend_z

        if station_offset is not None:
            transition_pose[0] += station_offset['x']
            transition_pose[1] += station_offset['y']
            transition_pose[2] += station_offset['z']
            transition_pose[3] += station_offset['dx']
            transition_pose[4] += station_offset['dy']
            transition_pose[5] += station_offset['dz']

        if transition_z_offset != 0:
            transition_pose[2] += transition_z_offset

        return transition_pose

    def _move_to_put_transition_pose(self, tray_position, station_offset=None, transition_z_offset=0, block=True):
        """
        功能:
            复用放托盘前半段动作, 运动到目标点前的过渡位并停住.

        参数:
            tray_position: 托盘点位配置对象.
            station_offset: 工站校准偏移, 为None表示不应用偏移.
            transition_z_offset: 过渡位Z轴附加偏移, 单位mm.
            block: 是否阻塞等待动作完成.

        返回:
            bool, True表示到达过渡位, False表示失败.
        """
        if tray_position is None or tray_position.pose is None:
            logger.error("托盘点位缺少有效pose, 无法运动到过渡位")
            return False

        logger.debug("步骤1: 运动到安全姿态")
        result = self.arm_go_home(block=block)
        logger.debug(f"安全姿态运动完成: {result}")

        logger.debug("步骤2: 运动到过渡点")
        transition_pose = self._build_transition_pose(
            tray_position,
            station_offset=station_offset,
            transition_z_offset=transition_z_offset,
        )
        logger.debug(f"目标过渡点位姿: {transition_pose}")

        current_pose = self.arm.get_tcp_pose()
        target_pose_for_orientation = [
            current_pose[0] / 1000.0,
            current_pose[1] / 1000.0,
            current_pose[2] / 1000.0,
            transition_pose[3],
            transition_pose[4],
            transition_pose[5],
        ]
        current_joints = self.arm.get_joints_position()
        target_joints = self.arm.calculate_inverse_kinematics(
            pose=target_pose_for_orientation,
            q_near=current_joints,
        )
        result = self.arm.move_to_joints(
            joints_list=target_joints,
            v=tray_position.speed,
            a=tray_position.acceleration,
            block=block,
        )
        logger.debug(f"姿态调整完成: {result}")

        if transition_pose[1] < 450:
            result = self.arm.move_linear(
                pose=transition_pose,
                v=tray_position.speed,
                a=tray_position.acceleration,
                block=block,
            )
            logger.debug(f"过渡点运动完成: {result}")
            return True

        current_pose = self.arm.get_tcp_pose()
        intermediate_pose = [
            transition_pose[0],
            400,
            transition_pose[2],
            current_pose[3],
            current_pose[4],
            current_pose[5],
        ]
        result = self.arm.move_linear(
            pose=intermediate_pose,
            v=tray_position.speed,
            a=tray_position.acceleration,
            block=block,
        )
        logger.debug(f"运动到y=400完成: {result}")

        result = self.arm.move_linear(
            pose=transition_pose,
            v=tray_position.speed * 0.2,
            a=tray_position.acceleration,
            block=block,
        )
        logger.debug(f"过渡点运动完成: {result}")
        return True

    def _finish_put_tray_from_current_pose(self, tray_position, lift_z=None, block=True):
        """
        功能:
            从当前位置执行松爪, 提升和回零收尾动作.

        参数:
            tray_position: 托盘点位配置对象.
            lift_z: 提升距离, 为None时使用点位配置.
            block: 是否阻塞等待动作完成.

        返回:
            bool, True表示收尾成功, False表示失败.
        """
        if tray_position is None:
            logger.error("托盘点位配置为空, 无法执行放托盘收尾")
            return False

        logger.debug("步骤4: 松开夹爪")
        self.arm.open_gripper(block=True)
        time.sleep(1)

        if self.arm.is_gripper_opened() is False:
            logger.error("夹爪未松开")
            return False
        logger.debug("夹爪松开成功")

        logger.debug("步骤5: 提升")
        if lift_z is None:
            lift_z = tray_position.lift_z if hasattr(tray_position, 'lift_z') else 0.1
        current_pose = self.arm.get_tcp_pose()
        logger.debug(f"当前位置: {current_pose}, 提升距离: {lift_z}mm")
        lift_pose = [
            current_pose[0],
            current_pose[1],
            current_pose[2] + lift_z,
            current_pose[3],
            current_pose[4],
            current_pose[5],
        ]
        result = self.arm.move_linear(
            pose=lift_pose,
            v=tray_position.speed * 0.5,
            a=tray_position.acceleration,
            block=block,
        )
        logger.debug(f"提升完成: {result}")

        logger.debug("步骤6: 回到home位置")
        result = self.arm_go_home(block=block)
        logger.debug(f"回到home位置完成: {result}")
        return True

    def _build_saved_tray_pose(self, tray_name, current_pose):
        """
        功能:
            将当前TCP位姿转换为配置文件中应保存的托盘位姿.

        参数:
            tray_name: 托盘点位名称.
            current_pose: 当前TCP位姿[x, y, z, rx, ry, rz].

        返回:
            list, 应保存到配置文件的位姿.
        """
        if tray_name.startswith('agv'):
            logger.info(f"AGV点位直接保存当前TCP位姿: {current_pose}")
            return current_pose

        station_name = self._get_station_name_from_tray(tray_name)
        if station_name is None:
            logger.warning(f"托盘 {tray_name} 未匹配到工站, 直接保存当前TCP位姿")
            return current_pose

        station_offset = self.position_manager.get_calibration_offset(station_name)
        if station_offset is None:
            logger.warning(f"工站 {station_name} 未校准, 直接保存当前TCP位姿")
            return current_pose

        pose_to_save = [
            current_pose[0] - station_offset['x'],
            current_pose[1] - station_offset['y'],
            current_pose[2] - station_offset['z'],
            current_pose[3] - station_offset['dx'],
            current_pose[4] - station_offset['dy'],
            current_pose[5] - station_offset['dz'],
        ]
        logger.info(f"工站 {station_name} 点位将保存去偏移后的TCP位姿: {pose_to_save}")
        return pose_to_save

    def pick_tray(self, tray_name, descend_z=None, lift_z=None, transition_z_offset=0, block=True):
        """
        功能:
            通用取托盘逻辑, 按照标准流程抓取托盘
        参数:
            tray_name: 托盘位置名称, 例如"agv_tray_1", 从配置文件tray_position中读取
            descend_z: 下探距离(mm), 为None时从配置文件读取
            lift_z: 提升距离(mm), 为None时从配置文件读取
            transition_z_offset: 过渡点Z值偏移量(mm), 默认为0
            block: 是否阻塞执行, True表示等待完成, False表示立即返回
        返回:
            bool, True表示抓取成功, False表示抓取失败
        """
        # 自动连接机械臂
        if not self._ensure_connected():
            logger.error("机械臂连接失败, 无法执行取托盘动作")
            return False

        # 获取托盘位置配置
        tray_position = self.position_manager.get_position('tray_position', tray_name)
        if tray_position is None:
            logger.error(f"未找到托盘位置配置: tray_position.{tray_name}")
            return False

        # 判断是否需要应用站点偏移量
        station_offset = None
        matched_station = None
        if not tray_name.startswith('agv'):
            # 读取配置文件中的所有站点校准信息
            try:
                import yaml
                with open(self.position_manager.config_file, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)

                if config is not None and 'station_calibration' in config:
                    # 遍历所有站点名称, 检查tray_name是否以某个站点名称开头
                    for station_name in config['station_calibration'].keys():
                        if tray_name.startswith(station_name):
                            matched_station = station_name
                            logger.debug(f"托盘 {tray_name} 匹配到站点 {station_name}, 尝试获取校准偏移量")

                            # 获取该站点的校准偏移量
                            station_offset = self.position_manager.get_calibration_offset(station_name)
                            if station_offset is not None:
                                logger.debug(f"找到站点 {station_name} 的校准偏移量: x={station_offset['x']:.6f}, y={station_offset['y']:.6f}, z={station_offset['z']:.6f}, dx={station_offset['dx']:.6f}, dy={station_offset['dy']:.6f}, dz={station_offset['dz']:.6f}")
                            break

                    if matched_station is None:
                        logger.debug(f"托盘 {tray_name} 未匹配到任何站点校准配置, 使用原始坐标")
            except Exception as e:
                logger.warning(f"读取站点校准配置失败: {e}, 使用原始坐标")

        logger.info(f"开始执行取托盘流程: {tray_name}")

        try:
            # 步骤1: 运动到安全姿态
            logger.debug("步骤1: 运动到安全姿态")
            result = self.arm_go_home(block=block)
            logger.debug(f"安全姿态运动完成: {result}")

            # 步骤2: 张开夹爪
            logger.debug("步骤2: 张开夹爪")
            self.arm.open_gripper(block=True)
            logger.debug("夹爪已张开")

            # 步骤3: 运动到过渡点 (先rx,ry,rz, 然后z, 最后xy且速度减半)
            logger.debug("步骤3: 运动到过渡点")
            # 获取抓取点位姿(配置文件中存储的是抓取点)
            grasp_pose = tray_position.pose.copy()
            # 获取下探距离, 用于计算过渡点
            config_descend_z = tray_position.descend_z if hasattr(tray_position, 'descend_z') else -32
            # 计算过渡点: 过渡点z = 抓取点z - descend_z (descend_z为负值, 所以减去它等于加上绝对值)
            transition_pose = grasp_pose.copy()
            transition_pose[2] = grasp_pose[2] - config_descend_z
            logger.debug(f"抓取点z={grasp_pose[2]:.2f}, descend_z={config_descend_z}, 过渡点z={transition_pose[2]:.2f}")

            # 如果有站点偏移量, 则应用到过渡点位姿
            if station_offset is not None:
                transition_pose[0] += station_offset['x']
                transition_pose[1] += station_offset['y']
                transition_pose[2] += station_offset['z']
                transition_pose[3] += station_offset['dx']
                transition_pose[4] += station_offset['dy']
                transition_pose[5] += station_offset['dz']
                logger.debug(f"应用站点偏移量后的过渡点位姿: {transition_pose}")

            # 应用过渡点Z偏移量(用于物料高度补偿)
            if transition_z_offset != 0:
                transition_pose[2] += transition_z_offset
                logger.debug(f"应用过渡点Z偏移量{transition_z_offset}mm后的过渡点位姿: {transition_pose}")

            # 3.1: 先运动rx,ry,rz到位 (使用关节运动避免多圈问题)
            current_pose = self.arm.get_tcp_pose()
            target_pose_for_orientation = [
                current_pose[0] / 1000.0,  # 转换为m
                current_pose[1] / 1000.0,
                current_pose[2] / 1000.0,
                transition_pose[3],
                transition_pose[4],
                transition_pose[5]
            ]
            # 使用逆运动学计算目标关节角度
            current_joints = self.arm.get_joints_position()
            target_joints = self.arm.calculate_inverse_kinematics(
                pose=target_pose_for_orientation,
                q_near=current_joints  # 使用当前关节角度作为参考, 确保选解合理
            )
            # 使用关节运动 (move_to_joints会自动调整j6角度到合理范围)
            result = self.arm.move_to_joints(
                joints_list=target_joints,
                v=tray_position.speed,
                a=tray_position.acceleration,
                block=block
            )
            logger.debug(f"姿态调整完成(关节运动): {result}")

            # 3.2: 根据目标点Y坐标判断运动策略
            if transition_pose[1] < 450:
                # Y < 450, 在车内, xyz直接同时运动到位
                logger.debug("目标点在车内(Y<450), xyz直接运动到位")
                result = self.arm.move_linear(
                    pose=transition_pose,
                    v=tray_position.speed,
                    a=tray_position.acceleration,
                    block=block
                )
                logger.debug(f"过渡点运动完成: {result}")
            else:
                # Y >= 450, 在车外, 先运动到y=400, 然后y前伸
                logger.debug("目标点在车外(Y>=450), 先运动到y=400")
                current_pose = self.arm.get_tcp_pose()
                intermediate_pose = [
                    transition_pose[0],
                    400,
                    transition_pose[2],
                    current_pose[3],
                    current_pose[4],
                    current_pose[5]
                ]
                result = self.arm.move_linear(
                    pose=intermediate_pose,
                    v=tray_position.speed,
                    a=tray_position.acceleration,
                    block=block
                )
                logger.debug(f"运动到y=450完成: {result}")

                # 然后y前伸到目标点
                logger.debug("y前伸到目标点")
                result = self.arm.move_linear(
                    pose=transition_pose,
                    v=tray_position.speed * 0.2,
                    a=tray_position.acceleration,
                    block=block
                )
                logger.debug(f"过渡点运动完成: {result}")

            # 步骤4: 下探到抓取点位置 (只有Z轴变化)
            logger.debug("步骤4: 下探到抓取点位置")
            # 计算抓取点位姿(应用站点偏移量)
            target_grasp_pose = grasp_pose.copy()
            if station_offset is not None:
                target_grasp_pose[0] += station_offset['x']
                target_grasp_pose[1] += station_offset['y']
                target_grasp_pose[2] += station_offset['z']
                target_grasp_pose[3] += station_offset['dx']
                target_grasp_pose[4] += station_offset['dy']
                target_grasp_pose[5] += station_offset['dz']
            # 如果传入了自定义descend_z, 则使用自定义值计算目标z
            if descend_z is not None:
                current_pose = self.arm.get_tcp_pose()
                target_grasp_pose[2] = current_pose[2] + descend_z
            # 应用物料高度偏移到抓取点(与过渡点保持一致的偏移)
            if transition_z_offset != 0:
                target_grasp_pose[2] += transition_z_offset
                logger.debug(f"应用物料高度偏移{transition_z_offset}mm到抓取点")
            logger.debug(f"目标抓取点位姿: {target_grasp_pose}")
            result = self.arm.move_linear(
                pose=target_grasp_pose,
                v=tray_position.speed * 0.2,
                a=tray_position.acceleration,
                block=block
            )
            logger.debug(f"下探完成: {result}")

            # 步骤5: 夹紧夹爪并检查是否夹紧
            logger.debug("步骤5: 夹紧夹爪")
            self.arm.close_gripper(block=True)

            # 根据配置决定是否进行夹持检测
            if ENABLE_GRIP_DETECTION:
                # 等待夹爪稳定并检查状态
                time.sleep(1)

                if not self.arm.is_gripper_gripped():
                    logger.error("夹爪未夹紧, 可能未夹到托盘")
                    # 张开夹爪并返回失败
                    self.arm.open_gripper(block=True)
                    return False
                logger.debug("夹爪夹紧成功")
            else:
                logger.debug("夹持检测已禁用, 跳过检测")

            # 步骤6: 提升一定距离 (只有Z轴变化)
            logger.debug("步骤6: 提升托盘")
            # 如果未传入lift_z参数, 则从配置文件读取
            if lift_z is None:
                lift_z = tray_position.lift_z if hasattr(tray_position, 'lift_z') else 0.1
            current_pose = self.arm.get_tcp_pose()
            logger.debug(f"当前位姿: {current_pose}, 提升距离: {lift_z}mm")
            lift_pose = [
                current_pose[0],
                current_pose[1],
                current_pose[2] + lift_z,
                current_pose[3],
                current_pose[4],
                current_pose[5]
            ]
            logger.debug(f"目标位姿: {lift_pose}")
            result = self.arm.move_linear(
                pose=lift_pose,
                v=tray_position.speed * 0.25,
                a=tray_position.acceleration,
                block=block
            )
            logger.debug(f"提升完成: {result}")

            # 步骤7: 回到home位置
            logger.debug("步骤7: 回到home位置")
            result = self.arm_go_home(block=block)
            logger.debug(f"回到home位置完成: {result}")

            logger.info(f"取托盘流程完成: {tray_name}")
            return True

        except Exception as e:
            logger.error(f"取托盘流程失败: {e}")
            # 发生异常时张开夹爪
            try:
                self.arm.open_gripper(block=True)
            except Exception:
                pass
            return False

    def calibrate_station(self, block=True):
        """
        功能:
            工站点位校准, 自动查询当前站点并运行内置校准程序, 保存偏移值到配置文件
        参数:
            block: 是否阻塞执行, True表示等待完成, False表示立即返回
        返回:
            dict或None, 成功时返回校准偏移值字典{"x": float, "y": float, "z": float, "dx": float, "dy": float, "dz": float}, 失败时返回None
        """
        # 查询当前站点
        logger.debug("正在查询当前站点...")
        station_info = self.query_current_station()
        if station_info is None:
            logger.error("查询当前站点失败, 无法执行点位校准")
            return None

        station_name = station_info["station_name"]
        logger.debug(f"当前站点: {station_info['station_id']} - {station_name} ({station_info['description']})")

        # 自动连接机械臂
        if not self._ensure_connected():
            logger.error("机械臂连接失败, 无法执行点位校准")
            return None

        # 工站名称与校准程序的映射
        calibration_programs = {
            "shelf": "shelf_calibration.jspf",
            "synthesis_station": "synthesis_station_calibration.jspf",
            "analysis_station": "analysis_station_calibration.jspf"
        }

        # 检查工站名称是否有效
        if station_name not in calibration_programs:
            logger.error(f"无效的工站名称: {station_name}, 支持的工站: {list(calibration_programs.keys())}")
            return None

        program_name = calibration_programs[station_name]
        logger.debug(f"开始执行工站点位校准: {station_name}, 程序: {program_name}")

        try:
            # 运行校准程序
            result = self.arm.run_program(program_name, block=block)
            logger.debug(f"校准程序运行结果: {result}")

            # 等待机械臂运动完成
            logger.debug("等待机械臂运动完成...")
            import time
            max_wait_time = 120  # 最大等待时间120秒
            check_interval = 0.5  # 每0.5秒检查一次
            elapsed_time = 0

            while elapsed_time < max_wait_time:
                if not self.arm.is_moving():
                    # 机械臂停止运动后, 再等待2秒确保变量已更新
                    time.sleep(2)
                    break
                time.sleep(check_interval)
                elapsed_time += check_interval

            if elapsed_time >= max_wait_time:
                logger.warning(f"等待超时({max_wait_time}秒), 机械臂可能仍在运动")
            else:
                logger.debug(f"机械臂运动完成, 耗时: {elapsed_time:.1f}秒")

            # 获取校准偏移值(从系统变量读取, 单位为m)
            logger.debug("正在读取校准偏移值...")
            g_pose_x = self.arm.get_system_value_double("g_pose_x")
            g_pose_y = self.arm.get_system_value_double("g_pose_y")
            g_pose_z = self.arm.get_system_value_double("g_pose_z")
            g_pose_dx = self.arm.get_system_value_double("g_pose_dx")
            g_pose_dy = self.arm.get_system_value_double("g_pose_dy")
            g_pose_dz = self.arm.get_system_value_double("g_pose_dz")

            # 将位置偏移从m转换为mm, 姿态偏移保持rad不变
            calibration_offset = {
                "x": g_pose_x * 1000,  # m转换为mm
                "y": g_pose_y * 1000,  # m转换为mm
                "z": g_pose_z * 1000,  # m转换为mm
                "dx": g_pose_dx,  # rad保持不变
                "dy": g_pose_dy,  # rad保持不变
                "dz": g_pose_dz   # rad保持不变
            }

            logger.debug(f"校准偏移值(mm坐标系): {calibration_offset}")

            # 保存偏移值到配置文件
            self.position_manager.save_calibration_offset(station_name, calibration_offset)
            logger.debug(f"工站 {station_name} 校准完成, 偏移值已保存到配置文件")

            return calibration_offset

        except Exception as e:
            logger.error(f"工站点位校准失败: {e}")
            return None

    def _query_with_retry(self, query_func, query_name, max_retries=None, retry_delay=None):
        """
        功能:
            带重试机制的AGV查询通用方法, 每次重试会创建新的AGVDriver连接
        参数:
            query_func: callable, 接收一个AGVDriver实例作为参数, 返回查询结果
            query_name: str, 查询操作名称, 用于日志输出
            max_retries: int, 最大重试次数, 默认使用配置值AGV_QUERY_MAX_RETRIES
            retry_delay: float, 首次重试延迟秒数, 后续指数退避, 默认使用AGV_QUERY_RETRY_DELAY
        返回:
            查询结果或None, 所有重试均失败时返回None
        """
        if max_retries is None:
            max_retries = AGV_QUERY_MAX_RETRIES
        if retry_delay is None:
            retry_delay = AGV_QUERY_RETRY_DELAY

        for attempt in range(1, max_retries + 1):
            agv_driver = AGVDriver(AGVDriverConfig(
                host=AGV_HOST,
                port=AGV_PORT,
                port_navigation=AGV_PORT_NAVIGATION,
                timeout_s=AGV_TIMEOUT,
                debug_hex=False
            ))

            try:
                agv_driver.connect()
                result = query_func(agv_driver)
                return result
            except Exception as e:
                if attempt < max_retries:
                    # 计算指数退避延迟
                    delay = retry_delay * (2 ** (attempt - 1))
                    logger.warning(
                        "%s第%d次尝试失败: %s, %.1f秒后重试",
                        query_name, attempt, e, delay
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        "%s第%d次尝试失败(已达最大重试次数): %s",
                        query_name, attempt, e
                    )
            finally:
                agv_driver.close()

        return None

    def query_current_station(self):
        """
        功能:
            查询AGV当前所在站点, 带重试机制
        返回:
            dict或None, 成功时返回包含站点信息的字典{"station_id": str, "station_name": str, "description": str}, 失败时返回None
        """

        def _do_query(agv_driver):
            """执行站点查询并映射结果"""
            location_info = agv_driver.query_robot_location()
            current_station_id = location_info.get("current_station", "")
            logger.debug("查询到当前站点ID: %s", current_station_id)

            if current_station_id in STATION_POSITIONS:
                station_info = STATION_POSITIONS[current_station_id]
                result = {
                    "station_id": current_station_id,
                    "station_name": station_info["name"],
                    "description": station_info["description"]
                }
                # 更新当前工站
                self.current_station = current_station_id
                logger.info(
                    "当前站点: %s - %s (%s)",
                    current_station_id, station_info["name"], station_info["description"]
                )
                return result
            else:
                logger.warning("未知的站点ID: %s", current_station_id)
                return {
                    "station_id": current_station_id,
                    "station_name": "未知站点",
                    "description": "未在配置中找到该站点"
                }

        return self._query_with_retry(_do_query, "查询站点")

    def query_battery_status(self, simple=True):
        """
        功能:
            查询AGV电池状态, 带重试机制
        参数:
            simple: True表示只返回电池电量, False返回完整信息, 默认True
        返回:
            dict或None, 成功时返回包含电池状态的字典, 失败时返回None
            - battery_level: 电池电量, 范围[0, 1]
            - battery_temp: 电池温度, 单位℃ (仅完整模式)
            - charging: 是否正在充电 (仅完整模式)
            - 其他字段见AGVDriver.query_battery_status文档
        """

        def _do_query(agv_driver):
            """执行电池状态查询"""
            battery_info = agv_driver.query_battery_status(simple=simple)
            if battery_info.get("ret_code") == 0:
                battery_level = battery_info.get("battery_level")
                if battery_level is not None:
                    logger.info("电池电量: %.1f%%", battery_level * 100)
                    return battery_info
                else:
                    raise ValueError("未获取到电池电量")
            else:
                raise RuntimeError(
                    "查询电池状态返回错误: %s" % battery_info.get("err_msg", "未知错误")
                )

        return self._query_with_retry(_do_query, "查询电池状态")

    def query_nav_task_status(self):
        """
        功能:
            查询AGV当前导航任务状态, 带重试机制, 用于判断AGV是否正在执行导航任务
        参数:
            无
        返回:
            dict或None, 成功时返回包含导航状态的字典, 失败时返回None
            - task_status: int, 状态码(0=NONE, 1=WAITING, 2=RUNNING, 3=SUSPENDED, 4=COMPLETED, 5=FAILED, 6=CANCELED)
            - task_status_name: str, 状态名称
        """

        def _do_query(agv_driver):
            """执行导航状态查询"""
            nav_info = agv_driver.query_agv_nav_status(simple=True)
            if nav_info is None:
                raise RuntimeError("查询导航状态返回空")

            task_status = nav_info.get("task_status")
            task_status_name = TASK_STATUS_MAP.get(task_status, "UNKNOWN")
            logger.debug("当前导航状态: %s(%s)", task_status_name, task_status)
            return {
                "task_status": task_status,
                "task_status_name": task_status_name,
            }

        return self._query_with_retry(_do_query, "查询导航任务状态")

    def navigate_to_station(self, station_id):
        """
        功能:
            控制AGV底盘移动到指定工站
        参数:
            station_id: 工站ID, 例如"LM1", "LM2"等, 从配置文件STATION_POSITIONS中读取
        返回:
            dict或None, 成功时返回导航响应字典, 失败时返回None
        """
        # 验证工站ID是否有效
        if station_id not in STATION_POSITIONS:
            logger.error(f"无效的工站ID: {station_id}, 可用的工站: {list(STATION_POSITIONS.keys())}")
            return None

        station_info = STATION_POSITIONS[station_id]
        logger.info(f"开始移动到工站: {station_id} ({station_info['description']})")

        # 初始化AGV驱动
        agv_driver = AGVDriver(AGVDriverConfig(
            host=AGV_HOST,
            port=AGV_PORT,
            port_navigation=AGV_PORT_NAVIGATION,
            timeout_s=AGV_TIMEOUT,
            debug_hex=False
        ))

        try:
            # 连接到AGV导航端口
            logger.debug("正在连接到AGV导航端口...")
            agv_driver.connect_navigation()
            logger.debug("连接成功")

            # 调用导航函数移动到目标工站
            logger.debug(f"正在导航到目标工站: {station_id}...")
            result = agv_driver.navigate_to_target(target_id=station_id)

            # 检查导航响应
            if result.get("ret_code") == 0:
                logger.debug(f"导航指令发送成功, 响应: {result}")
                # 更新当前工站
                self.current_station = station_id
                logger.debug(f"当前工站已设置为: {station_id}")
                return result
            else:
                logger.error(f"导航指令发送失败, 错误码: {result.get('ret_code')}, 错误信息: {result.get('err_msg', '未知错误')}")
                return None

        except Exception as e:
            logger.error(f"导航过程出错: {e}")
            return None
        finally:
            # 关闭AGV连接
            agv_driver.close()
            logger.debug("AGV连接已关闭")

    def safe_send_navigate_command(self, station_id):
        """
        功能:
            安全发送AGV导航命令到指定工站, 发送前先执行机械臂回零操作(固定回home_1), 发送完命令立即返回
        参数:
            station_id: 工站ID, 例如"LM1", "LM2"等, 从配置文件STATION_POSITIONS中读取
        返回:
            dict或None, 成功时返回导航命令响应字典, 失败时返回None
        """
        logger.info(f"开始安全发送导航命令到工站: {station_id}")

        # 步骤1: 机械臂回零到home_1
        logger.info("步骤1: 执行机械臂回零操作(home_1)")
        home_result = self.arm_go_home(block=True, home_name="home_1")
        if home_result is None:
            logger.error("机械臂回零失败, 取消AGV导航命令发送")
            return None
        logger.debug(f"机械臂回零完成: {home_result}")

        # 步骤2: 发送AGV导航命令到目标工站
        logger.info("步骤2: 发送AGV导航命令到目标工站")

        # 验证工站ID是否有效
        if station_id not in STATION_POSITIONS:
            logger.error(f"无效的工站ID: {station_id}, 可用的工站: {list(STATION_POSITIONS.keys())}")
            return None

        station_info = STATION_POSITIONS[station_id]
        logger.info(f"发送导航命令到工站: {station_id} ({station_info['description']})")

        # 初始化AGV驱动
        agv_driver = AGVDriver(AGVDriverConfig(
            host=AGV_HOST,
            port=AGV_PORT,
            port_navigation=AGV_PORT_NAVIGATION,
            timeout_s=AGV_TIMEOUT,
            debug_hex=False
        ))

        try:
            # 连接到AGV导航端口
            logger.debug("正在连接到AGV导航端口...")
            agv_driver.connect_navigation()
            logger.debug("连接成功")

            # 调用异步导航函数发送命令
            logger.debug(f"正在发送导航命令到目标工站: {station_id}...")
            result = agv_driver.send_navigate_command(target_id=station_id)

            # 检查导航响应
            if result.get("ret_code") == 0:
                logger.info(f"导航命令发送成功, 响应: {result}")
                return result
            else:
                logger.error(f"导航命令发送失败, 错误码: {result.get('ret_code')}, 错误信息: {result.get('err_msg', '未知错误')}")
                return None

        except Exception as e:
            logger.error(f"发送导航命令过程出错: {e}")
            return None
        finally:
            # 关闭AGV连接
            agv_driver.close()
            logger.debug("AGV连接已关闭")

    def safe_navigate_to_station(self, station_id):
        """
        功能:
            安全移动AGV到指定工站, 移动前先执行机械臂回零操作(固定回home_1)
        参数:
            station_id: 工站ID, 例如"LM1", "LM2"等, 从配置文件STATION_POSITIONS中读取
        返回:
            dict或None, 成功时返回导航响应字典, 失败时返回None
        """
        logger.info(f"开始安全移动到工站: {station_id}")

        # 步骤1: 机械臂回零到home_1
        logger.debug("步骤1: 执行机械臂回零操作(home_1)")
        home_result = self.arm_go_home(block=True, home_name="home_1")
        if home_result is None:
            logger.error("机械臂回零失败, 取消AGV移动")
            return None
        logger.debug(f"机械臂回零完成: {home_result}")

        # 步骤2: AGV移动到目标工站
        logger.debug("步骤2: AGV移动到目标工站")
        result = self.navigate_to_station(station_id)

        return result

    def go_to_charging_station(self, block=False):
        """
        功能:
            让AGV移动到充电站CP6进行充电, 移动前先执行机械臂回零操作
        参数:
            block: 是否阻塞等待AGV到达, 默认False
                  - False: 发送导航命令后立即返回
                  - True: 等待AGV到达充电站后返回
        返回:
            dict或None, 成功时返回导航响应字典, 失败时返回None
        """
        logger.info(f"开始移动到充电站 (block={block})")

        # 根据block参数选择不同的导航方法
        if block:
            # 阻塞模式: 使用safe_navigate_to_station等待AGV到达
            result = self.safe_navigate_to_station("CP6")
        else:
            # 非阻塞模式: 使用safe_send_navigate_command立即返回
            result = self.safe_send_navigate_command("CP6")

        if result is not None:
            logger.info("成功到达充电站CP6")
        else:
            logger.error("移动到充电站失败")

        return result

    def auto_charge_check(self):
        """
        功能:
            自动充电检查函数, 按优先级依次判断并执行充电动作
            前置守卫(任一成立则跳过本次):
                1. AGV导航任务正在运行(WAITING/RUNNING/SUSPENDED)
            主要逻辑:
                - 不在CP6         → 不执行任何操作(not_at_cp6)
                - 在CP6且电量<50%:
                    - 先查询完整电池状态, 已在充电则跳过进出站(already_charging)
                    - 无法确认是否正在充电则保守跳过(charging_state_unknown)
                    - 未在充电时执行充电循环CP6->PP5->CP6
                    - 到达PP5后检查设备状态, 非空闲则认为被接管, 跳过后续(intercepted_after_pp5)
                    - 返回CP6后再次查询完整电池状态, 确认是否正在充电(charge_cycle_completed)
                - 在CP6且电量>=50%→ 无需动作(battery_sufficient)
        参数:
            无
        返回:
            dict, 包含检查结果的字典:
                - status: "success" / "skipped" / "error"
                - action: 执行的动作标识
                - battery_level: 电池电量(查询成功时包含)
                - charging: 是否正在充电(相关分支时包含)
                - message: 详细信息
        """
        logger.info("开始自动充电检查")

        try:
            # 前置守卫: AGV导航任务正忙时跳过
            nav_status = self.query_nav_task_status()
            if nav_status is not None:
                task_status = nav_status.get("task_status")
                # 1=WAITING / 2=RUNNING / 3=SUSPENDED 均视为忙碌
                if task_status in {1, 2, 3}:
                    status_name = nav_status.get("task_status_name", "UNKNOWN")
                    logger.info(f"AGV导航任务正忙(状态={status_name}), 跳过本次充电检查")
                    return {
                        "status": "skipped",
                        "action": "skipped_busy_nav",
                        "nav_task_status": task_status,
                        "nav_task_status_name": status_name,
                        "message": f"AGV导航任务正忙(状态={status_name}), 跳过本次充电检查"
                    }

            # 步骤1: 查询当前位置
            logger.info("步骤1: 查询当前位置")
            current_station = self.query_current_station()

            if current_station is None:
                logger.error("查询当前位置失败")
                return {
                    "status": "error",
                    "action": "query_location",
                    "message": "查询当前位置失败"
                }

            current_station_id = current_station.get("station_id")
            logger.info(f"当前位置: {current_station_id} - {current_station.get('station_name')}")

            # 步骤2: 查询电池电量
            logger.info("步骤2: 查询电池电量")
            battery_info = self.query_battery_status(simple=True)

            if battery_info is None:
                logger.error("查询电池电量失败")
                return {
                    "status": "error",
                    "action": "query_battery",
                    "message": "查询电池电量失败"
                }

            battery_level = battery_info.get("battery_level")
            logger.info(f"当前电池电量: {battery_level * 100:.1f}%")

            # 步骤3: 若不在CP6, 不执行任何操作直接跳过
            if current_station_id != "CP6":
                logger.info(f"当前不在CP6充电站(当前位置={current_station_id}), 跳过充电检查")
                return {
                    "status": "skipped",
                    "action": "not_at_cp6",
                    "battery_level": battery_level,
                    "current_station": current_station_id,
                    "message": f"当前不在CP6充电站(当前位置={current_station_id}), 不执行任何操作"
                }

            # 步骤4: 已在CP6, 电量低则执行充电循环
            if battery_level < 0.5:
                logger.info("步骤4: 电量低于50%, 先确认当前是否正在充电")
                battery_full_info = self.query_battery_status(simple=False)
                charging_flag = battery_full_info.get("charging") if battery_full_info is not None else None

                if charging_flag is None:
                    logger.warning("无法确认AGV当前是否正在充电, 本次不执行进出站")
                    return {
                        "status": "skipped",
                        "action": "charging_state_unknown",
                        "battery_level": battery_level,
                        "message": "无法确认是否正在充电, 本次不执行进出站"
                    }

                if charging_flag is True:
                    logger.info("检测到AGV当前已在充电, 跳过CP6->PP5->CP6充电循环")
                    return {
                        "status": "success",
                        "action": "already_charging",
                        "battery_level": battery_level,
                        "charging": True,
                        "message": f"电量{battery_level * 100:.1f}%低于50%, 但当前已在充电, 跳过CP6->PP5->CP6"
                    }

                logger.info(f"电池电量{battery_level * 100:.1f}%低于50%, 当前未在充电, 开始充电循环")

                # 步骤4.1: 移动到PP5充电过渡点
                logger.info("步骤4.1: 移动到PP5充电过渡点")
                result_pp5 = self.safe_navigate_to_station("PP5")

                if result_pp5 is None:
                    logger.error("移动到PP5失败")
                    return {
                        "status": "error",
                        "action": "move_to_pp5",
                        "battery_level": battery_level,
                        "message": f"电量{battery_level * 100:.1f}%低于50%, 但移动到PP5失败"
                    }

                logger.info("成功到达PP5")

                # 步骤4.2: 检查设备是否处于空闲状态, 非空闲则认为途中被接管
                logger.info("步骤4.2: 检查设备空闲状态")
                nav_status_after_pp5 = self.query_nav_task_status()
                if nav_status_after_pp5 is not None:
                    task_status_pp5 = nav_status_after_pp5.get("task_status")
                    # 0=NONE / 4=COMPLETED 视为空闲, 其余视为被接管
                    if task_status_pp5 not in {0, 4}:
                        status_name_pp5 = nav_status_after_pp5.get("task_status_name", "UNKNOWN")
                        logger.info(f"到达PP5后设备非空闲(状态={status_name_pp5}), 认为途中被接管, 跳过后续步骤")
                        return {
                            "status": "skipped",
                            "action": "intercepted_after_pp5",
                            "battery_level": battery_level,
                            "nav_task_status": task_status_pp5,
                            "nav_task_status_name": status_name_pp5,
                            "message": f"到达PP5后设备非空闲(状态={status_name_pp5}), 认为途中被接管, 跳过后续步骤"
                        }
                logger.info("设备处于空闲状态, 继续返回CP6")

                # 步骤4.3: 从PP5返回CP6
                logger.info("步骤4.3: 从PP5返回CP6")
                result_cp6 = self.safe_navigate_to_station("CP6")

                if result_cp6 is None:
                    logger.error("从PP5返回CP6失败")
                    return {
                        "status": "error",
                        "action": "return_to_cp6",
                        "battery_level": battery_level,
                        "message": f"电量{battery_level * 100:.1f}%低于50%, 已到达PP5但返回CP6失败"
                    }

                logger.info("已返回CP6, 检查充电状态")

                # 步骤4.4: 查询完整电池状态, 确认是否正在充电
                logger.info("步骤4.4: 查询完整电池状态, 确认充电状态")
                battery_full_info = self.query_battery_status(simple=False)

                if battery_full_info is not None and battery_full_info.get("charging"):
                    logger.info("确认AGV正在充电, 充电循环成功")
                    return {
                        "status": "success",
                        "action": "charge_cycle_completed",
                        "battery_level": battery_level,
                        "charging": True,
                        "message": f"电量{battery_level * 100:.1f}%低于50%, 已完成充电循环(CP6->PP5->CP6), 确认正在充电"
                    }
                else:
                    charging_val = battery_full_info.get("charging") if battery_full_info is not None else None
                    logger.warning(f"已返回CP6但未检测到充电状态(charging={charging_val})")
                    return {
                        "status": "success",
                        "action": "charge_cycle_completed_no_charging",
                        "battery_level": battery_level,
                        "charging": False,
                        "message": f"电量{battery_level * 100:.1f}%低于50%, 已完成充电循环(CP6->PP5->CP6), 但未检测到正在充电"
                    }
            else:
                logger.info(f"电池电量{battery_level * 100:.1f}%充足, 无需充电")
                return {
                    "status": "success",
                    "action": "battery_sufficient",
                    "battery_level": battery_level,
                    "message": f"电池电量{battery_level * 100:.1f}%充足, 无需充电"
                }

        except Exception as e:
            logger.error(f"自动充电检查过程中发生异常: {e}")
            return {
                "status": "error",
                "action": "exception",
                "message": f"自动充电检查过程中发生异常: {e}"
            }

    def auto_charge_loop(self, interval_hours=1, retry_wait_minutes=5):
        """
        功能:
            自动充电循环函数, 持续监控AGV充电状态
            - AGV在CP6时: 执行电量检查与充电, 之后等待interval_hours
            - AGV不在CP6时: 认为AGV正忙, 等待retry_wait_minutes后重试
        参数:
            interval_hours: AGV在CP6完成检查后的等待时间, 单位小时, 默认1小时
            retry_wait_minutes: AGV不在CP6时的重试间隔, 单位分钟, 默认5分钟
        返回:
            无(持续运行, 按Ctrl+C中断)
        """
        logger.info(f"启动自动充电循环, 检查间隔: {interval_hours}小时, 不在CP6时重试间隔: {retry_wait_minutes}分钟")

        while True:
            try:
                # 执行充电检查(内部已判断是否在CP6)
                result = self.auto_charge_check()
                action = result.get("action", "")
                status = result.get("status", "")
                logger.info(f"充电检查结果: {result}")

                # 根据检查结果决定等待时长
                if status == "skipped":
                    # AGV不在CP6, 短暂等待后重试
                    wait_seconds = retry_wait_minutes * 60
                    logger.info(f"跳过充电检查(原因={action}), 等待{retry_wait_minutes}分钟后重试...")
                else:
                    # 完成了充电检查, 等待较长时间再检查
                    wait_seconds = interval_hours * 3600
                    logger.info(f"充电检查完成, 等待{interval_hours}小时后进行下次检查...")

                # 分段睡眠, 每60秒一次, 使KeyboardInterrupt能及时响应
                self._interruptible_sleep(wait_seconds)

            except KeyboardInterrupt:
                logger.info("用户中断自动充电循环")
                break
            except Exception as e:
                logger.error(f"自动充电循环中发生异常: {e}")
                logger.info("等待5分钟后重试...")
                self._interruptible_sleep(300)

    def auto_charge_pp5_cp6_check(self, low_battery_pct=AGV_PP5_CP6_AUTO_CHARGE_LOW_BATTERY_PCT):
        """
        功能:
            基于PP5待命点和CP6充电站的自动充电检查函数.
            前置守卫:
                1. AGV导航任务正在运行时, 直接跳过本次检查.
            主要逻辑:
                - 在PP5且电量<low_battery_pct时, 进入CP6充电.
                - 在PP5且电量>=low_battery_pct时, 继续在PP5待命.
                - 在CP6且电量>90%时, 返回PP5待命.
                - 在CP6且电量<low_battery_pct且未在充电时, 执行CP6->PP5->CP6充电循环.
                - 在CP6且电量<low_battery_pct且已在充电时, 跳过进出站.
                - 在CP6且电量在low_battery_pct~90%之间时, 继续在CP6待命.
                - 既不在PP5也不在CP6时, 视为工作途中并跳过本次检查.
        参数:
            low_battery_pct: 低电量阈值(百分比), 默认80, 即电量低于80%触发充电.
        返回:
            dict, 包含检查结果的字典:
                - status: "success" / "skipped" / "error"
                - action: 执行的动作标识
                - battery_level: 电池电量, 查询成功时包含
                - current_station: 当前站点ID, 查询成功时包含
                - charging: 是否正在充电, 相关分支时包含
                - message: 详细信息
        """
        logger.info("开始PP5/CP6自动充电检查")

        try:
            # 将百分比阈值转为小数, 方便与battery_level比较
            low_threshold = low_battery_pct / 100

            # 导航任务忙碌时直接跳过, 避免监控逻辑和现场任务争抢控制权.
            nav_status = self.query_nav_task_status()
            if nav_status is not None:
                task_status = nav_status.get("task_status")
                if task_status in {1, 2, 3}:
                    status_name = nav_status.get("task_status_name", "UNKNOWN")
                    logger.info(f"AGV导航任务正忙(状态={status_name}), 跳过本次PP5/CP6充电检查")
                    return {
                        "status": "skipped",
                        "action": "skipped_busy_nav",
                        "nav_task_status": task_status,
                        "nav_task_status_name": status_name,
                        "message": f"AGV导航任务正忙(状态={status_name}), 跳过本次PP5/CP6充电检查"
                    }

            logger.info("步骤1: 查询当前位置")
            current_station = self.query_current_station()
            if current_station is None:
                logger.error("查询当前位置失败")
                return {
                    "status": "error",
                    "action": "query_location",
                    "message": "查询当前位置失败"
                }

            current_station_id = current_station.get("station_id")
            logger.info(f"当前位置: {current_station_id} - {current_station.get('station_name')}")

            logger.info("步骤2: 查询电池电量")
            battery_info = self.query_battery_status(simple=True)
            if battery_info is None:
                logger.error("查询电池电量失败")
                return {
                    "status": "error",
                    "action": "query_battery",
                    "current_station": current_station_id,
                    "message": "查询电池电量失败"
                }

            battery_level = battery_info.get("battery_level")
            if battery_level is None:
                logger.error("查询电池电量失败, 返回结果缺少battery_level")
                return {
                    "status": "error",
                    "action": "query_battery",
                    "current_station": current_station_id,
                    "message": "查询电池电量失败, 返回结果缺少battery_level"
                }

            logger.info(f"当前电池电量: {battery_level * 100:.1f}% (低电量阈值: {low_battery_pct}%)")

            if current_station_id == "PP5":
                if battery_level < low_threshold:
                    logger.info(f"步骤3: AGV在PP5且电量低于{low_battery_pct}%, 准备进入CP6充电")
                    result_cp6 = self.safe_navigate_to_station("CP6")
                    if result_cp6 is None:
                        logger.error("从PP5移动到CP6失败")
                        return {
                            "status": "error",
                            "action": "move_to_cp6",
                            "battery_level": battery_level,
                            "current_station": current_station_id,
                            "message": f"电量{battery_level * 100:.1f}%低于{low_battery_pct}%, 但从PP5移动到CP6失败"
                        }

                    logger.info("AGV已从PP5移动到CP6充电站")
                    return {
                        "status": "success",
                        "action": "pp5_to_cp6_for_charge",
                        "battery_level": battery_level,
                        "current_station": current_station_id,
                        "message": f"电量{battery_level * 100:.1f}%低于{low_battery_pct}%, 已从PP5移动到CP6充电"
                    }

                logger.info("AGV在PP5待命, 当前电量无需进入CP6")
                return {
                    "status": "success",
                    "action": "standby_at_pp5",
                    "battery_level": battery_level,
                    "current_station": current_station_id,
                    "message": f"电量{battery_level * 100:.1f}%达到待命要求, 继续在PP5待命"
                }

            if current_station_id == "CP6":
                if battery_level > 0.9:
                    logger.info("步骤3: AGV在CP6且电量高于90%, 准备返回PP5待命")
                    result_pp5 = self.safe_navigate_to_station("PP5")
                    if result_pp5 is None:
                        logger.error("从CP6移动到PP5失败")
                        return {
                            "status": "error",
                            "action": "move_to_pp5",
                            "battery_level": battery_level,
                            "current_station": current_station_id,
                            "message": f"电量{battery_level * 100:.1f}%高于90%, 但从CP6移动到PP5失败"
                        }

                    logger.info("AGV已从CP6返回PP5待命点")
                    return {
                        "status": "success",
                        "action": "cp6_to_pp5_after_charge",
                        "battery_level": battery_level,
                        "current_station": current_station_id,
                        "message": f"电量{battery_level * 100:.1f}%高于90%, 已从CP6返回PP5待命"
                    }

                # 在CP6且电量低于阈值时, 检查是否正在充电, 未充电则执行CP6->PP5->CP6循环
                if battery_level < low_threshold:
                    logger.info(f"步骤3: AGV在CP6且电量低于{low_battery_pct}%, 检查是否正在充电")
                    battery_full_info = self.query_battery_status(simple=False)
                    charging_flag = battery_full_info.get("charging") if battery_full_info is not None else None

                    if charging_flag is None:
                        logger.warning("无法确认AGV当前是否正在充电, 本次不执行进出站")
                        return {
                            "status": "skipped",
                            "action": "charging_state_unknown",
                            "battery_level": battery_level,
                            "current_station": current_station_id,
                            "message": f"电量{battery_level * 100:.1f}%低于{low_battery_pct}%, 但无法确认是否正在充电, 本次不执行进出站"
                        }

                    if charging_flag is True:
                        logger.info("检测到AGV当前已在充电, 跳过CP6->PP5->CP6充电循环")
                        return {
                            "status": "success",
                            "action": "already_charging",
                            "battery_level": battery_level,
                            "current_station": current_station_id,
                            "charging": True,
                            "message": f"电量{battery_level * 100:.1f}%低于{low_battery_pct}%, 但当前已在充电, 跳过CP6->PP5->CP6"
                        }

                    # 未在充电, 执行CP6->PP5->CP6充电循环
                    logger.info(f"电量{battery_level * 100:.1f}%低于{low_battery_pct}%且未在充电, 开始CP6->PP5->CP6充电循环")

                    # 步骤3.1: 从CP6移动到PP5
                    logger.info("步骤3.1: 从CP6移动到PP5")
                    result_pp5 = self.safe_navigate_to_station("PP5")
                    if result_pp5 is None:
                        logger.error("从CP6移动到PP5失败")
                        return {
                            "status": "error",
                            "action": "charge_cycle_move_to_pp5",
                            "battery_level": battery_level,
                            "current_station": current_station_id,
                            "message": f"电量{battery_level * 100:.1f}%低于{low_battery_pct}%且未在充电, 但从CP6移动到PP5失败"
                        }
                    logger.info("成功到达PP5")

                    # 步骤3.2: 检查设备是否处于空闲状态, 非空闲则认为途中被接管
                    logger.info("步骤3.2: 检查设备空闲状态")
                    nav_status_after_pp5 = self.query_nav_task_status()
                    if nav_status_after_pp5 is not None:
                        task_status_pp5 = nav_status_after_pp5.get("task_status")
                        if task_status_pp5 not in {0, 4}:
                            status_name_pp5 = nav_status_after_pp5.get("task_status_name", "UNKNOWN")
                            logger.info(f"到达PP5后设备非空闲(状态={status_name_pp5}), 认为途中被接管, 跳过后续步骤")
                            return {
                                "status": "skipped",
                                "action": "intercepted_after_pp5",
                                "battery_level": battery_level,
                                "current_station": current_station_id,
                                "nav_task_status": task_status_pp5,
                                "nav_task_status_name": status_name_pp5,
                                "message": f"到达PP5后设备非空闲(状态={status_name_pp5}), 认为途中被接管, 跳过后续步骤"
                            }
                    logger.info("设备处于空闲状态, 继续返回CP6")

                    # 步骤3.3: 从PP5返回CP6
                    logger.info("步骤3.3: 从PP5返回CP6")
                    result_cp6 = self.safe_navigate_to_station("CP6")
                    if result_cp6 is None:
                        logger.error("从PP5返回CP6失败")
                        return {
                            "status": "error",
                            "action": "charge_cycle_return_to_cp6",
                            "battery_level": battery_level,
                            "current_station": current_station_id,
                            "message": f"电量{battery_level * 100:.1f}%低于{low_battery_pct}%, 已到达PP5但返回CP6失败"
                        }

                    logger.info("已返回CP6, 检查充电状态")

                    # 步骤3.4: 查询完整电池状态, 确认是否正在充电
                    logger.info("步骤3.4: 查询完整电池状态, 确认充电状态")
                    battery_full_info = self.query_battery_status(simple=False)
                    if battery_full_info is not None and battery_full_info.get("charging"):
                        logger.info("确认AGV正在充电, 充电循环成功")
                        return {
                            "status": "success",
                            "action": "charge_cycle_completed",
                            "battery_level": battery_level,
                            "current_station": current_station_id,
                            "charging": True,
                            "message": f"电量{battery_level * 100:.1f}%低于{low_battery_pct}%, 已完成充电循环(CP6->PP5->CP6), 确认正在充电"
                        }
                    else:
                        charging_val = battery_full_info.get("charging") if battery_full_info is not None else None
                        logger.warning(f"已返回CP6但未检测到充电状态(charging={charging_val})")
                        return {
                            "status": "success",
                            "action": "charge_cycle_completed_no_charging",
                            "battery_level": battery_level,
                            "current_station": current_station_id,
                            "charging": False,
                            "message": f"电量{battery_level * 100:.1f}%低于{low_battery_pct}%, 已完成充电循环(CP6->PP5->CP6), 但未检测到正在充电"
                        }

                # 电量在阈值~90%之间, 继续在CP6待命
                logger.info("AGV在CP6待命, 当前电量尚未达到离站阈值")
                return {
                    "status": "success",
                    "action": "standby_at_cp6",
                    "battery_level": battery_level,
                    "current_station": current_station_id,
                    "message": f"电量{battery_level * 100:.1f}%未高于90%, 继续在CP6待命"
                }

            logger.info(f"AGV当前位置={current_station_id}, 视为工作途中, 跳过本次PP5/CP6充电检查")
            return {
                "status": "skipped",
                "action": "working_in_progress",
                "battery_level": battery_level,
                "current_station": current_station_id,
                "message": f"当前位置={current_station_id}, 不在PP5或CP6, 视为工作途中并跳过本次检查"
            }

        except Exception as e:
            logger.error(f"PP5/CP6自动充电检查过程中发生异常: {e}")
            return {
                "status": "error",
                "action": "exception",
                "message": f"PP5/CP6自动充电检查过程中发生异常: {e}"
            }

    def auto_charge_pp5_cp6_loop(
        self,
        interval_minutes=AGV_PP5_CP6_AUTO_CHARGE_INTERVAL_MINUTES,
        retry_wait_minutes=5,
        low_battery_pct=AGV_PP5_CP6_AUTO_CHARGE_LOW_BATTERY_PCT,
    ):
        """
        功能:
            基于PP5待命点和CP6充电站的自动充电循环函数.
            - 检查成功时, 等待interval_minutes后执行下一轮.
            - 检查被跳过或出错时, 等待retry_wait_minutes后重试.
        参数:
            interval_minutes: 检查成功后的等待时间, 单位分钟, 默认3分钟.
            retry_wait_minutes: 检查跳过或出错后的重试间隔, 单位分钟, 默认5分钟.
            low_battery_pct: 低电量阈值(百分比), 默认80, 即电量低于80%触发充电.
        返回:
            无, 持续运行直到用户中断.
        """
        logger.info(
            f"启动PP5/CP6自动充电循环, 检查间隔: {interval_minutes}分钟, "
            f"重试间隔: {retry_wait_minutes}分钟, 低电量阈值: {low_battery_pct}%"
        )

        while True:
            try:
                result = self.auto_charge_pp5_cp6_check(low_battery_pct=low_battery_pct)
                action = result.get("action", "")
                status = result.get("status", "")
                logger.info(f"PP5/CP6充电检查结果: {result}")

                if status == "success":
                    wait_seconds = interval_minutes * 60
                    logger.info(f"检查成功(action={action}), 等待{interval_minutes}分钟后进行下次检查...")
                else:
                    wait_seconds = retry_wait_minutes * 60
                    logger.info(f"检查未完成(action={action}, status={status}), 等待{retry_wait_minutes}分钟后重试...")

                self._interruptible_sleep(wait_seconds)

            except KeyboardInterrupt:
                logger.info("用户中断PP5/CP6自动充电循环")
                break
            except Exception as e:
                logger.error(f"PP5/CP6自动充电循环中发生异常: {e}")
                logger.info(f"等待{retry_wait_minutes}分钟后重试...")
                self._interruptible_sleep(retry_wait_minutes * 60)

    def _interruptible_sleep(self, total_seconds):
        """
        功能:
            分段睡眠, 将长时间睡眠拆分为多个60秒片段
            使KeyboardInterrupt信号能在最多60秒内得到响应
        参数:
            total_seconds: 总睡眠时间, 单位秒
        返回:
            无
        """
        elapsed = 0
        while elapsed < total_seconds:
            # 每次最多睡60秒, 剩余不足60秒则按实际时间睡
            step = min(60, total_seconds - elapsed)
            time.sleep(step)
            elapsed += step

    def move_to_grasp_position(self, tray_name, block=True):
        """
        功能:
            运动到抓取点位, 执行取托盘流程的前4步(到下探完成为止)
        参数:
            tray_name: 托盘位置名称, 例如"agv_tray_1", 从配置文件tray_position中读取
            block: 是否阻塞执行, True表示等待完成, False表示立即返回
        返回:
            bool, True表示运动成功, False表示运动失败
        """
        # 自动连接机械臂
        if not self._ensure_connected():
            logger.error("机械臂连接失败, 无法执行运动到抓取点位")
            return False

        # 获取托盘位置配置
        tray_position = self.position_manager.get_position('tray_position', tray_name)
        if tray_position is None:
            logger.error(f"未找到托盘位置配置: tray_position.{tray_name}")
            return False

        # 判断是否需要应用站点偏移量
        station_offset = None
        matched_station = None
        if not tray_name.startswith('agv'):
            # 读取配置文件中的所有站点校准信息
            try:
                import yaml
                with open(self.position_manager.config_file, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)

                if config is not None and 'station_calibration' in config:
                    # 遍历所有站点名称, 检查tray_name是否以某个站点名称开头
                    for station_name in config['station_calibration'].keys():
                        if tray_name.startswith(station_name):
                            matched_station = station_name
                            logger.debug(f"托盘 {tray_name} 匹配到站点 {station_name}, 尝试获取校准偏移量")

                            # 获取该站点的校准偏移量
                            station_offset = self.position_manager.get_calibration_offset(station_name)
                            if station_offset is not None:
                                logger.debug(f"找到站点 {station_name} 的校准偏移量: x={station_offset['x']:.6f}, y={station_offset['y']:.6f}, z={station_offset['z']:.6f}, dx={station_offset['dx']:.6f}, dy={station_offset['dy']:.6f}, dz={station_offset['dz']:.6f}")
                            break

                    if matched_station is None:
                        logger.debug(f"托盘 {tray_name} 未匹配到任何站点校准配置, 使用原始坐标")
            except Exception as e:
                logger.warning(f"读取站点校准配置失败: {e}, 使用原始坐标")

        logger.debug(f"开始执行运动到抓取点位流程: {tray_name}")

        try:
            # 步骤1: 运动到安全姿态
            logger.debug("步骤1: 运动到安全姿态")
            result = self.arm_go_home(block=block)
            logger.debug(f"安全姿态运动完成: {result}")

            # 步骤2: 张开夹爪
            logger.debug("步骤2: 张开夹爪")
            self.arm.open_gripper(block=True)
            logger.debug("夹爪已张开")

            # 步骤3: 运动到过渡点 (先rx,ry,rz, 然后z, 最后xy且速度减半)
            logger.debug("步骤3: 运动到过渡点")
            # 获取抓取点位姿(配置文件中存储的是抓取点)
            grasp_pose = tray_position.pose.copy()
            # 获取下探距离, 用于计算过渡点
            config_descend_z = tray_position.descend_z if hasattr(tray_position, 'descend_z') else -32
            # 计算过渡点: 过渡点z = 抓取点z - descend_z (descend_z为负值, 所以减去它等于加上绝对值)
            transition_pose = grasp_pose.copy()
            transition_pose[2] = grasp_pose[2] - config_descend_z
            logger.debug(f"抓取点z={grasp_pose[2]:.2f}, descend_z={config_descend_z}, 过渡点z={transition_pose[2]:.2f}")

            # 如果有站点偏移量, 则应用到过渡点位姿
            if station_offset is not None:
                transition_pose[0] += station_offset['x']
                transition_pose[1] += station_offset['y']
                transition_pose[2] += station_offset['z']
                transition_pose[3] += station_offset['dx']
                transition_pose[4] += station_offset['dy']
                transition_pose[5] += station_offset['dz']
                logger.debug(f"应用站点偏移量后的过渡点位姿: {transition_pose}")

            # 3.1: 先运动rx,ry,rz到位 (使用关节运动避免多圈问题)
            current_pose = self.arm.get_tcp_pose()
            target_pose_for_orientation = [
                current_pose[0] / 1000.0,  # 转换为m
                current_pose[1] / 1000.0,
                current_pose[2] / 1000.0,
                transition_pose[3],
                transition_pose[4],
                transition_pose[5]
            ]
            # 使用逆运动学计算目标关节角度
            current_joints = self.arm.get_joints_position()
            target_joints = self.arm.calculate_inverse_kinematics(
                pose=target_pose_for_orientation,
                q_near=current_joints  # 使用当前关节角度作为参考, 确保选解合理
            )
            # 使用关节运动 (move_to_joints会自动调整j6角度到合理范围)
            result = self.arm.move_to_joints(
                joints_list=target_joints,
                v=tray_position.speed,
                a=tray_position.acceleration,
                block=block
            )
            logger.debug(f"姿态调整完成(关节运动): {result}")

            # 3.2: 根据目标点Y坐标判断运动策略
            if transition_pose[1] < 450:
                # Y < 450, 在车内, xyz直接同时运动到位
                logger.debug("目标点在车内(Y<450), xyz直接运动到位")
                result = self.arm.move_linear(
                    pose=transition_pose,
                    v=tray_position.speed,
                    a=tray_position.acceleration,
                    block=block
                )
                logger.debug(f"过渡点运动完成: {result}")
            else:
                # Y >= 450, 在车外, 先运动到y=400, 然后y前伸
                logger.debug("目标点在车外(Y>=450), 先运动到y=400")
                current_pose = self.arm.get_tcp_pose()
                intermediate_pose = [
                    transition_pose[0],
                    400,
                    transition_pose[2],
                    current_pose[3],
                    current_pose[4],
                    current_pose[5]
                ]
                result = self.arm.move_linear(
                    pose=intermediate_pose,
                    v=tray_position.speed,
                    a=tray_position.acceleration,
                    block=block
                )
                logger.debug(f"运动到y=450完成: {result}")

                # 然后y前伸到目标点
                logger.debug("y前伸到目标点")
                result = self.arm.move_linear(
                    pose=transition_pose,
                    v=tray_position.speed * 0.5,
                    a=tray_position.acceleration,
                    block=block
                )
                logger.debug(f"过渡点运动完成: {result}")

            # 步骤4: 下探到抓取点位置 (只有Z轴变化)
            logger.debug("步骤4: 下探到抓取点位置")
            # 计算抓取点位姿(应用站点偏移量)
            target_grasp_pose = grasp_pose.copy()
            if station_offset is not None:
                target_grasp_pose[0] += station_offset['x']
                target_grasp_pose[1] += station_offset['y']
                target_grasp_pose[2] += station_offset['z']
                target_grasp_pose[3] += station_offset['dx']
                target_grasp_pose[4] += station_offset['dy']
                target_grasp_pose[5] += station_offset['dz']
            logger.debug(f"目标抓取点位姿: {target_grasp_pose}")
            result = self.arm.move_linear(
                pose=target_grasp_pose,
                v=tray_position.speed * 0.5,
                a=tray_position.acceleration,
                block=block
            )
            logger.debug(f"下探完成: {result}")

            logger.debug(f"运动到抓取点位流程完成: {tray_name}")
            return True

        except Exception as e:
            logger.error(f"运动到抓取点位流程失败: {e}")
            # 发生异常时张开夹爪
            try:
                self.arm.open_gripper(block=True)
            except Exception:
                pass
            return False

    def put_tray(self, tray_name, descend_z=None, lift_z=None, transition_z_offset=0, block=True):
        """
        功能:
            通用放托盘逻辑, 按照标准流程放置托盘
        参数:
            tray_name: 托盘位置名称, 例如"agv_tray_1", 从配置文件tray_position中读取
            descend_z: 下探距离(mm), 为None时从配置文件读取
            lift_z: 提升距离(mm), 为None时从配置文件读取
            transition_z_offset: 过渡点Z值偏移量(mm), 默认为0
            block: 是否阻塞执行, True表示等待完成, False表示立即返回
        返回:
            bool, True表示放置成功, False表示放置失败
        """
        # 自动连接机械臂
        if self._ensure_connected() is False:
            logger.error("机械臂连接失败, 无法执行放托盘动作")
            return False

        tray_position, station_offset = self._get_tray_position_context(tray_name)
        if tray_position is None:
            return False

        logger.info(f"开始执行放托盘流程: {tray_name}")

        try:
            transition_result = self._move_to_put_transition_pose(
                tray_position,
                station_offset=station_offset,
                transition_z_offset=transition_z_offset,
                block=block,
            )
            if transition_result is False:
                return False

            logger.debug("步骤3: 下探到抓取点位置")
            target_grasp_pose = tray_position.pose.copy()
            if station_offset is not None:
                target_grasp_pose[0] += station_offset['x']
                target_grasp_pose[1] += station_offset['y']
                target_grasp_pose[2] += station_offset['z']
                target_grasp_pose[3] += station_offset['dx']
                target_grasp_pose[4] += station_offset['dy']
                target_grasp_pose[5] += station_offset['dz']

            if descend_z is not None:
                current_pose = self.arm.get_tcp_pose()
                target_grasp_pose[2] = current_pose[2] + descend_z

            if transition_z_offset != 0:
                target_grasp_pose[2] += transition_z_offset
                logger.debug(f"应用物料高度偏移{transition_z_offset}mm到抓取点")

            drop_z_offset = tray_position.drop_z if hasattr(tray_position, 'drop_z') else 0
            if drop_z_offset > 0:
                target_grasp_pose[2] += drop_z_offset
                logger.debug(f"应用放置下落偏移{drop_z_offset}mm, 将在抓取点上方松开夹爪")

            logger.debug(f"目标抓取点位姿: {target_grasp_pose}")
            result = self.arm.move_linear(
                pose=target_grasp_pose,
                v=tray_position.speed * 0.1,
                a=tray_position.acceleration,
                block=block,
            )
            logger.debug(f"下探完成: {result}")

            if drop_z_offset > 0:
                time.sleep(2)  # 等待托盘自然落位稳定.

            finish_result = self._finish_put_tray_from_current_pose(
                tray_position,
                lift_z=lift_z,
                block=block,
            )
            if finish_result is False:
                return False

            logger.info(f"放托盘流程完成: {tray_name}")
            return True

        except Exception as e:
            logger.error(f"放托盘流程失败: {e}")
            return False

        if not self._ensure_connected():
            logger.error("机械臂连接失败, 无法执行放托盘动作")
            return False

        # 获放托盘位置配置
        tray_position = self.position_manager.get_position('tray_position', tray_name)
        if tray_position is None:
            logger.error(f"未找到托盘位置配置: tray_position.{tray_name}")
            return False

        # 判断是否需要应用站点偏移量
        station_offset = None
        matched_station = None
        if not tray_name.startswith('agv'):
            # 读取配置文件中的所有站点校准信息
            try:
                import yaml
                with open(self.position_manager.config_file, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)

                if config is not None and 'station_calibration' in config:
                    # 遍历所有站点名称, 检查tray_name是否以某个站点名称开头
                    for station_name in config['station_calibration'].keys():
                        if tray_name.startswith(station_name):
                            matched_station = station_name
                            logger.info(f"托盘 {tray_name} 匹配到站点 {station_name}, 尝试获取校准偏移量")

                            # 获取该站点的校准偏移量
                            station_offset = self.position_manager.get_calibration_offset(station_name)
                            if station_offset is not None:
                                logger.info(f"找到站点 {station_name} 的校准偏移量: x={station_offset['x']:.6f}, y={station_offset['y']:.6f}, z={station_offset['z']:.6f}, dx={station_offset['dx']:.6f}, dy={station_offset['dy']:.6f}, dz={station_offset['dz']:.6f}")
                            break

                    if matched_station is None:
                        logger.info(f"托盘 {tray_name} 未匹配到任何站点校准配置, 使用原始坐标")
            except Exception as e:
                logger.warning(f"读取站点校准配置失败: {e}, 使用原始坐标")

        logger.info(f"开始执行放托盘流程: {tray_name}")

        try:
            # 步骤1: 运动到安全姿态
            logger.debug("步骤1: 运动到安全姿态")
            result = self.arm_go_home(block=block)
            logger.debug(f"安全姿态运动完成: {result}")

            # 步骤2: 运动到过渡点 (先rx,ry,rz, 然后z, 最后xy且速度减半)
            logger.debug("步骤2: 运动到过渡点")
            # 获取抓取点位姿(配置文件中存储的是抓取点)
            grasp_pose = tray_position.pose.copy()
            # 获取下探距离, 用于计算过渡点
            config_descend_z = tray_position.descend_z if hasattr(tray_position, 'descend_z') else -32
            # 计算过渡点: 过渡点z = 抓取点z - descend_z (descend_z为负值, 所以减去它等于加上绝对值)
            transition_pose = grasp_pose.copy()
            transition_pose[2] = grasp_pose[2] - config_descend_z
            logger.debug(f"抓取点z={grasp_pose[2]:.2f}, descend_z={config_descend_z}, 过渡点z={transition_pose[2]:.2f}")

            # 如果有站点偏移量, 则应用到过渡点位姿
            if station_offset is not None:
                transition_pose[0] += station_offset['x']
                transition_pose[1] += station_offset['y']
                transition_pose[2] += station_offset['z']
                transition_pose[3] += station_offset['dx']
                transition_pose[4] += station_offset['dy']
                transition_pose[5] += station_offset['dz']
                logger.debug(f"应用站点偏移量后的过渡点位姿: {transition_pose}")

            # 应用过渡点Z偏移量(用于物料高度补偿)
            if transition_z_offset != 0:
                transition_pose[2] += transition_z_offset
                logger.debug(f"应用过渡点Z偏移量{transition_z_offset}mm后的过渡点位姿: {transition_pose}")

            # 2.1: 先运动rx,ry,rz到位 (使用关节运动避免多圈问题)
            current_pose = self.arm.get_tcp_pose()
            target_pose_for_orientation = [
                current_pose[0] / 1000.0,  # 转换为m
                current_pose[1] / 1000.0,
                current_pose[2] / 1000.0,
                transition_pose[3],
                transition_pose[4],
                transition_pose[5]
            ]
            # 使用逆运动学计算目标关节角度
            current_joints = self.arm.get_joints_position()
            target_joints = self.arm.calculate_inverse_kinematics(
                pose=target_pose_for_orientation,
                q_near=current_joints  # 使用当前关节角度作为参考, 确保选解合理
            )
            # 使用关节运动 (move_to_joints会自动调整j6角度到合理范围)
            result = self.arm.move_to_joints(
                joints_list=target_joints,
                v=tray_position.speed,
                a=tray_position.acceleration,
                block=block
            )
            logger.debug(f"姿态调整完成(关节运动): {result}")

            # 2.2: 根据目标点Y坐标判断运动策略
            if transition_pose[1] < 450:
                # Y < 450, 在车内, xyz直接同时运动到位
                logger.debug("目标点在车内(Y<450), xyz直接运动到位")
                result = self.arm.move_linear(
                    pose=transition_pose,
                    v=tray_position.speed,
                    a=tray_position.acceleration,
                    block=block
                )
                logger.debug(f"过渡点运动完成: {result}")
            else:
                # Y >= 450, 在车外, 先运动到y=400, 然后y前伸
                logger.debug("目标点在车外(Y>=450), 先运动到y=400")
                current_pose = self.arm.get_tcp_pose()
                intermediate_pose = [
                    transition_pose[0],
                    400,
                    transition_pose[2],
                    current_pose[3],
                    current_pose[4],
                    current_pose[5]
                ]
                result = self.arm.move_linear(
                    pose=intermediate_pose,
                    v=tray_position.speed,
                    a=tray_position.acceleration,
                    block=block
                )
                logger.debug(f"运动到y=400完成: {result}")

                # 然后y前伸到目标点
                logger.info("y前伸到目标点")
                result = self.arm.move_linear(
                    pose=transition_pose,
                    v=tray_position.speed * 0.2,
                    a=tray_position.acceleration,
                    block=block
                )
                logger.info(f"过渡点运动完成: {result}")

            # 步骤3: 下探到抓取点位置 (只有Z轴变化)
            logger.debug("步骤3: 下探到抓取点位置")
            # 计算抓取点位姿(应用站点偏移量)
            target_grasp_pose = grasp_pose.copy()
            if station_offset is not None:
                target_grasp_pose[0] += station_offset['x']
                target_grasp_pose[1] += station_offset['y']
                target_grasp_pose[2] += station_offset['z']
                target_grasp_pose[3] += station_offset['dx']
                target_grasp_pose[4] += station_offset['dy']
                target_grasp_pose[5] += station_offset['dz']
            # 如果传入了自定义descend_z, 则使用自定义值计算目标z
            if descend_z is not None:
                current_pose = self.arm.get_tcp_pose()
                target_grasp_pose[2] = current_pose[2] + descend_z
            # 应用物料高度偏移到抓取点(与过渡点保持一致的偏移)
            if transition_z_offset != 0:
                target_grasp_pose[2] += transition_z_offset
                logger.debug(f"应用物料高度偏移{transition_z_offset}mm到抓取点")
            # 应用放置下落偏移(在抓取点上方 drop_z mm处松开夹爪)
            drop_z_offset = tray_position.drop_z if hasattr(tray_position, 'drop_z') else 0
            if drop_z_offset > 0:
                target_grasp_pose[2] += drop_z_offset
                logger.debug(f"应用放置下落偏移{drop_z_offset}mm, 将在抓取点上方松开夹爪")
            logger.debug(f"目标抓取点位姿: {target_grasp_pose}")
            result = self.arm.move_linear(
                pose=target_grasp_pose,
                v=tray_position.speed * 0.1,
                a=tray_position.acceleration,
                block=block
            )
            logger.debug(f"下探完成: {result}")

            if drop_z_offset > 0:
                time.sleep(2)  # 有下落偏移时额外等待托盘落位稳定

            # 步骤4: 松开夹爪并检查是否松开
            logger.debug("步骤4: 松开夹爪")
            self.arm.open_gripper(block=True)

            # 等待夹爪稳定并检查状态
            time.sleep(1)

            if not self.arm.is_gripper_opened():
                logger.error("夹爪未松开")
                return False
            logger.debug("夹爪松开成功")

            # 步骤5: 提升一定距离 (只有Z轴变化)
            logger.debug("步骤5: 提升")
            # 如果未传入lift_z参数, 则从配置文件读取
            if lift_z is None:
                lift_z = tray_position.lift_z if hasattr(tray_position, 'lift_z') else 0.1
            current_pose = self.arm.get_tcp_pose()
            logger.debug(f"当前位姿: {current_pose}, 提升距离: {lift_z}mm")
            lift_pose = [
                current_pose[0],
                current_pose[1],
                current_pose[2] + lift_z,
                current_pose[3],
                current_pose[4],
                current_pose[5]
            ]
            logger.debug(f"目标位姿: {lift_pose}")
            result = self.arm.move_linear(
                pose=lift_pose,
                v=tray_position.speed * 0.5,
                a=tray_position.acceleration,
                block=block
            )
            logger.debug(f"提升完成: {result}")

            # 步骤6: 回到home位置
            logger.debug("步骤6: 回到home位置")
            result = self.arm_go_home(block=block)
            logger.debug(f"回到home位置完成: {result}")

            logger.info(f"放托盘流程完成: {tray_name}")
            return True

        except Exception as e:
            logger.error(f"放托盘流程失败: {e}")
            return False

    # ==================== 夹爪管理 ====================

    def get_current_gripper(self):
        """
        功能:
            获取当前安装的夹爪名称
        返回:
            str或None, 当前夹爪名称
        """
        return self.arm.get_current_gripper()

    def change_gripper(self, target_gripper, block=True):
        """
        功能:
            自动更换夹爪
        参数:
            target_gripper: 目标夹爪名称, 如"gripper_type_a"
            block: 是否阻塞执行
        返回:
            bool, True表示更换成功
        """
        # 检查目标夹爪配置是否存在
        gripper_config = self.position_manager.get_gripper(target_gripper)
        if gripper_config is None:
            logger.error(f"未找到夹爪配置: {target_gripper}")
            return False

        # 如果当前已经是目标夹爪, 直接返回
        current_gripper = self.arm.get_current_gripper()
        if current_gripper == target_gripper:
            logger.info(f"当前已安装目标夹爪: {target_gripper}")
            return True

        # 自动连接机械臂
        if not self._ensure_connected():
            logger.error("机械臂连接失败, 无法执行换爪操作")
            return False

        logger.info(f"开始更换夹爪: {current_gripper} -> {target_gripper}")

        try:
            # 步骤1: 回到安全位置
            logger.info("步骤1: 回到安全位置")
            self.arm_go_home(block=block)

            # 步骤2: 如果当前有夹爪, 先放回原位
            if current_gripper is not None:
                logger.info(f"步骤2: 放回当前夹爪 {current_gripper}")
                success = self._put_gripper(current_gripper, block=block)
                if not success:
                    logger.error(f"放回夹爪失败: {current_gripper}")
                    return False
            else:
                logger.info("步骤2: 当前无夹爪, 跳过放回步骤")

            # 步骤3: 取出目标夹爪
            logger.info(f"步骤3: 取出目标夹爪 {target_gripper}")
            success = self._pick_gripper(target_gripper, block=block)
            if not success:
                logger.error(f"取出夹爪失败: {target_gripper}")
                return False

            # 步骤4: 更新当前夹爪状态
            self.arm.set_current_gripper(target_gripper)

            # 步骤5: 回到安全位置
            logger.info("步骤5: 回到安全位置")
            self.arm_go_home(block=block)

            logger.info(f"夹爪更换完成: {target_gripper}")
            return True

        except Exception as e:
            logger.error(f"更换夹爪失败: {e}")
            return False

    def _pick_gripper(self, gripper_name, block=True):
        """
        功能:
            从存放位置取出夹爪
        参数:
            gripper_name: 夹爪名称
            block: 是否阻塞执行
        返回:
            bool, True表示取出成功
        """
        # 获取夹爪存放位置
        storage_pos = self.position_manager.get_gripper_storage_position(gripper_name)
        if storage_pos is None:
            logger.error(f"未找到夹爪存放位置: {gripper_name}")
            return False

        # 获取夹爪配置
        gripper_config = self.position_manager.get_gripper(gripper_name)
        if gripper_config is None:
            logger.error(f"未找到夹爪配置: {gripper_name}")
            return False

        # 检查夹爪是否在料位上
        if not self.arm.check_quick_change_slot(gripper_config.slot):
            logger.error(f"夹爪料位{gripper_config.slot}上没有夹爪")
            return False

        logger.info(f"开始取出夹爪: {gripper_name}, 料位: {gripper_config.slot}")

        try:
            # 松开快换装置
            logger.info("松开快换装置")
            self.arm.release_quick_change(block=True)

            # 运动到存放位置上方
            logger.info("运动到夹爪存放位置上方")
            self.arm.move_linear(
                pose=storage_pos.pose,
                v=storage_pos.speed,
                a=storage_pos.acceleration,
                block=block
            )

            # 下探对接夹爪
            logger.info("下探对接夹爪")
            current_pose = self.arm.get_tcp_pose()
            descend_pose = [
                current_pose[0],
                current_pose[1],
                current_pose[2] + storage_pos.descend_z,
                current_pose[3],
                current_pose[4],
                current_pose[5]
            ]
            self.arm.move_linear(
                pose=descend_pose,
                v=storage_pos.speed * 0.5,
                a=storage_pos.acceleration,
                block=block
            )

            # 锁紧快换装置
            logger.info("锁紧快换装置")
            self.arm.lock_quick_change(block=True)
            import time
            time.sleep(0.5)  # 等待气缸动作完成

            # 提升
            logger.info("提升夹爪")
            current_pose = self.arm.get_tcp_pose()
            lift_pose = [
                current_pose[0],
                current_pose[1],
                current_pose[2] + storage_pos.lift_z,
                current_pose[3],
                current_pose[4],
                current_pose[5]
            ]
            self.arm.move_linear(
                pose=lift_pose,
                v=storage_pos.speed * 0.5,
                a=storage_pos.acceleration,
                block=block
            )

            logger.info(f"成功取出夹爪: {gripper_name}")
            return True

        except Exception as e:
            logger.error(f"取出夹爪失败: {e}")
            return False

    def _put_gripper(self, gripper_name, block=True):
        """
        功能:
            将夹爪放回存放位置
        参数:
            gripper_name: 夹爪名称
            block: 是否阻塞执行
        返回:
            bool, True表示放回成功
        """
        # 获取夹爪存放位置
        storage_pos = self.position_manager.get_gripper_storage_position(gripper_name)
        if storage_pos is None:
            logger.error(f"未找到夹爪存放位置: {gripper_name}")
            return False

        logger.info(f"开始放回夹爪: {gripper_name}")

        try:
            # 运动到存放位置上方
            logger.info("运动到夹爪存放位置上方")
            self.arm.move_linear(
                pose=storage_pos.pose,
                v=storage_pos.speed,
                a=storage_pos.acceleration,
                block=block
            )

            # 下探到存放位置
            logger.info("下探到存放位置")
            current_pose = self.arm.get_tcp_pose()
            descend_pose = [
                current_pose[0],
                current_pose[1],
                current_pose[2] + storage_pos.descend_z,
                current_pose[3],
                current_pose[4],
                current_pose[5]
            ]
            self.arm.move_linear(
                pose=descend_pose,
                v=storage_pos.speed * 0.5,
                a=storage_pos.acceleration,
                block=block
            )

            # 松开快换装置
            logger.info("松开快换装置")
            self.arm.release_quick_change(block=True)
            import time
            time.sleep(0.5)  # 等待气缸动作完成

            # 提升离开
            logger.info("提升离开")
            current_pose = self.arm.get_tcp_pose()
            lift_pose = [
                current_pose[0],
                current_pose[1],
                current_pose[2] + storage_pos.lift_z,
                current_pose[3],
                current_pose[4],
                current_pose[5]
            ]
            self.arm.move_linear(
                pose=lift_pose,
                v=storage_pos.speed * 0.5,
                a=storage_pos.acceleration,
                block=block
            )

            # 清除当前夹爪状态
            self.arm.set_current_gripper(None)

            logger.info(f"成功放回夹爪: {gripper_name}")
            return True

        except Exception as e:
            logger.error(f"放回夹爪失败: {e}")
            return False

    # ==================== 物料适配转移 ====================

    def pick_tray_with_material(self, tray_name, material_type=None, block=True):
        """
        功能:
            根据物料类型取托盘, 自动选择夹爪和调整夹持高度
        参数:
            tray_name: 托盘位置名称
            material_type: 物料类型名称, 为None时使用默认参数
            block: 是否阻塞执行
        返回:
            bool, True表示抓取成功
        """
        # 自动连接机械臂
        if not self._ensure_connected():
            logger.error("机械臂连接失败")
            return False

        # 获取物料配置
        material_config = None
        if material_type is not None:
            material_config = self.position_manager.get_material(material_type)
            if material_config is None:
                logger.warning(f"未找到物料配置: {material_type}, 使用默认参数")

        # 如果有物料配置, 检查并更换夹爪
        if material_config is not None:
            required_gripper = material_config.gripper
            current_gripper = self.arm.get_current_gripper()
            if current_gripper != required_gripper:
                logger.info(f"物料 {material_type} 需要夹爪 {required_gripper}, 当前夹爪: {current_gripper}")
                success = self.change_gripper(required_gripper, block=block)
                if not success:
                    logger.error(f"更换夹爪失败, 无法继续取托盘")
                    return False

        # 获取托盘位置配置
        tray_position = self.position_manager.get_position('tray_position', tray_name)
        if tray_position is None:
            logger.error(f"未找到托盘位置配置: {tray_name}")
            return False

        # 计算过渡点Z偏移量(用于物料高度补偿)
        transition_z_offset = 0
        if material_config is not None:
            # 物料偏移量应用到过渡点Z值, 使过渡点更高
            transition_z_offset = material_config.descend_z_offset
            logger.info(f"应用物料偏移到过渡点Z值: transition_z_offset={transition_z_offset}mm")

        # 执行取托盘流程(使用过渡点Z偏移量)
        return self.pick_tray(tray_name, descend_z=None, lift_z=None, transition_z_offset=transition_z_offset, block=block)

    def put_tray_with_material(self, tray_name, material_type=None, block=True):
        """
        功能:
            根据物料类型放托盘, 自动调整放置高度
        参数:
            tray_name: 托盘位置名称
            material_type: 物料类型名称, 为None时使用默认参数
            block: 是否阻塞执行
        返回:
            bool, True表示放置成功
        """
        # 自动连接机械臂
        if not self._ensure_connected():
            logger.error("机械臂连接失败")
            return False

        # 获取物料配置
        material_config = None
        if material_type is not None:
            material_config = self.position_manager.get_material(material_type)
            if material_config is None:
                logger.warning(f"未找到物料配置: {material_type}, 使用默认参数")

        # 获取托盘位置配置
        tray_position = self.position_manager.get_position('tray_position', tray_name)
        if tray_position is None:
            logger.error(f"未找到托盘位置配置: {tray_name}")
            return False

        # 计算过渡点Z偏移量(用于物料高度补偿)
        transition_z_offset = 0
        if material_config is not None:
            # 物料偏移量应用到过渡点Z值, 使过渡点更高
            transition_z_offset = material_config.descend_z_offset
            logger.info(f"应用物料偏移到过渡点Z值: transition_z_offset={transition_z_offset}mm")

        # 执行放托盘流程(使用过渡点Z偏移量)
        return self.put_tray(tray_name, descend_z=None, lift_z=None, transition_z_offset=transition_z_offset, block=block)

    def transfer_material(self, source_tray, target_tray, material_type=None, block=True):
        """
        功能:
            物料转移, 从源位置取出并放到目标位置
        参数:
            source_tray: 源托盘位置名称
            target_tray: 目标托盘位置名称
            material_type: 物料类型名称
            block: 是否阻塞执行
        返回:
            bool, True表示转移成功
        """
        logger.info(f"开始物料转移: {source_tray} -> {target_tray}, 物料类型: {material_type}")

        # 从源位置取出
        success = self.pick_tray_with_material(source_tray, material_type, block)
        if not success:
            logger.error(f"从 {source_tray} 取出物料失败")
            return False

        # 放到目标位置
        success = self.put_tray_with_material(target_tray, material_type, block)
        if not success:
            logger.error(f"放置物料到 {target_tray} 失败")
            return False

        logger.info(f"物料转移完成: {source_tray} -> {target_tray}")
        return True

    def batch_transfer_materials(self, transfer_tasks, block=True, on_station_delivered=None):
        """
        功能:
            批量物料转运, AGV自动移动到各站点并进行点位校准, 支持一次转运最多4个物料.
            Phase 2 中每完成一个目标站点的全部放料后, 若提供了 on_station_delivered 回调,
            则在新线程中异步调用该回调, 不阻塞后续站点的转运.
        参数:
            transfer_tasks: 转运任务列表, 每个任务为字典{"source_tray": str, "target_tray": str, "material_type": str}
                          例如: [{"source_tray": "shelf_tray_1", "target_tray": "agv_tray_1", "material_type": "vial_10ml"}]
            block: 是否阻塞执行
            on_station_delivered: 可选回调函数, 签名为
                                  callback(station_id: str, delivered_task_indices: list[int]) -> None.
                                  Phase 2 每个目标站点全部放料完成后在新 daemon 线程中异步调用.
                                  回调异常不影响转运流程. 默认为 None.
        返回:
            bool, True表示全部转运成功
        """
        # 验证任务数量
        if len(transfer_tasks) == 0:
            logger.error("转运任务列表为空")
            return False

        if len(transfer_tasks) > 4:
            logger.error(f"转运任务数量超过限制, 最多支持4个任务, 当前: {len(transfer_tasks)}")
            return False

        logger.info(f"开始批量物料转运, 共{len(transfer_tasks)}个任务")

        # 按站点分组任务
        source_stations = {}  # {station_id: [task_index]}
        target_stations = {}  # {station_id: [task_index]}

        for idx, task in enumerate(transfer_tasks):
            source_tray = task.get("source_tray")
            target_tray = task.get("target_tray")
            material_type = task.get("material_type")

            if not source_tray or not target_tray:
                logger.error(f"任务{idx+1}缺少必要参数: source_tray或target_tray")
                return False

            logger.info(f"任务{idx+1}: {source_tray} -> {target_tray}, 物料类型: {material_type}")

            # 确定源托盘所属站点
            source_station = self._get_station_from_tray(source_tray)
            if source_station is not None:
                if source_station not in source_stations:
                    source_stations[source_station] = []
                source_stations[source_station].append(idx)

            # 确定目标托盘所属站点
            target_station = self._get_station_from_tray(target_tray)
            if target_station is not None:
                if target_station not in target_stations:
                    target_stations[target_station] = []
                target_stations[target_station].append(idx)

        # 存储物料在AGV货架上的位置映射
        task_to_agv_tray = {}  # {task_index: agv_tray_name}
        agv_tray_names = ["agv_tray_1", "agv_tray_2", "agv_tray_3", "agv_tray_4"]

        try:
            # 阶段1: 从各源站点取料并放到AGV货架
            logger.info("阶段1: 从源站点取料并放到AGV货架")

            for station_id, task_indices in source_stations.items():
                logger.info(f"处理源站点: {station_id}")

                # AGV移动到源站点
                logger.info(f"AGV移动到站点: {station_id}")
                result = self.safe_navigate_to_station(station_id)
                if result is None:
                    logger.error(f"AGV移动到站点{station_id}失败")
                    return False

                # 等待AGV到达
                logger.info("等待AGV到达站点...")
                import time
                time.sleep(2)

                # 进行点位校准
                logger.info(f"执行站点{station_id}点位校准")
                calibration_result = self.calibrate_station(block=block)
                if calibration_result is None:
                    logger.error(f"站点{station_id}校准失败, 停止运行")
                    return False
                else:
                    logger.info(f"站点{station_id}校准成功")

                # 依次取出该站点的所有物料并放到AGV货架
                for task_idx in task_indices:
                    task = transfer_tasks[task_idx]
                    source_tray = task["source_tray"]
                    material_type = task.get("material_type")

                    # 分配AGV货架位置
                    agv_tray = agv_tray_names[task_idx]
                    task_to_agv_tray[task_idx] = agv_tray

                    logger.info(f"任务{task_idx+1}: 从{source_tray}取料")
                    success = self.pick_tray_with_material(source_tray, material_type, block)
                    if not success:
                        logger.error(f"从{source_tray}取出物料失败")
                        return False

                    logger.info(f"任务{task_idx+1}: 放置到AGV货架{agv_tray}")
                    success = self.put_tray_with_material(agv_tray, material_type, block)
                    if not success:
                        logger.error(f"放置物料到{agv_tray}失败")
                        return False

                    logger.info(f"任务{task_idx+1}: 成功放置到AGV货架, 已完成{len(task_to_agv_tray)}/{len(transfer_tasks)}个取料")

            # 阶段2: 从AGV货架取料并放置到各目标站点
            logger.info("阶段2: 从AGV货架取料并放置到目标站点")

            for station_id, task_indices in target_stations.items():
                logger.debug(f"\n处理目标站点: {station_id}")

                # AGV移动到目标站点
                logger.info(f"AGV移动到站点: {station_id}")
                result = self.safe_navigate_to_station(station_id)
                if result is None:
                    logger.error(f"AGV移动到站点{station_id}失败")
                    return False

                # 等待AGV到达
                logger.info("等待AGV到达站点...")
                import time
                time.sleep(2)

                # 进行点位校准
                logger.info(f"执行站点{station_id}点位校准")
                calibration_result = self.calibrate_station(block=block)
                if calibration_result is None:
                    logger.error(f"站点{station_id}校准失败, 停止运行")
                    return False
                else:
                    logger.info(f"站点{station_id}校准成功")

                # 依次从AGV货架取料并放置到目标位置
                for task_idx in task_indices:
                    task = transfer_tasks[task_idx]
                    target_tray = task["target_tray"]
                    material_type = task.get("material_type")
                    agv_tray = task_to_agv_tray[task_idx]

                    logger.info(f"任务{task_idx+1}: 从AGV货架{agv_tray}取料")
                    success = self.pick_tray_with_material(agv_tray, material_type, block)
                    if not success:
                        logger.error(f"从{agv_tray}取出物料失败")
                        return False

                    logger.info(f"任务{task_idx+1}: 放置到目标位置{target_tray}")
                    success = self.put_tray_with_material(target_tray, material_type, block)
                    if not success:
                        logger.error(f"放置物料到{target_tray}失败")
                        return False

                    logger.info(f"任务{task_idx+1}: 成功放置到目标位置")

                # 该站点全部放料完成, 异步触发回调(不阻塞后续站点转运)
                if on_station_delivered is not None:
                    _sid = station_id
                    _indices = list(task_indices)

                    def _fire_callback(sid=_sid, indices=_indices):
                        try:
                            on_station_delivered(sid, indices)
                        except Exception as cb_exc:
                            logger.error(
                                f"on_station_delivered 回调执行异常 (station={sid}): {cb_exc}"
                            )

                    t = threading.Thread(
                        target=_fire_callback, daemon=True, name=f"agv_cb_{_sid}"
                    )
                    t.start()
                    logger.info(f"站点 {station_id} 卸货完成, 已异步触发回调")

            logger.info(f"批量物料转运完成, 共完成{len(transfer_tasks)}个任务")
            return True

        except Exception as e:
            logger.error(f"批量物料转运失败: {e}")
            return False

    def batch_transfer_cycle_test(self, transfer_tasks, cycle_count=1, block=True):
        """
        功能:
            批量物料转运循环测试, 执行正向转运->充电站->反向转运->充电站的循环
        参数:
            transfer_tasks: 转运任务列表, 每个任务为字典{"source_tray": str, "target_tray": str, "material_type": str}
                          例如: [{"source_tray": "shelf_tray_1", "target_tray": "agv_tray_1", "material_type": "vial_10ml"}]
            cycle_count: 循环次数, 默认为1
            block: 是否阻塞执行
        返回:
            dict, 包含测试结果的字典:
                - success: bool, 是否全部成功
                - completed_cycles: int, 完成的循环次数
                - total_cycles: int, 总循环次数
                - failed_at: str或None, 失败的阶段描述
        """
        logger.info(f"=" * 80)
        logger.info(f"开始批量物料转运循环测试, 共{cycle_count}轮循环")
        logger.info(f"=" * 80)

        # 验证任务列表
        if len(transfer_tasks) == 0:
            logger.error("转运任务列表为空")
            return {
                "success": False,
                "completed_cycles": 0,
                "total_cycles": cycle_count,
                "failed_at": "任务验证失败: 任务列表为空"
            }

        if len(transfer_tasks) > 4:
            logger.error(f"转运任务数量超过限制, 最多支持4个任务, 当前: {len(transfer_tasks)}")
            return {
                "success": False,
                "completed_cycles": 0,
                "total_cycles": cycle_count,
                "failed_at": f"任务验证失败: 任务数量超过限制({len(transfer_tasks)}>4)"
            }

        # 显示任务信息
        logger.info(f"转运任务列表:")
        for idx, task in enumerate(transfer_tasks, 1):
            logger.info(f"任务{idx}: {task['source_tray']} <-> {task['target_tray']}, 物料类型: {task.get('material_type', '未指定')}")

        completed_cycles = 0
        charging_station_wait_seconds = 10

        try:
            for cycle in range(cycle_count):
                logger.info(f"\n{'=' * 80}")
                logger.info(f"第 {cycle + 1}/{cycle_count} 轮循环开始")
                logger.info(f"{'=' * 80}")

                # 步骤1: 正向转运(源->目标)
                logger.info(f"\n步骤1: 正向转运(源->目标)")
                logger.info(f"-" * 80)
                result = self.batch_transfer_materials(transfer_tasks, block=block)
                if not result:
                    logger.error(f"第{cycle + 1}轮正向转运失败")
                    return {
                        "success": False,
                        "completed_cycles": completed_cycles,
                        "total_cycles": cycle_count,
                        "failed_at": f"第{cycle + 1}轮正向转运"
                    }
                logger.info(f"第{cycle + 1}轮正向转运完成")

                # 步骤2: AGV移动到充电站
                logger.info(f"\n步骤2: AGV移动到充电站")
                logger.info(f"-" * 80)
                result = self.go_to_charging_station(block=True)
                if result is None:
                    logger.error(f"第{cycle + 1}轮正向转运后移动到充电站失败")
                    return {
                        "success": False,
                        "completed_cycles": completed_cycles,
                        "total_cycles": cycle_count,
                        "failed_at": f"第{cycle + 1}轮正向转运后移动到充电站"
                    }
                logger.info(f"第{cycle + 1}轮正向转运后成功到达充电站")

                # 步骤3: 反向转运(目标->源)
                logger.info(f"\n步骤3: 反向转运(目标->源)")
                logger.info(f"-" * 80)
                # 构建反向任务列表(交换源和目标)
                # 回到充电站后停留 10 秒, 再执行下一段循环测试.
                logger.info(f"第{cycle + 1}轮回到充电站后等待{charging_station_wait_seconds}秒, 然后开始反向转运")
                time.sleep(charging_station_wait_seconds)
                reverse_tasks = []
                for task in transfer_tasks:
                    reverse_task = {
                        "source_tray": task["target_tray"],
                        "target_tray": task["source_tray"],
                        "material_type": task.get("material_type")
                    }
                    reverse_tasks.append(reverse_task)

                result = self.batch_transfer_materials(reverse_tasks, block=block)
                if not result:
                    logger.error(f"第{cycle + 1}轮反向转运失败")
                    return {
                        "success": False,
                        "completed_cycles": completed_cycles,
                        "total_cycles": cycle_count,
                        "failed_at": f"第{cycle + 1}轮反向转运"
                    }
                logger.info(f"第{cycle + 1}轮反向转运完成")

                # 步骤4: AGV移动到充电站
                logger.info(f"\n步骤4: AGV移动到充电站")
                logger.info(f"-" * 80)
                result = self.go_to_charging_station(block=True)
                if result is None:
                    logger.error(f"第{cycle + 1}轮反向转运后移动到充电站失败")
                    return {
                        "success": False,
                        "completed_cycles": completed_cycles,
                        "total_cycles": cycle_count,
                        "failed_at": f"第{cycle + 1}轮反向转运后移动到充电站"
                    }
                logger.info(f"第{cycle + 1}轮反向转运后成功到达充电站")

                # 完成一轮循环
                if cycle < cycle_count - 1:
                    # 非最后一轮时, 从充电站再次出发前同样等待 10 秒.
                    logger.info(f"第{cycle + 1}轮结束后回到充电站, 等待{charging_station_wait_seconds}秒再开始下一轮")
                    time.sleep(charging_station_wait_seconds)

                completed_cycles += 1
                logger.info(f"\n{'=' * 80}")
                logger.info(f"第 {cycle + 1}/{cycle_count} 轮循环完成")
                logger.info(f"{'=' * 80}")

            # 全部循环完成
            logger.info(f"\n{'=' * 80}")
            logger.info(f"批量物料转运循环测试全部完成! 共完成{completed_cycles}轮循环")
            logger.info(f"{'=' * 80}")

            return {
                "success": True,
                "completed_cycles": completed_cycles,
                "total_cycles": cycle_count,
                "failed_at": None
            }

        except Exception as e:
            logger.error(f"批量物料转运循环测试失败: {e}")
            return {
                "success": False,
                "completed_cycles": completed_cycles,
                "total_cycles": cycle_count,
                "failed_at": f"异常: {str(e)}"
            }

    def transfer_analysis_to_shelf(
        self,
        source_trays=None,
        material_type="FLASH_FILTER_OUTER_BOTTLE_TRAY",
        poll_interval=30.0,
        poll_timeout=7200.0,
        block=True,
    ):
        """
        功能:
            从分析站取走完成检测的样品, 放置到货架空位上.
            先轮询智达进样设备状态, 等待其变为 Idle 后执行转运.
            转运和货架状态更新完成后, 让 AGV 返回充电站待命.
        参数:
            source_trays: 源托盘列表, 默认 ["analysis_station_tray_1-2"]
            material_type: 物料类型标识, 默认 "FLASH_FILTER_OUTER_BOTTLE_TRAY"
            poll_interval: 状态轮询间隔(秒), 默认 30
            poll_timeout: 轮询超时(秒), 默认 7200(2小时)
            block: 是否阻塞执行
        返回:
            bool, True 表示转运和回充都成功, False 表示任一步失败
        """
        if source_trays is None:
            source_trays = ["analysis_station_tray_1-2"]

        logger.info("开始分析站→货架样品转运, 源托盘: %s", source_trays)

        # 步骤1: 轮询智达设备状态, 等待变为 Idle
        logger.info("步骤1: 轮询智达进样设备状态, 等待变为 Idle ...")
        from unilabos.devices.eit_analysis_station.driver.zhida_driver import ZhidaClient

        client = ZhidaClient()
        try:
            client.connect()
            logger.info("已连接到智达进样设备")
        except Exception as e:
            logger.error("连接智达进样设备失败: %s", e)
            return False

        try:
            elapsed = 0.0
            while elapsed < poll_timeout:
                status_detail = client.get_status_detail()
                base_status = status_detail["base_status"]
                raw_status = status_detail["raw_status"] or "(空)"
                logger.info(
                    "智达设备当前状态, 主状态: %s, 原始状态: %s, 已等待 %.0f 秒",
                    base_status,
                    raw_status,
                    elapsed,
                )

                if base_status == "Idle":
                    logger.info("智达设备主状态已空闲, 原始状态: %s, 准备执行转运", raw_status)
                    break
                elif base_status in ("Offline", "Error"):
                    logger.error(
                        "智达设备异常状态, 主状态: %s, 原始状态: %s, 终止转运",
                        base_status,
                        raw_status,
                    )
                    return False
                else:
                    # Busy / RunSample 等状态, 继续等待
                    time.sleep(poll_interval)
                    elapsed += poll_interval
            else:
                logger.error("轮询超时(%.0f秒), 设备未变为 Idle, 终止转运", poll_timeout)
                return False
        finally:
            client.close()

        # 步骤2: 查找货架空闲槽位
        logger.info("步骤2: 查找货架空闲槽位, 需要 %d 个", len(source_trays))
        empty_slots = self.shelf_manager.find_empty_slots(len(source_trays))

        if len(empty_slots) < len(source_trays):
            logger.error(
                "货架空闲槽位不足: 需要 %d 个, 仅有 %d 个",
                len(source_trays), len(empty_slots),
            )
            return False

        logger.info("已找到空闲槽位: %s", empty_slots)

        # 步骤3: 构建并执行转运任务
        logger.info("步骤3: 执行批量物料转运")
        transfer_tasks = []
        for src, tgt in zip(source_trays, empty_slots):
            transfer_tasks.append({
                "source_tray": src,
                "target_tray": tgt,
                "material_type": material_type,
            })
            logger.info("转运任务: %s -> %s", src, tgt)

        result = self.batch_transfer_materials(transfer_tasks, block=block)
        if not result:
            logger.error("批量物料转运失败")
            return False

        # 步骤4: 更新货架状态记录
        logger.info("步骤4: 更新货架物料状态")
        for src, tgt in zip(source_trays, empty_slots):
            self.shelf_manager.place_material(
                slot_name=tgt,
                material_type=material_type,
                source=src,
                description="分析完成样品(自动转运)",
            )

        # 货架状态已经与实际转运结果一致, 回充失败时不回滚状态.
        logger.info("步骤5: 返回充电站")
        try:
            charge_result = self.go_to_charging_station(block=block)
        except Exception as exc:
            logger.error("分析站→货架样品转运完成, 但返回充电站异常: %s", exc)
            return False

        if charge_result is None:
            logger.error("分析站→货架样品转运完成, 但返回充电站失败")
            return False

        logger.info("分析站→货架样品转运完成, AGV 已返回充电站")
        return True

    def _get_station_from_tray(self, tray_name):
        """
        功能:
            根据托盘名称推断所属站点ID
        参数:
            tray_name: 托盘位置名称
        返回:
            str或None, 站点ID, 如果是AGV上的托盘则返回None
        """
        # 如果是AGV上的托盘, 返回None
        if tray_name.startswith('agv'):
            return None

        # 遍历所有站点, 查找匹配的站点名称
        for station_id, station_info in STATION_POSITIONS.items():
            station_name = station_info["name"]
            if tray_name.startswith(station_name):
                return station_id

        logger.warning(f"无法确定托盘{tray_name}所属站点")
        return None

    def prepare_loaded_tray_calibration(self, target_tray_name, source_tray_name="agv_tray_1", block=True):
        """
        功能:
            为带托盘点位校准准备现场状态, 固定先夹取源托盘, 再运动到目标点前过渡位.

        参数:
            target_tray_name: 目标托盘点位名称.
            source_tray_name: 源托盘点位名称, 默认agv_tray_1.
            block: 是否阻塞等待动作完成.

        返回:
            bool, True表示准备完成, False表示失败.
        """
        logger.info(f"开始准备带托盘点位校准: {source_tray_name} -> {target_tray_name}")

        pick_result = self.pick_tray(source_tray_name, block=block)
        if pick_result is False:
            logger.error(f"源托盘夹取失败, 无法继续带托盘点位校准: {source_tray_name}")
            return False

        tray_position, station_offset = self._get_tray_position_context(target_tray_name)
        if tray_position is None:
            logger.error(f"目标点位不存在, 保持当前夹持状态等待人工处理: {target_tray_name}")
            return False

        try:
            move_result = self._move_to_put_transition_pose(
                tray_position,
                station_offset=station_offset,
                transition_z_offset=0,
                block=block,
            )
            if move_result is False:
                logger.error(f"目标过渡位运动失败, 保持当前夹持状态等待人工处理: {target_tray_name}")
                return False
        except Exception as e:
            logger.error(f"带托盘点位校准准备失败, 保持当前夹持状态等待人工处理: {e}")
            return False

        logger.info(f"带托盘点位校准准备完成, 已到达目标过渡位: {target_tray_name}")
        return True

    def get_calibrated_tray_pose_from_current_pose(self, tray_name, current_pose=None):
        """
        功能:
            将当前TCP位姿转换为应保存的托盘点位姿态.

        参数:
            tray_name: 托盘点位名称.
            current_pose: 当前TCP位姿, 为None时实时读取机械臂当前位姿.

        返回:
            list或None, 成功时返回应保存的位姿, 失败时返回None.
        """
        if current_pose is None:
            if self._ensure_connected() is False:
                logger.error("机械臂连接失败, 无法读取当前TCP位姿")
                return None
            current_pose = self.arm.get_tcp_pose()

        logger.info(f"当前TCP位姿: {current_pose}")
        return self._build_saved_tray_pose(tray_name, current_pose)

    def complete_loaded_tray_calibration(self, target_tray_name, block=True):
        """
        功能:
            完成带托盘点位校准的收尾动作, 在当前位置松爪, 提升并回零.

        参数:
            target_tray_name: 目标托盘点位名称.
            block: 是否阻塞等待动作完成.

        返回:
            bool, True表示收尾成功, False表示失败.
        """
        tray_position, _ = self._get_tray_position_context(target_tray_name)
        if tray_position is None:
            return False

        try:
            return self._finish_put_tray_from_current_pose(
                tray_position,
                lift_z=None,
                block=block,
            )
        except Exception as e:
            logger.error(f"带托盘点位校准收尾失败: {e}")
            return False

    def calibrate_tray_position(self, tray_name, block=True):
        """
        功能:
            托盘点位校准, 运动到抓取点位后等待用户手动矫正, 确认后保存当前TCP位姿到配置文件
            对于非AGV点位, 会减去站点校准偏移量后存储原始TCP位姿
        参数:
            tray_name: 托盘位置名称, 例如"agv_tray_1", "shelf_tray_1-1"
            block: 是否阻塞执行, True表示等待完成
        返回:
            list或None, 成功时返回保存的TCP位姿列表[x, y, z, rx, ry, rz], 失败时返回None
        """
        # 自动连接机械臂
        if not self._ensure_connected():
            logger.error("机械臂连接失败, 无法执行点位校准")
            return None

        # 获取托盘位置配置
        tray_position = self.position_manager.get_position('tray_position', tray_name)
        if tray_position is None:
            logger.error(f"未找到托盘位置配置: tray_position.{tray_name}")
            return None

        logger.info(f"开始执行托盘点位校准: {tray_name}")

        try:
            # 步骤1: 运动到抓取点位
            logger.info("步骤1: 运动到抓取点位")
            result = self.move_to_grasp_position(tray_name, block=block)
            if not result:
                logger.error("运动到抓取点位失败")
                return None
            logger.info("已到达抓取点位, 请手动矫正机械臂位置")

            # 步骤2: 等待用户确认(在交互式环境中由调用者处理)
            # 此处仅返回当前TCP位姿供调用者使用

            # 步骤3: 获取当前TCP位姿
            current_pose = self.arm.get_tcp_pose()
            logger.info(f"当前TCP位姿: {current_pose}")

            # 步骤4: 判断是否为AGV上的点位
            is_agv_position = tray_name.startswith('agv')

            if is_agv_position:
                # AGV上的点位, 直接保存当前TCP位姿
                pose_to_save = current_pose
                logger.info(f"AGV点位, 直接保存当前TCP位姿: {pose_to_save}")
            else:
                # 非AGV点位, 需要减去站点校准偏移量
                # 查找匹配的站点
                matched_station = None
                import yaml
                with open(self.position_manager.config_file, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)

                if config is not None and 'station_calibration' in config:
                    for station_name in config['station_calibration'].keys():
                        if tray_name.startswith(station_name):
                            matched_station = station_name
                            break

                if matched_station is not None:
                    # 获取站点校准偏移量
                    station_offset = self.position_manager.get_calibration_offset(matched_station)
                    if station_offset is not None:
                        # 原始TCP位姿 = 当前TCP位姿 - 偏移量
                        pose_to_save = [
                            current_pose[0] - station_offset['x'],
                            current_pose[1] - station_offset['y'],
                            current_pose[2] - station_offset['z'],
                            current_pose[3] - station_offset['dx'],
                            current_pose[4] - station_offset['dy'],
                            current_pose[5] - station_offset['dz']
                        ]
                        logger.info(f"非AGV点位, 匹配站点: {matched_station}")
                        logger.info(f"站点偏移量: x={station_offset['x']:.6f}, y={station_offset['y']:.6f}, z={station_offset['z']:.6f}")
                        logger.info(f"原始TCP位姿(减去偏移量后): {pose_to_save}")
                    else:
                        # 站点未校准, 使用当前位姿
                        pose_to_save = current_pose
                        logger.warning(f"站点 {matched_station} 未校准, 直接保存当前TCP位姿")
                else:
                    # 未匹配到站点, 使用当前位姿
                    pose_to_save = current_pose
                    logger.warning(f"托盘 {tray_name} 未匹配到任何站点, 直接保存当前TCP位姿")

            return pose_to_save

        except Exception as e:
            logger.error(f"托盘点位校准失败: {e}")
            return None

    def save_calibrated_tray_position(self, tray_name, pose, description=None):
        """
        功能:
            保存校准后的托盘位置到配置文件
        参数:
            tray_name: 托盘位置名称
            pose: TCP位姿列表[x, y, z, rx, ry, rz]
            description: 位置描述, 为None时保留原有描述
        返回:
            bool, True表示保存成功
        """
        try:
            self.position_manager.save_tray_position(tray_name, pose, description)
            logger.info(f"托盘位置 {tray_name} 已保存到配置文件")
            return True
        except Exception as e:
            logger.error(f"保存托盘位置失败: {e}")
            return False

    def calibrate_station_offset(self, block=True):
        """
        功能:
            工站整体偏差矫正, 通过选择参考点位计算偏移量并应用到工站所有点位.
            支持空载或带托盘两种校准方式, 带托盘时固定从 agv_tray_1 夹取托盘.
            流程:
            1. 选择要校准的工站(agv或当前所在工站).
            2. 如果不是agv, 先进行视觉补偿并记录偏移量.
            3. 让用户选择一个参考点位.
            4. 询问是否夹托盘进行校准.
            5. 空载时可选择运动到该点位, 带托盘时自动从 agv_tray_1 夹取并运动到目标点前过渡位.
            6. 用户微调坐标后按回车确认.
            7. 计算偏移量并询问是否应用到工站所有点位.
        参数:
            block: 是否阻塞执行, True表示等待完成.
        返回:
            dict或None, 成功时返回偏移量字典{"x": float, "y": float, "z": float, "rx": float, "ry": float, "rz": float}, 失败时返回None.
        """
        # 自动连接机械臂
        if self._ensure_connected() is False:
            logger.error("机械臂连接失败, 无法执行工站偏差矫正")
            return None

        # 查询当前站点
        logger.info("正在查询当前站点...")
        station_info = self.query_current_station()
        current_station_name = None
        if station_info is not None:
            current_station_name = station_info["station_name"]
            logger.info(f"当前站点: {station_info['station_id']} - {current_station_name}")
        else:
            logger.warning("查询当前站点失败, 只能校准agv工站")

        # 步骤1: 选择要校准的工站
        station_options = ["agv"]
        if current_station_name is not None and current_station_name != "agv":
            station_options.append(current_station_name)

        print("\n请选择要校准的工站:")
        for idx, station in enumerate(station_options, 1):
            print(f"  {idx}. {station}")

        station_choice = input(f"请输入工站编号 (1-{len(station_options)}): ").strip()
        if station_choice.isdigit() is False:
            logger.error("输入无效")
            return None

        station_index = int(station_choice) - 1
        if station_index < 0 or station_index >= len(station_options):
            logger.error("输入超出范围")
            return None

        selected_station = station_options[station_index]
        logger.info(f"选择校准工站: {selected_station}")

        # 步骤2: 如果不是agv, 先进行视觉补偿
        vision_offset = None
        if selected_station != "agv":
            print(f"\n是否先进行 {selected_station} 工站的视觉补偿校准?")
            vision_confirm = input("确认执行视觉补偿? (y/n): ").strip().lower()
            if vision_confirm == 'y':
                logger.info(f"执行 {selected_station} 工站视觉补偿校准...")
                calibration_result = self.calibrate_station(block=block)
                if calibration_result is not None:
                    vision_offset = calibration_result
                    logger.info(f"视觉补偿完成, 偏移量: x={vision_offset['x']:.3f}, y={vision_offset['y']:.3f}, z={vision_offset['z']:.3f}")
                else:
                    logger.error("视觉补偿校准失败, 停止运行")
                    return None

        # 步骤3: 获取该工站的所有点位供用户选择
        tray_positions = self.position_manager.get_category('tray_position')
        if tray_positions is None:
            logger.error("未找到托盘位置配置")
            return None

        # 过滤出该工站的点位
        station_tray_list = []
        for tray_name in tray_positions.keys():
            if tray_name.startswith(selected_station):
                station_tray_list.append(tray_name)

        if len(station_tray_list) == 0:
            logger.error(f"工站 {selected_station} 没有可用的点位")
            return None

        print(f"\n{selected_station} 工站的点位:")
        for idx, tray_name in enumerate(station_tray_list, 1):
            tray_config = tray_positions[tray_name]
            description = tray_config.get('description', '无描述')
            print(f"  {idx}. {tray_name} - {description}")

        tray_choice = input(f"请选择参考点位 (1-{len(station_tray_list)}): ").strip()
        if tray_choice.isdigit() is False:
            logger.error("输入无效")
            return None

        tray_index = int(tray_choice) - 1
        if tray_index < 0 or tray_index >= len(station_tray_list):
            logger.error("输入超出范围")
            return None

        selected_tray = station_tray_list[tray_index]
        logger.info(f"选择参考点位: {selected_tray}")

        # 获取该点位的原始TCP位姿(配置文件中存储的)
        tray_position = self.position_manager.get_position('tray_position', selected_tray)
        if tray_position is None or tray_position.pose is None:
            logger.error(f"点位 {selected_tray} 没有有效的位姿数据")
            return None

        original_pose = tray_position.pose.copy()
        logger.info(f"原始TCP位姿(配置文件): {original_pose}")

        print("\n是否夹托盘进行校准?")
        loaded_confirm = input("确认夹取 agv_tray_1 的托盘? (y/n): ").strip().lower()
        use_loaded_tray = loaded_confirm == "y"
        entered_manual_stage = False

        try:
            if use_loaded_tray is True:
                logger.info(f"开始带托盘工站偏差矫正: agv_tray_1 -> {selected_tray}")
                result = self.prepare_loaded_tray_calibration(
                    selected_tray,
                    source_tray_name="agv_tray_1",
                    block=block,
                )
                if result is False:
                    logger.error("带托盘参考点准备失败, 当前可能仍保持夹持状态, 请人工处理")
                    return None

                entered_manual_stage = True
                logger.info(f"已带托盘到达参考点前过渡位: {selected_tray}")
            else:
                print(f"\n是否运动到点位 {selected_tray}?")
                move_confirm = input("确认运动? (y/n): ").strip().lower()

                if move_confirm == "y":
                    logger.info(f"运动到点位 {selected_tray}...")
                    result = self.move_to_grasp_position(selected_tray, block=block)
                    if not result:
                        logger.error("运动到点位失败")
                        return None
                    logger.info("已到达点位")

                entered_manual_stage = True

            # 用户在参考点附近手动完成最终对位.
            print("\n请手动微调机械臂位置到正确位置")
            print("提示: 可以使用示教器或其他方式调整机械臂位置")
            print("微调完成后, 按回车键继续...")
            input()

            current_pose = self.arm.get_tcp_pose()
            logger.info(f"当前TCP位姿(微调后): {current_pose}")

            # 非AGV工站完成视觉补偿后, 需先叠加视觉偏移再计算整体偏差.
            if selected_station != "agv" and vision_offset is not None:
                expected_pose = [
                    original_pose[0] + vision_offset["x"],
                    original_pose[1] + vision_offset["y"],
                    original_pose[2] + vision_offset["z"],
                    original_pose[3] + vision_offset["dx"],
                    original_pose[4] + vision_offset["dy"],
                    original_pose[5] + vision_offset["dz"],
                ]
                logger.info(f"期望TCP位姿(原始+视觉偏移): {expected_pose}")

                offset_x = current_pose[0] - expected_pose[0]
                offset_y = current_pose[1] - expected_pose[1]
                offset_z = current_pose[2] - expected_pose[2]
                offset_rx = current_pose[3] - expected_pose[3]
                offset_ry = current_pose[4] - expected_pose[4]
                offset_rz = current_pose[5] - expected_pose[5]
            else:
                offset_x = current_pose[0] - original_pose[0]
                offset_y = current_pose[1] - original_pose[1]
                offset_z = current_pose[2] - original_pose[2]
                offset_rx = current_pose[3] - original_pose[3]
                offset_ry = current_pose[4] - original_pose[4]
                offset_rz = current_pose[5] - original_pose[5]

            print(f"\n{'=' * 60}")
            print("偏移量计算结果:")
            print(f"{'=' * 60}")
            print(f"原始TCP位姿(配置文件): x={original_pose[0]:.3f}, y={original_pose[1]:.3f}, z={original_pose[2]:.3f}")
            print(f"                       rx={original_pose[3]:.6f}, ry={original_pose[4]:.6f}, rz={original_pose[5]:.6f}")
            print(f"当前TCP位姿(微调后):   x={current_pose[0]:.3f}, y={current_pose[1]:.3f}, z={current_pose[2]:.3f}")
            print(f"                       rx={current_pose[3]:.6f}, ry={current_pose[4]:.6f}, rz={current_pose[5]:.6f}")
            print(f"计算得到的偏移量:      dx={offset_x:.3f}, dy={offset_y:.3f}, dz={offset_z:.3f}")
            print(f"                       drx={offset_rx:.6f}, dry={offset_ry:.6f}, drz={offset_rz:.6f}")

            offset_result = {
                "x": offset_x,
                "y": offset_y,
                "z": offset_z,
                "rx": offset_rx,
                "ry": offset_ry,
                "rz": offset_rz,
            }

            print(f"\n是否将此偏移量应用到 {selected_station} 工站的所有点位?")
            print(f"将影响以下 {len(station_tray_list)} 个点位:")
            for tray_name in station_tray_list:
                print(f"  - {tray_name}")

            apply_confirm = input("确认应用偏移量? (y/n): ").strip().lower()

            if apply_confirm != "y":
                logger.info("用户取消应用偏移量")
                print("\n偏移量未应用, 但已计算:")
                print(f"  位置: dx={offset_x:.3f}, dy={offset_y:.3f}, dz={offset_z:.3f}")
                print(f"  姿态: drx={offset_rx:.6f}, dry={offset_ry:.6f}, drz={offset_rz:.6f}")
                return offset_result

            logger.info(f"开始应用偏移量到 {selected_station} 工站的所有点位...")

            success_count = 0
            fail_count = 0

            for tray_name in station_tray_list:
                try:
                    tray_pos = self.position_manager.get_position("tray_position", tray_name)
                    if tray_pos is None or tray_pos.pose is None:
                        logger.warning(f"点位 {tray_name} 没有有效的位姿数据, 跳过")
                        fail_count += 1
                        continue

                    old_pose = tray_pos.pose.copy()
                    new_pose = [
                        old_pose[0] + offset_x,
                        old_pose[1] + offset_y,
                        old_pose[2] + offset_z,
                        old_pose[3] + offset_rx,
                        old_pose[4] + offset_ry,
                        old_pose[5] + offset_rz,
                    ]

                    self.position_manager.save_tray_position(tray_name, new_pose)
                    logger.info(f"点位 {tray_name} 已更新: x={old_pose[0]:.3f}->{new_pose[0]:.3f}, y={old_pose[1]:.3f}->{new_pose[1]:.3f}, z={old_pose[2]:.3f}->{new_pose[2]:.3f}")
                    success_count += 1

                except Exception as e:
                    logger.error(f"更新点位 {tray_name} 失败: {e}")
                    fail_count += 1

            print(f"\n{'=' * 60}")
            print("偏移量应用完成!")
            print(f"{'=' * 60}")
            print(f"成功更新: {success_count} 个点位")
            print(f"更新失败: {fail_count} 个点位")
            print("应用的偏移量:")
            print(f"  位置: dx={offset_x:.3f}, dy={offset_y:.3f}, dz={offset_z:.3f}")
            print(f"  姿态: drx={offset_rx:.6f}, dry={offset_ry:.6f}, drz={offset_rz:.6f}")

            return offset_result
        finally:
            if use_loaded_tray is True and entered_manual_stage is True:
                cleanup_result = self.complete_loaded_tray_calibration(
                    selected_tray,
                    block=block,
                )
                if cleanup_result is False:
                    logger.error("带托盘工站偏差矫正收尾失败, 请人工处理")

    def test_all_positions(self, material_type, block=True):
        """
        功能:
            全点位测试函数, 从agv_tray_1取托盘依次放到每个点位再取回, 测试所有点位的准确性
            测试流程:
            1. 提示用户在agv_tray_1放置托盘
            2. 执行点位校准
            3. 从agv_tray_1取托盘, 放到目标点位, 再取回放回agv_tray_1
            4. 重复步骤3直到测试完所有点位
        参数:
            material_type: 托盘物料类型名称, 用于确定夹爪和高度偏移
            block: 是否阻塞执行, True表示等待完成
        返回:
            dict, 测试结果字典{"success": list, "failed": list, "skipped": list}
        """
        import time

        logger.info("=" * 60)
        logger.info("开始全点位测试")
        logger.info("=" * 60)

        # 获取物料配置
        material_config = self.position_manager.get_material(material_type)
        if material_config is None:
            logger.error(f"未找到物料配置: {material_type}")
            return {"success": [], "failed": [], "skipped": []}

        logger.info(f"物料类型: {material_type} - {material_config.description}")
        logger.info(f"使用夹爪: {material_config.gripper}")

        # 自动连接机械臂
        if not self._ensure_connected():
            logger.error("机械臂连接失败, 无法执行全点位测试")
            return {"success": [], "failed": [], "skipped": []}

        # 获取所有托盘位置
        tray_positions = self.position_manager.get_category('tray_position')
        if tray_positions is None:
            logger.error("未找到托盘位置配置")
            return {"success": [], "failed": [], "skipped": []}

        # 过滤出当前站点的点位(排除agv开头的点位)
        test_positions = []
        if self.current_station is not None and self.current_station in STATION_POSITIONS:
            station_name = STATION_POSITIONS[self.current_station]["name"]
            for tray_name in tray_positions.keys():
                # 只测试当前站点的点位, 排除agv开头的点位
                if tray_name.startswith(station_name):
                    test_positions.append(tray_name)
        else:
            logger.warning("未设置当前站点, 将测试所有非AGV点位")
            for tray_name in tray_positions.keys():
                if not tray_name.startswith('agv'):
                    test_positions.append(tray_name)

        if len(test_positions) == 0:
            logger.error("当前站点没有可测试的点位")
            return {"success": [], "failed": [], "skipped": []}

        logger.info(f"待测试点位数量: {len(test_positions)}")
        for idx, pos_name in enumerate(test_positions, 1):
            logger.info(f"  {idx}. {pos_name}")

        # 测试结果记录
        results = {
            "success": [],
            "failed": [],
            "skipped": []
        }

        try:
            # 步骤1: 执行点位校准
            logger.info("\n" + "=" * 60)
            logger.info("步骤1: 执行点位校准")
            logger.info("=" * 60)

            calibration_result = self.calibrate_station(block=block)
            if calibration_result is None:
                logger.error("点位校准失败, 停止测试")
                return results
            else:
                logger.info(f"点位校准成功: x={calibration_result['x']:.3f}, y={calibration_result['y']:.3f}, z={calibration_result['z']:.3f}")

            # 步骤2: 依次测试每个点位
            logger.info("\n" + "=" * 60)
            logger.info("步骤2: 开始逐点位测试")
            logger.info("=" * 60)

            for idx, target_position in enumerate(test_positions, 1):
                logger.info(f"\n{'=' * 60}")
                logger.info(f"测试点位 {idx}/{len(test_positions)}: {target_position}")
                logger.info(f"{'=' * 60}")

                try:
                    # 2.1: 从agv_tray_1取托盘
                    logger.info(f"从 agv_tray_1 取托盘...")
                    pick_result = self.pick_tray_with_material("agv_tray_1", material_type, block=block)
                    if not pick_result:
                        logger.error(f"从 agv_tray_1 取托盘失败")
                        results["failed"].append(target_position)
                        continue

                    # 2.2: 放到目标点位
                    logger.info(f"放置托盘到 {target_position}...")
                    put_result = self.put_tray_with_material(target_position, material_type, block=block)
                    if not put_result:
                        logger.error(f"放置托盘到 {target_position} 失败")
                        # 尝试回到home位置
                        self.arm_go_home(block=block)
                        results["failed"].append(target_position)
                        continue

                    # 2.3: 从目标点位取回托盘
                    logger.info(f"从 {target_position} 取回托盘...")
                    pick_back_result = self.pick_tray_with_material(target_position, material_type, block=block)
                    if not pick_back_result:
                        logger.error(f"从 {target_position} 取回托盘失败")
                        results["failed"].append(target_position)
                        continue

                    # 2.4: 放回agv_tray_1
                    logger.info(f"放回托盘到 agv_tray_1...")
                    put_back_result = self.put_tray_with_material("agv_tray_1", material_type, block=block)
                    if not put_back_result:
                        logger.error(f"放回托盘到 agv_tray_1 失败")
                        results["failed"].append(target_position)
                        continue

                    # 测试成功
                    logger.info(f"点位 {target_position} 测试成功!")
                    results["success"].append(target_position)

                except Exception as e:
                    logger.error(f"测试点位 {target_position} 时发生异常: {e}")
                    results["failed"].append(target_position)
                    # 尝试回到home位置
                    try:
                        self.arm_go_home(block=block)
                    except Exception:
                        pass

            # 输出测试结果汇总
            logger.info("\n" + "=" * 60)
            logger.info("全点位测试完成")
            logger.info("=" * 60)
            logger.info(f"成功: {len(results['success'])} 个点位")
            for pos in results["success"]:
                logger.info(f"  - {pos}")
            logger.info(f"失败: {len(results['failed'])} 个点位")
            for pos in results["failed"]:
                logger.info(f"  - {pos}")
            logger.info(f"跳过: {len(results['skipped'])} 个点位")
            for pos in results["skipped"]:
                logger.info(f"  - {pos}")

            return results

        except Exception as e:
            logger.error(f"全点位测试过程中发生异常: {e}")
            return results


