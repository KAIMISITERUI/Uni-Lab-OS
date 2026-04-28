/**
 * 功能:
 *   工作站等距底图渲染入口, 解析 SVG 站点底图, 建立 slot 索引, 接收资源数据触发 vessel/cap/magneton 显隐.
 *   本副本相对原 dynamic-graph 仅保留 NTU 站点, 删除其它 station SVG 引用以缩减包体.
 * 主要导出:
 *   Station 类: create(zr, callback) 渲染并绑定点击, setResource(list) 更新内容, getSlot(layout_code) 取槽位.
 *   StationMap: 站点 model -> 原始 SVG 字符串映射.
 */
import * as Zrender from 'zrender'
import CanvasPainter from 'zrender/lib/canvas/Painter'
import type { SVGParserResult } from 'zrender/lib/tool/parseSVG'
import type { ZRenderType } from 'zrender'
import { Recorder, GraphCallback, RulerType } from 'Types/graph/graph'
import type { StationData } from 'Types/graph/station'
import type { ModelConfigDef } from 'Types/config/model'

// 仅保留 NTU 工作站底图, 其它工作站 SVG 已裁剪
import HAGONGDA from 'Models/NTU/HAGONGDA.svg'

import { handleLinear } from 'Utils/linear'
import { fixedSVG } from 'Utils/svg'
import { mathSlotTndir, travelZ } from 'Utils/zr'
import { getProp, getVesselConfig, getView, insertProp, isCapV2 } from 'Utils/utils'

import { BaseTray } from '../tray'
import { TraySlot } from './slot'
import SyncManager from '../tray/SyncManager'

Zrender.registerPainter('canvas', CanvasPainter)

interface GraphBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

const StationMap: Record<string, StationData> = {
  NTU: {
    raw: HAGONGDA
  }
}

/**
 * Station接口：
 * Station 整个站的对象
 *   - create 渲染并传入事件回调
 *   - slots  全部托盘位
 *   - getSlot 获取托盘位，返回托盘位对象
 */

class Station {
  recorder: Recorder;
  res: SVGParserResult | undefined;
  zr: ZRenderType | undefined;
  items: Record<string, Zrender.Displayable>;
  slots: Record<string, TraySlot>;
  disSelectSlot: boolean = false
  trays_group: Zrender.Group | undefined;
  station_cache: Record<string, any>;
  powder_amount_slot?: Zrender.TSpan;
  stationModel: string
  private fitBounds: GraphBounds = { x: 0, y: 0, width: 1, height: 1 };
  private currentScale = 1;
  private currentPosition: [number, number] = [0, 0];
  private viewportPadding: number;
  private setResourceDebounced: ((resource: any[]) => void) | null = null;

  constructor (stationModel?: string, raw?: string, viewportPadding: number = 24) {
    this.viewportPadding = Station.normalizeViewportPadding(viewportPadding)
    const _params = window?.webb?.store?.get?.('params') || {}
    const _container = _params.$view || ''
    if (StationMap[_container]?.mut) {
      Object.assign(StationMap, StationMap[_container].mut)
    }

    if (!stationModel) {
      const _ModelConfig = _params.model as ModelConfigDef

      if (_container && _ModelConfig?.station?.[_container]) {
        stationModel = _ModelConfig?.station?.[_container].model
      } else {
        throw new Error('station model is required')
      }
    }
    if (!StationMap[stationModel]) throw new Error(`Not found station ${stationModel}`)

    if (raw) {
      StationMap[stationModel] = { raw }
    }
    const locale = (window as any).i18n?.locale?.value
    if (locale !== 'zh' && StationMap[stationModel]?.[`raw_${locale}`]) {
      StationMap[stationModel] = { raw: StationMap[stationModel]?.[`raw_${locale}`] }
    }

    this.station_cache = StationMap[stationModel]
    this.stationModel = stationModel
    if (typeof this.station_cache.cached === 'undefined') {
      const parser = new DOMParser()
      const recorder: Recorder = {
        anchors: {},
        rulers: {}
      }
      const svg_dom = parser.parseFromString(fixedSVG(this.station_cache.raw, recorder, 0), 'text/xml')
      handleLinear(svg_dom)

      this.station_cache.dom = svg_dom.childNodes[0] as ChildNode
      this.station_cache.recorder = recorder
      this.station_cache.cached = true
    }

    this.recorder = this.station_cache.recorder
    this.items = {}
    this.slots = {}
    this.setResourceDebounced = this.debounce(this.setResourceInner.bind(this), 0) // 100ms 可根据实际调整
  }

