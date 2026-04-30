import http from './http'
import type { LogEntry } from './log'

export type { LogEntry } from './log'

export type QuickChangeAction = 'lock' | 'release'
export type GripperAction = 'open' | 'close'

export interface AgvConnections {
  chassis_connected: boolean
  arm_connected: boolean
}

export interface AgvStationInfo {
  station_id: string
  station_name: string
  description: string
}

export interface AgvBatteryInfo {
  battery_level?: number | null
  charging?: boolean
  voltage?: number | null
  current?: number | null
  temperature?: number | null
  [key: string]: unknown
}

export interface AgvNavTaskInfo {
  task_status?: number
  task_status_name?: string
  task_type?: number
  task_type_name?: string
  target_id?: string
  [key: string]: unknown
}

export interface AgvSlotsStatus {
  quick_change: boolean[]
  tray: boolean[]
}

export interface AgvArmState {
  drive_ready: boolean | null
  quick_change_locked: boolean | null
  gripper_open: boolean | null
}

export interface AgvCollisionInfo {
  active: boolean
  axis: number | null
}

export interface ChargeLoopStatus {
  running: boolean
  config: ChargeLoopConfig
  last_action: Record<string, unknown> | null
}

export interface ChargeLoopConfig {
  interval_minutes: number
  retry_wait_minutes: number
  low_battery_pct: number
  full_battery_pct: number
}

export interface AgvChargeControlInfo {
  do_id: number
  do_status: boolean | null
  stop_charging: boolean | null
  charging_enabled: boolean | null
  source?: string | null
  valid?: boolean | null
  message?: string | null
  [key: string]: unknown
}

export interface AgvStatusResponse {
  connections: AgvConnections
  station: AgvStationInfo | null
  battery: AgvBatteryInfo | null
  battery_latest: { timestamp: string; battery_level: number; charging: boolean } | null
  charge_control: AgvChargeControlInfo | null
  nav_task: AgvNavTaskInfo | null
  slots: AgvSlotsStatus | null
  gripper_state: string | null
  current_gripper: string | null
  tcp_pose: number[] | null
  joints: number[] | null
  is_moving: boolean | null
  arm_state: AgvArmState
  collision: AgvCollisionInfo
  charge_loop: ChargeLoopStatus
}

export interface AgvMapStation {
  id: string
  name: string
  description: string
  label: string
  x: number
  y: number
}

export interface AgvMapResponse {
  stations: AgvMapStation[]
  current_station_id: string | null
}

export interface TrayPointOption {
  name: string
  label: string
  description: string
  station_id: string | null
  station_name: string | null
}

export interface TrayOptionsResponse {
  station_id: string | null
  options: TrayPointOption[]
}

export interface BatteryHistoryRecord {
  timestamp: string
  battery_level: number
  charging: boolean
  voltage?: number | null
  current?: number | null
  temperature?: number | null
}

export interface BatteryHistoryResponse {
  hours: number
  records: BatteryHistoryRecord[]
}

export interface JobCreateResponse {
  job_id: string
  status?: string
}

export interface ShelfSlotInfo {
  material_type: string
  source: string
  description: string
  placed_at: string
}

export interface ShelfStatusResponse {
  last_updated: string
  slots: Record<string, ShelfSlotInfo | null>
}

export interface MiddleTrayRow {
  row_index: number
  target_tray: string
  left_tray: string
  right_tray: string
  target_col: number
  ratio: number
  old_pose?: number[] | null
  new_pose?: number[] | null
  exists: boolean
}

export interface MiddleTrayRowOption {
  station_name: string
  row_index: number
  left_tray: string
  right_tray: string
  target_count: number
  update_count: number
  create_count: number
  label: string
}

export interface MiddleTrayPreviewResponse {
  station_name: string
  row_index: number
  rows: MiddleTrayRow[]
}

// ==================== 基础状态与连接 ====================

export async function fetchAgvStatus(): Promise<AgvStatusResponse> {
  const { data } = await http.get<AgvStatusResponse>('/api/agv/status')
  return data
}

export async function fetchAgvMap(): Promise<AgvMapResponse> {
  const { data } = await http.get<AgvMapResponse>('/api/agv/map')
  return data
}

export async function saveAgvMapLayout(
  stations: Array<{ id: string; x: number; y: number }>,
): Promise<AgvMapResponse> {
  const { data } = await http.post<AgvMapResponse>('/api/agv/map/layout', { stations })
  return data
}

export async function connectChassis(): Promise<AgvConnections> {
  const { data } = await http.post<AgvConnections>('/api/agv/chassis/connect')
  return data
}

export async function disconnectChassis(): Promise<AgvConnections> {
  const { data } = await http.post<AgvConnections>('/api/agv/chassis/disconnect')
  return data
}

