# -*- coding: utf-8 -*-
"""
功能:
    提供 AGV 工站地图布局. 由于 agv_config.STATION_POSITIONS 只定义了工站 ID 到
    名称的映射, 没有坐标, 所以此处硬编码 Web 可视化地图的布局坐标.
    坐标为 0-100 的相对单位, 由前端按画布宽高缩放绘制.
"""

from __future__ import annotations

from typing import Dict, List

from unilabos.devices.eit_agv.config.agv_config import STATION_POSITIONS


# 工站布局, 相对坐标 (x, y) 取值范围 [0, 100]
STATION_LAYOUT: Dict[str, Dict[str, float]] = {
    "LM0": {"x": 10, "y": 85, "label": "检修点"},
    "LM1": {"x": 30, "y": 20, "label": "合成工站"},
    "LM2": {"x": 60, "y": 20, "label": "分析工站"},
    "LM3": {"x": 90, "y": 20, "label": "浓缩工站"},
    "LM4": {"x": 50, "y": 50, "label": "货架"},
    "CP6": {"x": 90, "y": 85, "label": "充电站"},
    "PP5": {"x": 75, "y": 85, "label": "待充点"},
}


def build_map_payload() -> Dict[str, List[Dict]]:
    """
    功能:
        将 STATION_POSITIONS 与前端布局合并为一个可直接下发到前端的结构.
    返回:
        Dict[str, List[Dict]], 包含 stations 列表, 每项含 id/name/description/label/x/y.
    """
    stations: List[Dict] = []
    for station_id, meta in STATION_POSITIONS.items():
        layout = STATION_LAYOUT.get(station_id, {"x": 50, "y": 50, "label": meta.get("name", station_id)})
        stations.append({
            "id": station_id,
            "name": meta.get("name", ""),
            "description": meta.get("description", ""),
            "label": layout.get("label", meta.get("name", station_id)),
            "x": float(layout.get("x", 50)),
            "y": float(layout.get("y", 50)),
        })
    return {"stations": stations}
