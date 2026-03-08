import uuid
from typing import Any, Dict

from pylabrobot.resources import Coordinate, Deck, Resource

from unilabos.resources.eit_synthesis_station.warehouses import (
    eit_warehouse_AS,
    eit_warehouse_FF,
    eit_warehouse_MS,
    eit_warehouse_MSB,
    eit_warehouse_N,
    eit_warehouse_SC,
    eit_warehouse_T,
    eit_warehouse_TB,
    eit_warehouse_TS,
    eit_warehouse_W,
)
from unilabos.utils.log import logger


class EIT_Synthesis_Station_Deck(Deck):
    def __init__(
        self,
        name: str = "Synthesis_Station_Deck",
        size_x: float = 2800.0,
        size_y: float = 1500.0,
        size_z: float = 1500.0,
        category: str = "deck",
        setup: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(name=name, size_x=size_x, size_y=size_y, size_z=size_z, category=category)
        if not getattr(self, "unilabos_uuid", None):
            self.unilabos_uuid = str(uuid.uuid4())
        if setup:
            self.setup()

    @classmethod
    def deserialize(cls, data: Dict[str, Any], allow_marshal: bool = False):
        """
        功能:
            反序列化 EIT 合成站 Deck, 并在 children 已完整存在时跳过 setup, 避免仓库重复挂载.
        参数:
            data: Dict[str, Any], Deck 的序列化字典.
            allow_marshal: bool, 是否允许反序列化封送类型.
        返回:
            EIT_Synthesis_Station_Deck, 反序列化后的 Deck 实例.
        """
        data_copy = data.copy()
        should_skip_setup = (
            data_copy.get("setup") is True
            and bool(data_copy.get("children"))
            and (
                data_copy.get("type") == "EIT_Synthesis_Station_Deck"
                or cls is EIT_Synthesis_Station_Deck
            )
        )
        if should_skip_setup:
            # children 已包含完整仓库树时, 跳过 setup 避免再次挂载同名仓库.
            data_copy.pop("setup", None)
            logger.info("检测到带 children 的 EIT Deck 反序列化, 跳过 setup 以避免重复挂载")
        return Resource.deserialize(data_copy, allow_marshal=allow_marshal)

    def _recursive_assign_uuid(self, res) -> None:
        """
        功能:
            递归为资源及其子资源补齐 unilabos_uuid.
        参数:
            res: Resource, 待处理的资源对象.
        返回:
            无.
        """
        if not hasattr(res, "unilabos_uuid") or not res.unilabos_uuid:
            res.unilabos_uuid = str(uuid.uuid4())

        if hasattr(res, "children"):
            for child in res.children:
                self._recursive_assign_uuid(child)

    def setup(self) -> None:
        """
        功能:
            挂载 EIT 合成站的全部仓库资源, 并补齐 UUID.
        参数:
            无.
        返回:
            无.
        """
        self.warehouses = {
            "W": eit_warehouse_W("W"),
            "N": eit_warehouse_N("N"),
            "TB": eit_warehouse_TB("TB"),
            "AS": eit_warehouse_AS("AS"),
            "FF": eit_warehouse_FF("FF"),
            "MS": eit_warehouse_MS("MS"),
            "MSB": eit_warehouse_MSB("MSB"),
            "SC": eit_warehouse_SC("SC"),
            "T": eit_warehouse_T("T"),
            "TS": eit_warehouse_TS("TS"),
        }
        self.warehouse_locations = {
            "W": Coordinate(80.0, 80.0, 0.0),
            "TB": Coordinate(80.0, 560.0, 0.0),
            "N": Coordinate(80.0, 848.0, 0.0),
            "AS": Coordinate(1400.0, 80.0, 0.0),
            "FF": Coordinate(1400.0, 360.0, 0.0),
            "MS": Coordinate(1400.0, 540.0, 0.0),
            "MSB": Coordinate(1400.0, 720.0, 0.0),
            "SC": Coordinate(2100.0, 720.0, 0.0),
            "T": Coordinate(2100.0, 80.0, 0.0),
            "TS": Coordinate(2100.0, 360.0, 0.0),
        }

        for zone_key, warehouse in self.warehouses.items():
            location = self.warehouse_locations.get(zone_key)
            if location:
                self._recursive_assign_uuid(warehouse)
                self.assign_child_resource(warehouse, location)
                logger.info(f"已将仓库 {zone_key} 挂载到 Deck")

        self._recursive_assign_uuid(self)
        logger.info("EIT Deck 全量资源 UUID 校验完成")
