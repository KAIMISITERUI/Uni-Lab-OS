<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { CircleClose, Edit, Refresh, VideoPause, VideoPlay } from '@element-plus/icons-vue'
import {
  type ReactionTemplate,
  type WorkflowBatchInMode,
  type WorkflowState,
  type WorkflowStartPayload,
  type WorkflowStepId,
  fetchReactionTemplate,
  fetchSynthesisWorkflow,
  pauseSynthesisWorkflow,
  resumeSynthesisWorkflow,
  startSynthesisWorkflow,
  stopSynthesisWorkflow,
} from '../api/synthesis'
import { getErrorMessage } from '../api/http'
import ResultConsole from '../components/ResultConsole.vue'

const EXPERIMENT_ID_PARAM_NAME = '实验ID'
const EXPERIMENT_NAME_PARAM_NAME = '实验名称'
const WORKFLOW_STORAGE_KEY = 'eit_hub.synthesis_workflow.current'
const WORKFLOW_STEPS: Array<{ id: WorkflowStepId; label: string }> = [
  { id: 'batch_in', label: 'AGV上料' },
  { id: 'resource_check', label: '物料检查' },
  { id: 'start_task', label: '开始合成任务' },
  { id: 'wait_task', label: '任务监控' },
  { id: 'batch_out', label: '下料' },
  { id: 'auto_unload', label: 'AGV转运' },
  { id: 'submit_analysis', label: '运行分析任务' },
  { id: 'poll_analysis', label: '谱图数据处理' },
  { id: 'calculate_yields', label: '产率计算' },
]
const ANALYSIS_PARAM_NAMES = ['GC_MS', 'UPLC_QTOF', 'HPLC']

const workflowExperimentId = ref('')
const workflowExperimentName = ref('')
const workflowStartStepIndex = ref(0)
const workflowBatchInMode = ref<WorkflowBatchInMode>('agv')
const workflowCheckGloveboxEnv = ref(true)
const workflowWaterLimit = ref(10)
const workflowOxygenLimit = ref(10)
const workflowWaitPollInterval = ref(2)
const workflowHasAnalysisTask = ref(false)
const workflowAutoSubmitAnalysisAfterAgv = ref(true)
const workflowAnalysisPollInterval = ref(30)
const workflowDialogVisible = ref(false)
const editingWorkflowStepId = ref<WorkflowStepId | null>(null)
const currentWorkflowId = ref('')
const workflowState = ref<WorkflowState | null>(null)
const workflowLoading = ref(false)
const templateLoading = ref(false)
let workflowTimer: number | undefined
let workflowInitialized = false

const workflowSteps = computed(() => {
  if (workflowHasAnalysisTask.value === true) {
    return WORKFLOW_STEPS
  }
  return WORKFLOW_STEPS.filter((step) => {
    return step.id !== 'submit_analysis' && step.id !== 'poll_analysis' && step.id !== 'calculate_yields'
  })
})

const workflowStartStepId = computed<WorkflowStepId>(() => workflowSteps.value[workflowStartStepIndex.value]?.id || 'batch_in')

const workflowSliderMarks = computed<Record<number, string>>(() => {
  const marks: Record<number, string> = {}
  for (let index = 0; index < workflowSteps.value.length; index += 1) {
    marks[index] = String(index + 1)
  }
  return marks
})

const editingWorkflowStep = computed(() => {
  if (editingWorkflowStepId.value === null) {
    return null
  }
  const step = workflowSteps.value.find((item) => item.id === editingWorkflowStepId.value)
  if (step === undefined) {
    return null
  }
  return {
    ...step,
    label: workflowStepLabel(step.id),
  }
})

const workflowCanStart = computed(() => {
  return workflowLoading.value === false && workflowLocked.value === false && parseWorkflowExperimentId() !== null
})

const workflowLocked = computed(() => {
  if (currentWorkflowId.value === '') {
    return false
  }
  if (workflowState.value === null) {
    return true
  }
  return isWorkflowTerminal(workflowState.value.status) === false
})

