<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Link as LinkIcon, Refresh } from '@element-plus/icons-vue'
import JobPanel from '../components/JobPanel.vue'
import {
  type DashboardData,
  type JobState,
  type OuterDoorAction,
  type W1ShelfAction,
  fetchDashboard,
  controlOuterDoor,
  controlW1Shelf,
  initSynthesisDevice,
} from '../api/synthesis'
import { listChemicals, type ChemicalRow } from '../api/chemicals'
import { getErrorMessage } from '../api/http'
import ChemicalDetailDialog from '../components/ChemicalDetailDialog.vue'
import StructurePreview from '../components/StructurePreview.vue'

interface ReagentOccurrence {
  amount: string
  position: string
  trayType: string
}

interface ReagentDisplayRow {
  substance: string
  chemical: ChemicalRow | null
  structureSmiles: string
  physicalState: string
  occurrences: ReagentOccurrence[]
}

type DeviceTargetStatus = 'OPEN' | 'CLOSE' | 'OUTSIDE' | 'HOME'
type ConsumableIcon =
  | 'reactionTube'
  | 'sealCap'
  | 'magnet'
  | 'tip'
  | 'filterInnerBottle'
  | 'filterOuterBottle'

interface PendingOperation {
  kind: 'outer-door' | 'w1-shelf'
  action: OuterDoorAction | W1ShelfAction
  targetStatus: DeviceTargetStatus
  position?: string
}

interface W1ShelfOption {
  position: string
  action: W1ShelfAction
  label: string
  currentStatusLabel: string
}

interface OuterDoorButtonState {
  action: OuterDoorAction | null
  label: string
  loading: boolean
  disabled: boolean
}

const dashboard = ref<DashboardData | null>(null)
const currentJobId = ref('')
const dashboardLoading = ref(false)
const actionLoading = ref('')
const pendingOperation = ref<PendingOperation | null>(null)
const reagentChemicalMap = ref<Record<string, ChemicalRow | null | undefined>>({})
const reagentDetailVisible = ref(false)
const reagentDetailChemical = ref<ChemicalRow | null>(null)
const w1SelectedPosition = ref('W-1-1')
let dashboardTimer: number | undefined
let actionRefreshTimer: number | undefined

const reagentResourceTypeCodes = new Set([201000600, 201000730, 201000502, 201000503, 220000023])
const consumableCardConfigs: Array<{ resourceType: number; label: string; icon: ConsumableIcon }> = [
  { resourceType: 201000726, label: '2 mL 反应试管', icon: 'reactionTube' },
  { resourceType: 201000712, label: '反应密封盖', icon: 'sealCap' },
  { resourceType: 201000711, label: '2 mL 试管磁子', icon: 'magnet' },
  { resourceType: 201000512, label: '5 mL Tip 头', icon: 'tip' },
  { resourceType: 201000731, label: '1 mL Tip 头', icon: 'tip' },
  { resourceType: 201000815, label: '50 μL Tip 头', icon: 'tip' },
  { resourceType: 201000727, label: '闪滤瓶内瓶', icon: 'filterInnerBottle' },
  { resourceType: 201000728, label: '闪滤瓶外瓶', icon: 'filterOuterBottle' },
]
const w1ShelfPositions = ['W-1-1', 'W-1-3', 'W-1-5', 'W-1-7']
const synthesisControlUrl =
  'http://10.40.13.51:9191/#/?$skipCheckService=true&hostname=http://10.40.13.51:4669&$view=NTU'

const deviceStatusCodeMap: Record<DeviceTargetStatus, number> = {
  OPEN: 3,
  CLOSE: 4,
  OUTSIDE: 5,
  HOME: 6,
}

const stationStateText = computed(() => stateLabel(dashboard.value?.station_state ?? null))

const dashboardErrors = computed(() => {
  if (dashboard.value === null) {
    return []
  }
  return Object.entries(dashboard.value.errors || {}).map(([key, value]) => `${key}: ${value}`)
})

const visibleDeviceStatus = computed(() => {
  return (dashboard.value?.device_status || []).filter((row) => {
    return row.device_name !== '手套箱箱体环境'
  })
})

