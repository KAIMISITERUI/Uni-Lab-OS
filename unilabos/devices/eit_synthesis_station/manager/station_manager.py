# -*- coding: utf-8 -*-
import csv
import re
import logging
import shutil
import pandas as pd
import openpyxl
from datetime import datetime
from openpyxl import Workbook,load_workbook
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.styles import Font, Alignment, NamedStyle 
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 引入底层的控制器
from ..controller.station_controller import SynthesisStationController
from ..config.setting import Settings, configure_logging
from ..config.constants import ResourceCode, TRAY_CODE_DISPLAY_NAME, TraySpec
from .synchronizer import EITSynthesisWorkstation

from ..driver.exceptions import ValidationError,ApiError
from ..utils.file_utils import safe_excel_write, safe_workbook_save

logger = logging.getLogger("StationManager")

JsonDict = Dict[str, Any]

# 模块根目录, 用于构建相对路径
MODULE_ROOT = Path(__file__).resolve().parent.parent

class SynthesisStationManager(EITSynthesisWorkstation, SynthesisStationController):
    """
    功能:
        上层面向用户的管理器，继承自 SynthesisStationController。
        负责处理 CSV/Excel 文件读取、生成模板，将文件内容转换为中间格式(List/Dict)，
        然后调用父类方法执行具体的业务逻辑。
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        config: Optional[Dict[str, Any]] = None,
        deck: Optional[Any] = None,
        **kwargs,
    ):
        settings = settings or Settings.from_env()
        configure_logging(settings.log_level)
        SynthesisStationController.__init__(self, settings)
        EITSynthesisWorkstation.__init__(
            self,
            config=config,
            deck=deck,
            controller=self,
            **kwargs,
        )

    # ---------- 1. 化合物库文件处理 ----------
    def export_chemical_list_to_file(self, output_path: str) -> None:
        """
        功能:
            获取所有化学品并导出到 CSV 文件
        参数:
            output_path: 输出路径
        返回:
            None
        """
        path = Path(output_path)
        chemical_info = self.get_all_chemical_list()
        chemical_list = chemical_info.get("chemical_list", [])

        if not chemical_list:
            logger.warning("化学品列表为空，未写入文件")
            return

        fieldnames = [
            "fid", "name", "sssi", "cas", "element", "state",
            "concentration_str", "chemical_properties", "preparation_method"
        ]
        
        # 确保目录存在
        path.parent.mkdir(parents=True, exist_ok=True)

        with path.open("w", newline="", encoding="utf-8-sig") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            for item in chemical_list:
                writer.writerow(item)
        
        logger.info(f"化学品列表已导出至: {path.resolve()}")

    def sync_chemicals_from_file(self, file_path: str, overwrite: bool = False) -> None:
        """
        功能:
            读取 CSV 文件并通过父类同步化学品到工站
        参数:
            file_path: CSV 文件路径
            overwrite: 是否覆盖更新
        返回:
            None
        """
        path = Path(file_path)
        if not path.exists():
            # 生成模板
            header = ["name", "cas", "element", "state", "concentration_str", "chemical_properties", "preparation_method"]
            with path.open("w", newline="", encoding="utf-8-sig") as f:
                csv.writer(f).writerow(header)
            logger.warning(f"文件不存在，已生成模板: {path}")
            return

        # 读取并清洗数据
        items: List[JsonDict] = []
        with path.open("r", newline="", encoding="utf-8-sig") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                name = (row.get("name") or "").strip()
                state = (row.get("state") or "").strip()
                if name and state:
                    # 过滤空值键
                    clean_item = {k: v.strip() for k, v in row.items() if v and str(v).strip()}
                    items.append(clean_item)
        
        # 调用父类逻辑处理
        self.sync_chemicals_from_data(items, overwrite=overwrite)

    def check_chemical_library_by_file(self, file_path: str) -> Dict[str, List[str]]:
        """
        功能:
            读取化学品库文件并调用底层校验逻辑，输出校验结果
        参数:
            file_path: str, 化学品库文件路径，支持 Excel/CSV
        返回:
            Dict[str, List[str]], 包含 errors 与 warnings
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"未找到化学品库文件: {path}")

        # 读取文件后交给控制层做校验
        df = pd.read_excel(path) if path.suffix.lower() in [".xlsx", ".xls"] else pd.read_csv(path)
        df = df.fillna("")
        rows = df.to_dict(orient="records")
        headers = [str(col).strip() for col in df.columns]

        result = self.check_chemical_library_data(rows, headers)

        for msg in result.get("warnings", []):
            logger.warning(msg)

        if len(result.get("errors", [])) > 0:
            for msg in result["errors"]:
                logger.error(msg)
            raise ValidationError("化学品库完整性检查未通过，请修复错误后重试")

        return result
    
    def deduplicate_chemical_library_by_file(self, file_path: str, output_path: Optional[str] = None) -> List[JsonDict]:
        """
        功能:
            读取化学品库文件，按 substance 自动去重并回写
        参数:
            file_path: str, 输入文件路径，支持 Excel/CSV
            output_path: Optional[str], 输出文件路径，默认覆盖原文件
        返回:
            List[Dict[str, Any]], 去重后的数据
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"未找到化学品库文件: {path}")

        df = pd.read_excel(path) if path.suffix.lower() in [".xlsx", ".xls"] else pd.read_csv(path)
        df = df.fillna("")
        headers = [str(c).strip() for c in df.columns]
        rows = df.to_dict(orient="records")

        dedup_rows = self.deduplicate_chemical_library_data(rows, headers)

        target_path = Path(output_path) if output_path else path
        out_df = pd.DataFrame(dedup_rows)
        if target_path.suffix.lower() == ".csv":
            out_df.to_csv(target_path, index=False, encoding="utf-8-sig")
        else:
            safe_excel_write(out_df, target_path, index=False)
            self._beautify_excel_database(target_path)  # 保存后再美化

        logger.info("化合物库去重完成，输出文件: %s", target_path.resolve())
        return dedup_rows
    
    def _beautify_excel_database(self, file_path: Path) -> None:
        """
        功能:
            美化去重后的 Excel: 表头加粗、全居中、列宽自适应、按内容选择中英文字体
        参数:
            file_path: Path, 目标 Excel 路径
        返回:
            None
        """
        wb = load_workbook(file_path)
        ws = wb.active
        MAX_WIDTH = 60  # 列宽上限

        align_center = Alignment(horizontal="center", vertical="center")

        def _is_chinese(text: str) -> bool:
            return re.search(r"[\u4e00-\u9fff]", text) is not None

        # 遍历列计算列宽并设置字体/对齐
        for col_cells in ws.iter_cols():
            max_len = 0
            for idx, cell in enumerate(col_cells):
                val_str = "" if cell.value is None else str(cell.value)
                max_len = max(max_len, len(val_str))

                # 按内容切换字体，表头加粗
                if idx == 0:
                    cell.font = Font(name="微软雅黑", bold=True)
                else:
                    cell.font = Font(name="微软雅黑")

                cell.alignment = align_center

            # 列宽留一点边距，最小 10，最大 40
            col_width = max(10, max_len + 2)
            col_width = min(col_width, MAX_WIDTH)
            ws.column_dimensions[col_cells[0].column_letter].width = col_width

        safe_workbook_save(wb, file_path)

    def align_chemicals_with_file(self, file_path: str, auto_delete: bool = True) -> None:
        """
        功能:
            读取 Excel/CSV 文件，调用父类对齐逻辑，并将结果(fid)写回文件
        参数:
            file_path: 文件路径
            auto_delete: 是否删除不在文件中的工站化学品
        返回:
            None
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"未找到化学品对齐文件: {path}")

        # 读取文件内容为 List[Dict]
        df = pd.read_excel(path) if path.suffix in ['.xlsx', '.xls'] else pd.read_csv(path)
        # 将 NaN 替换为空字符串
        df = df.fillna("")
        rows = df.to_dict(orient='records')
        header = df.columns.tolist()

        # 调用父类进行对齐，父类会修改 rows 中的数据(如回填 chemical_id)
        updated_rows = self.align_chemicals_from_data(rows, auto_delete=auto_delete)

        # 写回文件
        new_df = pd.DataFrame(updated_rows)
        # 保持原有列顺序，如果增加了新列(如 chemical_id 之前没有)，这会包含它
        if path.suffix == '.csv':
            new_df.to_csv(path, index=False, encoding="utf-8-sig")
        else:
            safe_excel_write(new_df, path, index=False)
            self._beautify_excel_database(path)  # 保存后再美化
        
        logger.info(f"化学品对齐完成并回写文件: {path}")

    # ---------- 2. 上料动作 ----------
    def batch_in_tray_by_file(self, file_path: str) -> JsonDict:
        """
        功能:
            读取上料表格，转换为中间格式，调用父类生成 Payload 并执行上料
        参数:
            file_path: 文件路径
        返回:
            Dict: API 响应
        """
        path = Path(file_path)
        if not path.exists():
            logger.warning(f"未找到{file_path}.自动生成模板文件")
            self._generate_batch_in_tray_template(path.with_suffix(".xlsx"))
            return {}

        rows: List[Tuple[str, str, str]] = []
        
        # 读取文件
        if path.suffix == '.xlsx':
            wb = openpyxl.load_workbook(path)
            ws = wb.active
            for row in ws.iter_rows(min_row=2, values_only=True):
                # 确保取前三列，且处理 None
                pos = str(row[0]) if row[0] is not None else ""
                t_type = str(row[1]) if len(row) > 1 and row[1] is not None else ""
                content = str(row[2]) if len(row) > 2 and row[2] is not None else ""
                rows.append((pos, t_type, content))
        else:
            df = pd.read_csv(path)
            df = df.fillna("")
            for _, row in df.iterrows():
                rows.append((str(row[0]), str(row[1]), str(row[2])))

        # 调用父类生成 Payload
        payload = self.build_batch_in_tray_payload(rows)

        if not payload:
            logger.warning("生成的上料数据为空")
            return {}

        # 执行上料
        resp = self.batch_in_tray(payload)

        return resp

    def batch_in_tray_with_agv_transfer(
        self,
        file_path: str = None,
        *,
        block: bool = True
    ) -> JsonDict:
        """
        功能:
            根据 batch_in_tray.xlsx 中的信息, 先使用 AGV 批量转移物料到合成工站,
            然后让 AGV 前往充电站, 最后执行上料操作
        参数:
            file_path: 上料文件路径, 默认为 sheet/batch_in_tray.xlsx
            block: 是否阻塞等待 AGV 转运完成
        返回:
            Dict, 包含转运、充电和上料的结果:
                - transfer_result: Dict, AGV 转运结果
                - charging_result: Dict, AGV 充电结果
                - in_tray_result: Dict, 上料结果
        """
        # 设置默认文件路径
        if file_path is None:
            file_path = str(MODULE_ROOT / "sheet" / "batch_in_tray.xlsx")

        # 1. 使用 AGV 批量转移物料到合成工站
        logger.info("开始使用 AGV 批量转移物料到合成工站")
        transfer_result = self.auto_load_trays_from_agv(
            batch_in_file=file_path,
            block=block
        )

        # 检查转运是否成功
        if not transfer_result.get("success"):
            logger.error("AGV 转运失败, 停止后续操作")
            return {
                "transfer_result": transfer_result,
                "charging_result": None,
                "in_tray_result": None,
                "success": False,
                "message": "AGV 转运失败"
            }

        logger.info(f"AGV 转运成功, 共转运 {transfer_result.get('transferred_trays')} 个托盘")

        # 2. 让 AGV 前往充电站
        logger.info("开始让 AGV 前往充电站")
        charging_result = None
        try:
            import sys
            from pathlib import Path
            sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
            from eit_agv.controller.agv_controller import AGVController
            agv_controller = AGVController()

            charging_result = agv_controller.go_to_charging_station()
            if charging_result is not None:
                logger.info("AGV 已成功前往充电站")
            else:
                logger.warning("AGV 前往充电站失败, 但继续执行上料操作")
        except Exception as e:
            logger.error(f"AGV 前往充电站时发生异常: {e}, 但继续执行上料操作")

        # 3. 执行上料操作
        logger.info("开始执行上料操作")
        in_tray_result = None
        try:
            in_tray_result = self.batch_in_tray_by_file(file_path)
            logger.info(f"上料操作完成, 结果: {in_tray_result}")
        except Exception as e:
            logger.error(f"上料操作发生异常: {e}")
            return {
                "transfer_result": transfer_result,
                "charging_result": charging_result,
                "in_tray_result": None,
                "success": False,
                "message": f"上料操作失败: {e}"
            }

        return {
            "transfer_result": transfer_result,
            "charging_result": charging_result,
            "in_tray_result": in_tray_result,
            "success": True,
            "message": "AGV 转运、充电和上料操作全部完成"
        }

    def _generate_batch_in_tray_template(self, file_path: Path) -> None:
        """
        功能:
            生成批量上料Excel模板, 配置上料点位下拉、托盘类型下拉与内容示例
        参数:
            file_path: Path, 模板输出路径
        返回:
            None
        """
        wb = Workbook()
        ws = wb.active
        ws.title = "batch_in_tray"
        ws.append(["position", "tray_type", "content", "shelf_position", "storage"])
        ws.column_dimensions["B"].width = 60
        ws.column_dimensions["C"].width = 80
        ws.column_dimensions["D"].width = 15
        ws.column_dimensions["E"].width = 50

        # 位置下拉，包含 TB 列与 W-1-1~W-1-8 货位
        positions_tb = [f"TB-{row}-{col}" for row in (1, 2) for col in range(1, 5)]
        positions_w = [f"W-1-{index}" for index in range(1, 9)]
        positions = positions_tb + positions_w
        dv_pos = DataValidation(type="list", formula1=f"\"{','.join(positions)}\"")
        ws.add_data_validation(dv_pos)
        dv_pos.add("A2:A101")

        # 托盘下拉，耗材显示数量范围，带物质显示点位范围
        consumable_trays = {
            int(ResourceCode.TIP_TRAY_50UL),
            int(ResourceCode.TIP_TRAY_1ML),
            int(ResourceCode.TIP_TRAY_5ML),
            int(ResourceCode.REACTION_SEAL_CAP_TRAY),
            int(ResourceCode.FLASH_FILTER_INNER_BOTTLE_TRAY),
            int(ResourceCode.FLASH_FILTER_OUTER_BOTTLE_TRAY),
            int(ResourceCode.REACTION_TUBE_TRAY_2ML),
            int(ResourceCode.TEST_TUBE_MAGNET_TRAY_2ML),
        }
        tray_display: List[str] = []
        for code, name in TRAY_CODE_DISPLAY_NAME.items():
            base_text = f"{name}({code})"
            try:
                enum_name = ResourceCode(code).name
                spec = getattr(TraySpec, enum_name, None)
            except Exception:
                spec = None

            if spec is None:
                tray_display.append(base_text)
                continue

            col_count, row_count = spec
            if col_count <= 0 or row_count <= 0:
                tray_display.append(base_text)
                continue

            if code in consumable_trays:
                capacity = col_count * row_count
                tray_display.append(f"{base_text} [1-{capacity}]")
            else:
                end_row_char = chr(ord("A") + row_count - 1)
                tray_display.append(f"{base_text} [A1-{end_row_char}{col_count}]")

        # 用隐藏sheet作为数据源，避免下拉字符串过长
        tray_sheet = wb.create_sheet("validation_meta")
        for idx, option in enumerate(tray_display, start=1):
            tray_sheet.cell(row=idx, column=1).value = option
        tray_sheet.sheet_state = "hidden"

        # 定义命名区域, 避免跨 sheet 验证被 Excel 写成 x14 扩展
        options_name = "tray_type_options"
        options_ref  = f"validation_meta!$A$1:$A${len(tray_display)}"
        wb.defined_names.add(DefinedName(options_name, attr_text=options_ref))

        dv_tray = DataValidation(
            type="list",
            formula1=f"={options_name}",
            showInputMessage=True,
        )
        ws.add_data_validation(dv_tray)
        dv_tray.add("B2:B101")

        ws["C1"] = "content(耗材填数量; 物质填: A1|名称|2mL; B2|名称|5mg)"
        ws["D1"] = "shelf_position"
        ws["E1"] = "storage(格式: 物质|位置; 多个用;隔开)"
        safe_workbook_save(wb, file_path)
        logger.info(f"已生成上料模板: {file_path}")

    # ---------- 3. 任务生成文件处理 ----------
    def create_task_by_file(self, template_path: str, chemical_db_path: str) -> JsonDict:
        """
        功能:
            读取任务模板和化学品库，解析为中间数据，调用父类生成任务 Payload 并提交
        参数:
            template_path: 实验模板路径
            chemical_db_path: 化学品库路径
        返回:
            Dict: 任务创建结果
        """
        t_path = Path(template_path)
        c_path = Path(chemical_db_path)

        # 1. 检查并生成模板
        if not t_path.exists():
            self._generate_reaction_template(t_path)
            raise FileNotFoundError(f"已生成模板 {t_path}，请填写后重试")

        if not c_path.exists():
            raise FileNotFoundError(f"未找到化学品库文件: {c_path}")

        # 2. 读取化学品库 -> Dict
        chem_df = pd.read_excel(c_path) if c_path.suffix.lower() in [".xlsx", ".xls"] else pd.read_csv(c_path)
        chem_df.columns = [str(c).strip().lower() for c in chem_df.columns]

        def _pick(row, *keys, default=None):
            for k in keys:
                if k in row and pd.notna(row[k]):
                    return row[k]
            return default

        chemical_db: Dict[str, Dict[str, Any]] = {}
        for _, r in chem_df.iterrows():
            row = {k: r.get(k) for k in chem_df.columns}
            name = str(_pick(row, "substance", "name", "chemical_name", default="") or "").strip()
            if not name:
                continue

            # 小写后的列名
            chemical_db[name] = {
                "chemical_id": _pick(row, "chemical_id"),
                "molecular_weight": _pick(row, "molecular_weight", "mw"),
                "physical_state": str(_pick(row, "physical_state", "state", default="") or "").strip().lower(),
                "density (g/mL)": _pick(row, "density (g/ml)", "density(g/ml)", "density_g_ml", "density", default=None),
                "physical_form": str(_pick(row, "physical_form", default="") or "").strip().lower(),
                "active_content": _pick(row, "active_content","active_content(mmol/ml or wt%)" ,"active_content(mol/l or wt%)", default="" ),
            }

        # 3. 读取任务模板 -> params(Dict), headers(List), data_rows(List[List])
        wb = load_workbook(t_path, data_only=True)
        ws = wb.active

        # 3.1 找到表头行/实验编号列（模板里一般是：row=1, col=3）
        header_row = None
        exp_no_col = None
        for r in range(1, min(ws.max_row, 50) + 1):
            for c in range(1, min(ws.max_column, 50) + 1):
                v = ws.cell(r, c).value
                if isinstance(v, str) and "实验编号" in v:
                    header_row, exp_no_col = r, c
                    break
            if header_row is not None:
                break
        if header_row is None or exp_no_col is None:
            raise ValueError("模板中未找到'实验编号'表头")

        # 3.2 提取全局参数（左侧 A/B）
        # - 实验名称：A1是标签，用户通常填在 B1
        params: Dict[str, Any] = {}
        exp_name = ws.cell(1, 2).value  # B1
        if exp_name is not None and str(exp_name).strip() != "":
            params["实验名称"] = str(exp_name).strip()

        # 扫描 A/B（从第2行开始，遇到“注：”不停止也可以；这里仅跳过“注：”本行）
        for r in range(2, ws.max_row + 1):
            key = ws.cell(r, 1).value
            val = ws.cell(r, 2).value

            if key is None:
                continue
            key_str = str(key).strip()
            if not key_str:
                continue

            # 跳过注释行（不写入 params；否则会污染）
            if key_str.startswith("注：") or key_str.startswith("注:"):
                continue

            # 分类标题行通常是合并单元格，B 为空；这类不要写入 params
            if val is None or (isinstance(val, str) and val.strip() == ""):
                continue

            params[key_str] = val

        # 3.3 生成 headers（从 “实验编号”列开始往右：C..M）
        # 同时把 “试剂_1” -> “试剂名称_1”，让 build_task_payload 能识别
        raw_headers: List[Any] = []
        for c in range(exp_no_col, ws.max_column + 1):
            raw_headers.append(ws.cell(header_row, c).value)

        headers: List[str] = []
        reagent_idx = 0
        for h in raw_headers:
            s = "" if h is None else str(h).strip()

            # 规范化：试剂_1/试剂1 -> 试剂名称_1
            if s.startswith("试剂") and "量" not in s and s != "试剂名称":
                reagent_idx += 1
                headers.append(f"试剂名称_{reagent_idx}")
                continue

            # 规范化：试剂量 -> 试剂量_1/2/...
            if "试剂量" in s:
                # 若前面还没遇到试剂列，给个兜底编号
                idx = reagent_idx if reagent_idx > 0 else (len([x for x in headers if "试剂量" in x]) + 1)
                headers.append(f"试剂量_{idx}")
                continue

            headers.append(s)

        # 3.4 生成 data_rows：从表头下一行开始，按实验编号列读取到最后一列（C..M）
        data_rows: List[List[Any]] = []
        for r in range(header_row + 1, ws.max_row + 1):
            exp_no = ws.cell(r, exp_no_col).value

            # 实验编号为空：认为实验区结束（模板一般后面都是空）
            if exp_no is None or (isinstance(exp_no, str) and exp_no.strip() == ""):
                # 只有在已经读到至少一行实验后才 break，避免中间空行误判
                if data_rows:
                    break
                else:
                    continue

            row_vals: List[Any] = []
            for c in range(exp_no_col, ws.max_column + 1):
                v = ws.cell(r, c).value
                # 这里不要强制 str 化，build_task_payload 内部会 str()；但 None 要变成 ""
                row_vals.append("" if v is None else v)

            data_rows.append(row_vals)

        # 4. 调用父类纯逻辑生成 Payload
        task_payload = self.build_task_payload(params, headers, data_rows, chemical_db)

        # 5. 提交任务信息到工站
        try:
            resp = self.add_task(task_payload)
        except ApiError as exc:
            if getattr(exc, "code", None) == 409:
                # 自动重命名: 在任务名称后添加当前日期时间(精确到秒)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

                task_name = task_payload.get("task_name") or params.get("实验名称")
                new_task_name = f"{task_name}_{timestamp}"

                task_payload["task_name"] = new_task_name
                logger.info(f"任务名称重复, 自动重命名为: {new_task_name}")

                # 重试提交
                try:
                    resp = self.add_task(task_payload)
                except ApiError as retry_exc:
                    logger.error(f"重命名后任务提交仍失败: {retry_exc}")
                    raise
            else:
                raise

        # 6. 提交任务信息到工站
        task_id = resp.get("task_id")

        # 7. 回写任务ID和任务名称到模板
        try:
            task_id_int = int(task_id)
            id_updated = False
            name_updated = False
            # 获取实际提交的任务名称(可能经过重命名)
            final_task_name = task_payload.get("task_name")

            for r in range(1, ws.max_row + 1):
                key_val = ws.cell(r, 1).value
                if key_val is None:
                    continue
                key_str = str(key_val).strip()
                # 回写实验ID
                if key_str == "实验ID":
                    ws.cell(r, 2, value=task_id_int)
                    id_updated = True
                # 回写任务名称(重命名后同步更新模板)
                if key_str == "实验名称" and final_task_name is not None:
                    ws.cell(r, 2, value=final_task_name)
                    name_updated = True

            if id_updated or name_updated:
                safe_workbook_save(wb, t_path)
                if id_updated:
                    logger.info("已将任务ID写入模板文件: %s", t_path)
                if name_updated:
                    logger.info("已将任务名称同步写入模板文件: %s", final_task_name)
            else:
                logger.warning("未找到'实验ID'位置, 未回写任务ID")
        except Exception as exc:
            logger.warning("任务ID回写失败: %s", exc)

        # 8. 将模板文件拷贝到 data/tasks/<task_id>/ 并重命名为任务ID
        try:
            task_dir = MODULE_ROOT / "data" / "tasks" / str(task_id)
            task_dir.mkdir(parents=True, exist_ok=True)          # 创建任务文件夹(若已存在则忽略)
            dest_path = task_dir / f"{task_id}{t_path.suffix}"   # 目标路径: <task_id>.xlsx
            shutil.copy2(t_path, dest_path)                      # 拷贝并保留元数据
            logger.info("已将模板文件拷贝至任务目录: %s", dest_path)
        except Exception as exc:
            logger.warning("模板文件拷贝至任务目录失败: %s", exc)

        return task_id

    def _generate_reaction_template(self, path: Path) -> None:
        """
        生成与 reeaction_template.xlsx 一致的反应模板
        结构：左侧为参数配置区，右侧为实验试剂填报区
        """
        wb = Workbook()
        ws = wb.active
        ws.title = "Sheet1"

        # 模板默认字体：等线 11
        base_font = Font(name="Microsoft YaHei", charset=134, family=2, scheme="minor", sz=11)
        title_font = Font(name="Microsoft YaHei", charset=134, family=2, scheme="minor", sz=11, bold=True)
        center = Alignment(horizontal="center", vertical="center")

        # 覆盖默认 Normal 样式，保证空白单元格也用微软雅黑
        for style in getattr(wb, "_named_styles", []):
            if getattr(style, "name", "").lower() == "normal":
                style.font = base_font
                break

        # --- 1. 定义左侧参数配置数据 (行2开始, A列和B列) ---
        left_params = [
            ("实验设定", ""),
            ("实验名称", "Auto_task"),
            ("实验ID", 0),
            ("反应设定", ""),
            ("反应规模(mmol)", "0.2"),
            ("反应器类型", "heat"),
            ("反应时间(h)", 8),
            ("反应温度(°C)", 40),
            ("转速(rpm)", 500),
            ("搅拌后⽬标温度(°C)", 30),
            ("等待目标温度", "否"),
            ("称量设定", ""),
            ("称量误差(%)", 3),
            ("最大称量误差(mg)", 1),
            ("加料设定", ""),
            ("固定加料顺序", "否"),
            ("自动加磁子", "是"),
            ("内标设定", ""),
            ("内标种类", "1,3,5-三异丙基苯(溶液,1mol/L in MeCN)"),
            ("内标用量(μL/mg)", 100),
            ("加入内标后搅拌时间(min)", 5),
            ("稀释设定", ""),
            ("稀释液种类", "乙腈"),
            ("稀释量(μL)", 500),
            ("闪滤设定", ""),
            ("闪滤液种类", "乙腈"),
            ("闪滤液用量(μL)", 500),
            ("取样量(μL)", 1),
            ("", ""),  # 空行
        ]
        left_param_rows = len(left_params)

        # --- 2. 设置第一行表头 (Row 1) ---
        ws.cell(row=1, column=3, value="实验编号").font = base_font
        
        reagent_count = 5
        current_col = 4
        for i in range(1, reagent_count + 1):
            ws.cell(row=1, column=current_col, value=f"试剂").font = base_font
            ws.cell(row=1, column=current_col + 1, value="试剂量").font = base_font
            current_col += 2

        # --- 3. 填充左侧参数区 (Row 2 ~ Row 22) ---
        for idx, (param_name, default_val) in enumerate(left_params):
            row_idx = idx + 1  # 从第2行开始

            # 分类标题：模板是 A:B 合并，只写 A 列，且加粗
            if param_name and default_val == "":
                ws.cell(row=row_idx, column=1, value=param_name).font = title_font
                ws.merge_cells(start_row=row_idx, start_column=1, end_row=row_idx, end_column=2)
                continue

            # 空行：保持空
            if param_name == "" and default_val == "":
                continue

            # 普通参数行
            ws.cell(row=row_idx, column=1, value=param_name).font = base_font
            ws.cell(row=row_idx, column=2, value=default_val).font = base_font

        # --- 4. 填充右侧实验编号 (Row 2 ~ Row 25) ---
        for i in range(1, 25):  # 1~24
            row_idx = i + 1
            ws.cell(row=row_idx, column=3, value=i).font = base_font

        # --- 5. 底部注释 (跟随参数行, 预留一行空白) ---
        note_row = left_param_rows + 2
        note_text = "注：试剂量支持单位：(eq,mmol,g,mg,μL,mL）"
        ws.cell(row=note_row, column=1, value=note_text).font = base_font
        ws.merge_cells(start_row=note_row, start_column=1, end_row=note_row, end_column=2)
        ws.cell(row=note_row, column=1).alignment = center  # 合并后的单元格居中

        max_template_row = max(note_row, 25)

        # --- 6. 字体铺满 (A1:M*)  ---
        for r in range(1, max_template_row + 1):
            for c in range(1, 14):  # A..M
                cell = ws.cell(r, c)
                # 标题行的粗体不要覆盖
                if cell.font and cell.font.bold:
                    continue
                cell.font = base_font

        # --- 7. 对齐 ---
        # C~L 整块都居中（含空白）
        for r in range(1, max_template_row + 1):
            for c in range(3, 13):  # C..L
                ws.cell(r, c).alignment = center

        # A 列：参数行和注释行居中
        a_rows = []
        b_rows = []
        for idx, (param_name, default_val) in enumerate(left_params):
            row_idx = idx + 1
            if param_name != "":
                a_rows.append(row_idx)
            if param_name != "" and default_val != "":
                b_rows.append(row_idx)
        for r in a_rows + [note_row]:
            ws.cell(r, 1).alignment = center

        # B 列：只有有值的参数行居中（标题行/空白行/合并后的 B 不处理）
        for r in b_rows:
            ws.cell(r, 2).alignment = center

        # M 列：只有表头 M1 居中
        ws.cell(1, 13).alignment = center

        # 表头 A1/C1 也居中（模板如此）
        ws.cell(1, 1).alignment = center
        ws.cell(1, 3).alignment = center

        # --- 8. 列宽： ---
        widths_map = {
            "A": 26.0,
            "B": 38.0,
            "C": 15.0,
            "D": 14.0,
            "E": 14.0,
            "F": 14.0,
            "G": 14.0,
            "H": 14.0,
            "I": 14.0,
            "J": 14.0,
            "K": 14.0,
            "L": 14.0,
            "M": 14.0,
        }
        for col_letter, w in widths_map.items():
            ws.column_dimensions[col_letter].width = w

        safe_workbook_save(wb, path)
        logger.info(f"已生成任务模板: {path}")

    # ---------- 4. 物料核算 ----------
    def check_resource_for_task(self, template_path: str, chemical_db_path: str, auto_generate_batch_file: bool = True) -> JsonDict:
        """
        功能:
            读取实验模板与化学品库, 构建任务 Payload, 获取站内资源并比对是否满足实验需求。
        参数:
            template_path: 实验模板文件路径(xlsx/csv)。
            chemical_db_path: 化学品库文件路径(xlsx/csv)。
            auto_generate_batch_file: 是否自动生成上料文件, 默认为 True。
        返回:
            Dict, analyze_resource_readiness 的结果, 包含需求、库存、缺失与冗余信息。
        """
        t_path = Path(template_path)
        c_path = Path(chemical_db_path)

        if not t_path.exists():
            raise FileNotFoundError(f"未找到实验模板文件: {t_path}")
        if not c_path.exists():
            raise FileNotFoundError(f"未找到化学品库文件: {c_path}")

        chem_df = pd.read_excel(c_path) if c_path.suffix.lower() in [".xlsx", ".xls"] else pd.read_csv(c_path)
        chem_df.columns = [str(c).strip().lower() for c in chem_df.columns]

        def _pick(row, *keys, default=None):
            for k in keys:
                if k in row and pd.notna(row[k]):
                    return row[k]
            return default

        chemical_db: Dict[str, Dict[str, Any]] = {}
        for _, r in chem_df.iterrows():
            row = {k: r.get(k) for k in chem_df.columns}
            name = str(_pick(row, "substance", "name", "chemical_name", default="") or "").strip()
            if not name:
                continue
            chemical_db[name] = {
                "chemical_id": _pick(row, "chemical_id"),
                "molecular_weight": _pick(row, "molecular_weight", "mw"),
                "physical_state": str(_pick(row, "physical_state", "state", default="") or "").strip().lower(),
                "density (g/mL)": _pick(row, "density (g/ml)", "density(g/ml)", "density_g_ml", "density", default=None),
                "physical_form": str(_pick(row, "physical_form", default="") or "").strip().lower(),
                "active_content": _pick(row, "active_content", "active_content(mmol/ml or wt%)", "active_content(mol/l or wt%)", default=""),
            }

        wb = load_workbook(t_path, data_only=True)
        ws = wb.active

        header_row = None
        exp_no_col = None
        for r in range(1, min(ws.max_row, 50) + 1):
            for c in range(1, min(ws.max_column, 50) + 1):
                v = ws.cell(r, c).value
                if isinstance(v, str) and "实验编号" in v:
                    header_row, exp_no_col = r, c
                    break
            if header_row is not None:
                break
        if header_row is None or exp_no_col is None:
            raise ValidationError("模板中未找到'实验编号'表头")

        params: Dict[str, Any] = {}
        exp_name = ws.cell(1, 2).value
        if exp_name is not None and str(exp_name).strip() != "":
            params["实验名称"] = str(exp_name).strip()

        task_id = None  # 用于存储实验ID
        for r in range(2, ws.max_row + 1):
            key = ws.cell(r, 1).value
            val = ws.cell(r, 2).value
            if key is None:
                continue
            key_str = str(key).strip()
            if key_str == "":
                continue
            if key_str.startswith("注：") or key_str.startswith("注"):
                continue
            if val is None or (isinstance(val, str) and val.strip() == ""):
                continue
            
            # 识别实验ID参数并提取整数值
            if key_str == "实验ID":
                try:
                    task_id = int(val)
                    self._logger.info("从模板中读取到实验ID: %d", task_id)
                except (ValueError, TypeError):
                    self._logger.warning("实验ID格式无效: %s, 将跳过二次校验", val)
            
            params[key_str] = val

        raw_headers: List[Any] = []
        for c in range(exp_no_col, ws.max_column + 1):
            raw_headers.append(ws.cell(header_row, c).value)

        headers: List[str] = []
        reagent_idx = 0
        for h in raw_headers:
            s = "" if h is None else str(h).strip()
            if s.startswith("试剂") and "量" not in s and s != "试剂名称":
                reagent_idx += 1
                headers.append(f"试剂名称_{reagent_idx}")
                continue
            if "试剂量" in s:
                idx = reagent_idx if reagent_idx > 0 else (len([x for x in headers if "试剂量" in x]) + 1)
                headers.append(f"试剂量_{idx}")
                continue
            headers.append(s)

        data_rows: List[List[Any]] = []
        for r in range(header_row + 1, ws.max_row + 1):
            exp_no = ws.cell(r, exp_no_col).value
            if exp_no is None or (isinstance(exp_no, str) and exp_no.strip() == ""):
                if data_rows:
                    break
                else:
                    continue
            row_vals: List[Any] = []
            for c in range(exp_no_col, ws.max_column + 1):
                v = ws.cell(r, c).value
                row_vals.append("" if v is None else v)
            data_rows.append(row_vals)

        task_payload = self.build_task_payload(params, headers, data_rows, chemical_db)
        resource_rows = self.get_resource_info()
        result = self.analyze_resource_readiness(task_payload, resource_rows, chemical_db, task_id=task_id)

        # 自动保存物料核算结果
        if self._data_manager and task_id:
            self._data_manager.save_resource_check(str(task_id), result)

        # 自动生成上料文件
        if auto_generate_batch_file and task_id:
            self.auto_generate_batch_in_tray_from_resource_check(task_id)

        return result

    def auto_generate_batch_in_tray_from_resource_check(self, task_id: Optional[int] = None) -> None:
        """
        功能:
            根据资源核查结果自动修改上料文件, 考虑料盘规格, 优先填满一个料盘再使用下一个
        参数:
            task_id: 任务ID, 如果为None则自动搜索data/tasks中id最大且状态为UNSTARTED的任务
        返回:
            None
        """
        import json
        import math

        # 1. 确定任务ID
        if task_id is None:
            tasks_dir = MODULE_ROOT / "data/tasks"
            if not tasks_dir.exists():
                raise FileNotFoundError(f"任务目录不存在: {tasks_dir}")

            # 获取所有任务文件夹, 按ID降序排列
            task_folders = []
            for folder in tasks_dir.iterdir():
                if folder.is_dir() and folder.name.isdigit():
                    task_folders.append(int(folder.name))

            if not task_folders:
                raise FileNotFoundError("未找到任何任务文件夹")

            task_folders.sort(reverse=True)

            # 查找第一个状态为UNSTARTED的任务
            found_task = None
            for tid in task_folders:
                task_info_path = tasks_dir / str(tid) / "task_info.json"
                if task_info_path.exists():
                    with open(task_info_path, "r", encoding="utf-8") as f:
                        task_info = json.load(f)
                    if task_info.get("status") == "UNSTARTED":
                        found_task = tid
                        break

            if found_task is None:
                raise ValueError("未找到状态为UNSTARTED的任务")

            task_id = found_task
            logger.info(f"自动选择任务ID: {task_id}")

        # 2. 读取resource_check.json
        resource_check_path = MODULE_ROOT / "data" / "tasks" / str(task_id) / "resource_check.json"
        if not resource_check_path.exists():
            raise FileNotFoundError(f"未找到资源核查文件: {resource_check_path}")

        with open(resource_check_path, "r", encoding="utf-8") as f:
            resource_check = json.load(f)

        missing_list = resource_check.get("missing", [])
        if not missing_list:
            logger.info("没有缺失的物资, 无需生成上料文件")
            return

        # 3. 读取chemical_list.xlsx
        chemical_list_path = MODULE_ROOT / "sheet" / "chemical_list.xlsx"
        if not chemical_list_path.exists():
            raise FileNotFoundError(f"未找到化学品列表文件: {chemical_list_path}")

        chem_df = pd.read_excel(chemical_list_path)
        chem_df = chem_df.fillna("")

        # 创建物质名到信息的映射
        chemical_dict = {}
        for _, row in chem_df.iterrows():
            substance = str(row.get("substance", "")).strip()
            if substance:
                chemical_dict[substance] = {
                    "physical_state": str(row.get("physical_state", "")).strip().lower(),
                    "storage_location": str(row.get("storage_location", "")).strip()
                }

        # 4. 准备料盘规格信息和位置管理
        position_list = ["TB-2-1", "TB-2-2", "TB-2-3", "TB-2-4",
                        "TB-1-1", "TB-1-2", "TB-1-3", "TB-1-4"]
        shelf_position_list = ["3-1", "3-2", "3-3", "3-4",
                              "2-1", "2-2", "2-3", "2-4"]

        # 料盘类型到规格的映射
        tray_spec_map = {
            int(ResourceCode.REAGENT_BOTTLE_TRAY_2ML): TraySpec.REAGENT_BOTTLE_TRAY_2ML,
            int(ResourceCode.REAGENT_BOTTLE_TRAY_8ML): TraySpec.REAGENT_BOTTLE_TRAY_8ML,
            int(ResourceCode.REAGENT_BOTTLE_TRAY_40ML): TraySpec.REAGENT_BOTTLE_TRAY_40ML,
            int(ResourceCode.POWDER_BUCKET_TRAY_30ML): TraySpec.POWDER_BUCKET_TRAY_30ML,
            int(ResourceCode.REACTION_TUBE_TRAY_2ML): TraySpec.REACTION_TUBE_TRAY_2ML,
            int(ResourceCode.TEST_TUBE_MAGNET_TRAY_2ML): TraySpec.TEST_TUBE_MAGNET_TRAY_2ML,
            int(ResourceCode.REACTION_SEAL_CAP_TRAY): TraySpec.REACTION_SEAL_CAP_TRAY,
            int(ResourceCode.FLASH_FILTER_INNER_BOTTLE_TRAY): TraySpec.FLASH_FILTER_INNER_BOTTLE_TRAY,
            int(ResourceCode.FLASH_FILTER_OUTER_BOTTLE_TRAY): TraySpec.FLASH_FILTER_OUTER_BOTTLE_TRAY,
            int(ResourceCode.TIP_TRAY_50UL): TraySpec.TIP_TRAY_50UL,
            int(ResourceCode.TIP_TRAY_1ML): TraySpec.TIP_TRAY_1ML,
            int(ResourceCode.TIP_TRAY_5ML): TraySpec.TIP_TRAY_5ML,
        }

        # 跟踪每种料盘类型的使用情况: {tray_type_code: [(position, shelf_position, current_slot_index, max_slots)]}
        tray_usage = {}

        def _get_slot_name(slot_index: int, cols: int, rows: int) -> str:
            """
            功能:
                根据坑位索引生成坑位名称, 按行优先排列
            参数:
                slot_index: 坑位索引(从0开始)
                cols: 列数
                rows: 行数
            返回:
                坑位名称, 如 "A1", "A2", "B1" 等
            """
            row_idx = slot_index // cols
            col_idx = slot_index % cols
            row_letter = chr(ord('A') + row_idx)
            return f"{row_letter}{col_idx + 1}"

        def _allocate_slot(tray_type_code: int, tray_type_name: str) -> Tuple[str, str, str]:
            """
            功能:
                为指定料盘类型分配一个坑位
            参数:
                tray_type_code: 料盘类型代码
                tray_type_name: 料盘类型名称
            返回:
                (position, shelf_position, slot_name) 元组
            """
            # 获取料盘规格
            spec = tray_spec_map.get(tray_type_code)
            if spec is None:
                raise ValueError(f"未找到料盘规格: {tray_type_code}")

            cols, rows = spec
            max_slots = cols * rows

            # 检查是否已有该类型的料盘在使用
            if tray_type_code not in tray_usage:
                tray_usage[tray_type_code] = []

            # 查找是否有未满的料盘
            for tray_info in tray_usage[tray_type_code]:
                position, shelf_position, current_slot, max_slots_in_tray = tray_info
                if current_slot < max_slots_in_tray:
                    # 找到未满的料盘, 分配下一个坑位
                    slot_name = _get_slot_name(current_slot, cols, rows)
                    tray_info[2] += 1  # 更新当前坑位索引
                    logger.info(f"使用现有料盘 {position}, 坑位 {slot_name}")
                    return position, shelf_position, slot_name

            # 没有未满的料盘, 需要分配新位置
            if len(tray_usage[tray_type_code]) >= len(position_list):
                raise ValueError(f"可用位置已用完, 无法分配新料盘")

            # 找到下一个可用位置
            used_positions = set()
            for trays in tray_usage.values():
                for tray_info in trays:
                    used_positions.add(tray_info[0])

            new_position = None
            new_shelf_position = None
            for i, pos in enumerate(position_list):
                if pos not in used_positions:
                    new_position = pos
                    new_shelf_position = shelf_position_list[i]
                    break

            if new_position is None:
                raise ValueError(f"可用位置已用完, 无法分配新料盘")

            # 创建新料盘记录
            slot_name = _get_slot_name(0, cols, rows)
            tray_usage[tray_type_code].append([new_position, new_shelf_position, 1, max_slots])
            logger.info(f"分配新料盘 {new_position}, 类型 {tray_type_name}")
            return new_position, new_shelf_position, slot_name

        # 5. 解析missing列表并生成上料数据
        # 使用字典来按位置分组物资: {position: {"tray_type": ..., "contents": [...], "shelf_position": ..., "storages": [...]}}
        position_groups = {}

        # 分类存储: 先处理固体、液体、耗材，按顺序生成
        solid_items = []
        liquid_items = []
        consumable_items = []

        # 第一遍: 分类
        for missing_item in missing_list:
            # 解析格式: "物质名:数量单位"
            if ":" not in missing_item:
                logger.warning(f"跳过格式错误的缺失项: {missing_item}")
                continue

            substance, amount_str = missing_item.split(":", 1)
            substance = substance.strip()
            amount_str = amount_str.strip()

            # 检查是否为耗材(以"件"结尾)
            is_consumable = amount_str.endswith("件")

            if is_consumable:
                consumable_items.append((substance, amount_str))
            else:
                # 获取物质信息判断固液
                chem_info = chemical_dict.get(substance)
                if not chem_info:
                    logger.warning(f"在化学品列表中未找到物质: {substance}, 跳过")
                    continue

                physical_state = chem_info["physical_state"]
                if physical_state == "solid":
                    solid_items.append((substance, amount_str, chem_info))
                elif physical_state == "liquid":
                    liquid_items.append((substance, amount_str, chem_info))
                else:
                    logger.warning(f"物质状态未知: {physical_state}, 跳过物质 {substance}")

        # 第二遍: 按顺序处理 - 固体
        for substance, amount_str, chem_info in solid_items:
            physical_state = chem_info["physical_state"]
            storage_location = chem_info["storage_location"]

            # 解析数量和单位
            amount_value = 0.0
            unit = ""

            # 提取数字和单位
            import re
            match = re.match(r"([\d.]+)\s*(\w+)", amount_str)
            if match:
                amount_value = float(match.group(1))
                unit = match.group(2).lower()
            else:
                logger.warning(f"无法解析数量: {amount_str}, 跳过")
                continue

            # 固体: 使用粉桶托盘
            tray_type_code = int(ResourceCode.POWDER_BUCKET_TRAY_30ML)
            tray_type_name = f"30 mL粉桶托盘({tray_type_code})"

            # 单位转换为mg
            if unit == "mg":
                final_amount = amount_value
            elif unit == "g":
                final_amount = amount_value * 1000
            else:
                logger.warning(f"固体物质单位不支持: {unit}, 跳过")
                continue

            # 计算上料量: 最小100mg, 大于100mg按实际需要量的两倍取整
            if final_amount <= 100:
                final_amount = 100
            else:
                final_amount = final_amount * 2
                # 向上取整到百位
                final_amount = math.ceil(final_amount / 100) * 100

            final_unit = "mg"

            # 分配坑位
            try:
                position, shelf_position, slot_name = _allocate_slot(tray_type_code, tray_type_name)
            except ValueError as e:
                logger.warning(f"无法分配坑位: {e}, 跳过物资 {substance}")
                break

            # 处理final_amount可能是int或float的情况
            if isinstance(final_amount, int):
                amount_display = final_amount
            elif isinstance(final_amount, float) and final_amount.is_integer():
                amount_display = int(final_amount)
            else:
                amount_display = final_amount

            # 生成单个坑位的内容: "坑位|物质名|数量单位"
            slot_content = f"{slot_name}|{substance}|{amount_display}{final_unit}"

            # 按位置分组
            if position not in position_groups:
                position_groups[position] = {
                    "tray_type": tray_type_name,
                    "contents": [],
                    "shelf_position": shelf_position,
                    "storages": []
                }

            position_groups[position]["contents"].append(slot_content)
            position_groups[position]["storages"].append(f"{substance}|{storage_location if storage_location else '未知'}")
            logger.info(f"添加固体上料项: {substance} -> {position} {slot_name}, {final_amount}{final_unit}")

        # 第三遍: 处理液体
        for substance, amount_str, chem_info in liquid_items:
            physical_state = chem_info["physical_state"]
            storage_location = chem_info["storage_location"]

            # 解析数量和单位
            amount_value = 0.0
            unit = ""

            # 提取数字和单位
            import re
            match = re.match(r"([\d.]+)\s*(\w+)", amount_str)
            if match:
                amount_value = float(match.group(1))
                unit = match.group(2).lower()
            else:
                logger.warning(f"无法解析数量: {amount_str}, 跳过")
                continue

            # 液体: 根据量选择试剂瓶托盘
            # 单位转换为mL
            if unit == "ml" or unit == "mL":
                final_amount = amount_value
            elif unit == "μl" or unit == "ul":
                final_amount = amount_value / 1000
            elif unit == "l":
                final_amount = amount_value * 1000
            else:
                logger.warning(f"液体物质单位不支持: {unit}, 跳过")
                continue

            # 最少1mL, 向上取整
            final_amount = max(1, math.ceil(final_amount))
            final_unit = "mL"

            # 根据量选择瓶子规格
            if final_amount <= 2:
                tray_type_code = int(ResourceCode.REAGENT_BOTTLE_TRAY_2ML)
                tray_type_name = f"2 mL试剂瓶托盘({tray_type_code})"
            elif final_amount <= 8:
                tray_type_code = int(ResourceCode.REAGENT_BOTTLE_TRAY_8ML)
                tray_type_name = f"8 mL试剂瓶托盘({tray_type_code})"
            elif final_amount <= 40:
                tray_type_code = int(ResourceCode.REAGENT_BOTTLE_TRAY_40ML)
                tray_type_name = f"40 mL试剂瓶托盘({tray_type_code})"
            else:
                logger.warning(f"液体量超过40mL, 不支持: {final_amount}mL, 跳过")
                continue

            # 分配坑位
            try:
                position, shelf_position, slot_name = _allocate_slot(tray_type_code, tray_type_name)
            except ValueError as e:
                logger.warning(f"无法分配坑位: {e}, 跳过物资 {substance}")
                break

            # 处理final_amount可能是int或float的情况
            if isinstance(final_amount, int):
                amount_display = final_amount
            elif isinstance(final_amount, float) and final_amount.is_integer():
                amount_display = int(final_amount)
            else:
                amount_display = final_amount

            # 生成单个坑位的内容: "坑位|物质名|数量单位"
            slot_content = f"{slot_name}|{substance}|{amount_display}{final_unit}"

            # 按位置分组
            if position not in position_groups:
                position_groups[position] = {
                    "tray_type": tray_type_name,
                    "contents": [],
                    "shelf_position": shelf_position,
                    "storages": []
                }

            position_groups[position]["contents"].append(slot_content)
            position_groups[position]["storages"].append(f"{substance}|{storage_location if storage_location else '未知'}")
            logger.info(f"添加液体上料项: {substance} -> {position} {slot_name}, {final_amount}{final_unit}")

        # 第四遍: 处理耗材
        for substance, amount_str in consumable_items:
            # 耗材处理: 解析数量
            import re
            match = re.match(r"([\d.]+)\s*件", amount_str)
            if not match:
                logger.warning(f"无法解析耗材数量: {amount_str}, 跳过")
                continue

            consumable_count = int(float(match.group(1)))

            # 根据耗材名称确定托盘类型
            tray_type_code = None
            tray_type_name = ""

            if ("反应试管" in substance or "反应管" in substance or "2mL反应试管" in substance or "2mL反应管" in substance or "2 mL反应试管" in substance or "2 mL反应管" in substance) and "磁子" not in substance:
                tray_type_code = int(ResourceCode.REACTION_TUBE_TRAY_2ML)
                tray_type_name = f"2 mL反应试管托盘({tray_type_code})"
            elif "试管磁子" in substance or "反应管磁子" in substance or "2mL试管磁子" in substance or "2mL反应管磁子" in substance or "2 mL试管磁子" in substance or "2 mL反应管磁子" in substance:
                tray_type_code = int(ResourceCode.TEST_TUBE_MAGNET_TRAY_2ML)
                tray_type_name = f"2 mL试管磁子托盘({tray_type_code})"
            elif "密封盖" in substance or "反应密封盖" in substance or "反应盖板" in substance:
                tray_type_code = int(ResourceCode.REACTION_SEAL_CAP_TRAY)
                tray_type_name = f"反应密封盖托盘({tray_type_code})"
            elif "闪滤瓶内瓶" in substance or "内瓶" in substance:
                tray_type_code = int(ResourceCode.FLASH_FILTER_INNER_BOTTLE_TRAY)
                tray_type_name = f"闪滤瓶内瓶托盘({tray_type_code})"
            elif "闪滤瓶外瓶" in substance or "外瓶" in substance:
                tray_type_code = int(ResourceCode.FLASH_FILTER_OUTER_BOTTLE_TRAY)
                tray_type_name = f"闪滤瓶外瓶托盘({tray_type_code})"
            elif "50" in substance and ("tip" in substance.lower() or "吸头" in substance):
                tray_type_code = int(ResourceCode.TIP_TRAY_50UL)
                tray_type_name = f"50 μL Tip 头托盘({tray_type_code})"
            elif "1ml" in substance.lower() or "1 ml" in substance.lower():
                tray_type_code = int(ResourceCode.TIP_TRAY_1ML)
                tray_type_name = f"1 mL Tip 头托盘({tray_type_code})"
            elif "5ml" in substance.lower() or "5 ml" in substance.lower():
                tray_type_code = int(ResourceCode.TIP_TRAY_5ML)
                tray_type_name = f"5 mL Tip 头托盘({tray_type_code})"
            else:
                logger.warning(f"无法识别耗材类型: {substance}, 跳过")
                continue

            # 获取托盘规格，计算满盘数量
            spec = tray_spec_map.get(tray_type_code)
            if spec is None:
                logger.warning(f"未找到托盘规格: {tray_type_code}, 跳过")
                continue

            cols, rows = spec
            full_tray_capacity = cols * rows

            # 分配位置
            try:
                position, shelf_position, slot_name = _allocate_slot(tray_type_code, tray_type_name)
            except ValueError as e:
                logger.warning(f"无法分配坑位: {e}, 跳过耗材 {substance}")
                break

            # 耗材的content格式: 满盘数量
            slot_content = str(full_tray_capacity)

            # 按位置分组
            if position not in position_groups:
                position_groups[position] = {
                    "tray_type": tray_type_name,
                    "contents": [],
                    "shelf_position": shelf_position,
                    "storages": []
                }

            position_groups[position]["contents"].append(slot_content)
            position_groups[position]["storages"].append(f"{substance}|耗材库")
            logger.info(f"添加耗材上料项: {substance} -> {position}, 满盘数量 {full_tray_capacity} (需求 {consumable_count})")

        # 6. 合并同一位置的内容并生成最终数据
        batch_in_data = []
        for position in sorted(position_groups.keys()):
            group = position_groups[position]
            # 用分号连接同一料盘的所有坑位
            combined_content = ";".join(group["contents"])
            combined_storage = ";".join(group["storages"])
            batch_in_data.append({
                "position": position,
                "tray_type": group["tray_type"],
                "content": combined_content,
                "shelf_position": group["shelf_position"],
                "storage": combined_storage
            })

        # 7. 写入batch_in_tray.xlsx
        if not batch_in_data:
            logger.warning("没有生成任何上料数据")
            return

        batch_in_path = MODULE_ROOT / "sheet" / "batch_in_tray.xlsx"

        # 检查模板是否存在，不存在则生成
        if not batch_in_path.exists():
            logger.info(f"未找到上料模板，正在生成: {batch_in_path}")
            self._generate_batch_in_tray_template(batch_in_path)

        # 读取现有模板
        wb = load_workbook(batch_in_path)
        ws = wb.active

        # 清除现有数据（保留表头，从第2行开始清除）
        max_row = ws.max_row
        if max_row > 1:
            ws.delete_rows(2, max_row - 1)

        # 写入新数据（从第2行开始）
        for idx, item in enumerate(batch_in_data, start=2):
            ws.cell(row=idx, column=1, value=item["position"])
            ws.cell(row=idx, column=2, value=item["tray_type"])
            ws.cell(row=idx, column=3, value=item["content"])
            ws.cell(row=idx, column=4, value=item["shelf_position"])
            ws.cell(row=idx, column=5, value=item["storage"])

        # 保存文件
        safe_workbook_save(wb, batch_in_path)

        logger.info(f"已生成上料文件: {batch_in_path}, 共{len(batch_in_data)}行, 包含{sum(len(g['contents']) for g in position_groups.values())}个物资")
        logger.info(f"请检查文件并根据需要调整")

    # ---------- 5. 执行任务 ----------
    def device_init(self, device_id=None, *, poll_interval_s: float = 1.0, timeout_s: float = 600.0):
        return super().device_init(device_id, poll_interval_s=poll_interval_s, timeout_s=timeout_s)

    def start_task(self, task_id: int | None = None, *, check_glovebox_env: bool = True, water_limit_ppm: float = 10.0, oxygen_limit_ppm: float = 10.0):
        return super().start_task(task_id, check_glovebox_env=check_glovebox_env, water_limit_ppm=water_limit_ppm, oxygen_limit_ppm=oxygen_limit_ppm)

    def wait_task_with_ops(self, task_id: int | None = None, *, poll_interval_s: float = 2.0) -> int:
        return super().wait_task_with_ops(task_id, poll_interval_s=poll_interval_s)

    def export_task_report(self, task_id: int, file_type: str = "excel") -> Path:
        return super().export_task_report(task_id, file_type=file_type)

    # ---------- 6. 下料动作 ----------
    def batch_out_task_and_empty_trays(self, task_id: int | None = None, *, poll_interval_s: float = 1.0, ignore_missing: bool = True, timeout_s: float = 900.0, move_type: str = "main_out"):
        return super().batch_out_task_and_empty_trays(task_id, poll_interval_s=poll_interval_s, ignore_missing=ignore_missing, timeout_s=timeout_s, move_type=move_type)

    def batch_out_task_and_chemical_trays(self, task_id: int | None = None, *, poll_interval_s: float = 1.0, ignore_missing: bool = True, timeout_s: float = 900.0, move_type: str = "main_out"):
        return super().batch_out_task_and_chemical_trays(task_id, poll_interval_s=poll_interval_s, ignore_missing=ignore_missing, timeout_s=timeout_s, move_type=move_type)

    def batch_out_task_trays(self, task_id: int | None = None, *, poll_interval_s: float = 1.0, ignore_missing: bool = True, timeout_s: float = 900.0, move_type: str = "main_out"):
        return super().batch_out_task_trays(task_id, poll_interval_s=poll_interval_s, ignore_missing=ignore_missing, timeout_s=timeout_s, move_type=move_type)

    def batch_out_empty_trays(self, *, poll_interval_s: float = 1.0, ignore_missing: bool = True, timeout_s: float = 900.0, move_type: str = "main_out"):
        return super().batch_out_empty_trays(poll_interval_s=poll_interval_s, ignore_missing=ignore_missing, timeout_s=timeout_s, move_type=move_type)

    def batch_out_tray(self, layout_list: list[dict], move_type: str = "main_out", *, task_id: int = None, poll_interval_s: float = 1.0, timeout_s: float = 900.0):
        return super().batch_out_tray(layout_list, move_type=move_type, task_id=task_id, poll_interval_s=poll_interval_s, timeout_s=timeout_s)

    def auto_unload_trays_to_agv(self, batch_out_file: Optional[str] = None, *, block: bool = True):
        return super().auto_unload_trays_to_agv(batch_out_file, block=block)

    # ---------- 7. Unilab 接口（待修改） ----------
    def submit_experiment_task(
        self,
        chemical_db_path: str,
        task_name: str = "Unilab_Auto_Job",
        reaction_type: str = "heat",
        duration: str = "8",
        temperature: str = "40",
        stir_speed: str = "500",
        target_temp: str = "30",
        auto_magnet: bool = True,
        fixed_order: bool = False,
        internal_std_name: str = "",
        stir_time_after_std: str = "",
        diluent_name: str = "",
        rows: list = None
    ) -> JsonDict:
        """
        功能:
            提交 Unilab 流程编排任务, 按行数据动态生成表头, 兼容包含“加磁子”的列.
        参数:
            chemical_db_path: str, 化学品库文件路径.
            task_name: str, 任务名称.
            reaction_type: str, 反应类型.
            duration: str, 反应时间(h).
            temperature: str, 反应温度(°C).
            stir_speed: str, 搅拌速度(rpm).
            target_temp: str, 搅拌后目标温度(°C).
            auto_magnet: bool, 是否自动加磁子.
            fixed_order: bool, 是否固定加料顺序.
            internal_std_name: str, 内标名称.
            stir_time_after_std: str, 内标加入后搅拌时间(min).
            diluent_name: str, 稀释液名称.
            rows: List[List[Any]], 行数据矩阵, 第1列为实验编号, 其余列为试剂或“加磁子”.
        返回:
            Dict[str, Any], 提交成功后返回的任务 ID.
        """
        c_path = Path(chemical_db_path)
        if c_path.exists() is False:
            raise FileNotFoundError(f"未找到化学品库文件: {c_path}")

        chem_df = pd.read_excel(c_path) if c_path.suffix.lower() in [".xlsx", ".xls"] else pd.read_csv(c_path)
        chem_df.columns = [str(c).strip().lower() for c in chem_df.columns]

        def _pick(row, *keys, default=None):
            for k in keys:
                if k in row and pd.notna(row[k]):
                    return row[k]
            return default

        chemical_db: Dict[str, Dict[str, Any]] = {}
        for _, r in chem_df.iterrows():
            row = {k: r.get(k) for k in chem_df.columns}
            name = str(_pick(row, "substance", "name", "chemical_name", default="") or "").strip()
            if name == "":
                continue
            chemical_db[name] = {
                "chemical_id": _pick(row, "chemical_id"),
                "molecular_weight": _pick(row, "molecular_weight", "mw"),
                "physical_state": str(_pick(row, "physical_state", "state", default="") or "").strip().lower(),
                "density (g/mL)": _pick(row, "density (g/ml)", "density(g/ml)", "density_g_ml", "density", default=None),
                "physical_form": str(_pick(row, "physical_form", default="") or "").strip().lower(),
                "active_content": _pick(row, "active_content", "active_content(mmol/ml or wt%)", "active_content(mol/l or wt%)", default=""),
            }

        if auto_magnet is True:
            auto_magnet_text = "是"
        else:
            auto_magnet_text = "否"

        if fixed_order is True:
            fixed_order_text = "是"
        else:
            fixed_order_text = "否"

        params = {
            "实验名称": task_name,
            "反应器类型": reaction_type,
            "反应时间(h)": duration,
            "反应温度(°C)": temperature,
            "转速(rpm)": stir_speed,
            "搅拌后目标温度(°C)": target_temp,
            "自动加磁子": auto_magnet_text,
            "固定加料顺序": fixed_order_text,
            "内标种类": internal_std_name,
            "加入内标后搅拌时间(min)": stir_time_after_std,
            "稀释液种类": diluent_name,
        }

        if rows is None:
            rows = []

        default_pair_count = 5
        cleaned_rows: List[List[Any]] = []
        magnet_columns: set[int] = set()
        max_col_count = 1

        for row in rows:
            if isinstance(row, (list, tuple)) is False:
                logger.warning("行数据格式需要列表或元组, 已跳过一行")
                continue
            row_values = list(row)
            while len(row_values) > 0:
                tail_text = "" if row_values[-1] is None else str(row_values[-1]).strip()
                if tail_text == "":
                    row_values.pop()
                    continue
                break
            if len(row_values) > max_col_count:
                max_col_count = len(row_values)
            for col_index, cell in enumerate(row_values):
                cell_text = "" if cell is None else str(cell).strip()
                if "加磁子" in cell_text:
                    magnet_columns.add(col_index)
            cleaned_rows.append(row_values)

        if len(cleaned_rows) == 0:
            header_count = 1 + default_pair_count * 2
        else:
            header_count = max_col_count

        headers: List[str] = ["实验编号"]
        for col_index in range(1, header_count):
            if col_index in magnet_columns:
                headers.append("加磁子")
            elif col_index % 2 == 1:
                headers.append("试剂")
            else:
                headers.append("试剂量")

        normalized_rows: List[List[Any]] = []
        for row_values in cleaned_rows:
            padded_values = row_values + [""] * (header_count - len(row_values))
            normalized_rows.append(padded_values)

        try:
            task_payload = self.build_task_payload(params, headers, normalized_rows, chemical_db)
        except AttributeError as exc:
            raise Exception("无法找到 build_task_payload 方法, 请检查 StationController 定义") from exc

        try:
            resp = self.add_task(task_payload)
        except ApiError as exc:
            if getattr(exc, "code", None) == 409:
                # 自动重命名: 在任务名称后添加当前日期时间(精确到秒)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

                task_name_val = task_payload.get("task_name") or params.get("实验名称")
                new_task_name = f"{task_name_val}_{timestamp}"

                task_payload["task_name"] = new_task_name
                logger.info(f"任务名称重复, 自动重命名为: {new_task_name}")

                # 重试提交
                try:
                    resp = self.add_task(task_payload)
                except ApiError as retry_exc:
                    logger.error(f"重命名后任务提交仍失败: {retry_exc}")
                    raise
            else:
                raise

        task_id = resp.get("task_id")
        return task_id

    # ---------- 分析站对接 ----------
    def run_analysis(self, task_id: Optional[str] = None) -> Dict:
        """
        功能:
            读取指定合成任务(或最新任务)的 xlsx 配置, 自动生成分析任务 CSV
            并通过 AnalysisStationController 提交至对应仪器(当前已实现 GC_MS).
        参数:
            task_id: 合成任务 ID 字符串, 为 None 时自动选取编号最大的最近任务.
        返回:
            Dict: 各仪器提交结果, 格式示例:
                {
                    "gc_ms":      {"success": bool, "return_info": str},
                    "uplc_qtof":  {"success": bool, "return_info": str},
                    "hplc":       {"success": bool, "return_info": str},
                }
        """
        # 延迟绝对导入，避免模块级相对导入越界问题
        # 运行目录为 devices/，eit_analysis_station 可直接作为顶层包访问
        from eit_analysis_station.controller.analysis_controller import AnalysisStationController

        # 创建分析站控制器实例，使用其默认配置
        analysis_ctrl = AnalysisStationController()

        logger.info("启动分析任务提交流程, task_id=%s", task_id)
        results = analysis_ctrl.run_analysis(task_id=task_id)
        return results

    def poll_analysis_run(
        self, task_id: Optional[str] = None, poll_interval: float = 30.0
    ) -> Dict:
        """
        功能:
            轮询 GC-MS 分析任务运行状态, 完成后自动触发结果处理(积分+定性+报告).
            内部委托给 AnalysisStationController.poll_analysis_run 执行.
        参数:
            task_id: 合成任务 ID 字符串, 为 None 时自动选取编号最大的最近任务.
            poll_interval: 轮询间隔(秒), 默认 30 秒.
        返回:
            Dict: process_gc_ms_results 的返回值, 包含 success/return_info/report_path.
        """
        from eit_analysis_station.controller.analysis_controller import AnalysisStationController

        analysis_ctrl = AnalysisStationController()

        logger.info("启动 GC-MS 轮询流程, task_id=%s, poll_interval=%.0fs", task_id, poll_interval)
        result = analysis_ctrl.poll_analysis_run(task_id=task_id, poll_interval=poll_interval)
        return result