const workflowCanPause = computed(() => {
  if (workflowState.value === null) {
    return false
  }
  return workflowState.value.status === 'running' || workflowState.value.status === 'pausing'
})

const workflowCanResume = computed(() => {
  if (workflowState.value === null) {
    return false
  }
  return workflowState.value.status === 'paused' || workflowState.value.status === 'pausing'
})

const workflowCanStop = computed(() => {
  if (workflowLoading.value === true || workflowState.value === null) {
    return false
  }
  return (
    workflowState.value.status === 'queued' ||
    workflowState.value.status === 'running' ||
    workflowState.value.status === 'pausing' ||
    workflowState.value.status === 'paused'
  )
})

const workflowStatusText = computed(() => {
  if (workflowState.value === null) {
    return '未开始'
  }
  const map: Record<string, string> = {
    queued: '排队中',
    running: '运行中',
    pausing: '暂停中',
    paused: '已暂停',
    stopping: '停止中',
    stopped: '已停止',
    succeeded: '已完成',
    failed: '失败',
  }
  return map[workflowState.value.status] || workflowState.value.status
})

const workflowStatusType = computed(() => {
  if (workflowState.value === null) {
    return 'info'
  }
  if (workflowState.value.status === 'succeeded') {
    return 'success'
  }
  if (workflowState.value.status === 'failed') {
    return 'danger'
  }
  if (workflowState.value.status === 'stopping' || workflowState.value.status === 'stopped') {
    return 'danger'
  }
  if (workflowState.value.status === 'paused' || workflowState.value.status === 'pausing') {
    return 'warning'
  }
  return 'primary'
})

const workflowPanelClass = computed(() => {
  if (workflowState.value === null) {
    return ''
  }
  if (workflowState.value.status === 'succeeded') {
    return 'workflow-panel-succeeded'
  }
  if (workflowState.value.status === 'failed') {
    return 'workflow-panel-failed'
  }
  if (workflowState.value.status === 'stopped') {
    return 'workflow-panel-failed'
  }
  return ''
})

onMounted(() => {
  void initializeWorkflowView()
})

onActivated(() => {
  if (workflowInitialized === false) {
    void initializeWorkflowView()
    return
  }
  void refreshWorkflowView()
})

onBeforeUnmount(() => {
  stopWorkflowPolling()
})


async function initializeWorkflowView() {
  if (workflowInitialized === true) {
    return
  }
  workflowInitialized = true
  const restored = await restoreStoredWorkflow()
  if (restored === true) {
    return
  }
  await loadWorkflowDefaults()
}

async function refreshWorkflowView() {
  if (currentWorkflowId.value !== '') {
    const loaded = await loadWorkflowState({ showError: false, clearOnError: true })
    if (loaded === true && workflowState.value !== null && isWorkflowTerminal(workflowState.value.status) === false) {
      startWorkflowPolling()
    }
    return
  }
  await loadWorkflowDefaults()
}

async function loadWorkflowDefaults() {
  if (workflowLocked.value === true) {
    return
  }
  templateLoading.value = true
  try {
    const data = await fetchReactionTemplate()
    syncWorkflowInfoFromTemplate(data)
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    templateLoading.value = false
  }
}

async function restoreStoredWorkflow(): Promise<boolean> {
  const stored = readStoredWorkflow()
  if (stored === null) {
    return false
  }
  try {
    applyStoredWorkflowPayload(stored.payload)
  } catch {
    clearStoredWorkflow()
    return false
  }
  currentWorkflowId.value = stored.workflow_id
  const loaded = await loadWorkflowState({ showError: false, clearOnError: true })
  if (loaded === false) {
    return false
  }
  if (workflowState.value !== null && isWorkflowTerminal(workflowState.value.status) === false) {
    startWorkflowPolling()
  }
  return true
}

