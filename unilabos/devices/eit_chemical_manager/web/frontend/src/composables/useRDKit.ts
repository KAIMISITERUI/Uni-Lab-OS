/**
 * 功能:
 *     封装 RDKit.js (WebAssembly) 的单例加载与 SMILES -> SVG 渲染
 * 说明:
 *     - RDKit_minimal.js 是 Emscripten UMD 产物, 依赖浏览器全局作用域的
 *       var initRDKitModule 声明, 必须用普通 <script> 注入, 无法作为
 *       ES module 导入; 通过 vite 插件复制到 /rdkit/ 后用 loadScript 加载
 *     - WASM 文件通过 /rdkit/RDKit_minimal.wasm 访问
 *     - 全局仅初始化一次, 多处调用共享同一个 RDKit 模块实例
 *     - 同一 SMILES 与尺寸的渲染结果写入内存缓存, 避免列表重渲染时重复解析
 *     - 每次 get_mol 后必须 delete 以释放 WASM 堆内存
 */
import { loadScript } from './loadScript'

// RDKit.js 运行时类型声明, 仅保留本模块用到的接口
interface RDKitMol {
  is_valid(): boolean
  get_svg(width: number, height: number): string
  // 接受 JSON 字符串形式的 draw options, 可精确控制键宽、字号、留白等
  get_svg_with_highlights(details: string): string
  // 规范化坐标方向, canonicalize=1 表示让分子主轴水平
  normalize_depiction(canonicalize?: number, scaleFactor?: number): number
  // 拉直 CoordGen 产生的键角偏差, 让环之间的过渡更工整
  straighten_depiction(): void
  delete(): void
}

interface RDKitModule {
  get_mol(smiles: string): RDKitMol | null
  // 全局切换到 Schrodinger CoordGen 坐标算法, 影响后续所有 get_mol
  prefer_coordgen(prefer: boolean): void
}

interface InitOptions {
  locateFile?: (path: string) => string
}

type RDKitInitializer = (options?: InitOptions) => Promise<RDKitModule>

// RDKit UMD 脚本加载后挂在 window 上的全局符号
declare global {
  interface Window {
    initRDKitModule?: RDKitInitializer
  }
}

// 单例 Promise, 防止并发调用触发多次初始化
let rdkitPromise: Promise<RDKitModule> | null = null

// 缓存键格式: `${smiles}|${width}x${height}`, 值为 SVG 字符串或 null(无效 SMILES)
const svgCache = new Map<string, string | null>()

const RENDER_BASE_SHORT_SIDE = 90
const RENDER_BASE_MAX_FONT_SIZE = 12
const RENDER_MAX_FONT_SIZE = 30
const RENDER_FONT_SIZE_STEP = 0.06

/**
 * 功能:
 *     按渲染画布短边计算 RDKit 原子标签最大字号, 小图保持原有字号, 大图放大但不超过上限.
 * 参数:
 *     width 渲染画布宽度, 单位 px.
 *     height 渲染画布高度, 单位 px.
 * 返回:
 *     number, RDKit draw option 使用的 maxFontSize.
 */
function calculateMaxFontSize(width: number, height: number): number {
  const shortSide = Math.min(width, height)
  const scaledFontSize = Math.round(
    RENDER_BASE_MAX_FONT_SIZE + (shortSide - RENDER_BASE_SHORT_SIDE) * RENDER_FONT_SIZE_STEP,
  )

  if (scaledFontSize < RENDER_BASE_MAX_FONT_SIZE) {
    return RENDER_BASE_MAX_FONT_SIZE
  }
  if (scaledFontSize > RENDER_MAX_FONT_SIZE) {
    return RENDER_MAX_FONT_SIZE
  }
  return scaledFontSize
}

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
    // 先通过 <script> 注入执行 UMD, 将 initRDKitModule 绑定到 window
    await loadScript('/rdkit/RDKit_minimal.js')
    const initRDKitModule = window.initRDKitModule
    if (typeof initRDKitModule !== 'function') {
      throw new Error('RDKit 脚本已加载但未在 window 上暴露 initRDKitModule')
    }
    const RDKit = await initRDKitModule({
      locateFile: () => '/rdkit/RDKit_minimal.wasm',
    })
    // 启用 CoordGen 算法, 对稠环(萘/菲/蒽等)给出教科书式的规整朝向
    RDKit.prefer_coordgen(true)
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
    // 坐标后处理: 先旋转让主轴水平, 再拉直 CoordGen 的键角, 避免稠环倾斜
    mol.normalize_depiction(1)
    mol.straighten_depiction()
    const maxFontSize = calculateMaxFontSize(width, height)
    // 键宽恒定 1.2px, 不随分子大小缩放, 避免长链分子(如硬脂酸)键被压得极细
    // 字号按画布短边放大, 让详情大图的杂原子 label 与结构尺寸匹配
    const svg = mol.get_svg_with_highlights(
      JSON.stringify({
        width,
        height,
        bondLineWidth: 1.2,
        scaleBondWidth: false,
        minFontSize: 6,
        maxFontSize,
        baseFontSize: 0.5,
        padding: 0.06,
      }),
    )
    svgCache.set(cacheKey, svg)
    return svg
  } finally {
    // 无论成功失败都要释放 WASM 堆对象, 否则会造成内存泄漏
    if (mol !== null) {
      mol.delete()
    }
  }
}
