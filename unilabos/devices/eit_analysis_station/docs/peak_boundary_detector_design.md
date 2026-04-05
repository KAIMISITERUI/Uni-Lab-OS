# 峰边界识别器实施设计稿

## 1. 目标

本设计稿面向 `eit_analysis_station` 当前工程, 收敛一套可执行的峰边界识别器落地方案, 目标如下:

- 同时支持 GC-MS 的 TIC 和 FID 色谱图.
- 输出稳定积分所需的 `start/apex/end`.
- GC-MS 边界不再只由 TIC 单维切分, 而由 TIC 与质谱维度联合决定.
- FID 通过稳健基线、候选峰检测、局部拟合和边界精修输出边界.
- 首版落地时不破坏现有报表、NIST 检索和产率计算链路.

## 2. 当前工程约束

### 2.1 当前调用链

当前峰检测与积分主链路如下:

1. `GCMSDataReader` 负责读取 TIC、FID 和峰区间质谱.
2. `analysis_controller.py` 分别为 TIC 和 FID 构造 `PeakIntegrator`.
3. `PeakIntegrator.integrate()` 输出 `PeakResult`.
4. `NISTMatcher`、`ReportGenerator`、`YieldCalculator` 依赖 `PeakResult.retention_time/start_time/end_time/area`.

### 2.2 当前接入点

首版新方案必须兼容以下现有调用点:

- `controller/analysis_controller.py`
  - TIC 分支构造积分器.
  - FID 分支构造积分器.
- `processor/data_reader.py`
  - 现有 `read_tic()`、`read_fid()`、`read_ms_spectra_at_peak()` 可保留.
  - 需要补充读取完整 `data.ms` 矩阵的接口.
- `processor/peak_integrator.py`
  - 对外契约仍为 `List[PeakResult]`.
  - 新方案应作为新的 `integration_mode` 接入.

### 2.3 首版不做的事

- 不修改 Excel 报告主表结构.
- 不修改 NIST 检索输入输出协议.
- 不强制替换 `robust_v3`, 新方案先以新模式并行接入.
- 不引入在线依赖.

## 3. 建议的模块拆分

建议新增以下模块:

### 3.1 `processor/peak_boundary_models.py`

职责:

- 定义边界识别内部数据结构.
- 提供 `PeakBoundary -> PeakResult` 转换.
- 持有质量评分、证据、告警标记.

核心对象:

- `PeakBoundaryEvidence`
- `PeakBoundaryQuality`
- `PeakBoundary`
- `PeakDetectionTrace`
- `PeakDetectionResult`

### 3.2 `processor/peak_boundary_detector.py`

职责:

- 定义统一检测器协议.
- 定义配置对象.
- 提供 `GCMSPeakBoundaryDetector` 与 `FIDPeakBoundaryDetector` 的工厂入口.
- 后续承载公共预处理逻辑.

核心对象:

- `PeakBoundaryDetectorConfig`
- `PeakDetectionInput`
- `PeakBoundaryDetector`
- `BasePeakBoundaryDetector`
- `GCMSPeakBoundaryDetector`
- `FIDPeakBoundaryDetector`
- `PeakBoundaryDetectorFactory`

### 3.3 数据读取补充

后续在 `processor/data_reader.py` 中新增:

- `read_ms_matrix(d_dir) -> tuple[np.ndarray, np.ndarray, np.ndarray]`
  - 返回 `scan_times`, `mz_axis`, `ms_matrix`
- `extract_xic_batch(ms_matrix, mz_indices) -> np.ndarray`
  - 用于批量提取候选离子色谱

说明:

- 首版只新增读取接口, 不改现有读取接口语义.
- `read_ms_spectra_at_peak()` 保留供 NIST 和报图使用.

## 4. 对外契约

### 4.1 外部保持不变

外部调用模块继续依赖 `PeakResult`, 这样可以保持:

- 报告生成不变.
- NIST 检索不变.
- 产率计算不变.

### 4.2 内部增强

内部检测结果新增以下信息:

- 边界质量分数
- 拆峰置信度
- 特征离子列表
- 谱相似性分数
- 基线可信度
- 边界失败标记

最终由适配层统一转成 `PeakResult`.

## 5. 集成模式设计

建议在 `Settings.integration_mode` 中新增模式:

- `boundary_v1`

其行为定义如下:

