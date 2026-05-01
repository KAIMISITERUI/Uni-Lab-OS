<script setup lang="ts">
// AI 助手历史页: 左侧会话列表 + 右侧详情. 复用 .panel / .two-column 与 TaskHistoryView 的布局模式.
import { computed, nextTick, onActivated, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ChatDotRound,
  Delete,
  EditPen,
  Loading,
  Plus,
  Search,
  Setting,
} from '@element-plus/icons-vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import {
  fetchAiConfig,
  listAiSessions,
  updateAiConfig,
} from '../api/client'
import {
  AI_AGENT_MODEL_OPTIONS,
  type AiAgentModelOption,
  type AiConfigResponse,
  type AiSessionSummary,
} from '../types'
import { useAiAgent } from '../state/useAiAgent'

const ai = useAiAgent()

const sessions = ref<AiSessionSummary[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const keyword = ref('')
const listLoading = ref(false)

const selectedSessionId = ref<string | null>(null)
const detailLoading = ref(false)
const historyInputText = ref('')
const detailScroll = ref<HTMLDivElement | null>(null)

marked.setOptions({ gfm: true, breaks: true })

function renderMarkdown(content: string): string {
  if ((content || '').trim() === '') {
    return ''
  }
  const html = marked.parse(content, { async: false }) as string
  return DOMPurify.sanitize(html)
}

const visibleMessages = computed(() => {
  if (selectedSessionId.value === null || ai.state.sessionId !== selectedSessionId.value) {
    return []
  }
  return ai.state.messages.filter((row) => row.role !== 'system')
})

const selectedSummary = computed<AiSessionSummary | null>(() => {
  if (selectedSessionId.value === null) {
    return null
  }
  return sessions.value.find((row) => row.session_id === selectedSessionId.value) ?? null
})

async function scrollDetailToBottom(): Promise<void> {
  await nextTick()
  if (detailScroll.value !== null) {
    detailScroll.value.scrollTop = detailScroll.value.scrollHeight
  }
}

async function loadSessions(): Promise<void> {
  listLoading.value = true
  try {
    const response = await listAiSessions({
      keyword: keyword.value,
      page: page.value,
      page_size: pageSize.value,
    })
    sessions.value = response.sessions
    total.value = response.total
  } catch (err) {
    ElMessage.error((err as Error).message)
  } finally {
    listLoading.value = false
  }
}

async function loadDetail(sessionId: string): Promise<void> {
  detailLoading.value = true
  try {
    await ai.loadSession(sessionId, false)
  } catch (err) {
    ElMessage.error((err as Error).message)
  } finally {
    detailLoading.value = false
    void scrollDetailToBottom()
  }
}

async function onPickSession(sessionId: string) {
  if (ai.state.sending === true) {
    ElMessage.warning('模型生成中, 请稍后切换会话.')
    return
  }
  selectedSessionId.value = sessionId
  await loadDetail(sessionId)
}

function onSearch() {
  page.value = 1
  void loadSessions()
}

function onPageChange(value: number) {
  page.value = value
  void loadSessions()
}

async function onRename(session: AiSessionSummary) {
  let title = session.title
  try {
    const result = await ElMessageBox.prompt('请输入新的会话标题:', '重命名会话', {
      inputValue: session.title,
      confirmButtonText: '保存',
      cancelButtonText: '取消',
    })
    title = (result.value || '').trim()
  } catch (_err) {
    return
  }
  if (title === '' || title === session.title) {
    return
  }
  try {
    await ai.rename(session.session_id, title)
    ElMessage.success('已重命名')
    await loadSessions()
  } catch (err) {
    ElMessage.error((err as Error).message)
  }
}

async function onDelete(session: AiSessionSummary) {
  try {
    await ElMessageBox.confirm(`确定删除会话 "${session.title}" ? 删除后不可恢复.`, '删除会话', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch (_err) {
    return
  }
  try {
    await ai.deleteSession(session.session_id)
    ElMessage.success('已删除')
    if (selectedSessionId.value === session.session_id) {
      selectedSessionId.value = null
    }
    await loadSessions()
  } catch (err) {
    ElMessage.error((err as Error).message)
  }
}

async function onContinueInLauncher(sessionId: string) {
  if (ai.state.sending === true) {
    ElMessage.warning('模型生成中, 请稍后切换会话.')
    return
  }
  await ai.openWith(sessionId)
}

async function onNewSession() {
  await ai.newSession()
  ai.open()
}

function formatTime(text: string | null): string {
  if (text === null || text === '') {
    return ''
  }
  try {
    return new Date(text).toLocaleString('zh-CN', { hour12: false })
  } catch (_err) {
    return text
  }
}

function parseToolPayload(content: string | null): string {
  if (content === null) {
    return ''
  }
  try {
    return JSON.stringify(JSON.parse(content), null, 2)
  } catch (_err) {
    return content
  }
}

async function onSendInHistory(): Promise<void> {
  if (selectedSessionId.value === null) {
    return
  }
  const text = historyInputText.value.trim()
  if (text === '') {
    return
  }
  if (ai.state.sessionId !== selectedSessionId.value) {
    await loadDetail(selectedSessionId.value)
  }
  historyInputText.value = ''
  await ai.sendMessage(text)
  await loadSessions()
  await scrollDetailToBottom()
}

function onHistoryKeyDown(event: KeyboardEvent): void {
  if (event.key === 'Enter' && event.shiftKey === false && event.isComposing === false) {
    event.preventDefault()
    void onSendInHistory()
  }
}

async function onConfirmPendingInHistory(): Promise<void> {
  await ai.confirmPending()
  await loadSessions()
  await scrollDetailToBottom()
}

async function onRejectPendingInHistory(): Promise<void> {
  let reason = ''
  try {
    const result = await ElMessageBox.prompt('请说明拒绝原因 (可空):', '拒绝执行', {
      inputType: 'textarea',
      confirmButtonText: '提交拒绝',
      cancelButtonText: '取消',
      inputPlaceholder: '比如: 当前信息不足, 暂不执行.',
    })
    reason = (result.value || '').trim()
  } catch (_err) {
    return
  }
  await ai.rejectPending(reason)
  await loadSessions()
  await scrollDetailToBottom()
}

onActivated(() => {
  void loadSessions()
})

watch(
  () => ai.state.messages.length,
  () => {
    void scrollDetailToBottom()
  },
)

watch(
  () => ai.state.messages[ai.state.messages.length - 1]?.content,
  () => {
    void scrollDetailToBottom()
  },
)

void loadSessions()

// ==== 配置 dialog ====

const settingsOpen = ref(false)
const settingsLoading = ref(false)
const settingsSaving = ref(false)
const settingsConfig = ref<AiConfigResponse | null>(null)

interface SettingsForm {
  // 受控输入框, 字符串以保留空字符串语义 (空字符串=清除字段)
  api_key: string
  base_url: string
  model: string
  timeout_s: string
  // 标记 api_key 是否被用户修改过, 未修改则不发送 (避免脱敏预览覆盖真实密钥)
  api_key_dirty: boolean
}

const settingsForm = reactive<SettingsForm>({
  api_key: '',
  base_url: '',
  model: '',
  timeout_s: '',
  api_key_dirty: false,
})

function getConfigModelOptions(config: AiConfigResponse | null): AiAgentModelOption[] {
  if (config !== null && config.model_options !== undefined && config.model_options.length > 0) {
    return config.model_options
  }
  return AI_AGENT_MODEL_OPTIONS.map((item) => ({ label: item.label, value: item.value }))
}

function normalizeConfigModel(value: string | null | undefined, config: AiConfigResponse | null): string {
  const options = getConfigModelOptions(config)
  const matched = options.find((item) => item.value === value)
  if (matched !== undefined) {
    return matched.value
  }
  return options[0]?.value ?? 'deepseek-v4-flash'
}

function modelDisplayName(modelId: string): string {
  const option = getConfigModelOptions(settingsConfig.value).find((item) => item.value === modelId)
  if (option === undefined) {
    return modelId
  }
  return `${option.label} (${option.value})`
}

function _resetSettingsForm(config: AiConfigResponse): void {
  settingsForm.api_key = config.ui.api_key_preview ?? ''
  settingsForm.base_url = config.ui.base_url ?? ''
  settingsForm.model = normalizeConfigModel(config.ui.model ?? config.effective.model, config)
  settingsForm.timeout_s =
    config.ui.timeout_s !== null && config.ui.timeout_s !== undefined
      ? String(config.ui.timeout_s)
      : ''
  settingsForm.api_key_dirty = false
}

async function onOpenSettings() {
  settingsOpen.value = true
  settingsLoading.value = true
  try {
    const config = await fetchAiConfig()
    settingsConfig.value = config
    _resetSettingsForm(config)
  } catch (err) {
    ElMessage.error((err as Error).message)
  } finally {
    settingsLoading.value = false
  }
}

async function onSaveSettings() {
  if (settingsConfig.value === null) {
    return
  }
  settingsSaving.value = true
  try {
    const payload: { api_key?: string; base_url?: string; model?: string; timeout_s?: number | null } = {}
    if (settingsForm.api_key_dirty === true) {
      payload.api_key = settingsForm.api_key.trim()
    }
    payload.base_url = settingsForm.base_url.trim()
    payload.model = normalizeConfigModel(settingsForm.model, settingsConfig.value)
    const timeoutText = settingsForm.timeout_s.trim()
    if (timeoutText === '') {
      payload.timeout_s = null
    } else {
      const parsed = Number(timeoutText)
      if (Number.isFinite(parsed) === false || parsed <= 0) {
        ElMessage.error('超时秒必须为正数, 或留空表示使用默认 / env 值.')
        settingsSaving.value = false
        return
      }
      payload.timeout_s = parsed
    }
    const updated = await updateAiConfig(payload)
    settingsConfig.value = updated
    _resetSettingsForm(updated)
    await ai.refreshConfig()
    ElMessage.success('配置已保存, 下一次对话生效.')
  } catch (err) {
    ElMessage.error((err as Error).message)
  } finally {
    settingsSaving.value = false
  }
}

async function onClearApiKey() {
  // 显式清除 UI 设置的 api_key, 回退环境变量
  settingsForm.api_key = ''
  settingsForm.api_key_dirty = true
}

function onApiKeyInput() {
  settingsForm.api_key_dirty = true
}

function sourceLabel(source: 'ui' | 'env' | 'default' | 'none'): string {
  if (source === 'ui') {
    return 'UI 设置'
  }
  if (source === 'env') {
    return '环境变量'
  }
  if (source === 'default') {
    return '默认值'
  }
  return '未设置'
}

function sourceTagType(source: 'ui' | 'env' | 'default' | 'none'): string {
  if (source === 'ui') {
    return 'success'
  }
  if (source === 'env') {
    return 'warning'
  }
  if (source === 'none') {
    return 'danger'
  }
  return 'info'
}
</script>

<template>
  <div class="view-stack">
    <div class="panel">
      <div class="panel-title">
        <h2>AI 助手对话历史</h2>
        <div class="button-row">
          <el-input
            v-model="keyword"
            placeholder="按标题搜索..."
            clearable
            class="ai-history-search"
            @keyup.enter="onSearch"
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
          <el-button type="primary" @click="onSearch">搜索</el-button>
          <el-button :icon="Plus" @click="onNewSession">新建会话</el-button>
          <el-button :icon="Setting" @click="onOpenSettings">设置</el-button>
        </div>
      </div>

      <div class="two-column">
        <!-- 左侧: 会话列表 -->
        <div class="ai-history-list">
          <div v-if="listLoading === true" class="ai-history-empty">
            <el-icon class="is-loading"><Loading /></el-icon>
            加载中...
          </div>
          <div v-else-if="sessions.length === 0" class="ai-history-empty">
            <el-icon><ChatDotRound /></el-icon>
            <span>暂无对话</span>
          </div>
          <div
            v-for="session in sessions"
            :key="session.session_id"
            class="ai-history-item"
            :class="{ 'ai-history-item-active': session.session_id === selectedSessionId }"
            @click="onPickSession(session.session_id)"
          >
            <div class="ai-history-item-row">
              <span class="ai-history-item-name">{{ session.title }}</span>
              <span class="ai-history-item-count">{{ session.user_turns }} 轮 · {{ session.message_count }} 条</span>
            </div>
            <div class="ai-history-item-time">{{ formatTime(session.last_at) }}</div>
            <div class="ai-history-item-actions" @click.stop>
              <el-button text size="small" :icon="EditPen" @click="onRename(session)">重命名</el-button>
              <el-button text size="small" :icon="Delete" type="danger" @click="onDelete(session)">删除</el-button>
            </div>
          </div>
          <el-pagination
            v-if="total > pageSize"
            class="ai-history-pagination"
            background
            layout="prev, pager, next"
            :total="total"
            :page-size="pageSize"
            :current-page="page"
            @current-change="onPageChange"
          />
        </div>

        <!-- 右侧: 详情 -->
        <div class="ai-history-detail">
          <div v-if="selectedSessionId === null" class="ai-history-empty">
            <el-icon><ChatDotRound /></el-icon>
            <span>从左侧选择一个会话以查看详情</span>
          </div>
          <template v-else>
            <div class="ai-history-detail-header">
              <div>
                <h3 class="ai-history-detail-title">{{ selectedSummary?.title || '会话详情' }}</h3>
                <div class="ai-history-detail-sub">
                  开始: {{ formatTime(selectedSummary?.started_at ?? null) }} · 最近:
                  {{ formatTime(selectedSummary?.last_at ?? null) }} ·
                  {{ visibleMessages.length }} 条消息
                </div>
              </div>
              <div class="button-row">
                <el-button type="primary" @click="onContinueInLauncher(selectedSessionId)">
                  在浮动窗中继续对话
                </el-button>
              </div>
            </div>

            <div v-if="detailLoading === true" class="ai-history-empty">
              <el-icon class="is-loading"><Loading /></el-icon>
              加载中...
            </div>
            <div v-else ref="detailScroll" class="ai-history-detail-body">
              <template v-for="row in visibleMessages" :key="row.local_id">
                <div v-if="row.role === 'user'" class="ai-msg ai-msg-user">
                  <div class="ai-msg-bubble">{{ row.content }}</div>
                </div>
                <div v-else-if="row.role === 'assistant'" class="ai-msg ai-msg-assistant">
                  <div class="ai-msg-bubble">
                    <div
                      v-if="row.content !== ''"
                      class="ai-md-body"
                      v-html="renderMarkdown(row.content)"
                    ></div>
                    <div v-if="row.status === 'streaming'" class="ai-cursor">▌</div>
                    <div v-if="row.content === '' && row.status !== 'streaming'" class="ai-msg-empty">(仅工具调用, 无文本回复)</div>
                  </div>
                </div>
                <div v-else-if="row.role === 'tool'" class="ai-msg ai-msg-tool">
                  <div
                    class="ai-tool-card"
                    :class="{
                      'ai-tool-card-pending': row.status === 'pending_confirm',
                      'ai-tool-card-rejected': row.status === 'rejected',
                    }"
                  >
                    <div class="ai-tool-card-header">
                      <span class="ai-tool-card-name">
                        工具: {{ row.pending_tool_name || row.tool_call_id }}
                      </span>
                      <span v-if="row.status === 'streaming'" class="ai-tool-card-status">执行中...</span>
                      <span v-else-if="row.status === 'pending_confirm'" class="ai-tool-card-status">待确认</span>
                      <span v-else-if="row.status === 'rejected'" class="ai-tool-card-status">已拒绝</span>
                      <span v-else class="ai-tool-card-status ai-tool-card-status-ok">已执行</span>
                    </div>
                    <div v-if="row.pending_tool_args" class="ai-tool-card-section">
                      <div class="ai-tool-card-section-title">参数</div>
                      <pre class="ai-tool-card-pre">{{ JSON.stringify(row.pending_tool_args, null, 2) }}</pre>
                    </div>
                    <div v-if="row.status === 'committed' || row.status === 'rejected'" class="ai-tool-card-section">
                      <div class="ai-tool-card-section-title">结果</div>
                      <pre class="ai-tool-card-pre">{{ row.display_payload ? JSON.stringify(row.display_payload, null, 2) : parseToolPayload(row.content) }}</pre>
                    </div>
                  </div>
                </div>
              </template>

              <div
                v-if="ai.state.pending !== null && ai.state.sessionId === selectedSessionId"
                class="ai-pending-card"
              >
                <div class="ai-pending-title">写操作待确认</div>
                <div class="ai-pending-meta">
                  <div><strong>工具:</strong> {{ ai.state.pending.name }}</div>
                  <div v-if="ai.state.pending.description !== ''">
                    <strong>说明:</strong> {{ ai.state.pending.description }}
                  </div>
                </div>
                <div class="ai-pending-section">
                  <div class="ai-tool-card-section-title">参数 (将提交至后端)</div>
                  <pre class="ai-tool-card-pre">{{ JSON.stringify(ai.state.pending.arguments, null, 2) }}</pre>
                </div>
                <div class="ai-pending-actions">
                  <el-button type="primary" :loading="ai.state.sending" @click="onConfirmPendingInHistory">
                    确认执行
                  </el-button>
                  <el-button :disabled="ai.state.sending" @click="onRejectPendingInHistory">
                    拒绝并说明
                  </el-button>
                </div>
              </div>
            </div>

            <footer class="ai-history-input-panel">
              <textarea
                v-model="historyInputText"
                class="ai-history-input"
                rows="3"
                :disabled="ai.state.sending || ai.state.pending !== null"
                :placeholder="
                  ai.state.pending !== null
                    ? '请先处理待确认的写操作'
                    : '输入消息 (Shift+Enter 换行, Enter 发送)'
                "
                @keydown="onHistoryKeyDown"
              ></textarea>
              <div class="ai-history-input-bar">
                <span class="ai-history-input-tip">
                  <span v-if="ai.state.sending"><el-icon class="is-loading"><Loading /></el-icon> 模型生成中...</span>
                  <span v-else-if="ai.state.pending !== null">写操作等待你的判断</span>
                  <span v-else>支持 markdown · 工具调用自动展示</span>
                </span>
                <el-button
                  type="primary"
                  :loading="ai.state.sending"
                  :disabled="ai.state.pending !== null || historyInputText.trim() === ''"
                  @click="onSendInHistory"
                >
                  发送
                </el-button>
              </div>
            </footer>
          </template>
        </div>
      </div>
    </div>

    <!-- 配置 dialog -->
    <el-dialog
      v-model="settingsOpen"
      title="AI 助手配置 (DeepSeek)"
      width="560px"
      :close-on-click-modal="false"
    >
      <div v-if="settingsLoading === true" class="ai-history-empty">
        <el-icon class="is-loading"><Loading /></el-icon>
        加载中...
      </div>
      <template v-else>
        <div v-if="settingsConfig !== null" class="ai-config-effective">
          <div class="ai-config-section-title">当前生效配置</div>
          <div class="ai-config-effective-grid">
            <div class="ai-config-effective-row">
              <span class="ai-config-label">API Key</span>
              <span class="ai-config-value">
                {{ settingsConfig.effective.api_key_preview ?? '未设置 (无法发送对话)' }}
                <el-tag size="small" :type="sourceTagType(settingsConfig.effective.source.api_key)">
                  {{ sourceLabel(settingsConfig.effective.source.api_key) }}
                </el-tag>
              </span>
            </div>
            <div class="ai-config-effective-row">
              <span class="ai-config-label">Base URL</span>
              <span class="ai-config-value">
                {{ settingsConfig.effective.base_url }}
                <el-tag size="small" :type="sourceTagType(settingsConfig.effective.source.base_url)">
                  {{ sourceLabel(settingsConfig.effective.source.base_url) }}
                </el-tag>
              </span>
            </div>
            <div class="ai-config-effective-row">
              <span class="ai-config-label">模型</span>
              <span class="ai-config-value">
                {{ modelDisplayName(settingsConfig.effective.model) }}
                <el-tag size="small" :type="sourceTagType(settingsConfig.effective.source.model)">
                  {{ sourceLabel(settingsConfig.effective.source.model) }}
                </el-tag>
              </span>
            </div>
            <div class="ai-config-effective-row">
              <span class="ai-config-label">Timeout</span>
              <span class="ai-config-value">
                {{ settingsConfig.effective.timeout_s }} s
                <el-tag size="small" :type="sourceTagType(settingsConfig.effective.source.timeout_s)">
                  {{ sourceLabel(settingsConfig.effective.source.timeout_s) }}
                </el-tag>
              </span>
            </div>
          </div>
          <div class="ai-config-hint">
            UI 设置优先于环境变量. API Key, Base URL 和 Timeout 留空表示使用 env / 默认值. API Key 仅显示脱敏预览, 点击输入框开始编辑.
          </div>
        </div>

        <el-form label-width="120px" class="ai-config-form">
          <el-form-item label="API Key">
            <el-input
              v-model="settingsForm.api_key"
              type="password"
              show-password
              :placeholder="
                settingsConfig?.env.has_api_key === true
                  ? '留空使用环境变量, 或输入 sk-xxx 覆盖'
                  : '请输入 sk-xxx (DeepSeek 平台获取)'
              "
              @input="onApiKeyInput"
            />
            <div class="ai-config-form-hint">
              <el-button text size="small" type="danger" @click="onClearApiKey">
                清除 UI 设置, 回退环境变量
              </el-button>
            </div>
          </el-form-item>
          <el-form-item label="Base URL">
            <el-input
              v-model="settingsForm.base_url"
              :placeholder="`留空使用 ${settingsConfig?.defaults.base_url ?? 'https://api.deepseek.com'}`"
            />
          </el-form-item>
          <el-form-item label="模型">
            <el-radio-group v-model="settingsForm.model" class="ai-config-model-group">
              <el-radio-button
                v-for="option in getConfigModelOptions(settingsConfig)"
                :key="option.value"
                :label="option.value"
              >
                <span class="ai-config-model-label">{{ option.label }}</span>
                <span class="ai-config-model-id">{{ option.value }}</span>
              </el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="Timeout (秒)">
            <el-input
              v-model="settingsForm.timeout_s"
              :placeholder="`留空使用 ${settingsConfig?.defaults.timeout_s ?? 120} 秒`"
            />
          </el-form-item>
        </el-form>
      </template>

      <template #footer>
        <el-button @click="settingsOpen = false">取消</el-button>
        <el-button type="primary" :loading="settingsSaving" @click="onSaveSettings">
          保存配置
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.ai-history-search {
  width: 240px;
}

.ai-history-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  border-right: 1px solid #dce5f0;
  padding-right: 12px;
  min-height: 480px;
  max-height: calc(100vh - 220px);
  overflow: auto;
}

.ai-history-empty {
  margin: auto;
  padding: 32px 12px;
  color: #94a2b8;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.ai-history-item {
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid transparent;
  cursor: pointer;
  transition: background 0.16s ease;
}

.ai-history-item:hover {
  background: #f4f7fb;
}

.ai-history-item-active {
  background: #e6edf6;
  border-color: #1a5fa8;
}

.ai-history-item-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.ai-history-item-name {
  font-size: 14px;
  color: #12325a;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 220px;
}

.ai-history-item-count {
  font-size: 11px;
  color: #66758a;
}

.ai-history-item-time {
  font-size: 11px;
  color: #94a2b8;
  margin-bottom: 4px;
}

.ai-history-item-actions {
  display: flex;
  gap: 4px;
}

.ai-history-pagination {
  margin-top: 8px;
  align-self: center;
}

.ai-history-detail {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-left: 12px;
  min-width: 0;
  min-height: 480px;
  max-height: calc(100vh - 220px);
}

.ai-history-detail-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid #dce5f0;
}

