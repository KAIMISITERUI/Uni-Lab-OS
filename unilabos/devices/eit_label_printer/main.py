# coding: utf-8
"""
功能:
    EIT 标签打印独立模块交互式入口.
    被 eit_hub 通过 importlib.import_module("eit_label_printer.main").interactive() 调用.
    也支持直接运行 python -m unilabos.devices.eit_label_printer.main.

用法:
    python -m unilabos.devices.eit_label_printer.main
"""

import logging
import sys

from unilabos.devices.eit_label_printer.config import PrinterSettings, configure_logging
from unilabos.devices.eit_label_printer.driver.print_engine import (
    check_printer_ready,
    execute_print_job,
    load_config,
    load_dll,
)


logger = logging.getLogger(__name__)


def interactive() -> None:
    """
    功能:
        启动标签打印交互式循环.
        按照 YAML 列数依次提示输入每列内容, 回车后立即打印.
        输入 quit 或 Ctrl+C 退出.

    参数:
        无.

    返回:
        无.
    """
    settings = PrinterSettings.from_env()
    configure_logging(settings.log_level)

    logger.info("=== EIT 标签打印交互台启动 ===")
    logger.info("配置文件: %s", settings.config_path)
    logger.info("DLL 路径: %s", settings.dll_path)

    # 加载配置和DLL
    config = load_config(str(settings.config_path))
    lib = load_dll(str(settings.dll_path))

    # 启动时预检一次, 但不长期占用端口
    try:
        check_printer_ready(lib, config)
    except Exception as exc:
        logger.error("打印机初始化失败: %s", exc)
        print(f"打印机初始化失败: {exc}")
        return

    columns = config["paper"].get("columns", 1)

    logger.info("打印机就绪, 等待输入...")
    print("-" * 40)
    if columns > 1:
        print(f"当前配置: {columns}列标签, 每次需依次输入{columns}列内容")
    print("输入要打印的文字后按回车即可打印")
    print("输入 quit 退出程序")
    print("-" * 40)

    try:
        while True:
            texts = []
            quit_flag = False

            # 收集每列的输入内容
            for col in range(columns):
                try:
                    if columns > 1:
                        prompt = f"\n请输入第{col + 1}列内容: "
                    else:
                        prompt = "\n请输入打印内容: "
                    text = input(prompt).strip()
                except EOFError:
                    quit_flag = True
                    break

                if text.lower() == "quit":
                    quit_flag = True
                    break

                texts.append(text)

            if quit_flag:
                break

            # 检查是否所有列都为空
            if all(t == "" for t in texts):
                print("输入为空, 请重新输入")
                continue

            try:
                execute_print_job(lib, config, texts)
                print(f"已打印: {' | '.join(texts)}")
            except Exception as exc:
                logger.error("打印失败: %s", exc)
                print(f"打印出错: {exc}, 请检查打印机连接")

    except KeyboardInterrupt:
        print("\n检测到中断信号")

    finally:
        logger.info("=== 标签打印交互台已退出 ===")


if __name__ == "__main__":
    interactive()
    sys.exit(0)
