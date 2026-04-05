"""
功能:
    根据已确认的主表规则, 按原子局部环境计算分子的有效碳数.
    当前仅实现主表中的 C, O, Cl, N 规则, 暂不包含补充表.

参数:
    无.

返回:
    无.
"""

import logging
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

try:
    from rdkit import Chem
    from rdkit.Chem.rdchem import BondType, HybridizationType
except Exception:
    Chem = None
    BondType = None
    HybridizationType = None

logger = logging.getLogger(__name__)

CARBON_RULE_VALUES = {
    "芳香烃": 1.0,
    "腈类": 0.30,
    "羧基": 0.032,
    "羰基": 0.0,
    "炔烃": 1.30,
    "烯烃": 0.95,
    "烷烃类": 1.0,
}

OXYGEN_RULE_VALUES = {
    "酚": -0.25,
    "伯醇": -0.60,
    "仲醇": -0.75,
    "叔醇": -0.25,
    "醚": -1.0,
}

CHLORINE_RULE_VALUES = {
    "一个烷烃碳原子上有两个或更多": -0.12,
    "烯烃碳原子上": 0.05,
}

AMINE_RULE_VALUES = {
    "一级胺": -0.60,
    "二级胺": -0.75,
    "三级胺": -0.25,
    "苯胺型伯胺": -0.25,
}


@dataclass(frozen=True)
class AtomContribution:
    """
    功能:
        记录单个原子的 ECN 贡献信息.

    参数:
        atom_index: 原子编号, 从 0 开始.
        atom_symbol: 原子元素符号.
        rule_name: 命中的主表规则名称.
        value: 该原子的 ECN 贡献值.

    返回:
        AtomContribution, 单原子贡献记录.
    """

    atom_index: int
    atom_symbol: str
    rule_name: str
    value: float


def _ensure_rdkit_ready() -> None:
    """
    功能:
        确保 RDKit 可用.

    参数:
        无.

    返回:
        无.
    """

    if Chem is None:
        raise RuntimeError("未安装 RDKit, 无法计算 ECN")


def _parse_smiles_to_molecule(smiles: str) -> Any:
    """
    功能:
        使用 RDKit 解析 SMILES 并返回分子对象.

    参数:
        smiles: 化合物的 SMILES 字符串.

    返回:
        RDKit Mol, 解析成功后的分子对象.
    """

    smiles_text = str(smiles).strip()
    if smiles_text == "":
        raise ValueError("SMILES 不能为空")

    _ensure_rdkit_ready()

    try:
        molecule = Chem.MolFromSmiles(smiles_text)
    except Exception as exc:
        raise ValueError(f"SMILES 解析失败: {smiles_text}, 错误={exc}") from exc

    if molecule is None:
        raise ValueError(f"SMILES 解析失败: {smiles_text}")

    return Chem.Mol(molecule)


def _get_neighbor_atoms(atom: Any, atomic_num: Optional[int] = None) -> List[Any]:
    """
    功能:
        返回目标原子的邻居原子列表, 可按元素筛选.

    参数:
        atom: RDKit Atom 对象.
        atomic_num: 可选原子序数, None 表示不过滤.

    返回:
        List[Any], 邻居原子列表.
    """

    neighbors = list(atom.GetNeighbors())
    if atomic_num is None:
        return neighbors
    return [neighbor for neighbor in neighbors if neighbor.GetAtomicNum() == atomic_num]


def _has_bond_to(atom: Any, atomic_num: int, bond_type: Any) -> bool:
    """
    功能:
        判断原子是否与指定元素存在指定键型的连接.

    参数:
        atom: RDKit Atom 对象.
        atomic_num: 邻居原子的原子序数.
        bond_type: RDKit 键类型.

    返回:
        bool, 是否存在匹配键.
    """

    for bond in atom.GetBonds():
        neighbor = bond.GetOtherAtom(atom)
        if neighbor.GetAtomicNum() == atomic_num and bond.GetBondType() == bond_type:
            return True
    return False


def _count_neighbor_atoms(atom: Any, atomic_num: int) -> int:
    """
    功能:
        统计原子直接相连的指定元素个数.

    参数:
        atom: RDKit Atom 对象.
        atomic_num: 邻居原子的原子序数.

    返回:
        int, 匹配邻居数量.
    """

    return sum(1 for neighbor in atom.GetNeighbors() if neighbor.GetAtomicNum() == atomic_num)


