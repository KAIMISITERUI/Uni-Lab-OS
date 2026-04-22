/**
 * 功能:
 *     将现有 useRDKit.ts 的 renderSmilesToSvg 包装成统一 RenderFn 接口的适配器
 * 说明:
 *     - 原实现允许返回 null(无效/空), 此处将 null 映射为抛错, 与其他候选行为一致
 *     - 不修改 useRDKit.ts 本身, 避免影响主业务
 */
import type { RenderFn } from './rendererTypes'
import { renderSmilesToSvg as rdkitRender } from '../useRDKit'

export const renderSmilesToSvg: RenderFn = async (smiles, width, height) => {
  const svg = await rdkitRender(smiles, width, height)
  if (svg === null) {
    throw new Error('RDKit 返回空结果 (SMILES 无效或为空)')
  }
  return svg
}