function readStoredWorkflow(): { workflow_id: string; payload: WorkflowStartPayload } | null {
  const rawText = window.localStorage.getItem(WORKFLOW_STORAGE_KEY)
  if (rawText === null || rawText.trim() === '') {
    return null
  }
  try {
    const data = JSON.parse(rawText) as { workflow_id?: unknown; payload?: unknown }
    if (typeof data.workflow_id !== 'string' || typeof data.payload !== 'object' || data.payload === null) {
      clearStoredWorkflow()
      return null
    }
    return {
      workflow_id: data.workflow_id,
      payload: data.payload as WorkflowStartPayload,
    }
  } catch {
    clearStoredWorkflow()
    return null
  }
}

function persistWorkflow(payload: WorkflowStartPayload) {
  if (currentWorkflowId.value === '') {
    return
  }
  window.localStorage.setItem(
    WORKFLOW_STORAGE_KEY,
    JSON.stringify({
      workflow_id: currentWorkflowId.value,
      payload,
    }),
  )
}

function clearStoredWorkflow() {
  window.localStorage.removeItem(WORKFLOW_STORAGE_KEY)
}

function applyStoredWorkflowPayload(payload: WorkflowStartPayload) {
  workflowExperimentId.value = String(payload.experiment_id)
  workflowExperimentName.value = payload.experiment_name
  workflowBatchInMode.value = payload.batch_in.mode
  workflowCheckGloveboxEnv.value = payload.start_task.check_glovebox_env
  workflowWaterLimit.value = payload.start_task.water_limit_ppm
  workflowOxygenLimit.value = payload.start_task.oxygen_limit_ppm
  workflowWaitPollInterval.value = payload.wait_task.poll_interval_s
  workflowHasAnalysisTask.value = payload.has_analysis_task
  workflowAutoSubmitAnalysisAfterAgv.value = payload.submit_analysis.auto_submit_after_agv
  workflowAnalysisPollInterval.value = payload.poll_analysis.poll_interval
  const startIndex = workflowSteps.value.findIndex((step) => step.id === payload.start_step)
  if (startIndex >= 0) {
    workflowStartStepIndex.value = startIndex
  }
}

function parseWorkflowExperimentId(): number | null {
  const text = workflowExperimentId.value.trim()
  if (text === '') {
    return null
  }
  const value = Number.parseInt(text, 10)
  if (Number.isNaN(value) === true || value <= 0) {
    return null
  }
  return value
}

function syncWorkflowInfoFromTemplate(data: ReactionTemplate) {
  workflowExperimentId.value = cellText(readTemplateParam(data, EXPERIMENT_ID_PARAM_NAME))
  workflowExperimentName.value = cellText(readTemplateParam(data, EXPERIMENT_NAME_PARAM_NAME))
  workflowHasAnalysisTask.value = hasAnalysisTask(data)
  if (workflowStartStepIndex.value >= workflowSteps.value.length) {
    workflowStartStepIndex.value = Math.max(workflowSteps.value.length - 1, 0)
  }
}

function syncWorkflowInfoFromState(data: WorkflowState) {
  workflowExperimentId.value = String(data.experiment_id)
  workflowExperimentName.value = data.experiment_name
  const startIndex = workflowSteps.value.findIndex((step) => step.id === data.start_step)
  if (startIndex >= 0) {
    workflowStartStepIndex.value = startIndex
  }
}

function readTemplateParam(data: ReactionTemplate, name: string): unknown {
  const row = data.param_rows.find((item) => item.type === 'parameter' && item.name === name)
  if (row !== undefined) {
    return row.value
  }
  return data.params[name]
}

function cellText(value: unknown): string {
  if (value === null || value === undefined) {
    return ''
  }
  return String(value)
}

function hasAnalysisTask(data: ReactionTemplate): boolean {
  for (const name of ANALYSIS_PARAM_NAMES) {
    if (cellText(readTemplateParam(data, name)).trim() !== '') {
      return true
    }
  }
  return false
}

function openWorkflowStepDialog(stepId: WorkflowStepId) {
  editingWorkflowStepId.value = stepId
  workflowDialogVisible.value = true
}

