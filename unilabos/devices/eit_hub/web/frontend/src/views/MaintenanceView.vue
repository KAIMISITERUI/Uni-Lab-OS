<script setup lang="ts">
import { computed, onActivated, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Check, Edit, Plus, Refresh, Search, Setting } from '@element-plus/icons-vue'
import { getErrorMessage } from '../api/http'
import {
  createMaintenanceEvent,
  fetchMaintenanceEvents,
  fetchMaintenanceOverview,
  fetchMaintenanceRecords,
  submitMaintenanceRecords,
  updateMaintenanceEvent,
  type MaintenanceDueItem,
  type MaintenanceEvent,
  type MaintenanceEventPayload,
  type MaintenanceOverviewResponse,
  type MaintenanceRecord,
} from '../api/maintenance'

interface MaintenanceDraft {
  value_text: string
}

interface MaintenanceEventForm {
  id: string
  station: string
  title: string
  start_date: string
  interval_days: number
  enabled: boolean
  sort_order: number
}

const selectedDate = ref(toDateText(new Date()))
const overview = ref<MaintenanceOverviewResponse | null>(null)
const events = ref<MaintenanceEvent[]>([])
const records = ref<MaintenanceRecord[]>([])
const loadingOverview = ref(false)
const loadingEvents = ref(false)
const loadingRecords = ref(false)
const submitting = ref(false)
const eventSaving = ref(false)
const activeReminderTab = ref<'today' | 'overdue'>('today')
const selectedKeys = ref<string[]>([])
const completionOverrides = reactive<Record<string, boolean>>({})
const operator = ref(localStorage.getItem('maintenance_operator') || '')
const drafts = reactive<Record<string, MaintenanceDraft>>({})
const settingsDialogVisible = ref(false)
const eventDialogVisible = ref(false)
const activatedOnce = ref(false)

const recordRange = reactive({
  start_date: toDateText(addDays(new Date(), -7)),
  end_date: toDateText(new Date()),
})

const eventForm = reactive<MaintenanceEventForm>({
  id: '',
  station: '',
  title: '',
  start_date: selectedDate.value,
  interval_days: 1,
  enabled: true,
  sort_order: 10,
})

const dueItems = computed(() => overview.value?.due_items ?? [])
const overdueItems = computed(() => overview.value?.overdue_items ?? [])
const allReminderItems = computed(() => [...dueItems.value, ...overdueItems.value])
const stats = computed(() => overview.value?.stats ?? {
  due_count: 0,
  pending_count: 0,
  completed_count: 0,
  overdue_count: 0,
})
const selectedReminderItems = computed<MaintenanceDueItem[]>(() => {
  return allReminderItems.value.filter((item) => isSelected(item) === true)
})
const eventDialogTitle = computed(() => {
  if (eventForm.id === '') {
    return '新增运维事件'
  }
  return '编辑运维事件'
})

async function loadAll(): Promise<void> {
  await Promise.all([loadOverview(), loadEvents(), loadRecords()])
}

async function loadOverview(): Promise<void> {
  loadingOverview.value = true
  try {
    overview.value = await fetchMaintenanceOverview(selectedDate.value)
    syncDrafts()
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    loadingOverview.value = false
  }
}

async function loadEvents(): Promise<void> {
  loadingEvents.value = true
  try {
    const response = await fetchMaintenanceEvents()
    events.value = response.events
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    loadingEvents.value = false
  }
}

async function loadRecords(): Promise<void> {
  loadingRecords.value = true
  try {
    const response = await fetchMaintenanceRecords(recordRange.start_date, recordRange.end_date)
    records.value = response.records
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    loadingRecords.value = false
  }
}

function syncDrafts(): void {
  const validKeys = new Set<string>()
  for (const item of allReminderItems.value) {
    const key = itemKey(item)
    validKeys.add(key)
    if (drafts[key] === undefined) {
      drafts[key] = {
        value_text: item.record?.value_text ?? '',
      }
    }
  }
  selectedKeys.value = selectedKeys.value.filter((key) => validKeys.has(key))
  for (const key of Object.keys(completionOverrides)) {
    if (validKeys.has(key) === false) {
      delete completionOverrides[key]
    }
  }
}

