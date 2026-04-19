/**
 * 功能:
 *     使用 Indigo 渲染引擎 (via indigo-ketcher WASM) 将 SMILES 渲染为 SVG
 * 说明:
 *     - indigo-ketcher.js 是 Emscripten UMD 产物, 顶层 var Module 必须通过
 *       <script> 注入执行后从 window.Module 取工厂函数
 *     - Module(moduleArg?) 返回 Promise<instance>, instance 即 Indigo 运行时
 *     - render 接受 SMILES / molfile 自动识别, options 为 MapStringString
 *     - options 为 C++ 堆对象, 必须调用 delete 释放, 否则泄漏
 *     - render 返回 Base64 编码字符串 (Indigo 统一用 base64 以兼容 PNG/二进制格式),
 *       对 svg 输出需手动 atob + TextDecoder 还原为 UTF-8 SVG 文本
 *     - render-coloring 打开后原子 label 按元素类型着色, 贴近目标风格
 */
import type { RenderFn } from './rendererTypes'
import { loadScript } from '../loadScript'

interface IndigoMapStringString {
  set(key: string, value: string): void
  delete(): void
}

interface IndigoInstance {
  MapStringString: new () => IndigoMapStringString
  render(input: string, options: IndigoMapStringString): string
}

type IndigoFactory = (moduleArg?: Record<string, unknown>) => Promise<IndigoInstance>

// Indigo UMD 脚本加载后挂在 window 上的全局工厂 (变量名为 Module)
declare global {
  interface Window {
    Module?: IndigoFactory
  }
}

let indigoPromise: Promise<IndigoInstance> | null = null

function loadIndigo(): Promise<IndigoInstance> {
  if (indigoPromise !== null) {
    return indigoPromise
  }
  indigoPromise = (async () => {
    await loadScript('/indigo-ketcher/indigo-ketcher.js')
    const factory = window.Module
    if (typeof factory !== 'function') {
      throw new Error('indigo-ketcher 脚本已加载但未在 window 上暴露 Module')
    }
    // 注意: 此处调用工厂会把全局 Module 从函数替换为 instance 的中间态
    // 取得 instance 后的清理由后续调用自身单例保护
    return factory()
  })()
  return indigoPromise
}

// 将 Indigo 返回的 Base64 字符串解码为 UTF-8 SVG 文本
function decodeBase64Utf8(b64: string): string {
  const binary = atob(b64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i)
  }
  return new TextDecoder('utf-8').decode(bytes)
}

export const renderSmilesToSvg: RenderFn = async (smiles, width, height) => {
  const normalized = (smiles ?? '').trim()
  if (normalized === '') {
    throw new Error('SMILES 为空')
  }
  const indigo = await loadIndigo()
  const options = new indigo.MapStringString()
  try {
    options.set('render-output-format', 'svg')
    options.set('render-image-width', String(width))
    options.set('render-image-height', String(height))
    options.set('render-coloring', 'true')
    options.set('render-background-color', '1.0, 1.0, 1.0')
    options.set('render-stereo-style', 'ext')
    const base64 = indigo.render(normalized, options)
    return decodeBase64Utf8(base64)
  } finally {
    // 必须释放 C++ 堆对象, 否则 WASM 堆持续增长
    options.delete()
  }
}
