<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  type AgvMapStation,
  type AgvMapResponse,
  type AgvStatusResponse,
  type BatteryHistoryRecord,
  type ChargingStandby,
  type TrayPointOption,
  armGripper,
  armHome,
  armPowerOff,
  armPowerOn,
  armQuickChange,
  armStop,
  chargingCheckOnce,
  connectArm,
  connectChassis,
  disconnectArm,
  disconnectChassis,
  fetchAgvMap,
  fetchAgvStatus,
  fetchBatteryHistory,
  fetchTrayOptions,
  navigateToStation,
  saveAgvMapLayout,
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
const mapDraftStations = ref<AgvMapStation[]>([])
const mapEditing = ref(false)
const mapSaving = ref(false)
const historyRecords = ref<BatteryHistoryRecord[]>([])
const historyHours = ref(6)
const trayOptions = ref<TrayPointOption[]>([])

const currentJobId = ref('')
const actionLoading = ref('')

type ArmStateField = 'drive_ready' | 'quick_change_locked' | 'gripper_open'
type HardwareActionGroup = 'drive' | 'quick-change' | 'gripper'
type ControlButtonType = 'primary' | 'success' | 'warning' | 'danger' | 'info'

interface SlotDisplayItem {
  key: string
  label: string
  occupied: boolean | null
}

interface HardwarePendingAction {
  key: string
  group: HardwareActionGroup
  targetField: ArmStateField
  targetValue: boolean
  jobFinished: boolean
}

type HardwareActionPlan = Omit<HardwarePendingAction, 'jobFinished'>

const pendingHardwareAction = ref<HardwarePendingAction | null>(null)

interface HardwareButtonView {
  key: string
  label: string
  type: ControlButtonType
  group: HardwareActionGroup
}

const transferForm = ref({ source_tray: '', target_tray: '', material_type: '' })
const chargingForm = ref({
  standby: 'PP5' as ChargingStandby,
  interval_minutes: 30,
  retry_wait_minutes: 5,
  low_battery_pct: 50,
})
const jogRefCoord = ref<'base' | 'tcp' | 'user'>('base')
const armJogPanelRef = ref<InstanceType<typeof ArmJogPanel> | null>(null)

let statusTimer: number | undefined
let historyTimer: number | undefined
let lastTrayStationId: string | null | undefined

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

const slotItems = computed<SlotDisplayItem[]>(() => {
  const slots = status.value?.slots
  const quickChange = slots?.quick_change ?? []
  const tray = slots?.tray ?? []
  return [
    ...Array.from({ length: 3 }, (_item, index) => ({
      key: `quick-${index + 1}`,
      label: `快换${index + 1}`,
      occupied: readSlotValue(quickChange, index),
    })),
    ...Array.from({ length: 4 }, (_item, index) => ({
      key: `tray-${index + 1}`,
      label: `托盘${index + 1}`,
      occupied: readSlotValue(tray, index),
    })),
  ]
})

const isCharging = computed(() => status.value?.charge_loop?.running === true)
const currentStationId = computed(() => status.value?.station?.station_id ?? mapData.value?.current_station_id ?? null)
const displayStations = computed(() => {
  if (mapEditing.value === true) {
    return mapDraftStations.value
  }
  return mapData.value?.stations ?? []
})
const armState = computed(() => {
  return status.value?.arm_state ?? {
    drive_ready: null,
    quick_change_locked: null,
    gripper_open: null,
  }
})

const driveButton = computed<HardwareButtonView>(() => {
  const pending = getPendingButton('drive')
  if (pending !== null) {
    return pending
  }
  if (armState.value.drive_ready === true) {
    return { key: 'arm-power-off', label: '下使能下电', type: 'warning', group: 'drive' }
  }
  return { key: 'arm-power-on', label: '上电使能', type: 'success', group: 'drive' }
})