  static isDisableClick (layout_code: string): boolean {
    if (!layout_code) return true
    const _params = window.webb.store.get('params')
    const { $view, model: _model } = _params
    const disableList = _model.disable_click_slots?.[$view]
    return !!disableList?.find?.(((item: string) => layout_code.startsWith(item)))
  }

  create (zr: Zrender.ZRenderType, callback: GraphCallback): void {
    this.res = Zrender.parseSVG(this.station_cache.dom, {})

    travelZ(this.res.root, 80000, 10000)

    this.hideAllLock()
    for (const named_item of this.res!.named) {
      if (named_item.name === 'GL3buffer_floor' && window.webb.store.get('params').noBuffer3) { named_item.el.hide() }
      if (named_item.namedFrom == null && named_item.name.startsWith('item_')) {
        insertProp(named_item.el, 'item_name', named_item.name)
      }
      insertProp(named_item.el, 'name', named_item.name)
    }

    for (const named_item of this.res!.named) {
      if (named_item.namedFrom === null && ['label', 'text', 'part', 'floor', 'large_floor'].includes(named_item.name)) {
        const parent_name = getProp(named_item.el.parent, 'item_name')
        const reg = /^item_[A-Za-z\d]+(-|\s)[A-Za-z\d]+$/
        reg.test(parent_name) && insertProp(named_item, 'name', `${parent_name}_${named_item.name}`)
      }
      if (named_item.namedFrom == null && named_item.name.startsWith('item_')) {
        this.items[named_item.name] = <Zrender.Displayable>named_item.el
      }
    }

    for (const key in this.items) {
      if (key.endsWith('_floor')) {
        const rulerTypeStr = [RulerType.large, RulerType.medium, RulerType.small].map((item: RulerType) => `_${item}`).join('|')
        const reg = new RegExp(`item_([A-Za-z\\d]+(.*\\d+)*)(_front|_right|_back|_left)?(${rulerTypeStr})?_floor`)
        const ma = key.match(reg)
        if (!ma) throw new Error(`unknow item label: ${key}`)

        const layout_code = ma[1]
        const tndir = mathSlotTndir(layout_code, this.stationModel) || 'left'
        if (!tndir) throw new Error(`No Match tndir layout_code:${layout_code}`)
        const size = rulerTypeStr.includes(ma[4]) ? ma[4] : RulerType.normal

        insertProp(this.items[key].parent, '_layout_code', layout_code)
        this.slots[layout_code] = new TraySlot(
          this,
          layout_code,
          `tray_${tndir}`,
          this.items[key],
          this.items[`item_${layout_code}_label`],
          this.items[`item_${layout_code}_text`],
          this.items[`item_${layout_code}_part`],
          this.station_cache,
          size
        )
      }
    }

    this.zr = zr
    zr.add(this.res!.root)
    this.trays_group = new Zrender.Group()
    zr.add(this.trays_group)
    this.fitBounds = this.measureFitBounds()
    this.zr.on('click', (a: any) => {
      if (typeof a.topTarget !== 'undefined') {
        let tar = a.topTarget
        while (typeof tar !== 'undefined') {
          if (typeof tar._layout_code !== 'undefined') {
            break
          }
          tar = tar.parent
        }

        if (typeof tar?._layout_code !== 'undefined' && !Station.isDisableClick(tar?._layout_code)) {
          callback.clickTray(tar._layout_code, a.offsetX, a.offsetY)
        }
      }
    })

    this.onResize()
  }

  onResize (): void {
    if (this.zr === undefined || this.res === undefined) {
      return
    }
    this.zr?.resize?.()

    const width = this.zr?.getWidth?.() || 1
    const height = this.zr?.getHeight?.() || 1
    const availableWidth = Math.max(width - this.viewportPadding * 2, 1)
    const availableHeight = Math.max(height - this.viewportPadding * 2, 1)

    const scale_x = availableWidth / this.fitBounds.width
    const scale_y = availableHeight / this.fitBounds.height
    const scale = Math.min(scale_x, scale_y)

    const centerX = (width - this.fitBounds.width * scale) / 2 - this.fitBounds.x * scale
    const centerY = (height - this.fitBounds.height * scale) / 2 - this.fitBounds.y * scale

    this.currentScale = scale
    this.currentPosition = [centerX, centerY]
    this.res?.root?.setScale?.([scale, scale])
    this.res?.root?.setPosition?.([centerX, centerY])
    this.res?.root?.dirty?.()
    this.trays_group?.setScale?.([scale, scale])
    this.trays_group?.setPosition?.([centerX, centerY])
    this.trays_group?.dirty?.()
    this.zr?.flush?.()
  }

