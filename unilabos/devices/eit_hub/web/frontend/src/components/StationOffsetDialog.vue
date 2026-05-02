<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  type StationCalibrationOffset,
  type StationOffsetPreviewResponse,
  type StationOffsetVector,
  type TrayPointOption,
  applyStationOffset,
  cleanupStationOffsetCalibration,
  fetchAgvJob,
  prepareStationOffsetCalibration,
  previewStationOffset,
} from '../api/agv'
import { getErrorMessage } from '../api/http'
import ArmJogPanel from './ArmJogPanel.vue'

type Step = 'select' | 'preparing' | 'jog' | 'preview' | 'finishing'

const dialogWidth = 'min(960px, 92vw)'

const props = defineProps<{
  visible: boolean
  trayOptions: TrayPointOption[]
  currentStationName: string
  tcpPose: number[] | null
  joints: number[] | null
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  applied: []
}>()

const dialogVisible = computed({
  get: () => props.visible,
  set: (v: boolean) => emit('update:visible', v),
})

const station = ref('agv')
const referenceTray = ref('')
const useLoadedTray = ref(false)
const sourceTray = ref('agv_tray_1')
const runVision = ref(false)
const moveToPoint = ref(true)
const step = ref<Step>('select')
const prepareJobId = ref('')
const visionOffset = ref<StationCalibrationOffset | null>(null)
const preview = ref<StationOffsetPreviewResponse | null>(null)
const busy = ref(false)

const stationOptions = computed(() => {
  const options: string[] = ['agv']
  if (props.currentStationName !== '' && props.currentStationName !== 'agv') {
    options.push(props.currentStationName)
  }
  return options
})

const filteredTrays = computed(() => {
  return props.trayOptions.filter((opt) => opt.name.startsWith(station.value))
})

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

watch(station, () => {
  referenceTray.value = ''
})

function resetState() {
  station.value = 'agv'
  referenceTray.value = ''
  useLoadedTray.value = false
  sourceTray.value = 'agv_tray_1'
  runVision.value = false
  moveToPoint.value = true
  step.value = 'select'
  prepareJobId.value = ''
  visionOffset.value = null
  preview.value = null
  busy.value = false
}

