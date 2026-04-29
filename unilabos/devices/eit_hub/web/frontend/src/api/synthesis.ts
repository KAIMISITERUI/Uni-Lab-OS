import http from './http'
import type { LogEntry } from './log'

export type { LogEntry } from './log'

export interface ParamRow {
  name: string
  value: unknown
  row?: number
  type: 'section' | 'parameter'
}

export interface GcMsYieldProduct {
  applicable_experiments: unknown
  product_name: unknown
  equivalent: unknown
  smiles: unknown
  expected_rt: unknown
}

export interface GcMsYieldConfig {
  internal_standard_smiles: unknown
  internal_standard_expected_rt: unknown
  yield_method: unknown
  curve_slope: unknown
  curve_intercept: unknown
  response_factor: unknown
  products: GcMsYieldProduct[]
}

export interface ReactionTemplate {
  path: string
  sheet_name: string
  has_gc_ms_yield_sheet?: boolean
  supported_experiment_counts: number[]
  param_rows: ParamRow[]
  params: Record<string, unknown>
  gc_ms_yield: GcMsYieldConfig
  headers: string[]
  rows: unknown[][]
  reagent_pair_count: number
}

export interface BatchInTemplate {
  path: string
  sheet_name: string
  headers: string[]
  tray_type_options: string[]
  rows: unknown[][]
}

export interface DashboardData {
  station_state: number | null
  glovebox_env: Record<string, unknown> | null
  device_status: Array<Record<string, unknown>>
  resources: Array<Record<string, unknown>>
  recent_tasks: Array<Record<string, unknown>>
  jobs: JobState[]
  errors: Record<string, string>
}

export interface JobState {
  job_id: string
  name: string
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'stopped'
  logs: LogEntry[]
  result?: unknown
  error?: string | null
  created_at?: string
  started_at?: string | null
  finished_at?: string | null
}

export type OuterDoorAction = 'open' | 'close'

export type W1ShelfAction = 'outside' | 'home'

export interface W1ShelfPayload {
  position: string
  action: W1ShelfAction
}

export interface JobCreateResponse {
  job_id: string
}

export type WorkflowStepId =
  | 'batch_in'
  | 'resource_check'
  | 'start_task'
  | 'wait_task'
  | 'batch_out'
  | 'auto_unload'
  | 'submit_analysis'
  | 'poll_analysis'
  | 'calculate_yields'

export type WorkflowStatus =
  | 'queued'
  | 'running'
  | 'pausing'
  | 'paused'
  | 'stopping'
  | 'stopped'
  | 'succeeded'
  | 'failed'

export type WorkflowStepStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'skipped' | 'stopped'

export type WorkflowBatchInMode = 'manual' | 'agv'

export interface WorkflowStepState {
  id: WorkflowStepId
  name: string
  status: WorkflowStepStatus
  result?: unknown
  error?: string | null
}

export interface WorkflowState {
  workflow_id: string
  job_id: string
  status: WorkflowStatus
  current_step: WorkflowStepId | null
  experiment_id: number
  experiment_name: string
  start_step: WorkflowStepId
  steps: WorkflowStepState[]
  logs: LogEntry[]
  result?: unknown
  error?: string | null
}

export interface WorkflowStartPayload {
  experiment_id: number
  experiment_name: string
  start_step: WorkflowStepId
  batch_in: {
    mode: WorkflowBatchInMode
    chamber_capacity: number
  }
  start_task: {
    check_glovebox_env: boolean
    water_limit_ppm: number
    oxygen_limit_ppm: number
  }
  wait_task: {
    poll_interval_s: number
  }
  has_analysis_task: boolean
  submit_analysis: {
    auto_submit_after_agv: boolean
  }
  poll_analysis: {
    poll_interval: number
  }
}

export interface WorkflowStartResponse {
  workflow_id: string
  job_id: string
  status: 'queued'
}

export interface ResourceCheckPayload {
  template: ReactionTemplate
  auto_generate_batch_file: boolean
}

export interface ReactionTemplateHistoryItem {
  task_id: number
  task_name: string
  experiment_count: number
}

export interface ReactionTemplateHistoryResponse {
  total: number
  page: number
  page_size: number
  items: ReactionTemplateHistoryItem[]
}

export async function fetchDashboard(): Promise<DashboardData> {
  const { data } = await http.get<DashboardData>('/api/synthesis/dashboard')
  return data
}

export async function fetchReactionTemplate(): Promise<ReactionTemplate> {
  const { data } = await http.get<ReactionTemplate>('/api/synthesis/reaction-template')
  return data
}

export async function saveReactionTemplate(payload: ReactionTemplate): Promise<ReactionTemplate> {
  const { data } = await http.put<ReactionTemplate>('/api/synthesis/reaction-template', payload)
  return data
}

export async function fetchReactionTemplateHistory(params?: {
  q?: string
  page?: number
  page_size?: number
}): Promise<ReactionTemplateHistoryResponse> {
  const { data } = await http.get<ReactionTemplateHistoryResponse>(
    '/api/synthesis/reaction-template/history',
    { params },
  )
  return data
}