const reagentResources = computed(() => {
  return (dashboard.value?.resources || []).filter((row) => isReagentResource(row))
})

const reagentDisplayRows = computed(() => {
  const rowMap = new Map<string, ReagentDisplayRow>()
  for (const resource of reagentResources.value) {
    const details = Array.isArray(resource.substance_details) ? resource.substance_details : []
    for (const item of details) {
      if (typeof item !== 'object' || item === null) {
        continue
      }
      const detail = item as Record<string, unknown>
      const substance = String(detail.substance || '').trim()
      if (substance === '') {
        continue
      }
      const key = normalizeChemicalName(substance)
      if (rowMap.has(key) === false) {
        const chemical = reagentChemicalMap.value[key] || null
        rowMap.set(key, {
          substance,
          chemical,
          structureSmiles: String(chemical?.smiles || ''),
          physicalState: formatChemicalField(chemical?.physical_state),
          occurrences: [],
        })
      }
      rowMap.get(key)?.occurrences.push({
        amount: String(detail.value || '--'),
        position: formatReagentPosition(resource, detail),
        trayType: String(resource.resource_type_name || '--'),
      })
    }
  }
  return Array.from(rowMap.values())
})

const consumableCards = computed(() => {
  const countMap = new Map<number, number>()
  for (const row of dashboard.value?.resources || []) {
    const code = Number(row.resource_type)
    if (Number.isFinite(code) === false) {
      continue
    }
    const count = Number(row.count)
    countMap.set(code, (countMap.get(code) || 0) + (Number.isFinite(count) ? count : 0))
  }
  return consumableCardConfigs.map((config) => ({
    ...config,
    count: countMap.get(config.resourceType) || 0,
  }))
})

const outerDoorDevice = computed(() => findOuterDoorDevice())

const outerDoorAction = computed(() => {
  const device = outerDoorDevice.value
  const status = String(device?.status || '').toUpperCase()
  const statusCode = Number(device?.status_code)
  if (status === 'OPEN' || statusCode === 3) {
    return { action: 'close' as const, label: '关闭外门' }
  }
  if (status === 'CLOSE' || statusCode === 4) {
    return { action: 'open' as const, label: '打开外门' }
  }
  return null
})

const isOuterDoorPending = computed(() => pendingOperation.value?.kind === 'outer-door')

const outerDoorButton = computed<OuterDoorButtonState>(() => {
  if (isOuterDoorPending.value === true) {
    return {
      action: null,
      label: '运行中',
      loading: true,
      disabled: true,
    }
  }
  if (outerDoorAction.value === null) {
    return {
      action: null,
      label: '外门状态未知',
      loading: false,
      disabled: true,
    }
  }
  const action = outerDoorAction.value.action
  const loading = actionLoading.value === `outer_door_${action}`
  return {
    action,
    label: outerDoorAction.value.label,
    loading,
    disabled: loading || pendingOperation.value !== null,
  }
})

const w1ShelfExecutableOptions = computed<W1ShelfOption[]>(() => {
  return w1ShelfPositions.flatMap((position) => {
    const device = findW1ShelfDevice(position)
    if (isDeviceStatus(device, 'OUTSIDE') === true) {
      return [
        {
          position,
          action: 'home' as const,
          label: `${position} 复位`,
          currentStatusLabel: '当前推出',
        },
      ]
    }
    if (isDeviceStatus(device, 'HOME') === true) {
      return [
        {
          position,
          action: 'outside' as const,
          label: `${position} 推出`,
          currentStatusLabel: '当前复位',
        },
      ]
    }
    return []
  })
})

const selectedW1ShelfOption = computed(() => {
  return w1ShelfExecutableOptions.value.find((option) => option.position === w1SelectedPosition.value) || null
})

const isW1Pending = computed(() => pendingOperation.value?.kind === 'w1-shelf')

const w1ExecuteLabel = computed(() => {
  if (isW1Pending.value === true) {
    return '运行中'
  }
  if (selectedW1ShelfOption.value === null) {
    return '暂无可执行 W1 操作'
  }
  return `执行${selectedW1ShelfOption.value.action === 'home' ? '复位' : '推出'}`
})

