import vue from '../../../eit_chemical_manager/web/frontend/node_modules/@vitejs/plugin-vue/dist/index.mjs'
import { dirname, resolve, normalize } from 'node:path'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const projectRoot = dirname(fileURLToPath(import.meta.url))
const sharedNodeModules = resolve(projectRoot, '../../../eit_chemical_manager/web/frontend/node_modules')
const chemicalManagerPublic = resolve(projectRoot, '../../../eit_chemical_manager/web/frontend/public')
// dynamic-graph 移植根, station/tray/utils/types/models 全部置于此处
const graphRoot = resolve(projectRoot, 'src/lib/dynamic-graph')
const graphRootNorm = normalize(graphRoot)

// dynamic-graph 内部约定 SVG 以原始字符串形式被 import (zrender.parseSVG 直接消费),
// 仅命中 src/lib/dynamic-graph/models/ 下的 SVG 时返回原文; 其它 SVG 不影响.
const svgAsRawForGraphPlugin = {
  name: 'svg-as-raw-for-dynamic-graph',
  enforce: 'pre' as const,
  load (id: string) {
    const idNoQuery = id.split('?')[0]
    if (!idNoQuery.endsWith('.svg')) { return null }
    if (!normalize(idNoQuery).startsWith(graphRootNorm)) { return null }
    const raw = readFileSync(idNoQuery, 'utf-8')
    return `export default ${JSON.stringify(raw)}`
  },
}

export default {
  plugins: [svgAsRawForGraphPlugin, vue()],
  publicDir: chemicalManagerPublic,
  resolve: {
    alias: [
      { find: '@', replacement: resolve(projectRoot, 'src') },
      // dynamic-graph 源码内的别名 (原 vue.config.js 同步)
      { find: 'Models', replacement: resolve(graphRoot, 'models') },
      { find: 'Types', replacement: resolve(graphRoot, 'types') },
      { find: 'Utils', replacement: resolve(graphRoot, 'utils') },
      { find: 'Tray', replacement: resolve(graphRoot, 'tray') },
      { find: 'Station', replacement: resolve(graphRoot, 'station') },
      { find: 'vue-router', replacement: resolve(sharedNodeModules, 'vue-router') },
      { find: 'vue', replacement: resolve(sharedNodeModules, 'vue') },
      { find: 'axios', replacement: resolve(sharedNodeModules, 'axios') },
      { find: 'element-plus', replacement: resolve(sharedNodeModules, 'element-plus') },
      { find: 'openchemlib', replacement: resolve(sharedNodeModules, 'openchemlib') },
      {
        find: '@element-plus/icons-vue',
        replacement: resolve(sharedNodeModules, '@element-plus/icons-vue'),
      },
    ],
  },
  server: {
    port: 5174,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8770',
        changeOrigin: true,
      },
      // 代理到 eit_hub 后端的 /synthesis-api/* 路由,
      // 由 web/routers/synthesis_proxy.py 转发到 eit_synthesis_station 设备 PC,
      // 这样 dev 与生产模式走同一条链路 (都经过 eit_hub 鉴权代理)
      '/synthesis-api': {
        target: 'http://127.0.0.1:8770',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
}
