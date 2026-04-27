import * as Zrender from 'zrender'
import { ChildAttr } from 'Types/graph/tray'
import { cloneDeep } from 'lodash'
import { getView } from './utils'

export function syncPart (els: Zrender.Group[], attr: ChildAttr, capType?: number): void {
  const disableMagneton = window.webb.store.get('params').model.station?.[getView()].disableMagneton
  const isShowCap = (c: number): boolean => attr.with_cap && capType === c
    els?.forEach?.((el: Zrender.Group) => {
      el.children?.()?.forEach?.((child: any): void => {
        child.show()
        if (child.name.startsWith('vessel_')) {
          if (child.name === `vessel_${attr.resource_type}`) {
            syncPart([child], attr, capType)
          } else {
            child.hide()
          }
        } else {
          switch (child.name) {
            case 'magneton':
              (disableMagneton || !attr.with_magneton) && child.hide()
              break
            case 'cap':
              !attr.with_cap && child.hide()
              break
            case 'cap_normal':
              !isShowCap(1) && child.hide()
              updateUsedCap(child, attr.used)
              break
            case 'cap_puncture':
              !isShowCap(2) && child.hide()
              updateUsedCap(child, attr.used)
              break
            case 'bottle':
              updateUsedBottle(child, attr.used)
              break
            default:
              break
          }
        }
      })
    })
}

function updateUsedCap (el: any, used: boolean): void {
  if (!el?.children?.()?.length) return
  el.children()?.forEach((child: any) => {
    switch (child.name) {
      case 'part_1':
        if (child.originStyle?.fill instanceof Zrender.LinearGradient) {
          const fill = cloneDeep(child.originStyle.fill)
          fill.colorStops[0] && (fill.colorStops[0].color = '#828ab0')
          fill.colorStops[1] && (fill.colorStops[1].color = '#a1a7c4')
          setStyle(child, used, fill)
        }
        break
      case 'part_2':
        setStyle(child, used, '#828ab0')
        break
      case 'part_3':
        setStyle(child, used, '#4f577d')
        break
      default:
        break
    }
  })
}

function updateUsedBottle (el: any, used: boolean): void {
  if (!el?.children?.()?.length) return
  el.children()?.forEach((child: any) => {
    switch (child.name) {
      case 'part_1':
        setStyle(child, used, child.originStyle.fill, '#a1a7c4')
        break
      case 'part_2':
        setStyle(child, used, undefined, '#a1a7c4')
        if (child.originStyle?.fill instanceof Zrender.LinearGradient) {
          const fill = cloneDeep(child.originStyle.fill)
          fill.colorStops[0] && (fill.colorStops[0].color = 'rgba(193, 196, 215, 0.898)')
          fill.colorStops[1] && (fill.colorStops[1].color = 'rgba(252, 254, 255, 0.8)')
          fill.colorStops[2] && (fill.colorStops[2].color = 'rgba(193, 196, 215, 0.8)')
          setStyle(child, used, fill, '#a1a7c4')
        }
        break
      case 'part_3':
        setStyle(child, used, '#a1a7c4')
        break
      default:
        break
    }
  })
}

function setStyle (el: any, used: boolean, fill?: string | Zrender.LinearGradient, stroke?: string | Zrender.LinearGradient) :void {
  el.style = { ...el.originStyle }
  if (used) {
    fill !== undefined && el.setStyle?.('fill', fill)
    stroke !== undefined && el.setStyle?.('stroke', stroke)
  }
}