- TIC:
  - 若 `detector == TIC` 且 `data.ms` 可读, 走 GC-MS 多维边界识别.
  - 若 `data.ms` 不可读, 记录告警并回退为保守单维模式.
- FID:
  - 走 FID 局部拟合边界识别.

保留已有模式:

- `legacy`
- `robust_v2`
- `robust_v3`
- `gcpy`

## 6. GC-MS 分支实施方案

### 6.1 输入

- `times`: TIC 扫描时间
- `signal`: TIC 强度
- `ms_matrix`: 原始 `scan x mz` 强度矩阵
- `mz_axis`: m/z 轴

### 6.2 首版步骤

1. TIC 预处理
   - SG 平滑, 仅用于候选窗口生成.
   - 估计 TIC 基线与局部噪声.
2. 候选 apex 生成
   - 先基于 TIC 的多尺度局部极大值生成种子.
   - 再用局部离子共峰计数补种子.
3. 局部窗口构建
   - 以种子为中心给出宽松窗口.
   - 窗口宽度由 `peak width + 邻峰距离 + 最大允许边界跨度` 共同限制.
4. 特征离子筛选
   - 以窄核心区对比左右背景.
   - 计算每个 m/z 的富集度、共洗脱一致性、局部峰显著性、主离子比例稳定性.
   - 输出前 `N` 条特征离子.
5. 组分拆分
   - 对特征离子按 XIC apex 时间聚类.
   - 若存在多个稳定离子簇, 建立多个候选组分.
6. 扫描级责任度计算
   - 对每个扫描点计算:
     - 谱相似性
     - 特征离子共洗脱分数
     - 主离子比例稳定性
     - TIC 局部形状分数
     - 基线惩罚
7. 边界搜索
   - 从 apex 向两侧做双阈值扩展.
   - 终止条件为“责任度连续下降 + 特征离子失活 + TIC 回归基线包络”.
   - 最后吸附到局部谷值或责任度拐点.
8. 输出与评分
   - 输出 `PeakBoundary`.
   - 若无法稳定拆峰, 合并为单峰并打低拆峰置信度.

### 6.3 GC-MS 首版回退规则

- 没有足够特征离子时:
  - 回退为 TIC 单维保守边界.
- 离子簇不可分, 但谱型稳定时:
  - 输出单峰.
- 谱型不稳定且边界不清时:
  - 输出低质量峰并附加 `manual_review`.

## 7. FID 分支实施方案

### 7.1 输入

- `times`
- `signal`

### 7.2 首版步骤

1. 预处理
   - Hampel 或中值去尖峰.
   - 估计局部噪声.
2. 基线校正
   - 第一阶段 `pybaselines.arpls/asls` 粗校正.
   - 生成 peak mask.
   - 第二阶段约束重估基线.
3. 候选峰检测
   - 平滑后的 `y_bc` 上运行 `find_peaks`.
   - 用二阶导数和残差补肩峰与弱峰种子.
4. 局部窗口合并
   - 将相邻候选峰合并为局部拟合窗口.
5. `lmfit` 局部拟合
   - 模型: `局部线性基线 + K 个 EMG`
   - `K = 1..4` 递增.
   - 使用 BIC 选择最小充分模型.
6. 边界精修
   - 初值来自组分贡献曲线阈值截断.
   - 再用原始减基线信号谷值吸附.
   - 重叠区取相邻组分贡献相等点.
7. 输出与评分
   - 输出 `PeakBoundary`.
   - 若拟合失败则回退为非参数边界.

### 7.3 FID 首版回退规则

- 拟合不收敛:
  - 回退为 `峰顶 + 局部谷值 + 基线包络` 边界.
- 参数贴边界:
  - 判为不稳定拟合, 降低质量分数.
- 肩峰证据不足:
  - 不强拆峰.

## 8. 控制器接入方案

### 8.1 `analysis_controller.py`

当前控制器为 TIC 和 FID 分别直接实例化 `PeakIntegrator`.

下一步改造策略:

1. 保持原有 `PeakIntegrator` 不动.
2. 在控制器中新增一个小工厂:
   - `integration_mode != boundary_v1` 时沿用现有 `PeakIntegrator`.
   - `integration_mode == boundary_v1` 时:
     - TIC: 组装 `PeakDetectionInput` 并调用 `GCMSPeakBoundaryDetector`.
     - FID: 调用 `FIDPeakBoundaryDetector`.
