#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    分析站配置模块, 统一管理仪器连接参数, 数据目录和积分参数.
参数:
    无.
返回:
    Settings 实例.
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Settings:
    """
    功能:
        存储分析站运行所需的全部配置项.
    参数:
        无.
    返回:
        Settings.
    """

    # ---------- GC_MS 设备 ----------
    gc_ms_host: str = "10.40.6.101"  # GC-MS 控制端地址, 修改后切换仪器目标主机.
    gc_ms_port: int = 5792  # GC-MS 控制端端口, 修改后切换连接端口.
    gc_ms_timeout: float = 10.0  # GC-MS 通信超时秒数, 调大可降低慢响应误判.

    # ---------- UPLC_QTOF 设备 ----------
    uplc_qtof_host: str = "10.40.8.69"  # UPLC_QTOF 控制端地址, 修改后流程切换主机.
    uplc_qtof_port: int = 5792  # UPLC_QTOF 控制端端口, 修改后流程切换端口.
    uplc_qtof_timeout: float = 10.0  # UPLC_QTOF 通信超时秒数, 调大可降低超时告警.
    uplc_qtof_append_wash_stop: bool = False  # 是否追加 Wash stop 方法, 打开后序列会追加停机步骤.

    # ---------- HPLC 设备(预留) ----------
    hplc_host: str = "192.168.3.186"  # HPLC 控制端地址, 预留流程切换主机.
    hplc_port: int = 5792  # HPLC 控制端端口, 预留流程切换端口.
    hplc_timeout: float = 10.0  # HPLC 通信超时秒数, 调大可降低超时告警.

    # ---------- 仪器侧数据目录 ----------
    gc_ms_data_dir: Path = field(default_factory=lambda: Path(r"\\10.37.2.2\Autolab_Database\Auto_GC_MS\data"))  # GC-MS 仪器导出目录, 修改后切换采集源路径.
    uplc_qtof_data_dir: Path = field(default_factory=lambda: Path("Z:/Auto_UPLC_QTOF/data"))  # UPLC_QTOF 仪器导出目录, 修改后切换采集源路径.
    hplc_data_dir: Path = field(default_factory=lambda: Path("Z:/Auto_HPLC/data"))  # HPLC 仪器导出目录, 修改后切换采集源路径.

    # ---------- 合成任务目录 ----------
    synthesis_tasks_dir: Path = field(  # 合成站任务目录, 修改后会改变任务同步目标.
        default_factory=lambda: Path(__file__).parent.parent.parent
        / "eit_synthesis_station"
        / "data"
        / "tasks"
    )

    # ---------- 分析站本地数据目录 ----------
    data_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent / "data")  # 分析站本地数据根目录, 修改后影响本地缓存与中间产物位置.

    # ---------- 日志 ----------
    log_level: str = "INFO"  # 日志等级, 调为 DEBUG 可输出更详细排障信息.

    # ---------- NIST 配置 ----------
    nist_path: Path = field(default_factory=lambda: Path(r"D:\NIST23\MSSEARCH"))  # NIST 安装目录, 修改后切换检索程序与库路径基准.
    nist_max_hits: int = 5  # NIST 每峰返回命中数, 调大可保留更多候选.
    nist_search_timeout: float = 120.0  # NIST 单峰搜索超时秒数, 调大可降低超时中断.
    nist_avg_scans: int = 3  # 质谱平均扫描数, 调大可提升信噪比但会平滑细节.
    pim_enable: bool = True  # 是否启用 PIM 预测, 关闭后不输出 PIM 列结果.
    pim_ab_m: float = 0.3  # PIM 参数 ab_m, 调整后影响分子离子峰判定敏感度. 调大: 只允许更强的高 m/z 峰参与判断, 抗噪更强, 但更容易把真实分子离子峰(弱峰)跳过, 预测质量偏低.
    pim_beta: float = 5.0  # PIM 参数 beta, 调整后影响高质量峰加权强度.
    pim_epsilon_f: float = 0.0  # PIM 参数 epsilon_f, 调整后影响峰筛选阈值.

    # ---------- MSPepSearch 预测配置 ----------
    mspepsearch_enable: bool = True  # 是否启用 MSPepSearch 预测链路, 关闭后不执行 SS-HM/iHS-HM.
    process_gc_ms_enable_sshm_search: bool = True  # 是否启用 SS-HM 预测, 关闭后报告不写 SS-HM 结果.
    process_gc_ms_enable_ihshm_search: bool = False  # 是否启用 iHS-HM 预测, 打开后增加 iHS-HM 计算耗时.
    mspepsearch_exe: Path = field(  # MSPepSearch 可执行文件路径, 修改后切换调用程序.
        default_factory=lambda: Path(
            r"D:\EIMS-mass-predictions\R_ShinyApplication\shiny\wrk"
            r"\MSPepSearch\2017_05_15_MSPepSearch\x64\MSPepSearch64.exe"
        )
    )
    mspepsearch_lib_path: Path = field(  # MSPepSearch 库目录, 修改后切换检索库来源.
        default_factory=lambda: Path(r"D:\NIST23\MSSEARCH\mainlib")
    )
    mspepsearch_lib_type: str = "MAIN"  # MSPepSearch 库类型, 改为 REPL/LIB 会改变命中空间.
    nist_mainlib_msp: Path = field(  # mainlib 导出 MSP 路径, 修改后影响离线库解析来源.
        default_factory=lambda: Path(r"D:\NIST23\MSSEARCH\mainlib_export.msp")
    )
    nist_structure_seed_msp: Path = field(  # 结构映射 seed MSP 路径, 修改后影响 NIST# 到 CAS 映射.
        default_factory=lambda: Path(r"D:\NIST23\MSSEARCH\mainlib_export.msp")
    )
    nist_structure_seed_mol_dir: Path = field(  # 结构映射 seed MOL 目录, 修改后影响本地结构图渲染命中率.
        default_factory=lambda: Path(r"D:\NIST23\MSSEARCH\mainlib_export.MOL")
    )
    nist_structure_runtime_cache_path: Path = field(  # 运行时结构映射缓存路径, 修改后影响映射复用位置.
        default_factory=lambda: Path(__file__).parent.parent / "data" / "nist_runtime_map.pkl"
    )
    structure_offline_only: bool = False  # 是否严格离线结构模式, 打开后禁用 PubChem 网络回退.
    sshm_hits: int = 25  # SS-HM 搜索返回命中数, 调大可增加候选覆盖.
    sshm_b_ss: int = 75  # SS-HM 概率加权参数 B_SS, 调整后影响置信度分布.
    ihshm_hits: int = 25  # iHS-HM 搜索返回命中数, 调大可增加候选覆盖.
    ihshm_mEMF: int = 700  # iHS-HM 最小匹配因子阈值, 调高会更严格过滤低质量命中.
    mspepsearch_timeout: float = 120.0  # MSPepSearch 超时秒数, 调大可降低复杂谱图超时失败.

    # ---------- 峰检测与积分参数 ----------
    peak_smoothing_window: int = 11  # TIC 平滑窗口点数, 调大可抑制噪声但可能吞并窄峰.
    peak_prominence: float = 10000.0  # TIC 最小峰显著性阈值, 调高会减少弱峰识别.
    peak_min_distance: int = 5  # TIC 相邻峰最小点距, 调大可减少近邻峰分裂.
    peak_width_rel_height: float = 0.99  # 峰宽计算相对高度, 调整后影响峰边界与面积.
    fid_peak_prominence: float = 0.5  # FID 最小峰显著性阈值, 调高会减少弱峰识别.
    fid_peak_min_distance: int = 50  # FID 相邻峰最小点距, 调大可减少近邻峰分裂.

    # ---------- legacy 参数 ----------
    use_als_baseline: bool = True  # 是否使用 ALS 基线, 关闭后使用替代基线策略.
    als_lambda: float = 1e7  # ALS 平滑参数 lambda, 调大可使基线更平滑.
    als_p: float = 0.01  # ALS 非对称参数 p, 调整后影响正负残差惩罚.
    use_valley_boundary: bool = False  # 是否使用谷底边界法, 打开后边界更贴近局部谷底.

    # ---------- robust_v2 参数 ----------
    integration_mode: str = "robust_v2"  # 积分模式, 切换后改变峰检测与边界算法路径.
    baseline_method: str = "rolling_quantile"  # robust_v2 基线方法, 修改后改变背景估计方式.
    baseline_quantile: float = 20.0  # rolling quantile 分位数, 调低会提升基线灵敏度.
    baseline_window_min: float = 0.9  # 基线窗口宽度(min), 调大可提升基线平稳性.
    boundary_sigma_factor: float = 3.0  # 边界 sigma 系数, 调大通常会扩展积分边界.
    boundary_edge_ratio: float = 0.01  # 边缘阈值比例, 调整后影响峰起止截断位置.
    boundary_expand_factor: float = 6.0  # 边界扩展系数, 调大可覆盖更多拖尾区域.
    boundary_min_span_min: float = 0.08  # 峰最小宽度(min), 调大可过滤过窄噪声峰.
    boundary_max_span_min: float = 1.00  # 峰最大宽度(min), 调小可抑制异常宽峰.

    # ---------- 峰过滤参数 ----------
    peak_rt_min: Optional[float] = 4.0  # 峰保留时间下限(min), 调大可忽略前段溶剂峰.
    peak_rt_max: Optional[float] = 10.0  # 峰保留时间上限(min), 调小可限制后段噪声峰.
    tic_area_min: Optional[float] = 10000.0  # TIC 峰面积下限, 调大可过滤小面积峰.
    tic_area_max: Optional[float] = None  # TIC 峰面积上限, 设置后可过滤过载峰.
    fid_area_min: Optional[float] = 0.01  # FID 峰面积下限, 调大可过滤微小峰.
    fid_area_max: Optional[float] = None  # FID 峰面积上限, 设置后可过滤异常大峰.

    # ---------- TIC-FID 峰对齐参数 ----------
    alignment_tolerance: float = 0.05  # FID 与 TIC 峰保留时间对齐容差(min), 调大可提高配对成功率.
    alignment_include_tic_only: bool = False  # 是否输出仅 TIC 有峰行, 打开后对照表会增加 TIC-only 记录.
    alignment_include_fid_only: bool = True  # 是否输出仅 FID 有峰行, 关闭后对照表会隐藏 FID-only 记录.

    # ---------- 产率计算参数 ----------
    yield_rt_tolerance: float = 0.1  # 产率计算 RT 匹配容差(min), 调大可放宽目标峰匹配.

    # ---------- TIC 绘图参数 ----------
    tic_plot_show_compound: bool = True  # TIC 色谱图是否标注化合物名称, 关闭后图面更简洁.

    # ---------- 图片导出参数 ----------
    chromatogram_plot_ppi: int = 300  # 色谱图导出 PPI, 调高可提升 TIC/FID 图清晰度并增大文件体积.
    ms_spectrum_plot_ppi: int = 300  # 质谱图导出 PPI, 调高可提升棒图与标签清晰度并增大文件体积.
    structure_image_ppi: int = 300  # 结构图导出 PPI, 调高可提升本地渲染结构图清晰度并增大文件体积.

    # ---------- 报告目录 ----------
    report_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent / "data")  # 报告输出根目录, 修改后改变报告与图像落盘位置.

    # ---------- 化学品库目录 ----------
    chemical_list_path: Path = field(  # 化学品清单路径, 修改后切换产率计算的物性来源.
        default_factory=lambda: Path(__file__).parent.parent.parent
        / "eit_synthesis_station"
        / "sheet"
        / "chemical_list.xlsx"
    )

    # ---------- 结构图缓存目录 ----------
    structure_cache_dir: Path = field(  # 全局结构图缓存目录, 修改后影响跨任务复用缓存位置.
        default_factory=lambda: Path(__file__).parent.parent / "data" / "structure_cache"
    )

    @staticmethod
    def from_env() -> "Settings":
        """
        功能:
            从环境变量读取配置, 未配置时使用默认值.
        参数:
            无.
        返回:
            Settings.
        环境变量:
            ANALYSIS_GC_MS_HOST, ANALYSIS_GC_MS_PORT, ANALYSIS_GC_MS_TIMEOUT,
            ANALYSIS_UPLC_QTOF_HOST, ANALYSIS_UPLC_QTOF_PORT, ANALYSIS_UPLC_QTOF_TIMEOUT,
            ANALYSIS_UPLC_QTOF_APPEND_WASH_STOP,
            ANALYSIS_HPLC_HOST, ANALYSIS_HPLC_PORT, ANALYSIS_HPLC_TIMEOUT,
            ANALYSIS_GC_MS_DATA_DIR, ANALYSIS_UPLC_QTOF_DATA_DIR, ANALYSIS_HPLC_DATA_DIR,
            ANALYSIS_SYNTHESIS_TASKS_DIR, ANALYSIS_DATA_DIR, ANALYSIS_LOG_LEVEL,
            ANALYSIS_PEAK_SMOOTHING_WINDOW, ANALYSIS_PEAK_PROMINENCE,
            ANALYSIS_PEAK_MIN_DISTANCE, ANALYSIS_PEAK_WIDTH_REL_HEIGHT,
            ANALYSIS_FID_PEAK_PROMINENCE, ANALYSIS_FID_PEAK_MIN_DISTANCE,
            ANALYSIS_USE_ALS_BASELINE, ANALYSIS_ALS_LAMBDA, ANALYSIS_ALS_P,
            ANALYSIS_USE_VALLEY_BOUNDARY,
            ANALYSIS_INTEGRATION_MODE, ANALYSIS_BASELINE_METHOD,
            ANALYSIS_BASELINE_QUANTILE, ANALYSIS_BASELINE_WINDOW_MIN,
            ANALYSIS_BOUNDARY_SIGMA_FACTOR, ANALYSIS_BOUNDARY_EDGE_RATIO,
            ANALYSIS_BOUNDARY_EXPAND_FACTOR, ANALYSIS_BOUNDARY_MIN_SPAN_MIN,
            ANALYSIS_BOUNDARY_MAX_SPAN_MIN,
            ANALYSIS_PEAK_RT_MIN, ANALYSIS_PEAK_RT_MAX,
            ANALYSIS_TIC_AREA_MIN, ANALYSIS_TIC_AREA_MAX,
            ANALYSIS_FID_AREA_MIN, ANALYSIS_FID_AREA_MAX,
            ANALYSIS_REPORT_DIR, ANALYSIS_STRUCTURE_CACHE_DIR,
            ANALYSIS_NIST_PATH, ANALYSIS_NIST_MAX_HITS,
            ANALYSIS_NIST_SEARCH_TIMEOUT, ANALYSIS_NIST_AVG_SCANS,
            ANALYSIS_PIM_ENABLE, ANALYSIS_PIM_AB_M,
            ANALYSIS_PIM_BETA, ANALYSIS_PIM_EPSILON_F,
            ANALYSIS_ALIGNMENT_INCLUDE_TIC_ONLY,
            ANALYSIS_ALIGNMENT_INCLUDE_FID_ONLY,
            ANALYSIS_TIC_PLOT_SHOW_COMPOUND,
            ANALYSIS_CHROMATOGRAM_PLOT_PPI, ANALYSIS_MS_SPECTRUM_PLOT_PPI,
            ANALYSIS_STRUCTURE_IMAGE_PPI,
            ANALYSIS_MSPEPSEARCH_ENABLE, ANALYSIS_MSPEPSEARCH_EXE,
            ANALYSIS_PROCESS_GC_MS_ENABLE_SSHM_SEARCH,
            ANALYSIS_PROCESS_GC_MS_ENABLE_IHSHM_SEARCH,
            ANALYSIS_MSPEPSEARCH_LIB_PATH, ANALYSIS_MSPEPSEARCH_LIB_TYPE,
            ANALYSIS_NIST_MAINLIB_MSP, ANALYSIS_SSHM_HITS,
            ANALYSIS_SSHM_B_SS, ANALYSIS_IHSHM_HITS,
            ANALYSIS_IHSHM_MEMF, ANALYSIS_MSPEPSEARCH_TIMEOUT,
            ANALYSIS_NIST_STRUCTURE_SEED_MSP, ANALYSIS_NIST_STRUCTURE_SEED_MOL_DIR,
            ANALYSIS_NIST_STRUCTURE_RUNTIME_CACHE_PATH, ANALYSIS_STRUCTURE_OFFLINE_ONLY.
        """
        defaults = Settings()

        def _str(key: str, default: str) -> str:
            return os.getenv(key, default)

        def _int(key: str, default: int) -> int:
            try:
                return int(os.getenv(key, str(default)))
            except ValueError:
                return default

        def _float(key: str, default: float) -> float:
            try:
                return float(os.getenv(key, str(default)))
            except ValueError:
                return default

        def _path(key: str, default: Path) -> Path:
            value = os.getenv(key)
            if value is None or value.strip() == "":
                return default
            return Path(value)

        def _opt_float(key: str, default: Optional[float] = None) -> Optional[float]:
            value = os.getenv(key)
            if value is None or value.strip() == "":
                return default
            try:
                return float(value)
            except ValueError:
                return default

        def _bool(key: str, default: bool) -> bool:
            value = os.getenv(key)
            if value is None or value.strip() == "":
                return default
            return value.strip().lower() in ("true", "1", "yes")

        return Settings(
            gc_ms_host=_str("ANALYSIS_GC_MS_HOST", defaults.gc_ms_host),
            gc_ms_port=_int("ANALYSIS_GC_MS_PORT", defaults.gc_ms_port),
            gc_ms_timeout=_float("ANALYSIS_GC_MS_TIMEOUT", defaults.gc_ms_timeout),
            uplc_qtof_host=_str("ANALYSIS_UPLC_QTOF_HOST", defaults.uplc_qtof_host),
            uplc_qtof_port=_int("ANALYSIS_UPLC_QTOF_PORT", defaults.uplc_qtof_port),
            uplc_qtof_timeout=_float("ANALYSIS_UPLC_QTOF_TIMEOUT", defaults.uplc_qtof_timeout),
            uplc_qtof_append_wash_stop=_bool(
                "ANALYSIS_UPLC_QTOF_APPEND_WASH_STOP", defaults.uplc_qtof_append_wash_stop
            ),
            hplc_host=_str("ANALYSIS_HPLC_HOST", defaults.hplc_host),
            hplc_port=_int("ANALYSIS_HPLC_PORT", defaults.hplc_port),
            hplc_timeout=_float("ANALYSIS_HPLC_TIMEOUT", defaults.hplc_timeout),
            gc_ms_data_dir=_path("ANALYSIS_GC_MS_DATA_DIR", defaults.gc_ms_data_dir),
            uplc_qtof_data_dir=_path("ANALYSIS_UPLC_QTOF_DATA_DIR", defaults.uplc_qtof_data_dir),
            hplc_data_dir=_path("ANALYSIS_HPLC_DATA_DIR", defaults.hplc_data_dir),
            synthesis_tasks_dir=_path("ANALYSIS_SYNTHESIS_TASKS_DIR", defaults.synthesis_tasks_dir),
            data_dir=_path("ANALYSIS_DATA_DIR", defaults.data_dir),
            log_level=_str("ANALYSIS_LOG_LEVEL", defaults.log_level),
            peak_smoothing_window=_int("ANALYSIS_PEAK_SMOOTHING_WINDOW", defaults.peak_smoothing_window),
            peak_prominence=_float("ANALYSIS_PEAK_PROMINENCE", defaults.peak_prominence),
            peak_min_distance=_int("ANALYSIS_PEAK_MIN_DISTANCE", defaults.peak_min_distance),
            peak_width_rel_height=_float("ANALYSIS_PEAK_WIDTH_REL_HEIGHT", defaults.peak_width_rel_height),
            fid_peak_prominence=_float("ANALYSIS_FID_PEAK_PROMINENCE", defaults.fid_peak_prominence),
            fid_peak_min_distance=_int("ANALYSIS_FID_PEAK_MIN_DISTANCE", defaults.fid_peak_min_distance),
            use_als_baseline=_bool("ANALYSIS_USE_ALS_BASELINE", defaults.use_als_baseline),
            als_lambda=_float("ANALYSIS_ALS_LAMBDA", defaults.als_lambda),
            als_p=_float("ANALYSIS_ALS_P", defaults.als_p),
            use_valley_boundary=_bool("ANALYSIS_USE_VALLEY_BOUNDARY", defaults.use_valley_boundary),
            integration_mode=_str("ANALYSIS_INTEGRATION_MODE", defaults.integration_mode),
            baseline_method=_str("ANALYSIS_BASELINE_METHOD", defaults.baseline_method),
            baseline_quantile=_float("ANALYSIS_BASELINE_QUANTILE", defaults.baseline_quantile),
            baseline_window_min=_float("ANALYSIS_BASELINE_WINDOW_MIN", defaults.baseline_window_min),
            boundary_sigma_factor=_float("ANALYSIS_BOUNDARY_SIGMA_FACTOR", defaults.boundary_sigma_factor),
            boundary_edge_ratio=_float("ANALYSIS_BOUNDARY_EDGE_RATIO", defaults.boundary_edge_ratio),
            boundary_expand_factor=_float("ANALYSIS_BOUNDARY_EXPAND_FACTOR", defaults.boundary_expand_factor),
            boundary_min_span_min=_float("ANALYSIS_BOUNDARY_MIN_SPAN_MIN", defaults.boundary_min_span_min),
            boundary_max_span_min=_float("ANALYSIS_BOUNDARY_MAX_SPAN_MIN", defaults.boundary_max_span_min),
            report_dir=_path("ANALYSIS_REPORT_DIR", defaults.report_dir),
            structure_cache_dir=_path("ANALYSIS_STRUCTURE_CACHE_DIR", defaults.structure_cache_dir),
            chemical_list_path=_path("ANALYSIS_CHEMICAL_LIST_PATH", defaults.chemical_list_path),
            nist_path=_path("ANALYSIS_NIST_PATH", defaults.nist_path),
            nist_max_hits=_int("ANALYSIS_NIST_MAX_HITS", defaults.nist_max_hits),
            nist_search_timeout=_float("ANALYSIS_NIST_SEARCH_TIMEOUT", defaults.nist_search_timeout),
            nist_avg_scans=_int("ANALYSIS_NIST_AVG_SCANS", defaults.nist_avg_scans),
            pim_enable=_bool("ANALYSIS_PIM_ENABLE", defaults.pim_enable),
            pim_ab_m=_float("ANALYSIS_PIM_AB_M", defaults.pim_ab_m),
            pim_beta=_float("ANALYSIS_PIM_BETA", defaults.pim_beta),
            pim_epsilon_f=_float("ANALYSIS_PIM_EPSILON_F", defaults.pim_epsilon_f),
            mspepsearch_enable=_bool("ANALYSIS_MSPEPSEARCH_ENABLE", defaults.mspepsearch_enable),
            process_gc_ms_enable_sshm_search=_bool(
                "ANALYSIS_PROCESS_GC_MS_ENABLE_SSHM_SEARCH",
                defaults.process_gc_ms_enable_sshm_search
            ),
            process_gc_ms_enable_ihshm_search=_bool(
                "ANALYSIS_PROCESS_GC_MS_ENABLE_IHSHM_SEARCH",
                defaults.process_gc_ms_enable_ihshm_search
            ),
            mspepsearch_exe=_path("ANALYSIS_MSPEPSEARCH_EXE", defaults.mspepsearch_exe),
            mspepsearch_lib_path=_path("ANALYSIS_MSPEPSEARCH_LIB_PATH", defaults.mspepsearch_lib_path),
            mspepsearch_lib_type=_str("ANALYSIS_MSPEPSEARCH_LIB_TYPE", defaults.mspepsearch_lib_type),
            nist_mainlib_msp=_path("ANALYSIS_NIST_MAINLIB_MSP", defaults.nist_mainlib_msp),
            nist_structure_seed_msp=_path(
                "ANALYSIS_NIST_STRUCTURE_SEED_MSP", defaults.nist_structure_seed_msp
            ),
            nist_structure_seed_mol_dir=_path(
                "ANALYSIS_NIST_STRUCTURE_SEED_MOL_DIR", defaults.nist_structure_seed_mol_dir
            ),
            nist_structure_runtime_cache_path=_path(
                "ANALYSIS_NIST_STRUCTURE_RUNTIME_CACHE_PATH",
                defaults.nist_structure_runtime_cache_path,
            ),
            structure_offline_only=_bool(
                "ANALYSIS_STRUCTURE_OFFLINE_ONLY", defaults.structure_offline_only
            ),
            sshm_hits=_int("ANALYSIS_SSHM_HITS", defaults.sshm_hits),
            sshm_b_ss=_int("ANALYSIS_SSHM_B_SS", defaults.sshm_b_ss),
            ihshm_hits=_int("ANALYSIS_IHSHM_HITS", defaults.ihshm_hits),
            ihshm_mEMF=_int("ANALYSIS_IHSHM_MEMF", defaults.ihshm_mEMF),
            mspepsearch_timeout=_float("ANALYSIS_MSPEPSEARCH_TIMEOUT", defaults.mspepsearch_timeout),
            peak_rt_min=_opt_float("ANALYSIS_PEAK_RT_MIN", defaults.peak_rt_min),
            peak_rt_max=_opt_float("ANALYSIS_PEAK_RT_MAX", defaults.peak_rt_max),
            tic_area_min=_opt_float("ANALYSIS_TIC_AREA_MIN", defaults.tic_area_min),
            tic_area_max=_opt_float("ANALYSIS_TIC_AREA_MAX", defaults.tic_area_max),
            fid_area_min=_opt_float("ANALYSIS_FID_AREA_MIN", defaults.fid_area_min),
            fid_area_max=_opt_float("ANALYSIS_FID_AREA_MAX", defaults.fid_area_max),
            alignment_tolerance=_float("ANALYSIS_ALIGNMENT_TOLERANCE", defaults.alignment_tolerance),
            alignment_include_tic_only=_bool("ANALYSIS_ALIGNMENT_INCLUDE_TIC_ONLY", defaults.alignment_include_tic_only),
            alignment_include_fid_only=_bool("ANALYSIS_ALIGNMENT_INCLUDE_FID_ONLY", defaults.alignment_include_fid_only),
            tic_plot_show_compound=_bool("ANALYSIS_TIC_PLOT_SHOW_COMPOUND", defaults.tic_plot_show_compound),
            chromatogram_plot_ppi=_int("ANALYSIS_CHROMATOGRAM_PLOT_PPI", defaults.chromatogram_plot_ppi),
            ms_spectrum_plot_ppi=_int("ANALYSIS_MS_SPECTRUM_PLOT_PPI", defaults.ms_spectrum_plot_ppi),
            structure_image_ppi=_int("ANALYSIS_STRUCTURE_IMAGE_PPI", defaults.structure_image_ppi),
            yield_rt_tolerance=_float("ANALYSIS_YIELD_RT_TOLERANCE", defaults.yield_rt_tolerance),
        )


def configure_logging(level: str = "INFO") -> None:
    """
    功能:
        配置全局 logging.
    参数:
        level: 日志等级字符串.
    返回:
        无.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    if not root_logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
