/**
 * 功能:
 *     Marvin JS 渲染占位, 由于商业许可证限制, 评估期不做本地集成
 * 说明:
 *     - 调用立即抛错, 对比页面展示占位文本与官方 demo 链接
 *     - 用户可前往 https://marvinjs-demo.chemaxon.com/ 使用同批 SMILES 手工比对
 */
import type { RenderFn } from './rendererTypes'

export const renderSmilesToSvg: RenderFn = async () => {
  throw new Error(
    'Marvin JS 需 ChemAxon 商业许可证, 本地评估跳过; 请前往 https://marvinjs-demo.chemaxon.com/ 手工对比',
  )
}
