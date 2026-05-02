import http, { getErrorMessage } from '../../../api/http'
import type {
  AiConfigResponse,
  AiConfigUpdatePayload,
  AiSessionListResponse,
  AiSessionMessagesResponse,
  SseEvent,
  SseEventType,
  StreamHandle,
} from '../types'

// ==== REST API ====

export async function createAiSession(): Promise<{ session_id: string }> {
  const { data } = await http.post<{ session_id: string }>('/api/ai-agent/sessions')
  return data
}

export async function listAiSessions(params: {
  keyword?: string
  page?: number
  page_size?: number
}): Promise<AiSessionListResponse> {
  const { data } = await http.get<AiSessionListResponse>('/api/ai-agent/sessions', {
    params: {
      keyword: params.keyword ?? '',
      page: params.page ?? 1,
      page_size: params.page_size ?? 20,
    },
  })
  return data
}

export async function fetchAiSessionMessages(sessionId: string): Promise<AiSessionMessagesResponse> {
  const { data } = await http.get<AiSessionMessagesResponse>(
    `/api/ai-agent/sessions/${encodeURIComponent(sessionId)}/messages`,
  )
  return data
}

export async function renameAiSession(
  sessionId: string,
  title: string,
): Promise<{ affected: number; title: string }> {
  const { data } = await http.put<{ affected: number; title: string }>(
    `/api/ai-agent/sessions/${encodeURIComponent(sessionId)}/title`,
    { title },
  )
  return data
}

export async function deleteAiSession(sessionId: string): Promise<{ affected: number }> {
  const { data } = await http.delete<{ affected: number }>(
    `/api/ai-agent/sessions/${encodeURIComponent(sessionId)}`,
  )
  return data
}

export async function fetchAiConfig(): Promise<AiConfigResponse> {
  const { data } = await http.get<AiConfigResponse>('/api/ai-agent/config')
  return data
}

export async function updateAiConfig(payload: AiConfigUpdatePayload): Promise<AiConfigResponse> {
  // axios 会过滤 undefined, 但保留 null - 而后端 None 表示"不修改". 所以我们只送 != undefined 的字段.
  const body: Record<string, unknown> = {}
  if (payload.api_key !== undefined) {
    body.api_key = payload.api_key
  }
  if (payload.base_url !== undefined) {
    body.base_url = payload.base_url
  }
  if (payload.model !== undefined) {
    body.model = payload.model
  }
  if (payload.timeout_s !== undefined) {
    body.timeout_s = payload.timeout_s
  }
  const { data } = await http.put<AiConfigResponse>('/api/ai-agent/config', body)
  return data
}

// ==== SSE 流式调用 ====

// fetch + ReadableStream 实现 SSE 解析, 替代 EventSource (后者只支持 GET)
async function* parseSseStream(
  response: Response,
  signal: AbortSignal,
): AsyncGenerator<SseEvent, void, unknown> {
  if (response.body === null) {
    throw new Error('响应体为空, 无法读取流')
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  // abort 时主动 cancel reader, 让正在阻塞的 read() 立即解除, 不必等下一个 chunk.
  const onAbort = () => {
    reader.cancel().catch(() => {
      // 忽略 cancel 错误.
    })
  }
  if (signal.aborted === true) {
    onAbort()
  } else {
    signal.addEventListener('abort', onAbort, { once: true })
  }

  try {
    while (signal.aborted === false) {
      const { done, value } = await reader.read()
      if (done === true) {
        break
      }
      buffer += decoder.decode(value, { stream: true })
      // SSE 事件以两个换行分隔
      while (true) {
        const sepIndex = buffer.indexOf('\n\n')
        if (sepIndex < 0) {
          break
        }
        const block = buffer.slice(0, sepIndex)
        buffer = buffer.slice(sepIndex + 2)
        const parsed = parseSseBlock(block)
        if (parsed !== null) {
          yield parsed
        }
      }
    }
  } finally {
    signal.removeEventListener('abort', onAbort)
    try {
      await reader.cancel()
    } catch (_err) {
      // 忽略取消错误
    }
  }
}

function parseSseBlock(block: string): SseEvent | null {
  const lines = block.split('\n')
  let event: SseEventType | null = null
  let dataText = ''
  for (const rawLine of lines) {
    const line = rawLine.trimEnd()
    if (line === '' || line.startsWith(':') === true) {
      continue
    }
    if (line.startsWith('event:') === true) {
      event = line.slice('event:'.length).trim() as SseEventType
    } else if (line.startsWith('data:') === true) {
      const piece = line.slice('data:'.length).trimStart()
      dataText = dataText === '' ? piece : `${dataText}\n${piece}`
    }
  }
  if (event === null) {
    return null
  }
  let data: Record<string, unknown>
  try {
    data = dataText === '' ? {} : (JSON.parse(dataText) as Record<string, unknown>)
  } catch (_err) {
    data = { _raw: dataText }
  }
  return { event, data }
}

async function startSseRequest(
  url: string,
  payload: Record<string, unknown>,
): Promise<StreamHandle> {
  const controller = new AbortController()
  let response: Response
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    })
  } catch (err) {
    throw new Error(getErrorMessage(err))
  }
  if (response.ok === false) {
    let detailText = ''
    try {
      const errBody = await response.json()
      detailText = (errBody as { detail?: string })?.detail ?? ''
    } catch (_err) {
      detailText = ''
    }
    throw new Error(detailText !== '' ? detailText : `请求失败 (${response.status})`)
  }
  return {
    events: parseSseStream(response, controller.signal),
    abort: () => controller.abort(),
  }
}

export async function streamAiSendMessage(
  sessionId: string,
  content: string,
): Promise<StreamHandle> {
  return startSseRequest(
    `/api/ai-agent/sessions/${encodeURIComponent(sessionId)}/messages`,
    { content },
  )
}

export async function streamAiToolConfirm(
  sessionId: string,
  payload: {
    message_id: number
    action: 'approve' | 'reject' | 'edit'
    reject_reason?: string
    edited_arguments?: Record<string, unknown>
  },
): Promise<StreamHandle> {
  return startSseRequest(
    `/api/ai-agent/sessions/${encodeURIComponent(sessionId)}/tool-confirm`,
    payload,
  )
}
