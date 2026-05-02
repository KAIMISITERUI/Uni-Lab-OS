/**
 * Duco 机械臂原生 WebSocket RPC 单例
 * 复刻官方 movement 控制语义: notify 模式, fire-and-forget, 不等响应.
 * 官方帧格式: {id, task, block, ret, req}
 */
import axios from 'axios'

let socket: WebSocket | null = null
let wsUrl: string | null = null
let nextId = 1
let reconnectTimer: number | null = null
let activeRefs = 0
const RECONNECT_INTERVAL_MS = 2000

async function ensureWsUrl(): Promise<string> {
  if (wsUrl !== null) {
    return wsUrl
  }
  const { data } = await axios.get<{ ws_path: string }>('/api/agv/arm/duco-ws-endpoint')
  const loc = window.location
  const scheme = loc.protocol === 'https:' ? 'wss' : 'ws'
  // loc.host 已含端口, 同源拼接, 自动跟随访问入口 (本机/手机/HTTPS 反代)
  wsUrl = `${scheme}://${loc.host}${data.ws_path}`
  return wsUrl
}

function generateId(): number {
  nextId = (nextId + 1) & 0x7fffffff
  return nextId
}

function scheduleReconnect(): void {
  if (reconnectTimer !== null) {
    return
  }
  if (activeRefs <= 0) {
    return
  }
  reconnectTimer = window.setTimeout(() => {
    reconnectTimer = null
    void openSocket()
  }, RECONNECT_INTERVAL_MS)
}

async function openSocket(): Promise<void> {
  if (socket !== null) {
    const state = socket.readyState
    if (state === WebSocket.OPEN || state === WebSocket.CONNECTING) {
      return
    }
  }
  let url: string
  try {
    url = await ensureWsUrl()
  } catch (error) {
    console.warn('[ducoWs] 获取 ws_path 失败, 稍后重试', error)
    scheduleReconnect()
    return
  }
  const ws = new WebSocket(url)
  socket = ws
  ws.addEventListener('close', () => {
    if (socket === ws) {
      socket = null
      scheduleReconnect()
    }
  })
  ws.addEventListener('error', () => {
    // close 事件会紧随其后触发重连, 此处无需处理
  })
}

export function acquireDucoWs(): void {
  activeRefs = activeRefs + 1
  void openSocket()
}

export function releaseDucoWs(): void {
  activeRefs = Math.max(0, activeRefs - 1)
  if (activeRefs === 0) {
    if (reconnectTimer !== null) {
      window.clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (socket !== null) {
      try {
        socket.close(1000, 'client release')
      } catch {
        // 关闭失败忽略
      }
      socket = null
    }
  }
}

function notify(task: string, req: Record<string, unknown>): void {
  if (socket === null || socket.readyState !== WebSocket.OPEN) {
    return
  }
  const frame = { id: generateId(), task, block: false, ret: true, req }
  try {
    socket.send(JSON.stringify(frame))
  } catch {
    // 发送失败依赖 onclose 自动重连
  }
}

// ========== 方向字符串 → Duco 原生参数 ==========
const TCP_AXIS_MAP: Record<string, number> = { x: 0, y: 1, z: 2, rx: 3, ry: 4, rz: 5 }
const JOINT_AXIS_MAP: Record<string, number> = { j1: 0, j2: 1, j3: 2, j4: 3, j5: 4, j6: 5 }
const REF_COORDINATE_MAP: Record<'base' | 'tcp' | 'user', number> = {
  base: 0,
  tcp: 1,
  user: 2,
}

export interface MoveJogPayload {
  direction: string
  refCoord: 'base' | 'tcp' | 'user'
  useStep: boolean
  stepMm: number
  stepRad: number
  speed: number
}

export function moveJog(payload: MoveJogPayload): void {
  const token = payload.direction.trim().toLowerCase()
  if (token.length < 2) {
    return
  }
  const signChar = token.slice(-1)
  const axisKey = token.slice(0, -1)
  if (signChar !== '+' && signChar !== '-') {
    return
  }
  const dir = signChar === '+' ? 1 : -1
  let type = 0
  let axis = 0
  if (axisKey in TCP_AXIS_MAP) {
    type = 1
    axis = TCP_AXIS_MAP[axisKey]
  } else if (axisKey in JOINT_AXIS_MAP) {
    type = 2
    axis = JOINT_AXIS_MAP[axisKey]
  } else {
    return
  }
  const speedPct = Math.max(1, Math.min(100, Math.round(payload.speed * 100)))
  notify('moveJog', {
    type,
    dir,
    axis,
    speed: speedPct,
    ref: REF_COORDINATE_MAP[payload.refCoord],
    use_step: payload.useStep,
    step_j: payload.stepRad,
    step_l: payload.stepMm / 1000,
  })
}

export function stopManualMove(): void {
  notify('stopManualMove', {})
}