const outerDoorButtonClass = computed(() => {
  if (isOuterDoorPending.value === true) {
    return 'action-button--running'
  }
  if (outerDoorButton.value.action === 'open') {
    return 'door-action-button--open'
  }
  if (outerDoorButton.value.action === 'close') {
    return 'door-action-button--close'
  }
  return 'action-button--disabled'
})

const w1ExecuteClass = computed(() => {
  if (isW1Pending.value === true) {
    return 'action-button--running'
  }
  if (selectedW1ShelfOption.value?.action === 'outside') {
    return 'w1-action-button--outside'
  }
  if (selectedW1ShelfOption.value?.action === 'home') {
    return 'w1-action-button--home'
  }
  return 'action-button--disabled'
})

const w1ControlDisabled = computed(() => {
  return (
    isW1Pending.value === true ||
    actionLoading.value === 'control_w1_shelf' ||
    selectedW1ShelfOption.value === null ||
    pendingOperation.value !== null
  )
})

async function loadDashboard() {
  dashboardLoading.value = true
  try {
    const data = await fetchDashboard()
    dashboard.value = data
    syncPendingOperation(data)
    void loadReagentChemicals(data.resources || [])
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    dashboardLoading.value = false
  }
}

async function loadReagentChemicals(resources: Array<Record<string, unknown>>) {
  const names = collectReagentNames(resources)
  const missingNames = names.filter((name) => {
    return reagentChemicalMap.value[normalizeChemicalName(name)] === undefined
  })
  if (missingNames.length === 0) {
    return
  }

  const nextMap = { ...reagentChemicalMap.value }
  await Promise.all(
    missingNames.map(async (name) => {
      const key = normalizeChemicalName(name)
      try {
        const response = await listChemicals({
          q: name,
          query_type: 'name',
          page: 1,
          page_size: 10,
        })
        const chemical = pickChemicalByName(name, response.items)
        nextMap[key] = chemical
      } catch {
        nextMap[key] = null
      }
    }),
  )
  reagentChemicalMap.value = nextMap
}

async function runDeviceInit() {
  actionLoading.value = 'device_init'
  try {
    const data = await initSynthesisDevice()
    currentJobId.value = data.job_id
    ElMessage.success('设备初始化已进入后台')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    actionLoading.value = ''
  }
}

async function runOuterDoor(action: OuterDoorAction) {
  actionLoading.value = `outer_door_${action}`
  pendingOperation.value = {
    kind: 'outer-door',
    action,
    targetStatus: action === 'close' ? 'CLOSE' : 'OPEN',
  }
  try {
    const data = await controlOuterDoor(action)
    currentJobId.value = data.job_id
    ElMessage.success('外门操作已进入后台')
    queueActionDashboardRefresh()
  } catch (error) {
    pendingOperation.value = null
    ElMessage.error(getErrorMessage(error))
  } finally {
    actionLoading.value = ''
  }
}

async function runW1Shelf() {
  const option = selectedW1ShelfOption.value
  if (option === null) {
    ElMessage.warning('当前没有可执行的 W1 操作')
    return
  }
  actionLoading.value = 'control_w1_shelf'
  pendingOperation.value = {
    kind: 'w1-shelf',
    position: option.position,
    action: option.action,
    targetStatus: option.action === 'home' ? 'HOME' : 'OUTSIDE',
  }
  try {
    const data = await controlW1Shelf({
      position: option.position,
      action: option.action,
    })
    currentJobId.value = data.job_id
    ElMessage.success('W1 操作已进入后台')
    queueActionDashboardRefresh()
  } catch (error) {
    pendingOperation.value = null
    ElMessage.error(getErrorMessage(error))
  } finally {
    actionLoading.value = ''
  }
}

function runOuterDoorButton() {
  if (outerDoorButton.value.action !== null) {
    runOuterDoor(outerDoorButton.value.action)
  }
}

function onJobFinished(job: JobState) {
  if (actionRefreshTimer !== undefined) {
    window.clearTimeout(actionRefreshTimer)
    actionRefreshTimer = undefined
  }
  // job 成功: 交由 loadDashboard -> syncPendingOperation 基于真实 device_status 统一判定清除, 避免旧状态瞬时回显
  // job 失败: 设备不会到达 targetStatus, 必须主动清除以解锁 UI
  if (job.status === 'failed') {
    pendingOperation.value = null
  }
  loadDashboard()
}

