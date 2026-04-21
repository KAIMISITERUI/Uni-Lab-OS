# coding: utf-8
"""
功能:
    耗材货架 WiFi-RS485 网关模块.
    HaaS506-ED1 作为 TCP Server 把 RS485 总线抬到局域网, 电脑作 TCP Client 主动轮询.
    本包下 driver/ 与 config/ 为电脑端代码, firmware/ 为 HaaS506-ED1 侧 MicroPython 代码.
"""