.ai-history-detail-title {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: #12325a;
}

.ai-history-detail-sub {
  font-size: 12px;
  color: #66758a;
  margin-top: 4px;
}

.ai-history-detail-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding-right: 8px;
}

.ai-msg {
  display: flex;
}

.ai-msg-user {
  justify-content: flex-end;
}

.ai-msg-assistant {
  justify-content: flex-start;
}

.ai-msg-tool {
  justify-content: flex-start;
}

.ai-msg-bubble {
  max-width: 70%;
  padding: 10px 14px;
  border-radius: 10px;
  font-size: 14px;
  line-height: 1.6;
  word-break: break-word;
}

.ai-msg-user .ai-msg-bubble {
  background: #1a5fa8;
  color: #ffffff;
}

.ai-msg-assistant .ai-msg-bubble {
  background: #ffffff;
  color: #172033;
  border: 1px solid #dce5f0;
}

.ai-msg-empty {
  color: #94a2b8;
  font-style: italic;
}

.ai-cursor {
  display: inline-block;
  margin-left: 2px;
  color: #1a5fa8;
  animation: ai-blink 1s steps(1) infinite;
}

@keyframes ai-blink {
  50% {
    opacity: 0;
  }
}

.ai-md-body :deep(p) {
  margin: 0 0 6px;
}