export async function connectArm(): Promise<AgvConnections> {
  const { data } = await http.post<AgvConnections>('/api/agv/arm/connect')
  return data
}

export async function disconnectArm(): Promise<AgvConnections> {
  const { data } = await http.post<AgvConnections>('/api/agv/arm/disconnect')
  return data
}

export async function armPowerOn(): Promise<JobCreateResponse> {
  const { data } = await http.post<JobCreateResponse>('/api/agv/arm/power-on')
  return data
}

export async function armPowerOff(): Promise<JobCreateResponse> {
  const { data } = await http.post<JobCreateResponse>('/api/agv/arm/power-off')
  return data
}

export async function armHome(): Promise<JobCreateResponse> {
  const { data } = await http.post<JobCreateResponse>('/api/agv/arm/home')
  return data
}

export async function armStop(): Promise<{ ok: boolean }> {
  const { data } = await http.post<{ ok: boolean }>('/api/agv/arm/stop')
  return data
}

export async function resetArmCollision(): Promise<{ ok: boolean }> {
  const { data } = await http.post<{ ok: boolean }>('/api/agv/arm/reset-collision')
  return data
}

export async function armQuickChange(action: QuickChangeAction): Promise<JobCreateResponse> {
  const { data } = await http.post<JobCreateResponse>('/api/agv/arm/quick-change', { action })
  return data
}

export async function armGripper(action: GripperAction): Promise<JobCreateResponse> {
  const { data } = await http.post<JobCreateResponse>('/api/agv/arm/gripper', { action })
  return data
}

// ==================== 导航与转运 ====================

export async function navigateToStation(stationId: string): Promise<JobCreateResponse> {
  const { data } = await http.post<JobCreateResponse>('/api/agv/navigate', { station_id: stationId })
  return data
}

export async function fetchTrayOptions(stationId?: string | null): Promise<TrayOptionsResponse> {
  const { data } = await http.get<TrayOptionsResponse>('/api/agv/tray-options', {
    params: { station_id: stationId ?? undefined },
  })
  return data
}

export async function transferMaterial(payload: {
  source_tray: string
  target_tray: string
  material_type?: string | null
}): Promise<JobCreateResponse> {
  const { data } = await http.post<JobCreateResponse>('/api/agv/transfer', payload)
  return data
}

export async function batchTransferMaterials(
  tasks: Array<{ source_tray: string; target_tray: string; material_type?: string | null }>,
): Promise<JobCreateResponse> {
  const { data } = await http.post<JobCreateResponse>('/api/agv/batch-transfer', { tasks })
  return data
}

// ==================== 充电管理 ====================

export async function fetchChargingStatus(): Promise<ChargeLoopStatus> {
  const { data } = await http.get<ChargeLoopStatus>('/api/agv/charging/status')
  return data
}

export async function startCharging(payload: {
  interval_minutes: number
  retry_wait_minutes: number
  low_battery_pct: number
  full_battery_pct: number
}): Promise<ChargeLoopStatus> {
  const { data } = await http.post<ChargeLoopStatus>('/api/agv/charging/start', payload)
  return data
}

export async function saveChargingConfig(payload: ChargeLoopConfig): Promise<ChargeLoopStatus> {
  const { data } = await http.put<ChargeLoopStatus>('/api/agv/charging/config', payload)
  return data
}

export async function stopCharging(): Promise<ChargeLoopStatus> {
  const { data } = await http.post<ChargeLoopStatus>('/api/agv/charging/stop')
  return data
}

export async function chargingCheckOnce(payload: {
  low_battery_pct: number
  full_battery_pct: number
}): Promise<JobCreateResponse> {
  const { data } = await http.post<JobCreateResponse>('/api/agv/charging/check-once', {
    low_battery_pct: payload.low_battery_pct,
    full_battery_pct: payload.full_battery_pct,
  })
  return data
}

export async function fetchBatteryHistory(hours: number): Promise<BatteryHistoryResponse> {
  const { data } = await http.get<BatteryHistoryResponse>('/api/agv/battery/history', {
    params: { hours },
  })
  return data
}

// ==================== 校准 ====================

export async function calibrateStation(): Promise<JobCreateResponse> {
  const { data } = await http.post<JobCreateResponse>('/api/agv/calibration/station')
  return data
}

export async function calibrateTray(trayName: string): Promise<JobCreateResponse> {
  const { data } = await http.post<JobCreateResponse>('/api/agv/calibration/tray', { tray_name: trayName })
  return data
}

export async function calibrateStationOffset(): Promise<JobCreateResponse> {
  const { data } = await http.post<JobCreateResponse>('/api/agv/calibration/station-offset')
  return data
}

