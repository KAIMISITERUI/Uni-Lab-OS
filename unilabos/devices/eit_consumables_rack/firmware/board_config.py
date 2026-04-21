# coding: utf-8
"""
功能:
    HaaS506-ED1 固件运行时参数.
    板子实际运行标准 MicroPython on ESP32, RS485 走 UART2 (TX=GPIO18, RX=GPIO17).
    烧录前按实际现场修改 WIFI_SSID WIFI_PASSWORD WIFI_STATIC_IPCONFIG.
"""

# WiFi 连接参数
WIFI_SSID = "EIT-wireless"
WIFI_PASSWORD = ""
WIFI_CONNECT_TIMEOUT_S = 20                  # 连接阶段等待 isconnected 的超时
WIFI_RETRY_INTERVAL_S = 5                    # 掉线后重连间隔

# 静态 IP 配置, 4-tuple (ip, subnet_mask, gateway, dns)
WIFI_STATIC_IPCONFIG = (
    "192.168.1.45",
    "255.255.255.0",
    "192.168.1.1",
    "192.168.1.1",
)

# TCP Server 参数
TCP_LISTEN_HOST = ""                         # 空串表示监听全部网卡
TCP_LISTEN_PORT = 6006
TCP_BACKLOG = 1                              # 单客户端轮询即可
TCP_RECV_CHUNK = 512

# RS485 UART 参数, 来自板卡 factory.py: UART2 tx=18 rx=17
UART_ID = 2
UART_TX_PIN = 18
UART_RX_PIN = 17
UART_BAUDRATE = 38400                        # 数字量输入模块出厂波特率

# Modbus 轮询参数
SLAVE_ADDRS = (1, 2, 3, 4, 5)                # 5 层货架对应 5 个 Modbus 从机
REG_START = 0                                # Input Register 起始地址
REG_COUNT = 6                                # 每层 6 个盘位
PER_SLAVE_TIMEOUT_MS = 300                   # 单从机响应超时
INTER_FRAME_GAP_MS = 30                      # 相邻 RTU 帧之间间隔, 保证 >= 3.5 字符时长

# 板载 LED 指示 (来自 factory.py)
LED_WIFI_PIN = 39                            # WiFi 已连接时常亮
LED_RUN_PIN = 21                             # 主循环心跳, 每次查询闪一次