function onJobUpdated(_job: JobState) {
  if (pendingOperation.value !== null) {
    queueActionDashboardRefresh()
  }
}

function startDashboardPolling() {
  stopDashboardPolling()
  loadDashboard()
  dashboardTimer = window.setInterval(loadDashboard, 5000)
}

function stopDashboardPolling() {
  if (dashboardTimer !== undefined) {
    window.clearInterval(dashboardTimer)
    dashboardTimer = undefined
  }
  if (actionRefreshTimer !== undefined) {
    window.clearTimeout(actionRefreshTimer)
    actionRefreshTimer = undefined
  }
}

function queueActionDashboardRefresh() {
  if (actionRefreshTimer !== undefined) {
    window.clearTimeout(actionRefreshTimer)
  }
  actionRefreshTimer = window.setTimeout(() => {
    actionRefreshTimer = undefined
    loadDashboard()
  }, 1000)
}

function syncPendingOperation(data: DashboardData) {
  const pending = pendingOperation.value
  if (pending === null) {
    return
  }
  const devices = data.device_status || []
  if (pending.kind === 'outer-door') {
    const device = findOuterDoorDevice(devices)
    if (isDeviceStatus(device, pending.targetStatus) === true) {
      pendingOperation.value = null
    }
    return
  }
  if (pending.position === undefined) {
    return
  }
  const device = findW1ShelfDevice(pending.position, devices)
  if (isDeviceStatus(device, pending.targetStatus) === true) {
    pendingOperation.value = null
  }
}

function findOuterDoorDevice(devices = dashboard.value?.device_status || []) {
  return devices.find((row) => String(row.device_name || '').includes('过渡舱外门'))
}

function findW1ShelfDevice(position: string, devices = dashboard.value?.device_status || []) {
  return devices.find((row) => String(row.device_name || '').includes(position))
}

function isDeviceStatus(device: Record<string, unknown> | undefined, targetStatus: DeviceTargetStatus): boolean {
  if (device === undefined) {
    return false
  }
  const status = String(device.status || '').toUpperCase()
  const statusCode = Number(device.status_code)
  return status === targetStatus || statusCode === deviceStatusCodeMap[targetStatus]
}

function stateLabel(code: number | null): string {
  const map: Record<number, string> = {
    0: '空闲',
    1: '运行中',
    3: '已暂停',
    6: '暂停中',
    7: '停止中',
    10: '挂起',
  }
  if (code === null) {
    return '未知'
  }
  return map[code] || `未知(${code})`
}

function statusTagType(code: unknown): 'success' | 'warning' | 'danger' | 'info' {
  if (code === 0 || code === 'AVAILABLE') {
    return 'success'
  }
  if (code === 1 || code === 'RUNNING') {
    return 'warning'
  }
  if (code === 2 || code === 'UNAVAILABLE') {
    return 'danger'
  }
  return 'info'
}

function formatValue(value: unknown, suffix = ''): string {
  if (value === null || value === undefined || value === '') {
    return '--'
  }
  return `${value}${suffix}`
}

function formatChemicalField(value: unknown): string {
  if (value === null || value === undefined || value === '') {
    return '-'
  }
  return String(value)
}

function formatOneDecimalPpm(value: unknown): string {
  if (value === null || value === undefined || value === '') {
    return '--'
  }
  const numericValue = Number(value)
  if (Number.isFinite(numericValue) === false) {
    return '--'
  }
  return `${numericValue.toFixed(1)} ppm`
}

function isReagentResource(row: Record<string, unknown>): boolean {
  const code = Number(row.resource_type)
  if (Number.isFinite(code) && reagentResourceTypeCodes.has(code)) {
    return true
  }
  const resourceTypeName = String(row.resource_type_name || '')
  return resourceTypeName.includes('试剂瓶托盘') || resourceTypeName.includes('粉桶托盘')
}

