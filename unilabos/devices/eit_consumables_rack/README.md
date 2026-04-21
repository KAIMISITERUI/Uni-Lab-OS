# eit_consumables_rack

耗材货架 WiFi-RS485 网关模块。HaaS506-ED1 作为 TCP Server 把 RS485 Modbus RTU 总线抬到局域网, 电脑通过 TCP JSON 协议主动轮询 30 个盘位的占用状态。

## 硬件拓扑

```
+----------+   WiFi   +--------------+   RS485   +----- DI 模块(slave 01, 6 路) 第 1 层 6 盘位
|  电脑    | <------> | HaaS506-ED1  | <-------> +----- DI 模块(slave 02, 6 路) 第 2 层 6 盘位
| (Python) |   LAN    | (MicroPython)|           +----- DI 模块(slave 03, 6 路) 第 3 层 6 盘位
+----------+          +--------------+           +----- DI 模块(slave 04, 6 路) 第 4 层 6 盘位
                                                 +----- DI 模块(slave 05, 6 路) 第 5 层 6 盘位
```

- RS485 参数: 38400-8-N-1, 功能码 0x04(Read Input Registers), 起始 0, 数量 6
- 每个寄存器非 0 表示该盘位有耗材, 0 表示空

## 目录结构

```
eit_consumables_rack/
├── config/settings.py        电脑端运行参数 dataclass
├── driver/modbus_rtu.py      Modbus RTU CRC 与帧构造 / 解析(纯算法)
├── driver/rack_client.py     电脑端 TCP 客户端 RackClient
├── firmware/board_config.py  HaaS506 侧 WiFi / UART / 从机参数
├── firmware/board.json       HaaS506 串口硬件配置
├── firmware/rs485_modbus.py  HaaS506 侧 Modbus 查询(MicroPython)
├── firmware/main.py          HaaS506 固件入口
├── scripts/query_rack.py     命令行自检工具
└── tests/test_modbus_rtu.py  Modbus 算法单元测试(已通过)
```

## 通信协议

JSON over TCP, 一行一条, 以 `\n` 作帧分隔。电脑作客户端, HaaS 作服务端。

### 请求

```json
{"cmd": "query_all", "id": 1}
{"cmd": "query_layer", "layer": 1, "id": 2}
{"cmd": "ping", "id": 3}
```

### 响应

```json
{"ok": true, "cmd": "query_all", "id": 1, "ts_ms": 1745212766037,
 "layers": {"1":[0,1,0,0,0,0], "2":[0,0,0,0,0,0], "3":null, "4":[...], "5":[...]}}
{"ok": true, "cmd": "query_layer", "id": 2, "ts_ms": ..., "layer": 1, "positions": [0,1,0,0,0,0]}
{"ok": false, "cmd": "query_layer", "id": 2, "error": "slave 1 timeout"}
```

单层失败时 `query_all` 响应中该层值为 `null`, 同时附 `"partial": true`。

## HaaS506-ED1 端部署

> 实际板子刷的是标准 MicroPython on ESP32 (Thonny 识别为 `MicroPython (ESP32)`), 并非阿里 HaaS Python 轻应用. 固件因此使用 `machine.UART` / `network.WLAN` / 标准 `socket`, 不使用 `driver.UART` 和 `board.json`.
> RS485 硬件映射: **UART2, TX=GPIO18, RX=GPIO17, 硬件自动方向切换**. 信息来自板卡原厂 `factory.py`.

1. 修改 [firmware/board_config.py](firmware/board_config.py), 填入现场 WiFi SSID / 密码, 按需调整 `WIFI_STATIC_IPCONFIG` 和 `TCP_LISTEN_PORT`.
2. 通过 Thonny 或 ampy, 把 `firmware/` 下三个 `.py` 文件 (`main.py`, `board_config.py`, `rs485_modbus.py`) 拷到设备根目录. `factory.py` 保留不动.
3. 按 Ctrl+F2 重启后端, 或按板子 RST, 串口 115200 应看到:
   ```
   连接 WiFi SSID=EIT-wireless
   WiFi 已连接 IP=192.168.1.45
   RS485 UART 已打开 id=2 tx=18 rx=17 baud=38400
   TCP 监听 0.0.0.0:6006
   ```

## 电脑端使用

### 命令行自检

```bash
python -m unilabos.devices.eit_consumables_rack.scripts.query_rack \
    --host 192.168.1.xxx --port 6006
```

输出示例:
```
层 |  1   2   3   4   5   6
---------------------------
 1 |  ·   ■   ·   ·   ·   ·
 2 |  ·   ·   ·   ·   ·   ·
 3 |  ■   ■   ■   ·   ·   ·
 4 |  ·   ·   ·   ·   ·   ·
 5 |  ·   ·   ·   ·   ·   ·
```

退出码: 0 全部成功, 1 连接失败, 2 部分层查询失败。

### 业务代码调用

```python
from unilabos.devices.eit_consumables_rack.config.settings import RackSettings
from unilabos.devices.eit_consumables_rack.driver.rack_client import RackClient

settings = RackSettings(host="192.168.1.100", port=6006)
with RackClient(settings) as client:
    layers = client.query_all()                    # {1:[0,1,0,0,0,0], ..., 5:[...]}
    layer_1 = client.query_layer(1)                # [0,1,0,0,0,0]
    alive = client.ping()                          # True/False
```

或通过环境变量 `RACK_HOST` / `RACK_PORT` / `RACK_TIMEOUT` 初始化: `RackSettings.from_env()`。

## 单元测试

```bash
python -m unittest unilabos.devices.eit_consumables_rack.tests.test_modbus_rtu -v
```

测试覆盖: CRC 对真实抓包 `01 04 00 00 00 06 70 08` 的复现、空架响应、1 号位占用响应、坏 CRC、短帧、Modbus 异常响应。

## 端到端验证

1. HaaS 启动后, 从电脑 `ping` 命令返回 `true`
2. 手动遮挡任一盘位光电传感器, 500 ms 内 `query_all` 返回值相应位从 0 变 1
3. 拔掉 RS485 总线, `query_all` 对应层字段返回 `null`, 响应附 `partial:true`
4. 关闭 HaaS, `query_all` 抛 `RackClientError`, 不悬挂进程
