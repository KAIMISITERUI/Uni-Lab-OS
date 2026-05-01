import http from './http'

export interface FilePresence {
  key: string
  label: string
  filename: string
  exists: boolean
  size_bytes: number | null
  mtime: string | null
}

export interface TaskHistoryItem {
  task_id: number
  task_name: string
  status: string | null
  created_at: string | null
  started_at: string | null
  completed_at: string | null
  files: FilePresence[]
}

export interface TaskHistoryListResponse {
  items: TaskHistoryItem[]
  total: number
}

export interface SheetPreview {
  sheet_name: string
  headers: string[]
  rows: unknown[][]
  truncated: boolean
}

export interface XlsxPreview {
  kind: 'xlsx'
  sheets: SheetPreview[]
}

export interface CsvPreview {
  kind: 'csv'
  headers: string[]
  rows: string[][]
  truncated: boolean
}

export type FilePreview = XlsxPreview | CsvPreview

export interface ImageGroupInfo {
  name: string
  label: string
  count: number
  images: string[]
  lazy: boolean
}

export interface TaskHistoryDetailResponse {
  task: TaskHistoryItem
  image_groups: ImageGroupInfo[]
}

export interface ImageListResponse {
  name: string
  label: string
  count: number
  images: string[]
}

export async function fetchTaskHistoryList(query?: string): Promise<TaskHistoryListResponse> {
  const params = query !== undefined && query !== '' ? { query } : undefined
  const { data } = await http.get<TaskHistoryListResponse>('/api/task-history/list', { params })
  return data
}

export async function fetchTaskHistoryDetail(taskId: number): Promise<TaskHistoryDetailResponse> {
  const { data } = await http.get<TaskHistoryDetailResponse>(`/api/task-history/${taskId}`)
  return data
}

export async function fetchFilePreview(taskId: number, fileKey: string): Promise<FilePreview> {
  const { data } = await http.get<FilePreview>(
    `/api/task-history/${taskId}/files/${encodeURIComponent(fileKey)}/preview`,
  )
  return data
}

export function downloadFileUrl(taskId: number, fileKey: string): string {
  return `/api/task-history/${taskId}/files/${encodeURIComponent(fileKey)}/download`
}

export async function fetchImageList(taskId: number, group: string): Promise<ImageListResponse> {
  const { data } = await http.get<ImageListResponse>(
    `/api/task-history/${taskId}/images/${encodeURIComponent(group)}`,
  )
  return data
}

export function imageUrl(taskId: number, group: string, filename: string, version?: number | string): string {
  const url = `/api/task-history/${taskId}/images/${encodeURIComponent(group)}/${encodeURIComponent(filename)}`
  if (version === undefined || version === '') {
    return url
  }
  return `${url}?v=${encodeURIComponent(String(version))}`
}


// ===== 业务视图 =====

export interface ParamRowEntry {
  name: string
  value: unknown
  row: number
  type: 'parameter' | 'section'
}

export interface ExperimentPlanResponse {
  task_id: number
  path: string
  sheet_name: string
  header_row: number
  experiment_column: number
  has_gc_ms_yield_sheet: boolean
  supported_experiment_counts: number[]
  param_rows: ParamRowEntry[]
  params: Record<string, unknown>
  headers: string[]
  rows: unknown[][]
  reagent_pair_count: number
  gc_ms_yield?: unknown
}

export interface TaskReportMeta {
  task_name: string | null
  operator: string | null
  task_status: string | null
  duration: string | null
  started_at: string | null
  completed_at: string | null
  created_at: string | null
  tray_model: string | null
  tray_barcode: string | null
  tray_position: string | null
}

export interface TaskReportStepCell {
  step_name: string
  status: unknown
  completed_at: string | null
  extras: unknown[]
}

export interface TaskReportStep {
  step_index: number
  step_label: string
  step_name: string
  extra_columns: string[]
  experiments: Record<string, TaskReportStepCell>
}

export interface TaskReportResponse {
  task_id: number
  sheet_name: string
  metadata: TaskReportMeta
  experiments: number[]
  steps: TaskReportStep[]
}

export interface CompoundCandidate {
  rank: number
  name: string
  score: number | null
  formula: string | null
  molecular_weight: number | null
  structure_image: string | null
}

