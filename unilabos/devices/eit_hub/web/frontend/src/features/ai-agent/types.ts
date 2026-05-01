export const AI_AGENT_MODEL_OPTIONS = [
  { label: '快速', value: 'deepseek-v4-flash' },
  { label: '推理', value: 'deepseek-v4-pro' },
] as const

export type AiAgentModelId = (typeof AI_AGENT_MODEL_OPTIONS)[number]['value']

export interface AiAgentModelOption {
  label: string
  value: string
}

export type AiMessageRole = 'system' | 'user' | 'assistant' | 'tool'
export type AiMessageStatus = 'committed' | 'pending_confirm' | 'rejected'

export interface AiToolCall {
  id: string
  name: string
  arguments_text: string
}

export interface AiMessage {
  id: number
  session_id: string
  session_title: string
  role: AiMessageRole
  content: string | null
  tool_calls: AiToolCall[] | null
  tool_call_id: string | null
  status: AiMessageStatus
  pending_tool_name: string | null
  pending_tool_args: Record<string, unknown> | null
  prompt_tokens: number | null
  completion_tokens: number | null
  created_at: string
}

export interface AiSessionSummary {
  session_id: string
  title: string
  started_at: string
  last_at: string
  user_turns: number
  message_count: number
}

export interface AiSessionListResponse {
  sessions: AiSessionSummary[]
  total: number
  page: number
  page_size: number
}

export interface AiSessionMessagesResponse {
  messages: AiMessage[]
  total: number
}

export type SseEventType =
  | 'token'
  | 'tool_call'
  | 'tool_result'
  | 'pending_confirm'
  | 'done'
  | 'error'

export interface SseEvent {
  event: SseEventType
  data: Record<string, unknown>
}

export interface AiConfigSource {
  api_key: 'ui' | 'env' | 'none'
  base_url: 'ui' | 'env' | 'default'
  model: 'ui' | 'env' | 'default'
  timeout_s: 'ui' | 'env' | 'default'
}

export interface AiConfigPart {
  has_api_key: boolean
  api_key_preview: string | null
  base_url: string | null
  model: string | null
  timeout_s: number | null
}

export interface AiConfigEffective {
  has_api_key: boolean
  api_key_preview: string | null
  base_url: string
  model: string
  timeout_s: number
  source: AiConfigSource
}

export interface AiConfigDefaults {
  base_url: string
  model: string
  timeout_s: number
}

export interface AiConfigResponse {
  ui: AiConfigPart
  env: AiConfigPart
  effective: AiConfigEffective
  defaults: AiConfigDefaults
  model_options?: AiAgentModelOption[]
}

export interface AiConfigUpdatePayload {
  // null 表示不修改; "" 表示清除该字段 (回退 env / 默认值)
  api_key?: string | null
  base_url?: string | null
  model?: string | null
  timeout_s?: number | null
}

export interface StreamHandle {
  events: AsyncGenerator<SseEvent, void, unknown>
  abort: () => void
}