async function startWorkflow() {
  const experimentId = parseWorkflowExperimentId()
  if (experimentId === null) {
    ElMessage.error('请先填写有效的实验ID')
    return
  }
  if (workflowExperimentName.value.trim() === '') {
    ElMessage.error('请先填写实验名称')
    return
  }

  workflowLoading.value = true
  try {
    const payload: WorkflowStartPayload = {
      experiment_id: experimentId,
      experiment_name: workflowExperimentName.value.trim(),
      start_step: workflowStartStepId.value,
      batch_in: {
        mode: workflowBatchInMode.value,
        chamber_capacity: 8,
      },
      start_task: {
        check_glovebox_env: workflowCheckGloveboxEnv.value,
        water_limit_ppm: workflowWaterLimit.value,
        oxygen_limit_ppm: workflowOxygenLimit.value,
      },
      wait_task: {
        poll_interval_s: workflowWaitPollInterval.value,
      },
      has_analysis_task: workflowHasAnalysisTask.value,
      submit_analysis: {
        auto_submit_after_agv: workflowAutoSubmitAnalysisAfterAgv.value,
      },
      poll_analysis: {
        poll_interval: workflowAnalysisPollInterval.value,
      },
    }
    const data = await startSynthesisWorkflow(payload)
    currentWorkflowId.value = data.workflow_id
    persistWorkflow(payload)
    workflowState.value = null
    await loadWorkflowState()
    startWorkflowPolling()
    ElMessage.success('工作流已开始')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    workflowLoading.value = false
  }
}

async function pauseWorkflow() {
  if (currentWorkflowId.value === '') {
    return
  }
  workflowLoading.value = true
  try {
    workflowState.value = await pauseSynthesisWorkflow(currentWorkflowId.value)
    ElMessage.success('工作流已暂停')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    workflowLoading.value = false
  }
}

async function resumeWorkflow() {
  if (currentWorkflowId.value === '') {
    return
  }
  workflowLoading.value = true
  try {
    workflowState.value = await resumeSynthesisWorkflow(currentWorkflowId.value)
    startWorkflowPolling()
    ElMessage.success('工作流已恢复')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    workflowLoading.value = false
  }
}

async function stopWorkflow() {
  if (currentWorkflowId.value === '') {
    return
  }
  workflowLoading.value = true
  try {
    workflowState.value = await stopSynthesisWorkflow(currentWorkflowId.value)
    startWorkflowPolling()
    ElMessage.success('工作流已停止')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    workflowLoading.value = false
  }
}

async function loadWorkflowState(
  options: { showError?: boolean; clearOnError?: boolean; stopOnError?: boolean } = {},
): Promise<boolean> {
  if (currentWorkflowId.value === '') {
    return false
  }
  try {
    const data = await fetchSynthesisWorkflow(currentWorkflowId.value)
    workflowState.value = data
    syncWorkflowInfoFromState(data)
    if (isWorkflowTerminal(data.status) === true) {
      stopWorkflowPolling()
    }
    return true
  } catch (error) {
    if (options.stopOnError !== false) {
      stopWorkflowPolling()
    }
    if (options.clearOnError === true) {
      currentWorkflowId.value = ''
      workflowState.value = null
      clearStoredWorkflow()
    }
    if (options.showError !== false) {
      ElMessage.error(getErrorMessage(error))
    }
    return false
  }
}

function startWorkflowPolling() {
  if (currentWorkflowId.value === '') {
    return
  }
  stopWorkflowPolling()
  workflowTimer = window.setInterval(() => {
    void loadWorkflowState({ showError: false, stopOnError: false })
  }, 1200)
}

function stopWorkflowPolling() {
  if (workflowTimer !== undefined) {
    window.clearInterval(workflowTimer)
    workflowTimer = undefined
  }
}

function isWorkflowTerminal(statusText: string): boolean {
  return statusText === 'succeeded' || statusText === 'failed' || statusText === 'stopped'
}

function workflowStepState(stepId: WorkflowStepId) {
  if (workflowState.value === null) {
    return null
  }
  return workflowState.value.steps.find((step) => step.id === stepId) ?? null
}

function workflowStepStatus(stepId: WorkflowStepId): string {
  const state = workflowStepState(stepId)
  if (state !== null) {
    return state.status
  }
  if (workflowSteps.value[workflowStartStepIndex.value]?.id === stepId) {
    return 'selected'
  }
  return 'pending'
}

