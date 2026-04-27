// Copy from Zrender/parseSVG

import { matrix } from 'zrender'
import { MatrixArray } from 'zrender/lib/core/matrix'

// value can be like:
// '2e-4', 'l.5.9' (ignore 0), 'M-10-10', 'l-2.43e-1,34.9983',
// 'l-.5E1,54', '121-23-44-11' (no delimiter)
// PENDING: here continuous commas are treat as one comma, but the
// browser SVG parser treats this by printing error.
const numberReg = /-?([0-9]*\.)?[0-9]+([eE]-?[0-9]+)?/g
function splitNumberSequence (rawStr: string): string[] {
  return rawStr.match(numberReg) || []
}
// Most of the values can be separated by comma and/or white space.
// const DILIMITER_REG = /[\s,]+/;

// eslint-disable-next-line
const transformRegex = /(translate|scale|rotate|skewX|skewY|matrix)\(([\-\s0-9\.eE,]*)\)/g
const DEGREE_TO_ANGLE = Math.PI / 180

export function parseTransformAttribute (transform: string): MatrixArray | null {
  transform = transform.replace(/,/g, ' ')
  const transformOps: string[] = []
  let mt = null
  transform.replace(transformRegex, (str: string, type: string, value: string) => {
    transformOps.push(type, value)
    return ''
  })

  for (let i = transformOps.length - 1; i > 0; i -= 2) {
    const value = transformOps[i]
    const type = transformOps[i - 1]
    const valueArr: string[] = splitNumberSequence(value)
    mt = mt || matrix.create()

    const sx = Math.tan(parseFloat(valueArr[0]) * DEGREE_TO_ANGLE)
    const sy = Math.tan(parseFloat(valueArr[0]) * DEGREE_TO_ANGLE)

    switch (type) {
      case 'translate':
        matrix.translate(mt, mt, [parseFloat(valueArr[0]), parseFloat(valueArr[1] || '0')])
        break
      case 'scale':
        matrix.scale(mt, mt, [parseFloat(valueArr[0]), parseFloat(valueArr[1] || valueArr[0])])
        break
      case 'rotate':
        // TODO: zrender use different hand in coordinate system.
        matrix.rotate(mt, mt, -parseFloat(valueArr[0]) * DEGREE_TO_ANGLE)
        break
      case 'skewX':
        matrix.mul(mt, [1, 0, sx, 1, 0, 0], mt)
        break
      case 'skewY':
        matrix.mul(mt, [1, sy, 0, 1, 0, 0], mt)
        break
      case 'matrix':
        mt[0] = parseFloat(valueArr[0])
        mt[1] = parseFloat(valueArr[1])
        mt[2] = parseFloat(valueArr[2])
        mt[3] = parseFloat(valueArr[3])
        mt[4] = parseFloat(valueArr[4])
        mt[5] = parseFloat(valueArr[5])
        break
      default:
        break
    }
  }

  return mt
}
