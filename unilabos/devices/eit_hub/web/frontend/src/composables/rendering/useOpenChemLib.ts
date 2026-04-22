/**
 * 功能:
 *     使用 OpenChemLib JS 将 SMILES 渲染为 SVG 字符串
 * 说明:
 *     - 纯 JS, 无 WASM, 解析与渲染均同步完成
 *     - 分离组分 (`.` 拆分) 由库内部自动并排布局
 *     - fromSmiles 对无效 SMILES 抛异常, 外层捕获即可
 */
import type { RenderFn } from './rendererTypes'

// OCL 9.x 导出 ESM 命名空间, 使用 namespace 模式同时兼容 default 与命名导出
let oclPromise: Promise<typeof import('openchemlib')> | null = null

function loadOCL(): Promise<typeof import('openchemlib')> {
  if (oclPromise !== null) {
    return oclPromise
  }
  // 动态 import 避免污染主业务 bundle; OCL 9.x 默认入口即 full 版本
  oclPromise = import('openchemlib')
  return oclPromise
}

export const renderSmilesToSvg: RenderFn = async (smiles, width, height) => {
  const normalized = (smiles ?? '').trim()
  if (normalized === '') {
    throw new Error('SMILES 为空')
  }
  const OCL = await loadOCL()
  const mol = OCL.Molecule.fromSmiles(normalized)
  return mol.toSVG(width, height)
}