function itemKey(item: MaintenanceDueItem): string {
  return `${item.event_id}|${item.due_date}`
}

function rowKey(item: MaintenanceDueItem): string {
  return itemKey(item)
}

function draftFor(item: MaintenanceDueItem): MaintenanceDraft {
  const key = itemKey(item)
  if (drafts[key] === undefined) {
    drafts[key] = {
      value_text: item.record?.value_text ?? '',
    }
  }
  return drafts[key]
}

function isSelected(item: MaintenanceDueItem): boolean {
  const key = itemKey(item)
  if (completionOverrides[key] !== undefined) {
    return completionOverrides[key]
  }
  if (selectedKeys.value.includes(key) === true) {
    return true
  }
  return item.completed === true
}

function setSelected(item: MaintenanceDueItem, checked: boolean): void {
  const key = itemKey(item)
  completionOverrides[key] = checked
  if (checked === true) {
    if (selectedKeys.value.includes(key) === false) {
      selectedKeys.value = [...selectedKeys.value, key]
    }
    return
  }
  selectedKeys.value = selectedKeys.value.filter((itemKeyText) => itemKeyText !== key)
}

async function submitSelectedRecords(): Promise<void> {
  if (selectedReminderItems.value.length === 0) {
    ElMessage.warning('请先选择需要提交的运维事项')
    return
  }
  const operatorText = operator.value.trim()
  if (operatorText === '') {
    ElMessage.warning('请填写操作人')
    return
  }

  submitting.value = true
  try {
    await submitMaintenanceRecords({
      date: selectedDate.value,
      operator: operatorText,
      items: selectedReminderItems.value.map((item) => {
        const draft = draftFor(item)
        return {
          event_id: item.event_id,
          due_date: item.due_date,
          value_text: draft.value_text,
          note: '',
        }
      }),
    })
    localStorage.setItem('maintenance_operator', operatorText)
    selectedKeys.value = []
    for (const key of Object.keys(completionOverrides)) {
      delete completionOverrides[key]
    }
    ElMessage.success('运维记录已保存')
    await Promise.all([loadOverview(), loadRecords()])
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    submitting.value = false
  }
}

function openCreateEventDialog(): void {
  const maxSortOrder = events.value.reduce(
    (current, event) => Math.max(current, Number(event.sort_order) || 0),
    0,
  )
  Object.assign(eventForm, {
    id: '',
    station: '',
    title: '',
    start_date: selectedDate.value,
    interval_days: 1,
    enabled: true,
    sort_order: maxSortOrder + 10,
  })
  eventDialogVisible.value = true
}

async function openSettingsDialog(): Promise<void> {
  settingsDialogVisible.value = true
  await loadEvents()
}

function openEditEventDialog(event: MaintenanceEvent): void {
  Object.assign(eventForm, {
    id: event.id,
    station: event.station,
    title: event.title,
    start_date: event.start_date,
    interval_days: event.interval_days,
    enabled: event.enabled,
    sort_order: event.sort_order,
  })
  eventDialogVisible.value = true
}

async function saveEvent(): Promise<void> {
  const payload: MaintenanceEventPayload = {
    station: eventForm.station.trim(),
    title: eventForm.title.trim(),
    start_date: eventForm.start_date,
    interval_days: Number(eventForm.interval_days),
    enabled: eventForm.enabled,
    sort_order: Number(eventForm.sort_order),
  }
  if (payload.station === '') {
    ElMessage.warning('请填写工站名称')
    return
  }
  if (payload.title === '') {
    ElMessage.warning('请填写检查内容')
    return
  }
  if (Number.isInteger(payload.interval_days) === false || payload.interval_days <= 0) {
    ElMessage.warning('间隔天数必须大于 0')
    return
  }

  eventSaving.value = true
  try {
    if (eventForm.id === '') {
      await createMaintenanceEvent(payload)
      ElMessage.success('运维事件已新增')
    } else {
      await updateMaintenanceEvent(eventForm.id, payload)
      ElMessage.success('运维事件已保存')
    }
    eventDialogVisible.value = false
    await Promise.all([loadEvents(), loadOverview()])
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    eventSaving.value = false
  }
}

