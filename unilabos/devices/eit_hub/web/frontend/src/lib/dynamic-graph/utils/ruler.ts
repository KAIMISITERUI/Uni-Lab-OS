import type { Recorder, RecordItem } from 'Types/graph/graph'
import { RulerType } from 'Types/graph/graph'

export const getTrayRulerAnchor = (recorder?: Recorder): RecordItem | null => {
  const rulers = recorder?.rulers || {}
  const regx = /ruler_anchor([_A-Za-z\d]*)/
  const typeList = [RulerType.small, RulerType.medium, RulerType.large].map((t: string) => `_${t}`)
  let result = null

  const keys = Object.keys(rulers)
  for (let i = 0; i < keys.length; i++) {
    const matched = keys[i].match(regx)
    if (matched && typeof matched?.[1] === 'string') {
      if (matched[1] === '') {
        result = { ...rulers[keys[i]], type: RulerType.normal }
        break
      } else if (typeList.includes(matched[1])) {
        result = { ...rulers[keys[i]], type: matched[1].slice(1) }
        break
      }
    }
  }

  return result
}
