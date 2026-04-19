/**
 * 功能:
 *     定义 SMILES -> SVG 渲染器的统一接口, 供候选库对比评估页面驱动
 * 说明:
 *     - 所有候选实现都暴露 renderSmilesToSvg 命名导出, 签名严格一致
 *     - 空 SMILES 或解析失败应抛出 Error, 由对比页面统一捕获并展示
 *     - 候选库实现不做缓存, 以便对比页面真实测量每次渲染耗时
 */

export type RenderFn = (
  smiles: string,
  width: number,
  height: number,
) => Promise<string>

// 对比页面列定义: 库显示名 + 动态 import 的 RenderFn 工厂
export interface RendererEntry {
  name: string
  note?: string
  loader: () => Promise<{ renderSmilesToSvg: RenderFn }>
}
