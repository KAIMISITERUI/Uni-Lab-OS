import { defineConfig, type PluginOption } from 'vite'
import vue from '@vitejs/plugin-vue'
import { copyFileSync, existsSync, mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const projectRoot = dirname(fileURLToPath(import.meta.url))

// 插件: 构建或启动开发服务前, 将 RDKit 的 WASM 文件复制到 public/rdkit/
// 这样 dev 与 build 产物均可通过 /rdkit/RDKit_minimal.wasm 访问
// 未安装 @rdkit/rdkit 时仅输出警告, 不中断 Vite 启动
function copyRdkitWasm(): PluginOption {
  return {
    name: 'copy-rdkit-wasm',
    buildStart() {
      const src = resolve(projectRoot, 'node_modules/@rdkit/rdkit/dist/RDKit_minimal.wasm')
      const destDir = resolve(projectRoot, 'public/rdkit')
      const dest = resolve(destDir, 'RDKit_minimal.wasm')
      if (!existsSync(src)) {
        this.warn('未找到 @rdkit/rdkit WASM 文件, 请确认已执行 npm install')
        return
      }
      if (!existsSync(destDir)) {
        mkdirSync(destDir, { recursive: true })
      }
      if (!existsSync(dest)) {
        copyFileSync(src, dest)
      }
    },
  }
}

// 开发期: 前端 5173, 后端 8765, /api 反向代理到后端避免跨域
// 生产期: 构建产物 dist 由 FastAPI StaticFiles 直接提供, 同源
export default defineConfig({
  plugins: [vue(), copyRdkitWasm()],
  // RDKit.js 自带 WASM 与运行时, 排除预构建避免 Vite 误处理
  optimizeDeps: {
    exclude: ['@rdkit/rdkit'],
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