function collectReagentNames(resources: Array<Record<string, unknown>>): string[] {
  const names = new Map<string, string>()
  for (const resource of resources) {
    if (isReagentResource(resource) === false) {
      continue
    }
    const details = Array.isArray(resource.substance_details) ? resource.substance_details : []
    for (const item of details) {
      if (typeof item !== 'object' || item === null) {
        continue
      }
      const substance = String((item as Record<string, unknown>).substance || '').trim()
      if (substance !== '') {
        names.set(normalizeChemicalName(substance), substance)
      }
    }
  }
  return Array.from(names.values())
}

function normalizeChemicalName(value: unknown): string {
  return String(value || '').trim().replace(/\s+/g, '').toLowerCase()
}

function pickChemicalByName(name: string, rows: ChemicalRow[]): ChemicalRow | null {
  const key = normalizeChemicalName(name)
  return (
    rows.find((row) => normalizeChemicalName(row.substance) === key) ||
    rows.find((row) => normalizeChemicalName(row.other_name) === key) ||
    rows[0] ||
    null
  )
}

function openReagentDetail(row: ReagentDisplayRow): void {
  if (row.chemical === null) {
    return
  }
  reagentDetailChemical.value = row.chemical
  reagentDetailVisible.value = true
}

function formatReagentPosition(
  resource: Record<string, unknown>,
  detail: Record<string, unknown>,
): string {
  const layoutCode = String(resource.layout_code || '--')
  const well = String(detail.well || '').trim()
  if (well === '') {
    return layoutCode
  }
  return `${layoutCode} / ${well}`
}

watch(
  w1ShelfExecutableOptions,
  (options) => {
    if (pendingOperation.value?.kind === 'w1-shelf') {
      return
    }
    const selectedExists = options.some((option) => option.position === w1SelectedPosition.value)
    if (selectedExists === false) {
      w1SelectedPosition.value = options[0]?.position || ''
    }
  },
  { immediate: true },
)

onActivated(startDashboardPolling)

onDeactivated(stopDashboardPolling)

onBeforeUnmount(stopDashboardPolling)
</script>