.ai-md-body :deep(p:last-child) {
  margin-bottom: 0;
}

.ai-md-body :deep(pre) {
  background: #f4f7fb;
  border: 1px solid #dce5f0;
  border-radius: 6px;
  padding: 8px;
  overflow: auto;
  font-size: 12px;
}

.ai-md-body :deep(code) {
  background: #f4f7fb;
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 12px;
}

.ai-md-body :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 6px 0;
}

.ai-md-body :deep(th),
.ai-md-body :deep(td) {
  border: 1px solid #dce5f0;
  padding: 4px 6px;
  font-size: 12px;
}

.ai-tool-card {
  width: 100%;
  padding: 10px 12px;
  background: #ffffff;
  border: 1px solid #dce5f0;
  border-radius: 8px;
  font-size: 12px;
}

.ai-tool-card-rejected {
  border-color: #d6422b;
  background: #fdeeea;
}

.ai-tool-card-pending {
  border-color: #f0a040;
  background: #fff8eb;
}

.ai-tool-card-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 6px;
  color: #12325a;
}

.ai-tool-card-name {
  font-weight: 600;
}

.ai-tool-card-status {
  color: #66758a;
}

.ai-tool-card-status-ok {
  color: #168a4f;
}

.ai-tool-card-section {
  margin-top: 4px;
}

