/**
 * 功能:
 *   将 NTU Station 与 eit_synthesis_station 资源数据连接的最小控制器.
 *   职责:
 *     1. 在指定 DOM 上创建 zrender 实例并挂载 Station SVG 底图
 *     2. 周期性拉取资源列表, 按 layout_code diff 出新增/移除/换型, 同步到 Slot/Tray
 *     3. 调用 station.setResource() 触发 vessel/cap/magneton 显隐
 *   不包括: 资源录入对话框, 设备列表, 箱体环境, 库存计数 (那些由 SynthesisView 其它部分负责)
 */
import { getModule, type Module } from '../index'
import type { Station } from '../station/station'
import type { TraySlot } from '../station/slot'
import { applyTrayVisualResource } from '../utils/trayVisual'
import { createApi, type Api, type GraphResource } from './api-shim'

export interface StationGraphParams {
  containerId: string
  hostname?: string
  pollingIntervalMs?: number
  viewportPadding?: number
  // selected: true 表示该托盘点击后处于选中态, false 表示点击触发了取消选中 (toggle off)
  // 当 autoSelectOnClick 为 false 时, selected 始终为 true (保留旧行为)
  onClickTray?: (layout_code: string, x: number, y: number, selected: boolean) => void
  onClickBlank?: (x: number, y: number) => void
  onContextMenuTray?: (layout_code: string, x: number, y: number) => void
  onAfterRefresh?: () => void
  resourceLayoutFilter?: (layout_code: string) => boolean
  preserveFilteredOutResources?: boolean
  autoSelectOnClick?: boolean
}

interface ViewportBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

interface ViewportBoundsPadding {
  top?: number;
  right?: number;
  bottom?: number;
  left?: number;
}

interface SceneBoundsPadding {
  topRatio?: number;
  rightRatio?: number;
  bottomRatio?: number;
  leftRatio?: number;
}

export class StationGraph {
  private module: Module
  private api: Api
  public station: Station
  private zr: any | null = null
  private pollingTimer: any = null
  private lastResourceMap: Record<string, string> = {}
  private params: StationGraphParams

  constructor (params: StationGraphParams) {
    this.params = params
    this.module = getModule()
    this.api = createApi(params.hostname || '/synthesis-api')
    this.station = new this.module.Station('NTU', undefined, params.viewportPadding)
  }

  public mount (): void {
    const dom = document.getElementById(this.params.containerId)
    if (!dom) { throw new Error(`Container #${this.params.containerId} not found`) }
    // 兜底阻止浏览器默认右键菜单, 仅在容器 DOM 上, 不影响其它区域
    dom.addEventListener('contextmenu', (ev: MouseEvent) => {
      if (typeof this.params.onContextMenuTray === 'function') {
        ev.preventDefault()
      }
    })
    this.zr = this.module.Zrender.init(dom)
    this.zr.clear?.()
    this.station.create(this.zr, {
      clickTray: (layout_code: string, x: number, y: number) => {
        const slot = this.station.getSlot(layout_code) as TraySlot
        // toggle 行为: 同一托盘再次点击 → 取消选中; 否则切换至该托盘
        // selected 标志透传给上层, 用于决定详情浮卡是显示还是关闭
        let selectedAfter = true
        if (this.params.autoSelectOnClick !== false) {
          const wasSelected = slot?.selected === true
          // 先清掉其他绿框, 保证全局单选语义
          Object.values(this.station.slots).forEach((s: TraySlot) => {
            if (s !== slot && s.selected) {
              s.setSelected(false)
            }
          })
          if (wasSelected === true) {
            slot?.setSelected?.(false)
            selectedAfter = false
          } else {
            slot?.setSelected?.(true, '#0dbf75')
            selectedAfter = true
          }
        }
        if (typeof this.params.onClickTray === 'function') {
          this.params.onClickTray(layout_code, x, y, selectedAfter)
        }
      },
      contextMenuTray: (layout_code: string, x: number, y: number) => {
        if (typeof this.params.onContextMenuTray === 'function') {
          this.params.onContextMenuTray(layout_code, x, y)
        }
      },
      clickBlank: (x: number, y: number) => {
        if (typeof this.params.onClickBlank === 'function') {
          this.params.onClickBlank(x, y)
        }
      }
    })
  }