<template>
  <div class="view-stack">
    <section class="metrics-grid">
            <div class="metric">
              <div class="metric-label">工站状态</div>
              <div class="metric-value">{{ stationStateText }}</div>
              <div class="metric-note">实时轮询</div>
            </div>
            <div class="metric">
              <div class="metric-label">水含量</div>
              <div class="metric-value">
                {{ formatOneDecimalPpm(dashboard?.glovebox_env?.water_content) }}
              </div>
              <div class="metric-note">手套箱</div>
            </div>
            <div class="metric">
              <div class="metric-label">氧含量</div>
              <div class="metric-value">
                {{ formatOneDecimalPpm(dashboard?.glovebox_env?.oxygen_content) }}
              </div>
              <div class="metric-note">手套箱</div>
            </div>
            <div class="metric">
              <div class="metric-label">箱压</div>
              <div class="metric-value">
                {{ formatValue(dashboard?.glovebox_env?.box_pressure) }}
              </div>
              <div class="metric-note">环境监测</div>
            </div>
    </section>

          <el-alert
            v-for="errorText in dashboardErrors"
            :key="errorText"
            type="error"
            :title="errorText"
            :closable="false"
          />

          <section class="panel">
            <div class="panel-title">
              <h2>站内资源</h2>
              <el-button :icon="Refresh" :loading="dashboardLoading" @click="loadDashboard">
                刷新
              </el-button>
            </div>
            <div class="resource-stack">
              <div class="resource-group">
                <div class="consumable-card-grid">
                  <div
                    v-for="card in consumableCards"
                    :key="card.resourceType"
                    class="consumable-card"
                  >
                    <div class="consumable-card-content">
                      <div class="consumable-card-label">{{ card.label }}</div>
                      <div class="consumable-card-count">{{ card.count }}</div>
                    </div>
                    <div class="consumable-card-icon-wrap" aria-hidden="true">
                      <el-icon class="card-icon">
                        <svg v-if="card.icon === 'reactionTube'" viewBox="0 0 32 32" fill="none">
                          <path d="M11 5h10" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" />
                          <path
                            d="M12 5v19c0 3.3 2.7 6 6 6s6-2.7 6-6V5"
                            stroke="currentColor"
                            stroke-width="2.5"
                            stroke-linecap="round"
                            stroke-linejoin="round"
                          />
                        </svg>
                        <svg v-else-if="card.icon === 'sealCap'" viewBox="0 0 32 32" fill="none">
                          <rect
                            x="9"
                            y="3"
                            width="14"
                            height="26"
                            rx="2"
                            stroke="currentColor"
                            stroke-width="2.4"
                            stroke-linejoin="round"
                          />
                          <circle cx="16" cy="16" r="1.8" fill="currentColor" />
                        </svg>
                        <svg v-else-if="card.icon === 'magnet'" viewBox="0 0 32 32" fill="none">
                          <ellipse
                            cx="16"
                            cy="16"
                            rx="11"
                            ry="6"
                            stroke="currentColor"
                            stroke-width="2.4"
                          />
                        </svg>
                        <svg v-else-if="card.icon === 'tip'" viewBox="0 0 32 32" fill="none">
                          <path
                            d="M22 6 26 10 12 24 7 25 8 20Z"
                            stroke="currentColor"
                            stroke-width="2.2"
                            stroke-linejoin="round"
                            stroke-linecap="round"
                          />
                          <path
                            d="M19 9 23 13"
                            stroke="currentColor"
                            stroke-width="2.2"
                            stroke-linecap="round"
                          />
                        </svg>
                        <svg v-else-if="card.icon === 'filterInnerBottle'" viewBox="0 0 32 32" fill="none">
                          <rect
                            x="12"
                            y="5"
                            width="8"
                            height="3"
                            stroke="currentColor"
                            stroke-width="2.2"
                            stroke-linejoin="round"
                          />
                          <path
                            d="M14 8V11L11 13V25a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2V13L18 11V8"
                            stroke="currentColor"
                            stroke-width="2.2"
                            stroke-linejoin="round"
                            stroke-linecap="round"
                          />
                        </svg>
                        <svg v-else viewBox="0 0 32 32" fill="none">
                          <path d="M11 5h10" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" />
                          <path
                            d="M11 5V26a3 3 0 0 0 3 3h4a3 3 0 0 0 3-3V5"
                            stroke="currentColor"
                            stroke-width="2.2"
                            stroke-linejoin="round"
                            stroke-linecap="round"
                          />
                        </svg>
                      </el-icon>
                    </div>
                  </div>
                </div>
              </div>
              <div class="resource-group">
                <div class="table-wrap">
                  <el-table class="reagent-table" :data="reagentDisplayRows" border stripe height="420">
                    <el-table-column label="结构式" width="142" align="center">
                      <template #default="{ row }">
                        <StructurePreview
                          :smiles="row.structureSmiles"
                          :width="118"
                          :height="86"
                        />
                      </template>
                    </el-table-column>
                    <el-table-column label="物质名称" min-width="260" align="center">
                      <template #default="{ row }">
                        <el-button
                          v-if="row.chemical !== null"
                          class="reagent-name-button"
                          type="primary"
                          link
                          @click="openReagentDetail(row)"
                        >
                          {{ row.substance }}
                        </el-button>
                        <span v-else class="reagent-name-text">{{ row.substance }}</span>
                      </template>
                    </el-table-column>
                    <el-table-column prop="physicalState" label="物态" width="90" align="center" />
                    <el-table-column label="剩余量" width="140" align="center">
                      <template #default="{ row }">
                        <div class="reagent-occurrence-list">
                          <div
                            v-for="(item, index) in row.occurrences"
                            :key="`${item.position}-${index}`"
                          >
                            {{ item.amount }}
                          </div>
                        </div>
                      </template>
                    </el-table-column>
                    <el-table-column label="位置" width="170" align="center">
                      <template #default="{ row }">
                        <div class="reagent-occurrence-list">
                          <div
                            v-for="(item, index) in row.occurrences"
                            :key="`${item.position}-${index}`"
                          >
                            {{ item.position }}
                          </div>
                        </div>
                      </template>
                    </el-table-column>
                    <el-table-column label="托盘种类" min-width="180" align="center">
                      <template #default="{ row }">
                        <div class="reagent-occurrence-list">
                          <div
                            v-for="(item, index) in row.occurrences"
                            :key="`${item.position}-${index}`"
                          >
                            {{ item.trayType }}
                          </div>
                        </div>
                      </template>
                    </el-table-column>
                  </el-table>
                </div>
              </div>
            </div>
          </section>

          <section class="two-column overview-status-actions">
            <div class="panel">
              <div class="panel-title">
                <h3>设备状态</h3>
              </div>
              <div class="device-status-grid">
                <div
                  v-for="device in visibleDeviceStatus"
                  :key="String(device.device_name)"
                  class="device-status-item"
                >
                  <span class="device-status-name">{{ device.device_name }}</span>
                  <el-tag :type="statusTagType(device.status_code)">
                    {{ device.status || device.status_code }}
                  </el-tag>
                </div>
              </div>
            </div>

            <div class="panel">
              <div class="panel-title">
                <h3>其它操作</h3>
              </div>
              <div class="other-actions">
                <el-button
                  class="init-action-button"
                  type="primary"
                  :loading="actionLoading === 'device_init'"
                  @click="runDeviceInit"
                >
                  设备初始化
                </el-button>
                <div class="operation-group">
                  <div class="operation-title">过渡舱外门</div>
                  <div class="operation-row">
                    <el-button
                      class="door-action-button"
                      :class="outerDoorButtonClass"
                      :loading="outerDoorButton.loading"
                      :disabled="outerDoorButton.disabled"
                      @click="runOuterDoorButton"
                    >
                      {{ outerDoorButton.label }}
                    </el-button>
                  </div>
                </div>
                <div class="operation-group">
                  <div class="operation-title">W1 排货架</div>
                  <el-form label-position="top">
                    <div class="w1-form">
                      <el-form-item>
                        <el-select
                          class="w1-position-select"
                          v-model="w1SelectedPosition"
                          :disabled="pendingOperation !== null || w1ShelfExecutableOptions.length === 0"
                          popper-class="w1-position-popper"
                          placeholder="暂无可执行 W1 操作"
                        >
                          <el-option
                            v-for="option in w1ShelfExecutableOptions"
                            :key="option.position"
                            :label="option.position"
                            :value="option.position"
                          />
                        </el-select>
                      </el-form-item>
                      <el-button
                        class="w1-execute-button"
                        :class="w1ExecuteClass"
                        :loading="isW1Pending || actionLoading === 'control_w1_shelf'"
                        :disabled="w1ControlDisabled"
                        @click="runW1Shelf"
                      >
                        {{ w1ExecuteLabel }}
                      </el-button>
                    </div>
                  </el-form>
                  <div class="operation-title">后台控制</div>
                  <el-button
                    class="external-control-button"
                    type="primary"
                    tag="a"
                    :icon="LinkIcon"
                    :href="synthesisControlUrl"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    访问合成工站控制页面
                  </el-button>
                </div>
              </div>
            </div>
          </section>

    <JobPanel
      :job-id="currentJobId"
      title="运行结果"
      @updated="onJobUpdated"
      @finished="onJobFinished"
    />
    <ChemicalDetailDialog
      v-model="reagentDetailVisible"
      :chemical="reagentDetailChemical"
      :show-edit="false"
    />
  </div>