.ai-tool-card-section-title {
  color: #66758a;
  font-size: 11px;
  margin-bottom: 2px;
}

.ai-tool-card-pre {
  background: #f4f7fb;
  border: 1px solid #dce5f0;
  border-radius: 4px;
  padding: 6px;
  margin: 0;
  max-height: 240px;
  overflow: auto;
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-word;
}

.ai-pending-card {
  background: #fff8eb;
  border: 2px solid #f0a040;
  border-radius: 8px;
  padding: 10px 12px;
}

.ai-pending-title {
  color: #b56b00;
  font-weight: 700;
  font-size: 13px;
  margin-bottom: 6px;
}

.ai-pending-meta {
  font-size: 12px;
  color: #34445d;
  margin-bottom: 6px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.ai-pending-section {
  margin-bottom: 8px;
}

.ai-pending-actions {
  display: flex;
  gap: 8px;
}

.ai-history-input-panel {
  border-top: 1px solid #dce5f0;
  background: #ffffff;
  padding-top: 10px;
}

.ai-history-input {
  width: 100%;
  resize: none;
  border: 1px solid #dce5f0;
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 13px;
  line-height: 1.5;
  outline: none;
  transition: border-color 0.16s ease;
  font-family: inherit;
}

.ai-history-input:focus {
  border-color: #1a5fa8;
}

.ai-history-input:disabled {
  background: #f4f7fb;
  color: #94a2b8;
}

.ai-history-input-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 6px;
}

