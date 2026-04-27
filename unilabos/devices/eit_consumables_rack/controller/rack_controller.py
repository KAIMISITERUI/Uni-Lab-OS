# coding: utf-8
"""
功能:
    耗材货架资源管理控制器.
    将 yaml 中静态声明的盘位资源类型, 与 RackClient 实时返回的光电占用信号合并,
    对外暴露按资源种类 / 按物理坐标的查询接口.
    协议层 RackClient 不做改动, 本模块只承担 "资源语义" 的组装与过滤.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from unilabos.devices.eit_consumables_rack.config.settings import RackSettings
from unilabos.devices.eit_consumables_rack.driver.rack_client import (
    RackClient,
    RackClientError,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SlotResource:
    """
    功能:
        yaml 中声明的单个盘位资源信息, 不含运行时状态.

    参数:
        layer: 层号, 1 ~ RackSettings.layers.
        position: 位号, 0 ~ RackSettings.positions_per_layer - 1.
        resource_type: 资源类型字符串, None 表示该盘位未声明 (视为空槽).
        description: 资源描述, 仅用于日志和人读, 可为空字符串.

    返回:
        无.
    """

    layer: int
    position: int
    resource_type: Optional[str]
    description: str = ""


@dataclass(frozen=True)
class SlotStatus:
    """
    功能:
        盘位静态声明 + 实时光电占用信号的合并视图, 对外查询的统一返回类型.

    参数:
        layer: 层号.
        position: 位号.
        resource_type: 资源类型字符串, None 表示未声明.
        description: 资源描述.
        occupied: 实时光电状态, True 表示该盘位有耗材, False 表示空.

    返回:
        无.
    """

    layer: int
    position: int
    resource_type: Optional[str]
    description: str
    occupied: bool


def load_resource_config(
    path: Path,
    layers: int,
    positions_per_layer: int,
) -> Dict[Tuple[int, int], SlotResource]:
    """
    功能:
        加载耗材货架资源配置 yaml, 校验范围与重复, 返回完整盘位字典.
        未在 yaml 中声明的盘位会自动补 SlotResource(resource_type=None).

    参数:
        path: yaml 配置文件路径.
        layers: 货架层数, 用于校验 layer 范围.
        positions_per_layer: 每层盘位数量, 用于校验 position 范围.

    返回:
        Dict[Tuple[int, int], SlotResource], key 为 (layer, position),
        value 为对应的 SlotResource. 字典恒含 layers * positions_per_layer 项.
    """
    if not path.exists():
        raise ValueError(f"耗材货架资源配置文件不存在: {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if isinstance(raw, dict) is False:
        raise ValueError(f"资源配置 yaml 顶层必须是 mapping: {path}")

    raw_slots = raw.get("slots")
    if isinstance(raw_slots, list) is False:
        raise ValueError(f"资源配置 yaml 缺少 slots 列表: {path}")

    declared: Dict[Tuple[int, int], SlotResource] = {}
    for index, item in enumerate(raw_slots):
        if isinstance(item, dict) is False:
            raise ValueError(f"slots[{index}] 必须是 mapping: {item!r}")

        # 校验 layer / position 字段类型与范围
        layer = item.get("layer")
        position = item.get("position")
        if isinstance(layer, int) is False or isinstance(position, int) is False:
            raise ValueError(
                f"slots[{index}] 的 layer/position 必须为整数: {item!r}"
            )
        if layer < 1 or layer > layers:
            raise ValueError(
                f"slots[{index}] layer 超出范围 1 ~ {layers}: {layer}"
            )
        if position < 0 or position > positions_per_layer - 1:
            raise ValueError(
                f"slots[{index}] position 超出范围 0 ~ {positions_per_layer - 1}: {position}"
            )

        # 校验 resource_type, 必填字符串
        resource_type = item.get("resource_type")
        if isinstance(resource_type, str) is False or resource_type == "":
            raise ValueError(
                f"slots[{index}] resource_type 必须为非空字符串: {item!r}"
            )

        # description 可选
        description_raw = item.get("description", "")
        if isinstance(description_raw, str) is False:
            raise ValueError(
                f"slots[{index}] description 必须为字符串: {item!r}"
            )

        key = (layer, position)
        if key in declared:
            raise ValueError(
                f"盘位 (layer={layer}, position={position}) 在 yaml 中重复声明"
            )
        declared[key] = SlotResource(
            layer=layer,
            position=position,
            resource_type=resource_type,
            description=description_raw,
        )

    # 未声明的盘位补成空槽, 保证字典对所有物理盘位都有条目
    full: Dict[Tuple[int, int], SlotResource] = {}
    for layer_idx in range(1, layers + 1):
        for position_idx in range(0, positions_per_layer):
            key = (layer_idx, position_idx)
            if key in declared:
                full[key] = declared[key]
            else:
                full[key] = SlotResource(
                    layer=layer_idx,
                    position=position_idx,
                    resource_type=None,
                    description="",
                )

    logger.info(
        "已加载耗材货架资源配置 path=%s 已声明=%d 总盘位=%d",
        path,
        len(declared),
        len(full),
    )
    return full


class RackController:
    """
    功能:
        耗材货架资源管理控制器.
        组合 RackClient (协议层) 与 yaml 静态资源声明 (config 层),
        每次查询都实时调用 client.query_all(), 不缓存,
        将光电占用信号与资源类型合并为 SlotStatus 对外返回.

    参数:
        client: RackClient 实例, 由调用方负责创建/连接, 也可由 from_settings 自动创建.
        slot_resources: load_resource_config 的输出, 含全部物理盘位条目.

    返回:
        无.
    """

    def __init__(
        self,
        client: RackClient,
        slot_resources: Dict[Tuple[int, int], SlotResource],
    ) -> None:
        """
        功能:
            初始化控制器, 不立即建立到货架的连接.

        参数:
            client: RackClient 实例.
            slot_resources: load_resource_config 返回的盘位资源字典.

        返回:
            无.
        """
        self._client = client
        self._slot_resources = slot_resources

    @classmethod
    def from_settings(cls, settings: Optional[RackSettings] = None) -> "RackController":
        """
        功能:
            按 RackSettings 一站式构造控制器. 同时创建 RackClient 与加载 yaml.

        参数:
            settings: 可选 RackSettings, 省略时使用默认值.

        返回:
            RackController 实例.
        """
        effective = settings if settings is not None else RackSettings()
        client = RackClient(effective)
        slot_resources = load_resource_config(
            effective.resource_config_path,
            effective.layers,
            effective.positions_per_layer,
        )
        return cls(client=client, slot_resources=slot_resources)

    # --------------------------------------------------------------
    # 连接管理 (透传到内部 RackClient)
    # --------------------------------------------------------------

    def connect(self) -> None:
        """
        功能:
            建立到货架网关的 TCP 长连接, 透传 RackClient.connect.

        参数:
            无.

        返回:
            无.
        """
        self._client.connect()

    def close(self) -> None:
        """
        功能:
            关闭货架网关连接, 透传 RackClient.close.

        参数:
            无.

        返回:
            无.
        """
        self._client.close()

    def __enter__(self) -> "RackController":
        """
        功能:
            进入 with 语句时自动连接.

        参数:
            无.

        返回:
            RackController 实例.
        """
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """
        功能:
            退出 with 语句时自动关闭连接.

        参数:
            exc_type/exc_val/exc_tb: 上下文异常信息, 仅透传不处理.

        返回:
            无.
        """
        self.close()

    # --------------------------------------------------------------
    # 高层资源查询接口
    # --------------------------------------------------------------

    def find_by_type(self, resource_type: str) -> List[SlotStatus]:
        """
        功能:
            按资源种类查询所有盘位, 实时拉取光电占用状态.
            返回值同时包含已占用与未占用的盘位, 调用方按 occupied 字段自行筛选.

        参数:
            resource_type: 资源类型字符串, 与 yaml 中 resource_type 严格相等比较.

        返回:
            List[SlotStatus], 按 (layer, position) 升序的匹配盘位列表.
            若该 resource_type 在 yaml 中未声明任何盘位, 返回空列表.
        """
        if isinstance(resource_type, str) is False or resource_type == "":
            raise ValueError(f"resource_type 必须为非空字符串: {resource_type!r}")

        snapshot = self._snapshot()
        return [item for item in snapshot if item.resource_type == resource_type]

    def get_slot(self, layer: int, position: int) -> SlotStatus:
        """
        功能:
            按物理坐标查询单个盘位的资源类型与实时占用状态.

        参数:
            layer: 层号, 1 ~ layers.
            position: 位号, 0 ~ positions_per_layer - 1.

        返回:
            SlotStatus, 单个盘位的合并视图.
        """
        key = (layer, position)
        if key not in self._slot_resources:
            raise ValueError(
                f"盘位坐标越界: layer={layer}, position={position}"
            )

        snapshot = self._snapshot()
        for item in snapshot:
            if item.layer == layer and item.position == position:
                return item
        # 理论不可达, _snapshot 一定覆盖所有物理盘位
        raise RackClientError(
            f"未在快照中找到盘位 layer={layer} position={position}"
        )

    def list_all(self) -> List[SlotStatus]:
        """
        功能:
            列出全部物理盘位的当前状态, 用于上层做整体盘点或调试.

        参数:
            无.

        返回:
            List[SlotStatus], 按 (layer, position) 升序的全量列表.
        """
        return self._snapshot()

    def list_available(
        self,
        resource_type: Optional[str] = None,
    ) -> List[SlotStatus]:
        """
        功能:
            列出当前实际有耗材的盘位 (occupied=True),
            可选按 resource_type 进一步过滤. 用于回答 "现在还有哪些资源可用".

        参数:
            resource_type: 可选资源类型, None 表示不按种类过滤.

        返回:
            List[SlotStatus], 按 (layer, position) 升序的可用盘位列表.
        """
        snapshot = self._snapshot()
        result: List[SlotStatus] = []
        for item in snapshot:
            if item.occupied is False:
                continue
            if resource_type is not None and item.resource_type != resource_type:
                continue
            result.append(item)
        return result

    # --------------------------------------------------------------
    # 内部实现
    # --------------------------------------------------------------

    def _snapshot(self) -> List[SlotStatus]:
        """
        功能:
            实时调用 client.query_all 取一次全货架光电状态,
            与 yaml 资源声明合并成 SlotStatus 列表, 按 (layer, position) 升序返回.
            单层 RS485 通讯失败时直接抛 RackClientError, 不允许降级.

        参数:
            无.

        返回:
            List[SlotStatus], 长度为 layers * positions_per_layer.
        """
        raw_layers = self._client.query_all()

        result: List[SlotStatus] = []
        # 按 (layer, position) 升序遍历, 保证返回顺序确定
        for (layer_idx, position_idx), resource in sorted(self._slot_resources.items()):
            positions = raw_layers.get(layer_idx)
            if positions is None:
                # query_all 协议中单层失败置 None, 业务侧不容忍, 直接抛异常
                raise RackClientError(
                    f"第 {layer_idx} 层 RS485 通讯失败, 无法构建快照"
                )
            if position_idx >= len(positions):
                raise RackClientError(
                    f"第 {layer_idx} 层返回长度 {len(positions)} 不足 position={position_idx}"
                )
            occupied_value = positions[position_idx]
            result.append(
                SlotStatus(
                    layer=resource.layer,
                    position=resource.position,
                    resource_type=resource.resource_type,
                    description=resource.description,
                    occupied=occupied_value != 0,
                )
            )
        return result


__all__ = [
    "SlotResource",
    "SlotStatus",
    "RackController",
    "load_resource_config",
]
