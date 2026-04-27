import * as Zrender from 'zrender'
import type { SVGParserResult } from 'zrender/lib/tool/parseSVG'
import { RecordItem, RulerType } from 'Types/graph/graph'

import tray_selected_front_z0 from 'Models/common/tray_selected_front_z0.svg'
import tray_selected_front_z1 from 'Models/common/tray_selected_front_z1.svg'
import tray_selected_right_z0 from 'Models/common/tray_selected_right_z0.svg'
import tray_selected_right_z1 from 'Models/common/tray_selected_right_z1.svg'

import { fixedSVG } from 'Utils/svg'
import { travelZ } from 'Utils/zr'
import { insertProp } from 'Utils/utils'
import { BaseTray } from 'Tray/tray'
import { HIGHT_COLOR } from 'Utils/consts'
import type { Station } from './station'

/**
 * Slot 托盘位对象
 *  - tray              托盘位放的托盘
 *  - setTray           增加托盘
 *  - removeTray        删除托盘
 *  - hasTray           是否有托盘
 *  - setSelected       托盘位选中状态，可设置颜色
 */

class TraySlot {
  layout_code: string;
  tndir: string;
  zr_floor: Zrender.Displayable;
  zr_label: Zrender.Displayable;
  zr_text: Zrender.Displayable;
  zr_part: Zrender.Displayable | undefined;
  tray: BaseTray | undefined;
  station: Station;
  selected: boolean;
  highlight: boolean;
  tray_select_z0_res: SVGParserResult | undefined;
  tray_select_z1_res: SVGParserResult | undefined;
  tray_select_anchor: RecordItem;
  tray_select_stroke: Zrender.Displayable[];
  tray_select_fill: Zrender.Displayable[];
  size: string

  // 新增：静态缓存，避免重复解析相同的选择框 SVG
  static selectCache: Record<string, {
    z0_dom: any;
    z1_dom: any;
    anchor: RecordItem;
  }> = {}

