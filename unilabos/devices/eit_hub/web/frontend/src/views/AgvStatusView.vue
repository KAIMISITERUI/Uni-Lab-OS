<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  type AgvMapResponse,
  type AgvStatusResponse,
  type BatteryHistoryRecord,
  type ChargingStandby,
  armGripper,
  armHome,
  armPowerOff,
  armPowerOn,
  armQuickChange,
  armStop,
  batchTransferMaterials,
  chargingCheckOnce,
  connectArm,
  connectChassis,
  disconnectArm,
  disconnectChassis,
  fetchAgvMap,
  fetchAgvStatus,
  fetchBatteryHistory,
  navigateToStation,
  startCharging,
  stopCharging,
  transferMaterial,
} from '../api/agv'
import { getErrorMessage } from '../api/http'
import AgvMapView from '../components/AgvMapView.vue'
import ArmJogPanel from '../components/ArmJogPanel.vue'
import BatteryChart from '../components/BatteryChart.vue'
import JobPanel from '../components/JobPanel.vue'

const status = ref<AgvStatusResponse | null>(null)
const mapData = ref<AgvMapResponse | null>(null)
const historyRecords = ref<BatteryHistoryRecord[]>([])
const historyHours = ref(6)

const currentJobId = ref('')
const actionLoading = ref('')

const transferForm = ref({ source_tray: '', target_tray: '', material_type: '' })
const chargingForm = ref({
  standby: 'PP5' as ChargingStandby,
  interval_minutes: 30,
  retry_wait_minutes: 5,
  low_battery_pct: 50,
})

let statusTimer: number | undefined
let historyTimer: number | undefined

const connections = computed(() => status.value?.connections ?? { chassis_connected: false, arm_connected: false })
const isChassisConnected = computed(() => connections.value.chassis_connected === true)
const isArmConnected = computed(() => connections.value.arm_connected === true)

const batteryLevelPct = computed(() => {
  const level = status.value?.battery?.battery_level
  if (typeof level !== 'number') {
    const latest = status.value?.battery_latest?.battery_level
    if (typeof latest === 'number') {
      return Math.round(latest * 100)
    }
    return null
  }
  return Math.round(level * 100)
})

const batteryCharging = computed(() => {
  if (typeof status.value?.battery?.charging === 'boolean') {
    return status.value.battery.charging
  }
  return status.value?.battery_latest?.charging ?? false
})

const stationText = computed(() => {
  const s = status.value?.station
  if (s === null || s === undefined) {
    return '--'
  }
  return `${s.station_id} · ${s.description || s.station_name}`
})

const navTaskText = computed(() => {
  const t = status.value?.nav_task
  if (t === null || t === undefined) {
    return '空闲'
  }
  const statusName = t.task_status_name ?? t.task_status ?? '未知'
  const target = t.target_id ? ` → ${t.target_id}` : ''
  return `${statusName}${target}`
})

const gripperText = computed(() => {
  const g = status.value?.gripper_state
  const name = status.value?.current_gripper
  if (g === null || g === undefined) {
    return '--'
  }
  return name ? `${g} (${name})` : g
})

const slotsSummary = computed(() => {
  const slots = status.value?.slots
  if (slots === null || slots === undefined) {
    return { quickChange: [], tray: [] }
  }
  return { quickChange: slots.quick_change ?? [], tray: slots.tray ?? [] }
})

const isCharging = computed(() => status.value?.charge_loop?.running === true)

async function loadStatus() {
  try {
    const data = await fetchAgvStatus()
    status.value = data
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  }
}

async function loadMap() {
  try {
    const data = await fetchAgvMap()
    mapData.value = data
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  }
}

async function loadHistory() {
  try {
    const data = await fetchBatteryHistory(historyHours.value)
    historyRecords.value = data.records
  } catch (error) {
    // 电量历史失败不打扰用户, 仅静默
  }
}

function startAutoRefresh() {
  stopAutoRefresh()
  loadStatus()
  loadMap()
  loadHistory()
  statusTimer = window.setInterval(loadStatus, 2000)
  historyTimer = window.setInterval(loadHistory, 60000)
}

let autoConnectInFlight = false

