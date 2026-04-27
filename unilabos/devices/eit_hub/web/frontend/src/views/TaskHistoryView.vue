<script setup lang="ts">
import { computed, onActivated, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Check, Close, Refresh, Search } from '@element-plus/icons-vue'
import { getErrorMessage } from '../api/http'
import {
  fetchTaskHistoryList,
  type TaskHistoryItem,
  type FilePresence,
} from '../api/taskHistory'
import TabExperimentPlan from '../components/taskHistory/TabExperimentPlan.vue'
import TabTaskReport from '../components/taskHistory/TabTaskReport.vue'
import TabIntegrationReport from '../components/taskHistory/TabIntegrationReport.vue'
import TabYieldReport from '../components/taskHistory/TabYieldReport.vue'
import TabAnalysisMethods from '../components/taskHistory/TabAnalysisMethods.vue'

const FILE_KEYS = ['experiment_plan', 'task_report', 'gc_ms', 'uplc_qtof', 'hplc'] as const
type FileKey = (typeof FILE_KEYS)[number]

const FILE_LABELS: Record<FileKey, string> = {
  experiment_plan: '实验计划',
  task_report: '任务报告',
  gc_ms: 'GC-MS',
  uplc_qtof: 'UPLC-QTOF',
  hplc: 'HPLC',
}

const items = ref<TaskHistoryItem[]>([])
const total = ref(0)
const queryText = ref('')
const listLoading = ref(false)
const selectedTaskId = ref<number | null>(null)
const activeTab = ref<'experiment_plan' | 'task_report' | 'methods' | 'integration' | 'yield'>('experiment_plan')
const integrationReloadToken = ref(0)
const yieldReloadToken = ref(0)
const activatedOnce = ref(false)

async function loadList(): Promise<void> {
  listLoading.value = true
  try {
    const response = await fetchTaskHistoryList(queryText.value.trim())
    items.value = response.items
    total.value = response.total
    if (selectedTaskId.value === null && response.items.length > 0) {
      selectedTaskId.value = response.items[0].task_id
    } else if (selectedTaskId.value !== null) {
      const stillThere = response.items.find((entry) => entry.task_id === selectedTaskId.value)
      if (stillThere === undefined) {
        selectedTaskId.value = response.items.length > 0 ? response.items[0].task_id : null
      }
    }
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    listLoading.value = false
  }
}

const selectedTask = computed<TaskHistoryItem | null>(() => {
  if (selectedTaskId.value === null) {
    return null
  }
  return items.value.find((entry) => entry.task_id === selectedTaskId.value) ?? null
})

const selectedFileStatus = computed<Record<string, { exists: boolean; filename: string }>>(() => {
  if (selectedTask.value === null) {
    return {}
  }
  const map: Record<string, { exists: boolean; filename: string }> = {}
  for (const entry of selectedTask.value.files) {
    map[entry.key] = { exists: entry.exists, filename: entry.filename }
  }
  return map
})

function presenceFor(item: TaskHistoryItem, key: FileKey): FilePresence | null {
  return item.files.find((entry) => entry.key === key) ?? null
}

function selectTask(item: TaskHistoryItem): void {
  selectedTaskId.value = item.task_id
}

function statusType(status: string | null): 'success' | 'info' | 'warning' | 'danger' {
  if (status === null) return 'info'
  if (status.includes('COMPLETED') || status.includes('已完成')) return 'success'
  if (status.includes('FAILED') || status.includes('失败')) return 'danger'
  if (status.includes('RUNNING') || status.includes('进行')) return 'warning'
  return 'info'
}

function formatTime(value: string | null): string {
  if (value === null || value === '') {
    return '-'
  }
  return value.replace('T', ' ').slice(0, 19)
}

function triggerActiveReportReload(): void {
  if (selectedTask.value === null) {
    return
  }
  if (activeTab.value === 'integration') {
    integrationReloadToken.value += 1
  }
  if (activeTab.value === 'yield') {
    yieldReloadToken.value += 1
  }
}

onMounted(() => {
  void loadList()
})

onActivated(() => {
  if (activatedOnce.value === false) {
    activatedOnce.value = true
    return
  }
  void loadList()
  triggerActiveReportReload()
})

watch(activeTab, (tab) => {
  if (tab === 'integration') {
    integrationReloadToken.value += 1
  }
  if (tab === 'yield') {
    yieldReloadToken.value += 1
  }
})
</script>