const quickChangeButton = computed<HardwareButtonView>(() => {
  const pending = getPendingButton('quick-change')
  if (pending !== null) {
    return pending
  }
  if (armState.value.quick_change_locked === true) {
    return { key: 'quick-release', label: '松开快换', type: 'warning', group: 'quick-change' }
  }
  return { key: 'quick-lock', label: '夹紧快换', type: 'primary', group: 'quick-change' }
})

const gripperButton = computed<HardwareButtonView>(() => {
  const pending = getPendingButton('gripper')
  if (pending !== null) {
    return pending
  }
  if (armState.value.gripper_open === true) {
    return { key: 'gripper-close', label: '闭合夹爪', type: 'primary', group: 'gripper' }
  }
  return { key: 'gripper-open', label: '张开夹爪', type: 'success', group: 'gripper' }
})

function cloneStations(stations: AgvMapStation[]): AgvMapStation[] {
  return stations.map((station) => ({ ...station }))
}

function getPendingButton(group: HardwareActionGroup): HardwareButtonView | null {
  const pending = pendingHardwareAction.value
  if (pending === null || pending.group !== group) {
    return null
  }
  if (pending.key === 'arm-power-on') {
    return { key: pending.key, label: '上电使能', type: 'success', group }
  }
  if (pending.key === 'arm-power-off') {
    return { key: pending.key, label: '下使能下电', type: 'warning', group }
  }
  if (pending.key === 'quick-lock') {
    return { key: pending.key, label: '夹紧快换', type: 'primary', group }
  }
  if (pending.key === 'quick-release') {
    return { key: pending.key, label: '松开快换', type: 'warning', group }
  }
  if (pending.key === 'gripper-open') {
    return { key: pending.key, label: '张开夹爪', type: 'success', group }
  }
  return { key: pending.key, label: '闭合夹爪', type: 'primary', group }
}

function readSlotValue(values: boolean[], index: number): boolean | null {
  const value = values[index]
  if (typeof value !== 'boolean') {
    return null
  }
  return value
}

function slotTagType(occupied: boolean | null): 'success' | 'info' | 'warning' {
  if (occupied === true) {
    return 'success'
  }
  if (occupied === false) {
    return 'info'
  }
  return 'warning'
}

function slotStatusText(occupied: boolean | null): string {
  if (occupied === true) {
    return '有料'
  }
  if (occupied === false) {
    return '空'
  }
  return '未知'
}

function isActionLoading(key: string): boolean {
  return actionLoading.value === key || pendingHardwareAction.value?.key === key
}

function isHardwareActionDisabled(key: string, group: HardwareActionGroup): boolean {
  if (isArmConnected.value === false) {
    return true
  }
  if (actionLoading.value !== '' && actionLoading.value !== key) {
    return true
  }
  if (pendingHardwareAction.value !== null && pendingHardwareAction.value.group === group) {
    return pendingHardwareAction.value.key !== key
  }
  return false
}

function resolvePendingHardwareAction() {
  const pending = pendingHardwareAction.value
  if (pending === null) {
    return
  }
  if (pending.jobFinished === false) {
    return
  }
  const currentValue = armState.value[pending.targetField]
  if (typeof currentValue === 'boolean' && currentValue === pending.targetValue) {
    pendingHardwareAction.value = null
  }
}

function optionExists(optionName: string): boolean {
  return trayOptions.value.some((option) => option.name === optionName)
}

function syncTransferSelection() {
  if (transferForm.value.source_tray !== '' && optionExists(transferForm.value.source_tray) === false) {
    transferForm.value.source_tray = ''
  }
  if (transferForm.value.target_tray !== '' && optionExists(transferForm.value.target_tray) === false) {
    transferForm.value.target_tray = ''
  }
}

function formatTrayOption(option: TrayPointOption): string {
  if (option.description.trim() === '') {
    return option.name
  }
  return `${option.name} · ${option.description}`
}

async function loadStatus() {
  try {
    const data = await fetchAgvStatus()
    status.value = data
    if (data.connections.arm_connected === true) {
      resolvePendingHardwareAction()
    } else {
      pendingHardwareAction.value = null
    }
    const stationId = data.station?.station_id ?? null
    if (stationId !== lastTrayStationId) {
      lastTrayStationId = stationId
      await loadTrayOptions(stationId)
    }
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  }
}

