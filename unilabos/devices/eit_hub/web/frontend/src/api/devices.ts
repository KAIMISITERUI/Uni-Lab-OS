import http from './http'

export type DeviceStatusText = '在线' | '部分在线' | '离线'

export interface DeviceEndpointStatus {
  host: string
  port: number
  reachable: boolean
  latency_ms: number | null
  error: string
}

export interface DeviceStatusItem {
  key: string
  name: string
  category: string
  address: string
  reachable: boolean
  status: DeviceStatusText
  summary: string
  endpoints: DeviceEndpointStatus[]
}

export interface DeviceStatusResponse {
  checked_at: string
  items: DeviceStatusItem[]
}

export async function fetchDeviceStatus(): Promise<DeviceStatusResponse> {
  const { data } = await http.get<DeviceStatusResponse>('/api/devices/status')
  return data
}