export async function prepareLoadedTrayCalibration(payload: {
  target_tray: string
  source_tray: string
}): Promise<JobCreateResponse> {
  const { data } = await http.post<JobCreateResponse>('/api/agv/calibration/loaded-tray/prepare', payload)
  return data
}

// 仅计算带托盘校准应保存的位姿, 不写盘, 保存统一走 saveTrayCalibration.
export async function recordLoadedTrayPose(trayName: string): Promise<{ tray_name: string; pose: number[] }> {
  const { data } = await http.post<{ tray_name: string; pose: number[] }>(
    '/api/agv/calibration/loaded-tray/record',
    { tray_name: trayName },
  )
  return data
}

export async function completeLoadedTrayCalibration(trayName: string): Promise<JobCreateResponse> {
  const { data } = await http.post<JobCreateResponse>('/api/agv/calibration/loaded-tray/complete', {
    tray_name: trayName,
  })
  return data
}

export async function fetchMiddleTrayRows(): Promise<MiddleTrayRowOption[]> {
  const { data } = await http.get<{ rows: MiddleTrayRowOption[] }>('/api/agv/calibration/middle-tray/rows')
  return data.rows
}

export async function previewMiddleTray(
  stationName: string,
  rowIndex: number,
): Promise<MiddleTrayPreviewResponse> {
  const { data } = await http.get<MiddleTrayPreviewResponse>('/api/agv/calibration/middle-tray/preview', {
    params: { station_name: stationName, row_index: rowIndex },
  })
  return data
}

export async function applyMiddleTray(stationName: string, rowIndex: number): Promise<{
  station_name: string
  row_index: number
  updated_count: number
  created_count: number
  affected_trays: string[]
  skipped_rows: unknown[]
}> {
  const { data } = await http.post('/api/agv/calibration/middle-tray/apply', {
    station_name: stationName,
    row_index: rowIndex,
  })
  return data
}

export async function moveToGraspPosition(trayName: string): Promise<JobCreateResponse> {
  const { data } = await http.post<JobCreateResponse>('/api/agv/calibration/move-to-grasp', {
    tray_name: trayName,
  })
  return data
}

export interface StationCalibrationOffset {
  x: number
  y: number
  z: number
  dx: number
  dy: number
  dz: number
}

export async function fetchStationOffset(station: string): Promise<{
  station: string
  offset: StationCalibrationOffset | null
}> {
  const { data } = await http.get<{ station: string; offset: StationCalibrationOffset | null }>(
    '/api/agv/calibration/station/offset',
    { params: { station } },
  )
  return data
}

export interface TrayCalibrationPreview {
  tray_name: string
  original_pose: number[] | null
  current_pose: number[]
  pose_to_save: number[]
  station_offset: StationCalibrationOffset | null
}

export async function previewTrayCalibration(trayName: string): Promise<TrayCalibrationPreview> {
  const { data } = await http.post<TrayCalibrationPreview>('/api/agv/calibration/tray/preview', {
    tray_name: trayName,
  })
  return data
}

export async function saveTrayCalibration(payload: {
  tray_name: string
  pose: number[]
}): Promise<{ tray_name: string; ok: boolean }> {
  const { data } = await http.post<{ tray_name: string; ok: boolean }>(
    '/api/agv/calibration/tray/save',
    payload,
  )
  return data
}

export interface StationOffsetPreparePayload {
  station: string
  reference_tray: string
  use_loaded_tray: boolean
  source_tray?: string
  run_vision?: boolean
  move_to_point?: boolean
}

export async function prepareStationOffsetCalibration(
  payload: StationOffsetPreparePayload,
): Promise<JobCreateResponse> {
  const { data } = await http.post<JobCreateResponse>(
    '/api/agv/calibration/station-offset/prepare',
    payload,
  )
  return data
}

export interface StationOffsetVector {
  x: number
  y: number
  z: number
  rx: number
  ry: number
  rz: number
}

export interface StationOffsetPreviewResponse {
  station: string
  reference_tray: string
  original_pose: number[]
  current_pose: number[]
  expected_pose: number[]
  offset: StationOffsetVector
  affected_trays: string[]
}

export async function previewStationOffset(payload: {
  station: string
  reference_tray: string
  vision_offset?: StationCalibrationOffset | null
}): Promise<StationOffsetPreviewResponse> {
  const { data } = await http.post<StationOffsetPreviewResponse>(
    '/api/agv/calibration/station-offset/preview',
    payload,
  )
  return data
}

export async function applyStationOffset(payload: {
  station: string
  offset: StationOffsetVector
}): Promise<{
  station: string
  success_count: number
  fail_count: number
  affected_trays: string[]
}> {
  const { data } = await http.post('/api/agv/calibration/station-offset/apply', payload)
  return data
}

