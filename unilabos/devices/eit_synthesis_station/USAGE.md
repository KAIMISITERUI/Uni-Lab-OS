# SAE Ops Sidecar — API 使用手册

通过 HTTP 远程触发 SAE 工程界面里的常用动作（取放介质/托盘 + W1 排进出）。

- **服务地址**：`http://<sidecar 主机 IP>:4670`（局域网可达，本机为 `127.0.0.1:4670`）
- **进程**：独立 Python 进程，与 spacestation/saturnv 解耦，崩溃自重启
- **底层**：通过 saturnv `Lc39aClient` RPC 调用 station_agent（node 306）`operations/*`，与工程界面按按钮等价

---

## 1. 端点总览

| 方法 | 路径 | 作用 | 请求体 | 调用通路 |
|---|---|---|---|---|
| GET | `/health` | 探活 | 无 | — |
| POST | `/api/ops/pick_up` | 取介质 | `PickReq` | station_agent RPC |
| POST | `/api/ops/put_down` | 放介质 | `PickReq` | station_agent RPC |
| POST | `/api/ops/pick_up_tray` | 取托盘 | `TrayReq` | station_agent RPC |
| POST | `/api/ops/put_down_tray` | 放托盘 | `TrayReq` | station_agent RPC |
| POST | `/api/ops/w1_out` | W-1-X 伸到人工操作位 | `W1Req` | ScriptActionExecutor |
| POST | `/api/ops/w1_in` | W-1-X 缩回到操作位 | `W1Req` | ScriptActionExecutor |

所有 POST 接口都支持查询参数 **`?dry_run=true`**，仅校验/打印不真正下发动作。

**调用通路差异**：
- `station_agent RPC`：通过 [Lc39aClient.callWithFnName](c:/ProgramData/Anaconda3/envs/satv/Lib/site-packages/saturnv/runtime_db/lc39a/node_client.py) 调 node 306（`operations/*` 路径）。
- `ScriptActionExecutor`：通过 [ScriptActionExecutor](c:/ProgramData/Anaconda3/envs/satv/Lib/site-packages/standalone_gui/core/executor.py) 在 sidecar 进程内运行 `actions/*` onestep 脚本（station_agent 不暴露 actions/，只能这样调）。两条通路最终都会发 motor RPC，只是 sidecar 的角色不同。

### 请求体 schema

`PickReq`（介质）：
| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `src` | string | ✓ |  | 源孔位码，例 `W-2-1:0` |
| `dst` | string | * |  | 目标孔位码；**`put_down` 必填**，`pick_up` 可省（onestep 脚本只解析不使用，不影响机械臂） |
| `resource_type` | string | ✓ |  | 介质类型码，例 `220000005` |
| `has_cap` | bool |  | `false` | 介质是否带盖。`true`=带盖容器（瓶+盖），走带盖 take/put 分支；`false`=散件试管 |
| `timeout` | int |  | `600` | 单次 RPC 超时（秒） |

`TrayReq`（托盘）：
| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `src` | string | ✓ |  | 源孔位码，例 `TB-2-1:-1` |
| `dst` | string | * |  | 目标孔位码；**`put_down_tray` 必填**，`pick_up_tray` 可省 |
| `resource_type` | string | ✓ |  | 托盘类型码，例 `201000711` |
| `timeout` | int |  | `600` | 单次 RPC 超时（秒） |

> `*` `dst` 在 4 个动作里语义不对称——见下面"`dst` 的非对称语义"。

`W1Req`（W1 排进出）：
| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `location_num` | int | ✓ |  | 列号，工程界面用 `1`/`3`/`5`/`7` 标识 4 列；脚本接受 1-8（1-2、3-4、5-6、7-8 各为一对，控同一列） |
| `timeout` | int |  | `120` | 脚本执行超时（秒），单列伸/缩典型耗时 5-15s |

### 孔位码（layout_code）格式

`<区域>-<排>[-<列>]:<位号>`

