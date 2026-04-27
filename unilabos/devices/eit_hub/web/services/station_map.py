# -*- coding: utf-8 -*-
"""
功能:
    提供 AGV 工站地图布局. 由于 agv_config.STATION_POSITIONS 只定义了工站 ID 到
    名称的映射, 所以此处维护 Web 可视化地图的默认布局坐标并支持持久化覆盖.
    坐标为 0-100 的相对单位, 由前端按画布宽高缩放绘制.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from unilabos.devices.eit_agv.config.agv_config import STATION_POSITIONS

logger = logging.getLogger("EITHubStationMap")

MAP_LAYOUT_PATH = Path(__file__).resolve().parent.parent / "data" / "agv_station_layout.json"

# 工站布局, 相对坐标 (x, y) 取值范围 [0, 100]
DEFAULT_STATION_LAYOUT: Dict[str, Dict[str, Any]] = {
    "LM0": {"x": 10, "y": 85, "label": "检修点"},
    "LM1": {"x": 30, "y": 20, "label": "合成工站"},
    "LM2": {"x": 60, "y": 20, "label": "分析工站"},
    "LM3": {"x": 90, "y": 20, "label": "浓缩工站"},
    "LM4": {"x": 50, "y": 50, "label": "货架"},
    "CP6": {"x": 90, "y": 85, "label": "充电站"},
    "PP5": {"x": 75, "y": 85, "label": "待命点"},
}


def _coerce_percent(value: Any) -> float:
    """
    功能:
        将输入值转换为地图百分比坐标并校验范围.
    参数:
        value: Any, 前端提交的 x 或 y 坐标.
    返回:
        float, 0 到 100 范围内的百分比坐标.
    """
    try:
        percent = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("地图坐标必须是数字.") from exc

    if (0 <= percent <= 100) is False:
        raise ValueError("地图坐标必须在 0 到 100 之间.")
    return percent


def _default_station_layout() -> Dict[str, Dict[str, Any]]:
    """
    功能:
        生成默认工站布局副本, 避免调用方修改模块级默认值.
    返回:
        Dict[str, Dict[str, Any]], 工站布局字典.
    """
    layout: Dict[str, Dict[str, Any]] = {}
    for station_id, item in DEFAULT_STATION_LAYOUT.items():
        layout[station_id] = {
            "x": float(item.get("x", 50)),
            "y": float(item.get("y", 50)),
            "label": str(item.get("label", station_id)),
        }
    return layout


def load_station_layout(layout_path: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """
    功能:
        读取持久化工站布局, 并与默认布局合并.
    参数:
        layout_path: Optional[Path], 自定义布局文件路径, 默认使用 Web data 目录.
    返回:
        Dict[str, Dict[str, Any]], 合并后的工站布局.
    """
    target_path = layout_path if layout_path is not None else MAP_LAYOUT_PATH
    layout = _default_station_layout()
    if target_path.is_file() is False:
        return layout

    with target_path.open("r", encoding="utf-8") as file_obj:
        payload = json.load(file_obj)

    stations = payload.get("stations") if isinstance(payload, dict) else None
    if isinstance(stations, list) is False:
        raise ValueError("地图布局文件格式错误, stations 必须是列表.")

    for station in stations:
        if isinstance(station, dict) is False:
            raise ValueError("地图布局文件格式错误, 工站项必须是对象.")
        station_id = str(station.get("id", "")).strip().upper()
        if (station_id in layout) is False:
            raise ValueError(f"地图布局包含未知工站: {station_id}.")
        layout[station_id]["x"] = _coerce_percent(station.get("x"))
        layout[station_id]["y"] = _coerce_percent(station.get("y"))

    return layout


def save_station_layout(stations: List[Dict[str, Any]], layout_path: Optional[Path] = None) -> Dict[str, List[Dict]]:
    """
    功能:
        保存前端编辑后的工站相对坐标, 并返回更新后的地图结构.
    参数:
        stations: List[Dict[str, Any]], 工站坐标列表, 每项包含 id/x/y.
        layout_path: Optional[Path], 自定义布局文件路径, 默认使用 Web data 目录.
    返回:
        Dict[str, List[Dict]], 更新后的地图 payload.
    """
    if len(stations) == 0:
        raise ValueError("工站布局不能为空.")

    target_path = layout_path if layout_path is not None else MAP_LAYOUT_PATH
    layout = load_station_layout(target_path)
    seen_station_ids = set()

    for station in stations:
        station_id = str(station.get("id", "")).strip().upper()
        if station_id == "":
            raise ValueError("工站 ID 不能为空.")
        if (station_id in DEFAULT_STATION_LAYOUT) is False:
            raise ValueError(f"未知工站 ID: {station_id}.")
        if (station_id in seen_station_ids) is True:
            raise ValueError(f"工站 ID 重复: {station_id}.")
        seen_station_ids.add(station_id)

        layout[station_id]["x"] = _coerce_percent(station.get("x"))
        layout[station_id]["y"] = _coerce_percent(station.get("y"))

    payload = {
        "stations": [
            {
                "id": station_id,
                "x": layout[station_id]["x"],
                "y": layout[station_id]["y"],
            }
            for station_id in STATION_POSITIONS.keys()
        ]
    }
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with target_path.open("w", encoding="utf-8") as file_obj:
        json.dump(payload, file_obj, ensure_ascii=False, indent=2)
        file_obj.write("\n")

    logger.info("AGV 工站地图布局已保存: %s", target_path)
    return build_map_payload(target_path)


def build_map_payload(layout_path: Optional[Path] = None) -> Dict[str, List[Dict]]:
    """
    功能:
        将 STATION_POSITIONS 与前端布局合并为一个可直接下发到前端的结构.
    参数:
        layout_path: Optional[Path], 自定义布局文件路径, 默认使用 Web data 目录.
    返回:
        Dict[str, List[Dict]], 包含 stations 列表, 每项含 id/name/description/label/x/y.
    """
    layout_config = load_station_layout(layout_path)
    stations: List[Dict] = []
    for station_id, meta in STATION_POSITIONS.items():
        layout = layout_config.get(station_id, {"x": 50, "y": 50, "label": meta.get("name", station_id)})
        stations.append(
            {
                "id": station_id,
                "name": meta.get("name", ""),
                "description": meta.get("description", ""),
                "label": layout.get("label", meta.get("name", station_id)),
                "x": float(layout.get("x", 50)),
                "y": float(layout.get("y", 50)),
            }
        )
    return {"stations": stations}