export async function cleanupStationOffsetCalibration(payload: {
  reference_tray: string
  use_loaded_tray: boolean
}): Promise<JobCreateResponse | { ok: boolean; skipped: boolean }> {
  const { data } = await http.post('/api/agv/calibration/station-offset/cleanup', payload)
  return data
}

// ==================== 取放托盘测试 ====================

export async function testPickTray(payload: {
  tray_name: string
  material_type?: string | null
}): Promise<JobCreateResponse> {
  const { data } = await http.post<JobCreateResponse>('/api/agv/test/pick-tray', payload)
  return data
}

export async function testPutTray(payload: {
  tray_name: string
  material_type?: string | null
}): Promise<JobCreateResponse> {
  const { data } = await http.post<JobCreateResponse>('/api/agv/test/put-tray', payload)
  return data
}

// ==================== 批量测试 ====================

export interface BatchTransferTaskItem {
  source_tray: string
  target_tray: string
  material_type: string
}

export async function testAllPositions(payload: {
  material_type: string
}): Promise<JobCreateResponse> {
  const { data } = await http.post<JobCreateResponse>('/api/agv/test/all-positions', payload)
  return data
}

export async function testBatchTransferCycle(payload: {
  cycle_count: number
  transfer_tasks: BatchTransferTaskItem[]
}): Promise<JobCreateResponse> {
  const { data } = await http.post<JobCreateResponse>('/api/agv/test/batch-transfer-cycle', payload)
  return data
}

// ==================== 物料与点位管理 ====================

export interface MaterialOption {
  name: string
  gripper: string
  description: string
}

export async function fetchMaterials(): Promise<MaterialOption[]> {
  const { data } = await http.get<{ materials: MaterialOption[] }>('/api/agv/materials')
  return data.materials
}

export interface TrayPositionRecord {
  name: string
  pose: number[] | null
  joints: number[] | null
  descend_z: number | null
  lift_z: number | null
  drop_z: number | null
  speed: number | null
  acceleration: number | null
  description: string
}

export async function fetchTrayPositions(): Promise<TrayPositionRecord[]> {
  const { data } = await http.get<{ positions: TrayPositionRecord[] }>('/api/agv/positions/tray')
  return data.positions
}

export interface TrayPositionUpdatePayload {
  pose?: number[]
  descend_z?: number
  lift_z?: number
  drop_z?: number
  speed?: number
  acceleration?: number
  description?: string
}

export async function updateTrayPosition(
  trayName: string,
  payload: TrayPositionUpdatePayload,
): Promise<{ tray_name: string; ok: boolean }> {
  const { data } = await http.put<{ tray_name: string; ok: boolean }>(
    `/api/agv/positions/tray/${encodeURIComponent(trayName)}`,
    payload,
  )
  return data
}

export async function createTrayPosition(payload: {
  tray_name: string
  template_tray: string
  pose: number[]
  description?: string
}): Promise<{ tray_name: string; ok: boolean }> {
  const { data } = await http.post<{ tray_name: string; ok: boolean }>(
    '/api/agv/positions/tray',
    payload,
  )
  return data
}

export async function deleteTrayPosition(
  trayName: string,
): Promise<{ tray_name: string; ok: boolean }> {
  const { data } = await http.delete<{ tray_name: string; ok: boolean }>(
    `/api/agv/positions/tray/${encodeURIComponent(trayName)}`,
  )
  return data
}

// ==================== 货架 ====================

export async function fetchShelfStatus(): Promise<ShelfStatusResponse> {
  const { data } = await http.get<ShelfStatusResponse>('/api/agv/shelf/status')
  return data
}

export async function removeShelfSlot(slotName: string): Promise<{ ok: boolean }> {
  const { data } = await http.post<{ ok: boolean }>('/api/agv/shelf/remove', { slot_name: slotName })
  return data
}

export async function resetShelf(): Promise<{ ok: boolean }> {
  const { data } = await http.post<{ ok: boolean }>('/api/agv/shelf/reset-all', { confirm: true })
  return data
}

export async function placeShelfMaterial(payload: {
  slot_name: string
  material_type: string
  source: string
  description?: string
}): Promise<{ ok: boolean }> {
  const { data } = await http.post<{ ok: boolean }>('/api/agv/shelf/place', payload)
  return data
}

// ==================== 任务轮询 ====================

export interface AgvJobState {
  job_id: string
  name: string
  status: 'queued' | 'running' | 'succeeded' | 'failed'
  logs: LogEntry[]
  result?: unknown
  error?: string | null
  created_at?: string
  started_at?: string | null
  finished_at?: string | null
}

export async function fetchAgvJob(jobId: string): Promise<AgvJobState> {
  const { data } = await http.get<AgvJobState>(`/api/agv/jobs/${jobId}`)
  return data
}