| 前缀 | 含义 |
|---|---|
| `TB` | 托盘暂存 / 出入口 |
| `N` | N 层货架 |
| `W` | W 层货架 |
| `SC` | SC 位 |
| `MSB` | 加磁子模块 |

末尾位号约定：介质常用 `:0`、`:1` 等子位；托盘常用 `:-1`（无子位）。

### `dst` 的非对称语义（重要）

来自 onestep 脚本源码（[c:/deploy/os_scripts/os_scripts/HGDSZ/operations/](c:/deploy/os_scripts/os_scripts/HGDSZ/operations/)）的实际行为：

| 动作 | 脚本里 dst 是否驱动机械臂 | sidecar 处理 |
|---|---|---|
| `pick_up` | **否**——只 `@print` + 解析为 `$Dst_*`，所有 take 子动作只用 `$Src_*` | 可省；省略时 sidecar 自动用 `src` 占位 |
| `put_down` | **是**——`Claw_*/X/put Location_*: $Dst_*` | 必填，缺则 422 |
| `pick_up_tray` | **否**——只解析，后续不引用 `$Dst_*` | 可省；省略时自动占位 |
| `put_down_tray` | **是**——`Claw_TRAY/X/put Location_*: $Dst_*` | 必填，缺则 422 |

通俗讲：**取**（`pick_up` / `pick_up_tray`）只是从 `src` 抓到机械臂手爪里，下一步放哪还没决定，`dst` 给不给都行；**放**（`put_down` / `put_down_tray`）必须告诉它放到哪，`dst` 是核心。

工程界面上"取介质"按钮**只显示 `src` 和 `resource_type`**就是这个原因——`dst` 不影响动作所以没必要让操作员填。

---

## 2. 端点详细说明

### 2.1 GET `/health`

探活接口，无副作用。

**请求**：
```bash
curl http://127.0.0.1:4670/health
```

**响应**：
```json
{ "ok": true, "node_id": 306 }
```

---

### 2.2 POST `/api/ops/pick_up`（取介质）

**等价动作**：工程界面"取介质"按钮。机械臂从 `src` 抓取一个介质（瓶/管）到手爪。`dst` 不参与动作（参见上文"dst 的非对称语义"），可省。

**最小请求 curl 示例**（与工程界面字段一致）：
```bash
curl -X POST http://10.32.2.106:4670/api/ops/pick_up ^
  -H "Content-Type: application/json" ^
  -d "{\"src\":\"W-3-5:0\",\"resource_type\":\"201000816\"}"
```

**带 has_cap / dst 的完整示例**：
```bash
curl -X POST http://10.32.2.106:4670/api/ops/pick_up ^
  -H "Content-Type: application/json" ^
  -d "{\"src\":\"W-2-1:0\",\"dst\":\"SC-1:0\",\"resource_type\":\"220000005\",\"has_cap\":true}"
```

**Python 示例**：
```python
import requests
r = requests.post(
    "http://10.32.2.106:4670/api/ops/pick_up",
    json={"src": "W-3-5:0", "resource_type": "201000816"},  # dst/has_cap 可省
    timeout=620,
)
print(r.status_code, r.json())
```

**成功响应**：
```json
{ "ok": true, "result": { "...station_agent 返回..." } }
```

---

### 2.3 POST `/api/ops/put_down`（放介质）

**等价动作**：工程界面"放介质"按钮。机械臂把手爪上的介质放到 `dst`。**`dst` 必填**——缺了直接 422。

**curl 示例**：
```bash
curl -X POST http://10.32.2.106:4670/api/ops/put_down ^
  -H "Content-Type: application/json" ^
  -d "{\"src\":\"SC-1:0\",\"dst\":\"W-2-1:0\",\"resource_type\":\"220000005\",\"has_cap\":true}"
```

`src` 也填上是为了给上层任务做记账（onestep 脚本里 `@print :"src"`），动作上不读它。

---

### 2.4 POST `/api/ops/pick_up_tray`（取托盘）

**等价动作**：工程界面"取托盘"按钮。机械臂从 `src` 抓整盘托盘到手爪。`dst` 不参与动作，可省。