function statusTagType(item: MaintenanceDueItem): 'success' | 'warning' | 'danger' {
  if (isSelected(item) === true) {
    return 'success'
  }
  if (item.due_date < selectedDate.value) {
    return 'danger'
  }
  return 'warning'
}

function statusText(item: MaintenanceDueItem): string {
  if (isSelected(item) === true) {
    return '已完成'
  }
  if (item.due_date < selectedDate.value) {
    return '逾期'
  }
  return '待完成'
}

function eventStatusType(event: MaintenanceEvent): 'success' | 'info' {
  if (event.enabled === true) {
    return 'success'
  }
  return 'info'
}

function formatCycle(intervalDays: number): string {
  if (intervalDays === 1) {
    return '每天'
  }
  return `每 ${intervalDays} 天`
}

function formatDateTime(value: string | undefined): string {
  if (value === undefined || value === '') {
    return '-'
  }
  return value.replace('T', ' ').slice(0, 19)
}

function displayNumber(title: string): string {
  return splitNumberedTitle(title).number
}

function displayTitle(title: string): string {
  return splitNumberedTitle(title).title
}

function splitNumberedTitle(title: string): { number: string; title: string } {
  const match = title.trim().match(/^(\d+)\s*[.、]?\s*(.*)$/)
  if (match === null) {
    return { number: '-', title }
  }
  return {
    number: match[1],
    title: match[2] === '' ? title : match[2],
  }
}

function addDays(value: Date, days: number): Date {
  const dateValue = new Date(value)
  dateValue.setDate(dateValue.getDate() + days)
  return dateValue
}

