#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    读取 Agilent .D 目录中的色谱/质谱数据.
    支持 TIC (总离子流色谱), FID (火焰离子化检测器) 和单扫描质谱.
    TIC 优先从智达软件自动导出的 tic_front.csv 读取,
    备选使用 rainbow-api 解析 data.ms 二进制文件.
参数:
    无.
返回:
    无.
"""

import csv
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class GCMSDataReader:
    """
    功能:
        读取 .D 目录中的色谱/质谱数据.
        优先使用 tic_front.csv (智达自动导出),
        备选使用 rainbow-api 解析 data.ms 和 FID1A.ch 二进制文件.
    参数:
        无.
    返回:
        无.
    """

    def read_tic(self, d_dir: Path) -> Tuple[np.ndarray, np.ndarray]:
        """
        功能:
            读取 TIC (总离子流色谱) 数据.
            优先从 tic_front.csv 解析, 不存在时用 rainbow-api 解析 data.ms.
        参数:
            d_dir: .D 目录路径.
        返回:
            Tuple[np.ndarray, np.ndarray]: (保留时间数组, 强度数组).
        """
        csv_path = d_dir / "tic_front.csv"
        if csv_path.exists():
            return self._read_tic_from_csv(csv_path)

        logger.info("tic_front.csv 不存在, 使用 rainbow-api 解析 data.ms")
        return self._read_tic_from_ms(d_dir)

    def _read_tic_from_csv(self, csv_path: Path) -> Tuple[np.ndarray, np.ndarray]:
        """
        功能:
            从智达软件导出的 tic_front.csv 解析 TIC 数据.
            文件格式: 第1行为路径信息, 第2行为 "Start of data points",
            后续每行为 "retention_time,intensity".
        参数:
            csv_path: tic_front.csv 文件路径.
        返回:
            Tuple[np.ndarray, np.ndarray]: (保留时间数组, 强度数组).
        """
        times = []
        intensities = []

        with csv_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                # 跳过头部信息行
                if not line or line.startswith("Start of") or not line[0].isdigit():
                    continue
                parts = line.split(",")
                if len(parts) >= 2:
                    try:
                        times.append(float(parts[0]))
                        intensities.append(float(parts[1]))
                    except ValueError:
                        continue

        logger.info("从 tic_front.csv 读取 %d 个数据点", len(times))
        return np.array(times), np.array(intensities)

    def _read_tic_from_ms(self, d_dir: Path) -> Tuple[np.ndarray, np.ndarray]:
        """
        功能:
            使用 rainbow-api 解析 data.ms, 计算 TIC (各扫描全离子强度之和).
        参数:
            d_dir: .D 目录路径.
        返回:
            Tuple[np.ndarray, np.ndarray]: (保留时间数组, TIC 强度数组).
        """
        import rainbow as rb

        datadir = rb.read(str(d_dir))
        ms_file = datadir.get_file("data.ms")
        if ms_file is None:
            raise FileNotFoundError(f"未找到 data.ms: {d_dir}")

        times = ms_file.xlabels          # shape: (n_scans,)
        tic = ms_file.data.sum(axis=1)   # 每次扫描的总离子强度

        logger.info("从 data.ms 读取 %d 个扫描, TIC 范围: %.0f - %.0f",
                     len(times), tic.min(), tic.max())
        return times, tic

    def read_fid(self, d_dir: Path) -> Tuple[np.ndarray, np.ndarray]:
        """
        功能:
            使用 rainbow-api 解析 FID1A.ch, 读取 FID 检测器信号.
        参数:
            d_dir: .D 目录路径.
        返回:
            Tuple[np.ndarray, np.ndarray]: (保留时间数组, FID 强度数组).
        """
        import rainbow as rb

        datadir = rb.read(str(d_dir))
        fid_file = datadir.get_file("FID1A.ch")
        if fid_file is None:
            raise FileNotFoundError(f"未找到 FID1A.ch: {d_dir}")

        times = fid_file.xlabels              # shape: (n_points,)
        intensities = fid_file.data[:, 0]     # shape: (n_points,), 取第一列

        logger.info("从 FID1A.ch 读取 %d 个数据点, 信号范围: %.2f - %.2f",
                     len(times), intensities.min(), intensities.max())
        return times, intensities

    def read_ms_spectra_at_rt(
        self, d_dir: Path, retention_time: float, tolerance: float = 0.02
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        功能:
            读取指定保留时间处的质谱数据 (m/z vs intensity).
            在 tolerance 范围内找到最近的扫描.
        参数:
            d_dir: .D 目录路径.
            retention_time: 目标保留时间 (min).
            tolerance: 保留时间匹配容差 (min).
        返回:
            Tuple[np.ndarray, np.ndarray]: (m/z 数组, 强度数组).
        """
        import rainbow as rb

        datadir = rb.read(str(d_dir))
        ms_file = datadir.get_file("data.ms")
        if ms_file is None:
            raise FileNotFoundError(f"未找到 data.ms: {d_dir}")

        # 找到最近的扫描索引
        idx = int(np.argmin(np.abs(ms_file.xlabels - retention_time)))
        actual_rt = ms_file.xlabels[idx]

        if abs(actual_rt - retention_time) > tolerance:
            logger.warning(
                "最近扫描 RT=%.3f 与目标 RT=%.3f 偏差 %.3f min, 超出容差 %.3f",
                actual_rt, retention_time, abs(actual_rt - retention_time), tolerance
            )

        spectrum = ms_file.data[idx]          # shape: (n_mz,)
        mz_values = ms_file.ylabels           # shape: (n_mz,)

        # 过滤零强度离子
        nonzero = spectrum > 0
        return mz_values[nonzero], spectrum[nonzero]

    def read_sample_info(self, d_dir: Path) -> Dict:
        """
        功能:
            从 AcqData/sample_info.xml 读取样品元数据.
        参数:
            d_dir: .D 目录路径.
        返回:
            Dict: 包含 sample_name, acq_time, method, data_file 等键.
        """
        info_path = d_dir / "AcqData" / "sample_info.xml"
        result = {}

        if not info_path.exists():
            logger.warning("sample_info.xml 不存在: %s", info_path)
            return result

        tree = ET.parse(str(info_path))
        root = tree.getroot()

        # 字段名到键名的映射
        field_map = {
            "Sample Name": "sample_name",
            "Sample Position": "sample_position",
            "Data File": "data_file",
            "Method": "method",
            "AcqTime": "acq_time",
            "RunCompletedFlag": "run_completed",
            "InstrumentName": "instrument_name",
            "Inj Vol (µl)": "inj_vol",
        }

        for field_elem in root.findall("Field"):
            name = field_elem.findtext("Name", "")
            value = field_elem.findtext("Value", "")
            if name in field_map:
                result[field_map[name]] = value

        logger.info("样品信息: %s", result.get("sample_name", "未知"))
        return result