.ai-history-input-tip {
  font-size: 11px;
  color: #66758a;
  display: flex;
  align-items: center;
  gap: 4px;
}

/* ===== 配置 dialog ===== */
.ai-config-effective {
  background: #f4f7fb;
  border: 1px solid #dce5f0;
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 14px;
}

.ai-config-section-title {
  font-size: 12px;
  color: #66758a;
  margin-bottom: 8px;
}

.ai-config-effective-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 6px;
}

.ai-config-effective-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  font-size: 13px;
}

.ai-config-label {
  color: #66758a;
}

.ai-config-value {
  color: #12325a;
  display: flex;
  align-items: center;
  gap: 8px;
  font-family: 'Consolas', 'Microsoft YaHei', monospace;
  font-size: 12px;
  word-break: break-all;
}

.ai-config-hint {
  margin-top: 8px;
  font-size: 11px;
  color: #94a2b8;
  line-height: 1.5;
}

.ai-config-form {
  margin-top: 8px;
}

.ai-config-form-hint {
  margin-top: 4px;
}

.ai-config-model-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.ai-config-model-group :deep(.el-radio-button__inner) {
  display: flex;
  flex-direction: column;
  gap: 2px;
  align-items: flex-start;
  min-width: 168px;
  padding: 8px 12px;
  border-left: 1px solid var(--el-border-color);
  border-radius: 8px;
}

.ai-config-model-group :deep(.el-radio-button:first-child .el-radio-button__inner),
.ai-config-model-group :deep(.el-radio-button:last-child .el-radio-button__inner) {
  border-radius: 8px;
}

.ai-config-model-label {
  color: #12325a;
  font-size: 13px;
  font-weight: 700;
}

.ai-config-model-id {
  color: #66758a;
  font-size: 11px;
}
</style>