def _is_carboxyl_carbon(atom: Any) -> bool:
    """
    功能:
        判断碳原子是否为羧基碳, 即 C(=O)-O.

    参数:
        atom: RDKit Atom 对象.

    返回:
        bool, 是否为羧基碳.
    """

    if atom.GetAtomicNum() != 6:
        return False

    has_double_bond_oxygen = False
    has_single_bond_oxygen = False
    for bond in atom.GetBonds():
        neighbor = bond.GetOtherAtom(atom)
        if neighbor.GetAtomicNum() != 8:
            continue
        if bond.GetBondType() == BondType.DOUBLE:
            has_double_bond_oxygen = True
        if bond.GetBondType() == BondType.SINGLE:
            has_single_bond_oxygen = True
    return has_double_bond_oxygen and has_single_bond_oxygen


def _is_carbonyl_carbon(atom: Any) -> bool:
    """
    功能:
        判断碳原子是否为羰基碳, 即存在 C=O 且不属于羧基规则.

    参数:
        atom: RDKit Atom 对象.

    返回:
        bool, 是否为羰基碳.
    """

    if atom.GetAtomicNum() != 6:
        return False
    if _is_carboxyl_carbon(atom) is True:
        return False
    return _has_bond_to(atom, atomic_num=8, bond_type=BondType.DOUBLE)


def _is_nitrile_carbon(atom: Any) -> bool:
    """
    功能:
        判断碳原子是否为腈基碳, 即存在 C#N.

    参数:
        atom: RDKit Atom 对象.

    返回:
        bool, 是否为腈基碳.
    """

    if atom.GetAtomicNum() != 6:
        return False
    return _has_bond_to(atom, atomic_num=7, bond_type=BondType.TRIPLE)


def _is_alkyne_carbon(atom: Any) -> bool:
    """
    功能:
        判断碳原子是否为炔烃碳, 即存在 C#C.

    参数:
        atom: RDKit Atom 对象.

    返回:
        bool, 是否为炔烃碳.
    """

    if atom.GetAtomicNum() != 6:
        return False
    return _has_bond_to(atom, atomic_num=6, bond_type=BondType.TRIPLE)


def _is_alkene_carbon(atom: Any) -> bool:
    """
    功能:
        判断碳原子是否为非芳香烯烃碳, 即存在 C=C.

    参数:
        atom: RDKit Atom 对象.

    返回:
        bool, 是否为烯烃碳.
    """

    if atom.GetAtomicNum() != 6:
        return False
    if atom.GetIsAromatic() is True:
        return False
    return _has_bond_to(atom, atomic_num=6, bond_type=BondType.DOUBLE)


def _is_saturated_carbon(atom: Any) -> bool:
    """
    功能:
        判断碳原子是否为饱和碳, 用于氯代烷烃规则判定.

    参数:
        atom: RDKit Atom 对象.

    返回:
        bool, 是否为饱和碳.
    """

    if atom.GetAtomicNum() != 6:
        return False
    if atom.GetIsAromatic() is True:
        return False
    for bond in atom.GetBonds():
        if bond.GetBondType() != BondType.SINGLE:
            return False
    return True


def _get_alcohol_type(oxygen_atom: Any) -> Optional[str]:
    """
    功能:
        根据羟基连接碳的取代度判定伯醇, 仲醇或叔醇.

    参数:
        oxygen_atom: RDKit O 原子对象.

    返回:
        Optional[str], 匹配到的醇类型名称, 否则返回 None.
    """

    if oxygen_atom.GetAtomicNum() != 8:
        return None
    if oxygen_atom.GetFormalCharge() != 0:
        return None
    if oxygen_atom.GetTotalNumHs() < 1:
        return None

    carbon_neighbors = _get_neighbor_atoms(oxygen_atom, atomic_num=6)
    if len(carbon_neighbors) != 1:
        return None

    carbon_atom = carbon_neighbors[0]
    if carbon_atom.GetIsAromatic() is True:
        return None
    if carbon_atom.GetHybridization() != HybridizationType.SP3:
        return None

    carbon_neighbor_count = 0
    for neighbor in carbon_atom.GetNeighbors():
        if neighbor.GetIdx() == oxygen_atom.GetIdx():
            continue
        if neighbor.GetAtomicNum() == 6:
            carbon_neighbor_count += 1

    if carbon_neighbor_count <= 1:
        return "伯醇"
    if carbon_neighbor_count == 2:
        return "仲醇"
    return "叔醇"