async function loadMap() {
  try {
    const data = await fetchAgvMap()
    mapData.value = data
    if (mapEditing.value === false) {
      mapDraftStations.value = []
    }
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  }
}

async function loadTrayOptions(stationId: string | null = currentStationId.value) {
  try {
    const data = await fetchTrayOptions(stationId)
    trayOptions.value = data.options
    syncTransferSelection()
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
  statusTimer = window.setInterval(loadStatus, 5000)
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

function runJobAction(
  key: string,
  fn: () => Promise<{ job_id: string }>,
  options: { pendingAction?: HardwareActionPlan } = {},
) {
  if (actionLoading.value !== '') {
    return
  }
  actionLoading.value = key
  fn()
    .then((resp) => {
      currentJobId.value = resp.job_id
      if (options.pendingAction !== undefined) {
        pendingHardwareAction.value = { ...options.pendingAction, jobFinished: false }
      }
      ElMessage.success('任务已提交')
    })
    .catch((error) => {
      ElMessage.error(getErrorMessage(error))
    })
    .finally(() => {
      actionLoading.value = ''
    })
}

function runHardwareJobAction(pendingAction: HardwareActionPlan, fn: () => Promise<{ job_id: string }>) {
  if (armState.value[pendingAction.targetField] === pendingAction.targetValue) {
    return
  }
  runJobAction(pendingAction.key, fn, { pendingAction })
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
  runHardwareJobAction(
    { key: 'arm-power-on', group: 'drive', targetField: 'drive_ready', targetValue: true },
    armPowerOn,
  )
}

function handleArmPowerOff() {
  runHardwareJobAction(
    { key: 'arm-power-off', group: 'drive', targetField: 'drive_ready', targetValue: false },
    armPowerOff,
  )
}

function handleDriveAction() {
  if (driveButton.value.key === 'arm-power-off') {
    handleArmPowerOff()
    return
  }
  handleArmPowerOn()
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
  runHardwareJobAction(
    {
      key: `quick-${action}`,
      group: 'quick-change',
      targetField: 'quick_change_locked',
      targetValue: action === 'lock',
    },
    () => armQuickChange(action),
  )
}

function handleQuickChangeAction() {
  handleQuickChange(quickChangeButton.value.key === 'quick-release' ? 'release' : 'lock')
}

function handleGripper(action: 'open' | 'close') {
  runHardwareJobAction(
    {
      key: `gripper-${action}`,
      group: 'gripper',
      targetField: 'gripper_open',
      targetValue: action === 'open',
    },
    () => armGripper(action),
  )
}

function handleGripperAction() {
  handleGripper(gripperButton.value.key === 'gripper-close' ? 'close' : 'open')
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

function beginMapEdit() {
  mapDraftStations.value = cloneStations(mapData.value?.stations ?? [])
  mapEditing.value = true
}

function cancelMapEdit() {
  mapEditing.value = false
  mapDraftStations.value = []
}

function handleMapDraftUpdate(stations: AgvMapStation[]) {
  mapDraftStations.value = cloneStations(stations)
}

async function saveMapEdit() {
  if (mapDraftStations.value.length === 0) {
    ElMessage.warning('没有可保存的工站布局')
    return
  }
  mapSaving.value = true
  try {
    const data = await saveAgvMapLayout(
      mapDraftStations.value.map((station) => ({
        id: station.id,
        x: station.x,
        y: station.y,
      })),
    )
    mapData.value = data
    mapEditing.value = false
    mapDraftStations.value = []
    ElMessage.success('工站地图布局已保存')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    mapSaving.value = false
  }
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

function handleArmJogEmergencyStop() {
  armJogPanelRef.value?.emergencyStop()
}

async function handleJobFinished(job: { status?: string }) {
  if (pendingHardwareAction.value !== null) {
    pendingHardwareAction.value = { ...pendingHardwareAction.value, jobFinished: true }
  }
  await loadStatus()
  await loadMap()
  if (job.status === 'failed') {
    pendingHardwareAction.value = null
    return
  }
  resolvePendingHardwareAction()
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
        <h2>AGV 运输车</h2>
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
          <div class="metric-label">运输车站点</div>
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
        <div class="slot-row slot-row-fixed">
          <el-tag
            v-for="item in slotItems"
            :key="item.key"
            :type="slotTagType(item.occupied)"
          >
            {{ item.label }}: {{ slotStatusText(item.occupied) }}
          </el-tag>
        </div>
      </div>
    </section>

    <!-- 中间: 工站地图 + 基础控制 + 物料转移 -->
    <div class="agv-map-control-layout">
      <section class="panel">
        <div class="panel-title">
          <h3>工站地图</h3>
          <div class="panel-title-actions">
            <el-tag v-if="isCharging" type="warning">循环运行中, 手动导航不可用</el-tag>
            <el-button v-if="mapEditing === false" size="small" @click="beginMapEdit" :disabled="(mapData?.stations.length ?? 0) === 0">
              编辑
            </el-button>
            <template v-else>
              <el-button size="small" @click="cancelMapEdit" :disabled="mapSaving">取消</el-button>
              <el-button size="small" type="primary" :loading="mapSaving" @click="saveMapEdit">保存</el-button>
            </template>
          </div>
        </div>
        <AgvMapView
          :stations="displayStations"
          :current-station-id="currentStationId"
          :disabled="isCharging"
          :editable="mapEditing"
          @select="handleStationSelect"
          @update:stations="handleMapDraftUpdate"
        />
      </section>

      <div class="control-stack">
        <section class="panel transfer-panel">
          <div class="panel-title">
            <h3>基础控制</h3>
          </div>
          <div class="control-actions">
            <el-button
              class="control-action-button"
              :type="driveButton.type"
              :loading="isActionLoading(driveButton.key)"
              :disabled="isHardwareActionDisabled(driveButton.key, driveButton.group)"
              @click="handleDriveAction"
            >{{ driveButton.label }}</el-button>
            <el-button
              class="control-action-button"
              :type="quickChangeButton.type"
              :loading="isActionLoading(quickChangeButton.key)"
              :disabled="isHardwareActionDisabled(quickChangeButton.key, quickChangeButton.group)"
              @click="handleQuickChangeAction"
            >{{ quickChangeButton.label }}</el-button>
            <el-button
              class="control-action-button"
              :type="gripperButton.type"
              :loading="isActionLoading(gripperButton.key)"
              :disabled="isHardwareActionDisabled(gripperButton.key, gripperButton.group)"
              @click="handleGripperAction"
            >{{ gripperButton.label }}</el-button>
            <el-button
              class="control-action-button"
              :loading="isActionLoading('arm-home')"
              @click="handleArmHome"
              :disabled="isArmConnected === false || (actionLoading !== '' && actionLoading !== 'arm-home')"
            >
              机械臂回零
            </el-button>
            <el-button
              class="control-action-button"
              type="danger"
              @click="handleArmStop"
              :disabled="isArmConnected === false"
            >立即停止</el-button>
          </div>
        </section>

        <section class="panel">
          <div class="panel-title">
            <h3>物料转移</h3>
          </div>
          <el-form class="transfer-form" size="small" label-width="86px">
            <el-form-item label="源点位">
              <el-select
                v-model="transferForm.source_tray"
                filterable
                clearable
                placeholder="请选择源点位"
                class="tray-select"
              >
                <el-option
                  v-for="option in trayOptions"
                  :key="`source-${option.name}`"
                  :label="formatTrayOption(option)"
                  :value="option.name"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="目标点位">
              <el-select
                v-model="transferForm.target_tray"
                filterable
                clearable
                placeholder="请选择目标点位"
                class="tray-select"
              >
                <el-option
                  v-for="option in trayOptions"
                  :key="`target-${option.name}`"
                  :label="formatTrayOption(option)"
                  :value="option.name"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="物料类型">
              <el-input v-model="transferForm.material_type" placeholder="可留空" />
            </el-form-item>
            <el-form-item class="transfer-action-row" label=" ">
              <el-button
                type="primary"
                :loading="isActionLoading('transfer')"
                @click="handleTransfer"
                :disabled="isArmConnected === false"
              >
                执行单次转移
              </el-button>
            </el-form-item>
          </el-form>
        </section>
      </div>
    </div>

    <!-- 下方: 机械臂微调 -->
    <section class="panel agv-jog-panel">
      <div class="panel-title">
        <h3>机械臂微调</h3>
        <div class="jog-title-controls">
          <el-select v-model="jogRefCoord" size="small" class="jog-coord-select" :disabled="isArmConnected === false">
            <el-option label="参考坐标系: Base" value="base" />
            <el-option label="参考坐标系: TCP" value="tcp" />
            <el-option label="参考坐标系: User" value="user" />
          </el-select>
          <el-button type="danger" size="small" :disabled="isArmConnected === false" @click="handleArmJogEmergencyStop">
            立即停止
          </el-button>
        </div>
      </div>
      <ArmJogPanel
        ref="armJogPanelRef"
        :disabled="isArmConnected === false"
        :tcp-pose="status?.tcp_pose ?? null"
        :joints="status?.joints ?? null"
        :ref-coord="jogRefCoord"
      />
    </section>

    <!-- 充电管理与电量变化曲线 -->
    <div class="agv-charge-layout">
      <section class="panel battery-panel">
        <div class="panel-title">
          <h3>电量变化曲线</h3>
          <el-radio-group v-model="historyHours" size="small" @change="onHistoryHoursChange">
            <el-radio-button :label="1">1 小时</el-radio-button>
            <el-radio-button :label="6">6 小时</el-radio-button>
            <el-radio-button :label="24">24 小时</el-radio-button>
          </el-radio-group>
        </div>
        <BatteryChart :records="historyRecords" :hours="historyHours" />
      </section>

      <section class="panel agv-charge-panel">
        <div class="panel-title">
          <h3>充电管理</h3>
          <el-tag :type="isCharging ? 'success' : 'info'">
            {{ isCharging ? '循环运行中' : '未运行' }}
          </el-tag>
        </div>

        <el-form class="charge-form" size="default" label-width="94px">
          <div class="charge-form-grid">
            <el-form-item class="charge-form-wide" label="待命点">
              <el-radio-group v-model="chargingForm.standby">
                <el-radio-button label="CP6">CP6 充电点</el-radio-button>
                <el-radio-button label="PP5">PP5 待充点</el-radio-button>
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
            <el-form-item class="charge-action-row">
              <el-button
                v-if="isCharging === false"
                class="charge-action-button"
                size="large"
                type="primary"
                :loading="isActionLoading('charging-start')"
                @click="handleStartCharging"
                :disabled="isChassisConnected === false"
              >启动循环</el-button>
              <el-button
                v-else
                class="charge-action-button"
                size="large"
                type="danger"
                :loading="isActionLoading('charging-stop')"
                @click="handleStopCharging"
              >停止循环</el-button>
              <el-button
                class="charge-action-button"
                size="large"
                :loading="isActionLoading('charging-check-once')"
                @click="handleChargingCheckOnce"
                :disabled="isChassisConnected === false"
              >执行单次检查</el-button>
            </el-form-item>
          </div>
        </el-form>

      </section>
    </div>

    <!-- 运行结果 -->
    <JobPanel
      :job-id="currentJobId"
      source="agv"
      title="运行结果"
      @finished="handleJobFinished"
    />
  </div>
</template>

<style scoped>
.slot-section {
  margin-top: 16px;
  display: grid;
  gap: 10px;
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

.slot-row-fixed :deep(.el-tag) {
  justify-content: center;
  min-width: 96px;
  min-height: 34px;
  font-size: 14px;
}

.unit {
  margin-left: 8px;
  color: #66758a;
  font-size: 12px;
}

.agv-map-control-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 0.62fr);
  gap: 16px;
  align-items: stretch;
  min-width: 0;
}

.control-stack {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 16px;
  height: 100%;
  min-width: 0;
}

.transfer-panel {
  min-height: 0;
}

.panel-title-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.control-actions {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 132px), 1fr));
  gap: 12px;
  min-width: 0;
}

.control-action-button {
  width: 100%;
  min-width: 0;
  min-height: 38px;
  margin-left: 0;
  font-weight: 600;
  white-space: normal;
}

.control-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.transfer-form {
  width: 100%;
}

.transfer-form :deep(.el-form-item) {
  margin-bottom: 14px;
}

.transfer-form :deep(.el-form-item__label) {
  color: #53647b;
  font-weight: 600;
}

.transfer-form :deep(.el-select),
.transfer-form :deep(.el-input) {
  width: 100%;
}

.transfer-action-row {
  margin-bottom: 0;
}

.transfer-action-row :deep(.el-button) {
  min-width: 142px;
  min-height: 36px;
  margin-left: 0;
  font-weight: 600;
}

.tray-select {
  width: 100%;
}

.jog-title-controls {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.jog-coord-select {
  width: 166px;
}

.agv-charge-layout {
  display: grid;
  grid-template-columns: minmax(560px, 1.55fr) minmax(320px, 0.68fr);
  gap: 16px;
  align-items: stretch;
  min-width: 0;
}

.agv-jog-panel,
.agv-charge-panel {
  min-width: 0;
}

.agv-charge-panel {
  display: flex;
  flex-direction: column;
}

.charge-form {
  display: flex;
  flex: 1;
  align-items: center;
  width: 100%;
}

.charge-form-grid {
  display: grid;
  grid-template-columns: 1fr;
  row-gap: 16px;
  align-items: start;
  width: 100%;
  max-width: 760px;
  margin: 0 auto;
  transform: translateX(-18px);
}

.charge-form-wide,
.charge-action-row {
  grid-column: 1 / -1;
}

.charge-form :deep(.el-form-item) {
  margin-bottom: 0;
}

.charge-form :deep(.el-form-item__label) {
  color: #3e5068;
  font-size: 14px;
  font-weight: 700;
}

.charge-form :deep(.el-form-item__content) {
  min-width: 0;
}

.charge-form-grid > :not(.charge-form-wide):not(.charge-action-row) :deep(.el-form-item__content) {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 42px;
  align-items: center;
  gap: 10px;
}

.charge-form-wide :deep(.el-form-item__content) {
  display: block;
}

.charge-form-wide :deep(.el-radio-group) {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  width: 100%;
}

.charge-form-wide :deep(.el-radio-button__inner) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  min-height: 38px;
  padding: 0 14px;
  font-size: 15px;
  font-weight: 700;
}

.charge-form :deep(.el-input-number) {
  width: 100%;
}

.charge-form :deep(.el-input-number__decrease),
.charge-form :deep(.el-input-number__increase) {
  width: 38px;
  font-size: 16px;
}

.charge-form :deep(.el-input__wrapper) {
  min-height: 38px;
}

.charge-form :deep(.el-input__inner) {
  font-size: 16px;
  font-weight: 700;
}

.charge-form .unit {
  margin-left: 0;
  font-size: 14px;
  font-weight: 700;
}

.charge-action-row :deep(.el-form-item__content) {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.charge-action-row :deep(.el-button + .el-button) {
  margin-left: 0;
}

.charge-action-button {
  width: 100%;
  min-height: 44px;
  font-size: 16px;
  font-weight: 700;
}

.battery-panel :deep(.battery-chart) {
  height: 300px;
}

@media (max-width: 1180px) {
  .agv-map-control-layout,
  .agv-charge-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .charge-form-grid,
  .control-actions,
  .charge-action-row :deep(.el-form-item__content) {
    grid-template-columns: 1fr;
  }
}
</style>
