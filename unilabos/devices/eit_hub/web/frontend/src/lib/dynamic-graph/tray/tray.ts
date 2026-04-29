import * as Zrender from 'zrender'
import type { SVGParserResult } from 'zrender/lib/tool/parseSVG'
import type { ZRenderType } from 'zrender'
import { ChildAttr } from 'Types/graph/tray'
import type { SlotLabelInfo, TrayConfig } from 'Types/model/tray'
import { Recorder, RecordItem } from 'Types/graph/graph'

import { handleLinear } from 'Utils/linear'
import { fixedSVG } from 'Utils/svg'
import { travelZ } from 'Utils/zr'
import { getTrayRulerAnchor } from 'Utils/ruler'
import { getIndexArr, getVesselConfig, insertProp, isCapV2, isFSY } from 'Utils/utils'
import { mathWellPlates } from 'Utils/model_ruler'
import { syncPart } from 'Utils/syncPart'
import { isNaN, flattenDeep, throttle } from 'lodash'
import { TrayMap } from './cache'
import SyncManager from './SyncManager'

// 根据配置计算矩阵格式孔位
function calcSlotsMatrix (config: TrayConfig): SlotLabelInfo[][] {
  const { $view } = window.webb.store.get('params')
  const { row = 1, col = 1, layout } = config
  const slotInMultipleRows = [false, true].includes(config[$view]?.slotInMultipleRows) ? config[$view]?.slotInMultipleRows : config.slotInMultipleRows

  const { start = 'lb', direction = 'y', charPosition = 'top', groupedOriginChar = 'A' } = layout || {}
  const [ rStart = 'l', cStart = 'b' ] = start
  const originCharCode = groupedOriginChar?.charCodeAt?.(0) || 65
  const curChar = (index: number): string => String.fromCharCode(originCharCode + index - 1)
  const ischarLeft = slotInMultipleRows && charPosition === 'left'
  const isCharTop = slotInMultipleRows && charPosition === 'top'

  const result = getIndexArr(row).map((r: number) => {
    const _r = cStart === 'b' ? row - r + 1 : r
    let charLabel = ''
    if (ischarLeft) { charLabel = curChar(_r) }

    return getIndexArr(col).map((c: number) => {
      const _c = rStart === 'r' ? col - c + 1 : c
      if (isCharTop) { charLabel = curChar(_c) }

      const slot_index = direction === 'y' ? row * (_c - 1) + _r - 1 : col * (_r - 1) + _c - 1
      const slot_label = charLabel ? `${charLabel}${isCharTop ? _r : _c}` : `${slot_index + 1}`

      return {
        rowIndexLabel: ischarLeft ? charLabel : `${_r}`,
        colIndexLabel: isCharTop ? charLabel : `${_c}`,
        rowNum: _r,
        colNum: _c,
        slot_index,
        slot_label
      }
    })
  })

  return result
}

function calcSlotLabels (config: TrayConfig): string[] {
  return flattenDeep(calcSlotsMatrix(config)).sort((a: SlotLabelInfo, b:SlotLabelInfo) => (a.slot_index > b.slot_index ? 1 : -1)).map((item: SlotLabelInfo) => item.slot_label)
}

/**
 * BaseTray接口
 * BaseTray 托盘对象
 *  - fromModel 从型号创建
 *  - createAlone 渲染（单独看托盘）
 *  - children 下一级资源（如试管）
 *  - children_count 下一级资源数量
 *  - sync 状态同步。如下级资源修改了，需调用此接口
 */
class BaseTray {
  model: string;
  model_var: string;
  resource: Record<string, any> | undefined;
  cache_obj: Record<string, any>;
  children_count: number;
  children: ChildAttr[];
  child_nodes: Record<string, Zrender.Group[]>;
  slotLabels: string[];
  tray_cover: any
  used_cap_tray: any

  res: SVGParserResult | undefined;

  zr: ZRenderType | undefined;
  alone_group: Zrender.Group | undefined;
  layout_code?: string | undefined
  trayDirection?: string | undefined