function toDateText(value: Date): string {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

onMounted(() => {
  void loadAll()
})

onActivated(() => {
  if (activatedOnce.value === false) {
    activatedOnce.value = true
    return
  }
  void loadAll()
})
</script>

<template>
  <div class="view-stack maintenance-view">
    <section class="panel">
      <div class="panel-title maintenance-header">
        <h2>运维提醒</h2>
        <div class="maintenance-toolbar">
          <el-date-picker
            v-model="selectedDate"
            type="date"
            value-format="YYYY-MM-DD"
            :clearable="false"
            @change="loadOverview"
          />
          <el-button :icon="Refresh" :loading="loadingOverview" @click="loadOverview">刷新</el-button>
        </div>
      </div>

      <div class="metrics-grid maintenance-metrics">
        <div class="metric">
          <div class="metric-label">当日事项</div>
          <div class="metric-value">{{ stats.due_count }}</div>
          <div class="metric-note">{{ selectedDate }}</div>
        </div>
        <div class="metric">
          <div class="metric-label">待完成</div>
          <div class="metric-value warning-text">{{ stats.pending_count }}</div>
          <div class="metric-note">当日未提交</div>
        </div>
        <div class="metric">
          <div class="metric-label">已完成</div>
          <div class="metric-value success-text">{{ stats.completed_count }}</div>
          <div class="metric-note">已有运维记录</div>
        </div>
        <div class="metric">
          <div class="metric-label">逾期提醒</div>
          <div class="metric-value danger-text">{{ stats.overdue_count }}</div>
          <div class="metric-note">最近未完成到期项</div>
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-title">
        <h2>待办事项</h2>
        <div class="maintenance-title-actions">
          <span class="muted">已选择 {{ selectedReminderItems.length }} 项</span>
          <el-button :icon="Setting" @click="openSettingsDialog">事件设置</el-button>
        </div>
      </div>

      <el-tabs v-model="activeReminderTab" class="maintenance-tabs">
        <el-tab-pane label="当日待办" name="today">
          <div class="table-wrap">
            <el-table :data="dueItems" :row-key="rowKey" v-loading="loadingOverview">
              <el-table-column label="编号" width="80">
                <template #default="{ row }">{{ displayNumber(row.title) }}</template>
              </el-table-column>
              <el-table-column prop="station" label="工站" width="140" />
              <el-table-column label="检查内容" min-width="260" show-overflow-tooltip>
                <template #default="{ row }">{{ displayTitle(row.title) }}</template>
              </el-table-column>
              <el-table-column prop="due_date" label="到期日期" width="120" />
              <el-table-column label="周期" width="110">
                <template #default="{ row }">{{ formatCycle(row.interval_days) }}</template>
              </el-table-column>
              <el-table-column label="状态" width="110">
                <template #default="{ row }">
                  <el-tag :type="statusTagType(row)" effect="light">{{ statusText(row) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="运维信息" min-width="210">
                <template #default="{ row }">
                  <el-input v-model="draftFor(row).value_text" placeholder="填写运维信息" />
                </template>
              </el-table-column>
              <el-table-column label="完成" width="92" fixed="right" align="center">
                <template #default="{ row }">
                  <el-checkbox
                    class="maintenance-complete-checkbox"
                    :model-value="isSelected(row)"
                    @change="(checked) => setSelected(row, checked === true)"
                  />
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>
        <el-tab-pane label="逾期提醒" name="overdue">
          <div class="table-wrap">
            <el-table :data="overdueItems" :row-key="rowKey" v-loading="loadingOverview">
              <el-table-column label="编号" width="80">
                <template #default="{ row }">{{ displayNumber(row.title) }}</template>
              </el-table-column>
              <el-table-column prop="station" label="工站" width="140" />
              <el-table-column label="检查内容" min-width="260" show-overflow-tooltip>
                <template #default="{ row }">{{ displayTitle(row.title) }}</template>
              </el-table-column>
              <el-table-column prop="due_date" label="到期日期" width="120" />
              <el-table-column label="周期" width="110">
                <template #default="{ row }">{{ formatCycle(row.interval_days) }}</template>
              </el-table-column>
              <el-table-column label="状态" width="110">
                <template #default="{ row }">
                  <el-tag :type="statusTagType(row)" effect="light">{{ statusText(row) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="运维信息" min-width="210">
                <template #default="{ row }">
                  <el-input v-model="draftFor(row).value_text" placeholder="填写运维信息" />
                </template>
              </el-table-column>
              <el-table-column label="完成" width="92" fixed="right" align="center">
                <template #default="{ row }">
                  <el-checkbox
                    class="maintenance-complete-checkbox"
                    :model-value="isSelected(row)"
                    @change="(checked) => setSelected(row, checked === true)"
                  />
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>
      </el-tabs>

      <div class="maintenance-submit-bar">
        <el-input v-model="operator" class="operator-input" placeholder="操作人" />
        <el-button
          type="primary"
          :icon="Check"
          :loading="submitting"
          @click="submitSelectedRecords"
        >
          提交运维记录
        </el-button>
      </div>
    </section>

    <section class="panel">
      <div class="panel-title maintenance-header">
        <h2>运维记录</h2>
        <div class="maintenance-toolbar">
          <el-date-picker
            v-model="recordRange.start_date"
            type="date"
            value-format="YYYY-MM-DD"
            :clearable="false"
          />
          <el-date-picker
            v-model="recordRange.end_date"
            type="date"
            value-format="YYYY-MM-DD"
            :clearable="false"
          />
          <el-button :icon="Search" :loading="loadingRecords" @click="loadRecords">查询</el-button>
        </div>
      </div>
      <div class="table-wrap">
        <el-table :data="records" v-loading="loadingRecords" row-key="record_id">
          <el-table-column label="编号" width="80">
            <template #default="{ row }">{{ displayNumber(row.title_snapshot) }}</template>
          </el-table-column>
          <el-table-column prop="due_date" label="到期日期" width="120" />
          <el-table-column prop="station_snapshot" label="工站" width="140" />
          <el-table-column label="检查内容" min-width="260" show-overflow-tooltip>
            <template #default="{ row }">{{ displayTitle(row.title_snapshot) }}</template>
          </el-table-column>
          <el-table-column prop="operator" label="操作人" width="120" />
          <el-table-column prop="value_text" label="运维信息" min-width="180" show-overflow-tooltip />
          <el-table-column label="完成时间" width="180">
            <template #default="{ row }">{{ formatDateTime(row.completed_at) }}</template>
          </el-table-column>
        </el-table>
      </div>
    </section>

    <el-dialog v-model="settingsDialogVisible" title="事件设置" width="960px">
      <div class="maintenance-settings-head">
        <span class="muted">共 {{ events.length }} 个事件</span>
        <el-button type="primary" :icon="Plus" @click="openCreateEventDialog">新增事件</el-button>
      </div>
      <div class="table-wrap">
        <el-table :data="events" v-loading="loadingEvents" row-key="id">
          <el-table-column label="编号" width="80">
            <template #default="{ row }">{{ displayNumber(row.title) }}</template>
          </el-table-column>
          <el-table-column prop="station" label="工站" width="140" />
          <el-table-column label="检查内容" min-width="300" show-overflow-tooltip>
            <template #default="{ row }">{{ displayTitle(row.title) }}</template>
          </el-table-column>
          <el-table-column prop="start_date" label="开始日期" width="120" />
          <el-table-column label="周期" width="110">
            <template #default="{ row }">{{ formatCycle(row.interval_days) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="eventStatusType(row)" effect="light">
                {{ row.enabled ? '启用' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="sort_order" label="排序" width="90" />
          <el-table-column label="操作" width="110" fixed="right">
            <template #default="{ row }">
              <el-button :icon="Edit" text type="primary" @click="openEditEventDialog(row)">编辑</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-dialog>

    <el-dialog v-model="eventDialogVisible" :title="eventDialogTitle" width="640px">
      <el-form label-width="96px">
        <el-form-item label="工站名称">
          <el-input v-model="eventForm.station" placeholder="工站名称" />
        </el-form-item>
        <el-form-item label="检查内容">
          <el-input v-model="eventForm.title" type="textarea" :rows="3" placeholder="检查内容" />
        </el-form-item>
        <el-form-item label="开始日期">
          <el-date-picker
            v-model="eventForm.start_date"
            type="date"
            value-format="YYYY-MM-DD"
            :clearable="false"
          />
        </el-form-item>
        <el-form-item label="间隔天数">
          <el-input-number v-model="eventForm.interval_days" :min="1" :step="1" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="eventForm.sort_order" :step="10" />
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="eventForm.enabled" active-text="启用" inactive-text="停用" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="eventDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="eventSaving" @click="saveEvent">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.maintenance-view {
  min-width: 0;
}

.maintenance-header,
.maintenance-toolbar,
.maintenance-submit-bar,
.maintenance-title-actions,
.maintenance-settings-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.maintenance-header {
  justify-content: space-between;
}

.maintenance-toolbar {
  justify-content: flex-end;
}

.maintenance-title-actions,
.maintenance-settings-head {
  justify-content: flex-end;
}

.maintenance-metrics {
  grid-template-columns: repeat(4, minmax(150px, 1fr));
}

.maintenance-tabs {
  min-width: 0;
}

.maintenance-submit-bar {
  justify-content: flex-end;
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid #dce5f0;
}

.maintenance-complete-checkbox {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  margin: 0;
}

.maintenance-complete-checkbox :deep(.el-checkbox__input) {
  transform: scale(1.45);
  transform-origin: center;
}

.operator-input {
  width: 220px;
}

@media (max-width: 920px) {
  .maintenance-metrics {
    grid-template-columns: repeat(2, minmax(140px, 1fr));
  }

  .maintenance-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .maintenance-toolbar,
  .maintenance-submit-bar,
  .maintenance-title-actions,
  .maintenance-settings-head {
    justify-content: flex-start;
    width: 100%;
  }
}

@media (max-width: 560px) {
  .maintenance-metrics {
    grid-template-columns: 1fr;
  }

  .operator-input {
    width: 100%;
  }
}
</style>