3. 将内部 `PeakBoundary` 统一转换为 `PeakResult`.
4. 额外诊断信息暂存到 `SampleResult` 的新字段或控制器局部变量.

### 8.2 `SampleResult` 建议扩展

下一步建议为 `SampleResult` 增加两个可选字段:

- `tic_peak_diagnostics: Dict[int, Dict[str, Any]]`
- `fid_peak_diagnostics: Dict[int, Dict[str, Any]]`

说明:

- 首版不写入 Excel.
- 仅供调试与回归脚本使用.

## 9. 配置项规划

首版建议按检测器拆开配置, 但不一次性把全部细粒度参数暴露到环境变量.

### 9.1 公共配置

- `integration_mode = "boundary_v1"`
- `boundary_quality_manual_review_threshold`

### 9.2 GC-MS 配置

- `gcms_seed_prominence`
- `gcms_seed_min_distance`
- `gcms_feature_ion_min_count`
- `gcms_feature_ion_max_count`
- `gcms_spectral_similarity_threshold`
- `gcms_ratio_cv_threshold`
- `gcms_component_gap_min_scans`
- `gcms_boundary_low_score_threshold`
- `gcms_boundary_high_score_threshold`

### 9.3 FID 配置

- `fid_baseline_method`
- `fid_candidate_prominence`
- `fid_candidate_min_distance`
- `fid_fit_max_components`
- `fid_fit_bic_improve_min`
- `fid_boundary_rel_height`
- `fid_boundary_abs_noise_factor`

原则:

- 首版只暴露少量一级参数.
- 次级参数先放在 `PeakBoundaryDetectorConfig` 默认值中.

## 10. 测试与回归计划

### 10.1 单元测试

新增以下测试文件:

- `tests/test_peak_boundary_models.py`
  - 校验 `PeakBoundary -> PeakResult` 转换.
  - 校验质量分数字段保留.
- `tests/test_peak_boundary_detector_factory.py`
  - 校验工厂路由.

### 10.2 算法测试

后续新增:

- `tests/test_peak_boundary_detector_gcms.py`
- `tests/test_peak_boundary_detector_fid.py`

测试目标:

- 单峰边界正确
- 拖尾峰边界正确
- 肩峰拆分稳定
- 重叠峰不误拆或误并
- 大峰尾部弱峰保留

### 10.3 回归脚本

在现有 `scripts/regression_peak_integration.py` 基础上补两类回归:

- `boundary_v1` 与 `robust_v3` 对比回归
- 真实样本边界与面积稳定性回归

建议新增指标:

- `boundary_iou`
- `apex_abs_error`
- `area_cv_under_boundary_jitter`
- `split_precision`
- `split_recall`

## 11. 实施顺序

建议按以下顺序执行, 每一步都可单独验收:

### 阶段 1: 接口与数据结构

- 新增 `peak_boundary_models.py`
- 新增 `peak_boundary_detector.py`
- 新增基础单元测试

### 阶段 2: 数据读取增强

- 在 `data_reader.py` 增加 `read_ms_matrix()`
- 为 GC-MS 分支准备批量 XIC 提取

### 阶段 3: FID 先行落地

- 实现 FID 基线校正
- 实现候选峰检测
- 实现局部 EMG 拟合
- 在 `analysis_controller.py` 接入 `boundary_v1` 的 FID 分支

### 阶段 4: GC-MS 多维边界落地

- 实现特征离子筛选
- 实现扫描级责任度
- 实现共洗脱拆峰
- 接入 `boundary_v1` 的 TIC 分支

### 阶段 5: 真实样本回归与调参

- 跑合成数据
- 跑 `eit_analysis_station\fixtures\peak_integration` 等真实样本
- 固化默认参数

## 12. 验收标准

首版 `boundary_v1` 通过验收需满足:

- 对外仍输出 `PeakResult`, 不破坏现有报表链路.
- FID 对拖尾峰和肩峰边界明显优于 `robust_v3`.
- GC-MS 对共洗脱和尾部弱峰的拆分能力优于 TIC 单维方案.
- 面积对边界微扰的稳定性优于当前方案.
- 所有低质量峰都能输出明确告警标记.

## 13. 本次已完成的准备工作

- 已确认当前工程真实接入链路.
- 已确定首版采用 `boundary_v1` 新模式并行接入.
- 已准备边界识别数据结构与工厂骨架文件.

下一步实现时, 不再需要重新做架构决策, 直接按本设计稿分阶段落地即可.