</template>

<style scoped>
.resource-stack {
  display: grid;
  gap: 18px;
  min-width: 0;
}

.resource-group {
  display: grid;
  min-width: 0;
}

.consumable-card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(188px, 1fr));
  gap: 12px;
}

.consumable-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
  min-height: 88px;
  overflow: hidden;
  padding: 16px 18px;
  background: #f3f8ff;
  border: 1px solid #e3ebf8;
  border-radius: 8px;
}

.consumable-card-content {
  display: grid;
  flex: 1 1 auto;
  gap: 12px;
  min-width: 0;
}

.consumable-card-label {
  overflow: hidden;
  color: #738196;
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 0;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.consumable-card-count {
  color: #172033;
  font-size: 28px;
  font-weight: 700;
  line-height: 1;
}

.consumable-card-icon-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 44px;
  width: 44px;
  height: 44px;
}

.card-icon {
  width: 28px;
  height: 28px;
  color: #8595ae;
}

.card-icon svg {
  width: 100%;
  height: 100%;
}

.reagent-occurrence-list {
  display: grid;
  gap: 4px;
  justify-items: center;
  color: #24344d;
  line-height: 1.45;
  text-align: center;
}

.reagent-table :deep(.cell) {
  display: flex;
  justify-content: center;
}

.reagent-name-button {
  --el-button-active-text-color: #24344d;
  --el-button-hover-text-color: #24344d;
  --el-button-text-color: #24344d;
  height: auto;
  min-height: 22px;
  color: #24344d;
  line-height: 1.4;
  text-align: center;
  white-space: normal;
}

