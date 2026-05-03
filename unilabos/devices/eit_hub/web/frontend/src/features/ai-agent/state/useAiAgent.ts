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
  type AiBaseModel,
  type AiMessage,
  type AiPhase,
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
  // assistant 行专用: 流式中段的阶段提示, 仅在 streaming 状态下有值
  phase: AiPhase | null
  // assistant 流式 phase=tool_calling 时携带的具体工具名, 用于状态行展示 "正在调用 {name}"
  phase_tool_name: string | null
  // phase 关联工具的权限分类 (read/control), 决定状态点颜色 (read 橙, control 紫)
  phase_kind: 'read' | 'control' | null
  // tool 行专用: 工具权限分类, 来自 tool_call 事件的 kind 字段
  tool_kind: 'read' | 'control' | null
  // tool 行专用: tool_result 含 error 字段时为 true, 用于状态行的红色错误指示
  error_state: boolean
  // 行级 UI 状态: 是否展开参数/结果详情 (仅 tool 行可点击切换)
  expanded: boolean
}

interface AiAgentState {
  open: boolean
  pinned: boolean
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
  baseModels: AiBaseModel[]
  activeBaseModelId: string
  activeThinkingLevelId: string | null
  modelLoading: boolean
  modelSaving: boolean
}

// 图钉状态持久化键名, 跨刷新保留用户的"始终悬浮"偏好
const PIN_STORAGE_KEY = 'eit-ai-agent-pinned'

function _readPinned(): boolean {
  // 隐私模式 / SSR 下 localStorage 可能不可用, 安全降级为未钉住
  if (typeof window === 'undefined') {
    return false
  }
  try {
    return window.localStorage.getItem(PIN_STORAGE_KEY) === '1'
  } catch (_err) {
    return false
  }
}

const state = reactive<AiAgentState>({
  open: false,
  pinned: _readPinned(),
  sessionId: null,
  messages: [],
  sending: false,
  pending: null,
  error: null,
  recentSessions: [],
  recentLoading: false,
  baseModels: [],
  activeBaseModelId: '',
  activeThinkingLevelId: null,
  modelLoading: false,
  modelSaving: false,
})

let _localCounter = -1
let _activeStream: StreamHandle | null = null
let _streamStoppedByUser = false

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

function _handleStreamError(err: unknown): void {
  if (_streamStoppedByUser === true) {
    return
  }
  state.error = (err as Error).message
}

// 历史 tool 行如果未保存 pending_tool_name (老数据), 通过 tool_call_id 反查同会话内的 assistant.tool_calls 取 name 回填.
function _backfillToolNames(rows: ChatMessageRow[]): void {
  const idToName: Record<string, string> = {}
  for (const row of rows) {
    if (row.role !== 'assistant' || row.tool_calls === null) {
      continue
    }
    for (const call of row.tool_calls) {
      if (call.id !== '' && call.name !== '') {
        idToName[call.id] = call.name
      }
    }
  }
  for (const row of rows) {
    if (row.role !== 'tool') {
      continue
    }
    const hasName = row.pending_tool_name !== null && row.pending_tool_name !== ''
    if (hasName === true) {
      continue
    }
    const callId = row.tool_call_id ?? ''
    if (callId !== '' && idToName[callId] !== undefined) {
      row.pending_tool_name = idToName[callId]
    }
  }
}

function _newAssistantStreamingRow(): ChatMessageRow {
  // 流中临时占位的 assistant 行, 用于承接 phase / token 事件.
  return {
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
    phase: null,
    phase_tool_name: null,
    phase_kind: null,
    tool_kind: null,
    error_state: false,
    expanded: false,
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
  // 历史消息从后端加载时, payload.error 决定状态点是否显示为红色错误.
  const hasError = payload !== null && Object.prototype.hasOwnProperty.call(payload, 'error')
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
    phase: null,
    phase_tool_name: null,
    phase_kind: null,
    tool_kind: null,
    error_state: hasError,
    expanded: false,
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
      // 流式 assistant 行被一个非 token 事件 (tool_call / pending_confirm / error / done)
      // 切断时, 立即落库并清掉 phase 徽章, 否则空内容行会卡住 "正在思考..." / "正在调用 X" 展示.
      if (streamingAssistant !== null && streamingAssistant.status === 'streaming') {
        streamingAssistant.status = 'committed'
        streamingAssistant.phase = null
        streamingAssistant.phase_tool_name = null
        streamingAssistant.phase_kind = null
      }
      streamingAssistant = null
    })
    if (state.error !== null) {
      // error 事件已在 handler 中设置, 主循环可继续等 done 收尾
    }
  }
  // 流自然结束, 清理引用 (handle 已耗尽)
  _activeStream = null
  // 若结束时还有 streaming 状态行, 把它转为 committed (后端落库时已生成正式 id, 但前端无从感知,
  // 等下一次 fetchAiSessionMessages 刷新时对齐). 同时清掉 phase 防止徽章残留.
  // 使用断言绕过 TS 在 for+closure 场景下的过度收窄推断 (将类型推断为 never).
  const finalAssistant = streamingAssistant as ChatMessageRow | null
  if (finalAssistant !== null && finalAssistant.status === 'streaming') {
    finalAssistant.status = 'committed'
    finalAssistant.phase = null
    finalAssistant.phase_tool_name = null
    finalAssistant.phase_kind = null
  }
}