async function ensureAutoConnect() {
  if (autoConnectInFlight === true) {
    return
  }
  autoConnectInFlight = true
  try {
    // 若 status 还未加载完成则先刷新一次, 避免在 null 快照下重复发请求
    if (status.value === null) {
      await loadStatus()
    }
    const snapshot = status.value?.connections
    const chassisOk = snapshot?.chassis_connected === true
    const armOk = snapshot?.arm_connected === true

    if (chassisOk === false) {
      try {
        await connectChassis()
      } catch (error) {
        ElMessage.warning(`AGV 底盘自动连接失败: ${getErrorMessage(error)}`)
      }
    }
    if (armOk === false) {
      try {
        await connectArm()
      } catch (error) {
        ElMessage.warning(`机械臂自动连接失败: ${getErrorMessage(error)}`)
      }
    }
    await loadStatus()
    await loadMap()
  } finally {
    autoConnectInFlight = false
  }
}

function stopAutoRefresh() {
  if (statusTimer !== undefined) {
    window.clearInterval(statusTimer)
    statusTimer = undefined
  }
  if (historyTimer !== undefined) {
    window.clearInterval(historyTimer)
    historyTimer = undefined
  }
}

// ==================== 连接控制 ====================

async function runSimpleAction(key: string, fn: () => Promise<unknown>, successMsg: string) {
  if (actionLoading.value !== '') {
    return
  }
  actionLoading.value = key
  try {
    await fn()
    ElMessage.success(successMsg)
    await loadStatus()
    await loadMap()
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    actionLoading.value = ''
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

function handleConnectChassis() {
  runSimpleAction('chassis-connect', connectChassis, 'AGV 底盘已连接')
}

function handleDisconnectChassis() {
  runSimpleAction('chassis-disconnect', disconnectChassis, 'AGV 底盘已断开')
}

function handleConnectArm() {
  runSimpleAction('arm-connect', connectArm, '机械臂已连接')
}

function handleDisconnectArm() {
  runSimpleAction('arm-disconnect', disconnectArm, '机械臂已断开')
}

function handleArmPowerOn() {
  runJobAction('arm-power-on', armPowerOn)
}

function handleArmPowerOff() {
  runJobAction('arm-power-off', armPowerOff)
}

function handleArmHome() {
  runJobAction('arm-home', armHome)
}

async function handleArmStop() {
  try {
    await armStop()
    ElMessage.success('已发送停止指令')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  }
}

function handleQuickChange(action: 'lock' | 'release') {
  runJobAction(`quick-${action}`, () => armQuickChange(action))
}

function handleGripper(action: 'open' | 'close') {
  runJobAction(`gripper-${action}`, () => armGripper(action))
}

// ==================== 导航与转运 ====================

async function handleStationSelect(stationId: string) {
  if (isCharging.value === true) {
    ElMessage.warning('充电循环运行中, 请先停止后再手动导航')
    return
  }
  try {
    await ElMessageBox.confirm(`确认导航到 ${stationId} ?`, '导航确认', {
      confirmButtonText: '确认',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  runJobAction(`navigate-${stationId}`, () => navigateToStation(stationId))
}

function handleTransfer() {
  const payload = {
    source_tray: transferForm.value.source_tray.trim(),
    target_tray: transferForm.value.target_tray.trim(),
    material_type: transferForm.value.material_type.trim() || null,
  }
  if (payload.source_tray === '' || payload.target_tray === '') {
    ElMessage.warning('请填写源托盘和目标托盘')
    return
  }
  runJobAction('transfer', () => transferMaterial(payload))
}

// ==================== 充电管理 ====================

function handleStartCharging() {
  runSimpleAction(
    'charging-start',
    () =>
      startCharging({
        standby: chargingForm.value.standby,
        interval_minutes: chargingForm.value.interval_minutes,
        retry_wait_minutes: chargingForm.value.retry_wait_minutes,
        low_battery_pct: chargingForm.value.low_battery_pct,
      }),
    '充电循环已启动',
  )
}

function handleStopCharging() {
  runSimpleAction('charging-stop', stopCharging, '充电循环已停止')
}

function handleChargingCheckOnce() {
  runJobAction('charging-check-once', () =>
    chargingCheckOnce({ low_battery_pct: chargingForm.value.low_battery_pct }),
  )
}

function onHistoryHoursChange(value: number) {
  historyHours.value = value
  loadHistory()
}

// ==================== 生命周期 ====================

onMounted(() => {
  startAutoRefresh()
  ensureAutoConnect()
})
onActivated(() => {
  startAutoRefresh()
  ensureAutoConnect()
})
onDeactivated(() => {
  stopAutoRefresh()
})
onBeforeUnmount(() => {
  stopAutoRefresh()
})
</script>

<template>
  <div class="view-stack">
    <!-- 状态仪表盘 -->
    <section class="panel">
      <div class="panel-title">
        <h2>AGV 综合状态</h2>
        <div class="button-row">
          <el-button
            v-if="isChassisConnected === false"
            type="primary"
            :loading="actionLoading === 'chassis-connect'"
            @click="handleConnectChassis"
          >连接底盘</el-button>
          <el-button
            v-else
            :loading="actionLoading === 'chassis-disconnect'"
            @click="handleDisconnectChassis"
          >断开底盘</el-button>
          <el-button
            v-if="isArmConnected === false"
            type="primary"
            :loading="actionLoading === 'arm-connect'"
            @click="handleConnectArm"
          >连接机械臂</el-button>
          <el-button
            v-else
            :loading="actionLoading === 'arm-disconnect'"
            @click="handleDisconnectArm"
          >断开机械臂</el-button>
        </div>
      </div>

      <div class="metrics-grid">
        <div class="metric">
          <div class="metric-label">AGV 站点</div>
          <div class="metric-value">{{ stationText }}</div>
          <div class="metric-note">导航: {{ navTaskText }}</div>
        </div>
        <div class="metric">
          <div class="metric-label">电池电量</div>
          <div class="metric-value">
            <template v-if="batteryLevelPct !== null">{{ batteryLevelPct }} %</template>
            <template v-else>--</template>
          </div>
          <div class="metric-note">
            <el-tag v-if="batteryCharging" size="small" type="success">充电中</el-tag>
            <el-tag v-else size="small">未充电</el-tag>
          </div>
        </div>
        <div class="metric">
          <div class="metric-label">底盘连接</div>
          <div class="metric-value">
            <el-tag :type="isChassisConnected ? 'success' : 'info'">
              {{ isChassisConnected ? '已连接' : '未连接' }}
            </el-tag>
          </div>
          <div class="metric-note">19204 / 19206</div>
        </div>
        <div class="metric">
          <div class="metric-label">机械臂连接</div>
          <div class="metric-value">
            <el-tag :type="isArmConnected ? 'success' : 'info'">
              {{ isArmConnected ? '已连接' : '未连接' }}
            </el-tag>
          </div>
          <div class="metric-note">{{ gripperText }}</div>
        </div>
      </div>

      <div class="slot-section">
        <div class="slot-row">
          <el-tag
            v-for="(occupied, idx) in slotsSummary.quickChange"
            :key="`qc-${idx}`"
            :type="occupied ? 'success' : 'info'"
          >
            快换{{ idx + 1 }}: {{ occupied ? '有料' : '空' }}
          </el-tag>
        </div>
        <div class="slot-row">
          <el-tag
            v-for="(occupied, idx) in slotsSummary.tray"
            :key="`tr-${idx}`"
            :type="occupied ? 'success' : 'info'"
          >
            托盘{{ idx + 1 }}: {{ occupied ? '有料' : '空' }}
          </el-tag>
        </div>
      </div>
    </section>

    <!-- 中间: 可视化地图 + 基础控制 + 物料转移 -->
    <div class="agv-bottom-layout">
      <!-- 左列: 地图 -->
      <section class="panel">
        <div class="panel-title">
          <h3>工站地图</h3>
          <el-tag v-if="isCharging" type="warning">循环运行中, 手动导航不可用</el-tag>
        </div>
        <AgvMapView
          :stations="mapData?.stations ?? []"
          :current-station-id="mapData?.current_station_id ?? null"
          :disabled="isCharging"
          @select="handleStationSelect"
        />
      </section>

      <!-- 右列: 基础控制 + 物料转移 -->
      <section class="panel">
        <div class="panel-title">
          <h3>基础控制</h3>
        </div>
        <div class="button-row">
          <el-button :loading="actionLoading === 'arm-power-on'" @click="handleArmPowerOn" :disabled="!isArmConnected">上电上使能</el-button>
          <el-button :loading="actionLoading === 'arm-power-off'" @click="handleArmPowerOff" :disabled="!isArmConnected">下使能下电</el-button>
          <el-button :loading="actionLoading === 'arm-home'" @click="handleArmHome" :disabled="!isArmConnected">机械臂回零</el-button>
          <el-button type="danger" @click="handleArmStop">立即停止</el-button>
        </div>
        <div class="button-row" style="margin-top: 10px">
          <el-button :loading="actionLoading === 'quick-release'" @click="handleQuickChange('release')" :disabled="!isArmConnected">松开快换</el-button>
          <el-button :loading="actionLoading === 'quick-lock'" @click="handleQuickChange('lock')" :disabled="!isArmConnected">夹紧快换</el-button>
          <el-button :loading="actionLoading === 'gripper-open'" @click="handleGripper('open')" :disabled="!isArmConnected">张开夹爪</el-button>
          <el-button :loading="actionLoading === 'gripper-close'" @click="handleGripper('close')" :disabled="!isArmConnected">闭合夹爪</el-button>
        </div>

        <el-divider />

        <div class="panel-title">
          <h3>物料转移</h3>
        </div>
        <el-form size="small" label-width="80px">
          <el-form-item label="源托盘">
            <el-input v-model="transferForm.source_tray" placeholder="例如 agv_tray_1" />
          </el-form-item>
          <el-form-item label="目标托盘">
            <el-input v-model="transferForm.target_tray" placeholder="例如 shelf_tray_1-1" />
          </el-form-item>
          <el-form-item label="物料类型">
            <el-input v-model="transferForm.material_type" placeholder="可留空" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="actionLoading === 'transfer'" @click="handleTransfer" :disabled="!isArmConnected">
              执行单次转移
            </el-button>
          </el-form-item>
        </el-form>
      </section>
    </div>

    <!-- 下方: 机械臂微调 + 充电 + 电量曲线 -->
    <div class="agv-bottom-layout">
      <section class="panel agv-jog-panel">
        <div class="panel-title">
          <h3>机械臂微调</h3>
        </div>
        <ArmJogPanel
          :disabled="!isArmConnected"
          :tcp-pose="status?.tcp_pose ?? null"
          :joints="status?.joints ?? null"
        />
      </section>

      <section class="panel agv-charge-panel">
        <div class="panel-title">
          <h3>充电管理</h3>
          <el-tag :type="isCharging ? 'success' : 'info'">
            {{ isCharging ? '循环运行中' : '未运行' }}
          </el-tag>
        </div>

        <el-form size="small" label-width="110px">
          <el-form-item label="待命点">
            <el-radio-group v-model="chargingForm.standby">
              <el-radio-button label="CP6">CP6 充电点</el-radio-button>
              <el-radio-button label="PP5">PP5 待冲点</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="检查间隔">
            <el-input-number v-model="chargingForm.interval_minutes" :min="1" :max="180" />
            <span class="unit">分钟</span>
          </el-form-item>
          <el-form-item label="重试等待">
            <el-input-number v-model="chargingForm.retry_wait_minutes" :min="1" :max="60" />
            <span class="unit">分钟</span>
          </el-form-item>
          <el-form-item label="电量阈值">
            <el-input-number v-model="chargingForm.low_battery_pct" :min="10" :max="90" />
            <span class="unit">%</span>
          </el-form-item>
          <el-form-item>
            <el-button
              v-if="isCharging === false"
              type="primary"
              :loading="actionLoading === 'charging-start'"
              @click="handleStartCharging"
              :disabled="!isChassisConnected"
            >启动循环</el-button>
            <el-button
              v-else
              type="danger"
              :loading="actionLoading === 'charging-stop'"
              @click="handleStopCharging"
            >停止循环</el-button>
            <el-button
              :loading="actionLoading === 'charging-check-once'"
              @click="handleChargingCheckOnce"
              :disabled="!isChassisConnected"
            >执行单次检查</el-button>
          </el-form-item>
        </el-form>

        <div v-if="status?.charge_loop?.last_action" class="muted" style="font-size: 12px;">
          上次动作: {{ JSON.stringify(status.charge_loop.last_action) }}
        </div>
      </section>
    </div>

    <!-- 电量曲线 -->
    <section class="panel">
      <div class="panel-title">
        <h3>电量历史</h3>
        <el-radio-group v-model="historyHours" size="small" @change="onHistoryHoursChange">
          <el-radio-button :label="1">1 小时</el-radio-button>
          <el-radio-button :label="6">6 小时</el-radio-button>
          <el-radio-button :label="24">24 小时</el-radio-button>
        </el-radio-group>
      </div>
      <BatteryChart :records="historyRecords" :hours="historyHours" />
    </section>

    <!-- 任务运行结果 -->
    <JobPanel v-if="currentJobId !== ''" :job-id="currentJobId" source="agv" title="AGV 任务结果" />
  </div>
</template>

<style scoped>
.slot-section {
  margin-top: 16px;
  display: grid;
  gap: 8px;
}

.slot-section h4 {
  margin: 0;
  color: #34445d;
  font-size: 13px;
  font-weight: 600;
}

.slot-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.unit {
  margin-left: 8px;
  color: #66758a;
  font-size: 12px;
}

.agv-bottom-layout {
  display: grid;
  grid-template-columns: 1fr;
  gap: 16px;
  align-items: start;
  min-width: 0;
}

.agv-jog-panel,
.agv-charge-panel {
  min-width: 0;
}
</style>
