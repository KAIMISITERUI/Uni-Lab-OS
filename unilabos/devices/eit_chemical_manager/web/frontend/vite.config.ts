import { defineConfig, type PluginOption } from 'vite'
import vue from '@vitejs/plugin-vue'
import { copyFileSync, existsSync, mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const projectRoot = dirname(fileURLToPath(import.meta.url))

// 插件: 构建或启动开发服务前, 将 Emscripten UMD 产物(JS + WASM)复制到 public/
// 这些模块设计上必须作为 <script src="..."> 动态注入后通过全局变量调用, 无法被 Vite
// 作为 ES 模块导入; 统一放入 public 后由前端 loadScript 工具加载
// 未安装对应 npm 包时仅输出警告, 不中断 Vite 启动
function copyChemAssets(): PluginOption {
  const assets: Array<{ src: string; dest: string }> = [
    {
      src: 'node_modules/@rdkit/rdkit/dist/RDKit_minimal.js',
      dest: 'public/rdkit/RDKit_minimal.js',
    },
    {
      src: 'node_modules/@rdkit/rdkit/dist/RDKit_minimal.wasm',
      dest: 'public/rdkit/RDKit_minimal.wasm',
    },
    {
      src: 'node_modules/indigo-ketcher/indigo-ketcher.js',
      dest: 'public/indigo-ketcher/indigo-ketcher.js',
    },
  ]
  return {
    name: 'copy-chem-assets',
    buildStart() {
      for (const { src, dest } of assets) {
        const fullSrc = resolve(projectRoot, src)
        const fullDest = resolve(projectRoot, dest)
        if (!existsSync(fullSrc)) {
          this.warn(`未找到化学库资源: ${src} (请确认已执行 npm install)`)
          continue
        }
        const destDir = dirname(fullDest)
        if (!existsSync(destDir)) {
          mkdirSync(destDir, { recursive: true })
        }
        if (!existsSync(fullDest)) {
          copyFileSync(fullSrc, fullDest)
        }
      }
    },
  }
}

// 开发期: 前端 5173, 后端 8765, /api 反向代理到后端避免跨域
// 生产期: 构建产物 dist 由 FastAPI StaticFiles 直接提供, 同源
export default defineConfig({
  plugins: [vue(), copyChemAssets()],
  // @rdkit/rdkit 与 indigo-ketcher 为 Emscripten UMD 产物, 通过 script 注入加载
  // 不经过 ES import, 仍 exclude 以防 Vite 对 npm 包做无意义预构建
  // openchemlib 为原生 ESM, 交由 Vite 正常 pre-bundle
  optimizeDeps: {
    exclude: ['@rdkit/rdkit', 'indigo-ketcher'],
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