export async function fetchHistoricalReactionTemplate(taskId: number): Promise<ReactionTemplate> {
  const { data } = await http.get<ReactionTemplate>(`/api/synthesis/reaction-template/history/${taskId}`)
  return data
}

export async function fetchBatchInTemplate(): Promise<BatchInTemplate> {
  const { data } = await http.get<BatchInTemplate>('/api/synthesis/batch-in-template')
  return data
}

export async function saveBatchInTemplate(payload: BatchInTemplate): Promise<BatchInTemplate> {
  const { data } = await http.put<BatchInTemplate>('/api/synthesis/batch-in-template', payload)
  return data
}

export async function printBatchInReagentLabels(payload: BatchInTemplate): Promise<JobCreateResponse> {
  const { data } = await http.post<JobCreateResponse>(
    '/api/synthesis/batch-in-template/print-reagent-labels',
    payload,
  )
  return data
}

export async function printBatchInTemplate(payload: BatchInTemplate): Promise<JobCreateResponse> {
  const { data } = await http.post<JobCreateResponse>('/api/synthesis/batch-in-template/print-table', payload)
  return data
}

export async function submitReactionTemplate(payload: ReactionTemplate): Promise<JobCreateResponse> {
  const { data } = await http.post<JobCreateResponse>('/api/synthesis/reaction-template/submit', payload)
  return data
}

export async function checkResource(payload: ResourceCheckPayload): Promise<JobCreateResponse> {
  const { data } = await http.post<JobCreateResponse>('/api/synthesis/resource-check', payload)
  return data
}

export async function initSynthesisDevice(): Promise<JobCreateResponse> {
  const { data } = await http.post<JobCreateResponse>('/api/synthesis/device-init')
  return data
}

export async function controlOuterDoor(action: OuterDoorAction): Promise<JobCreateResponse> {
  const { data } = await http.post<JobCreateResponse>('/api/synthesis/outer-door', { action })
  return data
}

export async function controlW1Shelf(payload: W1ShelfPayload): Promise<JobCreateResponse> {
  const { data } = await http.post<JobCreateResponse>('/api/synthesis/w1-shelf', payload)
  return data
}

export async function fetchJob(jobId: string): Promise<JobState> {
  const { data } = await http.get<JobState>(`/api/synthesis/jobs/${jobId}`)
  return data
}

export async function startSynthesisWorkflow(payload: WorkflowStartPayload): Promise<WorkflowStartResponse> {
  const { data } = await http.post<WorkflowStartResponse>('/api/synthesis/workflow/start', payload)
  return data
}

export async function fetchSynthesisWorkflow(workflowId: string): Promise<WorkflowState> {
  const { data } = await http.get<WorkflowState>(`/api/synthesis/workflow/${workflowId}`)
  return data
}

export async function pauseSynthesisWorkflow(workflowId: string): Promise<WorkflowState> {
  const { data } = await http.post<WorkflowState>(`/api/synthesis/workflow/${workflowId}/pause`)
  return data
}

export async function resumeSynthesisWorkflow(workflowId: string): Promise<WorkflowState> {
  const { data } = await http.post<WorkflowState>(`/api/synthesis/workflow/${workflowId}/resume`)
  return data
}

export async function stopSynthesisWorkflow(workflowId: string): Promise<WorkflowState> {
  const { data } = await http.post<WorkflowState>(`/api/synthesis/workflow/${workflowId}/stop`)
  return data
}

// 录入资源相关接口, 通过 /synthesis-api/api/* 反代到 eit_synthesis_station 设备 PC
// 字段命名与请求体形状与 web_code (dynamic-api/resource.ts) 完全一致, 不做改写

export interface InTrayResource {
  layout_code: string
  resource_type: string
  substance: string
  unit?: string
  amount?: number
  initial_volume?: number
  initial_weight?: number
  with_cap?: boolean
  with_magneton?: boolean
  color?: string
  material_batch_number?: string
  QR_code?: string
  chemical_id?: string
  [key: string]: unknown
}

export interface InTrayPayload {
  tray_QR_code: string
  resource_list: InTrayResource[]
}

export interface BatchInTrayItem {
  tray_layout_code: string
  resource_list: InTrayResource[]
  [key: string]: unknown
}

export interface BatchInTrayPayload {
  resource_req_list: BatchInTrayItem[]
  remark?: string
}

export async function inTray(payload: InTrayPayload): Promise<Record<string, unknown>> {
  const { data } = await http.post<Record<string, unknown>>('/synthesis-api/api/InTray', payload)
  return data
}

export async function batchInTray(payload: BatchInTrayPayload): Promise<Record<string, unknown>> {
  const { data } = await http.post<Record<string, unknown>>('/synthesis-api/api/BatchInTray', payload)
  return data
}

export async function getResourceInfo(filters: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
  const { data } = await http.post<Record<string, unknown>>('/synthesis-api/api/GetResourceInfo', filters)
  return data
}
