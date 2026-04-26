<script setup lang="ts">
import { computed, ref, watch, type Component } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Coffee,
  Filter,
  MagicStick,
  Box,
  Sunny,
  Stopwatch,
  Help,
} from '@element-plus/icons-vue'
import {
  fetchTaskReport,
  type TaskReportResponse,
  type TaskReportStep,
  type TaskReportStepCell,
} from '../../api/taskHistory'
import { getErrorMessage } from '../../api/http'

const props = defineProps<{ taskId: number }>()

const data = ref<TaskReportResponse | null>(null)
const loading = ref(false)
const errorMessage = ref('')
const selectedCell = ref<{ experimentId: number; step: TaskReportStep; cell: TaskReportStepCell } | null>(null)

interface StepStyle {
  icon: Component
  color: string  // 主色 (头像/图标)
  hint: string   // 步骤辅助说明
}

// 步骤名 → 图标 + 颜色映射. 未匹配时退回 default 样式
const STEP_STYLE_MAP: Record<string, StepStyle> = {
  加磁子:     { icon: MagicStick, color: '#8e44ad', hint: '投放磁子' },
  加粉:       { icon: Box,        color: '#d35400', hint: '称量加粉' },
  移液加液:   { icon: Coffee,     color: '#2980b9', hint: '液体加料' },
  温控磁力搅拌: { icon: Sunny,    color: '#e67e22', hint: '温控搅拌反应' },
  闪滤制样:   { icon: Filter,     color: '#16a085', hint: '闪滤制样' },
}
const DEFAULT_STEP_STYLE: StepStyle = { icon: Stopwatch, color: '#909399', hint: '其他步骤' }

function styleFor(stepName: string): StepStyle {
  return STEP_STYLE_MAP[stepName] ?? DEFAULT_STEP_STYLE
}

async function load(taskId: number): Promise<void> {
  if (taskId <= 0) {
    return
  }
  loading.value = true
  errorMessage.value = ''
  selectedCell.value = null
  try {
    data.value = await fetchTaskReport(taskId)
  } catch (error) {
    errorMessage.value = getErrorMessage(error)
    data.value = null
    if (errorMessage.value.includes('未找到') === false) {
      ElMessage.error(errorMessage.value)
    }
  } finally {
    loading.value = false
  }
}

watch(
  () => props.taskId,
  (taskId) => { void load(taskId) },
  { immediate: true },
)

const meta = computed(() => data.value?.metadata ?? null)
const experiments = computed(() => data.value?.experiments ?? [])
const steps = computed(() => data.value?.steps ?? [])

type CellState = 'success' | 'failed' | 'running' | 'skipped' | 'unknown' | 'missing'

function statusToState(status: unknown): CellState {
  const text = String(status ?? '')
  if (text === '') return 'unknown'
  if (text.includes('完成')) return 'success'
  if (text.includes('失败') || text.includes('错误') || text.includes('异常')) return 'failed'
  if (text.includes('跳过')) return 'skipped'
  if (text.includes('进行') || text.includes('执行') || text.includes('运行')) return 'running'
  return 'unknown'
}

function shortTime(value: string | null): string {
  if (value === null || value === '') {
    return ''
  }
  const match = /T(\d{2}:\d{2}:\d{2})/.exec(value)
  if (match !== null) {
    return match[1]
  }
  return value
}

function fullTime(value: string | null): string {
  if (value === null || value === '') {
    return '-'
  }
  return value.replace('T', ' ').slice(0, 19)
}

function formatNumber(value: unknown): string {
  if (value === null || value === undefined || value === '') {
    return ''
  }
  if (typeof value === 'number') {
    if (Number.isInteger(value)) {
      return String(value)
    }
    return value.toFixed(3).replace(/\.?0+$/, '')
  }
  return String(value)
}

function findExtra(step: TaskReportStep, cell: TaskReportStepCell, ...keys: string[]): unknown {
  for (const key of keys) {
    const idx = step.extra_columns.indexOf(key)
    if (idx !== -1) {
      const value = cell.extras[idx]
      if (value !== null && value !== undefined && value !== '') {
        return value
      }
    }
  }
  return null
}

