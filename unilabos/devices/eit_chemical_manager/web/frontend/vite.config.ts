import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发期: 前端 5173, 后端 8765, /api 反向代理到后端避免跨域
// 生产期: 构建产物 dist 由 FastAPI StaticFiles 直接提供, 同源
export default defineConfig({
  plugins: [vue()],
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