def _is_phenol_oxygen(atom: Any) -> bool:
    """
    功能:
        判断氧原子是否为酚羟基中的氧.

    参数:
        atom: RDKit O 原子对象.

    返回:
        bool, 是否为酚氧原子.
    """

    if atom.GetAtomicNum() != 8:
        return False
    if atom.GetFormalCharge() != 0:
        return False
    if atom.GetTotalNumHs() < 1:
        return False

    carbon_neighbors = _get_neighbor_atoms(atom, atomic_num=6)
    if len(carbon_neighbors) != 1:
        return False
    return carbon_neighbors[0].GetIsAromatic() is True


def _is_ether_oxygen(atom: Any) -> bool:
    """
    功能:
        判断氧原子是否为醚氧, 即通过单键连接两个碳且不带氢.

    参数:
        atom: RDKit O 原子对象.

    返回:
        bool, 是否为醚氧.
    """

    if atom.GetAtomicNum() != 8:
        return False
    if atom.GetFormalCharge() != 0:
        return False
    if atom.GetTotalNumHs() != 0:
        return False

    carbon_neighbors = _get_neighbor_atoms(atom, atomic_num=6)
    if len(carbon_neighbors) != 2:
        return False

    for bond in atom.GetBonds():
        if bond.GetBondType() != BondType.SINGLE:
            return False
    return True


def _is_amide_like_nitrogen(atom: Any) -> bool:
    """
    功能:
        判断氮原子是否与羰基碳相连, 用于排除酰胺型氮.

    参数:
        atom: RDKit N 原子对象.

    返回:
        bool, 是否为酰胺型或其相近环境的氮.
    """

    if atom.GetAtomicNum() != 7:
        return False

    for neighbor in atom.GetNeighbors():
        if neighbor.GetAtomicNum() == 6 and _is_carbonyl_carbon(neighbor) is True:
            return True
    return False


def _get_carbon_contribution(atom: Any) -> Optional[Tuple[str, float]]:
    """
    功能:
        根据主表规则计算单个碳原子的 ECN 贡献.

    参数:
        atom: RDKit Atom 对象.

    返回:
        Optional[Tuple[str, float]], 命中的规则名称与贡献值, 若不适用返回 None.
    """

    if atom.GetAtomicNum() != 6:
        return None
    if atom.GetIsAromatic() is True:
        return "芳香烃", CARBON_RULE_VALUES["芳香烃"]
    if _is_nitrile_carbon(atom) is True:
        return "腈类", CARBON_RULE_VALUES["腈类"]
    if _is_carboxyl_carbon(atom) is True:
        return "羧基", CARBON_RULE_VALUES["羧基"]
    if _is_carbonyl_carbon(atom) is True:
        return "羰基", CARBON_RULE_VALUES["羰基"]
    if _is_alkyne_carbon(atom) is True:
        return "炔烃", CARBON_RULE_VALUES["炔烃"]
    if _is_alkene_carbon(atom) is True:
        return "烯烃", CARBON_RULE_VALUES["烯烃"]
    return "烷烃类", CARBON_RULE_VALUES["烷烃类"]


def _get_oxygen_contribution(atom: Any) -> Optional[Tuple[str, float]]:
    """
    功能:
        根据主表规则计算单个氧原子的 ECN 贡献.

    参数:
        atom: RDKit Atom 对象.

    返回:
        Optional[Tuple[str, float]], 命中的规则名称与贡献值, 若不适用返回 None.
    """

    if atom.GetAtomicNum() != 8:
        return None
    if _is_phenol_oxygen(atom) is True:
        return "酚", OXYGEN_RULE_VALUES["酚"]

    alcohol_type = _get_alcohol_type(atom)
    if alcohol_type is not None:
        return alcohol_type, OXYGEN_RULE_VALUES[alcohol_type]

    if _is_ether_oxygen(atom) is True:
        return "醚", OXYGEN_RULE_VALUES["醚"]
    return None


