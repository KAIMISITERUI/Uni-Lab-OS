import http from './http'
import type { JobState } from './synthesis'

export interface LabelPrinterProfileItem {
  name: string
  stem: string
  path: string
}

export interface LabelPrinterProfileList {
  items: LabelPrinterProfileItem[]
}

export interface LabelPrinterConfig {
  printer: {
    ppi: number
  }
  paper: {
    width: number
    height: number
    unit: 'mm'
    columns: number
    column_gap: number
    margin: number
    gap: number
    gap_offset: number
    direction: 0 | 1
  }
  font: {
    name: string
    size: number
    bold: 0 | 1
    underline: 0 | 1
    rotation: 0 | 90 | 180 | 270
  }
  position: {
    x: number
    y: number
  }
}

export interface LabelPrinterProfile {
  name: string
  path: string
  config: LabelPrinterConfig
  columns: number
}

export interface LabelProfileSavePayload {
  config: LabelPrinterConfig
}

export interface LabelProfileSaveAsPayload {
  name: string
  config: LabelPrinterConfig
}

export interface LabelPrintPayload {
  profile: string
  rows: unknown[][]
}

export interface LabelPrintResponse {
  job_id: string
  status: 'queued'
}

export async function fetchLabelProfiles(): Promise<LabelPrinterProfileList> {
  const { data } = await http.get<LabelPrinterProfileList>('/api/label-printer/profiles')
  return data
}

export async function fetchLabelProfile(name: string): Promise<LabelPrinterProfile> {
  const { data } = await http.get<LabelPrinterProfile>(
    `/api/label-printer/profiles/${encodeURIComponent(name)}`,
  )
  return data
}

export async function saveLabelProfile(
  name: string,
  payload: LabelProfileSavePayload,
): Promise<LabelPrinterProfile> {
  const { data } = await http.put<LabelPrinterProfile>(
    `/api/label-printer/profiles/${encodeURIComponent(name)}`,
    payload,
  )
  return data
}

export async function saveLabelProfileAs(
  payload: LabelProfileSaveAsPayload,
): Promise<LabelPrinterProfile> {
  const { data } = await http.post<LabelPrinterProfile>('/api/label-printer/profiles', payload)
  return data
}

export async function printLabels(payload: LabelPrintPayload): Promise<LabelPrintResponse> {
  const { data } = await http.post<LabelPrintResponse>('/api/label-printer/print', payload)
  return data
}

export async function fetchLabelPrinterJob(jobId: string): Promise<JobState> {
  const { data } = await http.get<JobState>(`/api/label-printer/jobs/${jobId}`)
  return data
}