  /** 单次刷新: 拉资源, diff, 同步到 station */
  public async refresh (): Promise<void> {
    let resourceList = await this.api.getResource()
    if (this.station.stationModel) {
      resourceList = resourceList.filter(item => !item.station || item.station === this.station.stationModel)
    }
    if (typeof this.params.resourceLayoutFilter === 'function') {
      resourceList = resourceList.filter(item => this.params.resourceLayoutFilter?.(item.layout_code) === true)
    }
    // 仅保留当前 module.TrayMap 中已注册的托盘型号 (BaseTray.checkModel)
    resourceList = resourceList.filter(item => item.resource_type && this.module.BaseTray.checkModel(item.resource_type))

    const currentMap: Record<string, GraphResource> = {}
    resourceList.forEach(r => { currentMap[r.layout_code] = r })

    Object.keys(this.station.slots).forEach((layout_code: string) => {
      if (this.shouldPreserveFilteredOutSlot(layout_code) === true) {
        return
      }
      const slot = this.station.slots[layout_code] as TraySlot
      const cur = currentMap[layout_code]
      if (this.isNoTrayResourceLayout(layout_code) === true) {
        if (slot.hasTray() === true) {
          slot.removeTray()
        }
        return
      }
      if (cur !== undefined && slot.hasTray() === true) {
        if (cur.resource_type === slot.tray?.model) {
          // 同型号只刷新托盘内部视觉, 避免工站 SVG 内置孔位叠加.
          applyTrayVisualResource(slot.tray, cur as any, 'station')
        } else {
          // 换型, 移除老托盘后重建
          slot.removeTray()
          this.attachTray(slot, cur)
        }
      } else if (cur === undefined && slot.hasTray() === true) {
        slot.removeTray()
      } else if (cur !== undefined && slot.hasTray() === false) {
        this.attachTray(slot, cur)
      }
    })

    // 仅无托盘槽位使用工站底图内置资源, 常规槽位统一交给托盘 SVG.
    this.station.setResource(resourceList.filter(resource => this.isNoTrayResourceLayout(resource.layout_code) === true))
  }

  private shouldPreserveFilteredOutSlot (layoutCode: string): boolean {
    if (this.params.preserveFilteredOutResources !== true) {
      return false
    }
    if (typeof this.params.resourceLayoutFilter !== 'function') {
      return false
    }
    return this.params.resourceLayoutFilter(layoutCode) === false
  }

  private isNoTrayResourceLayout (layoutCode: string): boolean {
    return this.getNoTrayResourcePrefixes().some(prefix => layoutCode.startsWith(prefix))
  }

  private getNoTrayResourcePrefixes (): string[] {
    const params = window.webb.store.get('params') || {}
    const $view = params.$view
    const _model = params.model || {}
    const noTray = _model.no_tray_resource?.[$view]?.[this.station.stationModel || ''] || _model.no_tray_resource?.[$view] || []
    if (Array.isArray(noTray) === false) {
      return []
    }
    return noTray
  }

  /** 在 slot 上实例化并附着 BaseTray */
  private attachTray (slot: TraySlot, resource: GraphResource): void {
    if (this.isNoTrayResourceLayout(slot.layout_code) === true) {
      return
    }
    if (resource.resource_type === undefined || resource.resource_type === '') { return }
    let trayInstance: any = null
    try {
      trayInstance = this.module.BaseTray.fromModel(resource.resource_type)
    } catch (err) {
      console.warn('[StationGraph] fromModel failed:', resource.resource_type, err)
      return
    }
    if (trayInstance === undefined || trayInstance === null) { return }
    slot.setTray(trayInstance)
    applyTrayVisualResource(trayInstance, resource as any, 'station')
  }

