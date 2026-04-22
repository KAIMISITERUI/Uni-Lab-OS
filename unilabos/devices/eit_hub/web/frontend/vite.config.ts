import vue from '../../../eit_chemical_manager/web/frontend/node_modules/@vitejs/plugin-vue/dist/index.mjs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const projectRoot = dirname(fileURLToPath(import.meta.url))
const sharedNodeModules = resolve(projectRoot, '../../../eit_chemical_manager/web/frontend/node_modules')
const chemicalManagerPublic = resolve(projectRoot, '../../../eit_chemical_manager/web/frontend/public')

export default {
  plugins: [vue()],
  publicDir: chemicalManagerPublic,
  resolve: {
    alias: [
      { find: '@', replacement: resolve(projectRoot, 'src') },
      { find: 'vue-router', replacement: resolve(sharedNodeModules, 'vue-router') },
      { find: 'vue', replacement: resolve(sharedNodeModules, 'vue') },
      { find: 'axios', replacement: resolve(sharedNodeModules, 'axios') },
      { find: 'element-plus', replacement: resolve(sharedNodeModules, 'element-plus') },
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
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
}
