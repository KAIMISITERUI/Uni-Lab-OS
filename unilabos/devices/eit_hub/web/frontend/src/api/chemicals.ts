import axios, { type AxiosInstance } from 'axios'

// 与后端约定的化学品行结构, 字段尽量松散以兼容 extra_json 展开列
export interface ChemicalRow {
  id: number
  substance?: string | null
  cas_number?: string | null
  chemical_id?: string | null
  substance_english_name?: string | null
  physical_state?: string | null
  physical_form?: string | null
  storage_location?: string | null
  density?: number | null
  molecular_weight?: number | null
  active_content?: string | null
  smiles?: string | null
  brand?: string | null
  package_size?: string | null
  other_name?: string | null
  chemicalbook_record_path?: string | null
  created_at?: string | null
  updated_at?: string | null
  [key: string]: unknown
}

export interface ChemicalListResponse {
  total: number
  page: number
  page_size: number
  items: ChemicalRow[]
}

export type StructureSearchInputFormat = 'smiles' | 'molfile'
export type StructureSearchMatchMode = 'exact' | 'substructure'

export interface StructureSearchRequest {
  structure: string
  input_format: StructureSearchInputFormat
  match_mode: StructureSearchMatchMode
  page?: number
  page_size?: number
}

export interface StructureSearchResponse extends ChemicalListResponse {
  query_smiles: string
}

export interface DuplicateNameGroup {
  name: string
  rows: ChemicalRow[]
}

export interface IntegrityReport {
  duplicate_chinese_names: DuplicateNameGroup[]
  duplicate_english_names: DuplicateNameGroup[]
  missing_physical_state: ChemicalRow[]
  missing_physical_form: ChemicalRow[]
  neat_missing_molecular_weight: ChemicalRow[]
  neat_liquid_missing_density: ChemicalRow[]
  beads_solution_missing_content: ChemicalRow[]
}

export interface LookupResponse {
  success: boolean
  row_data?: Record<string, unknown> | null
  chemicalbook_status?: string | null
  chemicalbook_record_path?: string | null
  message?: string | null
}

export interface ImportResponse {
  migrated: number
  skipped: number
  failed: number
}

// axios 实例: 同源时 baseURL 为空, 开发期 vite 代理 /api 到后端
const http: AxiosInstance = axios.create({
  baseURL: '',
  timeout: 60000,
})

/**
 * 注入 X-API-Token 请求头. token 为空字符串时移除头.
 */
export function setApiToken(token: string): void {
  const trimmed = (token || '').trim()
  if (trimmed === '') {
    delete http.defaults.headers.common['X-API-Token']
  } else {
    http.defaults.headers.common['X-API-Token'] = trimmed
  }
}

export async function listChemicals(params: {
  q?: string
  page?: number
  page_size?: number
}): Promise<ChemicalListResponse> {
  const { data } = await http.get<ChemicalListResponse>('/api/chemicals', { params })
  return data
}

export async function searchChemicalsByStructure(
  payload: StructureSearchRequest,
): Promise<StructureSearchResponse> {
  const { data } = await http.post<StructureSearchResponse>(
    '/api/chemicals/structure-search',
    payload,
  )
  return data
}

export async function getChemical(id: number): Promise<ChemicalRow> {
  const { data } = await http.get<ChemicalRow>(`/api/chemicals/${id}`)
  return data
}

export async function getChemicalBySubstance(substance: string): Promise<ChemicalRow> {
  const { data } = await http.get<ChemicalRow>('/api/chemicals/by-substance', {
    params: { substance },
  })
  return data
}

export async function createChemical(payload: Partial<ChemicalRow>): Promise<ChemicalRow> {
  const { data } = await http.post<ChemicalRow>('/api/chemicals', payload)
  return data
}

export async function updateChemical(
  id: number,
  payload: Partial<ChemicalRow>,
): Promise<ChemicalRow> {
  const { data } = await http.put<ChemicalRow>(`/api/chemicals/${id}`, payload)
  return data
}

export async function deleteChemical(id: number): Promise<{ deleted: boolean }> {
  const { data } = await http.delete<{ deleted: boolean }>(`/api/chemicals/${id}`)
  return data
}

export async function lookupChemical(payload: {
  query: string
  query_type: 'cas' | 'name' | 'smiles'
}): Promise<LookupResponse> {
  const { data } = await http.post<LookupResponse>('/api/lookup', payload)
  return data
}

export async function fetchIntegrity(): Promise<IntegrityReport> {
  const { data } = await http.get<IntegrityReport>('/api/integrity')
  return data
}

/**
 * 触发 CSV 下载. 由浏览器自动处理 Content-Disposition 文件名.
 */
export function exportCsvUrl(): string {
  return '/api/export.csv'
}

/**
 * 触发 XLSX 下载. 由浏览器自动处理 Content-Disposition 文件名.
 */
export function exportXlsxUrl(): string {
  return '/api/export.xlsx'
}

/**
 * 上传 xlsx / csv 文件并追加到化学品库. dryRun=true 时仅统计不写入.
 */
export async function importChemicals(
  file: File,
  dryRun: boolean,
): Promise<ImportResponse> {
  const form = new FormData()
  form.append('file', file)
  form.append('dry_run', dryRun ? 'true' : 'false')
  const { data } = await http.post<ImportResponse>('/api/import', form)
  return data
}

export default http