  config: TrayConfig;
  capType?: number

  // 优化：SVG 模板缓存粒度细化，按不同视图分别缓存
  static svgTemplateCache: Record<string, {
    dom: any;
    recorder: any;
  }> = {}

  // 新增：slotLabels 缓存
  static slotLabelsCache: Record<string, string[]> = {}

  // 新增：虚拟化渲染支持
  static enableVirtualization: boolean = false // 暂时禁用虚拟化，确保所有元素都能渲染
  static visibleRange: { start: number; end: number } = { start: 0, end: 100 }

  // 优化：SVGParserResult 缓存，按不同视图分别缓存（修正：只缓存 DOM，始终重新 parseSVG，避免对象引用问题）
  static svgDomCache: Record<string, any> = {}

  // 缓存命中统计
  static svgDomCacheHit: number = 0
  static svgDomCacheMiss: number = 0
  static cacheAutoClearTimer: any = null

  constructor (params: TrayConfig) {
    const _params = window.webb.store.get('params')
    const { $view } = _params

    this.config = Object.assign(params, params[$view] || {})
    this.model = params.model
    this.model_var = params.model
    this.resource = undefined
    this.cache_obj = { ...params }
    this.children_count = params.children_count
    this.children = []
    this.capType = this.config.capType

    // 优化：缓存 slotLabels 计算
    const slotLabelsKey = `${this.model}_${this.children_count}_${JSON.stringify(this.config.layout || {})}`
    if (BaseTray.slotLabelsCache[slotLabelsKey]) {
      this.slotLabels = BaseTray.slotLabelsCache[slotLabelsKey]
    } else {
      this.slotLabels = calcSlotLabels(this.config)
      BaseTray.slotLabelsCache[slotLabelsKey] = this.slotLabels
    }

    const with_cap = this.config.isCapTray ? true : !!this.config?.with_cap?.[$view]
    const with_magneton = !!this.config?.with_magneton?.[$view]

    for (let idx = 0; idx < this.children_count; idx++) {
      this.children.push({
        display: true,
        highlight: false,
        selected: false,
        used: false,
        with_cap,
        cap_type: this.capType,
        resource_type: '',
        with_magneton
      })
    }
    this.child_nodes = {}
  }

  static checkModel (model: string): boolean {
    let _model = model
    const wp = mathWellPlates(model)
    if (wp) { _model = wp.model }
    return !!TrayMap[_model]
  }

  // 从型号创建出型号实例 model:型号名称 isBuild:是否构建svg数据(可视化时需要构建，仅获取型号配置时不需要构建)
  static fromModel (model: string, isBuild: boolean = true): BaseTray {
    const startTime = performance.now()

    let _model = model
    const wp = mathWellPlates(model)
    if (wp) { _model = wp.model }

    if (!TrayMap[_model]) {
      const msg = `unknow Model: ${_model}`
      throw new Error(msg)
    }

    // 优化：如果只需要配置信息，直接返回轻量实例
    if (!isBuild && BaseTray.modelConfigCache[model]) {
      const config = BaseTray.modelConfigCache[model]
      const trayIns = new (TrayMap[_model])(false)
      trayIns.config = config

      const endTime = performance.now()
      const duration = endTime - startTime

      if (duration > 10) { // 超过 10ms 记录警告
        console.warn(`BaseTray.fromModel(${model}) took ${duration.toFixed(2)}ms`)
      }

      return trayIns
    }

    const trayIns = new (TrayMap[_model])(isBuild)

    if (wp?.height) {
      trayIns.model_var = model
    }

    BaseTray.modelConfigCache[model] = { ...trayIns.config }

    const endTime = performance.now()
    const duration = endTime - startTime

    if (duration > 50) { // 超过 50ms 记录警告
      console.warn(`BaseTray.fromModel(${model}, ${isBuild}) took ${duration.toFixed(2)}ms`)
    }

    // 调试：记录创建的实例
    console.log(`Created tray instance: ${model}, instance ID: ${trayIns.model_var}, isBuild: ${isBuild}`)

    return trayIns
  }