function workflowStepStatusText(stepId: WorkflowStepId): string {
  const map: Record<string, string> = {
    pending: '待执行',
    selected: '起点',
    running: '运行中',
    succeeded: '完成',
    failed: '失败',
    skipped: '跳过',
    stopped: '已停止',
  }
  const statusText = workflowStepStatus(stepId)
  return map[statusText] || statusText
}

function workflowStepIndex(stepId: WorkflowStepId): number {
  return workflowSteps.value.findIndex((step) => step.id === stepId) + 1
}

function workflowStepLabel(stepId: WorkflowStepId): string {
  if (stepId === 'batch_in') {
    if (workflowBatchInMode.value === 'manual') {
      return '手动上料'
    }
    return 'AGV上料'
  }
  return workflowSteps.value.find((step) => step.id === stepId)?.label ?? stepId
}

function workflowStepClass(stepId: WorkflowStepId): string {
  return `workflow-step-${workflowStepStatus(stepId)}`
}
</script>

<template>
  <div class="view-stack" v-loading="templateLoading">
    <section :class="['panel', 'workflow-panel', workflowPanelClass]">
      <div class="panel-title workflow-panel-title">
        <h2>工作流</h2>
        <el-button size="small" :icon="Refresh" :disabled="workflowLocked" @click="loadWorkflowDefaults">
          重载任务信息
        </el-button>
      </div>

      <div class="workflow-panel-body">
        <section class="workflow-header">
          <div class="workflow-form-grid">
            <el-form-item label="实验ID" class="settings-item">
              <el-input v-model="workflowExperimentId" placeholder="实验ID" :disabled="workflowLocked" />
            </el-form-item>
            <el-form-item label="实验名称" class="settings-item">
              <el-input v-model="workflowExperimentName" placeholder="实验名称" :disabled="workflowLocked" />
            </el-form-item>
            <el-form-item label="开始步骤" class="settings-item">
              <el-select v-model="workflowStartStepIndex" style="width: 100%" :disabled="workflowLocked">
                <el-option
                  v-for="(step, index) in workflowSteps"
                  :key="step.id"
                  :label="`${index + 1}. ${workflowStepLabel(step.id)}`"
                  :value="index"
                />
              </el-select>
            </el-form-item>
          </div>

          <div class="button-row workflow-actions">
            <el-tag :type="workflowStatusType">{{ workflowStatusText }}</el-tag>
            <el-button
              type="primary"
              :icon="VideoPlay"
              :loading="workflowLoading"
              :disabled="workflowCanStart === false"
              @click="startWorkflow"
            >
              开始
            </el-button>
            <el-button
              type="warning"
              :icon="VideoPause"
              :loading="workflowLoading"
              :disabled="workflowCanPause === false"
              @click="pauseWorkflow"
            >
              暂停
            </el-button>
            <el-button
              type="danger"
              :icon="CircleClose"
              :loading="workflowLoading"
              :disabled="workflowCanStop === false"
              @click="stopWorkflow"
            >
              停止
            </el-button>
            <el-button
              type="success"
              :icon="VideoPlay"
              :loading="workflowLoading"
              :disabled="workflowCanResume === false"
              @click="resumeWorkflow"
            >
              恢复
            </el-button>
            <el-button :icon="Refresh" :disabled="currentWorkflowId === ''" @click="loadWorkflowState">
              刷新
            </el-button>
          </div>
        </section>

        <section class="workflow-track">
          <div
            class="workflow-steps"
            :style="{ gridTemplateColumns: `repeat(${workflowSteps.length}, minmax(132px, 1fr))` }"
          >
            <button
              v-for="step in workflowSteps"
              :key="step.id"
              type="button"
              :disabled="workflowLocked"
              :class="['workflow-step-card', workflowStepClass(step.id)]"
              @click="openWorkflowStepDialog(step.id)"
            >
              <span class="workflow-step-index">{{ workflowStepIndex(step.id) }}</span>
              <span class="workflow-step-main">
                <span class="workflow-step-name">{{ workflowStepLabel(step.id) }}</span>
                <span class="workflow-step-status">{{ workflowStepStatusText(step.id) }}</span>
              </span>
              <el-icon><Edit /></el-icon>
            </button>
          </div>
          <el-slider
            v-model="workflowStartStepIndex"
            class="workflow-slider"
            :min="0"
            :max="workflowSteps.length - 1"
            :step="1"
            :marks="workflowSliderMarks"
            :disabled="workflowLocked"
            show-stops
          />
        </section>

        <section class="workflow-output">
          <div class="panel-title workflow-output-title">
            <h3>执行结果</h3>
            <el-tag v-if="currentWorkflowId !== ''" effect="plain">{{ currentWorkflowId }}</el-tag>
          </div>
          <div v-if="workflowState === null" class="muted">暂无运行结果</div>
          <template v-else>
            <ResultConsole :entries="workflowState.logs" empty-text="暂无运行结果" />
            <el-alert
              v-if="workflowState.error"
              style="margin-top: 12px"
              type="error"
              :title="workflowState.error"
              :closable="false"
            />
          </template>
        </section>
      </div>
    </section>

    <el-dialog
      v-model="workflowDialogVisible"
      :title="editingWorkflowStep === null ? '步骤参数' : `${editingWorkflowStep.label} 参数`"
      width="520px"
      destroy-on-close
    >
      <el-form label-width="140px">
        <template v-if="editingWorkflowStepId === 'batch_in'">
          <el-form-item label="上料方式">
            <el-radio-group v-model="workflowBatchInMode" :disabled="workflowLocked">
              <el-radio-button label="manual">手动上料</el-radio-button>
              <el-radio-button label="agv">AGV上料</el-radio-button>
            </el-radio-group>
          </el-form-item>
        </template>
        <template v-else-if="editingWorkflowStepId === 'start_task'">
          <el-form-item label="检测水氧">
            <el-switch v-model="workflowCheckGloveboxEnv" :disabled="workflowLocked" />
          </el-form-item>
          <el-form-item label="水上限(ppm)">
            <el-input-number
              v-model="workflowWaterLimit"
              :min="0.1"
              :step="0.1"
              :disabled="workflowLocked || workflowCheckGloveboxEnv === false"
            />
          </el-form-item>
          <el-form-item label="氧上限(ppm)">
            <el-input-number
              v-model="workflowOxygenLimit"
              :min="0.1"
              :step="0.1"
              :disabled="workflowLocked || workflowCheckGloveboxEnv === false"
            />
          </el-form-item>
        </template>
        <template v-else-if="editingWorkflowStepId === 'wait_task'">
          <el-form-item label="轮询间隔(秒)">
            <el-input-number v-model="workflowWaitPollInterval" :min="1" :step="1" :disabled="workflowLocked" />
          </el-form-item>
        </template>
        <template v-else-if="editingWorkflowStepId === 'submit_analysis'">
          <el-form-item label="AGV转移完成后立即提交">
            <el-switch v-model="workflowAutoSubmitAnalysisAfterAgv" :disabled="workflowLocked" />
          </el-form-item>
        </template>
        <template v-else-if="editingWorkflowStepId === 'poll_analysis'">
          <el-form-item label="轮询间隔(秒)">
            <el-input-number v-model="workflowAnalysisPollInterval" :min="1" :step="1" :disabled="workflowLocked" />
          </el-form-item>
        </template>
        <template v-else>
          <p class="muted dialog-muted">该步骤无单独参数</p>
        </template>
      </el-form>
      <template #footer>
        <el-button type="primary" @click="workflowDialogVisible = false">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.workflow-panel {
  padding: 14px;
}