  getContentAspectRatio (): number {
    return this.fitBounds.width / this.fitBounds.height
  }

  setViewportPadding (viewportPadding: number): void {
    this.viewportPadding = Station.normalizeViewportPadding(viewportPadding)
  }

  updateFitBoundsFromViewport (bounds: GraphBounds): void {
    this.fitBounds = {
      x: (bounds.x - this.currentPosition[0]) / this.currentScale,
      y: (bounds.y - this.currentPosition[1]) / this.currentScale,
      width: bounds.width / this.currentScale,
      height: bounds.height / this.currentScale
    }
  }

  getSlot (layout_code: string): TraySlot {
    return this.slots[layout_code]
  }

  hideAllLock ():void {
    this.res?.named.map((named: any) => {
      if (named.name.endsWith('_lock')) named.el.hide()
    })
  }

  private setResourceInner (resource: any[]): void {
    const _params = window.webb.store.get('params')
    const { $view, model: _model } = _params
    const ignore: string[] = _model.ignore_switch_cap_on_station?.[$view] || []
    let noTray: string[] = _model.no_tray_resource?.[$view]?.[this.stationModel] || _model.no_tray_resource?.[$view] || []
    if (!Array.isArray(noTray)) { noTray = [] }
    const reg = new RegExp(`^item_(${noTray.join('|')})(_|-|\\s)\\d+$`)

    // 1. 收集本次 resource 需要显示的 slot 名称
    const showSlotNames = new Set<string>()
    resource?.forEach((r: any) => {
      r.children.forEach((c: any) => {
        const arr = c?.layout_code?.split(':')
        arr[1] = Number(arr[1]) + 1
        const elName = `item_${arr.join('_')}`
        reg.test(elName) && showSlotNames.add(elName)
      })
    })

    // 只对 noTray 范围的元素做 show/hide
    if (noTray?.length) {
      Object.keys(this.items).forEach((name: string) => {
        if (reg.test(name)) {
          const el = this.items[name]
          const shouldShow = showSlotNames.has(name)
          if (shouldShow) {
            el.show()
          } else {
            el.hide()
          }
        }
      })
    }

    // 3. 批量收集需要更新的元素，减少 DOM 操作
    const updateQueue: Array<{
      slot: any;
      with_cap: boolean;
      cap_type: number;
      used: boolean;
      with_magneton: boolean;
      resource_type: string;
    }> = []

    const disableMagneton = _model.station?.[getView()]?.disableMagneton
    resource?.forEach((r: any) => {
      r.children.forEach((c: any) => {
        const { resource_type, used } = c
        let { with_cap } = c
        let { with_magneton } = c
        if (disableMagneton) { with_magneton = false }
        if (ignore?.find((item: string) => c.layout_code.startsWith(item))) { with_cap = true }
        const arr = c?.layout_code?.split(':')
        arr[1] = Number(arr[1]) + 1
        const slot: any = this.res?.named.find((named: any) => named.name === `item_${arr.join('_')}`)
        let cap_type: number | undefined = 0

        // 优化：预加载配置，避免在循环中重复调用 fromModel
        if (resource_type && _model?.tray?.[resource_type] && !BaseTray.modelConfigCache[resource_type]) {
          BaseTray.fromModel(resource_type, false)
        }
        if (resource_type && BaseTray.modelConfigCache[resource_type]) {
          cap_type = BaseTray.modelConfigCache[resource_type].capType
        }

        if (isCapV2()) {
          with_cap = !!c.cap_resource_type
          if (with_cap) {
            cap_type = getVesselConfig(c.cap_resource_type)?.cap_style || 1
          }
        }

        if (slot && slot.el) {
          updateQueue.push({
            slot,
            with_cap,
            used,
            cap_type: cap_type || 0,
            with_magneton,
            resource_type
          })
        }
      })
    })

    // 分批处理 updateQueue，防止主线程阻塞
    this.processUpdateQueueInBatches(updateQueue)

    // 只注册全局渲染任务
    SyncManager.addStationTask(this, 0)
  }

  private measureFitBounds (): GraphBounds {
    const rect = this.res!.root.getBoundingRect()
    return {
      x: rect.x,
      y: rect.y,
      width: rect.width,
      height: rect.height
    }
  }

  private static normalizeViewportPadding (viewportPadding: number): number {
    if (Number.isFinite(viewportPadding) === false || viewportPadding < 0) {
      return 0
    }
    return viewportPadding
  }

