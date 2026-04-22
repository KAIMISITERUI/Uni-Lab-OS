import http from './http'

export type AnalysisInstrumentKey = 'gc_ms' | 'uplc_qtof' | 'hplc'

export interface AnalysisStatusRow {
  instrument: AnalysisInstrumentKey
  name: string
  host: string
  port: number
  status: string
  connected: boolean
  error?: string
}

export interface AnalysisSampleRow {
  SampleName: string | number | null
  AcqMethod: string | number | null
  RackCode: string | number | null
  VialPos: string | number | null
  SmplInjVol: string | number | null
  OutputFile: string | number | null
}

export interface AnalysisSubmitPayload {
  tables: Record<AnalysisInstrumentKey, AnalysisSampleRow[]>
}

export interface AnalysisSubmitResponse {
  job_id: string
  status: 'queued'
  run_id: string
  saved_files: Partial<Record<AnalysisInstrumentKey, string>>
  skipped: AnalysisInstrumentKey[]
}

export async function fetchAnalysisStatus(): Promise<AnalysisStatusRow[]> {
  const { data } = await http.get<{ items: AnalysisStatusRow[] }>('/api/analysis/status')
  return data.items
}

export async function submitAnalysisTables(
  payload: AnalysisSubmitPayload,
): Promise<AnalysisSubmitResponse> {
  const { data } = await http.post<AnalysisSubmitResponse>('/api/analysis/submit', payload)
  return data
}