export interface AlignmentEntry {
  fid_peak_no: number | null
  fid_rt: number | null
  fid_area: number | null
  tic_peak_no: number | null
  tic_rt: number | null
  ms_image: string | null
  candidates: CompoundCandidate[]
  pim_mw: number | null
  pim_confidence: number | null
  sshm_mw: number | null
  sshm_confidence: number | null
}

export interface TicPeak {
  peak_no: number | null
  rt: number | null
  height: number | null
  area: number | null
  area_pct: number | null
  start: number | null
  end: number | null
  width: number | null
  ms_image: string | null
  candidates: CompoundCandidate[]
  pim_mw: number | null
  pim_confidence: number | null
  sshm_mw: number | null
  sshm_confidence: number | null
}

export interface FidPeak {
  peak_no: number | null
  rt: number | null
  height: number | null
  area: number | null
  area_pct: number | null
  start: number | null
  end: number | null
  width: number | null
}

export interface IntegrationSample {
  name: string
  tic_peak_count: number | null
  fid_peak_count: number | null
  tic_total_area: number | null
  fid_total_area: number | null
  acquired_at: string | null
  tic_image: string | null
  fid_image: string | null
  tic_peaks: TicPeak[]
  fid_peaks: FidPeak[]
  alignments: AlignmentEntry[]
}

export interface IntegrationReportResponse {
  task_id: number
  samples: IntegrationSample[]
}

export interface YieldInternalStandard {
  name?: string
  smiles?: string
  formula?: string
  molecular_weight?: number
  nominal_mw?: number
  ecn?: number
  nist_recorded?: string
  nist_query_mode?: string
  dosage?: number
  mmol?: number
  expected_rt?: number | null
}

export interface YieldProductConfig {
  product_index: number
  name?: string
  smiles?: string
  formula?: string
  molecular_weight?: number
  nominal_mw?: number
  ecn?: number
  nist_recorded?: string
  nist_query_mode?: string
  expected_rt?: number | null
  applicable_experiments?: string
  equivalent?: number
}

export interface YieldConfig {
  calc_method: string | null
  reaction_scale: number | null
  internal_standard: YieldInternalStandard
  products: YieldProductConfig[]
}

export interface YieldResultEntry {
  product_name: string
  product_rt: number | null
  product_area: number | null
  product_match: string | null
  internal_rt: number | null
  internal_area: number | null
  internal_match: string | null
  ratio: number | null
  product_ecn: number | null
  internal_ecn: number | null
  yield_pct: number | null
  yield_display?: string
  match_method: string | null
  confidence: number | null
  nist_mw: number | null
  pim_mw: number | null
  sshm_mw: number | null
  remarks: string | null
}

export interface YieldSampleEntry {
  sample: string
  results: YieldResultEntry[]
}

export interface YieldReportResponse {
  task_id: number
  config: YieldConfig
  products: string[]
  samples: YieldSampleEntry[]
}

export async function fetchExperimentPlan(taskId: number): Promise<ExperimentPlanResponse> {
  const { data } = await http.get<ExperimentPlanResponse>(`/api/task-history/${taskId}/experiment-plan`)
  return data
}

export async function fetchTaskReport(taskId: number): Promise<TaskReportResponse> {
  const { data } = await http.get<TaskReportResponse>(`/api/task-history/${taskId}/task-report`)
  return data
}

export async function fetchIntegrationReport(
  taskId: number,
  refreshKey?: number | string,
): Promise<IntegrationReportResponse> {
  const params = refreshKey === undefined || refreshKey === '' ? undefined : { refresh_key: refreshKey }
  const { data } = await http.get<IntegrationReportResponse>(
    `/api/task-history/${taskId}/integration-report`,
    { params },
  )
  return data
}

export async function fetchYieldReport(
  taskId: number,
  refreshKey?: number | string,
): Promise<YieldReportResponse> {
  const params = refreshKey === undefined || refreshKey === '' ? undefined : { refresh_key: refreshKey }
  const { data } = await http.get<YieldReportResponse>(
    `/api/task-history/${taskId}/yield-report`,
    { params },
  )
  return data
}
