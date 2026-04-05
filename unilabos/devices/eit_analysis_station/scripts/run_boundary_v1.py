#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    使用 boundary_v1 峰边界识别器批量处理 fixtures/peak_integration 下的样本,
    输出 TIC 和 FID 检测结果汇总.

参数:
    无.

返回:
    无.
"""

import logging
import sys
from pathlib import Path

import numpy as np

# 将 devices 目录加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eit_analysis_station.processor.data_reader import GCMSDataReader
from eit_analysis_station.processor.peak_boundary_detector import (
    FIDPeakBoundaryDetector,
    GCMSPeakBoundaryDetector,
    PeakBoundaryDetectorConfig,
    PeakBoundaryDetectorFactory,
    PeakDetectionInput,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def process_sample(d_dir: Path, reader: GCMSDataReader,
                   factory: PeakBoundaryDetectorFactory) -> dict:
    """
    功能:
        对单个 .D 目录执行 boundary_v1 TIC + FID 检测.

    参数:
        d_dir: .D 目录路径.
        reader: 数据读取器.
        factory: 检测器工厂.

    返回:
        dict, 包含 tic_peaks, fid_peaks 等检测结果.
    """
    sample_name = d_dir.name
    result = {"sample": sample_name, "tic_peaks": [], "fid_peaks": [],
              "tic_error": None, "fid_error": None}

    # TIC (GC-MS 多维)
    try:
        tic_times, tic_signal = reader.read_tic(d_dir)

        ms_matrix = None
        mz_axis = None
        try:
            _, mz_axis, ms_matrix = reader.read_ms_matrix(d_dir)
        except Exception as e:
            logger.warning("%s: 无法读取 ms_matrix, 降级 TIC-only: %s", sample_name, e)

        gcms_det = factory.build("gcms_tic")
        tic_input = PeakDetectionInput(
            detector="gcms_tic",
            times=tic_times,
            signal=tic_signal,
            ms_matrix=ms_matrix,
            mz_axis=mz_axis,
        )
        tic_result = gcms_det.detect(tic_input)
        result["tic_peaks"] = tic_result.peaks
        result["tic_baseline"] = tic_result.trace.baseline
    except Exception as e:
        result["tic_error"] = str(e)
        logger.error("%s TIC 处理失败: %s", sample_name, e)

    # FID
    try:
        fid_times, fid_signal = reader.read_fid(d_dir)
        fid_det = factory.build("fid")
        fid_input = PeakDetectionInput(
            detector="fid",
            times=fid_times,
            signal=fid_signal,
        )
        fid_result = fid_det.detect(fid_input)
        result["fid_peaks"] = fid_result.peaks
        result["fid_baseline"] = fid_result.trace.baseline
    except Exception as e:
        result["fid_error"] = str(e)
        logger.error("%s FID 处理失败: %s", sample_name, e)

    return result


def main():
    fixture_dir = Path(__file__).resolve().parent.parent / "fixtures" / "peak_integration"

    if not fixture_dir.exists():
        logger.error("fixtures 目录不存在: %s", fixture_dir)
        return

    d_dirs = sorted(fixture_dir.glob("*.D"))
    logger.info("共发现 %d 个样本目录", len(d_dirs))

    reader = GCMSDataReader()
    config = PeakBoundaryDetectorConfig(
        smoothing_window=11,
        gcms_seed_prominence=20000.0,
        gcms_seed_min_distance=3,
        fid_candidate_prominence=0.5,
        fid_candidate_min_distance=50,
        fid_fit_max_components=4,
        fid_baseline_method="arpls",
    )
    factory = PeakBoundaryDetectorFactory(config)

    # 保留时间过滤范围
    rt_min = 4.0
    rt_max = 12.0

    all_results = []
    for d_dir in d_dirs:
        result = process_sample(d_dir, reader, factory)
        all_results.append(result)

    # 输出汇总
    sep = "=" * 100
    print(f"\n{sep}")
    print(f"  boundary_v1 峰边界识别结果汇总  ({len(all_results)} 个样本)")
    print(sep)

    for res in all_results:
        sample = res["sample"]

        # TIC
        tic_peaks = res["tic_peaks"]
        tic_filtered = [p for p in tic_peaks
                        if rt_min <= p.apex_time <= rt_max]

        print(f"\n{'─' * 100}")
        print(f"  样本: {sample}")
        print(f"{'─' * 100}")

        if res["tic_error"] is not None:
            print(f"  [TIC] 处理失败: {res['tic_error']}")
        else:
            print(f"  [TIC] 检测到 {len(tic_peaks)} 个峰 (RT {rt_min}-{rt_max} min 内 {len(tic_filtered)} 个)")
            if tic_filtered:
                print(f"  {'ID':>4s}  {'RT(min)':>8s}  {'Start':>8s}  {'End':>8s}  {'Width':>7s}  {'Height':>12s}  {'Area':>14s}  {'Quality':>7s}  {'Flags'}")
                print(f"  {'─'*4}  {'─'*8}  {'─'*8}  {'─'*8}  {'─'*7}  {'─'*12}  {'─'*14}  {'─'*7}  {'─'*20}")
                for p in tic_filtered:
                    width = p.end_time - p.start_time
                    print(f"  {p.peak_id:4d}  {p.apex_time:8.3f}  {p.start_time:8.3f}  {p.end_time:8.3f}  {width:7.3f}  {p.height:12.0f}  {p.area:14.0f}  {p.quality.quality_score:7.2f}  {','.join(p.flags)}")

        # FID
        fid_peaks = res["fid_peaks"]
        fid_filtered = [p for p in fid_peaks
                        if rt_min <= p.apex_time <= rt_max]

        if res["fid_error"] is not None:
            print(f"  [FID] 处理失败: {res['fid_error']}")
        else:
            print(f"  [FID] 检测到 {len(fid_peaks)} 个峰 (RT {rt_min}-{rt_max} min 内 {len(fid_filtered)} 个)")
            if fid_filtered:
                print(f"  {'ID':>4s}  {'RT(min)':>8s}  {'Start':>8s}  {'End':>8s}  {'Width':>7s}  {'Height':>12s}  {'Area':>14s}  {'Quality':>7s}  {'Flags'}")
                print(f"  {'─'*4}  {'─'*8}  {'─'*8}  {'─'*8}  {'─'*7}  {'─'*12}  {'─'*14}  {'─'*7}  {'─'*20}")
                for p in fid_filtered:
                    width = p.end_time - p.start_time
                    print(f"  {p.peak_id:4d}  {p.apex_time:8.3f}  {p.start_time:8.3f}  {p.end_time:8.3f}  {width:7.3f}  {p.height:12.4f}  {p.area:14.6f}  {p.quality.quality_score:7.2f}  {','.join(p.flags)}")

    # 总体统计
    print(f"\n{sep}")
    print(f"  总体统计")
    print(sep)
    total_tic = sum(len([p for p in r["tic_peaks"] if rt_min <= p.apex_time <= rt_max]) for r in all_results)
    total_fid = sum(len([p for p in r["fid_peaks"] if rt_min <= p.apex_time <= rt_max]) for r in all_results)
    tic_errors = sum(1 for r in all_results if r["tic_error"] is not None)
    fid_errors = sum(1 for r in all_results if r["fid_error"] is not None)
    print(f"  TIC: {total_tic} 个峰 (RT {rt_min}-{rt_max}), {tic_errors} 个样本失败")
    print(f"  FID: {total_fid} 个峰 (RT {rt_min}-{rt_max}), {fid_errors} 个样本失败")

    # 多维 vs TIC-only 统计
    multidim_count = 0
    fallback_count = 0
    for r in all_results:
        for p in r["tic_peaks"]:
            if "gcms_multidim" in p.flags:
                multidim_count += 1
            elif "gcms_tic_only_fallback" in p.flags:
                fallback_count += 1
    print(f"  GC-MS 多维边界: {multidim_count} 个峰")
    print(f"  GC-MS TIC-only 回退: {fallback_count} 个峰")

    # FID 拟合统计
    fit_ok = sum(1 for r in all_results for p in r["fid_peaks"] if "fid_fit_ok" in p.flags)
    fit_fb = sum(1 for r in all_results for p in r["fid_peaks"] if "fid_fit_fallback" in p.flags)
    print(f"  FID 拟合成功: {fit_ok} 个峰")
    print(f"  FID 拟合回退: {fit_fb} 个峰")
    print(sep)


if __name__ == "__main__":
    main()
