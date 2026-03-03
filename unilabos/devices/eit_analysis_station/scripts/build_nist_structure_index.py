#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    构建 NIST 本地结构图索引.
    输入 mainlib_export.msp 与对应 .MOL 目录, 输出 index.json 与 PNG 结构图目录.
参数:
    无.
返回:
    无.
"""

import argparse
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def _normalize_cas_digits(cas_number: str) -> str:
    """
    功能:
        将 CAS 字符串标准化为纯数字.
    参数:
        cas_number: CAS 字符串.
    返回:
        str, 纯数字 CAS.
    """
    return re.sub(r"\D", "", cas_number.strip())


def _extract_nist_id_from_comment(comment: str) -> Optional[int]:
    """
    功能:
        从 MSP Comment 行中提取 NIST MS#.
    参数:
        comment: Comment 行内容.
    返回:
        Optional[int], NIST MS#.
    """
    match = re.search(r"NIST\s+MS#\s*(\d+)", comment, re.IGNORECASE)
    if match is None:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _parse_mainlib_export_records(msp_path: Path) -> List[Dict[str, Optional[str]]]:
    """
    功能:
        解析 mainlib_export.msp 的记录元数据.
    参数:
        msp_path: MSP 文件路径.
    返回:
        List[Dict], 记录列表.
    """
    records: List[Dict[str, Optional[str]]] = []
    current: Dict[str, Optional[str]] = {
        "name": None,
        "cas_digits": None,
        "record_id": None,
        "nist_id": None,
    }

    def _flush_record() -> None:
        if current["name"] is None and current["cas_digits"] is None and current["nist_id"] is None:
            return
        records.append(
            {
                "name": current["name"],
                "cas_digits": current["cas_digits"],
                "record_id": current["record_id"],
                "nist_id": current["nist_id"],
            }
        )

    for raw_line in msp_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()

        if line == "":
            _flush_record()
            current = {"name": None, "cas_digits": None, "record_id": None, "nist_id": None}
            continue

        if line.startswith("Name:"):
            current["name"] = line.split(":", 1)[1].strip()
            continue

        if line.startswith("CASNO:"):
            cas_digits = _normalize_cas_digits(line.split(":", 1)[1])
            current["cas_digits"] = cas_digits if cas_digits else None
            continue

        if line.startswith("ID:"):
            record_id = line.split(":", 1)[1].strip()
            current["record_id"] = record_id if record_id else None
            continue

        if line.startswith("Comment:"):
            nist_id = _extract_nist_id_from_comment(line)
            if nist_id is not None:
                current["nist_id"] = str(nist_id)
            continue

    _flush_record()
    return records


def _scan_mol_files(seed_mol_dir: Path) -> Dict[str, Path]:
    """
    功能:
        扫描 .MOL 目录并建立大小写不敏感文件索引.
    参数:
        seed_mol_dir: .MOL 目录路径.
    返回:
        Dict[str, Path], 小写文件名到路径映射.
    """
    file_map: Dict[str, Path] = {}
    for mol_path in seed_mol_dir.iterdir():
        if mol_path.is_file() is False:
            continue
        if mol_path.suffix.lower() != ".mol":
            continue
        file_map[mol_path.name.lower()] = mol_path
    return file_map


def _select_mol_path(record: Dict[str, Optional[str]], mol_map: Dict[str, Path]) -> Optional[Path]:
    """
    功能:
        按优先级选择记录对应的 MOL 文件.
        优先级: N<nist_id>.MOL -> S<cas_digits>.MOL -> ID<id>.MOL.
    参数:
        record: MSP 记录元数据.
        mol_map: MOL 文件索引.
    返回:
        Optional[Path], 命中的 MOL 路径.
    """
    candidate_names: List[str] = []

    nist_id = record.get("nist_id")
    if nist_id:
        candidate_names.append(f"N{nist_id}.MOL")

    cas_digits = record.get("cas_digits")
    if cas_digits:
        candidate_names.append(f"S{cas_digits}.MOL")

    record_id = record.get("record_id")
    if record_id:
        candidate_names.append(f"ID{record_id}.MOL")

    for candidate_name in candidate_names:
        lower_name = candidate_name.lower()
        if lower_name in mol_map:
            return mol_map[lower_name]

    return None


def _render_mol_to_png(mol_path: Path, png_path: Path, image_size: int) -> bool:
    """
    功能:
        使用 RDKit 将 MOL 渲染为 PNG.
    参数:
        mol_path: MOL 文件路径.
        png_path: PNG 输出路径.
        image_size: 图片边长像素.
    返回:
        bool, 渲染是否成功.
    """
    try:
        from rdkit import Chem
        from rdkit.Chem import Draw
    except ImportError:
        logger.error("未安装 RDKit, 无法构建本地结构索引.")
        return False

    try:
        mol = Chem.MolFromMolFile(str(mol_path), sanitize=True, removeHs=False)
        if mol is None:
            mol = Chem.MolFromMolFile(str(mol_path), sanitize=False, removeHs=False)
        if mol is None:
            logger.warning("MOL 解析失败: %s", mol_path)
            return False

        png_path.parent.mkdir(parents=True, exist_ok=True)
        image = Draw.MolToImage(mol, size=(image_size, image_size))
        image.save(str(png_path))
        return True
    except Exception as exc:
        logger.warning("渲染结构图失败: %s, 错误: %s", mol_path, exc)
        return False


def build_nist_structure_index(
    seed_msp: Path,
    seed_mol_dir: Path,
    index_dir: Path,
    image_size: int = 200,
) -> Dict[str, int]:
    """
    功能:
        构建 NIST 本地结构索引并输出 index.json.
    参数:
        seed_msp: mainlib_export.msp 路径.
        seed_mol_dir: 对应 .MOL 目录路径.
        index_dir: 索引输出目录.
        image_size: 结构图渲染尺寸.
    返回:
        Dict[str, int], 构建统计信息.
    """
    if seed_msp.exists() is False:
        raise FileNotFoundError(f"未找到 MSP 文件: {seed_msp}")

    if seed_mol_dir.exists() is False:
        raise FileNotFoundError(f"未找到 MOL 目录: {seed_mol_dir}")

    index_dir.mkdir(parents=True, exist_ok=True)
    png_dir = index_dir / "png"
    png_dir.mkdir(parents=True, exist_ok=True)

    records = _parse_mainlib_export_records(seed_msp)
    mol_map = _scan_mol_files(seed_mol_dir)

    by_nist_id: Dict[str, str] = {}
    by_cas_digits: Dict[str, str] = {}

    stats = {
        "total_records": 0,
        "rendered_records": 0,
        "missing_mol_records": 0,
        "render_failed_records": 0,
        "no_key_records": 0,
    }

    for record in records:
        stats["total_records"] += 1

        mol_path = _select_mol_path(record, mol_map)
        if mol_path is None:
            stats["missing_mol_records"] += 1
            continue

        nist_id = record.get("nist_id")
        cas_digits = record.get("cas_digits")
        record_id = record.get("record_id")

        if nist_id:
            png_name = f"N{nist_id}.png"
        elif cas_digits:
            png_name = f"S{cas_digits}.png"
        elif record_id:
            png_name = f"ID{record_id}.png"
        else:
            stats["no_key_records"] += 1
            continue

        png_path = png_dir / png_name
        if png_path.exists() is False:
            rendered = _render_mol_to_png(mol_path, png_path, image_size)
            if rendered is False:
                stats["render_failed_records"] += 1
                continue

        rel_png = png_path.relative_to(index_dir).as_posix()

        if nist_id and nist_id not in by_nist_id:
            by_nist_id[nist_id] = rel_png

        if cas_digits and cas_digits not in by_cas_digits:
            by_cas_digits[cas_digits] = rel_png

        stats["rendered_records"] += 1

    payload = {
        "version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "seed_msp": str(seed_msp),
        "seed_mol_dir": str(seed_mol_dir),
        "by_nist_id": by_nist_id,
        "by_cas_digits": by_cas_digits,
        "stats": stats,
    }

    index_path = index_dir / "index.json"
    index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info(
        "结构索引构建完成: 记录=%d, 成功=%d, 缺失MOL=%d, 渲染失败=%d, 索引=%s",
        stats["total_records"],
        stats["rendered_records"],
        stats["missing_mol_records"],
        stats["render_failed_records"],
        index_path,
    )
    return stats


def _build_arg_parser() -> argparse.ArgumentParser:
    """
    功能:
        构建命令行参数解析器.
    参数:
        无.
    返回:
        argparse.ArgumentParser.
    """
    parser = argparse.ArgumentParser(description="构建 NIST 本地结构图索引")
    parser.add_argument(
        "--seed-msp",
        default=r"D:\NIST23\MSSEARCH\mainlib_export.msp",
        help="NIST 导出的 MSP 文件路径",
    )
    parser.add_argument(
        "--seed-mol-dir",
        default=r"D:\NIST23\MSSEARCH\mainlib_export.MOL",
        help="与 MSP 对应的 .MOL 目录路径",
    )
    parser.add_argument(
        "--index-dir",
        default=r"D:\Uni-Lab-OS\unilabos\devices\eit_analysis_station\data\nist_structure_index",
        help="索引输出目录",
    )
    parser.add_argument("--image-size", type=int, default=200, help="结构图尺寸")
    return parser


def main() -> None:
    """
    功能:
        命令行入口.
    参数:
        无.
    返回:
        无.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = _build_arg_parser()
    args = parser.parse_args()

    build_nist_structure_index(
        seed_msp=Path(args.seed_msp),
        seed_mol_dir=Path(args.seed_mol_dir),
        index_dir=Path(args.index_dir),
        image_size=args.image_size,
    )


if __name__ == "__main__":
    main()
