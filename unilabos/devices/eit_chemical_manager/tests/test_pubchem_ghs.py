# -*- coding: utf-8 -*-
"""
功能:
    覆盖 PubChem GHS 危害信息解析逻辑.
"""

from __future__ import annotations

from unilabos.devices.eit_chemical_manager.driver.pubchem_ghs import (
    parse_pubchem_ghs_payload,
)


def _ghs_item(name: str, strings: list[str], *, icons: list[str] | None = None) -> dict:
    """
    功能:
        构造最小 PUG-View Information 节点.
    参数:
        name: str, Information Name.
        strings: list[str], StringWithMarkup 文本.
        icons: list[str] | None, 图标编码列表.
    返回:
        dict, PUG-View Information 节点.
    """
    markup = []
    if icons is not None:
        for icon in icons:
            markup.append({
                "Type": "Icon",
                "URL": f"https://pubchem.ncbi.nlm.nih.gov/images/ghs/{icon}.svg",
                "Extra": icon,
            })
    return {
        "Name": name,
        "Value": {
            "StringWithMarkup": [
                {
                    "String": text,
                    "Markup": markup if idx == 0 else [],
                }
                for idx, text in enumerate(strings)
            ],
        },
    }


def _payload(items: list[dict]) -> dict:
    """
    功能:
        构造最小 PUG-View GHS Classification 响应.
    参数:
        items: list[dict], Information 节点列表.
    返回:
        dict, PUG-View 响应.
    """
    return {
        "Record": {
            "Section": [
                {
                    "TOCHeading": "Safety and Hazards",
                    "Section": [
                        {
                            "TOCHeading": "Hazards Identification",
                            "Section": [
                                {
                                    "TOCHeading": "GHS Classification",
                                    "Information": items,
                                },
                            ],
                        },
                    ],
                },
            ],
        },
    }


def test_parse_benzene_high_health_hazards() -> None:
    """功能: 苯的 GHS 信息可识别致癌, 致突变和长期器官损害."""
    data = _payload([
        _ghs_item("Pictogram(s)", ["   "], icons=["GHS02", "GHS07", "GHS08"]),
        _ghs_item("Signal", ["Danger"]),
        _ghs_item(
            "GHS Hazard Statements",
            [
                "H225 (100%): Highly Flammable liquid and vapor [Danger Flammable liquids]",
                "H304 (100%): May be fatal if swallowed and enters airways [Danger Aspiration hazard]",
                "H315 (100%): Causes skin irritation [Warning Skin corrosion/irritation]",
                "H319 (100%): Causes serious eye irritation [Warning Serious eye damage/eye irritation]",
                "H340 (100%): May cause genetic defects [Danger Germ cell mutagenicity]",
                "H350 (100%): May cause cancer [Danger Carcinogenicity]",
                "H372 (100%): Causes damage to organs through prolonged or repeated exposure [Danger Specific target organ toxicity, repeated exposure]",
            ],
        ),
        _ghs_item(
            "Precautionary Statement Codes",
            ["P203, P210, P260, P280, P301+P316, P370+P378, and P501"],
        ),
    ])

    result = parse_pubchem_ghs_payload(data, cid=241)

    assert result["hazard_signal"] == "Danger"
    assert result["hazard_pictograms"] == ["GHS02", "GHS07", "GHS08"]
    codes = [item["code"] for item in result["hazard_statements"]]
    assert "H340" in codes
    assert "H350" in codes
    assert "H372" in codes
    assert "P301+P316" in result["precautionary_codes"]
    assert result["hazard_source_cid"] == 241


def test_parse_ethanol_common_hazards() -> None:
    """功能: 乙醇的普通易燃和眼刺激危害可被识别."""
    data = _payload([
        _ghs_item("Pictogram(s)", ["   "], icons=["GHS02", "GHS07"]),
        _ghs_item("Signal", ["Danger"]),
        _ghs_item(
            "GHS Hazard Statements",
            [
                "H225 (> 99.9%): Highly Flammable liquid and vapor [Danger Flammable liquids]",
                "H319 (37.7%): Causes serious eye irritation [Warning Serious eye damage/eye irritation]",
            ],
        ),
    ])

    result = parse_pubchem_ghs_payload(data, cid=702)

    assert result["hazard_signal"] == "Danger"
    assert result["hazard_pictograms"] == ["GHS02", "GHS07"]
    assert [item["code"] for item in result["hazard_statements"]] == ["H225", "H319"]


def test_parse_missing_ghs_returns_empty_dict() -> None:
    """功能: 缺少 GHS Classification 时返回空字典, 不影响上层新增和编辑."""
    result = parse_pubchem_ghs_payload({"Record": {"Section": []}}, cid=1)

    assert result == {}