// 根据步骤名生成单元格主摘要 (省略次要信息, 突出"加了什么/多少/温度时间")
function summaryFor(step: TaskReportStep, cell: TaskReportStepCell): string {
  const name = step.step_name
  if (name === '加粉') {
    const reagent = findExtra(step, cell, '目标粉末名称')
    const amount = findExtra(step, cell, '实际加粉重量', '加粉量(mg)')
    const unit = findExtra(step, cell, '单位') ?? 'mg'
    if (reagent === null && amount === null) return ''
    return `${reagent ?? '?'} ${formatNumber(amount)} ${unit}`.trim()
  }
  if (name === '移液加液') {
    const reagent = findExtra(step, cell, '目标溶剂名称')
    const amount = findExtra(step, cell, '加液量(mL)')
    const unit = findExtra(step, cell, '单位') ?? 'mL'
    if (reagent === null && amount === null) return ''
    return `${reagent ?? '?'} ${formatNumber(amount)} ${unit}`.trim()
  }
  if (name === '温控磁力搅拌') {
    const temp = findExtra(step, cell, '温度(℃)', '目标温度(℃)')
    const duration = findExtra(step, cell, '反应时间(s)')
    const parts: string[] = []
    if (temp !== null) parts.push(`${formatNumber(temp)} ℃`)
    if (duration !== null) parts.push(`${formatNumber(duration)} s`)
    return parts.join(' · ')
  }
  if (name === '闪滤制样') {
    const reagent = findExtra(step, cell, '目标溶剂名称')
    const sample = findExtra(step, cell, '制样量(mL)')
    if (reagent === null && sample === null) return ''
    return `${reagent ?? '?'} ${formatNumber(sample)} mL`.trim()
  }
  if (name === '加磁子') {
    return ''
  }
  return name
}

function selectCell(experimentId: number, step: TaskReportStep): void {
  const cell = step.experiments[String(experimentId)]
  if (cell === undefined) {
    return
  }
  selectedCell.value = { experimentId, step, cell }
}

function formatExtra(value: unknown): string {
  if (value === null || value === undefined || value === '') {
    return '-'
  }
  return String(value)
}
</script>