  static modelConfigCache: Record<string, TrayConfig> = {}

  static isHideTray (layout_code: string | undefined): boolean {
    if (!layout_code) return false
    const _params = window.webb.store.get('params')
    const { $view, model: _model } = _params
    const hideTrayList = _model.hide_tray[$view]
    return !!hideTrayList?.find?.(((item: string) => layout_code.startsWith(item)))
  }

  static isHideTrayV2 (layout_code: string | undefined): boolean {
    if (!layout_code) return false
    const _params = window.webb.store.get('params')
    const { $view, model: _model } = _params
    const hideTrayList = _model.hide_tray_v2?.[$view]
    return !!hideTrayList?.find?.(((item: string) => layout_code.startsWith(item)))
  }

  // 扩展新型号
  static extendModel (params: TrayConfig, isForce?: boolean): void {
    if (!params.model) throw new Error('model is required')
    if (!(params.children_count >= 0 && typeof params.children_count === 'number')) {
      throw new Error('invalid children_count')
    }
    if (TrayMap[params.model] && !isForce) return

    const newFunc = function (isBuild: boolean = true): BaseTray {
      const baseTray = new BaseTray({ ...params })
      isBuild && baseTray.buildCache()
      return baseTray
    }
    newFunc.prototype = BaseTray.prototype

    TrayMap[params.model] = newFunc
  }

  static includeModels (models: string[]): void {
    Object.keys(TrayMap).map((m: string) => {
      !models.includes(m) && delete TrayMap[m]
    })
  }

  static getAllModels (): Array<BaseTray> {
    return Object.keys(TrayMap).map((model: string) => {
      return new (TrayMap[model])(false)
    }).sort((tray1: BaseTray, tray2: BaseTray) => {
      return tray1.getConfig().model > tray2.getConfig().model ? 1 : -1
    }).sort((tray1: BaseTray, tray2: BaseTray) => {
      const config1 = tray1.getConfig()
      const config2 = tray2.getConfig()
      if (config1.weight === undefined && config2.weight === undefined) {
        return 0
      }
      return (config1.weight || 0) > (config2.weight || 0) ? 1 : -1
    })
  }

  static mathWellPlates: typeof mathWellPlates = mathWellPlates

  getConfig (): TrayConfig {
    return { ...this.config }
  }

  setResource (resource: Record<string, any>): void {
    if (isFSY() && ['IR-1', 'IR-3', 'IR-5'].includes(resource?.layout_code)) {
      resource.used = true
    }

    this.resource = resource
    // 优化：提前缓存常用对象，减少循环内访问
    const vessel_configs = window.webb.store.get('params').model.vessel
    const { children } = this
    const { config } = this
    let { capType } = this

    // 先全部隐藏，后面只显示有用的
    for (let i = 0; i < children.length; i++) {
      children[i].display = false
    }

    // 批量处理 children
    if (Array.isArray(resource?.children)) {
      for (let i = 0; i < resource.children.length; i++) {
        const item = resource.children[i]
        if ('cap_type' in item) capType = item.cap_type
        const { slot_index, used, resource_type, with_tube } = item
        let cap_variation = config?.cap_variation?.[resource_type]
        let with_cap = !!item.with_cap
        const with_magneton = (config?.isMagnetonTray) ? true : !!item.with_magneton
        const _used = config?.isCapTray ? false : !!used
        let cap_type = capType

        if (vessel_configs[resource_type]) {
          cap_variation = vessel_configs[resource_type].cap_type || vessel_configs[resource_type].cap_style
        }
        if (resource_type && BaseTray.checkModel(resource_type) && !BaseTray.modelConfigCache[resource_type]) {
          BaseTray.fromModel(resource_type, false)
        }
        if (resource_type && BaseTray.modelConfigCache[resource_type]) {
          cap_type = BaseTray.modelConfigCache[resource_type].cap_type
        }
        if (isCapV2()) {
          with_cap = !!item.cap_resource_type
          if (with_cap) {
            cap_variation = getVesselConfig(item.cap_resource_type)?.cap_style || 1
          }
        }

        if (config?.isCapTray || with_tube) { with_cap = true }

        // 只对有效 slot_index 赋值
        if (children[slot_index]) {
          const child = children[slot_index]
          child.display = true
          child.with_cap = !!with_cap
          child.with_magneton = !!with_magneton
          child.cap_type = cap_variation || cap_type
          child.used = _used
          child.resource_type = resource_type
        }
      }
    }

    this.used_cap_tray && (resource?.used ? this.used_cap_tray.el.show() : this.used_cap_tray.el.hide())
    this.tray_cover && (resource?.with_cap ? this.tray_cover.el.show() : this.tray_cover.el.hide())
    // 只同步可见/变化的 children
    this.sync()
  }

