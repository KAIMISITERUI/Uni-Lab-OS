/**
 * 功能:
 *   dynamic-graph 模块的入口, 暴露 getModule 给业务层. 业务层通过 getModule 拿到 Station/BaseTray/TraySlot 三个核心类.
 *   裁剪自原 dynamic-graph/src/index.ts, 移除 M01TC 专用 helper 与 packageData 暴露.
 */
import { Station, StationMap, Zrender } from './station/station'
import { TraySlot } from './station/slot'
import { BaseTray, TrayMap, extendModel } from './tray'
import { patchConfig } from './utils/patch'
import type { StationData } from './types/graph/station'
import type { ModelConfigDef } from './types/config/model'
import { HIGHT_COLOR, HIGHT_COLOR_SELECTED } from './utils/consts'

export interface Module {
  Station: typeof Station;
  BaseTray: typeof BaseTray;
  TraySlot: typeof TraySlot;
  TrayMap: Record<string, any>;
  StationMap: Record<string, StationData>;
  ModelConfig: ModelConfigDef;
  container: string;
  Zrender: typeof Zrender;
  [propName: string]: any;
}

let _module: Module | null = null

export const getModule = (): Module => {
  if (_module) return _module

  const _params = window?.webb?.store?.get?.('params') || {}
  const _container = _params.$view || ''
  const _ModelConfig = _params.model as ModelConfigDef
  if (!_container) throw new Error('Not found webb container')

  patchConfig(_ModelConfig, _params.patch, _container)
  extendModel(_ModelConfig, _ModelConfig?.station?.[_container]?.is2D)

  // 仅保留当前站点 (NTU) 启用的托盘型号
  const _disabledTrays = Object.keys(TrayMap).filter((_model: string) => {
    if (!_ModelConfig?.tray?.[_model]) return true
    return !_ModelConfig?.tray?.[_model]?.range?.includes?.(_container)
  })
  _disabledTrays.forEach((_model: string) => {
    if (TrayMap[_model]) delete TrayMap[_model]
  })

  _module = {
    Station,
    BaseTray,
    TraySlot,
    TrayMap,
    StationMap,
    ModelConfig: _ModelConfig,
    container: _container,
    Zrender
  }
  return _module
}

export const getHightColor = (isSelect: boolean = false): any => (isSelect ? HIGHT_COLOR_SELECTED : HIGHT_COLOR)

export { Station, BaseTray, TraySlot, Zrender }
