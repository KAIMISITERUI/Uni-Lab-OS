import type { ModelConfigDef } from 'Types/config/model'

export const patchConfig = (modelConfig: ModelConfigDef, targetConfig: any, container: string): void => {
  Object.keys(modelConfig.tray || {}).forEach((trayModel: string) => {
    const obj = modelConfig.tray as any
    obj[trayModel] = {
      ...obj[trayModel],
      ...(obj[trayModel]?.[container] || {})
    }
  })

  if (!container || !targetConfig) return

  const targetModelConfig = targetConfig?.[container]?.model || {} as ModelConfigDef
  if (!targetModelConfig) return

  ['tray', 'vessel'].forEach((key: any): void => {
    const trayConfigMap = targetModelConfig?.[key] || {}
    const modelConfigMap: any = (modelConfig as any)[key] || {}

    Object.keys(trayConfigMap).forEach((trayModel: string) => {
      if (trayConfigMap[trayModel] && modelConfigMap[trayModel]) {
        modelConfigMap[trayModel] = {
          ...modelConfigMap[trayModel],
          ...trayConfigMap[trayModel]
        }
      }
    })
  })
}
