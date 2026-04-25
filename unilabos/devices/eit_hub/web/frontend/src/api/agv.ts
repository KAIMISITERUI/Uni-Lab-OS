import http from './http'

export type ChargingStandby = 'CP6' | 'PP5'
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

export interface ChargeLoopStatus {
  running: boolean
  standby: string
  config: {
    interval_minutes: number
    retry_wait_minutes: number
    low_battery_pct: number
  }
  last_action: Record<string, unknown> | null
}

export interface AgvStatusResponse {
  connections: AgvConnections
  station: AgvStationInfo | null
  battery: AgvBatteryInfo | null
  battery_latest: { timestamp: string; battery_level: number; charging: boolean } | null
  nav_task: AgvNavTaskInfo | null
  slots: AgvSlotsStatus | null
  gripper_state: string | null
  current_gripper: string | null
  tcp_pose: number[] | null
  joints: number[] | null
  is_moving: boolean | null
  arm_state: AgvArmState
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
  ratio: number
  old_pose?: number[] | null
  new_pose?: number[] | null
  exists: boolean
}

export interface MiddleTrayPreviewResponse {
  station_name: string
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
  standby: ChargingStandby
  interval_minutes: number
  retry_wait_minutes: number
  low_battery_pct: number
}): Promise<ChargeLoopStatus> {
  const { data } = await http.post<ChargeLoopStatus>('/api/agv/charging/start', payload)
  return data
}

export async function stopCharging(): Promise<ChargeLoopStatus> {
  const { data } = await http.post<ChargeLoopStatus>('/api/agv/charging/stop')
  return data
}

export async function chargingCheckOnce(payload: {
  low_battery_pct: number
}): Promise<JobCreateResponse> {
  const { data } = await http.post<JobCreateResponse>('/api/agv/charging/check-once', {
    low_battery_pct: payload.low_battery_pct,
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

export async function previewMiddleTray(station: string): Promise<MiddleTrayPreviewResponse> {
  const { data } = await http.get<MiddleTrayPreviewResponse>('/api/agv/calibration/middle-tray/preview', {
    params: { station },
  })
  return data
}

export async function applyMiddleTray(stationName: string): Promise<{
  station_name: string
  updated_count: number
  created_count: number
  affected_trays: string[]
  skipped_rows: unknown[]
}> {
  const { data } = await http.post('/api/agv/calibration/middle-tray/apply', {
    station_name: stationName,
  })
  return data
}

export async function moveToGraspPosition(trayName: string): Promise<JobCreateResponse> {
  const { data } = await http.post<JobCreateResponse>('/api/agv/calibration/move-to-grasp', {
    tray_name: trayName,
  })
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
  logs: string[]
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