  /** 启动周期轮询 (默认 10s) */
  public startPolling (intervalMs?: number): void {
    const interval = intervalMs || this.params.pollingIntervalMs || 10_000
    this.stopPolling()
    let busy = false
    const tick = async () => {
      if (busy) { return }
      if (typeof document !== 'undefined' && document.visibilityState !== 'visible') { return }
      busy = true
      try {
        await this.refresh()
        if (typeof this.params.onAfterRefresh === 'function') {
          this.params.onAfterRefresh()
        }
      } catch (err) {
        console.error('[StationGraph] refresh error:', err)
      } finally {
        busy = false
      }
    }
    void tick()
    this.pollingTimer = setInterval(tick, interval)
  }

  public stopPolling (): void {
    if (this.pollingTimer) {
      clearInterval(this.pollingTimer)
      this.pollingTimer = null
    }
  }

  public onResize (): void {
    this.zr?.resize?.()
    this.station?.onResize?.()
  }

  public setViewportPadding (viewportPadding: number): void {
    this.params.viewportPadding = viewportPadding
    this.station.setViewportPadding(viewportPadding)
  }

  public resetContentBounds (): void {
    this.station.resetFitBounds()
  }

  public fitVisibleScene (padding?: SceneBoundsPadding): number {
    this.station.updateFitBoundsFromVisibleScene(padding)
    return this.getContentAspectRatio()
  }

  public getContentAspectRatio (): number {
    return this.station.getContentAspectRatio()
  }

  public calibrateContentBounds (padding?: ViewportBoundsPadding): number {
    const bounds = this.measureCanvasContentBounds(padding)
    if (bounds !== null) {
      this.station.updateFitBoundsFromViewport(bounds)
    }
    return this.getContentAspectRatio()
  }

  public destroy (): void {
    this.stopPolling()
    try { this.zr?.dispose?.() } catch (_e) { /* noop */ }
    this.zr = null
  }

  private measureCanvasContentBounds (padding?: ViewportBoundsPadding): ViewportBounds | null {
    const dom = document.getElementById(this.params.containerId)
    if (dom === null) {
      return null
    }
    const canvas = dom.querySelector('canvas')
    if (canvas instanceof HTMLCanvasElement === false) {
      return null
    }
    const rect = canvas.getBoundingClientRect()
    const context = canvas.getContext('2d')
    if (context === null) {
      return null
    }

    const imageData = context.getImageData(0, 0, canvas.width, canvas.height).data
    let minX = canvas.width
    let minY = canvas.height
    let maxX = -1
    let maxY = -1

    for (let y = 0; y < canvas.height; y++) {
      for (let x = 0; x < canvas.width; x++) {
        const index = (y * canvas.width + x) * 4
        if (imageData[index + 3] > 0) {
          minX = Math.min(minX, x)
          minY = Math.min(minY, y)
          maxX = Math.max(maxX, x)
          maxY = Math.max(maxY, y)
        }
      }
    }

    if (maxX < minX || maxY < minY) {
      return null
    }

    const scaleX = rect.width / canvas.width
    const scaleY = rect.height / canvas.height
    const padded = this.normalizeViewportBoundsPadding(padding)
    return {
      x: minX * scaleX - padded.left,
      y: minY * scaleY - padded.top,
      width: (maxX - minX + 1) * scaleX + padded.left + padded.right,
      height: (maxY - minY + 1) * scaleY + padded.top + padded.bottom
    }
  }

  private normalizeViewportBoundsPadding (padding?: ViewportBoundsPadding): Required<ViewportBoundsPadding> {
    return {
      top: this.normalizePaddingValue(padding?.top),
      right: this.normalizePaddingValue(padding?.right),
      bottom: this.normalizePaddingValue(padding?.bottom),
      left: this.normalizePaddingValue(padding?.left)
    }
  }

  private normalizePaddingValue (value?: number): number {
    if (typeof value !== 'number') {
      return 0
    }
    if (Number.isFinite(value) === false || value < 0) {
      return 0
    }
    return value
  }
}