  constructor (
    station: Station,
    layout_code: string,
    tndir: string,
    floor: Zrender.Displayable,
    label: Zrender.Displayable,
    text: Zrender.Displayable,
    part: Zrender.Displayable | undefined,
    station_cache: Record<string, any>,
    size: string
  ) {
    floor?.style?.fill && insertProp(floor, 'originFill', (floor as any).style.fill)
    label?.style?.fill && insertProp(label, 'originFill', (label as any).style.fill)
    part?.style?.fill && insertProp(part, 'originFill', (part as any).style.fill)

    this.station = station
    this.tndir = tndir
    this.layout_code = layout_code
    this.zr_floor = floor
    this.zr_label = label
    this.zr_text = text
    this.zr_part = part
    this.zr_floor ? (this.zr_floor as any)._layout_code = this.layout_code : ''
    this.zr_label ? (this.zr_label as any)._layout_code = this.layout_code : ''
    this.zr_text ? (this.zr_text as any)._layout_code = this.layout_code : ''
    this.zr_part ? (this.zr_part as any)._layout_code = this.layout_code : ''
    this.selected = false
    this.highlight = false
    this.tray_select_stroke = []
    this.tray_select_fill = []
    this.size = size || RulerType.normal

    // 修复：检查选择框缓存，只缓存 DOM 和 anchor，不缓存 ZRender 结果
    const cacheKey = `${tndir}_${size}`
    if (TraySlot.selectCache[cacheKey]) {
      const cached = TraySlot.selectCache[cacheKey]
      // 每次都重新解析 ZRender，确保每个实例独立
      this.tray_select_z0_res = Zrender.parseSVG(cached.z0_dom, {})
      this.tray_select_z1_res = Zrender.parseSVG(cached.z1_dom, {})
      this.tray_select_anchor = cached.anchor
      // 处理选择框元素
      this.processSelectElements()
    } else {
      // 首次构建，缓存选择框
      if (typeof station_cache.tray_select_cached === 'undefined') {
        station_cache.tray_select_front_z0_recorder = { anchors: {}, rulers: {} }
        station_cache.tray_select_front_z1_recorder = { anchors: {}, rulers: {} }
        station_cache.tray_select_right_z0_recorder = { anchors: {}, rulers: {} }
        station_cache.tray_select_right_z1_recorder = { anchors: {}, rulers: {} }

        station_cache.tray_select_front_z0_dom = this.svgDOM(
          fixedSVG(tray_selected_front_z0 as string, station_cache.tray_select_front_z0_recorder)
        )
        station_cache.tray_select_front_z1_dom = this.svgDOM(
          fixedSVG(tray_selected_front_z1 as string, station_cache.tray_select_front_z1_recorder)
        )
        station_cache.tray_select_right_z0_dom = this.svgDOM(
          fixedSVG(tray_selected_right_z0 as string, station_cache.tray_select_right_z0_recorder)
        )
        station_cache.tray_select_right_z1_dom = this.svgDOM(
          fixedSVG(tray_selected_right_z1 as string, station_cache.tray_select_right_z1_recorder)
        )

        station_cache.tray_select_cached = true
      }

      if (this.tndir === 'tray_front' || this.tndir === 'tray_back') {
        this.tray_select_z0_res = Zrender.parseSVG(<any>station_cache.tray_select_front_z0_dom, {})
        this.tray_select_z1_res = Zrender.parseSVG(<any>station_cache.tray_select_front_z1_dom, {})
        this.tray_select_anchor = station_cache.tray_select_front_z0_recorder.rulers.ruler_anchor
      } else {
        this.tray_select_z0_res = Zrender.parseSVG(<any>station_cache.tray_select_right_z0_dom, {})
        this.tray_select_z1_res = Zrender.parseSVG(<any>station_cache.tray_select_right_z1_dom, {})
        this.tray_select_anchor = station_cache.tray_select_right_z0_recorder.rulers.ruler_anchor
      }

      // 缓存 DOM 和 anchor，不缓存 ZRender 结果
      TraySlot.selectCache[cacheKey] = {
        z0_dom: this.tndir === 'tray_front' || this.tndir === 'tray_back'
          ? station_cache.tray_select_front_z0_dom
          : station_cache.tray_select_right_z0_dom,
        z1_dom: this.tndir === 'tray_front' || this.tndir === 'tray_back'
          ? station_cache.tray_select_front_z1_dom
          : station_cache.tray_select_right_z1_dom,
        anchor: this.tray_select_anchor
      }

      // 处理选择框元素
      this.processSelectElements()
    }

    insertProp(this.tray_select_z0_res.root, '_layout_code', this.layout_code)
    insertProp(this.tray_select_z1_res.root, '_layout_code', this.layout_code)
  }

  // 新增：处理选择框元素的辅助方法
  private processSelectElements (): void {
    for (const res of [this.tray_select_z0_res, this.tray_select_z1_res]) {
      for (const x of res!.named) {
        if (x.svgNodeTagLower === 'path' || x.svgNodeTagLower === 'rect') {
          const _el = x.el as any
          const { style } = _el

          if (typeof style !== 'undefined' && !x.el.isGroup) {
            const fill = !!(style.fill && style.fill !== '#ffffff')
            const stroke = !!(style.stroke && style.lineWidth > 0.001)

            fill ? this.tray_select_fill.push(<Zrender.Displayable>x.el) : ''
            stroke ? this.tray_select_stroke.push(<Zrender.Displayable>x.el) : ''
          }
        }
      }
    }
  }

  svgDOM (svg_xml: string): ChildNode {
    const parser = new DOMParser()
    const svg_dom = parser.parseFromString(svg_xml, 'text/xml')
    return svg_dom.childNodes[0]
  }

  setTray (tray: BaseTray): void {
    this.tray = tray
    this.tray.setLaycode(this.layout_code)
    this.tray.create(this.tndir, this.station.trays_group!)
    this.tray.setPoseScale(
      this.tndir,
      this.station.recorder,
      this.layout_code, this.zr_floor.z
    )

    console.log(`Tray set successfully for slot ${this.layout_code}`)
  }

  removeTray (): void {
    this.tray?.remove?.(this.station.trays_group!)
    this.tray = undefined
  }

  hasTray (): boolean {
    return !!this.tray
  }