  // 修改 setResource 为防抖触发
  setResource (resource: any[]): void {
    this.setResourceDebounced?.(resource)
  }

  // 新增：批量更新槽位的方法
  private batchUpdateSlots (updateQueue: Array<{
    slot: any;
    with_cap: boolean;
    cap_type: number;
    used: boolean;
    with_magneton: boolean;
    resource_type: string;
  }>): void {
    // 使用 requestAnimationFrame 优化渲染性能
    if (updateQueue.length > 10) {
      // 大量更新时使用分批处理
      this.processUpdateQueueInBatches(updateQueue)
    } else {
      // 少量更新时直接处理
      updateQueue.forEach(({ slot, with_cap, cap_type, used, with_magneton, resource_type }: {
        slot: any;
        with_cap: boolean;
        cap_type: number;
        used: boolean;
        with_magneton: boolean;
        resource_type: string;
      }) => {
        this.updateSingleSlot(slot, with_cap, cap_type, used, with_magneton, resource_type)
      })
    }
  }

  // 新增：分批处理更新队列
  private processUpdateQueueInBatches (updateQueue: Array<{
    slot: any;
    with_cap: boolean;
    cap_type: number;
    used: boolean;
    with_magneton: boolean;
    resource_type: string;
  }>): void {
    const batchSize: number = 20
    let currentIndex: number = 0

    const processBatch = (): void => {
      const endIndex = Math.min(currentIndex + batchSize, updateQueue.length)

      for (let i = currentIndex; i < endIndex; i++) {
        const { slot, with_cap, cap_type, with_magneton, resource_type, used } = updateQueue[i]
        this.updateSingleSlot(slot, with_cap, cap_type, used, with_magneton, resource_type)
      }

      currentIndex = endIndex

      if (currentIndex < updateQueue.length) {
        // 继续处理下一批
        requestAnimationFrame(processBatch)
      }
    }

    requestAnimationFrame(processBatch)
  }

  private applyUsedInnerShadow (els: Zrender.Group[], used: boolean): void {
    try {
      els.forEach((el: any) => {
        if (!el) return
        // 迭代所有子节点，仅调整阴影样式，不改动 fill/stroke
        const stack: any[] = [el]
        while (stack.length) {
          const node = stack.pop()
          if (node && typeof node.setStyle === 'function') {
            if (used) {
              node.setStyle({
                shadowColor: 'rgba(0,0,0,0.9)',
                shadowBlur: 1,
                shadowOffsetX: 0,
                shadowOffsetY: 0
              })
            } else {
              node.setStyle({
                shadowBlur: 0
              })
            }
          }
          const children = node?.children?.()
          if (children && children.length) {
            for (let i = 0; i < children.length; i++) stack.push(children[i])
          }
        }
      })
    } catch (e) {
      console.warn('applyUsedInnerShadow error', e)
    }
  }
  // 新增：更新单个槽位
  private updateSingleSlot (slot: any, with_cap: boolean, cap_type: number, used: boolean, with_magneton: boolean, resource_type: string): void {
    slot.el?.children?.().forEach((child: any) => {
      if (child.name?.startsWith('vessel_')) {
        if (child.name === `vessel_${resource_type}`) {
          child.show()
          this.updateSingleSlot({ el: child }, with_cap, cap_type, used, with_magneton, resource_type)
        } else {
          child.hide()
        }
      } else {
        switch (child.name) {
          case 'cap_puncture':
            if (with_cap && cap_type === 2) {
              child.show()
            } else {
              child.hide()
            }
            break
          case 'cap_normal':
            if (with_cap && cap_type === 1) {
              child.show()
            } else {
              child.hide()
            }
            break
          case 'magneton':
            if (with_magneton) {
              child.show()
            } else {
              child.hide()
            }
            break
          default:
            break
        }
      }
    })
    if (used) {
      // this.applyUsedInnerShadow(slot.el?.children?.() || [], used)
    }
  }

  setPowderAmountSlot (text: string): void {
    if (!(this.powder_amount_slot instanceof Zrender.TSpan)) { return }
    if (text) {
      this.powder_amount_slot.attr('style', { text, fill: '#1239FF' })
      this.powder_amount_slot?.show?.()
    } else {
      this.powder_amount_slot?.hide?.()
    }
  }

  // 防抖函数实现
  private debounce (func: (...args: any[]) => void, wait: number): (...args: any[]) => void {
    let timeout: any
    return function (...args: any[]): void {
      clearTimeout(timeout)
      timeout = setTimeout(() => func(...args), wait)
    }
  }
}

export {
  Station,
  StationMap,
  Zrender,
  ZRenderType
}
