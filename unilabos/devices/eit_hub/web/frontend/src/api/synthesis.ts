import http from './http'

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
  status: 'queued' | 'running' | 'succeeded' | 'failed'
  logs: string[]
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
