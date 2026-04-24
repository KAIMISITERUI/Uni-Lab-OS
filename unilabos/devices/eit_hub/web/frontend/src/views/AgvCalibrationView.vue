<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  type AgvStatusResponse,
  type MiddleTrayRow,
  applyMiddleTray,
  calibrateStation,
  calibrateStationOffset,
  calibrateTray,
  completeLoadedTrayCalibration,
  fetchAgvStatus,
  moveToGraspPosition,
  prepareLoadedTrayCalibration,
  previewMiddleTray,
  recordLoadedTrayPose,
} from '../api/agv'
import { getErrorMessage } from '../api/http'
import ArmJogPanel from '../components/ArmJogPanel.vue'
import JobPanel from '../components/JobPanel.vue'

const status = ref<AgvStatusResponse | null>(null)
const currentJobId = ref('')
const actionLoading = ref('')

const trayForm = ref({ tray_name: '' })
const loadedTrayForm = ref({ target_tray: '', source_tray: 'agv_tray_1' })
const middleTrayForm = ref({ station_name: '' })
const middleTrayRows = ref<MiddleTrayRow[]>([])
const recordedPose = ref<number[] | null>(null)

let statusTimer: number | undefined

const connections = computed(() => status.value?.connections ?? { chassis_connected: false, arm_connected: false })
const isChassisConnected = computed(() => connections.value.chassis_connected === true)
const isArmConnected = computed(() => connections.value.arm_connected === true)

async function loadStatus() {
  try {
    const data = await fetchAgvStatus()
    status.value = data
  } catch (error) {
    // 静默忽略, 避免轮询失败打扰用户
  }
}

function startAutoRefresh() {
  stopAutoRefresh()
  loadStatus()
  statusTimer = window.setInterval(loadStatus, 2000)
}

function stopAutoRefresh() {
  if (statusTimer !== undefined) {
    window.clearInterval(statusTimer)
    statusTimer = undefined
  }
}

function runJobAction(key: string, fn: () => Promise<{ job_id: string }>) {
  if (actionLoading.value !== '') {
    return
  }
  actionLoading.value = key
  fn()
    .then((resp) => {
      currentJobId.value = resp.job_id
      ElMessage.success('任务已提交')
    })
    .catch((error) => {
      ElMessage.error(getErrorMessage(error))
    })
    .finally(() => {
      actionLoading.value = ''
    })
}

function handleCalibrateStation() {
  runJobAction('calibrate-station', calibrateStation)
}

function handleCalibrateStationOffset() {
  runJobAction('calibrate-station-offset', calibrateStationOffset)
}

function handleCalibrateTray() {
  const name = trayForm.value.tray_name.trim()
  if (name === '') {
    ElMessage.warning('请填写托盘名称')
    return
  }
  runJobAction('calibrate-tray', () => calibrateTray(name))
}

function handleMoveToGrasp() {
  const name = trayForm.value.tray_name.trim()
  if (name === '') {
    ElMessage.warning('请填写托盘名称')
    return
  }
  runJobAction('move-to-grasp', () => moveToGraspPosition(name))
}

function handlePrepareLoadedTray() {
  const target = loadedTrayForm.value.target_tray.trim()
  const source = loadedTrayForm.value.source_tray.trim()
  if (target === '' || source === '') {
    ElMessage.warning('请填写源托盘和目标托盘')
    return
  }
  runJobAction('loaded-prepare', () =>
    prepareLoadedTrayCalibration({ target_tray: target, source_tray: source }),
  )
}

async function handleRecordLoadedTrayPose() {
  const target = loadedTrayForm.value.target_tray.trim()
  if (target === '') {
    ElMessage.warning('请填写目标托盘')
    return
  }
  try {
    const resp = await recordLoadedTrayPose(target)
    recordedPose.value = resp.pose
    ElMessage.success('位姿已记录')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  }
}

function handleCompleteLoadedTray() {
  const target = loadedTrayForm.value.target_tray.trim()
  if (target === '') {
    ElMessage.warning('请填写目标托盘')
    return
  }
  runJobAction('loaded-complete', () => completeLoadedTrayCalibration(target))
}

async function handlePreviewMiddleTray() {
  const station = middleTrayForm.value.station_name.trim()
  if (station === '') {
    ElMessage.warning('请填写工站名称')
    return
  }
  try {
    const resp = await previewMiddleTray(station)
    middleTrayRows.value = resp.rows
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  }
}