<template>
  <div v-loading="loading" class="task-report-tab">
    <el-empty v-if="errorMessage !== '' && data === null" :description="errorMessage" />
    <template v-else-if="data !== null && meta !== null">
      <el-descriptions :column="3" border size="small" class="meta">
        <el-descriptions-item label="任务名称">{{ meta.task_name ?? '-' }}</el-descriptions-item>
        <el-descriptions-item label="操作者">{{ meta.operator ?? '-' }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ meta.task_status ?? '-' }}</el-descriptions-item>
        <el-descriptions-item label="开始时间">{{ fullTime(meta.started_at) }}</el-descriptions-item>
        <el-descriptions-item label="完成时间">{{ fullTime(meta.completed_at) }}</el-descriptions-item>
        <el-descriptions-item label="执行时长">{{ meta.duration ?? '-' }}</el-descriptions-item>
        <el-descriptions-item label="托盘型号">{{ meta.tray_model ?? '-' }}</el-descriptions-item>
        <el-descriptions-item label="托盘位置">{{ meta.tray_position ?? '-' }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ fullTime(meta.created_at) }}</el-descriptions-item>
      </el-descriptions>

      <div class="gantt-wrapper">
        <div class="gantt-grid" :style="`grid-template-columns: 60px repeat(${steps.length}, minmax(140px, 1fr));`">
          <div class="head head-corner">实验</div>
          <div
            v-for="step in steps"
            :key="step.step_index"
            class="head step-head"
          >
            <div class="step-icon-wrapper" :style="`background:${styleFor(step.step_name).color};`">
              <el-icon :size="14" color="#fff">
                <component :is="styleFor(step.step_name).icon" />
              </el-icon>
            </div>
            <div class="step-text">
              <div class="step-label">{{ step.step_label }}</div>
              <div class="step-name">{{ step.step_name || '-' }}</div>
            </div>
          </div>
          <template v-for="experimentId in experiments" :key="experimentId">
            <div class="row-head">#{{ experimentId }}</div>
            <button
              v-for="step in steps"
              :key="experimentId + ':' + step.step_index"
              class="cell"
              :class="[
                `state-${step.experiments[String(experimentId)] ? statusToState(step.experiments[String(experimentId)].status) : 'missing'}`,
                {
                  active:
                    selectedCell !== null &&
                    selectedCell.experimentId === experimentId &&
                    selectedCell.step.step_index === step.step_index,
                },
              ]"
              type="button"
              :title="step.experiments[String(experimentId)] ? `${step.step_name} - ${step.experiments[String(experimentId)].status}` : ''"
              @click="selectCell(experimentId, step)"
            >
              <template v-if="step.experiments[String(experimentId)]">
                <span class="cell-icon" :style="`color:${styleFor(step.step_name).color};`">
                  <el-icon :size="16">
                    <component :is="styleFor(step.step_name).icon" />
                  </el-icon>
                </span>
                <span class="cell-body">
                  <span class="cell-summary">
                    {{ summaryFor(step, step.experiments[String(experimentId)]) || '—' }}
                  </span>
                  <span class="cell-time">
                    {{ shortTime(step.experiments[String(experimentId)].completed_at) }}
                  </span>
                </span>
              </template>
              <span v-else class="cell-empty">—</span>
            </button>
          </template>
        </div>
      </div>

      <transition name="fade">
        <div v-if="selectedCell !== null" class="cell-detail">
          <div class="cell-detail-head">
            <span class="detail-icon" :style="`background:${styleFor(selectedCell.step.step_name).color};`">
              <el-icon :size="16" color="#fff">
                <component :is="styleFor(selectedCell.step.step_name).icon" />
              </el-icon>
            </span>
            <span class="detail-title">
              实验 #{{ selectedCell.experimentId }} · {{ selectedCell.step.step_label }} · {{ selectedCell.step.step_name }}
            </span>
            <el-button text size="small" @click="selectedCell = null">关闭</el-button>
          </div>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="状态">{{ selectedCell.cell.status ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="完成时间">{{ fullTime(selectedCell.cell.completed_at) }}</el-descriptions-item>
            <el-descriptions-item
              v-for="(col, idx) in selectedCell.step.extra_columns"
              :key="col"
              :label="col"
            >
              {{ formatExtra(selectedCell.cell.extras[idx]) }}
            </el-descriptions-item>
          </el-descriptions>
        </div>
      </transition>
    </template>
  </div>
</template>

<style scoped>
.task-report-tab {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 200px;
}

.meta :deep(.el-descriptions__label) {
  width: 90px;
}

.gantt-wrapper {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-fill-color-blank);
  overflow-x: auto;
}

.gantt-grid {
  display: grid;
  min-width: 100%;
}

.head {
  background: var(--el-fill-color-light);
  padding: 8px;
  border-right: 1px solid var(--el-border-color-lighter);
  border-bottom: 1px solid var(--el-border-color);
  font-weight: 600;
  font-size: 12px;
}

.head-corner {
  text-align: center;
  color: var(--el-text-color-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
}

.step-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.step-icon-wrapper {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.step-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.step-label {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.step-name {
  font-size: 13px;
  color: var(--el-text-color-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.row-head {
  background: var(--el-fill-color-light);
  padding: 8px;
  border-right: 1px solid var(--el-border-color);
  border-bottom: 1px solid var(--el-border-color-lighter);
  font-weight: 600;
  text-align: center;
  display: flex;
  align-items: center;
  justify-content: center;
}

.cell {
  background: var(--el-fill-color-blank);
  border: none;
  border-right: 1px solid var(--el-border-color-lighter);
  border-bottom: 1px solid var(--el-border-color-lighter);
  padding: 6px 8px;
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  transition: filter 0.12s, outline 0.12s;
  text-align: left;
  min-height: 44px;
}

.cell:hover {
  filter: brightness(0.96);
}

.cell.active {
  outline: 2px solid var(--el-color-primary);
  outline-offset: -2px;
}

.cell.state-success {
  background: rgba(103, 194, 58, 0.18);
}

.cell.state-failed {
  background: rgba(245, 108, 108, 0.22);
}

.cell.state-running {
  background: rgba(230, 162, 60, 0.22);
}

.cell.state-skipped {
  background: rgba(144, 147, 153, 0.18);
}

.cell.state-unknown {
  background: rgba(144, 147, 153, 0.10);
}

.cell.state-missing {
  background: repeating-linear-gradient(
    45deg,
    var(--el-fill-color-light),
    var(--el-fill-color-light) 6px,
    var(--el-fill-color-blank) 6px,
    var(--el-fill-color-blank) 12px
  );
  cursor: default;
  justify-content: center;
}

.cell-icon {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

.cell-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.cell-summary {
  font-size: 12px;
  color: var(--el-text-color-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-weight: 500;
}

.cell-time {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  font-family: var(--el-font-family-monospace, monospace);
}

.cell-empty {
  color: var(--el-text-color-disabled);
}

.cell-detail {
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-color-primary-light-7);
  border-radius: 6px;
  padding: 12px;
}

.cell-detail-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.detail-icon {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.detail-title {
  flex: 1;
  font-weight: 600;
  color: var(--el-color-primary);
}

.fade-enter-active, .fade-leave-active {
  transition: opacity 0.15s;
}

.fade-enter-from, .fade-leave-to {
  opacity: 0;
}
</style>