**最小请求 curl**：
```bash
curl -X POST http://10.32.2.106:4670/api/ops/pick_up_tray ^
  -H "Content-Type: application/json" ^
  -d "{\"src\":\"TB-2-1:-1\",\"resource_type\":\"201000711\"}"
```

**Python 示例（带 dst 做记账）**：
```python
import requests
r = requests.post(
    "http://10.32.2.106:4670/api/ops/pick_up_tray",
    json={"src": "TB-2-1:-1", "resource_type": "201000711"},  # dst 可省
    timeout=620,
)
print(r.status_code, r.json())
```

---

### 2.5 POST `/api/ops/put_down_tray`（放托盘）

**等价动作**：工程界面"放托盘"按钮。**`dst` 必填**——缺了直接 422。

**curl 示例**：
```bash
curl -X POST http://10.32.2.106:4670/api/ops/put_down_tray ^
  -H "Content-Type: application/json" ^
  -d "{\"src\":\"N-3:-1\",\"dst\":\"TB-2-1:-1\",\"resource_type\":\"201000711\"}"
```

---

### 2.6 POST `/api/ops/w1_out`（W-1-X 伸到人工操作位）

**等价动作**：工程界面下拉项 "1: W-1-X伸到人工操作位（参数1，3，5，7）"。底层 onestep 脚本：[c:/deploy/os_scripts/os_scripts/HGDSZ/actions/eq_W_Do/W1_DO/single_go_out_pos](c:/deploy/os_scripts/os_scripts/HGDSZ/actions/eq_W_Do/W1_DO/single_go_out_pos)

**curl 示例**：
```bash
curl -X POST http://10.32.2.106:4670/api/ops/w1_out ^
  -H "Content-Type: application/json" ^
  -d "{\"location_num\":1}"
```

**Python 示例**：
```python
import requests
r = requests.post(
    "http://10.32.2.106:4670/api/ops/w1_out",
    json={"location_num": 1},      # 工程界面用 1/3/5/7
    timeout=140,
)
print(r.status_code, r.json())
```

执行流程：脚本里依据 `Location_Num` 的奇偶组（1-2/3-4/5-6/7-8）选择对应电机 ID，先 `Motor.home`（仅前 2 列）再 `Motor.move` 到 `W_1_GO_OUTSIDE_POS` 全局常量定义的位置。

---

### 2.7 POST `/api/ops/w1_in`（W-1-X 缩回到操作位）

**等价动作**：与 `w1_out` 反向，把 W-1 排某列从外面缩回到操作位。底层脚本：[c:/deploy/os_scripts/os_scripts/HGDSZ/actions/eq_W_Do/W1_DO/single_go_in_operate_pos](c:/deploy/os_scripts/os_scripts/HGDSZ/actions/eq_W_Do/W1_DO/single_go_in_operate_pos)

**curl 示例**：
```bash
curl -X POST http://10.32.2.106:4670/api/ops/w1_in ^
  -H "Content-Type: application/json" ^
  -d "{\"location_num\":1}"
```

执行流程：先 `Motor.getPos` 读当前位置，若已在 `W_1_GO_IN_OPERATE_POS` 处则跳过；否则 `Motor.home`（前 2 列）+ `Motor.move` 回操作位。脚本自带幂等检测，重复调用安全。

---

## 3. dry_run 模式（仅校验不下发）

任何 POST 接口加查询参数 `?dry_run=true`，请求体一致，但**不会真正调用 lc39a，不会驱动机械臂**。返回将要下发的 RPC 参数，便于上线前对参数。

```bash
curl -X POST "http://10.32.2.106:4670/api/ops/pick_up_tray?dry_run=true" ^
  -H "Content-Type: application/json" ^
  -d "{\"src\":\"TB-2-1:-1\",\"dst\":\"N-3:-1\",\"resource_type\":\"201000711\"}"
```

返回：
```json
{
  "dry_run": true,
  "fn_name": "operations/pick_up_tray",
  "payload": {
    "src": "TB-2-1:-1",
    "dst": "N-3:-1",
    "resource_type": "201000711",
    "__async": true
  }
}
```