.workflow-panel-succeeded {
  background: #f0fdf4;
  border-color: #86efac;
}

.workflow-panel-failed {
  background: #fff5f5;
  border-color: #f0a39a;
}

.workflow-panel-title {
  margin-bottom: 10px;
}

.workflow-panel-body {
  display: grid;
  gap: 16px;
  min-width: 0;
}

.workflow-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 14px;
  align-items: end;
  min-width: 0;
}

.workflow-form-grid {
  display: grid;
  grid-template-columns: 150px minmax(220px, 1fr) 220px;
  gap: 8px 12px;
  align-items: start;
  min-width: 0;
}

.settings-item {
  margin-bottom: 0;
}

.settings-item :deep(.el-form-item__label) {
  display: flex;
  align-items: center;
  min-height: 32px;
  line-height: 16px;
}

.settings-item :deep(.el-form-item__content) {
  min-width: 0;
}

.settings-item :deep(.el-input__wrapper),
.settings-item :deep(.el-select__wrapper) {
  min-height: 32px;
}

.workflow-actions {
  justify-content: flex-end;
  align-items: center;
  padding-bottom: 1px;
}

.workflow-track {
  min-width: 0;
  padding: 12px 2px 4px;
}

.workflow-steps {
  display: grid;
  grid-template-columns: repeat(7, minmax(132px, 1fr));
  gap: 10px;
  min-width: 0;
  overflow-x: auto;
  padding-bottom: 10px;
}

