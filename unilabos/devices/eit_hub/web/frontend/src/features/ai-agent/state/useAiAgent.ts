// AI 助手全局状态管理: 模块级 reactive 单例.
// 跨路由保留 sessionId / messages / sending 等状态, 浮动抽屉与历史页共享同一份引用.
// 与 Pinia 等价的最短路径方案, 不引入额外依赖.
import { computed, reactive } from 'vue'
import {
  createAiSession,
  deleteAiSession,
  fetchAiConfig,
  fetchAiSessionMessages,
  listAiSessions,
  renameAiSession,
  streamAiSendMessage,
  streamAiToolConfirm,
  updateAiConfig,
} from '../api/client'
import {
  AI_AGENT_MODEL_OPTIONS,
  type AiAgentModelId,
  type AiMessage,
  type AiSessionSummary,
  type SseEvent,
  type StreamHandle,
} from '../types'

// 浮动抽屉中显示的消息行, 与后端 AiMessage 拓扑一致, 但额外允许"流式构建中的 assistant"
export interface ChatMessageRow {
  // local_id 用于在流中累加 assistant token, 后端尚未返回 id 时使用负数占位
  local_id: number
  server_id: number | null
  role: 'system' | 'user' | 'assistant' | 'tool'
  content: string
  tool_calls: { id: string; name: string; arguments_text: string }[] | null
  tool_call_id: string | null
  status: 'committed' | 'pending_confirm' | 'rejected' | 'streaming'
  pending_tool_name: string | null
  pending_tool_args: Record<string, unknown> | null
  created_at: string
  // tool 行专用: 解析后的 result 或 error, 直接用于折叠卡片渲染
  display_payload: Record<string, unknown> | null
}

interface AiAgentState {
  open: boolean
  sessionId: string | null
  messages: ChatMessageRow[]
  sending: boolean
  pending: {
    message_id: number
    tool_call_id: string
    name: string
    arguments: Record<string, unknown>
    description: string
  } | null
  error: string | null
  recentSessions: AiSessionSummary[]
  recentLoading: boolean
  modelId: string
  modelLoading: boolean
  modelSaving: boolean
}

const state = reactive<AiAgentState>({
  open: false,
  sessionId: null,
  messages: [],
  sending: false,
  pending: null,
  error: null,
  recentSessions: [],
  recentLoading: false,
  modelId: AI_AGENT_MODEL_OPTIONS[0].value,
  modelLoading: false,
  modelSaving: false,
})

let _localCounter = -1
let _activeStream: StreamHandle | null = null

function _nextLocalId(): number {
  _localCounter -= 1
  return _localCounter
}

function _abortActiveStream(): void {
  if (_activeStream !== null) {
    try {
      _activeStream.abort()
    } catch (_err) {
      // 忽略 abort 错误
    }
    _activeStream = null
  }
}

function _toChatRow(message: AiMessage): ChatMessageRow {
  let payload: Record<string, unknown> | null = null
  if (message.role === 'tool' && message.content !== null) {
    try {
      payload = JSON.parse(message.content) as Record<string, unknown>
    } catch (_err) {
      payload = { _raw: message.content }
    }
  }
  return {
    local_id: message.id,
    server_id: message.id,
    role: message.role,
    content: message.content ?? '',
    tool_calls: message.tool_calls ?? null,
    tool_call_id: message.tool_call_id,
    status: message.status,
    pending_tool_name: message.pending_tool_name,
    pending_tool_args: message.pending_tool_args,
    created_at: message.created_at,
    display_payload: payload,
  }
}

async function _ensureSession(): Promise<string> {
  if (state.sessionId !== null && state.sessionId !== '') {
    return state.sessionId
  }
  const created = await createAiSession()
  state.sessionId = created.session_id
  return created.session_id
}

async function _consumeStream(handle: StreamHandle): Promise<void> {
  // 当前轮的 streaming assistant 行, 流结束或换轮时重置
  let streamingAssistant: ChatMessageRow | null = null

  for await (const event of handle.events) {
    _handleSseEvent(event, (row) => {
      streamingAssistant = row
    }, () => {
      streamingAssistant = null
    })
    if (state.error !== null) {
      // error 事件已在 handler 中设置, 主循环可继续等 done 收尾
    }
  }
  // 流自然结束, 清理引用 (handle 已耗尽)
  _activeStream = null
  // 若结束时还有 streaming 状态行, 把它转为 committed (后端落库时已生成正式 id, 但前端无从感知,
  // 等下一次 fetchAiSessionMessages 刷新时对齐)
  if (streamingAssistant !== null && streamingAssistant.status === 'streaming') {
    streamingAssistant.status = 'committed'
  }
}

