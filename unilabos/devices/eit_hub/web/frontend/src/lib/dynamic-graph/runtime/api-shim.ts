/**
 * 功能:
 *   通过 Vite 代理调用 eit_synthesis_station 设备 PC 上的 /api/GetResourceInfo,
 *   并将后端返回的扁平资源列表按 LAYOUT:INDEX 规则聚合为带 children 的 tray 结构.
 * 数据流:
 *   POST /synthesis-api/api/GetResourceInfo  body { roll: 'normal' }
 *     -> { resource_list: [{ layout_code, resource_type, ... }, ...] }
 *     -> 聚合后 [{ layout_code, resource_type, children: [{ slot_index, ... }, ...] }, ...]
 */
import axios from 'axios'

export interface FlatResource {
  layout_code: string
  resource_type?: string
  station?: string
  tray_QR_code?: string
  cap_resource_type?: string
  with_cap?: boolean
  with_magneton?: boolean
  used?: boolean
  status?: number
  [key: string]: any
}

export interface GraphResourceChild extends FlatResource {
  slot_index: number
}

export interface GraphResource {
  layout_code: string
  resource_type?: string
  station?: string
  tray_QR_code?: string
  status?: number
  children: GraphResourceChild[]
}

export function createApi (baseURL: string) {
  const http = axios.create({ baseURL, headers: { 'Content-Type': 'application/json' } })

  return {
    /**
     * 拉取当前工作站的资源列表并按 tray/children 聚合.
     * 与原 dynamic-api 的 getResource 行为一致: 把 LAYOUT:INDEX 形态的扁平条目挂到 layout_code 父托盘下.
     */
    async getResource (): Promise<GraphResource[]> {
      const res = await http.post('/api/GetResourceInfo', { roll: 'normal' })
      // 后端可能用 data 或 resource_list 字段返回, 两种都兼容
      let raw: FlatResource[] = res?.data?.resource_list
      if (!Array.isArray(raw) && Array.isArray(res?.data?.data)) { raw = res.data.data }
      if (!Array.isArray(raw)) { throw new Error('Invalid /api/GetResourceInfo response') }

      const grouped: GraphResource[] = []
      const findOrCreate = (layout_code: string, item: FlatResource): GraphResource => {
        const exist = grouped.find(g => g.layout_code === layout_code && g.station === item.station)
        if (exist) { return exist }
        const created: GraphResource = {
          layout_code,
          resource_type: item.resource_type,
          station: item.station,
          tray_QR_code: item.tray_QR_code || '',
          status: item.status,
          children: []
        }
        grouped.push(created)
        return created
      }

      raw.forEach((item: FlatResource) => {
        const code = item.layout_code || ''
        if (code.includes(':')) {
          const [trayLayout, idxStr] = code.split(':')
          const slot_index = Number(idxStr)
          if (slot_index === -1) {
            // 兼容空托盘标记 (LAYOUT:-1), 仅占位
            findOrCreate(trayLayout, item)
            return
          }
          const tray = findOrCreate(trayLayout, item)
          tray.children.push({ ...item, slot_index })
        } else {
          // 整张直接顶层挂载, 无 children
          findOrCreate(code, item)
        }
      })
      return grouped
    }
  }
}

export type Api = ReturnType<typeof createApi>