把 `payload` 与 [c:/SAE/spacestation/logs/](c:/SAE/spacestation/logs/) 当天日志里 `>>> call operation operations/pick_up_tray ... kwargs { ... }` 段比对，字段一致即可放心切到正式调用。

---

## 4. 真实参数取值参考

来自 `node_log` 实际执行的 4 类调用样例（`dst` 在 pick 类里只是上层任务的目标记账，机械臂不读）：

| 动作 | src | dst | resource_type | 备注 |
|---|---|---|---|---|
| `pick_up_tray` | `TB-2-1:-1` | `N-3:-1` | `201000711` | TB 暂存 → N 层 |
| `pick_up_tray` | `TB-2-2:-1` | `W-2-5:-1` | `201000726` | TB 暂存 → W 层 |
| `pick_up_tray` | `TB-2-3:-1` | `N-1:-1` | `201000712` | TB 暂存 → N 层 |
| `pick_up_tray` | `N-1:-1` | `MSB-...` | `201000726` | N 层 → 加磁子模块 |
| `pick_up` | `W-2-1:0` | `SC-1:0` | `220000005` | `has_cap=true`，介质瓶 |
| `pick_up` | `W-3-5:0` | (省略) | `201000816` | 工程界面截图——只填 src+resource_type |

onestep 脚本里的默认值（参考）：

| 脚本 | 默认 src | 默认 dst | 默认 has_cap |
|---|---|---|---|
| [pick_up](c:/deploy/os_scripts/os_scripts/HGDSZ/operations/pick_up) | `MSFG:1` | `MS-1:0` | `false` |
| [put_down](c:/deploy/os_scripts/os_scripts/HGDSZ/operations/put_down) | `W-2-7:0` | `N-2:0` | `false` |
| [pick_up_tray](c:/deploy/os_scripts/os_scripts/HGDSZ/operations/pick_up_tray) | `N-3:0` | `W-1-2:0` | `false` |
| [put_down_tray](c:/deploy/os_scripts/os_scripts/HGDSZ/operations/put_down_tray) | `N-2:0` | `N-3:0` | `false` |

---

## 5. 错误码

| HTTP 状态 | 含义 | 处理 |
|---|---|---|
| 200 | 成功；查 `result.ok` 字段 | 正常处理结果 |
| 422 | 请求体字段缺失/类型错误 | FastAPI 返回的字段级错误，按 `detail` 修参数 |
| 500 | 调 lc39a 失败（节点不在线 / station 拒绝 / RPC 超时） | 看 sidecar 的 [audit.log](c:/SAE/ops_http/audit.log) `FAIL` 条目；常见原因看下面"故障排查" |
| 连接拒绝 | 4670 端口没起来 | 跑 [start.bat](c:/SAE/ops_http/start.bat) 或 schtasks 检查 |

---

## 6. 日志与监控

### 6.1 sidecar 自身日志

- **审计日志**：[c:/SAE/ops_http/audit.log](c:/SAE/ops_http/audit.log)
  - 每次调用三条：`CALL`（入参）→ `OK` 或 `FAIL`（结果）
- **stdout 日志**：[c:/SAE/ops_http/stdout.log](c:/SAE/ops_http/stdout.log)（仅开机自启模式下生成）
  - uvicorn 标准输出 + 崩溃重启记录

### 6.2 站点侧日志（产线现有）

- [c:/SAE/spacestation/logs/node_log.<日期>](c:/SAE/spacestation/logs/) — 收到 RPC 后由 station_agent 打印的详细执行日志，含 `STATION_RUN_*` 线程分配、子动作、返回状态等。
- 调用一次后在最新 node_log 末尾应能看到对应的 `>>> call operation operations/<name>: func_name: "operations/<name>"`，其 `kwargs { ... }` 与 sidecar `audit.log` 的 `payload` 字段一一对应。

---

## 7. 故障排查

