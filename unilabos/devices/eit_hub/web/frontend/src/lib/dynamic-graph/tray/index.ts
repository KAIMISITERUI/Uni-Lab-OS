import type { TrayConfig } from 'Types/model/tray'
import type { ModelConfigDef } from 'Types/config/model'
import { TraySvgMap } from 'Models/tray_svg_map'

import { TrayMap } from './cache'
import { BaseTray } from './tray'

/**
 * 基于托盘型号配置，扩展托盘型号
 * @param modelConfig:ModelConfigDef
 */
const extendModel = (modelConfig: ModelConfigDef, is2D?: boolean): void => {
  const suffix = is2D ? '_2d' : ''

  Object.keys(modelConfig?.tray || {}).forEach((trayModel: string) => {
    let config = modelConfig?.tray?.[trayModel] as TrayConfig
    if (TraySvgMap[trayModel]) {
      config = {
        ...config,
        tray_front: TraySvgMap[trayModel][`tray_front${suffix}`] || '',
        tray_right: TraySvgMap[trayModel][`tray_right${suffix}`] || '',
        tray_back: TraySvgMap[trayModel][`tray_back${suffix}`] || undefined,
        tray_left: TraySvgMap[trayModel][`tray_left${suffix}`] || undefined
      }
    }

    BaseTray.extendModel(config)
  })
}

export { BaseTray, TrayMap, extendModel }
