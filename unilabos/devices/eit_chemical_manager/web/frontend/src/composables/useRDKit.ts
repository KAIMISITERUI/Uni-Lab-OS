/**
 * 功能:
 *     封装 RDKit.js (WebAssembly) 的单例加载与 SMILES -> SVG 渲染
 * 说明:
 *     - 全局仅初始化一次, 多处调用共享同一个 RDKit 模块实例
 *     - WASM 文件通过 /rdkit/RDKit_minimal.wasm 访问, 由 vite 插件复制到 public/
 *     - 同一 SMILES 与尺寸的渲染结果写入内存缓存, 避免列表重渲染时重复解析
 *     - 每次 get_mol 后必须 delete 以释放 WASM 堆内存
 */

// RDKit.js 运行时类型声明, 仅保留本模块用到的接口
interface RDKitMol {
  is_valid(): boolean
  get_svg(width: number, height: number): string
  delete(): void
}

interface RDKitModule {
  get_mol(smiles: string): RDKitMol | null
}

interface InitOptions {
  locateFile?: (path: string) => string
}

type RDKitInitializer = (options?: InitOptions) => Promise<RDKitModule>

// 单例 Promise, 防止并发调用触发多次初始化
let rdkitPromise: Promise<RDKitModule> | null = null

// 缓存键格式: `${smiles}|${width}x${height}`, 值为 SVG 字符串或 null(无效 SMILES)
const svgCache = new Map<string, string | null>()

/**
 * 功能:
 *     异步加载并初始化 RDKit.js 模块, 全局单例
 * 返回:
 *     Promise<RDKitModule>, 解析后为可用的 RDKit 运行时对象
 */
export function loadRDKit(): Promise<RDKitModule> {
  if (rdkitPromise !== null) {
    return rdkitPromise
  }
  rdkitPromise = (async () => {
    // 动态 import 触发 WASM 延迟加载, 避免阻塞首屏
    const module = await import('@rdkit/rdkit')
    const initRDKitModule = (module as unknown as { default: RDKitInitializer }).default
    const RDKit = await initRDKitModule({
      locateFile: () => '/rdkit/RDKit_minimal.wasm',
    })
    return RDKit
  })()
  return rdkitPromise
}

/**
 * 功能:
 *     将 SMILES 渲染为指定尺寸的 SVG 字符串
 * 参数:
 *     smiles 原始 SMILES 字符串, 空串或无效时返回 null
 *     width/height 渲染尺寸(像素)
 * 返回:
 *     Promise<string | null>, SVG 文本或 null(空/无效)
 */
export async function renderSmilesToSvg(
  smiles: string,
  width: number,
  height: number,
): Promise<string | null> {
  const normalized = (smiles ?? '').trim()
  if (normalized === '') {
    return null
  }
  const cacheKey = `${normalized}|${width}x${height}`
  if (svgCache.has(cacheKey)) {
    return svgCache.get(cacheKey) ?? null
  }
  const RDKit = await loadRDKit()
  const mol = RDKit.get_mol(normalized)
  try {
    if (mol === null || !mol.is_valid()) {
      svgCache.set(cacheKey, null)
      return null
    }
    const svg = mol.get_svg(width, height)
    svgCache.set(cacheKey, svg)
    return svg
  } finally {
    // 无论成功失败都要释放 WASM 堆对象, 否则会造成内存泄漏
    if (mol !== null) {
      mol.delete()
    }
  }
}