.workflow-step-card {
  display: grid;
  grid-template-columns: 26px minmax(0, 1fr) 18px;
  align-items: center;
  gap: 8px;
  min-width: 132px;
  min-height: 74px;
  padding: 10px;
  color: #24344d;
  text-align: left;
  background: #ffffff;
  border: 1px solid #dce5f0;
  border-radius: 8px;
  cursor: pointer;
}

.workflow-step-card:hover {
  border-color: #1a75cf;
  box-shadow: 0 8px 18px rgba(26, 117, 207, 0.12);
}

.workflow-step-card:disabled {
  cursor: not-allowed;
}

.workflow-step-card:disabled:hover {
  box-shadow: none;
}

.workflow-step-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  color: #ffffff;
  font-size: 13px;
  font-weight: 700;
  background: #6a7a90;
  border-radius: 50%;
}

.workflow-step-main {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.workflow-step-name {
  overflow: hidden;
  color: #12325a;
  font-size: 13px;
  font-weight: 700;
  line-height: 18px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workflow-step-status {
  color: #66758a;
  font-size: 12px;
  line-height: 16px;
}

.workflow-step-selected {
  background: #eef7ff;
  border-color: #1a75cf;
}

.workflow-step-selected .workflow-step-index {
  background: #1a75cf;
}

.workflow-step-running {
  background: #fff3e2;
  border-color: #f59e0b;
}

.workflow-step-running .workflow-step-index {
  background: #f59e0b;
}

.workflow-step-succeeded {
  background: #edf8f2;
  border-color: #8fd3ac;
}

.workflow-step-succeeded .workflow-step-index {
  background: #168a4f;
}

.workflow-step-failed {
  background: #fff2f0;
  border-color: #f0a39a;
}

.workflow-step-failed .workflow-step-index {
  background: #d6422b;
}

.workflow-step-skipped {
  color: #8793a4;
  background: #f7f9fc;
}

.workflow-step-skipped .workflow-step-index {
  background: #a8b3c2;
}

.workflow-step-stopped {
  background: #fff2f0;
  border-color: #f0a39a;
}

.workflow-step-stopped .workflow-step-index {
  background: #d6422b;
}

.workflow-slider {
  width: calc(100% - 22px);
  margin: 4px 11px 0;
}

.workflow-output {
  min-width: 0;
}

.workflow-output-title {
  margin-bottom: 10px;
}

.dialog-muted {
  margin: 0;
}

@media (max-width: 767.98px) {
  .workflow-form-grid,
  .workflow-header {
    grid-template-columns: 1fr;
  }

  .workflow-actions {
    justify-content: flex-start;
    flex-wrap: wrap;
  }

  /* 步骤卡: 手机端 2 列网格, 而非随步骤数横铺 */
  .workflow-steps {
    grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
  }

  .workflow-step-card {
    min-height: 76px;
    padding: 10px;
  }
}
</style>