  svgDOM (svg_xml: string, renum: number = 0): any {
    const parser = new DOMParser()
    const svg_dom = parser.parseFromString(svg_xml, 'text/xml')
    handleLinear(svg_dom)

    const gs = svg_dom.getElementsByTagName('g')
    for (let i = 0; i < gs.length; i++) {
      const gEle = gs[i]
      const attrLabel = gEle?.getAttribute?.('inkscape:label')

      if (attrLabel?.startsWith?.('item_') && Number(gEle?.childNodes?.length) > 0) {
        let _label = attrLabel
        if (renum > 0) {
          const n = parseInt(_label.slice(5), 10)
          if (renum > n) {
            _label = `item_${renum - n}`
          }
        }
      }
    }
    return svg_dom.childNodes[0]
  }

  buildCache (): void {
    try {
      const cache_obj = this.cache_obj as Record<string, any>
      if (!cache_obj.cached) {
        const trayTypes = ['tray_front', 'tray_right', 'tray_back', 'tray_left']
        const renum = (this.config?.fixed_slot_index || this.children_count) + 1
        trayTypes.forEach((tndir: string) => {
          const cacheKey = `${this.model}_${this.children_count}_${tndir}`
          if (BaseTray.svgTemplateCache[cacheKey]) {
            const template = BaseTray.svgTemplateCache[cacheKey]
            cache_obj[`${tndir}_dom`] = this.cloneSVGDOM(template.dom)
            cache_obj[`${tndir}_recorder`] = JSON.parse(JSON.stringify(template.recorder))
          } else {
            cache_obj[`${tndir}_recorder`] = { anchors: {}, rulers: {} }
            let svgRaw = cache_obj[tndir]
            let dom
            if (!svgRaw && (tndir === 'tray_back' || tndir === 'tray_left')) {
              const refType = tndir === 'tray_back' ? 'tray_front' : 'tray_right'
              svgRaw = cache_obj[refType]
              dom = this.svgDOM(fixedSVG(svgRaw, cache_obj[`${tndir}_recorder`], renum), renum)
            } else if (svgRaw) {
              dom = this.svgDOM(fixedSVG(svgRaw, cache_obj[`${tndir}_recorder`]))
            }
            cache_obj[`${tndir}_dom`] = dom
            BaseTray.svgTemplateCache[cacheKey] = {
              dom: dom?.cloneNode(true),
              recorder: JSON.parse(JSON.stringify(cache_obj[`${tndir}_recorder`]))
            }
          }
          // 新增：缓存 DOM 源数据，供 parseSVG 使用
          if (BaseTray.svgDomCache[cacheKey]) {
            BaseTray.svgDomCacheHit++
          } else {
            BaseTray.svgDomCacheMiss++
          }
          BaseTray.svgDomCache[cacheKey] = cache_obj[`${tndir}_dom`]
        })
        trayTypes.forEach((tndir: string) => {
          const ruler_anchor = getTrayRulerAnchor(cache_obj[`${tndir}_recorder`])
          if (!ruler_anchor) {
            throw new Error(`ruler_anchor not found in ${this.model}_${tndir}`)
          }
        })
        cache_obj.cached = true
      }
      // 启动定时自动清理缓存
      if (!BaseTray.cacheAutoClearTimer) {
        BaseTray.cacheAutoClearTimer = setInterval(() => {
          BaseTray.smartClearCache()
          // 输出命中率日志
        }, 5 * 60 * 1000) // 5分钟
      }
    } catch (error) {
      console.error(error)
    }
  }