async function pollJob(jobId: string): Promise<{ vision_offset?: StationCalibrationOffset | null }> {
  return new Promise((resolve, reject) => {
    const timer = window.setInterval(async () => {
      try {
        const data = await fetchAgvJob(jobId)
        if (data.status === 'succeeded') {
          window.clearInterval(timer)
          const result = (data.result ?? {}) as { vision_offset?: StationCalibrationOffset | null }
          resolve(result)
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
  if (referenceTray.value.trim() === '') {
    ElMessage.warning('请选择参考点位')
    return
  }
  busy.value = true
  step.value = 'preparing'
  try {
    const resp = await prepareStationOffsetCalibration({
      station: station.value,
      reference_tray: referenceTray.value.trim(),
      use_loaded_tray: useLoadedTray.value,
      source_tray: sourceTray.value.trim() === '' ? 'agv_tray_1' : sourceTray.value.trim(),
      run_vision: station.value !== 'agv' && runVision.value,
      move_to_point: useLoadedTray.value === false ? moveToPoint.value : true,
    })
    prepareJobId.value = resp.job_id
    const jobResult = await pollJob(prepareJobId.value)
    visionOffset.value = jobResult.vision_offset ?? null
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
  busy.value = true
  try {
    preview.value = await previewStationOffset({
      station: station.value,
      reference_tray: referenceTray.value.trim(),
      vision_offset: visionOffset.value,
    })
    step.value = 'preview'
  } catch (err) {
    ElMessage.error(getErrorMessage(err))
  } finally {
    busy.value = false
  }
}

async function performCleanup() {
  try {
    const resp = await cleanupStationOffsetCalibration({
      reference_tray: referenceTray.value.trim(),
      use_loaded_tray: useLoadedTray.value,
    })
    if ('job_id' in resp && typeof resp.job_id === 'string' && resp.job_id !== '') {
      await pollJob(resp.job_id)
    }
  } catch (err) {
    ElMessage.error(getErrorMessage(err))
  }
}

async function handleApply() {
  if (preview.value === null) {
    return
  }
  busy.value = true
  step.value = 'finishing'
  try {
    const result = await applyStationOffset({
      station: station.value,
      offset: preview.value.offset,
    })
    ElMessage.success(`已应用偏移量, 成功更新 ${result.success_count} 个点位`)
    emit('applied')
    await performCleanup()
    dialogVisible.value = false
  } catch (err) {
    ElMessage.error(getErrorMessage(err))
    step.value = 'preview'
  } finally {
    busy.value = false
  }
}

async function handleSkipApply() {
  try {
    await ElMessageBox.confirm('确认仅查看不应用偏移量?', '确认', {
      confirmButtonText: '确认',
      cancelButtonText: '继续校准',
    })
  } catch {
    return
  }
  busy.value = true
  step.value = 'finishing'
  try {
    await performCleanup()
  } finally {
    busy.value = false
    dialogVisible.value = false
  }
}

async function handleDiscard() {
  try {
    await ElMessageBox.confirm('确认放弃当前校准?', '确认', {
      confirmButtonText: '放弃',
      cancelButtonText: '继续校准',
    })
  } catch {
    return
  }
  busy.value = true
  step.value = 'finishing'
  try {
    await performCleanup()
  } finally {
    busy.value = false
    dialogVisible.value = false
  }
}

function formatPoseLine(pose: number[] | null | undefined): string {
  if (pose === null || pose === undefined) {
    return '--'
  }
  return pose
    .map((value, index) => (index < 3 ? value.toFixed(3) : value.toFixed(6)))
    .join(', ')
}

function formatOffsetField(value: number, isAngle: boolean): string {
  return isAngle ? value.toFixed(6) : value.toFixed(3)
}
</script>

<template>
  <el-dialog
    v-model="dialogVisible"
    title="工站整体偏差校准"
    :width="dialogWidth"
    top="5vh"
    class="calibration-dialog"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    destroy-on-close
  >
    <el-steps :active="stepIndex" finish-status="success" align-center class="dialog-steps">
      <el-step title="选择参数" />
      <el-step title="准备" />
      <el-step title="微调" />
      <el-step title="预览" />
      <el-step title="收尾" />
    </el-steps>

    <!-- 步骤 1: 选择参数 -->
    <div v-if="step === 'select'" class="dialog-body">
      <el-form size="small" label-width="120px">
        <el-form-item label="校准工站">
          <el-radio-group v-model="station">
            <el-radio-button v-for="opt in stationOptions" :key="opt" :label="opt">
              {{ opt }}
            </el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="station !== 'agv'" label="先做视觉补偿">
          <el-switch v-model="runVision" />
          <span class="muted" style="margin-left: 8px">非 AGV 工站建议先跑 jspf 示教视觉补偿</span>
        </el-form-item>
        <el-form-item label="参考点位">
          <el-select
            v-model="referenceTray"
            placeholder="请选择"
            filterable
            style="width: 100%"
            :disabled="filteredTrays.length === 0"
          >
            <el-option
              v-for="opt in filteredTrays"
              :key="opt.name"
              :label="opt.label"
              :value="opt.name"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="校准方式">
          <el-radio-group v-model="useLoadedTray">
            <el-radio-button :label="false">空载</el-radio-button>
            <el-radio-button :label="true">带托盘</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="useLoadedTray" label="源托盘">
          <el-input v-model="sourceTray" />
        </el-form-item>
        <el-form-item v-if="useLoadedTray === false" label="运动到该点">
          <el-switch v-model="moveToPoint" />
        </el-form-item>
        <el-alert
          v-if="useLoadedTray"
          type="info"
          :closable="false"
          title="带托盘提示"
          description="请确认已在 AGV 1 号位 (agv_tray_1) 放置托盘, 准备阶段会自动夹取并运动到目标点过渡位."
          show-icon
        />
      </el-form>
    </div>

    <!-- 步骤 2: 准备 -->
    <div v-else-if="step === 'preparing'" class="dialog-body">
      <el-result icon="info" title="准备中" sub-title="包含视觉补偿/取托盘/运动到参考点">
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
        title="准备完成, 请使用下方面板手动微调机械臂到参考点的精确位置"
        show-icon
      />
      <div v-if="visionOffset !== null" class="muted">
        视觉补偿偏移已记录: x={{ visionOffset.x.toFixed(3) }}, y={{ visionOffset.y.toFixed(3) }}, z={{ visionOffset.z.toFixed(3) }}
      </div>
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
        title="预览将要应用的偏移量"
        :description="`将影响 ${preview?.affected_trays.length ?? 0} 个点位`"
        show-icon
      />
      <div v-if="preview !== null" class="diff-grid">
        <div class="diff-cell"><span class="muted">Δx</span> {{ formatOffsetField(preview.offset.x, false) }} mm</div>
        <div class="diff-cell"><span class="muted">Δy</span> {{ formatOffsetField(preview.offset.y, false) }} mm</div>
        <div class="diff-cell"><span class="muted">Δz</span> {{ formatOffsetField(preview.offset.z, false) }} mm</div>
        <div class="diff-cell"><span class="muted">Δrx</span> {{ formatOffsetField(preview.offset.rx, true) }} rad</div>
        <div class="diff-cell"><span class="muted">Δry</span> {{ formatOffsetField(preview.offset.ry, true) }} rad</div>
        <div class="diff-cell"><span class="muted">Δrz</span> {{ formatOffsetField(preview.offset.rz, true) }} rad</div>
      </div>
      <div v-if="preview !== null" class="pose-block">
        <div><span class="muted">原始 pose:</span> {{ formatPoseLine(preview.original_pose) }}</div>
        <div><span class="muted">期望 pose:</span> {{ formatPoseLine(preview.expected_pose) }}</div>
        <div><span class="muted">当前 TCP:</span> {{ formatPoseLine(preview.current_pose) }}</div>
      </div>
      <details v-if="preview !== null">
        <summary>受影响点位 ({{ preview.affected_trays.length }})</summary>
        <ul class="trays-list">
          <li v-for="name in preview.affected_trays" :key="name">{{ name }}</li>
        </ul>
      </details>
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
        <el-button type="primary" :loading="busy" @click="handleComputePreview">计算偏移</el-button>
      </div>
      <div v-else-if="step === 'preview'">
        <el-button @click="handleDiscard">放弃</el-button>
        <el-button :loading="busy" @click="handleSkipApply">仅查看不应用</el-button>
        <el-button type="primary" :loading="busy" @click="handleApply">应用到所有点位</el-button>
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
.pose-block {
  display: grid;
  gap: 4px;
  padding: 10px 12px;
  background: #f7f9fc;
  border: 1px solid #dce5f0;
  border-radius: 8px;
  font-family: "Cascadia Mono", Consolas, monospace;
  font-size: 12px;
  word-break: break-all;
}
.trays-list {
  margin: 6px 0 0;
  padding-left: 18px;
  line-height: 1.6;
  font-family: "Cascadia Mono", Consolas, monospace;
  font-size: 12px;
}

@media (max-width: 767.98px) {
  /* x/y/z 三列偏移网格 -> 单列 */
  .diff-grid {
    grid-template-columns: 1fr;
  }
  .dialog-body {
    max-height: none;
  }
}
</style>
