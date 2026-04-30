<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  type TrayCalibrationPreview,
  type TrayPointOption,
  completeLoadedTrayCalibration,
  fetchAgvJob,
  moveToGraspPosition,
  prepareLoadedTrayCalibration,
  previewTrayCalibration,
  saveTrayCalibration,
} from '../api/agv'
import { getErrorMessage } from '../api/http'
import ArmJogPanel from './ArmJogPanel.vue'

type Mode = 'empty' | 'loaded'
type Step = 'select' | 'preparing' | 'jog' | 'preview' | 'finishing'

const dialogWidth = 'min(960px, 92vw)'

const props = defineProps<{
  visible: boolean
  trayOptions: TrayPointOption[]
  tcpPose: number[] | null
  joints: number[] | null
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  saved: []
}>()

const dialogVisible = computed({
  get: () => props.visible,
  set: (v: boolean) => emit('update:visible', v),
})

const targetTray = ref('')
const sourceTray = ref('agv_tray_1')
const mode = ref<Mode>('empty')
const step = ref<Step>('select')
const prepareJobId = ref('')
const preview = ref<TrayCalibrationPreview | null>(null)
const busy = ref(false)

const isLoaded = computed(() => mode.value === 'loaded')
const stepIndex = computed(() => {
  const map: Record<Step, number> = { select: 0, preparing: 1, jog: 2, preview: 3, finishing: 4 }
  return map[step.value]
})

watch(
  () => props.visible,
  (v) => {
    if (v === true) {
      resetState()
    }
  },
)

function resetState() {
  targetTray.value = ''
  sourceTray.value = 'agv_tray_1'
  mode.value = 'empty'
  step.value = 'select'
  prepareJobId.value = ''
  preview.value = null
  busy.value = false
}

async function pollJob(jobId: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = window.setInterval(async () => {
      try {
        const data = await fetchAgvJob(jobId)
        if (data.status === 'succeeded') {
          window.clearInterval(timer)
          resolve()
        } else if (data.status === 'failed') {
          window.clearInterval(timer)
          reject(new Error(data.error ?? '任务失败'))
        }
      } catch (err) {
        window.clearInterval(timer)
        reject(err)
      }
    }, 1200)
  })
}

async function handlePrepare() {
  const tray = targetTray.value.trim()
  if (tray === '') {
    ElMessage.warning('请选择目标托盘')
    return
  }
  busy.value = true
  step.value = 'preparing'
  try {
    if (mode.value === 'loaded') {
      const resp = await prepareLoadedTrayCalibration({
        target_tray: tray,
        source_tray: sourceTray.value.trim() === '' ? 'agv_tray_1' : sourceTray.value.trim(),
      })
      prepareJobId.value = resp.job_id
    } else {
      const resp = await moveToGraspPosition(tray)
      prepareJobId.value = resp.job_id
    }
    await pollJob(prepareJobId.value)
    step.value = 'jog'
    ElMessage.success('准备完成, 请使用机械臂微调')
  } catch (err) {
    ElMessage.error(getErrorMessage(err))
    step.value = 'select'
  } finally {
    busy.value = false
  }
}

async function handleComputePreview() {
  const tray = targetTray.value.trim()
  busy.value = true
  try {
    preview.value = await previewTrayCalibration(tray)
    step.value = 'preview'
  } catch (err) {
    ElMessage.error(getErrorMessage(err))
  } finally {
    busy.value = false
  }
}

async function handleSave() {
  if (preview.value === null) {
    return
  }
  const tray = targetTray.value.trim()
  busy.value = true
  step.value = 'finishing'
  try {
    await saveTrayCalibration({ tray_name: tray, pose: preview.value.pose_to_save })
    emit('saved')
    if (mode.value === 'loaded') {
      const resp = await completeLoadedTrayCalibration(tray)
      await pollJob(resp.job_id)
    }
    ElMessage.success('已保存校准结果')
    dialogVisible.value = false
  } catch (err) {
    ElMessage.error(getErrorMessage(err))
    step.value = 'preview'
  } finally {
    busy.value = false
  }
}

async function handleDiscard() {
  try {
    await ElMessageBox.confirm('确认放弃校准结果?', '确认', {
      confirmButtonText: '放弃',
      cancelButtonText: '继续校准',
    })
  } catch {
    return
  }
  if (mode.value === 'loaded') {
    busy.value = true
    step.value = 'finishing'
    try {
      const resp = await completeLoadedTrayCalibration(targetTray.value.trim())
      await pollJob(resp.job_id)
      ElMessage.info('已松爪并回零')
    } catch (err) {
      ElMessage.error(getErrorMessage(err))
    } finally {
      busy.value = false
    }
  }
  dialogVisible.value = false
}

function formatPoseLine(pose: number[] | null | undefined): string {
  if (pose === null || pose === undefined) {
    return '--'
  }
  return pose
    .map((value, index) => (index < 3 ? value.toFixed(3) : value.toFixed(6)))
    .join(', ')
}

function formatDelta(a: number | undefined, b: number | undefined, isAngle: boolean): string {
  if (a === undefined || b === undefined) {
    return '--'
  }
  const delta = b - a
  return isAngle ? delta.toFixed(6) : delta.toFixed(3)
}
</script>

