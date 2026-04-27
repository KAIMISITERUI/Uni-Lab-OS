import http from './http'

export interface MaintenanceEvent {
  id: string
  station: string
  title: string
  start_date: string
  interval_days: number
  enabled: boolean
  sort_order: number
  created_at: string
  updated_at: string
}

export interface MaintenanceRecord {
  record_id: string
  event_id: string
  due_date: string
  station_snapshot: string
  title_snapshot: string
  operator: string
  value_text: string
  note: string
  completed_at: string
  updated_at: string
  created_at?: string
}

export interface MaintenanceDueItem {
  event_id: string
  station: string
  title: string
  due_date: string
  start_date: string
  interval_days: number
  completed: boolean
  record: MaintenanceRecord | null
}

export interface MaintenanceOverviewStats {
  due_count: number
  pending_count: number
  completed_count: number
  overdue_count: number
}

export interface MaintenanceOverviewResponse {
  date: string
  due_items: MaintenanceDueItem[]
  overdue_items: MaintenanceDueItem[]
  stats: MaintenanceOverviewStats
}

export interface MaintenanceEventsResponse {
  events: MaintenanceEvent[]
  total: number
}

export interface MaintenanceEventPayload {
  station: string
  title: string
  start_date: string
  interval_days: number
  enabled: boolean
  sort_order?: number
}

export interface MaintenanceRecordSubmitItem {
  event_id: string
  due_date?: string
  value_text?: string
  note?: string
}

export interface MaintenanceBatchRecordPayload {
  date: string
  operator: string
  items: MaintenanceRecordSubmitItem[]
}

export interface MaintenanceBatchRecordResponse {
  saved_count: number
  records: MaintenanceRecord[]
}

export interface MaintenanceRecordsResponse {
  records: MaintenanceRecord[]
  total: number
}

export async function fetchMaintenanceOverview(dateText: string): Promise<MaintenanceOverviewResponse> {
  const { data } = await http.get<MaintenanceOverviewResponse>('/api/maintenance/overview', {
    params: { date: dateText },
  })
  return data
}

export async function fetchMaintenanceEvents(): Promise<MaintenanceEventsResponse> {
  const { data } = await http.get<MaintenanceEventsResponse>('/api/maintenance/events')
  return data
}

export async function createMaintenanceEvent(
  payload: MaintenanceEventPayload,
): Promise<MaintenanceEvent> {
  const { data } = await http.post<MaintenanceEvent>('/api/maintenance/events', payload)
  return data
}

export async function updateMaintenanceEvent(
  eventId: string,
  payload: MaintenanceEventPayload,
): Promise<MaintenanceEvent> {
  const { data } = await http.put<MaintenanceEvent>(
    `/api/maintenance/events/${encodeURIComponent(eventId)}`,
    payload,
  )
  return data
}

export async function submitMaintenanceRecords(
  payload: MaintenanceBatchRecordPayload,
): Promise<MaintenanceBatchRecordResponse> {
  const { data } = await http.post<MaintenanceBatchRecordResponse>(
    '/api/maintenance/records/batch',
    payload,
  )
  return data
}

export async function fetchMaintenanceRecords(
  startDate: string,
  endDate: string,
): Promise<MaintenanceRecordsResponse> {
  const { data } = await http.get<MaintenanceRecordsResponse>('/api/maintenance/records', {
    params: {
      start_date: startDate,
      end_date: endDate,
    },
  })
  return data
}