| 现象 | 原因 | 处置 |
|---|---|---|
| 远程 `curl /health` 不通；本机通 | Windows 防火墙未放行 | 入站规则添加 `TCP 4670` 允许 |
| 4670 没人监听 | sidecar 没起来 | 看 [stdout.log](c:/SAE/ops_http/stdout.log) 末尾报错；手动 [start.bat](c:/SAE/ops_http/start.bat) 看前台输出 |
| 启动报 `ImportError: saturnv...` | 没在 satv conda 环境 | 必须用 [start.bat](c:/SAE/ops_http/start.bat) / [autostart.bat](c:/SAE/ops_http/autostart.bat)，它们激活了 `satv` |
| 500 `node 306 is not online` | spacestation 的 station_agent 节点没起来 | 先启动 spacestation 主服务（任务管理器看 4669 端口的 python 进程） |
| 500 `unsurpported operation:xxx` | 该工站没注册此 operation | 工站当前不支持该动作；非 sidecar 问题 |
| 500 RPC 超时 | 设备在动其它任务 / 节点卡住 | 看产线 node_log；必要时人工干预，等清空后再调 |
| 422 字段错 | JSON 缺字段或类型错 | 按响应 `detail` 修；常忘 `resource_type` |
| 调用阻塞很久 | 介质/托盘真实耗时 30~60s 正常；> 600s 即超时返错 | 默认 600s 已够；脚本侧 `requests.timeout` 至少给 620s |
| 工程界面与 sidecar 同时按 | sidecar 进程内 `_lock` + station_agent 内部线程串行 | 不会冲突，但会等前一个动作完才能下下一个 |
| 503 `ScriptActionExecutor unavailable` | sidecar 启动时 `import standalone_gui.core.executor` 失败（多半是 satv 环境缺依赖、配置目录不存在等）| `/health` 返回里 `script_import_err` 字段是具体异常；定位后修；station_agent 4 个 RPC 端点不受影响 |
| `/api/ops/w1_*` 500 `script timeout` | W1 电机卡住或 home 失败 | 看 sidecar `audit.log` 和电机节点日志；通常需要人工到 W1 排现场处理 |
| `/api/ops/w1_*` 500 onestep 异常 | 脚本内部抛错（如 motor 节点不在线） | 按 `detail` 中的错误码定位；`audit.log` 同步记 `FAIL` |

---

## 8. 服务管理速查

| 操作 | 命令 |
|---|---|
| 手动启动（前台调试） | 双击 [start.bat](c:/SAE/ops_http/start.bat) |
| 手动停止 | 双击 [stop.bat](c:/SAE/ops_http/stop.bat) |
| 注册开机自启 | 右键 [install_autostart.bat](c:/SAE/ops_http/install_autostart.bat) → 以管理员身份运行 |
| 取消开机自启 | 右键 [uninstall_autostart.bat](c:/SAE/ops_http/uninstall_autostart.bat) → 以管理员身份运行 |
| 查询任务计划 | `schtasks /query /tn SAE_OpsHttp_Sidecar` |
| 不重启立即触发自启脚本 | `schtasks /run /tn SAE_OpsHttp_Sidecar` |
| 看正在运行的实例 | `netstat -ano \| findstr :4670` |
| 看实时审计 | PowerShell：`Get-Content C:\SAE\ops_http\audit.log -Wait -Tail 10` |
| 完全卸载 | 先 `uninstall_autostart.bat` → 再 `stop.bat` → 删除 [c:/SAE/ops_http/](c:/SAE/ops_http/) 目录 |

---

## 9. 安全说明（用户已确认局域网可接受）

当前版本：
- 绑 `0.0.0.0:4670`，**任何局域网内可访问 4670 的设备都可触发动作**。
- 未启用 token / IP 白名单 / HTTPS。

如需加固（不需要修改产线源码，只动 sidecar 的 [app.py](c:/SAE/ops_http/app.py)）：
- 加 `Authorization: Bearer <token>` 头校验；
- 加请求源 IP 白名单中间件；
- 通过反向代理（nginx/caddy）提供 HTTPS。