async function handleApplyMiddleTray() {
  const station = middleTrayForm.value.station_name.trim()
  if (station === '') {
    ElMessage.warning('请填写工站名称')
    return
  }
  try {
    await ElMessageBox.confirm(`确认将中间托盘计算结果应用到 ${station} 的配置文件?`, '确认应用', {
      confirmButtonText: '确认',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    const resp = await applyMiddleTray(station)
    ElMessage.success(`已更新 ${resp.updated_count}, 新增 ${resp.created_count}`)
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  }
}

onMounted(startAutoRefresh)
onActivated(startAutoRefresh)
onDeactivated(stopAutoRefresh)
onBeforeUnmount(stopAutoRefresh)
</script>

<template>
  <div class="view-stack">
    <div class="two-column">
      <section class="panel">
        <div class="panel-title">
          <h3>工站点位校准</h3>
        </div>
        <p class="muted">
          运行 AGV 当前站点的 jspf 示教程序, 读取 TCP 位姿偏移并保存. 需要底盘和机械臂均已连接.
        </p>
        <div class="button-row">
          <el-button
            type="primary"
            :loading="actionLoading === 'calibrate-station'"
            :disabled="!isChassisConnected || !isArmConnected"
            @click="handleCalibrateStation"
          >执行工站点位校准</el-button>
          <el-button
            :loading="actionLoading === 'calibrate-station-offset'"
            :disabled="!isChassisConnected || !isArmConnected"
            @click="handleCalibrateStationOffset"
          >工站整体偏差矫正</el-button>
        </div>
      </section>

      <section class="panel">
        <div class="panel-title">
          <h3>托盘点位校准 (空载)</h3>
        </div>
        <el-form size="small" label-width="90px">
          <el-form-item label="托盘名称">
            <el-input v-model="trayForm.tray_name" placeholder="例如 agv_tray_1" />
          </el-form-item>
          <el-form-item>
            <el-button
              :loading="actionLoading === 'move-to-grasp'"
              :disabled="!isArmConnected"
              @click="handleMoveToGrasp"
            >运动到抓取点位</el-button>
            <el-button
              type="primary"
              :loading="actionLoading === 'calibrate-tray'"
              :disabled="!isArmConnected"
              @click="handleCalibrateTray"
            >执行空载校准</el-button>
          </el-form-item>
        </el-form>
      </section>
    </div>

    <div class="two-column">
      <section class="panel">
        <div class="panel-title">
          <h3>带托盘校准</h3>
        </div>
        <p class="muted">
          1. 填写源/目标托盘 → 点 "准备", AGV 从源托盘取托盘并运动到目标过渡点<br />
          2. 使用下方微调面板手动对准目标位置<br />
          3. 点 "记录当前位姿" → 计算并保存<br />
          4. 点 "收尾流程" 松开夹爪并回到 safe 位姿
        </p>
        <el-form size="small" label-width="90px">
          <el-form-item label="目标托盘">
            <el-input v-model="loadedTrayForm.target_tray" placeholder="例如 synthesis_station_tray_1-1" />
          </el-form-item>
          <el-form-item label="源托盘">
            <el-input v-model="loadedTrayForm.source_tray" />
          </el-form-item>
          <el-form-item>
            <el-button
              :loading="actionLoading === 'loaded-prepare'"
              :disabled="!isArmConnected"
              @click="handlePrepareLoadedTray"
            >准备</el-button>
            <el-button
              type="primary"
              :disabled="!isArmConnected"
              @click="handleRecordLoadedTrayPose"
            >记录当前位姿</el-button>
            <el-button
              :loading="actionLoading === 'loaded-complete'"
              :disabled="!isArmConnected"
              @click="handleCompleteLoadedTray"
            >收尾流程</el-button>
          </el-form-item>
        </el-form>
        <div v-if="recordedPose !== null" class="pose-display">
          已记录位姿: {{ recordedPose.map((v) => v.toFixed(3)).join(', ') }}
        </div>
      </section>

      <section class="panel">
        <div class="panel-title">
          <h3>中间托盘自动计算</h3>
        </div>
        <el-form size="small" label-width="90px">
          <el-form-item label="工站名称">
            <el-input v-model="middleTrayForm.station_name" placeholder="例如 synthesis_station" />
          </el-form-item>
          <el-form-item>
            <el-button @click="handlePreviewMiddleTray">预览</el-button>
            <el-button type="primary" @click="handleApplyMiddleTray">应用</el-button>
          </el-form-item>
        </el-form>
        <el-table v-if="middleTrayRows.length > 0" :data="middleTrayRows" size="small" stripe>
          <el-table-column label="行" prop="row_index" width="50" />
          <el-table-column label="目标托盘" prop="target_tray" />
          <el-table-column label="左" prop="left_tray" />
          <el-table-column label="右" prop="right_tray" />
          <el-table-column label="比例" prop="ratio" width="70">
            <template #default="{ row }">
              {{ Number(row.ratio).toFixed(2) }}
            </template>
          </el-table-column>
          <el-table-column label="存在" prop="exists" width="60">
            <template #default="{ row }">
              <el-tag :type="row.exists ? 'success' : 'warning'" size="small">
                {{ row.exists ? '是' : '否' }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
      </section>
    </div>

    <section class="panel">
      <div class="panel-title">
        <h3>机械臂微调</h3>
      </div>
      <ArmJogPanel
        :disabled="!isArmConnected"
        :tcp-pose="status?.tcp_pose ?? null"
        :joints="status?.joints ?? null"
      />
    </section>

    <JobPanel v-if="currentJobId !== ''" :job-id="currentJobId" source="agv" title="校准任务结果" />
  </div>
</template>

<style scoped>
.pose-display {
  margin-top: 8px;
  padding: 8px 12px;
  color: #12325a;
  font-family: "Cascadia Mono", Consolas, monospace;
  font-size: 12px;
  background: #f7f9fc;
  border: 1px solid #dce5f0;
  border-radius: 6px;
}
</style>