  // 新增：轻量级 SVG DOM 克隆方法
  private cloneSVGDOM (originalDOM: any): any {
    // 修复：使用深度克隆确保完整的 DOM 结构
    const cloned = originalDOM.cloneNode(true)

    // 确保克隆的元素有正确的属性
    if (originalDOM.hasAttribute('name')) {
      cloned.setAttribute('name', originalDOM.getAttribute('name'))
    }
    if (originalDOM.hasAttribute('inkscape:label')) {
      cloned.setAttribute('inkscape:label', originalDOM.getAttribute('inkscape:label'))
    }

    return cloned
  }

  createAlone (tndir: string, zr: Zrender.ZRenderType): void {
    this.zr = zr
    this.alone_group = new Zrender.Group()
    this.zr.add(this.alone_group)

    this.create(tndir, this.alone_group)
    this.res?.root?.setPosition?.([0, 0])
    this.onResize()
  }

  onResize: any= throttle(function (this: BaseTray) {
    if (!this.zr || !this.res) return
    this.zr?.resize?.()
    setTimeout(() => {
      const width = this.zr?.getWidth?.() || 1
      const height = this.zr?.getHeight?.() || 1
      const scale_x = width / (this.res?.width || 1)
      const scale_y = height / (this.res?.height || 1)
      const scale = Math.min(scale_x, scale_y)
      this.alone_group?.setScale?.([scale, scale])
      this.res?.root?.dirty?.()
      this.zr?.flush?.()
    }, 10)
  }, 100)

  create (tndir: string, zr: Zrender.Group): void {
    try {
      this.trayDirection = tndir
      // 修正：始终用缓存的 DOM 重新 parseSVG，避免对象树复用导致渲染异常
      const cacheKey = `${this.model}_${this.children_count}_${tndir}`
      const dom = BaseTray.svgDomCache[cacheKey] ? BaseTray.svgDomCache[cacheKey].cloneNode(true) : this.cache_obj[`${tndir}_dom`]
      this.res = Zrender.parseSVG(dom, {})
      this.setupTrayElements(tndir)
      this.sync()
      zr.add(this.res!.root)
      insertProp(this.res?.root, '_layout_code', this.layout_code)
    } catch (error) {
      console.error(error)
    }
  }

  // 新增：设置托盘元素的辅助方法
  private setupTrayElements (tndir: string): void {
    // 修复：确保每个实例都有独立的 child_nodes 映射
    this.child_nodes = {}

    this.res?.named?.forEach?.((x: any) => {
      x.el && insertProp(x.el, 'originStyle', { ...x.el.style })
      if (x.namedFrom == null) {
        insertProp(x.el, 'name', x.name)
        if (x.name.startsWith('sign_')) {
          x.el.hide();
          ['tray_front', 'tray_right'].includes(tndir) && x.name === 'sign_1' && x.el.show();
          ['tray_back', 'tray_left'].includes(tndir) && x.name === 'sign_2' && x.el.show()
        } else if (x.name === 'used_cap_tray') {
          this.used_cap_tray = x
        } else if (x.name === 'tray_cover') {
          this.tray_cover = x
        } else if (x.name.startsWith('item_')) {
          this.child_nodes[x.name] = this.child_nodes[x.name] || []
          this.child_nodes[x.name].push(x.el as Zrender.Group)
        }
      }
    })
  }

  // 新增：对 used 项应用内阴影样式（黑色 60% 透明度，模糊 12）
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

