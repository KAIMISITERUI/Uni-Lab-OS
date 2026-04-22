# coding: utf-8
"""
功能:
    EIT 标签打印独立模块交互式入口.
    被 eit_hub 通过 importlib.import_module("eit_label_printer.main").interactive() 调用.
    也支持直接运行 python -m unilabos.devices.eit_label_printer.main.

用法:
    python -m unilabos.devices.eit_label_printer.main

环境变量 (可选):
    LABEL_PRINTER_TRANSPORT=wifi  或  dll
    LABEL_PRINTER_WIFI_HOST=192.168.1.20
    LABEL_PRINTER_WIFI_PORT=9100
    LABEL_PRINTER_DLL_PRINTER_PORT="Gprinter GP-1134T"
"""

import logging
import sys

from unilabos.devices.eit_label_printer.config import PrinterSettings, configure_logging
from unilabos.devices.eit_label_printer.driver import LabelPrintService


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
    logger.info("传输方式: %s", settings.transport)
    if settings.transport == "wifi":
        logger.info("WiFi 目标: %s:%d (超时 %.1fs)",
                    settings.wifi_host, settings.wifi_port, settings.wifi_timeout)
    else:
        logger.info("Windows 打印机名: %s", settings.dll_printer_port)
        logger.info("DLL 路径: %s", settings.dll_path)

    # 构造服务并预检打印机可用性
    service = LabelPrintService(settings=settings)
    if not service.connect():
        print("打印机初始化失败, 请检查通讯配置")
        return

    columns = service.columns

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

            # 逐列收集输入内容, 任一列输入 quit 立即退出循环
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

            # 所有列都为空视为无效输入, 重新提示
            if all(t == "" for t in texts):
                print("输入为空, 请重新输入")
                continue

            if service.print_label(texts):
                print(f"已打印: {' | '.join(texts)}")
            else:
                print("打印失败, 请检查打印机连接")

    except KeyboardInterrupt:
        print("\n检测到中断信号")

    finally:
        service.disconnect()
        logger.info("=== 标签打印交互台已退出 ===")


if __name__ == "__main__":
    interactive()
    sys.exit(0)
