#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    分析站上层控制器, 读取合成任务 xlsx 中的实验信息和仪器方法配置,
    自动生成分析任务 CSV 并通过 ZhidaClient 提交至对应仪器.
    当前已实现 GC_MS 接入, UPLC_QTOF 和 HPLC 预留占位.
参数:
    无(通过 Settings 传入配置).
返回:
    无.
"""

import csv
import json
import logging
import io
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import openpyxl

from ..config.setting import Settings, configure_logging
from ..driver.zhida_driver import ZhidaClient
from ..processor.chromatogram_plotter import ChromatogramPlotter
from ..processor.data_reader import GCMSDataReader
from ..processor.peak_integrator import PeakIntegrator, PeakResult
from ..processor.nist_matcher import NISTMatcher
from ..processor.report_generator import ReportGenerator, SampleResult


def _natural_sort_key(path: Path) -> list:
    """
    功能:
        自然排序键函数, 将路径名中的连续数字段转换为 int 排序,
        非数字段按小写字符串排序, 实现 725-1 < 725-2 < 725-10 的效果.
    参数:
        path: 文件或目录路径.
    返回:
        list: 混合类型排序键列表.
    """
    parts = re.split(r'(\d+)', path.stem)
    return [int(p) if p.isdigit() else p.lower() for p in parts]


class AnalysisStationController:
    """
    功能:
        检测站上层控制器, 提供以下核心流程:
        1. 定位合成任务目录(按 task_id 或取最新任务).
        2. 检查任务状态(非 COMPLETED 时发出 warning 但继续).
        3. 解析任务 xlsx, 提取实验数量及各仪器方法名称.
        4. 生成分析任务 CSV, 双路保存.
        5. 通过 ZhidaClient 提交 CSV 给 GC_MS 仪器.
    参数:
        settings: Settings 实例, 为 None 时从环境变量读取.
    返回:
        无.
    """

    # CSV 列头(按仪器协议固定顺序)
    _CSV_HEADERS: List[str] = [
        "SampleName", "AcqMethod", "RackCode", "VialPos", "SmplInjVol", "OutputFile"
    ]

    # 默认 Rack 编号
    _DEFAULT_RACK_CODE: str = "Rack 6"

    # 默认进样量
    _DEFAULT_INJ_VOL: int = 1

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings or Settings.from_env()
        configure_logging(self._settings.log_level)
        self._logger = logging.getLogger(self.__class__.__name__)
        self._logger.info("分析站控制器初始化完成, 合成任务目录: %s", self._settings.synthesis_tasks_dir)

    # ------------------------------------------------------------------
    # 任务定位与状态检查
    # ------------------------------------------------------------------

    def _find_task_dir(self, task_id: Optional[str] = None) -> Tuple[Path, str]:
        """
        功能:
            定位合成任务目录.
            若指定 task_id 则直接定位, 否则取编号最大(最新)的任务目录.
        参数:
            task_id: 任务编号字符串, None 表示自动选取最新任务.
        返回:
            Tuple[Path, str]: (任务目录 Path, 任务 ID 字符串).
        """
        tasks_root = self._settings.synthesis_tasks_dir

        if not tasks_root.exists():
            raise FileNotFoundError(f"合成任务根目录不存在: {tasks_root}")

        if task_id is not None:
            # 按指定 ID 定位
            task_dir = tasks_root / str(task_id)
            if not task_dir.is_dir():
                raise FileNotFoundError(f"指定的任务目录不存在: {task_dir}")
            self._logger.info("使用指定任务目录: %s", task_dir)
            return task_dir, str(task_id)

        # 自动选取编号最大的子目录
        sub_dirs = [d for d in tasks_root.iterdir() if d.is_dir()]
        if not sub_dirs:
            raise FileNotFoundError(f"合成任务根目录下没有任务: {tasks_root}")

        # 尝试将目录名解析为整数排序, 取最大值
        def _dir_key(d: Path) -> int:
            try:
                return int(d.name)
            except ValueError:
                return -1

        latest_dir = max(sub_dirs, key=_dir_key)
        self._logger.info("自动选取最新任务目录: %s", latest_dir)
        return latest_dir, latest_dir.name

    def _check_task_status(self, task_dir: Path) -> str:
        """
        功能:
            读取 task_info.json 中的任务状态, 非 COMPLETED 时发出 warning.
        参数:
            task_dir: 任务目录 Path.
        返回:
            str: 任务状态字符串(如 "COMPLETED").
        """
        info_path = task_dir / "task_info.json"
        if not info_path.exists():
            self._logger.warning("未找到 task_info.json: %s, 跳过状态检查", info_path)
            return "UNKNOWN"

        with info_path.open("r", encoding="utf-8") as f:
            info = json.load(f)

        status = info.get("status", "UNKNOWN")

        if status != "COMPLETED":
            self._logger.warning(
                "任务 %s 状态为 [%s], 并非 COMPLETED, 将继续生成分析CSV.",
                info.get("task_id", "?"), status
            )
        else:
            self._logger.info("任务状态: %s", status)

        return status

    # ------------------------------------------------------------------
    # xlsx 解析
    # ------------------------------------------------------------------

    def _parse_task_xlsx(self, task_dir: Path, task_id: str) -> Dict:
        """
        功能:
            解析合成任务 xlsx 文件, 提取实验数量及各仪器方法名称.
            扫描 col A 定位 GC_MS/UPLC_QTOF/HPLC 字段(ASCII 可靠锚点),
            扫描 col C 统计实验数量(连续整数字符串).
        参数:
            task_dir: 任务目录 Path.
            task_id: 任务 ID 字符串.
        返回:
            Dict, 包含以下键:
                task_id (str): 任务 ID.
                exp_count (int): 实验数量.
                gc_ms_method (str|None): GC_MS 方法名, None 表示不使用.
                uplc_qtof_method (str|None): UPLC_QTOF 方法名.
                hplc_method (str|None): HPLC 方法名.
        """
        # 优先查找 .xlsx, 兼容 .csv
        xlsx_path = task_dir / f"{task_id}.xlsx"
        csv_path = task_dir / f"{task_id}.csv"

        if xlsx_path.exists():
            file_path = xlsx_path
        elif csv_path.exists():
            file_path = csv_path
        else:
            raise FileNotFoundError(
                f"未找到任务文件 {task_id}.xlsx 或 {task_id}.csv 于: {task_dir}"
            )

        self._logger.info("解析任务文件: %s", file_path)

        wb = openpyxl.load_workbook(file_path, data_only=True)
        ws = wb.active

        exp_count = 0
        gc_ms_method: Optional[str] = None
        uplc_qtof_method: Optional[str] = None
        hplc_method: Optional[str] = None

        for row in ws.iter_rows(values_only=True):
            col_a = row[0] if len(row) > 0 else None
            col_b = row[1] if len(row) > 1 else None
            col_c = row[2] if len(row) > 2 else None

            # 统计 col C 中连续整数形式的实验编号
            if col_c is not None:
                try:
                    exp_num = int(str(col_c).strip())
                    if exp_num > exp_count:
                        exp_count = exp_num  # 取最大值即为总数
                except (ValueError, TypeError):
                    pass

            # 定位仪器方法行(col A 为 ASCII 关键字)
            if col_a is None:
                continue
            col_a_str = str(col_a).strip()

            if col_a_str == "GC_MS":
                # col B 为方法名, 空值则跳过该仪器
                gc_ms_method = str(col_b).strip() if col_b is not None else None
            elif col_a_str == "UPLC_QTOF":
                uplc_qtof_method = str(col_b).strip() if col_b is not None else None
            elif col_a_str == "HPLC":
                hplc_method = str(col_b).strip() if col_b is not None else None

        if exp_count == 0:
            raise ValueError(f"未能从 {file_path} 中读取到有效实验编号, 请检查 col C 数据.")

        self._logger.info(
            "任务解析完成: 实验数=%d, GC_MS方法=%s, UPLC_QTOF方法=%s, HPLC方法=%s",
            exp_count, gc_ms_method, uplc_qtof_method, hplc_method
        )

        return {
            "task_id": task_id,
            "exp_count": exp_count,
            "gc_ms_method": gc_ms_method,
            "uplc_qtof_method": uplc_qtof_method,
            "hplc_method": hplc_method,
        }

    # ------------------------------------------------------------------
    # VialPos 计算
    # ------------------------------------------------------------------

    def _calc_vial_pos(self, exp_num: int) -> int:
        """
        功能:
            根据实验编号计算 GC-MS 进样位置 VialPos.

            样品托盘(闪滤瓶外瓶托盘) 规格: 6行(A-F) × 8列(1-8).
            装样遵循蛇形规则:
                偶数行(A/C/E): 从左到右 col 1→8.
                奇数行(B/D/F): 从右到左 col 8→1.
            GC-MS 进样位置从 F8=1 向上递增, 直至 A1=48.
        参数:
            exp_num: 实验编号, 范围 1-48.
        返回:
            int, 对应的 VialPos(1-48).
        """
        exp_0 = exp_num - 1              # 转为 0-indexed
        row_0 = exp_0 // 8              # 行索引: 0=A, 1=B, ..., 5=F
        col_within = exp_0 % 8          # 该行内第几个样品(0-indexed)

        # 蛇形: 奇数行(B/D/F)列方向翻转
        col_0 = col_within if row_0 % 2 == 0 else 7 - col_within

        row = row_0 + 1                 # 1=A, ..., 6=F
        col = col_0 + 1                 # 1-8

        # VialPos: F8=1, F7=2, ..., A1=48
        vial_pos = (6 - row) * 8 + (9 - col)
        return vial_pos

    # ------------------------------------------------------------------
    # CSV 生成
    # ------------------------------------------------------------------

    def _generate_gc_ms_csv(self, task_id: str, exp_count: int, method: str) -> str:
        """
        功能:
            生成 GC_MS 分析任务 CSV 字符串.
            每一行对应一个实验样品, VialPos 由蛇形映射公式计算.
        参数:
            task_id: 任务 ID, 用于拼接 SampleName/OutputFile.
            exp_count: 实验数量.
            method: GC_MS 方法名称.
        返回:
            str: CSV 文本内容(含列头).
        """
        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\n")

        # 写入列头
        writer.writerow(self._CSV_HEADERS)

        for exp_num in range(1, exp_count + 1):
            sample_name = f"{task_id}-{exp_num}"          # 如 "719-1"
            vial_pos = self._calc_vial_pos(exp_num)        # VialPos 蛇形映射
            writer.writerow([
                sample_name,                               # SampleName
                method,                                    # AcqMethod
                self._DEFAULT_RACK_CODE,                   # RackCode
                vial_pos,                                  # VialPos
                self._DEFAULT_INJ_VOL,                     # SmplInjVol
                sample_name,                               # OutputFile(与 SampleName 相同)
            ])

        return output.getvalue()

    # ------------------------------------------------------------------
    # CSV 保存
    # ------------------------------------------------------------------

    def _save_csv(self, content: str, task_id: str, instrument: str) -> List[Path]:
        """
        功能:
            将 CSV 内容双路保存:
            1. 分析站本地数据目录: eit_analysis_station/data/<task_id>/<instrument>.csv.
            2. 合成任务目录: eit_synthesis_station/data/tasks/<task_id>/<instrument>.csv.
        参数:
            content: CSV 文本内容.
            task_id: 任务 ID.
            instrument: 仪器名称(如 "gc_ms", "hplc", "uplc_qtof").
        返回:
            List[Path]: 实际保存的文件路径列表.
        """
        filename = f"{instrument}.csv"
        saved_paths: List[Path] = []

        # 路径 1: 分析站本地 data/<task_id>/
        local_dir = self._settings.data_dir / task_id
        local_dir.mkdir(parents=True, exist_ok=True)
        local_path = local_dir / filename
        local_path.write_text(content, encoding="utf-8")
        self._logger.info("CSV 已保存至本地: %s", local_path)
        saved_paths.append(local_path)

        # 路径 2: 合成任务目录 synthesis_tasks/<task_id>/
        syn_dir = self._settings.synthesis_tasks_dir / task_id
        if syn_dir.is_dir():
            syn_path = syn_dir / filename
            syn_path.write_text(content, encoding="utf-8")
            self._logger.info("CSV 已同步至合成任务目录: %s", syn_path)
            saved_paths.append(syn_path)
        else:
            self._logger.warning("合成任务目录不存在, 跳过同步: %s", syn_dir)

        return saved_paths

    # ------------------------------------------------------------------
    # GC_MS 提交流程
    # ------------------------------------------------------------------

    def _do_submit_gc_ms(self, resolved_id: str, task_info: Dict) -> Dict:
        """
        功能:
            GC_MS 提交核心逻辑(内部方法), 接收已解析的任务信息直接执行,
            避免 run_analysis 统一调度时重复解析 xlsx.
        参数:
            resolved_id: 任务 ID 字符串.
            task_info: _parse_task_xlsx 返回的任务信息字典.
        返回:
            Dict: {"success": bool, "return_info": str}.
        """
        gc_ms_method = task_info["gc_ms_method"]

        if gc_ms_method is None:
            msg = f"任务 {resolved_id} 未配置 GC_MS 方法, 跳过 GC_MS 提交."
            self._logger.info(msg)
            return {"success": True, "return_info": msg}

        # 步骤1: 生成并保存 CSV
        csv_content = self._generate_gc_ms_csv(
            resolved_id, task_info["exp_count"], gc_ms_method
        )
        saved_paths = self._save_csv(csv_content, resolved_id, "gc_ms")

        # 步骤2: 通过 ZhidaClient 提交至 GC_MS 仪器
        client = ZhidaClient(
            host=self._settings.gc_ms_host,
            port=self._settings.gc_ms_port,
            timeout=self._settings.gc_ms_timeout,
        )
        self._logger.info(
            "连接 GC_MS: %s:%d", self._settings.gc_ms_host, self._settings.gc_ms_port
        )

        try:
            client.connect()
            # 使用本地保存的第一份 CSV 文件提交
            submit_path = str(saved_paths[0])
            result = client.start_with_csv_file(string=submit_path)
        finally:
            client.close()  # 确保连接关闭

        self._logger.info("GC_MS 提交结果: %s", result)
        return result

    def submit_gc_ms(self, task_id: Optional[str] = None) -> Dict:
        """
        功能:
            GC_MS 分析任务完整提交流程(公开入口, 独立调用时使用):
            1. 定位任务目录(task_id 或最新).
            2. 检查 task_info.json 状态(非 COMPLETED 则 warning 后继续).
            3. 解析 xlsx, 若无 gc_ms_method 则跳过提交.
            4. 生成分析 CSV 并双路保存.
            5. ZhidaClient 连接 GC_MS 并调用 start_with_csv_file 提交.
        参数:
            task_id: 任务 ID 字符串, None 表示自动选取最新任务.
        返回:
            Dict: {"success": bool, "return_info": str}.
        """
        try:
            # 定位任务目录
            task_dir, resolved_id = self._find_task_dir(task_id)
            # 检查任务状态(仅 warning, 不阻断)
            self._check_task_status(task_dir)
            # 解析 xlsx
            task_info = self._parse_task_xlsx(task_dir, resolved_id)
            # 调用核心提交逻辑
            return self._do_submit_gc_ms(resolved_id, task_info)

        except Exception as exc:
            msg = f"GC_MS 提交失败: {exc}"
            self._logger.error(msg)
            return {"success": False, "return_info": msg}

    # ------------------------------------------------------------------
    # 统一分析入口
    # ------------------------------------------------------------------

    def run_analysis(self, task_id: Optional[str] = None) -> Dict:
        """
        功能:
            统一分析入口, 依据 xlsx 中各仪器方法配置依次处理.
            xlsx 仅解析一次, 各仪器提交直接调用内部核心方法避免重复解析.
            当前已实现: GC_MS.
            预留未实现: UPLC_QTOF, HPLC(方法存在时发出 warning).
        参数:
            task_id: 任务 ID 字符串, None 表示自动选取最新任务.
        返回:
            Dict: {"gc_ms": result_dict, "uplc_qtof": result_dict, "hplc": result_dict}.
        """
        results: Dict = {}

        try:
            # 定位任务目录并解析 xlsx(仅执行一次)
            task_dir, resolved_id = self._find_task_dir(task_id)
            self._check_task_status(task_dir)
            task_info = self._parse_task_xlsx(task_dir, resolved_id)
        except Exception as exc:
            msg = f"任务初始化失败: {exc}"
            self._logger.error(msg)
            return {"error": msg}

        # ---------- GC_MS ----------
        if task_info["gc_ms_method"] is not None:
            self._logger.info("开始提交 GC_MS 分析任务...")
            try:
                # 直接调用核心方法，跳过重复的定位+解析步骤
                results["gc_ms"] = self._do_submit_gc_ms(resolved_id, task_info)
            except Exception as exc:
                results["gc_ms"] = {"success": False, "return_info": f"GC_MS 提交失败: {exc}"}
        else:
            results["gc_ms"] = {"success": True, "return_info": "未配置 GC_MS 方法, 已跳过."}

        # ---------- UPLC_QTOF(预留) ----------
        if task_info["uplc_qtof_method"] is not None:
            self._logger.warning(
                "任务 %s 配置了 UPLC_QTOF 方法 [%s], 但 UPLC_QTOF 接入尚未实现, 已跳过.",
                resolved_id, task_info["uplc_qtof_method"]
            )
            results["uplc_qtof"] = {"success": False, "return_info": "UPLC_QTOF 接入尚未实现."}
        else:
            results["uplc_qtof"] = {"success": True, "return_info": "未配置 UPLC_QTOF 方法, 已跳过."}

        # ---------- HPLC(预留) ----------
        if task_info["hplc_method"] is not None:
            self._logger.warning(
                "任务 %s 配置了 HPLC 方法 [%s], 但 HPLC 接入尚未实现, 已跳过.",
                resolved_id, task_info["hplc_method"]
            )
            results["hplc"] = {"success": False, "return_info": "HPLC 接入尚未实现."}
        else:
            results["hplc"] = {"success": True, "return_info": "未配置 HPLC 方法, 已跳过."}

        self._logger.info("分析任务提交完毕, 结果: %s", results)
        return results

    # ------------------------------------------------------------------
    # GC_MS 结果处理(积分 + 定性 + 报告)
    # ------------------------------------------------------------------

    def _enumerate_d_dirs(self, task_id: str) -> List[Path]:
        """
        功能:
            枚举指定任务下所有 .D 结果目录.
            先在仪器侧网络目录查找, 再在本地 data 目录查找.
        参数:
            task_id: 任务 ID.
        返回:
            List[Path]: 找到的 .D 目录列表, 按样品编号排序.
        """
        d_dirs: List[Path] = []

        # 优先查找仪器侧网络目录
        remote_data_dir = self._settings.gc_ms_data_dir
        if remote_data_dir.exists():
            # 匹配 <task_id>-<num>.D 格式
            for d_dir in sorted(remote_data_dir.glob(f"{task_id}-*.D"), key=_natural_sort_key):
                if d_dir.is_dir():
                    d_dirs.append(d_dir)

        if d_dirs:
            self._logger.info("从仪器侧目录找到 %d 个 .D 文件: %s", len(d_dirs), remote_data_dir)
            return d_dirs

        # 备选: 在本地 data/<task_id>/ 目录下查找
        local_data_dir = self._settings.data_dir / task_id
        if local_data_dir.exists():
            for d_dir in sorted(local_data_dir.glob("*.D"), key=_natural_sort_key):
                if d_dir.is_dir():
                    d_dirs.append(d_dir)

        if d_dirs:
            self._logger.info("从本地目录找到 %d 个 .D 文件: %s", len(d_dirs), local_data_dir)
        else:
            self._logger.warning("未找到任务 %s 的 .D 结果目录", task_id)

        return d_dirs

    def _load_expected_samples(self, task_id: str) -> List[str]:
        """
        功能:
            从本地数据目录的 gc_ms.csv 读取预期样品列表, 按 CSV 行顺序返回.
            CSV 由 _save_csv 生成, 格式为:
            SampleName,AcqMethod,RackCode,VialPos,SmplInjVol,OutputFile.
        参数:
            task_id: 任务 ID 字符串.
        返回:
            List[str]: 样品名称列表, 如 ["725-1", "725-2", ..., "725-12"].
        """
        csv_path = self._settings.data_dir / task_id / "gc_ms.csv"
        if not csv_path.exists():
            raise FileNotFoundError(f"未找到样品列表文件: {csv_path}")

        with csv_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            samples = [row["SampleName"] for row in reader]

        if not samples:
            raise ValueError(f"样品列表为空: {csv_path}")

        self._logger.info("从 gc_ms.csv 加载 %d 个预期样品", len(samples))
        return samples

    def _read_run_completed_flag(self, d_dir: Path) -> Optional[bool]:
        """
        功能:
            读取 .D 目录下 AcqData/sample_info.xml 中的 RunCompletedFlag 字段.
            解析 XML 中所有 <Field> 元素, 找到 Name 为 "RunCompletedFlag" 的条目,
            返回其 Value 的布尔解析结果.
        参数:
            d_dir: .D 目录路径.
        返回:
            Optional[bool]: True 表示采集完成, False 表示采集中,
                            None 表示文件不存在或解析失败.
        """
        info_path = d_dir / "AcqData" / "sample_info.xml"
        if not info_path.exists():
            return None

        try:
            tree = ET.parse(str(info_path))
            root = tree.getroot()
            for field_elem in root.findall("Field"):
                name = field_elem.findtext("Name", "")
                if name == "RunCompletedFlag":
                    value = field_elem.findtext("Value", "").strip()
                    return value.lower() == "true"
            # RunCompletedFlag 字段不存在, 视为未完成
            return False
        except (ET.ParseError, OSError) as exc:
            # 文件可能正在被仪器写入, 视为采集中
            self._logger.debug("解析 %s 失败: %s, 视为采集中", info_path, exc)
            return None

    def _filter_peaks(
        self,
        peaks: List[PeakResult],
        area_min: Optional[float] = None,
        area_max: Optional[float] = None,
    ) -> List[PeakResult]:
        """
        功能:
            按保留时间范围和面积阈值过滤峰列表, 过滤后重新计算面积百分比.
        参数:
            peaks: 积分后的峰列表.
            area_min: 峰面积下限, None 表示不过滤.
            area_max: 峰面积上限, None 表示不过滤.
        返回:
            List[PeakResult]: 过滤后的峰列表.
        """
        filtered = peaks

        # 保留时间范围过滤 (TIC/FID 共用)
        if self._settings.peak_rt_min is not None:
            filtered = [p for p in filtered if p.retention_time >= self._settings.peak_rt_min]
        if self._settings.peak_rt_max is not None:
            filtered = [p for p in filtered if p.retention_time <= self._settings.peak_rt_max]

        # 面积范围过滤 (TIC/FID 分别传入不同阈值)
        if area_min is not None:
            filtered = [p for p in filtered if p.area >= area_min]
        if area_max is not None:
            filtered = [p for p in filtered if p.area <= area_max]

        # 重新计算面积百分比
        if len(filtered) < len(peaks):
            total_area = sum(p.area for p in filtered)
            if total_area > 0:
                for p in filtered:
                    p.area_percent = (p.area / total_area) * 100.0
            self._logger.info("峰过滤: %d -> %d 个峰", len(peaks), len(filtered))

        return filtered

    def _process_single_sample(
        self, d_dir: Path, nist: NISTMatcher, report_dir: Optional[Path] = None,
    ) -> SampleResult:
        """
        功能:
            处理单个 .D 目录: 读取 TIC/FID, 积分, NIST 匹配, 生成色谱图.
        参数:
            d_dir: .D 目录路径.
            nist: NISTMatcher 实例 (由外部传入, 保持状态复用).
            report_dir: 报告输出目录, 用于保存色谱图. None 则不生成图.
        返回:
            SampleResult: 该样品的完整积分结果.
        """
        reader = GCMSDataReader()

        # 读取样品元数据
        sample_info = reader.read_sample_info(d_dir)
        sample_name = sample_info.get("sample_name", d_dir.stem)
        acq_time = sample_info.get("acq_time", "")

        result = SampleResult(
            sample_name=sample_name,
            d_dir=d_dir,
            acq_time=acq_time,
        )

        # 缓存色谱数据, 供后续绘图复用
        tic_times = tic_intensities = None
        fid_times = fid_intensities = None
        tic_baseline = fid_baseline = None  # 积分基线, 供绘图使用

        # TIC 积分
        try:
            tic_times, tic_intensities = reader.read_tic(d_dir)
            tic_integrator = PeakIntegrator(
                smoothing_window=self._settings.peak_smoothing_window,
                prominence=self._settings.peak_prominence,
                min_distance=self._settings.peak_min_distance,
                width_rel_height=self._settings.peak_width_rel_height,
                use_als_baseline=self._settings.use_als_baseline,
                als_lambda=self._settings.als_lambda,
                als_p=self._settings.als_p,
                use_valley_boundary=self._settings.use_valley_boundary,
                integration_mode=self._settings.integration_mode,
                baseline_method=self._settings.baseline_method,
                baseline_quantile=self._settings.baseline_quantile,
                baseline_window_min=self._settings.baseline_window_min,
                boundary_sigma_factor=self._settings.boundary_sigma_factor,
                boundary_edge_ratio=self._settings.boundary_edge_ratio,
                boundary_expand_factor=self._settings.boundary_expand_factor,
                boundary_min_span_min=self._settings.boundary_min_span_min,
                boundary_max_span_min=self._settings.boundary_max_span_min,
            )
            result.tic_peaks = tic_integrator.integrate(tic_times, tic_intensities)
            tic_baseline = tic_integrator.last_baseline
            result.tic_peaks = self._filter_peaks(
                result.tic_peaks,
                area_min=self._settings.tic_area_min,
                area_max=self._settings.tic_area_max,
            )
            self._logger.info("样品 %s TIC 积分: %d 个峰", sample_name, len(result.tic_peaks))
        except Exception as e:
            self._logger.error("样品 %s TIC 积分失败: %s", sample_name, e)

        # FID 积分
        try:
            fid_times, fid_intensities = reader.read_fid(d_dir)
            fid_integrator = PeakIntegrator(
                smoothing_window=self._settings.peak_smoothing_window,
                prominence=self._settings.fid_peak_prominence,
                min_distance=self._settings.fid_peak_min_distance,
                width_rel_height=self._settings.peak_width_rel_height,
                use_als_baseline=self._settings.use_als_baseline,
                als_lambda=self._settings.als_lambda,
                als_p=self._settings.als_p,
                use_valley_boundary=self._settings.use_valley_boundary,
                integration_mode=self._settings.integration_mode,
                baseline_method=self._settings.baseline_method,
                baseline_quantile=self._settings.baseline_quantile,
                baseline_window_min=self._settings.baseline_window_min,
                boundary_sigma_factor=self._settings.boundary_sigma_factor,
                boundary_edge_ratio=self._settings.boundary_edge_ratio,
                boundary_expand_factor=self._settings.boundary_expand_factor,
                boundary_min_span_min=self._settings.boundary_min_span_min,
                boundary_max_span_min=self._settings.boundary_max_span_min,
            )
            result.fid_peaks = fid_integrator.integrate(fid_times, fid_intensities)
            fid_baseline = fid_integrator.last_baseline
            result.fid_peaks = self._filter_peaks(
                result.fid_peaks,
                area_min=self._settings.fid_area_min,
                area_max=self._settings.fid_area_max,
            )
            self._logger.info("样品 %s FID 积分: %d 个峰", sample_name, len(result.fid_peaks))
        except Exception as e:
            self._logger.error("样品 %s FID 积分失败: %s", sample_name, e)

        # NIST 化合物匹配 (优先使用 NIST MS Search 自动化)
        try:
            if nist.nist_available and result.tic_peaks:
                # 提取各 TIC 峰的质谱并通过 NIST 搜索匹配
                result.compound_matches = nist.match_peaks_with_nist(
                    d_dir, result.tic_peaks, reader,
                    avg_scans=self._settings.nist_avg_scans,
                )
                if result.compound_matches:
                    self._logger.info(
                        "样品 %s NIST 自动匹配: %d 个峰有匹配结果",
                        sample_name, len(result.compound_matches)
                    )
                # 记录 NIST 结果文件副本路径
                if hasattr(nist, '_saved_srcreslt') and nist._saved_srcreslt is not None:
                    result.nist_result_path = nist._saved_srcreslt
            else:
                # 降级: 从 MassHunter 已有报告中提取
                result.compound_matches = nist.match_from_qual_results(d_dir)

            if not result.compound_matches:
                self._logger.info("样品 %s 无可用的 NIST 定性结果", sample_name)
        except Exception as e:
            self._logger.error("样品 %s NIST 匹配失败: %s", sample_name, e)

        # 生成色谱图 (TIC + FID)
        if report_dir is not None:
            plotter = ChromatogramPlotter()
            plot_dir = report_dir / "plots"

            # TIC 色谱图
            if tic_times is not None and result.tic_peaks:
                try:
                    tic_plot = plot_dir / f"{sample_name}_tic.png"
                    result.tic_plot_path = plotter.plot_chromatogram(
                        tic_times, tic_intensities, result.tic_peaks,
                        compound_matches=result.compound_matches or None,
                        title=f"TIC Chromatogram - {sample_name}",
                        ylabel="TIC Intensity",
                        output_path=tic_plot,
                        rt_min=self._settings.peak_rt_min,
                        rt_max=self._settings.peak_rt_max,
                        baseline=tic_baseline,
                        fill_baseline_mode="local",
                    )
                except Exception as e:
                    self._logger.error("样品 %s TIC 色谱图生成失败: %s", sample_name, e)

            # FID 色谱图
            if fid_times is not None and result.fid_peaks:
                try:
                    fid_plot = plot_dir / f"{sample_name}_fid.png"
                    result.fid_plot_path = plotter.plot_chromatogram(
                        fid_times, fid_intensities, result.fid_peaks,
                        compound_matches=None,  # FID 不标注化合物
                        title=f"FID Chromatogram - {sample_name}",
                        ylabel="FID Signal",
                        output_path=fid_plot,
                        rt_min=self._settings.peak_rt_min,
                        rt_max=self._settings.peak_rt_max,
                        y_range_min=100,  # FID 信号较小, 确保 Y 轴最小范围
                        baseline=fid_baseline,
                        fill_baseline_mode="local",
                    )
                except Exception as e:
                    self._logger.error("样品 %s FID 色谱图生成失败: %s", sample_name, e)

        return result

    def process_gc_ms_results(self, task_id: Optional[str] = None) -> Dict:
        """
        功能:
            GC-MS 运行完成后的结果处理入口:
            1. 定位任务目录, 找到所有 .D 结果文件.
            2. 逐个读取 TIC/FID 数据并积分.
            3. 读取/匹配 NIST 定性结果.
            4. 按任务汇总生成 Excel 报告.
        参数:
            task_id: 任务 ID 字符串, None 表示自动选取最新任务.
        返回:
            Dict: {"success": bool, "return_info": str, "report_path": str}.
        """
        try:
            # 定位任务(取 resolved_id, task_dir 不直接使用)
            _, resolved_id = self._find_task_dir(task_id)
            self._logger.info("开始处理任务 %s 的 GC-MS 结果", resolved_id)

            # 枚举 .D 目录
            d_dirs = self._enumerate_d_dirs(resolved_id)
            if not d_dirs:
                return {
                    "success": False,
                    "return_info": f"任务 {resolved_id} 未找到 .D 结果目录",
                }

            # 初始化 NIST 匹配器 (复用同一实例)
            nist = NISTMatcher(
                nist_path=self._settings.nist_path,
                max_hits=self._settings.nist_max_hits,
                search_timeout=self._settings.nist_search_timeout,
            )

            # 本地报告目录 (色谱图也保存在此)
            local_report_dir = self._settings.report_dir / resolved_id

            # 逐样品处理
            sample_results: List[SampleResult] = []
            for d_dir in d_dirs:
                self._logger.info("处理样品: %s", d_dir.name)
                sr = self._process_single_sample(d_dir, nist, report_dir=local_report_dir)
                sample_results.append(sr)

            # 收集所有唯一 CAS 号, 批量获取化合物结构图
            structure_images = {}
            all_cas_numbers = set()
            for sr in sample_results:
                for match_list in sr.compound_matches.values():
                    for m in match_list:
                        if m.cas_number:
                            all_cas_numbers.add(m.cas_number)

            if all_cas_numbers:
                try:
                    from ..processor.structure_fetcher import StructureFetcher
                    fetcher = StructureFetcher(
                        task_cache_dir=local_report_dir / "structures",
                        global_cache_dir=self._settings.structure_cache_dir,
                    )
                    structure_images = fetcher.fetch_batch(list(all_cas_numbers))
                except Exception as e:
                    self._logger.warning("化合物结构图获取失败, 报告将不含结构图: %s", e)

            # 生成 Excel 报告
            generator = ReportGenerator()

            # 保存到本地数据目录
            report_path = generator.generate_task_report(
                resolved_id, sample_results, local_report_dir,
                structure_images=structure_images,
            )

            # 同步到合成任务目录
            syn_dir = self._settings.synthesis_tasks_dir / resolved_id
            if syn_dir.is_dir():
                syn_report = generator.generate_task_report(
                    resolved_id, sample_results, syn_dir,
                    structure_images=structure_images,
                )
                self._logger.info("报告已同步至合成任务目录: %s", syn_report)

            # 统计摘要
            total_tic_peaks = sum(len(sr.tic_peaks) for sr in sample_results)
            total_fid_peaks = sum(len(sr.fid_peaks) for sr in sample_results)
            msg = (
                f"任务 {resolved_id} 结果处理完成: "
                f"{len(sample_results)} 个样品, "
                f"TIC 共 {total_tic_peaks} 个峰, "
                f"FID 共 {total_fid_peaks} 个峰, "
                f"报告: {report_path}"
            )
            self._logger.info(msg)

            return {
                "success": True,
                "return_info": msg,
                "report_path": str(report_path),
            }

        except Exception as exc:
            msg = f"结果处理失败: {exc}"
            self._logger.error(msg)
            return {"success": False, "return_info": msg}

    def poll_analysis_run(
        self, task_id: Optional[str] = None, poll_interval: float = 30.0
    ) -> Dict:
        """
        功能:
            基于文件监控的 GC-MS 分析任务轮询.
            1. 从 gc_ms.csv 读取预期样品列表, 确定总样品数和采集顺序.
            2. 循环检查数据目录中 .D 目录的出现情况.
            3. 对每个 .D 目录, 解析 AcqData/sample_info.xml 中的
               RunCompletedFlag 判断采集状态:
               - .D 目录不存在 -> "等待进样"
               - .D 存在但 RunCompletedFlag 非 True -> "采集中"
               - RunCompletedFlag 为 True -> "采集结束"
            4. 实时反馈每个样品的状态变更和整体进度.
            5. 当所有样品均为 "采集结束" 时, 调用 process_gc_ms_results 处理结果.
        参数:
            task_id: 任务 ID 字符串, None 表示自动选取最新任务.
            poll_interval: 轮询间隔(秒), 默认 30 秒.
        返回:
            Dict: process_gc_ms_results 的返回值, 包含 success/return_info/report_path.
        """
        # 解析任务 ID
        _, resolved_id = self._find_task_dir(task_id)

        # 从 gc_ms.csv 加载预期样品列表(按表格顺序)
        try:
            expected_samples = self._load_expected_samples(resolved_id)
        except (FileNotFoundError, ValueError) as exc:
            msg = f"加载预期样品列表失败: {exc}"
            self._logger.error(msg)
            return {"success": False, "return_info": msg}

        total = len(expected_samples)

        # 确定 .D 目录搜索路径: 优先远程仪器目录, 回退到本地数据目录
        remote_data_dir = self._settings.gc_ms_data_dir
        local_data_dir = self._settings.data_dir / resolved_id
        if remote_data_dir.exists():
            search_dir = remote_data_dir
        else:
            self._logger.warning(
                "远程数据目录不可达: %s, 回退到本地目录: %s",
                remote_data_dir, local_data_dir
            )
            search_dir = local_data_dir

        self._logger.info(
            "开始文件监控轮询, 任务 %s, 共 %d 个样品, 间隔 %.0f 秒, 监控目录: %s",
            resolved_id, total, poll_interval, search_dir
        )

        # 记录每个样品的上次状态, 用于检测状态变更
        prev_status: Dict[str, str] = {name: "" for name in expected_samples}

        try:
            while True:
                completed_count = 0

                for idx, sample_name in enumerate(expected_samples, start=1):
                    d_dir = search_dir / f"{sample_name}.D"

                    # 判断当前样品采集状态
                    if not d_dir.exists():
                        status = "等待进样"
                    else:
                        flag = self._read_run_completed_flag(d_dir)
                        if flag is True:
                            status = "采集结束"
                        else:
                            status = "采集中"

                    # 状态变更时输出日志
                    if status != prev_status[sample_name]:
                        self._logger.info(
                            "[%d/%d] 样品 %s: %s -> %s",
                            idx, total, sample_name,
                            prev_status[sample_name] or "(初始)", status
                        )
                        prev_status[sample_name] = status

                    if status == "采集结束":
                        completed_count += 1

                # 输出整体进度
                self._logger.info(
                    "轮询进度: %d/%d 样品已完成采集", completed_count, total
                )

                # 全部采集完成, 进入结果处理
                if completed_count == total:
                    self._logger.info(
                        "任务 %s 全部 %d 个样品采集完成, 开始处理结果...",
                        resolved_id, total
                    )
                    return self.process_gc_ms_results(resolved_id)

                time.sleep(poll_interval)

        except KeyboardInterrupt:
            self._logger.info("轮询被用户中断")
            return {"success": False, "return_info": "轮询被用户中断"}


# ------------------------------------------------------------------
# 交互式测试入口
# ------------------------------------------------------------------

def _print_result(result: Dict) -> None:
    """
    功能:
        格式化打印函数返回结果.
    参数:
        result: 函数返回的字典.
    返回:
        无.
    """
    print("\n========== 执行结果 ==========")
    for key, value in result.items():
        print(f"  {key}: {value}")
    print("==============================\n")


def main() -> None:
    """
    功能:
        交互式菜单, 用于手动测试 run_analysis / process_gc_ms_results /
        poll_analysis_run / get_status / get_methods.
        用户可选择功能并输入 task_id, 输入 q 退出.
    参数:
        无.
    返回:
        无.
    """
    configure_logging("DEBUG")
    logger = logging.getLogger("main")
    logger.info("初始化分析站控制器...")

    controller = AnalysisStationController()

    menu = (
        "\n===== 分析站交互式测试菜单 =====\n"
        "  1. run_analysis          - 统一分析入口(生成CSV并提交至仪器)\n"
        "  2. process_gc_ms_results - GC-MS结果处理(积分+定性+报告)\n"
        "  3. poll_analysis_run    - 轮询GC-MS分析任务状态并自动处理结果\n"
        "  4. get_status            - 获取GC-MS设备当前状态\n"
        "  5. get_methods           - 获取当前Project的方法列表\n"
        "  q. 退出\n"
        "================================"
    )

    while True:
        print(menu)
        choice = input("请选择功能编号: ").strip()

        if choice in ("q", "Q"):
            print("已退出测试.")
            break

        if choice not in ("1", "2", "3", "4", "5"):
            print("无效选择, 请输入 1/2/3/4/5 或 q.")
            continue

        # 选项 4/5 直接操作设备驱动, 不需要 task_id
        if choice in ("4", "5"):
            settings = controller._settings
            client = ZhidaClient(
                host=settings.gc_ms_host,
                port=settings.gc_ms_port,
                timeout=settings.gc_ms_timeout,
            )
            try:
                client.connect()
                if choice == "4":
                    print("\n>>> 调用 ZhidaClient.get_status()")
                    status = client.get_status()
                    print(f"\n  设备状态: {status}\n")
                else:
                    print("\n>>> 调用 ZhidaClient.get_methods()")
                    methods = client.get_methods()
                    _print_result(methods)
            except Exception as exc:
                logger.error("设备操作失败: %s", exc)
                print(f"\n  操作失败: {exc}\n")
            finally:
                client.close()
            continue

        # 获取 task_id, 空字符串视为 None(自动选取最新任务)
        task_id_input = input("请输入 task_id (留空则自动选取最新任务): ").strip()
        task_id = task_id_input if task_id_input else None

        if choice == "1":
            print(f"\n>>> 调用 run_analysis(task_id={task_id!r})")
            result = controller.run_analysis(task_id=task_id)
            _print_result(result)

        elif choice == "2":
            print(f"\n>>> 调用 process_gc_ms_results(task_id={task_id!r})")
            result = controller.process_gc_ms_results(task_id=task_id)
            _print_result(result)

        elif choice == "3":
            # poll_analysis_run 额外支持配置轮询间隔
            interval_input = input("请输入轮询间隔秒数 (留空默认30): ").strip()
            try:
                interval = float(interval_input) if interval_input else 30.0
            except ValueError:
                print("无效数值, 使用默认30秒.")
                interval = 30.0

            print(
                f"\n>>> 调用 poll_analysis_run(task_id={task_id!r}, "
                f"poll_interval={interval})"
            )
            result = controller.poll_analysis_run(
                task_id=task_id, poll_interval=interval
            )
            _print_result(result)


if __name__ == "__main__":
    main()