  private getMagnetonNodeCenter (node: any): [number, number] | null {
    const shape = node?.shape
    if (typeof shape?.cx === 'number' && typeof shape?.cy === 'number') {
      return [shape.cx, shape.cy]
    }
    if (
      typeof shape?.x === 'number' &&
      typeof shape?.y === 'number' &&
      typeof shape?.width === 'number' &&
      typeof shape?.height === 'number'
    ) {
      return [shape.x + shape.width / 2, shape.y + shape.height / 2]
    }
    return null
  }

  private getMagnetonEllipseRotation (): number {
    if (this.trayDirection === 'tray_right') {
      return -Math.PI * 2 / 3
    }
    if (this.trayDirection === 'tray_left') {
      return Math.PI * 2 / 3
    }
    return 0
  }

  private applyMagnetonUsedHighlight (els: Zrender.Group[], used: boolean): void {
    if (this.config?.isMagnetonTray !== true) {
      return
    }
    try {
      els.forEach((el: any) => {
        if (!el) {
          return
        }
        const stack: any[] = [el]
        while (stack.length) {
          const node = stack.pop()
          if (node && typeof node.setStyle === 'function') {
            node.originStyle = node.originStyle || { ...node.style }
            node.magnetonOriginTransform = node.magnetonOriginTransform || {
              originX: typeof node.originX === 'number' ? node.originX : 0,
              originY: typeof node.originY === 'number' ? node.originY : 0,
              rotation: typeof node.rotation === 'number' ? node.rotation : 0,
              scaleX: typeof node.scaleX === 'number' ? node.scaleX : 1,
              scaleY: typeof node.scaleY === 'number' ? node.scaleY : 1
            }
            if (used) {
              const center = this.getMagnetonNodeCenter(node)
              const baseScaleX = node.magnetonOriginTransform.scaleX || 1
              const baseScaleY = node.magnetonOriginTransform.scaleY || 1
              if (center !== null) {
                node.setOrigin?.(center)
                node.setScale?.([baseScaleX * 0.95, baseScaleY * 0.42])
                node.rotation = this.getMagnetonEllipseRotation()
              }
              node.setStyle({
                fill: '#ffffff',
                stroke: '#d9dee8',
                lineWidth: 0.6,
                shadowColor: 'rgba(38,43,62,0.28)',
                shadowBlur: 2,
                shadowOffsetX: 0,
                shadowOffsetY: 1
              })
            } else {
              node.setOrigin?.([
                node.magnetonOriginTransform.originX,
                node.magnetonOriginTransform.originY
              ])
              node.rotation = node.magnetonOriginTransform.rotation
              node.setScale?.([
                node.magnetonOriginTransform.scaleX,
                node.magnetonOriginTransform.scaleY
              ])
              node.style = { ...node.originStyle }
              node.setStyle({ shadowBlur: 0 })
            }
            node.dirty?.()
          }
          const children = node?.children?.()
          if (children && children.length) {
            for (let i = 0; i < children.length; i++) {
              stack.push(children[i])
            }
          }
        }
      })
    } catch (e) {
      console.warn('磁子托盘高光渲染失败', e)
    }
  }

  remove (zr: Zrender.Group): void {
    if (!zr) return
    zr.remove(this.res?.root as any)
    zr.dirty()
  }