.reagent-name-text {
  line-height: 1.4;
  overflow-wrap: anywhere;
}

.overview-status-actions {
  grid-template-columns: minmax(560px, 1.35fr) minmax(320px, 0.65fr);
  align-items: stretch;
}

.overview-status-actions > .panel {
  height: 100%;
}

.device-status-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(220px, 1fr));
  gap: 10px;
  max-height: 300px;
  overflow: auto;
}

.device-status-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
  min-height: 42px;
  padding: 8px 10px;
  background: #f7f9fc;
  border: 1px solid #dce5f0;
  border-radius: 8px;
}

.device-status-name {
  overflow: hidden;
  color: #24344d;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.other-actions {
  display: grid;
  gap: 14px;
}

.other-actions .el-button {
  justify-content: flex-start;
  min-height: 40px;
  margin-left: 0;
}

.init-action-button,
.door-action-button,
.w1-execute-button {
  justify-content: center !important;
}

.operation-group {
  display: grid;
  gap: 10px;
  min-width: 0;
}

.operation-title {
  color: #34445d;
  font-size: 13px;
  font-weight: 700;
}

.operation-row {
  display: grid;
  grid-template-columns: 1fr;
  gap: 10px;
}

.w1-form {
  display: grid;
  grid-template-columns: minmax(190px, 1fr) minmax(144px, 0.72fr);
  gap: 10px;
  align-items: center;
}

.w1-form :deep(.el-form-item) {
  margin-bottom: 0;
}

.w1-execute-button {
  width: 100%;
  min-height: 44px;
  height: 44px;
}

.w1-position-select {
  width: 100%;
}

.w1-position-select :deep(.el-select__wrapper) {
  min-height: 44px;
  text-align: center;
}

.w1-position-select :deep(.el-select__selected-item) {
  width: 100%;
  justify-content: center;
}

.w1-position-select :deep(.el-select__placeholder) {
  justify-content: center;
}

.door-action-button,
.w1-execute-button {
  color: #ffffff;
  border-color: transparent;
}

.door-action-button--open {
  background: #0f766e;
}

.door-action-button--close {
  background: #d97706;
}

.w1-action-button--outside {
  background: #0f766e;
}

.w1-action-button--home {
  background: #d97706;
}

.door-action-button--open:hover,
.door-action-button--open:focus {
  color: #ffffff;
  background: #0d5f59;
  border-color: transparent;
}

.door-action-button--close:hover,
.door-action-button--close:focus {
  color: #ffffff;
  background: #b45309;
  border-color: transparent;
}

.w1-action-button--outside:hover,
.w1-action-button--outside:focus {
  color: #ffffff;
  background: #0d5f59;
  border-color: transparent;
}

.w1-action-button--home:hover,
.w1-action-button--home:focus {
  color: #ffffff;
  background: #b45309;
  border-color: transparent;
}

.action-button--running,
.action-button--disabled,
.action-button--running:hover,
.action-button--disabled:hover {
  color: #ffffff;
  background: #a8b1bf;
  border-color: transparent;
}

.external-control-button {
  justify-content: center !important;
  width: 100%;
  min-height: 40px;
}

:global(.w1-position-popper .el-select-dropdown__item) {
  text-align: center;
}

@media (max-width: 860px) {
  .overview-status-actions,
  .device-status-grid,
  .operation-row,
  .w1-form {
    grid-template-columns: 1fr;
  }
}
</style>
