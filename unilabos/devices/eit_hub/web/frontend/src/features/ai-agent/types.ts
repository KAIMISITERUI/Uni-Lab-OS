export const AI_AGENT_PROVIDER_OPTIONS = [
  { label: 'DeepSeek', value: 'deepseek' },
  { label: 'OpenAI', value: 'openai' },
  { label: 'Anthropic', value: 'anthropic' },
] as const

export type AiAgentProviderId = (typeof AI_AGENT_PROVIDER_OPTIONS)[number]['value']

export interface AiAgentProviderOption {
  label: string
  value: AiAgentProviderId
}

// 下拉左按钮: 一项 base_model 决定 provider 与实际 API 模型名.
// 下拉右按钮: 一档 thinking_level 决定 reasoning_effort 或 thinking.budget_tokens.
export interface AiThinkingLevel {
  id: string
  label: string
}

export interface AiBaseModel {
  id: string
  label: string
  provider_id: AiAgentProviderId
  thinking_levels: AiThinkingLevel[]
  default_level_id: string | null
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
  | 'phase'
  | 'tool_call'
  | 'tool_result'
  | 'pending_confirm'
  | 'done'
  | 'error'

// 模型流式中段的阶段标识, 仅用于驱动 assistant 气泡内联的动态提示徽章.
export type AiPhase = 'thinking' | 'tool_calling'

export interface SseEvent {
  event: SseEventType
  data: Record<string, unknown>
}

export type ConfigSourceName = 'ui' | 'env' | 'default' | 'none'

export interface AiProviderCredentialsPart {
  has_api_key: boolean
  api_key_preview: string | null
  base_url: string | null
  timeout_s: number | null
}

export interface AiProviderCredentialsEffective {
  has_api_key: boolean
  api_key_preview: string | null
  base_url: string
  timeout_s: number
  source: {
    api_key: ConfigSourceName
    base_url: ConfigSourceName
    timeout_s: ConfigSourceName
  }
}

export interface AiProviderCredentialsDefaults {
  base_url: string
  timeout_s: number
}

export interface AiProviderCredentialsResponse {
  label: string
  ui: AiProviderCredentialsPart
  env: AiProviderCredentialsPart
  effective: AiProviderCredentialsEffective
  defaults: AiProviderCredentialsDefaults
}

export interface AiConfigResponse {
  active_base_model_id: string
  active_thinking_level_id: string | null
  active_source: {
    base_model: ConfigSourceName
    thinking_level: ConfigSourceName
  }
  base_models: AiBaseModel[]
  provider_options: AiAgentProviderOption[]
  providers: Record<AiAgentProviderId, AiProviderCredentialsResponse>
}

// 单个 provider 凭证更新片段; 字段缺省 = 不修改, null/"" = 清除.
export interface AiProviderCredentialsUpdate {
  api_key?: string | null
  base_url?: string | null
  timeout_s?: number | null
}

export interface AiConfigUpdatePayload {
  active_base_model_id?: string | null
  active_thinking_level_id?: string | null
  providers?: Partial<Record<AiAgentProviderId, AiProviderCredentialsUpdate>>
}

export interface StreamHandle {
  events: AsyncGenerator<SseEvent, void, unknown>
  abort: () => void
}

// ask_user_choice 工具相关类型
// 后端 ChoiceOption 模型: {label, value, description?}
export interface AiChoiceOption {
  label: string
  value: string
  description?: string | null
}

// AI 调 ask_user_choice 时传入的参数, 不含 selected
export interface AskUserChoiceArgs {
  question: string
  options: AiChoiceOption[]
  multi: boolean
  allow_other: boolean
  allow_skip: boolean
  selected?: unknown
}
