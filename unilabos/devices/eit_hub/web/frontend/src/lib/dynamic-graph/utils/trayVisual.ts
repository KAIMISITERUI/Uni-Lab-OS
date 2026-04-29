import type { GraphResource, GraphResourceChild } from '../runtime/api-shim'

export interface TrayVisualWell {
  slotIndex: number
  resourceType: string
  withCap?: boolean
  withMagneton?: boolean
  used?: boolean
  slotLabel?: string
}

export interface TrayVisualResourceInput {
  layoutCode: string
  trayModel: string
  wells: TrayVisualWell[]
}

export type TrayVisualMode = 'station' | 'thumbnail'

export type TrayVisualResource = GraphResource & Record<string, unknown>

/**
 * 功能:
 *   将托盘孔位视觉数据转换成 BaseTray.setResource 需要的资源结构.
 *   统一主 3D 大图, 录入预览图, 托盘缩略图的孔位, 容器, 盖子, 磁子显示入参.
 * 参数:
 *   input: 托盘位置码, 托盘型号, 已填充孔位列表.
 * 返回:
 *   TrayVisualResource, 可直接传给 applyTrayVisualResource 或 BaseTray.setResource.
 */
export function buildTrayVisualResource (input: TrayVisualResourceInput): TrayVisualResource {
  const children: GraphResourceChild[] = input.wells.map((well) => {
    const child: GraphResourceChild = {
      layout_code: `${input.layoutCode}:${well.slotIndex}`,
      slot_index: well.slotIndex,
      selected: true,
      used: well.used === true,
      display: true,
      resource_type: well.resourceType,
      with_cap: well.withCap !== false,
      with_magneton: well.withMagneton === true,
    }

    if (well.slotLabel !== undefined && well.slotLabel !== '') {
      child.slot_label = well.slotLabel
    }

    return child
  })

  return {
    children,
    layout_code: input.layoutCode,
    resource_type: input.trayModel,
    with_cap: children.some((child) => child.with_cap === true),
  }
}

/**
 * 功能:
 *   对托盘实例应用统一资源视觉, 并在当前帧内刷新孔位显示.
 * 参数:
 *   tray: BaseTray 实例.
 *   resource: 托盘资源结构, 通常来自 buildTrayVisualResource 或 GetResourceInfo 聚合结果.
 *   mode: station 表示工站槽位内托盘, thumbnail 表示独立缩略图.
 * 返回:
 *   void.
 */
export function applyTrayVisualResource (
  tray: any,
  resource: Record<string, any>,
  mode: TrayVisualMode = 'station',
): void {
  if (tray === undefined || tray === null || typeof tray.setResource !== 'function') {
    return
  }

  const normalizedResource = normalizeTrayVisualResource(resource)
  tray.setResource(normalizedResource)
  renderTrayImmediately(tray, mode)
}

/**
 * 功能:
 *   取消托盘实例上的节流渲染任务, 避免组件销毁后继续访问已释放的 zrender.
 * 参数:
 *   tray: BaseTray 实例.
 * 返回:
 *   void.
 */
export function cancelTrayVisualRender (tray: any): void {
  if (tray === undefined || tray === null) {
    return
  }
  cancelThrottle(tray.onResize)
  cancelThrottle(tray.alignToBottom)
}

function normalizeTrayVisualResource (resource: Record<string, any>): Record<string, any> {
  const layoutCode = String(resource.layout_code || '')
  const children = Array.isArray(resource.children)
    ? resource.children.map((child: Record<string, any>) => normalizeTrayVisualChild(child, layoutCode))
    : []

  return {
    ...resource,
    children,
  }
}

function normalizeTrayVisualChild (
  child: Record<string, any>,
  layoutCode: string,
): Record<string, any> {
  const normalized = { ...child }
  const slotIndex = Number(normalized.slot_index)
  if (Number.isFinite(slotIndex) === true) {
    normalized.slot_index = slotIndex
    if (typeof normalized.layout_code !== 'string' || normalized.layout_code === '') {
      normalized.layout_code = `${layoutCode}:${slotIndex}`
    }
  }

  if (normalized.display === undefined) {
    normalized.display = true
  }

  return normalized
}

function renderTrayImmediately (tray: any, mode: TrayVisualMode): void {
  try {
    tray.zr?.resize?.()
    flushThrottle(tray.onResize)
    syncTrayItems(tray)

    if (mode === 'thumbnail') {
      applyThumbnailScale(tray)
      if (typeof tray.alignToBottom === 'function') {
        tray.alignToBottom()
      }
      flushThrottle(tray.alignToBottom)
    }

    tray.res?.root?.dirty?.()
    tray.alone_group?.dirty?.()
    tray.zr?.flush?.()
  } catch (_error) {
    // 视觉刷新失败时保留 setResource 结果, 下一次 SyncManager 调度仍会补刷.
  }
}

function syncTrayItems (tray: any): void {
  const childrenCount = Array.isArray(tray.children) ? tray.children.length : 0
  if (typeof tray.syncItem !== 'function') {
    return
  }

  for (let index = 0; index < childrenCount; index++) {
    tray.syncItem(index)
  }
}

function applyThumbnailScale (tray: any): void {
  const zr = tray.zr
  if (
    zr === undefined ||
    zr === null ||
    tray.res === undefined ||
    tray.res === null ||
    tray.alone_group === undefined ||
    tray.alone_group === null
  ) {
    return
  }

  const width = zr.getWidth?.() || 1
  const height = zr.getHeight?.() || 1
  const scaleX = width / (tray.res.width || 1)
  const scaleY = height / (tray.res.height || 1)
  const scale = Math.min(scaleX, scaleY)
  tray.alone_group.setScale?.([scale, scale])
}

function flushThrottle (fn: any): void {
  if (typeof fn?.flush === 'function') {
    fn.flush()
  }
}

function cancelThrottle (fn: any): void {
  if (typeof fn?.cancel === 'function') {
    fn.cancel()
  }
}
