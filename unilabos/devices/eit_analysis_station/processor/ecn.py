"""
功能:
根据 SMILES 字符串分类碳原子的官能团, 并计算有效碳数(ECN).
ECN 用于 GC-FID 定量分析中的响应因子校正.
参数:
无.
返回:
无.
"""

from collections import defaultdict
from typing import Dict, Generator, Iterable, List, Tuple

try:
    from rdkit import Chem
except Exception:
    Chem = None

ary_dct = {0: "", 1: "primary", 2: "secondary", 3: "tertiary", 4: "quaternary"}
alk_dct = {2: "alkyne", 3: "alkene", 4: "alkane"}
dldct: Dict[int, str] = {}


def _parse_smiles_to_molecule(smiles: str):
    """
    功能:
    使用 RDKit 解析 SMILES, 并返回基础分子对象.
    参数:
    smiles: str, 化合物 SMILES 字符串.
    返回:
    RDKit Mol, 不含显式氢的分子对象.
    """
    smiles_text = str(smiles).strip()
    if smiles_text == "":
        raise ValueError("SMILES 不能为空")
    if Chem is None:
        raise RuntimeError("未安装 RDKit, 无法计算 ECN")

    try:
        molecule = Chem.MolFromSmiles(smiles_text)
    except Exception as exc:
        raise ValueError(f"SMILES 解析失败: {smiles_text}, 错误={exc}") from exc

    if molecule is None:
        raise ValueError(f"SMILES 解析失败: {smiles_text}")

    return Chem.Mol(molecule)


def _collect_compatible_cycle_nodes(molecule) -> List[int]:
    """
    功能:
    复现历史 ECN 实现中的环系兼容口径.
    仅将偶数元且大小不小于 4 的环标记为候选环原子.
    参数:
    molecule: RDKit Mol, 含显式氢的分子对象.
    返回:
    List[int], 满足兼容规则的环原子编号列表.
    """
    cycle_nodes: List[int] = []
    ring_info = molecule.GetRingInfo()
    for ring_atoms in ring_info.AtomRings():
        if len(ring_atoms) % 2 == 0 and len(ring_atoms) >= 4:
            for atom_idx in ring_atoms:
                if atom_idx not in cycle_nodes:
                    cycle_nodes.append(atom_idx)
    return cycle_nodes


def molecule2carbontypes(molecule) -> Generator[Tuple[str, str], None, None]:
    """
    功能:
    将 RDKit 分子对象转换为碳原子分类结果.
    参数:
    molecule: RDKit Mol, 不含或含显式氢均可.
    返回:
    Generator[Tuple[str, str], None, None], 每个碳原子的 (醇级别, 官能团类型).
    """
    if Chem is None:
        raise RuntimeError("未安装 RDKit, 无法计算 ECN")
    if molecule is None:
        raise ValueError("RDKit 分子对象不能为空")

    explicit_h_molecule = Chem.AddHs(Chem.Mol(molecule))
    cycle_nodes = _collect_compatible_cycle_nodes(explicit_h_molecule)

    global dldct
    dldct = {
        atom.GetIdx(): atom.GetSymbol()
        for atom in explicit_h_molecule.GetAtoms()
    }

    for atom in explicit_h_molecule.GetAtoms():
        if atom.GetSymbol() != "C":
            continue

        nbors1_parts: List[str] = []
        nbors2_parts: List[str] = []
        edge01: List[int] = []
        edge12: List[List[int]] = []

        for neighbor in atom.GetNeighbors():
            neighbor_idx = neighbor.GetIdx()
            nbors1_parts.append(dldct[neighbor_idx])
            edge01.append(neighbor_idx)

            second_neighbors: List[int] = []
            for second_neighbor in neighbor.GetNeighbors():
                second_idx = second_neighbor.GetIdx()
                nbors2_parts.append(dldct[second_idx])
                if second_idx != atom.GetIdx():
                    second_neighbors.append(second_idx)
            edge12.append(second_neighbors)

        nbors1 = "".join(sorted(nbors1_parts))
        nbors2 = "".join(sorted(nbors2_parts))
        is_cycle = atom.GetIdx() in cycle_nodes

        yield classify(nbors1, nbors2, edge01, edge12, is_cycle)


def smiles2carbontypes(smiles: str) -> Generator[Tuple[str, str], None, None]:
    """
    功能:
    将 SMILES 字符串转换为碳原子分类结果.
    参数:
    smiles: str, 化合物 SMILES 字符串.
    返回:
    Generator[Tuple[str, str], None, None], 每个碳原子的 (醇级别, 官能团类型).
    """
    molecule = _parse_smiles_to_molecule(smiles)
    yield from molecule2carbontypes(molecule)