  setPoseScale (tndir: string, station_recorder: Recorder, layout_code: string, start_z: number): void {
    const recorder = this.cache_obj[`${tndir}_recorder`] as Recorder
    const self_anchor = getTrayRulerAnchor(recorder) || {} as RecordItem
    const ruler_0_anchor = recorder.rulers.ruler_0

    const ruler_tray_front_key = self_anchor.type ? `ruler_tray_front_${self_anchor.type}` : 'ruler_tray_front'
    const ruler_tray_right_key = self_anchor.type ? `ruler_tray_right_${self_anchor.type}` : 'ruler_tray_right'
    if (!station_recorder.rulers[ruler_tray_front_key] && !station_recorder.rulers[ruler_tray_right_key]) {
      console.warn(`No ${ruler_tray_front_key} or ${ruler_tray_right_key} in station`)
    }

    const station_ruler_width = [ 'tray_front', 'tray_back' ].includes(tndir)
      ? station_recorder.rulers[ruler_tray_front_key]?.width
      : station_recorder.rulers[ruler_tray_right_key]?.width
    if (!station_ruler_width) { throw new Error('看看是不是方向没有配置') }

    const scale = station_ruler_width / self_anchor.width
    this.res!.root.setScale([scale, scale])

    const station_anchor = station_recorder.anchors[`anchor_${layout_code}`]

    if (BaseTray.isHideTray(layout_code)) {
      this.res?.root?.setPosition?.([
        station_anchor.x - ruler_0_anchor.x,
        station_anchor.y - ruler_0_anchor.y
      ])
      this.res?.named?.find?.((item: any) => item.name === 'tray')?.el?.hide?.()
      this.res?.named?.find?.((item: any) => item.name === 'tray_cover')?.el?.hide?.()
    } else {
      if (BaseTray.isHideTrayV2(layout_code)) {
        this.res?.named?.find?.((item: any) => item.name === 'tray')?.el?.hide?.()
        this.res?.named?.find?.((item: any) => item.name === 'tray_cover')?.el?.hide?.()
      }
      this.res?.root?.setPosition?.([
        station_anchor.x - self_anchor.x,
        station_anchor.y + station_anchor.height - self_anchor.y - self_anchor.height
      ])
    }

    travelZ(this.res!.root, start_z + 100000, 1)

    // 调试：记录位置设置信息
  }

  // 新增：设置可见范围
  static setVisibleRange (start: number, end: number): void {
    BaseTray.visibleRange = { start, end }
  }

  // 新增：检查元素是否在可见范围内
  private isElementVisible (index: number): boolean {
    if (!BaseTray.enableVirtualization) return true
    return index >= BaseTray.visibleRange.start && index <= BaseTray.visibleRange.end
  }

  // 全局调度：sync 只注册任务
  sync (): void {
    SyncManager.addTrayTask(this, 0)
  }

  // 优化：syncItem 方法
  syncItem (n: number): void {
    const attr = this.children[n]
    const els = this.child_nodes[`item_${n + 1}`]

    if (!els || els.length === 0) {
      console.warn(`No elements found for item_${n + 1} in tray ${this.model}, layout_code: ${this.layout_code}`)
      return
    }

    const method = attr.display ? 'show' : 'hide'

    // 优化：批量操作，减少 DOM 访问
    els.forEach((el: Zrender.Group) => {
      if (el && typeof el[method] === 'function') {
        el[method]()
      }
    })

    if (attr.display) {
      // 不再对子元素进行 used 颜色处理，仅保留结构显隐等逻辑
      const attrWithoutUsed = { ...attr, used: false } as any
      syncPart(els, attrWithoutUsed, this.children[n]?.cap_type || this.capType)
      // 直接给元素应用内阴影样式
      this.applyUsedInnerShadow(els, !!attr.used)
      this.applyMagnetonUsedHighlight(els, !!attr.used)
    }
  }

  setLaycode (layout_code: string): void {
    this.layout_code = layout_code
  }

  updateDecorate (capType: number, params: { with_cap?: boolean, with_magneton?: boolean }): void {
    this.capType = capType
    this.children.map((item: ChildAttr) => Object.assign(item, params))
    this.sync()
  }

  alignToBottom: any = throttle(function (this: BaseTray) {
    const canvasHeight = this.zr?.getHeight()
    const canvasWidth = this.zr?.getWidth()
    if (canvasHeight && canvasWidth) {
      const { height = 0, width = 0 } = this.res || {}
      const scaleX = width / canvasWidth
      const scaleY = height / canvasHeight
      const scale = Math.max(scaleX, scaleY)
      this.res?.root?.setPosition?.([(canvasWidth * scale - width) / 2, canvasHeight * scale - height])
    }
  }, 100)

