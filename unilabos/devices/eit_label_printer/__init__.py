# coding: utf-8
"""
功能:
    EIT 标签打印独立模块.
    封装 TSC/TSPL 兼容打印机的驱动, 服务与交互式入口, 被 eit_hub 作为一级工站调度,
    也可被 eit_synthesis_station 等其它设备作为通用打印服务复用.

子目录:
    config/   打印机运行参数 (YAML 路径, DLL 路径, 日志级别等)
    driver/   LabelPrintService 服务类与底层 TSPL 打印引擎
    libs/     TSCLIB.dll (Windows 原生驱动)
    profiles/ 标签纸物理规格 YAML 模板
    tests/    单元测试与 Spooler 诊断脚本
"""