<template>
  <div class="task-history-page">
    <header class="toolbar">
      <el-input
        v-model="queryText"
        placeholder="按任务 ID 或任务名称搜索"
        :prefix-icon="Search"
        clearable
        class="search-input"
        @keyup.enter="loadList"
        @clear="loadList"
      />
      <el-button :icon="Search" type="primary" @click="loadList">搜索</el-button>
      <el-button :icon="Refresh" @click="loadList">刷新</el-button>
      <span class="toolbar-meta">共 {{ total }} 个任务</span>
    </header>

    <div class="split-layout">
      <aside v-loading="listLoading" class="list-pane">
        <ul v-if="items.length > 0" class="task-list">
          <li
            v-for="item in items"
            :key="item.task_id"
            class="task-item"
            :class="{ active: item.task_id === selectedTaskId }"
            @click="selectTask(item)"
          >
            <div class="task-head">
              <span class="task-id">#{{ item.task_id }}</span>
              <el-tag size="small" :type="statusType(item.status)">{{ item.status ?? '-' }}</el-tag>
            </div>
            <div class="task-name">{{ item.task_name || '(未命名)' }}</div>
            <div class="task-meta">
              <span class="task-time">{{ formatTime(item.completed_at ?? item.started_at ?? item.created_at) }}</span>
              <div class="presence-row">
                <el-tooltip
                  v-for="key in FILE_KEYS"
                  :key="key"
                  placement="top"
                >
                  <template #content>
                    <div>{{ FILE_LABELS[key] }}: {{ presenceFor(item, key)?.filename }}</div>
                    <div>{{ presenceFor(item, key)?.exists ? '已生成' : '缺失' }}</div>
                  </template>
                  <span class="presence-dot">
                    <el-icon
                      v-if="presenceFor(item, key)?.exists"
                      class="presence-icon presence-yes"
                    >
                      <Check />
                    </el-icon>
                    <el-icon v-else class="presence-icon presence-no">
                      <Close />
                    </el-icon>
                    <span class="presence-label">{{ FILE_LABELS[key] }}</span>
                  </span>
                </el-tooltip>
              </div>
            </div>
          </li>
        </ul>
        <el-empty v-else description="暂无任务历史" :image-size="80" />
      </aside>

      <section class="detail-pane">
        <template v-if="selectedTask !== null">
          <header class="detail-header">
            <div class="detail-title">
              <span class="big-id">#{{ selectedTask.task_id }}</span>
              <span class="big-name">{{ selectedTask.task_name || '(未命名)' }}</span>
              <el-tag size="small" :type="statusType(selectedTask.status)">{{ selectedTask.status ?? '-' }}</el-tag>
            </div>
            <div class="detail-times">
              <span>创建 {{ formatTime(selectedTask.created_at) }}</span>
              <span>开始 {{ formatTime(selectedTask.started_at) }}</span>
              <span>完成 {{ formatTime(selectedTask.completed_at) }}</span>
            </div>
          </header>
          <el-tabs v-model="activeTab" class="detail-tabs" type="border-card">
            <el-tab-pane label="实验计划" name="experiment_plan">
              <KeepAlive>
                <TabExperimentPlan v-if="activeTab === 'experiment_plan'" :task-id="selectedTask.task_id" />
              </KeepAlive>
            </el-tab-pane>
            <el-tab-pane label="任务报告" name="task_report">
              <KeepAlive>
                <TabTaskReport v-if="activeTab === 'task_report'" :task-id="selectedTask.task_id" />
              </KeepAlive>
            </el-tab-pane>
            <el-tab-pane label="分析方法" name="methods">
              <KeepAlive>
                <TabAnalysisMethods
                  v-if="activeTab === 'methods'"
                  :task-id="selectedTask.task_id"
                  :file-status="selectedFileStatus"
                />
              </KeepAlive>
            </el-tab-pane>
            <el-tab-pane label="积分报告" name="integration">
              <KeepAlive>
                <TabIntegrationReport
                  v-if="activeTab === 'integration'"
                  :task-id="selectedTask.task_id"
                  :reload-token="integrationReloadToken"
                />
              </KeepAlive>
            </el-tab-pane>
            <el-tab-pane label="产率报告" name="yield">
              <KeepAlive>
                <TabYieldReport
                  v-if="activeTab === 'yield'"
                  :task-id="selectedTask.task_id"
                  :reload-token="yieldReloadToken"
                />
              </KeepAlive>
            </el-tab-pane>
          </el-tabs>
        </template>
        <el-empty v-else description="从左侧选择一个任务" />
      </section>
    </div>
  </div>
</template>

<style scoped>
.task-history-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;
  padding: 12px;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
}

.search-input {
  width: 320px;
}

.toolbar-meta {
  margin-left: auto;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.split-layout {
  display: grid;
  grid-template-columns: 360px 1fr;
  gap: 12px;
  flex: 1;
  min-height: 0;
}

.list-pane {
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  overflow-y: auto;
}

.task-list {
  list-style: none;
  margin: 0;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.task-item {
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 10px 12px;
  cursor: pointer;
  transition: all 0.12s;
}

.task-item:hover {
  background: var(--el-color-primary-light-9);
  border-color: var(--el-color-primary-light-5);
}

.task-item.active {
  background: var(--el-color-primary-light-9);
  border-color: var(--el-color-primary);
  box-shadow: var(--el-box-shadow-light);
}

.task-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.task-id {
  font-weight: 600;
  font-size: 13px;
  color: var(--el-color-primary);
}

.task-name {
  font-size: 14px;
  color: var(--el-text-color-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 6px;
}

.task-meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.task-time {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  font-family: var(--el-font-family-monospace, monospace);
}

.presence-row {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.presence-dot {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 10px;
  background: var(--el-fill-color-blank);
}

.presence-icon {
  font-size: 12px;
}

.presence-yes {
  color: var(--el-color-success);
}

.presence-no {
  color: var(--el-color-danger);
  opacity: 0.5;
}

.presence-label {
  color: var(--el-text-color-regular);
}

.detail-pane {
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.detail-header {
  padding: 12px 16px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.detail-title {
  display: flex;
  align-items: center;
  gap: 12px;
}

.big-id {
  font-size: 18px;
  font-weight: 700;
  color: var(--el-color-primary);
}

.big-name {
  font-size: 16px;
  color: var(--el-text-color-primary);
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.detail-times {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  font-family: var(--el-font-family-monospace, monospace);
}

.detail-tabs {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.detail-tabs :deep(.el-tabs__content) {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}
</style>
