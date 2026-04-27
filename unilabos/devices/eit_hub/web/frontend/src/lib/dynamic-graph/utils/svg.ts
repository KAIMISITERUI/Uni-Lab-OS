import { XMLParser, XMLBuilder } from 'fast-xml-parser'
import * as Zrender from 'zrender'
import type { MatrixArray } from 'zrender/lib/core/matrix'
import type { Recorder } from 'Types/graph/graph'
import { parseTransformAttribute } from './transform'

function procElement (element: any, renum: number, recoreder: Recorder, transfrom: MatrixArray, _label?: string): string {
  if (!element) return ''

  let label = element['@_inkscape:label']
  if (_label && ['label', 'part', 'floor', 'text', 'large_floor', 'medium_floor', 'small_floor'].includes(label)) {
    label = `${_label}_${label}`
  }
  if (label) {
    if (label.startsWith('item_') && renum > 0) {
      const n = parseInt(label.slice(5), 10)
      if (renum > n) {
        element['@_name'] = `item_${renum - n}`
      } else {
        element['@_name'] = `item_${n}`
      }
    } else {
      element['@_name'] = label
      if (label.startsWith('anchor_') || label.startsWith('ruler_')) {
        const x = parseFloat(element['@_x'])
        const y = parseFloat(element['@_y'])
        const width = parseFloat(element['@_width'])
        const height = parseFloat(element['@_height'])

        const xy1 = Zrender.vector.create(x, y)
        const xy2 = Zrender.vector.create(x + width, y + height)

        Zrender.vector.applyTransform(xy1, xy1, transfrom)
        Zrender.vector.applyTransform(xy2, xy2, transfrom)

        const tar = label.startsWith('anchor_')
          ? recoreder.anchors
          : recoreder.rulers

        tar[label] = {
          x: Math.min(xy1[0], xy2[0]),
          y: Math.min(xy1[1], xy2[1]),
          width: Math.abs(xy1[0] - xy2[0]),
          height: Math.abs(xy1[1] - xy2[1])
        }
      }
    }
  }

  if (_label) {
    const anchor_label = _label.replace('item_', 'anchor_')
    if (!recoreder.anchors[anchor_label] && label?.includes('label')) {
      const x = parseFloat(element['@_x'])
      const y = parseFloat(element['@_y'])
      const width = parseFloat(element['@_width'])
      const height = parseFloat(element['@_height'])

      const xy1 = Zrender.vector.create(x, y)
      const xy2 = Zrender.vector.create(x + width, y + height)

      Zrender.vector.applyTransform(xy1, xy1, transfrom)
      Zrender.vector.applyTransform(xy2, xy2, transfrom)

      const tar = recoreder.anchors
      // const _width = Math.abs(xy1[0] - xy2[0]),
      const _height = Math.abs(xy1[1] - xy2[1])

      tar[anchor_label] = {
        x: Math.min(xy1[0], xy2[0]),
        y: Math.min(xy1[1] - _height, xy2[1]),
        width: Math.abs(xy1[0] - xy2[0]),
        height: Math.abs(xy1[1] - xy2[1])
      }
    }
  }

  if (label && /^item_[A-Za-z\d]+(-|\s)[A-Za-z\d]+$/.test(label)) {
    return label
  }
  return ''
}

function removeSVGComments (svg: string): string {
  return svg.replace(/<!--([\s\S]*?)-->/g, '')
}

function travelNodeIterative (nodes: any[], renum: number, recoreder: Recorder, transfrom: MatrixArray, label?: string): void {
  const stack: Array<{ node: any, trans: MatrixArray, label?: string }> = []
  for (const node of nodes) {
    stack.push({ node, trans: transfrom, label })
  }
  while (stack.length) {
    const { node, trans, label: parentLabel } = stack.pop()!
    const attr: any = node[':@']
    let onceFlag = false
    for (let key in node) {
      // eslint-disable-next-line
      if (key === ':@') continue
      if (key === '#text') break
      if (onceFlag) throw new Error(`travelNode error ${key} in ${node}`)
      onceFlag = true
      if (key === 'a') {
        node.g = node.a
        delete node.a
        key = 'g'
      }
      let nextChain = trans
      if (attr?.['@_transform']) {
        const mt = parseTransformAttribute(attr['@_transform'])
        nextChain = Zrender.matrix.create()
        Zrender.matrix.mul(nextChain, trans, mt!)
      }
      const _label = procElement(attr, renum, recoreder, nextChain, parentLabel)
      if (Array.isArray(node[key])) {
        for (const child of node[key]) {
          stack.push({ node: child, trans: nextChain, label: _label })
        }
      }
    }
  }
}

function fixedSVG (svg_raw: string, recoreder: Recorder, renum: number = 0): string {
  const cleanSvg = removeSVGComments(svg_raw)
  const parser = new XMLParser({ ignoreAttributes: false, allowBooleanAttributes: true, preserveOrder: true })
  const svgObj = parser.parse(cleanSvg)
  travelNodeIterative(svgObj, renum, recoreder, Zrender.matrix.create())
  const builder = new XMLBuilder({ ignoreAttributes: false, suppressBooleanAttributes: false, preserveOrder: true })
  const newSvg = builder.build(svgObj)
  return newSvg
}

export {
  procElement,
  travelNodeIterative,
  fixedSVG
}
