# coding: utf-8
"""
功能:
    eit_label_printer 配置子包, 对外暴露 PrinterSettings.
"""

from .settings import PrinterSettings, configure_logging

__all__ = ["PrinterSettings", "configure_logging"]