  setSelected (is_selected: boolean, color: string = '#0dbf75'): void {
    const { $view, model } = window.webb.store.get('params')
    const { focusSlotStyle, disSelectSlotOnPick } = model.station?.[$view]
    if (this.station.disSelectSlot || disSelectSlotOnPick) { return }
    this.selected = is_selected
    if (focusSlotStyle === 'highlight') {
      this.setHighlight(this.selected, HIGHT_COLOR)
      return
    }

    if (typeof this.tray_select_z1_res!.root.parent === 'undefined') {
      const station_ruler_width = [ 'tray_front', 'tray_back' ].includes(this.tndir)
        ? this.station.recorder.rulers[`ruler_tray_front${this.size}`].width
        : this.station.recorder.rulers[`ruler_tray_right${this.size}`].width
      if (!station_ruler_width) { throw new Error('看看是不是方向没有配置') }

      const scale = station_ruler_width / this.tray_select_anchor.width
      this.tray_select_z0_res?.root?.setScale?.([scale, scale])
      this.tray_select_z1_res?.root?.setScale?.([scale, scale])

      const station_anchor = this.station.recorder.anchors[`anchor_${this.layout_code}`]

      if (BaseTray.isHideTray(this.layout_code)) {
        this.tray_select_z0_res?.root?.setPosition?.([
          station_anchor.x - this.tray_select_anchor.x - this.tray_select_anchor.width / 2,
          station_anchor.y + station_anchor.height - this.tray_select_anchor.y + this.tray_select_anchor.height
        ])
        this.tray_select_z1_res?.root?.setPosition?.([
          station_anchor.x - this.tray_select_anchor.x - this.tray_select_anchor.width / 2,
          station_anchor.y + station_anchor.height - this.tray_select_anchor.y + this.tray_select_anchor.height
        ])
      } else {
        this.tray_select_z0_res?.root?.setPosition?.([
          station_anchor.x - this.tray_select_anchor.x,
          station_anchor.y + station_anchor.height - (this.tray_select_anchor.y + this.tray_select_anchor.height) * scale
        ])
        this.tray_select_z1_res?.root?.setPosition?.([
          station_anchor.x - this.tray_select_anchor.x,
          station_anchor.y + station_anchor.height - (this.tray_select_anchor.y + this.tray_select_anchor.height) * scale
        ])
      }
      travelZ(this.tray_select_z0_res!.root, this.zr_floor.z + 1 + 100000, 1)
      travelZ(this.tray_select_z1_res!.root, this.zr_floor.z + 1000 + 100000, 1)
      // zr.add(this.res!.root)

      this.station.trays_group!.add(this.tray_select_z0_res!.root)
      this.station.trays_group!.add(this.tray_select_z1_res!.root)
    }

    if (this.selected) {
      for (const displayable of this.tray_select_stroke) {
        displayable.setStyle('stroke' as never, color as never)
      }
      for (const displayable of this.tray_select_fill) {
        displayable.setStyle('fill' as never, color as never)
      }

      this.tray_select_z0_res?.root?.show?.()
      this.tray_select_z1_res?.root?.show?.()
    } else {
      this.tray_select_z0_res?.root?.hide?.()
      this.tray_select_z1_res?.root?.hide?.()
    }
  }

  setHighlight (isHighlight: boolean, color: string | Zrender.LinearGradient | undefined = undefined): void {
    this.highlight = isHighlight
    const _zr_floor = this.zr_floor as any
    const _zr_label = this.zr_label as any
    const _zr_part = this.zr_part as any
    const _zr_text = this.zr_text as any

    [
      _zr_floor,
      _zr_part,
      _zr_label
    ].forEach((item: any) => {
      if (item?.style?.fill) {
        item.style.fill = isHighlight ? color || item.originFill : item.originFill
      }
    })

    const zr_text_Tspan = _zr_text?.children?.()?.[0].children?.()?.[0] as Zrender.TSpan
    if (zr_text_Tspan instanceof Zrender.TSpan) {
      zr_text_Tspan.setStyle({ fill: isHighlight ? '#fff' : _zr_text?.style?.fill })
    }

    this.zr_floor?.parent?.dirty?.()
    this.zr_label?.parent?.dirty?.()
    this.zr_part?.parent.dirty?.()
    this.zr_text?.parent.dirty?.()
  }

  // 新增：供全局 SyncManager 调用的批量渲染方法
  updateView (): void {
    // 这里可以根据实际需求刷新 slot 的显示状态
    // 例如刷新 highlight、selected、tray 的显示等
    if (this.tray) {
      this.tray.sync()
    }
  }
}

export {
  TraySlot
}
