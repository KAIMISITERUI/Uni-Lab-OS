<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import JobPanel from '../components/JobPanel.vue'
import {
  type DashboardData,
  type JobState,
  type OuterDoorAction,
  type W1ShelfAction,
  fetchDashboard,
  controlOuterDoor,
  controlW1Shelf,
  getResourceInfo,
  initSynthesisDevice,
} from '../api/synthesis'
import { listChemicals, type ChemicalRow } from '../api/chemicals'
import { getErrorMessage } from '../api/http'
import ChemicalDetailDialog from '../components/ChemicalDetailDialog.vue'
import StructurePreview from '../components/StructurePreview.vue'
import NTUStationGraph from '../components/NTUStationGraph.vue'
import ResourcePanel from '../components/synthesis/ResourcePanel/ResourcePanel.vue'
import TrayDetailPopover from '../components/synthesis/StationDetail/TrayDetailPopover.vue'
import { buildTrayDetail, type TrayDetail } from '../components/synthesis/StationDetail/buildTrayDetail'
import type { TrayModelOption } from '../components/synthesis/ResourcePanel/types'
import { getModule } from '../lib/dynamic-graph'

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

interface W1ShelfControl {
  position: string
  positionLabel: string
  label: string
  action: W1ShelfAction | null
  loading: boolean
  disabled: boolean
  buttonClass: string
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
// 录入资源右侧面板与主 3D 视图引用, 用于右键联动和录入后的强制刷新
const resourcePanelRef = ref<InstanceType<typeof ResourcePanel> | null>(null)
const stationGraphRef = ref<InstanceType<typeof NTUStationGraph> | null>(null)
// 主 3D 视图外层容器, 用于将 zrender 的 (offsetX, offsetY) 转为 viewport 坐标给浮卡定位
const stationGraphWrapRef = ref<HTMLDivElement | null>(null)
// 工站资源全量列表, 浮卡解析与点击查看共用. mounted / 资源变更 / 内部刷新后同步
const latestResourceList = ref<Array<Record<string, unknown>>>([])
// 托盘型号选项 (BaseTray.getAllModels() 派生), 仅在第一次需要时加载, 之后复用
const trayOptions = ref<TrayModelOption[]>([])
// 浮卡可见状态: null 表示关闭
interface PopoverState {
  detail: TrayDetail
  anchor: { x: number; y: number }
}
const popoverState = ref<PopoverState | null>(null)

// 主 3D 视图右键命中槽位时, 携带 layout_code 打开录入对话框
function onSlotContextMenu (layoutCode: string, _x: number, _y: number): void {
  if (resourcePanelRef.value !== null) {
    resourcePanelRef.value.openDialog(layoutCode)
  }
}

// 加载托盘型号选项, 与 ResourceEditDialog 同款 BaseTray 派生逻辑.
// 静默失败回退空数组 (浮卡解析失败 → 不显示, 与空托盘表现一致)
function ensureTrayOptions (): void {
  if (trayOptions.value.length > 0) {
    return
  }
  try {
    const module = getModule()
    const all = module.BaseTray.getAllModels?.() || []
    const opts: TrayModelOption[] = []
    all.forEach((tray: { config?: Record<string, unknown>; model?: string }) => {
      const cfg = (tray.config || {}) as Record<string, unknown>
      const model = tray.model || (cfg.model as string)
      if (!model) {
        return
      }
      const editSubstance = cfg.editSubstance as Record<string, unknown> | undefined
      const withCapVal = cfg.with_cap as boolean | Record<string, unknown> | undefined
      opts.push({
        model: String(model),
        name: String(cfg.name || model),
        row: Number(cfg.row) || 0,
        col: Number(cfg.col) || 0,
        childrenCount: Number(cfg.children_count) || ((Number(cfg.row) || 0) * (Number(cfg.col) || 0)),
        vesselModels: Array.isArray(cfg.vessel_models) ? (cfg.vessel_models as string[]) : [],
        noAddin: cfg.noAddin === true,
        defaultWithCap: typeof withCapVal === 'boolean'
          ? withCapVal
          : (typeof (withCapVal as Record<string, unknown> | undefined)?.NTU === 'boolean'
            ? (withCapVal as Record<string, unknown>).NTU as boolean
            : true),
        defaultWithMagneton: cfg.isMagnetonTray === true || cfg.with_magneton === true,
        editSubstanceCreate: editSubstance?.create === true,
      })
    })
    trayOptions.value = opts
  } catch (err) {
    console.warn('[SynthesisView] loadTrayOptions failed:', err)
    trayOptions.value = []
  }
}

// 同步全量资源列表给浮卡使用. 静默失败 (浮卡找不到对应数据 → 自然不显示)
async function syncResourceList (): Promise<void> {
  try {
    const resp = await getResourceInfo({})
    const list = (resp?.resource_list as Array<Record<string, unknown>> | undefined) || []
    latestResourceList.value = list
  } catch (err) {
    console.warn('[SynthesisView] syncResourceList failed:', err)
  }
  // 浮卡仍打开时按新数据重渲染当前 layout_code
  refreshOpenPopover()
}

// 数据变化后, 若浮卡仍指向某个 layout_code, 重新解析并替换 detail (空托盘则关闭)
function refreshOpenPopover (): void {
  const cur = popoverState.value
  if (cur === null) {
    return
  }
  const detail = buildTrayDetail(latestResourceList.value, cur.detail.layoutCode, trayOptions.value)
  if (detail === null) {
    popoverState.value = null
    return
  }
  popoverState.value = { detail, anchor: cur.anchor }
}

// 主 3D 视图左键命中槽位回调.
// selected=false 表示同一托盘再次点击触发 toggle off → 关闭浮卡.
// selected=true 时, 用 latestResourceList 解析 detail; 空托盘 (返回 null) 不弹.
function onSlotClick (layoutCode: string, x: number, y: number, selected: boolean): void {
  if (selected === false) {
    popoverState.value = null
    return
  }
  ensureTrayOptions()
  const detail = buildTrayDetail(latestResourceList.value, layoutCode, trayOptions.value)
  if (detail === null) {
    popoverState.value = null
    return
  }
  // 把容器内 offset 转为 viewport (浮卡用 position: fixed)
  const wrap = stationGraphWrapRef.value
  let clientX = x
  let clientY = y
  if (wrap !== null) {
    const rect = wrap.getBoundingClientRect()
    clientX = rect.left + x
    clientY = rect.top + y
  }
  popoverState.value = { detail, anchor: { x: clientX, y: clientY } }
}

// 强制刷新主 3D 视图. 供资源变更成功回调和 ResourcePanel 手动刷新按钮共同复用
// 异常会向上抛出, 由调用方决定是否提示 (手动刷新会在子组件捕获并提示)
async function refreshStationGraph (): Promise<void> {
  if (stationGraphRef.value === null) {
    return
  }
  try {
    await stationGraphRef.value.refresh()
  } catch (err) {
    console.error('[SynthesisView] graph refresh failed:', err)
    throw err
  }
}

// 录入成功后强制刷新主 3D 视图, 同步显示新增试管
// 资源变更链路保留原有静默策略 (refreshStationGraph 内部已 console.error), 不打断各 Dialog 的 success 流程
async function onResourceMutationSuccess (): Promise<void> {
  try {
    await refreshStationGraph()
  } catch {
    // 静默吞掉, 错误已在 refreshStationGraph 中打日志
  }
  // 资源变更后同步浮卡数据源, 若浮卡仍打开则刷新内容
  await syncResourceList()
}
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

const w1ShelfControls = computed<W1ShelfControl[]>(() => {
  return w1ShelfPositions.map((position) => createW1ShelfControl(position))
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

function createW1ShelfControl(position: string): W1ShelfControl {
  const pending = pendingOperation.value
  const isCurrentPending = pending?.kind === 'w1-shelf' && pending.position === position
  const action = resolveW1ShelfAction(position)
  const loading = isCurrentPending === true
  const blocked = pending !== null && isCurrentPending === false
  const disabled = loading === true || blocked === true || actionLoading.value === 'control_w1_shelf' || action === null
  if (loading === true) {
    return {
      position,
      positionLabel: formatW1ShelfPositionLabel(position),
      action,
      label: '运行中',
      loading,
      disabled,
      buttonClass: 'action-button--running',
    }
  }
  if (action === 'outside') {
    return {
      position,
      positionLabel: formatW1ShelfPositionLabel(position),
      action,
      label: '推出',
      loading,
      disabled,
      buttonClass: 'w1-action-button--outside',
    }
  }
  if (action === 'home') {
    return {
      position,
      positionLabel: formatW1ShelfPositionLabel(position),
      action,
      label: '复位',
      loading,
      disabled,
      buttonClass: 'w1-action-button--home',
    }
  }
  return {
    position,
    positionLabel: formatW1ShelfPositionLabel(position),
    action: null,
    label: '状态未知',
    loading,
    disabled,
    buttonClass: 'action-button--disabled',
  }
}

function resolveW1ShelfAction(position: string): W1ShelfAction | null {
  const device = findW1ShelfDevice(position)
  if (isDeviceStatus(device, 'OUTSIDE') === true) {
    return 'home'
  }
  if (isDeviceStatus(device, 'HOME') === true) {
    return 'outside'
  }
  return null
}

function formatW1ShelfPositionLabel(position: string): string {
  const match = /^W-1-(\d+)$/.exec(position)
  if (match === null) {
    return position
  }
  const startIndex = Number(match[1])
  if (Number.isFinite(startIndex) === false) {
    return position
  }
  return `${position}, W-1-${startIndex + 1}`
}

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

async function runW1Shelf(control: W1ShelfControl) {
  const action = control.action
  if (action === null) {
    ElMessage.warning(`${control.position} 当前没有可执行的操作`)
    return
  }
  if (control.disabled === true) {
    return
  }
  actionLoading.value = 'control_w1_shelf'
  pendingOperation.value = {
    kind: 'w1-shelf',
    position: control.position,
    action,
    targetStatus: action === 'home' ? 'HOME' : 'OUTSIDE',
  }
  try {
    const data = await controlW1Shelf({
      position: control.position,
      action,
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
  // 主 3D 视图浮卡所需资源列表与 dashboard 解耦, 但激活时一并拉取以保证首次点击就有数据
  void syncResourceList()
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
                        <svg v-if="card.icon === 'reactionTube'" viewBox="0 0 1024 1024" fill="currentColor">
                          <path d="M736 192c0-18.88-13.696-42.304-49.472-62.72-34.88-19.968-85.248-33.28-142.528-33.28-57.28 0-107.648 13.312-142.528 33.28-35.776 20.416-49.472 43.84-49.472 62.72 0 18.88 13.696 42.304 49.472 62.72 34.88 19.968 85.248 33.28 142.528 33.28 57.28 0 107.648-13.312 142.528-33.28 35.776-20.416 49.472-43.84 49.472-62.72z m64 0c0 51.84-36.48 92.416-81.728 118.336C672 336.64 610.368 352 544 352s-128-15.296-174.272-41.664C324.48 284.416 288 243.776 288 192c0-51.84 36.48-92.416 81.728-118.336C416 47.36 477.632 32 544 32s128 15.296 174.272 41.664C763.52 99.584 800 140.224 800 192zM544 672c66.368 0 128 15.296 174.272 41.664 45.248 25.92 81.728 66.56 81.728 118.336h-64c0-18.88-13.696-42.304-49.472-62.72-34.88-19.968-85.248-33.28-142.528-33.28-57.28 0-107.648 13.312-142.528 33.28-35.776 20.416-49.472 43.84-49.472 62.72h-64c0-51.84 36.48-92.416 81.728-118.336C416 687.36 477.632 672 544 672z" />
                          <path d="M288 832V192h64v640c0 18.88 13.696 42.304 49.472 62.72 34.88 19.968 85.248 33.28 142.528 33.28 57.28 0 107.648-13.312 142.528-33.28 35.776-20.416 49.472-43.84 49.472-62.72V192h64v640c0 51.84-36.48 92.416-81.728 118.336-46.208 26.368-107.904 41.664-174.272 41.664s-128-15.296-174.272-41.664C324.48 924.416 288 883.776 288 832z" />
                          <path d="M448 416v64H320v-64h128zM448 576v64H320V576h128z" />
                        </svg>
                        <svg v-else-if="card.icon === 'sealCap'" viewBox="0 0 1024 1024" fill="currentColor">
                          <path d="M339.968 277.263059h-3.975529a26.985412 26.985412 0 0 1-26.50353-27.467294V116.976941c0-15.119059 11.866353-27.467294 26.50353-27.467294h352.015058c14.637176 0 26.503529 12.348235 26.50353 27.467294v132.818824a26.985412 26.985412 0 0 1-26.50353 27.467294h-4.035764v37.948235C723.245176 322.258824 752.941176 354.364235 752.941176 392.734118v517.662117c0 43.550118-38.189176 78.908235-85.11247 78.908236H356.171294c-46.983529 0-85.112471-35.358118-85.11247-78.908236V392.734118c0-38.430118 29.696-70.415059 68.909176-77.402353v-38.008471z m307.922824 1.987765l-271.781648 27.105882v7.408941h271.781648v-34.514823z m19.877647 654.155294c13.733647 0 24.937412-10.360471 24.937411-23.070118V392.734118c0-12.709647-11.143529-23.070118-24.877176-23.070118H356.171294c-13.733647 0-24.877176 10.360471-24.877176 23.070118v517.662117c0 12.709647 11.143529 23.070118 24.877176 23.070118h311.657412z" />
                        </svg>
                        <svg v-else-if="card.icon === 'magnet'" viewBox="0 0 1024 1024" fill="currentColor">
                          <path d="M263.04 263.04C354.816 171.52 465.216 114.112 570.816 96.512c105.472-17.6 208.96 4.48 280.64 76.16 71.68 71.68 93.76 175.168 76.16 280.64-17.6 105.6-75.008 216-166.656 307.648-91.648 91.648-202.048 149.12-307.648 166.656-105.472 17.6-208.96-4.48-280.64-76.16-71.68-71.68-93.76-175.168-76.16-280.64 17.6-105.6 75.008-216 166.656-307.648z m45.312 45.312C225.024 391.68 174.72 490.304 159.552 581.248l-0.512 2.816c-39.616 338.944 540.416 260.48 682.048-57.6 10.88-28.16 18.752-56.32 23.36-83.712 15.168-91.072-4.992-171.648-58.24-224.896-53.312-53.312-133.888-73.472-224.96-58.304C490.24 174.72 391.68 225.024 308.352 308.352z" />
                          <path d="M473.6 375.168a32 32 0 0 1-51.2-38.4C508.16 222.336 626.88 215.744 679.68 228.928a32 32 0 0 1-15.488 62.08c-32.512-8.064-122.88-6.144-190.656 84.16z" />
                        </svg>
                        <svg v-else-if="card.icon === 'tip'" viewBox="0 0 1024 1024" fill="currentColor">
                          <path d="M894.6 263.88L758.72 128l-88.15 88.15 21.47 21.46-479.3 502.61-83.34 132.11L153.07 896l127.78-87.66L784.23 329.8l22.22 22.23z" />
                        </svg>
                        <svg v-else-if="card.icon === 'filterInnerBottle'" viewBox="0 0 1024 1024" fill="currentColor">
                          <path d="M832 356.992c0 25.6-15.616 45.44-32.64 58.944-17.408 13.888-40.96 25.28-68.096 34.368-54.528 18.368-130.176 29.696-219.264 29.696-89.216 0-164.864-11.712-219.392-30.272-27.072-9.152-50.56-20.608-67.84-34.368C208 402.112 192 382.528 192 356.992V160h64v196.096a27.456 27.456 0 0 0 8.512 9.152c9.536 7.552 25.536 16 48.768 23.936 46.08 15.68 114.432 26.816 198.72 26.816 84.416 0 152.768-10.816 198.848-26.304 23.232-7.808 39.168-16.256 48.64-23.808 6.784-5.44 8.256-8.704 8.512-9.472V160h64v196.992z" />
                          <path d="M767.872 159.488a8.896 8.896 0 0 0-1.024-2.112 39.68 39.68 0 0 0-9.28-9.6c-10.56-8.32-27.904-17.216-52.096-25.28-48-16-116.48-26.496-193.472-26.496-77.056 0-145.472 10.496-193.472 26.496-24.192 8.064-41.536 16.96-52.096 25.28a39.68 39.68 0 0 0-9.28 9.6A9.152 9.152 0 0 0 256 160l0.128 0.512a9.152 9.152 0 0 0 1.024 2.112 39.68 39.68 0 0 0 9.28 9.6c10.56 8.32 27.904 17.216 52.096 25.28 48 16 116.48 26.496 193.472 26.496 77.056 0 145.472-10.496 193.472-26.496 24.192-8.064 41.536-16.96 52.096-25.28a39.68 39.68 0 0 0 9.28-9.6A8.896 8.896 0 0 0 768 160l-0.128-0.512zM832 160c0 27.264-16.64 48.128-34.816 62.528-18.56 14.592-43.52 26.432-71.424 35.712-56.192 18.752-131.776 29.76-213.76 29.76-81.984 0-157.568-11.008-213.76-29.76-27.904-9.28-52.864-21.12-71.424-35.712C208.576 208.128 192 187.264 192 160c0-27.264 16.64-48.128 34.816-62.528 18.56-14.592 43.52-26.432 71.424-35.712C354.432 43.008 430.08 32 512 32c81.984 0 157.568 11.008 213.76 29.76 27.904 9.28 52.864 21.12 71.424 35.712 18.24 14.4 34.816 35.264 34.816 62.528z" />
                          <path d="M352 416V256a32 32 0 0 1 64 0v160a32 32 0 0 1-64 0zM608 416V256a32 32 0 0 1 64 0v160a32 32 0 0 1-64 0zM512 800c55.488 0 107.072 7.424 145.92 20.352 19.2 6.4 37.12 14.72 50.816 25.6 13.376 10.496 27.264 27.2 27.264 50.048 0 22.848-13.888 39.552-27.264 50.048-13.696 10.88-31.616 19.2-50.88 25.6-38.784 12.928-90.368 20.352-145.856 20.352s-107.072-7.424-145.92-20.352c-19.2-6.4-37.12-14.72-50.816-25.6-13.376-10.496-27.264-27.2-27.264-50.048 0-22.848 13.888-39.552 27.264-50.048 13.696-10.88 31.616-19.2 50.88-25.6 38.784-12.928 90.368-20.352 145.856-20.352z m0 64c-50.56 0-94.912 6.912-125.632 17.152-15.232 5.056-25.408 10.368-31.168 14.848 5.76 4.48 15.936 9.792 31.168 14.848 30.72 10.24 75.072 17.152 125.632 17.152s94.912-6.912 125.632-17.152a109.44 109.44 0 0 0 31.104-14.848 109.44 109.44 0 0 0-31.104-14.848C606.912 870.912 562.56 864 512 864z" />
                          <path d="M288 896V448a32 32 0 0 1 64 0v448a32 32 0 0 1-64 0zM672 896V448a32 32 0 0 1 64 0v448a32 32 0 0 1-64 0z" />
                        </svg>
                        <svg v-else viewBox="0 0 1024 1024" fill="currentColor">
                          <path d="M800 160v186.048c-0.128 23.936-11.84 44.416-27.52 60.288-15.808 15.872-37.312 29.056-62.08 39.616-49.728 21.12-118.208 34.048-198.4 34.048-80.32 0-148.864-13.312-198.528-34.688-24.704-10.624-46.144-23.872-61.824-39.68-15.68-15.68-27.648-36.096-27.648-60.032V160h64v185.6c0 1.536 0.768 6.656 8.96 14.912 8.256 8.192 21.888 17.408 41.856 25.984 39.808 17.088 99.264 29.504 173.184 29.504 74.048 0 133.568-12.032 173.312-28.928 19.904-8.512 33.472-17.6 41.6-25.792a30.144 30.144 0 0 0 8.832-13.44L736 345.6V160h64z" />
                          <path d="M736 160c0-0.832-0.384-5.44-9.344-13.44-8.96-7.936-23.808-16.64-44.8-24.512C639.872 106.368 579.84 96 512 96c-67.84 0-127.936 10.368-169.792 26.048-21.056 7.936-35.84 16.576-44.8 24.512-9.024 8-9.408 12.608-9.408 13.44 0 0.832 0.384 5.44 9.344 13.44 8.96 7.936 23.808 16.64 44.8 24.512C384.128 213.632 444.16 224 512 224c67.84 0 127.936-10.368 169.792-26.048 21.056-7.936 35.84-16.576 44.8-24.512 9.024-8 9.408-12.608 9.408-13.44z m64 0c0 25.664-14.016 46.336-30.848 61.312-16.96 14.976-39.68 27.072-64.896 36.544C653.44 276.928 585.536 288 512 288s-141.44-11.072-192.256-30.08c-25.28-9.536-48-21.632-64.896-36.608C238.08 206.336 224 185.664 224 160c0-25.664 14.016-46.336 30.848-61.312 16.96-14.976 39.68-27.072 64.896-36.544C370.56 43.072 438.464 32 512 32s141.44 11.072 192.256 30.08c25.28 9.536 48 21.632 64.896 36.608 16.832 14.976 30.848 35.648 30.848 61.312zM704 832c0-2.432-1.024-7.424-8.32-14.848-7.552-7.68-19.968-16-37.888-23.68C622.144 778.24 570.56 768 512 768s-110.08 10.24-145.792 25.472c-17.92 7.68-30.336 16-37.824 23.68-7.36 7.424-8.384 12.416-8.384 14.848 0 2.432 1.024 7.424 8.32 14.848 7.552 7.68 19.968 16 37.888 23.68C401.856 885.76 453.44 896 512 896s110.08-10.24 145.792-25.472c17.92-7.68 30.336-16 37.824-23.68 7.36-7.424 8.384-12.416 8.384-14.848z m64 0c0 24.064-11.52 44.352-26.816 59.84-15.168 15.36-35.52 27.776-58.24 37.44-45.312 19.52-105.792 30.72-170.944 30.72-65.152 0-125.632-11.2-171.008-30.72-22.656-9.664-43.008-22.016-58.24-37.44C267.52 876.416 256 856.128 256 832s11.52-44.352 26.816-59.84c15.168-15.36 35.52-27.776 58.24-37.44C386.304 715.2 446.784 704 512 704c65.152 0 125.632 11.2 171.008 30.72 22.656 9.664 43.008 22.016 58.24 37.44 15.232 15.488 26.752 35.776 26.752 59.84z" />
                          <path d="M256 800V384h64v416c0 18.88 13.696 42.304 49.472 62.72 34.88 19.968 85.248 33.28 142.528 33.28 57.28 0 107.648-13.312 142.528-33.28 35.776-20.416 49.472-43.84 49.472-62.72V384h64v416c0 51.84-36.48 92.416-81.728 118.336C640 944.64 578.368 960 512 960s-128-15.296-174.272-41.664C292.48 892.416 256 851.776 256 800z" />
                        </svg>
                      </el-icon>
                    </div>
                  </div>
                </div>
              </div>
              <div class="resource-group station-with-panel">
                <div class="station-main-column">
                  <div ref="stationGraphWrapRef" class="station-graph-wrap">
                    <NTUStationGraph
                      ref="stationGraphRef"
                      :margin="50"
                      :on-context-menu-tray="onSlotContextMenu"
                      :on-click-tray="onSlotClick"
                      :on-after-refresh="syncResourceList"
                    />
                    <TrayDetailPopover
                      v-if="popoverState !== null"
                      :detail="popoverState.detail"
                      :anchor="popoverState.anchor"
                      @close="popoverState = null"
                    />
                  </div>
                </div>
                <div class="station-side-panel">
                  <ResourcePanel
                    ref="resourcePanelRef"
                    :on-refresh="refreshStationGraph"
                    @success="onResourceMutationSuccess"
                  />
                  <div class="side-management-panel">
                    <div class="panel-title side-panel-title">
                      <h3>设备管理</h3>
                    </div>
                    <div class="device-management-actions">
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
                        <div class="w1-control-list">
                          <div
                            v-for="control in w1ShelfControls"
                            :key="control.position"
                            class="w1-control-row"
                          >
                            <span class="w1-position-name">{{ control.positionLabel }}</span>
                            <el-button
                              class="w1-control-button"
                              :class="control.buttonClass"
                              :loading="control.loading"
                              :disabled="control.disabled"
                              @click="runW1Shelf(control)"
                            >
                              {{ control.label }}
                            </el-button>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <section class="chemical-status-layout">
            <div class="panel display-panel">
              <div class="panel-title">
                <h3>化学品库</h3>
              </div>
              <div class="table-wrap chemical-table-wrap">
                <el-table class="reagent-table" :data="reagentDisplayRows" border stripe height="520">
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

            <div class="panel display-panel">
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

.station-with-panel {
  grid-template-columns: minmax(0, 1fr) 200px;
  gap: 14px;
  align-items: start;
}

.station-main-column {
  display: grid;
  gap: 14px;
  min-width: 0;
}

.station-graph-wrap {
  min-width: 0;
  width: 100%;
}

.station-side-panel {
  display: grid;
  align-content: start;
  gap: 12px;
  width: 100%;
}

.side-management-panel {
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
  background: #ffffff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
}

.side-panel-title {
  margin-bottom: 0;
  padding: 10px;
  border-bottom: 1px solid #ebeef5;
}

.side-panel-title h3 {
  overflow: hidden;
  min-width: 0;
  color: #303133;
  text-overflow: ellipsis;
  white-space: nowrap;
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

.chemical-status-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 420px);
  gap: 16px;
  align-items: stretch;
  min-width: 0;
}

.display-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-width: 0;
}

.chemical-table-wrap {
  min-height: 520px;
}

.device-status-grid {
  display: grid;
  grid-template-columns: 1fr;
  align-content: start;
  gap: 10px;
  height: 520px;
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

.device-management-actions {
  display: grid;
  gap: 14px;
  padding: 10px;
}

.device-management-actions .el-button {
  justify-content: flex-start;
  min-height: 40px;
  margin-left: 0;
}

.init-action-button,
.door-action-button,
.w1-control-button {
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

.w1-control-list {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.w1-control-row {
  display: grid;
  grid-template-columns: max-content 54px;
  justify-content: end;
  gap: 15px;
  align-items: center;
  min-width: 0;
}

.w1-position-name {
  justify-self: end;
  color: #34445d;
  font-size: 14px;
  font-weight: 700;
  line-height: 1.25;
  text-align: right;
  white-space: normal;
}

.w1-control-button {
  width: 100%;
  min-width: 0;
  min-height: 38px;
  height: 38px;
  padding: 0 8px;
  text-align: center;
}

.w1-control-button :deep(span) {
  display: inline-block;
  width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.door-action-button,
.w1-control-button {
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

@media (max-width: 860px) {
  .chemical-status-layout,
  .station-with-panel,
  .operation-row {
    grid-template-columns: 1fr;
  }

  .station-side-panel {
    width: 100%;
  }
}
</style>