function _handleSseEvent(
  event: SseEvent,
  setStreaming: (row: ChatMessageRow) => void,
  clearStreaming: () => void,
): void {
  if (event.event === 'token') {
    const text = String((event.data as { text?: string }).text ?? '')
    let last = state.messages[state.messages.length - 1]
    if (last === undefined || last.role !== 'assistant' || last.status !== 'streaming') {
      last = {
        local_id: _nextLocalId(),
        server_id: null,
        role: 'assistant',
        content: '',
        tool_calls: null,
        tool_call_id: null,
        status: 'streaming',
        pending_tool_name: null,
        pending_tool_args: null,
        created_at: new Date().toISOString(),
        display_payload: null,
      }
      state.messages.push(last)
      setStreaming(last)
    }
    last.content += text
    return
  }
  if (event.event === 'tool_call') {
    // 流中标记一条临时 tool_call 卡片, 后续 tool_result 会替换或保留
    clearStreaming()
    state.messages.push({
      local_id: _nextLocalId(),
      server_id: null,
      role: 'tool',
      content: '正在执行工具...',
      tool_calls: null,
      tool_call_id: String((event.data as { tool_call_id?: string }).tool_call_id ?? ''),
      status: 'streaming',
      pending_tool_name: String((event.data as { name?: string }).name ?? ''),
      pending_tool_args: (event.data as { arguments?: Record<string, unknown> }).arguments ?? null,
      created_at: new Date().toISOString(),
      display_payload: null,
    })
    return
  }
  if (event.event === 'tool_result') {
    clearStreaming()
    const data = event.data as {
      tool_call_id?: string
      name?: string
      result?: Record<string, unknown>
      error?: string
      rejected?: boolean
      reason?: string
    }
    // 找到对应的 streaming tool 行, 替换成最终内容
    const target = state.messages
      .slice()
      .reverse()
      .find((row) => row.role === 'tool' && row.tool_call_id === data.tool_call_id)
    const payload: Record<string, unknown> = {}
    if (data.result !== undefined) {
      payload.result = data.result
    }
    if (data.error !== undefined) {
      payload.error = data.error
    }
    if (data.rejected === true) {
      payload.rejected = true
      payload.reason = data.reason ?? ''
    }
    if (target !== undefined) {
      target.content = JSON.stringify(payload, null, 2)
      target.status = 'committed'
      target.pending_tool_name = String(data.name ?? target.pending_tool_name ?? '')
      target.display_payload = payload
    } else {
      state.messages.push({
        local_id: _nextLocalId(),
        server_id: null,
        role: 'tool',
        content: JSON.stringify(payload, null, 2),
        tool_calls: null,
        tool_call_id: String(data.tool_call_id ?? ''),
        status: 'committed',
        pending_tool_name: String(data.name ?? ''),
        pending_tool_args: null,
        created_at: new Date().toISOString(),
        display_payload: payload,
      })
    }
    return
  }
  if (event.event === 'pending_confirm') {
    clearStreaming()
    const data = event.data as {
      message_id?: number
      tool_call_id?: string
      name?: string
      arguments?: Record<string, unknown>
      description?: string
    }
    state.pending = {
      message_id: Number(data.message_id ?? 0),
      tool_call_id: String(data.tool_call_id ?? ''),
      name: String(data.name ?? ''),
      arguments: data.arguments ?? {},
      description: String(data.description ?? ''),
    }
    state.messages.push({
      local_id: _nextLocalId(),
      server_id: Number(data.message_id ?? 0) || null,
      role: 'tool',
      content: '(等待用户确认)',
      tool_calls: null,
      tool_call_id: String(data.tool_call_id ?? ''),
      status: 'pending_confirm',
      pending_tool_name: String(data.name ?? ''),
      pending_tool_args: data.arguments ?? null,
      created_at: new Date().toISOString(),
      display_payload: null,
    })
    return
  }
  if (event.event === 'error') {
    clearStreaming()
    const message = String((event.data as { message?: string }).message ?? '未知错误')
    state.error = message
    return
  }
  if (event.event === 'done') {
    clearStreaming()
    return
  }
}

async function _refreshFromServer(): Promise<void> {
  if (state.sessionId === null) {
    return
  }
  try {
    const response = await fetchAiSessionMessages(state.sessionId)
    state.messages = response.messages.map(_toChatRow)
    // 如果有 pending_confirm 行, 还原 pending 状态
    const pendingRow = state.messages.find((row) => row.status === 'pending_confirm')
    if (pendingRow !== undefined && pendingRow.server_id !== null) {
      state.pending = {
        message_id: pendingRow.server_id,
        tool_call_id: pendingRow.tool_call_id ?? '',
        name: pendingRow.pending_tool_name ?? '',
        arguments: pendingRow.pending_tool_args ?? {},
        description: '',
      }
    } else {
      state.pending = null
    }
  } catch (err) {
    state.error = (err as Error).message
  }
}

// ==== 对外暴露的接口 ====

