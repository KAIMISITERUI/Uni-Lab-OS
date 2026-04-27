import * as Zrender from 'zrender'

export enum CAP_TYPES {
  NONE = 0,
  NORMAL = 1,
  PUNCTURE = 2,
}
export interface ChildAttr {
  display: boolean
  highlight: boolean
  selected: boolean
  with_cap: boolean
  with_magneton: boolean
  used: boolean
  resource_type: string
  cap_type?: number
}

export interface ChildElements {
  fill: Zrender.Displayable[]
  stroke: Zrender.Displayable[]
}