def _get_chlorine_contribution(atom: Any) -> Optional[Tuple[str, float]]:
    """
    功能:
        根据主表规则计算单个氯原子的 ECN 贡献.

    参数:
        atom: RDKit Atom 对象.

    返回:
        Optional[Tuple[str, float]], 命中的规则名称与贡献值, 若不适用返回 None.
    """

    if atom.GetAtomicNum() != 17:
        return None
    carbon_neighbors = _get_neighbor_atoms(atom, atomic_num=6)
    if len(carbon_neighbors) != 1:
        return None

    carbon_atom = carbon_neighbors[0]
    if _is_alkene_carbon(carbon_atom) is True:
        return "烯烃碳原子上", CHLORINE_RULE_VALUES["烯烃碳原子上"]

    chlorine_count = _count_neighbor_atoms(carbon_atom, atomic_num=17)
    if _is_saturated_carbon(carbon_atom) is True and chlorine_count >= 2:
        return (
            "一个烷烃碳原子上有两个或更多",
            CHLORINE_RULE_VALUES["一个烷烃碳原子上有两个或更多"],
        )
    return None


def _get_nitrogen_contribution(atom: Any) -> Optional[Tuple[str, float]]:
    """
    功能:
        根据主表规则计算单个胺氮原子的 ECN 贡献.

    参数:
        atom: RDKit Atom 对象.

    返回:
        Optional[Tuple[str, float]], 命中的规则名称与贡献值, 若不适用返回 None.
    """

    if atom.GetAtomicNum() != 7:
        return None
    if atom.GetFormalCharge() != 0:
        return None
    if _is_amide_like_nitrogen(atom) is True:
        return None

    for bond in atom.GetBonds():
        if bond.GetBondType() != BondType.SINGLE:
            return None

    carbon_neighbors = _get_neighbor_atoms(atom, atomic_num=6)
    if len(carbon_neighbors) == 0:
        return None

    hydrogen_count = atom.GetTotalNumHs()
    if len(carbon_neighbors) == 1 and hydrogen_count >= 2:
        if carbon_neighbors[0].GetIsAromatic() is True:
            return "苯胺型伯胺", AMINE_RULE_VALUES["苯胺型伯胺"]
        return "一级胺", AMINE_RULE_VALUES["一级胺"]
    if len(carbon_neighbors) == 2 and hydrogen_count == 1:
        return "二级胺", AMINE_RULE_VALUES["二级胺"]
    if len(carbon_neighbors) == 3 and hydrogen_count == 0:
        return "三级胺", AMINE_RULE_VALUES["三级胺"]
    return None


def _get_atom_contribution(atom: Any) -> Optional[Tuple[str, float]]:
    """
    功能:
        按元素类型分发单原子 ECN 贡献规则.

    参数:
        atom: RDKit Atom 对象.

    返回:
        Optional[Tuple[str, float]], 命中的规则名称与贡献值, 若不适用返回 None.
    """

    for classifier in (
        _get_carbon_contribution,
        _get_oxygen_contribution,
        _get_chlorine_contribution,
        _get_nitrogen_contribution,
    ):
        contribution = classifier(atom)
        if contribution is not None:
            return contribution
    return None


def get_atom_contributions(molecule: Any) -> List[AtomContribution]:
    """
    功能:
        返回分子中所有参与主表 ECN 计算的原子贡献明细.

    参数:
        molecule: RDKit Mol 对象.

    返回:
        List[AtomContribution], 原子贡献记录列表.
    """

    _ensure_rdkit_ready()
    if molecule is None:
        raise ValueError("RDKit 分子对象不能为空")

    contributions: List[AtomContribution] = []
    for atom in Chem.Mol(molecule).GetAtoms():
        contribution = _get_atom_contribution(atom)
        if contribution is None:
            continue
        rule_name, value = contribution
        contributions.append(
            AtomContribution(
                atom_index=atom.GetIdx(),
                atom_symbol=atom.GetSymbol(),
                rule_name=rule_name,
                value=value,
            )
        )
    return contributions


def calculate_ecn_from_molecule(molecule: Any) -> float:
    """
    功能:
        根据 RDKit 分子对象计算有效碳数.

    参数:
        molecule: RDKit Mol 对象.

    返回:
        float, 主表规则下的 ECN 结果.
    """

    contributions = get_atom_contributions(molecule)
    total_value = sum(item.value for item in contributions)
    logger.debug("ECN 贡献明细: %s", contributions)
    return float(total_value)


def calculate_ecn_from_smiles(smiles: str) -> float:
    """
    功能:
        根据 SMILES 直接计算有效碳数.

    参数:
        smiles: 化合物的 SMILES 字符串.

    返回:
        float, 主表规则下的 ECN 结果.
    """

    molecule = _parse_smiles_to_molecule(smiles)
    return calculate_ecn_from_molecule(molecule)