<template>
  <el-dialog
    v-model="dialogVisible"
    title="托盘点位校准"
    :width="dialogWidth"
    top="5vh"
    class="calibration-dialog"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    destroy-on-close
  >
    <el-steps :active="stepIndex" finish-status="success" align-center class="dialog-steps">
      <el-step title="选择目标" />
      <el-step title="准备" />
      <el-step title="微调" />
      <el-step title="预览" />
      <el-step title="保存" />
    </el-steps>

    <!-- 步骤 1: 选择 -->
    <div v-if="step === 'select'" class="dialog-body">
      <el-form size="small" label-width="100px">
        <el-form-item label="目标托盘">
          <el-select v-model="targetTray" placeholder="请选择" filterable style="width: 100%">
            <el-option
              v-for="opt in props.trayOptions"
              :key="opt.name"
              :label="opt.label"
              :value="opt.name"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="校准方式">
          <el-radio-group v-model="mode">
            <el-radio-button label="empty">空载</el-radio-button>
            <el-radio-button label="loaded">带托盘</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="isLoaded" label="源托盘">
          <el-input v-model="sourceTray" placeholder="agv_tray_1" />
        </el-form-item>
        <el-alert
          v-if="isLoaded"
          type="info"
          :closable="false"
          title="带托盘提示"
          description="请确认已在 AGV 1 号位 (agv_tray_1) 放置托盘, 准备阶段会自动夹取并运动到目标点过渡位."
          show-icon
        />
      </el-form>
    </div>

    <!-- 步骤 2: 准备中 -->
    <div v-else-if="step === 'preparing'" class="dialog-body">
      <el-result icon="info" title="准备中" sub-title="正在执行机械臂运动, 请稍候">
        <template #extra>
          <el-tag type="warning">任务 {{ prepareJobId }}</el-tag>
        </template>
      </el-result>
    </div>

    <!-- 步骤 3: 微调 -->
    <div v-else-if="step === 'jog'" class="dialog-body">
      <el-alert
        type="success"
        :closable="false"
        title="准备完成, 请使用下方面板手动微调机械臂到精确位置"
        show-icon
      />
      <ArmJogPanel
        :tcp-pose="props.tcpPose"
        :joints="props.joints"
      />
    </div>

    <!-- 步骤 4: 预览 -->
    <div v-else-if="step === 'preview'" class="dialog-body">
      <el-alert
        type="warning"
        :closable="false"
        title="校准结果预览"
        :description="preview?.station_offset !== null ? '已自动减去工站校准偏移量, 落盘的是原始位姿' : '将直接保存当前 TCP 位姿'"
        show-icon
      />
      <el-table v-if="preview !== null" :data="[preview]" size="small" stripe>
        <el-table-column label="字段" width="120">
          <template #default>原始位姿</template>
        </el-table-column>
        <el-table-column label="值">
          <template #default>{{ formatPoseLine(preview!.original_pose) }}</template>
        </el-table-column>
      </el-table>
      <el-table v-if="preview !== null" :data="[preview]" size="small" stripe class="diff-table">
        <el-table-column label="字段" width="120">
          <template #default>当前 TCP</template>
        </el-table-column>
        <el-table-column label="值">
          <template #default>{{ formatPoseLine(preview!.current_pose) }}</template>
        </el-table-column>
      </el-table>
      <el-table v-if="preview !== null" :data="[preview]" size="small" stripe class="diff-table">
        <el-table-column label="字段" width="120">
          <template #default>待保存位姿</template>
        </el-table-column>
        <el-table-column label="值">
          <template #default>{{ formatPoseLine(preview!.pose_to_save) }}</template>
        </el-table-column>
      </el-table>
      <div v-if="preview !== null && preview.original_pose !== null" class="diff-grid">
        <div class="diff-cell">
          <span class="muted">Δx</span>
          {{ formatDelta(preview.original_pose[0], preview.pose_to_save[0], false) }}
        </div>
        <div class="diff-cell">
          <span class="muted">Δy</span>
          {{ formatDelta(preview.original_pose[1], preview.pose_to_save[1], false) }}
        </div>
        <div class="diff-cell">
          <span class="muted">Δz</span>
          {{ formatDelta(preview.original_pose[2], preview.pose_to_save[2], false) }}
        </div>
        <div class="diff-cell">
          <span class="muted">Δrx</span>
          {{ formatDelta(preview.original_pose[3], preview.pose_to_save[3], true) }}
        </div>
        <div class="diff-cell">
          <span class="muted">Δry</span>
          {{ formatDelta(preview.original_pose[4], preview.pose_to_save[4], true) }}
        </div>
        <div class="diff-cell">
          <span class="muted">Δrz</span>
          {{ formatDelta(preview.original_pose[5], preview.pose_to_save[5], true) }}
        </div>
      </div>
    </div>

    <!-- 步骤 5: 收尾 -->
    <div v-else-if="step === 'finishing'" class="dialog-body">
      <el-result icon="info" title="正在收尾" sub-title="请稍候" />
    </div>

    <template #footer>
      <div v-if="step === 'select'">
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="busy" @click="handlePrepare">开始准备</el-button>
      </div>
      <div v-else-if="step === 'preparing' || step === 'finishing'">
        <el-button disabled>处理中...</el-button>
      </div>
      <div v-else-if="step === 'jog'">
        <el-button @click="handleDiscard">放弃</el-button>
        <el-button type="primary" :loading="busy" @click="handleComputePreview">完成微调</el-button>
      </div>
      <div v-else-if="step === 'preview'">
        <el-button @click="handleDiscard">放弃</el-button>
        <el-button type="primary" :loading="busy" @click="handleSave">保存校准结果</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.dialog-steps {
  margin-bottom: 16px;
}
.dialog-body {
  display: grid;
  gap: 12px;
  max-height: 72vh;
  overflow-y: auto;
  padding-right: 4px;
}
.diff-table :deep(.el-table__header-wrapper) {
  display: none;
}
.diff-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px 16px;
  padding: 10px 12px;
  background: #f7f9fc;
  border: 1px solid #dce5f0;
  border-radius: 8px;
  font-family: "Cascadia Mono", Consolas, monospace;
  font-size: 12px;
}
.diff-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}
</style>
