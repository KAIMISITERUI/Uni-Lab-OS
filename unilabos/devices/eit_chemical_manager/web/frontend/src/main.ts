import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'

import App from './App.vue'
import router from './router'
import { setApiToken } from './api/chemicals'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })

// 注册全部 Element Plus 图标, 模板中可直接 <el-icon><Edit /></el-icon> 使用
for (const [name, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(name, component)
}

// 启动时若 localStorage 已存有 token, 注入 axios 默认请求头
const savedToken = localStorage.getItem('chem_mgr_token')
if (savedToken) {
  setApiToken(savedToken)
}

app.mount('#app')