export function useAiAgent() {
  return {
    state,
    open,
    close,
    toggle,
    newSession,
    loadSession,
    openWith,
    sendMessage,
    confirmPending,
    rejectPending,
    refreshRecentSessions,
    refreshCurrentSession,
    refreshConfig,
    switchModel,
    deleteSession,
    rename,
    isStreaming: computed(() => state.sending),
  }
}

function open(): void {
  state.open = true
}

function close(): void {
  state.open = false
}

function toggle(): void {
  state.open = state.open === false
}

async function newSession(): Promise<void> {
  _abortActiveStream()
  state.sessionId = null
  state.messages = []
  state.pending = null
  state.error = null
}

async function loadSession(sessionId: string, openPanel: boolean): Promise<void> {
  if (state.sending === true) {
    state.error = '模型生成中, 请稍后切换会话.'
    return
  }
  _abortActiveStream()
  state.sessionId = sessionId
  state.messages = []
  state.pending = null
  state.error = null
  if (openPanel === true) {
    state.open = true
  }
  await _refreshFromServer()
}

async function openWith(sessionId: string): Promise<void> {
  await loadSession(sessionId, true)
}

async function sendMessage(content: string): Promise<void> {
  if (state.sending === true) {
    return
  }
  const text = content.trim()
  if (text === '') {
    return
  }
  state.sending = true
  state.error = null
  try {
    const sessionId = await _ensureSession()
    // 立即把 user 行推入界面, 后端落库后通过下次刷新对齐 id
    state.messages.push({
      local_id: _nextLocalId(),
      server_id: null,
      role: 'user',
      content: text,
      tool_calls: null,
      tool_call_id: null,
      status: 'committed',
      pending_tool_name: null,
      pending_tool_args: null,
      created_at: new Date().toISOString(),
      display_payload: null,
    })
    const handle = await streamAiSendMessage(sessionId, text)
    _activeStream = handle
    await _consumeStream(handle)
  } catch (err) {
    state.error = (err as Error).message
  } finally {
    state.sending = false
    // 流结束后从后端拉一次, 确保前端 server_id 与 token 用量等字段对齐
    await _refreshFromServer()
    await refreshRecentSessions()
  }
}

async function confirmPending(): Promise<void> {
  if (state.pending === null || state.sessionId === null) {
    return
  }
  if (state.sending === true) {
    return
  }
  state.sending = true
  state.error = null
  const messageId = state.pending.message_id
  const sessionId = state.sessionId
  state.pending = null
  try {
    const handle = await streamAiToolConfirm(sessionId, {
      message_id: messageId,
      action: 'confirm',
    })
    _activeStream = handle
    await _consumeStream(handle)
  } catch (err) {
    state.error = (err as Error).message
  } finally {
    state.sending = false
    await _refreshFromServer()
    await refreshRecentSessions()
  }
}

async function rejectPending(reason: string): Promise<void> {
  if (state.pending === null || state.sessionId === null) {
    return
  }
  if (state.sending === true) {
    return
  }
  state.sending = true
  state.error = null
  const messageId = state.pending.message_id
  const sessionId = state.sessionId
  state.pending = null
  try {
    const handle = await streamAiToolConfirm(sessionId, {
      message_id: messageId,
      action: 'reject',
      reject_reason: reason,
    })
    _activeStream = handle
    await _consumeStream(handle)
  } catch (err) {
    state.error = (err as Error).message
  } finally {
    state.sending = false
    await _refreshFromServer()
    await refreshRecentSessions()
  }
}

async function refreshRecentSessions(): Promise<void> {
  state.recentLoading = true
  try {
    const response = await listAiSessions({ page: 1, page_size: 5 })
    state.recentSessions = response.sessions
  } catch (err) {
    state.error = (err as Error).message
  } finally {
    state.recentLoading = false
  }
}

async function refreshCurrentSession(): Promise<void> {
  await _refreshFromServer()
}

async function refreshConfig(): Promise<void> {
  state.modelLoading = true
  try {
    const config = await fetchAiConfig()
    state.modelId = config.effective.model
  } catch (err) {
    state.error = (err as Error).message
  } finally {
    state.modelLoading = false
  }
}

async function switchModel(modelId: AiAgentModelId): Promise<void> {
  if (state.modelSaving === true) {
    return
  }
  if (state.modelId === modelId) {
    return
  }
  state.modelSaving = true
  state.error = null
  try {
    const config = await updateAiConfig({ model: modelId })
    state.modelId = config.effective.model
  } catch (err) {
    state.error = (err as Error).message
    throw err
  } finally {
    state.modelSaving = false
  }
}

async function deleteSession(sessionId: string): Promise<void> {
  await deleteAiSession(sessionId)
  if (state.sessionId === sessionId) {
    await newSession()
  }
  await refreshRecentSessions()
}

async function rename(sessionId: string, title: string): Promise<void> {
  await renameAiSession(sessionId, title)
  await refreshRecentSessions()
}