function _handleSseEvent(
  event: SseEvent,
  setStreaming: (row: ChatMessageRow) => void,
  clearStreaming: () => void,
): void {
  if (event.event === 'phase') {
    // 模型流式中段的阶段提示, 把 phase 挂在当前流式 assistant 行上.
    // 若无现有流式行 (例如 thinking 块在任何 token 之前到达), 先创建一行空 assistant.
    const phaseData = event.data as { phase?: string; tool_name?: string; kind?: string }
    const phase = String(phaseData.phase ?? '')
    if (phase !== 'thinking' && phase !== 'tool_calling') {
      return
    }
    const phaseToolName = phaseData.tool_name ? String(phaseData.tool_name) : null
    const rawKind = phaseData.kind ? String(phaseData.kind) : ''
    const phaseKind = rawKind === 'read' || rawKind === 'control' ? rawKind : null
    let last = state.messages[state.messages.length - 1]
    if (last === undefined || last.role !== 'assistant' || last.status !== 'streaming') {
      last = _newAssistantStreamingRow()
      state.messages.push(last)
      setStreaming(last)
    }
    last.phase = phase
    last.phase_tool_name = phaseToolName
    last.phase_kind = phaseKind
    return
  }
  if (event.event === 'token') {
    const text = String((event.data as { text?: string }).text ?? '')
    let last = state.messages[state.messages.length - 1]
    if (last === undefined || last.role !== 'assistant' || last.status !== 'streaming') {
      last = _newAssistantStreamingRow()
      state.messages.push(last)
      setStreaming(last)
    }
    last.content += text
    // 首个文本到达即代表进入 responding 阶段, 清除上一阶段 (thinking / tool_calling) 徽章.
    last.phase = null
    last.phase_tool_name = null
    last.phase_kind = null
    return
  }
  if (event.event === 'tool_call') {
    // 流中标记一条临时 tool_call 行, 后续 tool_result 会替换或保留
    clearStreaming()
    const data = event.data as { tool_call_id?: string; name?: string; arguments?: Record<string, unknown>; kind?: string }
    const rawKind = data.kind ? String(data.kind) : ''
    const toolKind = rawKind === 'read' || rawKind === 'control' ? rawKind : null
    state.messages.push({
      local_id: _nextLocalId(),
      server_id: null,
      role: 'tool',
      content: '正在执行工具...',
      tool_calls: null,
      tool_call_id: String(data.tool_call_id ?? ''),
      status: 'streaming',
      pending_tool_name: String(data.name ?? ''),
      pending_tool_args: data.arguments ?? null,
      created_at: new Date().toISOString(),
      display_payload: null,
      phase: null,
      phase_tool_name: null,
      phase_kind: null,
      tool_kind: toolKind,
      error_state: false,
      expanded: false,
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
    // 工具结果含 error 或 rejected 时, 状态点改为红色; 仅有 result 时为成功绿色.
    const errorState = data.error !== undefined || data.rejected === true
    if (target !== undefined) {
      target.content = JSON.stringify(payload, null, 2)
      target.status = data.rejected === true ? 'rejected' : 'committed'
      target.pending_tool_name = String(data.name ?? target.pending_tool_name ?? '')
      target.display_payload = payload
      target.error_state = errorState
    } else {
      state.messages.push({
        local_id: _nextLocalId(),
        server_id: null,
        role: 'tool',
        content: JSON.stringify(payload, null, 2),
        tool_calls: null,
        tool_call_id: String(data.tool_call_id ?? ''),
        status: data.rejected === true ? 'rejected' : 'committed',
        pending_tool_name: String(data.name ?? ''),
        pending_tool_args: null,
        created_at: new Date().toISOString(),
        display_payload: payload,
        phase: null,
        phase_tool_name: null,
        phase_kind: null,
        tool_kind: null,
        error_state: errorState,
        expanded: false,
      })
    }
    // AI 工具改写了任务编辑或上料表 Excel 后, 通知相关视图自动刷新.
    const writeKindByTool: Record<string, string> = {
      save_reaction_template: 'reaction_template',
      submit_reaction_template: 'reaction_template',
      save_batch_in_template: 'batch_in_template',
      run_resource_check: 'batch_in_template',
      print_reagent_labels: 'batch_in_template',
      print_batch_in_table: 'batch_in_template',
    }
    const writeKind = writeKindByTool[String(data.name ?? '')]
    if (
      writeKind !== undefined
      && data.error === undefined
      && data.rejected !== true
      && typeof window !== 'undefined'
    ) {
      window.dispatchEvent(
        new CustomEvent('eit-hub:reload-task-editor', { detail: { kind: writeKind } }),
      )
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
      phase: null,
      phase_tool_name: null,
      phase_kind: null,
      // 写类工具默认 control, pending_confirm 仅出现在 control 流程中, 直接固化分类.
      tool_kind: 'control',
      error_state: false,
      expanded: false,
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
    _backfillToolNames(state.messages)
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
    setPinned,
    togglePin,
    newSession,
    loadSession,
    openWith,
    sendMessage,
    stopStreaming,
    confirmPending,
    rejectPending,
    refreshRecentSessions,
    refreshCurrentSession,
    refreshConfig,
    switchBaseModel,
    switchThinkingLevel,
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

function setPinned(value: boolean): void {
  state.pinned = value
  if (typeof window === 'undefined') {
    return
  }
  try {
    window.localStorage.setItem(PIN_STORAGE_KEY, value === true ? '1' : '0')
  } catch (_err) {
    // 隐私模式下 localStorage 写入失败, 内存状态仍然有效
  }
}

function togglePin(): void {
  setPinned(state.pinned === false)
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
      phase: null,
      phase_tool_name: null,
      phase_kind: null,
      tool_kind: null,
      error_state: false,
      expanded: false,
    })
    const handle = await streamAiSendMessage(sessionId, text)
    _activeStream = handle
    if (_streamStoppedByUser === true) {
      _abortActiveStream()
      return
    }
    await _consumeStream(handle)
  } catch (err) {
    _handleStreamError(err)
  } finally {
    state.sending = false
    _streamStoppedByUser = false
    // 流结束后从后端拉一次, 确保前端 server_id 与 token 用量等字段对齐
    await _refreshFromServer()
    await refreshRecentSessions()
  }
}

function stopStreaming(): void {
  if (state.sending === false) {
    return
  }
  _streamStoppedByUser = true
  _abortActiveStream()
  // 立即把 UI 切回 可输入 状态, 不等 _consumeStream 的 finally 走完.
  // _consumeStream 在 abort 后仍会异步退出循环, 但 sending 已置 false 不再阻塞输入.
  state.sending = false
  // 把仍处于 streaming 状态的 assistant 行落定, 防止 UI 一直转圈.
  for (const row of state.messages) {
    if (row.status === 'streaming') {
      row.status = 'committed'
    }
  }
}

async function confirmPending(editedArguments?: Record<string, unknown>): Promise<void> {
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
      action: editedArguments !== undefined ? 'edit' : 'approve',
      edited_arguments: editedArguments,
    })
    _activeStream = handle
    if (_streamStoppedByUser === true) {
      _abortActiveStream()
      return
    }
    await _consumeStream(handle)
  } catch (err) {
    _handleStreamError(err)
  } finally {
    state.sending = false
    _streamStoppedByUser = false
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
    if (_streamStoppedByUser === true) {
      _abortActiveStream()
      return
    }
    await _consumeStream(handle)
  } catch (err) {
    _handleStreamError(err)
  } finally {
    state.sending = false
    _streamStoppedByUser = false
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
    state.baseModels = config.base_models
    state.activeBaseModelId = config.active_base_model_id
    state.activeThinkingLevelId = config.active_thinking_level_id
  } catch (err) {
    state.error = (err as Error).message
  } finally {
    state.modelLoading = false
  }
}

async function switchBaseModel(baseModelId: string): Promise<void> {
  if (state.modelSaving === true) {
    return
  }
  if (state.activeBaseModelId === baseModelId) {
    return
  }
  state.modelSaving = true
  state.error = null
  try {
    // 切左按钮时同时清掉 thinking_level (传 null), 让后端按新 base_model 的 default_level_id 兜底.
    const config = await updateAiConfig({
      active_base_model_id: baseModelId,
      active_thinking_level_id: null,
    })
    state.baseModels = config.base_models
    state.activeBaseModelId = config.active_base_model_id
    state.activeThinkingLevelId = config.active_thinking_level_id
  } catch (err) {
    state.error = (err as Error).message
    throw err
  } finally {
    state.modelSaving = false
  }
}

async function switchThinkingLevel(levelId: string): Promise<void> {
  if (state.modelSaving === true) {
    return
  }
  if (state.activeThinkingLevelId === levelId) {
    return
  }
  state.modelSaving = true
  state.error = null
  try {
    const config = await updateAiConfig({ active_thinking_level_id: levelId })
    state.baseModels = config.base_models
    state.activeBaseModelId = config.active_base_model_id
    state.activeThinkingLevelId = config.active_thinking_level_id
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