def classify(
    nbors1: str,
    nbors2: str,
    edge01: Iterable[int],
    edge12: Iterable[Iterable[int]],
    is_cycle: bool,
) -> Tuple[str, str]:
    """
    功能:
    根据碳原子的邻居信息判断其官能团类型.
    参数:
    nbors1: str, 最近邻原子元素字符串, 已排序.
    nbors2: str, 次近邻原子元素字符串, 已排序.
    edge01: Iterable[int], 最近邻原子编号列表.
    edge12: Iterable[Iterable[int]], 次近邻原子编号分组列表.
    is_cycle: bool, 当前碳原子是否属于兼容环系.
    返回:
    Tuple[str, str], (醇级别, 官能团类型).
    """
    del nbors2

    ary = nbors1.count("C")
    hyd = nbors1.count("H")

    ln1 = len(nbors1)
    if ln1 == ary + hyd:
        if ln1 == 3 and is_cycle:
            return ary_dct[ary], "aromatic"
        return ary_dct[ary], alk_dct[ln1]

    if nbors1 == "CCO":
        return "", "ketone"
    if nbors1 == "CHO":
        return "", "aldehyde"

    if nbors1 == "CHHO" or nbors1 == "CCHO":
        for index, neighbor_idx in enumerate(edge01):
            if dldct[neighbor_idx] == "O":
                second_neighbors = list(edge12[index])
                if len(second_neighbors) == 1 and dldct[second_neighbors[0]] == "H":
                    return ary_dct[ary], "alcohol"
        return "", "ether"

    if nbors1 == "COO":
        for index, neighbor_idx in enumerate(edge01):
            if dldct[neighbor_idx] == "O":
                second_neighbors = list(edge12[index])
                if len(second_neighbors) == 1 and dldct[second_neighbors[0]] == "H":
                    return "", "carboxylic acid"
        return "", "acid anhydride or ester"

    if "N" in nbors1:
        if nbors1 == "CNO":
            return "", "amide"
        if nbors1 == "CN":
            return "", "nitrile"

        for index, neighbor_idx in enumerate(edge01):
            if dldct[neighbor_idx] == "N":
                second_neighbors = list(edge12[index])
                amine_ary = 1
                for second_idx in second_neighbors:
                    if dldct[second_idx] == "C":
                        return "", "amine, or carbon adjacent to amide"
                    if dldct[second_idx] == "C":
                        amine_ary += 1
                return ary_dct[amine_ary], "amine"

    if "S" in nbors1:
        for index, neighbor_idx in enumerate(edge01):
            if dldct[neighbor_idx] == "S":
                second_neighbors = list(edge12[index])
                if len(second_neighbors) == 1 and dldct[second_neighbors[0]] == "H":
                    return "", "thiol"
                return "", "sulfide"

    if "F" in nbors1 or "Cl" in nbors1 or "Br" in nbors1 or "I" in nbors1:
        return ary_dct[ary], "halide"

    return "", "unknown"


class_dct = {
    "alkane": "aliphatic",
    "alkene": "olefinic",
    "alkyne": "acetylinic",
    "carboxylic acid": "carboxyl",
    "aldehyde": "carbonyl",
    "ketone": "carbonyl",
    "ester": "carboxyl",
    "nitrile": "nitrile",
    "ether": "ether",
    "amine": "amine",
    "alcohol": "alcohol",
    "acid anhydride": "ester",
    "amide": "aliphatic",
    "acid anhydride or ester": "ester",
    "aromatic": "aromatic",
}


def factory() -> int:
    """
    功能:
    为 defaultdict 提供默认值 0.
    参数:
    无.
    返回:
    int, 默认值 0.
    """
    return 0


class_dct = defaultdict(factory, class_dct)
u = 0

ecn_dct = {
    "aliphatic": 1.00,
    "aromatic": 1.00,
    "olefinic": 0.95,
    "acetylinic": 1.30,
    "carbonyl": u,
    "carboxyl": u,
    "nitrile": 0.30,
    "ether": -1.00 + 1.5,
    "primary alcohol": -0.50 + 1,
    "secondary alcohol": -0.75 + 1,
    "tertiary alcohol": -0.25 + 1,
    "amine": u + 1,
}

ecn_dct = defaultdict(factory, ecn_dct)