  getSlotLabel (slotIndex: number | string): string {
    if (!slotIndex && slotIndex !== 0) { return '' }
    const index = Number(slotIndex)
    if (isNaN(index)) { return '' }
    return this.slotLabels[index]
  }

  getSlotsMatrix (): SlotLabelInfo[][] {
    return calcSlotsMatrix(this.config)
  }

  static getTrayModel (resource_type: string): string {
    const { $view, model } = window.webb.store?.get?.('params')
    if (model?.tray?.[resource_type]?.model === resource_type) return resource_type
    const viewModels = Object.values(model?.tray || {}).filter((item: any) => item.range.includes($view))
    const other: any = viewModels.find((v: any) => v.vessel_models?.includes(resource_type))
    return other?.model || resource_type
  }

  // 新增：清理缓存方法
  static clearCache (): void {
    BaseTray.modelConfigCache = {}
    BaseTray.svgTemplateCache = {}
    BaseTray.slotLabelsCache = {}
  }

  // 新增：清理特定型号的缓存
  static clearModelCache (model: string): void {
    delete BaseTray.modelConfigCache[model]
    // 清理相关的 SVG 模板缓存
    Object.keys(BaseTray.svgTemplateCache).forEach((key: string) => {
      if (key.startsWith(model)) {
        delete BaseTray.svgTemplateCache[key]
      }
    })
    // 清理相关的 slotLabels 缓存
    Object.keys(BaseTray.slotLabelsCache).forEach((key: string) => {
      if (key.startsWith(model)) {
        delete BaseTray.slotLabelsCache[key]
      }
    })
  }

  // 新增：获取缓存统计信息
  static getCacheStats (): {
    modelConfigCount: number;
    svgTemplateCount: number;
    slotLabelsCount: number;
    memoryUsage?: number;
    } {
    const stats: {
      modelConfigCount: number;
      svgTemplateCount: number;
      slotLabelsCount: number;
      memoryUsage?: number;
    } = {
      modelConfigCount: Object.keys(BaseTray.modelConfigCache).length,
      svgTemplateCount: Object.keys(BaseTray.svgTemplateCache).length,
      slotLabelsCount: Object.keys(BaseTray.slotLabelsCache).length
    }

    // 尝试获取内存使用情况（如果浏览器支持）
    if ((performance as any).memory) {
      stats.memoryUsage = (performance as any).memory.usedJSHeapSize
    }

    return stats
  }

  // 新增：智能缓存清理
  static smartClearCache (maxMemoryMB: number = 100): void {
    // 如果内存使用超过阈值，清理最旧的缓存
    if ((performance as any).memory && (performance as any).memory.usedJSHeapSize > maxMemoryMB * 1024 * 1024) {
      console.warn('Memory usage high, clearing old cache entries')

      // 清理一半的缓存
      const modelKeys = Object.keys(BaseTray.modelConfigCache)
      const svgKeys = Object.keys(BaseTray.svgTemplateCache)
      const slotKeys = Object.keys(BaseTray.slotLabelsCache)

      // 清理最旧的 50% 缓存
      const clearCount = Math.floor(modelKeys.length / 2)
      for (let i = 0; i < clearCount; i++) {
        delete BaseTray.modelConfigCache[modelKeys[i]]
      }

      for (let i = 0; i < Math.floor(svgKeys.length / 2); i++) {
        delete BaseTray.svgTemplateCache[svgKeys[i]]
      }

      for (let i = 0; i < Math.floor(slotKeys.length / 2); i++) {
        delete BaseTray.slotLabelsCache[slotKeys[i]]
      }
    }
  }

  // 新增：预加载常用型号
  static preloadModels (models: string[]): void {
    models.forEach((model: string) => {
      if (!BaseTray.modelConfigCache[model]) {
        try {
          BaseTray.fromModel(model, false)
        } catch (error) {
          console.warn(`Failed to preload model: ${model}`, error)
        }
      }
    })
  }
}

export {
  BaseTray
}
