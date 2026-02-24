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
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import openpyxl

from ..config.setting import Settings, configure_logging
from ..driver.zhida_driver import ZhidaClient


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
